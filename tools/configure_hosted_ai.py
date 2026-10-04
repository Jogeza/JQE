"""Transfer the owner-approved existing assistant key to Vercel through stdin."""
from pathlib import Path
import subprocess
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
values = dotenv_values(ROOT / ".env.ai")
key = values.get("JQE_META_API_KEY")
base = values.get("JQE_META_API_BASE", "").rstrip("/")
if not key or base != "https://openrouter.ai/api/v1":
    raise SystemExit("Existing OpenRouter-compatible configuration is required.")
for name, value, sensitive in (
    ("OPENROUTER_API_KEY", key, True),
    ("JQE_AI_ASSISTANT_MODEL", values.get("JQE_AI_ASSISTANT_MODEL", ""), False),
):
    result = subprocess.run(
        ["C:/Program Files/nodejs/node.exe", "C:/Program Files/nodejs/node_modules/npm/bin/npx-cli.js",
         "--cache", str(ROOT / ".npm-cache"), "--yes", "vercel", "env", "add", name,
         "production", "--force", "--yes", "--sensitive" if sensitive else "--no-sensitive"],
        input=value.encode(), cwd=ROOT, capture_output=True,
    )
    if result.returncode:
        raise SystemExit(f"Vercel configuration failed for {name}; no secret output retained.")
    print(f"Configured {name} in Vercel Production.")
