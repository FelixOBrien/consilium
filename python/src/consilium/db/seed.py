"""Idempotent synthetic fixture load.

`db seed` loads these rows. Two pyramidal TIFFs and their thumbnail packs are written
under the storage root (default `data/`) and are never committed.

Running seed again deletes the fixture keys and inserts the same rows, so counts
stay the same. Vectors are deterministic unit vectors, not model outputs.
"""

from __future__ import annotations

import hashlib
import io
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import numpy as np
import tifffile
from pgvector import HalfVector, Vector
from PIL import Image
from psycopg import Connection, Error
from psycopg.types.json import Jsonb

from consilium.config import get_settings  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.seed_data import (  # pragma: allowlist secret
    CASES,
    CONCEPTS,
    DEMO_USER_ID,
    FIXTURE_CREATED,
    MAGNIFICATION,
    MPP,
    PATCH_SIZE,
    PATIENTS,
    ROSTER,
    SECTION_HEADING,
    SECTION_ORDER,
    SLIDE_ASSETS,
    CaseSeed,
    ConceptSeed,
    SlideAsset,
    report_sections,
    slide_asset,
    validate_seed_data,
)

STORED_TABLES = (
    "pathologist",
    "patient",
    "path_case",
    "slide",
    "report",
    "report_chunk",
    "patch",
    "concept",
    "annotation",
    "consult_thread",
    "consult_message",
    "ingestion_job",
)

CONCHZ_DIM = 768
REPORT_DIM = 384
WORD_LIMIT = 200
SIGN_OUT_LAG = timedelta(days=3)

THREAD_ID = UUID("00000000-0000-4000-8000-0000000000a1")
USER_MESSAGE_ID = UUID("00000000-0000-4000-8000-0000000000a2")
ASSISTANT_MESSAGE_ID = UUID("00000000-0000-4000-8000-0000000000a3")
ANNOTATION_RECT_ID = UUID("00000000-0000-4000-8000-000000000001")
ANNOTATION_POINT_ID = UUID("00000000-0000-4000-8000-000000000002")
JOB_DONE_ID = UUID("00000000-0000-4000-8000-0000000000b1")
JOB_FAILED_ID = UUID("00000000-0000-4000-8000-0000000000b2")
JOB_QUEUED_ID = UUID("00000000-0000-4000-8000-0000000000b3")

_OPEN_CASE_ID = "breast-FX-B042C"
_PRIOR_CASE_IDS = ("breast-FX-B042A", "breast-FX-B042B")
_ANNOTATED_CASE_ID = "breast-FX-B042A"

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def seed(
    database_url: str | None = None,
    storage_root: Path | str | None = None,
) -> dict[str, int]:
    """Load fixture rows and generated slide files. Safe to run more than once."""
    validate_seed_data()
    settings = get_settings()
    url = database_url if database_url is not None else settings.database_url
    root = Path(storage_root) if storage_root is not None else Path(settings.storage_root)
    images = _write_slide_files(root)
    prepared = _prepare(images, root)
    conn = connect(url)
    try:
        with conn.transaction():
            _delete_fixture(conn)
            _insert(conn, prepared)
        return _counts(conn)
    finally:
        conn.close()


def run_seed_command() -> int:
    """CLI handler. Prints one `table count` line per stored table."""
    try:
        counts = seed()
    except (OSError, Error, RuntimeError, ValueError) as exc:
        print(_public_error(exc), file=sys.stderr)
        return 1
    for table in STORED_TABLES:
        print(f"{table} {counts[table]}")
    return 0


def compose_body(sections: Mapping[str, str]) -> str:
    """Join extracted sections into `report.body`. Headings are part of the text."""
    return "\n\n".join(
        f"{SECTION_HEADING[key]}:\n{sections[key].strip()}" for key in SECTION_ORDER
    )


