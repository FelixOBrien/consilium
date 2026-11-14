"""Cohort manifest: fixtures, tier sampling, and the CLI."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from consilium.pipeline.cohort import (  # pragma: allowlist secret
    SPECIALTY_ORDER,
    CohortCandidate,
    allocate,
    select_cohort,
)
from consilium.pipeline.manifest import build_manifest  # pragma: allowlist secret

FIXTURES = Path(__file__).parent / "fixtures" / "manifest"
SLIDES = FIXTURES / "slides.json"
CASES = FIXTURES / "cases.json"
REPORTS = FIXTURES / "reports.csv"


def _load(path: Path) -> list[object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build(tmp_path: Path, tier: str, seed: int = 0, *, slides: list[object] | None = None):
    return build_manifest(
        tier=tier,
        seed=seed,
        max_slide_gb=1.0,
        slides=_load(SLIDES) if slides is None else slides,
        cases=_load(CASES),
        reports_csv=REPORTS,
        data_root=tmp_path,
    )


def test_fixture_smoke_filters_balance_and_held_out(tmp_path: Path) -> None:
    result = _build(tmp_path, "smoke", seed=0)
    assert result.slides_seen == 26
    assert result.cases_eligible == 11
    assert len(result.rows) == 10
    assert sum(row.held_out for row in result.rows) == 2
    assert result.removed == {
        "corrupt_slide": 1,
        "duplicate_file": 1,
        "bad_barcode": 1,
        "unknown_project": 1,
        "non_svs": 1,
        "non_diagnostic": 1,
        "non_ffpe": 1,
        "over_size_cap": 1,
        "missing_case": 1,
        "missing_primary_diagnosis": 2,
        "missing_report": 1,
        "empty_report": 1,
        "extra_slides": 2,
        "not_sampled": 1,
        "corrupt_case": 1,
        "corrupt_report": 2,
    }
    counts = result.selected_by_specialty
    assert counts == {
        "breast": 2,
        "thorax": 2,
        "colorectal": 2,
        "gastrointestinal": 2,
        "skin": 1,
        "hematologic": 1,
    }
    assert result.held_out_by_specialty["breast"] == 1
    assert result.held_out_by_specialty["thorax"] == 1
    assert sum(result.held_out_by_specialty.values()) == 2
    by_id = {row.submitter_id: row for row in result.rows}
    breast_history = by_id["TCGA-AA-0001"]
    assert breast_history.held_out is True
    assert breast_history.case_id == "breast-TCGA-AA-0001"
    assert breast_history.slide_id == "breast-TCGA-AA-0001-s1"
    assert breast_history.gdc_file_id == "file-aa-0001-dx1"
    assert breast_history.file_size == 500_000_000
    assert breast_history.project_id == "TCGA-BRCA"
    assert breast_history.tier == "smoke"
    assert by_id["TCGA-AA-0002"].held_out is False
    assert by_id["TCGA-AA-0002"].gdc_file_id == "file-aa-0002-dx4"
    assert by_id["TCGA-AA-0002"].file_size == 40_000_000
    assert by_id["TCGA-BB-0001"].held_out is True
    assert by_id["TCGA-BB-0002"].held_out is False
    assert by_id["TCGA-FF-0001"].specialty == "hematologic"
    assert "TCGA-AA-0008" not in by_id
    assert "TCGA-AA-0013" not in by_id


def test_fixture_joins_barcode_and_keeps_primary_diagnosis(tmp_path: Path) -> None:
    result = _build(tmp_path, "demo", seed=0)
    table = pq.read_table(result.cases_path).to_pydict()
    indexed = {submitter: index for index, submitter in enumerate(table["submitter_id"])}
    breast = indexed["TCGA-AA-0001"]
    assert table["patient_sex"][breast] == "F"
    assert table["patient_age"][breast] == 61
    assert table["primary_diagnosis"][breast] == "Invented duct carcinoma"
    assert table["morphology"][breast] == "8500/3"
    assert table["icd10"][breast] == "C50.9"
    assert table["classification_of_tumor"][breast] == "primary"
    assert table["gdc_case_id"][breast] == "case-TCGA-AA-0001"
    assert table["case_id"][breast] == "breast-TCGA-AA-0001"
    thorax = indexed["TCGA-BB-0001"]
    assert table["patient_sex"][thorax] == "M"
    colorectal = indexed["TCGA-CC-0001"]
    assert table["primary_diagnosis"][colorectal] == "Invented colorectal carcinoma"
    heme = indexed["TCGA-FF-0001"]
    assert table["patient_age"][heme] == 55
    assert table["patient_sex"][heme] == "M"
    csv_text = result.cohort_path.read_text(encoding="utf-8")
    assert "Invented duct carcinoma" not in csv_text
    header = csv_text.splitlines()[0]
    assert header == (
        "case_id,slide_id,gdc_file_id,file_name,file_size,project_id,specialty,tier,held_out"
    )
    assert len(result.rows) == 11
    assert sum(row.held_out for row in result.rows) == 10
    assert result.removed["not_sampled"] == 0
    assert result.rows[0].case_id.startswith("breast-")


def test_smoke_is_a_subset_of_demo_and_stretch(tmp_path: Path) -> None:
    smoke = _build(tmp_path / "smoke", "smoke")
    demo = _build(tmp_path / "demo", "demo")
    stretch = _build(tmp_path / "stretch", "stretch")
    smoke_ids = {row.case_id for row in smoke.rows}
    demo_ids = {row.case_id for row in demo.rows}
    stretch_ids = {row.case_id for row in stretch.rows}
    assert smoke_ids < demo_ids
    assert demo_ids == stretch_ids
    assert sum(row.held_out for row in stretch.rows) == 11
    demo_held = {row.case_id for row in demo.rows if row.held_out}
    assert {row.case_id for row in smoke.rows if row.held_out} <= demo_held


def test_same_seed_is_byte_identical_and_order_independent(tmp_path: Path) -> None:
    first = _build(tmp_path / "a", "smoke", seed=4)
    second = _build(tmp_path / "b", "smoke", seed=4)
    assert first.cohort_path.read_bytes() == second.cohort_path.read_bytes()
    reversed_slides = list(reversed(_load(SLIDES)))
    third = _build(tmp_path / "c", "smoke", seed=4, slides=reversed_slides)
    assert first.cohort_path.read_bytes() == third.cohort_path.read_bytes()


def test_summary_lists_every_specialty_and_filter(tmp_path: Path) -> None:
    text = _build(tmp_path, "smoke").summary()
    assert "tier smoke" in text
    assert "max_slide_bytes 1000000000" in text
    assert "filter over_size_cap removed 1" in text
    assert "filter corrupt_report removed 2" in text
    for specialty in SPECIALTY_ORDER:
        assert f"specialty {specialty} " in text
    assert "wrote " in text


def test_size_cap_boundary(tmp_path: Path) -> None:
    reports = tmp_path / "reports.csv"
    _write_reports(reports, {"TCGA-AA-0001": "Invented report text for the cap."})
    slides = [
        _hit("TCGA-AA-0001", "TCGA-BRCA", file_id="at-cap", size=1_000_000_000),
        _hit("TCGA-AA-0002", "TCGA-BRCA", file_id="over-cap", size=1_000_000_001),
    ]
    cases = [_clinical("TCGA-AA-0001"), _clinical("TCGA-AA-0002")]
    _write_reports(
        reports,
        {
            "TCGA-AA-0001": "Invented report text for the cap.",
            "TCGA-AA-0002": "Invented report text over the cap.",
        },
    )
    result = build_manifest(
        tier="smoke",
        seed=0,
        max_slide_gb=1.0,
        slides=slides,
        cases=cases,
        reports_csv=reports,
        data_root=tmp_path / "out",
    )
    assert result.removed["over_size_cap"] == 1
    assert [row.gdc_file_id for row in result.rows] == ["at-cap"]


def test_absent_preservation_kept_and_unknown_dropped(tmp_path: Path) -> None:
    reports = tmp_path / "reports.csv"
    _write_reports(
        reports,
        {
            "TCGA-AA-0001": "Invented report.",
            "TCGA-AA-0002": "Invented report two.",
        },
    )
    slides = [
        _hit("TCGA-AA-0001", "TCGA-BRCA", file_id="no-method", preservation=None),
        _hit("TCGA-AA-0002", "TCGA-BRCA", file_id="unknown", preservation="Unknown"),
    ]
    result = build_manifest(
        tier="smoke",
        seed=0,
        max_slide_gb=1.0,
        slides=slides,
        cases=[_clinical("TCGA-AA-0001"), _clinical("TCGA-AA-0002")],
        reports_csv=reports,
        data_root=tmp_path / "out",
    )
    assert [row.gdc_file_id for row in result.rows] == ["no-method"]
    assert result.removed["non_ffpe"] == 1


def test_allocate_is_even_and_monotonic() -> None:
    available = {name: 100 for name in SPECIALTY_ORDER}
    smoke = allocate(10, available)
    demo = allocate(200, available)
    stretch = allocate(500, available)
    assert smoke == {
        "breast": 2,
        "thorax": 2,
        "colorectal": 2,
        "gastrointestinal": 2,
        "skin": 1,
        "hematologic": 1,
    }
    assert demo["breast"] == 34 and demo["hematologic"] == 33
    assert sum(demo.values()) == 200
    assert stretch["breast"] == 84 and stretch["skin"] == 83
    assert sum(stretch.values()) == 500
    for name in SPECIALTY_ORDER:
        assert smoke[name] <= demo[name] <= stretch[name]
    short = dict(available)
    short["hematologic"] = 3
    stretched = allocate(500, short)
    assert stretched["hematologic"] == 3
    assert sum(stretched.values()) == 500
    assert (
        max(stretched[name] for name in SPECIALTY_ORDER if name != "hematologic")
        - min(stretched[name] for name in SPECIALTY_ORDER if name != "hematologic")
        <= 1
    )


def test_sampling_prefers_history_and_nests_tiers() -> None:
    candidates = [
        CohortCandidate(specialty, f"{specialty}-{index}", 0 if index == 0 else 2)
        for specialty in SPECIALTY_ORDER
        for index in range(2)
    ]
    smoke = select_cohort(candidates, "smoke", seed=0)
    assert smoke["breast-0"] is True
    assert smoke["breast-1"] is False
    assert smoke["thorax-0"] is True
    assert sum(smoke.values()) == 2
    assert len({key.split("-")[0] for key, held in smoke.items() if held}) == 2

    # Scarce held-out slots go to specialties that actually have a history.
    preferred = []
    for specialty in SPECIALTY_ORDER:
        rank = 0 if specialty in {"thorax", "skin"} else 2
        for index in range(4):
            preferred.append(CohortCandidate(specialty, f"{specialty}-{index}", rank))
    held = select_cohort(preferred, "smoke", seed=0)
    held_specialties = {key.split("-")[0] for key, flagged in held.items() if flagged}
    assert held_specialties == {"thorax", "skin"}
    assert sum(held.values()) == 2

    wide = [
        CohortCandidate(specialty, f"{specialty}-{index}", 2)
        for specialty in SPECIALTY_ORDER
        for index in range(90)
    ]
    demo = select_cohort(wide, "demo", seed=3)
    stretch = select_cohort(wide, "stretch", seed=3)
    smoke_wide = select_cohort(wide, "smoke", seed=3)
    assert set(smoke_wide) < set(demo) < set(stretch)
    assert len(smoke_wide) == 10
    assert len(demo) == 200
    assert len(stretch) == 500
    demo_counts: dict[str, int] = dict.fromkeys(SPECIALTY_ORDER, 0)
    held_counts: dict[str, int] = dict.fromkeys(SPECIALTY_ORDER, 0)
    for key, held in demo.items():
        specialty = key.split("-")[0]
        demo_counts[specialty] += 1
        if held:
            held_counts[specialty] += 1
    assert demo_counts["breast"] == 34
    assert demo_counts["thorax"] == 34
    assert demo_counts["colorectal"] == 33
    assert sum(demo_counts.values()) == 200
    assert sum(held_counts.values()) == 10
    assert max(held_counts.values()) - min(held_counts.values()) <= 1
    assert set(held_counts) == set(SPECIALTY_ORDER)
    other = select_cohort(wide, "demo", seed=4)
    assert set(other) != set(demo)
    assert select_cohort(list(reversed(wide)), "demo", seed=3) == demo

    short = [CohortCandidate("hematologic", f"hematologic-{index}", 2) for index in range(3)]
    short += [
        CohortCandidate(specialty, f"{specialty}-{index}", 2)
        for specialty in SPECIALTY_ORDER
        if specialty != "hematologic"
        for index in range(100)
    ]
    picked = select_cohort(short, "stretch", seed=1)
    assert sum(key.startswith("hematologic-") for key in picked) == 3
    assert len(picked) == 500


def test_empty_inputs_write_headers(tmp_path: Path) -> None:
    reports = tmp_path / "reports.csv"
    _write_reports(reports, {})
    result = build_manifest(
        tier="demo",
        seed=0,
        max_slide_gb=1.0,
        slides=[],
        cases=[],
        reports_csv=reports,
        data_root=tmp_path / "out",
    )
    assert result.rows == ()
    assert result.cases_eligible == 0
    with result.cohort_path.open(newline="", encoding="utf-8") as handle:
        assert list(csv.reader(handle)) == [
            [
                "case_id",
                "slide_id",
                "gdc_file_id",
                "file_name",
                "file_size",
                "project_id",
                "specialty",
                "tier",
                "held_out",
            ]
        ]
    assert pq.read_table(result.cases_path).num_rows == 0


def test_cli_on_fixtures(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from consilium.pipeline.__main__ import main  # pragma: allowlist secret

    code = main(
        [
            "manifest",
            "--tier",
            "smoke",
            "--max-slide-gb",
            "1.0",
            "--seed",
            "0",
            "--data-root",
            str(tmp_path),
            "--reports",
            str(REPORTS),
            "--slides-json",
            str(SLIDES),
            "--cases-json",
            str(CASES),
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "specialty breast eligible 2 selected 2 held_out 1" in output
    assert "cases_selected 10" in output
    assert "filter missing_report removed 1" in output
    assert (tmp_path / "cohort" / "cohort.csv").is_file()
    assert (tmp_path / "source" / "gdc_cases.parquet").is_file()


def test_cli_usage_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from consilium.pipeline.__main__ import main  # pragma: allowlist secret

    with pytest.raises(SystemExit) as exc:
        main(["manifest", "--tier", "nope"])
    assert exc.value.code == 2
    code = main(
        [
            "manifest",
            "--tier",
            "smoke",
            "--max-slide-gb",
            "0",
            "--reports",
            str(REPORTS),
            "--slides-json",
            str(SLIDES),
            "--cases-json",
            str(CASES),
            "--data-root",
            str(tmp_path),
        ]
    )
    assert code == 1
    assert "max_slide_gb" in capsys.readouterr().err
    code = main(
        [
            "manifest",
            "--tier",
            "smoke",
            "--slides-json",
            str(SLIDES),
            "--data-root",
            str(tmp_path),
        ]
    )
    assert code == 1
    assert "both" in capsys.readouterr().err


def test_module_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "consilium.pipeline", "--help"],  # pragma: allowlist secret
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    output = " ".join(result.stdout.split())
    assert "manifest" in output
    assert "not for clinical use" in output


def _write_reports(path: Path, texts: dict[str, str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["patient_filename", "text"])
        for barcode, text in texts.items():
            writer.writerow([f"{barcode}.fixture-uuid", text])


def _hit(
    submitter: str,
    project: str,
    *,
    file_id: str,
    size: int = 100,
    preservation: str | None = "FFPE",
    kind: str = "DX1",
) -> dict[str, object]:
    samples: list[dict[str, str]] = []
    if preservation is not None:
        samples.append(
            {
                "submitter_id": f"{submitter}-01Z",
                "sample_type": "Primary Tumor",
                "preservation_method": preservation,
            }
        )
    return {
        "file_id": file_id,
        "file_name": f"{submitter}-01Z-00-{kind}.{file_id}.svs",
        "file_size": size,
        "data_format": "SVS",
        "cases": [
            {
                "submitter_id": submitter,
                "project": {"project_id": project},
                "samples": samples,
            }
        ],
    }


def _clinical(submitter: str, project: str = "TCGA-BRCA") -> dict[str, object]:
    return {
        "submitter_id": submitter,
        "case_id": f"case-{submitter}",
        "project": {"project_id": project},
        "demographic": {"sex_at_birth": "female", "age_at_index": 50},
        "diagnoses": [
            {
                "primary_diagnosis": "Invented carcinoma",
                "classification_of_tumor": "primary",
                "morphology": "8140/3",
                "icd_10_code": "C50.9",
            }
        ],
    }
