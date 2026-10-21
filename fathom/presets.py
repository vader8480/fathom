"""Built-in device type presets: generic AV / IT infrastructure gear.

A preset is a *generic* device type (UPS, PDU, 24-port switch, patch panel,
stagebox, projector, ...) with a vocabulary ``kind``, sensible default ports,
typical rack units and the fields that matter for that type. Presets are the
quick path in the "Add gear" dialog (pick → pre-filled form → create) and are
also exposed as library templates (``source: "preset"``, lowest precedence),
so ``device.template``, the CSV ``template`` column and "Apply template" all
work with them. The CSV ``kind`` column accepts a preset id, label or alias
(``ups``, ``pdu``, ``patch panel``, ``access point`` ...) and resolves it to
the preset's kind and ports (:func:`resolve_kind`).

Every preset ``kind`` is a key of :data:`fathom.vocab.KINDS`; no new kinds
are introduced, so importers that validate ``kind`` against the vocabulary
stay compatible.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

MANUFACTURER = "Generic"

#: Display order of preset groups (the UI shows them as sections).
GROUPS: Tuple[str, ...] = ("Power", "Network & IT", "Audio", "Video", "Lighting")


def _g(group: str, dir_: str, medium: str, connector: str = "", count: Optional[int] = None, **extra: Any) -> Dict[str, Any]:
    g: Dict[str, Any] = {"group": group, "dir": dir_, "medium": medium}
    if connector:
        g["connector"] = connector
    if count and count > 1:
        g["count"] = count
    g.update(extra)
    return g


def _p(id_: str, label: str, group: str, kind: str, description: str, aliases: List[str], ports: List[Dict[str, Any]],
       ru: Optional[int] = None, **fields: Any) -> Dict[str, Any]:
    p: Dict[str, Any] = {"id": id_, "label": label, "group": group, "kind": kind, "description": description,
                         "aliases": list(aliases), "ru": ru, "ports": ports}
    p.update(fields)
    return p


_NET, _FIB = "network", "fiber"

#: The presets, in display order. ``ru`` None = not rack-mounted.
PRESETS: List[Dict[str, Any]] = [
    # ------------------------------------------------------------------ power
    _p("generic-ups", "UPS", "Power", "power",
       "Rackmount uninterruptible power supply: one mains input, battery-backed outlets and a management port.",
       ["ups", "uninterruptible power supply", "battery backup"],
       [_g("Mains In", "in", "power", "IEC C14"), _g("Outlet", "out", "power", "IEC C13", 6), _g("Management", "io", _NET, "RJ45")],
       ru=2, routing="passthrough", tags=["ups"]),
    _p("generic-pdu", "PDU", "Power", "power",
       "Rackmount power distribution unit: one mains input feeding switched or metered outlets.",
       ["pdu", "power distribution unit", "power strip", "rack pdu"],
       [_g("Mains In", "in", "power", "IEC C14"), _g("Outlet", "out", "power", "IEC C13", 8)],
       ru=1, routing="passthrough", tags=["pdu"]),
    # ----------------------------------------------------------- network & IT
    _p("generic-patch-panel-copper", "Patch panel · copper", "Network & IT", "patch_panel",
       "24-port Cat6 keystone / punch-down patch panel; each port passes straight through.",
       ["patch panel", "copper patch panel", "cat6 patch panel", "rj45 patch panel", "keystone panel"],
       [_g("Port", "io", _NET, "RJ45", 24)],
       ru=1, tags=["patch-panel", "copper"]),
    _p("generic-patch-panel-fibre", "Patch panel · fibre", "Network & IT", "patch_panel",
       "24-port LC duplex fibre patch panel / enclosure; each port passes straight through.",
       ["fibre patch panel", "fiber patch panel", "lc patch panel", "fibre panel", "fiber panel", "fiber enclosure"],
       [_g("Port", "io", _FIB, "LC", 24)],
       ru=1, tags=["patch-panel", "fibre"]),
    _p("generic-switch-24", "Network switch · 24-port", "Network & IT", "switch",
       "Managed 24-port gigabit access switch with four SFP+ uplinks (PoE optional).",
       ["network switch", "switch", "ethernet switch", "switch 24", "24-port switch", "poe switch"],
       [_g("Port", "io", _NET, "RJ45", 24), _g("SFP+", "io", _FIB, "SFP+", 4), _g("Mains In", "in", "power", "IEC C14")],
       ru=1, tags=["switch"]),
    _p("generic-switch-48", "Network switch · 48-port", "Network & IT", "switch",
       "Managed 48-port gigabit access switch with four SFP+ uplinks (PoE optional).",
       ["switch 48", "48-port switch", "core switch"],
       [_g("Port", "io", _NET, "RJ45", 48), _g("SFP+", "io", _FIB, "SFP+", 4), _g("Mains In", "in", "power", "IEC C14")],
       ru=1, tags=["switch"]),
    _p("generic-router", "Router / firewall", "Network & IT", "network",
       "Edge router or firewall appliance with WAN and LAN ports and a serial console.",
       ["router", "firewall", "gateway", "edge router", "security appliance", "utm"],
       [_g("WAN", "io", _NET, "RJ45", 2), _g("LAN", "io", _NET, "RJ45", 8), _g("Console", "in", "rs232", "RJ45"),
        _g("Mains In", "in", "power", "IEC C14")],
       ru=1, tags=["router", "firewall"]),
    _p("generic-wifi-ap", "Wireless access point", "Network & IT", "network",
       "Ceiling or wall mounted Wi-Fi access point powered over its uplink (PoE).",
       ["access point", "wireless access point", "wap", "wifi", "wi-fi", "wifi access point", "ap"],
       [_g("PoE Uplink", "io", _NET, "RJ45")],
       tags=["wifi", "access-point"]),
    _p("generic-server", "Server", "Network & IT", "computer",
       "1U rack server with dual LAN, out-of-band management, local console and redundant power.",
       ["server", "rack server", "hypervisor", "vm host"],
       [_g("LAN", "io", _NET, "RJ45", 2), _g("Management", "io", _NET, "RJ45"), _g("USB", "io", "usb", "USB-A", 2),
        _g("Console Out", "out", "video", "VGA"), _g("Mains In", "in", "power", "IEC C14", 2)],
       ru=1, tags=["server", "it"]),
    _p("generic-nas", "NAS / storage", "Network & IT", "computer",
       "2U network attached storage with four LAN ports, two SFP+ ports and redundant power.",
       ["nas", "storage", "san", "storage array", "network storage", "file server"],
       [_g("LAN", "io", _NET, "RJ45", 4), _g("SFP+", "io", _FIB, "SFP+", 2), _g("USB", "io", "usb", "USB-A", 2),
        _g("Mains In", "in", "power", "IEC C14", 2)],
       ru=2, tags=["nas", "storage", "it"]),
    _p("generic-kvm", "KVM switch", "Network & IT", "control",
       "8-port rack KVM: computer inputs on HDMI + USB, one console output, optional IP access.",
       ["kvm", "kvm switch", "ip kvm", "console switch"],
       [_g("Computer", "in", "video", "HDMI-A", 8), _g("Computer USB", "io", "usb", "USB-B", 8), _g("Console Out", "out", "video", "HDMI-A"),
        _g("Console USB", "io", "usb", "USB-A", 2), _g("Management", "io", _NET, "RJ45")],
       ru=1, tags=["kvm", "it"]),
    _p("generic-media-converter", "Media converter", "Network & IT", "network",
       "Copper ↔ fibre Ethernet media converter (RJ45 to SFP), half-rack or desktop.",
       ["media converter", "fibre converter", "fiber converter", "fibre media converter", "fiber media converter", "copper to fibre", "copper to fiber"],
       [_g("Copper", "io", _NET, "RJ45"), _g("Fibre", "io", _FIB, "SFP"), _g("DC In", "in", "power_dc", "barrel")],
       ru=1, width="half", routing="passthrough", tags=["media-converter", "fibre"]),
    # ------------------------------------------------------------------ audio
    _p("generic-dante-interface", "Dante / AES67 interface", "Audio", "stage_io",
       "16 × 16 analog ↔ Dante / AES67 audio network interface with redundant network ports.",
       ["dante interface", "dante", "aes67", "aes67 interface", "dante io", "audio network interface", "dante converter"],
       [_g("Analog In", "in", "analog", "DB25", 16), _g("Analog Out", "out", "analog", "DB25", 16),
        _g("Dante Primary", "io", "dante", "RJ45", channels=16), _g("Dante Secondary", "io", "dante", "RJ45", channels=16),
        _g("Mains In", "in", "power", "IEC C14")],
       ru=1, dante=True, tags=["dante", "aes67", "interface"]),
    _p("generic-stagebox", "Stagebox / I/O rack", "Audio", "stage_io",
       "32-in / 16-out digital stagebox on a redundant audio network.",
       ["stagebox", "stage box", "io rack", "i/o rack", "stage rack", "io box", "digital stagebox"],
       [_g("Analog In", "in", "analog", "XLR3F", 32), _g("Analog Out", "out", "analog", "XLR3M", 16),
        _g("Network Primary", "io", "dante", "etherCON", channels=32), _g("Network Secondary", "io", "dante", "etherCON", channels=32),
        _g("Mains In", "in", "power", "powerCON TRUE1")],
       ru=3, dante=True, tags=["stagebox"]),
    _p("generic-audio-console", "Audio console", "Audio", "console",
       "Digital mixing console surface: local I/O, AES out, redundant audio network, USB and control.",
       ["audio console", "console", "mixer", "mixing console", "digital mixer", "sound desk", "mixing desk", "desk"],
       [_g("Local In", "in", "analog", "XLR3F", 8), _g("Local Out", "out", "analog", "XLR3M", 8), _g("AES Out", "out", "aes3", "XLR3M"),
        _g("Network Primary", "io", "dante", "etherCON", channels=64), _g("Network Secondary", "io", "dante", "etherCON", channels=64),
        _g("USB", "io", "usb", "USB-B"), _g("Control", "io", _NET, "RJ45")],
       dante=True, tags=["console", "mixer"]),
    _p("generic-amplifier", "Power amplifier", "Audio", "amp",
       "4-channel installation / touring power amplifier with network control.",
       ["amplifier", "amp", "power amp", "power amplifier", "4-channel amp"],
       [_g("Input", "in", "analog", "XLR3F", 4), _g("Output", "out", "speaker", "NL4", 4), _g("Control", "io", _NET, "RJ45"),
        _g("Mains In", "in", "power", "powerCON TRUE1")],
       ru=2, tags=["amplifier"]),
    _p("generic-dsp", "DSP processor", "Audio", "processor",
       "8 × 8 analog DSP with a redundant Dante / AES67 network, GPIO and control.",
       ["dsp", "signal processor", "audio processor", "audio dsp", "loudspeaker processor", "processor"],
       [_g("Analog In", "in", "analog", "Phoenix", 8), _g("Analog Out", "out", "analog", "Phoenix", 8),
        _g("Dante Primary", "io", "dante", "RJ45", channels=32), _g("Dante Secondary", "io", "dante", "RJ45", channels=32),
        _g("GPIO", "io", "gpio", "Phoenix", 8), _g("Control", "io", _NET, "RJ45"), _g("Mains In", "in", "power", "IEC C14")],
       ru=1, dante=True, tags=["dsp"]),
    _p("generic-wireless-mic-rx", "Wireless mic receiver", "Audio", "wireless_rx",
       "4-channel wireless microphone receiver with diversity antennas and network control.",
       ["wireless mic receiver", "wireless receiver", "mic receiver", "rf receiver", "wireless mic", "radio mic receiver", "receiver"],
       [_g("Antenna", "in", "rf", "BNC", names=["A", "B"]), _g("Output", "out", "analog", "XLR3M", 4), _g("Control", "io", _NET, "RJ45"),
        _g("Mains In", "in", "power", "IEC C14")],
       ru=1, tags=["wireless", "receiver"]),
    _p("generic-iem-transmitter", "IEM transmitter", "Audio", "iem",
       "Dual-channel in-ear monitor transmitter with stereo inputs per channel.",
       ["iem transmitter", "iem", "in-ear transmitter", "in-ear monitor transmitter", "transmitter"],
       [_g("Input", "in", "analog", "XLR/TRS combo", 4), _g("Antenna Out", "out", "iem_wireless", "BNC"), _g("Control", "io", _NET, "RJ45"),
        _g("Mains In", "in", "power", "IEC C14")],
       ru=1, tags=["iem", "transmitter"]),
    # ------------------------------------------------------------------ video
    _p("generic-video-switcher", "Video switcher", "Video", "video_switcher",
       "8-input SDI production switcher with program, aux and multiview outputs.",
       ["video switcher", "switcher", "vision mixer", "production switcher", "video mixer"],
       [_g("SDI In", "in", "sdi", "BNC", 8), _g("Program Out", "out", "sdi", "BNC", 2), _g("Aux Out", "out", "sdi", "BNC", 2),
        _g("Multiview Out", "out", "hdmi", "HDMI-A"), _g("Control", "io", _NET, "RJ45"), _g("Mains In", "in", "power", "IEC C14")],
       ru=1, tags=["switcher"]),
    _p("generic-projector", "Projector", "Video", "projector",
       "Installation projector with HDMI and HDBaseT inputs, network and serial control.",
       ["projector", "beamer", "video projector"],
       [_g("HDMI In", "in", "hdmi", "HDMI-A", 2), _g("HDBaseT In", "in", "hdbaset", "RJ45"), _g("Control", "io", _NET, "RJ45"),
        _g("RS-232", "in", "rs232", "DB9"), _g("Mains In", "in", "power", "IEC C14")],
       tags=["projector"]),
    _p("generic-display", "Display", "Video", "display",
       "Commercial display / monitor with HDMI and DisplayPort inputs, network and serial control.",
       ["display", "monitor", "tv", "screen", "flat panel", "commercial display", "signage display"],
       [_g("HDMI In", "in", "hdmi", "HDMI-A", 2), _g("DisplayPort In", "in", "displayport", "DP"), _g("Control", "io", _NET, "RJ45"),
        _g("RS-232", "in", "rs232", "DB9"), _g("Mains In", "in", "power", "IEC C14")],
       tags=["display"]),
    _p("generic-camera", "Camera", "Video", "camera",
       "PTZ or box camera with SDI and HDMI outputs and IP / serial control.",
       ["camera", "ptz", "ptz camera", "video camera", "box camera"],
       [_g("SDI Out", "out", "sdi", "BNC"), _g("HDMI Out", "out", "hdmi", "HDMI-A"), _g("Control", "io", _NET, "RJ45"),
        _g("RS-422", "io", "rs422", "RJ45"), _g("DC In", "in", "power_dc", "barrel")],
       tags=["camera", "ptz"]),
    _p("generic-encoder-decoder", "Encoder / decoder", "Video", "encoder",
       "Single-channel streaming / AV-over-IP encoder-decoder: SDI and HDMI in, HDMI out, LAN.",
       ["encoder", "decoder", "encoder/decoder", "streaming encoder", "av over ip", "avoip"],
       [_g("SDI In", "in", "sdi", "BNC"), _g("HDMI In", "in", "hdmi", "HDMI-A"), _g("HDMI Out", "out", "hdmi", "HDMI-A"),
        _g("Audio In", "in", "analog", "TRS 3.5mm"), _g("LAN", "io", _NET, "RJ45"), _g("USB", "io", "usb", "USB-A"), _g("DC In", "in", "power_dc", "barrel")],
       ru=1, width="half", tags=["encoder", "decoder", "streaming"]),
    # --------------------------------------------------------------- lighting
    _p("generic-lighting-console", "Lighting console", "Lighting", "lighting_console",
       "Lighting control desk with four DMX outputs, sACN / Art-Net network, MIDI and timecode.",
       ["lighting console", "lighting desk", "lx console", "lx desk", "lighting board", "lighting controller"],
       [_g("DMX Out", "out", "dmx", "XLR5F", 4), _g("Network", "out", "sacn", "RJ45", 2),
        _g("MIDI", "io", "midi", "DIN5", names=["In", "Out"], dirs={"In": "in", "Out": "out"}), _g("Timecode In", "in", "timecode", "XLR3F"),
        _g("USB", "io", "usb", "USB-A", 2)],
       tags=["lighting", "console"]),
    _p("generic-dimmer-pack", "Dimmer / relay pack", "Lighting", "dimmer",
       "6-channel dimmer or relay pack: DMX in / thru and six switched or dimmed circuits.",
       ["dimmer", "dimmer pack", "relay pack", "relay", "dimmer/relay pack", "dimmer rack"],
       [_g("DMX In", "in", "dmx", "XLR5M"), _g("DMX Thru", "out", "dmx", "XLR5F"), _g("Circuit", "out", "power", "Edison 5-15", 6),
        _g("Mains In", "in", "power", "terminal")],
       ru=2, dmx_footprint=6, tags=["dimmer", "relay"]),
    _p("generic-dmx-node", "DMX node", "Lighting", "dmx_node",
       "4-port Ethernet-to-DMX gateway (sACN / Art-Net in, DMX or RDM out) with PoE.",
       ["dmx node", "artnet node", "art-net node", "sacn node", "dmx gateway", "ethernet dmx gateway", "node"],
       [_g("Network", "io", "sacn", "RJ45", 2), _g("DMX Port", "io", "dmx", "XLR5F", 4)],
       ru=1, tags=["dmx", "node"]),
]

_NORM_RE = re.compile(r"[^a-z0-9]+")


def _norm(text: str) -> str:
    return _NORM_RE.sub(" ", (text or "").lower()).strip()


def _index() -> Dict[str, Dict[str, Any]]:
    """Normalized id / label / alias → preset (ids win over labels over aliases)."""
    idx: Dict[str, Dict[str, Any]] = {}
    for key in ("aliases", "label", "id"):
        for p in PRESETS:
            vals = p[key] if key == "aliases" else [p[key]]
            for v in vals:
                n = _norm(str(v))
                if n:
                    idx[n] = p
    return idx


_INDEX = _index()


def all_presets() -> List[Dict[str, Any]]:
    """Deep copies of every preset, in display order."""
    return copy.deepcopy(PRESETS)


def get_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    for p in PRESETS:
        if p["id"] == preset_id:
            return copy.deepcopy(p)
    return None


def find_preset(text: str) -> Optional[Dict[str, Any]]:
    """Preset by id, label or alias (case-, punctuation- and plural-insensitive); None if nothing matches."""
    n = _norm(text)
    if not n:
        return None
    p = _INDEX.get(n) or (_INDEX.get(n[:-1]) if n.endswith("s") else None)
    return copy.deepcopy(p) if p else None


def resolve_kind(text: str) -> Tuple[str, Optional[str]]:
    """``(kind, preset_id)`` for a free-text kind cell.

    A vocabulary kind key (or its label) wins and returns ``(kind, None)``; otherwise a preset id, label or alias
    returns the preset's kind and id; unknown text returns ``("", None)``.
    """
    from .vocab import KINDS

    t = (text or "").strip()
    if t in KINDS:
        return t, None
    key = _NORM_RE.sub("_", t.lower()).strip("_")
    if key in KINDS:
        return key, None
    n = _norm(t)
    for k, meta in KINDS.items():
        lab = _norm(str(meta.get("label", "")))
        if lab and lab in (n, n + "s"):
            return k, None
    p = find_preset(t)
    if p:
        return str(p["kind"]), str(p["id"])
    return "", None


def as_template(preset: Dict[str, Any]) -> Dict[str, Any]:
    """The preset in the §4.5 equipment template format (``source: "preset"``)."""
    p = preset
    t: Dict[str, Any] = {"id": p["id"], "manufacturer": MANUFACTURER, "model": p["label"], "name": p["label"], "kind": p["kind"]}
    for k in ("discipline", "brand", "ru", "width", "power_w", "weight_kg", "dante", "routing", "dmx_footprint"):
        if p.get(k) is not None:
            t[k] = p[k]
    t["cost"] = None
    t["ports"] = copy.deepcopy(p["ports"])
    t["tags"] = ["preset", _NORM_RE.sub("-", p["group"].lower()).strip("-")] + [x for x in p.get("tags") or [] if x]
    t["notes"] = p.get("description", "")
    t["source"] = "preset"
    return t


def as_templates() -> Dict[str, Dict[str, Any]]:
    """id → template for every preset (feeds :func:`fathom.library.load_library`)."""
    return {p["id"]: as_template(p) for p in PRESETS}


def as_dict() -> Dict[str, Any]:
    """JSON-ready payload of ``GET /api/v2/presets``."""
    return {"groups": list(GROUPS), "presets": all_presets()}


__all__ = ["GROUPS", "MANUFACTURER", "PRESETS", "all_presets", "get_preset", "find_preset", "resolve_kind", "as_template", "as_templates", "as_dict"]
