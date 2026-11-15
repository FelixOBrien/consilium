"""One consult turn: at most eight tool calls, then a cited answer.

Events match the API schema. `ranking` is the latest SQL result. Citations are
the case ids that survived the turn allowlist, expanded with `CaseSummary`.
A client disconnect stores the partial answer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from psycopg import Connection

from consilium.agent.postcheck import (  # pragma: allowlist secret
    AllowedCase,
    Allowlist,
    CitationSanitizer,
    citation_records,
    unlink_unknown,
)
from consilium.agent.prompt import system_prompt  # pragma: allowlist secret
from consilium.agent.provider import (  # pragma: allowlist secret
    PUBLIC_UNAVAILABLE,
    AgentUnavailable,
    LLMProvider,
    ProviderEvent,
)
from consilium.agent.tools import (  # pragma: allowlist secret
    TOOL_SCHEMAS,
    ToolContext,
    execute_tool,
    outcome_json,
)
from consilium.agent.tracing import NoopTurnTracer  # pragma: allowlist secret
from consilium.api.schemas.consult import (  # pragma: allowlist secret
    CitationsEvent,
    ConsultMessage,
    ConsultMessageCreate,
    ConsultStreamEvent,
    DoneEvent,
    ErrorEvent,
    MessageAttachments,
    PathologistRank,
    RankingEvent,
    StepEvent,
    TextEvent,
)
from consilium.db.consult import (  # pragma: allowlist secret
    expand_citation_summaries,
    finalize_assistant_message,
    get_thread,
    insert_streaming_assistant_message,
    insert_user_message,
    precedent_cases,
    thread_case_context,
)
from consilium.embed.text import TextEncoders  # pragma: allowlist secret

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8

DbFactory = Callable[[], AbstractContextManager[Connection]]


@dataclass
class _Turn:
    case_id: str
    patient_id: str
    case_count: int
    assistant_id: UUID
    allowlist: Allowlist
    history: list[ConsultMessage]
    parts: list[str] = field(default_factory=list)
    trace: list[dict[str, object]] = field(default_factory=list)
    ranking: list[PathologistRank] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    model: str | None = None
    finalized: bool = False

    @property
    def content(self) -> str:
        return "".join(self.parts)


async def consult_turn(
    *,
    db_factory: DbFactory,
    provider: LLMProvider,
    encoders: TextEncoders,
    thread_id: UUID,
    actor_id: str,
    body: ConsultMessageCreate,
    tracer: NoopTurnTracer | None = None,
) -> AsyncIterator[ConsultStreamEvent]:
    spans = tracer or NoopTurnTracer()
    turn = _begin(db_factory, thread_id, actor_id, body, spans)
    turn.model = provider.model_name
    spans.start_turn(
        case_id=turn.case_id,
        thread_id=str(thread_id),
        model=provider.model_name,
    )
    status = "complete"
    citation_count = 0
    try:
        async for event in _drive(db_factory, provider, encoders, body, turn, spans):
            yield event
        saved = _finish(db_factory, thread_id, actor_id, turn, status="complete")
        if saved is not None:
            citation_count = _citation_count(saved)
        if saved is None:
            return
        yield CitationsEvent(citations=saved.citations or [])
        if saved.ranking:
            yield RankingEvent(ranking=saved.ranking)
        yield DoneEvent(message=saved)
    except asyncio.CancelledError:
        try:
            saved = _finish(db_factory, thread_id, actor_id, turn, status="complete")
            if saved is not None:
                citation_count = _citation_count(saved)
        finally:
            raise
    except AgentUnavailable as exc:
        status = "error"
        logger.error("consult provider unavailable: %s", exc.detail)
        if not turn.content:
            turn.parts.append(PUBLIC_UNAVAILABLE)
        saved = _finish(db_factory, thread_id, actor_id, turn, status="error")
        if saved is not None:
            citation_count = _citation_count(saved)
        yield ErrorEvent(message=PUBLIC_UNAVAILABLE)
        if saved is not None:
            return
    except Exception as exc:
        status = "error"
        logger.error("consult turn failed: %s", type(exc).__name__)
        if not turn.content:
            turn.parts.append(PUBLIC_UNAVAILABLE)
        saved = _finish(db_factory, thread_id, actor_id, turn, status="error")
        if saved is not None:
            citation_count = _citation_count(saved)
        yield ErrorEvent(message=PUBLIC_UNAVAILABLE)
    finally:
        spans.end_turn(
            status=status,
            model=turn.model,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            tool_call_count=turn.tool_calls,
            citation_count=citation_count,
        )


def _citation_count(message: ConsultMessage | None) -> int:
    if message is None or not message.citations:
        return 0
    return len(message.citations)


def _begin(
    db_factory: DbFactory,
    thread_id: UUID,
    actor_id: str,
    body: ConsultMessageCreate,
    tracer: NoopTurnTracer,
) -> _Turn:
    with db_factory() as conn:
        context = thread_case_context(conn, thread_id)
        if str(context["user_id"]) != actor_id:
            from consilium.api.errors import fail  # pragma: allowlist secret

            fail(403, "forbidden", "This consult thread belongs to another pathologist.")
        case_id = str(context["case_id"])
        patient_id = str(context["patient_id"])
        case_count = int(context["case_count"])
        history = list(get_thread(conn, thread_id, actor_id).messages)
        allowlist = Allowlist()
        _seed_attachments(conn, allowlist, body.attachments, case_id, patient_id)
        insert_user_message(
            conn,
            thread_id=thread_id,
            content=body.content,
            attachments=body.attachments,
        )
        assistant_id = insert_streaming_assistant_message(conn, thread_id=thread_id)
        tracer.case_id = case_id
    return _Turn(
        case_id=case_id,
        patient_id=patient_id,
        case_count=case_count,
        assistant_id=assistant_id,
        allowlist=allowlist,
        history=history,
    )


async def _drive(
    db_factory: DbFactory,
    provider: LLMProvider,
    encoders: TextEncoders,
    body: ConsultMessageCreate,
    turn: _Turn,
    tracer: NoopTurnTracer,
) -> AsyncIterator[ConsultStreamEvent]:
    messages = _model_messages(turn.history, body)
    system = system_prompt(
        case_id=turn.case_id,
        patient_id=turn.patient_id,
        case_count=turn.case_count,
    )
    turn.model = provider.model_name
    calls = 0
    step_index = 0
    while True:
        forced = calls >= MAX_TOOL_CALLS
        schemas = [] if forced else TOOL_SCHEMAS
        sanitizer = CitationSanitizer(turn.allowlist)
        span = tracer.start_model_span(model=turn.model, step_index=step_index)
        end: ProviderEvent | None = None
        try:
            async for event in provider.stream(system=system, messages=messages, tools=schemas):
                if event.kind == "text" and event.text:
                    visible = sanitizer.push(event.text)
                    if visible:
                        turn.parts.append(visible)
                        yield TextEvent(content=visible)
                elif event.kind == "end":
                    end = event
            tail = sanitizer.finish()
            if tail:
                turn.parts.append(tail)
                yield TextEvent(content=tail)
        finally:
            span.end(
                input_tokens=0 if end is None else end.input_tokens,
                output_tokens=0 if end is None else end.output_tokens,
                stop_reason=None if end is None else end.stop_reason,
            )
        step_index += 1
        if end is None:
            break
        turn.input_tokens += end.input_tokens
        turn.output_tokens += end.output_tokens
        if not end.tool_calls or forced:
            break
        tool_results: list[dict[str, Any]] = []
        for call in end.tool_calls:
            if calls >= MAX_TOOL_CALLS:
                tool_results.append(_budget_result(call.id))
                continue
            calls += 1
            turn.tool_calls = calls
            yield StepEvent(tool=call.name, summary=f"Running {call.name}.", duration_ms=0)
            started = time.perf_counter()
            tool_span = tracer.start_tool_span(tool=call.name, arguments=call.arguments)
            outcome = _run_tool(db_factory, encoders, turn, call.name, call.arguments)
            duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            encoded = outcome_json(outcome)
            tool_span.end(
                result_count=outcome.result_count,
                result_bytes=len(encoded.encode("utf-8")),
                ok="error" not in outcome.payload,
            )
            turn.trace.append(
                {
                    "tool": call.name,
                    "input": call.arguments,
                    "summary": outcome.summary,
                    "duration_ms": duration_ms,
                }
            )
            if call.name == "rank_pathologists":
                turn.ranking = _ranks(outcome.payload)
            yield StepEvent(tool=call.name, summary=outcome.summary, duration_ms=duration_ms)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": encoded,
                }
            )
        if end.content:
            messages.append({"role": "assistant", "content": end.content})
            messages.append({"role": "user", "content": tool_results})
        if calls >= MAX_TOOL_CALLS:
            continue
    logger.info(
        "consult turn case_id=%s input_tokens=%s output_tokens=%s tool_calls=%s",
        turn.case_id,
        turn.input_tokens,
        turn.output_tokens,
        calls,
    )


def _run_tool(
    db_factory: DbFactory,
    encoders: TextEncoders,
    turn: _Turn,
    name: str,
    arguments: dict[str, Any],
) -> Any:
    from consilium.agent.tools import ToolOutcome  # pragma: allowlist secret

    try:
        with db_factory() as conn:
            ctx = ToolContext(
                conn=conn,
                encoders=encoders,
                thread_case_id=turn.case_id,
                patient_id=turn.patient_id,
                allowlist=turn.allowlist,
            )
            return execute_tool(ctx, name, arguments)
    except Exception:
        logger.error("consult tool failed tool=%s", name)
        return ToolOutcome("Tool failed.", {"error": "tool_failed"}, 0)


def _finish(
    db_factory: DbFactory,
    thread_id: UUID,
    actor_id: str,
    turn: _Turn,
    *,
    status: str,
) -> ConsultMessage | None:
    if turn.finalized:
        return None
    turn.finalized = True
    content = unlink_unknown(turn.content, turn.allowlist)
    if not content and status == "complete":
        content = "No answer was produced."
    records = citation_records(content, turn.allowlist) if status == "complete" else None
    with db_factory() as conn:
        if records is not None:
            expanded = expand_citation_summaries(conn, records) or []
            kept = {item.case_id for item in expanded}
            records = [item for item in records if str(item["case_id"]) in kept]
            content = unlink_unknown(content, _only(turn.allowlist, kept))
        else:
            expanded = None
        finalize_assistant_message(
            conn,
            message_id=turn.assistant_id,
            content=content,
            citations=records,
            ranking=turn.ranking,
            tool_trace=turn.trace,
            model=turn.model,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            status=status,
        )
        thread = get_thread(conn, thread_id, actor_id)
    for message in thread.messages:
        if message.id == turn.assistant_id:
            return message
    return None


def _seed_attachments(
    conn: Connection,
    allowlist: Allowlist,
    attachments: MessageAttachments | None,
    thread_case_id: str,
    patient_id: str,
) -> None:
    if attachments is None or not attachments.case_ids:
        return
    rows = precedent_cases(
        conn,
        case_ids=list(attachments.case_ids),
        thread_case_id=thread_case_id,
    )
    for row in rows:
        allowlist.add(
            AllowedCase(
                case_id=str(row["id"]),
                patient_id=str(row["patient_id"]),
                same_patient=str(row["patient_id"]) == patient_id,
            )
        )


def _model_messages(
    history: list[ConsultMessage],
    body: ConsultMessageCreate,
) -> list[dict[str, Any]]:
    """Prior turns as plain text. The new question is the last user message."""
    prior = history
    if prior and prior[-1].role == "user" and prior[-1].content == body.content:
        prior = prior[:-1]
    messages: list[dict[str, Any]] = []
    for message in prior:
        if message.role == "user":
            messages.append(
                {
                    "role": "user",
                    "content": _render_user(message.content, message.attachments),
                }
            )
        elif message.content:
            messages.append({"role": "assistant", "content": message.content})
    messages.append(
        {"role": "user", "content": _render_user(body.content, body.attachments)}
    )
    return messages


def _render_user(content: str, attachments: MessageAttachments | None) -> str:
    parts = [content.strip()]
    if attachments is not None and attachments.region is not None:
        region = attachments.region
        parts.append(
            "Attached region "
            f"(slide_id={region.slide_id}, x={region.x}, y={region.y}, "
            f"width={region.width}, height={region.height})."
        )
    if attachments is not None and attachments.case_ids:
        joined = ", ".join(attachments.case_ids)
        parts.append(f"Attached case ids: {joined}.")
    return "\n\n".join(part for part in parts if part)


def _ranks(payload: dict[str, Any]) -> list[PathologistRank] | None:
    raw = payload.get("ranking")
    if not isinstance(raw, list):
        return None
    ranks: list[PathologistRank] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ranks.append(
            PathologistRank(
                pathologist_id=str(item["pathologist_id"]),
                name=str(item["name"]),
                specialty=item["specialty"],
                case_count=int(item["case_count"]),
                case_ids=[str(case_id) for case_id in item["case_ids"]],
            )
        )
    return ranks or None


def _only(allowed: Allowlist, kept: set[str]) -> Allowlist:
    narrowed = Allowlist()
    for case_id, meta in allowed.cases.items():
        if case_id in kept:
            narrowed.add(meta)
    return narrowed


def _budget_result(tool_use_id: str) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "is_error": True,
        "content": '{"error":"tool_budget_exhausted"}',
    }
