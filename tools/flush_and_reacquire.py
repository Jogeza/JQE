"""Flush corrupted weltrade candles and re-acquire with corrected UTC timestamps.

Steps:
1. Delete all candles WHERE provider='weltrade' using CandleStore.clear()
2. Re-acquire via WeltradeGateway if the terminal is live (500 bars M1+M5)
3. Print a coverage summary; flag any bar whose timestamp exceeds current UTC
   (which would indicate the fix is insufficient or a new offset bug)
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.storage import CandleStore
from broker.types import Timeframe

DB_PATH = ROOT / "data" / "historical.sqlite3"

WATCHLIST = [
    "FX Vol 20",
    "FX Vol 40",
    "FX Vol 60",
    "FX Vol 80",
    "FX Vol 99",
    "SFX Vol 20",
    "SFX Vol 40",
    "SFX Vol 60",
    "SFX Vol 80",
    "SFX Vol 99",
    "PainX 400",
    "PainX 600",
    "PainX 800",
    "PainX 999",
    "PainX 1200",
    "MAX PainX 1000",
    "MAX PainX 2000",
]

TIMEFRAMES = [Timeframe.M1, Timeframe.M5]
TF_LABELS = {Timeframe.M1: "M1", Timeframe.M5: "M5"}


async def main() -> None:
    store = CandleStore(DB_PATH)

    # --- Step 1: Flush ---
    print("=== Step 1: Flushing corrupted weltrade candles ===")
    deleted = store.clear(provider="weltrade")
    print(f"Deleted {deleted} rows from candles (provider='weltrade')")

    # --- Step 2: Try to connect to WeltradeGateway ---
    print("\n=== Step 2: Acquiring corrected candles via WeltradeGateway ===")

    try:
        from broker.weltrade_gateway import WeltradeGateway
        from config.settings import Settings

        settings = Settings()
        gateway = WeltradeGateway(settings)

        try:
            async with gateway:
                print("Gateway connected. Acquiring 500 bars per symbol/timeframe...")
                ok_count = 0
                fail_count = 0
                for symbol in WATCHLIST:
                    for tf in TIMEFRAMES:
                        tf_label = TF_LABELS[tf]
                        try:
                            candles = await gateway.get_candles(symbol, tf, count=500)
                            if not candles:
                                print(f"  {symbol:22} {tf_label} -> EMPTY (0 candles)")
                                fail_count += 1
                                continue
                            saved = store.save_candles(symbol, tf, candles, provider="weltrade")
                            print(f"  {symbol:22} {tf_label} -> OK  ({len(candles)} fetched, {saved} new stored)")
                            ok_count += 1
                        except Exception as e:
                            print(f"  {symbol:22} {tf_label} -> ERROR: {e}")
                            fail_count += 1
                print(f"\nAcquisition: {ok_count} OK, {fail_count} failed/empty")

        except Exception as conn_err:
            print(f"Gateway connection failed: {conn_err}")
            print("Cannot acquire without live Weltrade MT5 terminal.")
            print("Run this script again when the terminal is connected.")
            return

    except Exception as import_err:
        print(f"Import error: {import_err}")
        return

    # --- Step 3: Validation coverage summary ---
    print("\n=== Step 3: Post-acquisition validation ===")
    now_utc = datetime.now(tz=timezone.utc)
    print(f"Current UTC: {now_utc.isoformat()}")
    print()

    issues = []
    print(f"{'Symbol':22} {'TF':3} | {'Bars':>5} | {'Min UTC':30} | {'Max UTC':30} | Status")
    print("-" * 115)
    for symbol in WATCHLIST:
        for tf in TIMEFRAMES:
            tf_label = TF_LABELS[tf]
            coverage = store.get_coverage(symbol, tf, provider="weltrade")
            cnt = store.count(symbol, tf, provider="weltrade")
            if coverage is None:
                print(f"{symbol:22} {tf_label:3} | {0:5} | {'MISSING':30} | {'':30} | MISSING")
                issues.append(f"{symbol} {tf_label}: no data")
                continue
            mn_dt, mx_dt = coverage
            future_flag = ""
            if mx_dt > now_utc:
                future_flag = " [FUTURE - OFFSET BUG]"
                issues.append(f"{symbol} {tf_label}: max timestamp in future ({mx_dt.isoformat()})")
            print(
                f"{symbol:22} {tf_label:3} | {cnt:5} | {mn_dt.isoformat():30} | "
                f"{mx_dt.isoformat():30} | {'OK' if not future_flag else 'FUTURE'}"
            )

    print()
    if issues:
        print(f"ISSUES FOUND ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("All timestamps validated: no future-dated bars detected.")


if __name__ == "__main__":
    asyncio.run(main())
