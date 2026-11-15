"""Choose a Lakebase subset of the pipeline parquet and write it out.

Lakebase Free Edition stores 512 MB. A local measurement on Postgres 16 with
pgvector 0.8.7 (the extension version on this Lakebase project) put a patch
row at 2,048 bytes of heap and an in-corpus HNSW entry at 2,051 bytes. The
selector adds 25% headroom for longer ids and page waste, keeps a 32 MiB
allowance for the rest of the catalog, and stops adding signed-out cases once
the estimate reaches 320 MiB. That is inside the 250–350 MiB band and leaves
the rest of the 512 MB cap unused.

Every held-out open case is kept, and so is every earlier case of a patient
who is included, so longitudinal history stays intact. Every pathologist and
every concept is copied. Sampling is a deterministic round-robin across
specialties.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from consilium.pipeline.load import PARQUET_FILES, PIPELINE_TABLES  # pragma: allowlist secret

# Measured 14 Nov 2026, 4,000 patch rows, 3,200 of them in_corpus:
#   pg_relation_size(patch) = 8,192,000 bytes (2,048 per row)
#   pg_relation_size(patch_embedding_hnsw) = 6,561,792 bytes (2,051 per in-corpus row)
# Headroom is 25%. Report-chunk vectors are the same 1,536-byte payload.
PATCH_IN_CORPUS_BYTES = 5124
PATCH_OUT_CORPUS_BYTES = 2560
CHUNK_IN_CORPUS_BYTES = 5124
CHUNK_OUT_CORPUS_BYTES = 2560
SLIDE_READY_BYTES = 5124
FIXED_OVERHEAD_BYTES = 32 * 1024 * 1024
BYTE_BUDGET = 320 * 1024 * 1024
LAKEBASE_CAP_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_CASES = 45

# Same order as consilium.pipeline.cohort.SPECIALTY_ORDER.  # pragma: allowlist secret
_SPECIALTIES: tuple[str, ...] = (
    "breast",
    "thorax",
    "colorectal",
    "gastrointestinal",
    "skin",
    "hematologic",
)

_COUNT_KEYS = ("patch_in", "patch_out", "chunk_in", "chunk_out", "slides_ready")


@dataclass(frozen=True)
class SubsetResult:
    """What ``write_subset`` kept, and the size it expects in Postgres."""

    case_ids: tuple[str, ...]
    held_out: int
    priors: int
    sampled: int
    counts: dict[str, int]
    estimated_bytes: int
    stopped: str
    specialties: dict[str, int]
    out_dir: Path

    def summary(self) -> str:
        lines = [
            f"cases {len(self.case_ids)}",
            f"held_out {self.held_out}",
            f"priors {self.priors}",
            f"sampled {self.sampled}",
            f"estimated_bytes {self.estimated_bytes}",
            f"estimated_mebibytes {self.estimated_bytes / (1024 * 1024):.1f}",
            f"byte_budget {BYTE_BUDGET}",
            f"lakebase_cap {LAKEBASE_CAP_BYTES}",
            f"stopped {self.stopped}",
        ]
        lines.extend(f"{table} {self.counts[table]}" for table in PIPELINE_TABLES)
        lines.extend(f"specialty {name} {self.specialties.get(name, 0)}" for name in _SPECIALTIES)
        return "\n".join(lines) + "\n"


def write_subset(
    export_dir: Path,
    out_dir: Path,
    *,
    max_cases: int = DEFAULT_MAX_CASES,
    byte_budget: int = BYTE_BUDGET,
) -> SubsetResult:
    """Write the eight pipeline parquets for one Lakebase subset."""
    source = Path(export_dir)
    destination = Path(out_dir)
    _require_files(source)
    if max_cases < 1:
        raise ValueError("max_cases must be at least 1")
    if byte_budget < 1:
        raise ValueError("byte_budget must be at least 1")

    cases = _case_rows(source / PARQUET_FILES["path_case"])
    counts = _case_counts(source)
    chosen = select_case_ids(cases, counts, max_cases=max_cases, byte_budget=byte_budget)
    case_ids = set(chosen["case_ids"])
    patient_ids = {str(row["patient_id"]) for row in cases if str(row["id"]) in case_ids}

    written: dict[str, int] = {}
    destination.mkdir(parents=True, exist_ok=True)
    for table in PIPELINE_TABLES:
        path = source / PARQUET_FILES[table]
        table_data = pq.read_table(path)
        if table == "pathologist" or table == "concept":
            filtered = table_data
        elif table == "patient":
            filtered = _filter_in(table_data, "id", patient_ids)
        elif table == "path_case":
            filtered = _filter_in(table_data, "id", case_ids)
        else:
            filtered = _filter_in(table_data, "case_id", case_ids)
        _write_atomic(filtered, destination / PARQUET_FILES[table])
        written[table] = int(filtered.num_rows)

    specialties: dict[str, int] = dict.fromkeys(_SPECIALTIES, 0)
    for row in cases:
        if str(row["id"]) not in case_ids:
            continue
        name = str(row.get("specialty") or "")
        if name in specialties:
            specialties[name] += 1
    return SubsetResult(
        case_ids=tuple(chosen["case_ids"]),
        held_out=len(chosen["held_out_ids"]),
        priors=len(chosen["prior_ids"]),
        sampled=len(chosen["sampled_ids"]),
        counts=written,
        estimated_bytes=int(chosen["estimated_bytes"]),
        stopped=str(chosen["stopped"]),
        specialties=specialties,
        out_dir=destination,
    )


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


def _require_files(directory: Path) -> None:
    if not directory.is_dir():
        raise ValueError(f"export directory not found: {directory}")
    missing = [
        name for name in PIPELINE_TABLES if not (directory / PARQUET_FILES[name]).is_file()
    ]
    if missing:
        names = ", ".join(PARQUET_FILES[name] for name in missing)
        raise ValueError(f"export directory is missing parquet files: {names}")


def _case_rows(path: Path) -> list[dict[str, object]]:
    columns = ["id", "patient_id", "specialty", "status", "is_held_out", "accessioned_at"]
    present = set(pq.ParquetFile(path).schema_arrow.names)
    missing = [name for name in columns if name not in present]
    if missing:
        raise ValueError(f"path_case parquet is missing columns: {', '.join(missing)}")
    return pq.read_table(path, columns=columns).to_pylist()


def _case_counts(directory: Path) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}

    def row_for(case_id: object) -> dict[str, int]:
        key = str(case_id)
        found = counts.get(key)
        if found is None:
            found = dict.fromkeys(_COUNT_KEYS, 0)
            counts[key] = found
        return found

    patches = pq.read_table(directory / PARQUET_FILES["patch"], columns=["case_id", "in_corpus"])
    for case_id, flag in zip(
        patches.column("case_id").to_pylist(),
        patches.column("in_corpus").to_pylist(),
        strict=True,
    ):
        row_for(case_id)["patch_in" if flag else "patch_out"] += 1

    chunks = pq.read_table(
        directory / PARQUET_FILES["report_chunk"],
        columns=["case_id", "in_corpus"],
    )
    for case_id, flag in zip(
        chunks.column("case_id").to_pylist(),
        chunks.column("in_corpus").to_pylist(),
        strict=True,
    ):
        row_for(case_id)["chunk_in" if flag else "chunk_out"] += 1

    slide_path = directory / PARQUET_FILES["slide"]
    slide_columns = ["case_id"]
    names = set(pq.ParquetFile(slide_path).schema_arrow.names)
    if "status" in names:
        slide_columns.append("status")
    slides = pq.read_table(slide_path, columns=slide_columns)
    statuses = (
        slides.column("status").to_pylist()
        if "status" in slide_columns
        else [None] * slides.num_rows
    )
    for case_id, status in zip(slides.column("case_id").to_pylist(), statuses, strict=True):
        if status is None or str(status) == "ready":
            row_for(case_id)["slides_ready"] += 1
    return counts


def _filter_in(table: pa.Table, column: str, values: set[str]) -> pa.Table:
    if table.num_rows == 0 or not values:
        return table.slice(0, 0)
    mask = pc.is_in(table.column(column), value_set=pa.array(sorted(values)))
    return table.filter(mask)


def _write_atomic(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    pq.write_table(table, temporary)
    temporary.replace(path)
