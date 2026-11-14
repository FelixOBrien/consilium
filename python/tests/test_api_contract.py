"""Stub API contract: routes, withholding, headers, search, heatmap and SSE."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.api.store import (  # pragma: allowlist secret
    CASE_OPEN_BREAST,
    CASE_SIGNED_BREAST,
    CASE_SIGNED_THORAX,
    DEMO_USER_ID,
    OTHER_USER_ID,
    PATCH_BREAST,
    PATCH_THORAX,
    PATIENT_MULTI_ID,
    SEEDED_ANNOTATION_ID,
    SEEDED_JOB_ID,
    SEEDED_THREAD_ID,
    SLIDE_SIGNED_BREAST,
    SLIDE_SIGNED_THORAX,
)

ARCHITECTURE_ROUTES = {
    ("get", "/api/pathologists"),
    ("get", "/api/me"),
    ("get", "/api/patients"),
    ("get", "/api/patients/{patient_id}"),
    ("get", "/api/cases"),
    ("get", "/api/cases/{case_id}"),
    ("get", "/api/cases/{case_id}/report"),
    ("get", "/api/cases/{case_id}/similar"),
    ("get", "/api/slides/{slide_id}"),
    ("get", "/api/slides/{slide_id}.dzi"),
    ("get", "/api/slides/{slide_id}_files/{level}/{col}_{row}.jpeg"),
    ("get", "/api/slides/{slide_id}/thumbnail"),
    ("get", "/api/slides/{slide_id}/patches/at"),
    ("get", "/api/patches/{patch_id}"),
    ("get", "/api/patches/{patch_id}/thumbnail"),
    ("post", "/api/search/reports"),
    ("post", "/api/search/patches"),
    ("get", "/api/concepts"),
    ("post", "/api/slides/{slide_id}/heatmap"),
    ("get", "/api/slides/{slide_id}/annotations"),
    ("post", "/api/slides/{slide_id}/annotations"),
    ("patch", "/api/annotations/{annotation_id}"),
    ("delete", "/api/annotations/{annotation_id}"),
    ("post", "/api/cases/{case_id}/consult/threads"),
    ("get", "/api/consult/threads/{thread_id}"),
    ("post", "/api/consult/threads/{thread_id}/messages"),
    ("post", "/api/ingestion/jobs"),
    ("get", "/api/ingestion/jobs"),
    ("get", "/api/ingestion/jobs/{job_id}"),
    ("get", "/api/health"),
}

NEVER_SENT = {
    "embedding",
    "negative_embedding",
    "storage_key",
    "thumb_pack_key",
    "source_path",
    "thumb_offset",
    "thumb_length",
    "in_corpus",
    "search_tsv",
    "is_held_out",
    "source_dataset",
    "source_case_id",
    "cohort_tier",
    "morphology",
    "primary_diagnosis",
    "input_tokens",
    "output_tokens",
    "worker_id",
}


def _client() -> TestClient:
    return TestClient(create_app(use_stub_store=True))


def test_openapi_lists_architecture_routes() -> None:
    schema = create_app().openapi()
    found: set[tuple[str, str]] = set()
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method not in {"get", "post", "patch", "delete"}:
                continue
            assert operation.get("operationId"), path
            found.add((method, path))
    assert found == ARCHITECTURE_ROUTES


def test_response_models_omit_never_sent_fields() -> None:
    schemas = create_app().openapi()["components"]["schemas"]
    leaked: list[tuple[str, str]] = []
    for name, body in schemas.items():
        for field in body.get("properties", {}):
            if field in NEVER_SENT:
                leaked.append((name, field))
    assert leaked == []
    trace = schemas["ToolTraceStep"]["properties"]
    assert "input" not in trace
    report_status = json.dumps(schemas["Report"]["properties"]["status"])
    open_status = json.dumps(schemas["ReportNotReported"]["properties"]["status"])
    assert "withheld" not in report_status
    assert "withheld" not in open_status


def test_error_envelope_and_unknown_user() -> None:
    with _client() as client:
        missing = client.get("/api/me")
        assert missing.status_code == 200
        assert missing.json()["id"] == DEMO_USER_ID
        assert missing.json()["is_demo_user"] is True
        assert missing.json()["is_synthetic"] is True

        other = client.get("/api/me", headers={"X-User-Id": OTHER_USER_ID})
        assert other.status_code == 200
        assert other.json()["id"] == OTHER_USER_ID
        assert other.json()["is_synthetic"] is True

        unknown = client.get("/api/me", headers={"X-User-Id": "path-missing"})
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "unknown_user"

        invalid = client.post("/api/slides/not-a-slide/heatmap", json={})
        assert invalid.status_code == 422
        body = invalid.json()["error"]
        assert body["code"] == "validation_error"
        assert body["fields"]

        missing_route = client.get("/api/missing")
        assert missing_route.status_code == 404
        assert missing_route.json()["error"]["code"] == "not_found"


def test_roster_is_synthetic() -> None:
    with _client() as client:
        roster = client.get("/api/pathologists").json()
    assert sum(person["is_demo_user"] for person in roster) == 1
    assert all(person["is_synthetic"] is True for person in roster)


def test_open_case_withholds_diagnosis() -> None:
    with _client() as client:
        listed = client.get("/api/cases").json()["items"]
        open_row = next(row for row in listed if row["id"] == CASE_OPEN_BREAST)
        assert open_row["status"] == "open"
        assert open_row["icd10"] is None
        assert open_row["conclusion_line"] is None
        assert open_row["patient"]["is_synthetic_linkage"] is True

        detail = client.get(f"/api/cases/{CASE_OPEN_BREAST}").json()
        assert detail["report_status"] == "none"
        assert "primary_diagnosis" not in detail
        assert "morphology" not in detail
        assert "is_held_out" not in detail

        report = client.get(f"/api/cases/{CASE_OPEN_BREAST}/report")
        assert report.status_code == 200
        payload = report.json()
        assert set(payload) == {"case_id", "status", "clinical_history"}
        assert payload["status"] == "none"
        assert "diagnosis" not in payload["clinical_history"].lower()

        signed = client.get(f"/api/cases/{CASE_SIGNED_BREAST}/report").json()
        assert signed["status"] == "signed"
        assert signed["is_synthetic_author"] is True
        assert signed["author"]["is_synthetic"] is True
        assert signed["body"]
        assert signed["conclusion"]


def test_patient_timeline_orders_newest_first() -> None:
    with _client() as client:
        page = client.get("/api/patients", params={"multi_case": "true", "q": "pt-0042"})
        assert page.status_code == 200
        assert [row["id"] for row in page.json()["items"]] == [PATIENT_MULTI_ID]
        detail = client.get(f"/api/patients/{PATIENT_MULTI_ID}").json()
    assert detail["birth_year"] == 1966
    assert [case["id"] for case in detail["cases"]] == [CASE_OPEN_BREAST, CASE_SIGNED_BREAST]
    open_case = detail["cases"][0]
    assert open_case["icd10"] is None
    assert open_case["conclusion_line"] is None
    assert detail["cases"][1]["conclusion_line"]


def test_case_list_view_and_cursor() -> None:
    with _client() as client:
        mine = client.get("/api/cases", params={"view": "mine", "limit": 1})
        assert mine.status_code == 200
        body = mine.json()
        assert body["items"][0]["id"] == CASE_OPEN_BREAST
        assert body["items"][0]["assigned_to"]["id"] == DEMO_USER_ID
        nxt = client.get(
            "/api/cases",
            params={"view": "mine", "limit": 1, "cursor": body["next_cursor"]},
        )
        assert [row["id"] for row in nxt.json()["items"]] == [CASE_SIGNED_BREAST]
        bad = client.get("/api/cases", params={"cursor": "missing"})
        assert bad.status_code == 422
        assert bad.json()["error"]["code"] == "validation_error"


def test_search_excludes_open_and_context_cases() -> None:
    with _client() as client:
        empty = client.post("/api/search/patches", json={})
        assert empty.status_code == 422
        both = client.post(
            "/api/search/patches",
            json={"text": "glands", "patch_id": PATCH_BREAST},
        )
        assert both.status_code == 422

        found = client.post(
            "/api/search/patches",
            json={"text": "glands", "context_case_id": CASE_OPEN_BREAST},
        )
        assert found.status_code == 200
        hits = found.json()["hits"]
        ids = [hit["case"]["id"] for hit in hits]
        assert CASE_OPEN_BREAST not in ids
        assert all(hit["case"]["status"] == "signed_out" for hit in hits)
        same = next(hit for hit in hits if hit["case"]["id"] == CASE_SIGNED_BREAST)
        assert same["same_patient"] is True
        assert hits[0]["score"] == 1
        assert found.json()["query_kind"] == "text_patches"

        scoped = client.post(
            "/api/search/patches",
            json={"patch_id": PATCH_BREAST, "scope": "slide"},
        )
        assert scoped.status_code == 200
        assert "hits" not in scoped.json()
        assert scoped.json()["patches"][0]["patch_id"] != PATCH_BREAST

        bare = client.post(
            "/api/search/patches",
            json={
                "region": {
                    "slide_id": SLIDE_SIGNED_BREAST,
                    "x": 2000,
                    "y": 2000,
                    "width": 10,
                    "height": 10,
                }
            },
        )
        assert bare.status_code == 422
        assert "no tissue" in bare.json()["error"]["message"]

        reports = client.post(
            "/api/search/reports",
            json={"text": "carcinoma", "mode": "keyword", "context_case_id": CASE_OPEN_BREAST},
        )
        assert reports.status_code == 200
        passage = reports.json()["hits"][0]["passage"]
        assert passage["highlights"]
        assert reports.json()["hits"][0]["matched_by"] == ["keyword"]

        semantic = client.post(
            "/api/search/reports",
            json={"text": "glands", "mode": "semantic"},
        )
        assert semantic.json()["hits"][0]["passage"]["highlights"] == []

        filtered = client.post(
            "/api/search/patches",
            json={"text": "glands", "filters": {"specialty": ["thorax"]}},
        )
        assert {hit["case"]["specialty"] for hit in filtered.json()["hits"]} == {"thorax"}


def test_similar_returns_both_lists() -> None:
    with _client() as client:
        response = client.get(f"/api/cases/{CASE_OPEN_BREAST}/similar")
    assert response.status_code == 200
    body = response.json()
    assert body["slide"]["query_kind"] == "slide"
    assert body["reports"]["query_kind"] == "reports"
    assert CASE_OPEN_BREAST not in [hit["case"]["id"] for hit in body["slide"]["hits"]]


def test_heatmap_accepts_report_word_and_optional_concept() -> None:
    with _client() as client:
        word = client.post(f"/api/slides/{SLIDE_SIGNED_BREAST}/heatmap", json={"text": "necrosis"})
        assert word.status_code == 200
        body = word.json()
        assert body["text"] == "necrosis"
        assert body["concept_id"] is None
        assert body["source"] == "text"
        assert body["cluster"] is None
        scores = {patch["score"] for patch in body["patches"]}
        assert 0 in scores and 1 in scores
        assert "Not a finding" in body["notice"]
        assert "not a diagnosis" in body["notice"]
        assert body["top"][0]["score"] == 1
        assert [patch["score"] for patch in body["top"]] == sorted(
            (patch["score"] for patch in body["top"]),
            reverse=True,
        )

        negative = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/heatmap",
            json={"text": "necrosis", "negative_text": "normal tissue"},
        )
        assert negative.status_code == 200
        assert negative.json()["negative_text"] == "normal tissue"
        plain_top = (body["top"][0]["x"], body["top"][0]["y"])
        negative_top = (negative.json()["top"][0]["x"], negative.json()["top"][0]["y"])
        assert negative_top != plain_top

        concept = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/heatmap",
            json={"concept_id": "keratinisation"},
        )
        assert concept.status_code == 200
        assert concept.json()["concept_id"] == "keratinisation"
        assert concept.json()["text"].startswith("an H&E image")
        assert concept.json()["source"] == "concept"
        assert concept.json()["cluster"] is None

        both = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/heatmap",
            json={"text": "necrosis", "concept_id": "necrosis"},
        )
        assert both.status_code == 422

        missing = client.post(
            "/api/slides/missing/heatmap",
            json={"concept_id": "not-a-concept"},
        )
        assert missing.status_code == 404

        long_word = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/heatmap",
            json={"text": "necrosis " * 40},
        )
        assert long_word.status_code == 200
        assert long_word.json()["truncated"] is True
        assert "truncated" in long_word.json()["notice"]

        concepts = client.get("/api/concepts", params={"specialty": "breast"}).json()
        assert [row["id"] for row in concepts] == ["necrosis", "mitotic-figures"]
        assert all(set(row) == {"id", "label", "prompt", "specialty"} for row in concepts)


def test_stub_heatmap_accepts_patch_and_region() -> None:
    region = {"slide_id": SLIDE_SIGNED_BREAST, "x": 0, "y": 0, "width": 512, "height": 512}
    with _client() as client:
        grown = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/heatmap",
            json={"patch_id": PATCH_BREAST, "grow": True},
        )
        assert grown.status_code == 200
        body = grown.json()
        assert body["source"] == "patch"
        assert body["text"] == ""
        assert "selected tissue" in body["notice"]
        assert "Not a finding" in body["notice"]
        assert "not a diagnosis" in body["notice"]
        seed = next(patch for patch in body["patches"] if patch["x"] == 0 and patch["y"] == 0)
        assert seed["score"] == 1.0
        assert body["cluster"]["cells"] == [{"x": 0, "y": 0, "size": 512}]
        assert body["cluster"]["patch_count"] == 1
        assert body["cluster"]["bbox"] == {"x": 0, "y": 0, "width": 512, "height": 512}
        assert "embedding" not in grown.text

        plain = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/heatmap",
            json={"region": region, "grow": False},
        )
        assert plain.status_code == 200
        assert plain.json()["source"] == "region"
        assert plain.json()["cluster"] is None

        wrong = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/heatmap",
            json={"patch_id": PATCH_THORAX},
        )
        assert wrong.status_code == 422
        assert wrong.json()["error"]["code"] == "validation_error"
        assert "different slide" in wrong.json()["error"]["message"]

        mismatched = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/heatmap",
            json={
                "region": {
                    "slide_id": SLIDE_SIGNED_THORAX,
                    "x": 0,
                    "y": 0,
                    "width": 512,
                    "height": 512,
                }
            },
        )
        assert mismatched.status_code == 422
        assert "different slide" in mismatched.json()["error"]["message"]

        empty = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/heatmap",
            json={
                "region": {
                    "slide_id": SLIDE_SIGNED_BREAST,
                    "x": 9000,
                    "y": 9000,
                    "width": 10,
                    "height": 10,
                }
            },
        )
        assert empty.status_code == 422
        assert "no tissue" in empty.json()["error"]["message"]

        missing = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/heatmap",
            json={"patch_id": 999999},
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["message"] == "Patch not found."


def test_slide_and_patch_placeholders() -> None:
    with _client() as client:
        dzi = client.get(f"/api/slides/{SLIDE_SIGNED_BREAST}.dzi")
        assert dzi.status_code == 200
        assert dzi.headers["content-type"].startswith("application/xml")
        assert "Width=" in dzi.text and "Height=" in dzi.text

        tile = client.get(f"/api/slides/{SLIDE_SIGNED_BREAST}_files/0/1_2.jpeg")
        assert tile.status_code == 200
        assert tile.content.startswith(b"\xff\xd8")

        thumb = client.get(f"/api/patches/{PATCH_BREAST}/thumbnail")
        assert thumb.status_code == 200
        assert thumb.content.startswith(b"\xff\xd8")

        found = client.get(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/patches/at",
            params={"x": 10, "y": 10},
        )
        assert found.status_code == 200
        assert found.json()["id"] == PATCH_BREAST
        assert "embedding" not in found.json()

        glass = client.get(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/patches/at",
            params={"x": 2000, "y": 2000},
        )
        assert glass.status_code == 404


def test_annotation_author_only() -> None:
    with _client() as client:
        listed = client.get(f"/api/slides/{SLIDE_SIGNED_BREAST}/annotations")
        assert listed.status_code == 200
        assert listed.json()[0]["can_edit"] is True
        assert listed.json()[0]["author"]["is_synthetic"] is True

        denied = client.patch(
            f"/api/annotations/{SEEDED_ANNOTATION_ID}",
            headers={"X-User-Id": OTHER_USER_ID},
            json={"label": "nope"},
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "forbidden"

        updated = client.patch(
            f"/api/annotations/{SEEDED_ANNOTATION_ID}",
            json={"note": None},
        )
        assert updated.status_code == 200
        assert updated.json()["note"] is None

        created = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/annotations",
            headers={"X-User-Id": OTHER_USER_ID},
            json={"kind": "point", "geometry": {"x": 4, "y": 5}, "label": "point"},
        )
        assert created.status_code == 201
        assert created.json()["can_edit"] is True
        outside = client.post(
            f"/api/slides/{SLIDE_SIGNED_BREAST}/annotations",
            json={
                "kind": "rect",
                "geometry": {"x": 1, "y": 1, "width": 5000, "height": 10},
                "label": "too big",
            },
        )
        assert outside.status_code == 422

        removed = client.delete(
            f"/api/annotations/{created.json()['id']}",
            headers={"X-User-Id": OTHER_USER_ID},
        )
        assert removed.status_code == 204


def test_consult_stream_and_history() -> None:
    with _client() as client:
        history = client.get(f"/api/consult/threads/{SEEDED_THREAD_ID}")
        assert history.status_code == 200
        assert history.json()["case_id"] == CASE_OPEN_BREAST
        assert "input_tokens" not in json.dumps(history.json())

        hidden = client.get(
            f"/api/consult/threads/{SEEDED_THREAD_ID}",
            headers={"X-User-Id": OTHER_USER_ID},
        )
        assert hidden.status_code == 404

        response = client.post(
            f"/api/consult/threads/{SEEDED_THREAD_ID}/messages",
            json={"content": "Who should I consult?"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        names = [
            line.removeprefix("event: ").strip()
            for line in response.text.splitlines()
            if line.startswith("event:")
        ]
        assert names == ["step", "step", "text", "citations", "ranking", "done"]
        assert "does not diagnose" in response.text
        assert '"input":' not in response.text
        done = json.loads(response.text.split("event: done\ndata: ", 1)[1].split("\n", 1)[0])
        rank = done["message"]["ranking"][0]
        assert rank["case_count"] == len(rank["case_ids"])
        assert "input" not in done["message"]["tool_trace"][0]

        fresh = client.post(
            f"/api/cases/{CASE_SIGNED_THORAX}/consult/threads",
            json={"new": True},
        )
        assert fresh.status_code == 200
        assert fresh.json()["messages"] == []
        assert fresh.json()["id"] != str(SEEDED_THREAD_ID)


def test_ingestion_job_hides_worker_id() -> None:
    with _client() as client:
        listed = client.get("/api/ingestion/jobs")
        assert listed.status_code == 200
        assert "worker_id" not in listed.text
        created = client.post(
            "/api/ingestion/jobs",
            json={"dataset": "TCGA-BRCA", "slide_path": "sample.svs"},
        )
        assert created.status_code == 201
        assert created.json()["status"] == "queued"
        assert created.json()["requested_by"]["is_synthetic"] is True
        again = client.post(
            "/api/ingestion/jobs",
            json={"dataset": "TCGA-BRCA", "slide_path": "sample.svs"},
        )
        assert again.status_code == 200
        assert again.json()["id"] == created.json()["id"]
        one = client.get(f"/api/ingestion/jobs/{SEEDED_JOB_ID}")
        assert one.status_code == 200
        assert one.json()["counts"]["patches"] == 1
        assert "worker_id" not in one.json()
