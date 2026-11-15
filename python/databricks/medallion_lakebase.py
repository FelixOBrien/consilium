# Databricks notebook source
# MAGIC %md
# MAGIC # Lakehouse medallion
# MAGIC
# MAGIC Research prototype, not a medical device and not for clinical use.
# MAGIC This notebook does not create lakebase_ann or lakebase_bm25 indexes.
# MAGIC `SEARCH_BACKEND` stays `pgvector`. Vectors stay `ARRAY<FLOAT>` until the
# MAGIC Lakebase load casts them to `halfvec(768)` or `vector(384)`.

# COMMAND ----------

import os
import re

from pyspark.sql.functions import col, current_timestamp, lit
from pyspark.sql.types import ArrayType, FloatType

spark = globals().get("spark")
dbutils = globals().get("dbutils")

MODELS = (
    "pathologist",
    "patient",
    "concept",
    "path_case",
    "slide",
    "report",
    "report_chunk",
    "patch",
)
RULES = (
    "non_empty_id",
    "valid_specialty",
    "unit_norm",
    "in_corpus",
    "positive_dimension",
    "duplicate_natural_key",
)
_PATCH_LIMIT = 20_000
_SPECIALTY_LIST = (
    "('breast', 'thorax', 'colorectal', 'gastrointestinal', 'skin', 'hematologic')"
)


def _widget(name: str, default: str) -> str:
    """Widget value, or `default` when the widget is missing or blank."""
    try:
        dbutils.widgets.text(name, default)
        value = str(dbutils.widgets.get(name) or "").strip()
    except Exception:
        value = ""
    return value or default


def _identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""):
        raise ValueError(f"{label} is not a catalog identifier")
    return value


def _with_ssl(url: str) -> str:
    """Require TLS without downgrading verify-full or verify-ca."""
    match = re.search(r"sslmode=([A-Za-z0-9-]+)", url)
    if match is None:
        joiner = "&" if "?" in url else "?"
        return f"{url}{joiner}sslmode=require"
    mode = match.group(1)
    if mode in {"require", "verify-ca", "verify-full"}:
        return url
    return url[: match.start(1)] + "require" + url[match.end(1) :]


catalog = _identifier(
    _widget("catalog", os.environ.get("DATABRICKS_CATALOG", "main")),
    "catalog",
)
schema_name = _identifier(
    _widget("schema", os.environ.get("DATABRICKS_SCHEMA", "consilium")),  # pragma: allowlist secret
    "schema",
)
volume_name = _identifier(
    _widget("volume_name", os.environ.get("DATABRICKS_VOLUME", "raw")) or "raw",
    "volume_name",
)
database_url = _widget("database_url", os.environ.get("DATABASE_URL", "")).strip()
max_cases = int(_widget("max_cases", os.environ.get("LAKEBASE_MAX_CASES", "45")).strip() or "45")
if not database_url:
    try:
        found = dbutils.secrets.get(
            scope="consilium",  # pragma: allowlist secret
            key="database_url",
        )
        database_url = str(found or "").strip()
    except Exception:
        database_url = ""

volume = f"/Volumes/{catalog}/{schema_name}/{volume_name}"
print(f"volume={volume}")
print("lakebase_sync " + ("configured" if database_url else "skipped"))

# COMMAND ----------

# BEGIN SELECT
from collections.abc import Mapping, Sequence  # noqa: E402
from datetime import UTC, datetime  # noqa: E402


