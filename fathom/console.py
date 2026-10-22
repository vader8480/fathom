"""Console internals (SPEC §4.3.17): input channels, buses, DCAs, racks and the
patch edges between them, generic across consoles and populated by importers.

``devices[].channels`` lists the logical channels of a mixer; ``channel_links``
are the edges inside it (physical port ↔ channel, channel → bus, bus →
output, inserts, DCA membership). An endpoint is a console channel
``{"channel": "in-12"}`` (racks add ``"tag": "A"``), a sub-channel of a device
port ``{"port": "dante-primary", "ch": 17}`` (``ch`` omitted for a mono
connector), or ``{"text": "REC 1"}`` when the importer could not map a console
port onto a device port. A port endpoint at the ``from`` of a link is where the
signal *enters* the device (a Dante receive channel); at the ``to`` it is where
it *leaves* (a transmit channel).

Importers never write into the doc: they contribute ``overlay.channels[dev]``
and the user applies that to the device (``apply_ops``). Once a device carries
``channels`` the persisted set is authoritative; the overlay only reports what
a re-apply would change.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .model import norm_name

Doc = Dict[str, Any]

#: ``ConsoleChannel.kind`` (parsers.yamaha) → channel kind
_YAMAHA_KINDS = {"in": "input", "stin": "stereo_input", "mix": "mix", "matrix": "matrix", "stereo": "stereo", "mono": "mono",
                 "dca": "dca", "mute": "mute_group"}
_PREFIX = {"input": "in", "stereo_input": "stin", "mix": "mix", "aux": "aux", "group": "grp", "matrix": "mtx", "stereo": "st",
           "mono": "mono", "dca": "dca", "mute_group": "mute", "rack": "rack", "monitor": "mon", "cue": "cue", "talkback": "tb",
           "oscillator": "osc"}
_SHORT = {"input": "CH", "stereo_input": "ST IN", "mix": "MIX", "aux": "AUX", "group": "GRP", "matrix": "MATRIX", "stereo": "ST",
          "mono": "MONO", "dca": "DCA", "mute_group": "MUTE", "monitor": "MONITOR", "cue": "CUE", "talkback": "TALKBACK", "oscillator": "OSC"}
_ORDER = {"input": 0, "stereo_input": 1, "mix": 2, "aux": 2, "group": 3, "matrix": 4, "stereo": 5, "mono": 6, "dca": 7, "mute_group": 8,
          "rack": 9, "monitor": 10, "cue": 11, "talkback": 12, "oscillator": 13}
AUDIO_LINK_KINDS = ("input_patch", "send", "output_patch", "direct_out", "insert_send", "insert_return")
CONTROL_LINK_KINDS = ("dca", "mute")


def channel_id(kind: str, index: Optional[int] = None, side: str = "", rack: str = "") -> str:
    """``("input", 12) → "in-12"``, ``("stereo_input", 4, "L") → "stin-4-l"``, ``("stereo", None, "L") → "st-l"``,
    ``("rack", 1, rack="FX") → "fx-1"``."""
    if kind == "rack":
        base = (rack or "rack").lower()
    else:
        base = _PREFIX.get(kind, re.sub(r"[^a-z0-9]+", "-", kind.lower()).strip("-") or "ch")
    parts = [base]
    if index is not None:
        parts.append(str(index))
    if side:
        parts.append(side.lower())
    return "-".join(parts)


def channel_label(ch: Dict[str, Any]) -> str:
    """Console-style label: ``CH 12``, ``ST IN 4 L``, ``MIX 3``, ``ST L``, ``MONO``, ``DCA 1``, ``FX 1``."""
    if ch.get("label"):
        return str(ch["label"])
    kind = str(ch.get("kind") or "")
    if kind == "rack":
        head = str(ch.get("rack") or "RACK").upper()
    else:
        head = _SHORT.get(kind, kind.upper())
    parts = [head]
    if ch.get("index") is not None and kind not in ("stereo", "mono"):
        parts.append(str(ch["index"]))
    if ch.get("side"):
        parts.append(str(ch["side"]).upper())
    return " ".join(parts)


def channel_title(ch: Dict[str, Any]) -> str:
    """``CH 12 · Bass`` (label plus name when the name adds information)."""
    lab = channel_label(ch)
    name = str(ch.get("name") or "").strip()
    if name and norm_name(name) != norm_name(lab):
        return f"{lab} · {name}"
    return lab


def endpoint_text(ep: Dict[str, Any], channels: Optional[Dict[str, Dict[str, Any]]] = None, ports: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    """Human text for a link endpoint (``CH 12 · Bass``, ``FX 1 A``, ``Dante 17``, ``REC 1``)."""
    if not isinstance(ep, dict):
        return ""
    if ep.get("channel"):
        ch = (channels or {}).get(str(ep["channel"]))
        base = channel_title(ch) if ch else str(ep["channel"])
        return f"{base} {ep['tag']}" if ep.get("tag") else base
    if ep.get("port"):
        p = (ports or {}).get(str(ep["port"]))
        base = str((p or {}).get("label") or (p or {}).get("name") or ep["port"])
        return f"{base} {ep['ch']}" if ep.get("ch") else base
    return str(ep.get("text") or "")


def sort_channels(channels: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(c: Dict[str, Any]) -> Tuple[int, str, int, str]:
        return (_ORDER.get(str(c.get("kind") or ""), 99), str(c.get("rack") or ""), int(c.get("index") or 0), str(c.get("side") or ""))

    return sorted(channels, key=key)


# ---------------------------------------------------------- port mapping


class PortMapper:
    """Resolve a console's own port names (``DANTE 17``, ``OMNI 3``, ``SLOT1 5``) to the device's ports."""

    def __init__(self, device: Dict[str, Any]) -> None:
        self.ports: List[Dict[str, Any]] = [p for p in (device or {}).get("ports") or [] if isinstance(p, dict) and p.get("id")]
        self.unmapped: List[str] = []

    @staticmethod
    def _hay(p: Dict[str, Any]) -> str:
        return norm_name(f"{p.get('group') or ''} {p.get('name') or ''} {p.get('label') or ''}")

    def _first(self, medium: str, dirs: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
        for p in self.ports:
            if p.get("medium") == medium and p.get("dir") in dirs:
                return p
        return None

    def _indexed(self, word: str, dirs: Tuple[str, ...], n: int, medium: Optional[str] = None) -> Optional[Dict[str, Any]]:
        group = [p for p in self.ports if word in self._hay(p) and p.get("dir") in dirs and (medium is None or p.get("medium") == medium)]
        if not group and medium:
            group = [p for p in self.ports if p.get("medium") == medium and p.get("dir") in dirs]
        for p in group:
            if p.get("index") == n or str(p.get("id", "")).endswith(f"-{n}"):
                return p
        return group[n - 1] if 0 < n <= len(group) else None

    def dante(self, direction: str) -> Optional[Dict[str, Any]]:
        return self._first("dante", ("io",)) or self._first("dante", (direction, "io"))

    def endpoint(self, port: Any, direction: str) -> Dict[str, Any]:
        """``direction`` = ``in`` for a signal entering the console (InPatch sources), ``out`` for leaving (PortRackPatch ports)."""
        text = str(getattr(port, "text", port) or "")
        bus = str(getattr(port, "bus", "") or "")
        n = getattr(port, "number", None)
        hit: Optional[Dict[str, Any]] = None
        if bus == "DANTE":
            hit = self.dante(direction)
            if hit is not None:
                return {"port": hit["id"], "ch": int(n)} if n else {"port": hit["id"]}
        elif bus in ("OMNI", "INPUT") and n:
            hit = self._indexed("omni", ("in", "io") if direction == "in" else ("out", "io"), int(n), "analog")
            if hit is not None:
                return {"port": hit["id"]}
        elif bus == "SLOT" and getattr(port, "slot", None):
            hit = self._indexed("slot", ("io", direction), int(port.slot))
            if hit is not None:
                return {"port": hit["id"], "ch": int(n)} if n else {"port": hit["id"]}
        if text and text not in self.unmapped:
            self.unmapped.append(text)
        return {"text": text}


# --------------------------------------------------- Yamaha contribution


def _rack_endpoint(port: Any, chans: Dict[str, Dict[str, Any]], source: str) -> Dict[str, Any]:
    rack = str(port.bus)
    cid = channel_id("rack", port.number, rack=rack)
    if cid not in chans:
        chans[cid] = {"id": cid, "kind": "rack", "rack": rack, "index": int(port.number or 0), "source": source}
    ep: Dict[str, Any] = {"channel": cid}
    if port.tag:
        ep["tag"] = str(port.tag)
    return ep


def _canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def console_contribution(data: Any, device: Dict[str, Any], source: str = "yamaha") -> Dict[str, Any]:
    """Channels and links for ``device`` from a parsed Yamaha export (``parsers.yamaha.ConsoleData``).

    Returns ``{"channels": [...], "links": [...], "unmapped": [...], "notes": [...]}``; ``unmapped`` lists
    console ports that have no counterpart on the device (kept as ``text`` endpoints).
    """
    mapper = PortMapper(device)
    chans: Dict[str, Dict[str, Any]] = {}
    links: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    by_label: Dict[str, str] = {}

    def add_link(ln: Dict[str, Any]) -> None:
        ln = {k: v for k, v in ln.items() if v not in (None, "", [], {})}
        ln.setdefault("source", source)
        key = _canon({k: v for k, v in ln.items() if k != "source"})
        if key in seen:
            return
        seen.add(key)
        links.append(ln)

    for ch in data.channels.values():
        kind = _YAMAHA_KINDS.get(ch.kind)
        if kind is None:
            continue
        if kind in ("stereo", "mono"):
            side = "" if kind == "mono" else ("R" if ch.index == 1 else "L")
            cid = channel_id(kind, None, side)
            c: Dict[str, Any] = {"id": cid, "kind": kind}
            if side:
                c["side"] = side
        else:
            side = ch.tag if kind == "stereo_input" else ""
            cid = channel_id(kind, ch.index, side)
            c = {"id": cid, "kind": kind, "index": ch.index}
            if side:
                c["side"] = side
        if ch.name and ch.name.strip():
            c["name"] = ch.name.strip()
        if ch.color and ch.color != "Off":
            c["color"] = ch.color
        if ch.icon and ch.icon != "Blank":
            c["icon"] = ch.icon
        c["source"] = source
        chans[cid] = c
        by_label[ch.label] = cid

    def chan_ep(ch: Any) -> Optional[Dict[str, Any]]:
        cid = by_label.get(ch.label)
        return {"channel": cid} if cid else None

    for ch in data.inputs:
        me = chan_ep(ch)
        if me is None:
            continue
        if ch.patch is not None and ch.patch.bus != "NONE":
            if ch.patch.is_rack:
                src = _rack_endpoint(ch.patch, chans, source)
            else:
                src = mapper.endpoint(ch.patch, "in")
            add_link({"from": src, "to": me, "kind": "input_patch"})
    for ch in data.channels.values():
        me = chan_ep(ch)
        if me is None:
            continue
        for slot, ret in sorted(ch.insert_returns.items()):
            if ret.is_rack:
                add_link({"from": _rack_endpoint(ret, chans, source), "to": me, "kind": "insert_return", "insert": slot})
            elif ret.bus != "NONE":
                add_link({"from": mapper.endpoint(ret, "in"), "to": me, "kind": "insert_return", "insert": slot})
    for op in list(data.output_patches) + list(data.rack_patches):
        if op.source is None:
            continue
        src_ch = data.channel_for_source(op.source)
        if src_ch is not None and chan_ep(src_ch) is not None:
            src = chan_ep(src_ch) or {}
        else:
            src = {"text": op.source.text}
        dst = _rack_endpoint(op.port, chans, source) if op.port.is_rack else mapper.endpoint(op.port, "out")
        ln: Dict[str, Any] = {"from": src, "to": dst}
        if op.source.bus == "INS":
            ln["kind"], ln["insert"] = "insert_send", op.source.insert or 1
        elif op.source.bus == "DIRECT":
            ln["kind"] = "direct_out"
        else:
            ln["kind"] = "output_patch"
        add_link(ln)
    notes = []
    if mapper.unmapped:
        notes.append("console ports without a device port (kept as text): " + ", ".join(mapper.unmapped[:12]) + (" …" if len(mapper.unmapped) > 12 else ""))
    return {"channels": sort_channels(list(chans.values())), "links": links, "unmapped": list(mapper.unmapped), "notes": notes}


# ------------------------------------------------------- doc ∪ overlay


def device_channels(device: Optional[Dict[str, Any]]) -> Tuple[Optional[List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """``(channels | None, links)`` persisted on a device; ``None`` channels = never applied."""
    if not device:
        return None, []
    chans = device.get("channels")
    links = device.get("channel_links")
    chans_l = [c for c in chans if isinstance(c, dict) and c.get("id")] if isinstance(chans, list) else None
    links_l = [ln for ln in links if isinstance(ln, dict)] if isinstance(links, list) else []
    return chans_l, links_l


def overlay_channels(overlay: Optional[Dict[str, Any]], device_id: str) -> Optional[Dict[str, Any]]:
    ov = ((overlay or {}).get("channels") or {}).get(device_id)
    return ov if isinstance(ov, dict) and (ov.get("channels") or ov.get("links")) else None


def effective_channels(doc: Doc, overlay: Optional[Dict[str, Any]], device_id: str) -> Dict[str, Any]:
    """What the tracer / UI should use: the device's own channels once applied, else the overlay's.

    ``{"channels", "links", "source": "device"|"overlay"|"none", "pending": bool}``; ``pending`` is
    true when an overlay contribution exists that differs from what is persisted (re-apply would change).
    """
    dev = next((d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id") == device_id), None)
    chans, links = device_channels(dev)
    ov = overlay_channels(overlay, device_id)
    if chans is not None:
        pending = False
        if ov is not None:
            merged = _merge_sets(chans, links, ov.get("channels") or [], ov.get("links") or [])
            pending = _canon(merged[0]) != _canon(chans) or _canon(merged[1]) != _canon(links)
        return {"channels": chans, "links": links, "source": "device", "pending": pending}
    if ov is not None:
        return {"channels": list(ov.get("channels") or []), "links": list(ov.get("links") or []), "source": "overlay", "pending": True}
    return {"channels": [], "links": [], "source": "none", "pending": False}


def _merge_sets(old_ch: List[Dict[str, Any]], old_ln: List[Dict[str, Any]], new_ch: List[Dict[str, Any]], new_ln: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Imported set on top of the persisted one: ``user`` channels / links survive, everything else is replaced."""
    out: Dict[str, Dict[str, Any]] = {}
    for c in new_ch:
        if isinstance(c, dict) and c.get("id"):
            out[c["id"]] = copy.deepcopy(c)
    for c in old_ch:
        if not isinstance(c, dict) or not c.get("id") or c.get("source") != "user":
            continue
        if c["id"] in out:  # user-edited name / colour wins, imported structure fills
            out[c["id"]].update({k: v for k, v in c.items() if k in ("name", "color", "icon", "note", "label", "source")})
        else:
            out[c["id"]] = copy.deepcopy(c)
    links: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def key(ln: Dict[str, Any]) -> str:
        return _canon({k: v for k, v in ln.items() if k not in ("source", "note")})

    for ln in old_ln:
        if isinstance(ln, dict) and ln.get("source") == "user":
            links.append(copy.deepcopy(ln))
            seen.add(key(ln))
    for ln in new_ln:
        if isinstance(ln, dict) and key(ln) not in seen:
            links.append(copy.deepcopy(ln))
            seen.add(key(ln))
    return sort_channels(list(out.values())), links


