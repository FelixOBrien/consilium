"""Heatmap and concept endpoints against a migrated, seeded database."""

from __future__ import annotations

import inspect
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pgvector import HalfVector
from psycopg import Connection

from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.config import Settings  # pragma: allowlist secret
from consilium.db.concepts import (  # pragma: allowlist secret
    CONTRAST_HEATMAP_SQL,
    POSITIVE_HEATMAP_SQL,
    _score_slide,
    normalise_scores,
)
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import seed  # pragma: allowlist secret
from consilium.embed.text import (  # pragma: allowlist secret
    CONCHZ_MAX_TOKENS,
    EncodedText,
    MockTextEncoder,
    ReportTextKind,
    build_text_encoders,
)
from consilium.seed_data import CONCEPTS, ConceptSeed  # pragma: allowlist secret

BENCHMARK_PATCHES = 3000
# MockTextEncoder counts whitespace pieces plus two special tokens, the same
# 127-token rule the CONCH-Z text tower uses.
_OVERLONG_TEXT = "necrosis " * (CONCHZ_MAX_TOKENS + 4)
_LONG_SINGLE_WORD = "necrosis" * 80


@dataclass
class CountingBackend:
    """Records CONCH-Z encode calls. Report space must not be used here."""

    conch: list[list[str]]

    def __init__(self) -> None:
        self.conch = []

    def encode_conchz(self, texts: Sequence[str]) -> list[EncodedText]:
        batch = list(texts)
        self.conch.append(batch)
        return MockTextEncoder().encode_conchz(batch)

    def encode_report(
        self, texts: Sequence[str], *, kind: ReportTextKind
    ) -> list[EncodedText]:
        del texts, kind
        raise AssertionError("heatmap encoding must stay in the conchz space")


@dataclass
class HeatmapWorld:
    client: TestClient
    backend: CountingBackend
    database_url: str
    slide_id: str
    other_slide_id: str


def test_heatmap_sql_is_an_exact_slide_scan() -> None:
    source = inspect.getsource(_score_slide)
    assert "POSITIVE_HEATMAP_SQL" in source
    assert "CONTRAST_HEATMAP_SQL" in source
    for statement in (POSITIVE_HEATMAP_SQL, CONTRAST_HEATMAP_SQL):
        folded = " ".join(statement.lower().split())
        assert "where slide_id = %s" in folded
        assert "order by" not in folded
        assert "limit" not in folded
        assert "(1 - (embedding <=> %s::halfvec(768)))" in folded
    contrast = " ".join(CONTRAST_HEATMAP_SQL.lower().split())
    assert contrast.count("(1 - (embedding <=> %s::halfvec(768)))") == 2


def test_normalise_scores_handles_empty_and_flat_slides() -> None:
    assert normalise_scores([]) == []
    assert normalise_scores([0.2, 0.2, 0.2]) == [0.0, 0.0, 0.0]
    assert normalise_scores([2.0, 4.0, 3.0]) == [0.0, 1.0, 0.5]
    assert normalise_scores([-3.0, -1.0]) == [0.0, 1.0]


