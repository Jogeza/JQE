"""Reproducible campaign provenance and immutable evidence."""

from dataclasses import replace
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.research import get_campaign_provenance
from research import campaign_provenance as provenance
from research.campaign_provenance import (
    CampaignEvidence, CampaignEvidenceStore, build_fingerprint, fingerprint_diff,
)


def fingerprint(tmp_path: Path, monkeypatch, **config):
    if not (tmp_path / "source.py").exists():
        (tmp_path / "source.py").write_text("authority = 1\n", encoding="utf-8")
    monkeypatch.setattr(provenance, "SOURCE_AUTHORITIES", {"strategy": ("source.py",)})
    monkeypatch.setattr(provenance, "dependency_versions", lambda: {"python": "3.test", "pandas": "test"})
    return build_fingerprint(
        root=tmp_path, git_commit="abc", strategy_id="strategy.pipeline.generate_trading_signal",
        effective_config={"risk_percent": "1", "max_open_positions": 1, **config},
        dataset_identity="sha256:data", symbol="XAUUSD", timeframe="M15",
        first_candle="2026-01-01T00:00:00+00:00", last_candle="2026-01-02T00:00:00+00:00",
        requested_observations=10, safety_context={"kind": "HISTORICAL_RESEARCH"},
    )


def test_canonical_fingerprint_is_deterministic_and_secret_free(tmp_path, monkeypatch):
    first = fingerprint(tmp_path, monkeypatch)
    second = fingerprint(tmp_path, monkeypatch)
    assert first == second
    encoded = provenance.canonical_json(first.payload())
    assert "token" not in encoded.lower() and "credential" not in encoded.lower()


def test_fingerprint_changes_with_source_config_warmup_and_dependencies(tmp_path, monkeypatch):
    first = fingerprint(tmp_path, monkeypatch)
    changed_config = fingerprint(tmp_path, monkeypatch, max_open_positions=2)
    assert first.research_fingerprint_sha256 != changed_config.research_fingerprint_sha256
    assert "effective_config.max_open_positions" in fingerprint_diff(first, changed_config)
    changed_warmup = replace(first, warmup_semantics="different", research_fingerprint_sha256="changed")
    assert "warmup_semantics" in fingerprint_diff(first, changed_warmup)
    (tmp_path / "source.py").write_text("authority = 2\n", encoding="utf-8")
    changed_source = fingerprint(tmp_path, monkeypatch)
    assert first.source_hashes != changed_source.source_hashes
    monkeypatch.setattr(provenance, "dependency_versions", lambda: {"python": "other", "pandas": "test"})
    changed_dependency = build_fingerprint(
        root=tmp_path, git_commit="abc", strategy_id="strategy.pipeline.generate_trading_signal",
        effective_config={"risk_percent": "1", "max_open_positions": 1}, dataset_identity="sha256:data",
        symbol="XAUUSD", timeframe="M15", first_candle="a", last_candle="b",
        requested_observations=10, safety_context={"kind": "HISTORICAL_RESEARCH"},
    )
    assert changed_source.dependency_fingerprint != changed_dependency.dependency_fingerprint


def test_append_finalize_immutability_and_fingerprint_mismatch(tmp_path, monkeypatch):
    first = fingerprint(tmp_path, monkeypatch)
    store = CampaignEvidenceStore(tmp_path / "evidence.sqlite3")
    store.start("session", first)
    store.append("session", CampaignEvidence("1", "CANDIDATE", "candidate", "now", {"candidate_status": "CONFIRMATION_PENDING"}))
    assert store.events("session")[0]["facts"]["candidate_status"] == "CONFIRMATION_PENDING"
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        store.start("session", fingerprint(tmp_path, monkeypatch, max_open_positions=2))
    store.finalize("session")
    with pytest.raises(ValueError, match="immutable"):
        store.append("session", CampaignEvidence("2", "RISK", "candidate", "now", {}))
    with pytest.raises(ValueError, match="immutable"):
        store.start("session", first)


def test_read_only_provenance_api_marks_legacy_and_exposes_v2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "state" / "paper_campaigns"
    folder.mkdir(parents=True)
    (folder / "old.json").write_text(json.dumps({"session": {"dataset_identity": "old", "git_commit": "abc"}}))
    assert get_campaign_provenance("old.json")["provenance_status"] == "PROVENANCE_INCOMPLETE"
    (folder / "v2.json").write_text(json.dumps({
        "provenance_status": "PROVENANCE_COMPLETE", "research_fingerprint": {
            "schema_version": 1, "research_fingerprint_sha256": "hash",
            "dataset_identity": "data", "git_commit": "def",
        }}))
    assert get_campaign_provenance("v2.json")["research_fingerprint_sha256"] == "hash"
    with pytest.raises(HTTPException):
        get_campaign_provenance("../old.json")
