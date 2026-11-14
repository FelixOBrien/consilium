"""Fixture seed: model-doc rules, OpenSlide slides, thumbnail packs, idempotency."""

from __future__ import annotations

import hashlib
import io
import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import openslide
import pytest
from PIL import Image

from consilium.api.store import DEMO_USER_ID as STORE_DEMO_USER_ID  # pragma: allowlist secret
from consilium.cli import main  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import (  # pragma: allowlist secret
    STORED_TABLES,
    chunk_report,
    compose_body,
    seed,
    split_span,
)
from consilium.seed_data import (  # pragma: allowlist secret
    CASES,
    DEMO_USER_ID,
    PATIENTS,
    report_sections,
    validate_seed_data,
)


def test_shared_roster_matches_the_api_demo_user() -> None:
    validate_seed_data()
    assert DEMO_USER_ID == STORE_DEMO_USER_ID == "path-okafor"


def test_fixture_reports_are_invented_and_partitioned() -> None:
    for case in CASES:
        sections = report_sections(case)
        body = compose_body(sections)
        chunks = chunk_report(body)
        words = [word for _section, text in chunks for word in text.split()]
        assert words == body.split()
        assert [section for section, _text in chunks] == [
            "clinical_history",
            "gross_description",
            "microscopic_description",
            "conclusion",
            "additional_info",
        ]
        history = sections["clinical_history"]
        assert history in body
        assert case.primary_diagnosis not in history
        assert case.morphology not in history
        assert "Gross Description" not in history
        assert "Conclusion" not in history
        assert "TCGA" not in body


def test_long_section_overlaps_one_sentence() -> None:
    def sentence(index: int) -> str:
        return " ".join(f"s{index}w{word}" for word in range(40)) + "."

    text = " ".join(sentence(index) for index in range(5))
    parts = split_span(text, word_limit=80)
    assert len(parts) == 4
    assert sentence(1) in parts[0]
    assert parts[1].startswith(sentence(1))
    assert parts[-1].endswith(sentence(4))


@pytest.fixture
def seeded(empty_database: str, tmp_path: Path) -> tuple[str, Path]:
    migrate(empty_database)
    counts = seed(empty_database, tmp_path)
    assert set(counts) == set(STORED_TABLES)
    assert all(count > 0 for count in counts.values())
    return empty_database, tmp_path


def test_every_table_has_rows(seeded: tuple[str, Path]) -> None:
    url, _root = seeded
    with connect(url) as conn:
        for table in STORED_TABLES:
            count = conn.execute(f"select count(*) from {table}").fetchone()
            assert count is not None
            assert count[0] > 0


