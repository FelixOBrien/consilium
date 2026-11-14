from __future__ import annotations

import psycopg
import pytest
from pgvector import HalfVector, Vector

from consilium.cli import main  # pragma: allowlist secret
from consilium.config import SearchBackend  # pragma: allowlist secret
from consilium.db.connection import connect, connection_pool  # pragma: allowlist secret
from consilium.db.migrate import (  # pragma: allowlist secret
    LakebaseIndexesNotImplemented,
    LakebaseMigrationRefused,
    _strip_comments,
    list_migrations,
    migrate,
    migration_status,
    split_sql,
)

STORED_TABLES = {
    "annotation",
    "concept",
    "consult_message",
    "consult_thread",
    "ingestion_job",
    "patch",
    "path_case",
    "pathologist",
    "patient",
    "report",
    "report_chunk",
    "slide",
}

# (column, udt_name, nullable). Order is the documented field order.
COLUMNS: dict[str, list[tuple[str, str, bool]]] = {
    "pathologist": [
        ("id", "text", False),
        ("name", "text", False),
        ("role_title", "text", False),
        ("primary_specialty", "text", False),
        ("secondary_specialties", "_text", False),
        ("is_demo_user", "bool", False),
        ("is_synthetic", "bool", False),
        ("created_at", "timestamptz", False),
    ],
    "patient": [
        ("id", "text", False),
        ("display_label", "text", False),
        ("sex", "text", True),
        ("birth_year", "int4", True),
        ("is_synthetic_linkage", "bool", False),
        ("created_at", "timestamptz", False),
    ],
    "concept": [
        ("id", "text", False),
        ("label", "text", False),
        ("prompt", "text", False),
        ("negative_prompt", "text", True),
        ("specialty", "text", True),
        ("ordinal", "int4", False),
        ("embedding", "halfvec", True),
        ("negative_embedding", "halfvec", True),
        ("created_at", "timestamptz", False),
    ],
    "path_case": [
        ("id", "text", False),
        ("patient_id", "text", False),
        ("specimen_label", "text", True),
        ("source_dataset", "text", False),
        ("source_case_id", "text", False),
        ("specialty", "text", False),
        ("patient_age", "int4", True),
        ("patient_sex", "text", True),
        ("primary_diagnosis", "text", True),
        ("morphology", "text", True),
        ("icd10", "text", True),
        ("status", "text", False),
        ("assigned_to", "text", False),
        ("accessioned_at", "timestamptz", False),
        ("is_held_out", "bool", False),
        ("cohort_tier", "text", False),
        ("created_at", "timestamptz", False),
    ],
    "slide": [
        ("id", "text", False),
        ("case_id", "text", False),
        ("ordinal", "int4", False),
        ("stain", "text", False),
        ("magnification", "float4", False),
        ("mpp", "float4", False),
        ("width", "int4", False),
        ("height", "int4", False),
        ("patch_size", "int4", False),
        ("patch_count", "int4", False),
        ("storage_key", "text", False),
        ("thumb_pack_key", "text", True),
        ("source_path", "text", False),
        ("embedding", "halfvec", True),
        ("status", "text", False),
        ("created_at", "timestamptz", False),
    ],
    "report": [
        ("id", "text", False),
        ("case_id", "text", False),
        ("author_id", "text", False),
        ("status", "text", False),
        ("body", "text", False),
        ("clinical_history", "text", True),
        ("gross_description", "text", True),
        ("microscopic_description", "text", True),
        ("conclusion", "text", True),
        ("additional_info", "text", True),
        ("icd10", "text", True),
        ("signed_at", "timestamptz", True),
        ("search_tsv", "tsvector", False),
        ("created_at", "timestamptz", False),
    ],
    "patch": [
        ("id", "int8", False),
        ("slide_id", "text", False),
        ("case_id", "text", False),
        ("patient_id", "text", False),
        ("specialty", "text", False),
        ("x", "int4", False),
        ("y", "int4", False),
        ("size", "int4", False),
        ("embedding", "halfvec", False),
        ("in_corpus", "bool", False),
        ("thumb_offset", "int8", False),
        ("thumb_length", "int4", False),
        ("created_at", "timestamptz", False),
    ],
    "report_chunk": [
        ("id", "int8", False),
        ("report_id", "text", False),
        ("case_id", "text", False),
        ("patient_id", "text", False),
        ("specialty", "text", False),
        ("section", "text", False),
        ("ordinal", "int4", False),
        ("text", "text", False),
        ("embedding", "vector", False),
        ("in_corpus", "bool", False),
        ("created_at", "timestamptz", False),
    ],
    "annotation": [
        ("id", "uuid", False),
        ("slide_id", "text", False),
        ("case_id", "text", False),
        ("author_id", "text", False),
        ("kind", "text", False),
        ("geometry", "jsonb", False),
        ("label", "text", False),
        ("note", "text", True),
        ("created_at", "timestamptz", False),
        ("updated_at", "timestamptz", False),
    ],
    "consult_thread": [
        ("id", "uuid", False),
        ("case_id", "text", False),
        ("user_id", "text", False),
        ("title", "text", True),
        ("created_at", "timestamptz", False),
        ("updated_at", "timestamptz", False),
    ],
    "consult_message": [
        ("id", "uuid", False),
        ("thread_id", "uuid", False),
        ("role", "text", False),
        ("content", "text", False),
        ("attachments", "jsonb", True),
        ("citations", "jsonb", True),
        ("ranking", "jsonb", True),
        ("tool_trace", "jsonb", True),
        ("model", "text", True),
        ("input_tokens", "int4", True),
        ("output_tokens", "int4", True),
        ("status", "text", False),
        ("created_at", "timestamptz", False),
    ],
    "ingestion_job": [
        ("id", "uuid", False),
        ("dataset", "text", False),
        ("slide_path", "text", False),
        ("case_id", "text", True),
        ("slide_id", "text", True),
        ("requested_by", "text", True),
        ("status", "text", False),
        ("stage", "text", True),
        ("stage_history", "jsonb", False),
        ("counts", "jsonb", True),
        ("error", "text", True),
        ("attempts", "int4", False),
        ("worker_id", "text", True),
        ("created_at", "timestamptz", False),
        ("started_at", "timestamptz", True),
        ("finished_at", "timestamptz", True),
    ],
}

