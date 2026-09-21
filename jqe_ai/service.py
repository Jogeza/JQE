"""Fail-closed orchestration for the stateless JQE AI assistant."""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Callable

from jqe_ai.client import AnthropicModelClient, ModelClient
from jqe_ai.context import build_context, serialize_context
from jqe_ai.models import (
    AssistantChatResponse, AssistantStatusResponse, ContextSummary, UsageSummary,
)
from jqe_ai.prompt import SYSTEM_PROMPT

FIGURE_WARNING = "Contains figures not found in the evidence"
_NUMBER = re.compile(r"(?<![A-Za-z_])-?\d+(?:\.\d+)?%?")
_TRADE_TERM = re.compile(r"\b(?:BUY|SELL|entry|stop(?:-loss)?|target)\b", re.IGNORECASE)


class AssistantUnavailable(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503) -> None:
        self.code, self.user_message, self.status_code = code, message, status_code
        super().__init__(code)


class InMemoryRateLimiter:
    """Process-local limits; all counters reset on server restart or reload."""

    def __init__(self, per_minute: int, daily: int) -> None:
        self.per_minute, self.daily = per_minute, daily
        self._minute: dict[str, deque[float]] = defaultdict(deque)
        self._daily: dict[tuple[str, str], int] = defaultdict(int)

    def check_and_record(self, key: str, now: datetime) -> None:
        seconds = now.timestamp()
        window = self._minute[key]
        while window and seconds - window[0] >= 60:
            window.popleft()
        day_key = (key, now.date().isoformat())
        if len(window) >= self.per_minute or self._daily[day_key] >= self.daily:
            raise AssistantUnavailable("ASSISTANT_RATE_LIMITED", "JQE AI request limit reached. Try again later.", 429)
        window.append(seconds)
        self._daily[day_key] += 1


def output_warning(answer: str, evidence: str, message: str) -> str | None:
    allowed = set(_NUMBER.findall(evidence + "\n" + message))
    if any(number not in allowed for number in _NUMBER.findall(answer)):
        return FIGURE_WARNING
    evidence_terms = {term.lower() for term in _TRADE_TERM.findall(evidence + "\n" + message)}
    if any(term.lower() not in evidence_terms for term in _TRADE_TERM.findall(answer)):
        return FIGURE_WARNING
    return None


