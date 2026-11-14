"""Case, patient and pathologist routes against a migrated, seeded database."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.config import Settings  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import compose_body, seed  # pragma: allowlist secret
from consilium.seed_data import (  # pragma: allowlist secret
    CASES,
    DEMO_USER_ID,
    PATIENTS,
    CaseSeed,
    report_sections,
)

OPEN_CASE_ID = "breast-FX-B042C"
SIGNED_CASE_ID = "breast-FX-B042A"
MULTI_PATIENT_ID = "pt-0042"
SINGLE_OPEN_PATIENT_ID = "pt-0074"
UNKNOWN_ID = "missing-id"


@pytest.fixture
def api(empty_database: str, tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    migrate(empty_database)
    seed(empty_database, tmp_path)
    app = create_app(Settings(database_url=empty_database))
    with TestClient(app) as client:
        yield client, empty_database


def test_roster_and_acting_pathologist(api: tuple[TestClient, str]) -> None:
    client, _url = api
    roster = client.get("/api/pathologists")
    assert roster.status_code == 200
    people = roster.json()
    assert [person["id"] for person in people] == sorted(person["id"] for person in people)
    assert sum(person["is_demo_user"] for person in people) == 1
    assert all(person["is_synthetic"] is True for person in people)
    demo = next(person for person in people if person["is_demo_user"])
    assert demo["id"] == DEMO_USER_ID
    assert demo["secondary_specialties"] == ["skin"]

    missing = client.get("/api/me")
    assert missing.status_code == 200
    assert missing.json()["id"] == DEMO_USER_ID
    assert missing.json()["is_demo_user"] is True
    assert missing.json()["is_synthetic"] is True

    blank = client.get("/api/me", headers={"X-User-Id": "   "})
    assert blank.status_code == 200
    assert blank.json()["id"] == DEMO_USER_ID

    named = client.get("/api/me", headers={"X-User-Id": "path-adebayo"})
    assert named.status_code == 200
    assert named.json()["id"] == "path-adebayo"
    assert named.json()["is_synthetic"] is True

    unknown = client.get("/api/me", headers={"X-User-Id": "path-missing"})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "unknown_user"

    still_unknown = client.get("/api/cases", headers={"X-User-Id": "path-missing"})
    assert still_unknown.status_code == 404
    assert still_unknown.json()["error"]["code"] == "unknown_user"


def test_case_filters_and_default_view(api: tuple[TestClient, str]) -> None:
    client, url = api
    omitted = client.get("/api/cases")
    mine = client.get("/api/cases", params={"view": "mine"})
    assert omitted.status_code == 200
    omitted_ids = [row["id"] for row in omitted.json()["items"]]
    mine_ids = [row["id"] for row in mine.json()["items"]]
    assert omitted_ids == _case_ids(view=None, actor=DEMO_USER_ID)
    assert mine_ids == omitted_ids
    assert all(row["assigned_to"]["id"] == DEMO_USER_ID for row in mine.json()["items"])
    assert mine.json()["items"][0]["status"] == "open"

    everyone = client.get("/api/cases", params={"view": "all"})
    everyone_ids = [row["id"] for row in everyone.json()["items"]]
    assert everyone_ids == _case_ids(view="all", actor=DEMO_USER_ID)
    assert len(everyone.json()["items"]) == len(CASES)

    adebayo = client.get(
        "/api/cases",
        params={"view": "mine"},
        headers={"X-User-Id": "path-adebayo"},
    )
    assert [row["id"] for row in adebayo.json()["items"]] == _case_ids(
        view="mine",
        actor="path-adebayo",
    )

    combined = client.get(
        "/api/cases",
        params={
            "view": "all",
            "status": "signed_out",
            "specialty": "breast",
            "assigned_to": DEMO_USER_ID,
            "patient_id": MULTI_PATIENT_ID,
            "icd10": "C50",
        },
    )
    assert [row["id"] for row in combined.json()["items"]] == _case_ids(
        view="all",
        actor=DEMO_USER_ID,
        status="signed_out",
        specialty="breast",
        assigned_to=DEMO_USER_ID,
        patient_id=MULTI_PATIENT_ID,
        icd10="C50",
    )
    assert combined.json()["items"]
    assert all(row["icd10"].startswith("C50") for row in combined.json()["items"])

    open_and_code = client.get(
        "/api/cases",
        params={"view": "all", "status": "open", "icd10": "C50"},
    )
    assert open_and_code.json()["items"] == []

    prefix = client.get("/api/cases", params={"view": "all", "icd10": "C50"})
    leaked = [row["id"] for row in prefix.json()["items"] if row["status"] == "open"]
    assert leaked == []
    assert {row["id"] for row in prefix.json()["items"]} == {
        case.id for case in CASES if case.status == "signed_out" and case.icd10.startswith("C50")
    }
    with connect(url) as conn:
        stored = conn.execute(
            "select count(*) from path_case where status = 'open' and icd10 like %s",
            ("C50%",),
        ).fetchone()
    assert stored is not None and stored[0] > 0

    wildcard = client.get("/api/cases", params={"view": "all", "icd10": "C50%"})
    assert wildcard.json()["items"] == []

    by_patient = client.get(
        "/api/cases",
        params={"view": "all", "patient_id": MULTI_PATIENT_ID},
    )
    assert [row["id"] for row in by_patient.json()["items"]] == _case_ids(
        view="all",
        actor=DEMO_USER_ID,
        patient_id=MULTI_PATIENT_ID,
    )


def test_patient_filters(api: tuple[TestClient, str]) -> None:
    client, _url = api
    listed = client.get("/api/patients")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["items"]] == _patient_ids()
    multi = next(row for row in listed.json()["items"] if row["id"] == MULTI_PATIENT_ID)
    assert multi["case_count"] == 3
    assert multi["open_case_count"] == 1
    assert multi["signed_out_case_count"] == 2
    assert multi["specialties"] == ["breast"]
    assert multi["is_synthetic_linkage"] is True
    assert multi["display_label"] == "PT-0042"

    both = client.get("/api/patients", params={"q": "PT-0042", "multi_case": "true"})
    assert [row["id"] for row in both.json()["items"]] == [MULTI_PATIENT_ID]
    folded = client.get("/api/patients", params={"q": "pt-0018", "multi_case": "true"})
    assert [row["id"] for row in folded.json()["items"]] == ["pt-0018"]
    singles = client.get(
        "/api/patients",
        params={"q": SINGLE_OPEN_PATIENT_ID, "multi_case": "true"},
    )
    assert singles.json()["items"] == []
    none = client.get("/api/patients", params={"q": "no-such-patient"})
    assert none.status_code == 200
    assert none.json() == {"items": [], "next_cursor": None}


def test_cursor_pagination(api: tuple[TestClient, str]) -> None:
    client, _url = api
    expected_cases = _case_ids(view="all", actor=DEMO_USER_ID)
    walked = _walk(client, "/api/cases", {"view": "all"}, limit=5)
    assert walked == expected_cases

    first = client.get("/api/cases", params={"view": "all", "limit": 1})
    assert first.status_code == 200
    body = first.json()
    assert body["next_cursor"] == body["items"][0]["id"]
    second = client.get(
        "/api/cases",
        params={"view": "all", "limit": 1, "cursor": body["next_cursor"]},
    )
    assert [row["id"] for row in second.json()["items"]] == [expected_cases[1]]
    assert body["items"][0]["id"] not in {row["id"] for row in second.json()["items"]}

    bad = client.get("/api/cases", params={"cursor": "missing"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "validation_error"
    excluded = client.get(
        "/api/cases",
        params={"view": "all", "specialty": "breast", "cursor": "thorax-FX-T007A"},
    )
    assert excluded.status_code == 422
    assert excluded.json()["error"]["code"] == "validation_error"

    expected_patients = _patient_ids()
    assert _walk(client, "/api/patients", {}, limit=3) == expected_patients
    bad_patient = client.get("/api/patients", params={"cursor": "missing"})
    assert bad_patient.status_code == 422
    assert bad_patient.json()["error"]["code"] == "validation_error"
    single = client.get(
        "/api/patients",
        params={"multi_case": "true", "cursor": SINGLE_OPEN_PATIENT_ID},
    )
    assert single.status_code == 422
    assert single.json()["error"]["code"] == "validation_error"


def test_patient_timeline_and_case_detail(api: tuple[TestClient, str]) -> None:
    client, _url = api
    detail = client.get(f"/api/patients/{MULTI_PATIENT_ID}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["birth_year"] == 1965
    assert [case["id"] for case in body["cases"]] == _case_ids(
        view="all",
        actor=DEMO_USER_ID,
        patient_id=MULTI_PATIENT_ID,
    )
    assert body["cases"][0]["status"] == "open"
    assert body["cases"][0]["icd10"] is None
    assert body["cases"][0]["conclusion_line"] is None
    signed = body["cases"][1]
    assert signed["conclusion_line"] == _conclusion(signed["id"])
    assert signed["icd10"] == "C50.9"
    assert signed["patient"]["case_count"] == 3
    assert signed["slide_count"] == 1
    assert signed["thumbnail_url"] == f"/api/slides/{signed['id']}-s1/thumbnail"
    assert signed["specimen_label"]

    case = client.get(f"/api/cases/{OPEN_CASE_ID}")
    assert case.status_code == 200
    opened = case.json()
    assert opened["report_status"] == "none"
    assert opened["prior_case_count"] == 2
    assert opened["icd10"] is None
    assert opened["conclusion_line"] is None
    assert opened["slides"][0]["id"] == f"{OPEN_CASE_ID}-s1"
    assert opened["slides"][0]["ordinal"] == 1
    assert opened["slides"][0]["stain"] == "HE"
    assert "withheld" not in case.text.lower()

    earliest = client.get(f"/api/cases/{SIGNED_CASE_ID}").json()
    assert earliest["prior_case_count"] == 2
    assert earliest["report_status"] == "signed"
    assert earliest["conclusion_line"] == _conclusion(SIGNED_CASE_ID)

    alone = client.get("/api/cases/thorax-FX-T007A").json()
    assert alone["prior_case_count"] == 0

    report = client.get(f"/api/cases/{SIGNED_CASE_ID}/report")
    assert report.status_code == 200
    signed_report = report.json()
    sections = report_sections(_case(SIGNED_CASE_ID))
    assert signed_report["status"] == "signed"
    assert signed_report["is_synthetic_author"] is True
    assert signed_report["author"]["id"] == DEMO_USER_ID
    assert signed_report["author"]["is_synthetic"] is True
    assert signed_report["body"] == compose_body(sections)
    assert signed_report["conclusion"] == sections["conclusion"]
    assert signed_report["clinical_history"] == sections["clinical_history"]
    assert signed_report["icd10"] == "C50.9"
    assert signed_report["signed_at"]

    hidden = client.get(f"/api/cases/{OPEN_CASE_ID}/report")
    assert hidden.status_code == 200
    assert set(hidden.json()) == {"case_id", "status", "clinical_history"}
    assert hidden.json()["status"] == "none"
    history = report_sections(_case(OPEN_CASE_ID))["clinical_history"]
    assert hidden.json()["clinical_history"] == history


def test_unknown_case_and_patient(api: tuple[TestClient, str]) -> None:
    client, _url = api
    missing_case = client.get(f"/api/cases/{UNKNOWN_ID}")
    assert missing_case.status_code == 404
    assert missing_case.json()["error"]["code"] == "not_found"
    missing_report = client.get(f"/api/cases/{UNKNOWN_ID}/report")
    assert missing_report.status_code == 404
    assert missing_report.json()["error"]["code"] == "not_found"
    missing_patient = client.get(f"/api/patients/{UNKNOWN_ID}")
    assert missing_patient.status_code == 404
    assert missing_patient.json()["error"]["code"] == "not_found"


def test_open_case_sorts_before_a_newer_signed_case(api: tuple[TestClient, str]) -> None:
    client, url = api
    with connect(url) as conn:
        conn.execute(
            "update path_case set accessioned_at = %s where id = %s",
            (datetime(2026, 12, 1, 9, 0, tzinfo=UTC), "breast-FX-B042B"),
        )
        conn.commit()
    mine = client.get("/api/cases", params={"view": "mine", "limit": 5})
    ids = [row["id"] for row in mine.json()["items"]]
    assert ids[0] != "breast-FX-B042B"
    assert ids[:3] == ["breast-FX-B074A", "breast-FX-B042C", "skin-FX-S018B"]
    assert "breast-FX-B042B" in ids[3:]


def test_conclusion_line_falls_back_to_primary_diagnosis(api: tuple[TestClient, str]) -> None:
    client, url = api
    with connect(url) as conn:
        conn.execute(
            "update report set conclusion = %s where case_id = %s",
            ("\n\nFirst real line\nSecond line", SIGNED_CASE_ID),
        )
        conn.commit()
    listed = client.get("/api/cases", params={"view": "all", "patient_id": MULTI_PATIENT_ID})
    row = next(item for item in listed.json()["items"] if item["id"] == SIGNED_CASE_ID)
    assert row["conclusion_line"] == "First real line"

    with connect(url) as conn:
        conn.execute(
            "update report set conclusion = null where case_id = %s",
            (SIGNED_CASE_ID,),
        )
        conn.commit()
    again = client.get(f"/api/cases/{SIGNED_CASE_ID}")
    assert again.json()["conclusion_line"] == "Invasive carcinoma of no special type"
    assert "primary_diagnosis" not in again.json()


def test_open_cases_do_not_leak_withheld_report_text(api: tuple[TestClient, str]) -> None:
    client, url = api
    secrets = _open_secrets(url)
    assert secrets

    open_list = client.get("/api/cases", params={"view": "all", "status": "open"})
    assert open_list.status_code == 200
    _assert_clean(open_list.text, [value for group in secrets.values() for value in group])
    for row in open_list.json()["items"]:
        assert row["icd10"] is None
        assert row["conclusion_line"] is None
        assert row["status"] == "open"

    patients = client.get("/api/patients")
    _assert_clean(patients.text, [value for group in secrets.values() for value in group])

    for case_id, forbidden in secrets.items():
        case = client.get(f"/api/cases/{case_id}")
        report = client.get(f"/api/cases/{case_id}/report")
        assert case.status_code == 200
        assert report.status_code == 200
        assert case.json()["report_status"] == "none"
        assert "withheld" not in case.text.lower()
        assert "withheld" not in report.text.lower()
        _assert_clean(case.text, forbidden)
        _assert_clean(report.text, forbidden)
        assert set(report.json()) == {"case_id", "status", "clinical_history"}
        history = report.json()["clinical_history"] or ""
        for secret in forbidden:
            assert secret not in history

        patient_id = case.json()["patient"]["id"]
        patient = client.get(f"/api/patients/{patient_id}")
        assert patient.status_code == 200
        assert "withheld" not in patient.text.lower()
        open_rows = [row for row in patient.json()["cases"] if row["id"] == case_id]
        assert len(open_rows) == 1
        _assert_clean(_dump(open_rows[0]), forbidden)
        if patient.json()["case_count"] == 1:
            _assert_clean(patient.text, forbidden)

    worklist = client.get("/api/cases", params={"view": "all"})
    for row in worklist.json()["items"]:
        if row["status"] != "open":
            continue
        _assert_clean(_dump(row), secrets[row["id"]])
        assert "withheld" not in _dump(row).lower()


def _assert_clean(document: str, secrets: list[str]) -> None:
    assert "withheld" not in document.lower()
    for secret in secrets:
        assert secret
        assert secret not in document


def _dump(payload: object) -> str:
    return json.dumps(payload)


def _open_secrets(url: str) -> dict[str, list[str]]:
    with connect(url) as conn:
        rows = conn.execute(
            """
            select
                c.id,
                c.primary_diagnosis,
                c.morphology,
                c.icd10,
                r.body,
                r.conclusion,
                r.microscopic_description,
                r.gross_description
            from path_case c
            join report r on r.case_id = c.id
            where c.status = 'open'
            order by c.id
            """
        ).fetchall()
    secrets: dict[str, list[str]] = {}
    for row in rows:
        case_id = row[0]
        values = [value for value in row[1:] if isinstance(value, str) and value]
        assert len(values) == 7
        secrets[case_id] = values
    return secrets


def _walk(client: TestClient, path: str, params: dict[str, object], *, limit: int) -> list[str]:
    found: list[str] = []
    cursor: str | None = None
    for _page in range(20):
        query = {**params, "limit": limit}
        if cursor is not None:
            query["cursor"] = cursor
        response = client.get(path, params=query)
        assert response.status_code == 200, response.text
        body = response.json()
        items = body["items"]
        found.extend(item["id"] for item in items)
        nxt = body["next_cursor"]
        if nxt is None:
            return found
        assert items
        assert nxt == items[-1]["id"]
        assert nxt not in found[:-1]
        cursor = nxt
    raise AssertionError("pagination did not end")


def _case_ids(
    *,
    view: str | None,
    actor: str,
    status: str | None = None,
    specialty: str | None = None,
    assigned_to: str | None = None,
    icd10: str | None = None,
    patient_id: str | None = None,
) -> list[str]:
    return [case.id for case in _case_rows(
        view=view,
        actor=actor,
        status=status,
        specialty=specialty,
        assigned_to=assigned_to,
        icd10=icd10,
        patient_id=patient_id,
    )]


def _case_rows(
    *,
    view: str | None,
    actor: str,
    status: str | None,
    specialty: str | None,
    assigned_to: str | None,
    icd10: str | None,
    patient_id: str | None,
) -> list[CaseSeed]:
    mine = view != "all"
    rows = []
    for case in CASES:
        if mine and case.assigned_to != actor:
            continue
        if status is not None and case.status != status:
            continue
        if specialty is not None and case.specialty != specialty:
            continue
        if assigned_to is not None and case.assigned_to != assigned_to:
            continue
        if patient_id is not None and case.patient_id != patient_id:
            continue
        if icd10 is not None and (case.status != "signed_out" or not case.icd10.startswith(icd10)):
            continue
        rows.append(case)
    if mine:
        rows.sort(
            key=lambda case: (
                case.status != "open",
                -case.accessioned_at.timestamp(),
                case.id,
            )
        )
    else:
        rows.sort(key=lambda case: (-case.accessioned_at.timestamp(), case.id))
    return rows


def _patient_ids(*, q: str | None = None, multi_case: bool = False) -> list[str]:
    grouped: dict[str, list[CaseSeed]] = {patient.id: [] for patient in PATIENTS}
    for case in CASES:
        grouped[case.patient_id].append(case)
    rows: list[tuple[datetime, str]] = []
    for patient in PATIENTS:
        group = grouped[patient.id]
        if q is not None:
            needle = q.casefold()
            label = patient.display_label.casefold()
            if needle not in patient.id.casefold() and needle not in label:
                continue
        if multi_case and len(group) <= 1:
            continue
        latest = max(case.accessioned_at for case in group)
        rows.append((latest, patient.id))
    rows.sort(key=lambda item: (-item[0].timestamp(), item[1]))
    return [patient_id for _latest, patient_id in rows]


def _case(case_id: str) -> CaseSeed:
    for case in CASES:
        if case.id == case_id:
            return case
    raise KeyError(case_id)


def _conclusion(case_id: str) -> str:
    text = report_sections(_case(case_id))["conclusion"]
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    raise AssertionError(case_id)
