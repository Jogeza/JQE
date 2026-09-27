"""Bounded offline backend validation with durable logs and JUnit summaries.

Run with the repository venv Python. No terminal session or orders are allowed.
Each group runs in a separate process and has a wall-clock deadline.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def worker(files: list[str], xml: str) -> int:
    sys.path.insert(0, str(ROOT))
    os.environ["JQE_RUN_LIVE_MT5_TESTS"] = "0"
    os.environ["JQE_RUN_LIVE_WELTRADE_TESTS"] = "0"
    import pytest
    from config.settings import Settings, settings
    # Fresh Settings() in tests must not read the operator's credential files.
    Settings.model_config["env_file"] = None
    isolated = Path(tempfile.mkdtemp(prefix="jqe-check-"))
    for name in Settings.model_fields:
        if (name.endswith("_path") or name in {"log_dir", "cache_dir"}) and not any(
            part in name for part in ("terminal", "portable")
        ):
            setattr(settings, name, isolated / name)
        if any(part in name for part in ("password", "token", "login", "server", "terminal_path")):
            if Settings.model_fields[name].default is None:
                setattr(settings, name, None)
    settings.broker_execution_enabled = False
    settings.telegram_enabled = False
    import MetaTrader5 as mt5
    from unittest.mock import patch
    from contextlib import ExitStack
    with ExitStack() as stack:
        for name in ("initialize", "login", "shutdown", "order_send"):
            stack.enter_context(patch.object(mt5, name, side_effect=RuntimeError(
                "Real MT5 calls blocked: inject an offline SDK/gateway in this test"
            )))
        return pytest.main([*files, "-vv", "--tb=long", "--color=no", "-o",
                            "faulthandler_timeout=30", f"--junitxml={xml}"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*")
    parser.add_argument("--output", default=f"reports/backend-{time.strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--size", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--xml")
    args = parser.parse_args()
    if args.worker:
        return worker(args.files, args.xml)
    output = (ROOT / args.output).resolve()
    if output.exists() and any(output.glob("group-*")):
        parser.error("Output already contains validation evidence; choose a new --output directory")
    output.mkdir(parents=True, exist_ok=True)
    files = args.files or sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_*.py"))
    # Inspect the previously unfinished tail first, then cover the whole suite.
    if not args.files:
        files.sort(key=lambda name: (Path(name).name < "test_recovery", name))
    results = []
    for offset in range(0, len(files), args.size):
        group = files[offset:offset + args.size]
        name = f"group-{offset // args.size + 1:02}"
        log, xml = output / f"{name}.log", output / f"{name}.xml"
        (output / "running.json").write_text(json.dumps({"group": name, "files": group}), encoding="utf-8")
        started = time.monotonic()
        with log.open("w", encoding="utf-8") as stream:
            try:
                run = subprocess.run([sys.executable, "-u", str(Path(__file__).resolve()),
                                      "--worker", "--xml", str(xml), *group],
                                     cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                     timeout=args.timeout)
                code = run.returncode
            except subprocess.TimeoutExpired:
                stream.write(f"\nGROUP DEADLINE EXCEEDED: {args.timeout}s\n")
                code = 124
        result = {"group": name, "files": group, "exit_code": code,
                  "seconds": round(time.monotonic() - started, 2), "log": str(log)}
        if xml.exists():
            suite = ET.parse(xml).getroot().find("testsuite")
            result.update({k: int(suite.get(k, "0")) for k in ("tests", "failures", "errors", "skipped")})
        results.append(result)
        (output / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
    totals = {key: sum(r.get(key, 0) for r in results)
              for key in ("tests", "failures", "errors", "skipped")}
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    totals["complete"] = all(r["exit_code"] in (0, 1) and "tests" in r for r in results)
    totals["groups"] = len(results)
    totals["files"] = len(files)
    (output / "totals.json").write_text(json.dumps(totals, indent=2), encoding="utf-8")
    (output / "running.json").write_text(json.dumps({"complete": True}), encoding="utf-8")
    return int(any(r["exit_code"] != 0 for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
