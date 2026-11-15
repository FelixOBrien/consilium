"""Annotation routes against a migrated, seeded database."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.config import Settings  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import (  # pragma: allowlist secret
    ANNOTATION_POINT_ID,
    ANNOTATION_RECT_ID,
    seed,
)
from consilium.seed_data import DEMO_USER_ID, ROSTER  # pragma: allowlist secret

OTHER = next(person for person in ROSTER if person.id != DEMO_USER_ID)
EMPTY_SLIDE_ID = "breast-FX-B042B-s1"
SEEDED_SLIDE_ID = "breast-FX-B042A-s1"
OTHER_HEADERS = {"X-User-Id": OTHER.id}


@dataclass
class _Api:
    client: TestClient
    width: int
    height: int


@pytest.fixture
def api(empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Api]:
    migrate(empty_database)
    seed(empty_database, tmp_path)
    monkeypatch.setenv("DATABASE_URL", empty_database)
    with connect(empty_database) as conn:
        row = conn.execute(
            "select width, height from slide where id = %s",
            (EMPTY_SLIDE_ID,),
        ).fetchone()
    assert row is not None
    app = create_app(Settings(database_url=empty_database), use_stub_store=False)
    with TestClient(app) as client:
        yield _Api(client, int(row[0]), int(row[1]))


def _code(response: Response) -> str:
    return str(response.json()["error"]["code"])


def test_create_rect_and_point_listed_in_creation_order(api: _Api) -> None:
    empty = api.client.get(f"/api/slides/{EMPTY_SLIDE_ID}/annotations")
    assert empty.status_code == 200
    assert empty.json() == []

    rectangle = api.client.post(
        f"/api/slides/{EMPTY_SLIDE_ID}/annotations",
        json={
            "kind": "rect",
            "geometry": {"x": 10, "y": 20, "width": 30, "height": 40},
            "label": "Region",
            "note": "first mark",
        },
    )
    assert rectangle.status_code == 201
    rect_body = rectangle.json()
    assert rect_body["can_edit"] is True
    assert rect_body["kind"] == "rect"
    assert rect_body["geometry"] == {"x": 10, "y": 20, "width": 30, "height": 40}
    assert rect_body["slide_id"] == EMPTY_SLIDE_ID
    assert rect_body["case_id"] == "breast-FX-B042B"
    assert rect_body["author"]["id"] == DEMO_USER_ID
    assert rect_body["author"]["is_synthetic"] is True

    point = api.client.post(
        f"/api/slides/{EMPTY_SLIDE_ID}/annotations",
        json={"kind": "point", "geometry": {"x": 4, "y": 5}, "label": "Point"},
    )
    assert point.status_code == 201
    point_body = point.json()
    assert point_body["can_edit"] is True
    assert point_body["kind"] == "point"
    assert point_body["geometry"] == {"x": 4, "y": 5}
    assert point_body["note"] is None

    listed = api.client.get(f"/api/slides/{EMPTY_SLIDE_ID}/annotations")
    assert listed.status_code == 200
    body = listed.json()
    assert [item["id"] for item in body] == [rect_body["id"], point_body["id"]]
    assert [item["created_at"] for item in body] == sorted(item["created_at"] for item in body)
    assert body == sorted(body, key=lambda item: (item["created_at"], item["id"]))

    seeded = api.client.get(f"/api/slides/{SEEDED_SLIDE_ID}/annotations")
    assert seeded.status_code == 200
    seeded_ids = [item["id"] for item in seeded.json()]
    assert seeded_ids[:2] == [str(ANNOTATION_RECT_ID), str(ANNOTATION_POINT_ID)]


def test_can_edit_follows_the_acting_pathologist(api: _Api) -> None:
    created = api.client.post(
        f"/api/slides/{EMPTY_SLIDE_ID}/annotations",
        headers={"X-User-Id": DEMO_USER_ID},
        json={"kind": "point", "geometry": {"x": 8, "y": 9}, "label": "Mine"},
    )
    assert created.status_code == 201
    annotation_id = created.json()["id"]
    assert created.json()["can_edit"] is True
    assert created.json()["author"]["is_synthetic"] is True

    as_author = api.client.get(f"/api/slides/{EMPTY_SLIDE_ID}/annotations")
    assert as_author.status_code == 200
    author_row = as_author.json()[0]
    assert author_row["id"] == annotation_id
    assert author_row["can_edit"] is True
    assert author_row["author"]["id"] == DEMO_USER_ID

    as_other = api.client.get(
        f"/api/slides/{EMPTY_SLIDE_ID}/annotations",
        headers=OTHER_HEADERS,
    )
    assert as_other.status_code == 200
    assert as_other.json()[0]["id"] == annotation_id
    assert as_other.json()[0]["can_edit"] is False
    assert as_other.json()[0]["author"]["id"] == DEMO_USER_ID

    theirs = api.client.post(
        f"/api/slides/{EMPTY_SLIDE_ID}/annotations",
        headers=OTHER_HEADERS,
        json={
            "kind": "rect",
            "geometry": {"x": 1, "y": 2, "width": 3, "height": 4},
            "label": "Theirs",
        },
    )
    assert theirs.status_code == 201
    assert theirs.json()["can_edit"] is True
    assert theirs.json()["author"]["id"] == OTHER.id
    assert theirs.json()["author"]["name"] == OTHER.name
    assert theirs.json()["author"]["is_synthetic"] is True

    mixed = api.client.get(f"/api/slides/{EMPTY_SLIDE_ID}/annotations")
    by_id = {item["id"]: item["can_edit"] for item in mixed.json()}
    assert by_id[annotation_id] is True
    assert by_id[theirs.json()["id"]] is False

    mixed_other = api.client.get(
        f"/api/slides/{EMPTY_SLIDE_ID}/annotations",
        headers=OTHER_HEADERS,
    )
    by_id_other = {item["id"]: item["can_edit"] for item in mixed_other.json()}
    assert by_id_other[annotation_id] is False
    assert by_id_other[theirs.json()["id"]] is True


def test_author_can_edit_including_clearing_note(api: _Api) -> None:
    created = api.client.post(
        f"/api/slides/{EMPTY_SLIDE_ID}/annotations",
        json={
            "kind": "rect",
            "geometry": {"x": 0, "y": 0, "width": 12, "height": 12},
            "label": "First",
            "note": "keep me",
        },
    )
    assert created.status_code == 201
    annotation_id = created.json()["id"]
    path = f"/api/annotations/{annotation_id}"

    renamed = api.client.patch(path, json={"label": "Second"})
    assert renamed.status_code == 200
    assert renamed.json()["label"] == "Second"
    assert renamed.json()["note"] == "keep me"
    assert renamed.json()["geometry"] == {"x": 0, "y": 0, "width": 12, "height": 12}
    assert renamed.json()["can_edit"] is True
    assert renamed.json()["updated_at"] >= created.json()["updated_at"]

    cleared = api.client.patch(path, json={"note": None})
    assert cleared.status_code == 200
    assert cleared.json()["note"] is None
    assert cleared.json()["label"] == "Second"

    moved = api.client.patch(
        path,
        json={"geometry": {"x": 3, "y": 4, "width": 5, "height": 6}},
    )
    assert moved.status_code == 200
    assert moved.json()["geometry"] == {"x": 3, "y": 4, "width": 5, "height": 6}
    assert moved.json()["note"] is None
    assert moved.json()["label"] == "Second"

    outside = api.client.patch(
        path,
        json={"geometry": {"x": 0, "y": 0, "width": api.width + 1, "height": 1}},
    )
    assert outside.status_code == 422
    assert _code(outside) == "validation_error"

    mismatched = api.client.patch(path, json={"geometry": {"x": 1, "y": 1}})
    assert mismatched.status_code == 422
    assert _code(mismatched) == "validation_error"

    denied = api.client.patch(path, headers=OTHER_HEADERS, json={"label": "nope"})
    assert denied.status_code == 403
    assert _code(denied) == "forbidden"

    denied_delete = api.client.delete(path, headers=OTHER_HEADERS)
    assert denied_delete.status_code == 403
    assert _code(denied_delete) == "forbidden"

    listed = api.client.get(f"/api/slides/{EMPTY_SLIDE_ID}/annotations")
    assert listed.json()[0]["label"] == "Second"
    assert listed.json()[0]["note"] is None
    assert listed.json()[0]["geometry"] == {"x": 3, "y": 4, "width": 5, "height": 6}

    removed = api.client.delete(path)
    assert removed.status_code == 204

    after = api.client.get(f"/api/slides/{EMPTY_SLIDE_ID}/annotations")
    assert after.status_code == 200
    assert after.json() == []
    missing = api.client.patch(path, json={"label": "gone"})
    assert missing.status_code == 404
    assert _code(missing) == "not_found"
    missing_delete = api.client.delete(path)
    assert missing_delete.status_code == 404
    assert _code(missing_delete) == "not_found"


def test_geometry_must_lie_inside_the_slide(api: _Api) -> None:
    on_edge = api.client.post(
        f"/api/slides/{EMPTY_SLIDE_ID}/annotations",
        json={
            "kind": "point",
            "geometry": {"x": api.width - 1, "y": api.height - 1},
            "label": "Corner",
        },
    )
    assert on_edge.status_code == 201
    full = api.client.post(
        f"/api/slides/{EMPTY_SLIDE_ID}/annotations",
        json={
            "kind": "rect",
            "geometry": {"x": 0, "y": 0, "width": api.width, "height": api.height},
            "label": "Whole slide",
        },
    )
    assert full.status_code == 201

    rejected = [
        {"kind": "point", "geometry": {"x": api.width, "y": 0}, "label": "Past width"},
        {"kind": "point", "geometry": {"x": 0, "y": api.height}, "label": "Past height"},
        {"kind": "point", "geometry": {"x": -1, "y": 0}, "label": "Negative"},
        {
            "kind": "rect",
            "geometry": {"x": -1, "y": 0, "width": 2, "height": 2},
            "label": "Negative",
        },
        {
            "kind": "rect",
            "geometry": {"x": 1, "y": 1, "width": api.width, "height": 2},
            "label": "Too wide",
        },
        {
            "kind": "rect",
            "geometry": {"x": 0, "y": 1, "width": 2, "height": api.height},
            "label": "Too tall",
        },
        {
            "kind": "rect",
            "geometry": {"x": 0, "y": 0, "width": 0, "height": 10},
            "label": "Zero width",
        },
        {
            "kind": "rect",
            "geometry": {"x": 0, "y": 0, "width": 10, "height": -1},
            "label": "Negative height",
        },
        {
            "kind": "point",
            "geometry": {"x": 1, "y": 1, "width": 2, "height": 2},
            "label": "Point shape",
        },
        {"kind": "rect", "geometry": {"x": 1, "y": 1}, "label": "Rect shape"},
        {"kind": "point", "geometry": {"x": 1.5, "y": 2}, "label": "Float"},
        {
            "kind": "rect",
            "geometry": {"x": 0, "y": 0, "width": 10.2, "height": 4},
            "label": "Float width",
        },
    ]
    for payload in rejected:
        response = api.client.post(f"/api/slides/{EMPTY_SLIDE_ID}/annotations", json=payload)
        assert response.status_code == 422, payload
        assert _code(response) == "validation_error"

    listed = api.client.get(f"/api/slides/{EMPTY_SLIDE_ID}/annotations")
    assert [item["label"] for item in listed.json()] == ["Corner", "Whole slide"]


def test_unknown_slide_or_annotation_is_not_found(api: _Api) -> None:
    missing_slide = "/api/slides/missing-slide/annotations"
    listed = api.client.get(missing_slide)
    assert listed.status_code == 404
    assert _code(listed) == "not_found"
    created = api.client.post(
        missing_slide,
        json={"kind": "point", "geometry": {"x": 1, "y": 1}, "label": "Nowhere"},
    )
    assert created.status_code == 404
    assert _code(created) == "not_found"

    missing_id = uuid4()
    updated = api.client.patch(f"/api/annotations/{missing_id}", json={"label": "gone"})
    assert updated.status_code == 404
    assert _code(updated) == "not_found"
    removed = api.client.delete(f"/api/annotations/{missing_id}")
    assert removed.status_code == 404
    assert _code(removed) == "not_found"
