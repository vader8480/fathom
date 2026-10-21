"""ATEM Software Control settings XML (P2): input names → overlay port labels.

The export holds ``<Input id="1" shortName="CAM1" longName="Camera 1"
externalPortType="HDMI"/>`` elements. Inputs are matched by index to the
ATEM device's input ports (``hdmi-in-<n>`` / ``sdi-in-<n>``, else the n-th
``in`` port with a video medium).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

from .common import ParseResult, check_size


class AtemSettings(ParseResult):
    kind = "atem"

    def __init__(self) -> None:
        super().__init__()
        self.product = ""
        self.inputs: List[Dict[str, Any]] = []

    def summary(self) -> Dict[str, object]:
        return {"kind": self.kind, "product": self.product, "inputs": len(self.inputs), "notes": list(self.notes)}


def parse_atem(path: Path, **_opts: Any) -> AtemSettings:
    res = AtemSettings()
    check_size(path)
    res.source_files.append(str(path))
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        res.note(f"{path.name}: XML parse error: {exc}")
        return res
    res.product = root.attrib.get("product", "") or root.attrib.get("majorVersion", "")
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "Input":
            continue
        iid = el.attrib.get("id", "")
        if not iid.isdigit():
            continue
        res.inputs.append({
            "id": int(iid),
            "short": el.attrib.get("shortName", ""),
            "long": el.attrib.get("longName", ""),
            "type": el.attrib.get("externalPortType", ""),
        })
    if not res.inputs:
        res.note("no <Input> elements found")
    return res


def detect(path: Path) -> float:
    if path.is_dir() or path.suffix.lower() != ".xml":
        return 0.0
    try:
        head = path.read_bytes()[:4000].decode("utf-8", errors="ignore")
    except OSError:
        return 0.0
    if "<Profile" in head and "ATEM" in head or "externalPortType" in head:
        return 0.85
    return 0.0


def contribute(result: AtemSettings, doc: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    devices = [d for d in doc.get("devices") or [] if isinstance(d, dict)]
    target = None
    if ctx.get("device"):
        target = next((d for d in devices if d.get("id") == ctx["device"]), None)
    if target is None:
        target = next((d for d in devices if d.get("kind") == "video_switcher" and "atem" in (d.get("model", "") + d.get("name", "")).lower()), None)
    if target is None:
        return {"notes": ["atem: no ATEM device in the project; pass the device id"]}
    ports = target.get("ports") or []
    ins = [p for p in ports if p.get("dir") == "in" and p.get("medium") in ("hdmi", "sdi", "video")]
    labels: Dict[str, str] = {}
    for inp in result.inputs:
        n = inp["id"]
        if n < 1 or n > 40:
            continue  # internal sources (colour bars, media players …)
        text = inp["long"] or inp["short"]
        if not text:
            continue
        pid = None
        for cand in (f"hdmi-in-{n}", f"sdi-in-{n}"):
            if any(p.get("id") == cand for p in ports):
                pid = cand
                break
        if pid is None and n <= len(ins):
            pid = ins[n - 1].get("id")
        if pid and not re.match(r"^(Camera|Input) ?\d+$", text):
            labels[pid] = text
        elif pid:
            labels[pid] = text
    return {"port_labels": {target["id"]: labels}, "notes": [f"atem: {len(labels)} input labels for {target.get('name', target['id'])}"]}
