"""Lakebase subset selection stays under the measured byte budget."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from consilium.pipeline import __main__ as pipeline_main  # pragma: allowlist secret
from consilium.pipeline.cohort import SPECIALTY_ORDER  # pragma: allowlist secret
from consilium.pipeline.load import PARQUET_FILES, PIPELINE_TABLES  # pragma: allowlist secret
from consilium.pipeline.subset import (  # pragma: allowlist secret
    _SPECIALTIES,
    select_case_ids,
    write_subset,
)

_OVERHEAD = 32 * 1024 * 1024


def test_specialty_order_matches_the_cohort() -> None:
    assert _SPECIALTIES == tuple(SPECIALTY_ORDER)


def test_held_out_keeps_earlier_cases_and_skips_other_specialties() -> None:
    cases = [
        _case("thorax-1", "pt-other", "thorax", "signed_out", False, 2),
        _case("breast-late", "pt-1", "breast", "open", True, 10),
        _case("breast-early", "pt-1", "breast", "signed_out", False, 1),
    ]
    chosen = select_case_ids(cases, None, max_cases=1)
    assert set(chosen["case_ids"]) == {"breast-late", "breast-early"}
    assert chosen["held_out_ids"] == ["breast-late"]
    assert chosen["prior_ids"] == ["breast-early"]
    assert chosen["sampled_ids"] == []
    assert chosen["stopped"] == "max_cases"


def test_round_robin_is_deterministic() -> None:
    cases = []
    for specialty in SPECIALTY_ORDER:
        for suffix in ("b", "a"):
            cases.append(
                _case(
                    f"{specialty}-{suffix}",
                    f"pt-{specialty}-{suffix}",
                    specialty,
                    "signed_out",
                    False,
                    1,
                )
            )
    first = select_case_ids(cases, None, max_cases=6)
    second = select_case_ids(list(reversed(cases)), None, max_cases=6)
    expected = [f"{specialty}-a" for specialty in SPECIALTY_ORDER]
    assert first["case_ids"] == expected
    assert second["case_ids"] == expected
    seven = select_case_ids(cases, None, max_cases=7)
    assert len(seven["case_ids"]) == 7
    assert "breast-b" in seven["case_ids"]
    assert "thorax-b" not in seven["case_ids"]


def test_byte_budget_skips_a_large_case_and_keeps_a_later_small_one() -> None:
    cases = [
        _case("breast-a", "pt-a", "breast", "signed_out", False, 1),
        _case("breast-b", "pt-b", "breast", "signed_out", False, 2),
    ]
    counts = {
        "breast-a": _counts(patch_in=100_000),
        "breast-b": _counts(),
    }
    chosen = select_case_ids(cases, counts, max_cases=1, byte_budget=_OVERHEAD + 10_000)
    assert chosen["case_ids"] == ["breast-b"]
    assert chosen["stopped"] == "max_cases"
    assert int(chosen["estimated_bytes"]) <= _OVERHEAD + 10_000


def test_mandatory_rows_stay_when_they_already_pass_the_budget() -> None:
    cases = [_case("breast-open", "pt-1", "breast", "open", True, 1)]
    counts = {"breast-open": _counts(patch_out=100_000)}
    chosen = select_case_ids(cases, counts, max_cases=45, byte_budget=_OVERHEAD)
    assert chosen["case_ids"] == ["breast-open"]
    assert chosen["sampled_ids"] == []
    assert chosen["stopped"] == "byte_budget"


def test_unknown_specialty_is_not_sampled() -> None:
    cases = [_case("lung-1", "pt-1", "lung", "signed_out", False, 1)]
    chosen = select_case_ids(cases, None, max_cases=45)
    assert chosen["case_ids"] == []
    assert chosen["stopped"] == "exhausted"


def test_write_subset_keeps_dimensions_and_filters_patients(tmp_path: Path) -> None:
    source = tmp_path / "export"
    _write_narrow(
        source,
        cases=[
            _case("breast-late", "pt-1", "breast", "open", True, 10),
            _case("breast-early", "pt-1", "breast", "signed_out", False, 1),
            _case("thorax-1", "pt-2", "thorax", "signed_out", False, 3),
        ],
        patients=["pt-1", "pt-2", "pt-unused"],
        pathologists=["path-a", "path-b"],
        concepts=["necrosis", "stroma"],
    )
    destination = tmp_path / "export_lakebase"
    result = write_subset(source, destination, max_cases=1)
    assert set(result.case_ids) == {"breast-late", "breast-early"}
    assert result.counts["pathologist"] == 2
    assert result.counts["concept"] == 2
    assert result.counts["patient"] == 1
    assert result.counts["path_case"] == 2
    assert result.counts["patch"] == 2
    assert "lakebase_cap" in result.summary()
    kept = pq.read_table(destination / "patient.parquet").column("id").to_pylist()
    assert kept == ["pt-1"]
    code = pipeline_main.main(
        ["subset", "--from", str(source), "--out", str(tmp_path / "again"), "--max-cases", "1"]
    )
    assert code == 0


def _case(
    case_id: str,
    patient_id: str,
    specialty: str,
    status: str,
    held: bool,
    hour: int,
) -> dict[str, object]:
    return {
        "id": case_id,
        "patient_id": patient_id,
        "specialty": specialty,
        "status": status,
        "is_held_out": held,
        "accessioned_at": datetime(2026, 1, 1, hour, tzinfo=UTC),
    }


def _counts(
    *,
    patch_in: int = 0,
    patch_out: int = 0,
    chunk_in: int = 0,
    chunk_out: int = 0,
    slides_ready: int = 0,
) -> dict[str, int]:
    return {
        "patch_in": patch_in,
        "patch_out": patch_out,
        "chunk_in": chunk_in,
        "chunk_out": chunk_out,
        "slides_ready": slides_ready,
    }


def _write_narrow(
    directory: Path,
    *,
    cases: list[dict[str, object]],
    patients: list[str],
    pathologists: list[str],
    concepts: list[str],
) -> None:
    directory.mkdir(parents=True)
    rows: dict[str, list[dict[str, object]]] = {
        "pathologist": [{"id": item} for item in pathologists],
        "patient": [{"id": item} for item in patients],
        "concept": [{"id": item} for item in concepts],
        "path_case": cases,
        "slide": [
            {"id": f"slide-{row['id']}", "case_id": row["id"], "status": "ready"} for row in cases
        ],
        "report": [{"id": f"report-{row['id']}", "case_id": row["id"]} for row in cases],
        "report_chunk": [
            {
                "case_id": row["id"],
                "in_corpus": row["status"] == "signed_out" and not row["is_held_out"],
            }
            for row in cases
        ],
        "patch": [
            {
                "case_id": row["id"],
                "in_corpus": row["status"] == "signed_out" and not row["is_held_out"],
            }
            for row in cases
        ],
    }
    for table in PIPELINE_TABLES:
        pq.write_table(pa.Table.from_pylist(rows[table]), directory / PARQUET_FILES[table])
