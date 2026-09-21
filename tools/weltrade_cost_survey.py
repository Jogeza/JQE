"""Read-only Weltrade synthetic cost/feasibility survey. No orders, no mutation.

Connects once, then for every broker-discovered synthetic symbol measures the
broker's own terms (minimum lot, stops level, spread, margin, value per point)
and the canonical strategy's real stop distance (2.0 x ATR_14 of provably
closed candles) per timeframe. Prints a table sorted by minimum-lot loss and
writes JSON for later steps.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

MANAGED_CAPITAL_REFERENCE = 10.00
ATR_SL_MULTIPLIER = 2.0


def _closed_rates(rates: Any, tf: str, now: datetime) -> list[dict[str, Any]]:
    out = []
    for rate in rates:
        opened = datetime.fromtimestamp(int(rate["time"]), tz=timezone.utc)
        if opened.timestamp() + TIMEFRAME_SECONDS[tf] <= now.timestamp():
            out.append(
                {
                    "time": opened,
                    "open": float(rate["open"]),
                    "high": float(rate["high"]),
                    "low": float(rate["low"]),
                    "close": float(rate["close"]),
                    "volume": float(rate["tick_volume"]),
                }
            )
    return out


async def _warm_up_quote(call: Any, mt5: Any, name: str, timeout_s: float = 12.0) -> Any:
    """Poll until the terminal streams a live bid for a freshly-selected symbol.

    ``symbol_select(True)`` only requests streaming; the first tick can lag by a
    few seconds. Measuring from a zero bid would silently drop the symbol, so we
    wait for a real quote before extracting broker terms.
    """
    deadline = time.perf_counter() + timeout_s
    info = None
    while time.perf_counter() < deadline:
        info = await call(mt5.symbol_info, name)
        if info is not None and float(info.bid) > 0:
            return info
        await asyncio.sleep(0.5)
    return info if (info is not None and float(info.bid) > 0) else None


async def _fetch_rates(call: Any, mt5: Any, name: str, tf_const: int, count: int,
                       need: int = 30, attempts: int = 4) -> Any:
    """Fetch closed-candidate rates, retrying while history is still downloading."""
    rates = None
    for attempt in range(attempts):
        rates = await call(mt5.copy_rates_from_pos, name, tf_const, 0, count)
        if rates is not None and len(rates) >= need:
            return rates
        await asyncio.sleep(0.4)
    return rates


def _atr14(df: pd.DataFrame) -> float | None:
    from core.indicators import calculate_indicators

    enriched = calculate_indicators(df)
    for column in ("ATR_14", "ATR"):
        if column in enriched.columns:
            value = enriched[column].dropna()
            if len(value):
                return float(value.iloc[-1])
    return None


async def survey(timeframes: list[str], count: int, out_path: str | None) -> dict[str, Any]:
    import MetaTrader5 as mt5

    from config.settings import settings

    loop = asyncio.get_running_loop()

    def call(fn, *args):
        return asyncio.to_thread(fn, *args)

    ok = await call(mt5.initialize, str(settings.weltrade_terminal_path))
    if ok is not True:
        raise SystemExit(f"terminal initialize failed: {mt5.last_error()}")
    try:
        account = await call(mt5.account_info)
        account_facts = {
            "login": account.login,
            "server": account.server,
            "currency": account.currency,
            "balance": account.balance,
            "trade_mode": account.trade_mode,
        }
        if account.trade_mode != 0:
            raise SystemExit("refusing to survey a non-demo account")
        symbols = await call(mt5.symbols_get)
        rows: list[dict[str, Any]] = []
        enabled_by_survey: list[str] = []
        skipped: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for item in symbols:
            name = str(getattr(item, "name", "")).strip()
            if not name:
                continue
            info = await call(mt5.symbol_info, name)
            if info is None:
                skipped.append({"symbol": name, "reason": "no symbol_info"})
                continue
            if float(info.bid) <= 0:
                # Not streamed by the terminal yet; enable quotes (view-only,
                # reversible) so broker terms and rates can be measured.
                if await call(mt5.symbol_select, name, True) is not True:
                    skipped.append({"symbol": name, "reason": "symbol_select failed"})
                    continue
                enabled_by_survey.append(name)
                # trigger history download while the first tick is inbound
                await call(mt5.copy_rates_from_pos, name, mt5.TIMEFRAME_M1, 0, 60)
                info = await _warm_up_quote(call, mt5, name)
                if info is None:
                    skipped.append({"symbol": name, "reason": "no live bid after warm-up"})
                    continue
            point = float(info.point)
            digits = int(info.digits)
            volume_min = float(info.volume_min)
            volume_step = float(info.volume_step)
            stops_level_points = int(info.trade_stops_level)
            spread_points = int(info.spread)
            bid = float(info.bid)
            ask = float(info.ask)
            if point <= 0 or bid <= 0:
                skipped.append({"symbol": name, "reason": "nonpositive point or bid"})
                continue
            profit_one_point = await call(
                mt5.order_calc_profit, mt5.ORDER_TYPE_BUY, name, volume_min, bid, bid + 1.0
            )
            value_per_point_min_lot = abs(float(profit_one_point)) if profit_one_point else None
            tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
            tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
            implied_vpp = (tick_value / tick_size * volume_min) if tick_size > 0 else None
            margin_min = await call(mt5.order_calc_margin, mt5.ORDER_TYPE_BUY, name, volume_min, ask)
            row: dict[str, Any] = {
                "symbol": name,
                "point": point,
                "digits": digits,
                "bid": bid,
                "ask": ask,
                "volume_min": volume_min,
                "volume_step": volume_step,
                "volume_max": float(info.volume_max),
                "stops_level_points": stops_level_points,
                "min_stop_distance_price": stops_level_points * point,
                "spread_points": spread_points,
                "spread_price": spread_points * point,
                "value_per_point_min_lot_broker": value_per_point_min_lot,
                "value_per_point_min_lot_ticks": implied_vpp,
                "margin_at_min_lot": float(margin_min) if margin_min else None,
                "timeframes": {},
            }
            for tf in timeframes:
                started = time.perf_counter()
                rates = await _fetch_rates(call, mt5, name, _mt5_tf(mt5, tf), count)
                fetch_ms = (time.perf_counter() - started) * 1000.0
                if rates is None or len(rates) == 0:
                    row["timeframes"][tf] = {"error": "no rates"}
                    continue
                closed = _closed_rates(rates, tf, now)
                if len(closed) < 30:
                    row["timeframes"][tf] = {"error": "insufficient closed candles", "closed": len(closed)}
                    continue
                df = pd.DataFrame(closed)
                started = time.perf_counter()
                atr = await loop.run_in_executor(None, _atr14, df)
                calc_ms = (time.perf_counter() - started) * 1000.0
                if not atr:
                    row["timeframes"][tf] = {"error": "no atr", "closed": len(closed)}
                    continue
                stop_distance = atr * ATR_SL_MULTIPLIER
                loss = (value_per_point_min_lot or 0.0) * stop_distance
                row["timeframes"][tf] = {
                    "closed_candles": len(closed),
                    "last_closed_open": closed[-1]["time"].isoformat(),
                    "atr": round(atr, 6),
                    "stop_distance": round(stop_distance, 6),
                    "min_lot_loss_usd": round(loss, 4),
                    "min_lot_loss_pct_of_10": round(loss / MANAGED_CAPITAL_REFERENCE * 100.0, 3),
                    "spread_pct_of_stop": round(
                        (spread_points * point) / stop_distance * 100.0, 3
                    )
                    if stop_distance > 0
                    else None,
                    "fetch_ms": round(fetch_ms, 1),
                    "indicator_ms": round(calc_ms, 1),
                }
            rows.append(row)
        rows.sort(
            key=lambda r: (r["timeframes"].get("M5") or {}).get("min_lot_loss_usd", 1e18)
        )
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "account": account_facts,
            "managed_capital_reference": MANAGED_CAPITAL_REFERENCE,
            "atr_sl_multiplier": ATR_SL_MULTIPLIER,
            "market_watch_enabled_by_survey": enabled_by_survey,
            "skipped_symbols": skipped,
            "rows": rows,
        }
        if out_path:
            Path(out_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    finally:
        for name in enabled_by_survey:
            await call(mt5.symbol_select, name, False)
        await call(mt5.shutdown)


def _mt5_tf(mt5: Any, tf: str) -> int:
    return {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }[tf]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframes", default="M1,M5,M15,M30,H1,H4,D1")
    parser.add_argument("--count", type=int, default=220)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--table-for", default="M5")
    args = parser.parse_args()
    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    payload = asyncio.run(survey(tfs, args.count, args.json_out))
    tf = args.table_for
    print(
        f"{'symbol':<16}{'minlot':>7}{'stop':>12}{'loss$':>9}{'%10':>8}"
        f"{'sprd%stop':>10}{'minstop':>10}{'sprd$':>9}{'margin':>9}"
    )
    for row in payload["rows"]:
        cell = (row["timeframes"].get(tf) or {})
        if "min_lot_loss_usd" not in cell:
            continue
        flags = []
        if cell["min_lot_loss_usd"] <= 0.25:
            flags.append("<=0.25")
        elif cell["min_lot_loss_usd"] <= 0.50:
            flags.append("<=0.50")
        elif cell["min_lot_loss_usd"] <= 1.00:
            flags.append("<=1.00")
        print(
            f"{row['symbol']:<16}{row['volume_min']:>7.2f}{cell['stop_distance']:>12.4f}"
            f"{cell['min_lot_loss_usd']:>9.4f}{cell['min_lot_loss_pct_of_10']:>8.2f}"
            f"{cell['spread_pct_of_stop']:>10.2f}{row['min_stop_distance_price']:>10.4f}"
            f"{row['spread_price']:>9.4f}{(row['margin_at_min_lot'] or 0):>9.2f}"
            f"  {' '.join(flags)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
