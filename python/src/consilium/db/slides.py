"""Slide and patch reads for the tile server. Storage keys stay in this module."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg import Connection
from psycopg.rows import class_row

from consilium.api.schemas.common import SlideStatus  # pragma: allowlist secret
from consilium.api.schemas.patch import PatchRef  # pragma: allowlist secret
from consilium.api.schemas.slide import SlideDetail  # pragma: allowlist secret

_SLIDE_SQL = """
select id, case_id, ordinal, stain, magnification, mpp, width, height,
       patch_size, patch_count, status, storage_key, thumb_pack_key
from slide
where id = %s
"""

_PATCH_SQL = """
select p.id, p.slide_id, p.case_id, p.x, p.y, p.size,
       p.thumb_offset, p.thumb_length,
       s.status as slide_status, s.thumb_pack_key
from patch p
join slide s on s.id = p.slide_id
where p.id = %s
"""

# Hit test uses slide.patch_size (level-0 pixels), half-open on the right and bottom.
_PATCH_AT_SQL = """
select p.id, p.slide_id, p.case_id, p.x, p.y, p.size,
       p.thumb_offset, p.thumb_length,
       s.status as slide_status, s.thumb_pack_key
from patch p
join slide s on s.id = p.slide_id
where p.slide_id = %s
  and p.x <= %s
  and %s < p.x + s.patch_size
  and p.y <= %s
  and %s < p.y + s.patch_size
order by p.id
limit 1
"""


@dataclass(frozen=True)
class SlideRow:
    id: str
    case_id: str
    ordinal: int
    stain: str
    magnification: float
    mpp: float
    width: int
    height: int
    patch_size: int
    patch_count: int
    status: str
    storage_key: str
    thumb_pack_key: str | None


@dataclass(frozen=True)
class PatchRow:
    id: int
    slide_id: str
    case_id: str
    x: int
    y: int
    size: int
    thumb_offset: int
    thumb_length: int
    slide_status: str
    thumb_pack_key: str | None


def get_slide(conn: Connection, slide_id: str) -> SlideRow | None:
    with conn.cursor(row_factory=class_row(SlideRow)) as cur:
        cur.execute(_SLIDE_SQL, (slide_id,))
        return cur.fetchone()


def get_patch(conn: Connection, patch_id: int) -> PatchRow | None:
    with conn.cursor(row_factory=class_row(PatchRow)) as cur:
        cur.execute(_PATCH_SQL, (patch_id,))
        return cur.fetchone()


def find_patch_at(conn: Connection, slide_id: str, x: int, y: int) -> PatchRow | None:
    with conn.cursor(row_factory=class_row(PatchRow)) as cur:
        cur.execute(_PATCH_AT_SQL, (slide_id, x, x, y, y))
        return cur.fetchone()


def slide_detail(row: SlideRow) -> SlideDetail:
    """API shape. Storage keys and the embedding are not copied onto it."""
    return SlideDetail(
        id=row.id,
        ordinal=row.ordinal,
        stain=row.stain,
        magnification=row.magnification,
        status=SlideStatus(row.status),
        thumbnail_url=f"/api/slides/{row.id}/thumbnail",
        case_id=row.case_id,
        mpp=row.mpp,
        width=row.width,
        height=row.height,
        patch_size=row.patch_size,
        patch_count=row.patch_count,
        dzi_url=f"/api/slides/{row.id}.dzi",
    )


def patch_ref(row: PatchRow) -> PatchRef:
    """API shape. Offsets, length and the embedding are not copied onto it."""
    return PatchRef(
        id=row.id,
        slide_id=row.slide_id,
        case_id=row.case_id,
        x=row.x,
        y=row.y,
        size=row.size,
        thumbnail_url=f"/api/patches/{row.id}/thumbnail",
    )
