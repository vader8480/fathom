"""Yamaha CL / QL series CSV exports (console SAVE/LOAD → CSV, or CL/QL Editor
File → CSV File Export).

The export is a *folder* of CSV files: channel names (with color and icon),
input patching, output patching and other patching (output port / rack). Two
notations exist, "Normal" (V4.1: ``DANTE 1``, ``OMNI 3``, ``SLOT1 5``,
``MIX 1``, ``MATRIX 2``, ``STEREO L``) and "Short" (V4.0: ``DNT 1``, ``SL1 5``,
``MX 1``, ``MT 2``, ``STL``). Both are accepted, as are the documented
synonyms (``Dante 1``, ``AD 3``, ``Mix Channel 1`` ...). Hand-made CSVs with a
header row such as ``Channel, Name, Color, Icon, Patch`` work too.

Nothing here depends on exact file names or column order: each file is
classified by content (channel labels, port names, color / icon words).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .common import ParseResult, cell, column_index, compress_ranges, find_header, norm_header, read_rows, to_int

# ------------------------------------------------------------- vocabularies

COLOR_SYNONYMS = {
    "blue": "Blue", "bl": "Blue", "b": "Blue",
    "orange": "Orange", "or": "Orange", "o": "Orange",
    "yellow": "Yellow", "ye": "Yellow", "yl": "Yellow", "y": "Yellow",
    "purple": "Purple", "pu": "Purple", "p": "Purple",
    "cyan": "Cyan", "skyblue": "Cyan", "cy": "Cyan", "c": "Cyan",
    "magenta": "Magenta", "pink": "Magenta", "pk": "Magenta", "m": "Magenta", "mg": "Magenta",
    "red": "Red", "brown": "Red", "rd": "Red", "bn": "Red", "r": "Red",
    "green": "Green", "gn": "Green", "g": "Green",
    "off": "Off", "black": "Off", "bk": "Off", "": "Off",
}

_ICON_TABLE: Dict[str, Sequence[str]] = {
    "Kick": ("kick", "bassdrum", "b.dr", "bd", "b.d"),
    "Snare": ("snare", "sn", "s.dr", "botm", "botom"),
    "Hi-Hat": ("hi-hat", "hihat", "hh"),
    "Tom": ("tom", "racktom", "f.tom", "ftom", "ltom", "htom"),
    "Drumkit": ("drumkit", "drum", "kit", "drums", "top", "topl", "topr", "o.head", "o.h"),
    "Perc.": ("perc.", "perc", "percussion", "per", "cong", "conga", "bong", "bongo"),
    "A.Bass": ("a.bass", "acousticbass", "bass", "c.bass", "cb", "c.b", "ab", "a.b", "vc"),
    "Strings": ("strings", "string", "str", "vl", "vn", "vla"),
    "E.Bass": ("e.bass", "electricbass", "e.b", "eb"),
    "A.Guitar": ("a.guitar", "a.gt", "acousticguitar", "acousticgt", "a.g", "ag"),
    "E.Guitar": ("e.guitar", "e.gt", "electricguitar", "electricgt", "e.g", "eg"),
    "BassAmp": ("bassamp", "b.amp", "b.a"),
    "GuitarAmp": ("guitaramp", "gtamp", "g.amp", "g.a"),
    "Trumpet": ("trumpet", "tp", "trp"),
    "Trombone": ("trombone", "tb", "trb"),
    "Saxophone": ("saxophone", "sax", "ssax", "asax", "tsax", "bsax"),
    "Piano": ("piano", "pf", "ap", "pfl", "pfr", "pfh"),
    "Organ": ("organ", "org", "leslie"),
    "Keyboard": ("keyboard", "kb", "key", "keyl", "keyr", "ep", "e.pf", "syn", "epl", "epr", "synl", "synr"),
    "Male": ("male",),
    "Female": ("female",),
    "Choir": ("choir", "chorus", "cho", "chor"),
    "Dynamic": ("dynamic", "dynamicmic"),
    "Condenser": ("condenser", "condensermic"),
    "Wireless": ("wireless", "wirelessmic", "w/l", "w.l"),
    "Podium": ("podium", "speech", "lecture"),
    "Wedge": ("wedge", "foot", "flor", "floor"),
    "2way": ("2way",),
    "In-Ear": ("in-ear", "inear", "iem", "ear"),
    "Effector": ("effector", "fx", "eff", "effect"),
    "Media1": ("media1", "cd", "md", "disc"),
    "Media2": ("media2", "pb"),
    "Video": ("video", "vtr", "dvd", "blu"),
    "Mixer": ("mixer", "mix"),
    "PC": ("pc", "daw"),
    "Processor": ("processor", "dme", "dsp", "dly", "delay", "rev", "reverb"),
    "Audience": ("audience", "aud"),
    "Star1": ("star1",),
    "Star2": ("star2",),
    "Blank": ("blank", ""),
}
ICON_SYNONYMS: Dict[str, str] = {}
for _canon, _syns in _ICON_TABLE.items():
    for _s in _syns:
        ICON_SYNONYMS.setdefault(_s.replace(" ", ""), _canon)

#: icon → source category used by auto-generated source cards
ICON_CATEGORY = {
    "Kick": "Drums", "Snare": "Drums", "Hi-Hat": "Drums", "Tom": "Drums", "Drumkit": "Drums", "Perc.": "Drums",
    "A.Bass": "Bass", "E.Bass": "Bass", "BassAmp": "Bass",
    "A.Guitar": "Guitars", "E.Guitar": "Guitars", "GuitarAmp": "Guitars",
    "Piano": "Keys", "Organ": "Keys", "Keyboard": "Keys",
    "Strings": "Strings & horns", "Trumpet": "Strings & horns", "Trombone": "Strings & horns", "Saxophone": "Strings & horns",
    "Male": "Vocals", "Female": "Vocals", "Choir": "Vocals", "Dynamic": "Vocals", "Condenser": "Vocals", "Podium": "Vocals",
    "Wireless": "Wireless mics",
    "Media1": "Playback", "Media2": "Playback", "Video": "Playback", "PC": "Playback",
    "Audience": "Ambience & talkback",
    "Effector": "Effects returns", "Processor": "Effects returns", "Mixer": "Effects returns",
    "Wedge": "Monitors", "2way": "Monitors", "In-Ear": "Monitors",
}

_NAME_KEYWORDS: List[Tuple[str, Sequence[str]]] = [
    ("Ambience & talkback", ("talkback", "tb ", " tb", "amb", "crowd", "audience", "aud ", "room")),
    ("Drums", ("kick", "kik", "snare", "snr", "hat", "hh", "tom", " oh", "oh ", "ovh", "overhead", "ride", "crash", "drum", "perc", "cajon", "conga", "bongo", "shaker", "tamb", "cym", "spd", "pad")),
    ("Bass", ("bass", "bs di", "bgtr")),
    ("Guitars", ("gtr", "guitar", "egtr", "agtr", "acoustic", "eg ", "ag ")),
    ("Keys", ("keys", "key", "piano", "pno", "organ", "synth", "rhodes", "nord", "ep ", "wurli")),
    ("Strings & horns", ("vln", "violin", "viola", "cello", "str", "tpt", "trumpet", "tbn", "trombone", "sax", "horn", "flute")),
    ("Wireless mics", ("wl ", "wireless", "hh ", "handheld", "lav", "lapel", "headset", "hs ", "ulx", "axt", "rf ")),
    ("Vocals", ("vox", "voc", "vocal", "lead", "bgv", "bv", "choir", "spk", "speech", "pastor", "host", "mc ", "preach", "ld ", "wl")),
    ("Playback", ("pb", "playback", "trax", "tracks", "click", "cue", "mac", "pc", "daw", "ableton", "laptop", "video", "atem", "pro tools", "pt ", "media", "ipod", "aux in", "stream")),
    ("Effects returns", ("rev", "verb", "dly", "delay", "fx", "plate", "hall")),
]

# ----------------------------------------------------------- port notation

_PORT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"^NONE$"), "NONE"),
    (re.compile(r"^(?:DANTE|DNT)\s*(\d+)$"), "DANTE"),
    (re.compile(r"^(?:OMNI|AD)\s*(?:IN|OUT)?\s*(\d+)$"), "OMNI"),
    (re.compile(r"^INPUT\s*(\d+)$"), "INPUT"),
    (re.compile(r"^(?:PLAYBACK\s*(?:OUTPUT)?|PB)\s*(L|R|LEFT|RIGHT)$"), "PB"),
    (re.compile(r"^(?:SLOT|SL)\s*([123])\s*(\d+)$"), "SLOT"),
    (re.compile(r"^(?:PRFX|PR|PREMIUM\s*RACK)\s*(\d+)\s*([AB])$"), "PRFX"),
    (re.compile(r"^(?:FX|EFFECT\s*RACK)\s*(\d+)\s*([AB])$"), "FX"),
    (re.compile(r"^(?:GEQ(?:\s*RACK)?)\s*(\d+)\s*([AB])$"), "GEQ"),
    (re.compile(r"^(?:MIX(?:\s*CHANNEL)?|MX)\s*(\d+)$"), "MIX"),
    (re.compile(r"^(?:MATRIX(?:\s*CHANNEL)?|MT)\s*(\d+)$"), "MATRIX"),
    (re.compile(r"^(?:STEREO(?:\s*OUTPUT)?|ST|MAIN)\s*(L|R|LEFT|RIGHT)(?:\s*\+?\s*C)?$|^ST(L|R)C?$"), "STEREO"),
    (re.compile(r"^MONO(?:\s*\(?C\)?)?$"), "MONO"),
    (re.compile(r"^(?:MONITOR|MON)\s*(L|R|C)$"), "MONITOR"),
    (re.compile(r"^(?:CUE(?:\s*A)?)\s*(L|R)$|^CUE\s*B\s*(L|R)$|^CUE\s*B(L|R)$"), "CUE"),
    (re.compile(r"^(?:INS2?\s*CH|IC2?|INSERT[12]?\s*INPUT\s*CHANNEL)\s*(\d+)$"), "INS"),
    (re.compile(r"^(?:INS2?\s*MIX|IM2?|INSERT[12]?\s*MIX\s*CHANNEL)\s*(\d+)$"), "INS"),
    (re.compile(r"^(?:INS2?\s*MATRIX|IMT2?)\s*(\d+)$"), "INS"),
    (re.compile(r"^(?:INS2?\s*STEREO|ISTL2?|ISTR2?|INS2?\s*MONO|IMONO)"), "INS"),
    (re.compile(r"^(?:DIR\s*CH|DI|DIRECT\s*(?:INPUT\s*)?CHANNEL)\s*(\d+)$"), "DIRECT"),
    (re.compile(r"^(?:CAS|CASCADE)\b"), "CASCADE"),
    (re.compile(r"^(?:SUR\s*MONITOR|SMON|MONITOR\s*MATRIX|MMT)\b"), "MONITOR"),
    (re.compile(r"^(?:TALKBACK|TB)$"), "TALKBACK"),
    (re.compile(r"^OSC(?:ILLATOR)?$"), "OSC"),
]


@dataclass
class Port:
    bus: str  # DANTE | OMNI | INPUT | SLOT | PB | FX | PRFX | GEQ | MIX | MATRIX | STEREO | MONO | ... | NONE
    number: Optional[int] = None  # channel / port number
    slot: Optional[int] = None  # SLOT 1..3
    tag: str = ""  # L / R / A / B / C
    raw: str = ""

    @property
    def text(self) -> str:
        if self.bus == "SLOT":
            return f"SLOT{self.slot} {self.number}"
        if self.bus in ("FX", "PRFX", "GEQ"):
            return f"{self.bus} {self.number} {self.tag}".strip()
        if self.number is not None:
            return f"{self.bus} {self.number}"
        if self.tag:
            return f"{self.bus} {self.tag}"
        return self.bus

    @property
    def is_physical_input(self) -> bool:
        return self.bus in ("DANTE", "OMNI", "INPUT", "SLOT")


def parse_port(text: str) -> Optional[Port]:
    """Normalise a Yamaha port name in Normal, Short or synonym notation."""
    raw = (text or "").strip()
    if not raw:
        return None
    t = re.sub(r"\s+", " ", raw.upper().replace("_", " ").replace("-", " ")).strip()
    t = t.replace("( C )", "(C)")
    for pat, bus in _PORT_PATTERNS:
        m = pat.match(t)
        if not m:
            continue
        groups = [g for g in m.groups() if g is not None]
        port = Port(bus=bus, raw=raw)
        if bus == "SLOT":
            port.slot = int(groups[0])
            port.number = int(groups[1])
        elif bus in ("FX", "PRFX", "GEQ"):
            port.number = int(groups[0])
            port.tag = groups[1]
        elif bus in ("PB", "STEREO", "MONITOR", "CUE"):
            tag = groups[0] if groups else ""
            port.tag = {"LEFT": "L", "RIGHT": "R"}.get(tag, tag)
        else:
            port.number = int(groups[0]) if groups and groups[0].isdigit() else None
        return port
    return None


def looks_like_port(text: str) -> bool:
    p = parse_port(text)
    return p is not None and p.bus != "NONE"


# --------------------------------------------------------- channel labels

_CH_LABEL = re.compile(
    r"^(?:(?P<in>(?:CH|INPUT|IN)\s*(?P<in_n>\d+))"
    r"|(?P<stin>ST\s*IN\s*(?P<stin_n>\d+)\s*(?P<stin_lr>L|R)?)"
    r"|(?P<mix>MIX\s*(?P<mix_n>\d+))"
    r"|(?P<mtx>(?:MATRIX|MTRX|MT)\s*(?P<mtx_n>\d+))"
    r"|(?P<st>(?:STEREO|ST)\s*(?P<st_lr>L|R)?)"
    r"|(?P<mono>MONO(?:\s*\(?C\)?)?)"
    r"|(?P<dca>DCA\s*(?P<dca_n>\d+))"
    r"|(?P<mute>MUTE\s*(?:GROUP\s*)?(?P<mute_n>\d+)))$",
    re.IGNORECASE,
)


def parse_channel_label(text: str) -> Optional[Tuple[str, int, str]]:
    """``'CH 12' -> ('in', 12, 'CH 12')``; ``'MIX 3' -> ('mix', 3, 'MIX 3')``; ``'ST L' -> ('stereo', 0, 'ST L')``."""
    t = re.sub(r"\s+", " ", (text or "").strip().upper())
    if not t:
        return None
    m = _CH_LABEL.match(t)
    if not m:
        return None
    g = m.groupdict()
    if g["in"]:
        return "in", int(g["in_n"]), f"CH {int(g['in_n'])}"
    if g["stin"]:
        n = int(g["stin_n"])
        lr = (g["stin_lr"] or "").upper()
        return "stin", n, f"ST IN {n}{(' ' + lr) if lr else ''}"
    if g["mix"]:
        return "mix", int(g["mix_n"]), f"MIX {int(g['mix_n'])}"
    if g["mtx"]:
        return "matrix", int(g["mtx_n"]), f"MATRIX {int(g['mtx_n'])}"
    if g["st"]:
        lr = (g["st_lr"] or "").upper()
        return "stereo", 0 if lr != "R" else 1, f"ST {lr}".strip()
    if g["mono"]:
        return "mono", 0, "MONO"
    if g["dca"]:
        return "dca", int(g["dca_n"]), f"DCA {int(g['dca_n'])}"
    if g["mute"]:
        return "mute", int(g["mute_n"]), f"MUTE {int(g['mute_n'])}"
    return None


def normalize_color(text: str) -> str:
    key = re.sub(r"\s+", "", (text or "").lower())
    return COLOR_SYNONYMS.get(key, text.strip().title() if text else "Off")


def normalize_icon(text: str) -> str:
    key = re.sub(r"\s+", "", (text or "").lower())
    return ICON_SYNONYMS.get(key, text.strip() if text else "Blank")


_GENERIC_ICONS = {"", "Blank", "Star1", "Star2", "Dynamic", "Condenser"}


def _category_from_name(name: str) -> str:
    lname = f" {(name or '').lower()} "
    for category, words in _NAME_KEYWORDS:
        for w in words:
            if w in lname:
                return category
    return ""


def categorize(name: str, icon: str) -> str:
    """Source category for auto-generated source cards.

    Instrument icons win (the operator chose them); generic mic icons
    (Dynamic, Condenser, Blank) defer to keywords in the channel name.
    """
    icon = icon or ""
    if icon not in _GENERIC_ICONS and icon in ICON_CATEGORY:
        return ICON_CATEGORY[icon]
    by_name = _category_from_name(name)
    if by_name:
        return by_name
    return ICON_CATEGORY.get(icon, "Other inputs") if icon in ICON_CATEGORY else "Other inputs"


# ------------------------------------------------------------------ model


@dataclass
class ConsoleChannel:
    kind: str  # in | stin | mix | matrix | stereo | mono | dca | mute
    index: int
    label: str
    name: str = ""
    color: str = ""
    icon: str = ""
    patch: Optional[Port] = None  # input patch (inputs) / none for buses
    outputs: List[Port] = field(default_factory=list)  # physical output ports fed by this bus

    @property
    def is_input(self) -> bool:
        return self.kind in ("in", "stin")

    @property
    def category(self) -> str:
        return categorize(self.name, self.icon)


@dataclass
class OutputPatch:
    port: Port
    source: Optional[Port]  # MIX 1 / STEREO L / ...
    raw_source: str = ""


class ConsoleData(ParseResult):
    kind = "yamaha"

    def __init__(self) -> None:
        super().__init__()
        self.model = ""
        self.console_name = ""
        self.channels: Dict[str, ConsoleChannel] = {}  # by label
        self.output_patches: List[OutputPatch] = []
        self.files_by_role: Dict[str, List[str]] = {}

    # -- access helpers
    def channel(self, kind: str, index: int) -> ConsoleChannel:
        label = {"in": f"CH {index}", "stin": f"ST IN {index}", "mix": f"MIX {index}", "matrix": f"MATRIX {index}",
                 "stereo": "ST L" if index == 0 else "ST R", "mono": "MONO", "dca": f"DCA {index}", "mute": f"MUTE {index}"}[kind]
        ch = self.channels.get(label)
        if ch is None:
            ch = ConsoleChannel(kind=kind, index=index, label=label)
            self.channels[label] = ch
        return ch

    @property
    def inputs(self) -> List[ConsoleChannel]:
        return sorted((c for c in self.channels.values() if c.is_input), key=lambda c: (c.kind != "in", c.index))

    @property
    def named_inputs(self) -> List[ConsoleChannel]:
        return [c for c in self.inputs if c.name and c.name.strip() and not re.fullmatch(r"(?i)(ch|st in)\s*\d+", c.name.strip())]

    @property
    def buses(self) -> List[ConsoleChannel]:
        order = {"mix": 0, "matrix": 1, "stereo": 2, "mono": 3}
        return sorted((c for c in self.channels.values() if c.kind in order), key=lambda c: (order[c.kind], c.index))

    def dante_input_map(self) -> Dict[int, ConsoleChannel]:
        """Dante receive channel number → console input channel patched from it."""
        out: Dict[int, ConsoleChannel] = {}
        for c in self.inputs:
            if c.patch and c.patch.bus == "DANTE" and c.patch.number:
                out[c.patch.number] = c
        return out

    def dante_output_map(self) -> Dict[int, OutputPatch]:
        out: Dict[int, OutputPatch] = {}
        for op in self.output_patches:
            if op.port.bus == "DANTE" and op.port.number:
                out[op.port.number] = op
        return out

    def patch_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for c in self.inputs:
            if c.patch and c.patch.bus != "NONE":
                key = c.patch.text.split(" ")[0] if c.patch.bus != "SLOT" else f"SLOT{c.patch.slot}"
                counts[key] = counts.get(key, 0) + 1
        return counts

    def summary(self) -> Dict[str, object]:
        inputs = self.inputs
        return {
            "kind": self.kind,
            "model": self.model,
            "inputs": len(inputs),
            "named_inputs": len(self.named_inputs),
            "patched_inputs": sum(1 for c in inputs if c.patch and c.patch.bus != "NONE"),
            "patch_by_bus": self.patch_counts(),
            "buses_named": sum(1 for b in self.buses if b.name),
            "output_patches": len(self.output_patches),
            "files": dict(self.files_by_role),
            "notes": list(self.notes),
        }


# ------------------------------------------------------------- the parser

_COLOR_WORDS = set(COLOR_SYNONYMS) - {""}
_ICON_WORDS = set(ICON_SYNONYMS) - {""}


def _score_column(rows: Sequence[Sequence[str]], idx: int, test) -> float:
    vals = [r[idx] for r in rows if idx < len(r) and r[idx].strip()]
    if not vals:
        return 0.0
    hits = sum(1 for v in vals if test(v))
    return hits / len(vals)


def _is_color(v: str) -> bool:
    return re.sub(r"\s+", "", v.lower()) in _COLOR_WORDS


def _is_icon(v: str) -> bool:
    return re.sub(r"\s+", "", v.lower()) in _ICON_WORDS


def _is_channel(v: str) -> bool:
    return parse_channel_label(v) is not None


def _is_bus(v: str) -> bool:
    p = parse_port(v)
    return p is not None and p.bus in ("MIX", "MATRIX", "STEREO", "MONO", "MONITOR", "CUE", "DIRECT", "INS", "CASCADE", "TALKBACK", "OSC")


def _is_phys_port(v: str) -> bool:
    p = parse_port(v)
    return p is not None and (p.is_physical_input or p.bus in ("PB", "NONE"))


def _data_rows(rows: Sequence[Sequence[str]], header_idx: Optional[int]) -> List[List[str]]:
    start = (header_idx + 1) if header_idx is not None else 0
    out = []
    for r in rows[start:]:
        non_empty = [c for c in r if c]
        if not non_empty:
            continue
        if len(non_empty) == 1:
            v = non_empty[0]
            if v.startswith(("#", "//", ";")) or (not _is_channel(v) and not looks_like_port(v)):
                continue  # title / comment line
        out.append(list(r))
    return out


_MODEL_RE = re.compile(r"\b(CL[135]|QL[15]|TF\d|TF-RACK|DM[37]|PM\d+|RIVAGE)\b", re.I)


def _detect_model(rows: Sequence[Sequence[str]]) -> str:
    for r in rows[:4]:
        for c in r[:3]:
            m = _MODEL_RE.search(c or "")
            if m:
                return m.group(1).upper()
    return ""


def classify_file(path: Path) -> Tuple[str, Dict[str, int], List[List[str]]]:
    """Return (role, column map, data rows). role ∈ names | input_patch | output_patch | unknown."""
    rows = read_rows(path)
    return classify_rows(rows)


def classify_rows(rows: Sequence[Sequence[str]]) -> Tuple[str, Dict[str, int], List[List[str]]]:
    if not rows:
        return "unknown", {}, []
    header_idx = find_header(rows, ("name", "color", "colour", "icon", "patch", "port", "channel", "source", "input", "output"))
    header = rows[header_idx] if header_idx is not None else []
    data = _data_rows(rows, header_idx)
    if not data:
        return "unknown", {}, []
    width = max(len(r) for r in data)
    cols: Dict[str, int] = {}

    # header-driven first
    if header:
        for role, cands in (
            ("channel", ("channel", "ch", "no", "number", "input channel", "output channel", "bus")),
            ("name", ("name", "channel name", "label")),
            ("color", ("color", "colour")),
            ("icon", ("icon",)),
            ("port", ("port", "input port", "output port", "patch", "input patch", "source port", "dante", "in", "input")),
            ("source", ("source", "bus", "output source", "from", "signal", "out", "output")),
        ):
            idx = column_index(header, *cands)
            if idx is not None and idx not in cols.values():
                cols[role] = idx

    # content-driven (fills gaps / fixes header mislabels)
    scores = {i: {
        "channel": _score_column(data, i, _is_channel),
        "color": _score_column(data, i, _is_color),
        "icon": _score_column(data, i, _is_icon),
        "phys": _score_column(data, i, _is_phys_port),
        "bus": _score_column(data, i, _is_bus),
    } for i in range(width)}

    def best(key: str, exclude: Sequence[int], min_score: float = 0.6) -> Optional[int]:
        cands = [(scores[i][key], i) for i in range(width) if i not in exclude and scores[i][key] >= min_score]
        return max(cands)[1] if cands else None

    taken = list(cols.values())
    if "channel" not in cols:
        idx = best("channel", taken)
        if idx is not None:
            cols["channel"] = idx
            taken.append(idx)
    if "color" not in cols:
        idx = best("color", taken, 0.7)
        if idx is not None:
            cols["color"] = idx
            taken.append(idx)
    if "icon" not in cols:
        idx = best("icon", taken, 0.7)
        if idx is not None:
            cols["icon"] = idx
            taken.append(idx)

    phys_idx = best("phys", [], 0.6)
    bus_idx = best("bus", [phys_idx] if phys_idx is not None else [], 0.6)

    # Decide the role
    if "channel" in cols and ("color" in cols or "icon" in cols or "name" in cols) and phys_idx is None:
        role = "names"
    elif "channel" in cols and phys_idx is not None:
        role = "input_patch"
        cols.setdefault("port", phys_idx)
    elif phys_idx is not None and bus_idx is not None:
        role = "output_patch"
        cols.setdefault("port", phys_idx)
        cols.setdefault("source", bus_idx)
    elif "channel" in cols and "port" in cols:
        role = "input_patch"
    elif "channel" in cols:
        role = "names"
    else:
        role = "unknown"

    if role == "names" and "name" not in cols:
        # the name is the first text column that is not channel/color/icon
        for i in range(width):
            if i in cols.values():
                continue
            if scores[i]["channel"] < 0.3 and scores[i]["color"] < 0.3 and scores[i]["icon"] < 0.3:
                cols["name"] = i
                break
    if role == "input_patch" and "name" not in cols:
        for i in range(width):
            if i in cols.values():
                continue
            if scores[i]["channel"] < 0.3 and scores[i]["phys"] < 0.3 and scores[i]["color"] < 0.3 and scores[i]["icon"] < 0.3:
                cols["name"] = i
                break
    return role, cols, data


def parse_yamaha(path: Path) -> ConsoleData:
    """Parse one CSV or a folder of CSVs."""
    data = ConsoleData()
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.suffix.lower() in (".csv", ".txt", ".tsv"))
    if not files:
        data.note(f"no CSV files under {path}")
        return data
    for f in files:
        try:
            all_rows = read_rows(f)
            role, cols, rows = classify_rows(all_rows)
        except Exception as exc:  # pragma: no cover - defensive
            data.note(f"{f.name}: could not read ({exc})")
            continue
        data.source_files.append(str(f))
        data.files_by_role.setdefault(role, []).append(f.name)
        if role == "names":
            _ingest_names(data, cols, rows)
        elif role == "input_patch":
            _ingest_input_patch(data, cols, rows)
        elif role == "output_patch":
            _ingest_output_patch(data, cols, rows)
        else:
            data.note(f"{f.name}: not recognised as channel names / input patch / output patch")
        if not data.model:
            data.model = _detect_model(all_rows) or _detect_model([[f.stem]])
    if not data.channels and not data.output_patches:
        data.note("no channel data found (expected CL/QL CSV exports: channel names, input patch, output patch)")
    return data


def _ingest_names(data: ConsoleData, cols: Dict[str, int], rows: List[List[str]]) -> None:
    for r in rows:
        parsed = parse_channel_label(cell(r, cols.get("channel")))
        if not parsed:
            continue
        kind, idx, _label = parsed
        ch = data.channel(kind, idx)
        name = cell(r, cols.get("name"))
        if name:
            ch.name = name
        color = cell(r, cols.get("color"))
        if color:
            ch.color = normalize_color(color)
        icon = cell(r, cols.get("icon"))
        if icon:
            ch.icon = normalize_icon(icon)


def _ingest_input_patch(data: ConsoleData, cols: Dict[str, int], rows: List[List[str]]) -> None:
    for r in rows:
        parsed = parse_channel_label(cell(r, cols.get("channel")))
        if not parsed:
            continue
        kind, idx, _label = parsed
        if kind not in ("in", "stin"):
            continue
        ch = data.channel(kind, idx)
        port = parse_port(cell(r, cols.get("port")))
        if port:
            ch.patch = port
        name = cell(r, cols.get("name"))
        if name and not ch.name:
            ch.name = name


def _ingest_output_patch(data: ConsoleData, cols: Dict[str, int], rows: List[List[str]]) -> None:
    for r in rows:
        port = parse_port(cell(r, cols.get("port")))
        if not port or port.bus == "NONE":
            continue
        src_raw = cell(r, cols.get("source"))
        src = parse_port(src_raw)
        if src and src.bus == "NONE":
            continue
        data.output_patches.append(OutputPatch(port=port, source=src, raw_source=src_raw))
        if src and src.bus in ("MIX", "MATRIX", "STEREO", "MONO"):
            kind = {"MIX": "mix", "MATRIX": "matrix", "STEREO": "stereo", "MONO": "mono"}[src.bus]
            idx = src.number if src.number is not None else (1 if src.tag == "R" else 0)
            data.channel(kind, idx).outputs.append(port)


def describe_patch_source(port: Optional[Port]) -> str:
    if port is None:
        return ""
    if port.bus == "SLOT":
        return f"Slot {port.slot} ch {port.number}"
    if port.bus == "DANTE":
        return f"Dante {port.number}"
    if port.bus == "OMNI":
        return f"Omni {port.number}"
    return port.text.title()


def summarize_ranges(channels: Sequence[ConsoleChannel]) -> str:
    return compress_ranges(c.index for c in channels if c.kind == "in")
