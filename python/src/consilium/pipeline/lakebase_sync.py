"""Load pipeline rows into an already-migrated Postgres or Lakebase database.

Vectors arrive as arrays of float, which is what Delta stores, and are cast to
``halfvec(768)`` or ``vector(384)`` here. The loader does not create
``lakebase_ann`` or ``lakebase_bm25`` indexes. ``SEARCH_BACKEND`` stays on the
pgvector indexes from ``0002_indexes.sql``.

The block between the markers is copied into the Databricks notebook so the
same function can run on serverless when ``psycopg`` is installed.
"""

from __future__ import annotations

# BEGIN LOADER
from collections.abc import Mapping, Sequence  # noqa: E402


def _sql():
    from psycopg import sql

    return sql


class LakebaseLoader:
    """Upsert the eight pipeline tables. Child rows are replaced per parent."""

    def __init__(self, conn: object) -> None:
        self._conn = conn

    def load(self, tables: Mapping[str, Sequence[Mapping[str, object]]]) -> int:
        """Load rows and return ``pg_database_size(current_database())``."""
        with self._conn.transaction():
            self._load_pathologists(list(tables.get("pathologist", ())))
            self._upsert("patient", list(tables.get("patient", ())))
            self._upsert("concept", list(tables.get("concept", ())))
            self._upsert("path_case", list(tables.get("path_case", ())))
            self._load_reports(list(tables.get("report", ())))
            self._load_slides(list(tables.get("slide", ())))
            self._load_patches(list(tables.get("patch", ())))
            self._mark_ready()
            self._load_chunks(list(tables.get("report_chunk", ())))
            row = self._conn.execute("select pg_database_size(current_database())").fetchone()
        return int(row[0]) if row else 0

    def _load_pathologists(self, rows: list[Mapping[str, object]]) -> None:
        if not rows:
            return
        demo = [str(row["id"]) for row in rows if bool(row.get("is_demo_user"))]
        if len(demo) > 1:
            raise ValueError("pathologist rows have more than one demo user")
        if demo:
            self._conn.execute(
                "update pathologist set is_demo_user = false where is_demo_user and id <> %s",
                (demo[0],),
            )
        self._upsert("pathologist", rows)

    def _load_reports(self, rows: list[Mapping[str, object]]) -> None:
        if not rows:
            return
        self._stage("report", rows)
        self._conn.execute(
            """
            delete from report as existing
            using staging_report as incoming
            where existing.case_id = incoming.case_id
              and existing.id <> incoming.id
            """
        )
        self._upsert_from_staging("report")

    def _load_slides(self, rows: list[Mapping[str, object]]) -> None:
        if not rows:
            return
        self._stage("slide", rows)
        columns = _COLUMNS["slide"]
        skipped = {"embedding", "thumb_pack_key", "status"}
        pending = tuple(column for column in columns if column not in skipped)
        select_list = _sql().SQL(", ").join(
            [
                *(_sql().Identifier(column) for column in pending),
                _sql().SQL("null::halfvec(768)"),
                _sql().SQL("null::text"),
                _sql().SQL("'pending'"),
            ]
        )
        pending_columns = (*pending, "embedding", "thumb_pack_key", "status")
        column_list = _sql().SQL(", ").join(
            _sql().Identifier(column) for column in pending_columns
        )
        piece = _sql().SQL("{} = excluded.{}")
        assignments = _sql().SQL(", ").join(
            piece.format(_sql().Identifier(column), _sql().Identifier(column))
            for column in pending
        )
        self._conn.execute(
            _sql().SQL(
                """
                insert into slide ({columns})
                select {select_list}
                from staging_slide
                on conflict (id) do update set
                    {assignments},
                    embedding = null,
                    thumb_pack_key = null,
                    status = 'pending'
                """
            ).format(columns=column_list, select_list=select_list, assignments=assignments)
        )

    def _load_patches(self, rows: list[Mapping[str, object]]) -> None:
        if self._temp_ready("staging_slide"):
            self._conn.execute(
                """
                delete from patch
                where slide_id in (select id from staging_slide)
                """
            )
        elif rows:
            raise ValueError("patch rows require slide rows in the same load")
        if not rows:
            return
        self._stage("patch", rows)
        self._insert_from_staging("patch")

    def _mark_ready(self) -> None:
        if not self._temp_ready("staging_slide"):
            return
        self._conn.execute(
            """
            update slide as target
            set status = 'ready',
                embedding = incoming.embedding::halfvec(768),
                thumb_pack_key = incoming.thumb_pack_key,
                patch_count = incoming.patch_count,
                case_id = incoming.case_id,
                ordinal = incoming.ordinal,
                stain = incoming.stain,
                magnification = incoming.magnification,
                mpp = incoming.mpp,
                width = incoming.width,
                height = incoming.height,
                patch_size = incoming.patch_size,
                storage_key = incoming.storage_key,
                source_path = incoming.source_path
            from staging_slide as incoming
            where target.id = incoming.id
              and incoming.status = 'ready'
              and incoming.embedding is not null
              and incoming.thumb_pack_key is not null
            """
        )
        stranded = self._conn.execute(
            """
            select incoming.id
            from staging_slide as incoming
            join slide as target on target.id = incoming.id
            where incoming.status = 'ready'
              and target.status <> 'ready'
            """
        ).fetchall()
        if stranded:
            ids = ", ".join(str(row[0]) for row in stranded[:5])
            raise RuntimeError(f"slides stayed pending after their patches loaded: {ids}")

    def _temp_ready(self, name: str) -> bool:
        row = self._conn.execute("select to_regclass(%s) is not null", (name,)).fetchone()
        return bool(row and row[0])

    def _load_chunks(self, rows: list[Mapping[str, object]]) -> None:
        report_ids = sorted({str(row["report_id"]) for row in rows if row.get("report_id")})
        if report_ids:
            self._conn.execute(
                "delete from report_chunk where report_id = any(%s)",
                (report_ids,),
            )
        if not rows:
            return
        self._stage("report_chunk", rows)
        self._insert_from_staging("report_chunk")

    def _upsert(self, table: str, rows: list[Mapping[str, object]]) -> None:
        if not rows:
            return
        self._stage(table, rows)
        self._upsert_from_staging(table)

    def _stage(self, table: str, rows: Sequence[Mapping[str, object]]) -> None:
        columns = _COLUMNS[table]
        vectors = _VECTORS.get(table, ())
        staging = f"staging_{table}"
        definitions = _sql().SQL(", ").join(
            _sql().SQL("{} {}").format(
                _sql().Identifier(column),
                _sql().SQL("text" if column in vectors else _staging_type(column)),
            )
            for column in columns
        )
        self._conn.execute(
            _sql().SQL("create temp table {} ({}) on commit drop").format(
                _sql().Identifier(staging),
                definitions,
            )
        )
        tuples = [_values(row, columns) for row in rows]
        if not tuples:
            return
        statement = _sql().SQL("copy {} ({}) from stdin").format(
            _sql().Identifier(staging),
            _sql().SQL(", ").join(_sql().Identifier(column) for column in columns),
        )
        with self._conn.cursor() as cursor:
            with cursor.copy(statement) as copy:
                for row in tuples:
                    copy.write_row(row)

    def _upsert_from_staging(self, table: str) -> None:
        columns = _COLUMNS[table]
        casts = _CASTS.get(table, {})
        column_list = _sql().SQL(", ").join(_sql().Identifier(column) for column in columns)
        select_list = _sql().SQL(", ").join(_cast(column, casts.get(column)) for column in columns)
        piece = _sql().SQL("{} = excluded.{}")
        assignments = _sql().SQL(", ").join(
            piece.format(_sql().Identifier(column), _sql().Identifier(column))
            for column in columns
            if column != "id"
        )
        self._conn.execute(
            _sql().SQL(
                """
                insert into {table} ({columns})
                select {select_list}
                from {staging}
                on conflict (id) do update set {assignments}
                """
            ).format(
                table=_sql().Identifier(table),
                columns=column_list,
                select_list=select_list,
                staging=_sql().Identifier(f"staging_{table}"),
                assignments=assignments,
            )
        )

    def _insert_from_staging(self, table: str) -> None:
        columns = _COLUMNS[table]
        casts = _CASTS.get(table, {})
        column_list = _sql().SQL(", ").join(_sql().Identifier(column) for column in columns)
        select_list = _sql().SQL(", ").join(_cast(column, casts.get(column)) for column in columns)
        self._conn.execute(
            _sql().SQL(
                """
                insert into {table} ({columns})
                select {select_list}
                from {staging}
                """
            ).format(
                table=_sql().Identifier(table),
                columns=column_list,
                select_list=select_list,
                staging=_sql().Identifier(f"staging_{table}"),
            )
        )


