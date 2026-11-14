"""Stage 7: patients, reports, authorship, chunks, and concepts."""

from __future__ import annotations

import csv
import math
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from consilium.api.store import DEMO_USER_ID  # pragma: allowlist secret
from consilium.embed import MockTextEncoder, build_text_encoders  # pragma: allowlist secret
from consilium.embed.spaces import CONCHZ_DIM, REPORT_DIM  # pragma: allowlist secret
from consilium.embed.text import ReportTextKind  # pragma: allowlist secret
from consilium.pipeline.chunking import (  # pragma: allowlist secret
    chunk_report,
    chunk_span,
    clean_report_text,
    extract_sections,
    partition_body,
    split_sentences,
)
from consilium.pipeline.cohort import SPECIALTY_ORDER  # pragma: allowlist secret
from consilium.pipeline.concepts import concept_rows  # pragma: allowlist secret
from consilium.pipeline.roster import (  # pragma: allowlist secret
    DEFAULT_DEMO_USER_ID,
    assign_authors,
    author_slots,
    builtin_roster,
    load_roster_file,
)
from consilium.pipeline.stage_reports import (  # pragma: allowlist secret
    CaseInput,
    build_stage7,
    synthetic_budget,
    write_stage7,
)

_DIAGNOSIS = "poorly differentiated adenocarcinoma secret-marker"
_REPORT = (
    "Clinical History: weight loss for three months. "
    "Gross Description: a 2 cm firm nodule. "
    "Microscopic Description: infiltrative glands in desmoplastic stroma. "
    f"Final Diagnosis: {_DIAGNOSIS}. "
    "Comment: synoptic staging was recorded."
)


def _encoders():
    return build_text_encoders(backend=MockTextEncoder())


