"""Stage 1: build the cohort manifest and GDC clinical parquet.

One row per selected case. Synthetic pathologists, sign-out dates, and
longitudinal patient links (`patient.is_synthetic_linkage`) are stage 7.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from consilium.pipeline.cohort import (  # pragma: allowlist secret
    BYTES_PER_GB,
    PROJECT_SPECIALTY,
    SPECIALTY_ORDER,
    TIER_CASE_COUNTS,
    CohortCandidate,
    select_cohort,
)
from consilium.pipeline.gdc import (  # pragma: allowlist secret
    ClinicalCase,
    SlideFile,
    index_cases,
    parse_slide,
)
from consilium.pipeline.reports import (  # pragma: allowlist secret
    PATIENT_BARCODE,
    history_rank,
    load_reports,
)

COHORT_COLUMNS: tuple[str, ...] = (
    "case_id",
    "slide_id",
    "gdc_file_id",
    "file_name",
    "file_size",
    "project_id",
    "specialty",
    "tier",
    "held_out",
)

REMOVAL_ORDER: tuple[str, ...] = (
    "corrupt_slide",
    "duplicate_file",
    "bad_barcode",
    "unknown_project",
    "non_svs",
    "non_diagnostic",
    "non_ffpe",
    "over_size_cap",
    "missing_case",
    "missing_primary_diagnosis",
    "missing_report",
    "empty_report",
    "extra_slides",
    "not_sampled",
    "corrupt_case",
    "corrupt_report",
)


@dataclass(frozen=True)
class CohortRow:
    case_id: str
    slide_id: str
    gdc_file_id: str
    file_name: str
    file_size: int
    project_id: str
    specialty: str
    tier: str
    held_out: bool
    submitter_id: str
    gdc_case_id: str
    patient_sex: str | None
    patient_age: int | None
    primary_diagnosis: str
    morphology: str | None
    icd10: str | None
    classification_of_tumor: str


@dataclass
class ManifestResult:
    tier: str
    seed: int
    max_slide_bytes: int
    rows: tuple[CohortRow, ...]
    removed: dict[str, int]
    slides_seen: int
    cases_eligible: int
    eligible_by_specialty: dict[str, int]
    selected_by_specialty: dict[str, int]
    held_out_by_specialty: dict[str, int]
    cohort_path: Path
    cases_path: Path

    def summary(self) -> str:
        lines = [
            f"tier {self.tier}",
            f"seed {self.seed}",
            f"max_slide_bytes {self.max_slide_bytes}",
            f"slides_seen {self.slides_seen}",
            f"cases_eligible {self.cases_eligible}",
            f"cases_selected {len(self.rows)}",
            f"held_out {sum(1 for row in self.rows if row.held_out)}",
        ]
        for reason in REMOVAL_ORDER:
            lines.append(f"filter {reason} removed {self.removed.get(reason, 0)}")
        for specialty in SPECIALTY_ORDER:
            lines.append(
                f"specialty {specialty} "
                f"eligible {self.eligible_by_specialty.get(specialty, 0)} "
                f"selected {self.selected_by_specialty.get(specialty, 0)} "
                f"held_out {self.held_out_by_specialty.get(specialty, 0)}"
            )
        lines.append(f"wrote {self.cohort_path}")
        lines.append(f"wrote {self.cases_path}")
        return "\n".join(lines) + "\n"


def slide_cap_bytes(max_slide_gb: float) -> int:
    """Decimal gigabytes. 1.0 matches the context.md 'under 1 GB' column."""
    if max_slide_gb <= 0:
        raise ValueError("max_slide_gb must be positive")
    return int(round(max_slide_gb * BYTES_PER_GB))


def build_manifest(
    *,
    tier: str,
    seed: int,
    max_slide_gb: float,
    slides: Sequence[object],
    cases: Sequence[object],
    reports_csv: Path,
    data_root: Path,
) -> ManifestResult:
    """Filter, join, sample, and write `cohort/cohort.csv` plus `source/gdc_cases.parquet`."""
    if tier not in TIER_CASE_COUNTS:
        raise ValueError(f"unknown tier {tier!r}")
    cap = slide_cap_bytes(max_slide_gb)
    reports, corrupt_reports = load_reports(reports_csv)
    removed = dict.fromkeys(REMOVAL_ORDER, 0)
    removed["corrupt_report"] = corrupt_reports
    cases_by_id, corrupt_cases = index_cases(cases)
    removed["corrupt_case"] = corrupt_cases

    parsed: list[SlideFile] = []
    for hit in slides:
        slide, reason = parse_slide(hit)
        if reason is not None or slide is None:
            removed["corrupt_slide"] += 1
            continue
        parsed.append(slide)
    parsed.sort(key=lambda slide: (slide.file_id, slide.file_name))
    unique: list[SlideFile] = []
    seen_ids: set[str] = set()
    for slide in parsed:
        if slide.file_id in seen_ids:
            removed["duplicate_file"] += 1
            continue
        seen_ids.add(slide.file_id)
        unique.append(slide)

    kept: list[SlideFile] = []
    for slide in unique:
        reason = _slide_rejection(slide, cap)
        if reason is not None:
            removed[reason] += 1
            continue
        kept.append(slide)

    groups: dict[str, list[SlideFile]] = {}
    for slide in kept:
        groups.setdefault(slide.submitter_id, []).append(slide)

    eligible: list[tuple[SlideFile, ClinicalCase, str]] = []
    for submitter in sorted(groups):
        group = groups[submitter]
        clinical = cases_by_id.get(submitter)
        if clinical is None:
            removed["missing_case"] += len(group)
            continue
        if clinical.primary_diagnosis is None:
            removed["missing_primary_diagnosis"] += len(group)
            continue
        report = reports.get(submitter)
        if report is None:
            removed["missing_report"] += len(group)
            continue
        if not report.strip():
            removed["empty_report"] += len(group)
            continue
        ordered = sorted(group, key=_slide_sort_key)
        removed["extra_slides"] += len(ordered) - 1
        eligible.append((ordered[0], clinical, report))

    candidates = [
        CohortCandidate(
            specialty=PROJECT_SPECIALTY[slide.project_id],
            case_key=slide.submitter_id,
            history_rank=history_rank(report),
        )
        for slide, _clinical, report in eligible
    ]
    selected = select_cohort(candidates, tier, seed)
    removed["not_sampled"] = len(eligible) - len(selected)

    rows: list[CohortRow] = []
    for slide, clinical, _report in eligible:
        if slide.submitter_id not in selected:
            continue
        specialty = PROJECT_SPECIALTY[slide.project_id]
        case_id = f"{specialty}-{slide.submitter_id}"
        diagnosis = clinical.primary_diagnosis or ""
        rows.append(
            CohortRow(
                case_id=case_id,
                slide_id=f"{case_id}-s1",
                gdc_file_id=slide.file_id,
                file_name=slide.file_name,
                file_size=slide.file_size,
                project_id=slide.project_id,
                specialty=specialty,
                tier=tier,
                held_out=selected[slide.submitter_id],
                submitter_id=slide.submitter_id,
                gdc_case_id=clinical.gdc_case_id,
                patient_sex=clinical.patient_sex,
                patient_age=clinical.patient_age,
                primary_diagnosis=diagnosis,
                morphology=clinical.morphology,
                icd10=clinical.icd10,
                classification_of_tumor=clinical.classification_of_tumor or "primary",
            )
        )
    rows.sort(key=lambda row: (SPECIALTY_ORDER.index(row.specialty), row.case_id))

    cohort_path = data_root / "cohort" / "cohort.csv"
    cases_path = data_root / "source" / "gdc_cases.parquet"
    write_cohort_csv(cohort_path, rows)
    write_cases_parquet(cases_path, rows)

    eligible_counts = dict.fromkeys(SPECIALTY_ORDER, 0)
    for slide, _clinical, _report in eligible:
        eligible_counts[PROJECT_SPECIALTY[slide.project_id]] += 1
    selected_counts = dict.fromkeys(SPECIALTY_ORDER, 0)
    held_counts = dict.fromkeys(SPECIALTY_ORDER, 0)
    for row in rows:
        selected_counts[row.specialty] += 1
        if row.held_out:
            held_counts[row.specialty] += 1

    return ManifestResult(
        tier=tier,
        seed=seed,
        max_slide_bytes=cap,
        rows=tuple(rows),
        removed=removed,
        slides_seen=len(slides),
        cases_eligible=len(eligible),
        eligible_by_specialty=eligible_counts,
        selected_by_specialty=selected_counts,
        held_out_by_specialty=held_counts,
        cohort_path=cohort_path,
        cases_path=cases_path,
    )


def write_cohort_csv(path: Path, rows: Sequence[CohortRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COHORT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "case_id": row.case_id,
                    "slide_id": row.slide_id,
                    "gdc_file_id": row.gdc_file_id,
                    "file_name": row.file_name,
                    "file_size": row.file_size,
                    "project_id": row.project_id,
                    "specialty": row.specialty,
                    "tier": row.tier,
                    "held_out": "true" if row.held_out else "false",
                }
            )


def write_cases_parquet(path: Path, rows: Sequence[CohortRow]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema(
        [
            ("submitter_id", pa.string()),
            ("gdc_case_id", pa.string()),
            ("case_id", pa.string()),
            ("project_id", pa.string()),
            ("specialty", pa.string()),
            ("patient_sex", pa.string()),
            ("patient_age", pa.int64()),
            ("primary_diagnosis", pa.string()),
            ("morphology", pa.string()),
            ("icd10", pa.string()),
            ("classification_of_tumor", pa.string()),
        ]
    )
    payload = [
        {
            "submitter_id": row.submitter_id,
            "gdc_case_id": row.gdc_case_id,
            "case_id": row.case_id,
            "project_id": row.project_id,
            "specialty": row.specialty,
            "patient_sex": row.patient_sex,
            "patient_age": row.patient_age,
            "primary_diagnosis": row.primary_diagnosis,
            "morphology": row.morphology,
            "icd10": row.icd10,
            "classification_of_tumor": row.classification_of_tumor,
        }
        for row in rows
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(payload, schema=schema), path)


def load_hit_file(path: Path) -> list[Any]:
    """Load a JSON list or a saved GDC response (`data.hits`)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, dict) and isinstance(data.get("hits"), list):
            return list(data["hits"])
    raise ValueError(f"{path} is not a list of GDC records or a GDC response")


def _slide_rejection(slide: SlideFile, cap: int) -> str | None:
    if PATIENT_BARCODE.match(slide.submitter_id) is None or not slide.file_name.upper().startswith(
        slide.submitter_id
    ):
        return "bad_barcode"
    if slide.project_id not in PROJECT_SPECIALTY:
        return "unknown_project"
    if not _is_svs(slide):
        return "non_svs"
    if slide.slide_kind != "DX":
        return "non_diagnostic"
    if not _is_ffpe(slide.preservation_methods):
        return "non_ffpe"
    if slide.file_size > cap:
        return "over_size_cap"
    return None


def _is_svs(slide: SlideFile) -> bool:
    return slide.file_name.lower().endswith(".svs") and slide.data_format in {"", "SVS"}


def _is_ffpe(methods: tuple[str, ...]) -> bool:
    if not methods:
        return True
    return any(method.casefold() == "ffpe" for method in methods)


def _slide_sort_key(slide: SlideFile) -> tuple[int, int, str, str]:
    """DX1 first, then the smallest file, then name."""
    prefer_dx1 = 0 if slide.slide_number == 1 else 1
    return (prefer_dx1, slide.file_size, slide.file_name, slide.file_id)
