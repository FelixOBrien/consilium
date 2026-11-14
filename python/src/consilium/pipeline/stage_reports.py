"""Stage 7: patients, cases, reports, chunks, and concepts.

Reads the stage-1 cohort (`cohort.csv`, `gdc_cases.parquet`, `TCGA_Reports.csv`),
builds synthetic longitudinal links and skewed authorship, and writes parquet
under `data/export/`. Report passages use the bge-small passage encoder
(`report` space, 384-d). Concept embeddings are a separate CONCH-Z step.
"""

from __future__ import annotations

import csv
import hashlib
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from consilium.embed.spaces import CONCHZ_DIM, REPORT_DIM  # pragma: allowlist secret
from consilium.embed.text import TextEncoders  # pragma: allowlist secret
from consilium.pipeline.chunking import (  # pragma: allowlist secret
    SECTION_FIELDS,
    ExtractedSections,
    chunk_report,
    clean_report_text,
    clinical_history_is_bounded,
    extract_sections,
)
from consilium.pipeline.cohort import SPECIALTY_ORDER  # pragma: allowlist secret
from consilium.pipeline.concepts import (  # pragma: allowlist secret
    ConceptRow,
    concept_rows,
    encode_concept_rows,
)
from consilium.pipeline.reports import load_reports  # pragma: allowlist secret
from consilium.pipeline.roster import RosterMember, assign_authors  # pragma: allowlist secret

# Hackathon freeze is 15 Nov 2026, 12:00 UK, which is 12:00 UTC.
REFERENCE = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 11, 14, tzinfo=UTC)

_SAMPLE_LABELS = {
    "01": "Primary resection",
    "02": "Recurrent tumour",
    "05": "Additional tumour",
    "06": "Metastatic specimen",
    "07": "Additional metastatic",
    "11": "Normal tissue",
}

_TIERS = frozenset({"smoke", "demo", "stretch"})
_SEXES = frozenset({"F", "M"})


@dataclass(frozen=True)
class CaseInput:
    """One cohort case plus the GDC fields and the OCR report."""

    case_id: str
    project_id: str
    specialty: str
    tier: str
    held_out: bool
    submitter_id: str
    patient_sex: str | None
    patient_age: int | None
    primary_diagnosis: str | None
    morphology: str | None
    icd10: str | None
    report_text: str
    sample_code: str | None = None


@dataclass(frozen=True)
class PatientRow:
    id: str
    display_label: str
    sex: str | None
    birth_year: int | None
    is_synthetic_linkage: bool
    created_at: datetime


@dataclass(frozen=True)
class CaseRow:
    id: str
    patient_id: str
    specimen_label: str | None
    source_dataset: str
    source_case_id: str
    specialty: str
    patient_age: int | None
    patient_sex: str | None
    primary_diagnosis: str | None
    morphology: str | None
    icd10: str | None
    status: str
    assigned_to: str
    accessioned_at: datetime
    is_held_out: bool
    cohort_tier: str
    created_at: datetime


@dataclass(frozen=True)
class ReportRow:
    id: str
    case_id: str
    author_id: str
    status: str
    body: str
    clinical_history: str | None
    gross_description: str | None
    microscopic_description: str | None
    conclusion: str | None
    additional_info: str | None
    icd10: str | None
    signed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class ChunkRow:
    id: int
    report_id: str
    case_id: str
    patient_id: str
    specialty: str
    section: str
    ordinal: int
    text: str
    embedding: tuple[float, ...]
    in_corpus: bool
    created_at: datetime


@dataclass(frozen=True)
class Stage7Result:
    """Parquet-ready rows plus the counts the CLI prints."""

    tier: str
    roster_source: str
    pathologists: tuple[RosterMember, ...]
    patients: tuple[PatientRow, ...]
    cases: tuple[CaseRow, ...]
    reports: tuple[ReportRow, ...]
    chunks: tuple[ChunkRow, ...]
    concepts: tuple[ConceptRow, ...]
    concepts_encoded: bool
    created_at: datetime

    def summary(self) -> str:
        return format_summary(self)


def synthetic_budget(n_cases: int, n_held: int, tier: str) -> tuple[int, int]:
    """Cases to place in synthetic longitudinal groups, and held-out anchors.

    Cohorts of at least 10 cases stay inside 15–20%. Smaller cohorts, including
    a short fixture, still form one pair so the link is exercised. The demo
    tier (and any cohort of 30 or more) includes at least three held-out cases
    when that many exist; smoke scales that down to one.
    """
    if n_cases < 2 or n_held < 0:
        return 0, 0
    if n_cases >= 10:
        low = math.ceil(0.15 * n_cases)
        high = math.floor(0.20 * n_cases + 1e-9)
        raw = round(0.18 * n_cases)
        target = min(max(raw, low), high) if low <= high else max(2, raw)
    else:
        target = 2
    if n_held <= 0:
        min_held = 0
    elif tier == "smoke" or n_cases < 30:
        min_held = 1
    else:
        min_held = min(3, n_held)
    min_held = min(min_held, n_held)
    target = max(target, min_held * 2)
    if n_cases >= 10:
        high = math.floor(0.20 * n_cases + 1e-9)
        target = min(target, max(high, min_held * 2))
    target = min(target, n_cases)
    if target < 2:
        return 0, 0
    return target, min_held


