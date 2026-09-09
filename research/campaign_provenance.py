"""Canonical provenance and append-only evidence for historical campaigns."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


FINGERPRINT_SCHEMA_VERSION = 1
CAMPAIGN_RUNNER_VERSION = 2
RELEVANT_PACKAGES = ("numpy", "pandas", "pydantic")
SOURCE_AUTHORITIES = {
    "strategy": (
        "strategy/pipeline.py", "strategy/strategy_engine.py", "strategy/signal_engine.py",
        "strategy/scoring/signal_scorer.py", "intelligence/confidence_model.py",
        "intelligence/liquidity_engine.py", "intelligence/trade_plan.py",
    ),
    "confirmation": ("research/historical_confirmation.py",),
    "features": ("strategy/features/feature_engine.py", "intelligence/momentum_engine.py", "intelligence/trend_engine.py", "intelligence/volatility_engine.py"),
    "indicators": ("core/indicators.py",),
    "regime": ("intelligence/market_regime.py",),
    "risk": ("risk/risk_controller.py", "risk/risk_engine.py", "risk/position_sizing.py"),
    "execution_policy": ("execution/policy.py",),
    "paper_lifecycle": ("execution/paper_contract.py", "execution/paper_runtime.py"),
    "configuration": ("config/settings.py",),
    "campaign_runner": ("tools/paper_campaign.py", "tools/paper_runtime.py", "research/campaign_provenance.py"),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_hash(root: Path, paths: Iterable[str]) -> str:
    payload = [
        {"path": name.replace("\\", "/"), "sha256": sha256_file(root / name)}
        for name in sorted(paths)
    ]
    return sha256_text(canonical_json(payload))


def dependency_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        **{name: importlib.metadata.version(name) for name in sorted(RELEVANT_PACKAGES)},
    }


@dataclass(frozen=True, slots=True)
class ResearchFingerprint:
    schema_version: int
    git_commit: str
    strategy_id: str
    source_hashes: Mapping[str, str]
    effective_config: Mapping[str, Any]
    effective_config_hash: str
    dependencies: Mapping[str, str]
    dependency_fingerprint: str
    dataset_identity: str
    symbol: str
    timeframe: str
    first_candle: str
    last_candle: str
    requested_observations: int
    warmup_semantics: str
    history_window_semantics: str
    dataset_order: str
    gap_policy: str
    timezone: str
    research_safety_context: Mapping[str, Any]
    campaign_runner_version: int
    research_fingerprint_sha256: str

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        result = asdict(self)
        if not include_hash:
            result.pop("research_fingerprint_sha256", None)
        return result


def build_fingerprint(
    *, root: Path, git_commit: str, strategy_id: str,
    effective_config: Mapping[str, Any], dataset_identity: str,
    symbol: str, timeframe: str, first_candle: str, last_candle: str,
    requested_observations: int, safety_context: Mapping[str, Any],
    warmup: int = 500,
) -> ResearchFingerprint:
    sources = {name: source_hash(root, paths) for name, paths in sorted(SOURCE_AUTHORITIES.items())}
    config = dict(sorted(effective_config.items()))
    dependencies = dependency_versions()
    values: dict[str, Any] = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "git_commit": git_commit,
        "strategy_id": strategy_id,
        "source_hashes": sources,
        "effective_config": config,
        "effective_config_hash": sha256_text(canonical_json(config)),
        "dependencies": dependencies,
        "dependency_fingerprint": sha256_text(canonical_json(dependencies)),
        "dataset_identity": dataset_identity,
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "first_candle": first_candle,
        "last_candle": last_candle,
        "requested_observations": requested_observations,
        "warmup_semantics": f"first_{warmup}_candles_precede_observation_1",
        "history_window_semantics": f"rolling_closed_candle_window_{warmup}",
        "dataset_order": "provider_filtered_time_ascending_first_warmup_plus_requested",
        "gap_policy": "retain_gaps_missing_expected_candle_fails_exact_lifecycle_stage",
        "timezone": "UTC",
        "research_safety_context": dict(sorted(safety_context.items())),
        "campaign_runner_version": CAMPAIGN_RUNNER_VERSION,
    }
    values["research_fingerprint_sha256"] = sha256_text(canonical_json(values))
    return ResearchFingerprint(**values)


def fingerprint_diff(left: ResearchFingerprint | Mapping[str, Any], right: ResearchFingerprint | Mapping[str, Any]) -> dict[str, Any]:
    a = left.payload() if isinstance(left, ResearchFingerprint) else dict(left)
    b = right.payload() if isinstance(right, ResearchFingerprint) else dict(right)
    result: dict[str, Any] = {}
    def visit(prefix: str, x: Any, y: Any) -> None:
        if isinstance(x, Mapping) and isinstance(y, Mapping):
            for key in sorted(set(x) | set(y)):
                visit(f"{prefix}.{key}" if prefix else str(key), x.get(key), y.get(key))
        elif x != y:
            result[prefix] = {"left": x, "right": y}
    visit("", a, b)
    return result


@dataclass(frozen=True, slots=True)
class CampaignEvidence:
    event_id: str
    event_type: str
    candidate_id: str | None
    occurred_at: str
    facts: Mapping[str, Any]


class CampaignEvidenceStore:
    """Append-only event store; finalization permanently seals a session."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS campaign(session_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,status TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS evidence(session_id TEXT NOT NULL,event_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(session_id,event_id))")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5.0)

    def start(self, session_id: str, fingerprint: ResearchFingerprint) -> None:
        payload = canonical_json(fingerprint.payload())
        with self._connect() as connection:
            row = connection.execute("SELECT fingerprint,status FROM campaign WHERE session_id=?", (session_id,)).fetchone()
            if row and row[0] != payload:
                old = json.loads(row[0])
                raise ValueError(f"research fingerprint mismatch: {canonical_json(fingerprint_diff(old, fingerprint))}")
            if row and row[1] == "COMPLETED":
                raise ValueError("completed campaign evidence is immutable")
            connection.execute("INSERT OR IGNORE INTO campaign VALUES(?,?,?)", (session_id, payload, "RUNNING"))

    def append(self, session_id: str, event: CampaignEvidence) -> None:
        with self._connect() as connection:
            row = connection.execute("SELECT status FROM campaign WHERE session_id=?", (session_id,)).fetchone()
            if not row or row[0] != "RUNNING":
                raise ValueError("campaign evidence is unavailable or immutable")
            connection.execute("INSERT INTO evidence VALUES(?,?,?)", (session_id, event.event_id, canonical_json(asdict(event))))

    def finalize(self, session_id: str) -> None:
        with self._connect() as connection:
            changed = connection.execute("UPDATE campaign SET status='COMPLETED' WHERE session_id=? AND status='RUNNING'", (session_id,)).rowcount
            if changed != 1:
                raise ValueError("campaign evidence cannot be finalized")

    def events(self, session_id: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM evidence WHERE session_id=? ORDER BY rowid", (session_id,)).fetchall()
        return tuple(json.loads(row[0]) for row in rows)
