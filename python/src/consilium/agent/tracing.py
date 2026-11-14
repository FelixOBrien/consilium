"""No-op turn tracer.

SKO-285 replaces the bodies with MLflow spans. This seam records only
non-clinical metadata: case id, tool name, a short summary, counts, duration
and token totals. Report text and patient fields never go in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TraceRecord:
    kind: str
    case_id: str | None = None
    tool: str | None = None
    summary: str | None = None
    result_count: int | None = None
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class _Span:
    tracer: TurnTracer
    kind: str
    tool: str | None
    started: float = field(default_factory=time.perf_counter)

    def end(
        self,
        *,
        summary: str,
        result_count: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        elapsed = max(0, int((time.perf_counter() - self.started) * 1000))
        self.tracer.records.append(
            TraceRecord(
                kind=self.kind,
                case_id=self.tracer.case_id,
                tool=self.tool,
                summary=summary,
                result_count=result_count,
                duration_ms=elapsed,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )


@dataclass
class TurnTracer:
    """In-memory no-op. Safe to keep on in production until MLflow lands."""

    records: list[TraceRecord] = field(default_factory=list)
    case_id: str | None = None

    def start_turn(self, *, case_id: str) -> None:
        self.case_id = case_id
        self.records.append(TraceRecord(kind="turn", case_id=case_id))

    def start_model_span(self) -> _Span:
        return _Span(self, "model", None)

    def start_tool_span(self, *, tool: str) -> _Span:
        return _Span(self, "tool", tool)
