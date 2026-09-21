"""Mocked coverage for the read-only DEMO synthetic-index verification tool."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.demo_synthetic_verification as verification
from broker.types import AccountInfo, Candle, Timeframe, TradeHistorySnapshot
from core.exceptions import BrokerAuthenticationError
from data.broker_selection import BrokerSelectionStore
from tools.demo_synthetic_verification import (
    ReadOnlyGateway,
    _discover_deriv_symbols,
    _discover_weltrade_symbols,
    _evaluate_pipeline,
    _verify_deriv,
    _verify_weltrade,
    run,
)

DERIV_ACTIVE_SYMBOLS = {
    "active_symbols": [
        {
            "symbol": "R_75",
            "market": "synthetic_index",
            "submarket": "continuous_index",
            "display_name": "Volatility 75 Index",
            "exchange_is_open": 1,
        },
        {
            "symbol": "1HZ100V",
            "market": "synthetic_index",
            "submarket": "continuous_index",
            "display_name": "Volatility 100 (1s) Index",
            "exchange_is_open": 1,
        },
        {"symbol": "EURUSD", "market": "forex", "exchange_is_open": 1},
        {"symbol": "frxXAUUSD", "market": "commodities", "exchange_is_open": 0},
        {"market": "synthetic_index", "exchange_is_open": 1},
        "not-a-mapping",
    ]
}


@dataclass
class StubSettings:
    broker: str = "mt5"
    broker_execution_enabled: bool = False
    broker_selection_store_path: Path = field(
        default_factory=lambda: Path("state/broker_selection.sqlite3")
    )
    deriv_api_token: str = "test-token"
    deriv_app_id: str = "1089"
    deriv_options_account_id: str = "VRTC00008175"
    deriv_expected_environment: str = "demo"
    deriv_public_endpoint: str = "wss://example.invalid/public"
    weltrade_terminal_path: Path | None = Path("C:/terminal64.exe")
    effective_weltrade_login: int | None = 8111
    effective_weltrade_password: str | None = "test-password"
    effective_weltrade_server: str | None = "Weltrade-Demo"

    @property
    def effective_broker(self) -> str:
        from data.broker_selection import get_effective_broker

        return get_effective_broker(self)


class FakeGateway:
    """Read-only stand-in for a demo broker gateway."""

    def __init__(
        self,
        *,
        candles: list[Candle],
        account: AccountInfo,
        demo_verified: bool = True,
        connect_error: Exception | None = None,
        resolved_symbol: str | None = None,
    ) -> None:
        self._candles = candles
        self._account = account
        self._demo_verified = demo_verified
        self._connect_error = connect_error
        self._resolved = resolved_symbol
        self.connected = False
        self.connect_count = 0
        self.candle_requests: list[tuple[str, Timeframe, int]] = []
        self.inner_submit_calls = 0
        self.account_identity = SimpleNamespace(
            state=SimpleNamespace(value="VERIFIED_DEMO"), environment="demo"
        )

    async def __aenter__(self) -> "FakeGateway":
        self.connect_count += 1
        if self._connect_error is not None:
            raise self._connect_error
        self.connected = True
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        self.connected = False
        return False

    @property
    def is_connected(self) -> bool:
        return self.connected

    def _resolve_symbol(self, symbol: str) -> str | None:
        return self._resolved or symbol

    async def get_account_info(self) -> AccountInfo:
        return self._account

    async def get_candles(
        self, symbol: str, timeframe: Timeframe, count: int, end: datetime | None = None
    ) -> list[Candle]:
        self.candle_requests.append((symbol, timeframe, count))
        return list(self._candles)

    async def get_trade_history_snapshot(self, *, start, end, count) -> TradeHistorySnapshot:
        return TradeHistorySnapshot(coverage_start=start, coverage_end=end)

    async def submit_order(self, order) -> object:
        self.inner_submit_calls += 1
        raise AssertionError("verification gateway must never receive an order")


class FakePublicMarketData:
    payload: dict = DERIV_ACTIVE_SYMBOLS

    def __init__(self, app_id: str = "", endpoint: str = "") -> None:
        self.app_id = app_id
        self.endpoint = endpoint
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def get_active_symbols(self) -> dict:
        return type(self).payload


def _candles(count: int = 200, *, corrupt: bool = False) -> list[Candle]:
    anchor = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    first = anchor - timedelta(hours=count - 1)
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        open_price = price
        close_price = price + 0.35 * math.sin(index / 7.0) + 0.08
        high = max(open_price, close_price) + 0.4
        low = min(open_price, close_price) - 0.4
        if corrupt and index == count - 5:
            high, low = low - 1.0, high + 1.0
        candles.append(
            Candle(
                time=first + timedelta(hours=index),
                open=open_price,
                high=high,
                low=low,
                close=close_price,
                volume=1_000.0,
                source="test",
            )
        )
        price = close_price
    return candles


def _args(**overrides) -> argparse.Namespace:
    base = {
        "broker": "all",
        "symbol": None,
        "timeframe": "H1",
        "count": 200,
        "json_out": None,
        "keep_selection": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _steps(report) -> dict[str, object]:
    return {step.step: step for step in report.steps}


@pytest.fixture(autouse=True)
def _isolated_evidence_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verification, "DEFAULT_BROKER_EVIDENCE_PATH", tmp_path / "absent-evidence.sqlite3"
    )
    monkeypatch.setattr(
        "broker.deriv_public_data.DerivPublicMarketData", FakePublicMarketData
    )


@pytest.fixture
def stub_settings(tmp_path: Path) -> StubSettings:
    return StubSettings(broker_selection_store_path=tmp_path / "broker_selection.sqlite3")


def _install_gateway(monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway) -> list[StubSettings]:
    constructed: list[StubSettings] = []

    def fake_get_gateway(settings):
        constructed.append(settings)
        return gateway

    monkeypatch.setattr(verification, "get_gateway", fake_get_gateway)
    return constructed


def _install_mt5(monkeypatch: pytest.MonkeyPatch, names: list[str]) -> None:
    fake = SimpleNamespace(
        symbols_get=lambda: [
            SimpleNamespace(name=name, description=name, path="Synth", visible=True)
            for name in names
        ]
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)


# --- read-only gateway wrapper -------------------------------------------


async def test_read_only_gateway_blocks_submit_order() -> None:
    inner = FakeGateway(
        candles=_candles(5),
        account=AccountInfo(account_id="VRTC1", balance=100.0, currency="USD"),
    )
    gateway = ReadOnlyGateway(inner)
    with pytest.raises(AssertionError):
        await gateway.submit_order(object())
    assert gateway.submission_attempts == 1
    assert inner.inner_submit_calls == 0


def test_read_only_gateway_delegates_read_methods() -> None:
    inner = FakeGateway(
        candles=_candles(5),
        account=AccountInfo(account_id="VRTC1", balance=100.0, currency="USD"),
    )
    gateway = ReadOnlyGateway(inner)
    assert gateway.inner is inner
    assert gateway.is_connected is False
    assert gateway.get_account_info == inner.get_account_info


# --- broker-confirmed synthetic symbol discovery --------------------------


async def test_deriv_discovery_only_accepts_broker_synthetic_index_symbols() -> None:
    discovered = await _discover_deriv_symbols(StubSettings())
    assert [entry["symbol"] for entry in discovered] == ["1HZ100V", "R_75"]
    assert discovered[1]["display_name"] == "Volatility 75 Index"


async def test_deriv_discovery_ignores_unusable_records() -> None:
    FakePublicMarketData.payload = {
        "active_symbols": [{"market": "synthetic_index"}, {"symbol": "  ", "market": "synthetic_index"}]
    }
    try:
        assert await _discover_deriv_symbols(StubSettings()) == []
    finally:
        FakePublicMarketData.payload = DERIV_ACTIVE_SYMBOLS


async def test_weltrade_discovery_filters_terminal_synthetic_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mt5(monkeypatch, ["FX Vol 20", "EURUSD", "Vol 75 Index", "XAUUSD", "MAX PainX 1000"])
    discovered = _discover_weltrade_symbols()
    assert [entry["symbol"] for entry in discovered] == [
        "FX Vol 20",
        "MAX PainX 1000",
        "Vol 75 Index",
    ]


async def test_weltrade_discovery_returns_empty_when_no_synthetic_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mt5(monkeypatch, ["EURUSD", "XAUUSD"])
    assert _discover_weltrade_symbols() == []


# --- Deriv demo verification ---------------------------------------------


async def test_verify_deriv_completes_read_only_flow(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = FakeGateway(
        candles=_candles(),
        account=AccountInfo(
            account_id="VRTC00008175", balance=9_998.0, currency="USD", equity=9_998.0
        ),
    )
    constructed = _install_gateway(monkeypatch, gateway)

    report = await _verify_deriv(stub_settings, _args(broker="deriv"))
    report = verification._finalize(report)

    assert report.outcome == "VERIFIED_READ_ONLY"
    assert report.blocker is None
    steps = _steps(report)
    assert steps["1-2-selection"].status == "PASSED"
    assert steps["1-2-selection"].detail["persisted_selection"] == "deriv"
    assert steps["1-2-selection"].detail["effective_broker"] == "deriv"
    assert steps["4-demo-identity"].status == "PASSED"
    assert steps["4-demo-identity"].detail["account_id_masked"] == "******8175"
    assert steps["6-symbol-discovery"].detail["selected_symbol"] == "1HZ100V"
    assert gateway.candle_requests[0][0] == "1HZ100V"
    assert steps["7-candles"].status == "PASSED"
    assert steps["8-10-pipeline"].detail["market_data_valid"] is True
    assert steps["11-no-submission"].status == "PASSED"
    assert steps["11-no-submission"].detail["submission_attempts"] == 0
    assert steps["12-session-closed"].status == "PASSED"
    assert gateway.connect_count == 1
    assert gateway.inner_submit_calls == 0
    assert gateway.connected is False
    assert BrokerSelectionStore(stub_settings.broker_selection_store_path).get_selected_broker() == "deriv"
    assert constructed and constructed[0] is stub_settings


async def test_verify_deriv_uses_explicit_symbol_override(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = FakeGateway(
        candles=_candles(),
        account=AccountInfo(account_id="VRTC00008175", balance=100.0, currency="USD"),
    )
    _install_gateway(monkeypatch, gateway)

    report = await _verify_deriv(stub_settings, _args(broker="deriv", symbol="R_75"))

    assert gateway.candle_requests[0][0] == "R_75"
    assert _steps(report)["6-symbol-discovery"].detail["selected_symbol"] == "R_75"


async def test_verify_deriv_blocks_when_environment_is_not_demo(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_settings.deriv_expected_environment = "live"
    constructed = _install_gateway(
        monkeypatch,
        FakeGateway(
            candles=_candles(),
            account=AccountInfo(account_id="VRTC1", balance=1.0, currency="USD"),
        ),
    )

    report = await _verify_deriv(stub_settings, _args(broker="deriv"))

    assert report.outcome == "BLOCKED"
    assert "not 'demo'" in (report.blocker or "")
    assert constructed == []


async def test_verify_deriv_blocks_without_credentials_and_never_uses_simulation(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_settings.deriv_api_token = ""
    constructed = _install_gateway(
        monkeypatch,
        FakeGateway(
            candles=_candles(),
            account=AccountInfo(account_id="VRTC1", balance=1.0, currency="USD"),
        ),
    )

    report = await _verify_deriv(stub_settings, _args(broker="deriv"))

    assert report.outcome == "BLOCKED"
    assert constructed == []
    assert stub_settings.effective_broker == "mt5"


async def test_verify_deriv_blocks_when_no_synthetic_symbols_returned(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = FakeGateway(
        candles=_candles(),
        account=AccountInfo(account_id="VRTC00008175", balance=100.0, currency="USD"),
    )
    _install_gateway(monkeypatch, gateway)
    FakePublicMarketData.payload = {
        "active_symbols": [{"symbol": "EURUSD", "market": "forex", "exchange_is_open": 1}]
    }
    try:
        report = await _verify_deriv(stub_settings, _args(broker="deriv"))
    finally:
        FakePublicMarketData.payload = DERIV_ACTIVE_SYMBOLS

    assert report.outcome == "BLOCKED"
    assert "no synthetic_index symbols" in (report.blocker or "")
    assert gateway.candle_requests == []


async def test_verify_deriv_reports_demo_identity_rejection(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = FakeGateway(
        candles=_candles(),
        account=AccountInfo(account_id="CR00001234", balance=100.0, currency="USD"),
        connect_error=BrokerAuthenticationError(
            "Deriv account is not authoritatively verified as DEMO"
        ),
    )
    _install_gateway(monkeypatch, gateway)

    report = await _verify_deriv(stub_settings, _args(broker="deriv"))

    assert report.outcome == "BLOCKED"
    assert "not authoritatively verified as DEMO" in (report.blocker or "")
    assert _steps(report)["3-connect"].status == "FAILED"
    assert "12-session-closed" not in _steps(report)
    assert gateway.connect_count == 1


async def test_verify_deriv_flags_unverified_demo_guard(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = FakeGateway(
        candles=_candles(),
        account=AccountInfo(account_id="VRTC00008175", balance=100.0, currency="USD"),
        demo_verified=False,
    )
    _install_gateway(monkeypatch, gateway)

    report = await _verify_deriv(stub_settings, _args(broker="deriv"))
    report = verification._finalize(report)

    assert report.outcome == "FAILED"
    assert _steps(report)["4-demo-identity"].status == "FAILED"


# --- Weltrade demo verification ------------------------------------------


async def test_verify_weltrade_completes_read_only_flow(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mt5(monkeypatch, ["FX Vol 20", "Vol 75 Index", "EURUSD"])
    gateway = FakeGateway(
        candles=_candles(),
        account=AccountInfo(
            account_id="51008111",
            balance=198.92,
            currency="USD",
            server="Weltrade-Demo",
            trade_mode="demo",
        ),
        resolved_symbol="FX Vol 20",
    )
    _install_gateway(monkeypatch, gateway)

    report = await _verify_weltrade(stub_settings, _args(broker="weltrade"))
    report = verification._finalize(report)

    assert report.outcome == "VERIFIED_READ_ONLY"
    steps = _steps(report)
    assert steps["1-2-selection"].detail["effective_broker"] == "weltrade"
    assert steps["4-demo-identity"].detail["trade_mode"] == "demo"
    assert steps["4-demo-identity"].detail["server"] == "Weltrade-Demo"
    assert steps["4-demo-identity"].detail["account_id_masked"] == "******8111"
    assert steps["6-symbol-discovery"].detail["selected_symbol"] == "FX Vol 20"
    assert steps["6-symbol-discovery"].detail["resolved_symbol"] == "FX Vol 20"
    assert gateway.candle_requests[0][0] == "FX Vol 20"
    assert steps["11-no-submission"].detail["submission_attempts"] == 0
    assert steps["12-session-closed"].status == "PASSED"
    assert gateway.connect_count == 1
    assert gateway.connected is False


async def test_verify_weltrade_blocks_without_terminal_path(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_settings.weltrade_terminal_path = None
    constructed = _install_gateway(
        monkeypatch,
        FakeGateway(
            candles=_candles(),
            account=AccountInfo(account_id="1", balance=1.0, currency="USD"),
        ),
    )

    report = await _verify_weltrade(stub_settings, _args(broker="weltrade"))

    assert report.outcome == "BLOCKED"
    assert "TERMINAL_PATH" in (report.blocker or "")
    assert constructed == []


async def test_verify_weltrade_blocks_without_demo_login_identity(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_settings.effective_weltrade_login = None
    constructed = _install_gateway(
        monkeypatch,
        FakeGateway(
            candles=_candles(),
            account=AccountInfo(account_id="1", balance=1.0, currency="USD"),
        ),
    )

    report = await _verify_weltrade(stub_settings, _args(broker="weltrade"))

    assert report.outcome == "BLOCKED"
    assert constructed == []


async def test_verify_weltrade_reports_non_weltrade_server_rejection(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mt5(monkeypatch, ["FX Vol 20"])
    gateway = FakeGateway(
        candles=_candles(),
        account=AccountInfo(account_id="51008111", balance=1.0, currency="USD"),
        connect_error=BrokerAuthenticationError("MT5 account server is not a Weltrade demo server"),
    )
    _install_gateway(monkeypatch, gateway)

    report = await _verify_weltrade(stub_settings, _args(broker="weltrade"))

    assert report.outcome == "BLOCKED"
    assert "not a Weltrade demo server" in (report.blocker or "")


async def test_verify_weltrade_blocks_when_no_synthetic_symbols(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mt5(monkeypatch, ["EURUSD", "XAUUSD"])
    gateway = FakeGateway(
        candles=_candles(),
        account=AccountInfo(
            account_id="51008111", balance=1.0, currency="USD", trade_mode="demo"
        ),
    )
    _install_gateway(monkeypatch, gateway)

    report = await _verify_weltrade(stub_settings, _args(broker="weltrade"))

    assert report.outcome == "BLOCKED"
    assert "no recognizable synthetic symbols" in (report.blocker or "")
    assert gateway.candle_requests == []


async def test_verify_weltrade_reports_candle_failure(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mt5(monkeypatch, ["FX Vol 20"])
    gateway = FakeGateway(
        candles=[],
        account=AccountInfo(
            account_id="51008111", balance=1.0, currency="USD", trade_mode="demo"
        ),
    )
    _install_gateway(monkeypatch, gateway)

    report = await _verify_weltrade(stub_settings, _args(broker="weltrade"))

    assert report.outcome == "BLOCKED"
    assert "returned no candles" in (report.blocker or "")
    assert _steps(report)["7-candles"].status == "FAILED"


# --- pipeline, stop-loss and plan invariants ------------------------------


def test_pipeline_enforces_mandatory_stop_loss_and_lifecycle_invariants() -> None:
    result = _evaluate_pipeline(
        _candles(), symbol="R_75", balance=10_000.0, timeframe=Timeframe.H1
    )

    assert result["status"] == "PIPELINE_EXECUTED"
    assert result["market_data_valid"] is True
    assert result["candles_closed"] > 0
    for direction in ("buy", "sell"):
        check = result[f"invariant_self_check_{direction}"]
        assert check["stop_loss_present"] is True
        assert check["lifecycle_invariants_hold"] is True
        if direction == "buy":
            assert check["stop_loss"] < check["entry"] < check["take_profit"]
        else:
            assert check["take_profit"] < check["entry"] < check["stop_loss"]


def test_pipeline_rejects_invalid_market_data() -> None:
    result = _evaluate_pipeline(
        _candles(corrupt=True), symbol="R_75", balance=10_000.0, timeframe=Timeframe.H1
    )

    assert result["status"] == "MARKET_DATA_INVALID"
    assert result["market_data_valid"] is False
    assert "plan" not in result


def test_pipeline_requires_a_meaningful_candle_window() -> None:
    result = _evaluate_pipeline(
        _candles(10), symbol="R_75", balance=10_000.0, timeframe=Timeframe.H1
    )

    assert result["status"] == "INSUFFICIENT_CLOSED_CANDLES"


def test_pipeline_excludes_the_still_forming_candle() -> None:
    candles = _candles(120)
    result = _evaluate_pipeline(
        candles, symbol="R_75", balance=10_000.0, timeframe=Timeframe.H1
    )

    assert result["candles_returned"] == 120
    assert result["candles_closed"] == 119
    assert result["last_candle"] == candles[-2].time.isoformat()


# --- authorization gate and selection persistence -------------------------


async def test_run_requires_explicit_authorization(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(verification._AUTHORIZATION_ENV, raising=False)
    constructed = _install_gateway(
        monkeypatch,
        FakeGateway(
            candles=_candles(),
            account=AccountInfo(account_id="VRTC1", balance=1.0, currency="USD"),
        ),
    )

    assert await run(_args(broker="deriv")) == 2
    assert "BLOCKED" in capsys.readouterr().out
    assert constructed == []


async def test_run_blocks_when_broker_execution_is_enabled(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv(verification._AUTHORIZATION_ENV, "1")
    stub_settings.broker_execution_enabled = True
    monkeypatch.setattr(verification, "Settings", lambda: stub_settings)
    constructed = _install_gateway(
        monkeypatch,
        FakeGateway(
            candles=_candles(),
            account=AccountInfo(account_id="VRTC1", balance=1.0, currency="USD"),
        ),
    )

    assert await run(_args(broker="deriv")) == 2
    assert "EXECUTION_ENABLED" in capsys.readouterr().out
    assert constructed == []


async def test_run_persists_then_restores_broker_selection(
    stub_settings: StubSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setenv(verification._AUTHORIZATION_ENV, "1")
    monkeypatch.setattr(verification, "Settings", lambda: stub_settings)
    gateway = FakeGateway(
        candles=_candles(),
        account=AccountInfo(account_id="VRTC00008175", balance=100.0, currency="USD"),
    )
    _install_gateway(monkeypatch, gateway)
    json_out = tmp_path / "verification.json"

    exit_code = await run(_args(broker="deriv", json_out=str(json_out)))

    assert exit_code == 0
    store = BrokerSelectionStore(stub_settings.broker_selection_store_path)
    assert store.get_selected_broker() == "mt5"
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["execution_enabled"] is False
    assert payload["selection_before_run"] is None
    assert payload["selection_after_run"] == "mt5"
    assert payload["reports"][0]["outcome"] == "VERIFIED_READ_ONLY"
    assert "BLOCKED" not in capsys.readouterr().out


async def test_run_can_keep_the_verified_selection(
    stub_settings: StubSettings, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv(verification._AUTHORIZATION_ENV, "1")
    monkeypatch.setattr(verification, "Settings", lambda: stub_settings)
    gateway = FakeGateway(
        candles=_candles(),
        account=AccountInfo(account_id="VRTC00008175", balance=100.0, currency="USD"),
    )
    _install_gateway(monkeypatch, gateway)

    assert await run(_args(broker="deriv", keep_selection=True)) == 0
    store = BrokerSelectionStore(stub_settings.broker_selection_store_path)
    assert store.get_selected_broker() == "deriv"
