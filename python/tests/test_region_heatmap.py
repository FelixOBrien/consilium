"""Region and patch heatmaps, including the 8-connected tissue cluster."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pgvector import HalfVector

from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.api.schemas.common import Region  # pragma: allowlist secret
from consilium.config import Settings  # pragma: allowlist secret
from consilium.db.concepts import normalise_scores  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import seed  # pragma: allowlist secret
from consilium.embed.spaces import CONCHZ_DIM, ConchzEmbedding  # pragma: allowlist secret
from consilium.embed.text import MockTextEncoder, build_text_encoders  # pragma: allowlist secret
from consilium.search.query_vector import (  # pragma: allowlist secret
    patch_query_vector,
    region_query_vector,
)

_SIZE = 512
# 2x2 block of tissue A, plus one A island that is not 8-connected to the block.
_BLOCK = {(0, 0), (1, 0), (0, 1), (1, 1)}
_ISLAND = (3, 3)


@pytest.fixture
def heatmap(empty_database: str, tmp_path: Path) -> Iterator[tuple[TestClient, str, str, str]]:
    migrate(empty_database)
    seed(empty_database, tmp_path)
    app = create_app(Settings(database_url=empty_database, storage_root=tmp_path))
    app.state.text_encoders = build_text_encoders(backend=MockTextEncoder(), cache_size=0)
    conn = connect(empty_database)
    try:
        rows = conn.execute(
            "select id from slide order by patch_count desc, id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) >= 2
    with TestClient(app) as client:
        yield client, empty_database, rows[0][0], rows[1][0]


def test_heatmap_rejects_bad_sources(heatmap: tuple[TestClient, str, str, str]) -> None:
    client, _url, slide_id, other_id = heatmap
    region = {"slide_id": slide_id, "x": 0, "y": 0, "width": _SIZE, "height": _SIZE}
    rejected = (
        {},
        {"text": "necrosis", "concept_id": "tumour-necrosis"},
        {"text": "necrosis", "patch_id": 1},
        {"patch_id": 1, "region": region},
        {
            "text": "necrosis",
            "concept_id": "tumour-necrosis",
            "patch_id": 1,
            "region": region,
        },
        {"patch_id": 1, "negative_text": "normal tissue"},
        {"region": region, "negative_text": "normal tissue"},
        {"text": "necrosis", "grow": True},
        {"concept_id": "tumour-necrosis", "grow": True},
    )
    for payload in rejected:
        response = client.post(f"/api/slides/{slide_id}/heatmap", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    ids = _install_grid(heatmap[1], slide_id)
    wrong_patch = client.post(
        f"/api/slides/{other_id}/heatmap",
        json={"patch_id": ids[(0, 0)]},
    )
    assert wrong_patch.status_code == 422
    assert wrong_patch.json()["error"]["code"] == "validation_error"
    assert "different slide" in wrong_patch.json()["error"]["message"]

    wrong_region = client.post(
        f"/api/slides/{other_id}/heatmap",
        json={"region": region, "grow": True},
    )
    assert wrong_region.status_code == 422
    assert "different slide" in wrong_region.json()["error"]["message"]


def test_patch_heatmap_scores_the_seed_and_can_omit_the_cluster(
    heatmap: tuple[TestClient, str, str, str],
) -> None:
    client, url, slide_id, _other = heatmap
    ids = _install_grid(url, slide_id)
    plain = client.post(
        f"/api/slides/{slide_id}/heatmap",
        json={"patch_id": ids[(0, 0)], "grow": False},
    )
    assert plain.status_code == 200
    body = plain.json()
    assert body["source"] == "patch"
    assert body["text"] == ""
    assert body["concept_id"] is None
    assert body["cluster"] is None
    assert body["truncated"] is False
    _assert_tissue_notice(body["notice"])
    _assert_no_embedding(body)
    assert _score_at(body, 0, 0) == 1.0
    assert _score_at(body, _SIZE * 2, 0) == 0.0

    grown = client.post(
        f"/api/slides/{slide_id}/heatmap",
        json={"patch_id": ids[(0, 0)], "grow": True},
    )
    assert grown.status_code == 200
    cluster = grown.json()["cluster"]
    assert {(cell["x"], cell["y"]) for cell in cluster["cells"]} == _block_origins()
    _assert_cluster(cluster)


def test_region_cluster_contains_seeds_and_is_eight_connected(
    heatmap: tuple[TestClient, str, str, str],
) -> None:
    client, url, slide_id, _other = heatmap
    _install_grid(url, slide_id)
    response = client.post(
        f"/api/slides/{slide_id}/heatmap",
        json={
            "region": {
                "slide_id": slide_id,
                "x": 0,
                "y": 0,
                "width": _SIZE * 2,
                "height": _SIZE,
            },
            "grow": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "region"
    _assert_tissue_notice(body["notice"])
    _assert_no_embedding(body)
    cluster = body["cluster"]
    cells = {(cell["x"], cell["y"]) for cell in cluster["cells"]}
    assert {(0, 0), (_SIZE, 0)} <= cells
    assert (_SIZE * _ISLAND[0], _SIZE * _ISLAND[1]) not in cells
    assert cells == _block_origins()
    _assert_cluster(cluster)
    seed_scores = [
        _score_at(body, x, y) for x, y in ((0, 0), (_SIZE, 0))
    ]
    assert cluster["threshold"] <= sum(seed_scores) / len(seed_scores)


def test_empty_region_and_missing_patch_match_search(
    heatmap: tuple[TestClient, str, str, str],
) -> None:
    client, _url, slide_id, _other = heatmap
    empty_region = {
        "slide_id": slide_id,
        "x": 900_000,
        "y": 900_000,
        "width": 16,
        "height": 16,
    }
    heatmap_region = client.post(
        f"/api/slides/{slide_id}/heatmap",
        json={"region": empty_region},
    )
    search_region = client.post("/api/search/patches", json={"region": empty_region})
    assert heatmap_region.status_code == 422
    assert search_region.status_code == 422
    assert heatmap_region.json()["error"]["code"] == "validation_error"
    assert heatmap_region.json()["error"]["message"] == search_region.json()["error"]["message"]
    assert "no tissue" in heatmap_region.json()["error"]["message"]

    heatmap_patch = client.post(
        f"/api/slides/{slide_id}/heatmap",
        json={"patch_id": 9_999_999},
    )
    search_patch = client.post("/api/search/patches", json={"patch_id": 9_999_999})
    assert heatmap_patch.status_code == 404
    assert search_patch.status_code == 404
    assert heatmap_patch.json()["error"]["message"] == "Patch not found."
    assert heatmap_patch.json()["error"]["message"] == search_patch.json()["error"]["message"]


def test_text_and_concept_responses_only_add_source(
    heatmap: tuple[TestClient, str, str, str],
) -> None:
    client, _url, slide_id, _other = heatmap
    word = client.post(f"/api/slides/{slide_id}/heatmap", json={"text": "necrosis"})
    concept = client.post(
        f"/api/slides/{slide_id}/heatmap",
        json={"concept_id": "tumour-necrosis"},
    )
    assert word.status_code == 200
    assert concept.status_code == 200
    word_body = word.json()
    concept_body = concept.json()
    assert word_body["source"] == "text"
    assert concept_body["source"] == "concept"
    assert word_body["cluster"] is None
    assert concept_body["cluster"] is None
    assert word_body["text"] == "necrosis"
    assert concept_body["text"] == "an H&E image of tumour necrosis"
    assert concept_body["concept_id"] == "tumour-necrosis"
    assert "selected tissue" not in word_body["notice"]
    assert "selected tissue" not in concept_body["notice"]
    assert "Not a finding" in word_body["notice"]
    assert "not a diagnosis" in concept_body["notice"]
    for body in (word_body, concept_body):
        scores = [patch["score"] for patch in body["patches"]]
        assert min(scores) == 0.0
        assert max(scores) == 1.0
        assert set(body) == {
            "text",
            "concept_id",
            "negative_text",
            "notice",
            "truncated",
            "patches",
            "top",
            "source",
            "cluster",
        }


def test_heatmap_scores_match_the_shared_query_vector(
    heatmap: tuple[TestClient, str, str, str],
) -> None:
    client, url, slide_id, _other = heatmap
    ids = _install_grid(url, slide_id)
    conn = connect(url)
    try:
        tissue = patch_query_vector(conn, ids[(0, 0)])
        stored = conn.execute(
            "select embedding from patch where id = %s",
            (ids[(0, 0)],),
        ).fetchone()
        assert stored is not None
        expected = ConchzEmbedding.from_halfvec(_floats(stored[0]))
        assert tissue.vector.values == expected.values

        mixed = Region(
            slide_id=slide_id,
            x=_SIZE,
            y=0,
            width=_SIZE * 2,
            height=_SIZE,
        )
        rows = conn.execute(
            """
            select embedding from patch
            where slide_id = %s and y = 0 and x in (%s, %s)
            order by x
            """,
            (slide_id, _SIZE, _SIZE * 2),
        ).fetchall()
        manual = _renormalised_mean([_floats(row[0]) for row in rows])
        region_vector = region_query_vector(conn, mixed)
        assert list(region_vector.vector.values) == pytest.approx(manual)
        assert {seed.id for seed in region_vector.seeds} == {ids[(1, 0)], ids[(2, 0)]}
    finally:
        conn.close()

    found = client.post(
        "/api/search/patches",
        json={"patch_id": ids[(0, 0)], "scope": "slide", "limit": 20},
    )
    assert found.status_code == 200
    similarities = {
        (patch["x"], patch["y"]): patch["similarity"] for patch in found.json()["patches"]
    }
    assert (0, 0) not in similarities
    assert similarities[(_SIZE, 0)] == pytest.approx(1.0, abs=1e-3)
    assert similarities[(_SIZE * 2, 0)] == pytest.approx(0.0, abs=1e-3)

    shaded = client.post(
        f"/api/slides/{slide_id}/heatmap",
        json={"patch_id": ids[(0, 0)]},
    )
    assert shaded.status_code == 200
    half = tissue.vector.to_float16()
    conn = connect(url)
    try:
        scored = conn.execute(
            "select x, y, embedding from patch where slide_id = %s order by y, x",
            (slide_id,),
        ).fetchall()
    finally:
        conn.close()
    raw: list[float] = []
    order: list[tuple[int, int]] = []
    for x, y, embedding in scored:
        stored_values = _floats(embedding)
        raw.append(_cosine(stored_values, half))
        order.append((int(x), int(y)))
    expected_scores = {
        origin: score for origin, score in zip(order, normalise_scores(raw), strict=True)
    }
    for patch in shaded.json()["patches"]:
        origin = (patch["x"], patch["y"])
        assert patch["score"] == pytest.approx(expected_scores[origin], abs=1e-6)


def _install_grid(url: str, slide_id: str) -> dict[tuple[int, int], int]:
    conn = connect(url)
    try:
        meta = conn.execute(
            """
            select s.case_id, c.patient_id, c.specialty, s.patch_size
            from slide s
            join path_case c on c.id = s.case_id
            where s.id = %s
            """,
            (slide_id,),
        ).fetchone()
        assert meta is not None
        case_id, patient_id, specialty, size = meta
        assert int(size) == _SIZE
        conn.execute("delete from patch where slide_id = %s", (slide_id,))
        ids: dict[tuple[int, int], int] = {}
        for row in range(4):
            for col in range(4):
                kind = "a" if (col, row) in _BLOCK or (col, row) == _ISLAND else "b"
                vector = _basis(0 if kind == "a" else 1)
                inserted = conn.execute(
                    """
                    insert into patch (
                        slide_id, case_id, patient_id, specialty, x, y, size, embedding,
                        in_corpus, thumb_offset, thumb_length
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, false, 0, 1)
                    returning id
                    """,
                    (
                        slide_id,
                        case_id,
                        patient_id,
                        specialty,
                        col * _SIZE,
                        row * _SIZE,
                        _SIZE,
                        vector,
                    ),
                ).fetchone()
                assert inserted is not None
                ids[(col, row)] = int(inserted[0])
        conn.commit()
        return ids
    finally:
        conn.close()


def _basis(index: int) -> HalfVector:
    values = [0.0] * CONCHZ_DIM
    values[index] = 1.0
    return HalfVector(values)


def _floats(value: object) -> list[float]:
    to_list = getattr(value, "to_list", None)
    if callable(to_list):
        raw = to_list()
    else:
        raw = list(value)  # type: ignore[arg-type]
    return [float(item) for item in raw]


def _renormalised_mean(vectors: list[list[float]]) -> list[float]:
    total = [0.0] * CONCHZ_DIM
    for vector in vectors:
        for index, component in enumerate(vector):
            total[index] += component
    scale = 1.0 / len(vectors)
    mean = [component * scale for component in total]
    norm = sum(component * component for component in mean) ** 0.5
    return [component / norm for component in mean]


def _cosine(left: list[float], right: tuple[float, ...]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    return dot / (left_norm * right_norm)


def _block_origins() -> set[tuple[int, int]]:
    return {(col * _SIZE, row * _SIZE) for col, row in _BLOCK}


def _score_at(body: dict[str, object], x: int, y: int) -> float:
    patches = body["patches"]
    assert isinstance(patches, list)
    for patch in patches:
        assert isinstance(patch, dict)
        if patch["x"] == x and patch["y"] == y:
            return float(patch["score"])
    raise AssertionError(f"no patch at {x}, {y}")


def _assert_tissue_notice(notice: str) -> None:
    assert "selected tissue" in notice
    assert "Not a finding" in notice
    assert "not a diagnosis" in notice


def _assert_no_embedding(body: object) -> None:
    if isinstance(body, dict):
        assert "embedding" not in body
        for value in body.values():
            _assert_no_embedding(value)
    elif isinstance(body, list):
        for value in body:
            _assert_no_embedding(value)


def _assert_cluster(cluster: dict[str, object]) -> None:
    cells = cluster["cells"]
    bbox = cluster["bbox"]
    assert isinstance(cells, list)
    assert isinstance(bbox, dict)
    assert cluster["patch_count"] == len(cells)
    assert cells
    keys = {
        (int(cell["x"]) // int(cell["size"]), int(cell["y"]) // int(cell["size"]))
        for cell in cells
    }
    start = next(iter(keys))
    seen: set[tuple[int, int]] = set()
    stack = [start]
    while stack:
        gx, gy = stack.pop()
        if (gx, gy) in seen:
            continue
        seen.add((gx, gy))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                key = (gx + dx, gy + dy)
                if key in keys and key not in seen:
                    stack.append(key)
    assert seen == keys
    min_x = min(int(cell["x"]) for cell in cells)
    min_y = min(int(cell["y"]) for cell in cells)
    max_x = max(int(cell["x"]) + int(cell["size"]) for cell in cells)
    max_y = max(int(cell["y"]) + int(cell["size"]) for cell in cells)
    assert bbox == {"x": min_x, "y": min_y, "width": max_x - min_x, "height": max_y - min_y}
    for cell in cells:
        assert set(cell) == {"x", "y", "size"}