def apply_ops(doc: Doc, overlay: Optional[Dict[str, Any]], device_id: str) -> List[Dict[str, Any]]:
    """``merge`` op that persists the overlay's channels on ``device_id`` (user entries kept); ``[]`` when nothing to apply."""
    ov = overlay_channels(overlay, device_id)
    dev = next((d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id") == device_id), None)
    if ov is None or dev is None:
        return []
    chans, links = device_channels(dev)
    merged_ch, merged_ln = _merge_sets(chans or [], links, ov.get("channels") or [], ov.get("links") or [])
    if chans is not None and _canon(merged_ch) == _canon(chans) and _canon(merged_ln) == _canon(links):
        return []
    return [{"op": "merge", "coll": "devices", "id": device_id, "value": {"channels": merged_ch, "channel_links": merged_ln}}]


def channel_map(channels: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(c["id"]): c for c in channels if isinstance(c, dict) and c.get("id")}


def summary(channels: Sequence[Dict[str, Any]], links: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts for cards and import summaries."""
    by_kind: Dict[str, int] = {}
    for c in channels:
        k = str(c.get("kind") or "other")
        by_kind[k] = by_kind.get(k, 0) + 1
    by_link: Dict[str, int] = {}
    for ln in links:
        k = str(ln.get("kind") or "other")
        by_link[k] = by_link.get(k, 0) + 1
    return {
        "channels": len(channels), "links": len(links), "by_kind": by_kind, "by_link": by_link,
        "named": sum(1 for c in channels if c.get("name")),
        "sends": by_link.get("send", 0), "dca_members": by_link.get("dca", 0),
    }