def build_stage7(
    cases: Sequence[CaseInput],
    roster: Sequence[RosterMember],
    encoders: TextEncoders,
    *,
    encode_concepts: bool = False,
    created_at: datetime = CREATED_AT,
    roster_source: str = "builtin",
) -> Stage7Result:
    """Build every stage-7 table from cohort cases. Does not write files."""
    if not cases:
        raise ValueError("stage 7 needs at least one case")
    prepared = _prepare_cases(cases)
    groups = link_patients(prepared)
    authors = assign_authors(
        roster,
        [(case.case_id, case.specialty, case.held_out) for case in prepared],
    )
    patients, case_rows, report_rows, extracted = _materialise(
        groups,
        authors,
        created_at=created_at,
    )
    chunks = _embed_chunks(case_rows, report_rows, extracted, encoders, created_at)
    concepts = concept_rows()
    encoded = False
    if encode_concepts:
        concepts = encode_concept_rows(concepts, encoders)
        encoded = True
    tiers = {case.tier for case in prepared}
    tier = next(iter(tiers)) if len(tiers) == 1 else "mixed"
    result = Stage7Result(
        tier=tier,
        roster_source=roster_source,
        pathologists=tuple(roster),
        patients=patients,
        cases=case_rows,
        reports=report_rows,
        chunks=chunks,
        concepts=concepts,
        concepts_encoded=encoded,
        created_at=created_at,
    )
    validate_stage7(result, prepared)
    return result


def link_patients(cases: Sequence[CaseInput]) -> list[list[CaseInput]]:
    """Group same-donor specimens, then deterministically pair longitudinal histories."""
    by_donor: dict[str, list[CaseInput]] = defaultdict(list)
    for case in cases:
        by_donor[case.submitter_id].append(case)
    natural: list[list[CaseInput]] = []
    singletons: list[CaseInput] = []
    for members in by_donor.values():
        ordered = sorted(members, key=lambda case: case.case_id)
        if len(ordered) > 1:
            _require_compatible(ordered)
            natural.append(ordered)
        else:
            singletons.append(ordered[0])
    tier = _dominant_tier(cases)
    held = sum(1 for case in singletons if case.held_out)
    target, min_held = synthetic_budget(len(singletons), held, tier)
    synthetic, used = _synthetic_groups(singletons, target, min_held)
    leftover = [[case] for case in singletons if case.case_id not in used]
    groups = natural + synthetic + leftover
    groups.sort(key=lambda group: min(case.case_id for case in group))
    return groups