def split_span(text: str, *, word_limit: int = WORD_LIMIT) -> list[str]:
    """Split a long span on sentence boundaries, overlapping by one sentence.

    Spans at or under the limit are returned unchanged. A span with no sentence
    boundary is split on words without overlap, because there is no sentence to repeat.
    """
    stripped = text.strip()
    if len(stripped.split()) <= word_limit:
        return [stripped]
    sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(stripped) if part.strip()]
    if len(sentences) <= 1:
        words = stripped.split()
        pieces: list[str] = []
        start = 0
        while start < len(words):
            end = min(start + word_limit, len(words))
            pieces.append(" ".join(words[start:end]))
            if end >= len(words):
                break
            start = end
        return pieces

    pieces = []
    index = 0
    while index < len(sentences):
        taken: list[str] = []
        words = 0
        cursor = index
        while cursor < len(sentences):
            count = len(sentences[cursor].split())
            if taken and words + count > word_limit:
                break
            taken.append(sentences[cursor])
            words += count
            cursor += 1
        pieces.append(" ".join(taken))
        if cursor >= len(sentences):
            break
        index = cursor - 1 if len(taken) > 1 else cursor
    return pieces


def chunk_report(body: str, *, word_limit: int = WORD_LIMIT) -> list[tuple[str, str]]:
    """Partition `body` into `(section, text)` chunks. Every fixture word is indexed once.

    Long sections are the exception: `split_span` repeats one sentence at the boundary.
    """
    heading_to_section = {heading: key for key, heading in SECTION_HEADING.items()}
    chunks: list[tuple[str, str]] = []
    for block in body.split("\n\n"):
        heading, separator, _rest = block.partition(":\n")
        if not separator or heading not in heading_to_section:
            raise ValueError(f"report block has no known heading: {block[:40]!r}")
        section = heading_to_section[heading]
        chunks.extend((section, piece) for piece in split_span(block, word_limit=word_limit))
    if not chunks:
        raise ValueError("report produced no chunks")
    return chunks


def patch_origins(width: int, height: int, size: int = PATCH_SIZE) -> list[tuple[int, int]]:
    """Non-overlapping grid. Origins are multiples of `size` from (0, 0)."""
    return [
        (x, y)
        for y in range(0, height - size + 1, size)
        for x in range(0, width - size + 1, size)
    ]


def unit_vector(key: str, dim: int, *, half: bool) -> list[float]:
    """Deterministic L2-normalised vector. `half` matches `halfvec` storage."""
    digest = hashlib.sha256(key.encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:4], "little"))
    current = rng.standard_normal(dim)
    norm = np.linalg.norm(current)
    current = current / norm
    if half:
        for _ in range(4):
            current = current.astype(np.float16).astype(np.float64)
            current = current / np.linalg.norm(current)
        current = current.astype(np.float16).astype(np.float64)
    else:
        current = current.astype(np.float32).astype(np.float64)
        current = current / np.linalg.norm(current)
    return [float(value) for value in current]


class _Prepared:
    def __init__(self) -> None:
        self.slides: list[tuple[object, ...]] = []
        self.patches: list[tuple[object, ...]] = []
        self.reports: list[tuple[object, ...]] = []
        self.chunks: list[tuple[object, ...]] = []
        self.patch_count_for_case: dict[str, int] = {}
        self.chunk_count_for_case: dict[str, int] = {}