def select_case_ids(
    cases: Sequence[Mapping[str, object]],
    counts: Mapping[str, Mapping[str, int]] | None = None,
    *,
    max_cases: int = 45,
    byte_budget: int = 320 * 1024 * 1024,
) -> dict[str, list[str] | int | str]:
    """Pick case ids for the Lakebase subset.

    Held-out and open cases are always included, then every earlier case of
    those patients. Signed-out cases fill the remaining slots one specialty at
    a time, in a fixed specialty order, skipping any case that would pass
    ``max_cases`` or ``byte_budget``. The result is deterministic.
    """
    specialties = (
        "breast",
        "thorax",
        "colorectal",
        "gastrointestinal",
        "skin",
        "hematologic",
    )
    patch_in_bytes = 5124
    patch_out_bytes = 2560
    chunk_in_bytes = 5124
    chunk_out_bytes = 2560
    slide_bytes = 5124
    overhead = 32 * 1024 * 1024
    usage = counts or {}

    prepared: list[dict[str, object]] = []
    for row in cases:
        case_id = str(row.get("id") or "").strip()
        patient_id = str(row.get("patient_id") or "").strip()
        if case_id == "" or patient_id == "":
            continue
        status = str(row.get("status") or "").strip()
        held = bool(row.get("is_held_out"))
        prepared.append(
            {
                "id": case_id,
                "patient_id": patient_id,
                "specialty": str(row.get("specialty") or "").strip(),
                "status": status,
                "held": held or status == "open",
                "at": _stamp(row.get("accessioned_at")),
            }
        )

    def estimate(ids: set[str]) -> int:
        total = overhead
        for case_id in ids:
            row = usage.get(case_id, {})
            total += int(row.get("patch_in", 0)) * patch_in_bytes
            total += int(row.get("patch_out", 0)) * patch_out_bytes
            total += int(row.get("chunk_in", 0)) * chunk_in_bytes
            total += int(row.get("chunk_out", 0)) * chunk_out_bytes
            total += int(row.get("slides_ready", 0)) * slide_bytes
        return total

    def priors_of(anchor: dict[str, object], chosen: set[str]) -> list[dict[str, object]]:
        found: list[dict[str, object]] = []
        for other in prepared:
            if other["id"] in chosen or other["patient_id"] != anchor["patient_id"]:
                continue
            if other["id"] == anchor["id"]:
                continue
            other_at = other["at"]
            anchor_at = anchor["at"]
            if isinstance(other_at, datetime) and isinstance(anchor_at, datetime):
                if other_at <= anchor_at:
                    found.append(other)
        return found

    selected: dict[str, dict[str, object]] = {}
    held_ids: list[str] = []
    prior_ids: list[str] = []
    for row in prepared:
        if row["held"] and row["id"] not in selected:
            selected[str(row["id"])] = row
            held_ids.append(str(row["id"]))
    for row in list(selected.values()):
        for prior in priors_of(row, set(selected)):
            selected[str(prior["id"])] = prior
            prior_ids.append(str(prior["id"]))

    buckets: dict[str, list[dict[str, object]]] = {name: [] for name in specialties}
    for row in prepared:
        if row["id"] in selected or row["held"] or row["status"] != "signed_out":
            continue
        specialty = str(row["specialty"])
        if specialty in buckets:
            buckets[specialty].append(row)
    for name in specialties:
        buckets[name].sort(key=lambda item: str(item["id"]))
    cursor = dict.fromkeys(specialties, 0)
    sampled_ids: list[str] = []
    stopped = "exhausted"
    if estimate(set(selected)) > byte_budget:
        stopped = "byte_budget"
    else:
        while True:
            if len(selected) >= max_cases:
                stopped = "max_cases"
                break
            added = False
            saw_candidate = False
            hit_cap = False
            hit_budget = False
            for specialty in specialties:
                index = cursor[specialty]
                bucket = buckets[specialty]
                if index >= len(bucket):
                    continue
                candidate = bucket[index]
                cursor[specialty] = index + 1
                saw_candidate = True
                family = [candidate, *priors_of(candidate, set(selected))]
                fresh = [row for row in family if row["id"] not in selected]
                if len(selected) + len(fresh) > max_cases:
                    hit_cap = True
                    continue
                projected = set(selected)
                projected.update(str(row["id"]) for row in fresh)
                if estimate(projected) > byte_budget:
                    hit_budget = True
                    continue
                for row in fresh:
                    selected[str(row["id"])] = row
                    if row["id"] != candidate["id"]:
                        prior_ids.append(str(row["id"]))
                sampled_ids.append(str(candidate["id"]))
                added = True
            if added:
                continue
            if not saw_candidate:
                break
            if hit_budget and not hit_cap:
                stopped = "byte_budget"
            elif hit_cap:
                stopped = "max_cases"
            # A candidate that does not fit is skipped. Keep walking so a later,
            # smaller case in the same specialty can still be taken. Stop once
            # every remaining candidate has been considered without an add.
            if not hit_budget and not hit_cap:
                break

    ordered = sorted(
        selected.values(),
        key=lambda row: (
            specialties.index(str(row["specialty"]))
            if str(row["specialty"]) in specialties
            else len(specialties),
            str(row["id"]),
        ),
    )
    return {
        "case_ids": [str(row["id"]) for row in ordered],
        "held_out_ids": held_ids,
        "prior_ids": prior_ids,
        "sampled_ids": sampled_ids,
        "estimated_bytes": estimate(set(selected)),
        "stopped": stopped,
    }