def validate_stage7(result: Stage7Result, sources: Sequence[CaseInput]) -> None:
    """Raise when a model rule is broken. Called before parquet is written."""
    if len(result.cases) != len(sources):
        raise ValueError("every cohort case must become one path_case")
    patients = {patient.id: patient for patient in result.patients}
    if len(patients) != len(result.patients):
        raise ValueError("patient ids must be unique")
    labels = [patient.display_label.casefold() for patient in result.patients]
    if len(labels) != len(set(labels)):
        raise ValueError("patient display labels must be unique")
    by_patient: dict[str, list[CaseRow]] = defaultdict(list)
    reports = {report.case_id: report for report in result.reports}
    if len(reports) != len(result.cases):
        raise ValueError("every case has one report")
    source_keys = [(case.source_dataset, case.source_case_id) for case in result.cases]
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("source_dataset and source_case_id must be unique")
    sources_by_id = {case.case_id: case for case in sources}
    for case in result.cases:
        if case.patient_id not in patients:
            raise ValueError(f"{case.id} has no patient")
        if (case.status == "open") != case.is_held_out:
            raise ValueError(f"{case.id} status must be open exactly when it is held out")
        if case.status not in {"open", "signed_out"}:
            raise ValueError(f"{case.id} has status {case.status}")
        report = reports[case.id]
        if report.id != f"{case.id}-r1":
            raise ValueError(f"{case.id} report id must be {{case_id}}-r1")
        if not report.body.strip():
            raise ValueError(f"{case.id} report body is empty")
        if case.is_held_out:
            if report.status != "withheld" or report.signed_at is not None:
                raise ValueError(f"{case.id} held-out report must be withheld and unsigned")
        else:
            if report.status != "signed" or report.signed_at is None:
                raise ValueError(f"{case.id} corpus report must be signed")
            if report.signed_at <= case.accessioned_at:
                raise ValueError(f"{case.id} must be signed after accession")
            if case.assigned_to != report.author_id:
                raise ValueError(f"{case.id} assigned_to must be the report author")
        if report.author_id != case.assigned_to:
            raise ValueError(f"{case.id} report author drifted from assigned_to")
        for field in SECTION_FIELDS:
            value = getattr(report, field)
            if value is not None and not value.strip():
                raise ValueError(f"{case.id} {field} must be null rather than empty")
        source = sources_by_id[case.id]
        extracted = extract_sections(report.body)
        if not clinical_history_is_bounded(extracted):
            raise ValueError(f"{case.id} clinical_history crosses a diagnosis heading")
        if report.clinical_history and report.clinical_history not in report.body:
            raise ValueError(f"{case.id} clinical_history is not a span of the body")
        if report.icd10 != source.icd10:
            raise ValueError(f"{case.id} report icd10 must come from GDC")
        by_patient[case.patient_id].append(case)
    for patient in result.patients:
        members = sorted(by_patient[patient.id], key=lambda case: case.accessioned_at)
        if not members:
            raise ValueError(f"{patient.id} has no cases")
        sexes = {case.patient_sex for case in members if case.patient_sex}
        if patient.sex is not None and sexes and sexes != {patient.sex}:
            raise ValueError(f"{patient.id} sex does not match its cases")
        ages = [(case.accessioned_at, case.patient_age) for case in members]
        known = [(when, age) for when, age in ages if age is not None]
        for (left_at, left_age), (right_at, right_age) in zip(known, known[1:], strict=False):
            if right_at > left_at and right_age < left_age:
                raise ValueError(f"{patient.id} age must not fall as accession dates advance")
        donor_ids = {sources_by_id[case.id].submitter_id for case in members}
        synthetic = len(donor_ids) > 1
        if patient.is_synthetic_linkage != synthetic:
            raise ValueError(f"{patient.id} synthetic linkage flag does not match its donors")
        if synthetic and len(members) not in {2, 3}:
            raise ValueError(f"{patient.id} synthetic history must be 2 or 3 cases")
        if len(members) > 1:
            latest = members[-1]
            for prior in members[:-1]:
                gap = (latest.accessioned_at - prior.accessioned_at).days
                if gap < 92 or gap > 730:
                    raise ValueError(
                        f"{patient.id} prior cases must be dated 3–24 months earlier"
                    )
                if prior.is_held_out and synthetic:
                    raise ValueError(f"{patient.id} synthetic priors must be signed out")
    chunks_by_report: dict[str, list[ChunkRow]] = defaultdict(list)
    for chunk in result.chunks:
        if len(chunk.embedding) != REPORT_DIM:
            raise ValueError("report chunks must be 384-d")
        norm = math.sqrt(sum(value * value for value in chunk.embedding))
        if abs(norm - 1.0) > 1e-3:
            raise ValueError("report chunk embeddings must be L2-normalised")
        case = next(item for item in result.cases if item.id == chunk.case_id)
        if chunk.patient_id != case.patient_id or chunk.specialty != case.specialty:
            raise ValueError(f"{chunk.case_id} chunk patient or specialty was not copied")
        if chunk.in_corpus != (not case.is_held_out):
            raise ValueError(f"{chunk.case_id} in_corpus must be false exactly on held-out cases")
        if chunk.section not in {*SECTION_FIELDS, "body"}:
            raise ValueError(f"unknown chunk section {chunk.section}")
        if not chunk.text.strip():
            raise ValueError("chunk text is empty")
        chunks_by_report[chunk.report_id].append(chunk)
    for report in result.reports:
        rows = sorted(chunks_by_report[report.id], key=lambda chunk: chunk.ordinal)
        if [chunk.ordinal for chunk in rows] != list(range(len(rows))):
            raise ValueError(f"{report.id} chunk ordinals must be 0..n-1")
        if not rows:
            raise ValueError(f"{report.id} has no chunks")
    if len(result.concepts) < 16:
        raise ValueError("concept list should contain about 20 curated prompts")
    for concept in result.concepts:
        if result.concepts_encoded:
            if concept.embedding is None or len(concept.embedding) != CONCHZ_DIM:
                raise ValueError(f"{concept.id} is missing a 768-d conchz embedding")
            if concept.negative_prompt and (
                concept.negative_embedding is None
                or len(concept.negative_embedding) != CONCHZ_DIM
            ):
                raise ValueError(f"{concept.id} is missing a negative embedding")
        elif concept.embedding is not None or concept.negative_embedding is not None:
            raise ValueError(f"{concept.id} embedding must wait for the encode step")


def write_stage7(result: Stage7Result, export_dir: Path) -> dict[str, Path]:
    """Write the six parquet files. `search_tsv` is generated in Postgres, not here."""
    export_dir.mkdir(parents=True, exist_ok=True)
    written = {
        "pathologist": export_dir / "pathologist.parquet",
        "patient": export_dir / "patient.parquet",
        "path_case": export_dir / "path_case.parquet",
        "report": export_dir / "report.parquet",
        "report_chunk": export_dir / "report_chunk.parquet",
        "concept": export_dir / "concept.parquet",
    }
    _write(written["pathologist"], _pathologist_table(result))
    _write(written["patient"], _patient_table(result))
    _write(written["path_case"], _case_table(result))
    _write(written["report"], _report_table(result))
    _write(written["report_chunk"], _chunk_table(result))
    _write(written["concept"], _concept_table(result))
    return written


def load_case_inputs(
    cohort_csv: Path,
    cases_parquet: Path,
    reports_csv: Path,
) -> list[CaseInput]:
    """Join the manifest files. Report text is matched on the 12-character barcode."""
    if not cohort_csv.is_file():
        raise ValueError(f"cohort file not found: {cohort_csv}")
    if not cases_parquet.is_file():
        raise ValueError(f"clinical parquet not found: {cases_parquet}")
    reports, _corrupt = load_reports(reports_csv)
    clinical = {str(row["case_id"]): row for row in pq.read_table(cases_parquet).to_pylist()}
    inputs: list[CaseInput] = []
    with cohort_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        required = {"case_id", "project_id", "specialty", "tier", "held_out"}
        if not required <= fields:
            raise ValueError(f"cohort.csv is missing columns: {sorted(required - fields)}")
        for row in reader:
            case_id = str(row.get("case_id") or "").strip()
            record = clinical.get(case_id)
            if record is None:
                raise ValueError(f"gdc_cases.parquet has no row for {case_id}")
            submitter = str(record.get("submitter_id") or "").strip().upper()
            text = reports.get(submitter)
            if text is None or not str(text).strip():
                raise ValueError(f"no TCGA report for {case_id}")
            file_name = str(row.get("file_name") or "")
            inputs.append(
                CaseInput(
                    case_id=case_id,
                    project_id=str(record.get("project_id") or row.get("project_id") or "").strip(),
                    specialty=str(row.get("specialty") or record.get("specialty") or "").strip(),
                    tier=str(row.get("tier") or "").strip(),
                    held_out=_flag(str(row.get("held_out") or "")),
                    submitter_id=submitter,
                    patient_sex=_sex(record.get("patient_sex")),
                    patient_age=_age(record.get("patient_age")),
                    primary_diagnosis=_text(record.get("primary_diagnosis")),
                    morphology=_text(record.get("morphology")),
                    icd10=_text(record.get("icd10")),
                    report_text=str(text),
                    sample_code=_sample_code(file_name),
                )
            )
    if not inputs:
        raise ValueError("cohort.csv has no cases")
    return inputs


