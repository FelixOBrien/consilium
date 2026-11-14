"""Synthetic pathologist roster for stage 7.

The built-in roster is used when no shared roster file is present. A file
written by the fixture seed (``data/roster.json`` beside the package, or under the data root)
wins, so both jobs share one set of ids. Names are invented. Exactly one
member is the demo user, and that id matches ``api.store.DEMO_USER_ID``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from consilium.pipeline.cohort import SPECIALTY_ORDER  # pragma: allowlist secret

# Same default as api.store.DEMO_USER_ID (the X-User-Id fallback).
DEFAULT_DEMO_USER_ID = "path-okafor"

_ROLE = "Consultant Histopathologist"

# Lead is listed before the second pathologist of each specialty.
# Secondary specialties overlap so a few reports can be signed outside
# the author's main organ.
_BUILTIN: tuple[tuple[str, str, str, tuple[str, ...], bool], ...] = (
    ("path-okafor", "Dr A. Okafor", "breast", ("skin",), True),
    ("path-brennan", "Dr E. Brennan", "breast", (), False),
    ("path-adebayo", "Dr B. Adebayo", "thorax", (), False),
    ("path-vogel", "Dr F. Vogel", "thorax", ("breast",), False),
    ("path-nowak", "Dr C. Nowak", "colorectal", ("gastrointestinal",), False),
    ("path-ellis", "Dr G. Ellis", "colorectal", (), False),
    ("path-hassan", "Dr H. Hassan", "gastrointestinal", ("colorectal",), False),
    ("path-berg", "Dr I. Berg", "gastrointestinal", (), False),
    ("path-cho", "Dr J. Cho", "hematologic", (), False),
    ("path-diaz", "Dr K. Diaz", "hematologic", ("thorax",), False),
    ("path-singh", "Dr D. Singh", "skin", ("breast",), False),
    ("path-moreau", "Dr L. Moreau", "skin", ("hematologic",), False),
)


@dataclass(frozen=True)
class RosterMember:
    """One synthetic pathologist. `is_synthetic` is always true."""

    id: str
    name: str
    role_title: str
    primary_specialty: str
    secondary_specialties: tuple[str, ...]
    is_demo_user: bool
    is_synthetic: bool = True

    def covers(self, specialty: str) -> bool:
        return specialty == self.primary_specialty or specialty in self.secondary_specialties


def builtin_roster() -> tuple[RosterMember, ...]:
    """The canonical 12-pathologist roster, two per specialty."""
    members = [
        RosterMember(
            id=member_id,
            name=name,
            role_title=_ROLE,
            primary_specialty=specialty,
            secondary_specialties=secondary,
            is_demo_user=demo,
        )
        for member_id, name, specialty, secondary, demo in _BUILTIN
    ]
    validate_roster(members)
    return tuple(members)


def validate_roster(members: Sequence[RosterMember]) -> None:
    """Reject a roster that cannot drive authorship or the demo identity."""
    if not members:
        raise ValueError("roster is empty")
    ids = [member.id for member in members]
    if len(ids) != len(set(ids)):
        raise ValueError("roster ids must be unique")
    demos = [member for member in members if member.is_demo_user]
    if len(demos) != 1:
        raise ValueError("roster must have exactly one is_demo_user")
    allowed = set(SPECIALTY_ORDER)
    for member in members:
        if not member.is_synthetic:
            raise ValueError(f"{member.id} must be synthetic")
        if not member.id.startswith("path-") or not member.name.strip():
            raise ValueError(f"invalid roster member {member.id}")
        if member.primary_specialty not in allowed:
            raise ValueError(f"{member.id} has unknown specialty {member.primary_specialty}")
        for specialty in member.secondary_specialties:
            if specialty not in allowed:
                raise ValueError(f"{member.id} has unknown secondary specialty {specialty}")
            if specialty == member.primary_specialty:
                raise ValueError(f"{member.id} repeats {specialty} as a secondary specialty")
    for specialty in SPECIALTY_ORDER:
        primaries = [member for member in members if member.primary_specialty == specialty]
        if len(primaries) < 1:
            raise ValueError(f"roster has no pathologist for {specialty}")


def load_roster_file(path: Path) -> tuple[RosterMember, ...]:
    """Load a JSON list of roster objects. Every member must be synthetic."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must be a JSON list of pathologists")
    members: list[RosterMember] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"{path} has a non-object roster row")
        secondary = item.get("secondary_specialties") or []
        if isinstance(secondary, str) or not isinstance(secondary, list):
            raise ValueError(f"{path} secondary_specialties must be a list")
        members.append(
            RosterMember(
                id=str(item.get("id") or "").strip(),
                name=str(item.get("name") or "").strip(),
                role_title=str(item.get("role_title") or _ROLE).strip() or _ROLE,
                primary_specialty=str(item.get("primary_specialty") or "").strip(),
                secondary_specialties=tuple(str(value) for value in secondary),
                is_demo_user=bool(item.get("is_demo_user")),
                is_synthetic=bool(item.get("is_synthetic", True)),
            )
        )
    validate_roster(members)
    return tuple(members)


