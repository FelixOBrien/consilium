"""TCGA-Reports CSV: download, barcode join, clinical-history preference."""

from __future__ import annotations

import csv
import io
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPORTS_ZIP_URL = (
    "https://github.com/tatonetti-lab/tcga-path-reports/raw/refs/heads/main/TCGA_Reports.csv.zip"
)

# First 12 characters of patient_filename, e.g. TCGA-BP-5195.
PATIENT_BARCODE = re.compile(r"^TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}$")

# Longer phrases first so "diagnosis" does not swallow "preoperative diagnosis".
_HEADINGS: tuple[tuple[str, str], ...] = (
    ("clinical", "clinical diagnosis & history"),
    ("clinical", "clinical diagnosis and history"),
    ("clinical", "pre-operative diagnosis"),
    ("clinical", "preoperative diagnosis"),
    ("clinical", "clinical history"),
    ("clinical", "clinical information"),
    ("stop", "macroscopic description"),
    ("stop", "gross description"),
    ("stop", "gross examination"),
    ("stop", "microscopic description"),
    ("stop", "microscopic examination"),
    ("stop", "specimens submitted"),
    ("stop", "specimen submitted"),
    ("stop", "final diagnosis"),
    ("stop", "pathological diagnosis"),
    ("stop", "pathologic diagnosis"),
    ("stop", "diagnosis"),
)

_USER_AGENT = "cohort-manifest/0.1 (research prototype; not for clinical use)"


@dataclass(frozen=True)
class ClinicalHistory:
    """A clinical-history span. `bounded` means a later heading stopped it."""

    text: str
    bounded: bool


def extract_clinical_history(text: str) -> ClinicalHistory | None:
    """Best-effort clinical history, stopped before a diagnosis heading.

    Headings in TCGA-Reports are inline (the CSV has no line breaks) and are
    recognised when the phrase is followed by ':' or '.'. A bounded span is
    the one preferred for held-out cases: the section ended at a specimen,
    gross, microscopic, or diagnosis heading, so the conclusion is not in it.
    """
    if not text:
        return None
    # lower() keeps indexes aligned with `text` for the ASCII reports we see.
    folded = text.lower()
    occupied = bytearray(len(folded))
    found: list[tuple[int, int, str]] = []
    for kind, phrase in _HEADINGS:
        start = 0
        plen = len(phrase)
        while True:
            index = folded.find(phrase, start)
            if index < 0:
                break
            start = index + 1
            end = index + plen
            if any(occupied[index:end]):
                continue
            if index > 0 and folded[index - 1].isalnum():
                continue
            cursor = end
            while cursor < len(folded) and folded[cursor] in " \t":
                cursor += 1
            if cursor >= len(folded) or folded[cursor] not in ":.":
                continue
            occupied[index:end] = b"\x01" * plen
            found.append((index, cursor + 1, kind))
    found.sort()
    clinical = [item for item in found if item[2] == "clinical"]
    if not clinical:
        return None
    content_start = clinical[0][1]
    stops = [item for item in found if item[2] == "stop" and item[0] >= content_start]
    if stops:
        content_end = stops[0][0]
        bounded = True
    else:
        content_end = len(text)
        bounded = False
    body = text[content_start:content_end].strip()
    if not body:
        return None
    return ClinicalHistory(text=body, bounded=bounded)


def history_rank(text: str) -> int:
    """0 bounded history, 1 unbounded history, 2 none. Lower is preferred."""
    extracted = extract_clinical_history(text)
    if extracted is None:
        return 2
    if extracted.bounded:
        return 0
    return 1


def load_reports(path: Path) -> tuple[dict[str, str], int]:
    """Map patient barcode to report text. The second value is corrupt rows.

    Join key is ``patient_filename[:12]``, uppercased. A repeated barcode
    keeps the longer text. Rows whose first 12 characters are not a TCGA
    patient barcode are corrupt and skipped.
    """
    csv.field_size_limit(5_000_000)
    reports: dict[str, str] = {}
    lengths: dict[str, int] = {}
    corrupt = 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if "patient_filename" not in fields or "text" not in fields:
            raise ValueError("TCGA_Reports.csv must include patient_filename and text columns")
        for row in reader:
            filename = str(row.get("patient_filename") or "").strip().upper()
            barcode = filename[:12]
            if PATIENT_BARCODE.match(barcode) is None:
                corrupt += 1
                continue
            text = row.get("text") or ""
            if not isinstance(text, str):
                text = str(text)
            stripped = len(text.strip())
            previous = lengths.get(barcode)
            if previous is None or stripped > previous:
                reports[barcode] = text
                lengths[barcode] = stripped
    return reports, corrupt


def ensure_reports_csv(
    destination: Path,
    *,
    url: str = REPORTS_ZIP_URL,
    opener: urllib.request.OpenerDirector | None = None,
) -> Path:
    """Return `destination`, downloading the TCGA-Reports zip when it is absent."""
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    client = opener or urllib.request.build_opener()
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with client.open(request, timeout=180) as response:
            blob = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"TCGA-Reports download returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"TCGA-Reports download failed: {exc.reason}") from exc
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            member = _reports_member(archive)
            payload = archive.read(member)
    except zipfile.BadZipFile as exc:
        raise RuntimeError("TCGA-Reports download was not a zip file") from exc
    if not payload:
        raise RuntimeError("TCGA-Reports csv was empty")
    fd, tmp_name = tempfile.mkstemp(dir=destination.parent, suffix=".partial")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, destination)
    finally:
        if tmp.exists():
            tmp.unlink()
    return destination


def _reports_member(archive: zipfile.ZipFile) -> str:
    names = [
        name
        for name in archive.namelist()
        if name.endswith("TCGA_Reports.csv")
        and not name.startswith("__MACOSX")
        and not name.endswith("/")
    ]
    if not names:
        raise RuntimeError("TCGA_Reports.csv was not in the downloaded zip")
    return min(names, key=len)


def extract_reports_zip(blob: bytes, destination: Path) -> Path:
    """Write the CSV member of a zip payload. Used by tests and the downloader."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        member = _reports_member(archive)
        with archive.open(member) as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return destination
