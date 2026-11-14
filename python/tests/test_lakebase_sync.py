"""Lakebase loader and subset load against local Postgres."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.pipeline.lakebase_sync import LakebaseLoader  # pragma: allowlist secret
from consilium.pipeline.load import (  # pragma: allowlist secret
    PARQUET_FILES,
    PIPELINE_TABLES,
    load_parquet,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def test_loader_is_idempotent_and_marks_slides_ready(empty_database: str, tmp_path: Path) -> None:
    export = tmp_path / "export"
    _write_export(export)
    migrate(empty_database)
    tables = _read(export)
    first = _load(empty_database, tables)
    second = _load(empty_database, tables)
    assert first > 0
    assert second > 0
    conn = connect(empty_database)
    try:
        assert _count(conn, "patch") == 3
        assert _count(conn, "path_case") == 3
        ready = conn.execute("select count(*) from slide where status = 'ready'").fetchone()
        assert ready is not None and int(ready[0]) == 3
        indexes = conn.execute(
            "select indexdef from pg_indexes where schemaname = 'public'"
        ).fetchall()
    finally:
        conn.close()
    defs = "\n".join(str(row[0]) for row in indexes)
    assert "lakebase_ann" not in defs
    assert "lakebase_bm25" not in defs


def test_load_parquet_subset_logs_database_size(empty_database: str, tmp_path: Path) -> None:
    export = tmp_path / "export"
    _write_export(export)
    loaded = load_parquet(export, database_url=empty_database, max_cases=1)
    assert loaded.subset_cases == 2
    assert loaded.estimated_bytes is not None and loaded.estimated_bytes > 0
    assert loaded.pg_database_size > 0
    assert loaded.counts["pathologist"] == 2
    assert loaded.counts["concept"] == 1
    assert loaded.counts["patient"] == 1
    assert loaded.counts["path_case"] == 2
    assert loaded.counts["patch"] == 2
    assert loaded.patch_in_corpus_true == 1
    assert loaded.patch_in_corpus_false == 1
    assert "0002_indexes.sql" in loaded.indexes_applied
    summary = loaded.summary()
    assert f"pg_database_size {loaded.pg_database_size}" in summary
    assert "subset_cases 2" in summary

    again = load_parquet(export, database_url=empty_database, max_cases=1)
    assert again.counts == loaded.counts
    assert again.pg_database_size > 0
    conn = connect(empty_database)
    try:
        hnsw = conn.execute(
            """
            select indexdef from pg_indexes
            where schemaname = 'public' and indexdef ilike '%using hnsw%'
            """
        ).fetchall()
    finally:
        conn.close()
    assert hnsw
    assert all("lakebase" not in str(row[0]) for row in hnsw)


def _load(url: str, tables: dict[str, list[dict[str, object]]]) -> int:
    conn = connect(url)
    try:
        size = LakebaseLoader(conn).load(tables)
        conn.commit()
        return size
    finally:
        conn.close()


def _read(export: Path) -> dict[str, list[dict[str, object]]]:
    return {
        name: pq.read_table(export / PARQUET_FILES[name]).to_pylist() for name in PIPELINE_TABLES
    }


def _count(conn: object, table: str) -> int:
    row = conn.execute(f"select count(*) from {table}").fetchone()  # type: ignore[attr-defined]
    return int(row[0]) if row else 0


def _write_export(directory: Path) -> None:
    directory.mkdir(parents=True)
    vector = _unit(768)
    report_vector = _unit(384)
    pathologists = [
        _pathologist("path-a", demo=True),
        _pathologist("path-b", demo=False),
    ]
    patients = [_patient("pt-1", "F"), _patient("pt-2", "M"), _patient("pt-unused", "F")]
    cases = [
        _case("breast-open", "pt-1", "breast", "open", True, 5, "path-a"),
        _case("breast-prior", "pt-1", "breast", "signed_out", False, 1, "path-a"),
        _case("thorax-1", "pt-2", "thorax", "signed_out", False, 3, "path-b"),
    ]
    slides = [_slide(row) for row in cases]
    reports = [_report(row) for row in cases]
    chunks = [_chunk(row, report_vector) for row in cases]
    patches = [_patch(row, vector) for row in cases]
    concepts = [
        {
            "id": "necrosis",
            "label": "Necrosis",
            "prompt": "necrosis",
            "negative_prompt": None,
            "specialty": None,
            "ordinal": 1,
            "embedding": vector,
            "negative_embedding": None,
            "created_at": _WHEN,
        }
    ]
    rows = {
        "pathologist": pathologists,
        "patient": patients,
        "concept": concepts,
        "path_case": cases,
        "slide": slides,
        "report": reports,
        "report_chunk": chunks,
        "patch": patches,
    }
    for name in PIPELINE_TABLES:
        pq.write_table(pa.Table.from_pylist(rows[name]), directory / PARQUET_FILES[name])


def _pathologist(path_id: str, *, demo: bool) -> dict[str, object]:
    return {
        "id": path_id,
        "name": path_id,
        "role_title": "Consultant",
        "primary_specialty": "breast" if demo else "thorax",
        "secondary_specialties": [],
        "is_demo_user": demo,
        "is_synthetic": True,
        "created_at": _WHEN,
    }


def _patient(patient_id: str, sex: str) -> dict[str, object]:
    return {
        "id": patient_id,
        "display_label": patient_id,
        "sex": sex,
        "birth_year": 1970,
        "is_synthetic_linkage": True,
        "created_at": _WHEN,
    }


def _case(
    case_id: str,
    patient_id: str,
    specialty: str,
    status: str,
    held: bool,
    hour: int,
    assigned: str,
) -> dict[str, object]:
    return {
        "id": case_id,
        "patient_id": patient_id,
        "specimen_label": case_id,
        "source_dataset": "TCGA",
        "source_case_id": case_id,
        "specialty": specialty,
        "patient_age": 60,
        "patient_sex": "F",
        "primary_diagnosis": None,
        "morphology": None,
        "icd10": None,
        "status": status,
        "assigned_to": assigned,
        "accessioned_at": datetime(2026, 1, 1, hour, tzinfo=UTC),
        "is_held_out": held,
        "cohort_tier": "demo",
        "created_at": _WHEN,
    }


def _slide(case: dict[str, object]) -> dict[str, object]:
    return {
        "id": f"slide-{case['id']}",
        "case_id": case["id"],
        "ordinal": 1,
        "stain": "H&E",
        "magnification": 20.0,
        "mpp": 0.5,
        "width": 1000,
        "height": 1000,
        "patch_size": 512,
        "patch_count": 1,
        "storage_key": f"slides/slide-{case['id']}.svs",
        "thumb_pack_key": f"thumbs/slide-{case['id']}.pack",
        "source_path": f"slides/slide-{case['id']}.svs",
        "embedding": _unit(768),
        "status": "ready",
        "created_at": _WHEN,
    }


def _report(case: dict[str, object]) -> dict[str, object]:
    signed = case["status"] == "signed_out"
    return {
        "id": f"report-{case['id']}",
        "case_id": case["id"],
        "author_id": case["assigned_to"],
        "status": "signed" if signed else "withheld",
        "body": "Research text for retrieval. Not a diagnosis.",
        "clinical_history": None,
        "gross_description": None,
        "microscopic_description": None,
        "conclusion": None,
        "additional_info": None,
        "icd10": None,
        "signed_at": _WHEN if signed else None,
        "created_at": _WHEN,
    }


def _chunk(case: dict[str, object], embedding: list[float]) -> dict[str, object]:
    signed = case["status"] == "signed_out" and not case["is_held_out"]
    return {
        "report_id": f"report-{case['id']}",
        "case_id": case["id"],
        "patient_id": case["patient_id"],
        "specialty": case["specialty"],
        "section": "body",
        "ordinal": 1,
        "text": "Research text for retrieval.",
        "embedding": embedding,
        "in_corpus": signed,
        "created_at": _WHEN,
    }


def _patch(case: dict[str, object], embedding: list[float]) -> dict[str, object]:
    signed = case["status"] == "signed_out" and not case["is_held_out"]
    return {
        "slide_id": f"slide-{case['id']}",
        "case_id": case["id"],
        "patient_id": case["patient_id"],
        "specialty": case["specialty"],
        "x": 0,
        "y": 0,
        "size": 512,
        "embedding": embedding,
        "in_corpus": signed,
        "thumb_offset": 0,
        "thumb_length": 12,
        "created_at": _WHEN,
    }


def _unit(dim: int) -> list[float]:
    values = [0.0] * dim
    values[0] = 1.0
    return values
