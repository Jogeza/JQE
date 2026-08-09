"""Demo script for the TradePlan generation pipeline."""

import json

from core.logger import logger
from core.mt5_connection import connect, disconnect
import MetaTrader5 as mt5
from data.historical_data import HistoricalData
from strategy.pipeline import generate_trading_signal
from core.indicators import calculate_indicators
from intelligence.trade_plan import TradePlanBuilder
from core.symbol_manager import SymbolManager

# Initialize components
symbol_manager = SymbolManager()
db = HistoricalData()
builder = TradePlanBuilder(min_rr=1.5, atr_sl_multiplier=1.5, target_rr=2.0)

SYMBOLS = ["BTCUSD", "GOLD", "DOW30", "EURUSD"]


def print_trade_plan(plan):
    """Formats and prints the TradePlan matching the user's expected output."""
    print("=" * 50)
    print("JQE TRADE PLAN")
    print("=" * 50)
    print(f"\nSYMBOL: {plan.symbol}\n")
    print(f"SIGNAL: {plan.signal}")
    print(f"QUALITY: {plan.quality}")
    print(f"CONFIDENCE: {plan.confidence}\n")

    if plan.signal != "NO_TRADE":
        print(f"ENTRY: {plan.entry}")
        print(f"STOP LOSS: {plan.stop_loss}")
        print(f"TAKE PROFIT: {plan.take_profit}\n")
        
        risk = abs(plan.entry - plan.stop_loss)
        reward = abs(plan.take_profit - plan.entry)
        print(f"RISK: {round(risk, 5)}")
        print(f"REWARD: {round(reward, 5)}")
        print(f"R:R: 1:{plan.risk_reward}\n")

    print(f"ATR: {round(plan.atr, 5) if plan.atr else 'N/A'}\n")
    
    print(f"TREND: {plan.trend}")
    print(f"MOMENTUM: {plan.momentum}")
    print(f"VOLATILITY: {plan.volatility}")
    print(f"LIQUIDITY: {plan.liquidity}")
    print(f"REGIME: {plan.regime}\n")
    
    print("REASONS:")
    for reason in plan.reasons:
        print(f"  * {reason}")
    print()
    
    print("WARNINGS:")
    if not plan.warnings:
        print("  (None)")
    for warning in plan.warnings:
        print(f"  ! {warning}")
    print()
    
    if plan.invalidation:
        print("INVALIDATION:")
        print(f"  {plan.invalidation}\n")
        
    print(f"TRADE VALID: {'YES' if plan.is_valid() else 'NO'}")
    print("=" * 50)
    print()


def run():
    connect()

    for symbol in SYMBOLS:
        broker_symbol = symbol_manager.find_symbol(symbol)
        
        if not broker_symbol:
            # Replicate behavior of scanner
            plan = builder.build(
                symbol=symbol,
                intelligence={},
                signal_dict={},
                price=0.0
            )
            print_trade_plan(plan)
            continue
            
        # Get historical data for indicators
        try:
            df = db.load(symbol, "M15")
        except FileNotFoundError:
            # Replicate scanner's "no data" fallback
            plan = builder.build(
                symbol=symbol,
                intelligence={},
                signal_dict={},
                price=0.0
            )
            print_trade_plan(plan)
            continue
            
        df = calculate_indicators(df)
        
        # Get live price (mimic scanner)
        tick = mt5.symbol_info_tick(broker_symbol)
        price = tick.ask if tick else 0.0
        
        # We'll use the existing generate_trading_signal which wraps FeatureEngine/SignalEngine/Scorer
        # Note: generate_trading_signal expects the df
        signal_output = generate_trading_signal(df, broker_symbol)
        
        # Extract the intelligence part from generate_trading_signal's output to feed to TradePlanBuilder
        intelligence = signal_output.get("intelligence", {})
        
        plan = builder.build(
            symbol=symbol,
            intelligence=intelligence,
            signal_dict=signal_output,
            price=price,
            account_balance=10000.0, # Dummy balance
            risk_percent=1.0
        )
        
        print_trade_plan(plan)

    disconnect()


if __name__ == "__main__":
    run()