VECTOR_DIMS = {
    ("concept", "embedding"): ("halfvec", 768),
    ("concept", "negative_embedding"): ("halfvec", 768),
    ("slide", "embedding"): ("halfvec", 768),
    ("patch", "embedding"): ("halfvec", 768),
    ("report_chunk", "embedding"): ("vector", 384),
}

FOREIGN_KEYS = {
    ("path_case", "patient_id", "patient", "NO ACTION"),
    ("path_case", "assigned_to", "pathologist", "NO ACTION"),
    ("slide", "case_id", "path_case", "NO ACTION"),
    ("report", "case_id", "path_case", "NO ACTION"),
    ("report", "author_id", "pathologist", "NO ACTION"),
    ("patch", "slide_id", "slide", "CASCADE"),
    ("patch", "case_id", "path_case", "NO ACTION"),
    ("patch", "patient_id", "patient", "NO ACTION"),
    ("report_chunk", "report_id", "report", "CASCADE"),
    ("report_chunk", "case_id", "path_case", "NO ACTION"),
    ("report_chunk", "patient_id", "patient", "NO ACTION"),
    ("annotation", "slide_id", "slide", "CASCADE"),
    ("annotation", "case_id", "path_case", "NO ACTION"),
    ("annotation", "author_id", "pathologist", "NO ACTION"),
    ("consult_thread", "case_id", "path_case", "NO ACTION"),
    ("consult_thread", "user_id", "pathologist", "NO ACTION"),
    ("consult_message", "thread_id", "consult_thread", "CASCADE"),
    ("ingestion_job", "requested_by", "pathologist", "NO ACTION"),
}


def test_migration_files_match_the_issue() -> None:
    files = list_migrations()
    assert [item.filename for item in files] == ["0001_init.sql", "0002_indexes.sql"]
    assert [item.kind for item in files] == ["schema", "index"]

    init_sql = files[0].path.read_text(encoding="utf-8")
    init_statements = split_sql(init_sql)
    executable_init = _strip_comments(init_sql).lower()
    assert "create extension" in executable_init
    tables = [statement for statement in init_statements if "create table " in statement.lower()]
    assert len(tables) == 12
    assert "search_hit" not in executable_init
    assert "lakebase_ann" not in executable_init
    assert "lakebase_bm25" not in executable_init

    index_sql = files[1].path.read_text(encoding="utf-8")
    executable = _strip_comments(index_sql).lower()
    assert "using hnsw" in executable
    assert "halfvec_cosine_ops" in executable
    assert "vector_cosine_ops" in executable
    assert "using gin" in executable
    assert "search_tsv" in executable
    assert "lakebase_ann" not in executable
    assert "lakebase_bm25" not in executable
    assert "lakebase_ann" in index_sql
    assert "lakebase_bm25" in index_sql


