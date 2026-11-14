from __future__ import annotations

import json
from collections.abc import Iterator
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from consilium.api.deps import Acting, StoreDep  # pragma: allowlist secret
from consilium.api.schemas.consult import (  # pragma: allowlist secret
    ConsultMessageCreate,
    ConsultStreamEvent,
    ConsultThread,
    ConsultThreadCreate,
)

router = APIRouter(tags=["consult"])


def _frames(events: list[ConsultStreamEvent]) -> Iterator[bytes]:
    for event in events:
        payload = event.model_dump(mode="json")
        data = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        yield f"event: {payload['type']}\ndata: {data}\n\n".encode()


@router.post(
    "/cases/{case_id}/consult/threads",
    response_model=ConsultThread,
    operation_id="start_consult_thread",
)
def start_consult_thread(
    case_id: str,
    actor: Acting,
    store: StoreDep,
    body: ConsultThreadCreate | None = None,
) -> ConsultThread:
    created = body or ConsultThreadCreate()
    return store.start_thread(case_id, actor, created.new)


@router.get(
    "/consult/threads/{thread_id}",
    response_model=ConsultThread,
    operation_id="get_consult_thread",
)
def get_consult_thread(thread_id: UUID, actor: Acting, store: StoreDep) -> ConsultThread:
    return store.get_thread(thread_id, actor)


@router.post(
    "/consult/threads/{thread_id}/messages",
    response_model=ConsultStreamEvent,
    operation_id="create_consult_message",
)
def create_consult_message(
    thread_id: UUID,
    body: ConsultMessageCreate,
    actor: Acting,
    store: StoreDep,
) -> StreamingResponse:
    events = store.reply(thread_id, actor, body)
    return StreamingResponse(_frames(events), media_type="text/event-stream")
