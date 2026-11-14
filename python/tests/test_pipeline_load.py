"""Stage 9: parquet COPY into Postgres, then HNSW and GIN indexes."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from psycopg.types.json import Jsonb

from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.embed import (  # pragma: allowlist secret
    CONCHZ_DIM,
    MockTextEncoder,
    build_text_encoders,
)
from consilium.pipeline.__main__ import main  # pragma: allowlist secret
from consilium.pipeline.export import export_cohort  # pragma: allowlist secret
from consilium.pipeline.load import load_parquet  # pragma: allowlist secret
from consilium.pipeline.project import (  # pragma: allowlist secret
    l2_normalize,
    mean_embedding,
    projected_h5_path,
)
from consilium.pipeline.roster import builtin_roster  # pragma: allowlist secret
from consilium.pipeline.run import run_pipeline  # pragma: allowlist secret
from consilium.pipeline.stage_reports import (  # pragma: allowlist secret
    CaseInput,
    CaseRow,
    Stage7Result,
    build_stage7,
    write_stage7,
)
from consilium.pipeline.thumbs import index_path, pack_path  # pragma: allowlist secret

_REPORT = (
    "Clinical History: weight loss for three months. "
    "Gross Description: a 2 cm firm nodule. "
    "Microscopic Description: infiltrative glands in desmoplastic stroma. "
    "Final Diagnosis: poorly differentiated adenocarcinoma secret-marker. "
    "Comment: synoptic staging was recorded."
)
_PROJECTS = {
    "breast": "TCGA-BRCA",
    "thorax": "TCGA-LUAD",
    "colorectal": "TCGA-COAD",
    "gastrointestinal": "TCGA-STAD",
    "skin": "TCGA-SKCM",
    "hematologic": "TCGA-DLBC",
}
_SPECIALTIES = tuple(_PROJECTS)
_INDEXES = (
    "slide_embedding_hnsw",
    "patch_embedding_hnsw",
    "report_chunk_embedding_hnsw",
    "report_search_tsv_gin",
)
_PIPELINE_TABLES = (
    "pathologist",
    "patient",
    "concept",
    "path_case",
    "slide",
    "report",
    "report_chunk",
    "patch",
)
_APP_TABLES = ("annotation", "consult_thread", "consult_message", "ingestion_job")


def test_reports_then_export_keeps_concept_embeddings(tmp_path: Path) -> None:
    encoders = _encoders()
    result = _build(
        tmp_path,
        n_cases=2,
        held_out=1,
        patches_per_slide=2,
        encoders=encoders,
        export=False,
    )
    concept_path = tmp_path / "export" / "concept.parquet"
    before = {
        row["id"]: row["embedding"] for row in pq.read_table(concept_path).to_pylist()
    }
    assert before
    assert all(vector is not None and len(vector) == CONCHZ_DIM for vector in before.values())
    exported = export_cohort(
        cohort_csv=tmp_path / "cohort" / "cohort.csv",
        data_root=tmp_path,
        text_encoder=encoders,
    )
    assert exported.failed == 0
    assert exported.slides_written == len(result.cases)
    after_rows = pq.read_table(concept_path).to_pylist()
    after = {row["id"]: row for row in after_rows}
    for concept_id, vector in before.items():
        row = after[concept_id]
        assert row["embedding"] is not None
        assert len(row["embedding"]) == CONCHZ_DIM
        assert row["embedding"] == pytest.approx(vector, abs=1e-5)
        if row["negative_prompt"]:
            assert row["negative_embedding"] is not None
            assert len(row["negative_embedding"]) == CONCHZ_DIM
        else:
            assert row["negative_embedding"] is None
    for row in after_rows:
        assert row["embedding"] is not None
        assert len(row["embedding"]) == CONCHZ_DIM
    patches = pq.read_table(tmp_path / "export" / "patch.parquet")
    case_rows = pq.read_table(tmp_path / "export" / "path_case.parquet").to_pylist()
    cases = {row["id"]: row for row in case_rows}
    for row in patches.to_pylist():
        case = cases[row["case_id"]]
        assert row["patient_id"] == case["patient_id"]
        assert row["in_corpus"] is (case["status"] == "signed_out" and not case["is_held_out"])


def test_load_matches_parquet_and_is_searchable(empty_database: str, tmp_path: Path) -> None:
    _build(tmp_path, n_cases=4, held_out=1, patches_per_slide=3)
    export_dir = tmp_path / "export"
    result = load_parquet(export_dir, database_url=empty_database)
    expected = _expected_counts(export_dir)
    assert result.counts == expected
    assert result.indexes_applied == ("0002_indexes.sql",)
    assert result.slides_loaded == expected["slide"]
    _assert_loaded(empty_database, export_dir)
    assert "maintenance_work_mem" in result.summary()
    assert "projected_demo_load_seconds" in result.summary()
    assert "projected_demo_index_seconds" in result.summary()


def test_second_load_is_idempotent_and_keeps_app_rows(
    empty_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _build(tmp_path, n_cases=3, held_out=1, patches_per_slide=4)
    export_dir = tmp_path / "export"
    first = load_parquet(export_dir, database_url=empty_database)
    with connect(empty_database) as conn:
        author, case_id, slide_id = conn.execute(
            """
            select path_case.assigned_to, path_case.id, slide.id
            from path_case
            join slide on slide.case_id = path_case.id
            limit 1
            """
        ).fetchone()
        annotation_id = conn.execute(
            """
            insert into annotation (slide_id, case_id, author_id, kind, geometry, label)
            values (%s, %s, %s, 'point', %s, 'mark')
            returning id
            """,
            (slide_id, case_id, author, Jsonb({"x": 12, "y": 34})),
        ).fetchone()[0]
        thread_id = conn.execute(
            """
            insert into consult_thread (case_id, user_id, title)
            values (%s, %s, 'note')
            returning id
            """,
            (case_id, author),
        ).fetchone()[0]
        job_id = conn.execute(
            """
            insert into ingestion_job (dataset, slide_path, case_id, status)
            values ('TCGA-BRCA', 'already-loaded.svs', %s, 'done')
            returning id
            """,
            (case_id,),
        ).fetchone()[0]
        before_app = _table_counts(conn, _APP_TABLES)
        before_pipeline = _table_counts(conn, _PIPELINE_TABLES)
    monkeypatch.setenv("DATABASE_URL", empty_database)
    monkeypatch.setenv("SEARCH_BACKEND", "pgvector")
    assert main(["load", "--from", str(export_dir)]) == 0
    summary = capsys.readouterr().out
    assert "indexes_applied none" in summary
    with connect(empty_database) as conn:
        assert _table_counts(conn, _PIPELINE_TABLES) == before_pipeline
        assert _table_counts(conn, _APP_TABLES) == before_app
        assert conn.execute("select 1 from annotation where id = %s", (annotation_id,)).fetchone()
        assert conn.execute("select 1 from consult_thread where id = %s", (thread_id,)).fetchone()
        assert conn.execute("select 1 from ingestion_job where id = %s", (job_id,)).fetchone()
        assert conn.execute("select count(*) from patch").fetchone()[0] == first.counts["patch"]
        assert conn.execute(
            "select count(*) from slide where status = 'ready'"
        ).fetchone()[0] == first.counts["slide"]


def test_disjoint_cohort_leaves_the_first_untouched(empty_database: str, tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = _build(first_root, n_cases=2, held_out=1, patches_per_slide=3, start=0)
    second = _build(second_root, n_cases=2, held_out=0, patches_per_slide=5, start=40)
    _remap_patients(second_root / "export", "b")
    load_parquet(first_root / "export", database_url=empty_database)
    first_case = first.cases[0].id
    with connect(empty_database) as conn:
        first_patches = conn.execute(
            "select count(*) from patch where case_id = %s",
            (first_case,),
        ).fetchone()[0]
        first_cases = conn.execute("select count(*) from path_case").fetchone()[0]
    load_parquet(second_root / "export", database_url=empty_database)
    with connect(empty_database) as conn:
        assert conn.execute(
            "select count(*) from patch where case_id = %s",
            (first_case,),
        ).fetchone()[0] == first_patches
        assert conn.execute("select count(*) from path_case").fetchone()[0] == first_cases + len(
            second.cases
        )
        assert conn.execute(
            "select count(*) from patch where case_id = %s",
            (second.cases[0].id,),
        ).fetchone()[0] == 5
        assert conn.execute(
            "select count(*) from slide where id = %s",
            (f"{first_case}-s1",),
        ).fetchone()[0] == 1


def test_replace_fixtures_drops_seed_rows_and_keeps_real_cases(
    empty_database: str,
    tmp_path: Path,
) -> None:
    _build(tmp_path, n_cases=2, held_out=0, patches_per_slide=2, start=7)
    export_dir = tmp_path / "export"
    loaded_case = pq.read_table(export_dir / "path_case.parquet").column("id")[0].as_py()
    _install_fixtures(empty_database, tmp_path / "fixture-files")
    result = load_parquet(export_dir, database_url=empty_database, replace_fixtures=True)
    with connect(empty_database) as conn:
        assert conn.execute(
            "select count(*) from path_case where id = 'breast-FX-B042A'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "select count(*) from patient where id = 'pt-fixture'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "select count(*) from slide where id = 'breast-FX-B042A-s1'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "select count(*) from annotation where case_id = 'breast-FX-B042A'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "select count(*) from consult_thread where case_id = 'breast-FX-B042A'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "select count(*) from ingestion_job where case_id = 'breast-FX-B042A'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "select count(*) from path_case where id = 'thorax-KEEP-0001'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "select count(*) from patient where id = 'pt-keeper'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "select count(*) from consult_thread where case_id = 'thorax-KEEP-0001'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "select count(*) from ingestion_job where case_id = 'thorax-KEEP-0001'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "select count(*) from path_case where id = %s",
            (loaded_case,),
        ).fetchone()[0] == 1
    assert result.counts["path_case"] == 1 + _expected_counts(export_dir)["path_case"]


def test_smoke_scale_load_timings(empty_database: str, tmp_path: Path) -> None:
    patches_per_slide = 500
    slides = 10
    _build(
        tmp_path,
        n_cases=slides,
        held_out=2,
        patches_per_slide=patches_per_slide,
        tier="smoke",
    )
    result = load_parquet(tmp_path / "export", database_url=empty_database)
    assert result.counts["slide"] == slides
    assert result.counts["patch"] == slides * patches_per_slide
    assert result.slides_loaded == slides
    assert result.load_elapsed_seconds > 0
    assert result.index_elapsed_seconds > 0
    assert result.projected_demo_load_seconds == pytest.approx(
        result.load_elapsed_seconds * (200 / slides)
    )
    assert result.projected_demo_index_seconds == pytest.approx(
        result.index_elapsed_seconds * (200 / slides)
    )
    print(result.summary())


def test_run_order_puts_reports_before_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []

    def recorder(name: str):
        def _record(*_args: object, **_kwargs: object) -> SimpleNamespace:
            order.append(name)
            return SimpleNamespace(summary=lambda: f"{name} ok\n", failed=0)

        return _record

    monkeypatch.setattr(
        "consilium.pipeline.run.run_manifest_stage",  # pragma: allowlist secret
        recorder("manifest"),
    )
    monkeypatch.setattr(
        "consilium.pipeline.run.run_download_stage",  # pragma: allowlist secret
        recorder("download"),
    )
    monkeypatch.setattr(
        "consilium.pipeline.run.run_extract_stage",  # pragma: allowlist secret
        recorder("extract"),
    )
    monkeypatch.setattr(
        "consilium.pipeline.run.run_reports_stage",  # pragma: allowlist secret
        recorder("reports"),
    )
    monkeypatch.setattr(
        "consilium.pipeline.run.run_project_stage",  # pragma: allowlist secret
        recorder("project"),
    )
    monkeypatch.setattr(
        "consilium.pipeline.run.run_thumbs_stage",  # pragma: allowlist secret
        recorder("thumbs"),
    )
    monkeypatch.setattr(
        "consilium.pipeline.run.run_export_stage",  # pragma: allowlist secret
        recorder("export"),
    )
    monkeypatch.setattr(
        "consilium.pipeline.run.run_load_stage",  # pragma: allowlist secret
        recorder("load"),
    )
    result = run_pipeline(tier="smoke", data_root=tmp_path, workers=2, seed=0, gpu=0)
    assert order == [
        "manifest",
        "download",
        "extract",
        "reports",
        "project",
        "thumbs",
        "export",
        "load",
    ]
    text = result.summary()
    assert text.index("stage reports") < text.index("stage export")
    assert text.index("stage export") < text.index("stage load")


def test_load_requires_the_parquet_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing parquet"):
        load_parquet(tmp_path)


def _encoders():
    return build_text_encoders(backend=MockTextEncoder())


def _build(
    root: Path,
    *,
    n_cases: int,
    held_out: int,
    patches_per_slide: int,
    start: int = 0,
    tier: str = "smoke",
    encoders=None,
    export: bool = True,
) -> Stage7Result:
    encoder = encoders if encoders is not None else _encoders()
    cases = [
        _input(index, held_out=index < start + held_out, tier=tier)
        for index in range(start, start + n_cases)
    ]
    result = build_stage7(cases, builtin_roster(), encoder, encode_concepts=True)
    export_dir = root / "export"
    write_stage7(result, export_dir)
    _write_cohort(root / "cohort" / "cohort.csv", result.cases)
    _write_slide_inputs(root, result.cases, patches_per_slide)
    if not export:
        return result
    exported = export_cohort(
        cohort_csv=root / "cohort" / "cohort.csv",
        data_root=root,
        text_encoder=encoder,
    )
    assert exported.failed == 0, exported.summary()
    assert exported.slides_written == len(result.cases)
    return result


def _input(index: int, *, held_out: bool, tier: str) -> CaseInput:
    specialty = _SPECIALTIES[index % len(_SPECIALTIES)]
    barcode = f"TCGA-AA-{index:04d}"
    return CaseInput(
        case_id=f"{specialty}-{barcode}",
        project_id=_PROJECTS[specialty],
        specialty=specialty,
        tier=tier,
        held_out=held_out,
        submitter_id=barcode,
        patient_sex="F",
        patient_age=50 + (index % 20),
        primary_diagnosis="Adenocarcinoma, NOS",
        morphology="8140/3",
        icd10="C50.9",
        report_text=_REPORT,
        sample_code="01Z",
    )


def _write_cohort(path: Path, cases: tuple[CaseRow, ...] | list[CaseRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
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
            writer.writerow(
                {
                    "case_id": case.id,
                    "slide_id": f"{case.id}-s1",
                    "gdc_file_id": case.id,
                    "file_name": f"{case.source_case_id}-01Z-00-DX1.svs",
                    "file_size": "128",
                    "project_id": case.source_dataset,
                    "specialty": case.specialty,
                    "tier": case.cohort_tier,
                    "held_out": "true" if case.is_held_out else "false",
                }
            )


def _write_slide_inputs(
    root: Path,
    cases: tuple[CaseRow, ...] | list[CaseRow],
    patches: int,
) -> None:
    headers: dict[str, list[object]] = {
        "slide_id": [],
        "case_id": [],
        "width_px": [],
        "height_px": [],
        "magnification": [],
        "mpp": [],
        "patch_size_level0": [],
        "error": [],
    }
    for case_index, case in enumerate(cases):
        slide_id = f"{case.id}-s1"
        vectors = _unit_rows(patches, case_index + 3)
        coords = np.column_stack(
            [np.arange(patches, dtype=np.int64) * 512, np.zeros(patches, dtype=np.int64)]
        )
        path = projected_h5_path(root / "trident", slide_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(path, "w") as handle:
            handle.create_dataset("features", data=vectors)
            stored = handle.create_dataset("coords", data=coords)
            stored.attrs["patch_size_level0"] = 512
            handle.create_dataset("slide_embedding", data=mean_embedding(vectors))
        destination = index_path(root, slide_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "slide_id": slide_id,
            "patch_size_level0": 512,
            "thumb_side": 224,
            "jpeg_quality": 80,
            "patches": [
                {
                    "x": int(coords[row, 0]),
                    "y": int(coords[row, 1]),
                    "thumb_offset": 0,
                    "thumb_length": 4,
                }
                for row in range(patches)
            ],
        }
        destination.write_text(json.dumps(payload), encoding="utf-8")
        pack_path(root, slide_id).write_bytes(b"pack")
        headers["slide_id"].append(slide_id)
        headers["case_id"].append(case.id)
        headers["width_px"].append(1_000_000)
        headers["height_px"].append(1_000_000)
        headers["magnification"].append(20.0)
        headers["mpp"].append(0.5)
        headers["patch_size_level0"].append(512)
        headers["error"].append(None)
    header_path = root / "trident" / "slide_headers.parquet"
    header_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(headers), header_path)


def _unit_rows(count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    raw = rng.normal(size=(count, CONCHZ_DIM)).astype(np.float32)
    return l2_normalize(raw)


def _remap_patients(export_dir: Path, suffix: str) -> None:
    patients = pq.read_table(export_dir / "patient.parquet").to_pylist()
    mapping = {row["id"]: f"{row['id']}-{suffix}" for row in patients}
    labels = {row["id"]: f"{row['display_label']}-{suffix}" for row in patients}

    def rewrite(path: Path, column: str, values: list[object]) -> None:
        table = pq.read_table(path)
        field = table.schema.field(column)
        index = table.schema.get_field_index(column)
        updated = table.set_column(index, field, pa.array(values, type=field.type))
        pq.write_table(updated, path)

    rewrite(export_dir / "patient.parquet", "id", [mapping[row["id"]] for row in patients])
    rewrite(
        export_dir / "patient.parquet",
        "display_label",
        [labels[row["id"]] for row in patients],
    )
    for name in ("path_case", "patch", "report_chunk"):
        table = pq.read_table(export_dir / f"{name}.parquet")
        values = [mapping[value] for value in table.column("patient_id").to_pylist()]
        rewrite(export_dir / f"{name}.parquet", "patient_id", values)


def _expected_counts(export_dir: Path) -> dict[str, int]:
    counts = {}
    for table in _PIPELINE_TABLES:
        counts[table] = pq.ParquetFile(export_dir / f"{table}.parquet").metadata.num_rows
    return counts


def _assert_loaded(url: str, export_dir: Path) -> None:
    with connect(url) as conn:
        assert _table_counts(conn, _PIPELINE_TABLES) == _expected_counts(export_dir)
        ready = conn.execute(
            """
            select count(*) from slide
            where status = 'ready'
              and embedding is not null
              and thumb_pack_key is not null
            """
        ).fetchone()[0]
        assert ready == _expected_counts(export_dir)["slide"]
        names = {
            row[0]
            for row in conn.execute(
                "select indexname from pg_indexes where schemaname = 'public'"
            ).fetchall()
        }
        assert set(_INDEXES) <= names
        null_tsv = conn.execute(
            "select count(*) from report where search_tsv is null"
        ).fetchone()[0]
        assert null_tsv == 0
        matched = conn.execute(
            """
            select count(*) from report
            where search_tsv @@ plainto_tsquery('english', 'nodule')
            """
        ).fetchone()[0]
        assert matched == _expected_counts(export_dir)["report"]
        hits = conn.execute(
            """
            select count(*) from (
                select id from patch
                where in_corpus
                order by embedding <=> (select embedding from patch where in_corpus limit 1)
                limit 5
            ) hits
            """
        ).fetchone()[0]
        assert hits > 0
        patch_flags = conn.execute(
            """
            select count(*) filter (where in_corpus), count(*) filter (where not in_corpus)
            from patch
            """
        ).fetchone()
        chunk_flags = conn.execute(
            """
            select count(*) filter (where in_corpus), count(*) filter (where not in_corpus)
            from report_chunk
            """
        ).fetchone()
    patch_true, patch_false = _flag_counts(export_dir / "patch.parquet")
    chunk_true, chunk_false = _flag_counts(export_dir / "report_chunk.parquet")
    assert patch_flags == (patch_true, patch_false)
    assert chunk_flags == (chunk_true, chunk_false)
    assert patch_true > 0 and patch_false > 0
    assert chunk_true > 0 and chunk_false > 0


def _flag_counts(path: Path) -> tuple[int, int]:
    values = pq.read_table(path, columns=["in_corpus"]).column("in_corpus").to_pylist()
    true = sum(bool(value) for value in values)
    return true, len(values) - true


def _table_counts(conn: object, tables: tuple[str, ...]) -> dict[str, int]:
    counts = {}
    for table in tables:
        row = conn.execute(f"select count(*) from {table}").fetchone()  # type: ignore[attr-defined]
        counts[table] = int(row[0])
    return counts


def _install_fixtures(url: str, storage: Path) -> None:
    """Seed fixture rows the way ``db.seed`` does, when that module exists.

    SKO-259 is a separate branch. Until it is on this checkout the same shape is
    inserted here: ``source_dataset = 'fixture'`` and an ``FX-`` case id, plus one
    real case that must survive ``--replace-fixtures``.
    """
    try:
        from consilium.db.seed import seed  # pragma: allowlist secret
    except ImportError:
        seed = None
    if seed is not None:
        from consilium.db.migrate import migrate  # pragma: allowlist secret

        migrate(url, include_indexes=False)
        seed(url, storage_root=storage)
        _insert_keeper(url)
        return
    from consilium.db.migrate import migrate  # pragma: allowlist secret

    migrate(url, include_indexes=False)
    with connect(url) as conn:
        conn.execute(
            """
            insert into pathologist (
                id, name, role_title, primary_specialty, secondary_specialties,
                is_demo_user, is_synthetic
            ) values (
                'path-fixture', 'Dr Fixture', 'Consultant Histopathologist', 'breast',
                '{}', false, true
            )
            """
        )
        conn.execute(
            """
            insert into patient (id, display_label, sex, birth_year, is_synthetic_linkage)
            values ('pt-fixture', 'PT-FIXTURE', 'F', 1970, true)
            """
        )
        conn.execute(
            """
            insert into path_case (
                id, patient_id, specimen_label, source_dataset, source_case_id, specialty,
                patient_age, patient_sex, status, assigned_to, accessioned_at,
                is_held_out, cohort_tier
            ) values (
                'breast-FX-B042A', 'pt-fixture', 'Prior core biopsy', 'fixture', 'FX-B042A',
                'breast', 60, 'F', 'signed_out', 'path-fixture', now(), false, 'smoke'
            )
            """
        )
        conn.execute(
            """
            insert into slide (
                id, case_id, ordinal, stain, magnification, mpp, width, height,
                patch_size, patch_count, storage_key, source_path, status
            ) values (
                'breast-FX-B042A-s1', 'breast-FX-B042A', 1, 'HE', 20, 0.5, 2048, 1536,
                512, 0, 'slides/breast-FX-B042A-s1.svs', 'fixture/slide.svs', 'pending'
            )
            """
        )
        conn.execute(
            """
            insert into report (id, case_id, author_id, status, body, signed_at)
            values (
                'breast-FX-B042A-r1', 'breast-FX-B042A', 'path-fixture', 'signed',
                'Synthetic fixture text for the research prototype.', now()
            )
            """
        )
        conn.execute(
            """
            insert into annotation (slide_id, case_id, author_id, kind, geometry, label)
            values (
                'breast-FX-B042A-s1', 'breast-FX-B042A', 'path-fixture', 'point',
                %s, 'fixture mark'
            )
            """,
            (Jsonb({"x": 1, "y": 2}),),
        )
        conn.execute(
            """
            insert into consult_thread (case_id, user_id, title)
            values ('breast-FX-B042A', 'path-fixture', 'fixture consult')
            """
        )
        conn.execute(
            """
            insert into ingestion_job (dataset, slide_path, case_id, status)
            values ('fixture', 'fixture.svs', 'breast-FX-B042A', 'done')
            """
        )
        conn.commit()
    _insert_keeper(url)


def _insert_keeper(url: str) -> None:
    with connect(url) as conn:
        conn.execute(
            """
            insert into pathologist (
                id, name, role_title, primary_specialty, secondary_specialties,
                is_demo_user, is_synthetic
            ) values (
                'path-keeper', 'Dr Keeper', 'Consultant Histopathologist', 'thorax',
                '{}', false, true
            )
            on conflict (id) do nothing
            """
        )
        conn.execute(
            """
            insert into patient (id, display_label, sex, birth_year, is_synthetic_linkage)
            values ('pt-keeper', 'PT-KEEPER', 'M', 1960, false)
            on conflict (id) do nothing
            """
        )
        conn.execute(
            """
            insert into path_case (
                id, patient_id, specimen_label, source_dataset, source_case_id, specialty,
                patient_age, patient_sex, status, assigned_to, accessioned_at,
                is_held_out, cohort_tier
            ) values (
                'thorax-KEEP-0001', 'pt-keeper', 'Lung resection', 'TCGA-LUAD',
                'TCGA-KEEP-0001', 'thorax', 70, 'M', 'signed_out', 'path-keeper',
                now(), false, 'demo'
            )
            on conflict (id) do nothing
            """
        )
        conn.execute(
            """
            insert into consult_thread (case_id, user_id, title)
            values ('thorax-KEEP-0001', 'path-keeper', 'keep this consult')
            """
        )
        conn.execute(
            """
            insert into ingestion_job (dataset, slide_path, case_id, status)
            values ('TCGA-LUAD', 'keeper.svs', 'thorax-KEEP-0001', 'done')
            """
        )
        conn.commit()
