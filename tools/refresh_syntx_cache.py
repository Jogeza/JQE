"""Guarded read-only MT5 refresh into JQE's provider-partitioned research cache."""
from __future__ import annotations

import asyncio
import argparse
from datetime import datetime, timezone
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # D:\JQE
sys.path.insert(0, str(ROOT))

from config.settings import Settings
from broker.types import TIMEFRAME_SECONDS, Timeframe
from broker.weltrade_gateway import WeltradeGateway
from broker.weltrade_symbols import SUPPORTED_WELTRADE_SYNTX
from data.historical import HistoricalDataService
from data.provenance import DatasetProvenance, VolumeType
from data.storage import CandleStore
from core.exceptions import MarketDataError

PROVIDER = "weltrade"
BARS_BATCH = 50_000
TIMEFRAMES: list[tuple[str, Timeframe]] = [
    ("M1", Timeframe.M1),
    ("M5", Timeframe.M5),
    ("H1", Timeframe.H1),
]


def _write_checkpoint(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def archive_and_normalize_legacy_cache(
    db_path: Path, symbols: tuple[str, ...]
) -> tuple[Path | None, int, int]:
    """Preserve raw server-time rows, then normalize their active UTC timestamps once."""
    from broker.mt5_gateway import _MT5_SERVER_UTC_OFFSET_SECONDS

    marker = "weltrade_syntx_utc3_normalization_v1"
    archive_provider = "weltrade_legacy_raw_server_time"
    timeframe_labels = tuple(label for label, _ in TIMEFRAMES)
    with sqlite3.connect(db_path) as connection:
        migrated = connection.execute(
            "SELECT value FROM schema_metadata WHERE key=?", (marker,)
        ).fetchone()
        if migrated:
            return None, 0, 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.stem}.pre-utc-fix-{stamp}{db_path.suffix}")
    with sqlite3.connect(db_path, timeout=30) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)

    symbol_placeholders = ",".join("?" for _ in symbols)
    timeframe_placeholders = ",".join("?" for _ in timeframe_labels)
    partition_args = (*symbols, *timeframe_labels)
    with sqlite3.connect(db_path, timeout=30) as connection, connection:
        connection.execute("PRAGMA busy_timeout=30000")
        already_migrated = connection.execute(
            "SELECT value FROM schema_metadata WHERE key=?", (marker,)
        ).fetchone()
        if already_migrated:
            return None, 0, 0
        before = connection.execute(
            f"SELECT COUNT(*) FROM candles WHERE provider='weltrade' "
            f"AND symbol IN ({symbol_placeholders}) AND timeframe IN ({timeframe_placeholders})",
            partition_args,
        ).fetchone()[0]
        archived_before = connection.execute(
            f"SELECT COUNT(*) FROM candles WHERE provider=? AND symbol IN ({symbol_placeholders}) "
            f"AND timeframe IN ({timeframe_placeholders})",
            (archive_provider, *partition_args),
        ).fetchone()[0]
        connection.execute(
            f"INSERT OR IGNORE INTO candles "
            "(provider,symbol,timeframe,time,open,high,low,close,volume,source) "
            f"SELECT ?,symbol,timeframe,time,open,high,low,close,volume,source FROM candles "
            f"WHERE provider='weltrade' AND symbol IN ({symbol_placeholders}) "
            f"AND timeframe IN ({timeframe_placeholders})",
            (archive_provider, *partition_args),
        )
        archived_after = connection.execute(
            f"SELECT COUNT(*) FROM candles WHERE provider=? AND symbol IN ({symbol_placeholders}) "
            f"AND timeframe IN ({timeframe_placeholders})",
            (archive_provider, *partition_args),
        ).fetchone()[0]
        if archived_after - archived_before != before:
            raise RuntimeError("Legacy cache archive count did not match the source partitions")
        connection.execute(
            f"INSERT OR IGNORE INTO dataset_provenance "
            "(provider,symbol,timeframe,source,provider_symbol,volume_type,retrieved_at) "
            f"SELECT ?,symbol,timeframe,source,provider_symbol,volume_type,retrieved_at "
            f"FROM dataset_provenance WHERE provider='weltrade' AND symbol IN ({symbol_placeholders}) "
            f"AND timeframe IN ({timeframe_placeholders})",
            (archive_provider, *partition_args),
        )
        collisions = connection.execute(
            f"DELETE FROM candles WHERE provider='weltrade' AND source!='weltrade' "
            f"AND symbol IN ({symbol_placeholders}) AND timeframe IN ({timeframe_placeholders}) "
            "AND EXISTS (SELECT 1 FROM candles AS raw WHERE raw.provider='weltrade' "
            "AND raw.source='weltrade' AND raw.symbol=candles.symbol "
            "AND raw.timeframe=candles.timeframe "
            "AND raw.time=candles.time+?)",
            (*partition_args, _MT5_SERVER_UTC_OFFSET_SECONDS),
        ).rowcount
        temporary_offset = 1_000_000_000_000
        connection.execute(
            f"UPDATE candles SET time=time+? WHERE provider='weltrade' AND source='weltrade' "
            f"AND symbol IN ({symbol_placeholders}) AND timeframe IN ({timeframe_placeholders})",
            (temporary_offset, *partition_args),
        )
        shifted = connection.execute(
            f"UPDATE candles SET time=time-? WHERE provider='weltrade' AND source='weltrade' "
            f"AND symbol IN ({symbol_placeholders}) AND timeframe IN ({timeframe_placeholders})",
            (temporary_offset + _MT5_SERVER_UTC_OFFSET_SECONDS, *partition_args),
        ).rowcount
        connection.execute(
            "INSERT INTO schema_metadata(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (marker, f"offset_seconds={_MT5_SERVER_UTC_OFFSET_SECONDS}; archived_rows={before}"),
        )
    return backup_path, before, shifted


