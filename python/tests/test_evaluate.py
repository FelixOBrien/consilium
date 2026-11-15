"""Retrieval evaluation on held-out cases.

The controlled cohort uses deterministic vectors so precision, hit rate, the
random baseline, synthetic-link exclusion, and the best-patch vs mean-top-3
comparison are exact. The seeded cohort checks the same exclusion rule on the
fixture longitudinal patients, through the CLI.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from pgvector import HalfVector, Vector
from psycopg import Connection

from consilium.config import SearchBackend, repo_root  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import seed  # pragma: allowlist secret
from consilium.embed.text import MockTextEncoder, build_text_encoders  # pragma: allowlist secret
from consilium.pipeline.__main__ import main  # pragma: allowlist secret
from consilium.pipeline.evaluate import (  # pragma: allowlist secret
    aggregate_patch_scores,
    default_eval_dir,
    demo_rank_score,
    expected_hit_rate_at_k,
    expected_precision_at_k,
    fuse_case_ranks,
    histology_code,
    hit_rate_at_k,
    icd10_category,
    precision_at_k,
    retrieval_clarity,
    run_evaluate,
    select_hits,
)

SECRET = "Zephyriform secret diagnosis phrase"
HISTORY = "zebraglobin"
WHEN = datetime(2026, 6, 1, tzinfo=UTC)


def test_histology_and_icd10_codes() -> None:
    assert histology_code("8140/3") == "8140"
    assert histology_code(" 8070/3 ") == "8070"
    assert histology_code("8500") == "8500"
    assert histology_code(None) is None
    assert histology_code("   ") is None
    assert icd10_category("C50.9") == "C50"
    assert icd10_category("c34.1") == "C34"
    assert icd10_category("C34") == "C34"
    assert icd10_category("C5") is None
    assert icd10_category(None) is None


def test_precision_hit_rate_and_random_baseline() -> None:
    flags = [True, False, True]
    assert precision_at_k(flags, 5) == pytest.approx(2 / 5)
    assert hit_rate_at_k(flags, 5) == 1.0
    assert precision_at_k([False, False], 5) == 0.0
    assert hit_rate_at_k([False, False], 5) == 0.0
    assert hit_rate_at_k([], 10) == 0.0

    assert expected_precision_at_k(3, 8, 5) == pytest.approx(3 / 8)
    assert expected_precision_at_k(3, 8, 10) == pytest.approx(3 / 10)
    assert expected_precision_at_k(0, 8, 5) == 0.0
    assert expected_precision_at_k(3, 0, 5) == 0.0
    assert expected_hit_rate_at_k(3, 8, 5) == pytest.approx(1 - 1 / 56)
    assert expected_hit_rate_at_k(2, 9, 5) == pytest.approx(1 - (1 / 6))
    assert expected_hit_rate_at_k(3, 8, 10) == 1.0
    assert expected_hit_rate_at_k(0, 9, 5) == 0.0


def test_rank_score_adds_a_longitudinal_bonus() -> None:
    assert retrieval_clarity([]) == 0.0
    assert retrieval_clarity([0.6, 0.4]) == pytest.approx(0.5)
    assert demo_rank_score(0.6, 0) == pytest.approx(0.6)
    assert demo_rank_score(0.6, 2) == pytest.approx(0.85)


def test_fusion_aggregation_and_synthetic_exclusion() -> None:
    assert fuse_case_ranks([["a", "b", "c"]]) == ["a", "b", "c"]
    assert fuse_case_ranks([]) == []
    scores = aggregate_patch_scores(
        {"spike": [0.99, 0.0, 0.0], "flat": [0.7, 0.7, 0.7], "one": [0.4]}
    )
    assert scores["spike"][0] == pytest.approx(0.99)
    assert scores["spike"][1] == pytest.approx(0.99 / 3)
    assert scores["flat"] == pytest.approx((0.7, 0.7))
    assert scores["one"] == pytest.approx((0.4, 0.4))
    assert scores["spike"][0] > scores["flat"][0]
    assert scores["flat"][1] > scores["spike"][1]

    kept, excluded = select_hits(
        ["syn", "a", "syn", "outsider", "b"],
        corpus_ids={"syn", "a", "b"},
        synthetic_same_patient={"syn"},
    )
    assert kept == ["a", "b"]
    assert excluded == ["syn"]


def test_default_out_dir_is_gitignored_data() -> None:
    assert default_eval_dir() == repo_root() / "data" / "eval"


def test_evaluate_does_not_mount_an_api(capsys: pytest.CaptureFixture[str]) -> None:
    source = Path(run_evaluate.__code__.co_filename).read_text(encoding="utf-8")
    assert "APIRouter" not in source
    assert "consilium.api.app" not in source  # pragma: allowlist secret
    assert "FastAPI" not in source
    with pytest.raises(SystemExit) as exc:
        main(["evaluate", "--help"])
    assert exc.value.code == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "--out-dir" in output
    assert "not for clinical use" in output


def test_encoder_name_is_checked_before_connecting() -> None:
    with pytest.raises(ValueError, match="encoder"):
        run_evaluate(encoder="nope")


def test_empty_database_writes_both_reports(empty_database: str, tmp_path: Path) -> None:
    migrate(empty_database, search_backend=SearchBackend.PGVECTOR)
    result = run_evaluate(out_dir=tmp_path, encoder="mock", database_url=empty_database)
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert result.held_out_count == 0
    assert payload["held_out_count"] == 0
    assert payload["scoring_comparison"]["winner"] == "tie"
    assert all(metric["n"] == 0 for metric in payload["metrics"])
    assert "not for clinical use" in payload["notice"]
    assert "not for clinical use" in markdown
    assert "No held-out open cases" in markdown
    assert "held_out 0" in result.summary()


def test_controlled_cohort_metrics(empty_database: str, tmp_path: Path) -> None:
    migrate(empty_database, search_backend=SearchBackend.PGVECTOR)
    _load_controlled(empty_database)
    result = run_evaluate(out_dir=tmp_path, encoder="mock", database_url=empty_database)
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    markdown = result.markdown_path.read_text(encoding="utf-8")
    blob = result.json_path.read_text(encoding="utf-8") + markdown

    assert SECRET not in blob
    assert HISTORY not in blob
    assert "not for clinical use" in blob
    assert "8140" in blob

    by_id = {row["case_id"]: row for row in payload["cases"]}
    assert [row["case_id"] for row in payload["cases"]] == ["q-syn", "q-real"]
    assert [row["case_id"] for row in payload["demo_candidates"]] == ["q-syn", "q-real"]

    syn = by_id["q-syn"]
    real = by_id["q-real"]
    assert syn["has_clinical_history"] is True
    assert real["has_clinical_history"] is False
    assert real["searches"]["reports"] is None
    assert syn["synthetic_linkage"] is True
    assert real["synthetic_linkage"] is False

    assert syn["searches"]["slide"]["excluded_synthetic"] == ["syn-prior"]
    assert syn["searches"]["best_patch"]["excluded_synthetic"] == ["syn-prior"]
    assert syn["searches"]["mean_top_3"]["excluded_synthetic"] == ["syn-prior"]
    assert syn["searches"]["reports"]["excluded_synthetic"] == ["syn-prior"]
    for search_type in ("slide", "best_patch", "mean_top_3", "reports"):
        assert "syn-prior" not in syn["searches"][search_type]["top10"]
    assert real["searches"]["slide"]["excluded_synthetic"] == []
    assert "syn-prior" in real["searches"]["slide"]["top10"]
    assert real["searches"]["slide"]["top5"][0] == "real-prior"

    assert syn["searches"]["slide"]["top5"] == [
        "a-match",
        "c-match",
        "g-match",
        "b-other",
        "d-other",
    ]
    assert syn["searches"]["best_patch"]["top5"] == [
        "a-match",
        "c-match",
        "g-match",
        "b-other",
        "d-other",
    ]
    assert syn["searches"]["mean_top_3"]["top5"] == [
        "b-other",
        "d-other",
        "e-other",
        "f-other",
        "real-prior",
    ]
    assert syn["searches"]["reports"]["top5"] == [
        "a-match",
        "c-match",
        "g-match",
        "b-other",
        "d-other",
    ]
    assert real["searches"]["slide"]["top5"] == [
        "real-prior",
        "f-other",
        "e-other",
        "d-other",
        "b-other",
    ]
    assert real["searches"]["best_patch"]["top5"] == [
        "b-other",
        "d-other",
        "e-other",
        "f-other",
        "real-prior",
    ]

    assert syn["searches"]["slide"]["precision_at_5"]["icd_o3_histology"] == pytest.approx(0.6)
    assert syn["searches"]["mean_top_3"]["precision_at_5"]["icd_o3_histology"] == 0.0
    assert syn["searches"]["mean_top_3"]["hit_rate_at_5"]["icd_o3_histology"] == 0.0
    assert syn["searches"]["slide"]["precision_at_5"]["icd10_category"] == pytest.approx(0.4)
    assert syn["searches"]["slide"]["precision_at_5"]["specialty"] == pytest.approx(0.4)
    assert syn["searches"]["slide"]["precision_at_10"]["icd_o3_histology"] == pytest.approx(0.3)
    assert real["searches"]["slide"]["precision_at_5"]["icd_o3_histology"] == pytest.approx(0.4)
    assert real["searches"]["slide"]["hit_rate_at_5"]["specialty"] == 1.0

    slide_hist = _metric(payload, "slide", "icd_o3_histology")
    slide_icd = _metric(payload, "slide", "icd10_category")
    slide_spec = _metric(payload, "slide", "specialty")
    best_hist = _metric(payload, "best_patch", "icd_o3_histology")
    mean_hist = _metric(payload, "mean_top_3", "icd_o3_histology")
    report_hist = _metric(payload, "reports", "icd_o3_histology")
    report_icd = _metric(payload, "reports", "icd10_category")

    assert slide_hist["n"] == 2
    assert slide_icd["n"] == 2
    assert slide_spec["n"] == 2
    assert report_hist["n"] == 1
    assert slide_hist["precision_at_5"] == pytest.approx(0.5)
    assert slide_hist["hit_rate_at_5"] == 1.0
    assert slide_hist["precision_at_10"] == pytest.approx(0.25)
    assert slide_hist["hit_rate_at_10"] == 1.0
    assert slide_icd["precision_at_5"] == pytest.approx(0.4)
    assert slide_spec["precision_at_5"] == pytest.approx(0.4)
    assert slide_icd["precision_at_10"] == pytest.approx(0.2)
    assert best_hist["precision_at_5"] == pytest.approx(0.5)
    assert mean_hist["precision_at_5"] == pytest.approx(0.2)
    assert mean_hist["hit_rate_at_5"] == pytest.approx(0.5)
    assert report_hist["precision_at_5"] == pytest.approx(0.6)
    assert report_hist["precision_at_10"] == pytest.approx(0.3)
    assert report_icd["precision_at_5"] == pytest.approx(0.4)

    hist_p5 = (expected_precision_at_k(3, 8, 5) + expected_precision_at_k(2, 9, 5)) / 2
    hist_p10 = (expected_precision_at_k(3, 8, 10) + expected_precision_at_k(2, 9, 10)) / 2
    hist_h5 = (expected_hit_rate_at_k(3, 8, 5) + expected_hit_rate_at_k(2, 9, 5)) / 2
    secondary_p5 = (expected_precision_at_k(2, 8, 5) + expected_precision_at_k(2, 9, 5)) / 2
    assert slide_hist["baseline_precision_at_5"] == pytest.approx(hist_p5)
    assert slide_hist["baseline_precision_at_10"] == pytest.approx(hist_p10)
    assert slide_hist["baseline_hit_rate_at_5"] == pytest.approx(hist_h5)
    assert slide_hist["baseline_hit_rate_at_10"] == 1.0
    assert slide_icd["baseline_precision_at_5"] == pytest.approx(secondary_p5)
    assert slide_spec["baseline_precision_at_10"] == pytest.approx(0.2)
    assert report_hist["baseline_precision_at_5"] == pytest.approx(expected_precision_at_k(3, 8, 5))
    assert report_hist["baseline_hit_rate_at_5"] == pytest.approx(expected_hit_rate_at_k(3, 8, 5))

    comparison = payload["scoring_comparison"]
    assert comparison["winner"] == "best_patch"
    assert comparison["n"] == 2
    assert comparison["best_patch_precision_at_5"] == pytest.approx(0.5)
    assert comparison["mean_top_3_precision_at_5"] == pytest.approx(0.2)
    assert "best_patch" in markdown
    assert "mean_top_3" in markdown
    assert syn["rank_score"] == pytest.approx(0.85)
    assert real["rank_score"] == pytest.approx(0.65)
    assert "scoring best_patch" in result.summary()
    assert markdown.index("`q-syn`") < markdown.index("`q-real`")


def test_seeded_cohort_excludes_synthetic_links(
    empty_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    migrate(empty_database, search_backend=SearchBackend.PGVECTOR)
    seed(empty_database, tmp_path / "storage")
    out = tmp_path / "eval"
    monkeypatch.setenv("DATABASE_URL", empty_database)
    assert main(["evaluate", "--encoder", "mock", "--out-dir", str(out)]) == 0
    printed = capsys.readouterr().out
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    markdown = (out / "report.md").read_text(encoding="utf-8")

    assert "held_out 4" in printed
    assert "not clinical diagnostic accuracy" in printed
    assert "not for clinical use" in markdown
    assert "Recurrence excision" not in markdown
    assert "Recurrence excision" not in (out / "report.json").read_text(encoding="utf-8")

    by_id = {row["case_id"]: row for row in payload["cases"]}
    assert set(by_id) == {
        "breast-FX-B042C",
        "skin-FX-S018B",
        "thorax-FX-T019A",
        "breast-FX-B074A",
    }
    scores = [row["rank_score"] for row in payload["cases"]]
    assert scores == sorted(scores, reverse=True)
    assert [row["case_id"] for row in payload["demo_candidates"]] == [
        row["case_id"] for row in payload["cases"][:5]
    ]
    assert all(metric["n"] == 4 for metric in payload["metrics"])
    assert payload["scoring_comparison"]["winner"] in {"best_patch", "mean_top_3", "tie"}

    breast = by_id["breast-FX-B042C"]
    skin = by_id["skin-FX-S018B"]
    thorax = by_id["thorax-FX-T019A"]
    for search_type in ("slide", "best_patch", "mean_top_3", "reports"):
        breast_ids = set(breast["searches"][search_type]["top10"])
        skin_ids = set(skin["searches"][search_type]["top10"])
        thorax_ids = set(thorax["searches"][search_type]["top10"])
        assert "breast-FX-B042A" not in breast_ids
        assert "breast-FX-B042B" not in breast_ids
        assert "skin-FX-S018A" not in skin_ids
        assert "breast-FX-B042A" in thorax_ids
        assert "colorectal-FX-C033A" in thorax_ids
        assert "skin-FX-S018A" in thorax_ids
        assert set(breast["searches"][search_type]["excluded_synthetic"]) >= {
            "breast-FX-B042A",
            "breast-FX-B042B",
        }
        assert "skin-FX-S018A" in skin["searches"][search_type]["excluded_synthetic"]


def _metric(payload: dict[str, object], search_type: str, relevance: str) -> dict[str, object]:
    metrics = payload["metrics"]
    assert isinstance(metrics, list)
    for metric in metrics:
        assert isinstance(metric, dict)
        if metric["search_type"] == search_type and metric["relevance"] == relevance:
            return metric
    raise AssertionError(f"missing {search_type} {relevance}")


@dataclass(frozen=True)
class _Case:
    case_id: str
    patient_id: str
    synthetic: bool
    specialty: str
    morphology: str
    icd10: str
    status: str
    slide_deg: float
    patch: str
    keyword: bool
    history: str | None
    cosine: float


def _controlled_case(
    case_id: str,
    patient_id: str,
    synthetic: bool,
    specialty: str,
    morphology: str,
    icd10: str,
    status: str,
    slide_deg: float,
    patch: str,
    keyword: bool,
    history: str | None,
    cosine: float,
) -> _Case:
    return _Case(
        case_id,
        patient_id,
        synthetic,
        specialty,
        morphology,
        icd10,
        status,
        slide_deg,
        patch,
        keyword,
        history,
        cosine,
    )


_CONTROLLED = (
    _controlled_case(
        "q-syn", "pt-syn", True, "breast", "8140/3", "C50.9",
        "open", 0, "none", False, HISTORY, 0.0,
    ),
    _controlled_case(
        "syn-prior", "pt-syn", True, "breast", "8140/3", "C50.9",
        "signed_out", 0, "spike", False, None, 0.05,
    ),
    _controlled_case(
        "a-match", "pt-a", False, "breast", "8140/3", "C50.1",
        "signed_out", 5, "spike", True, None, 0.95,
    ),
    _controlled_case(
        "c-match", "pt-c", False, "colorectal", "8140/3", "C18.0",
        "signed_out", 10, "spike", True, None, 0.85,
    ),
    _controlled_case(
        "g-match", "pt-g", False, "gastrointestinal", "8140/3", "C16.9",
        "signed_out", 15, "spike", True, None, 0.75,
    ),
    _controlled_case(
        "b-other", "pt-b", False, "thorax", "8070/3", "C34.9",
        "signed_out", 20, "mid", False, None, 0.55,
    ),
    _controlled_case(
        "d-other", "pt-d", False, "breast", "8500/3", "C50.2",
        "signed_out", 25, "mid", False, None, 0.45,
    ),
    _controlled_case(
        "e-other", "pt-e", False, "hematologic", "9680/3", "C83.3",
        "signed_out", 30, "mid", False, None, 0.35,
    ),
    _controlled_case(
        "f-other", "pt-f", False, "skin", "8720/3", "C43.9",
        "signed_out", 35, "mid", False, None, 0.25,
    ),
    _controlled_case(
        "real-prior", "pt-real", False, "thorax", "8070/3", "C34.1",
        "signed_out", 40, "mid", False, None, 0.15,
    ),
    _controlled_case(
        "q-real", "pt-real", False, "thorax", "8070/3", "C34.1",
        "open", 40, "none", False, "   ", 0.0,
    ),
)


def _load_controlled(database_url: str) -> None:
    encoders = build_text_encoders(backend=MockTextEncoder())
    query = np.asarray(encoders.encode_report_query(HISTORY).vector.to_float32(), dtype=np.float64)
    query = query / np.linalg.norm(query)
    with connect(database_url) as conn:
        conn.execute(
            """
            insert into pathologist (
                id, name, role_title, primary_specialty, secondary_specialties,
                is_demo_user, is_synthetic
            ) values ('path-eval', 'Dr Eval', 'Consultant', 'breast', '{}', false, true)
            """
        )
        seen: set[str] = set()
        for case in _CONTROLLED:
            if case.patient_id in seen:
                continue
            seen.add(case.patient_id)
            conn.execute(
                """
                insert into patient (id, display_label, sex, birth_year, is_synthetic_linkage)
                values (%s, %s, 'F', 1970, %s)
                """,
                (case.patient_id, case.patient_id.upper(), case.synthetic),
            )
        for case in _CONTROLLED:
            _insert_case(conn, case, query)
        conn.commit()


def _insert_case(conn: Connection, case: _Case, query: np.ndarray) -> None:
    held_out = case.status == "open"
    diagnosis = SECRET if held_out else "Fixture label"
    history = case.history
    conclusion = SECRET if held_out else (
        "zebraglobin marker in this synthetic passage."
        if case.keyword
        else "No marker in this synthetic passage."
    )
    report_status = "withheld" if held_out else "signed"
    signed_at = None if held_out else WHEN
    conn.execute(
        """
        insert into path_case (
            id, patient_id, specimen_label, source_dataset, source_case_id, specialty,
            patient_age, patient_sex, primary_diagnosis, morphology, icd10, status,
            assigned_to, accessioned_at, is_held_out, cohort_tier
        ) values (
            %s, %s, 'specimen', 'FIXTURE', %s, %s,
            60, 'F', %s, %s, %s, %s,
            'path-eval', %s, %s, 'demo'
        )
        """,
        (
            case.case_id,
            case.patient_id,
            case.case_id,
            case.specialty,
            diagnosis,
            case.morphology,
            case.icd10,
            case.status,
            WHEN,
            held_out,
        ),
    )
    conn.execute(
        """
        insert into slide (
            id, case_id, ordinal, stain, magnification, mpp, width, height,
            patch_size, patch_count, storage_key, thumb_pack_key, source_path,
            embedding, status
        ) values (
            %s, %s, 1, 'HE', 20, 0.5, 2048, 2048,
            512, %s, %s, %s, %s,
            %s, 'ready'
        )
        """,
        (
            f"{case.case_id}-s1",
            case.case_id,
            0 if case.patch == "none" else 3,
            f"slides/{case.case_id}.svs",
            f"thumbs/{case.case_id}.pack",
            f"slides/{case.case_id}.svs",
            HalfVector(_half_at(case.slide_deg)),
        ),
    )
    conn.execute(
        """
        insert into report (
            id, case_id, author_id, status, body, clinical_history, conclusion,
            icd10, signed_at
        ) values (%s, %s, 'path-eval', %s, %s, %s, %s, %s, %s)
        """,
        (
            f"{case.case_id}-r1",
            case.case_id,
            report_status,
            conclusion,
            history,
            conclusion,
            case.icd10,
            signed_at,
        ),
    )
    in_corpus = not held_out
    text = conclusion
    salt = abs(hash(case.case_id)) % 10_000
    vector = Vector(_near(query, case.cosine if in_corpus else 0.01, salt=salt))
    conn.execute(
        """
        insert into report_chunk (
            report_id, case_id, patient_id, specialty, section, ordinal, text,
            embedding, in_corpus
        ) values (%s, %s, %s, %s, 'conclusion', 0, %s, %s, %s)
        """,
        (
            f"{case.case_id}-r1",
            case.case_id,
            case.patient_id,
            case.specialty,
            text,
            vector,
            in_corpus,
        ),
    )
    if case.patch == "none":
        return
    degrees = [0.0, 90.0, 90.0] if case.patch == "spike" else [45.0, 45.0, 45.0]
    for index, degrees_value in enumerate(degrees):
        conn.execute(
            """
            insert into patch (
                slide_id, case_id, patient_id, specialty, x, y, size, embedding,
                in_corpus, thumb_offset, thumb_length
            ) values (%s, %s, %s, %s, %s, 0, 512, %s, true, 0, 1)
            """,
            (
                f"{case.case_id}-s1",
                case.case_id,
                case.patient_id,
                case.specialty,
                index * 512,
                HalfVector(_half_at(degrees_value)),
            ),
        )


def _half_at(degrees: float) -> list[float]:
    radians = math.radians(degrees)
    values = np.zeros(768, dtype=np.float64)
    values[0] = math.cos(radians)
    values[1] = math.sin(radians)
    values = values.astype(np.float16).astype(np.float64)
    values /= np.linalg.norm(values)
    values = values.astype(np.float16).astype(np.float64)
    values /= np.linalg.norm(values)
    return [float(value) for value in values]


def _near(query: np.ndarray, cosine: float, salt: int) -> list[float]:
    rng = np.random.default_rng(salt)
    noise = rng.standard_normal(query.shape[0])
    noise = noise - query * float(np.dot(noise, query))
    noise = noise / np.linalg.norm(noise)
    mixed = cosine * query + math.sqrt(max(0.0, 1.0 - cosine * cosine)) * noise
    mixed = mixed / np.linalg.norm(mixed)
    return [float(value) for value in np.asarray(mixed, dtype=np.float32)]
