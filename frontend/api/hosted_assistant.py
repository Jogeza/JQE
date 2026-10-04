"""Vercel serverless handler for the JQE AI assistant (read-only, generic mode).

Proxies chat to an OpenAI-compatible provider using OPENROUTER_API_KEY from the
environment. No workspace, broker, or account evidence is available here: the
deployed assistant runs in generic mode only. All other /api/v1 routes are
served by api/unavailable.py and fail closed.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _lib.security import SecurityError, access_for, authenticate, rpc, write_json

MODEL = os.environ.get("JQE_AI_ASSISTANT_MODEL", "inclusionai/ling-3.0-flash-sante:free")
API_BASE = os.environ.get("JQE_AI_ASSISTANT_API_BASE", "https://openrouter.ai/api/v1")
TIMEOUT = float(os.environ.get("JQE_AI_ASSISTANT_TIMEOUT_SECONDS", "30"))
MAX_TOKENS = int(os.environ.get("JQE_AI_ASSISTANT_MAX_OUTPUT_TOKENS", "2048"))

SYSTEM_PROMPT = (
    "You are JQE AI, the assistant embedded in the JQE quantitative trading "
    "platform. You run in generic mode on the hosted deployment: answer general "
    "questions about trading concepts, quantitative research methods, risk "
    "management, and the platform's architecture. You have no access to live "
    "accounts, broker state, or market data and must not imply otherwise. You "
    "cannot approve risk, broker status, or any trade execution. Be concise, "
    "factual, and never present simulated or hypothetical results as verified."
)


class handler(BaseHTTPRequestHandler):
    def _resource(self):
        return parse_qs(urlparse(self.path).query).get("resource", [""])[0]

    def _send_error(self, exc):
        write_json(self, exc.status, {"detail": exc.detail, "reason_code": exc.reason_code})

    def _session(self):
        token, _user = authenticate(self.headers)
        access = access_for(token)
        if access.get("access_granted") is not True or "ai_chat" not in access.get("feature_access", []):
            raise SecurityError(403, "AI chat is not included in current access.", "FEATURE_ACCESS_DENIED")
        return token, access

    def _provider_ready(self):
        return bool(os.environ.get("OPENROUTER_API_KEY"))

    def do_GET(self):
        if self._resource() != "status":
            write_json(self, 404, {"detail": "Not found"})
            return
        try:
            _token, access = self._session()
        except SecurityError as exc:
            return self._send_error(exc)
        ready = self._provider_ready()
        write_json(self, 200, {
            "provider": "openrouter",
            "context_mode": "generic",
            "state": "READY" if ready else "UNCONFIGURED",
            "configured": ready,
            "enabled": True,
            "healthy": ready,
            "model": MODEL,
            "daily_limit": access.get("ai_daily_limit"),
            "used_today": access.get("ai_used_today"),
            "reason_codes": [] if ready else ["ASSISTANT_PROVIDER_UNCONFIGURED"],
        })

    def do_OPTIONS(self):
        write_json(self, 405, {"detail": "Method not allowed."})

    def do_POST(self):
        if self._resource() != "chat":
            write_json(self, 404, {"detail": "Not found"})
            return
        try:
            token, _access = self._session()
        except SecurityError as exc:
            return self._send_error(exc)
        if not self._provider_ready():
            write_json(self, 503, {
                "state": "UNAVAILABLE", "answer": None,
                "generated_at": "", "model": MODEL, "context": None,
                "usage": None, "warning": "Assistant provider is not configured.",
                "reason_code": "ASSISTANT_PROVIDER_UNCONFIGURED",
            })
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            if length > 8192:
                raise ValueError("request too large")
            message = str(json.loads(self.rfile.read(length) or b"{}").get("message", "")).strip()
        except (ValueError, UnicodeDecodeError):
            message = ""
        if not message:
            write_json(self, 400, {
                "state": "UNAVAILABLE", "answer": None,
                "generated_at": "", "model": MODEL, "context": None,
                "usage": None, "warning": "Empty question.", "reason_code": "EMPTY_MESSAGE",
            })
            return
        try:
            quota = rpc(token, "jqe_consume_feature", {"p_feature": "ai_chat"})
        except SecurityError as exc:
            return self._send_error(exc)
        if not isinstance(quota, dict) or quota.get("allowed") is not True:
            write_json(self, 429, {
                "state": "LIMIT_REACHED", "answer": None, "generated_at": "",
                "model": MODEL, "context": None, "usage": None,
                "warning": "Today's AI chat limit has been reached.",
                "reason_code": "AI_DAILY_LIMIT_REACHED",
                "daily_limit": quota.get("limit") if isinstance(quota, dict) else None,
                "used_today": quota.get("used") if isinstance(quota, dict) else None,
            })
            return
        try:
            answer, usage = self._ask(message)
        except Exception:
            write_json(self, 503, {
                "state": "UNAVAILABLE", "answer": None,
                "generated_at": "", "model": MODEL, "context": None,
                "usage": None, "warning": "Assistant provider request failed.",
                "reason_code": "ASSISTANT_PROVIDER_ERROR",
            })
            return
        from datetime import datetime, timezone
        write_json(self, 200, {
            "state": "ANSWERED", "answer": answer,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": MODEL, "context": None, "usage": usage,
            "warning": None, "reason_code": None,
        })

    def _ask(self, message):
        payload = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
        }
        req = urllib.request.Request(
            f"{API_BASE}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                "User-Agent": "JQE-AI/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choices = data.get("choices", [])
        if not choices:
            raise ValueError("No choices in model response")
        text = (choices[0].get("message", {}) or {}).get("content") or ""
        if not text.strip():
            raise ValueError("Empty model response")
        usage = data.get("usage") or {}
        return text, {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }

    def log_message(self, *args):
        pass
