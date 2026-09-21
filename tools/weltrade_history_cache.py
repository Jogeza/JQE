"""Read-only Weltrade history cache for offline Step 3 evaluation.

Connects once to the demo terminal, fetches provably-closed candles (with each
bar's recorded spread, in points) for the shortlisted symbols on the entry
timeframes (M1/M5) and the direction-filter timeframes (H1/H4), writes a
gzipped JSON cache, and restores Market Watch selection exactly as found.

No orders, no mutation, no config or risk changes. The offline evaluator
(``tools/weltrade_mtf_backtest.py``) reads this cache and never touches the
broker.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import io
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

# Bars requested per timeframe; the terminal returns whatever depth it holds.
DEFAULT_COUNTS = {"M1": 60000, "M5": 30000, "H1": 8000, "H4": 5000}

DEFAULT_SYMBOLS = [
    "FlipX 1",
    "FlipX 2",
    "SFX Vol 99",
    "SFX Vol 20",
    "FiboX",
    "PlusX 1",
]
DEFAULT_TIMEFRAMES = ["M1", "M5", "H1", "H4"]

# The scoped research fetch is pinned to the daemon's isolated demo profile.
# This path is used only by --scope-portable; the legacy CLI stays unchanged.
SCOPE_PROFILE = Path(r"D:\JQE\mt5-daemon-profile")
SCOPE_TERMINAL = SCOPE_PROFILE / "terminal64.exe"
SCOPE_FETCH = {
    "FX Vol 20": ("M1", "H1", "H4"),
    "FX Vol 60": ("M1", "M5", "H1", "H4"),
    "FX Vol 99": ("M1", "H1", "H4"),
    "SFX Vol 40": ("M1", "H1", "H4"),
    "PainX 400": ("M1", "H1", "H4"),
    "PainX 600": ("M1", "H1", "H4"),
    "PainX 800": ("M1", "H1", "H4"),
    "PainX 999": ("M1", "H1", "H4"),
    "PainX 1200": ("M1", "H1", "H4"),
}


def _terminal64_pids() -> list[int]:
    """Fail closed if Windows process enumeration cannot be trusted."""
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=True,
    )
    pids = []
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) >= 2 and row[0].strip().lower() == "terminal64.exe":
            pids.append(int(row[1].replace(",", "")))
    return pids


def _inside_profile(value: str, profile: Path) -> bool:
    try:
        path = Path(value).expanduser().resolve(strict=True)
        return path == profile or profile in path.parents
    except (OSError, ValueError):
        return False


def cache_scope_portable(out_path: str) -> dict[str, Any]:
    """One guarded, read-only demo fetch; preserve old cached symbols and dates."""
    import MetaTrader5 as mt5
    from config.settings import settings

    profile = SCOPE_PROFILE.resolve(strict=True)
    terminal = SCOPE_TERMINAL.resolve(strict=True)
    if terminal.parent != profile:
        raise RuntimeError("pinned terminal is outside the portable profile")
    expected_login = settings.effective_weltrade_login
    if expected_login is None:
        raise RuntimeError("configured Weltrade demo login is missing")
    if _terminal64_pids():
        raise RuntimeError("another terminal64 process is running; refusing MT5 initialize")

    existing_path = Path(out_path)
    with gzip.open(existing_path, "rt", encoding="utf-8") as handle:
        existing = json.load(handle)
    reference = existing["symbols"]["SFX Vol 99"]["timeframes"]
    for tf in ("M1", "M5", "H1", "H4"):
        if not reference[tf].get("candles"):
            raise RuntimeError(f"existing reference {tf} history is missing")

    initialized = False
    watch_before: set[str] | None = None
    verification: dict[str, Any] = {}
    new_symbols: dict[str, Any] = {}
    try:
        initialized = mt5.initialize(str(terminal), portable=True) is True
        if not initialized:
            raise RuntimeError("portable MT5 initialize failed")
        terminal_info = mt5.terminal_info()
        if terminal_info is None or not _inside_profile(str(terminal_info.path), profile) or not _inside_profile(str(terminal_info.data_path), profile):
            raise RuntimeError("MT5 terminal or data path is outside the pinned portable profile")
        if Path(str(terminal_info.data_path)).resolve() != profile:
            raise RuntimeError("MT5 data path differs from the pinned portable profile")
        account = mt5.account_info()
        if account is None or int(account.trade_mode) != 0:
            raise RuntimeError("MT5 account is not a verified demo account")
        if int(account.login) != int(expected_login):
            raise RuntimeError("MT5 login does not match the configured Weltrade demo login")
        verification = {"terminal_path_in_profile": True,
                        "data_path_is_profile": True,
                        "demo_trade_mode": True,
                        "configured_login_matches": True,
                        "other_terminal64_before_connect": False}

        symbols_before = mt5.symbols_get()
        if symbols_before is None:
            raise RuntimeError("cannot snapshot Market Watch")
        watch_before = {s.name for s in symbols_before if bool(getattr(s, "visible", False))}
        # Exact historical interval and count target come from the old cache.
        for name, timeframes in SCOPE_FETCH.items():
            info = mt5.symbol_info(name)
            if info is None:
                new_symbols[name] = {"error": "no symbol_info"}
                continue
            if not bool(getattr(info, "visible", False)):
                if mt5.symbol_select(name, True) is not True:
                    new_symbols[name] = {"error": "symbol_select failed"}
                    continue
            entry = {"point": float(info.point), "digits": int(info.digits),
                     "volume_min": float(info.volume_min), "volume_step": float(info.volume_step),
                     "was_visible": name in watch_before, "timeframes": {}}
            for tf in timeframes:
                ref = reference[tf]
                first = datetime.fromisoformat(ref["first"])
                last = datetime.fromisoformat(ref["last"])
                rates = mt5.copy_rates_range(name, _mt5_tf(mt5, tf), first, last)
                if rates is None or len(rates) == 0:
                    entry["timeframes"][tf] = {"error": "no rates", "candles": [],
                                                "reference_closed": ref["closed"]}
                    continue
                closed = [r for r in _closed_rows(rates, tf, datetime.now(timezone.utc))
                          if first.timestamp() <= r[0] <= last.timestamp()]
                entry["timeframes"][tf] = {
                    "returned": int(len(rates)), "closed": len(closed),
                    "first": datetime.fromtimestamp(closed[0][0], tz=timezone.utc).isoformat() if closed else None,
                    "last": datetime.fromtimestamp(closed[-1][0], tz=timezone.utc).isoformat() if closed else None,
                    "reference_closed": ref["closed"], "reference_first": ref["first"],
                    "reference_last": ref["last"], "candles": closed,
                }
            new_symbols[name] = entry
    finally:
        if initialized:
            try:
                if watch_before is not None:
                    symbols_after = mt5.symbols_get()
                    if symbols_after is None:
                        raise RuntimeError("cannot verify Market Watch restoration")
                    watch_after = {s.name for s in symbols_after if bool(getattr(s, "visible", False))}
                    for name in sorted(watch_after - watch_before):
                        if mt5.symbol_select(name, False) is not True:
                            raise RuntimeError("failed to restore Market Watch")
                    for name in sorted(watch_before - watch_after):
                        if mt5.symbol_select(name, True) is not True:
                            raise RuntimeError("failed to restore Market Watch")
                    final_symbols = mt5.symbols_get()
                    if final_symbols is None or {s.name for s in final_symbols if bool(getattr(s, "visible", False))} != watch_before:
                        raise RuntimeError("Market Watch restoration mismatch")
                    verification["market_watch_restored"] = True
            finally:
                mt5.shutdown()

    # Write only after MT5 has shut down and the Market Watch is restored.
    existing["symbols"].update(new_symbols)
    existing["scope_fetch"] = {"generated_at": datetime.now(timezone.utc).isoformat(),
                               "verification": verification,
                               "reference_symbol": "SFX Vol 99",
                               "requested_symbols": list(SCOPE_FETCH)}
    temp = existing_path.with_suffix(existing_path.suffix + ".tmp")
    with gzip.open(temp, "wt", encoding="utf-8") as handle:
        json.dump(existing, handle)
    temp.replace(existing_path)
    return {"verification": verification,
            "symbols": {name: {tf: cell.get("closed", 0) for tf, cell in entry.get("timeframes", {}).items()}
                        for name, entry in new_symbols.items()}}


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


def _closed_rows(rates: Any, tf: str, now: datetime) -> list[list[Any]]:
    """Keep only provably-closed bars as compact [time, o, h, l, c, spread_pts]."""
    out: list[list[Any]] = []
    for rate in rates:
        opened = datetime.fromtimestamp(int(rate["time"]), tz=timezone.utc)
        if opened.timestamp() + TIMEFRAME_SECONDS[tf] <= now.timestamp():
            out.append(
                [
                    int(rate["time"]),
                    float(rate["open"]),
                    float(rate["high"]),
                    float(rate["low"]),
                    float(rate["close"]),
                    int(rate["spread"]),
                ]
            )
    return out


async def _warm_up_quote(call: Any, mt5: Any, name: str, timeout_s: float = 12.0) -> Any:
    deadline = asyncio.get_running_loop().time() + timeout_s
    info = None
    while asyncio.get_running_loop().time() < deadline:
        info = await call(mt5.symbol_info, name)
        if info is not None and float(info.bid) > 0:
            return info
        await asyncio.sleep(0.5)
    return info if (info is not None and float(info.bid) > 0) else None


async def cache_history(
    symbols: list[str], timeframes: list[str], counts: dict[str, int], out_path: str
) -> dict[str, Any]:
    import MetaTrader5 as mt5

    from config.settings import settings

    def call(fn, *args):
        return asyncio.to_thread(fn, *args)

    ok = await call(mt5.initialize, str(settings.weltrade_terminal_path))
    if ok is not True:
        raise SystemExit(f"terminal initialize failed: {mt5.last_error()}")
    enabled_by_us: list[str] = []
    try:
        account = await call(mt5.account_info)
        if account.trade_mode != 0:
            raise SystemExit("refusing to read history from a non-demo account")
        account_facts = {
            "login": account.login,
            "server": account.server,
            "currency": account.currency,
            "balance": account.balance,
            "trade_mode": account.trade_mode,
        }
        now = datetime.now(timezone.utc)
        data: dict[str, Any] = {}
        for name in symbols:
            info = await call(mt5.symbol_info, name)
            if info is None:
                data[name] = {"error": "no symbol_info"}
                continue
            was_visible = bool(getattr(info, "visible", False)) or float(info.bid) > 0
            if float(info.bid) <= 0:
                if await call(mt5.symbol_select, name, True) is not True:
                    data[name] = {"error": "symbol_select failed"}
                    continue
                enabled_by_us.append(name)
                await call(mt5.copy_rates_from_pos, name, mt5.TIMEFRAME_M1, 0, 60)
                if await _warm_up_quote(call, mt5, name) is None:
                    data[name] = {"error": "no live bid after warm-up"}
                    continue
            point = float(info.point)
            entry: dict[str, Any] = {
                "point": point,
                "digits": int(info.digits),
                "volume_min": float(info.volume_min),
                "volume_step": float(info.volume_step),
                "was_visible": was_visible,
                "timeframes": {},
            }
            for tf in timeframes:
                rates = await call(
                    mt5.copy_rates_from_pos, name, _mt5_tf(mt5, tf), 0, counts.get(tf, 5000)
                )
                if rates is None or len(rates) == 0:
                    entry["timeframes"][tf] = {"error": "no rates", "candles": []}
                    continue
                closed = _closed_rows(rates, tf, now)
                entry["timeframes"][tf] = {
                    "returned": int(len(rates)),
                    "closed": len(closed),
                    "first": (
                        datetime.fromtimestamp(closed[0][0], tz=timezone.utc).isoformat()
                        if closed
                        else None
                    ),
                    "last": (
                        datetime.fromtimestamp(closed[-1][0], tz=timezone.utc).isoformat()
                        if closed
                        else None
                    ),
                    "candles": closed,
                }
            data[name] = entry
        payload = {
            "generated_at": now.isoformat(),
            "account": account_facts,
            "market_watch_enabled_by_tool": enabled_by_us,
            "symbols": data,
        }
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(out_path, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return payload
    finally:
        for name in enabled_by_us:
            await call(mt5.symbol_select, name, False)
        await call(mt5.shutdown)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-portable", action="store_true",
                        help="Guarded Weltrade demo scope extension in pinned portable profile")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--out", default="state/weltrade_history_cache.json.gz")
    args = parser.parse_args()
    if args.scope_portable:
        result = cache_scope_portable(args.out)
        print(json.dumps(result, indent=2))
        return 0
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    payload = asyncio.run(cache_history(symbols, timeframes, DEFAULT_COUNTS, args.out))
    print(f"enabled_by_tool: {payload['market_watch_enabled_by_tool']}")
    for name, entry in payload["symbols"].items():
        if "error" in entry:
            print(f"{name:<12} ERROR {entry['error']}")
            continue
        print(f"{name:<12} point={entry['point']} vol_min={entry['volume_min']}")
        for tf, cell in entry["timeframes"].items():
            if cell.get("candles"):
                print(
                    f"    {tf:<4} closed={cell['closed']:>6}  {cell['first']} .. {cell['last']}"
                )
            else:
                print(f"    {tf:<4} {cell.get('error')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