def run_reports(
    data_root: Path,
    *,
    reports_csv: Path | None,
    roster_path: Path | None,
    encoders: TextEncoders,
    encode_concepts: bool,
    roster: Sequence[RosterMember] | None = None,
    roster_source: str = "builtin",
) -> Stage7Result:
    """Load inputs, build tables, and write `data_root/export`."""
    from consilium.pipeline.roster import resolve_roster  # pragma: allowlist secret

    if roster is None:
        roster, roster_source = resolve_roster(data_root, roster_path)
    reports_path = reports_csv or (data_root / "source" / "TCGA_Reports.csv")
    cases = load_case_inputs(
        data_root / "cohort" / "cohort.csv",
        data_root / "source" / "gdc_cases.parquet",
        reports_path,
    )
    result = build_stage7(
        cases,
        roster,
        encoders,
        encode_concepts=encode_concepts,
        roster_source=roster_source,
    )
    write_stage7(result, data_root / "export")
    return result


def encode_concept_parquet(path: Path, encoders: TextEncoders) -> int:
    """Fill concept embeddings in an existing parquet file and write it back."""
    if not path.is_file():
        raise ValueError(f"concept parquet not found: {path}")
    table = pq.read_table(path)
    loaded = [
        ConceptRow(
            id=str(raw["id"]),
            label=str(raw["label"]),
            prompt=str(raw["prompt"]),
            negative_prompt=_text(raw.get("negative_prompt")),
            specialty=_text(raw.get("specialty")),
            ordinal=int(raw["ordinal"]),
        )
        for raw in table.to_pylist()
    ]
    encoded = encode_concept_rows(loaded, encoders)
    created_values = raw_created(table)
    replacement = Stage7Result(
        tier="",
        roster_source="",
        pathologists=(),
        patients=(),
        cases=(),
        reports=(),
        chunks=(),
        concepts=encoded,
        concepts_encoded=True,
        created_at=CREATED_AT,
    )
    written = _concept_table(replacement, created_at=created_values)
    _write(path, written)
    return len(encoded)


def format_summary(result: Stage7Result) -> str:
    """Heading coverage and the per-specialty authorship skew."""
    reports = result.reports
    total = len(reports) or 1
    synthetic_patients = [patient for patient in result.patients if patient.is_synthetic_linkage]
    by_patient: dict[str, list[CaseRow]] = defaultdict(list)
    for case in result.cases:
        by_patient[case.patient_id].append(case)
    synthetic_cases = sum(len(by_patient[patient.id]) for patient in synthetic_patients)
    held_in_link = 0
    for patient in synthetic_patients:
        held_in_link += sum(1 for case in by_patient[patient.id] if case.is_held_out)
    sizes = sorted(len(by_patient[patient.id]) for patient in synthetic_patients)
    lines = [
        f"tier {result.tier}",
        f"roster {result.roster_source}",
        f"cases {len(result.cases)}",
        f"patients {len(result.patients)}",
        f"synthetic_linkage_patients {len(synthetic_patients)}",
        f"synthetic_linkage_cases {synthetic_cases}",
        f"synthetic_fraction {synthetic_cases / len(result.cases):.3f}",
        f"longitudinal_sizes {','.join(str(size) for size in sizes) if sizes else '-'}",
        f"held_out {sum(1 for case in result.cases if case.is_held_out)}",
        f"held_out_in_longitudinal {held_in_link}",
        f"reports {len(result.reports)}",
        f"chunks {len(result.chunks)}",
        f"concepts {len(result.concepts)}",
        f"concepts_encoded {'yes' if result.concepts_encoded else 'no'}",
        "heading_coverage",
    ]
    for field in SECTION_FIELDS:
        count = sum(1 for report in reports if getattr(report, field))
        lines.append(f"  {field} {count}/{len(reports)} ({count / total:.0%})")
    lines.append("authorship_signed")
    signed = [report for report in result.reports if report.status == "signed"]
    case_specialty = {case.id: case.specialty for case in result.cases}
    members = {member.id: member for member in result.pathologists}
    for specialty in SPECIALTY_ORDER:
        authors: dict[str, int] = defaultdict(int)
        for report in signed:
            if case_specialty[report.case_id] == specialty:
                authors[report.author_id] += 1
        primaries = [
            member for member in result.pathologists if member.primary_specialty == specialty
        ]
        lines.append(f"specialty {specialty} signed {sum(authors.values())}")
        shown: set[str] = set()
        for index, member in enumerate(primaries[:2]):
            role = "lead" if index == 0 else "second"
            lines.append(f"  {member.id} {role} {authors.get(member.id, 0)}")
            shown.add(member.id)
        for author_id, count in sorted(authors.items()):
            if author_id in shown:
                continue
            member = members.get(author_id)
            role = "cross" if member and specialty in member.secondary_specialties else "other"
            lines.append(f"  {author_id} {role} {count}")
    open_demo = 0
    demo_ids = {member.id for member in result.pathologists if member.is_demo_user}
    for case in result.cases:
        if case.is_held_out and case.assigned_to in demo_ids:
            open_demo += 1
    lines.append(f"open_assigned_to_demo {open_demo}")
    return "\n".join(lines) + "\n"