def _prepare(images: dict[str, np.ndarray], root: Path) -> _Prepared:
    prepared = _Prepared()
    for case in CASES:
        asset = slide_asset(case.slide_key)
        image = images[asset.key]
        slide_id = f"{case.id}-s1"
        report_id = f"{case.id}-r1"
        in_corpus = case.status == "signed_out" and not case.is_held_out
        origins = patch_origins(asset.width, asset.height, PATCH_SIZE)
        pack_key = f"thumbs/{slide_id}.pack"
        patches, embeddings = _write_pack(root, pack_key, image, origins, slide_id, case, in_corpus)
        prepared.patches.extend(patches)
        prepared.patch_count_for_case[case.id] = len(patches)
        prepared.slides.append(
            (
                slide_id,
                case.id,
                1,
                "HE",
                MAGNIFICATION,
                MPP,
                asset.width,
                asset.height,
                PATCH_SIZE,
                len(patches),
                asset.storage_key,
                pack_key,
                f"fixture/{Path(asset.storage_key).name}",
                HalfVector(_mean_unit(embeddings)),
                "ready",
                FIXTURE_CREATED,
            )
        )
        sections = report_sections(case)
        body = compose_body(sections)
        chunks = chunk_report(body)
        status = "signed" if case.status == "signed_out" else "withheld"
        signed_at = case.accessioned_at + SIGN_OUT_LAG if status == "signed" else None
        prepared.reports.append(
            (
                report_id,
                case.id,
                case.assigned_to,
                status,
                body,
                sections["clinical_history"],
                sections["gross_description"],
                sections["microscopic_description"],
                sections["conclusion"],
                sections["additional_info"],
                case.icd10,
                signed_at,
                FIXTURE_CREATED,
            )
        )
        for ordinal, (section, text) in enumerate(chunks):
            prepared.chunks.append(
                (
                    report_id,
                    case.id,
                    case.patient_id,
                    case.specialty,
                    section,
                    ordinal,
                    text,
                    Vector(unit_vector(f"chunk:{report_id}:{ordinal}", REPORT_DIM, half=False)),
                    in_corpus,
                    FIXTURE_CREATED,
                )
            )
        prepared.chunk_count_for_case[case.id] = len(chunks)
    return prepared


def _write_slide_files(root: Path) -> dict[str, np.ndarray]:
    images: dict[str, np.ndarray] = {}
    for asset in SLIDE_ASSETS:
        image = _synthetic_image(asset)
        _write_tiff(_under(root, asset.storage_key), image)
        images[asset.key] = image
    return images


