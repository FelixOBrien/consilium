"""OCR cleanup, section extraction, and sentence chunking for reports.

`clinical_history` stops at the first specimen, gross, microscopic, or
diagnosis heading so a conclusion cannot ride along into an open case.
The body is partitioned on those same headings: every character is in
exactly one span, and spans over about 200 words are split on sentence
boundaries with one sentence of overlap.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# About 200 words. A chunk may run slightly over once the overlap sentence
# is attached.
MAX_CHUNK_WORDS = 200
_WORD_WINDOW_OVERLAP = 20

# Longer phrases are matched first so "diagnosis" does not swallow
# "preoperative diagnosis" or "clinical diagnosis & history".
_HEADINGS: tuple[tuple[str, str], ...] = (
    ("clinical_history", "clinical diagnosis & history"),
    ("clinical_history", "clinical diagnosis and history"),
    ("clinical_history", "pre-operative diagnosis"),
    ("clinical_history", "preoperative diagnosis"),
    ("clinical_history", "clinical history"),
    ("clinical_history", "clinical information"),
    ("gross_description", "macroscopic description"),
    ("gross_description", "gross description"),
    ("gross_description", "gross examination"),
    ("microscopic_description", "microscopic description"),
    ("microscopic_description", "microscopic examination"),
    ("conclusion", "final diagnosis"),
    ("conclusion", "pathological diagnosis"),
    ("conclusion", "pathologic diagnosis"),
    ("conclusion", "diagnosis"),
    ("conclusion", "conclusion"),
    ("conclusion", "interpretation"),
    ("additional_info", "synoptic report"),
    ("additional_info", "addendum"),
    ("additional_info", "comments"),
    ("additional_info", "comment"),
    ("additional_info", "note"),
    ("specimen", "specimens submitted"),
    ("specimen", "specimen submitted"),
    ("specimen", "specimens received"),
    ("specimen", "specimen received"),
    ("specimen", "nature of specimen"),
    ("specimen", "specimen"),
)

SECTION_FIELDS: tuple[str, ...] = (
    "clinical_history",
    "gross_description",
    "microscopic_description",
    "conclusion",
    "additional_info",
)

# clinical_history must not continue past these. Comment/note headings are
# not in this set; a partition still ends the clinical span at the next
# heading of any kind, which is earlier and therefore still safe.
_STOP_FIELDS = frozenset(
    {"specimen", "gross_description", "microscopic_description", "conclusion"}
)

_ABBREVIATIONS = frozenset(
    {
        "dr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "fig",
        "figs",
        "no",
        "nos",
        "vs",
        "st",
        "al",
        "eg",
        "ie",
        "etc",
        "approx",
        "ca",
        "cm",
        "mm",
    }
)

_OCR_FIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bRecelpt\b"), "Receipt"),
)


@dataclass(frozen=True)
class Heading:
    field: str
    start: int
    content_start: int


@dataclass(frozen=True)
class ExtractedSections:
    """Trimmed section columns. Empty spans are `None`. `spans` cover `body`."""

    body: str
    clinical_history: str | None
    gross_description: str | None
    microscopic_description: str | None
    conclusion: str | None
    additional_info: str | None
    spans: tuple[tuple[str, str], ...]
    clinical_stop: int | None
    clinical_end: int | None

    def column(self, name: str) -> str | None:
        value = getattr(self, name)
        if value is not None and not isinstance(value, str):
            raise TypeError(name)
        return value


def clean_report_text(text: str) -> str:
    """Light OCR cleanup. The full report is kept; wording is not rewritten."""
    cleaned = unicodedata.normalize("NFKC", text or "")
    cleaned = cleaned.replace("\x00", "")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    for pattern, replacement in _OCR_FIXES:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned.strip()


def find_headings(text: str) -> list[Heading]:
    """Heading matches. A phrase counts when it is followed by `:` `.` or a newline."""
    folded = text.lower()
    occupied = bytearray(len(folded))
    found: list[Heading] = []
    phrases = sorted(_HEADINGS, key=lambda item: len(item[1]), reverse=True)
    for field, phrase in phrases:
        start = 0
        phrase_len = len(phrase)
        while True:
            index = folded.find(phrase, start)
            if index < 0:
                break
            start = index + 1
            end = index + phrase_len
            if any(occupied[index:end]):
                continue
            if index > 0 and folded[index - 1].isalnum():
                continue
            content = _separator_end(folded, end)
            if content is None:
                continue
            occupied[index:end] = b"\x01" * phrase_len
            found.append(Heading(field=field, start=index, content_start=content))
    found.sort(key=lambda heading: (heading.start, heading.content_start))
    return found


def _separator_end(folded: str, end: int) -> int | None:
    cursor = end
    while cursor < len(folded) and folded[cursor] in " \t":
        cursor += 1
    if cursor >= len(folded):
        return None
    if folded[cursor] == "\n":
        content = cursor + 1
    elif folded[cursor] in ":.":
        content = cursor + 1
    else:
        return None
    while content < len(folded) and folded[content] in " \t":
        content += 1
    return content


def partition_body(body: str, headings: list[Heading] | None = None) -> tuple[tuple[str, str], ...]:
    """Split `body` into ordered `(section, text)` spans that concatenate to it.

    Text before the first heading, and text under a specimen heading, uses
    `section = 'body'`.
    """
    if headings is None:
        headings = find_headings(body)
    if not body:
        return ()
    bounds = sorted({0, len(body), *(heading.start for heading in headings)})
    heading_at = {heading.start: heading for heading in headings}
    spans: list[tuple[str, str]] = []
    for left, right in zip(bounds, bounds[1:], strict=False):
        if left >= right:
            continue
        heading = heading_at.get(left)
        if heading is None or heading.field not in SECTION_FIELDS:
            section = "body"
        else:
            section = heading.field
        spans.append((section, body[left:right]))
    if "".join(text for _, text in spans) != body:
        raise ValueError("section partition does not cover the report body")
    return tuple(spans)


def extract_sections(body: str) -> ExtractedSections:
    """Best-effort section columns. Clinical history cannot cross a stop heading."""
    headings = find_headings(body)
    spans = partition_body(body, headings)
    contents: dict[str, list[str]] = {field: [] for field in SECTION_FIELDS}
    for index, heading in enumerate(headings):
        if heading.field not in SECTION_FIELDS:
            continue
        next_start = headings[index + 1].start if index + 1 < len(headings) else len(body)
        text = body[heading.content_start : next_start].strip()
        if text:
            contents[heading.field].append(text)

    clinical, clinical_stop, clinical_end = _clinical_history(body, headings)
    return ExtractedSections(
        body=body,
        clinical_history=clinical,
        gross_description=_join(contents["gross_description"]),
        microscopic_description=_join(contents["microscopic_description"]),
        conclusion=_join(contents["conclusion"]),
        additional_info=_join(contents["additional_info"]),
        spans=spans,
        clinical_stop=clinical_stop,
        clinical_end=clinical_end,
    )


def _clinical_history(
    body: str, headings: list[Heading]
) -> tuple[str | None, int | None, int | None]:
    clinical = [heading for heading in headings if heading.field == "clinical_history"]
    if not clinical:
        return None, None, None
    first = clinical[0]
    later = [heading for heading in headings if heading.start >= first.content_start]
    end = len(body)
    if later:
        end = min(end, later[0].start)
    stops = [
        heading
        for heading in headings
        if heading.field in _STOP_FIELDS and heading.start >= first.content_start
    ]
    stop_at = stops[0].start if stops else None
    if stop_at is not None:
        end = min(end, stop_at)
    text = body[first.content_start : end].strip()
    return (text or None), stop_at, end


def _join(parts: list[str]) -> str | None:
    if not parts:
        return None
    joined = "\n\n".join(part.strip() for part in parts if part.strip())
    return joined or None


def split_sentences(text: str) -> list[str]:
    """Split on `.` `!` `?` while keeping common abbreviations intact."""
    stripped = text.strip()
    if not stripped:
        return []
    sentences: list[str] = []
    start = 0
    index = 0
    length = len(stripped)
    while index < length:
        if stripped[index] in ".!?":
            end_punct = index + 1
            while end_punct < length and stripped[end_punct] in ".!?":
                end_punct += 1
            token = ""
            pieces = stripped[start:index].split()
            if pieces:
                token = pieces[-1].lower().strip(".")
            at_boundary = end_punct == length or stripped[end_punct].isspace()
            short_initial = len(token) == 1 and token.isalpha()
            if at_boundary and token not in _ABBREVIATIONS and not short_initial:
                sentence = stripped[start:end_punct].strip()
                if sentence:
                    sentences.append(sentence)
                index = end_punct
                while index < length and stripped[index].isspace():
                    index += 1
                start = index
                continue
        index += 1
    tail = stripped[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def chunk_span(text: str, *, max_words: int = MAX_CHUNK_WORDS) -> list[str]:
    """Split one section span. Short spans stay whole. Long spans overlap by one sentence."""
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped.split()) <= max_words:
        return [stripped]
    sentences = split_sentences(stripped)
    if len(sentences) <= 1:
        return _word_windows(stripped.split(), max_words)
    chunks: list[list[str]] = []
    current: list[str] = []
    words = 0
    for sentence in sentences:
        sentence_words = sentence.split()
        if len(sentence_words) > max_words:
            if current:
                chunks.append(current)
                current = []
                words = 0
            for piece in _word_windows(sentence_words, max_words):
                chunks.append([piece])
            continue
        if current and words + len(sentence_words) > max_words:
            chunks.append(current)
            overlap = current[-1]
            current = [overlap]
            words = len(overlap.split())
        current.append(sentence)
        words += len(sentence_words)
    if current:
        chunks.append(current)
    return [" ".join(part) for part in chunks if part]


def _word_windows(words: list[str], max_words: int) -> list[str]:
    if len(words) <= max_words:
        return [" ".join(words)] if words else []
    overlap = min(_WORD_WINDOW_OVERLAP, max_words // 2)
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + max_words)
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start
    return chunks


def chunk_report(body: str, *, max_words: int = MAX_CHUNK_WORDS) -> list[tuple[str, str]]:
    """Partition `body`, then split long spans. Returns `(section, passage)` in order."""
    extracted = extract_sections(body)
    passages: list[tuple[str, str]] = []
    for section, text in extracted.spans:
        for piece in chunk_span(text, max_words=max_words):
            if piece.strip():
                passages.append((section, piece.strip()))
    if not passages and body.strip():
        passages.append(("body", body.strip()))
    return passages


def clinical_history_is_bounded(extracted: ExtractedSections) -> bool:
    """True when clinical history, if present, ends at or before the first stop heading."""
    if not extracted.clinical_history:
        return True
    if extracted.clinical_stop is None:
        return True
    if extracted.clinical_end is None:
        return False
    return extracted.clinical_end <= extracted.clinical_stop
