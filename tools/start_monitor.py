"""Launch only the isolated read-only owner monitor; no trading configuration."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = json.loads((ROOT / "state/monitor-config.json").read_text())
    env = os.environ.copy()
    for key in ("issuer", "audience", "email"):
        env["JQE_MONITOR_" + key.upper()] = config[key]
    env["JQE_MONITOR_SERVICE_CLIENT_ID"] = config.get("service_client_id", "")
    subprocess.run([sys.executable, "-m", "uvicorn", "api.monitor_relay:create_app", "--factory",
                    "--host", "127.0.0.1", "--port", "8766", "--no-access-log", "--no-proxy-headers"],
                   cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