def _stamp(value: object):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return datetime.min.replace(tzinfo=UTC)


# END SELECT

# COMMAND ----------

spark.sql(f"create schema if not exists {catalog}.{schema_name}")
for model in MODELS:
    source = f"{volume}/export/{model}.parquet"
    landed = (
        spark.read.parquet(source)
        .withColumn("_ingested_at", current_timestamp())
        .withColumn("_source_file", lit(source))
    )
    (
        landed.write.mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(f"{catalog}.{schema_name}.bronze_{model}")
    )
    print(f"bronze_{model} {landed.count()}")

# COMMAND ----------

_NATURAL = {
    "pathologist": ["id"],
    "patient": ["id"],
    "concept": ["id"],
    "path_case": ["id"],
    "slide": ["id"],
    "report": ["id"],
    "report_chunk": ["report_id", "ordinal"],
    "patch": ["slide_id", "x", "y"],
}
_ARRAYS = {
    "concept": ("embedding", "negative_embedding"),
    "slide": ("embedding",),
    "patch": ("embedding",),
    "report_chunk": ("embedding",),
}
for model in MODELS:
    typed = spark.table(f"{catalog}.{schema_name}.bronze_{model}")
    for column in _ARRAYS.get(model, ()):
        if column in typed.columns:
            typed = typed.withColumn(column, col(column).cast(ArrayType(FloatType())))
    typed = typed.dropDuplicates(_NATURAL[model])
    (
        typed.write.mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(f"{catalog}.{schema_name}.silver_{model}")
    )
    print(f"silver_{model} {typed.count()}")

# COMMAND ----------


def _silver(model: str) -> str:
    return f"{catalog}.{schema_name}.silver_{model}"


def _bronze(model: str) -> str:
    return f"{catalog}.{schema_name}.bronze_{model}"


def _count(query: str) -> int:
    row = spark.sql(query).collect()[0][0]
    return int(row or 0)


def _norm(column: str, dim: int, *, required: bool) -> str:
    score = (
        f"size({column}) <> {dim} or abs(sqrt(aggregate("
        f"{column}, cast(0 as double), (acc, x) -> "
        "acc + cast(x as double) * cast(x as double))) - 1.0) > 0.01"
    )
    if required:
        return f"({column} is null or {score})"
    return f"({column} is not null and ({score}))"


def _non_empty(model: str, columns: tuple[str, ...]) -> str:
    checks = [
        f"{column} is null or length(trim(cast({column} as string))) = 0" for column in columns
    ]
    return f"select count(*) as n from {_silver(model)} where {' or '.join(checks)}"


def _duplicates(model: str, keys: tuple[str, ...]) -> str:
    grouped = ", ".join(keys)
    return (
        "select coalesce(sum(extra), 0) as n from ("
        f"select count(*) - 1 as extra from {_bronze(model)} "
        f"group by {grouped} having count(*) > 1)"
    )


def _corpus(model: str) -> str:
    return (
        "select count(*) as n from "
        f"{_silver(model)} as child left join {_silver('path_case')} as path_case "
        "on child.case_id = path_case.id where path_case.id is null "
        "or child.in_corpus <> (path_case.status = 'signed_out' "
        "and not coalesce(path_case.is_held_out, false))"
    )


_TEXT = {
    "pathologist": ("id",),
    "patient": ("id",),
    "concept": ("id",),
    "path_case": ("id", "patient_id", "assigned_to"),
    "slide": ("id", "case_id"),
    "report": ("id", "case_id", "author_id"),
    "report_chunk": ("report_id", "case_id", "patient_id"),
    "patch": ("slide_id", "case_id", "patient_id"),
}
_KEYS = {
    "pathologist": ("id",),
    "patient": ("id",),
    "concept": ("id",),
    "path_case": ("id",),
    "slide": ("id",),
    "report": ("id",),
    "report_chunk": ("report_id", "ordinal"),
    "patch": ("slide_id", "x", "y"),
}
_QUERIES: dict[tuple[str, str], str] = {}
for _model in MODELS:
    _QUERIES[(_model, "non_empty_id")] = _non_empty(_model, _TEXT[_model])
    _QUERIES[(_model, "duplicate_natural_key")] = _duplicates(_model, _KEYS[_model])
    _QUERIES[(_model, "valid_specialty")] = "select 0 as n"
    _QUERIES[(_model, "unit_norm")] = "select 0 as n"
    _QUERIES[(_model, "in_corpus")] = "select 0 as n"
    _QUERIES[(_model, "positive_dimension")] = "select 0 as n"

