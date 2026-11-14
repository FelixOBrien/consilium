"""Stage 8: parquet for ``slide``, ``patch``, and ``concept``.

Column names follow ``docs/models/slide.md``, ``docs/models/patch.md``,
``docs/models/concept.md``, and ``python/sql/migrations/0001_init.sql``.
Intermediate geometry uses different names, and the parquet does not:

| Parquet / SQL | Where the value comes from |
| --- | --- |
| ``slide.width``, ``slide.height`` | header ``width_px``, ``height_px`` |
| ``slide.patch_size``, ``patch.size`` | ``patch_size_level0`` (512 at 20x, 1024 at 40x) |
| ``patch.x``, ``patch.y`` | TRIDENT coords, level-0 pixels |
| ``patch.embedding``, ``slide.embedding`` | float32 unit 768-d; Postgres ``halfvec(768)`` |

``patch.id`` is omitted. In SQL it is ``bigint generated always as identity``.

``patient_id`` and ``in_corpus`` come from ``data/export/path_case.parquet``
when that file exists (stage 7). Otherwise ``patient_id`` is the TCGA
submitter id from ``gdc_cases.parquet`` (or the barcode inside ``case_id``),
and ``in_corpus`` is false exactly for cohort rows marked ``held_out``.
A ready slide row is written only when geometry, a projected vector, and a
thumbnail pack are all present, which is what the ``status = 'ready'`` check
requires. Other slides are counted in the report and left out of the tables.

Concept rows are encoded with the CONCH-Z text tower. An existing
``concept.parquet`` keeps its ids, prompts, and ``created_at``; embeddings
are refreshed from those prompts, and catalog ids that are not yet present
are appended.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from consilium.embed.spaces import CONCHZ_DIM, UNIT_NORM_ATOL  # pragma: allowlist secret
from consilium.embed.text import TextEncoders  # pragma: allowlist secret
from consilium.pipeline.cohort import SPECIALTY_ORDER  # pragma: allowlist secret
from consilium.pipeline.download import (  # pragma: allowlist secret
    _one_line,
    _write_json,
    read_cohort_csv,
)
from consilium.pipeline.project import projected_h5_path, read_projected  # pragma: allowlist secret
from consilium.pipeline.thumbs import (  # pragma: allowlist secret
    index_path,
    pack_path,
    read_thumb_index,
)

VECTOR = pa.list_(pa.float32(), CONCHZ_DIM)

SLIDE_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("case_id", pa.string()),
        ("ordinal", pa.int32()),
        ("stain", pa.string()),
        ("magnification", pa.float32()),
        ("mpp", pa.float32()),
        ("width", pa.int32()),
        ("height", pa.int32()),
        ("patch_size", pa.int32()),
        ("patch_count", pa.int32()),
        ("storage_key", pa.string()),
        ("thumb_pack_key", pa.string()),
        ("source_path", pa.string()),
        ("embedding", VECTOR),
        ("status", pa.string()),
        ("created_at", pa.timestamp("us", tz="UTC")),
    ]
)

PATCH_SCHEMA = pa.schema(
    [
        ("slide_id", pa.string()),
        ("case_id", pa.string()),
        ("patient_id", pa.string()),
        ("specialty", pa.string()),
        ("x", pa.int32()),
        ("y", pa.int32()),
        ("size", pa.int32()),
        ("embedding", VECTOR),
        ("in_corpus", pa.bool_()),
        ("thumb_offset", pa.int64()),
        ("thumb_length", pa.int32()),
        ("created_at", pa.timestamp("us", tz="UTC")),
    ]
)

CONCEPT_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("label", pa.string()),
        ("prompt", pa.string()),
        ("negative_prompt", pa.string()),
        ("specialty", pa.string()),
        ("ordinal", pa.int32()),
        ("embedding", VECTOR),
        ("negative_embedding", VECTOR),
        ("created_at", pa.timestamp("us", tz="UTC")),
    ]
)

_CATALOG_PATH = Path(__file__).with_name("concepts.json")
_SPECIALTIES = frozenset(SPECIALTY_ORDER)


@dataclass(frozen=True)
class CohortExportRow:
    case_id: str
    slide_id: str
    gdc_file_id: str
    file_name: str
    specialty: str
    held_out: bool


@dataclass(frozen=True)
class CaseFacts:
    patient_id: str
    in_corpus: bool
    specialty: str
    source: str


@dataclass(frozen=True)
class ConceptSpec:
    id: str
    label: str
    prompt: str
    negative_prompt: str | None
    specialty: str | None
    ordinal: int


@dataclass(frozen=True)
class ExportResult:
    slides_written: int
    patches_written: int
    concepts_written: int
    failed: int
    slide_path: Path
    patch_path: Path
    concept_path: Path
    report_path: Path
    failures: tuple[tuple[str, str], ...]

    def summary(self) -> str:
        lines = [
            f"slides {self.slides_written}",
            f"patches {self.patches_written}",
            f"concepts {self.concepts_written}",
            f"failed {self.failed}",
            f"wrote {self.slide_path}",
            f"wrote {self.patch_path}",
            f"wrote {self.concept_path}",
            f"wrote {self.report_path}",
        ]
        for slide_id, error in self.failures:
            lines.append(f"failure {slide_id} {_one_line(error)}")
        return "\n".join(lines) + "\n"


def load_concept_catalog(path: Path | None = None) -> tuple[ConceptSpec, ...]:
    """Read the repository concept list. Prompts stay under the 127-token cap."""
    catalog = path if path is not None else _CATALOG_PATH
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"{catalog} does not list any concepts")
    specs: list[ConceptSpec] = []
    seen: set[str] = set()
    ordinals: set[int] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("concept catalog entry is not an object")
        spec = _spec_from_mapping(item)
        if spec.id in seen:
            raise ValueError(f"duplicate concept id {spec.id}")
        if spec.ordinal in ordinals:
            raise ValueError(f"duplicate concept ordinal {spec.ordinal}")
        seen.add(spec.id)
        ordinals.add(spec.ordinal)
        specs.append(spec)
    return tuple(specs)


def export_cohort(
    *,
    cohort_csv: Path,
    data_root: Path,
    text_encoder: TextEncoders | None = None,
    concepts_path: Path | None = None,
    now: datetime | None = None,
) -> ExportResult:
    """Write slide, patch, and concept parquet under ``data_root/export``."""
    rows = _read_export_cohort(cohort_csv)
    stamped = now if now is not None else datetime.now(UTC)
    if stamped.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    export_dir = data_root / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    facts, fact_note = _case_facts(data_root, rows)
    headers = _read_headers(data_root / "trident" / "slide_headers.parquet")
    slide_rows: list[dict[str, object]] = []
    patch_ids: list[str] = []
    patch_cases: list[str] = []
    patch_patients: list[str] = []
    patch_specialties: list[str] = []
    patch_x: list[int] = []
    patch_y: list[int] = []
    patch_size: list[int] = []
    patch_vectors: list[np.ndarray] = []
    patch_corpus: list[bool] = []
    patch_offset: list[int] = []
    patch_length: list[int] = []
    failures: list[tuple[str, str]] = []
    order = {name: index for index, name in enumerate(SPECIALTY_ORDER)}
    for row in sorted(rows, key=lambda item: (order.get(item.specialty, 99), item.slide_id)):
        try:
            slide, patches = _slide_and_patches(row, data_root, headers, facts, stamped)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            failures.append((row.slide_id, str(exc)))
            continue
        slide_rows.append(slide)
        for patch in patches:
            patch_ids.append(str(patch["slide_id"]))
            patch_cases.append(str(patch["case_id"]))
            patch_patients.append(str(patch["patient_id"]))
            patch_specialties.append(str(patch["specialty"]))
            patch_x.append(int(patch["x"]))
            patch_y.append(int(patch["y"]))
            patch_size.append(int(patch["size"]))
            patch_vectors.append(np.asarray(patch["embedding"], dtype=np.float32))
            patch_corpus.append(bool(patch["in_corpus"]))
            patch_offset.append(int(patch["thumb_offset"]))
            patch_length.append(int(patch["thumb_length"]))
    slide_path = export_dir / "slide.parquet"
    patch_path = export_dir / "patch.parquet"
    concept_path = export_dir / "concept.parquet"
    _write_table(slide_path, _slide_table(slide_rows))
    _write_table(patch_path, _patch_table(
        patch_ids,
        patch_cases,
        patch_patients,
        patch_specialties,
        patch_x,
        patch_y,
        patch_size,
        patch_vectors,
        patch_corpus,
        patch_offset,
        patch_length,
        stamped,
    ))
    encoder = text_encoder if text_encoder is not None else _default_encoder()
    concepts_written = _write_concepts(
        concept_path,
        load_concept_catalog(concepts_path),
        encoder,
        stamped,
    )
    report_path = export_dir / "export_report.json"
    result = ExportResult(
        slides_written=len(slide_rows),
        patches_written=len(patch_ids),
        concepts_written=concepts_written,
        failed=len(failures),
        slide_path=slide_path,
        patch_path=patch_path,
        concept_path=concept_path,
        report_path=report_path,
        failures=tuple(failures),
    )
    _write_json(
        report_path,
        {
            "stage": "export",
            "case_facts": fact_note,
            "slides": result.slides_written,
            "patches": result.patches_written,
            "concepts": result.concepts_written,
            "failed": result.failed,
            "failures": [{"slide_id": slide_id, "error": error} for slide_id, error in failures],
            "column_notes": {
                "width": "slide_headers.width_px, SQL slide.width",
                "height": "slide_headers.height_px, SQL slide.height",
                "x": "level-0 coord, SQL patch.x",
                "y": "level-0 coord, SQL patch.y",
                "size": "patch_size_level0, SQL patch.size",
                "patch_size": "patch_size_level0, SQL slide.patch_size",
                "embedding": "float32 unit-norm 768-d; Postgres halfvec(768)",
                "patch.id": "omitted; bigint generated always as identity",
            },
        },
    )
    return result


def _slide_and_patches(
    row: CohortExportRow,
    data_root: Path,
    headers: Mapping[str, Mapping[str, object]],
    facts: Mapping[str, CaseFacts],
    stamped: datetime,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    header = headers.get(row.slide_id)
    if header is None:
        raise ValueError("slide header is missing")
    if header.get("error"):
        raise ValueError(str(header["error"]))
    fact = facts.get(row.case_id)
    if fact is None:
        raise ValueError("patient_id is missing for this case")
    if fact.specialty != row.specialty:
        raise ValueError(
            f"specialty {fact.specialty} does not match the cohort specialty {row.specialty}"
        )
    projected_path = projected_h5_path(data_root / "trident", row.slide_id)
    if not projected_path.is_file():
        raise ValueError("projected features are missing")
    projected = read_projected(projected_path)
    thumb_file = index_path(data_root, row.slide_id)
    pack = pack_path(data_root, row.slide_id)
    if not thumb_file.is_file() or not pack.is_file():
        raise ValueError("thumbnail pack is missing")
    index = read_thumb_index(thumb_file)
    if len(index.patches) != projected.features.shape[0]:
        raise ValueError("thumbnail count does not match projected patches")
    width = _required_int(header, "width_px", "width")
    height = _required_int(header, "height_px", "height")
    level0 = projected.patch_size_level0
    if level0 is None:
        level0 = _optional_int(header.get("patch_size_level0"))
    header_level0 = _optional_int(header.get("patch_size_level0"))
    if level0 is None or level0 < 1:
        raise ValueError("patch_size_level0 is missing")
    if header_level0 is not None and header_level0 != level0:
        raise ValueError("header patch_size_level0 does not match projected coords")
    if index.patch_size_level0 != level0:
        raise ValueError("thumbnail patch size does not match projected coords")
    magnification = _required_float(header, "magnification")
    mpp = _required_float(header, "mpp")
    ordinal = _ordinal(row.slide_id, row.case_id)
    _assert_unit(projected.slide_embedding, "slide")
    patches: list[dict[str, object]] = []
    for vector, xy, thumb in zip(
        projected.features, projected.coords, index.patches, strict=True
    ):
        x = int(xy[0])
        y = int(xy[1])
        if thumb.x != x or thumb.y != y:
            raise ValueError(f"thumbnail index ({thumb.x}, {thumb.y}) != coords ({x}, {y})")
        _assert_unit(vector, "patch")
        patches.append(
            {
                "slide_id": row.slide_id,
                "case_id": row.case_id,
                "patient_id": fact.patient_id,
                "specialty": row.specialty,
                "x": x,
                "y": y,
                "size": level0,
                "embedding": np.asarray(vector, dtype=np.float32),
                "in_corpus": fact.in_corpus,
                "thumb_offset": thumb.thumb_offset,
                "thumb_length": thumb.thumb_length,
            }
        )
    slide = {
        "id": row.slide_id,
        "case_id": row.case_id,
        "ordinal": ordinal,
        "stain": "HE",
        "magnification": magnification,
        "mpp": mpp,
        "width": width,
        "height": height,
        "patch_size": level0,
        "patch_count": len(patches),
        "storage_key": f"slides/{row.slide_id}.svs",
        "thumb_pack_key": f"thumbs/{row.slide_id}.pack",
        "source_path": f"{row.gdc_file_id}/{row.file_name}",
        "embedding": np.asarray(projected.slide_embedding, dtype=np.float32),
        "status": "ready",
        "created_at": stamped,
    }
    return slide, patches


def _case_facts(
    data_root: Path,
    rows: Sequence[CohortExportRow],
) -> tuple[dict[str, CaseFacts], str]:
    path_case = data_root / "export" / "path_case.parquet"
    gdc = _gdc_donors(data_root / "source" / "gdc_cases.parquet")
    by_case = {row.case_id: row for row in rows}
    facts: dict[str, CaseFacts] = {}
    if path_case.is_file():
        for case_id, fact in _facts_from_path_case(path_case).items():
            facts[case_id] = fact
        note = "path_case.parquet"
    else:
        note = "cohort.csv+gdc_cases.parquet"
    for case_id, row in by_case.items():
        if case_id in facts:
            fact = facts[case_id]
            specialty = fact.specialty or row.specialty
            facts[case_id] = CaseFacts(
                patient_id=fact.patient_id,
                in_corpus=fact.in_corpus,
                specialty=specialty,
                source=fact.source,
            )
            continue
        donor = gdc.get(case_id) or _donor_barcode(case_id, row.specialty)
        facts[case_id] = CaseFacts(
            patient_id=donor,
            in_corpus=not row.held_out,
            specialty=row.specialty,
            source="cohort",
        )
    return facts, note


def _facts_from_path_case(path: Path) -> dict[str, CaseFacts]:
    table = pq.read_table(path)
    names = set(table.column_names)
    key = "id" if "id" in names else "case_id" if "case_id" in names else ""
    if key == "" or "patient_id" not in names:
        raise ValueError("path_case.parquet needs id (or case_id) and patient_id")
    facts: dict[str, CaseFacts] = {}
    for row in table.to_pylist():
        case_id = str(row[key] or "").strip()
        patient_id = str(row.get("patient_id") or "").strip()
        if case_id == "" or patient_id == "":
            raise ValueError("path_case.parquet has a row without id or patient_id")
        specialty = row.get("specialty")
        specialty_text = str(specialty).strip() if specialty else ""
        if specialty_text and specialty_text not in _SPECIALTIES:
            raise ValueError(f"path_case specialty {specialty_text!r} is unknown")
        facts[case_id] = CaseFacts(
            patient_id=patient_id,
            in_corpus=_in_corpus(row),
            specialty=specialty_text,
            source="path_case",
        )
    return facts


def _in_corpus(row: Mapping[str, object]) -> bool:
    status = row.get("status")
    held = row.get("is_held_out")
    if status is not None and str(status).strip() != "":
        signed = str(status) == "signed_out"
        return signed and not _flag(held)
    if held is not None:
        return not _flag(held)
    if "in_corpus" in row and row.get("in_corpus") is not None:
        return _flag(row.get("in_corpus"))
    raise ValueError("path_case row has no status, is_held_out, or in_corpus")


def _gdc_donors(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    table = pq.read_table(path, columns=["case_id", "submitter_id"])
    donors: dict[str, str] = {}
    for row in table.to_pylist():
        case_id = str(row.get("case_id") or "").strip()
        submitter = str(row.get("submitter_id") or "").strip()
        if case_id and submitter:
            donors[case_id] = submitter
    return donors


def _donor_barcode(case_id: str, specialty: str) -> str:
    prefix = f"{specialty}-"
    if case_id.startswith(prefix) and case_id[len(prefix) :]:
        return case_id[len(prefix) :]
    return case_id


def _read_headers(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    table = pq.read_table(path)
    headers: dict[str, dict[str, object]] = {}
    for row in table.to_pylist():
        slide_id = str(row.get("slide_id") or "")
        if slide_id:
            headers[slide_id] = row
    return headers


def _read_export_cohort(path: Path) -> list[CohortExportRow]:
    # Confirms the file exists and the ids are safe. Extra columns are read below.
    read_cohort_csv(path)
    rows: list[CohortExportRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or ()
        missing = [
            name
            for name in ("case_id", "slide_id", "gdc_file_id", "file_name", "specialty", "held_out")
            if name not in fieldnames
        ]
        if missing:
            raise ValueError(f"cohort file missing columns: {', '.join(missing)}")
        for line_no, raw in enumerate(reader, start=2):
            specialty = (raw.get("specialty") or "").strip()
            if specialty not in _SPECIALTIES:
                raise ValueError(f"cohort row {line_no} has unknown specialty {specialty!r}")
            held_text = (raw.get("held_out") or "").strip().lower()
            if held_text not in {"true", "false"}:
                raise ValueError(f"cohort row {line_no} has held_out {held_text!r}")
            case_id = (raw.get("case_id") or "").strip()
            file_name = (raw.get("file_name") or "").strip()
            if case_id == "" or file_name == "":
                raise ValueError(f"cohort row {line_no} is missing case_id or file_name")
            rows.append(
                CohortExportRow(
                    case_id=case_id,
                    slide_id=(raw.get("slide_id") or "").strip(),
                    gdc_file_id=(raw.get("gdc_file_id") or "").strip(),
                    file_name=file_name,
                    specialty=specialty,
                    held_out=held_text == "true",
                )
            )
    return rows


def _write_concepts(
    path: Path,
    catalog: Sequence[ConceptSpec],
    encoder: TextEncoders,
    stamped: datetime,
) -> int:
    existing = _read_existing_concepts(path) if path.is_file() else []
    merged = _merge_concepts(existing, catalog, stamped)
    prompts = [row["prompt"] for row in merged]
    negatives = [row["negative_prompt"] for row in merged if row["negative_prompt"]]
    encoded = encoder.encode_image_texts([str(item) for item in prompts])
    if len(encoded) != len(merged):
        raise ValueError("concept encoder returned a different number of vectors")
    negative_vectors: dict[str, np.ndarray] = {}
    if negatives:
        negative_encoded = encoder.encode_image_texts([str(item) for item in negatives])
        if len(negative_encoded) != len(negatives):
            raise ValueError("concept encoder dropped a negative prompt")
        for prompt, item in zip(negatives, negative_encoded, strict=True):
            if item.truncated:
                raise ValueError(f"negative prompt exceeds the CONCH-Z token limit: {prompt}")
            negative_vectors[str(prompt)] = np.asarray(item.vector.values, dtype=np.float32)
    embeddings: list[np.ndarray] = []
    negative_column: list[np.ndarray | None] = []
    for row, item in zip(merged, encoded, strict=True):
        if item.truncated:
            raise ValueError(f"concept prompt exceeds the CONCH-Z token limit: {row['prompt']}")
        vector = np.asarray(item.vector.values, dtype=np.float32)
        _assert_unit(vector, "concept")
        embeddings.append(vector)
        negative = row["negative_prompt"]
        if negative:
            negative_vector = negative_vectors[str(negative)]
            _assert_unit(negative_vector, "concept negative")
            negative_column.append(negative_vector)
        else:
            negative_column.append(None)
    table = pa.table(
        {
            "id": pa.array([row["id"] for row in merged], type=pa.string()),
            "label": pa.array([row["label"] for row in merged], type=pa.string()),
            "prompt": pa.array([row["prompt"] for row in merged], type=pa.string()),
            "negative_prompt": pa.array(
                [row["negative_prompt"] for row in merged], type=pa.string()
            ),
            "specialty": pa.array([row["specialty"] for row in merged], type=pa.string()),
            "ordinal": pa.array([row["ordinal"] for row in merged], type=pa.int32()),
            "embedding": _vector_array(embeddings),
            "negative_embedding": _optional_vector_array(negative_column),
            "created_at": pa.array(
                [row["created_at"] for row in merged],
                type=CONCEPT_SCHEMA.field("created_at").type,
            ),
        },
        schema=CONCEPT_SCHEMA,
    )
    _write_table(path, table)
    return len(merged)


def _merge_concepts(
    existing: Sequence[Mapping[str, object]],
    catalog: Sequence[ConceptSpec],
    stamped: datetime,
) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in existing:
        concept_id = str(row["id"])
        seen.add(concept_id)
        created = row.get("created_at")
        if not isinstance(created, datetime):
            created = stamped
        merged.append(
            {
                "id": concept_id,
                "label": str(row["label"]),
                "prompt": str(row["prompt"]),
                "negative_prompt": row.get("negative_prompt") or None,
                "specialty": row.get("specialty") or None,
                "ordinal": int(row["ordinal"]),
                "created_at": created,
            }
        )
    for spec in catalog:
        if spec.id in seen:
            continue
        merged.append(
            {
                "id": spec.id,
                "label": spec.label,
                "prompt": spec.prompt,
                "negative_prompt": spec.negative_prompt,
                "specialty": spec.specialty,
                "ordinal": spec.ordinal,
                "created_at": stamped,
            }
        )
    return merged


def _read_existing_concepts(path: Path) -> list[dict[str, object]]:
    table = pq.read_table(path)
    names = set(table.column_names)
    required = {"id", "label", "prompt", "ordinal"}
    missing = required - names
    if missing:
        raise ValueError(f"concept.parquet is missing columns: {', '.join(sorted(missing))}")
    rows: list[dict[str, object]] = []
    for row in table.to_pylist():
        concept_id = str(row.get("id") or "").strip()
        prompt = str(row.get("prompt") or "").strip()
        label = str(row.get("label") or "").strip()
        if concept_id == "" or prompt == "" or label == "":
            raise ValueError("concept.parquet has a row without id, label, or prompt")
        negative = row.get("negative_prompt")
        specialty = row.get("specialty")
        rows.append(
            {
                "id": concept_id,
                "label": label,
                "prompt": prompt,
                "negative_prompt": str(negative).strip() if negative else None,
                "specialty": str(specialty).strip() if specialty else None,
                "ordinal": int(row["ordinal"]),
                "created_at": row.get("created_at"),
            }
        )
    return rows


def _slide_table(rows: Sequence[Mapping[str, object]]) -> pa.Table:
    if not rows:
        empty = {field.name: pa.array([], type=field.type) for field in SLIDE_SCHEMA}
        return pa.table(empty, schema=SLIDE_SCHEMA)
    return pa.table(
        {
            "id": pa.array([row["id"] for row in rows], type=pa.string()),
            "case_id": pa.array([row["case_id"] for row in rows], type=pa.string()),
            "ordinal": pa.array([row["ordinal"] for row in rows], type=pa.int32()),
            "stain": pa.array([row["stain"] for row in rows], type=pa.string()),
            "magnification": pa.array([row["magnification"] for row in rows], type=pa.float32()),
            "mpp": pa.array([row["mpp"] for row in rows], type=pa.float32()),
            "width": pa.array([row["width"] for row in rows], type=pa.int32()),
            "height": pa.array([row["height"] for row in rows], type=pa.int32()),
            "patch_size": pa.array([row["patch_size"] for row in rows], type=pa.int32()),
            "patch_count": pa.array([row["patch_count"] for row in rows], type=pa.int32()),
            "storage_key": pa.array([row["storage_key"] for row in rows], type=pa.string()),
            "thumb_pack_key": pa.array([row["thumb_pack_key"] for row in rows], type=pa.string()),
            "source_path": pa.array([row["source_path"] for row in rows], type=pa.string()),
            "embedding": _vector_array([np.asarray(row["embedding"]) for row in rows]),
            "status": pa.array([row["status"] for row in rows], type=pa.string()),
            "created_at": pa.array(
                [row["created_at"] for row in rows],
                type=SLIDE_SCHEMA.field("created_at").type,
            ),
        },
        schema=SLIDE_SCHEMA,
    )


def _patch_table(
    slide_ids: Sequence[str],
    case_ids: Sequence[str],
    patient_ids: Sequence[str],
    specialties: Sequence[str],
    xs: Sequence[int],
    ys: Sequence[int],
    sizes: Sequence[int],
    vectors: Sequence[np.ndarray],
    corpus: Sequence[bool],
    offsets: Sequence[int],
    lengths: Sequence[int],
    stamped: datetime,
) -> pa.Table:
    count = len(slide_ids)
    created = pa.array([stamped] * count, type=PATCH_SCHEMA.field("created_at").type)
    return pa.table(
        {
            "slide_id": pa.array(list(slide_ids), type=pa.string()),
            "case_id": pa.array(list(case_ids), type=pa.string()),
            "patient_id": pa.array(list(patient_ids), type=pa.string()),
            "specialty": pa.array(list(specialties), type=pa.string()),
            "x": pa.array(list(xs), type=pa.int32()),
            "y": pa.array(list(ys), type=pa.int32()),
            "size": pa.array(list(sizes), type=pa.int32()),
            "embedding": _vector_array(vectors),
            "in_corpus": pa.array(list(corpus), type=pa.bool_()),
            "thumb_offset": pa.array(list(offsets), type=pa.int64()),
            "thumb_length": pa.array(list(lengths), type=pa.int32()),
            "created_at": created,
        },
        schema=PATCH_SCHEMA,
    )


def _vector_array(rows: Sequence[np.ndarray]) -> pa.Array:
    if not rows:
        return pa.array([], type=VECTOR)
    stacked = np.stack([np.asarray(row, dtype=np.float32).reshape(CONCHZ_DIM) for row in rows])
    flat = np.ascontiguousarray(stacked, dtype=np.float32).reshape(-1)
    values = pa.array(flat, type=pa.float32())
    return pa.FixedSizeListArray.from_arrays(values, CONCHZ_DIM)


def _optional_vector_array(rows: Sequence[np.ndarray | None]) -> pa.Array:
    if not rows:
        return pa.array([], type=VECTOR)
    values: list[list[float] | None] = []
    for row in rows:
        if row is None:
            values.append(None)
        else:
            values.append(np.asarray(row, dtype=np.float32).reshape(CONCHZ_DIM).tolist())
    return pa.array(values, type=VECTOR)


def _write_table(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    pq.write_table(table, temporary)
    temporary.replace(path)


def _spec_from_mapping(item: Mapping[str, object]) -> ConceptSpec:
    concept_id = str(item.get("id") or "").strip()
    label = str(item.get("label") or "").strip()
    prompt = str(item.get("prompt") or "").strip()
    if concept_id == "" or label == "" or prompt == "":
        raise ValueError("concept catalog entry needs id, label, and prompt")
    if any(char.isspace() for char in concept_id) or "/" in concept_id:
        raise ValueError(f"concept id {concept_id!r} is not a slug")
    negative_raw = item.get("negative_prompt")
    negative = str(negative_raw).strip() if negative_raw else None
    specialty_raw = item.get("specialty")
    specialty = str(specialty_raw).strip() if specialty_raw else None
    if specialty is not None and specialty not in _SPECIALTIES:
        raise ValueError(f"concept specialty {specialty!r} is unknown")
    try:
        ordinal = int(item["ordinal"])  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"concept {concept_id} has no ordinal") from exc
    if len(prompt.split()) > 80 or (negative is not None and len(negative.split()) > 80):
        raise ValueError(f"concept {concept_id} prompt is too long for a 127-token encoder")
    return ConceptSpec(
        id=concept_id,
        label=label,
        prompt=prompt,
        negative_prompt=negative or None,
        specialty=specialty,
        ordinal=ordinal,
    )


def _assert_unit(vector: np.ndarray, label: str) -> None:
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    if array.shape != (CONCHZ_DIM,) or not np.isfinite(array).all():
        raise ValueError(f"{label} vector is not a finite 768-d embedding")
    norm = float(np.linalg.norm(array))
    if abs(norm - 1.0) > UNIT_NORM_ATOL:
        raise ValueError(f"{label} vector is not unit-norm (norm {norm:.6f})")


def _ordinal(slide_id: str, case_id: str) -> int:
    prefix = f"{case_id}-s"
    if not slide_id.startswith(prefix):
        raise ValueError(f"slide id {slide_id} does not start with {prefix}")
    try:
        ordinal = int(slide_id[len(prefix) :])
    except ValueError as exc:
        raise ValueError(f"slide id {slide_id} has no ordinal") from exc
    if ordinal < 1:
        raise ValueError(f"slide ordinal {ordinal} is not positive")
    return ordinal


def _required_int(header: Mapping[str, object], key: str, label: str) -> int:
    value = _optional_int(header.get(key))
    if value is None or value <= 0:
        raise ValueError(f"header {label} is missing")
    return value


def _required_float(header: Mapping[str, object], key: str) -> float:
    raw = header.get(key)
    if raw is None:
        raise ValueError(f"header {key} is missing")
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"header {key} is not a number") from exc
    if value <= 0:
        raise ValueError(f"header {key} must be positive")
    return value


def _optional_int(raw: object) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "t", "yes"}


def _default_encoder() -> TextEncoders:
    from consilium.embed.text import build_text_encoders  # pragma: allowlist secret

    return build_text_encoders()
