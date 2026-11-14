"""Turn-scoped citation allowlist.

A case id may be cited only when a precedent tool in this turn returned it,
or an attachment was checked in SQL as signed-out corpus precedent.
Invented, open, held-out and own-case ids are unlinked before save.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN = re.compile(r"\[case:([A-Za-z0-9][A-Za-z0-9._-]*)\]")
# An unfinished `[case:...]` at the end of a stream chunk. Held until it closes.
_PARTIAL = re.compile(r"\[(?:c(?:a(?:s(?:e(?::[A-Za-z0-9._-]*)?)?)?)?)?$")


@dataclass(frozen=True)
class AllowedCase:
    case_id: str
    patient_id: str
    same_patient: bool
    slide_id: str | None = None
    patch_id: int | None = None
    quote: str | None = None


class Allowlist:
    def __init__(self) -> None:
        self.cases: dict[str, AllowedCase] = {}

    def add(self, meta: AllowedCase) -> None:
        current = self.cases.get(meta.case_id)
        if current is None:
            self.cases[meta.case_id] = meta
            return
        self.cases[meta.case_id] = AllowedCase(
            case_id=meta.case_id,
            patient_id=current.patient_id,
            same_patient=current.same_patient,
            slide_id=current.slide_id or meta.slide_id,
            patch_id=current.patch_id if current.patch_id is not None else meta.patch_id,
            quote=current.quote or meta.quote,
        )

    def __contains__(self, case_id: object) -> bool:
        return isinstance(case_id, str) and case_id in self.cases


def unlink_unknown(text: str, allowed: Allowlist) -> str:
    """Replace `[case:id]` with the bare id when this turn did not return it."""

    def replace(match: re.Match[str]) -> str:
        case_id = match.group(1)
        if case_id in allowed:
            return match.group(0)
        return case_id

    return _TOKEN.sub(replace, text)


def cited_case_ids(text: str, allowed: Allowlist) -> list[str]:
    found: list[str] = []
    for match in _TOKEN.finditer(text):
        case_id = match.group(1)
        if case_id in allowed and case_id not in found:
            found.append(case_id)
    return found


def citation_records(text: str, allowed: Allowlist) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for case_id in cited_case_ids(text, allowed):
        meta = allowed.cases[case_id]
        records.append(
            {
                "case_id": case_id,
                "slide_id": meta.slide_id,
                "patch_id": meta.patch_id,
                "quote": meta.quote,
            }
        )
    return records


class CitationSanitizer:
    """Stream text, holding back an unfinished `[case:` token.

    Complete tokens are unlinked against the live allowlist, so a citation
    emitted before a tool returns that case does not survive.
    """

    def __init__(self, allowed: Allowlist) -> None:
        self.allowed = allowed
        self._pending = ""

    def push(self, delta: str) -> str:
        self._pending += delta
        hold = _hold_index(self._pending)
        if hold is None:
            ready, self._pending = self._pending, ""
        else:
            ready, self._pending = self._pending[:hold], self._pending[hold:]
        return unlink_unknown(ready, self.allowed)

    def finish(self) -> str:
        ready, self._pending = self._pending, ""
        return unlink_unknown(ready, self.allowed)


def _hold_index(text: str) -> int | None:
    start = text.rfind("[")
    if start < 0:
        return None
    suffix = text[start:]
    if _TOKEN.fullmatch(suffix):
        return None
    if _PARTIAL.fullmatch(suffix):
        return start
    return None