def test_split_sql_keeps_semicolons_inside_strings() -> None:
    statements = split_sql("select 'a;b';\n-- tail\nselect 1;")
    assert len(statements) == 2
    assert "select 'a;b'" in statements[0]
    assert "select 1" in statements[1]
    assert "a;b" not in statements[1]


def test_refuses_databricks_host_without_connecting() -> None:
    url = "postgresql://role:fixture@lakebase.example:5432/db"
    with pytest.raises(LakebaseMigrationRefused) as exc:
        migrate(url)
    message = str(exc.value)
    assert url not in message
    assert "fixture" not in message


def test_refuses_lakebase_database_url_match(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql://127.0.0.1:1/not-opened"
    monkeypatch.setenv("LAKEBASE_DATABASE_URL", url)
    with pytest.raises(LakebaseMigrationRefused) as exc:
        migrate(url)
    assert url not in str(exc.value)
    assert "secret" not in str(exc.value)


def test_fresh_migrate_is_idempotent(empty_database: str) -> None:
    first = migrate(empty_database)
    assert first == ["0001_init.sql", "0002_indexes.sql"]
    assert migrate(empty_database) == []

    states = migration_status(empty_database)
    assert [state.filename for state in states] == ["0001_init.sql", "0002_indexes.sql"]
    assert all(state.applied_at is not None for state in states)

    with _conn(empty_database) as conn:
        conn.execute(
            """
            insert into concept (id, label, prompt, ordinal)
            values ('tumour-necrosis', 'Necrosis', 'an H&E image of tumour necrosis', 1)
            """
        )
        assert conn.execute("select count(*) from concept").fetchone() == (1,)
    assert migrate(empty_database) == []
    with _conn(empty_database) as conn:
        assert conn.execute("select count(*) from concept").fetchone() == (1,)
        names = {
            row[0]
            for row in conn.execute(
                "select tablename from pg_tables where schemaname = 'public'"
            ).fetchall()
        }
    assert names == STORED_TABLES | {"schema_migration"}
    assert "search_hit" not in names


def test_catalog_matches_model_docs(empty_database: str) -> None:
    migrate(empty_database)
    with _conn(empty_database) as conn:
        for table, expected in COLUMNS.items():
            rows = conn.execute(
                """
                select column_name, udt_name, is_nullable, column_default,
                       is_identity, identity_generation, is_generated
                from information_schema.columns
                where table_schema = 'public' and table_name = %s
                order by ordinal_position
                """,
                (table,),
            ).fetchall()
            actual = [(name, udt, nullable == "YES") for name, udt, nullable, *_rest in rows]
            assert actual == expected, table
            by_name = {row[0]: row for row in rows}
            created = by_name["created_at"]
            assert created[3] is not None and "now()" in created[3]

        for (table, column), (udt, dim) in VECTOR_DIMS.items():
            typname, typmod = conn.execute(
                """
                select t.typname, a.atttypmod
                from pg_attribute a
                join pg_class c on c.oid = a.attrelid
                join pg_namespace n on n.oid = c.relnamespace
                join pg_type t on t.oid = a.atttypid
                where n.nspname = 'public' and c.relname = %s and a.attname = %s
                """,
                (table, column),
            ).fetchone()
            assert (typname, typmod) == (udt, dim)

        for column in ("id",):
            patch_id = conn.execute(
                """
                select is_identity, identity_generation
                from information_schema.columns
                where table_schema = 'public' and table_name = 'patch' and column_name = %s
                """,
                (column,),
            ).fetchone()
            chunk_id = conn.execute(
                """
                select is_identity, identity_generation
                from information_schema.columns
                where table_schema = 'public' and table_name = 'report_chunk'
                  and column_name = 'id'
                """
            ).fetchone()
            assert patch_id == ("YES", "ALWAYS")
            assert chunk_id == ("YES", "ALWAYS")

        expression = conn.execute(
            """
            select pg_get_expr(d.adbin, d.adrelid), a.attgenerated
            from pg_attrdef d
            join pg_attribute a on a.attrelid = d.adrelid and a.attnum = d.adnum
            join pg_class c on c.oid = a.attrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relname = 'report' and a.attname = 'search_tsv'
            """
        ).fetchone()
        assert expression is not None
        generated, stored = expression
        lowered = generated.lower()
        assert stored == "s"
        for piece in (
            "setweight",
            "conclusion",
            "microscopic_description",
            "additional_info",
            "gross_description",
            "clinical_history",
            "body",
            "'a'",
            "'b'",
            "'c'",
        ):
            assert piece in lowered

        fks = {
            (table, column, foreign, rule)
            for table, column, foreign, rule in conn.execute(
                """
                select kcu.table_name, kcu.column_name, ccu.table_name, rc.delete_rule
                from information_schema.table_constraints tc
                join information_schema.key_column_usage kcu
                  on tc.constraint_name = kcu.constraint_name
                 and tc.table_schema = kcu.table_schema
                join information_schema.referential_constraints rc
                  on tc.constraint_name = rc.constraint_name
                 and tc.table_schema = rc.constraint_schema
                join information_schema.constraint_column_usage ccu
                  on rc.unique_constraint_name = ccu.constraint_name
                 and rc.unique_constraint_schema = ccu.constraint_schema
                where tc.constraint_type = 'FOREIGN KEY' and tc.table_schema = 'public'
                """
            ).fetchall()
        }
        assert fks == FOREIGN_KEYS

        index_rows = conn.execute(
            """
            select am.amname, pg_get_indexdef(i.indexrelid)
            from pg_index i
            join pg_class idx on idx.oid = i.indexrelid
            join pg_am am on am.oid = idx.relam
            join pg_class tbl on tbl.oid = i.indrelid
            join pg_namespace n on n.oid = tbl.relnamespace
            where n.nspname = 'public'
            """
        ).fetchall()
    _require_indexes(index_rows)


def test_vectors_text_and_constraints(empty_database: str) -> None:
    migrate(empty_database)
    conch = [0.0] * 768
    conch[0] = 1.0
    conch[1] = -0.5
    conch[2] = 0.25
    report_values = [0.0] * 384
    report_values[0] = 1.0
    report_values[3] = 0.5

    with _conn(empty_database) as conn:
        _seed(conn)
        patch_id, patch_embedding = conn.execute(
            """
            insert into patch (
                slide_id, case_id, patient_id, specialty, x, y, size,
                embedding, in_corpus, thumb_offset, thumb_length
            ) values (
                'thorax-TCGA-38-4631-s1', 'thorax-TCGA-38-4631', 'pt-0042', 'thorax',
                0, 0, 1024, %s, true, 0, 128
            )
            returning id, embedding
            """,
            (HalfVector(conch),),
        ).fetchone()
        assert patch_embedding.dimensions() == 768
        patch_values = patch_embedding.to_list()
        assert patch_values[0] == pytest.approx(1.0)
        assert patch_values[1] == pytest.approx(-0.5)
        assert patch_values[2] == pytest.approx(0.25)
        distance = conn.execute(
            "select embedding <=> %s from patch where id = %s",
            (HalfVector(conch), patch_id),
        ).fetchone()[0]
        assert float(distance) == pytest.approx(0.0, abs=1e-3)

        chunk_embedding = conn.execute(
            """
            insert into report_chunk (
                report_id, case_id, patient_id, specialty, section, ordinal, text,
                embedding, in_corpus
            ) values (
                'thorax-TCGA-38-4631-r1', 'thorax-TCGA-38-4631', 'pt-0042', 'thorax',
                'conclusion', 1, 'keratinisation present', %s, true
            )
            returning embedding
            """,
            (Vector(report_values),),
        ).fetchone()[0]
        assert chunk_embedding.dimensions() == 384
        chunk_values = chunk_embedding.to_list()
        assert chunk_values[0] == pytest.approx(1.0)
        assert chunk_values[3] == pytest.approx(0.5)

        with pytest.raises(psycopg.Error):
            with conn.transaction():
                conn.execute(
                    """
                    insert into patch (
                        slide_id, case_id, patient_id, specialty, x, y, size,
                        embedding, in_corpus, thumb_offset, thumb_length
                    ) values (
                        'thorax-TCGA-38-4631-s1', 'thorax-TCGA-38-4631', 'pt-0042', 'thorax',
                        512, 0, 1024, %s, true, 10, 8
                    )
                    """,
                    (HalfVector([1.0, *([0.0] * 383)]),),
                )
        with pytest.raises(psycopg.Error):
            with conn.transaction():
                conn.execute(
                    """
                    insert into report_chunk (
                        report_id, case_id, patient_id, specialty, section, ordinal, text,
                        embedding, in_corpus
                    ) values (
                        'thorax-TCGA-38-4631-r1', 'thorax-TCGA-38-4631', 'pt-0042', 'thorax',
                        'body', 2, 'wrong width', %s, false
                    )
                    """,
                    (Vector([1.0, *([0.0] * 767)]),),
                )
        with pytest.raises(psycopg.Error):
            with conn.transaction():
                conn.execute(
                    """
                    select p.embedding <=> c.embedding
                    from patch p
                    cross join report_chunk c
                    limit 1
                    """
                )

        tsv = conn.execute(
            "select search_tsv::text from report where id = 'thorax-TCGA-38-4631-r1'"
        ).fetchone()[0]
        assert _weight(conn, tsv, "keratinisation") == "A"
        assert _weight(conn, tsv, "cassette") == "C"
        matched = conn.execute(
            """
            select search_tsv @@ plainto_tsquery('english', 'keratinisation'),
                   search_tsv @@ plainto_tsquery('english', 'cassette')
            from report
            where id = 'thorax-TCGA-38-4631-r1'
            """
        ).fetchone()
        assert matched == (True, True)

        with pytest.raises(psycopg.Error):
            with conn.transaction():
                conn.execute(
                    """
                    insert into pathologist (
                        id, name, role_title, primary_specialty, secondary_specialties,
                        is_demo_user, is_synthetic
                    ) values (
                        'path-real', 'Dr Real Person', 'Consultant', 'skin', '{}', false, false
                    )
                    """
                )
        with pytest.raises(psycopg.Error):
            with conn.transaction():
                conn.execute(
                    """
                    insert into path_case (
                        id, patient_id, source_dataset, source_case_id, specialty, status,
                        assigned_to, accessioned_at, is_held_out, cohort_tier
                    ) values (
                        'skin-open', 'pt-0042', 'TCGA-SKCM', 'TCGA-OPEN-1', 'skin', 'open',
                        'path-okafor', now(), false, 'demo'
                    )
                    """
                )


def test_schema_and_indexes_run_separately(empty_database: str) -> None:
    assert migrate(empty_database, include_indexes=False) == ["0001_init.sql"]
    with _conn(empty_database) as conn:
        methods = _access_methods(conn)
    assert "btree" in methods
    assert "hnsw" not in methods
    assert "gin" not in methods

    assert migrate(empty_database, include_schema=False) == ["0002_indexes.sql"]
    with _conn(empty_database) as conn:
        methods = _access_methods(conn)
    assert "hnsw" in methods
    assert "gin" in methods
    assert migrate(empty_database) == []


def test_lakebase_backend_does_not_create_search_indexes(empty_database: str) -> None:
    with pytest.raises(LakebaseIndexesNotImplemented):
        migrate(empty_database, search_backend=SearchBackend.LAKEBASE)
    states = migration_status(empty_database)
    applied = {state.filename: state.applied_at is not None for state in states}
    assert applied == {"0001_init.sql": True, "0002_indexes.sql": False}
    with _conn(empty_database) as conn:
        methods = _access_methods(conn)
    assert "hnsw" not in methods
    assert "gin" not in methods

    with pytest.raises(LakebaseIndexesNotImplemented):
        migrate(
            "postgresql://127.0.0.1:1/not-opened",
            search_backend=SearchBackend.LAKEBASE,
            include_schema=False,
        )


def test_cli_migrate_and_status(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", empty_database)
    monkeypatch.setenv("SEARCH_BACKEND", "pgvector")
    assert main(["db", "migrate"]) == 0
    applied = capsys.readouterr().out
    assert "applied 0001_init.sql" in applied
    assert "applied 0002_indexes.sql" in applied

    assert main(["db", "migrate"]) == 0
    assert "up to date" in capsys.readouterr().out

    assert main(["db", "status"]) == 0
    status = capsys.readouterr().out
    assert "0001_init.sql applied" in status
    assert "0002_indexes.sql applied" in status


def test_pool_registers_pgvector(empty_database: str) -> None:
    migrate(empty_database, include_indexes=False)
    with connection_pool(empty_database, min_size=1) as pool:
        with pool.connection() as conn:
            assert conn.execute("select 1").fetchone() == (1,)
            vector = conn.execute("select %s::vector", (Vector([0.25, 0.5]),)).fetchone()[0]
            half = conn.execute("select %s::halfvec", (HalfVector([0.5, -0.5]),)).fetchone()[0]
    assert vector.to_list() == pytest.approx([0.25, 0.5])
    half_values = half.to_list()
    assert half_values[0] == pytest.approx(0.5)
    assert half_values[1] == pytest.approx(-0.5)


class _Conn:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> psycopg.Connection:
        return self._conn

    def __exit__(self, *exc: object) -> None:
        self._conn.close()


def _conn(url: str) -> _Conn:
    conn = connect(url)
    conn.autocommit = True
    return _Conn(conn)


def _seed(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        insert into pathologist (
            id, name, role_title, primary_specialty, secondary_specialties,
            is_demo_user, is_synthetic
        ) values (
            'path-okafor', 'Dr A. Okafor', 'Consultant Histopathologist', 'thorax',
            '{}', true, true
        )
        """
    )
    conn.execute(
        """
        insert into patient (id, display_label, sex, birth_year, is_synthetic_linkage)
        values ('pt-0042', 'PT-0042', 'F', 1970, false)
        """
    )
    conn.execute(
        """
        insert into path_case (
            id, patient_id, specimen_label, source_dataset, source_case_id, specialty,
            patient_age, patient_sex, primary_diagnosis, morphology, icd10, status,
            assigned_to, accessioned_at, is_held_out, cohort_tier
        ) values (
            'thorax-TCGA-38-4631', 'pt-0042', 'Primary resection', 'TCGA-LUAD',
            'TCGA-38-4631', 'thorax', 60, 'F', 'Adenocarcinoma, NOS', '8140/3', 'C34.1',
            'signed_out', 'path-okafor', now(), false, 'demo'
        )
        """
    )
    conn.execute(
        """
        insert into slide (
            id, case_id, ordinal, stain, magnification, mpp, width, height, patch_size,
            patch_count, storage_key, source_path, status
        ) values (
            'thorax-TCGA-38-4631-s1', 'thorax-TCGA-38-4631', 1, 'HE', 40, 0.25,
            4000, 4000, 1024, 1, 'slides/thorax-TCGA-38-4631-s1.svs',
            'file-id/slide.svs', 'pending'
        )
        """
    )
    conn.execute(
        """
        insert into report (
            id, case_id, author_id, status, body, conclusion, signed_at
        ) values (
            'thorax-TCGA-38-4631-r1', 'thorax-TCGA-38-4631', 'path-okafor', 'signed',
            'cassette received for processing', 'keratinisation present', now()
        )
        """
    )


def _weight(conn: psycopg.Connection, tsv: str, word: str) -> str:
    lexeme = conn.execute("select to_tsvector('english', %s)::text", (word,)).fetchone()[0]
    stem = lexeme.split(":", 1)[0]
    token = next(part for part in tsv.split() if part.startswith(stem))
    weights = token.split(":", 1)[1]
    assert "A" in weights or "B" in weights or "C" in weights or "D" in weights
    for letter in ("A", "B", "C", "D"):
        if letter in weights:
            return letter
    raise AssertionError(token)


def _access_methods(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute(
        """
        select am.amname
        from pg_index i
        join pg_class idx on idx.oid = i.indexrelid
        join pg_am am on am.oid = idx.relam
        join pg_class tbl on tbl.oid = i.indrelid
        join pg_namespace n on n.oid = tbl.relnamespace
        where n.nspname = 'public'
        """
    ).fetchall()
    return {row[0] for row in rows}


def _require_indexes(rows: list[tuple[str, str]]) -> None:
    hnsw = [definition for method, definition in rows if method == "hnsw"]
    gin = [definition for method, definition in rows if method == "gin"]
    assert len(hnsw) == 3
    assert len(gin) == 1
    assert any("halfvec_cosine_ops" in item and "slide" in item for item in hnsw)
    assert any("halfvec_cosine_ops" in item and "patch" in item for item in hnsw)
    assert any("vector_cosine_ops" in item and "report_chunk" in item for item in hnsw)
    assert all("concept" not in definition for definition in hnsw)
    assert "search_tsv" in gin[0]
    joined = "\n".join(definition.lower() for _method, definition in rows)
    for fragment in (
        "is_demo_user",
        "lower(display_label)",
        "accessioned_at desc",
        "text_pattern_ops",
        "in_corpus",
        "ready",
        "queued",
        "running",
        "(case_id, ordinal)",
        "(slide_id, x, y)",
        "(author_id)",
        "(patient_id)",
    ):
        assert fragment in joined, fragment
