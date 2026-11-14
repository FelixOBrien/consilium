"""Synthetic roster, concepts and fixture cohort.

`db seed` loads this module. The report pipeline (stage 7) imports
`ROSTER` and `CONCEPTS` from here as well, so both paths share one invented
roster. Names, patients and report text are invented in this repository.
Nothing here is copied from a TCGA report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

# Matches the API placeholder store and the missing `X-User-Id` fallback,
# which resolves the single `is_demo_user` row. The id is the documented example.
DEMO_USER_ID = "path-okafor"

SPECIALTIES = (
    "breast",
    "thorax",
    "colorectal",
    "gastrointestinal",
    "hematologic",
    "skin",
)

SECTION_ORDER = (
    "clinical_history",
    "gross_description",
    "microscopic_description",
    "conclusion",
    "additional_info",
)

# Heading spellings from report.md. Clinical history stops at the first of the later headings.
SECTION_HEADING = {
    "clinical_history": "Clinical History",
    "gross_description": "Gross Description",
    "microscopic_description": "Microscopic Description",
    "conclusion": "Conclusion",
    "additional_info": "Comment",
}

# CONCH-Z text tower cap. The API treats characters as a stand-in for tokens.
ENCODER_TEXT_LIMIT = 127

# Patch side at 20x. Both fixture slides use this magnification.
PATCH_SIZE = 512
MAGNIFICATION = 20.0
MPP = 0.5

FIXTURE_CREATED = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class PathologistSeed:
    id: str
    name: str
    role_title: str
    primary_specialty: str
    secondary_specialties: tuple[str, ...]
    is_demo_user: bool


@dataclass(frozen=True)
class ConceptSeed:
    id: str
    label: str
    prompt: str
    negative_prompt: str | None
    specialty: str | None
    ordinal: int


@dataclass(frozen=True)
class PatientSeed:
    id: str
    display_label: str
    sex: str
    birth_year: int
    is_synthetic_linkage: bool


@dataclass(frozen=True)
class SlideAsset:
    """One generated pyramidal TIFF reused by several fixture cases."""

    key: str
    storage_key: str
    width: int
    height: int
    salt: int


@dataclass(frozen=True)
class CaseSeed:
    source_case_id: str
    patient_id: str
    specialty: str
    specimen_label: str
    source_dataset: str
    patient_age: int
    patient_sex: str
    primary_diagnosis: str
    morphology: str
    icd10: str
    status: str
    assigned_to: str
    accessioned_at: datetime
    slide_key: str

    @property
    def id(self) -> str:
        return f"{self.specialty}-{self.source_case_id}"

    @property
    def is_held_out(self) -> bool:
        return self.status == "open"


# Two pathologists per specialty. Secondaries overlap so some report across organs.
# Exactly one demo user: Dr A. Okafor, the id documented in pathologist.md.
ROSTER: tuple[PathologistSeed, ...] = (
    PathologistSeed(
        "path-okafor",
        "Dr A. Okafor",
        "Consultant Histopathologist",
        "breast",
        ("skin",),
        True,
    ),
    PathologistSeed(
        "path-mensah",
        "Dr E. Mensah",
        "Consultant Histopathologist",
        "breast",
        ("gastrointestinal",),
        False,
    ),
    PathologistSeed(
        "path-adebayo",
        "Dr B. Adebayo",
        "Consultant Histopathologist",
        "thorax",
        ("hematologic",),
        False,
    ),
    PathologistSeed(
        "path-lindqvist",
        "Dr F. Lindqvist",
        "Consultant Histopathologist",
        "thorax",
        ("colorectal",),
        False,
    ),
    PathologistSeed(
        "path-nowak",
        "Dr C. Nowak",
        "Consultant Histopathologist",
        "colorectal",
        ("gastrointestinal",),
        False,
    ),
    PathologistSeed(
        "path-petrov",
        "Dr G. Petrov",
        "Consultant Histopathologist",
        "colorectal",
        ("breast",),
        False,
    ),
    PathologistSeed(
        "path-chen",
        "Dr H. Chen",
        "Consultant Histopathologist",
        "gastrointestinal",
        ("colorectal",),
        False,
    ),
    PathologistSeed(
        "path-rossi",
        "Dr I. Rossi",
        "Consultant Histopathologist",
        "gastrointestinal",
        ("breast",),
        False,
    ),
    PathologistSeed(
        "path-okonkwo",
        "Dr J. Okonkwo",
        "Consultant Histopathologist",
        "hematologic",
        ("thorax",),
        False,
    ),
    PathologistSeed(
        "path-bergstrom",
        "Dr K. Bergstrom",
        "Consultant Histopathologist",
        "hematologic",
        ("skin",),
        False,
    ),
    PathologistSeed(
        "path-singh",
        "Dr D. Singh",
        "Consultant Histopathologist",
        "skin",
        ("breast",),
        False,
    ),
    PathologistSeed(
        "path-moreau",
        "Dr L. Moreau",
        "Consultant Histopathologist",
        "skin",
        ("hematologic",),
        False,
    ),
)

# Twelve curated phrases. General concepts have a null specialty.
# Embeddings are filled when the fixture is loaded.
CONCEPTS: tuple[ConceptSeed, ...] = (
    ConceptSeed(
        "tumour-necrosis",
        "Necrosis",
        "an H&E image of tumour necrosis",
        "normal tissue",
        None,
        1,
    ),
    ConceptSeed(
        "mitotic-figures",
        "Mitoses",
        "an H&E image of mitotic figures",
        None,
        None,
        2,
    ),
    ConceptSeed(
        "lymphocytic-infiltrate",
        "Lymphocytes",
        "an H&E image of lymphocytic infiltrate",
        None,
        None,
        3,
    ),
    ConceptSeed(
        "fibrosis",
        "Fibrosis",
        "an H&E image of fibrosis",
        None,
        None,
        4,
    ),
    ConceptSeed(
        "mucin",
        "Mucin",
        "an H&E image of extracellular mucin",
        None,
        None,
        5,
    ),
    ConceptSeed(
        "glandular-differentiation",
        "Glands",
        "an H&E image of glandular differentiation",
        None,
        None,
        6,
    ),
    ConceptSeed(
        "breast-ducts",
        "Ducts",
        "an H&E image of breast ducts",
        None,
        "breast",
        7,
    ),
    ConceptSeed(
        "lepidic-growth",
        "Lepidic growth",
        "an H&E image of lepidic growth along alveolar walls",
        None,
        "thorax",
        8,
    ),
    ConceptSeed(
        "crypt-architecture",
        "Crypts",
        "an H&E image of colorectal crypt architecture",
        None,
        "colorectal",
        9,
    ),
    ConceptSeed(
        "signet-ring",
        "Signet ring",
        "an H&E image of signet ring cells",
        None,
        "gastrointestinal",
        10,
    ),
    ConceptSeed(
        "lymphoid-sheets",
        "Lymphoid sheets",
        "an H&E image of sheets of lymphoid cells",
        None,
        "hematologic",
        11,
    ),
    ConceptSeed(
        "melanin-pigment",
        "Melanin",
        "an H&E image of melanin pigment",
        None,
        "skin",
        12,
    ),
)

SLIDE_ASSETS: tuple[SlideAsset, ...] = (
    SlideAsset("rose", "slides/fixture-he-rose.svs", 2048, 1536, 1),
    SlideAsset("sage", "slides/fixture-he-sage.svs", 2560, 2048, 2),
)

PATIENTS: tuple[PatientSeed, ...] = (
    PatientSeed("pt-0042", "PT-0042", "F", 1965, True),
    PatientSeed("pt-0018", "PT-0018", "F", 1971, True),
    PatientSeed("pt-0033", "PT-0033", "M", 1959, True),
    PatientSeed("pt-0007", "PT-0007", "M", 1951, False),
    PatientSeed("pt-0019", "PT-0019", "M", 1963, False),
    PatientSeed("pt-0011", "PT-0011", "F", 1979, False),
    PatientSeed("pt-0024", "PT-0024", "M", 1949, False),
    PatientSeed("pt-0074", "PT-0074", "F", 1970, False),
)

def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 9, 0, tzinfo=UTC)


# Twelve cases, all six specialties. The demo user holds three open held-out cases
# (case.md rule 3; SKO-259 asked for these, including two). A fourth open case is
# assigned to the thorax lead so open work is spread across the roster by specialty.
# Two of the demo user's open cases belong to a patient with a signed-out prior.
# Longitudinal priors are 3–24 months earlier. Single-case dates sit in the
# 90 days before the November 2026 hackathon.
CASES: tuple[CaseSeed, ...] = (
    CaseSeed(
        "FX-B042A",
        "pt-0042",
        "breast",
        "Prior core biopsy",
        "TCGA-BRCA",
        60,
        "F",
        "Invasive carcinoma of no special type",
        "8500/3",
        "C50.9",
        "signed_out",
        "path-okafor",
        _at(2025, 8, 4),
        "rose",
    ),
    CaseSeed(
        "FX-B042B",
        "pt-0042",
        "breast",
        "Excision",
        "TCGA-BRCA",
        60,
        "F",
        "Invasive carcinoma of no special type",
        "8500/3",
        "C50.9",
        "signed_out",
        "path-okafor",
        _at(2026, 2, 16),
        "sage",
    ),
    CaseSeed(
        "FX-B042C",
        "pt-0042",
        "breast",
        "Recurrence excision",
        "TCGA-BRCA",
        61,
        "F",
        "Invasive carcinoma of no special type",
        "8500/3",
        "C50.9",
        "open",
        "path-okafor",
        _at(2026, 11, 2),
        "rose",
    ),
    CaseSeed(
        "FX-S018A",
        "pt-0018",
        "skin",
        "Prior excision",
        "TCGA-SKCM",
        54,
        "F",
        "Melanoma, NOS",
        "8720/3",
        "C43.9",
        "signed_out",
        "path-singh",
        _at(2025, 9, 10),
        "sage",
    ),
    CaseSeed(
        "FX-S018B",
        "pt-0018",
        "skin",
        "Re-excision",
        "TCGA-SKCM",
        55,
        "F",
        "Melanoma, NOS",
        "8720/3",
        "C43.9",
        "open",
        "path-okafor",
        _at(2026, 10, 20),
        "rose",
    ),
    CaseSeed(
        "FX-C033A",
        "pt-0033",
        "colorectal",
        "Prior biopsy",
        "TCGA-COAD",
        66,
        "M",
        "Adenocarcinoma, NOS",
        "8140/3",
        "C18.7",
        "signed_out",
        "path-nowak",
        _at(2025, 4, 8),
        "rose",
    ),
    CaseSeed(
        "FX-C033B",
        "pt-0033",
        "colorectal",
        "Resection",
        "TCGA-COAD",
        67,
        "M",
        "Adenocarcinoma, NOS",
        "8140/3",
        "C18.7",
        "signed_out",
        "path-nowak",
        _at(2026, 3, 18),
        "sage",
    ),
    CaseSeed(
        "FX-T007A",
        "pt-0007",
        "thorax",
        "Lung resection",
        "TCGA-LUAD",
        75,
        "M",
        "Adenocarcinoma, NOS",
        "8140/3",
        "C34.1",
        "signed_out",
        "path-adebayo",
        _at(2026, 8, 20),
        "rose",
    ),
    CaseSeed(
        "FX-T019A",
        "pt-0019",
        "thorax",
        "Lung biopsy",
        "TCGA-LUAD",
        63,
        "M",
        "Adenocarcinoma, NOS",
        "8140/3",
        "C34.1",
        "open",
        "path-adebayo",
        _at(2026, 9, 2),
        "sage",
    ),
    CaseSeed(
        "FX-G011A",
        "pt-0011",
        "gastrointestinal",
        "Distal gastrectomy",
        "TCGA-STAD",
        47,
        "F",
        "Adenocarcinoma, NOS",
        "8140/3",
        "C16.9",
        "signed_out",
        "path-mensah",
        _at(2026, 9, 16),
        "rose",
    ),
    CaseSeed(
        "FX-H024A",
        "pt-0024",
        "hematologic",
        "Lymph node excision",
        "TCGA-DLBC",
        77,
        "M",
        "Diffuse large B-cell lymphoma",
        "9680/3",
        "C83.3",
        "signed_out",
        "path-okonkwo",
        _at(2026, 10, 1),
        "sage",
    ),
    CaseSeed(
        "FX-B074A",
        "pt-0074",
        "breast",
        "Core biopsy",
        "TCGA-BRCA",
        56,
        "F",
        "Invasive carcinoma of no special type",
        "8500/3",
        "C50.9",
        "open",
        "path-okafor",
        _at(2026, 11, 10),
        "sage",
    ),
)

_ORGAN = {
    "breast": "breast",
    "thorax": "lung",
    "colorectal": "colon",
    "gastrointestinal": "stomach",
    "hematologic": "lymph node",
    "skin": "skin",
}

_MICROSCOPIC = {
    "breast": (
        "The cores show a gland-forming epithelial proliferation set in desmoplastic stroma. "
        "Small calcifications sit beside the glands. Skin is not included."
    ),
    "thorax": (
        "The fragments show an epithelial proliferation along alveolar spaces. "
        "Architecture is preserved at one edge of the sample."
    ),
    "colorectal": (
        "Mucosal fragments show crowded glands with luminal debris. "
        "Muscularis mucosae is present in the sections."
    ),
    "gastrointestinal": (
        "Sections of gastric wall show irregular glands in desmoplastic stroma. "
        "The change reaches the submucosa in this sample."
    ),
    "hematologic": (
        "The node is replaced by a sheet of large lymphoid cells with open nuclei. "
        "Residual follicles are not seen."
    ),
    "skin": (
        "The excision shows atypical melanocytes in the epidermis and the upper dermis. "
        "A peripheral margin is included in the block."
    ),
}


def report_sections(case: CaseSeed) -> dict[str, str]:
    """Invented section text. Clinical history stops before any diagnostic heading."""
    person = "woman" if case.patient_sex == "F" else "man"
    organ = _ORGAN[case.specialty]
    history = (
        f"A {case.patient_age}-year-old {person} was referred for histologic review of a "
        f"{case.specimen_label.lower()} from the {organ}. Imaging prompted the request. "
        "No diagnostic conclusion is stated in this history. "
        "Synthetic fixture text for the research prototype."
    )
    gross = (
        f"The specimen is labelled {case.specimen_label.lower()}. "
        "One sample was submitted entirely. Synthetic fixture description."
    )
    additional = (
        "Levels were examined. This comment is synthetic fixture text for retrieval tests "
        "and is not a clinical report."
    )
    conclusion = (
        "Synthetic fixture interpretation, not a clinical diagnosis: "
        f"{case.primary_diagnosis} ({case.morphology})."
    )
    return {
        "clinical_history": history,
        "gross_description": gross,
        "microscopic_description": _MICROSCOPIC[case.specialty],
        "conclusion": conclusion,
        "additional_info": additional,
    }


def slide_asset(key: str) -> SlideAsset:
    for asset in SLIDE_ASSETS:
        if asset.key == key:
            return asset
    raise KeyError(key)


def validate_seed_data() -> None:
    """Raise ValueError when the shared fixture breaks a model rule it is able to check."""
    if DEMO_USER_ID != "path-okafor":
        raise ValueError("demo user id must stay path-okafor so it matches the API store")
    if len(ROSTER) != 12:
        raise ValueError("roster must contain 12 pathologists")
    demo = [person for person in ROSTER if person.is_demo_user]
    if len(demo) != 1 or demo[0].id != DEMO_USER_ID:
        raise ValueError("exactly one demo user is required")
    by_specialty: dict[str, int] = dict.fromkeys(SPECIALTIES, 0)
    seen_ids: set[str] = set()
    for person in ROSTER:
        if person.id in seen_ids:
            raise ValueError(f"duplicate pathologist id {person.id}")
        seen_ids.add(person.id)
        if person.primary_specialty not in SPECIALTIES:
            raise ValueError(person.primary_specialty)
        if person.primary_specialty in person.secondary_specialties:
            raise ValueError(f"{person.id} repeats a primary specialty as secondary")
        if any(item not in SPECIALTIES for item in person.secondary_specialties):
            raise ValueError(f"{person.id} has an unknown secondary specialty")
        by_specialty[person.primary_specialty] += 1
        if not person.name.startswith("Dr "):
            raise ValueError(person.name)
    if any(count != 2 for count in by_specialty.values()):
        raise ValueError(f"expected two pathologists per specialty, got {by_specialty}")

    if len(CONCEPTS) < 10 or len(CONCEPTS) > 12:
        raise ValueError("expected about 10 to 12 concepts")
    ordinals = [concept.ordinal for concept in CONCEPTS]
    if len(set(ordinals)) != len(ordinals):
        raise ValueError("concept ordinals must be unique")
    covered = {concept.specialty for concept in CONCEPTS if concept.specialty is not None}
    if covered != set(SPECIALTIES):
        raise ValueError("each specialty needs at least one concept")
    for concept in CONCEPTS:
        if len(concept.prompt) > ENCODER_TEXT_LIMIT:
            raise ValueError(f"prompt too long: {concept.id}")
        negative = concept.negative_prompt
        if negative is not None and len(negative) > ENCODER_TEXT_LIMIT:
            raise ValueError(f"negative prompt too long: {concept.id}")
        if concept.specialty is not None and concept.specialty not in SPECIALTIES:
            raise ValueError(concept.specialty)

    if len(SLIDE_ASSETS) != 2:
        raise ValueError("fixture uses two generated slides")
    for asset in SLIDE_ASSETS:
        if asset.width % PATCH_SIZE or asset.height % PATCH_SIZE:
            raise ValueError(f"{asset.key} dimensions must be a multiple of the patch size")
        if min(asset.width, asset.height) < 1000:
            raise ValueError(f"{asset.key} must be a few thousand pixels across")

    if len(PATIENTS) != 8:
        raise ValueError("expected 8 patients")
    patients = {patient.id: patient for patient in PATIENTS}
    if len(patients) != len(PATIENTS):
        raise ValueError("duplicate patient id")
    if len(CASES) != 12:
        raise ValueError("expected 12 cases")
    specialties_seen = {case.specialty for case in CASES}
    if specialties_seen != set(SPECIALTIES):
        raise ValueError("cases must cover every specialty")

    by_patient: dict[str, list[CaseSeed]] = {patient.id: [] for patient in PATIENTS}
    source_keys: set[tuple[str, str]] = set()
    for case in CASES:
        if case.patient_id not in patients:
            raise ValueError(f"case {case.id} has no patient")
        if case.assigned_to not in seen_ids:
            raise ValueError(case.assigned_to)
        if (case.status == "open") != case.is_held_out:
            raise ValueError(case.id)
        if case.patient_sex != patients[case.patient_id].sex:
            raise ValueError(f"sex mismatch on {case.id}")
        source_key = (case.source_dataset, case.source_case_id)
        if source_key in source_keys:
            raise ValueError(f"duplicate source key {source_key}")
        source_keys.add(source_key)
        by_patient[case.patient_id].append(case)

    multi = 0
    open_cases = [case for case in CASES if case.status == "open"]
    demo_open = [case for case in open_cases if case.assigned_to == DEMO_USER_ID]
    if len(demo_open) < 3:
        raise ValueError("demo user must receive at least three open cases")
    if len({case.assigned_to for case in open_cases}) < 2:
        raise ValueError("open cases must be assigned across the roster")
    roster = {person.id: person for person in ROSTER}
    for case in open_cases:
        person = roster[case.assigned_to]
        covered_by = (person.primary_specialty, *person.secondary_specialties)
        if case.specialty not in covered_by:
            raise ValueError(f"{case.id} is outside the assignee specialty")

    longitudinal_open = 0
    for patient_id, group in by_patient.items():
        if not group:
            raise ValueError(f"patient {patient_id} has no case")
        patient = patients[patient_id]
        ordered = sorted(group, key=lambda item: item.accessioned_at)
        if len(ordered) >= 2:
            multi += 1
            if not patient.is_synthetic_linkage:
                raise ValueError(f"{patient_id} links multiple cases and must be marked synthetic")
        elif patient.is_synthetic_linkage:
            raise ValueError(f"{patient_id} is a single case and is not a synthetic linkage")
        ages = [item.patient_age for item in ordered]
        if ages != sorted(ages):
            raise ValueError(f"age is not monotonic for {patient_id}")
        earliest = ordered[0]
        if patient.birth_year != earliest.accessioned_at.year - earliest.patient_age:
            raise ValueError(f"birth year does not match the earliest case of {patient_id}")
        for previous, current in zip(ordered, ordered[1:], strict=False):
            gap_days = (current.accessioned_at - previous.accessioned_at).days
            if gap_days < 90 or gap_days > 730:
                raise ValueError(f"longitudinal spacing out of range for {patient_id}")
        if any(item.status == "open" for item in ordered) and any(
            item.status == "signed_out" for item in ordered
        ):
            longitudinal_open += 1
            if ordered[-1].status != "open":
                raise ValueError(f"open case is not the latest for {patient_id}")
    if multi < 3:
        raise ValueError("expected at least 3 multi-case patients")
    if longitudinal_open < 1:
        raise ValueError("an open case must belong to a patient with a signed-out prior")

    for case in CASES:
        sections = report_sections(case)
        history = sections["clinical_history"]
        if case.primary_diagnosis in history or case.morphology in history:
            raise ValueError(f"clinical history leaks the diagnosis of {case.id}")
        if "Conclusion" in history or "Gross Description" in history:
            raise ValueError(f"clinical history runs past its heading on {case.id}")
        for text in sections.values():
            if len(text.split()) > 200:
                raise ValueError("fixture sections must stay within one chunk")
            if not text.strip():
                raise ValueError("empty section")