def _norm(values: tuple[float, ...] | list[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def test_builtin_roster_matches_the_demo_user() -> None:
    roster = builtin_roster()
    assert DEFAULT_DEMO_USER_ID == DEMO_USER_ID
    assert len(roster) == 12
    assert sum(member.is_demo_user for member in roster) == 1
    assert all(member.is_synthetic for member in roster)
    demo = next(member for member in roster if member.is_demo_user)
    assert demo.id == DEMO_USER_ID
    assert demo.primary_specialty == "breast"
    for specialty in SPECIALTY_ORDER:
        primaries = [member for member in roster if member.primary_specialty == specialty]
        assert len(primaries) == 2
    names = {member.name for member in roster}
    assert len(names) == 12


def test_roster_file_overrides_builtin_and_rejects_a_real_person(tmp_path: Path) -> None:
    path = tmp_path / "roster.json"
    path.write_text(
        """
        [
          {"id": "path-okafor", "name": "Dr A. Okafor", "role_title": "Consultant Histopathologist",
           "primary_specialty": "breast", "secondary_specialties": ["skin"],
           "is_demo_user": true, "is_synthetic": false}
        ]
        """,
        encoding="utf-8",
    )
    try:
        load_roster_file(path)
    except ValueError as exc:
        assert "synthetic" in str(exc)
    else:
        raise AssertionError("a non-synthetic roster member was accepted")


def test_clinical_history_stops_before_diagnosis_and_gross() -> None:
    extracted = extract_sections(_REPORT)
    assert extracted.clinical_history == "weight loss for three months."
    assert extracted.gross_description == "a 2 cm firm nodule."
    assert extracted.microscopic_description == "infiltrative glands in desmoplastic stroma."
    assert extracted.conclusion == f"{_DIAGNOSIS}."
    assert extracted.additional_info == "synoptic staging was recorded."
    assert "secret-marker" not in (extracted.clinical_history or "")
    assert "Final Diagnosis" not in (extracted.clinical_history or "")
    assert "nodule" not in (extracted.clinical_history or "")
    assert extracted.clinical_history in extracted.body
    spans = partition_body(extracted.body)
    assert "".join(text for _, text in spans) == extracted.body
    assert [section for section, _ in spans if section != "body"] == [
        "clinical_history",
        "gross_description",
        "microscopic_description",
        "conclusion",
        "additional_info",
    ]
    passages = chunk_report(extracted.body)
    assert [text.split() for _, text in passages] == [text.split() for _, text in spans]
    words = extracted.body.split()
    assert [word for _, text in passages for word in text.split()] == words


def test_preoperative_diagnosis_is_clinical_not_a_conclusion() -> None:
    body = (
        "Preoperative Diagnosis: a mass in the breast. "
        "Final Diagnosis: secret-marker carcinoma."
    )
    extracted = extract_sections(body)
    assert extracted.clinical_history == "a mass in the breast."
    assert "secret-marker" not in (extracted.clinical_history or "")
    assert extracted.conclusion == "secret-marker carcinoma."
    assert extracted.clinical_end is not None
    assert extracted.clinical_stop is not None
    assert extracted.clinical_end <= extracted.clinical_stop


def test_missing_headings_stay_null_and_the_body_is_one_chunk() -> None:
    body = clean_report_text("Recelpt of a   short note without headings")
    assert body == "Receipt of a short note without headings"
    extracted = extract_sections(body)
    assert extracted.clinical_history is None
    assert extracted.gross_description is None
    assert extracted.microscopic_description is None
    assert extracted.conclusion is None
    assert extracted.additional_info is None
    assert chunk_report(body) == [("body", body)]


def test_sentence_overlap_past_200_words() -> None:
    sentences = []
    for index in range(15):
        tokens = [f"w{index}x{token}" for token in range(20)]
        sentences.append(" ".join(tokens) + ".")
    text = " ".join(sentences)
    assert len(text.split()) == 300
    chunks = chunk_span(text)
    assert len(chunks) >= 2
    first = split_sentences(chunks[0])
    second = split_sentences(chunks[1])
    assert second[0] == first[-1]
    assert len(chunks[0].split()) <= 200
    assert len(second[0].split()) <= 200
    rebuilt = [first[0]]
    rebuilt.extend(first[1:])
    rebuilt.extend(second[1:])
    for extra in chunks[2:]:
        rebuilt.extend(split_sentences(extra)[1:])
    assert rebuilt == split_sentences(text)


def test_abbreviation_does_not_split_a_sentence() -> None:
    text = "Dr. Smith reviewed the slide. The tumour forms glands."
    assert split_sentences(text) == [
        "Dr. Smith reviewed the slide.",
        "The tumour forms glands.",
    ]


def test_synthetic_budget_keeps_the_documented_band() -> None:
    assert synthetic_budget(10, 2, "smoke") == (2, 1)
    assert synthetic_budget(200, 10, "demo") == (36, 3)
    cases, held = synthetic_budget(30, 6, "demo")
    assert held == 3
    assert 0.15 <= cases / 30 <= 0.20
    low, high = synthetic_budget(500, 25, "stretch")
    assert 0.15 <= low / 500 <= 0.20
    assert high == 3


def test_authorship_skew_and_demo_open_cases() -> None:
    roster = builtin_roster()
    signed = [(f"breast-TCGA-BB-{index:04d}", "breast", False) for index in range(8)]
    assigned = assign_authors(roster, signed)
    counts = Counter(assigned.values())
    assert counts["path-okafor"] > counts["path-brennan"] >= 1
    assert counts["path-vogel"] + counts["path-singh"] >= 1
    lead, second, cross = author_slots(8, has_second=True, has_cross=True)
    assert lead > second >= 1 and cross >= 1
    assert lead + second + cross == 8

    opens = [(f"case-{index}", "breast" if index < 2 else "thorax", True) for index in range(6)]
    open_assigned = assign_authors(roster, opens)
    assert sum(author == DEMO_USER_ID for author in open_assigned.values()) == 3
    others = {author for author in open_assigned.values() if author != DEMO_USER_ID}
    assert others <= {"path-adebayo", "path-vogel"}


def test_longitudinal_pairing_held_out_and_natural_donor(tmp_path: Path) -> None:
    cases = [
        _case(index, specialty, held_out=held, age=50 + index, tier="demo")
        for index, (specialty, held) in enumerate(
            [
                ("breast", True),
                ("breast", False),
                ("thorax", True),
                ("thorax", False),
                ("colorectal", True),
                ("colorectal", False),
                ("gastrointestinal", False),
                ("gastrointestinal", False),
                ("skin", False),
                ("hematologic", False),
            ]
        )
    ]
    # Two specimens from one extra donor. They must not be marked synthetic.
    cases.append(
        _case(
            20,
            "skin",
            submitter="TCGA-ZZ-0001",
            sample="01Z",
            text="Skin primary without headings but with enough words.",
            project="TCGA-SKCM",
            age=55,
            tier="demo",
        )
    )
    cases.append(
        _case(
            21,
            "skin",
            submitter="TCGA-ZZ-0001",
            sample="06Z",
            text="Skin metastasis without headings but with enough words.",
            project="TCGA-SKCM",
            age=56,
            tier="demo",
            case_override=True,
        )
    )
    result = build_stage7(cases, builtin_roster(), _encoders(), roster_source="builtin")
    synthetic = [patient for patient in result.patients if patient.is_synthetic_linkage]
    assert synthetic
    by_patient: dict[str, list] = {}
    for case in result.cases:
        by_patient.setdefault(case.patient_id, []).append(case)
    for patient in synthetic:
        members = sorted(by_patient[patient.id], key=lambda case: case.accessioned_at)
        assert len(members) in {2, 3}
        ages = [case.patient_age for case in members]
        assert all(age is not None for age in ages)
        assert ages == sorted(ages)
        latest = members[-1]
        for prior in members[:-1]:
            gap = (latest.accessioned_at - prior.accessioned_at).days
            assert 92 <= gap <= 730
            assert prior.status == "signed_out"
            assert not prior.is_held_out
        if patient.birth_year is not None and members[0].patient_age is not None:
            derived = (
                members[0].accessioned_at - timedelta(days=members[0].patient_age * 365)
            ).year
            assert patient.birth_year == derived
        assert len({case.patient_sex for case in members}) == 1
        assert patient.sex == members[0].patient_sex
    held_cases = [case for case in result.cases if case.is_held_out]
    assert held_cases
    assert all(case.status == "open" for case in held_cases)
    linked_held = [
        case
        for patient in synthetic
        for case in by_patient[patient.id]
        if case.is_held_out
    ]
    assert linked_held
    natural = next(
        patient
        for patient in result.patients
        if not patient.is_synthetic_linkage and len(by_patient[patient.id]) > 1
    )
    natural_cases = by_patient[natural.id]
    assert {case.source_case_id for case in natural_cases} == {
        "TCGA-ZZ-0001-01Z",
        "TCGA-ZZ-0001-06Z",
    }
    assert {case.specimen_label for case in natural_cases} == {
        "Primary resection",
        "Metastatic specimen",
    }
    reports = {report.case_id: report for report in result.reports}
    chunks = {chunk.case_id: [] for chunk in result.chunks}
    for chunk in result.chunks:
        chunks[chunk.case_id].append(chunk)
    for case in held_cases:
        report = reports[case.id]
        assert report.status == "withheld"
        assert report.signed_at is None
        assert report.body
        assert "secret-marker" not in (report.clinical_history or "")
        assert report.conclusion and "secret-marker" in report.conclusion
        assert report.icd10 == "C50.9"
        assert chunks[case.id]
        assert all(not chunk.in_corpus for chunk in chunks[case.id])
        assert all(chunk.patient_id == case.patient_id for chunk in chunks[case.id])
    signed = [case for case in result.cases if not case.is_held_out]
    for case in signed:
        report = reports[case.id]
        assert report.status == "signed"
        assert report.author_id == case.assigned_to
        assert report.signed_at is not None and report.signed_at > case.accessioned_at
        assert all(chunk.in_corpus for chunk in chunks[case.id])
    demo_open = [case for case in held_cases if case.assigned_to == DEMO_USER_ID]
    assert len(demo_open) == min(3, len(held_cases))
    summary = result.summary()
    assert "heading_coverage" in summary
    assert "authorship_signed" in summary
    assert "path-okafor lead" in summary
    paths = write_stage7(result, tmp_path / "export")
    _assert_parquet_schemas(paths, encoded=False)
    again = build_stage7(cases, builtin_roster(), _encoders())
    assert [patient.id for patient in again.patients] == [patient.id for patient in result.patients]
    assert [case.assigned_to for case in again.cases] == [case.assigned_to for case in result.cases]
    assert [chunk.embedding for chunk in again.chunks] == [
        chunk.embedding for chunk in result.chunks
    ]


def test_passage_embeddings_are_report_space_not_queries() -> None:
    backend = MockTextEncoder()
    cases = [_case(1, "breast", held_out=False), _case(2, "thorax", held_out=True)]
    result = build_stage7(cases, builtin_roster(), build_text_encoders(backend=backend))
    assert result.chunks
    for chunk in result.chunks:
        passage = backend.encode_report([chunk.text], kind=ReportTextKind.PASSAGE)[0]
        query = backend.encode_report([chunk.text], kind=ReportTextKind.QUERY)[0]
        assert chunk.embedding == passage.values
        assert chunk.embedding != query.values
        assert len(chunk.embedding) == REPORT_DIM
        assert abs(_norm(chunk.embedding) - 1) < 1e-6
    assert all(concept.embedding is None for concept in result.concepts)


def test_concept_encoding_is_a_separate_conchz_step(tmp_path: Path) -> None:
    rows = concept_rows()
    assert len(rows) == 20
    assert {row.specialty for row in rows if row.specialty} == set(SPECIALTY_ORDER)
    assert any(row.negative_prompt is None for row in rows)
    assert all(len(row.prompt.split()) + 2 < 127 for row in rows)
    cases = [_case(1, "breast")]
    plain = build_stage7(cases, builtin_roster(), _encoders(), encode_concepts=False)
    encoded = build_stage7(cases, builtin_roster(), _encoders(), encode_concepts=True)
    assert all(row.embedding is None for row in plain.concepts)
    assert len(encoded.concepts) == 20
    for row in encoded.concepts:
        assert row.embedding is not None
        assert len(row.embedding) == CONCHZ_DIM
        assert abs(_norm(row.embedding) - 1) < 1e-6
        if row.negative_prompt is None:
            assert row.negative_embedding is None
        else:
            assert row.negative_embedding is not None
            assert len(row.negative_embedding) == CONCHZ_DIM
    paths = write_stage7(encoded, tmp_path)
    table = pq.read_table(paths["concept"])
    assert table.column("embedding").null_count == 0
    assert table.column("negative_embedding").null_count == sum(
        row.negative_prompt is None for row in encoded.concepts
    )


def test_cli_reports_and_encode_concepts(tmp_path: Path) -> None:
    from consilium.pipeline.__main__ import main  # pragma: allowlist secret

    _write_inputs(tmp_path, [_case(index, "breast", held_out=index == 0) for index in range(4)])
    code = main(
        [
            "reports",
            "--data-root",
            str(tmp_path),
            "--encoder",
            "mock",
            "--reports",
            str(tmp_path / "source" / "TCGA_Reports.csv"),
        ]
    )
    assert code == 0
    concept_path = tmp_path / "export" / "concept.parquet"
    assert pq.read_table(concept_path).column("embedding").null_count == 20
    code = main(["encode-concepts", "--data-root", str(tmp_path), "--encoder", "mock"])
    assert code == 0
    encoded = pq.read_table(concept_path)
    assert encoded.column("embedding").null_count == 0
    assert len(encoded.column("embedding")[0].as_py()) == CONCHZ_DIM


def test_held_out_fraction_on_a_demo_sized_slice() -> None:
    cases = []
    index = 0
    for specialty in SPECIALTY_ORDER:
        for offset in range(5):
            cases.append(
                _case(
                    index,
                    specialty,
                    held_out=offset == 0,
                    age=40 + offset,
                    tier="demo",
                    sex="M" if specialty in {"thorax", "hematologic"} else "F",
                )
            )
            index += 1
    result = build_stage7(cases, builtin_roster(), _encoders())
    synthetic_ids = {patient.id for patient in result.patients if patient.is_synthetic_linkage}
    fraction = sum(case.patient_id in synthetic_ids for case in result.cases) / len(result.cases)
    assert 0.15 <= fraction <= 0.20
    linked_held = 0
    patients = {patient.id: patient for patient in result.patients}
    for case in result.cases:
        if case.is_held_out and patients[case.patient_id].is_synthetic_linkage:
            linked_held += 1
            assert case.status == "open"
    assert linked_held >= 3
    case_by_id = {case.id: case for case in result.cases}
    breast_signed = Counter(
        report.author_id
        for report in result.reports
        if report.status == "signed" and case_by_id[report.case_id].specialty == "breast"
    )
    if sum(breast_signed.values()) >= 3:
        assert breast_signed["path-okafor"] > breast_signed["path-brennan"]


def _case(
    index: int,
    specialty: str,
    *,
    held_out: bool = False,
    sex: str | None = "F",
    age: int | None = 60,
    text: str = _REPORT,
    submitter: str | None = None,
    project: str = "TCGA-BRCA",
    sample: str | None = "01Z",
    tier: str = "smoke",
    diagnosis: str | None = "Adenocarcinoma, NOS",
    morphology: str | None = "8140/3",
    icd10: str | None = "C50.9",
    case_override: bool = False,
) -> CaseInput:
    barcode = submitter or f"TCGA-AA-{index:04d}"
    suffix = f"-{sample}" if case_override and sample else ""
    return CaseInput(
        case_id=f"{specialty}-{barcode}{suffix}",
        project_id=project,
        specialty=specialty,
        tier=tier,
        held_out=held_out,
        submitter_id=barcode,
        patient_sex=sex,
        patient_age=age,
        primary_diagnosis=diagnosis,
        morphology=morphology,
        icd10=icd10,
        report_text=text,
        sample_code=sample,
    )


def _write_inputs(root: Path, cases: list[CaseInput]) -> None:
    cohort = root / "cohort" / "cohort.csv"
    cohort.parent.mkdir(parents=True, exist_ok=True)
    with cohort.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "slide_id",
                "gdc_file_id",
                "file_name",
                "file_size",
                "project_id",
                "specialty",
                "tier",
                "held_out",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        for case in cases:
            sample = case.sample_code or "01Z"
            writer.writerow(
                {
                    "case_id": case.case_id,
                    "slide_id": f"{case.case_id}-s1",
                    "gdc_file_id": case.case_id,
                    "file_name": f"{case.submitter_id}-{sample}-00-DX1.fixture.svs",
                    "file_size": "100",
                    "project_id": case.project_id,
                    "specialty": case.specialty,
                    "tier": case.tier,
                    "held_out": "true" if case.held_out else "false",
                }
            )
    clinical = root / "source" / "gdc_cases.parquet"
    clinical.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "submitter_id": [case.submitter_id for case in cases],
                "gdc_case_id": [case.case_id for case in cases],
                "case_id": [case.case_id for case in cases],
                "project_id": [case.project_id for case in cases],
                "specialty": [case.specialty for case in cases],
                "patient_sex": [case.patient_sex for case in cases],
                "patient_age": [case.patient_age for case in cases],
                "primary_diagnosis": [case.primary_diagnosis for case in cases],
                "morphology": [case.morphology for case in cases],
                "icd10": [case.icd10 for case in cases],
                "classification_of_tumor": ["primary" for _ in cases],
            }
        ),
        clinical,
    )
    reports = root / "source" / "TCGA_Reports.csv"
    with reports.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["patient_filename", "text"])
        seen: set[str] = set()
        for case in cases:
            if case.submitter_id in seen:
                continue
            seen.add(case.submitter_id)
            writer.writerow([f"{case.submitter_id}.fixture", case.report_text])


