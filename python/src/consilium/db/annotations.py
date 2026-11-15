"""Annotation queries. Geometry stays in level-0 pixels on the slide."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from consilium.api.schemas.annotation import (  # pragma: allowlist secret
    Annotation,
    AnnotationCreate,
    AnnotationUpdate,
    PointGeometry,
    RectGeometry,
    _geometry_matches,
)
from consilium.api.schemas.pathologist import PathologistRef  # pragma: allowlist secret


class AnnotationError(Exception):
    """A request the annotation routes turn into an error envelope."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def list_for_slide(conn: Connection, slide_id: str, actor_id: str) -> list[Annotation]:
    slide = _fetchone(conn, "select id from slide where id = %s", (slide_id,))
    if slide is None:
        raise AnnotationError(404, "not_found", "Slide not found.")
    rows = _fetchall(
        conn,
        """
        select
            a.id,
            a.slide_id,
            a.case_id,
            a.kind,
            a.geometry,
            a.label,
            a.note,
            a.created_at,
            a.updated_at,
            p.id as author_id,
            p.name as author_name,
            p.primary_specialty as author_specialty,
            p.is_synthetic as author_is_synthetic
        from annotation a
        join pathologist p on p.id = a.author_id
        where a.slide_id = %s
        order by a.created_at asc, a.id asc
        """,
        (slide_id,),
    )
    return [_annotation(row, actor_id) for row in rows]


def insert_annotation(
    conn: Connection,
    slide_id: str,
    actor_id: str,
    body: AnnotationCreate,
) -> Annotation:
    slide = _fetchone(
        conn,
        "select id, case_id, width, height from slide where id = %s",
        (slide_id,),
    )
    if slide is None:
        raise AnnotationError(404, "not_found", "Slide not found.")
    _ensure_geometry(body.kind, body.geometry, int(slide["width"]), int(slide["height"]))
    row = _fetchone(
        conn,
        """
        with inserted as (
            insert into annotation (
                slide_id, case_id, author_id, kind, geometry, label, note
            ) values (%s, %s, %s, %s, %s, %s, %s)
            returning
                id, slide_id, case_id, author_id, kind, geometry, label, note,
                created_at, updated_at
        )
        select
            a.id,
            a.slide_id,
            a.case_id,
            a.kind,
            a.geometry,
            a.label,
            a.note,
            a.created_at,
            a.updated_at,
            p.id as author_id,
            p.name as author_name,
            p.primary_specialty as author_specialty,
            p.is_synthetic as author_is_synthetic
        from inserted a
        join pathologist p on p.id = a.author_id
        """,
        (
            slide_id,
            slide["case_id"],
            actor_id,
            body.kind,
            Jsonb(body.geometry.model_dump()),
            body.label,
            body.note,
        ),
    )
    if row is None:
        raise AnnotationError(404, "not_found", "Slide not found.")
    return _annotation(row, actor_id)


def update_for_author(
    conn: Connection,
    annotation_id: UUID,
    actor_id: str,
    body: AnnotationUpdate,
) -> Annotation:
    current = _fetchone(
        conn,
        """
        select
            a.id, a.author_id, a.kind, a.geometry, a.label, a.note,
            s.width, s.height
        from annotation a
        join slide s on s.id = a.slide_id
        where a.id = %s
        """,
        (annotation_id,),
    )
    if current is None:
        raise AnnotationError(404, "not_found", "Annotation not found.")
    if current["author_id"] != actor_id:
        raise AnnotationError(403, "forbidden", "Only the author can change this annotation.")

    kind = str(current["kind"])
    geometry = (
        body.geometry
        if body.geometry is not None
        else _geometry_model(kind, current["geometry"])
    )
    if body.geometry is not None:
        _ensure_geometry(kind, geometry, int(current["width"]), int(current["height"]))
    label = body.label if body.label is not None else str(current["label"])
    note = body.note if "note" in body.model_fields_set else current["note"]

    row = _fetchone(
        conn,
        """
        with updated as (
            update annotation
            set label = %s,
                note = %s,
                geometry = %s,
                updated_at = now()
            where id = %s
            returning
                id, slide_id, case_id, author_id, kind, geometry, label, note,
                created_at, updated_at
        )
        select
            a.id,
            a.slide_id,
            a.case_id,
            a.kind,
            a.geometry,
            a.label,
            a.note,
            a.created_at,
            a.updated_at,
            p.id as author_id,
            p.name as author_name,
            p.primary_specialty as author_specialty,
            p.is_synthetic as author_is_synthetic
        from updated a
        join pathologist p on p.id = a.author_id
        """,
        (label, note, Jsonb(geometry.model_dump()), annotation_id),
    )
    if row is None:
        raise AnnotationError(404, "not_found", "Annotation not found.")
    return _annotation(row, actor_id)