def test_model_rules(seeded: tuple[str, Path]) -> None:
    url, root = seeded
    with connect(url) as conn:
        demo = conn.execute(
            "select count(*) from pathologist where is_demo_user"
        ).fetchone()
        assert demo is not None and demo[0] == 1
        demo_id = conn.execute(
            "select id from pathologist where is_demo_user"
        ).fetchone()
        assert demo_id is not None and demo_id[0] == DEMO_USER_ID
        synthetic = conn.execute(
            "select count(*) from pathologist where not is_synthetic"
        ).fetchone()
        assert synthetic is not None and synthetic[0] == 0
        per_specialty = conn.execute(
            """
            select primary_specialty, count(*)
            from pathologist
            group by primary_specialty
            order by primary_specialty
            """
        ).fetchall()
        assert [count for _specialty, count in per_specialty] == [2, 2, 2, 2, 2, 2]

        assert _zero(
            conn,
            """
            select count(*) from path_case c
            join report r on r.case_id = c.id
            where (c.status = 'open') <> c.is_held_out
               or (c.status = 'signed_out' and (
                    r.status <> 'signed' or r.author_id <> c.assigned_to or r.signed_at is null
               ))
               or (c.status = 'open' and (
                    r.status <> 'withheld' or r.signed_at is not null
               ))
            """,
        )
        open_cases = conn.execute(
            """
            select count(*) from path_case
            where status = 'open' and assigned_to = %s
            """,
            (DEMO_USER_ID,),
        ).fetchone()
        assert open_cases is not None and open_cases[0] >= 3
        open_assignees = conn.execute(
            "select count(distinct assigned_to) from path_case where status = 'open'"
        ).fetchone()
        assert open_assignees is not None and open_assignees[0] >= 2
        assert _zero(
            conn,
            """
            select count(*) from path_case c
            join pathologist p on p.id = c.assigned_to
            where c.status = 'open'
              and c.specialty <> p.primary_specialty
              and not (c.specialty = any(p.secondary_specialties))
            """,
        )
        longitudinal = conn.execute(
            """
            select count(*) from patient p
            where p.is_synthetic_linkage
              and (select count(*) from path_case c where c.patient_id = p.id) >= 2
            """
        ).fetchone()
        assert longitudinal is not None and longitudinal[0] >= 3
        with_prior = conn.execute(
            """
            select count(*) from patient p
            where exists (
                select 1 from path_case c
                where c.patient_id = p.id and c.status = 'open'
            )
            and exists (
                select 1 from path_case c
                where c.patient_id = p.id and c.status = 'signed_out'
            )
            """
        ).fetchone()
        assert with_prior is not None and with_prior[0] >= 1
        _assert_patient_timeline(conn)

        assert _zero(
            conn,
            """
            select count(*) from patch p
            join path_case c on c.id = p.case_id
            where p.in_corpus <> (c.status = 'signed_out' and not c.is_held_out)
            """,
        )
        assert _zero(
            conn,
            """
            select count(*) from report_chunk k
            join report r on r.id = k.report_id
            join path_case c on c.id = k.case_id
            where k.in_corpus <> (r.status = 'signed' and not c.is_held_out)
            """,
        )
        assert _zero(
            conn,
            """
            select count(*) from patch p
            join slide s on s.id = p.slide_id
            join path_case c on c.id = s.case_id
            where p.case_id <> c.id
               or p.patient_id <> c.patient_id
               or p.specialty <> c.specialty
               or p.size <> s.patch_size
               or p.x % p.size <> 0
               or p.y % p.size <> 0
               or p.x + p.size > s.width
               or p.y + p.size > s.height
            """,
        )
        reports = conn.execute(
            """
            select r.id, r.body, r.clinical_history, r.gross_description,
                   r.microscopic_description, r.conclusion, r.additional_info,
                   r.status, c.primary_diagnosis, c.morphology
            from report r
            join path_case c on c.id = r.case_id
            order by r.id
            """
        ).fetchall()
        assert len(reports) == len(CASES)
        for row in reports:
            body = row[1]
            history = row[2]
            assert history in body
            assert row[3] in body and row[4] in body and row[5] in body and row[6] in body
            assert "Gross Description" not in history
            assert row[8] not in history
            assert row[9] not in history
            chunks = conn.execute(
                """
                select section, ordinal, text
                from report_chunk
                where report_id = %s
                order by ordinal
                """,
                (row[0],),
            ).fetchall()
            assert [ordinal for _section, ordinal, _text in chunks] == list(range(len(chunks)))
            words = [word for _section, _ordinal, text in chunks for word in text.split()]
            assert words == body.split()
            for _section, _ordinal, text in chunks:
                assert text in body

        _assert_unit_vectors(conn, "select embedding from patch", 768)
        _assert_unit_vectors(conn, "select embedding from slide where status = 'ready'", 768)
        _assert_unit_vectors(conn, "select embedding from concept", 768)
        _assert_unit_vectors(
            conn,
            "select negative_embedding from concept where negative_prompt is not null",
            768,
        )
        _assert_unit_vectors(conn, "select embedding from report_chunk", 384)
        assert _zero(conn, "select count(*) from concept where embedding is null")
        assert _zero(
            conn,
            """
            select count(*) from concept
            where (negative_prompt is null) <> (negative_embedding is null)
            """,
        )
        assert _zero(
            conn,
            """
            select count(*) from slide
            where status = 'ready' and (embedding is null or thumb_pack_key is null)
            """,
        )
        distinct_files = conn.execute("select count(distinct storage_key) from slide").fetchone()
        slide_count = conn.execute("select count(*) from slide").fetchone()
        assert distinct_files is not None and distinct_files[0] == 2
        assert slide_count is not None and slide_count[0] == len(CASES)

        _assert_annotations(conn)
        _assert_consult(conn)
        _assert_jobs(conn)
        _assert_thumbnails(conn, root)
        _assert_openslide(conn, root)


