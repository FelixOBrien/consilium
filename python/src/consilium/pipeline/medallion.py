"""Rule checks for the silver layer of the medallion notebook.

The Databricks notebook applies the same rules in Spark and prints the same
counts. Nothing here is dropped: a violation is counted so the gold tables
stay aligned with the parquet that produced them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import pyarrow as pa

from consilium.pipeline.cohort import SPECIALTY_ORDER  # pragma: allowlist secret

UNIT_NORM_ATOL = 1e-2
CONCHZ_DIM = 768
REPORT_DIM = 384

SPECIALTIES = frozenset(SPECIALTY_ORDER)
RULES: tuple[str, ...] = (
    "non_empty_id",
    "valid_specialty",
    "unit_norm",
    "in_corpus",
    "positive_dimension",
    "duplicate_natural_key",
)
MODELS: tuple[str, ...] = (
    "pathologist",
    "patient",
    "concept",
    "path_case",
    "slide",
    "report",
    "report_chunk",
    "patch",
)

_NATURAL_KEY: dict[str, tuple[str, ...]] = {
    "pathologist": ("id",),
    "patient": ("id",),
    "concept": ("id",),
    "path_case": ("id",),
    "slide": ("id",),
    "report": ("id",),
    "report_chunk": ("report_id", "ordinal"),
    "patch": ("slide_id", "x", "y"),
}
_TEXT_IDS: dict[str, tuple[str, ...]] = {
    "pathologist": ("id",),
    "patient": ("id",),
    "concept": ("id",),
    "path_case": ("id", "patient_id", "assigned_to"),
    "slide": ("id", "case_id"),
    "report": ("id", "case_id", "author_id"),
    "report_chunk": ("report_id", "case_id", "patient_id"),
    "patch": ("slide_id", "case_id", "patient_id"),
}


def violation_counts(
    tables: Mapping[str, pa.Table],
) -> dict[str, dict[str, int]]:
    """Count model-doc violations per pipeline table. Missing tables are skipped."""
    cases = _cases(tables.get("path_case"))
    counts: dict[str, dict[str, int]] = {}
    for model in MODELS:
        table = tables.get(model)
        if table is None:
            continue
        rows = table.to_pylist()
        counts[model] = {
            "non_empty_id": _non_empty(model, rows),
            "valid_specialty": _specialties(model, rows),
            "unit_norm": _unit_norms(model, rows),
            "in_corpus": _corpus(model, rows, cases),
            "positive_dimension": _dimensions(model, rows),
            "duplicate_natural_key": _duplicates(model, rows),
        }
    return counts


def format_violations(counts: Mapping[str, Mapping[str, int]]) -> str:
    """Plain table of rule-violation counts, suitable for a notebook cell."""
    lines = [f"{'table':<16} {'rule':<24} {'violations':>12}"]
    total = 0
    for model in MODELS:
        rules = counts.get(model)
        if rules is None:
            continue
        for rule in RULES:
            value = int(rules.get(rule, 0))
            total += value
            lines.append(f"{model:<16} {rule:<24} {value:12d}")
    lines.append(f"violation_total {total}")
    return "\n".join(lines) + "\n"


def _cases(table: pa.Table | None) -> dict[str, tuple[str, bool]]:
    if table is None:
        return {}
    found: dict[str, tuple[str, bool]] = {}
    for row in table.to_pylist():
        case_id = _text(row.get("id"))
        if case_id == "":
            continue
        found[case_id] = (str(row.get("status") or "").strip(), bool(row.get("is_held_out")))
    return found


def _non_empty(model: str, rows: Sequence[Mapping[str, object]]) -> int:
    columns = _TEXT_IDS[model]
    violations = 0
    for row in rows:
        if any(_text(row.get(column)) == "" for column in columns):
            violations += 1
    return violations


def _specialties(model: str, rows: Sequence[Mapping[str, object]]) -> int:
    violations = 0
    for row in rows:
        if model == "pathologist":
            if str(row.get("primary_specialty") or "").strip() not in SPECIALTIES:
                violations += 1
                continue
            secondary = row.get("secondary_specialties") or []
            if any(str(item).strip() not in SPECIALTIES for item in secondary):
                violations += 1
        elif model == "concept":
            specialty = row.get("specialty")
            if specialty is not None and str(specialty).strip() not in SPECIALTIES:
                violations += 1
        elif model in {"path_case", "patch", "report_chunk"}:
            if str(row.get("specialty") or "").strip() not in SPECIALTIES:
                violations += 1
    return violations


def _unit_norms(model: str, rows: Sequence[Mapping[str, object]]) -> int:
    violations = 0
    for row in rows:
        if model == "patch" and _bad_vector(row.get("embedding"), CONCHZ_DIM, required=True):
            violations += 1
        elif model == "report_chunk" and _bad_vector(
            row.get("embedding"), REPORT_DIM, required=True
        ):
            violations += 1
        elif model == "slide":
            required = str(row.get("status") or "") == "ready"
            if _bad_vector(row.get("embedding"), CONCHZ_DIM, required=required):
                violations += 1
        elif model == "concept":
            bad = _bad_vector(row.get("embedding"), CONCHZ_DIM, required=True)
            negative = row.get("negative_prompt")
            needs_negative = negative is not None and str(negative).strip() != ""
            if _bad_vector(row.get("negative_embedding"), CONCHZ_DIM, required=needs_negative):
                bad = True
            if bad:
                violations += 1
    return violations


def _corpus(
    model: str,
    rows: Sequence[Mapping[str, object]],
    cases: Mapping[str, tuple[str, bool]],
) -> int:
    if model not in {"patch", "report_chunk"}:
        return 0
    violations = 0
    for row in rows:
        case_id = _text(row.get("case_id"))
        case = cases.get(case_id)
        if case is None:
            violations += 1
            continue
        status, held = case
        expected = status == "signed_out" and not held
        if bool(row.get("in_corpus")) is not expected:
            violations += 1
    return violations


def _dimensions(model: str, rows: Sequence[Mapping[str, object]]) -> int:
    violations = 0
    for row in rows:
        if model == "slide":
            bad = any(
                _positive(row.get(name)) is False
                for name in ("width", "height", "patch_size", "magnification", "mpp")
            )
            ordinal = row.get("ordinal")
            if ordinal is not None and _number(ordinal) is not None and _number(ordinal) < 1:
                bad = True
            if bad:
                violations += 1
        elif model == "patch":
            bad = _positive(row.get("size")) is False or _positive(row.get("thumb_length")) is False
            for name in ("x", "y"):
                value = _number(row.get(name))
                if value is None or value < 0:
                    bad = True
            if bad:
                violations += 1
    return violations


def _duplicates(model: str, rows: Sequence[Mapping[str, object]]) -> int:
    keys = _NATURAL_KEY[model]
    seen: set[tuple[object, ...]] = set()
    duplicates = 0
    for row in rows:
        identity = tuple(row.get(key) for key in keys)
        if any(part is None or (isinstance(part, str) and part.strip() == "") for part in identity):
            continue
        if identity in seen:
            duplicates += 1
        else:
            seen.add(identity)
    return duplicates


def _bad_vector(value: object, dim: int, *, required: bool) -> bool:
    if value is None:
        return required
    try:
        numbers = [float(item) for item in value]  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True
    if len(numbers) != dim or any(not math.isfinite(item) for item in numbers):
        return True
    norm = math.sqrt(sum(item * item for item in numbers))
    return abs(norm - 1.0) > UNIT_NORM_ATOL


def _positive(value: object) -> bool | None:
    number = _number(value)
    if number is None:
        return False
    return number > 0


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