def _assert_parquet_schemas(paths: dict[str, Path], *, encoded: bool) -> None:
    expected = {
        "pathologist": [
            "id",
            "name",
            "role_title",
            "primary_specialty",
            "secondary_specialties",
            "is_demo_user",
            "is_synthetic",
            "created_at",
        ],
        "patient": [
            "id",
            "display_label",
            "sex",
            "birth_year",
            "is_synthetic_linkage",
            "created_at",
        ],
        "path_case": [
            "id",
            "patient_id",
            "specimen_label",
            "source_dataset",
            "source_case_id",
            "specialty",
            "patient_age",
            "patient_sex",
            "primary_diagnosis",
            "morphology",
            "icd10",
            "status",
            "assigned_to",
            "accessioned_at",
            "is_held_out",
            "cohort_tier",
            "created_at",
        ],
        "report": [
            "id",
            "case_id",
            "author_id",
            "status",
            "body",
            "clinical_history",
            "gross_description",
            "microscopic_description",
            "conclusion",
            "additional_info",
            "icd10",
            "signed_at",
            "created_at",
        ],
        "report_chunk": [
            "id",
            "report_id",
            "case_id",
            "patient_id",
            "specialty",
            "section",
            "ordinal",
            "text",
            "embedding",
            "in_corpus",
            "created_at",
        ],
        "concept": [
            "id",
            "label",
            "prompt",
            "negative_prompt",
            "specialty",
            "ordinal",
            "embedding",
            "negative_embedding",
            "created_at",
        ],
    }
    vector = pa.list_(pa.float32(), REPORT_DIM)
    halfvec = pa.list_(pa.float32(), CONCHZ_DIM)
    for name, columns in expected.items():
        table = pq.read_table(paths[name])
        assert table.column_names == columns
        assert table.schema.field("created_at").type == pa.timestamp("us", tz="UTC")
    chunks = pq.read_table(paths["report_chunk"])
    assert chunks.schema.field("embedding").type == vector
    concepts = pq.read_table(paths["concept"])
    assert concepts.schema.field("embedding").type == halfvec
    assert concepts.schema.field("negative_embedding").type == halfvec
    if encoded:
        assert concepts.column("embedding").null_count == 0
    else:
        assert concepts.column("embedding").null_count == concepts.num_rows
    pathologists = pq.read_table(paths["pathologist"])
    assert pathologists.column("is_synthetic").to_pylist() == [True] * pathologists.num_rows
    assert pathologists.column("is_demo_user").to_pylist().count(True) == 1
