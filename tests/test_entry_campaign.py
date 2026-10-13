from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.entry_campaign import UNIVERSE, build_protocol
from tools.acquire_entry_campaign import acquire, contract_probes, forbidden, save_new, readonly_initialize


def test_registration_keeps_future_holdout_separate_and_one_trial():
    now = datetime(2026, 10, 8, 8, tzinfo=timezone.utc)
    protocol = build_protocol(now)
    windows = protocol["windows"]
    assert datetime.fromisoformat(windows["train"]["end_exclusive"]) < now
    assert now < datetime.fromisoformat(windows["validation"]["start_inclusive"])
    assert windows["validation"]["end_exclusive"] == windows["test"]["start_inclusive"]
    assert protocol["parameter_grid"] == {"maximum_entry_distance_ema50_atr": [2.0]}
    assert len(protocol["symbols"]) == 10
    assert protocol["candidate_configurations_evaluated"] == 0
    with pytest.raises(ValueError):
        build_protocol(now.replace(tzinfo=None))


def test_contract_probes_check_both_sides_and_loss_signs():
    info = SimpleNamespace(trade_tick_size=.1, trade_tick_value=.1, volume_min=.01)
    sdk = SimpleNamespace(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1,
        symbol_info_tick=lambda s: SimpleNamespace(bid=1000, ask=1001),
        order_calc_profit=lambda side, symbol, volume, entry, exit: (exit-entry) * volume * (1 if side == 0 else -1))
    result = contract_probes(sdk, "FX Vol 20", info, "USD")
    assert len(result["profit_probes"]) == 8
    assert result["account_currency"] == "USD"
    assert result["commission_status"] == "NOT_VERIFIED"
    sdk.order_calc_profit = lambda *args: None
    with pytest.raises(RuntimeError, match="unavailable or inconsistent"):
        contract_probes(sdk, "FX Vol 20", info, "USD")


def test_minimum_lot_probes_survive_account_currency_rounding():
    info = SimpleNamespace(trade_tick_size=.01, trade_tick_value=.01, volume_min=.01)
    sdk = SimpleNamespace(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1,
        symbol_info_tick=lambda s: SimpleNamespace(bid=118000, ask=118004),
        order_calc_profit=lambda side,s,v,e,x: round((x-e)*v*(1 if side == 0 else -1), 2))
    result = contract_probes(sdk, "FX Vol 20", info, "USD")
    assert len(result["profit_probes"]) == 8
    assert all(abs(p["pnl"]) >= .1 for p in result["profit_probes"])


def test_existing_evidence_and_mutating_sdk_calls_are_rejected(tmp_path):
    path = tmp_path / "frozen.json"
    save_new(path, {"original": True})
    with pytest.raises(FileExistsError):
        save_new(path, {})
    assert json.loads(path.read_text()) == {"original": True}
    with pytest.raises(RuntimeError, match="forbids"):
        forbidden("FX Vol 20", True)


def test_readonly_attachment_never_logs_in_and_rejects_wrong_account(monkeypatch):
    import MetaTrader5 as mt5
    closed = []
    monkeypatch.setattr(mt5, "initialize", lambda *a, **k: True)
    monkeypatch.setattr(mt5, "login", lambda *a, **k: pytest.fail("Account mutation forbidden"))
    monkeypatch.setattr(mt5, "shutdown", lambda: closed.append(True))
    monkeypatch.setattr(mt5, "account_info", lambda: SimpleNamespace(trade_mode=0, login=123, server="Weltrade-Demo"))
    assert readonly_initialize(terminal_path="test", login=123, password=None, server="Weltrade-Demo") is True
    assert readonly_initialize(terminal_path="test", login=456, password=None, server="Weltrade-Demo") is False
    assert closed == [True]


