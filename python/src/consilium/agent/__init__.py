"""Consult agent. Counts of reported cases come from SQL, not from the model."""

from consilium.agent.loop import MAX_TOOL_CALLS, consult_turn  # pragma: allowlist secret
from consilium.agent.provider import (  # pragma: allowlist secret
    PUBLIC_UNAVAILABLE,
    AgentUnavailable,
    build_provider,
)

__all__ = [
    "MAX_TOOL_CALLS",
    "PUBLIC_UNAVAILABLE",
    "AgentUnavailable",
    "build_provider",
    "consult_turn",
]
