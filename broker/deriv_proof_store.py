"""Durable storage for validated Deriv proof-registry and revocation state.

This module persists authority that was established elsewhere.  It cannot admit
proofs, authorize risk, construct a gateway, or submit broker requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import json
import sqlite3
from typing import Any

from broker.deriv_evidence import DerivEvidenceApplicability
from broker.deriv_financial_semantics import (
    DerivCurrencyBinding,
    DerivEquationFamily,
    DerivFinancialOperand,
    DerivFinancialOutput,
    DerivFinancialSemanticsSpecification,
    DerivFinancialUnit,
    DerivNumericDomain,
    DerivOperandRole,
    DerivOutputSemantic,
    DerivRoundingMode,
    DerivRoundingPolicy,
    DerivRoundingStage,
)
from broker.deriv_proof_registration import (
    DerivGovernanceRevocationReason,
    DerivGovernanceRevocationTarget,
    DerivProofGovernanceRevocation,
    DerivProofRegistrationEligibilityState,
    DerivProofRegistrationReason,
)
from broker.deriv_proof_registry import DerivProofRegistryEntry, DerivProofRegistryState


DERIV_PROOF_STORE_SCHEMA_VERSION = 1
_TABLES = frozenset({"deriv_proof_store_metadata", "deriv_proof_state"})


class DerivProofStoreError(RuntimeError):
    """The durable proof state is missing, malformed, conflicting, or corrupt."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _payload_hash(payload: str) -> str:
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _timestamp(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _parse_timestamp(value: Any) -> datetime:
    if type(value) is not str:
        raise ValueError("timestamp must be canonical text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    normalized = parsed.astimezone(timezone.utc)
    if value != normalized.isoformat(timespec="microseconds"):
        raise ValueError("timestamp is not canonical UTC text")
    return normalized


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else value.to_eng_string()


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("Decimal must be canonical text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Decimal text is invalid") from exc
    if not parsed.is_finite() or parsed.to_eng_string() != value:
        raise ValueError("Decimal text is not canonical and finite")
    return parsed


def _applicability_to_data(value: DerivEvidenceApplicability) -> dict[str, Any]:
    return {
        name: getattr(value, name)
        for name in value.__dataclass_fields__
    }


def _applicability_from_data(value: Any) -> DerivEvidenceApplicability:
    if type(value) is not dict or set(value) != set(DerivEvidenceApplicability.__dataclass_fields__):
        raise ValueError("applicability payload is malformed")
    return DerivEvidenceApplicability(**value)


def _output_to_data(value: DerivFinancialOutput | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "semantic": value.semantic.value,
        "unit": value.unit.value,
        "currency_binding": value.currency_binding.value,
        "explicit_currency": value.explicit_currency,
        "signed": value.signed,
        "zero_allowed": value.zero_allowed,
    }


def _output_from_data(value: Any) -> DerivFinancialOutput | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != {
        "semantic", "unit", "currency_binding", "explicit_currency", "signed", "zero_allowed"
    }:
        raise ValueError("financial output payload is malformed")
    return DerivFinancialOutput(
        semantic=DerivOutputSemantic(value["semantic"]),
        unit=DerivFinancialUnit(value["unit"]),
        currency_binding=DerivCurrencyBinding(value["currency_binding"]),
        explicit_currency=value["explicit_currency"],
        signed=value["signed"],
        zero_allowed=value["zero_allowed"],
    )


def _semantics_to_data(value: DerivFinancialSemanticsSpecification | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "schema_version": value.schema_version,
        "semantic_id": value.semantic_id,
        "semantic_version": value.semantic_version,
        "equation_family": value.equation_family.value,
        "equation_identity_hash": value.equation_identity_hash,
        "operands": [
            {
                "operand_id": item.operand_id,
                "semantic_id": item.semantic_id,
                "unit": item.unit.value,
                "role": item.role.value,
                "position": item.position,
                "required": item.required,
                "domain": item.domain.value,
                "lower_bound": _decimal(item.lower_bound),
                "upper_bound": _decimal(item.upper_bound),
                "zero_allowed": item.zero_allowed,
                "currency_bound": item.currency_bound,
                "multiplier_bound": item.multiplier_bound,
            }
            for item in value.operands
        ],
        "output": _output_to_data(value.output),
        "rounding": {
            "required": value.rounding.required,
            "precision": value.rounding.precision,
            "mode": value.rounding.mode.value,
            "stage": value.rounding.stage.value,
        },
        "domain_constraint_ids": list(value.domain_constraint_ids),
        "applicability": _applicability_to_data(value.applicability),
        "contract_family": value.contract_family,
        "quantity_basis_semantic_id": value.quantity_basis_semantic_id,
        "stop_semantic_id": value.stop_semantic_id,
        "multiplier_semantic_id": value.multiplier_semantic_id,
        "take_profit_output": _output_to_data(value.take_profit_output),
        "take_profit_semantic_id": value.take_profit_semantic_id,
        "maximum_loss_output": _output_to_data(value.maximum_loss_output),
        "maximum_loss_semantic_id": value.maximum_loss_semantic_id,
        "allowed_multiplier_values": [_decimal(item) for item in value.allowed_multiplier_values],
    }


def _semantics_from_data(value: Any) -> DerivFinancialSemanticsSpecification | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise ValueError("financial semantics payload is malformed")
    operands = tuple(
        DerivFinancialOperand(
            operand_id=item["operand_id"], semantic_id=item["semantic_id"],
            unit=DerivFinancialUnit(item["unit"]), role=DerivOperandRole(item["role"]),
            position=item["position"], required=item["required"],
            domain=DerivNumericDomain(item["domain"]),
            lower_bound=_parse_decimal(item["lower_bound"]),
            upper_bound=_parse_decimal(item["upper_bound"]),
            zero_allowed=item["zero_allowed"], currency_bound=item["currency_bound"],
            multiplier_bound=item["multiplier_bound"],
        )
        for item in value["operands"]
    )
    rounding = value["rounding"]
    result = DerivFinancialSemanticsSpecification(
        schema_version=value["schema_version"], semantic_id=value["semantic_id"],
        semantic_version=value["semantic_version"],
        equation_family=DerivEquationFamily(value["equation_family"]),
        equation_identity_hash=value["equation_identity_hash"], operands=operands,
        output=_output_from_data(value["output"]),
        rounding=DerivRoundingPolicy(
            required=rounding["required"], precision=rounding["precision"],
            mode=DerivRoundingMode(rounding["mode"]), stage=DerivRoundingStage(rounding["stage"]),
        ),
        domain_constraint_ids=tuple(value["domain_constraint_ids"]),
        applicability=_applicability_from_data(value["applicability"]),
        contract_family=value["contract_family"],
        quantity_basis_semantic_id=value["quantity_basis_semantic_id"],
        stop_semantic_id=value["stop_semantic_id"],
        multiplier_semantic_id=value["multiplier_semantic_id"],
        take_profit_output=_output_from_data(value["take_profit_output"]),
        take_profit_semantic_id=value["take_profit_semantic_id"],
        maximum_loss_output=_output_from_data(value["maximum_loss_output"]),
        maximum_loss_semantic_id=value["maximum_loss_semantic_id"],
        allowed_multiplier_values=tuple(_parse_decimal(item) for item in value["allowed_multiplier_values"]),
    )
    return result


def _entry_to_data(entry: DerivProofRegistryEntry) -> dict[str, Any]:
    return {
        "schema_version": entry.schema_version, "admission_id": entry.admission_id,
        "proof_id": entry.proof_id, "candidate_id": entry.candidate_id,
        "candidate_material_hash": entry.candidate_material_hash,
        "verification_decision_id": entry.verification_decision_id,
        "source_assessment_id": entry.source_assessment_id,
        "review_decision_id": entry.review_decision_id,
        "artifact_ids": list(entry.artifact_ids),
        "artifact_content_hashes": list(entry.artifact_content_hashes),
        "claim_ids": list(entry.claim_ids),
        "applicability": _applicability_to_data(entry.applicability),
        "loss_model_id": entry.loss_model_id, "loss_model_version": entry.loss_model_version,
        "evidence_source_id": entry.evidence_source_id,
        "eligibility_state": entry.eligibility_state.value,
        "eligibility_reason_codes": sorted(reason.value for reason in entry.eligibility_reason_codes),
        "admitted_by": entry.admitted_by, "admitted_at": _timestamp(entry.admitted_at),
        "valid_from": _timestamp(entry.valid_from), "valid_until": _timestamp(entry.valid_until),
        "financial_semantics": _semantics_to_data(entry.financial_semantics),
    }


def _entry_from_data(value: Any) -> DerivProofRegistryEntry:
    if type(value) is not dict:
        raise ValueError("registry entry payload is malformed")
    semantics = _semantics_from_data(value["financial_semantics"])
    entry = DerivProofRegistryEntry(
        schema_version=value["schema_version"], admission_id=value["admission_id"],
        proof_id=value["proof_id"], candidate_id=value["candidate_id"],
        candidate_material_hash=value["candidate_material_hash"],
        verification_decision_id=value["verification_decision_id"],
        source_assessment_id=value["source_assessment_id"], review_decision_id=value["review_decision_id"],
        artifact_ids=tuple(value["artifact_ids"]), artifact_content_hashes=tuple(value["artifact_content_hashes"]),
        claim_ids=tuple(value["claim_ids"]), applicability=_applicability_from_data(value["applicability"]),
        loss_model_id=value["loss_model_id"], loss_model_version=value["loss_model_version"],
        evidence_source_id=value["evidence_source_id"],
        eligibility_state=DerivProofRegistrationEligibilityState(value["eligibility_state"]),
        eligibility_reason_codes=frozenset(DerivProofRegistrationReason(item) for item in value["eligibility_reason_codes"]),
        admitted_by=value["admitted_by"], admitted_at=_parse_timestamp(value["admitted_at"]),
        valid_from=_parse_timestamp(value["valid_from"]), valid_until=_parse_timestamp(value["valid_until"]),
        financial_semantics=semantics,
    )
    if semantics is not None and semantics.material_hash != entry.candidate_material_hash:
        raise ValueError("financial semantic material hash does not match proof lineage")
    return entry


def _revocation_to_data(value: DerivProofGovernanceRevocation) -> dict[str, Any]:
    return {
        "schema_version": value.schema_version, "revocation_id": value.revocation_id,
        "target_kind": value.target_kind.value, "target_id": value.target_id,
        "reason": value.reason.value, "revoked_by": value.revoked_by,
        "revoked_at": _timestamp(value.revoked_at), "superseded_by_id": value.superseded_by_id,
    }


def _revocation_from_data(value: Any) -> DerivProofGovernanceRevocation:
    if type(value) is not dict:
        raise ValueError("revocation payload is malformed")
    return DerivProofGovernanceRevocation(
        schema_version=value["schema_version"], revocation_id=value["revocation_id"],
        target_kind=DerivGovernanceRevocationTarget(value["target_kind"]), target_id=value["target_id"],
        reason=DerivGovernanceRevocationReason(value["reason"]), revoked_by=value["revoked_by"],
        revoked_at=_parse_timestamp(value["revoked_at"]), superseded_by_id=value["superseded_by_id"],
    )


@dataclass(frozen=True, slots=True)
class DerivDurableProofState:
    registry: DerivProofRegistryState = DerivProofRegistryState()
    revocations: tuple[DerivProofGovernanceRevocation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.registry, DerivProofRegistryState):
            raise ValueError("registry is invalid")
        if type(self.revocations) is not tuple or any(
            not isinstance(item, DerivProofGovernanceRevocation) for item in self.revocations
        ):
            raise ValueError("revocations must be an immutable typed tuple")
        if self.revocations != tuple(sorted(self.revocations, key=lambda item: item.revocation_id)):
            raise ValueError("revocations must use deterministic ID ordering")
        ids = tuple(item.revocation_id for item in self.revocations)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate revocation ID is not allowed")
        targets: dict[tuple[DerivGovernanceRevocationTarget, str], DerivProofGovernanceRevocation] = {}
        for item in self.revocations:
            key = (item.target_kind, item.target_id)
            previous = targets.get(key)
            if previous is not None and (
                previous.reason is not item.reason
                or previous.superseded_by_id != item.superseded_by_id
            ):
                raise ValueError("conflicting revocation authority is not allowed")
            targets[key] = item


def _state_to_payload(state: DerivDurableProofState) -> str:
    if not isinstance(state, DerivDurableProofState):
        raise ValueError("durable proof state is invalid")
    return _canonical_json({
        "entries": [_entry_to_data(item) for item in state.registry.entries],
        "revocations": [_revocation_to_data(item) for item in state.revocations],
    })


def _state_from_payload(payload: str) -> DerivDurableProofState:
    if type(payload) is not str:
        raise ValueError("durable payload must be text")
    value = json.loads(payload)
    if type(value) is not dict or set(value) != {"entries", "revocations"}:
        raise ValueError("durable payload shape is invalid")
    state = DerivDurableProofState(
        registry=DerivProofRegistryState(tuple(_entry_from_data(item) for item in value["entries"])),
        revocations=tuple(_revocation_from_data(item) for item in value["revocations"]),
    )
    if _state_to_payload(state) != payload:
        raise ValueError("durable payload is not canonical")
    return state


class SQLiteDerivProofStore:
    """Atomic snapshot store for canonical immutable proof and revocation state."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser().resolve()
        existed = self._path.exists()
        if not existed:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._create()
        else:
            self._validate_schema()

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(f"file:{self._path.as_posix()}?mode=ro", uri=True, timeout=1.0)
        else:
            connection = sqlite3.connect(str(self._path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=1000")
        return connection

    def _create(self) -> None:
        try:
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("CREATE TABLE deriv_proof_store_metadata (singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1), schema_version INTEGER NOT NULL)")
                connection.execute("CREATE TABLE deriv_proof_state (singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1), schema_version INTEGER NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL)")
                connection.execute("INSERT INTO deriv_proof_store_metadata VALUES (1, ?)", (DERIV_PROOF_STORE_SCHEMA_VERSION,))
        except sqlite3.DatabaseError as exc:
            raise DerivProofStoreError("cannot initialize durable proof store") from exc

    def _validate_schema(self) -> None:
        try:
            with self._connect(read_only=True) as connection:
                tables = frozenset(row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"))
                if not _TABLES <= tables:
                    raise DerivProofStoreError("durable proof store schema is missing")
                rows = connection.execute("SELECT singleton_id, schema_version FROM deriv_proof_store_metadata").fetchall()
                if len(rows) != 1 or rows[0]["singleton_id"] != 1 or type(rows[0]["schema_version"]) is not int:
                    raise DerivProofStoreError("durable proof store metadata is malformed")
                if rows[0]["schema_version"] != DERIV_PROOF_STORE_SCHEMA_VERSION:
                    raise DerivProofStoreError("unsupported durable proof store schema version")
        except DerivProofStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise DerivProofStoreError("durable proof store is unreadable") from exc

    def load(self) -> DerivDurableProofState:
        self._validate_schema()
        try:
            with self._connect(read_only=True) as connection:
                rows = connection.execute("SELECT schema_version, payload, payload_hash FROM deriv_proof_state").fetchall()
            if not rows:
                return DerivDurableProofState()
            if len(rows) != 1 or rows[0]["schema_version"] != DERIV_PROOF_STORE_SCHEMA_VERSION:
                raise DerivProofStoreError("durable proof snapshot metadata is malformed")
            payload = rows[0]["payload"]
            if type(payload) is not str or rows[0]["payload_hash"] != _payload_hash(payload):
                raise DerivProofStoreError("durable proof snapshot integrity check failed")
            return _state_from_payload(payload)
        except DerivProofStoreError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, sqlite3.DatabaseError) as exc:
            raise DerivProofStoreError("durable proof snapshot is malformed") from exc

    def persist(self, state: DerivDurableProofState) -> DerivDurableProofState:
        payload = _state_to_payload(state)
        rebuilt = _state_from_payload(payload)
        current = self.load()
        current_entries = {item.proof_id: item for item in current.registry.entries}
        new_entries = {item.proof_id: item for item in rebuilt.registry.entries}
        if any(new_entries.get(key) != value for key, value in current_entries.items()):
            raise DerivProofStoreError("persisted proof authority cannot be altered or removed")
        current_revocations = {item.revocation_id: item for item in current.revocations}
        new_revocations = {item.revocation_id: item for item in rebuilt.revocations}
        if any(new_revocations.get(key) != value for key, value in current_revocations.items()):
            raise DerivProofStoreError("persisted revocation authority cannot be altered or removed")
        connection = self._connect()
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO deriv_proof_state VALUES (1, ?, ?, ?) ON CONFLICT(singleton_id) DO UPDATE SET schema_version=excluded.schema_version, payload=excluded.payload, payload_hash=excluded.payload_hash",
                (DERIV_PROOF_STORE_SCHEMA_VERSION, payload, _payload_hash(payload)),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return rebuilt
