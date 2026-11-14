"""CONCH-Z projection, thumbnail packs, parquet export, and the alignment check."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from consilium.embed.spaces import (  # pragma: allowlist secret
    CONCHZ_DIM,
    UNIT_NORM_ATOL,
    ConchzEmbedding,
)
from consilium.embed.text import MockTextEncoder, TextEncoders  # pragma: allowlist secret
from consilium.pipeline.__main__ import main  # pragma: allowlist secret
from consilium.pipeline.export import (  # pragma: allowlist secret
    CONCEPT_SCHEMA,
    PATCH_SCHEMA,
    SLIDE_SCHEMA,
    export_cohort,
    load_concept_catalog,
)
from consilium.pipeline.extract import coords_h5_path, features_h5_path  # pragma: allowlist secret
from consilium.pipeline.project import (  # pragma: allowlist secret
    CONCHZ_REVISION,
    PROJ_CONTRAST_KEY,
    LinearProjector,
    fetch_proj_contrast,
    l2_normalize,
    mean_embedding,
    project_cohort,
)
from consilium.pipeline.thumbs import (  # pragma: allowlist secret
    OpenSlideOpener,
    decode_jpeg,
    jpeg_framed,
    pyramid_read,
    read_thumb_jpeg,
    thumbs_cohort,
    verify_alignment,
)

# Captured before the test fixture clears the environment. Never put this in an assertion.
_SAVED_HF_TOKEN = os.environ.get("HF_TOKEN")
_PROJ_SHA256 = "46bb027456fd7eff808f59a20e192093dbfb0e65f8c94f1cb0163f336625ec38"

CASE = "breast-TCGA-AA-1111"
SLIDE = f"{CASE}-s1"
FILE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FILE_NAME = "TCGA-AA-1111-01Z-00-DX1.svs"


class _CountingProjector:
    def __init__(self, inner: LinearProjector) -> None:
        self.inner = inner
        self.calls = 0

    def fingerprint(self) -> str:
        return self.inner.fingerprint()

    def project(self, features: np.ndarray) -> np.ndarray:
        self.calls += 1
        return self.inner.project(features)


class _Session:
    def __init__(self, colors: dict[tuple[int, int], tuple[int, int, int]]) -> None:
        self.colors = colors

    def read_rgb(self, x: int, y: int, patch_size_level0: int, thumb_side: int) -> np.ndarray:
        color = self.colors[(x, y)]
        return np.full((thumb_side, thumb_side, 3), color, dtype=np.uint8)

    def close(self) -> None:
        return None


class _Opener:
    def __init__(self, colors: dict[tuple[int, int], tuple[int, int, int]]) -> None:
        self.colors = colors
        self.opens = 0

    def open(self, path: Path) -> _Session:
        self.opens += 1
        return _Session(self.colors)


def _cohort(path: Path, slides: list[tuple[str, str, bool]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "case_id,slide_id,gdc_file_id,file_name,file_size,project_id,specialty,tier,held_out"
    ]
    for case_id, slide_id, held in slides:
        lines.append(
            f"{case_id},{slide_id},{FILE_ID},{FILE_NAME},128,TCGA-BRCA,breast,smoke,"
            f"{'true' if held else 'false'}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_raw(
    job_dir: Path,
    slide_id: str,
    features: np.ndarray,
    coords: np.ndarray,
    level0: int,
) -> None:
    coords_path = coords_h5_path(job_dir, slide_id)
    features_path = features_h5_path(job_dir, slide_id)
    coords_path.parent.mkdir(parents=True, exist_ok=True)
    features_path.parent.mkdir(parents=True, exist_ok=True)
    stored = coords.astype(np.int64)
    with h5py.File(coords_path, "w") as handle:
        dataset = handle.create_dataset("coords", data=stored)
        dataset.attrs["patch_size"] = 512
        dataset.attrs["target_magnification"] = 20
        dataset.attrs["overlap"] = 0
        dataset.attrs["patch_size_level0"] = level0
    with h5py.File(features_path, "w") as handle:
        dataset = handle.create_dataset("features", data=features.astype(np.float32))
        dataset.attrs["encoder"] = "conch_v15"
        handle.create_dataset("coords", data=stored)


def _headers(
    path: Path,
    slide_id: str,
    case_id: str,
    level0: int,
    *,
    error: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "slide_id": [slide_id],
            "case_id": [case_id],
            "width_px": [4096],
            "height_px": [2048],
            "magnification": [40.0],
            "magnification_source": ["test"],
            "mpp": [0.25],
            "mpp_source": ["test"],
            "trident_magnification": [40],
            "patch_size_level0": [None if error else level0],
            "error": [error],
        }
    )
    pq.write_table(table, path)


def _gdc(path: Path, case_id: str, submitter: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({"case_id": [case_id], "submitter_id": [submitter]}),
        path,
    )


def _unit_rows(count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    raw = rng.normal(size=(count, CONCHZ_DIM)).astype(np.float32)
    return l2_normalize(raw)


def _norms(rows: np.ndarray) -> np.ndarray:
    return np.linalg.norm(rows, axis=1)


def test_projection_matches_matrix_multiply_and_mean() -> None:
    rng = np.random.default_rng(1)
    weight = rng.normal(size=(CONCHZ_DIM, CONCHZ_DIM)).astype(np.float32)
    weight /= np.linalg.norm(weight, axis=0, keepdims=True)
    features = rng.normal(size=(5, CONCHZ_DIM)).astype(np.float32)
    projector = LinearProjector(weight, name="test")
    projected = projector.project(features)
    manual = np.asarray(features, dtype=np.float32) @ projector.weight
    manual = manual / np.linalg.norm(manual, axis=1, keepdims=True)
    np.testing.assert_allclose(projected, manual.astype(np.float32), atol=1e-4)
    assert projected.shape == (5, CONCHZ_DIM)
    assert np.all(np.abs(_norms(projected) - 1.0) <= UNIT_NORM_ATOL)
    mean = projected.mean(axis=0)
    mean = mean / np.linalg.norm(mean)
    np.testing.assert_allclose(mean_embedding(projected), mean.astype(np.float32), atol=1e-4)
    ConchzEmbedding(values=tuple(float(value) for value in mean_embedding(projected)))


def test_real_proj_contrast_tensor_when_hf_reachable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _SAVED_HF_TOKEN:
        pytest.skip("HF_TOKEN is absent")
    weight = fetch_proj_contrast(_SAVED_HF_TOKEN, cache_dir=tmp_path)
    assert weight.shape == (CONCHZ_DIM, CONCHZ_DIM)
    digest = hashlib.sha256(np.ascontiguousarray(weight).tobytes()).hexdigest()
    assert digest == _PROJ_SHA256
    assert PROJ_CONTRAST_KEY == "visual.proj_contrast"
    assert len(CONCHZ_REVISION) == 40

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("projection cache should not download again")

    monkeypatch.setattr("urllib.request.urlopen", _refuse)
    cached = fetch_proj_contrast("cached-token", cache_dir=tmp_path)
    np.testing.assert_array_equal(cached, weight)

    features = np.random.default_rng(0).normal(size=(4, CONCHZ_DIM)).astype(np.float32)
    projected = LinearProjector(weight, name=PROJ_CONTRAST_KEY).project(features)
    raw_unit = features / np.linalg.norm(features, axis=1, keepdims=True)
    cosine = np.sum(raw_unit.astype(np.float32) * projected, axis=1)
    assert np.all(np.abs(cosine) < 0.5)
    assert np.all(np.abs(_norms(projected) - 1.0) <= UNIT_NORM_ATOL)


def test_project_is_idempotent_and_keeps_going(tmp_path: Path) -> None:
    data = tmp_path / "data"
    job = data / "trident"
    cohort = data / "cohort" / "cohort.csv"
    other = "breast-TCGA-AA-2222"
    other_slide = f"{other}-s1"
    _cohort(cohort, [(CASE, SLIDE, False), (other, other_slide, True)])
    coords = np.array([[0, 0], [1024, 0]], dtype=np.int64)
    good = _unit_rows(2, 3)
    _write_raw(job, SLIDE, good, coords, 1024)
    broken = good.copy()
    broken[0] = 0
    _write_raw(job, other_slide, broken, coords, 1024)
    projector = _CountingProjector(LinearProjector(np.eye(CONCHZ_DIM, dtype=np.float32)))
    first = project_cohort(cohort_csv=cohort, data_root=data, projector=projector)
    assert first.succeeded == 1
    assert first.failed == 1
    assert first.skipped == 0
    assert projector.calls == 2
    assert "failure" in first.summary()
    second = project_cohort(cohort_csv=cohort, data_root=data, projector=projector)
    assert second.succeeded == 0
    assert second.skipped == 1
    assert second.failed == 1
    assert projector.calls == 3
    features_path = features_h5_path(job, SLIDE)
    with h5py.File(features_path, "r+") as handle:
        values = handle["features"][:]
        values[0, 0] = float(values[0, 0]) + 0.5
        handle["features"][:] = values
    third = project_cohort(cohort_csv=cohort, data_root=data, projector=projector)
    assert third.succeeded == 1
    assert projector.calls == 5


def test_pyramid_level_choice_matches_openslide(tmp_path: Path) -> None:
    path = _pyramid(tmp_path / "slide.svs")
    import openslide

    slide = openslide.OpenSlide(str(path))
    try:
        for thumb in (256, 224, 512, 1024):
            level, read_size, exact = pyramid_read(slide.level_downsamples, 1024, thumb)
            assert level == slide.get_best_level_for_downsample(1024 / thumb)
            assert read_size == max(1, int(round(1024 / slide.level_downsamples[level])))
            assert exact is (read_size == thumb)
    finally:
        slide.close()
    level, read_size, exact = pyramid_read((1.0, 2.0, 4.0), 1024, 256)
    assert (level, read_size, exact) == (2, 256, True)
    level, read_size, exact = pyramid_read((1.0, 2.0, 4.0), 512, 512)
    assert (level, read_size, exact) == (0, 512, True)


def test_pyramidal_svs_pack_decodes_from_offsets(tmp_path: Path) -> None:
    data = tmp_path / "data"
    job = data / "trident"
    cohort = data / "cohort" / "cohort.csv"
    _cohort(cohort, [(CASE, SLIDE, False)])
    _pyramid(data / "slides" / f"{SLIDE}.svs")
    coords = np.array([[0, 0], [1024, 0]], dtype=np.int64)
    _write_raw(job, SLIDE, _unit_rows(2, 4), coords, 1024)
    opener = OpenSlideOpener()
    first = thumbs_cohort(
        cohort_csv=cohort,
        data_root=data,
        opener=opener,
        thumb_side=256,
        jpeg_quality=90,
    )
    assert first.succeeded == 1
    assert first.failed == 0
    pack = data / "thumbs" / f"{SLIDE}.pack"
    index = json.loads((data / "thumbs" / f"{SLIDE}.index.json").read_text(encoding="utf-8"))
    assert [item["x"] for item in index["patches"]] == [0, 1024]
    rng = np.random.default_rng(7)
    for pick in rng.choice(len(index["patches"]), size=2, replace=False):
        item = index["patches"][int(pick)]
        blob = read_thumb_jpeg(pack, item["thumb_offset"], item["thumb_length"])
        assert jpeg_framed(blob)
        image = decode_jpeg(blob)
        assert image.shape == (256, 256, 3)
        expected = (10, 10, 220) if item["x"] == 0 else (10, 220, 10)
        assert np.max(np.abs(image.astype(int) - np.array(expected))) <= 2
    resized = thumbs_cohort(
        cohort_csv=cohort,
        data_root=data,
        opener=opener,
        thumb_side=100,
        jpeg_quality=90,
    )
    assert resized.succeeded == 1
    index = json.loads((data / "thumbs" / f"{SLIDE}.index.json").read_text(encoding="utf-8"))
    blob = read_thumb_jpeg(
        pack,
        index["patches"][0]["thumb_offset"],
        index["patches"][0]["thumb_length"],
    )
    small = decode_jpeg(blob)
    assert small.shape == (100, 100, 3)
    assert int(small[:, :, 2].mean()) > 200
    again = thumbs_cohort(
        cohort_csv=cohort,
        data_root=data,
        opener=opener,
        thumb_side=100,
        jpeg_quality=90,
    )
    assert again.skipped == 1
    assert again.succeeded == 0


def test_export_schema_unit_norm_and_idempotence(tmp_path: Path) -> None:
    data = tmp_path / "data"
    built = _ready_slide(data, held_out=True)
    encoders = built["encoders"]
    first = export_cohort(
        cohort_csv=built["cohort"],
        data_root=data,
        text_encoder=encoders,
        now=datetime(2026, 11, 14, tzinfo=UTC),
    )
    assert first.failed == 0
    assert first.slides_written == 1
    assert first.patches_written == 2
    assert first.concepts_written == 20
    slides = pq.read_table(first.slide_path)
    patches = pq.read_table(first.patch_path)
    concepts = pq.read_table(first.concept_path)
    assert slides.schema.equals(SLIDE_SCHEMA)
    assert patches.schema.equals(PATCH_SCHEMA)
    assert concepts.schema.equals(CONCEPT_SCHEMA)
    assert "width_px" not in slides.column_names
    assert "x_px" not in patches.column_names
    assert "id" not in patches.column_names
    slide = slides.to_pylist()[0]
    assert slide["width"] == 4096
    assert slide["height"] == 2048
    assert slide["patch_size"] == 1024
    assert slide["patch_count"] == 2
    assert slide["status"] == "ready"
    assert slide["storage_key"] == f"slides/{SLIDE}.svs"
    assert slide["thumb_pack_key"] == f"thumbs/{SLIDE}.pack"
    assert slide["source_path"] == f"{FILE_ID}/{FILE_NAME}"
    assert slide["stain"] == "HE"
    _assert_vector(slide["embedding"])
    rows = patches.to_pylist()
    assert {(row["x"], row["y"], row["size"]) for row in rows} == {(0, 0, 1024), (1024, 0, 1024)}
    assert {row["patient_id"] for row in rows} == {"donor-from-gdc"}
    assert {row["in_corpus"] for row in rows} == {False}
    assert {row["specialty"] for row in rows} == {"breast"}
    assert {row["case_id"] for row in rows} == {CASE}
    for row in rows:
        _assert_vector(row["embedding"])
        assert row["thumb_length"] > 4
    for row in concepts.to_pylist():
        _assert_vector(row["embedding"])
        if row["negative_prompt"]:
            _assert_vector(row["negative_embedding"])
        else:
            assert row["negative_embedding"] is None
    catalog_ids = {spec.id for spec in load_concept_catalog()}
    assert {row["id"] for row in concepts.to_pylist()} == catalog_ids

    kept_at = datetime(2026, 1, 2, tzinfo=UTC)
    custom_prompt = "an H&E image of a hand edited phrase"
    existing = concepts.to_pylist()
    necrosis = next(row for row in existing if row["id"] == "tumour-necrosis")
    necrosis["prompt"] = custom_prompt
    necrosis["created_at"] = kept_at
    extra = dict(existing[0])
    extra["id"] = "custom-phrase"
    extra["label"] = "Custom"
    extra["prompt"] = "an H&E image of custom tissue"
    extra["negative_prompt"] = None
    extra["specialty"] = None
    extra["ordinal"] = 50
    extra["created_at"] = kept_at
    extra["embedding"] = existing[0]["embedding"]
    extra["negative_embedding"] = None
    # Keep only the edited rows so catalog entries are appended on the next export.
    _write_concept_rows_to(first.concept_path, [extra, necrosis])
    second = export_cohort(
        cohort_csv=built["cohort"],
        data_root=data,
        text_encoder=encoders,
        now=datetime(2026, 11, 15, tzinfo=UTC),
    )
    assert second.failed == 0
    assert second.slides_written == 1
    assert second.patches_written == 2
    again = pq.read_table(second.concept_path).to_pylist()
    ids = [row["id"] for row in again]
    assert ids[:2] == ["custom-phrase", "tumour-necrosis"]
    assert set(ids) == catalog_ids | {"custom-phrase"}
    edited = next(row for row in again if row["id"] == "tumour-necrosis")
    assert edited["prompt"] == custom_prompt
    assert edited["created_at"] == kept_at
    expected = np.asarray(encoders.encode_image_text(custom_prompt).vector.values, dtype=np.float32)
    np.testing.assert_allclose(edited["embedding"], expected, atol=1e-5)
    catalog_prompt = next(
        spec.prompt for spec in load_concept_catalog() if spec.id == "tumour-necrosis"
    )
    catalog_vector = np.asarray(
        encoders.encode_image_text(catalog_prompt).vector.values, dtype=np.float32
    )
    assert not np.allclose(edited["embedding"], catalog_vector, atol=1e-3)

    path_case = data / "export" / "path_case.parquet"
    pq.write_table(
        pa.table(
            {
                "id": [CASE],
                "patient_id": ["patient-linked"],
                "status": ["signed_out"],
                "is_held_out": [False],
                "specialty": ["breast"],
            }
        ),
        path_case,
    )
    linked = export_cohort(
        cohort_csv=built["cohort"],
        data_root=data,
        text_encoder=encoders,
        now=datetime(2026, 11, 14, tzinfo=UTC),
    )
    linked_rows = pq.read_table(linked.patch_path).to_pylist()
    assert {row["patient_id"] for row in linked_rows} == {"patient-linked"}
    assert {row["in_corpus"] for row in linked_rows} == {True}


def test_export_donor_barcode_without_gdc_file(tmp_path: Path) -> None:
    data = tmp_path / "data"
    built = _ready_slide(data, held_out=False)
    (data / "source" / "gdc_cases.parquet").unlink()
    result = export_cohort(
        cohort_csv=built["cohort"],
        data_root=data,
        text_encoder=built["encoders"],
        now=datetime(2026, 11, 14, tzinfo=UTC),
    )
    rows = pq.read_table(result.patch_path).to_pylist()
    assert {row["patient_id"] for row in rows} == {"TCGA-AA-1111"}
    assert {row["in_corpus"] for row in rows} == {True}


def test_alignment_strips_use_pack_offsets(tmp_path: Path) -> None:
    data = tmp_path / "data"
    built = _ready_slide(data, held_out=False)
    output = tmp_path / "alignment"
    result = verify_alignment(
        data_root=data,
        slide_id=SLIDE,
        output_dir=output,
        prompt="tumour cells",
        contrast="adipose tissue",
        top_k=1,
        encoder=built["encoders"],
    )
    assert result.failed == 0
    by_prompt = {hit.prompt: hit for hit in result.hits}
    assert by_prompt["tumour cells"].x == 0
    assert by_prompt["adipose tissue"].x == 1024
    tumour = decode_jpeg(by_prompt["tumour cells"].path.read_bytes())
    adipose = decode_jpeg(by_prompt["adipose tissue"].path.read_bytes())
    assert int(tumour[:, :, 0].mean()) > 200
    assert int(adipose[:, :, 1].mean()) > 200
    for strip in result.strips:
        assert strip.suffix == ".png"
        assert strip.is_file()
        assert strip.stat().st_size > 32
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["prompts"][0]["hits"][0]["x"] == 0
    assert manifest["prompts"][1]["hits"][0]["x"] == 1024


def test_project_cli_reports_a_missing_token(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cohort = tmp_path / "cohort.csv"
    _cohort(cohort, [(CASE, SLIDE, False)])
    code = main(["project", "--data-root", str(tmp_path), "--cohort", str(cohort)])
    assert code == 1
    assert "HF_TOKEN" in capsys.readouterr().err


def test_cli_help_lists_new_commands() -> None:
    for command in ("project", "thumbs", "export", "verify-alignment"):
        with pytest.raises(SystemExit) as exc:
            main([command, "--help"])
        assert exc.value.code == 0


def _ready_slide(data: Path, *, held_out: bool) -> dict[str, object]:
    """One slide whose projected rows are the mock encodings of the two prompts."""
    job = data / "trident"
    cohort = data / "cohort" / "cohort.csv"
    _cohort(cohort, [(CASE, SLIDE, held_out)])
    encoders = TextEncoders(MockTextEncoder())
    tumour = np.asarray(encoders.encode_image_text("tumour cells").vector.values, dtype=np.float32)
    adipose = np.asarray(
        encoders.encode_image_text("adipose tissue").vector.values, dtype=np.float32
    )
    features = np.stack([tumour, adipose])
    coords = np.array([[0, 0], [1024, 0]], dtype=np.int64)
    _write_raw(job, SLIDE, features, coords, 1024)
    _headers(job / "slide_headers.parquet", SLIDE, CASE, 1024)
    _gdc(data / "source" / "gdc_cases.parquet", CASE, "donor-from-gdc")
    (data / "slides").mkdir(parents=True)
    (data / "slides" / f"{SLIDE}.svs").write_bytes(b"not-a-real-svs")
    colors = {(0, 0): (255, 0, 0), (1024, 0): (0, 255, 0)}
    projector = LinearProjector(np.eye(CONCHZ_DIM, dtype=np.float32))
    projected = project_cohort(cohort_csv=cohort, data_root=data, projector=projector)
    assert projected.failed == 0
    packed = thumbs_cohort(
        cohort_csv=cohort,
        data_root=data,
        opener=_Opener(colors),
        thumb_side=32,
        jpeg_quality=90,
    )
    assert packed.failed == 0
    return {"cohort": cohort, "encoders": encoders}


def _write_concept_rows_to(path: Path, rows: list[dict[str, object]]) -> None:
    embeddings = [np.asarray(row["embedding"], dtype=np.float32) for row in rows]
    negatives: list[list[float] | None] = []
    for row in rows:
        value = row["negative_embedding"]
        if value is None:
            negatives.append(None)
        else:
            negatives.append(np.asarray(value, dtype=np.float32).tolist())
    flat = np.concatenate(embeddings).astype(np.float32)
    table = pa.table(
        {
            "id": [row["id"] for row in rows],
            "label": [row["label"] for row in rows],
            "prompt": [row["prompt"] for row in rows],
            "negative_prompt": [row["negative_prompt"] for row in rows],
            "specialty": [row["specialty"] for row in rows],
            "ordinal": pa.array([int(row["ordinal"]) for row in rows], type=pa.int32()),
            "embedding": pa.FixedSizeListArray.from_arrays(
                pa.array(flat, type=pa.float32()),
                CONCHZ_DIM,
            ),
            "negative_embedding": pa.array(
                negatives,
                type=CONCEPT_SCHEMA.field("negative_embedding").type,
            ),
            "created_at": pa.array(
                [row["created_at"] for row in rows],
                type=CONCEPT_SCHEMA.field("created_at").type,
            ),
        },
        schema=CONCEPT_SCHEMA,
    )
    pq.write_table(table, path)


def _assert_vector(values: list[float] | None) -> None:
    assert values is not None and len(values) == CONCHZ_DIM
    ConchzEmbedding.from_halfvec(values)
    norm = float(np.linalg.norm(np.asarray(values, dtype=np.float32)))
    assert abs(norm - 1.0) <= UNIT_NORM_ATOL


def _pyramid(path: Path) -> Path:
    import tifffile

    path.parent.mkdir(parents=True, exist_ok=True)
    level0 = np.zeros((2048, 2048, 3), dtype=np.uint8)
    level0[:] = (220, 10, 10)
    level1 = level0[::2, ::2].copy()
    level2 = np.zeros((512, 512, 3), dtype=np.uint8)
    level2[:, :256] = (10, 10, 220)
    level2[:, 256:] = (10, 220, 10)
    with tifffile.TiffWriter(path) as handle:
        handle.write(level0, photometric="rgb", tile=(256, 256), compression="zlib")
        handle.write(level1, photometric="rgb", tile=(256, 256), compression="zlib", subfiletype=1)
        handle.write(level2, photometric="rgb", tile=(256, 256), compression="zlib", subfiletype=1)
    return path
