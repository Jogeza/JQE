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
