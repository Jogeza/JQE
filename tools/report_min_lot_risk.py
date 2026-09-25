"""Read-only minimum-lot stop-risk report for the 34 watch entries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config.settings import get_settings
from data.watchlist import WatchlistStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--balance", type=float, default=144.51)
    parser.add_argument("--risk-percent", type=float, default=1.0)
    parser.add_argument("--survey", type=Path, default=Path("state/weltrade_cost_survey.json"))
    parser.add_argument("--output", type=Path, default=Path("state/min_lot_risk_real_balance.json"))
    args = parser.parse_args()
    survey = json.loads(args.survey.read_text(encoding="utf-8"))
    watchlist = WatchlistStore(get_settings().watchlist_store_path)
    watched_symbols = {item.symbol.upper() for item in watchlist.get_watch_pairs()}
    authorized = args.balance * args.risk_percent / 100.0
    rows = []
    for item in sorted(survey.get("rows", []), key=lambda row: str(row.get("symbol", ""))):
        symbol = str(item.get("symbol", ""))
        if symbol.upper() not in watched_symbols:
            continue
        for timeframe in ("M1", "M5"):
            risk = item.get("timeframes", {}).get(timeframe, {}).get("min_lot_loss_usd")
            risk = None if risk is None else float(risk)
            rows.append({
                "symbol": symbol, "timeframe": timeframe,
                "min_lot": item.get("volume_min"),
                "min_lot_stop_risk_usd": risk,
                "min_lot_stop_risk_percent_of_balance": (100.0 * risk / args.balance if risk is not None else None),
                "authorized_risk_usd": authorized,
                "fits_at_configured_risk": risk is not None and risk <= authorized,
                "required_risk_percent_to_fit": (100.0 * risk / args.balance if risk is not None else None),
            })
    result = {
        "balance_usd": args.balance, "configured_risk_percent": args.risk_percent,
        "authorized_risk_usd": authorized, "source": str(args.survey), "rows": rows,
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "balance_usd": args.balance, "authorized_risk_usd": authorized, "rows": len(rows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
