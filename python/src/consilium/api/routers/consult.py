from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from consilium.agent import (  # pragma: allowlist secret
    AgentUnavailable,
    build_provider,
    consult_turn,
)
from consilium.agent.provider import LLMProvider, UnavailableProvider  # pragma: allowlist secret
from consilium.agent.tracing import build_tracer  # pragma: allowlist secret
from consilium.api.deps import (  # pragma: allowlist secret
    Acting,
    SettingsDep,
    StoreDep,
    read_connection,
    write_connection,
)
from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.schemas.consult import (  # pragma: allowlist secret
    ConsultMessageCreate,
    ConsultStreamEvent,
    ConsultThread,
    ConsultThreadCreate,
)
from consilium.db.consult import create_or_resume_thread, get_thread  # pragma: allowlist secret
from consilium.embed.text import TextEncoders  # pragma: allowlist secret

router = APIRouter(tags=["consult"])


def _frame(event: ConsultStreamEvent) -> bytes:
    payload = event.model_dump(mode="json")
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return f"event: {payload['type']}\ndata: {data}\n\n".encode()


def _frames(events: list[ConsultStreamEvent]) -> Iterator[bytes]:
    for event in events:
        yield _frame(event)


@router.post(
    "/cases/{case_id}/consult/threads",
    response_model=ConsultThread,
    operation_id="start_consult_thread",
)
def start_consult_thread(
    case_id: str,
    request: Request,
    actor: Acting,
    store: StoreDep,
    body: ConsultThreadCreate | None = None,
) -> ConsultThread:
    created = body or ConsultThreadCreate()
    if request.app.state.use_stub_store:
        return store.start_thread(case_id, actor, created.new)
    with write_connection(request) as conn:
        return create_or_resume_thread(
            conn,
            case_id=case_id,
            user_id=actor.id,
            new=created.new,
        )


@router.get(
    "/consult/threads/{thread_id}",
    response_model=ConsultThread,
    operation_id="get_consult_thread",
)
def get_consult_thread(
    thread_id: UUID,
    request: Request,
    actor: Acting,
    store: StoreDep,
) -> ConsultThread:
    if request.app.state.use_stub_store:
        return store.get_thread(thread_id, actor)
    with read_connection(request) as conn:
        return get_thread(conn, thread_id, actor.id)


@router.post(
    "/consult/threads/{thread_id}/messages",
    response_model=ConsultStreamEvent,
    operation_id="create_consult_message",
)
def create_consult_message(
    thread_id: UUID,
    body: ConsultMessageCreate,
    request: Request,
    actor: Acting,
    store: StoreDep,
    settings: SettingsDep,
) -> StreamingResponse:
    if request.app.state.use_stub_store:
        events = store.reply(thread_id, actor, body)
        return StreamingResponse(_frames(events), media_type="text/event-stream")
    with read_connection(request) as conn:
        get_thread(conn, thread_id, actor.id)
    encoders = getattr(request.app.state, "text_encoders", None)
    if not isinstance(encoders, TextEncoders):
        fail(500, "error", "Text encoder is not configured.")
    provider = _provider(request, settings)
    tracer = build_tracer(settings)

    async def events() -> AsyncIterator[bytes]:
        async for event in consult_turn(
            db_factory=lambda: write_connection(request),
            provider=provider,
            encoders=encoders,
            thread_id=thread_id,
            actor_id=actor.id,
            body=body,
            tracer=tracer,
        ):
            yield _frame(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _provider(request: Request, settings: SettingsDep) -> LLMProvider:
    override = getattr(request.app.state, "consult_provider", None)
    if override is not None:
        return override
    try:
        return build_provider(settings)
    except AgentUnavailable as exc:
        return UnavailableProvider(exc.detail)
