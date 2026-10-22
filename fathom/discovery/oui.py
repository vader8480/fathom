"""MAC OUI → vendor lookup from the bundled ``oui.csv``.

The bundled file is a curated subset of the IEEE MA-L registry (AV, lighting,
network and common IT vendors; ~8 000 prefixes). Point ``FATHOM_OUI_CSV`` at
the full IEEE ``oui.csv`` (``Registry,Assignment,Organization Name,…``) or any
two-column ``prefix,vendor`` file to extend it; both layouts are accepted.
"""

from __future__ import annotations

import csv
import os
import re
import threading
from pathlib import Path
from typing import Dict, Optional

from ..network import normalize_mac

BUNDLED = Path(__file__).with_name("oui.csv")
_LOCK = threading.Lock()
_TABLE: Optional[Dict[str, str]] = None
_SHORT = [
    (re.compile(r"\b(inc|incorporated|corp|corporation|co|ltd|limited|llc|gmbh|ag|bv|nv|sa|srl|spa|s\.p\.a|pty|kk|k\.k|plc|oy|a/s|ab|as|technologies|technology|electronics|systems|international|group|holdings|company)\b\.?", re.I), ""),
    (re.compile(r"[(),.]+"), " "),
    (re.compile(r"\s{2,}"), " "),
]
_PREFIX_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


def _load_file(path: Path, table: Dict[str, str]) -> None:
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.reader(fh)
            header = next(reader, None) or []
            if header and header[0].strip().lower() == "registry":  # IEEE layout
                for row in reader:
                    if len(row) >= 3 and row[0].strip() == "MA-L":
                        p = row[1].strip().upper()
                        if _PREFIX_RE.match(p):
                            table[p] = row[2].strip()
            else:
                if header and len(header) >= 2 and _PREFIX_RE.match(header[0].strip().replace(":", "").replace("-", "")):
                    reader_rows = [header]
                else:
                    reader_rows = []
                for row in list(reader_rows) + list(reader):
                    if len(row) >= 2:
                        p = row[0].strip().upper().replace(":", "").replace("-", "")
                        if _PREFIX_RE.match(p):
                            table[p] = row[1].strip()
    except OSError:
        return


def table() -> Dict[str, str]:
    global _TABLE
    with _LOCK:
        if _TABLE is None:
            t: Dict[str, str] = {}
            if BUNDLED.is_file():
                _load_file(BUNDLED, t)
            extra = os.environ.get("FATHOM_OUI_CSV") or ""
            if extra:
                p = Path(extra).expanduser()
                if p.is_file():
                    _load_file(p, t)
            _TABLE = t
        return _TABLE


def _reset_for_tests() -> None:  # pragma: no cover - test helper
    global _TABLE
    with _LOCK:
        _TABLE = None


def vendor(mac: str) -> str:
    """Registered organisation for ``mac``'s OUI, or ``""``."""
    m = normalize_mac(mac or "")
    if not m:
        return ""
    first = int(m[0:2], 16)
    if first & 0x02:  # locally administered (randomised phone MACs, VMs): no vendor
        return ""
    return table().get(m.replace(":", "")[:6].upper(), "")


def short_vendor(name: str) -> str:
    """``"Yamaha Corporation"`` → ``"Yamaha"``; ``"Audinate Pty L"`` → ``"Audinate"``."""
    s = name or ""
    for rx, rep in _SHORT:
        s = rx.sub(rep, s)
    s = s.strip(" -")
    return s or (name or "").strip()


def is_locally_administered(mac: str) -> bool:
    m = normalize_mac(mac or "")
    return bool(m) and bool(int(m[0:2], 16) & 0x02)


def is_multicast(mac: str) -> bool:
    m = normalize_mac(mac or "")
    return bool(m) and bool(int(m[0:2], 16) & 0x01)


__all__ = ["BUNDLED", "is_locally_administered", "is_multicast", "short_vendor", "table", "vendor"]
