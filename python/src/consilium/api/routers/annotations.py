from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, Request
from psycopg import Connection

from consilium.api.deps import Acting, StoreDep  # pragma: allowlist secret
from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.schemas.annotation import (  # pragma: allowlist secret
    Annotation,
    AnnotationCreate,
    AnnotationUpdate,
)
from consilium.db.annotations import (  # pragma: allowlist secret
    AnnotationError,
    delete_for_author,
    insert_annotation,
    list_for_slide,
    update_for_author,
)

router = APIRouter(tags=["annotations"])

T = TypeVar("T")


def _db(request: Request, action: Callable[[Connection], T]) -> T:
    with request.app.state.pool.connection() as conn:
        try:
            return action(conn)
        except AnnotationError as exc:
            fail(exc.status_code, exc.code, exc.message)


@router.get(
    "/slides/{slide_id}/annotations",
    response_model=list[Annotation],
    operation_id="list_slide_annotations",
)
def list_slide_annotations(
    slide_id: str,
    request: Request,
    actor: Acting,
    store: StoreDep,
) -> list[Annotation]:
    if request.app.state.use_stub_store:
        return store.list_annotations(slide_id, actor)
    return _db(request, lambda conn: list_for_slide(conn, slide_id, actor.id))


@router.post(
    "/slides/{slide_id}/annotations",
    response_model=Annotation,
    status_code=201,
    operation_id="create_slide_annotation",
)
def create_slide_annotation(
    slide_id: str,
    body: AnnotationCreate,
    request: Request,
    actor: Acting,
    store: StoreDep,
) -> Annotation:
    if request.app.state.use_stub_store:
        return store.create_annotation(slide_id, actor, body)
    return _db(request, lambda conn: insert_annotation(conn, slide_id, actor.id, body))


@router.patch(
    "/annotations/{annotation_id}",
    response_model=Annotation,
    operation_id="update_annotation",
)
def update_annotation(
    annotation_id: UUID,
    body: AnnotationUpdate,
    request: Request,
    actor: Acting,
    store: StoreDep,
) -> Annotation:
    if request.app.state.use_stub_store:
        return store.update_annotation(annotation_id, actor, body)
    return _db(
        request,
        lambda conn: update_for_author(conn, annotation_id, actor.id, body),
    )


@router.delete(
    "/annotations/{annotation_id}",
    status_code=204,
    operation_id="delete_annotation",
)
def delete_annotation(
    annotation_id: UUID,
    request: Request,
    actor: Acting,
    store: StoreDep,
) -> None:
    if request.app.state.use_stub_store:
        store.delete_annotation(annotation_id, actor)
        return
    _db(request, lambda conn: delete_for_author(conn, annotation_id, actor.id))
