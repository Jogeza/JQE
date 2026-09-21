"""Typed contracts for the isolated, stateless JQE AI assistant."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GlossaryEntry(BaseModel):
    code: str
    meaning: str


class GlossaryBundle(BaseModel):
    version: str
    items: list[GlossaryEntry]


class ContextItem(BaseModel):
    name: str
    source: str
    observed_at: str | None = None
    age_seconds: float | None = None
    stale: bool
    available: bool
    data: dict[str, Any] = Field(default_factory=dict)


class WorkspaceContextBundle(BaseModel):
    schema_version: int = 1
    built_at: str
    overall_freshness: Literal["FRESH", "MIXED", "STALE", "UNAVAILABLE"]
    stale_sources: list[str]
    unavailable_sources: list[str]
    items: list[ContextItem]
    glossary: GlossaryBundle


class AssistantStatusResponse(BaseModel):
    state: Literal["READY", "DISABLED", "KILLED", "UNCONFIGURED", "UNAVAILABLE"]
    configured: bool
    enabled: bool
    healthy: bool
    model: str
    reason_codes: list[str] = Field(default_factory=list)


class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ContextSummary(BaseModel):
    overall_freshness: str
    stale_sources: list[str]
    unavailable_sources: list[str]


class UsageSummary(BaseModel):
    input_tokens: int
    output_tokens: int


class AssistantChatResponse(BaseModel):
    state: Literal["ANSWERED", "UNAVAILABLE"]
    answer: str | None
    generated_at: str
    model: str
    context: ContextSummary | None = None
    usage: UsageSummary | None = None
    warning: str | None = None
    reason_code: str | None = None
    message: str | None = None
