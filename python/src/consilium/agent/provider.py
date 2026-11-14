"""Model providers for the consult loop.

`anthropic` streams the current Messages tool-use API. `databricks` is a seam
with no client yet. Tests inject a provider that yields scripted events.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from consilium.config import LlmProvider, Settings  # pragma: allowlist secret

logger = logging.getLogger(__name__)

PUBLIC_UNAVAILABLE = "The consult agent is unavailable."
_MAX_TOKENS = 1024


class AgentUnavailable(Exception):
    """The provider cannot run. `public_message` is safe to show in the UI."""

    public_message = PUBLIC_UNAVAILABLE

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderEvent:
    kind: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    content: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


class LLMProvider(Protocol):
    model_name: str

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[ProviderEvent]:
        """Yield `text` deltas, then one `end` event with tool calls and usage."""


class UnavailableProvider:
    """Raises before any token. Used when the configured provider cannot start."""

    model_name = "unavailable"

    def __init__(self, detail: str) -> None:
        self.detail = detail

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[ProviderEvent]:
        raise AgentUnavailable(self.detail)
        yield ProviderEvent(kind="end")


class DatabricksProvider:
    """Seam for `LLM_PROVIDER=databricks`. No model call is implemented."""

    model_name = "databricks"

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[ProviderEvent]:
        raise AgentUnavailable("LLM_PROVIDER=databricks is not implemented.")
        yield ProviderEvent(kind="end")


class AnthropicProvider:
    """Claude tool-use loop over `messages.stream`.

    Text is forwarded as `text_delta` events. Tool inputs are taken from the
    SDK's accumulated message, which concatenates `input_json_delta` fragments
    and parses them when the content block closes.
    """

    def __init__(self, *, api_key: str, model: str) -> None:
        self.model_name = model
        self._api_key = api_key

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[ProviderEvent]:
        from anthropic import APIConnectionError, APIStatusError, AsyncAnthropic

        client = AsyncAnthropic(api_key=self._api_key, timeout=90.0)
        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": _MAX_TOKENS,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    text = _text_delta(event)
                    if text:
                        yield ProviderEvent(kind="text", text=text)
                final = await stream.get_final_message()
        except (APIConnectionError, APIStatusError) as exc:
            status = getattr(exc, "status_code", None)
            logger.error("anthropic request failed status=%s", status)
            raise AgentUnavailable(f"anthropic status {status}") from exc
        usage = final.usage
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        logger.info(
            "consult model round model=%s input_tokens=%s output_tokens=%s",
            self.model_name,
            input_tokens,
            output_tokens,
        )
        content = _content_blocks(final.content)
        yield ProviderEvent(
            kind="end",
            tool_calls=_tool_calls(content),
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=getattr(final, "stop_reason", None),
        )


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider is LlmProvider.DATABRICKS:
        return DatabricksProvider()
    secret = settings.anthropic_api_key
    key = secret.get_secret_value().strip() if secret is not None else ""
    if not key:
        raise AgentUnavailable("ANTHROPIC_API_KEY is not set.")
    return AnthropicProvider(api_key=key, model=settings.anthropic_model)


def _text_delta(event: object) -> str:
    if getattr(event, "type", None) != "content_block_delta":
        return ""
    delta = getattr(event, "delta", None)
    if getattr(delta, "type", None) != "text_delta":
        return ""
    text = getattr(delta, "text", "")
    return text if isinstance(text, str) else ""


def _content_blocks(blocks: object) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for block in blocks if isinstance(blocks, list) else []:
        data = block.model_dump(exclude_none=True) if hasattr(block, "model_dump") else {}
        kind = data.get("type")
        if kind == "text" and data.get("text"):
            content.append({"type": "text", "text": data["text"]})
        elif kind == "tool_use":
            raw_input = data.get("input")
            content.append(
                {
                    "type": "tool_use",
                    "id": str(data.get("id") or ""),
                    "name": str(data.get("name") or ""),
                    "input": raw_input if isinstance(raw_input, dict) else {},
                }
            )
    return content


def _tool_calls(content: list[dict[str, Any]]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for block in content:
        if block.get("type") != "tool_use":
            continue
        raw = block.get("input")
        calls.append(
            ToolCall(
                id=str(block.get("id") or ""),
                name=str(block.get("name") or ""),
                arguments=raw if isinstance(raw, dict) else {},
            )
        )
    return calls