_QUERIES[("pathologist", "valid_specialty")] = (
    "select count(*) as n from "
    f"{_silver('pathologist')} where primary_specialty is null "
    f"or primary_specialty not in {_SPECIALTY_LIST} "
    f"or exists(secondary_specialties, item -> item not in {_SPECIALTY_LIST})"
)
_QUERIES[("concept", "valid_specialty")] = (
    "select count(*) as n from "
    f"{_silver('concept')} where specialty is not null "
    f"and specialty not in {_SPECIALTY_LIST}"
)
for _model in ("path_case", "patch", "report_chunk"):
    _QUERIES[(_model, "valid_specialty")] = (
        "select count(*) as n from "
        f"{_silver(_model)} where specialty is null or specialty not in {_SPECIALTY_LIST}"
    )
_QUERIES[("patch", "unit_norm")] = (
    f"select count(*) as n from {_silver('patch')} where {_norm('embedding', 768, required=True)}"
)
_QUERIES[("report_chunk", "unit_norm")] = (
    "select count(*) as n from "
    f"{_silver('report_chunk')} where {_norm('embedding', 384, required=True)}"
)
_QUERIES[("slide", "unit_norm")] = (
    "select count(*) as n from "
    f"{_silver('slide')} where "
    f"(status = 'ready' and {_norm('embedding', 768, required=True)}) or "
    f"(coalesce(status, '') <> 'ready' and {_norm('embedding', 768, required=False)})"
)
_QUERIES[("concept", "unit_norm")] = (
    "select count(*) as n from "
    f"{_silver('concept')} where {_norm('embedding', 768, required=True)} or ("
    "negative_prompt is not null and length(trim(negative_prompt)) > 0 and "
    f"{_norm('negative_embedding', 768, required=True)})"
)
_QUERIES[("patch", "in_corpus")] = _corpus("patch")
_QUERIES[("report_chunk", "in_corpus")] = _corpus("report_chunk")
_QUERIES[("slide", "positive_dimension")] = (
    "select count(*) as n from "
    f"{_silver('slide')} where coalesce(width, 0) <= 0 or coalesce(height, 0) <= 0 "
    "or coalesce(patch_size, 0) <= 0 or coalesce(magnification, 0) <= 0 "
    "or coalesce(mpp, 0) <= 0 or coalesce(ordinal, 0) < 1"
)
_QUERIES[("patch", "positive_dimension")] = (
    "select count(*) as n from "
    f"{_silver('patch')} where coalesce(size, 0) <= 0 or coalesce(thumb_length, 0) <= 0 "
    "or coalesce(x, -1) < 0 or coalesce(y, -1) < 0"
)

print(f"{'table':<16} {'rule':<24} {'violations':>12}")
violation_total = 0
for _model in MODELS:
    for _rule in RULES:
        _value = _count(_QUERIES[(_model, _rule)])
        violation_total += _value
        print(f"{_model:<16} {_rule:<24} {_value:12d}")
print(f"violation_total {violation_total}")

# COMMAND ----------

for model in MODELS:
    clean = spark.table(f"{catalog}.{schema_name}.silver_{model}").drop(
        "_ingested_at",
        "_source_file",
    )
    (
        clean.write.mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(f"{catalog}.{schema_name}.gold_{model}")
    )
    print(f"gold_{model} {clean.count()}")

# COMMAND ----------

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


def _usage() -> dict[str, dict[str, int]]:
    """Per-case patch, chunk, and ready-slide counts. Embeddings stay in Spark."""
    found: dict[str, dict[str, int]] = {}

    def bucket(case_id: object) -> dict[str, int]:
        key = str(case_id)
        row = found.get(key)
        if row is None:
            row = {
                "patch_in": 0,
                "patch_out": 0,
                "chunk_in": 0,
                "chunk_out": 0,
                "slides_ready": 0,
            }
            found[key] = row
        return row

    patches = spark.sql(
        f"""
        select case_id,
               sum(case when in_corpus then 1 else 0 end) as patch_in,
               sum(case when not in_corpus then 1 else 0 end) as patch_out
        from {catalog}.{schema_name}.gold_patch
        group by case_id
        """
    )
    for row in patches.toLocalIterator():
        item = bucket(row.case_id)
        item["patch_in"] = int(row.patch_in or 0)
        item["patch_out"] = int(row.patch_out or 0)
    chunks = spark.sql(
        f"""
        select case_id,
               sum(case when in_corpus then 1 else 0 end) as chunk_in,
               sum(case when not in_corpus then 1 else 0 end) as chunk_out
        from {catalog}.{schema_name}.gold_report_chunk
        group by case_id
        """
    )
    for row in chunks.toLocalIterator():
        item = bucket(row.case_id)
        item["chunk_in"] = int(row.chunk_in or 0)
        item["chunk_out"] = int(row.chunk_out or 0)
    slides = spark.sql(
        f"""
        select case_id,
               sum(case when status = 'ready' then 1 else 0 end) as slides_ready
        from {catalog}.{schema_name}.gold_slide
        group by case_id
        """
    )
    for row in slides.toLocalIterator():
        bucket(row.case_id)["slides_ready"] = int(row.slides_ready or 0)
    return found