@pytest.fixture
def world(empty_database: str, tmp_path: Path) -> Iterator[HeatmapWorld]:
    migrate(empty_database)
    seed(empty_database, tmp_path)
    backend = CountingBackend()
    app = create_app(Settings(database_url=empty_database, storage_root=tmp_path))
    app.state.text_encoders = build_text_encoders(backend=backend, cache_size=0)
    conn = connect(empty_database)
    try:
        rows = conn.execute(
            "select id from slide order by patch_count desc, id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) >= 2
    with TestClient(app) as client:
        yield HeatmapWorld(
            client=client,
            backend=backend,
            database_url=empty_database,
            slide_id=rows[0][0],
            other_slide_id=rows[1][0],
        )


def test_concepts_list_filters_specialty_and_omits_embeddings(world: HeatmapWorld) -> None:
    client = world.client
    full = client.get("/api/concepts")
    assert full.status_code == 200
    rows = full.json()
    assert [row["id"] for row in rows] == [concept.id for concept in _visible(None)]
    assert all(set(row) == {"id", "label", "prompt", "specialty"} for row in rows)
    blob = full.text
    assert "embedding" not in blob
    assert "negative_embedding" not in blob

    breast = client.get("/api/concepts", params={"specialty": "breast"})
    assert breast.status_code == 200
    breast_rows = breast.json()
    expected = _visible("breast")
    assert [row["id"] for row in breast_rows] == [concept.id for concept in expected]
    assert all(row["specialty"] in (None, "breast") for row in breast_rows)
    assert any(row["specialty"] is None for row in breast_rows)
    assert any(row["specialty"] == "breast" for row in breast_rows)
    for row, concept in zip(breast_rows, expected, strict=True):
        assert row["label"] == concept.label
        assert row["prompt"] == concept.prompt
        assert row["specialty"] == concept.specialty

    skin = client.get("/api/concepts", params={"specialty": "skin"}).json()
    skin_ids = {row["id"] for row in skin}
    assert "melanin-pigment" in skin_ids
    assert "breast-ducts" not in skin_ids

    invalid = client.get("/api/concepts", params={"specialty": "lung"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


def test_text_heatmap_normalises_ranks_and_reports_truncation(world: HeatmapWorld) -> None:
    client = world.client
    plain = client.post(f"/api/slides/{world.slide_id}/heatmap", json={"text": "necrosis"})
    assert plain.status_code == 200
    body = plain.json()
    assert body["text"] == "necrosis"
    assert body["concept_id"] is None
    assert body["negative_text"] is None
    assert body["source"] == "text"
    assert body["cluster"] is None
    assert body["truncated"] is False
    _assert_notice(body["notice"], truncated=False)
    _assert_unit_interval(body)
    assert world.backend.conch == [["necrosis"]]

    negative = client.post(
        f"/api/slides/{world.slide_id}/heatmap",
        json={"text": "necrosis", "negative_text": "normal tissue"},
    )
    assert negative.status_code == 200
    contrasted = negative.json()
    assert contrasted["negative_text"] == "normal tissue"
    assert _rank(body) != _rank(contrasted)
    assert world.backend.conch[-1] == ["necrosis", "normal tissue"]

    # A long character string that is still one token is not truncated. The cap
    # is the encoder's token limit, which MockTextEncoder applies the same way
    # the CONCH-Z tower does.
    single = client.post(
        f"/api/slides/{world.slide_id}/heatmap",
        json={"text": _LONG_SINGLE_WORD},
    )
    assert single.status_code == 200
    assert single.json()["truncated"] is False
    assert single.json()["text"] == _LONG_SINGLE_WORD
    assert len(_LONG_SINGLE_WORD) > 127

    overlong = client.post(
        f"/api/slides/{world.slide_id}/heatmap",
        json={"text": _OVERLONG_TEXT},
    )
    assert overlong.status_code == 200
    overlong_body = overlong.json()
    assert overlong_body["truncated"] is True
    assert overlong_body["text"] == _OVERLONG_TEXT.strip()
    _assert_notice(overlong_body["notice"], truncated=True)

    missing_slide = client.post("/api/slides/missing-slide/heatmap", json={"text": "necrosis"})
    assert missing_slide.status_code == 404
    assert missing_slide.json()["error"]["code"] == "not_found"

    missing_concept = client.post(
        f"/api/slides/{world.slide_id}/heatmap",
        json={"concept_id": "not-a-concept"},
    )
    assert missing_concept.status_code == 404
    assert missing_concept.json()["error"]["code"] == "not_found"

    both = client.post(
        f"/api/slides/{world.slide_id}/heatmap",
        json={"text": "necrosis", "concept_id": "tumour-necrosis"},
    )
    assert both.status_code == 422

    _assert_degenerate_slides(world)


def test_concept_heatmap_uses_stored_embeddings_without_encoding(world: HeatmapWorld) -> None:
    client = world.client
    world.backend.conch.clear()
    response = client.post(
        f"/api/slides/{world.slide_id}/heatmap",
        json={"concept_id": "tumour-necrosis"},
    )
    assert response.status_code == 200
    body = response.json()
    assert world.backend.conch == []
    assert body["concept_id"] == "tumour-necrosis"
    assert body["text"] == "an H&E image of tumour necrosis"
    assert body["negative_text"] is None
    assert body["source"] == "concept"
    assert body["cluster"] is None
    assert body["truncated"] is False
    _assert_notice(body["notice"], truncated=False)
    _assert_unit_interval(body)

    stored_positive, stored_negative = _concept_vectors(world.database_url, "tumour-necrosis")
    assert stored_negative is not None
    contrasted = _numpy_order(world.database_url, world.slide_id, stored_positive, stored_negative)
    positive_only = _numpy_order(world.database_url, world.slide_id, stored_positive, None)
    assert _rank(body) == contrasted
    assert _rank(body) != positive_only

    plain = client.post(
        f"/api/slides/{world.slide_id}/heatmap",
        json={"concept_id": "mitotic-figures"},
    )
    assert plain.status_code == 200
    assert world.backend.conch == []
    mitotic, mitotic_negative = _concept_vectors(world.database_url, "mitotic-figures")
    assert mitotic_negative is None
    assert _rank(plain.json()) == _numpy_order(
        world.database_url, world.slide_id, mitotic, None
    )

    overridden = client.post(
        f"/api/slides/{world.slide_id}/heatmap",
        json={"concept_id": "tumour-necrosis", "negative_text": "keratin"},
    )
    assert overridden.status_code == 200
    assert world.backend.conch == [["keratin"]]
    assert _rank(overridden.json()) != _rank(body)
    assert overridden.json()["negative_text"] == "keratin"
    assert overridden.json()["truncated"] is False


def test_concept_heatmap_scans_a_realistic_slide_quickly(world: HeatmapWorld) -> None:
    _insert_patches(world.database_url, world.slide_id, BENCHMARK_PATCHES)
    conn = connect(world.database_url)
    try:
        count = conn.execute(
            "select count(*) from patch where slide_id = %s",
            (world.slide_id,),
        ).fetchone()
        assert count is not None
        assert count[0] >= BENCHMARK_PATCHES
        plan = _explain(conn, world.slide_id)
        indexed = _explain(conn, world.slide_id, force_index=True)
    finally:
        conn.close()
    assert "hnsw" not in plan.lower()
    assert "patch_embedding_hnsw" not in plan
    assert "hnsw" not in indexed.lower()
    assert "patch_slide_position_unique" in indexed

    world.backend.conch.clear()
    started = time.perf_counter()
    response = world.client.post(
        f"/api/slides/{world.slide_id}/heatmap",
        json={"concept_id": "tumour-necrosis"},
    )
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    body = response.json()
    assert world.backend.conch == []
    assert len(body["patches"]) == count[0]
    _assert_unit_interval(body)
    assert elapsed < 2.0
    print(
        f"HEATMAP_BENCHMARK seconds={elapsed:.4f} patches={count[0]} "
        f"plan={plan.replace(chr(10), ' | ')}"
    )


def _visible(specialty: str | None) -> list[ConceptSeed]:
    rows = [
        concept
        for concept in CONCEPTS
        if specialty is None or concept.specialty is None or concept.specialty == specialty
    ]
    return sorted(rows, key=lambda concept: (concept.ordinal, concept.id))


def _assert_notice(notice: str, *, truncated: bool) -> None:
    assert "Not a finding" in notice
    assert "not a diagnosis" in notice
    if truncated:
        assert "truncated" in notice
        assert str(CONCHZ_MAX_TOKENS) in notice
    else:
        assert "truncated" not in notice


def _assert_unit_interval(body: dict[str, object]) -> None:
    patches = body["patches"]
    top = body["top"]
    assert isinstance(patches, list) and isinstance(top, list)
    assert patches
    scores = [float(patch["score"]) for patch in patches]  # type: ignore[index]
    assert min(scores) == 0.0
    assert max(scores) == 1.0
    assert all(0.0 <= score <= 1.0 for score in scores)
    top_scores = [float(patch["score"]) for patch in top]  # type: ignore[index]
    assert len(top) == min(10, len(patches))
    assert top_scores == sorted(top_scores, reverse=True)
    assert top_scores == sorted(scores, reverse=True)[: len(top)]
    for patch in [*patches, *top]:
        assert set(patch) == {"x", "y", "size", "score"}  # type: ignore[arg-type]


def _rank(body: dict[str, object]) -> list[tuple[int, int]]:
    patches = body["patches"]
    assert isinstance(patches, list)
    ordered = sorted(
        patches,
        key=lambda patch: (-float(patch["score"]), int(patch["y"]), int(patch["x"])),
    )
    return [(int(patch["x"]), int(patch["y"])) for patch in ordered]


def _concept_vectors(url: str, concept_id: str) -> tuple[np.ndarray, np.ndarray | None]:
    conn = connect(url)
    try:
        row = conn.execute(
            "select embedding, negative_embedding from concept where id = %s",
            (concept_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None and row[0] is not None
    negative = None if row[1] is None else _as_array(row[1])
    return _as_array(row[0]), negative


def _numpy_order(
    url: str,
    slide_id: str,
    positive: np.ndarray,
    negative: np.ndarray | None,
) -> list[tuple[int, int]]:
    conn = connect(url)
    try:
        rows = conn.execute(
            "select x, y, embedding from patch where slide_id = %s",
            (slide_id,),
        ).fetchall()
    finally:
        conn.close()
    raw: list[tuple[int, int, float]] = []
    for x, y, embedding in rows:
        similarity = _cosine(_as_array(embedding), positive)
        if negative is not None:
            similarity -= _cosine(_as_array(embedding), negative)
        raw.append((int(x), int(y), similarity))
    scores = normalise_scores([item[2] for item in raw])
    ranked = sorted(
        ((x, y, score) for (x, y, _), score in zip(raw, scores, strict=True)),
        key=lambda item: (-item[2], item[1], item[0]),
    )
    return [(item[0], item[1]) for item in ranked]


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right)))


def _as_array(value: object) -> np.ndarray:
    if isinstance(value, HalfVector):
        return np.asarray(value.to_numpy(), dtype=np.float64)
    return np.asarray(value, dtype=np.float64)


def _assert_degenerate_slides(world: HeatmapWorld) -> None:
    conn = connect(world.database_url)
    try:
        conn.execute(
            """
            update patch
            set embedding = (
                select embedding from patch where slide_id = %s limit 1
            )
            where slide_id = %s
            """,
            (world.other_slide_id, world.other_slide_id),
        )
        conn.commit()
    finally:
        conn.close()
    flat = world.client.post(
        f"/api/slides/{world.other_slide_id}/heatmap",
        json={"text": "fibrosis"},
    )
    assert flat.status_code == 200
    flat_scores = [patch["score"] for patch in flat.json()["patches"]]
    assert flat_scores
    assert flat_scores == [0.0 for _ in flat_scores]

    conn = connect(world.database_url)
    try:
        conn.execute("delete from patch where slide_id = %s", (world.other_slide_id,))
        conn.commit()
    finally:
        conn.close()
    empty = world.client.post(
        f"/api/slides/{world.other_slide_id}/heatmap",
        json={"text": "fibrosis"},
    )
    assert empty.status_code == 200
    assert empty.json()["patches"] == []
    assert empty.json()["top"] == []
    _assert_notice(empty.json()["notice"], truncated=False)


def _insert_patches(url: str, slide_id: str, count: int) -> None:
    rng = np.random.default_rng(267)
    vectors: list[HalfVector] = []
    for _ in range(32):
        values = rng.standard_normal(768)
        values = values / np.linalg.norm(values)
        stored = values.astype(np.float16).astype(np.float64)
        vectors.append(HalfVector([float(item) for item in stored]))
    conn = connect(url)
    try:
        meta = conn.execute(
            """
            select s.case_id, c.patient_id, c.specialty
            from slide s
            join path_case c on c.id = s.case_id
            where s.id = %s
            """,
            (slide_id,),
        ).fetchone()
        assert meta is not None
        rows = [
            (
                slide_id,
                meta[0],
                meta[1],
                meta[2],
                (index % 64) * 512,
                10_000_000 + (index // 64) * 512,
                512,
                vectors[index % len(vectors)],
                False,
                0,
                1,
            )
            for index in range(count)
        ]
        with conn.cursor() as cur:
            cur.executemany(
                """
                insert into patch (
                    slide_id, case_id, patient_id, specialty, x, y, size, embedding,
                    in_corpus, thumb_offset, thumb_length
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
        conn.commit()
    finally:
        conn.close()


def _explain(conn: Connection, slide_id: str, *, force_index: bool = False) -> str:
    vector = conn.execute(
        "select embedding from concept where embedding is not null limit 1"
    ).fetchone()
    assert vector is not None
    statement = "explain " + POSITIVE_HEATMAP_SQL
    if not force_index:
        rows = conn.execute(statement, (vector[0], slide_id)).fetchall()
        return "\n".join(row[0] for row in rows)
    with conn.transaction():
        conn.execute("set local enable_seqscan = off")
        rows = conn.execute(statement, (vector[0], slide_id)).fetchall()
    return "\n".join(row[0] for row in rows)
