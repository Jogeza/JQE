"""Centralized demo-only account verification and execution guard.

This module provides the single authoritative gate that ensures no order or
broker session can ever be initiated or dispatched against a real-money account.
All broker gateways (Deriv, MT5, and future integrations) must pass through
this guard at session connection/authorization and immediately prior to any
order submission.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Mapping
from uuid import uuid4

from core.exceptions import UnsafeBrokerAccountError
from core.logger import logger

DEFAULT_BROKER_EVIDENCE_PATH = Path("state/broker_evidence.sqlite3")

# MT5 official constants (MetaTrader 5 Python SDK)
MT5_ACCOUNT_TRADE_MODE_DEMO = 0
MT5_ACCOUNT_TRADE_MODE_CONTEST = 1
MT5_ACCOUNT_TRADE_MODE_REAL = 2


@dataclass(frozen=True, slots=True)
class DemoAccountVerification:
    """Immutable record of an authoritative broker-returned demo check."""

    broker: str
    account_id: str
    checked_field: str
    observed_value: int
    verified_at: str
    status: str = "PASSED"

    def to_facts(self) -> dict[str, Any]:
        return {
            "broker": self.broker,
            "account_id": self.account_id,
            "checked_field": self.checked_field,
            "observed_value": self.observed_value,
            "check": self.status,
            "verified_at": self.verified_at,
        }


class DemoOnlyGuard:
    """Central fail-closed verification gate for broker accounts."""

    @staticmethod
    def assert_demo_account(
        broker: str,
        account_data: Any,
        *,
        session_id: str | None = None,
        evidence_store_path: Path | None = None,
        campaign_evidence_store: Any | None = None,
    ) -> DemoAccountVerification:
        """Verify that broker-returned account data authoritatively proves a demo account.

        Args:
            broker: Broker identifier (e.g. "deriv", "deriv_demo", "mt5", "mt5_demo").
            account_data: Broker-returned payload (dict, SDK object, or response).
            session_id: Optional tracking session ID for evidence store.
            evidence_store_path: Optional SQLite store path for verification events.
            campaign_evidence_store: Optional CampaignEvidenceStore instance.

        Returns:
            DemoAccountVerification proof if verified.

        Raises:
            UnsafeBrokerAccountError: If the account is real, contest, indeterminate,
                missing verification fields, or if an unexpected exception occurs.
        """
        if account_data is None:
            raise UnsafeBrokerAccountError(
                "Broker account data is missing; cannot verify demo status",
                broker=broker,
            )

        broker_norm = str(broker).strip().lower()
        now_utc = datetime.now(timezone.utc).isoformat()

        if broker_norm in ("deriv", "deriv_demo"):
            return DemoOnlyGuard._verify_deriv(
                account_data,
                broker=broker_norm,
                now_utc=now_utc,
                session_id=session_id,
                evidence_store_path=evidence_store_path,
                campaign_evidence_store=campaign_evidence_store,
            )

        if broker_norm in ("mt5", "mt5_demo"):
            return DemoOnlyGuard._verify_mt5(
                account_data,
                broker=broker_norm,
                now_utc=now_utc,
                session_id=session_id,
                evidence_store_path=evidence_store_path,
                campaign_evidence_store=campaign_evidence_store,
            )

        raise UnsafeBrokerAccountError(
            f"Unsupported broker {broker!r}; only verified demo gateways are authorized",
            broker=broker,
        )

    @staticmethod
    def _verify_deriv(
        account_data: Any,
        *,
        broker: str,
        now_utc: str,
        session_id: str | None,
        evidence_store_path: Path | None,
        campaign_evidence_store: Any | None,
    ) -> DemoAccountVerification:
        # Deriv WebSocket API returns an `authorize` dict containing `is_virtual` and `loginid`.
        # account_data may be either the full response dict or the inner `authorize` dict.
        data = account_data
        if isinstance(data, Mapping) and "authorize" in data and isinstance(data["authorize"], Mapping):
            data = data["authorize"]

        if isinstance(data, Mapping):
            is_virtual = data.get("is_virtual")
            account_id = str(data.get("loginid") or data.get("account_id") or "").strip()
        else:
            is_virtual = getattr(data, "is_virtual", None)
            account_id = str(getattr(data, "loginid", None) or getattr(data, "account_id", None) or "").strip()

        # Refuse to proceed unless is_virtual is exactly integer 1 (not bool, not 0, not "1", not None).
        if type(is_virtual) is not int or is_virtual != 1:
            logger.critical(
                "SECURITY ALERT: Non-demo or ambiguous Deriv account rejected: is_virtual={!r}, account={!r}",
                is_virtual,
                account_id,
            )
            raise UnsafeBrokerAccountError(
                "Deriv account is NOT authoritatively verified as DEMO/virtual (is_virtual must be 1)",
                broker="deriv",
                is_virtual=is_virtual,
                account_id=account_id,
            )

        verification = DemoAccountVerification(
            broker="deriv",
            account_id=account_id or "UNKNOWN_DERIV",
            checked_field="is_virtual",
            observed_value=1,
            verified_at=now_utc,
            status="PASSED",
        )

        DemoOnlyGuard._record_verification(
            verification,
            session_id=session_id,
            evidence_store_path=evidence_store_path,
            campaign_evidence_store=campaign_evidence_store,
        )
        return verification

    @staticmethod
    def _verify_mt5(
        account_data: Any,
        *,
        broker: str,
        now_utc: str,
        session_id: str | None,
        evidence_store_path: Path | None,
        campaign_evidence_store: Any | None,
    ) -> DemoAccountVerification:
        # MT5 SDK returns an AccountInfo namedtuple containing `trade_mode` and `login`.
        # May also be passed as a dict in tests.
        if isinstance(account_data, Mapping):
            trade_mode = account_data.get("trade_mode")
            account_id = str(account_data.get("login") or "").strip()
        else:
            trade_mode = getattr(account_data, "trade_mode", None)
            account_id = str(getattr(account_data, "login", None) or "").strip()

        # Refuse to proceed if trade_mode != 0 (e.g. REAL=2, CONTEST=1, None, bool, str)
        if type(trade_mode) is not int or trade_mode != MT5_ACCOUNT_TRADE_MODE_DEMO:
            logger.critical(
                "SECURITY ALERT: Non-demo or ambiguous MT5 account rejected: trade_mode={!r}, account={!r}",
                trade_mode,
                account_id,
            )
            raise UnsafeBrokerAccountError(
                "MT5 account is NOT authoritatively verified as DEMO (trade_mode must be 0/ACCOUNT_TRADE_MODE_DEMO)",
                broker="mt5",
                trade_mode=trade_mode,
                account_id=account_id,
            )

        verification = DemoAccountVerification(
            broker="mt5",
            account_id=account_id or "UNKNOWN_MT5",
            checked_field="trade_mode",
            observed_value=0,
            verified_at=now_utc,
            status="PASSED",
        )

        DemoOnlyGuard._record_verification(
            verification,
            session_id=session_id,
            evidence_store_path=evidence_store_path,
            campaign_evidence_store=campaign_evidence_store,
        )
        return verification

    @staticmethod
    def guard_order_submission(
        broker: str,
        account_data_provider: Callable[[], Any],
        *,
        session_id: str | None = None,
    ) -> DemoAccountVerification:
        """Assert that an order submission target is authoritatively verified as demo.

        Called immediately prior to executing any order request.
        """
        try:
            data = account_data_provider()
        except Exception as exc:
            raise UnsafeBrokerAccountError(
                "Failed to fetch account data for pre-order demo verification",
                broker=broker,
            ) from exc
        return DemoOnlyGuard.assert_demo_account(broker, data, session_id=session_id)

    @staticmethod
    def _record_verification(
        verification: DemoAccountVerification,
        *,
        session_id: str | None,
        evidence_store_path: Path | None,
        campaign_evidence_store: Any | None,
    ) -> None:
        """Persist verification evidence event and log confirmation."""
        facts = verification.to_facts()
        logger.info(
            "DemoOnlyGuard passed: broker={} account={} checked_field={} observed_value={}",
            verification.broker,
            verification.account_id,
            verification.checked_field,
            verification.observed_value,
        )

        # 1. Persist to dedicated SQLite evidence store if path configured
        store_path = evidence_store_path or DEFAULT_BROKER_EVIDENCE_PATH
        try:
            store_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(store_path, timeout=5.0) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS broker_account_verifications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT,
                        broker TEXT NOT NULL,
                        account_id TEXT NOT NULL,
                        checked_field TEXT NOT NULL,
                        observed_value INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        verified_at TEXT NOT NULL,
                        facts_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO broker_account_verifications
                    (session_id, broker, account_id, checked_field, observed_value, status, verified_at, facts_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id or "",
                        verification.broker,
                        verification.account_id,
                        verification.checked_field,
                        verification.observed_value,
                        verification.status,
                        verification.verified_at,
                        json.dumps(facts, sort_keys=True),
                    ),
                )
        except Exception as exc:
            logger.warning("Could not persist broker account verification to SQLite store: {}", exc)

        # 2. If campaign evidence store is supplied, append evidence event
        if campaign_evidence_store is not None and session_id:
            try:
                from research.campaign_provenance import CampaignEvidence

                event = CampaignEvidence(
                    event_id=f"DEMO-VERIFY-{uuid4().hex[:12]}",
                    event_type="BROKER_ACCOUNT_VERIFIED",
                    candidate_id=None,
                    occurred_at=verification.verified_at,
                    facts=facts,
                )
                campaign_evidence_store.append(session_id, event)
            except Exception as exc:
                logger.warning("Could not append verification to campaign evidence store: {}", exc)