def raw_created(table: pa.Table) -> list[datetime | None]:
    column = table.column("created_at").to_pylist()
    return [value if isinstance(value, datetime) else None for value in column]


def _prepare_cases(cases: Sequence[CaseInput]) -> list[CaseInput]:
    seen: set[str] = set()
    prepared: list[CaseInput] = []
    for case in cases:
        if case.case_id in seen:
            raise ValueError(f"duplicate case id {case.case_id}")
        seen.add(case.case_id)
        if case.specialty not in SPECIALTY_ORDER:
            raise ValueError(f"{case.case_id} has unknown specialty {case.specialty}")
        if case.tier not in _TIERS:
            raise ValueError(f"{case.case_id} has unknown tier {case.tier}")
        body = clean_report_text(case.report_text)
        if not body:
            raise ValueError(f"{case.case_id} report text is empty after cleaning")
        sex = case.patient_sex if case.patient_sex in _SEXES else None
        prepared.append(
            CaseInput(
                case_id=case.case_id,
                project_id=case.project_id,
                specialty=case.specialty,
                tier=case.tier,
                held_out=case.held_out,
                submitter_id=case.submitter_id,
                patient_sex=sex,
                patient_age=case.patient_age,
                primary_diagnosis=case.primary_diagnosis,
                morphology=case.morphology,
                icd10=case.icd10,
                report_text=body,
                sample_code=case.sample_code,
            )
        )
    return prepared


