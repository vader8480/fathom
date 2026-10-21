"""Blackmagic Videohub protocol dump (the text a router sends on TCP 9990).

Blocks start with a ``HEADER:`` line and end with a blank line::

    VIDEOHUB DEVICE:
    Model name: Blackmagic Videohub 20x20 12G
    Friendly name: Broadcast Router
    Video inputs: 20
    Video outputs: 20

    INPUT LABELS:
    0 CAM 1
    ...

    VIDEO OUTPUT ROUTING:
    0 5

Numbers are zero-based. Port ids follow the library template
``blackmagic-videohub-20x20-12g``: ``sdi-in-<n+1>`` / ``sdi-out-<n+1>``.
Unknown blocks and lines are ignored (FR-IMP-07).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import ParseResult, check_size, read_text

TEMPLATE_ID = "blackmagic-videohub-20x20-12g"


class VideohubDump(ParseResult):
    kind = "videohub"

    def __init__(self) -> None:
        super().__init__()
        self.model = ""
        self.friendly_name = ""
        self.inputs = 0
        self.outputs = 0
        self.unique_id = ""
        self.input_labels: Dict[int, str] = {}
        self.output_labels: Dict[int, str] = {}
        self.routing: Dict[int, int] = {}  # output -> input
        self.locks: Dict[int, str] = {}

    def summary(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "model": self.model,
            "friendly_name": self.friendly_name,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "input_labels": len(self.input_labels),
            "output_labels": len(self.output_labels),
            "routes": len(self.routing),
            "notes": list(self.notes),
        }


_KNOWN = ("VIDEOHUB DEVICE", "INPUT LABELS", "OUTPUT LABELS", "VIDEO OUTPUT ROUTING", "VIDEO OUTPUT LOCKS", "PROTOCOL PREAMBLE")


def _blocks(text: str) -> List[tuple]:
    out: List[tuple] = []
    name: Optional[str] = None
    lines: List[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        if name is None:
            m = re.match(r"^([A-Z0-9 ]+):\s*$", line.strip())
            if m:
                name, lines = m.group(1).strip(), []
            continue
        if not line.strip():
            out.append((name, lines))
            name = None
            continue
        lines.append(line)
    if name is not None:
        out.append((name, lines))
    return out


def parse_videohub(path: Path, **_opts: Any) -> VideohubDump:
    res = VideohubDump()
    files = sorted(p for p in path.rglob("*") if p.is_file() and not p.name.startswith(".")) if path.is_dir() else [path]
    for f in files:
        check_size(f)
        res.source_files.append(str(f))
        _parse_text(read_text(f), res)
    if not (res.inputs or res.input_labels or res.routing):
        res.note("no VIDEOHUB DEVICE / labels / routing blocks found")
    return res


def _parse_text(text: str, res: VideohubDump) -> None:
    for name, lines in _blocks(text):
        if name == "VIDEOHUB DEVICE":
            for ln in lines:
                if ":" not in ln:
                    continue
                k, v = ln.split(":", 1)
                k, v = k.strip().lower(), v.strip()
                if k == "model name":
                    res.model = v
                elif k == "friendly name":
                    res.friendly_name = v
                elif k == "unique id":
                    res.unique_id = v
                elif k == "video inputs" and v.isdigit():
                    res.inputs = int(v)
                elif k == "video outputs" and v.isdigit():
                    res.outputs = int(v)
        elif name in ("INPUT LABELS", "OUTPUT LABELS"):
            tgt = res.input_labels if name.startswith("INPUT") else res.output_labels
            for ln in lines:
                m = re.match(r"^\s*(\d+)\s(.*)$", ln)
                if m and m.group(2).strip():
                    tgt[int(m.group(1))] = m.group(2).strip()
        elif name == "VIDEO OUTPUT ROUTING":
            for ln in lines:
                m = re.match(r"^\s*(\d+)\s+(\d+)\s*$", ln)
                if m:
                    res.routing[int(m.group(1))] = int(m.group(2))
        elif name == "VIDEO OUTPUT LOCKS":
            for ln in lines:
                m = re.match(r"^\s*(\d+)\s+([OLU])\s*$", ln)
                if m:
                    res.locks[int(m.group(1))] = m.group(2)
    res.inputs = res.inputs or (max(res.input_labels) + 1 if res.input_labels else 0)
    res.outputs = res.outputs or (max(list(res.output_labels) + list(res.routing)) + 1 if (res.output_labels or res.routing) else 0)


def detect(path: Path) -> float:
    if path.is_dir():
        return 0.0
    try:
        head = path.read_bytes()[:4000].decode("utf-8", errors="ignore")
    except OSError:
        return 0.0
    if "VIDEOHUB DEVICE:" in head or "PROTOCOL PREAMBLE:" in head:
        return 0.95
    if "VIDEO OUTPUT ROUTING:" in head or ("INPUT LABELS:" in head and "OUTPUT LABELS:" in head):
        return 0.8
    return 0.0


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def contribute(result: VideohubDump, doc: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    devices = [d for d in doc.get("devices") or [] if isinstance(d, dict)]
    ids = {d.get("id") for d in devices}
    target = (ctx.get("device") or "").strip()
    notes: List[str] = []
    out_devices: List[Dict[str, Any]] = []
    if target and target not in ids:
        notes.append(f"videohub: device '{target}' not found")
        target = ""
    if not target and result.friendly_name:
        key = _norm(result.friendly_name)
        for d in devices:
            if _norm(d.get("name", "")) == key or _norm(d.get("dante_name", "")) == key:
                target = d["id"]
                break
    if not target:
        base = re.sub(r"[^a-z0-9]+", "-", (result.friendly_name or "videohub").lower()).strip("-") or "videohub"
        target, i = base, 2
        while target in ids:
            target = f"{base}-{i}"
            i += 1
        dev: Dict[str, Any] = {}
        try:
            from ..library import get_template, instantiate

            t = get_template(TEMPLATE_ID, doc)
            if t:
                dev = instantiate(t, device_id=target, name=result.friendly_name or result.model or "Videohub", room=ctx.get("room") or "")
        except Exception:
            dev = {}
        if not dev:
            ports = [{"id": f"sdi-in-{n}", "name": f"SDI In {n}", "dir": "in", "medium": "sdi", "group": "SDI In", "index": n} for n in range(1, max(result.inputs, 1) + 1)]
            ports += [{"id": f"sdi-out-{n}", "name": f"SDI Out {n}", "dir": "out", "medium": "sdi", "group": "SDI Out", "index": n} for n in range(1, max(result.outputs, 1) + 1)]
            dev = {"id": target, "name": result.friendly_name or "Videohub", "kind": "video_router", "manufacturer": "Blackmagic Design", "model": result.model, "room": ctx.get("room") or "", "ports": ports}
        if result.model:
            dev["model"] = result.model.replace("Blackmagic ", "")
        dev.update({"auto": True, "source": "videohub"})
        out_devices.append(dev)
        notes.append(f"videohub: added router '{dev['name']}' to the overlay")
    labels: Dict[str, str] = {}
    for n, lab in sorted(result.input_labels.items()):
        labels[f"sdi-in-{n + 1}"] = lab
    for n, lab in sorted(result.output_labels.items()):
        labels[f"sdi-out-{n + 1}"] = lab
    routes = []
    for o, i in sorted(result.routing.items()):
        routes.append({
            "kind": "videohub",
            "from": {"device": target, "port": f"sdi-in-{i + 1}"},
            "to": {"device": target, "port": f"sdi-out-{o + 1}"},
            "label": result.input_labels.get(i, f"Input {i + 1}"),
            "medium": "sdi",
        })
    detail = {target: {"videohub": {"model": result.model, "friendly_name": result.friendly_name, "inputs": result.inputs, "outputs": result.outputs}}}
    return {"devices": out_devices, "port_labels": {target: labels}, "routes": routes, "detail": detail, "notes": notes + [f"videohub: {n}" for n in result.notes]}
