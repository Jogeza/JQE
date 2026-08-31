"""Offline tests for non-authoritative Deriv evidence provenance."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from unittest.mock import patch

import pytest

from broker.deriv_contract_spec import (
    DerivContractSpecification,
    DerivSpecificationVerification,
    DerivSupportState,
    current_deriv_multiplier_specification,
    evaluate_deriv_quantity_capability,
)
from broker.deriv_evidence import (
    DERIV_EVIDENCE_SCHEMA_VERSION,
    DerivEvidenceApplicability,
    DerivEvidenceArtifact,
    DerivEvidenceClaim,
    DerivEvidenceClaimType,
    DerivEvidenceRegistry,
    DerivEvidenceReviewState,
)
from risk.position_sizing import authorize_execution_quantity


_FIXTURE_ARTIFACT_ID = "offline:test-fixture:deriv-evidence-v1"
_FIXTURE_HASH = "sha256:" + "a" * 64


def _claim(**changes) -> DerivEvidenceClaim:
    values = {
        "claim_id": "offline:test-fixture:claim-1",
        "artifact_id": _FIXTURE_ARTIFACT_ID,
        "claim_type": DerivEvidenceClaimType.QUANTITY_BASIS_SEMANTICS,
        "subject": "synthetic offline fixture subject",
        "value": "synthetic offline fixture value",
        "applicability": DerivEvidenceApplicability(
            broker="deriv", contract_family="OFFLINE_TEST_FIXTURE"
        ),
        "review_state": DerivEvidenceReviewState.UNREVIEWED,
    }
    values.update(changes)
    return DerivEvidenceClaim(**values)


def _artifact(**changes) -> DerivEvidenceArtifact:
    values = {
        "schema_version": DERIV_EVIDENCE_SCHEMA_VERSION,
        "artifact_id": _FIXTURE_ARTIFACT_ID,
        "source_identifier": "offline:test-fixture:source",
        "source_title": "Synthetic Offline Test Fixture",
        "source_publisher": "JQE test suite",
        "source_version": "fixture-v1",
        "recorded_date": date(2026, 9, 1),
        "content_hash": _FIXTURE_HASH,
        "claims": (_claim(),),
        "review_state": DerivEvidenceReviewState.UNREVIEWED,
    }
    values.update(changes)
    return DerivEvidenceArtifact(**values)


def _complete_offline_spec() -> DerivContractSpecification:
    """Synthetic fixture metadata; never a statement of real broker facts."""
    return DerivContractSpecification(
        contract_type="MULTUP",
        contract_availability=DerivSupportState.SUPPORTED,
        symbol="OFFLINE_TEST_FIXTURE",
        symbol_support=DerivSupportState.SUPPORTED,
        duration_requirements_id="offline:test-fixture:duration",
        quantity_basis="stake",
        account_currency="TST",
        currency_treatment_id="offline:test-fixture:currency",
        multiplier=2,
        multiplier_semantics_id="offline:test-fixture:multiplier",
        minimum_stake=1,
        stake_precision=2,
        stake_increment=0.01,
        stop_loss_semantic_id="offline:test-fixture:stop",
        supported_limit_order_fields=frozenset({"stop_loss"}),
        loss_model_id="offline:test-fixture:model",
        loss_model_version=1,
        evidence_source_id=_FIXTURE_ARTIFACT_ID,
        verification_state=DerivSpecificationVerification.VERIFIED,
    )


def test_valid_evidence_artifact_is_immutable_and_offline() -> None:
    artifact = _artifact()
    assert artifact.artifact_id == _FIXTURE_ARTIFACT_ID
    with pytest.raises(FrozenInstanceError):
        artifact.source_title = "changed"


@pytest.mark.parametrize("schema", [True, False, 1.0, "1", None])
def test_malformed_schema_rejects_bool_and_non_integer_values(schema) -> None:
    with pytest.raises(ValueError, match="strict integer"):
        _artifact(schema_version=schema)


def test_future_schema_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _artifact(schema_version=DERIV_EVIDENCE_SCHEMA_VERSION + 1)


@pytest.mark.parametrize("artifact_id", ["", "   ", None, 123])
def test_empty_whitespace_and_non_string_artifact_ids_are_rejected(artifact_id) -> None:
    with pytest.raises(ValueError, match="nonblank string"):
        _artifact(artifact_id=artifact_id)


@pytest.mark.parametrize(
    "content_hash",
    [None, "", "   ", 123, "md5:" + "a" * 32, "sha256:xyz", "a" * 64],
)
def test_malformed_hashes_are_rejected(content_hash) -> None:
    with pytest.raises(ValueError, match="sha256"):
        _artifact(content_hash=content_hash)


@pytest.mark.parametrize(
    "content_hash",
    ["sha256:" + "a" * 63, "sha256:" + "a" * 65],
)
def test_wrong_sha256_lengths_are_rejected(content_hash) -> None:
    with pytest.raises(ValueError, match="64"):
        _artifact(content_hash=content_hash)


@pytest.mark.parametrize(
    "recorded_date", ["2026-09-01", datetime(2026, 9, 1), None, 20260901]
)
def test_malformed_dates_are_rejected(recorded_date) -> None:
    with pytest.raises(ValueError, match="date"):
        _artifact(recorded_date=recorded_date)


def test_duplicate_claim_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate claim IDs"):
        _artifact(claims=(_claim(), _claim()))


def test_claim_must_bind_to_its_containing_artifact() -> None:
    with pytest.raises(ValueError, match="identity mismatch"):
        _artifact(claims=(_claim(artifact_id="offline:test-fixture:other"),))


@pytest.mark.parametrize("broker", ["mt5", "simulation", "", None, 123])
def test_claim_applicability_is_strictly_deriv_scoped(broker) -> None:
    with pytest.raises(ValueError):
        DerivEvidenceApplicability(broker=broker)


@pytest.mark.parametrize("field,value", [("symbol", ""), ("environment", []), ("account_currency", 123)])
def test_malformed_optional_applicability_metadata_is_rejected(field, value) -> None:
    with pytest.raises(ValueError, match="nonblank string"):
        DerivEvidenceApplicability(broker="deriv", **{field: value})


def test_registry_lookup_removal_and_absence_are_immutable() -> None:
    artifact = _artifact()
    empty = DerivEvidenceRegistry()
    registered = empty.register(artifact)
    assert empty.get_by_id(artifact.artifact_id) is None
    assert registered.get_by_id(artifact.artifact_id) is artifact
    assert registered.get_by_hash(artifact.content_hash) is artifact
    assert registered.remove(artifact.artifact_id).get_by_id(artifact.artifact_id) is None


def test_duplicate_artifact_id_conflict_is_rejected() -> None:
    registry = DerivEvidenceRegistry().register(_artifact())
    conflict = _artifact(content_hash="sha256:" + "b" * 64)
    with pytest.raises(ValueError, match="duplicate artifact ID"):
        registry.register(conflict)


def test_duplicate_artifact_content_is_rejected() -> None:
    registry = DerivEvidenceRegistry().register(_artifact())
    duplicate = _artifact(
        artifact_id="offline:test-fixture:other",
        claims=(_claim(artifact_id="offline:test-fixture:other"),),
    )
    with pytest.raises(ValueError, match="content hash"):
        registry.register(duplicate)


def test_reviewed_artifact_and_claims_remain_non_authoritative() -> None:
    reviewed_claim = replace(_claim(), review_state=DerivEvidenceReviewState.REVIEWED)
    artifact = _artifact(
        claims=(reviewed_claim,), review_state=DerivEvidenceReviewState.REVIEWED
    )
    registry = DerivEvidenceRegistry().register(artifact)
    assert registry.get_by_id(artifact.artifact_id) is artifact
    capability = evaluate_deriv_quantity_capability(
        _complete_offline_spec()
    )
    assert capability.stop_risk_authorizable is False
    assert "independently validated loss-model proof" in capability.missing_requirements


def test_evidence_registry_cannot_populate_proof_authority() -> None:
    registry = DerivEvidenceRegistry().register(_artifact())
    assert not hasattr(registry, "register_proof")
    assert not hasattr(registry, "authorize")
    assert evaluate_deriv_quantity_capability(
        current_deriv_multiplier_specification()
    ).stop_risk_authorizable is False


def test_evidence_cannot_produce_deriv_stake() -> None:
    DerivEvidenceRegistry().register(
        _artifact(review_state=DerivEvidenceReviewState.REVIEWED)
    )
    decision = authorize_execution_quantity(
        broker="deriv", balance=10_000, risk_percent=0.5,
        entry=100, stop_loss=92,
    )
    assert decision.quantity is None
    assert decision.risk_verifiable is False


def test_evidence_operations_construct_no_gateway_or_network_connection() -> None:
    with patch("broker.deriv_gateway.DerivGateway") as gateway, patch(
        "broker.deriv_gateway.websockets.connect"
    ) as connect:
        registry = DerivEvidenceRegistry().register(_artifact())
        assert registry.get_by_id(_FIXTURE_ARTIFACT_ID) is not None
    gateway.assert_not_called()
    connect.assert_not_called()