class JQEAIService:
    def __init__(
        self, *, settings, projection_reader, client: ModelClient | None = None,
        limiter: InMemoryRateLimiter | None = None, clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.projection_reader = projection_reader
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._limiter = limiter or InMemoryRateLimiter(
            settings.ai_assistant_requests_per_minute, settings.ai_assistant_daily_request_limit,
        )

    def status(self) -> AssistantStatusResponse:
        configured = bool(self.settings.anthropic_api_key)
        if self.settings.ai_assistant_kill_switch:
            state, reasons = "KILLED", ["ASSISTANT_KILL_SWITCH_ACTIVE"]
        elif not self.settings.ai_assistant_enabled:
            state, reasons = "DISABLED", ["ASSISTANT_DISABLED"]
        elif not configured:
            state, reasons = "UNCONFIGURED", ["ANTHROPIC_API_KEY_MISSING"]
        else:
            state, reasons = "READY", []
        return AssistantStatusResponse(
            state=state, configured=configured, enabled=self.settings.ai_assistant_enabled,
            healthy=state == "READY", model=self.settings.ai_assistant_model, reason_codes=reasons,
        )

    def _ready_client(self) -> ModelClient:
        status = self.status()
        messages = {
            "KILLED": "JQE AI is unavailable — kill switch is active.",
            "DISABLED": "JQE AI is disabled.",
            "UNCONFIGURED": "JQE AI unavailable — API key is not configured.",
        }
        if status.state != "READY":
            raise AssistantUnavailable(status.reason_codes[0], messages[status.state])
        if self._client is None:
            try:
                self._client = AnthropicModelClient(
                    api_key=self.settings.anthropic_api_key,
                    model=self.settings.ai_assistant_model,
                    max_tokens=self.settings.ai_assistant_max_output_tokens,
                    timeout=self.settings.ai_assistant_timeout_seconds,
                )
            except Exception as exc:
                raise AssistantUnavailable("ASSISTANT_CLIENT_UNAVAILABLE", "JQE AI is temporarily unavailable. No answer was generated.") from exc
        return self._client

    async def chat(self, message: str, *, client_key: str = "local") -> AssistantChatResponse:
        if len(message) > self.settings.ai_assistant_max_message_chars:
            raise AssistantUnavailable("MESSAGE_TOO_LARGE", f"Message is too long. Limit: {self.settings.ai_assistant_max_message_chars} characters.", 422)
        client = self._ready_client()
        now = self._clock()
        self._limiter.check_and_record(client_key, now)
        try:
            bundle = build_context(
                reader=self.projection_reader.read,
                built_at=now.isoformat(), maximum_bytes=self.settings.ai_assistant_max_context_bytes,
            )
        except ValueError as exc:
            code = "CONTEXT_PRIVACY_FAILURE" if "Sensitive" in str(exc) else "CONTEXT_TOO_LARGE"
            message_text = "JQE AI is unavailable because the evidence bundle failed its privacy check." if code == "CONTEXT_PRIVACY_FAILURE" else "JQE AI is unavailable because the evidence bundle exceeded its safe limit."
            raise AssistantUnavailable(code, message_text) from exc
        summary = ContextSummary(
            overall_freshness=bundle.overall_freshness,
            stale_sources=bundle.stale_sources, unavailable_sources=bundle.unavailable_sources,
        )
        if len(bundle.unavailable_sources) == 7:
            return AssistantChatResponse(
                state="ANSWERED", answer="No Workspace evidence is available.", generated_at=now.isoformat(),
                model=self.settings.ai_assistant_model, context=summary,
            )
        encoded = serialize_context(bundle)
        try:
            result = await asyncio.wait_for(
                client.answer(system=SYSTEM_PROMPT, context=encoded, message=message),
                timeout=self.settings.ai_assistant_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise AssistantUnavailable("ASSISTANT_TIMEOUT", "JQE AI timed out. No answer was generated.", 504) from exc
        except Exception as exc:
            error_types = {base.__name__ for base in type(exc).__mro__}
            if "AuthenticationError" in error_types:
                raise AssistantUnavailable("ANTHROPIC_AUTH_FAILED", "JQE AI is unavailable — Anthropic authentication failed.") from exc
            if "APITimeoutError" in error_types:
                raise AssistantUnavailable("ASSISTANT_TIMEOUT", "JQE AI timed out. No answer was generated.", 504) from exc
            if "RateLimitError" in error_types:
                raise AssistantUnavailable("ANTHROPIC_RATE_LIMITED", "JQE AI is temporarily unavailable — Anthropic request limit reached.", 429) from exc
            if "APIConnectionError" in error_types:
                raise AssistantUnavailable("ANTHROPIC_CONNECTION_ERROR", "JQE AI is temporarily unavailable. No answer was generated.") from exc
            if "APIStatusError" in error_types:
                raise AssistantUnavailable("ANTHROPIC_STATUS_ERROR", "JQE AI is temporarily unavailable. No answer was generated.") from exc
            raise AssistantUnavailable("ASSISTANT_PROVIDER_ERROR", "JQE AI is temporarily unavailable. No answer was generated.") from exc
        answer = result.text.strip()
        if not answer or result.stop_reason not in {"end_turn", "stop_sequence"}:
            raise AssistantUnavailable("ASSISTANT_INVALID_RESPONSE", "JQE AI returned no usable answer. No answer was generated.", 502)
        return AssistantChatResponse(
            state="ANSWERED", answer=answer, generated_at=now.isoformat(),
            model=self.settings.ai_assistant_model, context=summary,
            usage=UsageSummary(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
            warning=output_warning(answer, encoded, message),
        )