def delete_for_author(conn: Connection, annotation_id: UUID, actor_id: str) -> None:
    current = _fetchone(
        conn,
        "select author_id from annotation where id = %s",
        (annotation_id,),
    )
    if current is None:
        raise AnnotationError(404, "not_found", "Annotation not found.")
    if current["author_id"] != actor_id:
        raise AnnotationError(403, "forbidden", "Only the author can change this annotation.")
    deleted = _fetchone(
        conn,
        "delete from annotation where id = %s returning id",
        (annotation_id,),
    )
    if deleted is None:
        raise AnnotationError(404, "not_found", "Annotation not found.")


def _ensure_geometry(
    kind: str,
    geometry: RectGeometry | PointGeometry,
    width: int,
    height: int,
) -> None:
    """Reject a shape that does not match `kind` or sit inside the slide.

    A point is a level-0 pixel, so it is inside when `0 <= x < width` and
    `0 <= y < height`. A rectangle starts at `x`, `y` and stays inside when
    its far edges satisfy `x + width <= width` and `y + height <= height`.
    """
    try:
        _geometry_matches(kind, geometry)
    except ValueError as exc:
        raise AnnotationError(422, "validation_error", str(exc)) from exc
    if isinstance(geometry, RectGeometry):
        inside = (
            geometry.x >= 0
            and geometry.y >= 0
            and geometry.width > 0
            and geometry.height > 0
            and geometry.x + geometry.width <= width
            and geometry.y + geometry.height <= height
        )
    else:
        inside = 0 <= geometry.x < width and 0 <= geometry.y < height
    if not inside:
        raise AnnotationError(422, "validation_error", "Geometry is outside the slide.")


def _geometry_model(kind: str, raw: object) -> RectGeometry | PointGeometry:
    if not isinstance(raw, dict):
        raise AnnotationError(422, "validation_error", "Geometry is outside the slide.")
    try:
        if kind == "rect":
            return RectGeometry.model_validate(
                {key: raw[key] for key in ("x", "y", "width", "height")}
            )
        if kind == "point":
            return PointGeometry.model_validate({key: raw[key] for key in ("x", "y")})
    except (KeyError, ValidationError) as exc:
        raise AnnotationError(422, "validation_error", "Geometry is outside the slide.") from exc
    raise AnnotationError(422, "validation_error", "Geometry is outside the slide.")


def _annotation(row: dict[str, Any], actor_id: str) -> Annotation:
    raw_kind = str(row["kind"])
    if raw_kind == "rect":
        kind: Literal["rect", "point"] = "rect"
    elif raw_kind == "point":
        kind = "point"
    else:
        raise AnnotationError(422, "validation_error", "Geometry is outside the slide.")
    return Annotation(
        id=row["id"],
        slide_id=row["slide_id"],
        case_id=row["case_id"],
        author=PathologistRef(
            id=row["author_id"],
            name=row["author_name"],
            primary_specialty=row["author_specialty"],
            is_synthetic=row["author_is_synthetic"],
        ),
        can_edit=row["author_id"] == actor_id,
        kind=kind,
        geometry=_geometry_model(kind, row["geometry"]),
        label=row["label"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _fetchone(
    conn: Connection,
    query: str,
    params: tuple[object, ...],
) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    return row


def _fetchall(
    conn: Connection,
    query: str,
    params: tuple[object, ...],
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return list(cur.fetchall())
