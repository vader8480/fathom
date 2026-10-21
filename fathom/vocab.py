"""AVL vocabulary: device kinds, media, disciplines, brands, connectors, enums.

Single source for Python (model, renderers, analysis) and, via ``as_dict()``
(``GET /api/v2/meta``, ``fathom vocab --json``), for the browser. Tables are
Appendix A of docs/SPEC.md verbatim. The first 9 kinds and first 14 media are
the v0.2 entries: their colors / line styles never change.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, FrozenSet, List, Tuple

# ------------------------------------------------------------- disciplines

DISCIPLINES: Dict[str, Dict[str, str]] = {
    "audio": {"label": "Audio", "color": "#4ea8ff", "letter": "A"},
    "video": {"label": "Video", "color": "#34d399", "letter": "V"},
    "lighting": {"label": "Lighting", "color": "#fbbf24", "letter": "L"},
    "network": {"label": "Network", "color": "#fb923c", "letter": "N"},
    "control": {"label": "Control", "color": "#c084fc", "letter": "C"},
    "power": {"label": "Power", "color": "#f87171", "letter": "P"},
    "other": {"label": "Other", "color": "#9aa3b5", "letter": "X"},
}

# ------------------------------------------------------------------- kinds


def _k(label: str, discipline: str, color: str, side: str, routing: str, legacy: str) -> Dict[str, Any]:
    return {"label": label, "discipline": discipline, "color": color, "side": side, "routing": routing, "legacy": legacy}


#: Device kinds (Appendix A.1). ``legacy`` = v1 kind whose layout heuristics apply.
KINDS: Dict[str, Dict[str, Any]] = {
    "source": _k("Sources", "audio", "#2fd4b4", "left", "none", "source"),
    "stage_io": _k("Stage I/O", "audio", "#4ea8ff", "left", "matrix", "stage_io"),
    "computer": _k("Computers", "audio", "#a98bff", "left", "matrix", "computer"),
    "console": _k("Consoles", "audio", "#7c5cff", "right", "matrix", "console"),
    "iem": _k("IEM gear", "audio", "#f06aa8", "right", "matrix", "iem"),
    "pa": _k("PA · amps, speakers", "audio", "#ff9548", "right", "matrix", "pa"),
    "network": _k("Network", "network", "#7b86ff", "right", "matrix", "network"),
    "video": _k("Video", "video", "#c084fc", "left", "matrix", "video"),
    "other": _k("Other", "other", "#9aa3b5", "right", "matrix", "other"),
    "mic": _k("Microphones", "audio", "#2fd4b4", "left", "none", "source"),
    "wireless_rx": _k("Wireless receivers", "audio", "#38bdf8", "left", "matrix", "stage_io"),
    "processor": _k("Processors · DSP", "audio", "#60a5fa", "right", "matrix", "console"),
    "amp": _k("Amplifiers", "audio", "#fb923c", "right", "matrix", "pa"),
    "speaker": _k("Loudspeakers", "audio", "#fdba74", "right", "passthrough", "pa"),
    "recorder": _k("Recorders", "audio", "#a78bfa", "right", "matrix", "computer"),
    "intercom": _k("Intercom", "audio", "#f472b6", "right", "matrix", "other"),
    "camera": _k("Cameras", "video", "#34d399", "left", "matrix", "video"),
    "video_source": _k("Playback · media servers", "video", "#2dd4bf", "left", "matrix", "video"),
    "video_switcher": _k("Video switchers", "video", "#22c55e", "right", "matrix", "console"),
    "video_router": _k("Video routers", "video", "#10b981", "right", "matrix", "console"),
    "converter": _k("Converters · extenders", "video", "#86efac", "right", "matrix", "video"),
    "encoder": _k("Encoders · streaming", "video", "#4ade80", "right", "matrix", "computer"),
    "stream": _k("Stream destinations", "network", "#fb923c", "right", "none", "pa"),
    "display": _k("Displays", "video", "#a3e635", "right", "passthrough", "pa"),
    "projector": _k("Projectors", "video", "#bef264", "right", "none", "pa"),
    "lighting_console": _k("Lighting consoles", "lighting", "#fbbf24", "left", "matrix", "console"),
    "dmx_node": _k("DMX nodes · splitters", "lighting", "#f59e0b", "right", "matrix", "stage_io"),
    "dimmer": _k("Dimmers · relays", "lighting", "#eab308", "right", "matrix", "pa"),
    "fixture": _k("Lighting fixtures", "lighting", "#fde047", "right", "passthrough", "pa"),
    "switch": _k("Network switches", "network", "#fb923c", "right", "matrix", "network"),
    "control": _k("Control processors", "control", "#c084fc", "right", "matrix", "other"),
    "touch_panel": _k("Touch panels", "control", "#d8b4fe", "left", "none", "source"),
    "power": _k("Power · UPS · PDU", "power", "#f87171", "right", "matrix", "other"),
    "patch_panel": _k("Patch panels · wall plates", "other", "#94a3b8", "right", "passthrough", "stage_io"),
}

# ------------------------------------------------------------------- media

_A, _V, _L, _N, _C, _P = "audio", "video", "lighting", "network", "control", "power"


def _m(label: str, discipline: str, color: str, dash: str, width: float, arrow: bool, carries: Tuple[str, ...], ip: bool, connector: str, short: str) -> Dict[str, Any]:
    return {
        "label": label, "color": color, "dash": dash, "width": width, "arrow": arrow,
        "discipline": discipline, "carries": list(carries), "ip": ip, "connector": connector, "short": short,
    }


#: Cable / transport types (Appendix A.2). ``dash`` is an SVG stroke-dasharray ("" = solid).
MEDIA: Dict[str, Dict[str, Any]] = {
    "dante": _m("Dante · Cat6", _A, "#7b86ff", "", 1.6, False, (_A, _N), True, "etherCON", "DANTE"),
    "analog": _m("Analog · XLR", _A, "#aab3c5", "", 1.4, True, (_A,), False, "XLR3", "XLR"),
    "aes3": _m("AES3 · 110 Ω", _A, "#2dd4ee", "7 4", 1.5, True, (_A,), False, "XLR3", "AES"),
    "aes50": _m("AES50 · Cat5e", _A, "#5ac8fa", "2 4", 1.6, False, (_A, _C), False, "etherCON", "AES50"),
    "madi": _m("MADI", _A, "#fbbf24", "10 4", 1.5, True, (_A,), False, "BNC", "MADI"),
    "avb": _m("AVB / Milan", _A, "#34d399", "6 3 2 3", 1.5, False, (_A, _N), True, "etherCON", "AVB"),
    "speaker": _m("Speaker · NL4/NL8", _A, "#ff9548", "", 1.8, True, (_A,), False, "NL4", "SPK"),
    "iem_wired": _m("Wired IEM", _A, "#f472b6", "1.5 4", 1.6, True, (_A,), False, 'TRS 1/4"', "IEM"),
    "iem_wireless": _m("Wireless IEM", _A, "#e879f9", "1.5 6", 1.6, True, (_A,), False, "RF", "IEM"),
    "rf": _m("RF · wireless mic", _A, "#f0abfc", "1.5 6", 1.6, True, (_A,), False, "BNC", "RF"),
    "usb": _m("USB", "other", "#cbd5e1", "4 3", 1.2, True, (_A, _V, _C), False, "USB-C", "USB"),
    "video": _m("SDI / HDMI", _V, "#c084fc", "", 1.2, True, (_V, _A), False, "BNC", "VID"),
    "network": _m("Control · IP", _N, "#94a3b8", "3 3", 1.0, False, (_N, _C, _A, _V, _L), True, "RJ45", "CAT"),
    "other": _m("Other", "other", "#9aa3b5", "", 1.2, True, (_A, _V, _L, _C, _N, _P), False, "", "OTH"),
    "aes67": _m("AES67 · IP audio", _A, "#818cf8", "", 1.6, False, (_A, _N), True, "RJ45", "AES67"),
    "qlan": _m("Q-LAN", _A, "#60a5fa", "", 1.6, False, (_A, _V, _C, _N), True, "RJ45", "QLAN"),
    "snake": _m("Digital snake · Cat5e", _A, "#38bdf8", "2 3", 1.6, False, (_A, _C), False, "etherCON", "SNAKE"),
    "adat": _m("ADAT · optical", _A, "#67e8f9", "1 3", 1.4, True, (_A,), False, "TOSLINK", "ADAT"),
    "speaker_70v": _m("70/100 V line", _A, "#fdba74", "8 3", 1.6, True, (_A,), False, "terminal", "70V"),
    "intercom": _m("Intercom · XLR", _A, "#fb7185", "5 2 1 2", 1.4, False, (_A, _C), False, "XLR3", "COM"),
    "sdi": _m("SDI · 75 Ω BNC", _V, "#facc15", "", 1.6, True, (_V, _A), False, "BNC", "SDI"),
    "hdmi": _m("HDMI", _V, "#f59e0b", "", 1.6, True, (_V, _A), False, "HDMI-A", "HDMI"),
    "displayport": _m("DisplayPort", _V, "#fda4af", "", 1.4, True, (_V, _A), False, "DP", "DP"),
    "hdbaset": _m("HDBaseT · Cat6", _V, "#fcd34d", "5 2", 1.6, True, (_V, _A, _C), False, "RJ45", "HDBT"),
    "fiber": _m("Fiber", "other", "#22d3ee", "12 3", 1.6, False, (_A, _V, _N, _C, _L), False, "LC", "FIB"),
    "ndi": _m("NDI · IP video", _V, "#a3e635", "4 2", 1.4, False, (_V, _A, _N), True, "RJ45", "NDI"),
    "st2110": _m("SMPTE ST 2110", _V, "#84cc16", "4 2 1 2", 1.4, False, (_V, _A, _N), True, "SFP", "2110"),
    "dmx": _m("DMX512 · XLR5", _L, "#fde047", "", 1.6, True, (_L,), False, "XLR5", "DMX"),
    "rdm": _m("DMX + RDM", _L, "#fef08a", "6 2", 1.6, False, (_L, _C), False, "XLR5", "RDM"),
    "sacn": _m("sACN (E1.31)", _L, "#fbbf24", "3 2", 1.4, True, (_L, _N), True, "RJ45", "SACN"),
    "artnet": _m("Art-Net", _L, "#f59e0b", "3 2 1 2", 1.4, True, (_L, _N), True, "RJ45", "ARTN"),
    "rs232": _m("RS-232 · serial", _C, "#c4b5fd", "2 2", 1.0, True, (_C,), False, "DB9", "232"),
    "rs422": _m("RS-422/485", _C, "#a78bfa", "2 2", 1.0, False, (_C,), False, "Phoenix", "422"),
    "ir": _m("IR emitter", _C, "#ddd6fe", "1 3", 1.0, True, (_C,), False, "TS 3.5mm", "IR"),
    "gpio": _m("GPIO · contact closure", _C, "#e9d5ff", "1 2", 1.0, True, (_C,), False, "Phoenix", "GPIO"),
    "osc": _m("OSC · IP control", _C, "#d8b4fe", "3 3", 1.0, True, (_C, _N), True, "RJ45", "OSC"),
    "midi": _m("MIDI", _C, "#f0abfc", "2 3", 1.0, True, (_C,), False, "DIN5", "MIDI"),
    "timecode": _m("Timecode (LTC)", _C, "#f5d0fe", "1 2", 1.0, True, (_C,), False, "XLR3", "LTC"),
    "sync": _m("Sync · word clock / genlock", "other", "#94a3b8", "1 4", 1.0, True, (_C,), False, "BNC", "SYNC"),
    "power": _m("Power · mains", _P, "#f87171", "", 2.0, True, (_P,), False, "IEC C13", "PWR"),
    "power_dc": _m("DC power", _P, "#fca5a5", "", 1.4, True, (_P,), False, "barrel", "DC"),
}

# ------------------------------------------------------------------ brands

#: Brand badges: text pill drawn on the card's top-right. Text only, no logos.
BRANDS: Dict[str, Dict[str, str]] = {
    "yamaha": {"text": "YAMAHA", "bg": "#1a1a1a", "fg": "#ffffff", "style": "wordmark"},
    "shure": {"text": "SHURE", "bg": "#f3f4f6", "fg": "#111111", "style": "bold-italic"},
    "focusrite": {"text": "Focusrite", "bg": "#f3f4f6", "fg": "#c2410c", "style": "serif"},
    "neve": {"text": "N", "bg": "#d7263d", "fg": "#ffffff", "style": "mono"},
    "ross": {"text": "ROSS", "bg": "#f3f4f6", "fg": "#c01830", "style": "bold"},
    "genelec": {"text": "GENELEC", "bg": "#ffffff", "fg": "#0b6e4f", "style": "bold"},
    "waves": {"text": "W", "bg": "#111111", "fg": "#ffffff", "style": "mono"},
    "ableton": {"text": "▮▮▮", "bg": "#f3f4f6", "fg": "#111111", "style": "mono"},
    "avid": {"text": "AVID", "bg": "#7c3aed", "fg": "#ffffff", "style": "bold"},
    "l-acoustics": {"text": "L-A", "bg": "#f3f4f6", "fg": "#111111", "style": "mono"},
    "lectrosonics": {"text": "LECTRO", "bg": "#1f2937", "fg": "#e5e7eb", "style": "bold"},
    "behringer": {"text": "BEHRINGER", "bg": "#1f2937", "fg": "#facc15", "style": "bold"},
    "midas": {"text": "MIDAS", "bg": "#1f2937", "fg": "#e5e7eb", "style": "bold"},
    "sennheiser": {"text": "SENNHEISER", "bg": "#111111", "fg": "#ffffff", "style": "bold"},
    "allen-heath": {"text": "A&H", "bg": "#111111", "fg": "#ffffff", "style": "bold"},
    "digico": {"text": "DiGiCo", "bg": "#111111", "fg": "#ffffff", "style": "bold"},
    "qsc": {"text": "QSC", "bg": "#111111", "fg": "#60a5fa", "style": "bold"},
    "powersoft": {"text": "POWERSOFT", "bg": "#111111", "fg": "#ffffff", "style": "bold"},
    "d&b": {"text": "d&b", "bg": "#f3f4f6", "fg": "#111111", "style": "bold"},
    "meyer": {"text": "MEYER", "bg": "#f3f4f6", "fg": "#111111", "style": "bold"},
    "audinate": {"text": "Dante", "bg": "#1d4ed8", "fg": "#ffffff", "style": "bold"},
    "blackmagic": {"text": "BMD", "bg": "#111111", "fg": "#f59e0b", "style": "bold"},
    "apple": {"text": "", "bg": "#f3f4f6", "fg": "#111111", "style": "mono"},
    "microsoft": {"text": "MS", "bg": "#f3f4f6", "fg": "#111111", "style": "bold"},
    # 0.3 additions (Appendix A.6)
    "ma": {"text": "MA", "bg": "#111111", "fg": "#f5c518", "style": "bold"},
    "etc": {"text": "ETC", "bg": "#111111", "fg": "#ffffff", "style": "bold"},
    "chauvet": {"text": "CHAUVET", "bg": "#111111", "fg": "#e5e7eb", "style": "bold"},
    "martin": {"text": "MARTIN", "bg": "#111111", "fg": "#ef4444", "style": "bold"},
    "panasonic": {"text": "Panasonic", "bg": "#f3f4f6", "fg": "#1d4ed8", "style": "serif"},
    "sony": {"text": "SONY", "bg": "#111111", "fg": "#ffffff", "style": "bold"},
    "epson": {"text": "EPSON", "bg": "#f3f4f6", "fg": "#1e3a8a", "style": "bold"},
    "samsung": {"text": "SAMSUNG", "bg": "#1e3a8a", "fg": "#ffffff", "style": "bold"},
    "extron": {"text": "EXTRON", "bg": "#111111", "fg": "#ffffff", "style": "bold"},
    "crestron": {"text": "CRESTRON", "bg": "#111111", "fg": "#93c5fd", "style": "bold"},
    "cisco": {"text": "CISCO", "bg": "#f3f4f6", "fg": "#0369a1", "style": "bold"},
    "netgear": {"text": "NETGEAR", "bg": "#111111", "fg": "#a78bfa", "style": "bold"},
    "ubiquiti": {"text": "UBNT", "bg": "#f3f4f6", "fg": "#0ea5e9", "style": "bold"},
    "decimator": {"text": "DECIMATOR", "bg": "#111111", "fg": "#f97316", "style": "bold"},
    "whirlwind": {"text": "WHIRLWIND", "bg": "#111111", "fg": "#e5e7eb", "style": "bold"},
    "electro-voice": {"text": "EV", "bg": "#111111", "fg": "#ef4444", "style": "bold"},
}

# ---------------------------------------------------------- other enums

CONNECTORS: List[str] = [
    "XLR3F", "XLR3M", "XLR5F", "XLR5M", "XLR/TRS combo", 'TRS 1/4"', 'TS 1/4"', "TRS 3.5mm", "TS 3.5mm", "RCA",
    "BNC", "HD-BNC", "NL2", "NL4", "NL8", "terminal", "Phoenix", "etherCON", "RJ45", "SFP", "SFP+", "LC", "SC", "ST",
    "opticalCON", "TOSLINK", "HDMI-A", "HDMI-mini", "HDMI-micro", "DP", "mini DP", "USB-A", "USB-B", "USB-C",
    "DB9", "DB15", "DB25", "DIN5", "IEC C13", "IEC C14", "IEC C19", "IEC C20", "powerCON", "powerCON TRUE1",
    "Edison 5-15", "Edison 5-20", "Schuko", "L5-20", "Socapex 19", "barrel", "F-type", "TNC", "DVI", "VGA",
]

STATUSES: Tuple[str, ...] = ("installed", "planned", "spare", "retired")
ROOM_KINDS: Tuple[str, ...] = (
    "auditorium", "sanctuary", "chapel", "theatre", "studio", "control_room", "broadcast",
    "classroom", "conference", "lobby", "outdoor", "rack_room", "storage", "other",
)
PORT_DIRS: Tuple[str, ...] = ("in", "out", "io")
LOCATION_KINDS: Tuple[str, ...] = ("booth", "stage", "rack_room", "storage", "catwalk", "closet", "other")
RACK_NUMBERING: Tuple[str, ...] = ("bottom_up", "top_down")
RACK_FACES: Tuple[str, ...] = ("front", "rear")
RACK_SIDES: Tuple[str, ...] = ("full", "left", "right")
RACK_DEPTHS: Tuple[str, ...] = ("full", "half")
INTERFACE_ROLES: Tuple[str, ...] = ("primary", "secondary", "control", "management", "media")
NETWORK_PROTOCOLS: Tuple[str, ...] = ("dante", "aes67", "avb", "ndi", "st2110", "sacn", "artnet", "qlan", "control", "management", "other")
DMX_PROTOCOLS: Tuple[str, ...] = ("dmx", "sacn", "artnet")
ROUTING_MODES: Tuple[str, ...] = ("matrix", "passthrough", "none", "explicit")
SYMPTOMS: Tuple[str, ...] = (
    "no_audio", "no_video", "noise", "feedback", "dropout", "latency", "no_power", "no_network",
    "lighting_no_response", "flicker", "wrong_source", "general",
)

#: v1 network rule: a v1 port group on these media counts channels, not connectors.
NETWORK_MEDIA: FrozenSet[str] = frozenset({"dante", "avb", "aes67", "aes50", "madi", "snake", "network", "qlan"})
#: kinds that originate signal (trace roots, assistant "sources").
SOURCE_KINDS: FrozenSet[str] = frozenset({"mic", "source", "video_source", "camera", "computer", "lighting_console", "touch_panel"})

#: the 9 v1 kinds and 14 v1 media (compat checks)
V1_KINDS: Tuple[str, ...] = ("source", "stage_io", "computer", "console", "iem", "pa", "network", "video", "other")
V1_MEDIA: Tuple[str, ...] = ("dante", "analog", "aes3", "aes50", "madi", "avb", "speaker", "iem_wired", "iem_wireless", "rf", "usb", "video", "network", "other")


def kind_discipline(kind: str) -> str:
    """Default discipline of a device kind (unknown → ``other``)."""
    k = KINDS.get(kind or "")
    return str(k["discipline"]) if k else "other"


def medium_discipline(medium: str) -> str:
    m = MEDIA.get(medium or "")
    return str(m["discipline"]) if m else "other"


def medium_carries(medium: str) -> Tuple[str, ...]:
    """Disciplines a medium can carry (unknown → ``("other",)``)."""
    m = MEDIA.get(medium or "")
    return tuple(m["carries"]) if m else ("other",)


def discipline_letter(discipline: str) -> str:
    d = DISCIPLINES.get(discipline or "")
    return d["letter"] if d else "X"


def kind_routing(kind: str) -> str:
    k = KINDS.get(kind or "")
    return str(k["routing"]) if k else "matrix"


def as_dict() -> Dict[str, Any]:
    """JSON-ready copy of every table (``GET /api/v2/meta`` → ``vocab``)."""
    return copy.deepcopy({
        "kinds": KINDS,
        "media": MEDIA,
        "disciplines": DISCIPLINES,
        "brands": BRANDS,
        "connectors": CONNECTORS,
        "statuses": list(STATUSES),
        "room_kinds": list(ROOM_KINDS),
        "port_dirs": list(PORT_DIRS),
        "location_kinds": list(LOCATION_KINDS),
        "interface_roles": list(INTERFACE_ROLES),
        "network_protocols": list(NETWORK_PROTOCOLS),
        "dmx_protocols": list(DMX_PROTOCOLS),
        "routing_modes": list(ROUTING_MODES),
        "symptoms": list(SYMPTOMS),
    })


__all__ = [
    "KINDS", "MEDIA", "DISCIPLINES", "BRANDS", "CONNECTORS", "STATUSES", "ROOM_KINDS", "PORT_DIRS",
    "LOCATION_KINDS", "RACK_NUMBERING", "RACK_FACES", "RACK_SIDES", "RACK_DEPTHS", "INTERFACE_ROLES",
    "NETWORK_PROTOCOLS", "DMX_PROTOCOLS", "ROUTING_MODES", "SYMPTOMS", "NETWORK_MEDIA", "SOURCE_KINDS",
    "V1_KINDS", "V1_MEDIA", "as_dict", "kind_discipline", "medium_discipline", "medium_carries",
    "discipline_letter", "kind_routing",
]
