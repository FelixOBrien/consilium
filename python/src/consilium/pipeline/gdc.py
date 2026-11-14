"""Read open-access TCGA diagnostic slides and clinical cases from the GDC API.

Checked against live `files` and `cases` payloads on 14 Nov 2026. See
`docs/context.md`. `samples.is_ffpe` and `demographic.gender` are not fields.
FFPE is `samples.preservation_method`. Sex is `demographic.sex_at_birth`
(`female` or `male`).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from consilium.pipeline.cohort import PROJECT_SPECIALTY, TARGET_PROJECTS  # pragma: allowlist secret

GDC_BASE_URL = "https://api.gdc.cancer.gov"
PAGE_SIZE = 2000

_USER_AGENT = "cohort-manifest/0.1 (research prototype; not for clinical use)"

_NOT_REPORTED = frozenset({"", "not reported", "unknown", "na", "n/a", "none"})

SLIDE_FIELDS = ",".join(
    (
        "file_id",
        "file_name",
        "file_size",
        "data_format",
        "access",
        "experimental_strategy",
        "data_type",
        "cases.submitter_id",
        "cases.case_id",
        "cases.project.project_id",
        "cases.samples.sample_type",
        "cases.samples.submitter_id",
        "cases.samples.preservation_method",
    )
)

CASE_FIELDS = ",".join(
    (
        "submitter_id",
        "case_id",
        "project.project_id",
        "demographic.sex_at_birth",
        "demographic.age_at_index",
        "demographic.days_to_birth",
        "diagnoses.primary_diagnosis",
        "diagnoses.morphology",
        "diagnoses.classification_of_tumor",
        "diagnoses.icd_10_code",
        "diagnoses.age_at_diagnosis",
    )
)


def slide_filters(projects: Sequence[str] = TARGET_PROJECTS) -> dict[str, Any]:
    """Open TCGA diagnostic slide images in the target projects."""
    return {
        "op": "and",
        "content": [
            {"op": "in", "content": {"field": "cases.project.project_id", "value": list(projects)}},
            {"op": "=", "content": {"field": "data_type", "value": "Slide Image"}},
            {"op": "=", "content": {"field": "experimental_strategy", "value": "Diagnostic Slide"}},
            {"op": "=", "content": {"field": "access", "value": "open"}},
        ],
    }


def case_filters(projects: Sequence[str] = TARGET_PROJECTS) -> dict[str, Any]:
    return {
        "op": "in",
        "content": {"field": "project.project_id", "value": list(projects)},
    }


@dataclass(frozen=True)
class SlideFile:
    file_id: str
    file_name: str
    file_size: int
    project_id: str
    submitter_id: str
    slide_kind: str
    slide_number: int | None
    preservation_methods: tuple[str, ...]
    data_format: str


@dataclass(frozen=True)
class ClinicalCase:
    submitter_id: str
    gdc_case_id: str
    project_id: str
    patient_sex: str | None
    patient_age: int | None
    primary_diagnosis: str | None
    morphology: str | None
    icd10: str | None
    classification_of_tumor: str | None


class GdcClient:
    """POST JSON to the GDC REST API and follow `from`/`size` pages."""

    def __init__(
        self,
        *,
        base_url: str = GDC_BASE_URL,
        timeout: float = 120.0,
        page_size: int = PAGE_SIZE,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.page_size = page_size
        self._opener = opener or urllib.request.build_opener()

    def fetch_slides(self) -> list[dict[str, Any]]:
        return self._fetch_all("files", slide_filters(), SLIDE_FIELDS)

    def fetch_cases(self) -> list[dict[str, Any]]:
        return self._fetch_all("cases", case_filters(), CASE_FIELDS)

    def _fetch_all(
        self,
        endpoint: str,
        filters: Mapping[str, Any],
        fields: str,
    ) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        start = 0
        total: int | None = None
        while total is None or start < total:
            page = self._post(
                endpoint,
                {"filters": filters, "fields": fields, "size": self.page_size, "from": start},
            )
            data = page.get("data")
            if not isinstance(data, dict):
                raise RuntimeError(f"GDC {endpoint} response has no data object")
            batch = data.get("hits")
            pagination = data.get("pagination") or {}
            if not isinstance(batch, list) or not isinstance(pagination, dict):
                raise RuntimeError(f"GDC {endpoint} response is missing hits")
            total = int(pagination.get("total", len(batch)))
            for item in batch:
                hits.append(item if isinstance(item, dict) else {})
            if not batch:
                break
            start += len(batch)
        return hits

    def _post(self, endpoint: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"GDC {endpoint} returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GDC {endpoint} request failed: {exc.reason}") from exc
        try:
            parsed = json.loads(raw.decode())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"GDC {endpoint} returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"GDC {endpoint} returned a non-object")
        warnings = parsed.get("warnings") or {}
        if isinstance(warnings, dict) and warnings.get("fields"):
            raise RuntimeError(f"GDC {endpoint} rejected fields: {warnings['fields']}")
        return parsed


def parse_slide(hit: object) -> tuple[SlideFile | None, str | None]:
    """Return a slide, or `(None, "corrupt_slide")` when the hit is unusable."""
    if not isinstance(hit, dict) or not hit:
        return None, "corrupt_slide"
    file_id = hit.get("file_id") or hit.get("id")
    file_name = hit.get("file_name")
    file_size = hit.get("file_size")
    if not isinstance(file_id, str) or not file_id.strip():
        return None, "corrupt_slide"
    if not isinstance(file_name, str) or not file_name.strip():
        return None, "corrupt_slide"
    if isinstance(file_size, bool) or not isinstance(file_size, int) or file_size < 0:
        return None, "corrupt_slide"
    case = _pick_case(hit.get("cases"))
    if case is None:
        return None, "corrupt_slide"
    submitter = str(case.get("submitter_id") or "").strip().upper()
    project = _project_id(case)
    if not submitter or not project:
        return None, "corrupt_slide"
    kind, number = _slide_code(file_name)
    data_format = hit.get("data_format")
    return (
        SlideFile(
            file_id=file_id.strip(),
            file_name=file_name.strip(),
            file_size=file_size,
            project_id=project,
            submitter_id=submitter,
            slide_kind=kind,
            slide_number=number,
            preservation_methods=_preservation_methods(case),
            data_format=data_format.strip().upper() if isinstance(data_format, str) else "",
        ),
        None,
    )


def parse_case(hit: object) -> ClinicalCase | None:
    """Return clinical fields, or None when the hit has no submitter id."""
    if not isinstance(hit, dict) or not hit:
        return None
    submitter = str(hit.get("submitter_id") or "").strip().upper()
    if not submitter:
        return None
    case_id = hit.get("case_id") or hit.get("id") or ""
    gdc_case_id = case_id.strip() if isinstance(case_id, str) else ""
    diagnosis = _primary_diagnosis(hit.get("diagnoses"))
    demographic = hit.get("demographic") if isinstance(hit.get("demographic"), dict) else {}
    if diagnosis is None:
        return ClinicalCase(
            submitter_id=submitter,
            gdc_case_id=gdc_case_id,
            project_id=_project_id(hit),
            patient_sex=_map_sex(demographic.get("sex_at_birth")),
            patient_age=_map_age(demographic, None),
            primary_diagnosis=None,
            morphology=None,
            icd10=None,
            classification_of_tumor=None,
        )
    return ClinicalCase(
        submitter_id=submitter,
        gdc_case_id=gdc_case_id,
        project_id=_project_id(hit),
        patient_sex=_map_sex(demographic.get("sex_at_birth")),
        patient_age=_map_age(demographic, diagnosis),
        primary_diagnosis=_reported(diagnosis.get("primary_diagnosis")),
        morphology=_reported(diagnosis.get("morphology")),
        icd10=_reported(diagnosis.get("icd_10_code")),
        classification_of_tumor=_reported(diagnosis.get("classification_of_tumor")) or "primary",
    )


def index_cases(hits: Sequence[object]) -> tuple[dict[str, ClinicalCase], int]:
    """First clinical record per submitter, in `(submitter_id, gdc_case_id)` order."""
    parsed: list[ClinicalCase] = []
    corrupt = 0
    for hit in hits:
        case = parse_case(hit)
        if case is None:
            corrupt += 1
            continue
        parsed.append(case)
    parsed.sort(key=lambda case: (case.submitter_id, case.gdc_case_id))
    indexed: dict[str, ClinicalCase] = {}
    for case in parsed:
        if case.submitter_id not in indexed:
            indexed[case.submitter_id] = case
    return indexed, corrupt


def _pick_case(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, list):
        return None
    dicts = [item for item in raw if isinstance(item, dict)]
    if not dicts:
        return None

    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        project = _project_id(item)
        known = 0 if project in PROJECT_SPECIALTY else 1
        return (known, str(item.get("submitter_id") or ""))

    return sorted(dicts, key=sort_key)[0]


def _project_id(case: Mapping[str, Any]) -> str:
    project = case.get("project")
    if not isinstance(project, dict):
        return ""
    value = project.get("project_id")
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _preservation_methods(case: Mapping[str, Any]) -> tuple[str, ...]:
    samples = case.get("samples")
    if not isinstance(samples, list):
        return ()
    methods: list[str] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        method = sample.get("preservation_method")
        if isinstance(method, str) and method.strip():
            methods.append(method.strip())
    return tuple(methods)


def _slide_code(file_name: str) -> tuple[str, int | None]:
    # TCGA-XX-XXXX-01Z-00-DX1.<uuid>.svs
    parts = file_name.upper().split(".")[0].split("-")
    if len(parts) < 6:
        return "", None
    code = parts[5]
    prefix = "".join(char for char in code if char.isalpha())
    digits = "".join(char for char in code if char.isdigit())
    if prefix not in {"DX", "TS", "BS"} or not digits:
        return "", None
    return prefix, int(digits)


def _reported(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.casefold() in _NOT_REPORTED:
        return None
    return text


def _primary_diagnosis(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, list):
        return None
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        classification = str(item.get("classification_of_tumor") or "").strip().casefold()
        if classification != "primary":
            continue
        if _reported(item.get("primary_diagnosis")) is None:
            continue
        morphology = _reported(item.get("morphology"))
        icd = _reported(item.get("icd_10_code"))
        ranked.append((0 if morphology and icd else 1, index, item))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][2]


def _map_sex(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().casefold()
    if token in {"female", "f"}:
        return "F"
    if token in {"male", "m"}:
        return "M"
    return None


def _map_age(demographic: Mapping[str, Any], diagnosis: Mapping[str, Any] | None) -> int | None:
    age = demographic.get("age_at_index")
    if _is_number(age) and age >= 0:
        return int(age)
    days_to_birth = demographic.get("days_to_birth")
    if _is_number(days_to_birth) and days_to_birth < 0:
        return int(round(-days_to_birth / 365.25))
    if diagnosis is not None:
        days = diagnosis.get("age_at_diagnosis")
        if _is_number(days) and days > 0:
            return int(round(days / 365.25))
    return None


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
