"""Read current contract conventions/margin into a NEW research evidence file."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from research.entry_campaign import UNIVERSE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("Refusing to overwrite research evidence")
    from config.settings import settings
    from tools.acquire_entry_campaign import terminal_processes
    processes = terminal_processes()
    if (len(processes) != 1 or not processes[0].get("ExecutablePath")
        or Path(processes[0]["ExecutablePath"]).resolve() != Path(settings.weltrade_terminal_path).resolve()):
        raise RuntimeError("Exactly the configured running terminal is required")
    import MetaTrader5 as mt5
    if not mt5.initialize(str(settings.weltrade_terminal_path), timeout=10000):
        raise RuntimeError("Read-only IPC attachment failed")
    try:
        account, terminal = mt5.account_info(), mt5.terminal_info()
        if (account is None or terminal is None or account.trade_mode != 0
            or account.login != settings.effective_weltrade_login or account.server != settings.effective_weltrade_server
            or "WELTRADE" not in account.server.upper()
            or (Path(terminal.path)/"terminal64.exe").resolve() != Path(settings.weltrade_terminal_path).resolve()):
            raise RuntimeError("Configured Weltrade demo identity/path mismatch")
        report = {"observed_at": datetime.now(timezone.utc).isoformat(), "account_currency": account.currency,
            "account_leverage": account.leverage, "symbols": [],
            "enum_values": {n: getattr(mt5,n) for n in ("SYMBOL_CALC_MODE_CFD", "SYMBOL_SWAP_MODE_INTEREST_CURRENT", "SYMBOL_CHART_MODE_BID")}}
        for symbol in UNIVERSE:
            info, tick = mt5.symbol_info(symbol), mt5.symbol_info_tick(symbol)
            if info is None or tick is None or not info.visible:
                raise RuntimeError("Visible exact symbol and tick required; no selection mutation permitted")
            fields = ("currency_profit", "currency_margin", "currency_base", "chart_mode", "swap_rollover3days",
                "swap_long", "swap_short", "swap_mode", "margin_initial", "margin_maintenance", "trade_calc_mode",
                "trade_contract_size", "trade_tick_size", "trade_tick_value", "trade_tick_value_profit", "trade_tick_value_loss",
                "point", "volume_min", "volume_step", "volume_max", "trade_stops_level")
            row = {"symbol": symbol, **{name: getattr(info,name,None) for name in fields}, "margin_probes": []}
            for side, action, price in (("BUY", mt5.ORDER_TYPE_BUY, tick.ask), ("SELL", mt5.ORDER_TYPE_SELL, tick.bid)):
                for lots in (info.volume_min, min(info.volume_max, info.volume_min * 2)):
                    row["margin_probes"].append({"side": side, "price": price, "lots": lots,
                        "margin": mt5.order_calc_margin(action, symbol, lots, price)})
            report["symbols"].append(row)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print(f"Captured {len(report['symbols'])} contract conventions; no orders or login calls")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