async def test_running_terminal_blocks_before_gateway_construction(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.acquire_entry_campaign.terminal_processes", lambda: [{"ProcessId": 1}])
    monkeypatch.setattr("broker.factory.get_gateway", lambda *args: pytest.fail("Must not construct gateway"))
    from config.settings import settings
    monkeypatch.setattr(settings, "market_data_source", "broker")
    report = await acquire(tmp_path / "campaign", 400)
    assert report["status"] == "BLOCKED"
    assert "Existing MT5 process" in report["reason"]
    assert (tmp_path / "campaign/protocol.json").is_file()
    assert not (tmp_path / "campaign/historical.sqlite3").exists()


async def test_acquisition_uses_new_service_store_and_binds_spread_sidecar(tmp_path, monkeypatch):
    import MetaTrader5 as mt5
    from broker.types import Candle
    from config.settings import settings
    from data.dataset import load_dataset_bundle
    import tools.acquire_entry_campaign as module

    now = datetime.now(timezone.utc)
    latest = datetime.fromtimestamp(int(now.timestamp()) // 300 * 300 - 300, tz=timezone.utc)
    candles = [Candle(time=latest - timedelta(minutes=5*(399-i)), open=100, high=102,
                     low=99, close=101, volume=10, source="weltrade") for i in range(400)]
    info = SimpleNamespace(name="FX Vol 20", visible=True, trade_tick_size=.1, trade_tick_value=.1, volume_min=.01, point=.01)
    tick = SimpleNamespace(time=int(now.timestamp())+10800, bid=1000, ask=1001)
    disconnected = []
    class Gateway:
        async def connect(self): pass
        async def disconnect(self): disconnected.append(True)
        async def get_candles(self, symbol, timeframe, count):
            assert count == 401
            mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 1, count)
            return candles
    monkeypatch.setattr(module, "UNIVERSE", ("FX Vol 20",))
    monkeypatch.setattr(module, "terminal_processes", lambda: [])
    monkeypatch.setattr("broker.factory.get_gateway", lambda s: Gateway())
    monkeypatch.setattr(settings, "market_data_source", "broker")
    monkeypatch.setattr(settings, "weltrade_terminal_path", Path("D:/fake/terminal64.exe"))
    monkeypatch.setattr(settings, "weltrade_demo_login", 123)
    monkeypatch.setattr(settings, "weltrade_demo_server", "Weltrade-Demo")
    monkeypatch.setattr(mt5, "account_info", lambda: SimpleNamespace(trade_mode=0, login=123, server="Weltrade-Demo", currency="USD"))
    monkeypatch.setattr(mt5, "terminal_info", lambda: SimpleNamespace(path="D:/fake"))
    monkeypatch.setattr(mt5, "symbols_get", lambda: [info])
    monkeypatch.setattr(mt5, "symbol_info", lambda s: info)
    monkeypatch.setattr(mt5, "symbol_info_tick", lambda s: tick)
    monkeypatch.setattr(mt5, "order_calc_profit", lambda side,s,v,e,x: (x-e)*v*(1 if side == mt5.ORDER_TYPE_BUY else -1))
    monkeypatch.setattr(mt5, "copy_rates_from_pos", lambda *a: [dict(time=int(c.time.timestamp())+10800,
        open=c.open, high=c.high, low=c.low, close=c.close, spread=10) for c in candles])
    original_store = settings.historical_data_path
    output = tmp_path / "campaign"
    report = await acquire(output, 400)
    assert report["status"] == "ACQUIRED_NEEDS_COST_MODEL_AND_FUTURE_HOLDOUT"
    assert report["market_watch_unchanged"] is True
    assert settings.historical_data_path == original_store
    assert disconnected == [True]
    assert (output / "historical.sqlite3").is_file()
    bundle = output / "bundles/FX_Vol_20_M5"
    loaded, manifest = load_dataset_bundle(bundle)
    spreads = json.loads((bundle / "recorded-spread.json").read_text())
    assert len(loaded) == len(spreads["rows"]) == 400
    assert spreads["content_hash"] == manifest.content_hash
