"""Read-only source identity for fresh-process canonical research replays."""
from pathlib import Path

from research.campaign_provenance import dependency_versions, sha256_file


def source_snapshot(root: Path | None = None) -> dict:
    root = root or Path(__file__).resolve().parents[1]
    paths = set()
    for folder in ("backtesting", "core", "strategy", "intelligence", "risk", "config", "analytics", "broker", "data"):
        paths.update(root.joinpath(folder).rglob("*.py"))
    # Hash the backtest-only arithmetic dependency without modifying execution.
    paths.update(root / name for name in (
        "execution/simulator.py", "research/campaign_provenance.py", "research/runner.py",
    ))
    return {
        "files": {path.relative_to(root).as_posix(): sha256_file(path) for path in sorted(paths)},
        "dependencies": dependency_versions(),
    }
