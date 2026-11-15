"""Silver rule counts, and the notebook embeds the same selector and loader."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from consilium.pipeline.medallion import (  # pragma: allowlist secret
    RULES,
    format_violations,
    violation_counts,
)

_ROOT = Path(__file__).resolve().parents[1]


def test_clean_rows_have_no_violations() -> None:
    counts = violation_counts(_tables(bad=False))
    assert all(value == 0 for rules in counts.values() for value in rules.values())
    text = format_violations(counts)
    assert "violation_total 0" in text
    for rule in RULES:
        assert rule in text


def test_each_rule_is_counted() -> None:
    counts = violation_counts(_tables(bad=True))
    assert counts["pathologist"]["non_empty_id"] == 1
    assert counts["pathologist"]["duplicate_natural_key"] == 1
    assert counts["path_case"]["valid_specialty"] == 1
    assert counts["patch"]["unit_norm"] == 1
    assert counts["patch"]["in_corpus"] == 1
    assert counts["slide"]["positive_dimension"] == 1
    assert "violation_total 0" not in format_violations(counts)


def test_notebook_embeds_the_selector_and_loader() -> None:
    pipeline = _ROOT / "src" / "consilium" / "pipeline"  # pragma: allowlist secret
    notebook = (_ROOT / "databricks" / "medallion_lakebase.py").read_text(encoding="utf-8")
    subset = (pipeline / "subset.py").read_text(encoding="utf-8")
    loader = (pipeline / "lakebase_sync.py").read_text(encoding="utf-8")
    assert _block(subset, "# BEGIN SELECT", "# END SELECT") in notebook
    assert _block(loader, "# BEGIN LOADER", "# END LOADER") in notebook
    assert notebook.startswith("# Databricks notebook source")
    assert "%pip" not in notebook
    for token in (
        "bronze_",
        "silver_",
        "gold_",
        "_ingested_at",
        "_source_file",
        "/Volumes/",
        "dbutils.widgets",
        "volume_name",
        "raw",
        "sslmode=require",
        "pg_database_size",
        "ArrayType(FloatType())",
        *RULES,
    ):
        assert token in notebook
    for line in notebook.splitlines():
        lowered = line.lower()
        if "lakebase_ann" in lowered or "lakebase_bm25" in lowered:
            assert "does not create" in lowered
    cells = notebook.split("# COMMAND ----------")
    assert len(cells) >= 6
    for cell in cells:
        body = "\n".join(line for line in cell.splitlines() if not line.startswith("# MAGIC"))
        compile(body, "medallion_lakebase.py", "exec")


def _block(text: str, begin: str, end: str) -> str:
    start = text.index(begin)
    stop = text.index(end)
    return text[start:stop]


def _tables(*, bad: bool) -> dict[str, pa.Table]:
    vector = [0.0] * 768
    vector[0] = 1.0
    report = [0.0] * 384
    report[0] = 1.0
    pathologist = [
        {"id": "path-a", "primary_specialty": "breast", "secondary_specialties": []},
    ]
    patient = [{"id": "pt-1"}]
    concept = [
        {
            "id": "necrosis",
            "specialty": None,
            "embedding": vector,
            "negative_prompt": None,
        }
    ]
    path_case = [
        {
            "id": "case-1",
            "patient_id": "pt-1",
            "assigned_to": "path-a",
            "specialty": "breast",
            "status": "signed_out",
            "is_held_out": False,
        }
    ]
    slide = [
        {
            "id": "slide-1",
            "case_id": "case-1",
            "status": "ready",
            "embedding": vector,
            "width": 10,
            "height": 10,
            "patch_size": 512,
            "magnification": 20,
            "mpp": 0.5,
            "ordinal": 1,
        }
    ]
    report_row = [{"id": "report-1", "case_id": "case-1", "author_id": "path-a"}]
    chunk = [
        {
            "report_id": "report-1",
            "ordinal": 1,
            "case_id": "case-1",
            "patient_id": "pt-1",
            "specialty": "breast",
            "embedding": report,
            "in_corpus": True,
        }
    ]
    patch = [
        {
            "slide_id": "slide-1",
            "x": 0,
            "y": 0,
            "case_id": "case-1",
            "patient_id": "pt-1",
            "specialty": "breast",
            "embedding": vector,
            "in_corpus": True,
            "size": 512,
            "thumb_length": 8,
        }
    ]
    if bad:
        pathologist.append(
            {"id": "", "primary_specialty": "breast", "secondary_specialties": []}
        )
        pathologist.append(dict(pathologist[0]))
        path_case.append(
            {
                "id": "case-2",
                "patient_id": "pt-1",
                "assigned_to": "path-a",
                "specialty": "lung",
                "status": "open",
                "is_held_out": True,
            }
        )
        slide[0]["width"] = 0
        patch.append(dict(patch[0]))
        patch[0]["embedding"] = [1.0, 0.0]
        patch.append(
            {
                "slide_id": "slide-1",
                "x": 1,
                "y": 0,
                "case_id": "missing",
                "patient_id": "pt-1",
                "specialty": "breast",
                "embedding": vector,
                "in_corpus": True,
                "size": 512,
                "thumb_length": 8,
            }
        )
    return {
        "pathologist": pa.Table.from_pylist(pathologist),
        "patient": pa.Table.from_pylist(patient),
        "concept": pa.Table.from_pylist(concept),
        "path_case": pa.Table.from_pylist(path_case),
        "slide": pa.Table.from_pylist(slide),
        "report": pa.Table.from_pylist(report_row),
        "report_chunk": pa.Table.from_pylist(chunk),
        "patch": pa.Table.from_pylist(patch),
    }
