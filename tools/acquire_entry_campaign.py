"""Acquire NEW canonical research bundles through HistoricalDataService.

No backtest, strategy evaluation, order submission or operator-store writes.
Market Watch changes are forbidden rather than silently restored.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import subprocess
from contextlib import nullcontext
from unittest.mock import patch

from research.entry_campaign import UNIVERSE, build_protocol
from research.campaign_provenance import canonical_json, sha256_file, sha256_text


def save_new(path: Path, payload) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n")


def forbidden(*args, **kwargs):
    raise RuntimeError("Research acquisition forbids orders and Market Watch mutation")


def validate_history_protocol(protocol):
    if protocol.get('protocol_id')!='jqe-pre-holdout-history-v1' or protocol.get('symbols')!=list(UNIVERSE):
        raise ValueError('Unrecognized native history-only registration')
    start=datetime.fromisoformat(protocol['history']['start_inclusive'])
    end=datetime.fromisoformat(protocol['history']['end_exclusive'])
    cutoff=datetime(2026,10,8,tzinfo=timezone.utc)
    if start.utcoffset() is None or end.utcoffset() is None or start>=end or end>cutoff or end-start<timedelta(days=90):
        raise ValueError('Require 90-day aware history window ending before sealed partitions')
    if protocol.get('models_fitted')!=0 or protocol.get('performance_evaluation_authorized') is not False:
        raise ValueError('History registration does not authorize model/performance work')
    return start,end


def terminal_processes() -> list:
    result = subprocess.run([
        "powershell", "-NoProfile", "-Command",
        "@(Get-CimInstance Win32_Process -Filter \"Name = 'terminal64.exe'\" | Select-Object ProcessId,ExecutablePath) | ConvertTo-Json -Compress",
    ], capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout) if result.stdout.strip() else []
    return payload if isinstance(payload, list) else [payload]


def readonly_initialize(*, terminal_path, login, password, server):
    """Attach IPC only: verify the already authenticated identity without login()."""
    import MetaTrader5 as mt5
    if mt5.initialize(str(terminal_path), timeout=10000) is not True:
        return False
    account = mt5.account_info()
    if account is None or account.trade_mode != 0 or account.login != login or account.server != server:
        mt5.shutdown()
        return False
    return True


def contract_probes(sdk, symbol: str, info, currency: str) -> dict:
    fields = ("point", "digits", "trade_tick_size", "trade_tick_value", "trade_tick_value_profit",
              "trade_tick_value_loss", "trade_contract_size", "volume_min", "volume_step", "volume_max",
              "trade_stops_level", "trade_freeze_level", "trade_calc_mode", "swap_long", "swap_short", "swap_mode")
    result = {name: getattr(info, name, None) for name in fields}
    tick = sdk.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError("No observed tick for contract probes")
    result["quote"] = {name: getattr(tick, name, None) for name in ("time", "time_msc", "bid", "ask")}
    result["account_currency"] = currency
    result["profit_probes"] = []
    step, volume = float(info.trade_tick_size), float(info.volume_min)
    if not all(math.isfinite(x) and x > 0 for x in (step, volume, float(tick.bid), float(tick.ask))):
        raise RuntimeError("Contract economics or quote are nonpositive/nonfinite")
    tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
    if not math.isfinite(tick_value) or tick_value <= 0:
        raise RuntimeError("Positive terminal tick value required to choose measurable P/L probes")
    # At minimum lot a single tick can round to zero in account currency.
    # Use two measurable distances; these are calculations, not submitted orders.
    probe_ticks = max(1, math.ceil(.10 / (volume * tick_value)))
    for side, action, entry, direction in (("BUY", sdk.ORDER_TYPE_BUY, float(tick.ask), 1),
                                            ("SELL", sdk.ORDER_TYPE_SELL, float(tick.bid), -1)):
        for ticks in (-10 * probe_ticks, -probe_ticks, probe_ticks, 10 * probe_ticks):
            exit_price = entry + direction * ticks * step
            if exit_price <= 0:
                raise RuntimeError("Measurable P/L probe would require a nonpositive price")
            profit = sdk.order_calc_profit(action, symbol, volume, entry, exit_price)
            if profit is None or not math.isfinite(float(profit)) or float(profit) * ticks <= 0:
                raise RuntimeError("Broker P/L probe unavailable or inconsistent")
            result["profit_probes"].append({"side": side, "lots": volume, "entry": entry,
                                            "exit": exit_price, "ticks": ticks, "pnl": float(profit)})
    result["economics_status"] = "CURRENT_SNAPSHOT_PROBED_NOT_HISTORICAL_GUARANTEE"
    result["commission_status"] = "NOT_VERIFIED"
    result["slippage_status"] = "NOT_VERIFIED"
    return result


async def acquire(output: Path, count: int = 12000, *, attach_existing: bool = False,
                  protocol_path: Path | None = None, history_only: bool = False, session_policy_path: Path | None = None) -> dict:
    if count < 400 or count > 50000:
        raise ValueError("Research acquisition count must be between 400 and 50000")
    output.mkdir(parents=True, exist_ok=False)
    protocol = build_protocol(datetime.now(timezone.utc)) if protocol_path is None else json.loads(protocol_path.read_text(encoding="utf-8"))
    history_start=history_end=None
    session_policy=None; session_evidence=None
    if session_policy_path is not None:
        if not history_only:raise ValueError('Session assumptions require history-only research')
        from research.session_coverage import load_policy
        session_policy,session_evidence=load_policy(session_policy_path)
    if history_only:
        if protocol_path is None or not attach_existing:
            raise ValueError('History-only acquisition requires frozen protocol and existing terminal attachment')
        history_start,history_end=validate_history_protocol(protocol)
    if protocol_path is not None:
        digest = json.loads(protocol_path.with_name("protocol.sha256.json").read_text(encoding="utf-8"))["sha256"]
        if digest != sha256_text(canonical_json(protocol)) or protocol.get("symbols") != list(UNIVERSE):
            raise ValueError("Frozen campaign protocol identity does not verify")
    save_new(output / "protocol.json", protocol)
    save_new(output / "protocol.sha256.json", {"sha256": sha256_text(canonical_json(protocol))})
    report = {"status": "ACQUISITION_STARTED", "symbols": [], "orders_permitted": False,
              "tool_sha256": sha256_file(Path(__file__)), "requested_bars_per_symbol": count}
    if session_policy_path is not None:
        save_new(output/'session-policy.json',session_evidence)
        from backtesting.label_protocol import file_hash
        report['session_policy_sha256']=file_hash(session_policy_path)
        report['calendar_scope']='CONDITIONAL_HISTORICAL_UTC_PLUS_3_NOT_VERIFIED'
        report['ml_fitting_authorized']=False
    gateway = None
    try:
        from config.settings import settings
        if settings.broker_execution_enabled or settings.market_data_source != "broker":
            raise RuntimeError("Research requires unchanged execution-disabled broker-data configuration")
        # Do not log in/reconfigure any terminal already used by another process.
        processes = terminal_processes()
        if processes and not attach_existing:
            raise RuntimeError("Existing MT5 process detected; acquisition refuses to change its account/session")
        if attach_existing and (len(processes) != 1 or not processes[0].get("ExecutablePath")
            or Path(processes[0]["ExecutablePath"]).resolve() != Path(settings.weltrade_terminal_path).resolve()):
            raise RuntimeError("Read-only attachment requires exactly the already-running configured terminal")
        import MetaTrader5 as mt5
        from broker.factory import get_gateway
        from broker.mt5_gateway import _history_server_offset, _MT5_SERVER_UTC_OFFSET_SECONDS
        from broker.types import Timeframe
        from data.historical import HistoricalDataService
        from data.storage import CandleStore
        from data.dataset import build_dataset_manifest, export_dataset_bundle
        from backtesting.provenance import source_snapshot
        from core.logger import logger

        logger.remove()
        logger.add(output / "acquisition.log", level="WARNING")
        report["source_snapshot"] = source_snapshot()
        with patch("broker.demo_guard.DEFAULT_BROKER_EVIDENCE_PATH", output / "demo-verification.sqlite3"), \
             patch.object(mt5, "order_send", forbidden), patch.object(mt5, "symbol_select", forbidden), \
             (patch("core.mt5_connection._initialize", readonly_initialize) if attach_existing else nullcontext()):
            gateway = get_gateway(settings)
            try:
                await gateway.connect()
                account, terminal = mt5.account_info(), mt5.terminal_info()
                configured = Path(settings.weltrade_terminal_path).resolve()
                if (account is None or terminal is None or account.trade_mode != 0
                    or account.login != settings.effective_weltrade_login
                    or account.server != settings.effective_weltrade_server
                    or "WELTRADE" not in account.server.upper()
                    or (Path(terminal.path) / "terminal64.exe").resolve() != configured):
                    raise RuntimeError("Configured Weltrade demo/terminal identity did not verify")
                now = datetime.now(timezone.utc)
                offset = _history_server_offset(mt5, now)
                # A newly started terminal can need a bounded quote warmup.
                for _ in range(30):
                    if offset is not None:
                        break
                    await asyncio.sleep(.5)
                    now = datetime.now(timezone.utc)
                    offset = _history_server_offset(mt5, now)
                report["clock_observation"] = {"offset_seconds": offset, "utc_observed_at": now.isoformat()}
                if offset != _MT5_SERVER_UTC_OFFSET_SECONDS:
                    raise RuntimeError("Fresh tick does not verify the gateway's fixed server-time offset")
                catalog = mt5.symbols_get()
                if catalog is None:
                    raise RuntimeError("Terminal catalogue unavailable")
                visible_before = sorted(s.name for s in catalog if s.visible)
                report["terminal_verification"] = {"configured_path_matches": True, "configured_demo_identity_matches": True,
                    "account_currency": account.currency, "server_offset_seconds": offset, "observed_at": now.isoformat()}
                store = CandleStore(db_path=output / "historical.sqlite3")
                service = HistoricalDataService(gateway, store,research_coverage_policy=session_policy)
                names = {s.name: s for s in catalog}
                for symbol in UNIVERSE:
                    record = {"symbol": symbol, "status": "BLOCKED"}
                    try:
                        info = names.get(symbol)
                        if info is None or not info.visible:
                            raise RuntimeError("Exact native symbol is absent or not visible; Market Watch changes forbidden")
                        record["economics"] = contract_probes(mt5, symbol, mt5.symbol_info(symbol), account.currency)
                        raw_pages = []
                        native_rates = mt5.copy_rates_range if history_only else mt5.copy_rates_from_pos
                        def capture_rates(*args, **kwargs):
                            rows = native_rates(*args, **kwargs)
                            if rows is not None:
                                raw_pages.append(rows)
                            return rows
                        # Capture metadata from the exact historical-service request,
                        # not a later request whose coverage may change while MT5 syncs.
                        with patch.object(mt5, "copy_rates_range" if history_only else "copy_rates_from_pos", capture_rates), \
                             (patch.object(mt5, "copy_rates_from_pos", forbidden) if history_only else nullcontext()):
                            if history_only:
                                candles = await service.get_candles_range(symbol,Timeframe.M5,history_start,
                                    history_end-timedelta(minutes=5),provider="weltrade",source_symbol=symbol)
                                downloaded=len(candles)
                            else:
                                candles, downloaded = await service.refresh_latest(symbol=symbol, provider_symbol=symbol,
                                    provider="weltrade", timeframe=Timeframe.M5, count=count, force=True, closed_only=True)
                        if history_only and any(c.time<history_start or c.time+timedelta(minutes=5)>history_end for c in candles):
                            raise RuntimeError('Historical service returned data outside sealed history-only boundary')
                        captured = datetime.now(timezone.utc)
                        if not candles or any(c.time + timedelta(seconds=300) > captured for c in candles):
                            raise RuntimeError("No provably closed historical sequence")
                        manifest = build_dataset_manifest(candles, provider="weltrade", source="weltrade",
                            provider_symbol=symbol, canonical_symbol=symbol, timeframe=Timeframe.M5, retrieved_at=captured)
                        directory = output / "bundles" / (symbol.replace(" ", "_") + "_M5")
                        if directory.exists():
                            raise RuntimeError("Refusing to overwrite a frozen research bundle")
                        export_dataset_bundle(directory, candles, manifest)
                        # SDK recorded spread is kept separately; canonical candles remain unchanged.
                        by_time = {int(r["time"]) - offset: r for page in raw_pages for r in page}
                        spreads = []
                        for candle in candles:
                            row = by_time.get(int(candle.time.timestamp()))
                            if row is None or any(float(row[key]) != float(getattr(candle, key)) for key in ("open", "high", "low", "close")):
                                raise RuntimeError("Spread sidecar cannot be bound to the frozen OHLC sequence")
                            points = int(row["spread"])
                            if points < 0:
                                raise RuntimeError("Negative historical spread")
                            spreads.append({"time": candle.time.isoformat(), "spread_points": points})
                        save_new(directory / "recorded-spread.json", {"provider": "weltrade", "content_hash": manifest.content_hash,
                            "point": record["economics"]["point"], "rows": spreads,
                            "status": "BAR_RECORDED_SPREAD_NOT_EXECUTABLE_BID_ASK_PATH"})
                        record.update(status="ACQUIRED_NOT_PROMOTION_QUALIFIED", candles=len(candles), downloaded=downloaded,
                            first=manifest.first_candle.isoformat(), last=manifest.last_candle.isoformat(),
                            content_hash=manifest.content_hash, gaps=sum((b.time-a.time).total_seconds() != 300 for a,b in zip(candles,candles[1:])),
                            spread_sidecar_sha256=sha256_file(directory / "recorded-spread.json"))
                    except Exception as exc:
                        record["error_type"] = type(exc).__name__
                        # Messages from local checks contain no account credentials.
                        record["reason"] = str(exc) if type(exc) is RuntimeError else "Acquisition failed; inspect isolated research log"
                    report["symbols"].append(record)
                    print(f"{symbol}: {record['status']}", flush=True)
                after = mt5.symbols_get()
                report["market_watch_unchanged"] = after is not None and visible_before == sorted(s.name for s in after if s.visible)
                if not report["market_watch_unchanged"]:
                    raise RuntimeError("Market Watch changed during acquisition; no restoration mutation attempted")
                if source_snapshot() != report["source_snapshot"]:
                    raise RuntimeError("Source/dependencies changed during acquisition")
                if session_policy_path is not None:
                    from research.session_coverage import load_policy
                    load_policy(session_policy_path)
                    if file_hash(session_policy_path)!=report['session_policy_sha256']:
                        raise RuntimeError('Session registration changed during acquisition')
                complete = all(r["status"] == "ACQUIRED_NOT_PROMOTION_QUALIFIED" for r in report["symbols"])
                report["status"] = "ACQUIRED_NEEDS_COST_MODEL_AND_FUTURE_HOLDOUT" if complete else "PARTIAL_ACQUISITION_BLOCKED"
                if complete and session_policy is not None:
                    report['status']='ACQUIRED_WITH_CONDITIONAL_CALENDAR_NOT_ML_READY'
            finally:
                await gateway.disconnect()
    except Exception as exc:
        report["status"] = "BLOCKED"
        report["error_type"] = type(exc).__name__
        report["reason"] = str(exc) if type(exc) is RuntimeError else "Verified gateway connection/acquisition failed; inspect isolated research log"
    save_new(output / "acquisition.json", report)
    print(f"Campaign: {output}; status: {report['status']}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bars", type=int, default=12000)
    parser.add_argument("--attach-existing", action="store_true", help="Read-only IPC attachment; never changes the authenticated account")
    parser.add_argument("--protocol", type=Path, help="Reuse a verified frozen registration across acquisition attempts")
    parser.add_argument('--history-only',action='store_true',help='Frozen pre-holdout range through historical service; latest reads forbidden')
    parser.add_argument('--session-policy',type=Path,help='Frozen evidence-bound conditional research calendar; never default')
    args = parser.parse_args()
    report = asyncio.run(acquire(args.output, args.bars, attach_existing=args.attach_existing, protocol_path=args.protocol,history_only=args.history_only,session_policy_path=args.session_policy))
    return 0 if report["status"] in ('ACQUIRED_NEEDS_COST_MODEL_AND_FUTURE_HOLDOUT','ACQUIRED_WITH_CONDITIONAL_CALENDAR_NOT_ML_READY') else 1


if __name__ == "__main__":
    raise SystemExit(main())
