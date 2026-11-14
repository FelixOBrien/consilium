from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from consilium.api.deps import Acting, StoreDep  # pragma: allowlist secret
from consilium.api.schemas.annotation import (  # pragma: allowlist secret
    Annotation,
    AnnotationCreate,
    AnnotationUpdate,
)

router = APIRouter(tags=["annotations"])


@router.get(
    "/slides/{slide_id}/annotations",
    response_model=list[Annotation],
    operation_id="list_slide_annotations",
)
def list_slide_annotations(slide_id: str, actor: Acting, store: StoreDep) -> list[Annotation]:
    return store.list_annotations(slide_id, actor)


@router.post(
    "/slides/{slide_id}/annotations",
    response_model=Annotation,
    status_code=201,
    operation_id="create_slide_annotation",
)
def create_slide_annotation(
    slide_id: str,
    body: AnnotationCreate,
    actor: Acting,
    store: StoreDep,
) -> Annotation:
    return store.create_annotation(slide_id, actor, body)


@router.patch(
    "/annotations/{annotation_id}",
    response_model=Annotation,
    operation_id="update_annotation",
)
def update_annotation(
    annotation_id: UUID,
    body: AnnotationUpdate,
    actor: Acting,
    store: StoreDep,
) -> Annotation:
    return store.update_annotation(annotation_id, actor, body)


@router.delete(
    "/annotations/{annotation_id}",
    status_code=204,
    operation_id="delete_annotation",
)
def delete_annotation(annotation_id: UUID, actor: Acting, store: StoreDep) -> None:
    store.delete_annotation(annotation_id, actor)