_COLUMNS: dict[str, tuple[str, ...]] = {
    "pathologist": (
        "id",
        "name",
        "role_title",
        "primary_specialty",
        "secondary_specialties",
        "is_demo_user",
        "is_synthetic",
        "created_at",
    ),
    "patient": (
        "id",
        "display_label",
        "sex",
        "birth_year",
        "is_synthetic_linkage",
        "created_at",
    ),
    "concept": (
        "id",
        "label",
        "prompt",
        "negative_prompt",
        "specialty",
        "ordinal",
        "embedding",
        "negative_embedding",
        "created_at",
    ),
    "path_case": (
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
    ),
    "slide": (
        "id",
        "case_id",
        "ordinal",
        "stain",
        "magnification",
        "mpp",
        "width",
        "height",
        "patch_size",
        "patch_count",
        "storage_key",
        "thumb_pack_key",
        "source_path",
        "embedding",
        "status",
        "created_at",
    ),
    "report": (
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
    ),
    "report_chunk": (
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
    ),
    "patch": (
        "slide_id",
        "case_id",
        "patient_id",
        "specialty",
        "x",
        "y",
        "size",
        "embedding",
        "in_corpus",
        "thumb_offset",
        "thumb_length",
        "created_at",
    ),
}

_VECTORS: dict[str, tuple[str, ...]] = {
    "concept": ("embedding", "negative_embedding"),
    "slide": ("embedding",),
    "patch": ("embedding",),
    "report_chunk": ("embedding",),
}