async def refresh(*, checkpoint_path: Path, resume: bool, refresh_ticks: bool) -> None:
    settings = Settings()
    if settings.broker_execution_enabled is not False:
        raise RuntimeError("Refresh blocked: broker execution must remain disabled")
    if settings.effective_broker not in {"weltrade", "weltrade_demo"}:
        raise RuntimeError("Refresh blocked: the configured broker is not Weltrade")
    if settings.market_data_source != "broker":
        raise RuntimeError("Refresh blocked: Weltrade terminal data is not authoritative")

    import MetaTrader5 as mt5

    gateway = WeltradeGateway()
    await gateway.connect()
    try:
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        configured_path = Path(settings.weltrade_terminal_path).resolve()
        reported_path = (Path(terminal.path) / "terminal64.exe").resolve() if terminal else None
        if not (
            account is not None
            and int(account.trade_mode) == 0
            and str(account.login) == str(settings.effective_weltrade_login)
            and str(account.server) == str(settings.effective_weltrade_server)
            and "WELTRADE" in str(account.server).upper()
            and reported_path == configured_path
        ):
            raise RuntimeError("Refresh blocked: configured Weltrade demo identity did not verify")

        raw_symbols = mt5.symbols_get()
        if raw_symbols is None:
            error = mt5.last_error()
            raise RuntimeError(f"MT5 symbol catalogue unavailable: {error!r}")
        terminal_names = {str(item.name) for item in raw_symbols}
        discovered = tuple(sorted(symbol for symbol in SUPPORTED_WELTRADE_SYNTX if symbol in terminal_names))
        missing = sorted(set(SUPPORTED_WELTRADE_SYNTX) - set(discovered))

        store = CandleStore(db_path=Path(settings.historical_data_path))
        backup, archived, shifted = archive_and_normalize_legacy_cache(
            store.db_path, tuple(SUPPORTED_WELTRADE_SYNTX)
        )
        if backup:
            print(f"Legacy snapshot: {backup}")
            print(f"Archived {archived:,} rows; normalized {shifted:,} raw server-time rows to UTC.")
        service = HistoricalDataService(gateway, store=store)
        now = datetime.now(timezone.utc)
        print(f"Weltrade demo verified; execution_enabled={settings.broker_execution_enabled}")
        print(f"Terminal symbols: {len(discovered)}/{len(SUPPORTED_WELTRADE_SYNTX)} exact-name matches")
        if missing:
            print("Unavailable exact symbols:", ", ".join(missing))

        if resume:
            if not checkpoint_path.is_file():
                raise RuntimeError(f"Resume checkpoint does not exist: {checkpoint_path}")
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if checkpoint.get("provider") != PROVIDER or checkpoint.get("timeframes") != [label for label, _ in TIMEFRAMES]:
                raise RuntimeError("Resume checkpoint does not match this provider/timeframe batch")
        else:
            checkpoint = {
                "provider": PROVIDER,
                "timeframes": [label for label, _ in TIMEFRAMES],
                "started_at": now.isoformat(),
                "partitions": {},
            }
            _write_checkpoint(checkpoint_path, checkpoint)

        partitions = checkpoint.setdefault("partitions", {})
        if not isinstance(partitions, dict):
            raise RuntimeError("Invalid refresh checkpoint partitions")
        print(f"Checkpoint: {checkpoint_path}")
        for symbol in discovered:
            for label, timeframe in TIMEFRAMES:
                partition_key = f"{symbol}|{label}"
                prior = partitions.get(partition_key)
                if resume and isinstance(prior, dict) and prior.get("status") == "OK":
                    print(f"{symbol:<22} {label:<3} RESUMED    cached checkpoint")
                    continue
                try:
                    candles, downloaded = await service.refresh_latest(
                        symbol=symbol,
                        provider_symbol=symbol,
                        provider=PROVIDER,
                        timeframe=timeframe,
                        count=BARS_BATCH,
                        force=True,
                        replace_conflicts=True,
                    )
                    store.save_provenance(DatasetProvenance(
                        provider=PROVIDER,
                        symbol=symbol,
                        timeframe=timeframe.value,
                        source="Weltrade MT5 terminal",
                        provider_symbol=symbol,
                        volume_type=VolumeType.TICK_VOLUME,
                        retrieved_at=datetime.now(timezone.utc),
                    ))
                    latest_open = candles[-1].time if candles else None
                    close_step = TIMEFRAME_SECONDS[timeframe]
                    latest_close = latest_open.timestamp() + close_step if latest_open else None
                    age_seconds = max(0.0, datetime.now(timezone.utc).timestamp() - latest_close) if latest_close else None
                    freshness_limit = max(120, close_step * 2)
                    first = candles[0].time.isoformat() if candles else None
                    total = store.count(symbol, timeframe, provider=PROVIDER)
                    result = {
                        "symbol": symbol, "timeframe": label, "status": "OK",
                        "new": downloaded, "fetched_returned": len(candles),
                        "total": total, "first": first,
                        "latest_closed_candle_open": latest_open.isoformat() if latest_open else None,
                        "latest_closed_candle_at": datetime.fromtimestamp(latest_close, tz=timezone.utc).isoformat() if latest_close else None,
                        "freshness_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
                        "freshness_limit_seconds": freshness_limit,
                        "freshness": "FRESH" if age_seconds is not None and age_seconds <= freshness_limit else "STALE",
                    }
                except Exception as exc:
                    result = {
                        "symbol": symbol, "timeframe": label, "status": "UNAVAILABLE",
                        "new": 0, "total": store.count(symbol, timeframe, provider=PROVIDER),
                        "first": None, "latest_closed_candle_open": None,
                        "latest_closed_candle_at": None, "freshness_age_seconds": None,
                        "freshness_limit_seconds": None, "freshness": "UNKNOWN",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                partitions[partition_key] = result
                _write_checkpoint(checkpoint_path, checkpoint)
                print(
                    f"{symbol:<22} {label:<3} {result['status']:<11} "
                    f"+{result['new']:>6} total={result['total']:>7} "
                    f"first={result['first']} close={result['latest_closed_candle_at']} "
                    f"freshness={result['freshness']}"
                )
        if missing:
            for symbol in missing:
                for label, _ in TIMEFRAMES:
                    partition_key = f"{symbol}|{label}"
                    partitions[partition_key] = {
                        "symbol": symbol, "timeframe": label, "status": "UNAVAILABLE",
                        "new": 0, "total": 0, "freshness": "UNKNOWN",
                        "error": "Exact symbol unavailable in terminal catalogue",
                    }
            _write_checkpoint(checkpoint_path, checkpoint)
        if refresh_ticks:
            for symbol in discovered:
                try:
                    tick = await service.refresh_latest_tick(
                        symbol=symbol, provider_symbol=symbol, provider=PROVIDER
                    )
                    print(f"{symbol}: tick={tick.time.isoformat() if tick else 'UNAVAILABLE'}")
                except Exception as exc:
                    print(f"{symbol}: latest tick unavailable ({type(exc).__name__}: {exc})")
        results = list(partitions.values())
        checkpoint["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_checkpoint(checkpoint_path, checkpoint)
        print(f"Finished at {checkpoint['finished_at']}; partitions={len(results)}")
        unavailable = [row for row in results if row.get("status") != "OK"]
        print(f"Unavailable partitions: {len(unavailable)}")
    finally:
        await gateway.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkpoint", type=Path,
        default=Path("reports/syntx-refresh-checkpoint.json"),
        help="Atomic JSON report and resume checkpoint path",
    )
    parser.add_argument("--resume", action="store_true", help="Skip previously successful partitions")
    parser.add_argument("--refresh-ticks", action="store_true", help="Also query and persist latest ticks")
    args = parser.parse_args()
    asyncio.run(refresh(
        checkpoint_path=args.checkpoint,
        resume=args.resume,
        refresh_ticks=args.refresh_ticks,
    ))


if __name__ == "__main__":
    main()
