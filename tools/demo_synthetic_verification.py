"""Opt-in, read-only DEMO synthetic-index acceptance verification.

Runs the Stage 6 acceptance flow against a real demo broker using a
broker-confirmed synthetic index. The gateway is wrapped so that
``submit_order`` raises and is counted, which makes an order submission
structurally impossible from this tool.

Authorize explicitly before running::

    set JQE_RUN_DEMO_VERIFICATION=1
    D:\\JQE\\venv\\Scripts\\python.exe tools/demo_synthetic_verification.py --broker all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from broker.base import BrokerGateway
from broker.demo_guard import DEFAULT_BROKER_EVIDENCE_PATH
from broker.factory import get_gateway
from broker.types import Candle, Timeframe, TIMEFRAME_SECONDS
from config.settings import Settings
from core.data_validator import validate_market_data
from core.indicators import calculate_indicators
from core.regime import detect_regime
from data.broker_selection import BrokerSelectionStore
from intelligence.trade_plan import TradePlanBuilder
from risk.risk_controller import approve_trade, get_reconciled_daily_state, reconcile_daily_history
from strategy.pipeline import generate_trading_signal

_AUTHORIZATION_ENV = "JQE_RUN_DEMO_VERIFICATION"
_WELTRADE_SYNTHETIC_TOKENS = ("VOL", "PAINX", "GAINX", "TRENDX", "FIBOX", "QUADX", "BOOM", "CRASH")
_DERIV_SYNTHETIC_MARKET = "synthetic_index"


class ReadOnlyGateway:
    """Broker gateway wrapper that makes order submission impossible."""

    def __init__(self, inner: BrokerGateway) -> None:
        self._inner = inner
        self.submission_attempts = 0

    @property
    def inner(self) -> BrokerGateway:
        return self._inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def submit_order(self, order: Any) -> Any:
        self.submission_attempts += 1
        raise AssertionError(
            "demo synthetic verification is read-only; submit_order must never be called"
        )

    async def __aenter__(self) -> "ReadOnlyGateway":
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return bool(await self._inner.__aexit__(exc_type, exc, traceback))


@dataclass
class StepResult:
    step: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerVerificationReport:
    broker: str
    started_at: str
    finished_at: str | None = None
    outcome: str = "NOT_RUN"
    blocker: str | None = None
    steps: list[StepResult] = field(default_factory=list)

    def record(self, step: str, outcome: str, **detail: Any) -> None:
        self.steps.append(StepResult(step=step, status=outcome, detail=detail))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mask(value: str | None) -> str:
    if not value:
        return "UNAVAILABLE"
    return f"******{value[-4:]}"


def _is_weltrade_synthetic(name: str) -> bool:
    upper = name.upper()
    return any(token in upper for token in _WELTRADE_SYNTHETIC_TOKENS)


def _closed_candles(candles: list[Candle], timeframe: Timeframe) -> list[Candle]:
    now = datetime.now(timezone.utc)
    duration = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    return [candle for candle in candles if candle.time + duration <= now]


def _latest_demo_guard_evidence(broker_keys: tuple[str, ...]) -> dict[str, Any]:
    path = Path(DEFAULT_BROKER_EVIDENCE_PATH)
    if not path.is_file():
        return {"status": "NO_EVIDENCE_STORE"}
    import sqlite3

    placeholders = ", ".join("?" for _ in broker_keys)
    try:
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                f"""SELECT broker, account_id, status, verified_at, checked_field, observed_value
                    FROM broker_account_verifications WHERE broker IN ({placeholders})
                    ORDER BY id DESC LIMIT 1""",
                broker_keys,
            ).fetchone()
    except Exception as exc:  # pragma: no cover - diagnostic only
        return {"status": "EVIDENCE_UNREADABLE", "reason": str(exc)}
    if row is None:
        return {"status": "NO_EVIDENCE_FOR_BROKER", "queried_broker_keys": list(broker_keys)}
    return {
        "evidence_broker_key": row[0],
        "account_id_masked": _mask(row[1]),
        "status": row[2],
        "verified_at": row[3],
        "checked_field": row[4],
        "observed_value": row[5],
    }


async def _discover_deriv_symbols(settings: Settings) -> list[dict[str, Any]]:
    """Return synthetic-index symbols from the broker's own active_symbols feed."""
    from broker.deriv_public_data import DerivPublicMarketData

    source = DerivPublicMarketData(
        app_id=settings.deriv_app_id, endpoint=settings.deriv_public_endpoint
    )
    await source.connect()
    try:
        payload = await source.get_active_symbols()
    finally:
        await source.disconnect()

    discovered: list[dict[str, Any]] = []
    for item in payload.get("active_symbols") or ():
        if not isinstance(item, dict) or item.get("market") != _DERIV_SYNTHETIC_MARKET:
            continue
        symbol = item.get("symbol") or item.get("underlying_symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            continue
        discovered.append(
            {
                "symbol": symbol.strip(),
                "display_name": item.get("display_name") or item.get("underlying_symbol_name"),
                "submarket": item.get("submarket"),
                "exchange_is_open": item.get("exchange_is_open"),
            }
        )
    discovered.sort(key=lambda entry: entry["symbol"])
    return discovered


def _discover_weltrade_symbols() -> list[dict[str, Any]]:
    """Return synthetic symbols from the connected Weltrade MT5 terminal."""
    import MetaTrader5 as mt5

    discovered: list[dict[str, Any]] = []
    for item in mt5.symbols_get() or ():
        name = str(getattr(item, "name", "")).strip()
        if not name or not _is_weltrade_synthetic(name):
            continue
        discovered.append(
            {
                "symbol": name,
                "description": getattr(item, "description", None),
                "path": getattr(item, "path", None),
                "visible": bool(getattr(item, "visible", False)),
            }
        )
    discovered.sort(key=lambda entry: entry["symbol"])
    return discovered


def _evaluate_pipeline(
    candles: list[Candle], *, symbol: str, balance: float, timeframe: Timeframe
) -> dict[str, Any]:
    closed = _closed_candles(candles, timeframe)
    result: dict[str, Any] = {
        "candles_returned": len(candles),
        "candles_closed": len(closed),
        "first_candle": closed[0].time.isoformat() if closed else None,
        "last_candle": closed[-1].time.isoformat() if closed else None,
    }
    result["feed_lag_minutes"] = (
        round(
            (
                datetime.now(timezone.utc)
                - (closed[-1].time + timedelta(seconds=TIMEFRAME_SECONDS[timeframe]))
            ).total_seconds()
            / 60,
            1,
        )
        if closed
        else None
    )
    if len(closed) < 60:
        result["status"] = "INSUFFICIENT_CLOSED_CANDLES"
        return result

    df = pd.DataFrame(
        [
            {
                "time": candle.time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            }
            for candle in closed
        ]
    )
    result["market_data_valid"] = bool(validate_market_data(df))
    if not result["market_data_valid"]:
        result["status"] = "MARKET_DATA_INVALID"
        return result

    df = calculate_indicators(df)
    regime = detect_regime(df)
    signal = generate_trading_signal(df, symbol, regime=regime)
    latest = df.iloc[-1]
    result["regime"] = str(regime)
    result["signal"] = signal.get("signal")
    result["confidence"] = signal.get("confidence")

    risk = approve_trade(
        {"signal": signal.get("signal"), "confidence": signal.get("confidence")},
        df,
        balance=balance,
        enforce_limits=True,
    )
    result["risk_approved"] = bool(risk.get("approved"))
    result["risk_reason"] = str(risk.get("reason"))
    result["risk_reason_code"] = (
        risk["reason_code"].value
        if getattr(risk.get("reason_code"), "value", None)
        else risk.get("reason_code")
    )
    daily_loss, daily_count, max_daily_loss, max_daily_trades = get_reconciled_daily_state()
    result["daily_state"] = {
        "daily_loss_percent": daily_loss,
        "daily_trade_count": daily_count,
        "max_daily_loss_percent": max_daily_loss,
        "max_daily_trades": max_daily_trades,
    }

    builder = TradePlanBuilder(atr_sl_multiplier=2.0, target_rr=2.0)
    intelligence = dict(signal.get("intelligence") or {})
    if not any(key in intelligence for key in ("atr", "ATR", "ATR_14")):
        intelligence["atr"] = latest.get("ATR", latest.get("ATR_14"))

    plan = builder.build(
        symbol=symbol,
        intelligence=intelligence,
        signal_dict=signal,
        price=float(latest["close"]),
    )
    result["plan"] = {
        "signal": plan.signal,
        "entry": plan.entry,
        "stop_loss": plan.stop_loss,
        "take_profit": plan.take_profit,
        "risk_reward": plan.risk_reward,
        "is_valid": plan.is_valid(),
        "invalidation": plan.invalidation,
        "warnings": list(plan.warnings),
    }

    # Builder invariant self-check on the same real broker prices. The direction
    # is forced purely to exercise the stop-loss/lifecycle math; it is not a
    # broker signal and is never routed anywhere.
    for direction in ("BUY", "SELL"):
        forced = builder.build(
            symbol=symbol,
            intelligence=intelligence,
            signal_dict={**signal, "signal": direction},
            price=float(latest["close"]),
        )
        ordered = (
            forced.stop_loss is not None
            and forced.entry is not None
            and forced.take_profit is not None
            and (
                forced.stop_loss < forced.entry < forced.take_profit
                if direction == "BUY"
                else forced.take_profit < forced.entry < forced.stop_loss
            )
        )
        result[f"invariant_self_check_{direction.lower()}"] = {
            "entry": forced.entry,
            "stop_loss": forced.stop_loss,
            "take_profit": forced.take_profit,
            "stop_loss_present": forced.stop_loss is not None,
            "lifecycle_invariants_hold": bool(ordered),
        }
    result["status"] = "PIPELINE_EXECUTED"
    return result


async def _verify_deriv(settings: Settings, args: argparse.Namespace) -> BrokerVerificationReport:
    report = BrokerVerificationReport(
        broker="deriv", started_at=datetime.now(timezone.utc).isoformat()
    )
    if not settings.deriv_api_token or not settings.deriv_options_account_id:
        report.outcome = "BLOCKED"
        report.blocker = "Deriv demo credentials are not configured"
        report.record("1-select", "BLOCKED", reason=report.blocker)
        return report
    if settings.deriv_expected_environment != "demo":
        report.outcome = "BLOCKED"
        report.blocker = "JQE_DERIV_EXPECTED_ENVIRONMENT is not 'demo'"
        report.record("1-select", "BLOCKED", reason=report.blocker)
        return report

    async with _connected(report, settings, "deriv") as gateway:
        if gateway is None:
            return report
        account = await gateway.get_account_info()
        identity = getattr(gateway.inner, "account_identity", None)
        report.record(
            "4-demo-identity",
            "PASSED" if getattr(gateway.inner, "_demo_verified", False) else "FAILED",
            account_id_masked=_mask(account.account_id),
            currency=account.currency,
            balance=account.balance,
            identity_state=getattr(getattr(identity, "state", None), "value", None),
            identity_environment=getattr(identity, "environment", None),
            demo_verified=bool(getattr(gateway.inner, "_demo_verified", False)),
        )
        report.record(
            "5-demo-guard-evidence", "OBSERVED", **_latest_demo_guard_evidence(("deriv",))
        )

        discovered = await _discover_deriv_symbols(settings)
        requested = args.symbol or next(
            (
                entry["symbol"]
                for entry in discovered
                if entry.get("exchange_is_open") in (1, True)
            ),
            discovered[0]["symbol"] if discovered else "",
        )
        report.record(
            "6-symbol-discovery",
            "PASSED" if requested else "FAILED",
            discovery_source="deriv active_symbols (market=synthetic_index)",
            synthetic_symbol_count=len(discovered),
            synthetic_symbols=[entry["symbol"] for entry in discovered],
            selected_symbol=requested or None,
        )
        if not requested:
            report.outcome = "BLOCKED"
            report.blocker = "Deriv active_symbols returned no synthetic_index symbols"
            return report

        await _fetch_and_evaluate(report, gateway, requested, settings, args)
    return report


async def _verify_weltrade(settings: Settings, args: argparse.Namespace) -> BrokerVerificationReport:
    report = BrokerVerificationReport(
        broker="weltrade", started_at=datetime.now(timezone.utc).isoformat()
    )
    if not settings.weltrade_terminal_path:
        report.outcome = "BLOCKED"
        report.blocker = "JQE_WELTRADE_TERMINAL_PATH is not configured"
        report.record("1-select", "BLOCKED", reason=report.blocker)
        return report
    if not (settings.effective_weltrade_login and settings.effective_weltrade_server):
        report.outcome = "BLOCKED"
        report.blocker = "Weltrade demo login/server identity is not configured"
        report.record("1-select", "BLOCKED", reason=report.blocker)
        return report

    async with _connected(report, settings, "weltrade") as gateway:
        if gateway is None:
            return report
        account = await gateway.get_account_info()
        report.record(
            "4-demo-identity",
            "PASSED" if getattr(gateway.inner, "_demo_verified", False) else "FAILED",
            account_id_masked=_mask(account.account_id),
            server=account.server,
            currency=account.currency,
            balance=account.balance,
            trade_mode=account.trade_mode,
            demo_verified=bool(getattr(gateway.inner, "_demo_verified", False)),
        )
        report.record(
            "5-demo-guard-evidence",
            "OBSERVED",
            **_latest_demo_guard_evidence(("weltrade", "mt5")),
        )

        discovered = _discover_weltrade_symbols()
        resolver = getattr(gateway.inner, "_resolve_symbol", None)
        requested = args.symbol or (discovered[0]["symbol"] if discovered else "")
        report.record(
            "6-symbol-discovery",
            "PASSED" if requested else "FAILED",
            discovery_source="MetaTrader5 symbols_get() synthetic filter",
            synthetic_symbol_count=len(discovered),
            synthetic_symbols=[entry["symbol"] for entry in discovered],
            selected_symbol=requested or None,
            resolved_symbol=resolver(requested) if requested and resolver else None,
        )
        if not requested:
            report.outcome = "BLOCKED"
            report.blocker = "Weltrade terminal returned no recognizable synthetic symbols"
            return report

        await _fetch_and_evaluate(report, gateway, requested, settings, args)
    return report


def _select_and_construct(
    report: BrokerVerificationReport, settings: Settings, broker: str
) -> ReadOnlyGateway | None:
    """Steps 1-2: persist the selection, confirm resolution, build the gateway."""
    store = BrokerSelectionStore(settings.broker_selection_store_path)
    persisted = store.set_selected_broker(broker, reason="stage6 demo synthetic verification")
    effective = settings.effective_broker
    constructed = get_gateway(settings)
    report.record(
        "1-2-selection",
        "PASSED" if persisted == broker == effective else "FAILED",
        persisted_selection=persisted,
        effective_broker=effective,
        gateway_class=type(constructed).__name__,
    )
    if effective != broker:
        report.outcome = "BLOCKED"
        report.blocker = f"effective broker resolved to {effective!r}, expected {broker!r}"
        return None
    return ReadOnlyGateway(constructed)


@asynccontextmanager
async def _connected(
    report: BrokerVerificationReport, settings: Settings, broker: str
) -> AsyncIterator[ReadOnlyGateway | None]:
    """Steps 3 and 12: connect exactly once and always release the session."""
    gateway = _select_and_construct(report, settings, broker)
    if gateway is None:
        yield None
        return
    try:
        await gateway.__aenter__()
    except Exception as exc:
        report.record("3-connect", "FAILED", error=type(exc).__name__, reason=str(exc))
        report.outcome = "BLOCKED"
        report.blocker = f"{type(exc).__name__}: {exc}"
        yield None
        return
    connected = bool(gateway.inner.is_connected)
    report.record("3-connect", "PASSED" if connected else "FAILED", connected=connected)
    try:
        yield gateway
    finally:
        await gateway.__aexit__(None, None, None)
        released = not gateway.inner.is_connected
        report.record(
            "12-session-closed",
            "PASSED" if released else "FAILED",
            connected_after_close=not released,
            submission_attempts=gateway.submission_attempts,
        )


async def _fetch_and_evaluate(
    report: BrokerVerificationReport,
    gateway: ReadOnlyGateway,
    symbol: str,
    settings: Settings,
    args: argparse.Namespace,
) -> None:
    timeframe = Timeframe(args.timeframe)
    try:
        candles = await gateway.get_candles(symbol, timeframe, args.count)
    except Exception as exc:
        report.record("7-candles", "FAILED", symbol=symbol, error=type(exc).__name__, reason=str(exc))
        report.outcome = "BLOCKED"
        report.blocker = f"candle retrieval failed for {symbol}: {type(exc).__name__}: {exc}"
        return
    report.record(
        "7-candles",
        "PASSED" if candles else "FAILED",
        symbol=symbol,
        timeframe=timeframe.value,
        requested=args.count,
        returned=len(candles),
        first=candles[0].time.isoformat() if candles else None,
        last=candles[-1].time.isoformat() if candles else None,
    )
    if not candles:
        report.outcome = "BLOCKED"
        report.blocker = f"broker returned no candles for {symbol}"
        return

    account = await gateway.get_account_info()
    try:
        history_end = datetime.now(timezone.utc)
        history = await gateway.get_trade_history_snapshot(
            start=datetime.combine(history_end.date(), datetime.min.time(), tzinfo=timezone.utc),
            end=history_end,
            count=500,
        )
        reconcile_daily_history(history.trades, balance=account.balance)
        history_state = {"available": True, "trades": len(history.trades)}
    except Exception as exc:
        history_state = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    pipeline = _evaluate_pipeline(
        candles, symbol=symbol, balance=account.balance, timeframe=timeframe
    )
    pipeline["daily_history"] = history_state
    report.record("8-10-pipeline", pipeline.pop("status", "UNKNOWN"), **pipeline)
    report.record(
        "11-no-submission",
        "PASSED" if gateway.submission_attempts == 0 else "FAILED",
        submission_attempts=gateway.submission_attempts,
        broker_execution_enabled=settings.broker_execution_enabled,
    )


def _finalize(report: BrokerVerificationReport) -> BrokerVerificationReport:
    report.finished_at = datetime.now(timezone.utc).isoformat()
    if report.outcome == "NOT_RUN":
        failed = [step.step for step in report.steps if step.status == "FAILED"]
        report.outcome = "FAILED" if failed else "VERIFIED_READ_ONLY"
    return report


async def _run(broker: str, settings: Settings, args: argparse.Namespace) -> BrokerVerificationReport:
    if broker == "deriv":
        report = await _verify_deriv(settings, args)
    elif broker == "weltrade":
        report = await _verify_weltrade(settings, args)
    else:  # pragma: no cover - argparse restricts choices
        raise ValueError(f"unsupported broker {broker!r}")
    return _finalize(report)


async def run(args: argparse.Namespace) -> int:
    if os.environ.get(_AUTHORIZATION_ENV) != "1":
        print(f"BLOCKED: set {_AUTHORIZATION_ENV}=1 to authorize this read-only demo verification")
        return 2
    settings = Settings()
    if settings.broker_execution_enabled:
        print("BLOCKED: JQE_BROKER_EXECUTION_ENABLED must remain false for this verification")
        return 2

    store = BrokerSelectionStore(settings.broker_selection_store_path)
    previous = store.get_selected_broker()
    targets = ["deriv", "weltrade"] if args.broker == "all" else [args.broker]
    reports: list[BrokerVerificationReport] = []
    restore_error: str | None = None
    try:
        for broker in targets:
            reports.append(await _run(broker, settings, args))
    finally:
        if not args.keep_selection:
            # Never delete the store file: on Windows the SQLite handle can
            # still be locked. Restoring the configured broker reproduces the
            # pre-run effective resolution exactly.
            restore_to = previous if previous is not None else settings.broker
            try:
                store.set_selected_broker(
                    restore_to, reason="restored after demo synthetic verification"
                )
            except Exception as exc:  # pragma: no cover - diagnostic only
                restore_error = f"{type(exc).__name__}: {exc}"

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_enabled": settings.broker_execution_enabled,
        "selection_before_run": previous,
        "selection_after_run": store.get_selected_broker(),
        "restore_error": restore_error,
        "reports": [report.to_dict() for report in reports],
    }
    text = json.dumps(payload, indent=2, default=str)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    return 0 if all(report.outcome == "VERIFIED_READ_ONLY" for report in reports) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", choices=("deriv", "weltrade", "all"), default="all")
    parser.add_argument("--symbol", default=None, help="broker-confirmed symbol override")
    parser.add_argument("--timeframe", default="H1", choices=[tf.value for tf in Timeframe])
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--json-out", default=None)
    parser.add_argument(
        "--keep-selection",
        action="store_true",
        help="leave the verified broker persisted instead of restoring the prior selection",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