def _dominant_tier(cases: Sequence[CaseInput]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for case in cases:
        counts[case.tier] += 1
    return max(counts, key=lambda tier: (counts[tier], tier))


def _require_compatible(members: Sequence[CaseInput]) -> None:
    sexes = {case.patient_sex for case in members if case.patient_sex}
    if len(sexes) > 1:
        raise ValueError(
            f"donor {members[0].submitter_id} has conflicting sex values {sorted(sexes)}"
        )


def _sex_compatible(left: CaseInput, right: CaseInput) -> bool:
    if left.patient_sex and right.patient_sex:
        return left.patient_sex == right.patient_sex
    return True


def _synthetic_groups(
    singletons: Sequence[CaseInput],
    target: int,
    min_held: int,
) -> tuple[list[list[CaseInput]], set[str]]:
    signed = sorted(
        (case for case in singletons if not case.held_out),
        key=lambda case: (SPECIALTY_ORDER.index(case.specialty), case.case_id),
    )
    held = sorted(
        (case for case in singletons if case.held_out),
        key=lambda case: (SPECIALTY_ORDER.index(case.specialty), case.case_id),
    )
    used: set[str] = set()
    groups: list[list[CaseInput]] = []

    def take_prior(anchor: CaseInput, *, same_specialty: bool) -> CaseInput | None:
        matches = [
            case
            for case in signed
            if case.case_id not in used
            and case.case_id != anchor.case_id
            and _sex_compatible(anchor, case)
            and (not same_specialty or case.specialty == anchor.specialty)
        ]
        if not matches:
            return None
        matches.sort(
            key=lambda case: (
                0 if case.project_id == anchor.project_id else 1,
                0 if case.specialty == anchor.specialty else 1,
                SPECIALTY_ORDER.index(case.specialty),
                case.case_id,
            )
        )
        return matches[0]

    anchors = 0
    for anchor in held:
        if anchors >= min_held:
            break
        prior = take_prior(anchor, same_specialty=True) or take_prior(anchor, same_specialty=False)
        if prior is None:
            continue
        used.add(anchor.case_id)
        used.add(prior.case_id)
        groups.append([prior, anchor])
        anchors += 1

    def used_count() -> int:
        return sum(len(group) for group in groups)

    def add_third(group: list[CaseInput]) -> bool:
        if len(group) >= 3:
            return False
        anchor = next((case for case in group if case.held_out), group[-1])
        prior = take_prior(anchor, same_specialty=True)
        if prior is None:
            return False
        used.add(prior.case_id)
        group.insert(0, prior)
        return True

    def make_pair() -> bool:
        free = [case for case in signed if case.case_id not in used]
        for anchor in free:
            prior = next(
                (
                    case
                    for case in free
                    if case.case_id != anchor.case_id
                    and case.specialty == anchor.specialty
                    and _sex_compatible(anchor, case)
                ),
                None,
            )
            if prior is None:
                continue
            used.add(anchor.case_id)
            used.add(prior.case_id)
            groups.append([prior, anchor])
            return True
        return False

    guard = 0
    while used_count() < target and guard < 10000:
        guard += 1
        gap = target - used_count()
        if gap == 1:
            if not any(add_third(group) for group in groups if len(group) < 3):
                break
            continue
        triples = sum(1 for group in groups if len(group) == 3)
        pairs = sum(1 for group in groups if len(group) == 2)
        if gap >= 3 and triples < pairs and any(add_third(group) for group in groups):
            continue
        if gap >= 2 and make_pair():
            continue
        if any(add_third(group) for group in groups if len(group) == 2):
            continue
        break
    return groups, used


def _materialise(
    groups: Sequence[Sequence[CaseInput]],
    authors: dict[str, str],
    *,
    created_at: datetime,
) -> tuple[
    tuple[PatientRow, ...],
    tuple[CaseRow, ...],
    tuple[ReportRow, ...],
    dict[str, ExtractedSections],
]:
    patients: list[PatientRow] = []
    cases: list[CaseRow] = []
    reports: list[ReportRow] = []
    extracted_by_case: dict[str, ExtractedSections] = {}
    donor_counts: dict[str, int] = defaultdict(int)
    for group in groups:
        for case in group:
            donor_counts[case.submitter_id] += 1
    for index, group in enumerate(groups, start=1):
        members = list(group)
        dates = _accessions(members)
        ages = _ages(members, dates)
        sex = _consensus_sex(members, dates)
        earliest = min(members, key=lambda case: dates[case.case_id])
        earliest_age = ages[earliest.case_id]
        birth_year = None
        if earliest_age is not None:
            birth_year = (dates[earliest.case_id] - timedelta(days=earliest_age * 365)).year
        donors = {case.submitter_id for case in members}
        patient_id = f"pt-{index:04d}"
        patients.append(
            PatientRow(
                id=patient_id,
                display_label=f"PT-{index:04d}",
                sex=sex,
                birth_year=birth_year,
                is_synthetic_linkage=len(donors) > 1,
                created_at=created_at,
            )
        )
        labels = _specimen_labels(members, dates, synthetic=len(donors) > 1)
        for case in members:
            source_id = case.submitter_id
            if donor_counts[case.submitter_id] > 1:
                source_id = (
                    f"{case.submitter_id}-{case.sample_code}"
                    if case.sample_code
                    else case.case_id
                )
            status = "open" if case.held_out else "signed_out"
            cases.append(
                CaseRow(
                    id=case.case_id,
                    patient_id=patient_id,
                    specimen_label=labels[case.case_id],
                    source_dataset=case.project_id,
                    source_case_id=source_id,
                    specialty=case.specialty,
                    patient_age=ages[case.case_id],
                    patient_sex=case.patient_sex or sex,
                    primary_diagnosis=case.primary_diagnosis,
                    morphology=case.morphology,
                    icd10=case.icd10,
                    status=status,
                    assigned_to=authors[case.case_id],
                    accessioned_at=dates[case.case_id],
                    is_held_out=case.held_out,
                    cohort_tier=case.tier,
                    created_at=created_at,
                )
            )
            extracted = extract_sections(case.report_text)
            extracted_by_case[case.case_id] = extracted
            signed_at = None
            report_status = "withheld" if case.held_out else "signed"
            if report_status == "signed":
                signed_at = dates[case.case_id] + timedelta(
                    days=2 + _stable_int(f"sign:{case.case_id}", 5)
                )
            reports.append(
                ReportRow(
                    id=f"{case.case_id}-r1",
                    case_id=case.case_id,
                    author_id=authors[case.case_id],
                    status=report_status,
                    body=extracted.body,
                    clinical_history=extracted.clinical_history,
                    gross_description=extracted.gross_description,
                    microscopic_description=extracted.microscopic_description,
                    conclusion=extracted.conclusion,
                    additional_info=extracted.additional_info,
                    icd10=case.icd10,
                    signed_at=signed_at,
                    created_at=created_at,
                )
            )
    cases.sort(key=lambda case: (SPECIALTY_ORDER.index(case.specialty), case.id))
    reports.sort(key=lambda report: report.case_id)
    return tuple(patients), tuple(cases), tuple(reports), extracted_by_case


def _embed_chunks(
    cases: Sequence[CaseRow],
    reports: Sequence[ReportRow],
    extracted: dict[str, ExtractedSections],
    encoders: TextEncoders,
    created_at: datetime,
) -> tuple[ChunkRow, ...]:
    case_by_id = {case.id: case for case in cases}
    pending: list[tuple[ReportRow, str, str, int]] = []
    for report in reports:
        passages = chunk_report(extracted[report.case_id].body)
        for ordinal, (section, text) in enumerate(passages):
            pending.append((report, section, text, ordinal))
    if not pending:
        return ()
    vectors = encoders.encode_report_passages([item[2] for item in pending])
    rows: list[ChunkRow] = []
    for index, ((report, section, text, ordinal), encoding) in enumerate(
        zip(pending, vectors, strict=True),
        start=1,
    ):
        case = case_by_id[report.case_id]
        rows.append(
            ChunkRow(
                id=index,
                report_id=report.id,
                case_id=report.case_id,
                patient_id=case.patient_id,
                specialty=case.specialty,
                section=section,
                ordinal=ordinal,
                text=text,
                embedding=encoding.vector.values,
                in_corpus=not case.is_held_out,
                created_at=created_at,
            )
        )
    return tuple(rows)


def _accessions(members: Sequence[CaseInput]) -> dict[str, datetime]:
    latest = _choose_latest(members)
    latest_at = _accession_for(latest.case_id)
    priors = sorted(
        (case for case in members if case.case_id != latest.case_id),
        key=lambda case: case.case_id,
    )
    dates = {latest.case_id: latest_at}
    for index, prior in enumerate(priors):
        if len(priors) == 1:
            offset = 92 + _stable_int(f"gap:{prior.case_id}", 639)
        elif index == 0:
            offset = 450 + _stable_int(f"gap:{prior.case_id}", 281)
        else:
            offset = 92 + _stable_int(f"gap:{prior.case_id}", 180)
        dates[prior.case_id] = latest_at - timedelta(days=offset)
    return dates


def _choose_latest(members: Sequence[CaseInput]) -> CaseInput:
    held = [case for case in members if case.held_out]
    pool = held if len(held) == 1 else list(members)
    if len(held) > 1:
        pool = held
    return max(pool, key=lambda case: (_accession_for(case.case_id), case.case_id))


def _accession_for(case_id: str) -> datetime:
    days = 1 + _stable_int(f"day:{case_id}", 90)
    minutes = _stable_int(f"min:{case_id}", 10 * 60)
    return REFERENCE - timedelta(days=days, minutes=minutes)


def _ages(members: Sequence[CaseInput], dates: dict[str, datetime]) -> dict[str, int | None]:
    known = [case.patient_age for case in members if case.patient_age is not None]
    if not known:
        return {case.case_id: None for case in members}
    base = min(known)
    earliest = min(dates.values())
    return {
        case.case_id: base + (dates[case.case_id] - earliest).days // 365
        for case in members
    }


def _consensus_sex(members: Sequence[CaseInput], dates: dict[str, datetime]) -> str | None:
    ordered = sorted(members, key=lambda case: dates[case.case_id])
    sexes = [case.patient_sex for case in ordered if case.patient_sex in _SEXES]
    if not sexes:
        return None
    if len(set(sexes)) > 1:
        raise ValueError("a patient group has conflicting sex values")
    return sexes[0]


def _specimen_labels(
    members: Sequence[CaseInput],
    dates: dict[str, datetime],
    *,
    synthetic: bool,
) -> dict[str, str]:
    ordered = sorted(members, key=lambda case: dates[case.case_id])
    if len(ordered) == 1:
        return {ordered[0].case_id: _sample_label(ordered[0])}
    if not synthetic:
        return {case.case_id: _sample_label(case) for case in ordered}
    names = {
        2: ("Prior core biopsy", "Excision"),
        3: ("Prior core biopsy", "Prior resection", "Excision"),
    }.get(len(ordered))
    if names is None:
        names = tuple(
            "Prior core biopsy" if index == 0 else "Excision" for index in range(len(ordered))
        )
    return {case.case_id: names[index] for index, case in enumerate(ordered)}


def _sample_label(case: CaseInput) -> str:
    code = (case.sample_code or "")[:2]
    return _SAMPLE_LABELS.get(code, "Primary resection")


def _stable_int(key: str, modulo: int) -> int:
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], "big") % modulo