_CASTS: dict[str, dict[str, str]] = {
    "concept": {"embedding": "halfvec(768)", "negative_embedding": "halfvec(768)"},
    "slide": {"embedding": "halfvec(768)"},
    "patch": {"embedding": "halfvec(768)"},
    "report_chunk": {"embedding": "vector(384)"},
}


def _cast(column: str, cast: str | None):
    if cast is None:
        return _sql().Identifier(column)
    return _sql().SQL("{}::{}").format(_sql().Identifier(column), _sql().SQL(cast))


def _staging_type(column: str) -> str:
    if column in {
        "ordinal",
        "birth_year",
        "patient_age",
        "width",
        "height",
        "patch_size",
        "patch_count",
        "x",
        "y",
        "size",
        "thumb_length",
    }:
        return "integer"
    if column == "thumb_offset":
        return "bigint"
    if column in {"magnification", "mpp"}:
        return "double precision"
    if column in {
        "is_demo_user",
        "is_synthetic",
        "is_synthetic_linkage",
        "is_held_out",
        "in_corpus",
    }:
        return "boolean"
    if column == "secondary_specialties":
        return "text[]"
    if column in {"created_at", "accessioned_at", "signed_at"}:
        return "timestamptz"
    return "text"


def _values(row: Mapping[str, object], columns: Sequence[str]) -> tuple[object, ...]:
    from datetime import UTC, datetime

    values: list[object] = []
    for column in columns:
        value = row.get(column)
        if column in {"embedding", "negative_embedding"}:
            values.append(_vector_text(value))
        elif column == "secondary_specialties":
            items = [] if value is None else list(value)  # type: ignore[arg-type]
            values.append([str(item) for item in items])
        elif column in {"created_at", "accessioned_at"} and value is None:
            values.append(datetime.now(UTC))
        else:
            values.append(value)
    return tuple(values)


def _vector_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    numbers = [float(item) for item in value]  # type: ignore[arg-type]
    if not numbers:
        return None
    return "[" + ",".join(repr(number) for number in numbers) + "]"


# END LOADER
