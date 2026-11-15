"""Search routes on a migrated, seeded Postgres database.

Encoders are `MockTextEncoder` (no weights). HNSW iterative scan is asserted
against the installed pgvector. Smoke/demo latency is rechecked after SKO-269
loads the real cohort; these timings are the fixture corpus only.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.api.schemas.search import (  # pragma: allowlist secret
    PatchSearchRequest,
    ReportSearchRequest,
)
from consilium.config import SearchBackend, Settings  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import seed  # pragma: allowlist secret
from consilium.embed.text import (  # pragma: allowlist secret
    MockTextEncoder,
    ReportTextKind,
    TextEncoders,
    build_text_encoders,
)
from consilium.search import (  # pragma: allowlist secret
    HNSW_EF_SEARCH,
    HNSW_ITERATIVE_SCAN,
    case_precedent_text,
    configure_hnsw,
    search_patches,
    search_reports,
)
from consilium.search.common import fetchall, fetchone  # pragma: allowlist secret

OPEN_BREAST = "breast-FX-B042C"
SIGNED_BREAST_PRIOR = "breast-FX-B042A"
SIGNED_BREAST_LATER = "breast-FX-B042B"
SIGNED_THORAX = "thorax-FX-T007A"
OPEN_THORAX = "thorax-FX-T019A"
PATIENT = "pt-0042"
PATIENT_LABEL = "PT-0042"


@pytest.fixture
def seeded(empty_database: str, tmp_path: Path) -> str:
    migrate(empty_database, search_backend=SearchBackend.PGVECTOR)
    seed(empty_database, tmp_path)
    return empty_database


@pytest.fixture
def encoders() -> TextEncoders:
    return build_text_encoders(backend=MockTextEncoder())


@pytest.fixture
def client(seeded: str, encoders: TextEncoders) -> Iterator[TestClient]:
    app = create_app(Settings(database_url=seeded))
    # Lifespan keeps an encoder already placed on app.state (same hook as SKO-267).
    app.state.text_encoders = encoders
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def facts(seeded: str) -> dict[str, Any]:
    with connect(seeded) as conn:
        patch = fetchone(
            conn,
            """
            SELECT p.id, p.slide_id, p.case_id
            FROM patch p
            WHERE p.case_id = %s AND p.in_corpus
            ORDER BY p.id
            LIMIT 1
            """,
            (SIGNED_THORAX,),
        )
        breast = fetchone(
            conn,
            """
            SELECT id FROM slide
            WHERE case_id = %s
            ORDER BY ordinal
            LIMIT 1
            """,
            (SIGNED_BREAST_PRIOR,),
        )
        withheld = fetchall(
            conn,
            """
            SELECT r.body, r.conclusion, r.microscopic_description, r.gross_description,
                   r.additional_info, r.clinical_history, r.icd10, c.primary_diagnosis,
                   c.morphology
            FROM report r
            JOIN path_case c ON c.id = r.case_id
            WHERE r.status = 'withheld'
            """,
        )
        signed_chunks = {
            str(row["text"])
            for row in fetchall(
                conn,
                """
                SELECT text FROM report_chunk ch
                JOIN report r ON r.id = ch.report_id
                WHERE r.status = 'signed' AND ch.in_corpus
                """,
            )
        }
        signed_sections: set[str] = set()
        for row in fetchall(
            conn,
            """
            SELECT body, conclusion, microscopic_description, gross_description,
                   additional_info, clinical_history
            FROM report WHERE status = 'signed'
            """,
        ):
            for value in row.values():
                if value:
                    signed_sections.add(str(value))
        secrets: list[str] = []
        for row in withheld:
            for value in row.values():
                if not value:
                    continue
                text = str(value)
                if text in signed_chunks or text in signed_sections:
                    continue
                # Shared labels (the diagnosis line) also appear inside signed
                # conclusions. Only prose that is unique to a withheld report counts.
                if any(text in section for section in signed_sections):
                    continue
                if len(text) < 24:
                    continue
                secrets.append(text)
        assert patch is not None and breast is not None
        assert secrets
    return {
        "patch_id": int(patch["id"]),
        "thorax_slide": str(patch["slide_id"]),
        "breast_slide": str(breast["id"]),
        "secrets": secrets,
    }


def _post(client: TestClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _hits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "slide" in payload and "reports" in payload:
        return list(payload["slide"]["hits"]) + list(payload["reports"]["hits"])
    return list(payload.get("hits", []))


def _assert_safe(
    payload: dict[str, Any],
    *,
    secrets: list[str],
    context_id: str | None,
    evidence: bool,
) -> None:
    blob = json.dumps(payload)
    for secret in secrets:
        assert secret not in blob
    for hit in _hits(payload):
        case = hit["case"]
        assert "primary_diagnosis" not in case
        assert "morphology" not in case
        if context_id is not None:
            assert case["id"] != context_id
        if evidence:
            assert case["status"] == "signed_out"
        if case["status"] == "open":
            assert case["icd10"] is None
            assert case["conclusion_line"] is None
            assert hit["passage"] is None
        passage = hit.get("passage")
        if passage is not None:
            text = passage["text"]
            for start, end in passage["highlights"]:
                assert 0 <= start < end <= len(text)
        assert len(hit["patches"]) <= 3
        assert hit["patch_match_count"] >= len(hit["patches"])
        assert 0 <= hit["score"] <= 1


def test_patch_queries_group_filter_and_slide_scope(
    client: TestClient,
    facts: dict[str, Any],
) -> None:
    empty = client.post("/api/search/patches", json={})
    assert empty.status_code == 422
    both = client.post(
        "/api/search/patches",
        json={"text": "glands", "patch_id": facts["patch_id"]},
    )
    assert both.status_code == 422

    bare = client.post(
        "/api/search/patches",
        json={
            "region": {
                "slide_id": facts["breast_slide"],
                "x": 9000,
                "y": 9000,
                "width": 10,
                "height": 10,
            }
        },
    )
    assert bare.status_code == 422
    assert "no tissue" in bare.json()["error"]["message"]

    missing = client.post("/api/search/patches", json={"patch_id": 999999})
    assert missing.status_code == 404

    q1 = _post(
        client,
        "/api/search/patches",
        {"patch_id": facts["patch_id"], "context_case_id": OPEN_BREAST},
    )
    assert q1["query_kind"] == "patch"
    assert q1["took_ms"] >= 0
    assert q1["total_candidates"] > 0
    assert q1["hits"]
    assert q1["hits"][0]["score"] == 1
    assert q1["total_candidates"] == sum(hit["patch_match_count"] for hit in q1["hits"])
    ids = [hit["case"]["id"] for hit in q1["hits"]]
    assert SIGNED_THORAX not in ids
    assert OPEN_BREAST not in ids
    assert all(hit["case"]["status"] == "signed_out" for hit in q1["hits"])
    assert all(hit["matched_by"] == ["morphology"] for hit in q1["hits"])
    assert all(hit["passage"] is None for hit in q1["hits"])
    bests = [hit["patches"][0]["similarity"] for hit in q1["hits"]]
    assert bests == sorted(bests, reverse=True)
    for hit in q1["hits"]:
        similarities = [patch["similarity"] for patch in hit["patches"]]
        assert similarities == sorted(similarities, reverse=True)
        assert len(hit["patches"]) == min(3, hit["patch_match_count"])
        assert hit["patch_match_count"] in {12, 20}
    same = [hit for hit in q1["hits"] if hit["case"]["patient"]["id"] == PATIENT]
    assert same
    assert all(hit["same_patient"] is True for hit in same)
    assert all(hit["same_patient"] is False for hit in q1["hits"] if hit not in same)

    q2 = _post(
        client,
        "/api/search/patches",
        {
            "region": {
                "slide_id": facts["breast_slide"],
                "x": 0,
                "y": 0,
                "width": 512,
                "height": 512,
            },
            "context_case_id": OPEN_BREAST,
        },
    )
    assert q2["query_kind"] == "region"
    assert SIGNED_BREAST_PRIOR not in [hit["case"]["id"] for hit in q2["hits"]]
    assert any(
        hit["case"]["id"] == SIGNED_BREAST_LATER and hit["same_patient"] for hit in q2["hits"]
    )

    q3 = _post(
        client,
        "/api/search/patches",
        {"slide_id": facts["thorax_slide"], "context_case_id": OPEN_BREAST},
    )
    assert q3["query_kind"] == "slide"
    assert SIGNED_THORAX not in [hit["case"]["id"] for hit in q3["hits"]]
    assert all(hit["patches"] for hit in q3["hits"])

    q4 = _post(
        client,
        "/api/search/patches",
        {"text": "gland-forming epithelial proliferation", "context_case_id": OPEN_BREAST},
    )
    assert q4["query_kind"] == "text_patches"
    assert all(hit["matched_by"] == ["morphology"] for hit in q4["hits"])

    thorax = _post(
        client,
        "/api/search/patches",
        {
            "text": "alveolar spaces",
            "context_case_id": OPEN_BREAST,
            "filters": {"specialty": ["thorax"]},
        },
    )
    assert {hit["case"]["specialty"] for hit in thorax["hits"]} == {"thorax"}
    assert {hit["case"]["id"] for hit in thorax["hits"]} == {SIGNED_THORAX}

    patient = _post(
        client,
        "/api/search/patches",
        {
            "patch_id": facts["patch_id"],
            "context_case_id": SIGNED_THORAX,
            "filters": {"patient_id": PATIENT},
        },
    )
    assert {hit["case"]["id"] for hit in patient["hits"]} == {
        SIGNED_BREAST_PRIOR,
        SIGNED_BREAST_LATER,
    }
    assert all(hit["same_patient"] is False for hit in patient["hits"])

    icd = _post(
        client,
        "/api/search/patches",
        {"text": "tissue", "filters": {"icd10_prefix": "C34"}},
    )
    assert {hit["case"]["id"] for hit in icd["hits"]} == {SIGNED_THORAX}
    assert all(hit["case"]["icd10"].startswith("C34") for hit in icd["hits"])

    stained = _post(
        client,
        "/api/search/patches",
        {"text": "tissue", "filters": {"stain": "HE", "status": "signed_out"}},
    )
    assert stained["hits"]
    assert all(hit["case"]["status"] == "signed_out" for hit in stained["hits"])
    none = _post(client, "/api/search/patches", {"text": "tissue", "filters": {"stain": "PAS"}})
    assert none["hits"] == []

    opened = _post(
        client,
        "/api/search/patches",
        {"text": "glands", "filters": {"status": "open"}},
    )
    assert opened["hits"] == []

    scoped = _post(
        client,
        "/api/search/patches",
        {"patch_id": facts["patch_id"], "scope": "slide"},
    )
    assert "hits" not in scoped
    assert scoped["query_kind"] == "patch"
    assert scoped["patches"]
    assert facts["patch_id"] not in [patch["patch_id"] for patch in scoped["patches"]]
    assert {patch["slide_id"] for patch in scoped["patches"]} == {facts["thorax_slide"]}
    assert scoped["total_candidates"] >= len(scoped["patches"])

    slide_text = _post(
        client,
        "/api/search/patches",
        {"text": "alveolar", "scope": "slide", "context_case_id": SIGNED_THORAX},
    )
    assert slide_text["query_kind"] == "text_patches"
    assert {patch["slide_id"] for patch in slide_text["patches"]} == {facts["thorax_slide"]}

    refused = client.post(
        "/api/search/patches",
        json={"slide_id": facts["thorax_slide"], "scope": "slide"},
    )
    assert refused.status_code == 422


def test_report_modes_highlights_exact_match_and_filters(
    client: TestClient,
    seeded: str,
) -> None:
    keyword = _post(
        client,
        "/api/search/reports",
        {"text": "calcifications", "mode": "keyword", "context_case_id": OPEN_BREAST},
    )
    assert keyword["query_kind"] == "reports"
    assert keyword["hits"]
    assert keyword["hits"][0]["score"] == 1
    assert {hit["case"]["id"] for hit in keyword["hits"]} == {
        SIGNED_BREAST_PRIOR,
        SIGNED_BREAST_LATER,
    }
    for hit in keyword["hits"]:
        assert hit["matched_by"] == ["keyword"]
        assert hit["patches"] == []
        assert hit["same_patient"] is True
        passage = hit["passage"]
        assert passage["section"] == "microscopic_description"
        assert passage["highlights"]
        text = passage["text"]
        marked = [text[start:end].lower() for start, end in passage["highlights"]]
        assert "calcifications" in marked

    semantic = _post(client, "/api/search/reports", {"text": "glands", "mode": "semantic"})
    assert semantic["hits"]
    assert all(hit["matched_by"] == ["semantic"] for hit in semantic["hits"])
    assert all(hit["passage"]["highlights"] == [] for hit in semantic["hits"])
    assert all(hit["same_patient"] is False for hit in semantic["hits"])

    hybrid = _post(
        client,
        "/api/search/reports",
        {"text": "calcifications", "mode": "hybrid", "context_case_id": OPEN_BREAST},
    )
    assert all("keyword" in hit["matched_by"] for hit in hybrid["hits"][:2])
    assert hybrid["hits"][0]["passage"]["highlights"]

    by_case = _post(client, "/api/search/reports", {"text": "BREAST-fx-b042a", "mode": "hybrid"})
    assert by_case["hits"][0]["case"]["id"] == SIGNED_BREAST_PRIOR

    by_patient = _post(client, "/api/search/reports", {"text": PATIENT_LABEL, "mode": "keyword"})
    assert [hit["case"]["id"] for hit in by_patient["hits"][:3]] == [
        OPEN_BREAST,
        SIGNED_BREAST_LATER,
        SIGNED_BREAST_PRIOR,
    ]
    open_hit = by_patient["hits"][0]
    assert open_hit["case"]["status"] == "open"
    assert open_hit["case"]["icd10"] is None
    assert open_hit["case"]["conclusion_line"] is None
    assert open_hit["passage"] is None

    by_id = _post(client, "/api/search/reports", {"text": PATIENT, "mode": "semantic"})
    assert [hit["case"]["id"] for hit in by_id["hits"][:3]] == [
        OPEN_BREAST,
        SIGNED_BREAST_LATER,
        SIGNED_BREAST_PRIOR,
    ]

    coded = _post(client, "/api/search/reports", {"text": "c50.9", "mode": "hybrid"})
    assert [hit["case"]["id"] for hit in coded["hits"][:2]] == [
        SIGNED_BREAST_LATER,
        SIGNED_BREAST_PRIOR,
    ]
    assert all(hit["case"]["icd10"] == "C50.9" for hit in coded["hits"][:2])
    assert OPEN_BREAST not in [hit["case"]["id"] for hit in coded["hits"]]

    evidence = _post(
        client,
        "/api/search/reports",
        {"text": PATIENT_LABEL, "mode": "keyword", "context_case_id": OPEN_BREAST},
    )
    evidence_ids = [hit["case"]["id"] for hit in evidence["hits"]]
    assert evidence_ids[:2] == [SIGNED_BREAST_LATER, SIGNED_BREAST_PRIOR]
    assert OPEN_BREAST not in evidence_ids
    assert all(hit["same_patient"] is True for hit in evidence["hits"][:2])

    hidden = _post(
        client,
        "/api/search/reports",
        {"text": SIGNED_BREAST_PRIOR, "context_case_id": SIGNED_BREAST_PRIOR},
    )
    assert SIGNED_BREAST_PRIOR not in [hit["case"]["id"] for hit in hidden["hits"]]

    thorax = _post(
        client,
        "/api/search/reports",
        {"text": "alveolar", "mode": "keyword", "filters": {"specialty": ["thorax"]}},
    )
    assert {hit["case"]["id"] for hit in thorax["hits"]} == {SIGNED_THORAX}

    prefix = _post(
        client,
        "/api/search/reports",
        {"text": "glands", "mode": "keyword", "filters": {"icd10_prefix": "C18"}},
    )
    assert prefix["hits"]
    assert {hit["case"]["specialty"] for hit in prefix["hits"]} == {"colorectal"}

    patient = _post(
        client,
        "/api/search/reports",
        {
            "text": "glands",
            "mode": "keyword",
            "context_case_id": SIGNED_THORAX,
            "filters": {"patient_id": PATIENT},
        },
    )
    assert {hit["case"]["patient"]["id"] for hit in patient["hits"]} == {PATIENT}
    assert all(hit["same_patient"] is False for hit in patient["hits"])

    signed_only = _post(
        client,
        "/api/search/reports",
        {"text": PATIENT_LABEL, "filters": {"status": "signed_out"}},
    )
    assert OPEN_BREAST not in [hit["case"]["id"] for hit in signed_only["hits"]]
    assert all(hit["case"]["status"] == "signed_out" for hit in signed_only["hits"])

    open_only = _post(
        client,
        "/api/search/reports",
        {"text": "carcinoma", "mode": "keyword", "filters": {"status": "open"}},
    )
    assert open_only["hits"] == []
    looked_up = _post(
        client,
        "/api/search/reports",
        {"text": OPEN_BREAST, "filters": {"status": "open"}},
    )
    assert [hit["case"]["id"] for hit in looked_up["hits"]] == [OPEN_BREAST]
    assert looked_up["hits"][0]["passage"] is None
    assert looked_up["hits"][0]["case"]["icd10"] is None

    blank = client.post("/api/search/reports", json={"text": " "})
    assert blank.status_code == 422
    unknown = client.post(
        "/api/search/reports",
        json={"text": "glands", "context_case_id": "missing-case"},
    )
    assert unknown.status_code == 404

    with connect(seeded) as conn:
        direct = search_reports(
            conn,
            ReportSearchRequest(text="calcifications", mode="keyword", context_case_id=OPEN_BREAST),
            build_text_encoders(backend=MockTextEncoder()),
        )
    assert [hit.case.id for hit in direct.hits] == [hit["case"]["id"] for hit in keyword["hits"]]


def test_similar_uses_clinical_history_for_open_cases(
    client: TestClient,
    seeded: str,
    encoders: TextEncoders,
) -> None:
    with connect(seeded) as conn:
        history = case_precedent_text(conn, OPEN_BREAST)
        conclusion = case_precedent_text(conn, SIGNED_BREAST_PRIOR)
    assert history is not None and conclusion is not None
    assert "Invasive carcinoma" not in history
    assert "8500/3" not in history
    assert "Invasive carcinoma" in conclusion

    similar = client.get(f"/api/cases/{OPEN_BREAST}/similar")
    assert similar.status_code == 200
    body = similar.json()
    assert body["slide"]["query_kind"] == "slide"
    assert body["reports"]["query_kind"] == "reports"
    assert OPEN_BREAST not in [hit["case"]["id"] for hit in body["slide"]["hits"]]
    assert OPEN_BREAST not in [hit["case"]["id"] for hit in body["reports"]["hits"]]
    assert any(hit["same_patient"] is True for hit in body["slide"]["hits"])

    direct = _post(
        client,
        "/api/search/reports",
        {"text": history, "mode": "hybrid", "context_case_id": OPEN_BREAST},
    )
    other = _post(
        client,
        "/api/search/reports",
        {"text": conclusion, "mode": "hybrid", "context_case_id": OPEN_BREAST},
    )
    assert [hit["case"]["id"] for hit in body["reports"]["hits"]] == [
        hit["case"]["id"] for hit in direct["hits"]
    ]
    assert [hit["case"]["id"] for hit in direct["hits"]] != [
        hit["case"]["id"] for hit in other["hits"]
    ]

    signed = client.get(f"/api/cases/{SIGNED_BREAST_PRIOR}/similar")
    assert signed.status_code == 200
    assert SIGNED_BREAST_PRIOR not in [
        hit["case"]["id"] for hit in signed.json()["slide"]["hits"]
    ]
    missing = client.get("/api/cases/not-a-case/similar")
    assert missing.status_code == 404

    with connect(seeded) as conn:
        found = search_patches(
            conn,
            PatchSearchRequest(slide_id=f"{SIGNED_THORAX}-s1", context_case_id=OPEN_BREAST),
            encoders,
        )
    assert found.query_kind == "slide"
    assert all(hit.case.id != OPEN_BREAST for hit in found.hits)  # type: ignore[union-attr]


def test_responses_never_leak_withheld_text(
    client: TestClient,
    facts: dict[str, Any],
) -> None:
    secrets: list[str] = facts["secrets"]
    requests: list[tuple[str, str, dict[str, Any] | None, str | None, bool]] = [
        (
            "post",
            "/api/search/patches",
            {"patch_id": facts["patch_id"], "context_case_id": OPEN_BREAST},
            OPEN_BREAST,
            True,
        ),
        (
            "post",
            "/api/search/patches",
            {
                "region": {
                    "slide_id": facts["breast_slide"],
                    "x": 0,
                    "y": 0,
                    "width": 400,
                    "height": 400,
                },
                "context_case_id": OPEN_BREAST,
            },
            OPEN_BREAST,
            True,
        ),
        (
            "post",
            "/api/search/patches",
            {"slide_id": facts["thorax_slide"], "context_case_id": SIGNED_BREAST_PRIOR},
            SIGNED_BREAST_PRIOR,
            True,
        ),
        (
            "post",
            "/api/search/patches",
            {"text": "61-year-old recurrence excision", "context_case_id": OPEN_BREAST},
            OPEN_BREAST,
            True,
        ),
        (
            "post",
            "/api/search/patches",
            {"patch_id": facts["patch_id"], "scope": "slide"},
            None,
            False,
        ),
        (
            "post",
            "/api/search/reports",
            {"text": "recurrence excision", "mode": "keyword"},
            None,
            False,
        ),
        (
            "post",
            "/api/search/reports",
            {"text": "61-year-old", "mode": "hybrid", "context_case_id": OPEN_BREAST},
            OPEN_BREAST,
            True,
        ),
        (
            "post",
            "/api/search/reports",
            {"text": "c50.9", "mode": "semantic", "context_case_id": OPEN_THORAX},
            OPEN_THORAX,
            True,
        ),
        (
            "post",
            "/api/search/reports",
            {"text": PATIENT_LABEL, "mode": "hybrid"},
            None,
            False,
        ),
        ("get", f"/api/cases/{OPEN_BREAST}/similar", None, OPEN_BREAST, True),
        ("get", f"/api/cases/{SIGNED_THORAX}/similar", None, SIGNED_THORAX, True),
    ]
    for method, path, payload, context_id, evidence in requests:
        if method == "get":
            response = client.get(path)
        else:
            response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        _assert_safe(
            response.json(),
            secrets=secrets,
            context_id=context_id,
            evidence=evidence,
        )


def test_hnsw_iterative_scan_and_separate_spaces(
    seeded: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with connect(seeded) as conn:
        version = fetchone(conn, "SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        assert version is not None
        assert str(version["extversion"]).startswith("0.8")
        with conn.transaction():
            configure_hnsw(conn)
            row = fetchone(
                conn,
                """
                SELECT current_setting('hnsw.iterative_scan') AS scan,
                       current_setting('hnsw.ef_search') AS ef
                """,
            )
        assert row is not None
        assert row["scan"] == HNSW_ITERATIVE_SCAN == "relaxed_order"
        assert int(row["ef"]) == HNSW_EF_SEARCH

    seen: dict[str, str] = {}

    def _spy(conn: Any) -> None:
        configure_hnsw(conn)
        current = fetchone(
            conn,
            """
            SELECT current_setting('hnsw.iterative_scan') AS scan,
                   current_setting('hnsw.ef_search') AS ef
            """,
        )
        assert current is not None
        seen["scan"] = str(current["scan"])
        seen["ef"] = str(current["ef"])

    monkeypatch.setattr("consilium.search.patches.configure_hnsw", _spy)  # pragma: allowlist secret
    monkeypatch.setattr("consilium.search.reports.configure_hnsw", _spy)  # pragma: allowlist secret

    class _SpyEncoder(MockTextEncoder):
        def __init__(self) -> None:
            self.conch = 0
            self.report = 0

        def encode_conchz(self, texts: Any) -> list[Any]:
            self.conch += 1
            return super().encode_conchz(texts)

        def encode_report(self, texts: Any, *, kind: ReportTextKind) -> list[Any]:
            self.report += 1
            return super().encode_report(texts, kind=kind)

    backend = _SpyEncoder()
    encoders = build_text_encoders(backend=backend)
    with connect(seeded) as conn:
        search_patches(conn, PatchSearchRequest(text="desmoplastic stroma"), encoders)
        assert seen["scan"] == "relaxed_order"
        assert int(seen["ef"]) == HNSW_EF_SEARCH
        assert backend.conch == 1
        assert backend.report == 0
        search_reports(conn, ReportSearchRequest(text="calcifications", mode="hybrid"), encoders)
        assert backend.conch == 1
        assert backend.report == 1


def test_warm_fixture_latency(client: TestClient, facts: dict[str, Any]) -> None:
    patch_body = {"patch_id": facts["patch_id"], "context_case_id": OPEN_BREAST}
    report_body = {"text": "calcifications", "mode": "hybrid", "context_case_id": OPEN_BREAST}
    assert client.post("/api/search/patches", json=patch_body).status_code == 200
    assert client.post("/api/search/reports", json=report_body).status_code == 200
    started = time.perf_counter()
    patch = client.post("/api/search/patches", json=patch_body)
    patch_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    report = client.post("/api/search/reports", json=report_body)
    report_ms = (time.perf_counter() - started) * 1000
    assert patch.status_code == 200
    assert report.status_code == 200
    # F-05.13 budgets (2s patch, 3s text) apply to the demo cohort once SKO-269
    # loads it. The fixture corpus is the check that runs here.
    assert patch_ms < 2000
    assert report_ms < 3000
    print(f"SEARCH_TIMING patch_ms={patch_ms:.1f} report_ms={report_ms:.1f}")
