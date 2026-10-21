"""Export parsers + auto-detection, registered in :mod:`fathom.plugins`.

The v0.2 API is unchanged: ``KINDS`` (the three legacy kinds),
``detect_kind`` (legacy heuristics, returns yamaha | dante | waves | unknown),
``parse_any`` and ``parse_yamaha/dante/waves``. New importers (Eos, MagicQ,
Videohub, generic CSV, ATEM) are reachable through the registry and through
``parse_any(path, kind)`` with an explicit kind.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Union

from .. import plugins as _plugins
from .common import ParseResult, read_text
from .dante import DanteNetwork, parse_dante
from .waves import SQLITE_MAGIC, WavesSession, parse_waves
from .yamaha import ConsoleData, parse_yamaha

KINDS = ("yamaha", "dante", "waves")
LEGACY_KINDS = KINDS

_CONSOLE_SECTION_RE = re.compile(r"^\[(?:Information|[A-Za-z]*(?:Name|Patch))\]\s*$", re.I | re.M)


def detect_kind(path: Path) -> str:
    """Guess which export a file / folder is. Returns yamaha | dante | waves | unknown."""
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file() and not p.name.startswith(".")]
        votes = {"yamaha": 0, "dante": 0, "waves": 0}
        for f in files[:40]:
            k = detect_kind(f)
            if k in votes:
                votes[k] += 1
        best = max(votes, key=votes.get)
        return best if votes[best] else "unknown"
    suffix = path.suffix.lower()
    head_bytes = path.read_bytes()[:4096]
    if head_bytes.startswith(SQLITE_MAGIC) or suffix in (".sprk", ".xps", ".mrsession", ".emo"):
        return "waves"
    head = head_bytes.decode("utf-8", errors="ignore").lstrip().lstrip("\ufeff")
    low = head.lower()
    if _CONSOLE_SECTION_RE.match(head):
        return "yamaha"  # console CSV export: [Information] / model / firmware / [Section]
    if head.startswith("<"):
        if "<preset" in low or "txchannel" in low or "rxchannel" in low or "subscribed_device" in low:
            return "dante"
        if "rack" in low or "plugin" in low or "waves" in low or "superrack" in low or "multirack" in low:
            return "waves"
        return "unknown"
    if head.startswith(("{", "[")):
        return "waves" if ("rack" in low or "plugin" in low) else "unknown"
    # text tables
    text = read_text(path)[:6000]
    tl = text.lower()
    at_lines = sum(1 for line in text.splitlines() if re.search(r"\S@\S", line))
    if at_lines >= 2 or any(w in tl for w in ("receiver", "transmitter", "rx device", "tx device", "subscribed", "device name", "connected to")):
        return "dante"
    if any(w in tl for w in ("plugin", "plugins", "rack", "superrack", "multirack", "soundgrid")):
        return "waves"
    if any(w in tl for w in ("dante ", "dnt ", "omni ", "slot1", "sl1 ", "mix ", "matrix", "stereo l", "icon", "color", "ch 1", "ch1", "st in")):
        return "yamaha"
    return "unknown"


def parse_any(path: Path, kind: str = "auto", device: str = "") -> Union[ConsoleData, DanteNetwork, WavesSession, Any]:
    kind = (kind or "auto").lower()
    if kind == "auto":
        kind = detect_kind(path)
        if kind == "unknown":
            kind = _plugins.detect(path)
    if kind == "yamaha":
        return parse_yamaha(path)
    if kind == "dante":
        return parse_dante(path, device=device)
    if kind == "waves":
        return parse_waves(path)
    imp = _plugins.get_importer(kind) if kind != "unknown" else None
    if imp is not None:
        return imp.parse(path, device=device) if device else imp.parse(path)
    raise SystemExit(f"error: could not tell what {path.name} is; pass --kind {'|'.join(k.kind for k in _plugins.importers())}")


# ------------------------------------------------------------ registry


def _legacy_detect(kind: str):
    def _detect(path: Path) -> float:
        try:
            k = detect_kind(path)
        except (OSError, ValueError):
            return 0.0
        if k != kind:
            return 0.0
        # plain-text heuristics score below the format-specific detectors of the new importers
        strong = path.is_dir() or path.suffix.lower() in (".xml", ".json", ".sprk", ".xps", ".mrsession", ".emo", ".sqlite", ".db")
        return 0.9 if strong else 0.6

    return _detect


def _parse_yamaha(path: Path, **_o: Any) -> ConsoleData:
    return parse_yamaha(path)


def _parse_dante(path: Path, device: str = "", **_o: Any) -> DanteNetwork:
    return parse_dante(path, device=device)


def _parse_waves(path: Path, **_o: Any) -> WavesSession:
    return parse_waves(path)


def _register_builtins() -> None:
    from . import atem, eos, generic_csv, magicq, videohub

    Imp = _plugins.Importer
    _plugins.register_importer(Imp(
        kind="yamaha", label="Yamaha console CSV (CL/QL/TF/DM/RIVAGE Editor)", detect=_legacy_detect("yamaha"), parse=_parse_yamaha,
        contribute=None, accepts=(".csv", ".txt"), folder=True,
        help="Channel names, input and output patch from the console Editor's CSV export (a folder of CSVs or one file).",
    ))
    _plugins.register_importer(Imp(
        kind="dante", label="Dante Controller preset / tables", detect=_legacy_detect("dante"), parse=_parse_dante,
        contribute=None, accepts=(".xml", ".txt", ".tsv", ".csv"), folder=True,
        help="Dante Controller preset (.xml), Receive-tab paste, routing CSV, or Device Info paste (Primary/Secondary Address → IP schedule).",
    ))
    _plugins.register_importer(Imp(
        kind="waves", label="Waves SuperRack / MultiRack session", detect=_legacy_detect("waves"), parse=_parse_waves,
        contribute=None, accepts=(".csv", ".xml", ".json", ".sprk", ".xps", ".mrsession", ".emo"), folder=False,
        help="Racks and plugin chains from a SuperRack / MultiRack session or rack list.",
    ))
    _plugins.register_importer(Imp(
        kind="eos", label="ETC Eos CSV / USITT ASCII / Lightwright", detect=eos.detect, parse=eos.parse_eos,
        contribute=eos.contribute, accepts=(".csv", ".asc", ".txt", ".tsv"), folder=False,
        help="Lighting patch: Eos CSV export (START_CHANNELS), USITT ASCII show file (.asc) or a Lightwright / Vectorworks instrument schedule.",
    ))
    _plugins.register_importer(Imp(
        kind="magicq", label="ChamSys MagicQ patch CSV", detect=magicq.detect, parse=magicq.parse_magicq,
        contribute=magicq.contribute, accepts=(".csv", ".txt", ".tsv", ".shw"), folder=False,
        help="Head list from MagicQ: Patch → View Heads → File → Print Window → Create CSV, or (older versions) Patch → View Chans → EXPORT HEADS. "
             "Head number, name, type, DMX address, mode, gel and channel count; .shw show files cannot be read.",
    ))
    _plugins.register_importer(Imp(
        kind="videohub", label="Blackmagic Videohub protocol dump", detect=videohub.detect, parse=videohub.parse_videohub,
        contribute=videohub.contribute, accepts=(".txt", ".log"), folder=False,
        help="Text captured from the router on TCP 9990 (e.g. nc <ip> 9990 > dump.txt): labels and routing.",
    ))
    _plugins.register_importer(Imp(
        kind="csv", label="Device / cable CSV (one-shot)", detect=generic_csv.detect, parse=generic_csv.parse_csv,
        preview=generic_csv.preview, mode="oneshot", accepts=(".csv", ".tsv", ".txt"), folder=False,
        help="Spreadsheet of devices (name, kind, model, room, serial, ip …) or cables (from/to device + port, tag, type, length). "
             "Start from a template, edit it in any spreadsheet app and upload it; every row is checked and previewed before anything is written.",
        templates=tuple(generic_csv.template_info()), template=generic_csv.template_csv,
    ))
    _plugins.register_importer(Imp(
        kind="atem", label="ATEM Software Control settings (XML)", detect=atem.detect, parse=atem.parse_atem,
        contribute=atem.contribute, accepts=(".xml",), folder=False,
        help="Input names from an ATEM settings export become port labels on the ATEM.",
    ))


_register_builtins()

__all__ = [
    "ConsoleData",
    "DanteNetwork",
    "WavesSession",
    "ParseResult",
    "KINDS",
    "LEGACY_KINDS",
    "detect_kind",
    "parse_any",
    "parse_yamaha",
    "parse_dante",
    "parse_waves",
]