def _synthetic_image(asset: SlideAsset) -> np.ndarray:
    height, width = asset.height, asset.width
    y = np.arange(height, dtype=np.int32)[:, None]
    x = np.arange(width, dtype=np.int32)[None, :]
    image = np.empty((height, width, 3), dtype=np.uint8)
    salt = asset.salt * 17
    image[..., 0] = np.asarray((170 + salt + (x // 64) * 3) % 220, dtype=np.uint8)
    image[..., 1] = np.asarray((110 + (y // 64) * 5) % 200, dtype=np.uint8)
    image[..., 2] = np.asarray((140 + ((x + y) // 128) + salt) % 210, dtype=np.uint8)
    radius = min(width, height) // 5
    mask = (y - height // 3) ** 2 + (x - width // 3) ** 2 < radius**2
    image[mask] = (90, 50, 70)
    return image


def _write_tiff(path: Path, image: np.ndarray) -> None:
    levels = [image]
    current = image
    while min(int(current.shape[0]), int(current.shape[1])) // 2 >= 256:
        current = np.ascontiguousarray(current[::2, ::2])
        levels.append(current)
    if len(levels) < 2:
        raise RuntimeError(f"{path.name} needs at least two resolutions")
    buffer = io.BytesIO()
    with tifffile.TiffWriter(buffer) as tif:
        tif.write(
            levels[0],
            photometric="rgb",
            tile=(256, 256),
            compression="adobe_deflate",
            metadata=None,
        )
        for level in levels[1:]:
            tif.write(
                level,
                photometric="rgb",
                tile=(256, 256),
                compression="adobe_deflate",
                subfiletype=1,
                metadata=None,
            )
    _write_bytes(path, buffer.getvalue())


def _write_pack(
    root: Path,
    pack_key: str,
    image: np.ndarray,
    origins: Sequence[tuple[int, int]],
    slide_id: str,
    case: CaseSeed,
    in_corpus: bool,
) -> tuple[list[tuple[object, ...]], list[list[float]]]:
    parts: list[bytes] = []
    rows: list[tuple[object, ...]] = []
    embeddings: list[list[float]] = []
    cursor = 0
    for x, y in origins:
        crop = np.ascontiguousarray(image[y : y + PATCH_SIZE, x : x + PATCH_SIZE])
        blob = _jpeg(crop)
        embedding = unit_vector(f"patch:{slide_id}:{x}:{y}", CONCHZ_DIM, half=True)
        embeddings.append(embedding)
        rows.append(
            (
                slide_id,
                case.id,
                case.patient_id,
                case.specialty,
                x,
                y,
                PATCH_SIZE,
                HalfVector(embedding),
                in_corpus,
                cursor,
                len(blob),
                FIXTURE_CREATED,
            )
        )
        parts.append(blob)
        cursor += len(blob)
    _write_bytes(_under(root, pack_key), b"".join(parts))
    return rows, embeddings


def _jpeg(rgb: np.ndarray) -> bytes:
    thumb = Image.fromarray(rgb, mode="RGB").resize((128, 128), Image.Resampling.BILINEAR)
    buffer = io.BytesIO()
    thumb.save(buffer, format="JPEG", quality=80)
    payload = buffer.getvalue()
    if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
        raise RuntimeError("thumbnail encoder did not write a JPEG")
    return payload


def _mean_unit(vectors: Sequence[Sequence[float]]) -> list[float]:
    mean = np.asarray(vectors, dtype=np.float64).mean(axis=0)
    mean = mean / np.linalg.norm(mean)
    for _ in range(4):
        mean = mean.astype(np.float16).astype(np.float64)
        mean = mean / np.linalg.norm(mean)
    stored = mean.astype(np.float16).astype(np.float64)
    return [float(value) for value in stored]


def _delete_fixture(conn: Connection) -> None:
    case_ids = [case.id for case in CASES]
    slide_ids = [f"{case.id}-s1" for case in CASES]
    report_ids = [f"{case.id}-r1" for case in CASES]
    patient_ids = [patient.id for patient in PATIENTS]
    pathologist_ids = [person.id for person in ROSTER]
    concept_ids = [concept.id for concept in CONCEPTS]
    conn.execute(
        """
        delete from consult_message
        where thread_id in (select id from consult_thread where case_id = any(%s))
        """,
        (case_ids,),
    )
    conn.execute("delete from consult_thread where case_id = any(%s)", (case_ids,))
    conn.execute(
        "delete from annotation where case_id = any(%s) or slide_id = any(%s)",
        (case_ids, slide_ids),
    )
    conn.execute(
        "delete from patch where case_id = any(%s) or slide_id = any(%s)",
        (case_ids, slide_ids),
    )
    conn.execute(
        "delete from report_chunk where case_id = any(%s) or report_id = any(%s)",
        (case_ids, report_ids),
    )
    conn.execute(
        "delete from ingestion_job where id = any(%s) or case_id = any(%s)",
        ([JOB_DONE_ID, JOB_FAILED_ID, JOB_QUEUED_ID], case_ids),
    )
    conn.execute("delete from report where id = any(%s)", (report_ids,))
    conn.execute("delete from slide where id = any(%s)", (slide_ids,))
    conn.execute("delete from path_case where id = any(%s)", (case_ids,))
    conn.execute("delete from patient where id = any(%s)", (patient_ids,))
    conn.execute("delete from concept where id = any(%s)", (concept_ids,))
    conn.execute("delete from pathologist where id = any(%s)", (pathologist_ids,))


def _executemany(conn: Connection, query: str, rows: Sequence[tuple[object, ...]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(query, rows)


def _insert(conn: Connection, prepared: _Prepared) -> None:
    _executemany(conn,
        """
        insert into pathologist (
            id, name, role_title, primary_specialty, secondary_specialties,
            is_demo_user, is_synthetic, created_at
        ) values (%s, %s, %s, %s, %s, %s, true, %s)
        """,
        [
            (
                person.id,
                person.name,
                person.role_title,
                person.primary_specialty,
                list(person.secondary_specialties),
                person.is_demo_user,
                FIXTURE_CREATED,
            )
            for person in ROSTER
        ],
    )
    _executemany(conn,
        """
        insert into patient (
            id, display_label, sex, birth_year, is_synthetic_linkage, created_at
        ) values (%s, %s, %s, %s, %s, %s)
        """,
        [
            (
                patient.id,
                patient.display_label,
                patient.sex,
                patient.birth_year,
                patient.is_synthetic_linkage,
                FIXTURE_CREATED,
            )
            for patient in PATIENTS
        ],
    )
    _executemany(conn,
        """
        insert into concept (
            id, label, prompt, negative_prompt, specialty, ordinal,
            embedding, negative_embedding, created_at
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [_concept_row(concept) for concept in CONCEPTS],
    )
    _executemany(conn,
        """
        insert into path_case (
            id, patient_id, specimen_label, source_dataset, source_case_id, specialty,
            patient_age, patient_sex, primary_diagnosis, morphology, icd10, status,
            assigned_to, accessioned_at, is_held_out, cohort_tier, created_at
        ) values (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, 'demo', %s
        )
        """,
        [
            (
                case.id,
                case.patient_id,
                case.specimen_label,
                case.source_dataset,
                case.source_case_id,
                case.specialty,
                case.patient_age,
                case.patient_sex,
                case.primary_diagnosis,
                case.morphology,
                case.icd10,
                case.status,
                case.assigned_to,
                case.accessioned_at,
                case.is_held_out,
                FIXTURE_CREATED,
            )
            for case in CASES
        ],
    )
    _executemany(conn,
        """
        insert into slide (
            id, case_id, ordinal, stain, magnification, mpp, width, height,
            patch_size, patch_count, storage_key, thumb_pack_key, source_path,
            embedding, status, created_at
        ) values (
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s
        )
        """,
        prepared.slides,
    )
    _executemany(conn,
        """
        insert into report (
            id, case_id, author_id, status, body, clinical_history, gross_description,
            microscopic_description, conclusion, additional_info, icd10, signed_at, created_at
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        prepared.reports,
    )
    _executemany(conn,
        """
        insert into patch (
            slide_id, case_id, patient_id, specialty, x, y, size, embedding,
            in_corpus, thumb_offset, thumb_length, created_at
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        prepared.patches,
    )
    _executemany(conn,
        """
        insert into report_chunk (
            report_id, case_id, patient_id, specialty, section, ordinal, text,
            embedding, in_corpus, created_at
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        prepared.chunks,
    )
    _insert_annotations(conn)
    _insert_consult(conn)
    _insert_jobs(conn, prepared)


def _concept_row(concept: ConceptSeed) -> tuple[object, ...]:
    negative = (
        HalfVector(unit_vector(f"concept:{concept.id}:negative", CONCHZ_DIM, half=True))
        if concept.negative_prompt is not None
        else None
    )
    return (
        concept.id,
        concept.label,
        concept.prompt,
        concept.negative_prompt,
        concept.specialty,
        concept.ordinal,
        HalfVector(unit_vector(f"concept:{concept.id}:prompt", CONCHZ_DIM, half=True)),
        negative,
        FIXTURE_CREATED,
    )


def _insert_annotations(conn: Connection) -> None:
    slide_id = f"{_ANNOTATED_CASE_ID}-s1"
    created = datetime(2026, 11, 3, 11, 0, tzinfo=UTC)
    conn.execute(
        """
        insert into annotation (
            id, slide_id, case_id, author_id, kind, geometry, label, note, created_at, updated_at
        ) values (%s, %s, %s, %s, 'rect', %s, %s, %s, %s, %s)
        """,
        (
            ANNOTATION_RECT_ID,
            slide_id,
            _ANNOTATED_CASE_ID,
            DEMO_USER_ID,
            Jsonb({"x": 128, "y": 128, "width": 512, "height": 512}),
            "Fixture region",
            "Synthetic mark for the annotations list.",
            created,
            created,
        ),
    )
    conn.execute(
        """
        insert into annotation (
            id, slide_id, case_id, author_id, kind, geometry, label, note, created_at, updated_at
        ) values (%s, %s, %s, %s, 'point', %s, %s, null, %s, %s)
        """,
        (
            ANNOTATION_POINT_ID,
            slide_id,
            _ANNOTATED_CASE_ID,
            DEMO_USER_ID,
            Jsonb({"x": 1000, "y": 700}),
            "Fixture point",
            created,
            created,
        ),
    )


def _insert_consult(conn: Connection) -> None:
    created = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
    user_at = datetime(2026, 11, 12, 10, 1, tzinfo=UTC)
    assistant_at = datetime(2026, 11, 12, 10, 2, tzinfo=UTC)
    conn.execute(
        """
        insert into consult_thread (
            id, case_id, user_id, title, created_at, updated_at
        ) values (%s, %s, %s, %s, %s, %s)
        """,
        (
            THREAD_ID,
            _OPEN_CASE_ID,
            DEMO_USER_ID,
            "What do this patient's earlier specimens show?",
            created,
            assistant_at,
        ),
    )
    conn.execute(
        """
        insert into consult_message (
            id, thread_id, role, content, attachments, status, created_at
        ) values (%s, %s, 'user', %s, %s, 'complete', %s)
        """,
        (
            USER_MESSAGE_ID,
            THREAD_ID,
            "What do this patient's earlier specimens show?",
            Jsonb(
                {
                    "region": {
                        "slide_id": f"{_OPEN_CASE_ID}-s1",
                        "x": 0,
                        "y": 0,
                        "width": 512,
                        "height": 512,
                    }
                }
            ),
            user_at,
        ),
    )
    citations = [
        {
            "case_id": case_id,
            "slide_id": f"{case_id}-s1",
            "quote": "gland-forming epithelial proliferation",
        }
        for case_id in _PRIOR_CASE_IDS
    ]
    ranking = [
        {
            "pathologist_id": DEMO_USER_ID,
            "name": "Dr A. Okafor",
            "specialty": "breast",
            "case_count": len(_PRIOR_CASE_IDS),
            "case_ids": list(_PRIOR_CASE_IDS),
        }
    ]
    tool_trace = [
        {
            "tool": "search_reports",
            "input": {"case_ids": list(_PRIOR_CASE_IDS)},
            "summary": "Retrieved signed reports from this patient's earlier specimens.",
            "duration_ms": 18,
        },
        {
            "tool": "rank_pathologists",
            "input": {"case_ids": list(_PRIOR_CASE_IDS)},
            "summary": "Counted signed cases per pathologist from the tool results.",
            "duration_ms": 6,
        },
    ]
    content = (
        "Retrieved precedent from this patient's earlier signed specimens. "
        "This is not a diagnosis of the open case.\n\n"
        "[case:breast-FX-B042A] [case:breast-FX-B042B]"
    )
    conn.execute(
        """
        insert into consult_message (
            id, thread_id, role, content, citations, ranking, tool_trace,
            model, input_tokens, output_tokens, status, created_at
        ) values (
            %s, %s, 'assistant', %s, %s, %s, %s, %s, %s, %s, 'complete', %s
        )
        """,
        (
            ASSISTANT_MESSAGE_ID,
            THREAD_ID,
            content,
            Jsonb(citations),
            Jsonb(ranking),
            Jsonb(tool_trace),
            "fixture-retriever",
            120,
            40,
            assistant_at,
        ),
    )


def _insert_jobs(conn: Connection, prepared: _Prepared) -> None:
    done_case = _ANNOTATED_CASE_ID
    started = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    finished = datetime(2026, 11, 1, 10, 5, tzinfo=UTC)
    history = [
        {
            "stage": "download",
            "started_at": started.isoformat(),
            "finished_at": datetime(2026, 11, 1, 10, 1, tzinfo=UTC).isoformat(),
            "detail": "fixture file already present",
        },
        {
            "stage": "thumbnails",
            "started_at": datetime(2026, 11, 1, 10, 1, tzinfo=UTC).isoformat(),
            "finished_at": datetime(2026, 11, 1, 10, 3, tzinfo=UTC).isoformat(),
            "detail": "pack written",
        },
        {
            "stage": "load",
            "started_at": datetime(2026, 11, 1, 10, 3, tzinfo=UTC).isoformat(),
            "finished_at": finished.isoformat(),
            "detail": "rows loaded",
        },
    ]
    conn.execute(
        """
        insert into ingestion_job (
            id, dataset, slide_path, case_id, slide_id, requested_by, status, stage,
            stage_history, counts, error, attempts, worker_id, created_at, started_at, finished_at
        ) values (
            %s, 'TCGA-BRCA', 'fixture/fixture-he-rose.svs', %s, %s, %s, 'done', 'load',
            %s, %s, null, 1, 'fixture-worker', %s, %s, %s
        )
        """,
        (
            JOB_DONE_ID,
            done_case,
            f"{done_case}-s1",
            DEMO_USER_ID,
            Jsonb(history),
            Jsonb(
                {
                    "patches": prepared.patch_count_for_case[done_case],
                    "chunks": prepared.chunk_count_for_case[done_case],
                }
            ),
            started,
            started,
            finished,
        ),
    )
    failed_at = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
    conn.execute(
        """
        insert into ingestion_job (
            id, dataset, slide_path, requested_by, status, stage, stage_history,
            error, attempts, worker_id, created_at, started_at, finished_at
        ) values (
            %s, 'TCGA-LUAD', 'fixture/missing-luad.svs', %s, 'failed', 'embed', %s,
            %s, 1, 'fixture-worker', %s, %s, %s
        )
        """,
        (
            JOB_FAILED_ID,
            DEMO_USER_ID,
            Jsonb(
                [
                    {
                        "stage": "embed",
                        "started_at": failed_at.isoformat(),
                        "finished_at": failed_at.isoformat(),
                        "detail": "fixture failure",
                    }
                ]
            ),
            "fixture failure recorded for the jobs list",
            failed_at,
            failed_at,
            failed_at,
        ),
    )
    conn.execute(
        """
        insert into ingestion_job (
            id, dataset, slide_path, requested_by, status, stage, stage_history,
            attempts, created_at
        ) values (
            %s, 'TCGA-SKCM', 'fixture/queued-skcm.svs', %s, 'queued', null, '[]'::jsonb,
            0, %s
        )
        """,
        (JOB_QUEUED_ID, DEMO_USER_ID, datetime(2026, 11, 13, 8, 0, tzinfo=UTC)),
    )


def _counts(conn: Connection) -> dict[str, int]:
    from psycopg import sql

    counts: dict[str, int] = {}
    for table in STORED_TABLES:
        query = sql.SQL("select count(*) from {}").format(sql.Identifier(table))
        row = conn.execute(query).fetchone()
        if row is None:
            raise RuntimeError(f"count failed for {table}")
        counts[table] = int(row[0])
    return counts


def _under(root: Path, key: str) -> Path:
    relative = Path(key)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"storage key must be a relative path: {key}")
    return root / relative


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == payload:
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _public_error(exc: BaseException) -> str:
    message = str(exc)
    lowered = message.lower()
    if "://" in message or "password" in lowered:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"
