"""GDC payload parsing, pagination, report join, and clinical-history spans."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from consilium.pipeline.gdc import (  # pragma: allowlist secret
    GdcClient,
    index_cases,
    parse_case,
    parse_slide,
)
from consilium.pipeline.reports import (  # pragma: allowlist secret
    ensure_reports_csv,
    extract_clinical_history,
    history_rank,
    load_reports,
)


def test_clinical_history_stops_before_diagnosis() -> None:
    bounded = extract_clinical_history(
        "CLINICAL HISTORY: Invented screening note. FINAL DIAGNOSIS: Invented label."
    )
    assert bounded is not None
    assert bounded.bounded is True
    assert bounded.text == "Invented screening note."
    assert "Invented label" not in bounded.text

    ampersand = extract_clinical_history(
        "Clinical Diagnosis & History: Invented incidental note. Gross Description: Invented gross."
    )
    assert ampersand is not None
    assert ampersand.bounded is True
    assert ampersand.text == "Invented incidental note."

    preoperative = extract_clinical_history(
        "Preoperative Diagnosis: Invented left mass. Final Diagnosis: Invented label."
    )
    assert preoperative is not None
    assert preoperative.bounded is True
    assert preoperative.text == "Invented left mass."

    specimens = extract_clinical_history(
        "the specimen is not a heading. Clinical History: Invented note. "
        "Specimens Submitted: A. Invented part."
    )
    assert specimens is not None
    assert specimens.bounded is True
    assert specimens.text == "Invented note."

    unbounded = extract_clinical_history(
        "Clinical History: Invented run-on note with no later heading"
    )
    assert unbounded is not None
    assert unbounded.bounded is False
    assert history_rank("Clinical History: Invented note. Gross Description: Invented.") == 0
    assert history_rank("Clinical History: Invented run-on note with no later heading") == 1
    assert history_rank("Invented narrative without headings.") == 2
    assert extract_clinical_history("") is None


def test_report_barcode_join_keeps_longer_text(tmp_path: Path) -> None:
    path = tmp_path / "reports.csv"
    path.write_text(
        "patient_filename,text\n"
        "TCGA-AA-0001.short,Short.\n"
        "TCGA-AA-0001.11111111-2222-3333-4444-555555555555,"
        "Clinical History: FIXTURE-HISTORY-AA-0001 invented note. "
        "Gross Description: Invented.\n"
        "not-a-barcode,Invented junk\n"
        "TCGA-AA-00,too short\n"
        "TCGA-AA-0009.uuid,   \n",
        encoding="utf-8",
    )
    reports, corrupt = load_reports(path)
    assert corrupt == 2
    assert "FIXTURE-HISTORY-AA-0001" in reports["TCGA-AA-0001"]
    assert reports["TCGA-AA-0009"].strip() == ""
    with pytest.raises(ValueError, match="patient_filename"):
        load_reports(_write(tmp_path / "bad.csv", "foo,bar\n1,2\n"))


def test_reports_zip_round_trip(tmp_path: Path) -> None:
    payload = b"patient_filename,text\nTCGA-AA-0001.uuid,Invented zip text\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__MACOSX/._TCGA_Reports.csv", b"junk")
        archive.writestr("TCGA_Reports.csv", payload)

    class _Response:
        def __init__(self, blob: bytes) -> None:
            self._blob = blob

        def read(self) -> bytes:
            return self._blob

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

    class _Opener:
        def open(self, _request: object, timeout: float | None = None) -> _Response:
            return _Response(buffer.getvalue())

    destination = tmp_path / "source" / "TCGA_Reports.csv"
    ensure_reports_csv(destination, opener=_Opener())  # type: ignore[arg-type]
    reports, corrupt = load_reports(destination)
    assert corrupt == 0
    assert reports["TCGA-AA-0001"] == "Invented zip text"

    # A present file is not downloaded again.
    class _Boom:
        def open(self, _request: object, timeout: float | None = None) -> _Response:
            raise AssertionError("should not download")

    ensure_reports_csv(destination, opener=_Boom())  # type: ignore[arg-type]


def test_parse_slide_and_case_from_live_shape() -> None:
    slide, reason = parse_slide(
        {
            "id": "164b1772-c07f-45a0-9462-b9df93861346",
            "file_id": "164b1772-c07f-45a0-9462-b9df93861346",
            "file_name": "TCGA-FA-8693-01Z-00-DX1.7bef9346-e85d-44c2-aa85-1f5faca9f97e.svs",
            "file_size": 935538577,
            "data_format": "SVS",
            "cases": [
                {
                    "case_id": "a43e5f0e-a21f-48d8-97e0-084d413680b7",
                    "submitter_id": "TCGA-FA-8693",
                    "project": {"project_id": "TCGA-DLBC"},
                    "samples": [
                        {
                            "submitter_id": "TCGA-FA-8693-01Z",
                            "sample_type": "Primary Tumor",
                            "preservation_method": "FFPE",
                        }
                    ],
                }
            ],
        }
    )
    assert reason is None
    assert slide is not None
    assert slide.submitter_id == "TCGA-FA-8693"
    assert slide.project_id == "TCGA-DLBC"
    assert slide.slide_kind == "DX"
    assert slide.slide_number == 1
    assert slide.preservation_methods == ("FFPE",)

    raw_case = {
        "case_id": "f978cb0f-d319-4c01-b4c5-23ae1403a106",
        "submitter_id": "TCGA-FF-8047",
        "project": {"project_id": "TCGA-DLBC"},
        "demographic": {"sex_at_birth": "female", "age_at_index": 38, "days_to_birth": -13996},
        "diagnoses": [
            {
                "primary_diagnosis": "Not Reported",
                "classification_of_tumor": "not reported",
            },
            {
                "primary_diagnosis": "Invented progression label",
                "classification_of_tumor": "Progression",
                "morphology": "9680/3",
            },
            {
                "primary_diagnosis": "Invented primary label",
                "classification_of_tumor": "primary",
                "morphology": "9680/3",
                "icd_10_code": "C83.3",
            },
        ],
    }
    parsed = parse_case(raw_case)
    assert parsed is not None
    assert parsed.patient_sex == "F"
    assert parsed.patient_age == 38
    assert parsed.primary_diagnosis == "Invented primary label"
    assert parsed.morphology == "9680/3"
    assert parsed.icd10 == "C83.3"
    missing, reason = parse_slide({"file_name": "TCGA-AA-0001-01Z-00-DX1.x.svs"})
    assert missing is None and reason == "corrupt_slide"
    indexed, corrupt = index_cases([{}, raw_case])
    assert corrupt == 1
    assert set(indexed) == {"TCGA-FF-8047"}


def test_gdc_client_paginates_and_rejects_bad_fields() -> None:
    pages = {
        0: _page([{"file_id": "a"}, {"file_id": "b"}], total=3, size=2),
        2: _page([{"file_id": "c"}], total=3, size=2),
    }

    class _Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self._raw = json.dumps(payload).encode()

        def read(self) -> bytes:
            return self._raw

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

    class _Opener:
        def __init__(self) -> None:
            self.bodies: list[dict[str, object]] = []

        def open(self, request: object, timeout: float | None = None) -> _Response:
            import urllib.request

            assert isinstance(request, urllib.request.Request)
            body = json.loads(request.data.decode())  # type: ignore[attr-defined]
            self.bodies.append(body)
            return _Response(pages[int(body["from"])])

    opener = _Opener()
    client = GdcClient(page_size=2, opener=opener)  # type: ignore[arg-type]
    hits = client.fetch_slides()
    assert [hit["file_id"] for hit in hits] == ["a", "b", "c"]
    assert len(opener.bodies) == 2
    filters = opener.bodies[0]["filters"]
    encoded = json.dumps(filters)
    assert "Diagnostic Slide" in encoded
    assert "TCGA-BRCA" in encoded
    assert "TCGA-DLBC" in encoded
    assert opener.bodies[0]["size"] == 2

    class _Warn:
        def open(self, _request: object, timeout: float | None = None) -> _Response:
            return _Response(
                {
                    "warnings": {"fields": "unrecognized values: [samples.is_ffpe]"},
                    "data": {},
                }
            )

    with pytest.raises(RuntimeError, match="rejected fields"):
        GdcClient(opener=_Warn()).fetch_cases()  # type: ignore[arg-type]


def _page(hits: list[dict[str, str]], *, total: int, size: int) -> dict[str, object]:
    return {
        "data": {
            "hits": hits,
            "pagination": {"total": total, "count": len(hits), "size": size},
        }
    }


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path
