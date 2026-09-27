"""Provider boundary; production import is lazy and tests inject a fake client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderResult:
    text: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None


class ModelClient(Protocol):
    async def answer(self, *, system: str, context: str, message: str) -> ProviderResult: ...


class AnthropicModelClient:
    def __init__(
        self, *, api_key: str, model: str, max_tokens: int, timeout: float,
        http_client=None,
    ) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(
            api_key=api_key, timeout=timeout, max_retries=0, http_client=http_client,
        )
        self._model = model
        self._max_tokens = max_tokens

    async def answer(self, *, system: str, context: str, message: str) -> ProviderResult:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"<workspace_context>{context}</workspace_context>\n"
                        f"<user_question>{message}</user_question>"
                    ),
                },
            ],
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return ProviderResult(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason,
        )


class MetaModelClient:
    """Async client for Meta Model API (Llama) and OpenAI-compatible endpoints."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str = "https://api.llama.com/v1",
        max_tokens: int = 512,
        timeout: float = 12.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._api_base = api_base.rstrip("/")
        self._max_tokens = max_tokens
        self._timeout = timeout

    async def answer(self, *, system: str, context: str, message: str) -> ProviderResult:
        import asyncio
        import json
        import urllib.error
        import urllib.request

        url = f"{self._api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "JQE-AI/1.0",
        }
        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"<workspace_context>{context}</workspace_context>\n"
                        f"<user_question>{message}</user_question>"
                    ),
                },
            ],
        }

        def _do_request() -> str:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    return resp.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                # Sanitize error to ensure api_key is never leaked
                body = exc.read().decode("utf-8", errors="replace")
                sanitized_msg = f"HTTP {exc.code}: {exc.reason}"
                raise RuntimeError(sanitized_msg) from None
            except urllib.error.URLError as exc:
                raise ConnectionError(f"Connection failed: {exc.reason}") from None

        try:
            raw_response = await asyncio.to_thread(_do_request)
            data = json.loads(raw_response)
        except Exception:
            raise

        choices = data.get("choices", [])
        if not choices:
            raise ValueError("No choices in model response")

        choice = choices[0]
        msg = choice.get("message", {})
        text = msg.get("content", "") or ""
        finish_reason = choice.get("finish_reason")

        # Map standard finish_reasons
        stop_reason = "end_turn" if finish_reason in {"stop", "end_turn", None} else finish_reason

        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        return ProviderResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=stop_reason,
        )
