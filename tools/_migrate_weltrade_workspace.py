"""One-time workspace migration edits; remove after applying."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]

def edit(name, replacements):
    path = root / name
    text = path.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in text:
            raise RuntimeError(f"Missing edit in {name}: {old[:80]}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")

edit(".env.example", [
    ("# Market candles: simulation, deriv_public, or broker (for broker-native symbols)\nJQE_MARKET_DATA_SOURCE=deriv_public", "# All market data comes from the configured Weltrade MT5 terminal.\nJQE_MARKET_DATA_SOURCE=broker"),
    ("# --- MT5 connection (used when JQE_BROKER=mt5; optional — omit\n#     to use an already logged-in terminal instance) -----------\nJQE_MT5_LOGIN=\nJQE_MT5_PASSWORD=\nJQE_MT5_SERVER=\nJQE_MT5_EXPECTED_ENVIRONMENT=demo\n", ""),
    ("# --- Deriv connection (used when JQE_BROKER=deriv) ---------------\n# Get a token at https://app.deriv.com/account/api-token — never\n# commit a real token.\nJQE_DERIV_API_TOKEN=\nJQE_DERIV_APP_ID=1089\nJQE_DERIV_ENDPOINT=wss://ws.derivws.com/websockets/v3\nJQE_DERIV_OPTIONS_ACCOUNT_ID=\nJQE_DERIV_EXPECTED_ENVIRONMENT=demo\n", ""),
    ("JQE_DEFAULT_SYMBOL=R_75", "JQE_DEFAULT_SYMBOL=FX Vol 20"),
    ("JQE_OBSERVATION_SYMBOLS=R_75:H1", "JQE_OBSERVATION_SYMBOLS=FX Vol 20:M1,FX Vol 20:M5,PainX 400:M1,PainX 400:M5"),
    ("JQE_TELEGRAM_ENABLED=true", "JQE_TELEGRAM_ENABLED=false"),
])

edit("backtesting/run.py", [
    ("cached or Deriv-public", "cached or Weltrade MT5"),
    ("from broker.deriv_public_data import DerivPublicMarketData", "from broker.factory import get_gateway\nfrom broker.weltrade_symbols import require_weltrade_synthetic"),
    ('    provider, provider_symbol = "deriv", "frxXAUUSD" if args.symbol.upper() == "XAUUSD" else args.symbol', '    require_weltrade_synthetic(args.symbol)\n    provider, provider_symbol = "weltrade", args.symbol'),
    ('source = DerivPublicMarketData(settings.deriv_app_id, endpoint=settings.deriv_public_endpoint)', 'source = get_gateway(settings)'),
    ('Deriv public historical WebSocket', 'Weltrade MT5 terminal'),
    ('VolumeType.UNAVAILABLE', 'VolumeType.TICK_VOLUME'),
    ('CACHE_PLUS_DERIV_PUBLIC', 'CACHE_PLUS_WELTRADE_MT5'),
    ('DERIV_PUBLIC', 'WELTRADE_MT5'),
    ('default="XAUUSD"', 'default="FX Vol 20"'),
])

# Migrate identity and quantity fixtures to Weltrade, retaining the existing
# assertions for recovery, idempotency, daily limits and account attribution.
for name in ("tests/test_main_durable_executor.py", "tests/test_main_mt5_composition.py", "tests/test_recovery_diagnostics.py"):
    path = root / name
    text = path.read_text(encoding="utf-8")
    text = text.replace('"simulation"', '"weltrade"').replace('"mt5"', '"weltrade"')
    text = text.replace('"Deriv-Demo"', '"Weltrade-Demo"')
    text = text.replace('"XAUUSD"', '"FX VOL 20"').replace('"EURUSD"', '"FX VOL 20"')
    text = text.replace('"SIMULATED"', '"4242"').replace('SIMULATION_UNITS', 'MT5_LOTS')
    if name.endswith('test_main_durable_executor.py'):
        text = text.replace('settings.market_data_source = "weltrade"', 'settings.market_data_source = "broker"')
        text = text.replace('settings.broker_execution_enabled = False', 'settings.broker_execution_enabled = True', 1)
        text = text.replace('AccountInfo(account_id="4242", balance=10_000.0, currency="USD")', 'AccountInfo(account_id="4242", balance=10_000.0, currency="USD", server="Weltrade-Demo", trade_mode="demo")')
        text = text.replace('    gateway.get_positions = AsyncMock(return_value=[])', '    gateway.get_positions = AsyncMock(return_value=[])\n    gateway.authorize_account_currency_risk = AsyncMock(return_value=(\n        ExecutionQuantity(value=1.0, unit=ExecutionQuantityUnit.MT5_LOTS),\n        {"authorized_risk_amount": 2.0, "expected_loss_at_stop": 2.0},\n    ))')
        text = text.replace('async def _empty_market_source(_settings):', 'async def _empty_market_source(_settings, broker_gateway=None):')
    if name.endswith('test_main_mt5_composition.py'):
        # Preserve the explicit sentinel-rejection negative test.
        pos = text.index('async def test_mt5_composition_rejects_simulated_identity')
        text = text[:pos] + text[pos:].replace('account_id="4242"', 'account_id="SIMULATED"')
    if name.endswith('test_recovery_diagnostics.py'):
        text = text.replace('    return SQLiteIntentRecordStore(path)', '    monkeypatch.setattr(settings, "weltrade_demo_login", 4242)\n    return SQLiteIntentRecordStore(path)')
    path.write_text(text, encoding="utf-8")
