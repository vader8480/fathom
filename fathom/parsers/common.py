"""Shared helpers for the export parsers (tolerant CSV / TSV reading)."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

ENCODINGS = ("utf-8-sig", "utf-16", "cp932", "cp1252", "latin-1")

#: untrusted import files larger than this are refused (§8.4 item 11)
MAX_IMPORT_BYTES = 50 * 1024 * 1024


class FileTooLarge(ValueError):
    pass


def check_size(path: Path, limit: int = MAX_IMPORT_BYTES) -> None:
    """Raise :class:`FileTooLarge` when ``path`` (a file) exceeds ``limit`` bytes."""
    try:
        size = path.stat().st_size
    except OSError:
        return
    if path.is_file() and size > limit:
        raise FileTooLarge(f"{path.name} is {size // (1024 * 1024)} MB; imports are limited to {limit // (1024 * 1024)} MB")


def read_text(path: Path) -> str:
    check_size(path)
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:30])
    if not sample.strip():
        return ","
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in (",", "\t", ";", "|")}
        return max(counts, key=counts.get) if any(counts.values()) else ","


def read_rows(path: Path) -> List[List[str]]:
    """All rows of a delimited text file as stripped string lists (blank rows dropped)."""
    text = read_text(path)
    delim = sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows: List[List[str]] = []
    for row in reader:
        cells = [c.strip() for c in row]
        if any(cells):
            rows.append(cells)
    return rows


def norm_header(cell: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (cell or "").strip().lower()).strip()


def find_header(rows: Sequence[Sequence[str]], required_any: Iterable[str], max_scan: int = 8) -> Optional[int]:
    """Index of the first header-looking row (within ``max_scan``).

    A header row has at least two non-empty cells (when the file has such
    rows), none of its cells contain digits (data rows like ``CH 1`` or
    ``01@Rio3224`` do), and at least one cell matches a token. Tokens match
    whole normalised cells or words inside them (``"name"`` matches
    ``"channel name"``). Title lines such as ``CL5 Input Patch`` are skipped.
    """
    toks = [norm_header(t) for t in required_any]
    multi = any(sum(1 for c in r if (c or "").strip()) >= 2 for r in rows[:max_scan])
    for i, row in enumerate(rows[:max_scan]):
        filled = [c for c in row if (c or "").strip()]
        if multi and len(filled) < 2:
            continue
        if any(re.search(r"\d", c) for c in filled):
            continue
        cells = [norm_header(c) for c in filled]
        for c in cells:
            words = set(c.split())
            for t in toks:
                if c == t or t in words or (" " in t and t in c):
                    return i
    return None


def column_index(header: Sequence[str], *candidates: str) -> Optional[int]:
    """Column index whose normalised header equals / contains one of ``candidates`` (in order of preference)."""
    cells = [norm_header(c) for c in header]
    for cand in candidates:
        cand_n = norm_header(cand)
        for i, c in enumerate(cells):
            if c == cand_n:
                return i
    for cand in candidates:
        cand_n = norm_header(cand)
        for i, c in enumerate(cells):
            if cand_n and (cand_n in c.split() or (" " in cand_n and cand_n in c)):
                return i
    return None


def cell(row: Sequence[str], idx: Optional[int]) -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def header_map(header: Sequence[str], spec: Dict[str, Sequence[str]]) -> Dict[str, int]:
    """Map canonical keys to column indexes by exact normalised header (key or synonyms)."""
    cells = [norm_header(c) for c in header]
    out: Dict[str, int] = {}
    for key, syns in spec.items():
        for cand in (key,) + tuple(syns):
            n = norm_header(cand)
            if n in cells and cells.index(n) not in out.values():
                out[key] = cells.index(n)
                break
    return out


def to_int(text: str) -> Optional[int]:
    m = re.search(r"-?\d+", text or "")
    return int(m.group(0)) if m else None


def compress_ranges(numbers: Iterable[int]) -> str:
    """``[1,2,3,5,7,8] -> '1-3, 5, 7-8'``."""
    nums = sorted(set(int(n) for n in numbers))
    if not nums:
        return ""
    parts: List[str] = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = n
    parts.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(parts)


class ParseResult:
    """Base for parser outputs: carries notes (warnings / what was detected)."""

    kind = "generic"

    def __init__(self) -> None:
        self.notes: List[str] = []
        self.source_files: List[str] = []

    def note(self, text: str) -> None:
        self.notes.append(text)

    def summary(self) -> Dict[str, object]:  # pragma: no cover - overridden
        return {"kind": self.kind, "notes": list(self.notes), "files": list(self.source_files)}