def _subset_frame(model: str):
    frame = spark.table(f"{catalog}.{schema_name}.gold_{model}")
    if model in {"pathologist", "concept"}:
        return frame
    subset_ids = spark.table("subset_case")
    if model == "patient":
        patients = (
            spark.table(f"{catalog}.{schema_name}.gold_path_case")
            .join(subset_ids, "id", "left_semi")
            .select("patient_id")
            .distinct()
        )
        return frame.join(patients, "patient_id", "left_semi")
    if model == "path_case":
        return frame.join(subset_ids, "id", "left_semi")
    return frame.join(subset_ids, frame["case_id"] == subset_ids["id"], "left_semi")


def _defer(reason: str) -> None:
    print(f"lakebase_sync deferred: {reason}")
    print(
        "uv run python -m consilium.pipeline subset "  # pragma: allowlist secret
        f"--from data/export --out data/export_lakebase --max-cases {max_cases}"
    )
    print(
        "SEARCH_BACKEND=pgvector uv run python -m consilium.pipeline "  # pragma: allowlist secret
        "load --from data/export_lakebase"
    )


if not database_url:
    print("lakebase_sync skipped")
elif violation_total:
    print(f"lakebase_sync refused: violation_total {violation_total}")
else:
    case_frame = spark.table(f"{catalog}.{schema_name}.gold_path_case").select(
        "id",
        "patient_id",
        "specialty",
        "status",
        "is_held_out",
        "accessioned_at",
    )
    case_rows = [row.asDict(recursive=True) for row in case_frame.toLocalIterator()]
    chosen = select_case_ids(case_rows, _usage(), max_cases=max_cases)
    print(f"subset_cases {len(chosen['case_ids'])}")
    print(f"estimated_bytes {chosen['estimated_bytes']}")
    print(f"stopped {chosen['stopped']}")
    id_rows = [(str(case_id),) for case_id in chosen["case_ids"]]
    if not id_rows:
        print("lakebase_sync skipped")
    else:
        spark.createDataFrame(id_rows, "id string").createOrReplaceTempView("subset_case")
        for model in MODELS:
            subset_rows = _subset_frame(model)
            destination = f"{volume}/export_lakebase/{model}.parquet"
            subset_rows.write.mode("overwrite").parquet(destination)
            print(f"export_lakebase {model} {subset_rows.count()}")
        patch_rows = 0
        usage = _usage()
        for case_id in chosen["case_ids"]:
            row = usage.get(str(case_id), {})
            patch_rows += int(row.get("patch_in", 0)) + int(row.get("patch_out", 0))
        try:
            import psycopg
        except ImportError:
            psycopg = None
        if psycopg is None or patch_rows > _PATCH_LIMIT:
            why = "psycopg is not installed" if psycopg is None else f"{patch_rows} patches"
            _defer(why)
        else:
            tables: dict[str, list[dict[str, object]]] = {}
            for model in MODELS:
                loaded = spark.read.parquet(f"{volume}/export_lakebase/{model}.parquet")
                tables[model] = [row.asDict(recursive=True) for row in loaded.toLocalIterator()]
            safe_url = _with_ssl(database_url)
            try:
                with psycopg.connect(safe_url) as sync_conn:
                    database_bytes = LakebaseLoader(sync_conn).load(tables)
                print(f"pg_database_size {database_bytes}")
                print("lakebase_sync loaded")
            except Exception as exc:
                print(f"lakebase_sync failed ({type(exc).__name__})")
                raise RuntimeError(f"lakebase_sync failed ({type(exc).__name__})") from None