def _flag(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "t", "yes"}


def _sex(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().upper()
    if token in _SEXES:
        return token
    return None


def _age(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _sample_code(file_name: str) -> str | None:
    parts = file_name.upper().split(".")[0].split("-")
    if len(parts) < 4:
        return None
    token = parts[3]
    if len(token) >= 2 and token[:2].isdigit():
        return token
    return None


def _write(path: Path, table: pa.Table) -> None:
    pq.write_table(table, path)


def _timestamp() -> pa.DataType:
    return pa.timestamp("us", tz="UTC")


def _vectors(values: Sequence[Sequence[float] | None], dim: int) -> pa.Array:
    data: list[list[float] | None] = []
    for item in values:
        if item is None:
            data.append(None)
        else:
            data.append([float(component) for component in item])
    return pa.array(data, type=pa.list_(pa.float32(), dim))


def _pathologist_table(result: Stage7Result) -> pa.Table:
    rows = result.pathologists
    return pa.table(
        {
            "id": [row.id for row in rows],
            "name": [row.name for row in rows],
            "role_title": [row.role_title for row in rows],
            "primary_specialty": [row.primary_specialty for row in rows],
            "secondary_specialties": [list(row.secondary_specialties) for row in rows],
            "is_demo_user": [row.is_demo_user for row in rows],
            "is_synthetic": [row.is_synthetic for row in rows],
            "created_at": [result.created_at for _ in rows],
        },
        schema=pa.schema(
            [
                ("id", pa.string(), False),
                ("name", pa.string(), False),
                ("role_title", pa.string(), False),
                ("primary_specialty", pa.string(), False),
                ("secondary_specialties", pa.list_(pa.string()), False),
                ("is_demo_user", pa.bool_(), False),
                ("is_synthetic", pa.bool_(), False),
                ("created_at", _timestamp(), False),
            ]
        ),
    )


def _patient_table(result: Stage7Result) -> pa.Table:
    rows = result.patients
    return pa.table(
        {
            "id": [row.id for row in rows],
            "display_label": [row.display_label for row in rows],
            "sex": [row.sex for row in rows],
            "birth_year": [row.birth_year for row in rows],
            "is_synthetic_linkage": [row.is_synthetic_linkage for row in rows],
            "created_at": [row.created_at for row in rows],
        },
        schema=pa.schema(
            [
                ("id", pa.string(), False),
                ("display_label", pa.string(), False),
                ("sex", pa.string(), True),
                ("birth_year", pa.int64(), True),
                ("is_synthetic_linkage", pa.bool_(), False),
                ("created_at", _timestamp(), False),
            ]
        ),
    )


def _case_table(result: Stage7Result) -> pa.Table:
    rows = result.cases
    return pa.table(
        {
            "id": [row.id for row in rows],
            "patient_id": [row.patient_id for row in rows],
            "specimen_label": [row.specimen_label for row in rows],
            "source_dataset": [row.source_dataset for row in rows],
            "source_case_id": [row.source_case_id for row in rows],
            "specialty": [row.specialty for row in rows],
            "patient_age": [row.patient_age for row in rows],
            "patient_sex": [row.patient_sex for row in rows],
            "primary_diagnosis": [row.primary_diagnosis for row in rows],
            "morphology": [row.morphology for row in rows],
            "icd10": [row.icd10 for row in rows],
            "status": [row.status for row in rows],
            "assigned_to": [row.assigned_to for row in rows],
            "accessioned_at": [row.accessioned_at for row in rows],
            "is_held_out": [row.is_held_out for row in rows],
            "cohort_tier": [row.cohort_tier for row in rows],
            "created_at": [row.created_at for row in rows],
        },
        schema=pa.schema(
            [
                ("id", pa.string(), False),
                ("patient_id", pa.string(), False),
                ("specimen_label", pa.string(), True),
                ("source_dataset", pa.string(), False),
                ("source_case_id", pa.string(), False),
                ("specialty", pa.string(), False),
                ("patient_age", pa.int64(), True),
                ("patient_sex", pa.string(), True),
                ("primary_diagnosis", pa.string(), True),
                ("morphology", pa.string(), True),
                ("icd10", pa.string(), True),
                ("status", pa.string(), False),
                ("assigned_to", pa.string(), False),
                ("accessioned_at", _timestamp(), False),
                ("is_held_out", pa.bool_(), False),
                ("cohort_tier", pa.string(), False),
                ("created_at", _timestamp(), False),
            ]
        ),
    )


def _report_table(result: Stage7Result) -> pa.Table:
    rows = result.reports
    return pa.table(
        {
            "id": [row.id for row in rows],
            "case_id": [row.case_id for row in rows],
            "author_id": [row.author_id for row in rows],
            "status": [row.status for row in rows],
            "body": [row.body for row in rows],
            "clinical_history": [row.clinical_history for row in rows],
            "gross_description": [row.gross_description for row in rows],
            "microscopic_description": [row.microscopic_description for row in rows],
            "conclusion": [row.conclusion for row in rows],
            "additional_info": [row.additional_info for row in rows],
            "icd10": [row.icd10 for row in rows],
            "signed_at": [row.signed_at for row in rows],
            "created_at": [row.created_at for row in rows],
        },
        schema=pa.schema(
            [
                ("id", pa.string(), False),
                ("case_id", pa.string(), False),
                ("author_id", pa.string(), False),
                ("status", pa.string(), False),
                ("body", pa.string(), False),
                ("clinical_history", pa.string(), True),
                ("gross_description", pa.string(), True),
                ("microscopic_description", pa.string(), True),
                ("conclusion", pa.string(), True),
                ("additional_info", pa.string(), True),
                ("icd10", pa.string(), True),
                ("signed_at", _timestamp(), True),
                ("created_at", _timestamp(), False),
            ]
        ),
    )


def _chunk_table(result: Stage7Result) -> pa.Table:
    rows = result.chunks
    schema = pa.schema(
        [
            ("id", pa.int64(), False),
            ("report_id", pa.string(), False),
            ("case_id", pa.string(), False),
            ("patient_id", pa.string(), False),
            ("specialty", pa.string(), False),
            ("section", pa.string(), False),
            ("ordinal", pa.int64(), False),
            ("text", pa.string(), False),
            ("embedding", pa.list_(pa.float32(), REPORT_DIM), False),
            ("in_corpus", pa.bool_(), False),
            ("created_at", _timestamp(), False),
        ]
    )
    return pa.table(
        {
            "id": [row.id for row in rows],
            "report_id": [row.report_id for row in rows],
            "case_id": [row.case_id for row in rows],
            "patient_id": [row.patient_id for row in rows],
            "specialty": [row.specialty for row in rows],
            "section": [row.section for row in rows],
            "ordinal": [row.ordinal for row in rows],
            "text": [row.text for row in rows],
            "embedding": _vectors([row.embedding for row in rows], REPORT_DIM),
            "in_corpus": [row.in_corpus for row in rows],
            "created_at": [row.created_at for row in rows],
        },
        schema=schema,
    )


def _concept_table(
    result: Stage7Result,
    *,
    created_at: Sequence[datetime | None] | None = None,
) -> pa.Table:
    rows = result.concepts
    created = list(created_at) if created_at is not None else [result.created_at for _ in rows]
    if len(created) != len(rows):
        created = [result.created_at for _ in rows]
    schema = pa.schema(
        [
            ("id", pa.string(), False),
            ("label", pa.string(), False),
            ("prompt", pa.string(), False),
            ("negative_prompt", pa.string(), True),
            ("specialty", pa.string(), True),
            ("ordinal", pa.int64(), False),
            ("embedding", pa.list_(pa.float32(), CONCHZ_DIM), True),
            ("negative_embedding", pa.list_(pa.float32(), CONCHZ_DIM), True),
            ("created_at", _timestamp(), False),
        ]
    )
    return pa.table(
        {
            "id": [row.id for row in rows],
            "label": [row.label for row in rows],
            "prompt": [row.prompt for row in rows],
            "negative_prompt": [row.negative_prompt for row in rows],
            "specialty": [row.specialty for row in rows],
            "ordinal": [row.ordinal for row in rows],
            "embedding": _vectors([row.embedding for row in rows], CONCHZ_DIM),
            "negative_embedding": _vectors([row.negative_embedding for row in rows], CONCHZ_DIM),
            "created_at": created,
        },
        schema=schema,
    )