def resolve_roster(
    data_root: Path,
    explicit: Path | None = None,
) -> tuple[tuple[RosterMember, ...], str]:
    """Return the roster and a short source label (`file` or `builtin`).

    Search order: `--roster`, `<data-root>/roster.json`, then the package
    data file the fixture seed is expected to write.
    """
    if explicit is not None:
        if not explicit.is_file():
            raise ValueError(f"roster file not found: {explicit}")
        return load_roster_file(explicit), "file"
    package_data = Path(__file__).resolve().parents[1] / "data" / "roster.json"
    for candidate in (data_root / "roster.json", package_data):
        if candidate.is_file() and candidate.stat().st_size > 0:
            return load_roster_file(candidate), "file"
    return builtin_roster(), "builtin"


def demo_member(roster: Sequence[RosterMember]) -> RosterMember:
    matches = [member for member in roster if member.is_demo_user]
    if len(matches) != 1:
        raise ValueError("roster must have exactly one is_demo_user")
    return matches[0]


def author_slots(signed_count: int, *, has_second: bool, has_cross: bool) -> tuple[int, int, int]:
    """Split signed reports into `(lead, second, cross)` counts.

    The lead has strictly more than the second whenever there are at least
    three signed reports. Cross-cover starts once a specialty has four, so a
    few reports go to a pathologist whose secondary specialty matches.
    """
    if signed_count <= 0:
        return 0, 0, 0
    if not has_second or signed_count == 1:
        return signed_count, 0, 0
    if signed_count == 2:
        return 2, 0, 0
    cross_count = 0
    if has_cross and signed_count >= 4:
        cross_count = max(1, round(0.10 * signed_count)) if signed_count >= 10 else 1
    lead_count, second_count, cross_count = _fit_slots(signed_count, cross_count)
    if second_count < 1 or lead_count <= second_count:
        lead_count, second_count, cross_count = _fit_slots(signed_count, 0)
    if lead_count + second_count + cross_count != signed_count:
        raise ValueError("authorship slots do not cover the signed reports")
    if signed_count >= 3 and lead_count <= second_count:
        raise ValueError("lead pathologist must sign more reports than the second")
    return lead_count, second_count, cross_count


def _fit_slots(signed_count: int, cross_count: int) -> tuple[int, int, int]:
    rest = signed_count - cross_count
    second_count = max(1, rest // 3)
    lead_count = rest - second_count
    if lead_count <= second_count:
        second_count = max(1, (rest - 1) // 2)
        lead_count = rest - second_count
        if lead_count <= second_count and second_count > 0:
            second_count -= 1
            lead_count += 1
    return lead_count, second_count, cross_count


def assign_authors(
    roster: Sequence[RosterMember],
    cases: Sequence[tuple[str, str, bool]],
) -> dict[str, str]:
    """Map `case_id` to a pathologist id.

    `cases` is `(case_id, specialty, held_out)`. Signed reports are skewed
    inside each specialty. Open cases are spread by specialty, and the demo
    user receives `min(3, open count)` of them.
    """
    validate_roster(roster)
    by_specialty: dict[str, list[tuple[str, bool]]] = {name: [] for name in SPECIALTY_ORDER}
    for case_id, specialty, held_out in cases:
        if specialty not in by_specialty:
            raise ValueError(f"unknown specialty {specialty}")
        by_specialty[specialty].append((case_id, held_out))

    assigned: dict[str, str] = {}
    open_cases: list[tuple[str, str]] = []
    for specialty in SPECIALTY_ORDER:
        rows = by_specialty[specialty]
        signed_ids = sorted(case_id for case_id, held_out in rows if not held_out)
        open_cases.extend((case_id, specialty) for case_id, held_out in rows if held_out)
        if not signed_ids:
            continue
        primaries = [member for member in roster if member.primary_specialty == specialty]
        lead = primaries[0]
        second = primaries[1] if len(primaries) > 1 else None
        excluded = {lead.id, second.id} if second is not None else {lead.id}
        cross = [
            member
            for member in roster
            if specialty in member.secondary_specialties and member.id not in excluded
        ]
        lead_n, second_n, cross_n = author_slots(
            len(signed_ids),
            has_second=second is not None,
            has_cross=bool(cross),
        )
        cursor = 0
        for case_id in signed_ids[cursor : cursor + lead_n]:
            assigned[case_id] = lead.id
        cursor += lead_n
        if second is not None:
            for case_id in signed_ids[cursor : cursor + second_n]:
                assigned[case_id] = second.id
            cursor += second_n
        for offset, case_id in enumerate(signed_ids[cursor : cursor + cross_n]):
            assigned[case_id] = cross[offset % len(cross)].id

    demo = demo_member(roster)
    quota = min(3, len(open_cases))
    ordered = sorted(
        open_cases,
        key=lambda item: (
            0 if item[1] == demo.primary_specialty else 1,
            SPECIALTY_ORDER.index(item[1]),
            item[0],
        ),
    )
    for index, (case_id, specialty) in enumerate(ordered):
        if index < quota:
            assigned[case_id] = demo.id
            continue
        primaries = [member for member in roster if member.primary_specialty == specialty]
        lead = primaries[0]
        second = primaries[1] if len(primaries) > 1 else None
        if lead.id != demo.id:
            assigned[case_id] = lead.id
        elif second is not None:
            assigned[case_id] = second.id
        else:
            assigned[case_id] = lead.id
    if len(assigned) != len(cases):
        raise ValueError("every case must be assigned a pathologist")
    return assigned
