"""Yamaha CL / QL series CSV exports (console SAVE/LOAD → CSV, or CL/QL Editor
File → CSV File Export).

The export is a *folder* of CSV files. A real console export (CL5 V4.1 and
friends) writes one file per section, each starting with four header lines
(``[Information]``, model, firmware, ``[SectionName]``) followed by a column
header row; data rows end with a trailing comma::

    [InName]        _01 … _72          name / color / icon of mono input channels
    [StName]        _01 … _16          stereo inputs as L/R halves (_01/_02 = ST IN 1 L/R)
    [MixName]       _01 … _24          Mix buses
    [MtxName]       _01 … _08          Matrix buses
    [StMonoName]    _01 … _03          Stereo L, Stereo R, Mono
    [DCAName]       _01 … _16          DCA names (no membership in the export)
    [InPatch]       CH n / STEREO INPUT nL / INS CH n / INS2 CH n  ← source or insert return
    [OutPatch]      INS MIX n / INS MATRIX n / INS STEREO L / INS MONO  ← insert return
    [PortRackPatch] DANTE n / OMNI n / SLOT1 n / REC n / GEQ nA / FX nA / PRFX nA ← console signal

``DANTE n`` in InPatch is a Dante *receive* channel; the same text in the
left column of PortRackPatch is a Dante *transmit* channel. They are kept in
separate namespaces (``dante_input_map`` vs ``dante_output_map``). Bus → port
patching comes from PortRackPatch; OutPatch only holds bus insert returns.

Two notations exist, "Normal" (``DANTE 1``, ``OMNI 3``, ``SLOT1 5``, ``MIX 1``,
``MATRIX 2``, ``STEREO L``) and "Short" (V4.0: ``DNT 1``, ``SL1 5``, ``MX 1``,
``MT 2``, ``STL``). Both are accepted, as are the documented synonyms
(``Dante 1``, ``AD 3``, ``Mix Channel 1`` ...). Files without the section
header (Editor exports, hand-made CSVs with ``Channel, Name, Color, Icon,
Patch`` columns) are classified by content instead.
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
    (re.compile(r"^(?:REC(?:ORDER)?(?:\s*OUT(?:PUT)?)?)\s*(\d+)$"), "REC"),
    (re.compile(r"^(?:CAS|CASCADE)\b"), "CASCADE"),
    (re.compile(r"^(?:SUR\s*MONITOR|SMON|MONITOR\s*MATRIX|MMT)\b"), "MONITOR"),
    (re.compile(r"^(?:TALKBACK|TB)$"), "TALKBACK"),
    (re.compile(r"^OSC(?:ILLATOR)?$"), "OSC"),
]

# Insert send / return points (``INS`` = insert 1, ``INS2`` = insert 2) and direct outs.
_INS_RE = re.compile(
    r"^INS(?:ERT)?\s*(?P<ins>[12])?\s+(?:"
    r"(?:CH|INPUT\s*CHANNEL)\s*(?P<ch>\d+)"
    r"|MIX(?:\s*CHANNEL)?\s*(?P<mix>\d+)"
    r"|MATRIX(?:\s*CHANNEL)?\s*(?P<mtx>\d+)"
    r"|(?:STEREO(?:\s*OUTPUT)?|ST)\s*(?P<st>L|R|LEFT|RIGHT)"
    r"|(?P<mono>MONO(?:\s*\(?C\)?)?)"
    r")$"
)
_INS_SHORT_RE = re.compile(
    r"^(?:IC(?P<ins_c>2)?\s*(?P<ch>\d+)|IM(?P<ins_m>2)?\s*(?P<mix>\d+)|IMT(?P<ins_t>2)?\s*(?P<mtx>\d+)"
    r"|IST(?P<st>L|R)(?P<ins_s>2)?|(?P<mono>IMONO)(?P<ins_o>2)?)$"
)
_DIRECT_RE = re.compile(r"^(?:DIR\s*CH|DI|DIRECT\s*(?:INPUT\s*)?CHANNEL)\s*(\d+)$")

#: output connectors of the console itself (as opposed to internal racks / buses)
PHYSICAL_OUTPUT_BUSES = ("DANTE", "OMNI", "SLOT", "REC")
RACK_BUSES = ("GEQ", "FX", "PRFX")
_BUS_KIND = {"MIX": "mix", "MATRIX": "matrix", "STEREO": "stereo", "MONO": "mono"}


@dataclass
class Port:
    bus: str  # DANTE | OMNI | INPUT | SLOT | REC | PB | FX | PRFX | GEQ | MIX | MATRIX | STEREO | MONO | INS | DIRECT | ... | NONE
    number: Optional[int] = None  # channel / port number
    slot: Optional[int] = None  # SLOT 1..3
    tag: str = ""  # L / R / A / B / C
    raw: str = ""
    insert: int = 0  # INS / DIRECT only: 1 = Insert 1, 2 = Insert 2
    channel: str = ""  # INS / DIRECT only: console channel label (``CH 7``, ``MIX 10``, ``ST L``, ``MONO``)

    @property
    def text(self) -> str:
        if self.bus == "SLOT":
            return f"SLOT{self.slot} {self.number}"
        if self.bus in RACK_BUSES:
            return f"{self.bus} {self.number}{self.tag}".strip()
        if self.bus == "INS" and self.channel:
            return f"INS{'2' if self.insert == 2 else ''} {self.channel}"
        if self.bus == "DIRECT" and self.channel:
            return f"DIR {self.channel}"
        if self.number is not None:
            return f"{self.bus} {self.number}"
        if self.tag:
            return f"{self.bus} {self.tag}"
        return self.bus

    @property
    def is_physical_input(self) -> bool:
        return self.bus in ("DANTE", "OMNI", "INPUT", "SLOT")

    @property
    def is_physical_output(self) -> bool:
        return self.bus in PHYSICAL_OUTPUT_BUSES

    @property
    def is_rack(self) -> bool:
        return self.bus in RACK_BUSES

    @property
    def is_bus(self) -> bool:
        return self.bus in _BUS_KIND


def _insert_port(m: "re.Match", raw: str) -> Port:
    g = m.groupdict()
    ins = next((v for k, v in g.items() if k.startswith("ins") and v), None)
    port = Port(bus="INS", raw=raw, insert=2 if ins == "2" else 1)
    if g.get("ch"):
        port.number, port.channel = int(g["ch"]), f"CH {int(g['ch'])}"
    elif g.get("mix"):
        port.number, port.channel = int(g["mix"]), f"MIX {int(g['mix'])}"
    elif g.get("mtx"):
        port.number, port.channel = int(g["mtx"]), f"MATRIX {int(g['mtx'])}"
    elif g.get("st"):
        port.tag = {"LEFT": "L", "RIGHT": "R"}.get(g["st"], g["st"])
        port.channel = f"ST {port.tag}"
    else:
        port.channel = "MONO"
    return port


def parse_port(text: str) -> Optional[Port]:
    """Normalise a Yamaha port name in Normal, Short or synonym notation."""
    raw = (text or "").strip()
    if not raw:
        return None
    t = re.sub(r"\s+", " ", raw.upper().replace("_", " ").replace("-", " ")).strip()
    t = t.replace("( C )", "(C)")
    m = _INS_RE.match(t) or _INS_SHORT_RE.match(t)
    if m:
        return _insert_port(m, raw)
    m = _DIRECT_RE.match(t)
    if m:
        n = int(m.group(1))
        return Port(bus="DIRECT", number=n, raw=raw, channel=f"CH {n}")
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
    r"|(?P<stin>(?:ST\s*IN|STEREO\s*IN(?:PUT)?|STIN)\s*(?P<stin_n>\d+)\s*(?P<stin_lr>L|R)?)"
    r"|(?P<mix>MIX\s*(?P<mix_n>\d+))"
    r"|(?P<mtx>(?:MATRIX|MTRX|MT)\s*(?P<mtx_n>\d+))"
    r"|(?P<st>(?:STEREO|ST)\s*(?P<st_lr>L|R)?)"
    r"|(?P<mono>MONO(?:\s*\(?C\)?)?)"
    r"|(?P<dca>DCA\s*(?P<dca_n>\d+))"
    r"|(?P<mute>MUTE\s*(?:GROUP\s*)?(?P<mute_n>\d+)))$",
    re.IGNORECASE,
)


def parse_channel_label(text: str) -> Optional[Tuple[str, int, str]]:
    """``'CH 12' -> ('in', 12, 'CH 12')``; ``'MIX 3' -> ('mix', 3, 'MIX 3')``; ``'ST L' -> ('stereo', 0, 'ST L')``;
    ``'STEREO INPUT 4L' -> ('stin', 4, 'ST IN 4 L')``."""
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


_PLACEHOLDER_NAME = re.compile(r"(?i)^(?:ch|st\s*in|mix|mtx|matrix|dca)\s*\d+$")


def is_placeholder_name(name: str) -> bool:
    """``ch28`` / ``DCA10`` style default names the console shows when nothing was typed."""
    return bool(_PLACEHOLDER_NAME.match((name or "").strip()))


@dataclass
class ConsoleChannel:
    kind: str  # in | stin | mix | matrix | stereo | mono | dca | mute
    index: int
    label: str
    name: str = ""
    color: str = ""
    icon: str = ""
    tag: str = ""  # stin only: L / R half
    patch: Optional[Port] = None  # input patch (inputs) / none for buses
    outputs: List[Port] = field(default_factory=list)  # physical output ports fed by this bus (PortRackPatch)
    direct_outs: List[Port] = field(default_factory=list)  # input channels: ports fed by the direct out (PortRackPatch ``DIR CH n``)
    rack_feeds: List[Port] = field(default_factory=list)  # rack inputs fed straight from this bus / direct out (``FX 1A ← MIX 17``)
    insert_sends: Dict[int, List[Port]] = field(default_factory=dict)  # insert 1/2 send → rack inputs (PortRackPatch ``… ← INS CH n``)
    insert_returns: Dict[int, Port] = field(default_factory=dict)  # insert 1/2 return ← rack output (InPatch / OutPatch ``INS CH n``)

    @property
    def is_input(self) -> bool:
        return self.kind in ("in", "stin")

    @property
    def is_bus(self) -> bool:
        return self.kind in ("mix", "matrix", "stereo", "mono")

    @property
    def category(self) -> str:
        return categorize(self.name, self.icon)

    @property
    def insert1(self) -> Optional[Port]:
        return self.insert_returns.get(1)

    @property
    def insert2(self) -> Optional[Port]:
        return self.insert_returns.get(2)

    @property
    def has_output(self) -> bool:
        return bool(self.outputs or self.rack_feeds or any(self.insert_sends.values()))

    def feeds_text(self) -> str:
        """``DANTE 28, GEQ 7A (via insert send)`` — everything this bus / channel feeds."""
        parts = [p.text for p in self.outputs] + [p.text for p in self.direct_outs] + [p.text for p in self.rack_feeds]
        for slot in sorted(self.insert_sends):
            parts.extend(f"{p.text} (via insert {slot} send)" if slot == 2 else f"{p.text} (via insert send)" for p in self.insert_sends[slot])
        return ", ".join(parts)


@dataclass
class OutputPatch:
    port: Port  # output connector (DANTE / OMNI / SLOT / REC) or rack input (GEQ / FX / PRFX)
    source: Optional[Port]  # MIX 1 / STEREO L / DIR CH 3 / INS CH 25 ...
    raw_source: str = ""


class ConsoleData(ParseResult):
    kind = "yamaha"

    def __init__(self) -> None:
        super().__init__()
        self.model = ""
        self.firmware = ""
        self.console_name = ""
        self.channels: Dict[str, ConsoleChannel] = {}  # by label
        self.output_patches: List[OutputPatch] = []  # physical output port ← console signal
        self.rack_patches: List[OutputPatch] = []  # rack input ← console signal
        self.files_by_role: Dict[str, List[str]] = {}
        self.sections: List[str] = []  # [SectionName] tags seen in console exports
        self.warnings: List[str] = []  # anomalies worth a look; never errors

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    # -- access helpers
    def channel(self, kind: str, index: int, tag: str = "") -> ConsoleChannel:
        label = {"in": f"CH {index}", "stin": f"ST IN {index}{(' ' + tag) if tag else ''}", "mix": f"MIX {index}", "matrix": f"MATRIX {index}",
                 "stereo": "ST L" if index == 0 else "ST R", "mono": "MONO", "dca": f"DCA {index}", "mute": f"MUTE {index}"}[kind]
        ch = self.channels.get(label)
        if ch is None:
            ch = ConsoleChannel(kind=kind, index=index, label=label, tag=tag if kind == "stin" else "")
            self.channels[label] = ch
        return ch

    def channel_by_label(self, label: str) -> Optional[ConsoleChannel]:
        parsed = parse_channel_label(label)
        if not parsed:
            return None
        kind, idx, lab = parsed
        tag = lab.rsplit(" ", 1)[-1] if kind == "stin" and lab[-1:] in ("L", "R") else ""
        return self.channel(kind, idx, tag)

    def channel_for_source(self, port: Optional[Port]) -> Optional[ConsoleChannel]:
        """Console channel a PortRackPatch / insert source refers to (bus, direct out or insert send)."""
        if port is None:
            return None
        if port.bus in _BUS_KIND:
            idx = port.number if port.number is not None else (1 if port.tag == "R" else 0)
            return self.channel(_BUS_KIND[port.bus], idx)
        if port.bus in ("INS", "DIRECT") and port.channel:
            return self.channel_by_label(port.channel)
        return None

    @property
    def inputs(self) -> List[ConsoleChannel]:
        return sorted((c for c in self.channels.values() if c.is_input), key=lambda c: (c.kind != "in", c.index, c.tag))

    @property
    def mono_inputs(self) -> List[ConsoleChannel]:
        return [c for c in self.inputs if c.kind == "in"]

    @property
    def stereo_inputs(self) -> List[ConsoleChannel]:
        return [c for c in self.inputs if c.kind == "stin"]

    @property
    def named_inputs(self) -> List[ConsoleChannel]:
        return [c for c in self.inputs if c.name and c.name.strip() and not re.fullmatch(r"(?i)(ch|st in)\s*\d+", c.name.strip())]

    @property
    def buses(self) -> List[ConsoleChannel]:
        order = {"mix": 0, "matrix": 1, "stereo": 2, "mono": 3}
        return sorted((c for c in self.channels.values() if c.kind in order), key=lambda c: (order[c.kind], c.index))

    @property
    def dcas(self) -> List[ConsoleChannel]:
        return sorted((c for c in self.channels.values() if c.kind == "dca"), key=lambda c: c.index)

    def dante_input_map(self) -> Dict[int, ConsoleChannel]:
        """Dante *receive* channel number → console input channel patched from it (InPatch namespace)."""
        out: Dict[int, ConsoleChannel] = {}
        for c in self.inputs:
            if c.patch and c.patch.bus == "DANTE" and c.patch.number:
                out.setdefault(c.patch.number, c)
        return out

    def dante_output_map(self) -> Dict[int, OutputPatch]:
        """Dante *transmit* channel number → what feeds it (PortRackPatch namespace, unrelated to the input map)."""
        out: Dict[int, OutputPatch] = {}
        for op in self.output_patches:
            if op.port.bus == "DANTE" and op.port.number:
                out[op.port.number] = op
        return out

    def output_port_map(self) -> Dict[str, OutputPatch]:
        return {op.port.text: op for op in self.output_patches}

    def rack_input_map(self) -> Dict[str, OutputPatch]:
        return {op.port.text: op for op in self.rack_patches}

    def patch_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for c in self.inputs:
            if c.patch and c.patch.bus != "NONE":
                key = c.patch.text.split(" ")[0] if c.patch.bus != "SLOT" else f"SLOT{c.patch.slot}"
                counts[key] = counts.get(key, 0) + 1
        return counts

    def source_name(self, port: Optional[Port]) -> str:
        """Name of the console channel behind a PortRackPatch source (``MIX 1`` → ``1 IEM``, ``DIR CH 43`` → ``Video L``)."""
        ch = self.channel_for_source(port)
        return ch.name if ch else ""

    # -- resolved views (joins across the files)
    def rack_table(self) -> List[Dict[str, str]]:
        """One row per rack I/O: what feeds it, where its output returns, and whether the loop closes."""
        fed: Dict[str, OutputPatch] = self.rack_input_map()
        returns: Dict[str, List[Tuple[ConsoleChannel, int]]] = {}
        for ch in self.channels.values():
            for slot, port in ch.insert_returns.items():
                returns.setdefault(port.text, []).append((ch, slot))
            if ch.kind == "stin" and ch.patch and ch.patch.is_rack:
                returns.setdefault(ch.patch.text, []).append((ch, 0))

        def sort_key(text: str) -> Tuple[int, int, str]:
            p = parse_port(text)
            return (RACK_BUSES.index(p.bus) if p and p.bus in RACK_BUSES else 9, (p.number or 0) if p else 0, (p.tag if p else ""))

        rows = []
        for text in sorted(set(fed) | set(returns), key=sort_key):
            op = fed.get(text)
            src = op.source.text if op and op.source else "NONE"
            rets = returns.get(text, [])
            ret_text = ", ".join(_return_label(ch, slot) for ch, slot in rets) or "NONE"
            status = "fed, output not returned anywhere"
            if rets:
                if all(slot == 0 for _, slot in rets):
                    if op is None or op.source is None:
                        status = "FX return (input not fed: mono-in effect or unused)"
                    elif op.source.bus == "INS":
                        status = f"FX send/return fed from an insert send ({src}); check that insert's return"
                    else:
                        status = "FX send/return"
                else:
                    ok = op is not None and op.source is not None and op.source.bus == "INS" and any(
                        slot and (op.source.insert or 1) == slot and self.channel_for_source(op.source) is ch for ch, slot in rets)
                    if ok:
                        status = "OK closed insert loop"
                    elif op is None or op.source is None:
                        status = "OPEN: insert return patched but the rack input is not fed"
                    else:
                        status = f"OPEN: insert return patched but the rack is fed by {src}"
            rows.append({"rack": text, "fed_by": src, "returns_to": ret_text, "status": status})
        return rows

    def insert_loops(self) -> List[Dict[str, str]]:
        return [r for r in self.rack_table() if "insert" in r["status"]]

    def dca_names(self) -> Dict[str, str]:
        return {d.label: d.name for d in self.dcas}

    def summary(self) -> Dict[str, object]:
        inputs = self.inputs
        racks = self.rack_table()
        out: Dict[str, object] = {
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
        if self.sections:
            out.update({
                "firmware": self.firmware,
                "sections": list(self.sections),
                "mono_inputs": len(self.mono_inputs),
                "stereo_inputs": len(self.stereo_inputs),
                "buses": len(self.buses),
                "buses_patched": sum(1 for b in self.buses if b.has_output),
                "dcas": len(self.dcas),
                "direct_outs": sum(len(c.direct_outs) for c in inputs),
                "rack_patches": len(self.rack_patches),
                "insert_loops_closed": sum(1 for r in racks if r["status"].startswith("OK")),
                "insert_loops_open": sum(1 for r in racks if r["status"].startswith("OPEN")),
                "fx_returns": sum(1 for r in racks if r["status"].startswith("FX")),
                "warnings": list(self.warnings),
            })
        return out


def _return_label(ch: ConsoleChannel, slot: int) -> str:
    if slot == 0:
        return ch.label
    return f"INS{'2' if slot == 2 else ''} {ch.label}"


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


# ------------------------------------------------ console exports ([Section] files)

_SECTION_RE = re.compile(r"^\[([A-Za-z0-9_ /-]+)\]$")
_INDEX_RE = re.compile(r"^_?0*(\d+)$")

#: [Section] tag (lower-case) → (role, channel kind)
_NAME_SECTIONS: Dict[str, str] = {
    "inname": "in", "inputname": "in", "inchname": "in",
    "stname": "stin", "stinname": "stin", "stereoinname": "stin",
    "mixname": "mix", "mtxname": "matrix", "matrixname": "matrix",
    "stmononame": "stmono", "stereomononame": "stmono",
    "dcaname": "dca", "mutename": "mute", "mutegroupname": "mute",
}
_PATCH_SECTIONS: Dict[str, str] = {
    "inpatch": "input_patch", "inputpatch": "input_patch",
    "outpatch": "insert_patch", "outputpatch": "insert_patch",
    "portrackpatch": "output_patch", "portpatch": "output_patch", "rackpatch": "output_patch",
}


def console_section(rows: Sequence[Sequence[str]]) -> Optional[Tuple[str, str, str, int]]:
    """``(section, model, firmware, header_row_index)`` for a console export, else ``None``.

    Console exports start with ``[Information]``, the model, the firmware and
    the ``[SectionName]`` line; the row after that is the column header.
    """
    if not rows or not _SECTION_RE.match(rows[0][0] or ""):
        return None
    section, idx = "", -1
    for i, r in enumerate(rows[:6]):
        m = _SECTION_RE.match(r[0] or "")
        if m and m.group(1).strip().lower() != "information":
            section, idx = m.group(1).strip(), i
            break
    if not section:
        return None
    model = firmware = ""
    for r in rows[1:idx]:
        c = (r[0] or "").strip()
        if not model and _MODEL_RE.search(c):
            model = _MODEL_RE.search(c).group(1).upper()  # type: ignore[union-attr]
        elif not firmware and re.match(r"^V?\d+(\.\d+)*$", c, re.I):
            firmware = c
    return section, model, firmware, idx


def _section_index(text: str) -> Optional[int]:
    m = _INDEX_RE.match((text or "").strip())
    return int(m.group(1)) if m else None


def _ingest_section(data: ConsoleData, section: str, rows: List[List[str]], fname: str) -> str:
    """Ingest one ``[Section]`` file. Returns the role recorded in ``files_by_role``."""
    key = re.sub(r"[^a-z0-9]", "", section.lower())
    header: List[str] = []
    body = rows
    if rows and not any(re.search(r"\d", c or "") for c in rows[0]):
        header, body = list(rows[0]), rows[1:]
    if key in _NAME_SECTIONS:
        cols: Dict[str, Optional[int]] = {"name": 1, "color": 2, "icon": 3}
        if header:
            for k, cands in (("name", ("name", "channel name", "label")), ("color", ("color", "colour")), ("icon", ("icon",))):
                found = column_index(header, *cands)
                if found is not None and found != 0:
                    cols[k] = found
        _ingest_section_names(data, _NAME_SECTIONS[key], cols, body)
        return "names"
    if key in _PATCH_SECTIONS:
        src_idx = (column_index(header, "source", "port", "patch") if header else None)
        if src_idx is None or src_idx == 0:
            src_idx = 1
        role = _PATCH_SECTIONS[key]
        if role == "output_patch":
            _ingest_port_patch(data, body, 0, src_idx, fname)
        else:
            _ingest_channel_patch(data, body, 0, src_idx, fname)
        return role
    data.note(f"{fname}: section [{section}] is not used by Fathom")
    return "unknown"


def _ingest_section_names(data: ConsoleData, kind: str, cols: Dict[str, Optional[int]], rows: List[List[str]]) -> None:
    for r in rows:
        n = _section_index(cell(r, 0))
        if n is None:
            parsed = parse_channel_label(cell(r, 0))
            if not parsed:
                continue
            ch = data.channel_by_label(parsed[2])
        elif kind == "stin":  # _01/_02 = ST IN 1 L/R, _(2n-1)/_(2n) = ST IN n L/R
            ch = data.channel("stin", (n + 1) // 2, "L" if n % 2 else "R")
        elif kind == "stmono":
            ch = data.channel("stereo", 0) if n == 1 else data.channel("stereo", 1) if n == 2 else data.channel("mono", 0)
        else:
            ch = data.channel(kind, n)
        if ch is None:
            continue
        ch.name = cell(r, cols.get("name"))  # trimmed by read_rows; blank names stay blank
        color = cell(r, cols.get("color"))
        if color:
            ch.color = normalize_color(color)
        icon = cell(r, cols.get("icon"))
        if icon:
            ch.icon = normalize_icon(icon)


def _ingest_channel_patch(data: ConsoleData, rows: List[List[str]], label_idx: int, src_idx: int, fname: str) -> None:
    """[InPatch] / [OutPatch]: channel sources and insert returns."""
    unknown = 0
    for r in rows:
        label, src_raw = cell(r, label_idx), cell(r, src_idx)
        if not label:
            continue
        parsed = parse_channel_label(label)
        if parsed and parsed[0] in ("in", "stin"):
            ch = data.channel_by_label(parsed[2])
            port = parse_port(src_raw)
            if ch is not None and port is not None:
                ch.patch = port
            continue
        point = parse_port(label)
        if point is not None and point.bus == "INS" and point.channel:
            ch = data.channel_by_label(point.channel)
            ret = parse_port(src_raw)
            if ch is not None and ret is not None and ret.bus != "NONE":
                ch.insert_returns[point.insert or 1] = ret
            elif ch is not None:
                ch.insert_returns.pop(point.insert or 1, None)
            continue
        unknown += 1
    if unknown:
        data.note(f"{fname}: {unknown} rows not understood (neither channel source nor insert return)")


def _ingest_port_patch(data: ConsoleData, rows: List[List[str]], port_idx: int, src_idx: int, fname: str = "") -> None:
    """[PortRackPatch] (and legacy ``PORT,SOURCE`` files): what feeds each output connector and rack input."""
    for r in rows:
        port = parse_port(cell(r, port_idx))
        if not port or port.bus == "NONE":
            continue
        src_raw = cell(r, src_idx)
        src = parse_port(src_raw)
        if src and src.bus == "NONE":
            continue
        if not src and not src_raw:
            continue
        entry = OutputPatch(port=port, source=src, raw_source=src_raw)
        (data.rack_patches if port.is_rack else data.output_patches).append(entry)
        target = data.channel_for_source(src)
        if target is None or src is None:
            continue
        if src.bus == "INS":
            target.insert_sends.setdefault(src.insert or 1, []).append(port)
        elif port.is_rack:
            target.rack_feeds.append(port)
        elif src.bus == "DIRECT":
            target.direct_outs.append(port)
        else:
            target.outputs.append(port)


def _finalize(data: ConsoleData) -> None:
    """Section 5-style anomaly scan: everything here is a warning, never an error."""
    have_in_patch = "input_patch" in data.files_by_role
    have_port_patch = "output_patch" in data.files_by_role
    inputs = data.inputs

    def label_name(ch: ConsoleChannel) -> str:
        return f"{ch.label} ({ch.name})" if ch.name and ch.name.strip().upper() != ch.label else ch.label

    # 1. one physical input feeding several channels
    by_source: Dict[str, List[ConsoleChannel]] = {}
    for ch in inputs:
        if ch.patch and ch.patch.is_physical_input:
            by_source.setdefault(ch.patch.text, []).append(ch)
    for src, chans in by_source.items():
        if len(chans) > 1:
            data.warn(f"{src} is patched to {len(chans)} input channels: {', '.join(label_name(c) for c in chans)}")

    # 2. insert loops that do not close
    rack_fed = data.rack_input_map()
    for ch in list(inputs) + list(data.buses):
        for slot, racks in sorted(ch.insert_sends.items()):
            for rack in racks:
                ret = ch.insert_returns.get(slot)
                if ret is None or ret.text != rack.text:
                    data.warn(f"INS{'2' if slot == 2 else ''} {ch.label} feeds {rack.text} but insert {slot} return of {label_name(ch)} is "
                              f"{ret.text if ret else 'NONE'} (open insert loop)")
        for slot, ret in sorted(ch.insert_returns.items()):
            op = rack_fed.get(ret.text)
            if op is None or op.source is None:
                data.warn(f"{label_name(ch)} insert {slot} returns from {ret.text} but nothing feeds {ret.text}")
            elif not (op.source.bus == "INS" and (op.source.insert or 1) == slot and data.channel_for_source(op.source) is ch):
                data.warn(f"{label_name(ch)} insert {slot} returns from {ret.text} but {ret.text} is fed by {op.source.text}")

    if have_port_patch:
        # 3. FX send buses that also leave the console
        for b in data.buses:
            fx = [p.text for p in b.rack_feeds if p.bus == "FX"]
            if fx and b.outputs:
                data.warn(f"{label_name(b)} feeds {', '.join(fx)} and also output {', '.join(p.text for p in b.outputs)} (FX send bus also leaves the console)")
        # 4. buses that go nowhere
        unpatched = [b for b in data.buses if not b.has_output]
        if unpatched:
            data.warn("not patched to any output port or rack: " + ", ".join(label_name(b) for b in unpatched))

    if have_in_patch:
        # 5. named channels with no source / 6. patched channels with default names
        no_src = [c for c in inputs if c.name and not is_placeholder_name(c.name) and (c.patch is None or c.patch.bus == "NONE")]
        if no_src:
            data.warn("named but no input source: " + ", ".join(label_name(c) for c in no_src))
        placeholder = [c for c in inputs if c.patch and c.patch.bus != "NONE" and is_placeholder_name(c.name)]
        if placeholder:
            data.warn("patched but still carrying the default name: " + ", ".join(f"{c.label} ({c.name} ← {c.patch.text})" for c in placeholder))  # type: ignore[union-attr]

    # 7. duplicate names (stereo halves legitimately share a name)
    for kind, group in (("in", data.mono_inputs), ("mix", [b for b in data.buses if b.kind == "mix"]),
                        ("matrix", [b for b in data.buses if b.kind == "matrix"]), ("dca", data.dcas)):
        seen: Dict[str, List[ConsoleChannel]] = {}
        for ch in group:
            if ch.name and not is_placeholder_name(ch.name):
                seen.setdefault(ch.name.strip().lower(), []).append(ch)
        for chans in seen.values():
            if len(chans) > 1:
                data.warn("same name on " + " and ".join(f"{c.label} '{c.name}'" for c in chans))


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
            sec = console_section(all_rows)
            if sec is not None:
                section, model, firmware, idx = sec
                data.sections.append(section)
                data.model = data.model or model
                data.firmware = data.firmware or firmware
                role = _ingest_section(data, section, all_rows[idx + 1:], f.name)
                data.source_files.append(str(f))
                data.files_by_role.setdefault(role, []).append(f.name)
                continue
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
            _ingest_port_patch(data, rows, cols.get("port", 0), cols.get("source", 1), f.name)
        else:
            data.note(f"{f.name}: not recognised as channel names / input patch / output patch")
        if not data.model:
            data.model = _detect_model(all_rows) or _detect_model([[f.stem]])
    if not data.channels and not data.output_patches:
        data.note("no channel data found (expected CL/QL CSV exports: channel names, input patch, output patch)")
    _finalize(data)
    return data


def _ingest_names(data: ConsoleData, cols: Dict[str, int], rows: List[List[str]]) -> None:
    for r in rows:
        parsed = parse_channel_label(cell(r, cols.get("channel")))
        if not parsed:
            continue
        ch = data.channel_by_label(parsed[2])
        if ch is None:
            continue
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
        kind, _idx, label = parsed
        if kind not in ("in", "stin"):
            continue
        ch = data.channel_by_label(label)
        if ch is None:
            continue
        port = parse_port(cell(r, cols.get("port")))
        if port:
            ch.patch = port
        name = cell(r, cols.get("name"))
        if name and not ch.name:
            ch.name = name


def describe_patch_source(port: Optional[Port]) -> str:
    if port is None:
        return ""
    if port.bus == "SLOT":
        return f"Slot {port.slot} ch {port.number}"
    if port.bus == "DANTE":
        return f"Dante {port.number}"
    if port.bus == "OMNI":
        return f"Omni {port.number}"
    if port.bus == "REC":
        return f"Rec {port.number}"
    if port.is_rack or port.bus in ("INS", "DIRECT"):
        return port.text
    return port.text.title()


def summarize_ranges(channels: Sequence[ConsoleChannel]) -> str:
    return compress_ranges(c.index for c in channels if c.kind == "in")