def test_seed_twice_is_idempotent(seeded: tuple[str, Path]) -> None:
    url, root = seeded
    before_counts, before_digest, before_files = _fingerprint(url, root)
    again = seed(url, root)
    after_counts, after_digest, after_files = _fingerprint(url, root)
    assert again == before_counts == after_counts
    assert before_digest == after_digest
    assert before_files == after_files


def test_cli_db_seed(
    empty_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", empty_database)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("SEARCH_BACKEND", "pgvector")
    assert main(["db", "migrate"]) == 0
    capsys.readouterr()
    assert main(["db", "seed"]) == 0
    output = capsys.readouterr().out
    assert "pathologist 12" in output
    assert "patient 8" in output
    assert main(["db", "seed"]) == 0
    assert "pathologist 12" in capsys.readouterr().out


def test_module_seed(empty_database: str, tmp_path: Path) -> None:
    migrate(empty_database)
    env = os.environ.copy()
    env["DATABASE_URL"] = empty_database
    env["STORAGE_ROOT"] = str(tmp_path)
    env["SEARCH_BACKEND"] = "pgvector"
    result = subprocess.run(
        [sys.executable, "-m", "consilium.db", "seed"],  # pragma: allowlist secret
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "concept 12" in result.stdout
    assert "ingestion_job 3" in result.stdout


def _zero(conn: object, query: str) -> bool:
    row = conn.execute(query).fetchone()  # type: ignore[attr-defined]
    assert row is not None
    assert row[0] == 0
    return True


def _assert_patient_timeline(conn: object) -> None:
    rows = conn.execute(  # type: ignore[attr-defined]
        """
        select p.id, p.sex, p.birth_year, p.is_synthetic_linkage,
               c.patient_sex, c.patient_age, c.accessioned_at, c.status
        from patient p
        join path_case c on c.patient_id = p.id
        order by p.id, c.accessioned_at
        """
    ).fetchall()
    grouped: dict[str, list[tuple[object, ...]]] = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row)
    assert len(grouped) == len(PATIENTS)
    multi = 0
    for group in grouped.values():
        if len(group) >= 2:
            multi += 1
            assert group[0][3] is True
        else:
            assert group[0][3] is False
        ages = [row[5] for row in group]
        assert ages == sorted(ages)
        earliest = group[0]
        accessioned = earliest[6]
        assert isinstance(accessioned, datetime)
        assert earliest[2] == accessioned.year - earliest[5]
        for row in group:
            assert row[1] == row[4]
    assert multi >= 3


def _assert_unit_vectors(conn: object, query: str, dim: int) -> None:
    rows = conn.execute(query).fetchall()  # type: ignore[attr-defined]
    assert rows
    for (embedding,) in rows:
        values = embedding.to_list()
        assert len(values) == dim
        norm = math.sqrt(sum(value * value for value in values))
        assert norm == pytest.approx(1.0, abs=1e-3)


def _assert_annotations(conn: object) -> None:
    rows = conn.execute(  # type: ignore[attr-defined]
        """
        select a.kind, a.geometry, a.label, s.width, s.height, a.case_id, s.case_id
        from annotation a
        join slide s on s.id = a.slide_id
        """
    ).fetchall()
    kinds = set()
    for kind, geometry, label, width, height, case_id, slide_case in rows:
        kinds.add(kind)
        assert 1 <= len(label) <= 80
        assert case_id == slide_case
        assert geometry["x"] >= 0 and geometry["y"] >= 0
        assert geometry["x"] < width and geometry["y"] < height
        if kind == "rect":
            assert geometry["width"] > 0 and geometry["height"] > 0
            assert geometry["x"] + geometry["width"] <= width
            assert geometry["y"] + geometry["height"] <= height
        else:
            assert kind == "point"
            assert "width" not in geometry
    assert kinds == {"rect", "point"}


def _assert_consult(conn: object) -> None:
    thread = conn.execute(
        "select case_id, user_id from consult_thread"
    ).fetchone()
    assert thread is not None
    case_id, user_id = thread
    assert user_id == DEMO_USER_ID
    message = conn.execute(
        """
        select citations, ranking, tool_trace, content
        from consult_message
        where role = 'assistant'
        """
    ).fetchone()
    assert message is not None
    citations, ranking, tool_trace, content = message
    assert "not a diagnosis" in content
    tool_cases: set[str] = set()
    for step in tool_trace:
        tool_cases.update(step["input"]["case_ids"])
    for citation in citations:
        cited = citation["case_id"]
        assert cited != case_id
        assert cited in tool_cases
        state = conn.execute(
            "select status, is_held_out from path_case where id = %s",
            (cited,),
        ).fetchone()
        assert state == ("signed_out", False)
    for rank in ranking:
        assert rank["case_count"] == len(rank["case_ids"])
        assert set(rank["case_ids"]) <= tool_cases


def _assert_jobs(conn: object) -> None:
    rows = {
        row[0]: row
        for row in conn.execute(
            """
            select status, stage, stage_history, error, finished_at, attempts, slide_id
            from ingestion_job
            """
        ).fetchall()
    }
    assert set(rows) == {"done", "failed", "queued"}
    done = rows["done"]
    assert done[1] == "load"
    assert done[2]
    assert done[3] is None and done[4] is not None and done[5] >= 1
    slide = conn.execute(
        "select status from slide where id = %s",
        (done[6],),
    ).fetchone()
    assert slide == ("ready",)
    failed = rows["failed"]
    assert failed[1] == "embed" and failed[3]
    queued = rows["queued"]
    assert queued[1] is None and queued[2] == [] and queued[4] is None and queued[5] == 0


def _assert_thumbnails(conn: object, root: Path) -> None:
    rows = conn.execute(
        """
        select s.thumb_pack_key, p.thumb_offset, p.thumb_length
        from patch p
        join slide s on s.id = p.slide_id
        """
    ).fetchall()
    assert rows
    cache: dict[str, bytes] = {}
    for key, offset, length in rows:
        if key not in cache:
            cache[key] = (root / key).read_bytes()
        blob = cache[key][offset : offset + length]
        assert blob.startswith(b"\xff\xd8")
        assert len(blob) == length
        with Image.open(io.BytesIO(blob)) as image:
            image.load()
            assert image.format == "JPEG"


def _assert_openslide(conn: object, root: Path) -> None:
    rows = conn.execute(
        "select distinct storage_key, width, height from slide order by storage_key"
    ).fetchall()
    assert len(rows) == 2
    for key, width, height in rows:
        path = root / key
        slide = openslide.OpenSlide(path)
        try:
            assert slide.dimensions == (width, height)
            assert slide.level_count >= 2
            assert slide.properties[openslide.PROPERTY_NAME_VENDOR] == "generic-tiff"
        finally:
            slide.close()


def _fingerprint(url: str, root: Path) -> tuple[dict[str, int], str, dict[str, str]]:
    conn = connect(url)
    try:
        counts = {
            table: int(conn.execute(f"select count(*) from {table}").fetchone()[0])
            for table in STORED_TABLES
        }
        lines: list[str] = []
        queries = (
            "select id, name, is_demo_user::text, is_synthetic::text from pathologist order by id",
            "select id, status, assigned_to, primary_diagnosis from path_case order by id",
            "select id, status, body from report order by id",
            """
            select slide_id, x::text, y::text, in_corpus::text, thumb_offset::text,
                   thumb_length::text, embedding::text
            from patch
            order by slide_id, x, y
            """,
            """
            select report_id, ordinal::text, section, in_corpus::text, text, embedding::text
            from report_chunk
            order by report_id, ordinal
            """,
            "select id, ordinal::text, embedding::text from concept order by id",
            "select id::text, kind, label from annotation order by id",
            "select id::text, role, content from consult_message order by created_at, id",
            "select id::text, status, stage from ingestion_job order by id",
        )
        for query in queries:
            for row in conn.execute(query).fetchall():
                lines.append("|".join("" if value is None else str(value) for value in row))
    finally:
        conn.close()
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    return counts, digest, files
