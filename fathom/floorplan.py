"""Floor-plan conversion: Draw.io / DXF → SVG, PDF → PNG, SVG sanitising, plan export.

Everything here parses untrusted uploads with the standard library only:

* **SVG** is re-serialised after dropping scripts, ``foreignObject``,
  ``iframe/embed/object``, ``on*`` handlers, ``javascript:`` values and
  external references (only ``#frag`` and ``data:image/…`` survive).
* **Draw.io** (``.drawio``/``.xml``): uncompressed ``<mxGraphModel>`` or the
  compressed ``<diagram>`` text (base64 → raw inflate → URL-decode).
* **DXF** (ASCII): LINE, LWPOLYLINE (bulges → arcs), POLYLINE/VERTEX, CIRCLE,
  ARC, ELLIPSE, SOLID, TEXT, MTEXT, INSERT (nested ≤ 8) with layers; bounded
  to 500 000 entities and a 20 s budget.
* **PDF** is rasterised by the first tool found (``FATHOM_PDF_RASTERIZER``,
  ``pdftoppm``, ``mutool``, ``gs``, macOS ``sips``).
* **DWG** is refused with guidance unless ``FATHOM_ODA`` names the ODA File
  Converter.
"""

from __future__ import annotations

import base64
import html
import math
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Doc = Dict[str, Any]

MAX_BYTES = 50 * 1024 * 1024
DXF_MAX_ENTITIES = 500_000
DXF_MAX_NESTING = 8
DXF_TIME_BUDGET = 20.0
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
DEFAULT_STROKE = "#c8cfdd"

DWG_MESSAGE = "DWG is a closed format. Export DXF (AutoCAD: SAVEAS → DXF), PDF or SVG, or configure the ODA File Converter (FATHOM_ODA)."
PDF_MESSAGE = "No PDF rasterizer found. Export the page as PNG or SVG, or install poppler-utils (pdftoppm)."


class UnsupportedPlan(Exception):
    """``code`` ∈ dwg_unsupported | pdf_unsupported | unsupported_format | binary_dxf."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ConvertResult:
    kind: str
    image_kind: str
    data: bytes
    width: float
    height: float
    layers: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    units: Optional[Dict[str, Any]] = None


def _f(v: float) -> str:
    """Compact number: 2 decimals, no trailing zeros."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


# ================================================================ detection


def detect_plan_kind(filename: str, head: bytes) -> str:
    """png | jpg | svg | pdf | drawio | dxf | dxf-binary | dwg | unknown."""
    name = (filename or "").lower()
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"AC10") or name.endswith(".dwg"):
        return "dwg"
    if head.startswith(b"AutoCAD Binary DXF"):
        return "dxf-binary"
    text = head[:8192].decode("utf-8", errors="ignore").lstrip("\ufeff \t\r\n")
    low = text.lower()
    if "<mxfile" in low or "<mxgraphmodel" in low:
        return "drawio"
    if "<svg" in low:
        return "svg"
    if name.endswith(".dxf") or re.match(r"^\s*0\s*\r?\n\s*SECTION\b", text) or re.match(r"^\s*999\s*\r?\n", text):
        return "dxf"
    for ext, kind in ((".png", "png"), (".jpg", "jpg"), (".jpeg", "jpg"), (".svg", "svg"), (".pdf", "pdf"), (".drawio", "drawio")):
        if name.endswith(ext):
            return kind
    return "unknown"


# ============================================================ image sizes


def png_size(data: bytes) -> Tuple[int, int]:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    return 0, 0


def jpg_size(data: bytes) -> Tuple[int, int]:
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return int(w), int(h)
        i += 2 + seg
    return 0, 0


def _svg_size(root: ET.Element) -> Tuple[float, float]:
    def num(v: Optional[str]) -> float:
        m = re.match(r"^\s*([0-9.]+)\s*(px|pt|mm|cm|in)?\s*$", v or "")
        if not m:
            return 0.0
        x = float(m.group(1))
        return x * {"pt": 1.3333, "mm": 3.7795, "cm": 37.795, "in": 96.0}.get(m.group(2) or "", 1.0)

    vb = (root.get("viewBox") or "").replace(",", " ").split()
    w, h = num(root.get("width")), num(root.get("height"))
    if (not w or not h) and len(vb) == 4:
        try:
            return float(vb[2]), float(vb[3])
        except ValueError:
            pass
    return (w or 1000.0), (h or 1000.0)


# ================================================================== SVG

_DROP_TAGS = {"script", "foreignobject", "iframe", "embed", "object", "handler", "listener", "frame", "frameset", "applet", "meta", "link", "base"}
_DATA_IMG = re.compile(r"^\s*data:image/(png|jpeg|jpg|gif|svg\+xml)[;,]", re.I)
_DOCTYPE_RE = re.compile(r"<!DOCTYPE[^\[>]*(\[.*?\])?\s*>", re.S | re.I)
_ENTITY_RE = re.compile(r"<!ENTITY", re.I)


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _js_like(value: str) -> bool:
    v = re.sub(r"[\x00-\x20]+", "", html.unescape(value or "")).lower()
    return "javascript:" in v or "vbscript:" in v or v.startswith("data:text/html")


def _clean_css(text: str) -> str:
    text = re.sub(r"@import[^;]*;?", "", text, flags=re.I)
    text = re.sub(r"expression\s*\(", "(", text, flags=re.I)

    def fix(m: "re.Match[str]") -> str:
        inner = m.group(1).strip().strip("'\"")
        return m.group(0) if inner.startswith("#") or _DATA_IMG.match(inner) else "none"

    return re.sub(r"url\(\s*([^)]*)\)", fix, text, flags=re.I)


def _register_ns() -> None:
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)


def sanitize_svg(text: str) -> str:
    """Return a safe SVG document (raises UnsupportedPlan on unparseable input)."""
    if len(text) > MAX_BYTES:
        raise UnsupportedPlan("unsupported_format", "SVG is larger than 50 MB")
    text = _DOCTYPE_RE.sub("", text)
    if _ENTITY_RE.search(text):
        raise UnsupportedPlan("unsupported_format", "SVG with entity declarations is not accepted")
    _register_ns()
    try:
        root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    except ET.ParseError as exc:
        raise UnsupportedPlan("unsupported_format", f"SVG could not be parsed: {exc}")
    if _local(root.tag).lower() != "svg":
        raise UnsupportedPlan("unsupported_format", "not an SVG document")
    _scrub(root)
    out = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + out


def _scrub(el: ET.Element) -> None:
    for child in list(el):
        if not isinstance(child.tag, str) or _local(child.tag).lower() in _DROP_TAGS:
            el.remove(child)
            continue
        if _local(child.tag).lower() in ("animate", "set", "animatemotion", "animatetransform"):
            target = (child.get("attributeName") or "").strip().lower()
            if target.startswith("on") or target.endswith("href") or target in ("src", "style"):
                el.remove(child)
                continue
        _scrub(child)
    for attr in list(el.attrib):
        name = _local(attr).lower()
        val = el.attrib[attr]
        if name.startswith("on") or _js_like(val):
            del el.attrib[attr]
        elif name == "href" or attr.endswith("}href"):
            if not (val.strip().startswith("#") or _DATA_IMG.match(val)):
                del el.attrib[attr]
        elif name == "style":
            el.attrib[attr] = _clean_css(val)
        elif name in ("src", "action", "formaction"):
            del el.attrib[attr]
    if _local(el.tag).lower() == "style" and el.text:
        el.text = _clean_css(el.text)
    if _local(el.tag).lower() in ("a",):
        el.attrib.pop("target", None)


# ================================================================ Draw.io


def _style(s: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in (s or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out.setdefault("_shape", part)
    return out


def _strip_html(v: str) -> str:
    v = re.sub(r"<\s*br\s*/?\s*>", "\n", v or "", flags=re.I)
    v = re.sub(r"</\s*(div|p)\s*>", "\n", v, flags=re.I)
    v = re.sub(r"<[^>]+>", "", v)
    v = html.unescape(v).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in v.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _inflate_diagram(text: str) -> str:
    raw = base64.b64decode(re.sub(r"\s+", "", text))
    d = zlib.decompressobj(-15)
    data = d.decompress(raw, MAX_BYTES)
    if d.unconsumed_tail:
        raise UnsupportedPlan("unsupported_format", "Draw.io diagram expands beyond 50 MB")
    return urllib.parse.unquote(data.decode("utf-8", errors="replace"))


def _graph_models(xml_text: str) -> List[ET.Element]:
    xml_text = _DOCTYPE_RE.sub("", xml_text)
    if _ENTITY_RE.search(xml_text):
        raise UnsupportedPlan("unsupported_format", "XML with entity declarations is not accepted")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise UnsupportedPlan("unsupported_format", f"Draw.io XML could not be parsed: {exc}")
    if _local(root.tag) == "mxGraphModel":
        return [root]
    models: List[ET.Element] = []
    diagrams = [d for d in root.iter() if _local(d.tag) == "diagram"]
    for d in diagrams:
        inner = next((c for c in d if _local(c.tag) == "mxGraphModel"), None)
        if inner is not None:
            models.append(inner)
        elif (d.text or "").strip():
            try:
                models.append(ET.fromstring(_inflate_diagram(d.text or "")))
            except (ValueError, zlib.error, ET.ParseError) as exc:
                raise UnsupportedPlan("unsupported_format", f"compressed Draw.io page could not be decoded: {exc}")
    if not models:
        models = [m for m in root.iter() if _local(m.tag) == "mxGraphModel"]
    return models


def _clip(cx: float, cy: float, tx: float, ty: float, box: Tuple[float, float, float, float], shape: str) -> Tuple[float, float]:
    """Point where the segment centre → (tx, ty) leaves the shape outline."""
    x, y, w, h = box
    dx, dy = tx - cx, ty - cy
    if (dx == 0 and dy == 0) or w <= 0 or h <= 0:
        return cx, cy
    if shape == "ellipse":
        rx, ry = w / 2, h / 2
        t = 1.0 / math.sqrt((dx / rx) ** 2 + (dy / ry) ** 2)
    elif shape == "rhombus":
        t = 1.0 / (abs(dx) / (w / 2) + abs(dy) / (h / 2))
    else:
        tx_ = (w / 2) / abs(dx) if dx else float("inf")
        ty_ = (h / 2) / abs(dy) if dy else float("inf")
        t = min(tx_, ty_)
    t = min(t, 1.0)
    return cx + dx * t, cy + dy * t


def drawio_to_svg(xml_text: str, page: int = 0) -> ConvertResult:
    warnings: List[str] = []
    models = _graph_models(xml_text)
    if not models:
        raise UnsupportedPlan("unsupported_format", "no Draw.io diagram found")
    if page < 0 or page >= len(models):
        warnings.append(f"page {page} not found; using page 0 of {len(models)}")
        page = 0
    model = models[page]
    root_el = next((c for c in model if _local(c.tag) == "root"), model)
    cells = [c for c in root_el if _local(c.tag) == "mxCell" or c.find("mxCell") is not None]
    norm: List[Dict[str, Any]] = []
    for c in cells:
        cell = c if _local(c.tag) == "mxCell" else c.find("mxCell")
        if cell is None:
            continue
        attrs = dict(cell.attrib)
        if cell is not c:  # <object label=…><mxCell …/></object>
            attrs.setdefault("id", c.get("id", ""))
            attrs["value"] = c.get("label", attrs.get("value", ""))
        geo = cell.find("mxGeometry")
        norm.append({"a": attrs, "geo": geo})
    by_id = {n["a"].get("id"): n for n in norm}
    abs_box: Dict[str, Tuple[float, float, float, float]] = {}

    def gnum(geo: Optional[ET.Element], k: str) -> float:
        try:
            return float(geo.get(k, 0)) if geo is not None else 0.0
        except ValueError:
            return 0.0

    def box(cid: str, depth: int = 0) -> Optional[Tuple[float, float, float, float]]:
        if cid in abs_box:
            return abs_box[cid]
        n = by_id.get(cid)
        if n is None or n["a"].get("vertex") != "1" or depth > 50:
            return None
        g = n["geo"]
        x, y, w, h = gnum(g, "x"), gnum(g, "y"), gnum(g, "width"), gnum(g, "height")
        par = box(n["a"].get("parent", ""), depth + 1)
        if par is not None:
            x, y = x + par[0], y + par[1]
        abs_box[cid] = (x, y, w, h)
        return abs_box[cid]

    parts: List[str] = []
    xs: List[float] = []
    ys: List[float] = []
    shapes: Dict[str, str] = {}
    by_cell: Dict[int, List[str]] = {}
    for ci, n in enumerate(norm):
        a = n["a"]
        if a.get("vertex") != "1":
            continue
        vertex_svg = by_cell.setdefault(ci, [])
        b = box(a.get("id", ""))
        if b is None:
            continue
        x, y, w, h = b
        st = _style(a.get("style", ""))
        shape = st.get("shape") or st.get("_shape") or "rect"
        if shape in ("text", "label"):
            shape = "text"
        shapes[a.get("id", "")] = shape
        fill = st.get("fillColor", "none" if shape == "text" else "#ffffff")
        stroke = st.get("strokeColor", "none" if shape == "text" else "#000000")
        fill = "none" if fill in ("none", "") else fill
        stroke = "none" if stroke in ("none", "") else stroke
        sw = st.get("strokeWidth", "1")
        dash = ' stroke-dasharray="6 4"' if st.get("dashed") == "1" else ""
        common = f'fill="{_esc(fill)}" stroke="{_esc(stroke)}" stroke-width="{_esc(sw)}"{dash}'
        cid = _esc(a.get("id", ""))
        if shape == "ellipse":
            vertex_svg.append(f'<ellipse data-cell="{cid}" cx="{_f(x + w / 2)}" cy="{_f(y + h / 2)}" rx="{_f(w / 2)}" ry="{_f(h / 2)}" {common}/>')
        elif shape == "rhombus":
            pts = f"{_f(x + w / 2)},{_f(y)} {_f(x + w)},{_f(y + h / 2)} {_f(x + w / 2)},{_f(y + h)} {_f(x)},{_f(y + h / 2)}"
            vertex_svg.append(f'<polygon data-cell="{cid}" points="{pts}" {common}/>')
        elif shape != "text":
            rx = f' rx="{_f(min(w, h) * 0.15)}"' if st.get("rounded") == "1" else ""
            vertex_svg.append(f'<rect data-cell="{cid}" x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}"{rx} {common}/>')
        label = _strip_html(a.get("value", ""))
        if label:
            fs = float(st.get("fontSize", "12") or 12)
            color = st.get("fontColor", "#000000")
            lines = label.split("\n")
            y0 = y + h / 2 - (len(lines) - 1) * fs * 0.6
            spans = "".join(f'<tspan x="{_f(x + w / 2)}" y="{_f(y0 + i * fs * 1.2)}">{_esc(ln)}</tspan>' for i, ln in enumerate(lines))
            vertex_svg.append(f'<text data-cell="{cid}" text-anchor="middle" dominant-baseline="middle" font-family="Helvetica, Arial, sans-serif" font-size="{_f(fs)}" fill="{_esc(color)}">{spans}</text>')
        xs += [x, x + w]
        ys += [y, y + h]
    for ci, n in enumerate(norm):
        a = n["a"]
        if a.get("edge") != "1":
            continue
        edge_svg = by_cell.setdefault(ci, [])
        st = _style(a.get("style", ""))
        geo = n["geo"]
        pts: List[Tuple[float, float]] = []
        sp = tp = None
        if geo is not None:
            for p in geo.iter():
                if _local(p.tag) != "mxPoint":
                    continue
                pt = (float(p.get("x", 0) or 0), float(p.get("y", 0) or 0))
                role = p.get("as")
                if role == "sourcePoint":
                    sp = pt
                elif role == "targetPoint":
                    tp = pt
                else:
                    pts.append(pt)
        sb, tb = box(a.get("source", "")), box(a.get("target", ""))
        if sb is not None:
            sp = (sb[0] + sb[2] / 2, sb[1] + sb[3] / 2)
        if tb is not None:
            tp = (tb[0] + tb[2] / 2, tb[1] + tb[3] / 2)
        if sp is None or tp is None:
            warnings.append(f"edge {a.get('id', '')}: missing endpoint, skipped")
            continue
        chain = [sp] + pts + [tp]
        if sb is not None:
            chain[0] = _clip(sp[0], sp[1], chain[1][0], chain[1][1], sb, shapes.get(a.get("source", ""), "rect"))
        if tb is not None:
            chain[-1] = _clip(tp[0], tp[1], chain[-2][0], chain[-2][1], tb, shapes.get(a.get("target", ""), "rect"))
        stroke = st.get("strokeColor", "#000000")
        dash = ' stroke-dasharray="6 4"' if st.get("dashed") == "1" else ""
        arrow = "" if st.get("endArrow", "classic") == "none" else ' marker-end="url(#fp-arrow)"'
        d = "M " + " L ".join(f"{_f(px)} {_f(py)}" for px, py in chain)
        edge_svg.append(f'<path data-cell="{_esc(a.get("id", ""))}" d="{d}" fill="none" stroke="{_esc(stroke)}" stroke-width="{_esc(st.get("strokeWidth", "1"))}"{dash}{arrow}/>')
        xs += [p[0] for p in chain]
        ys += [p[1] for p in chain]
        lab = _strip_html(a.get("value", ""))
        if lab:
            mid = chain[len(chain) // 2]
            edge_svg.append(f'<text x="{_f(mid[0])}" y="{_f(mid[1] - 4)}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="11">{_esc(lab)}</text>')
    margin = 20.0
    minx, miny = (min(xs), min(ys)) if xs else (0.0, 0.0)
    maxx, maxy = (max(xs), max(ys)) if xs else (100.0, 100.0)
    x0, y0 = min(0.0, minx - margin), min(0.0, miny - margin)
    w, h = maxx + margin - x0, maxy + margin - y0
    parts.append(f'<svg xmlns="{SVG_NS}" width="{_f(w)}" height="{_f(h)}" viewBox="{_f(x0)} {_f(y0)} {_f(w)} {_f(h)}">')
    parts.append('<defs><marker id="fp-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker></defs>')
    parts.append('<g data-source="drawio">')
    for ci in sorted(by_cell):
        parts.extend(by_cell[ci])
    parts.append("</g></svg>")
    svg_text = "\n".join(parts)
    return ConvertResult(kind="drawio", image_kind="svg", data=svg_text.encode("utf-8"), width=w, height=h, layers=[], warnings=warnings)


# =================================================================== DXF

ACI = {1: "#ff0000", 2: "#ffff00", 3: "#00ff00", 4: "#00ffff", 5: "#0000ff", 6: "#ff00ff", 7: "#ffffff", 8: "#808080", 9: "#c0c0c0"}
INSUNITS_M = {1: 0.0254, 2: 0.3048, 3: 1609.344, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0, 8: 2.54e-8, 9: 2.54e-5, 10: 0.9144, 11: 1e-10, 12: 1e-9, 13: 1e-6, 14: 0.1, 15: 10.0, 16: 100.0, 17: 1e9, 18: 1.495978707e11, 19: 9.4607e15, 20: 3.0857e16}


def aci_color(n: int) -> str:
    n = abs(int(n))
    if n in ACI:
        return ACI[n]
    if 250 <= n <= 255:
        g = int(51 + (n - 250) * 40.8)
        return f"#{g:02x}{g:02x}{g:02x}"
    return "#c0c0c0"


class _Budget:
    def __init__(self) -> None:
        self.start = time.monotonic()
        self.count = 0
        self.stopped = ""

    def tick(self) -> bool:
        if self.stopped:
            return False
        self.count += 1
        if self.count > DXF_MAX_ENTITIES:
            self.stopped = f"entity limit ({DXF_MAX_ENTITIES}) reached; drawing truncated"
            return False
        if self.count % 2000 == 0 and time.monotonic() - self.start > DXF_TIME_BUDGET:
            self.stopped = f"time budget ({int(DXF_TIME_BUDGET)} s) exceeded; drawing truncated"
            return False
        return True


def _pairs(text: str) -> List[Tuple[int, str]]:
    lines = text.splitlines()
    out: List[Tuple[int, str]] = []
    for i in range(0, len(lines) - 1, 2):
        try:
            code = int(lines[i].strip())
        except ValueError:
            continue
        out.append((code, lines[i + 1].strip()))
    return out


class _Ent:
    __slots__ = ("type", "codes", "verts", "children")

    def __init__(self, typ: str) -> None:
        self.type = typ
        self.codes: List[Tuple[int, str]] = []
        self.verts: List["_Ent"] = []
        self.children: List["_Ent"] = []

    def get(self, code: int, default: str = "") -> str:
        for c, v in self.codes:
            if c == code:
                return v
        return default

    def num(self, code: int, default: float = 0.0) -> float:
        v = self.get(code, "")
        try:
            return float(v) if v != "" else default
        except ValueError:
            return default

    @property
    def layer(self) -> str:
        return self.get(8, "0") or "0"


def _entities(pairs: List[Tuple[int, str]], i: int, end_markers: Tuple[str, ...]) -> Tuple[List[_Ent], int]:
    """Read entities starting at pairs[i] until a (0, end_marker). Returns (entities, index after the marker)."""
    ents: List[_Ent] = []
    cur: Optional[_Ent] = None
    poly: Optional[_Ent] = None
    n = len(pairs)
    while i < n:
        code, val = pairs[i]
        if code == 0:
            if val in end_markers:
                return ents, i + 1
            cur = _Ent(val)
            if val == "VERTEX" and poly is not None:
                poly.verts.append(cur)
            elif val == "SEQEND":
                poly = None
                cur = None
            else:
                if val == "POLYLINE":
                    poly = cur
                elif poly is not None and val != "VERTEX":
                    poly = None
                ents.append(cur)
        elif cur is not None:
            cur.codes.append((code, val))
        i += 1
    return ents, i


class _DXF:
    def __init__(self, text: str) -> None:
        self.header: Dict[str, List[Tuple[int, str]]] = {}
        self.layers: List[Dict[str, Any]] = []
        self.blocks: Dict[str, Tuple[Tuple[float, float], List[_Ent]]] = {}
        self.entities: List[_Ent] = []
        pairs = _pairs(text)
        i, n = 0, len(pairs)
        while i < n:
            code, val = pairs[i]
            if code == 0 and val == "SECTION" and i + 1 < n and pairs[i + 1][0] == 2:
                name = pairs[i + 1][1]
                i += 2
                if name == "HEADER":
                    i = self._header(pairs, i)
                elif name == "TABLES":
                    i = self._tables(pairs, i)
                elif name == "BLOCKS":
                    i = self._blocks(pairs, i)
                elif name == "ENTITIES":
                    self.entities, i = _entities(pairs, i, ("ENDSEC",))
                else:
                    while i < n and pairs[i] != (0, "ENDSEC"):
                        i += 1
                    i += 1
                continue
            if code == 0 and val == "EOF":
                break
            i += 1

    def _header(self, pairs: List[Tuple[int, str]], i: int) -> int:
        var = ""
        while i < len(pairs) and pairs[i] != (0, "ENDSEC"):
            code, val = pairs[i]
            if code == 9:
                var = val
                self.header[var] = []
            elif var:
                self.header[var].append((code, val))
            i += 1
        return i + 1

    def _tables(self, pairs: List[Tuple[int, str]], i: int) -> int:
        cur: Optional[Dict[str, Any]] = None
        in_layer_table = False
        while i < len(pairs) and pairs[i] != (0, "ENDSEC"):
            code, val = pairs[i]
            if code == 0:
                if cur is not None:
                    self.layers.append(cur)
                    cur = None
                if val == "TABLE":
                    in_layer_table = i + 1 < len(pairs) and pairs[i + 1] == (2, "LAYER")
                elif val == "ENDTAB":
                    in_layer_table = False
                elif val == "LAYER" and in_layer_table:
                    cur = {"name": "", "color": 7, "flags": 0}
            elif cur is not None:
                try:
                    if code == 2:
                        cur["name"] = val
                    elif code == 62:
                        cur["color"] = int(float(val))
                    elif code == 70:
                        cur["flags"] = int(float(val))
                except ValueError:
                    pass
            i += 1
        if cur is not None:
            self.layers.append(cur)
        return i + 1

    def _blocks(self, pairs: List[Tuple[int, str]], i: int) -> int:
        n = len(pairs)
        while i < n and pairs[i] != (0, "ENDSEC"):
            if pairs[i] == (0, "BLOCK"):
                i += 1
                name, bx, by = "", 0.0, 0.0
                while i < n and pairs[i][0] != 0:
                    code, val = pairs[i]
                    try:
                        if code == 2:
                            name = val
                        elif code == 10:
                            bx = float(val)
                        elif code == 20:
                            by = float(val)
                    except ValueError:
                        pass
                    i += 1
                ents, i = _entities(pairs, i, ("ENDBLK",))
                while i < n and pairs[i][0] != 0:  # ENDBLK body
                    i += 1
                if name:
                    self.blocks[name] = ((bx, by), ents)
                continue
            i += 1
        return i + 1

    def insunits(self) -> Optional[int]:
        for code, val in self.header.get("$INSUNITS", []):
            if code == 70:
                try:
                    return int(val)
                except ValueError:
                    return None
        return None


# 2D affine transform (a, b, c, d, e, f): x' = a x + c y + e ; y' = b x + d y + f
Aff = Tuple[float, float, float, float, float, float]
IDENT: Aff = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mul(m: Aff, n: Aff) -> Aff:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2, a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _ap(m: Aff, x: float, y: float) -> Tuple[float, float]:
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def _scale_of(m: Aff) -> Tuple[float, float, float, bool]:
    """(sx, sy, rotation radians, similarity?)"""
    sx = math.hypot(m[0], m[1])
    sy = math.hypot(m[2], m[3])
    rot = math.atan2(m[1], m[0])
    det = m[0] * m[3] - m[1] * m[2]
    sim = abs(sx - sy) < 1e-9 * max(1.0, sx) and abs(m[0] * m[2] + m[1] * m[3]) < 1e-9 * max(1.0, sx * sy)
    return sx, (sy if det >= 0 else -sy), rot, sim


# primitives in world coordinates
class _Prim:
    __slots__ = ("kind", "layer", "color", "data")

    def __init__(self, kind: str, layer: str, color: int, data: Any) -> None:
        self.kind, self.layer, self.color, self.data = kind, layer, color, data


def _arc_points(cx: float, cy: float, r: float, a0: float, a1: float, n: int = 24) -> List[Tuple[float, float]]:
    """Sample a CCW arc from a0 to a1 (radians)."""
    span = (a1 - a0) % (2 * math.pi) or 2 * math.pi
    return [(cx + r * math.cos(a0 + span * k / n), cy + r * math.sin(a0 + span * k / n)) for k in range(n + 1)]


def _bulge_arc(p0: Tuple[float, float], p1: Tuple[float, float], bulge: float) -> Tuple[float, float, float, float, float]:
    """(cx, cy, r, start_angle, end_angle) of a CCW (b > 0) or CW (b < 0) bulge segment."""
    theta = 4 * math.atan(bulge)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    chord = math.hypot(dx, dy)
    r = chord / (2 * math.sin(abs(theta) / 2)) if chord else 0.0
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    sag = math.sqrt(max(r * r - (chord / 2) ** 2, 0.0))
    # centre lies to the left of the chord for CCW arcs < 180°
    nx, ny = (-dy / chord, dx / chord) if chord else (0.0, 0.0)
    sign = 1 if (bulge > 0) == (abs(theta) < math.pi) else -1
    cx, cy = mx + nx * sag * sign, my + ny * sag * sign
    return cx, cy, r, math.atan2(p0[1] - cy, p0[0] - cx), math.atan2(p1[1] - cy, p1[0] - cx)


def _mtext_clean(s: str) -> List[str]:
    s = s.replace("\\P", "\n").replace("\\~", " ")
    s = re.sub(r"\\[ACcFfHhQTWp][^;\\{}]*;", "", s)
    s = re.sub(r"\\S([^;]*);", lambda m: m.group(1).replace("^", "/").replace("#", "/"), s)
    s = re.sub(r"\\[LlOoKkNn]", "", s)
    s = s.replace("{", "").replace("}", "").replace("\\\\", "\\")
    return [ln for ln in s.split("\n")]


def _text_clean(s: str) -> str:
    s = re.sub(r"%%[uUoO]", "", s)
    return s.replace("%%d", "°").replace("%%D", "°").replace("%%p", "±").replace("%%P", "±").replace("%%c", "⌀").replace("%%C", "⌀")


def _walk(dxf: _DXF, ents: Sequence[_Ent], m: Aff, depth: int, inherit_layer: str, hidden: set, out: List[_Prim], budget: _Budget, warn: Dict[str, int]) -> None:
    for e in ents:
        if not budget.tick():
            return
        layer = e.layer
        if layer == "0" and inherit_layer:
            layer = inherit_layer
        if layer in hidden:
            continue
        try:
            color = int(float(e.get(62, "256") or 256))
        except ValueError:
            color = 256
        t = e.type
        try:
            if t == "LINE":
                out.append(_Prim("line", layer, color, [_ap(m, e.num(10), e.num(20)), _ap(m, e.num(11), e.num(21))]))
            elif t in ("LWPOLYLINE", "POLYLINE"):
                verts: List[Tuple[float, float, float]] = []
                if t == "LWPOLYLINE":
                    for code, val in e.codes:
                        if code == 10:
                            verts.append((float(val), 0.0, 0.0))
                        elif code == 20 and verts:
                            verts[-1] = (verts[-1][0], float(val), verts[-1][2])
                        elif code == 42 and verts:
                            verts[-1] = (verts[-1][0], verts[-1][1], float(val))
                else:
                    if int(e.num(70)) & (16 | 64):  # 3D mesh / polyface: not a 2D outline
                        warn["POLYLINE mesh not rendered"] = warn.get("POLYLINE mesh not rendered", 0) + 1
                        continue
                    for v in e.verts:
                        if int(v.num(70)) & 16:  # spline frame control point
                            continue
                        verts.append((v.num(10), v.num(20), v.num(42)))
                closed = bool(int(e.num(70)) & 1)
                if len(verts) >= 2:
                    out.append(_Prim("poly", layer, color, (verts, closed, m)))
            elif t == "CIRCLE":
                out.append(_Prim("circle", layer, color, (e.num(10), e.num(20), e.num(40), m)))
            elif t == "ARC":
                out.append(_Prim("arc", layer, color, (e.num(10), e.num(20), e.num(40), math.radians(e.num(50)), math.radians(e.num(51)), m)))
            elif t == "ELLIPSE":
                cx, cy, mx, my, ratio = e.num(10), e.num(20), e.num(11), e.num(21), e.num(40, 1.0)
                t0, t1 = e.num(41, 0.0), e.num(42, 2 * math.pi)
                span = (t1 - t0) % (2 * math.pi) or 2 * math.pi
                pts = []
                for k in range(49):
                    a = t0 + span * k / 48
                    ux, uy = math.cos(a), math.sin(a) * ratio
                    pts.append(_ap(m, cx + mx * ux - my * uy, cy + my * ux + mx * uy))
                out.append(_Prim("pts", layer, color, (pts, span >= 2 * math.pi - 1e-9)))
            elif t in ("SOLID", "3DFACE", "TRACE"):
                p = [_ap(m, e.num(10 + k), e.num(20 + k)) for k in range(4)]
                if t != "3DFACE":
                    p = [p[0], p[1], p[3], p[2]]
                out.append(_Prim("pts", layer, color, (p, True)))
            elif t in ("TEXT", "ATTRIB"):
                x, y = (e.num(11), e.num(21)) if (e.get(72, "0") not in ("0", "") or e.get(73, "0") not in ("0", "")) and e.get(11) else (e.num(10), e.num(20))
                out.append(_Prim("text", layer, color, (_ap(m, x, y), e.num(40, 1.0), math.radians(e.num(50)), [_text_clean(e.get(1))], m, False)))
            elif t == "MTEXT":
                raw = "".join(v for c, v in e.codes if c == 3) + e.get(1)
                out.append(_Prim("text", layer, color, (_ap(m, e.num(10), e.num(20)), e.num(40, 1.0), math.radians(e.num(50)), _mtext_clean(raw), m, True)))
            elif t == "INSERT":
                name = e.get(2)
                blk = dxf.blocks.get(name)
                if blk is None:
                    warn["missing block " + name] = warn.get("missing block " + name, 0) + 1
                    continue
                if depth >= DXF_MAX_NESTING:
                    warn["block nesting deeper than 8 skipped"] = warn.get("block nesting deeper than 8 skipped", 0) + 1
                    continue
                (bx, by), bents = blk
                sx, sy, rot = e.num(41, 1.0), e.num(42, 1.0), math.radians(e.num(50))
                cos, sin = math.cos(rot), math.sin(rot)
                local: Aff = (cos * sx, sin * sx, -sin * sy, cos * sy, e.num(10), e.num(20))
                local = _mul(local, (1.0, 0.0, 0.0, 1.0, -bx, -by))
                _walk(dxf, bents, _mul(m, local), depth + 1, layer, hidden, out, budget, warn)
            elif t in ("DIMENSION", "HATCH", "MINSERT", "POINT", "SPLINE", "LEADER", "VIEWPORT", "IMAGE", "WIPEOUT", "SEQEND", "ATTDEF"):
                warn[f"{t} not rendered"] = warn.get(f"{t} not rendered", 0) + 1
            else:
                warn[f"{t} not rendered"] = warn.get(f"{t} not rendered", 0) + 1
        except (ValueError, ZeroDivisionError) as exc:
            warn[f"{t}: {exc}"] = warn.get(f"{t}: {exc}", 0) + 1


def _prim_points(p: _Prim) -> List[Tuple[float, float]]:
    if p.kind == "line":
        return list(p.data)
    if p.kind == "pts":
        return list(p.data[0])
    if p.kind == "circle":
        cx, cy, r, m = p.data
        return [_ap(m, cx + dx, cy + dy) for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r))]
    if p.kind == "arc":
        cx, cy, r, a0, a1, m = p.data
        return [_ap(m, x, y) for x, y in _arc_points(cx, cy, r, a0, a1, 36)]
    if p.kind == "poly":
        verts, closed, m = p.data
        pts = []
        n = len(verts)
        for i in range(n if closed else n - 1):
            x0, y0, b = verts[i]
            x1, y1, _ = verts[(i + 1) % n]
            if b:
                cx, cy, r, a0, a1 = _bulge_arc((x0, y0), (x1, y1), b)
                arc = _arc_points(cx, cy, r, a0, a1, 16) if b > 0 else _arc_points(cx, cy, r, a1, a0, 16)
                pts += [_ap(m, x, y) for x, y in arc]
            else:
                pts.append(_ap(m, x0, y0))
                pts.append(_ap(m, x1, y1))
        return pts
    if p.kind == "text":
        return [p.data[0]]
    return []


def dxf_to_svg(text: str, hide_layers: Optional[List[str]] = None, use_dxf_colors: bool = False) -> ConvertResult:
    if isinstance(text, bytes):  # pragma: no cover - defensive
        text = text.decode("utf-8", errors="replace")
    if text.startswith("AutoCAD Binary DXF"):
        raise UnsupportedPlan("binary_dxf", "Binary DXF is not supported. Save as ASCII DXF.")
    if len(text) > MAX_BYTES:
        raise UnsupportedPlan("unsupported_format", "DXF is larger than 50 MB")
    dxf = _DXF(text)
    if not dxf.entities and not dxf.layers:
        raise UnsupportedPlan("unsupported_format", "no DXF ENTITIES section found")
    hide = set(hide_layers or [])
    table = {L["name"]: L for L in dxf.layers}
    off = {L["name"] for L in dxf.layers if L["color"] < 0 or (L["flags"] & 1)}
    hidden = off | hide
    budget = _Budget()
    warn: Dict[str, int] = {}
    prims: List[_Prim] = []
    _walk(dxf, dxf.entities, IDENT, 0, "", hidden, prims, budget, warn)
    warnings = [f"{k} ({v}×)" if v > 1 else k for k, v in sorted(warn.items())]
    if budget.stopped:
        warnings.append(budget.stopped)
    xs: List[float] = []
    ys: List[float] = []
    for p in prims:
        for x, y in _prim_points(p):
            xs.append(x)
            ys.append(y)
    if xs:
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    else:
        minx, maxx, miny, maxy = 0.0, 1.0, 0.0, 1.0
    span = max(maxx - minx, maxy - miny) or 1.0
    k = 2000.0 / span
    M = 40.0
    W, H = (maxx - minx) * k + 2 * M, (maxy - miny) * k + 2 * M

    def mp(x: float, y: float) -> Tuple[float, float]:
        return (M + (x - minx) * k, M + (maxy - y) * k)

    def col(layer: str, c: int) -> Optional[str]:
        if not use_dxf_colors:
            return None
        if c in (0, 256):
            return aci_color((table.get(layer) or {}).get("color", 7))
        return aci_color(c)

    order = [L["name"] for L in dxf.layers]
    for p in prims:
        if p.layer not in order:
            order.append(p.layer)
    groups: Dict[str, List[str]] = {name: [] for name in order}
    counts: Dict[str, int] = {}
    for p in prims:
        counts[p.layer] = counts.get(p.layer, 0) + 1
        c = col(p.layer, p.color)
        stroke = f' stroke="{c}"' if c else ""
        groups[p.layer].append(_svg_prim(p, mp, k, stroke, c))
    out = [f'<svg xmlns="{SVG_NS}" width="{_f(W)}" height="{_f(H)}" viewBox="0 0 {_f(W)} {_f(H)}">']
    out.append(f'<g fill="none" stroke="{DEFAULT_STROKE}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" font-family="Helvetica, Arial, sans-serif">')
    for name in order:
        if name in hidden or not groups.get(name):
            continue
        lc = aci_color((table.get(name) or {}).get("color", 7)) if use_dxf_colors else None
        gstroke = f' stroke="{lc}"' if lc else ""
        out.append(f'<g data-layer="{_esc(name)}"{gstroke}>')
        out.extend(groups[name])
        out.append("</g>")
    out.append("</g></svg>")
    layers = []
    for name in order:
        L = table.get(name)
        color = aci_color(L["color"]) if L else "#c0c0c0"
        visible = name not in off and name not in hide
        layers.append({"name": name, "color": color, "visible": visible, "count": counts.get(name, sum(1 for e in dxf.entities if e.layer == name))})
    iu = dxf.insunits()
    units = {"insunits": iu, "meters_per_unit": INSUNITS_M.get(iu)} if iu is not None else None
    return ConvertResult(kind="dxf", image_kind="svg", data="\n".join(out).encode("utf-8"), width=W, height=H, layers=layers, warnings=warnings, units=units)


def _svg_prim(p: _Prim, mp: Any, k: float, stroke: str, color: Optional[str]) -> str:
    if p.kind == "line":
        (x1, y1), (x2, y2) = mp(*p.data[0]), mp(*p.data[1])
        return f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}"{stroke}/>'
    if p.kind == "pts":
        pts, closed = p.data
        s = " ".join(f"{_f(a)},{_f(b)}" for a, b in (mp(x, y) for x, y in pts))
        return f'<{"polygon" if closed else "polyline"} points="{s}"{stroke}/>'
    if p.kind == "circle":
        cx, cy, r, m = p.data
        sx, sy, rot, sim = _scale_of(m)
        X, Y = mp(*_ap(m, cx, cy))
        if sim:
            return f'<circle cx="{_f(X)}" cy="{_f(Y)}" r="{_f(r * sx * k)}"{stroke}/>'
        return f'<ellipse cx="{_f(X)}" cy="{_f(Y)}" rx="{_f(r * sx * k)}" ry="{_f(r * abs(sy) * k)}" transform="rotate({_f(-math.degrees(rot))} {_f(X)} {_f(Y)})"{stroke}/>'
    if p.kind == "arc":
        cx, cy, r, a0, a1, m = p.data
        sx, sy, rot, sim = _scale_of(m)
        if not sim:
            pts = [mp(*_ap(m, x, y)) for x, y in _arc_points(cx, cy, r, a0, a1, 36)]
            return '<polyline points="' + " ".join(f"{_f(a)},{_f(b)}" for a, b in pts) + f'"{stroke}/>'
        span = (a1 - a0) % (2 * math.pi) or 2 * math.pi
        ccw_world = sy > 0  # mirrored inserts flip the direction
        P0 = mp(*_ap(m, cx + r * math.cos(a0), cy + r * math.sin(a0)))
        P1 = mp(*_ap(m, cx + r * math.cos(a1), cy + r * math.sin(a1)))
        R = r * sx * k
        sweep = 0 if ccw_world else 1  # y is flipped: CCW in the drawing is the SVG negative-angle direction
        if span >= 2 * math.pi - 1e-9:
            Pm = mp(*_ap(m, cx + r * math.cos(a0 + math.pi), cy + r * math.sin(a0 + math.pi)))
            return f'<path d="M {_f(P0[0])} {_f(P0[1])} A {_f(R)} {_f(R)} 0 0 {sweep} {_f(Pm[0])} {_f(Pm[1])} A {_f(R)} {_f(R)} 0 0 {sweep} {_f(P0[0])} {_f(P0[1])}"{stroke}/>'
        large = 1 if span > math.pi else 0
        return f'<path d="M {_f(P0[0])} {_f(P0[1])} A {_f(R)} {_f(R)} 0 {large} {sweep} {_f(P1[0])} {_f(P1[1])}"{stroke}/>'
    if p.kind == "poly":
        verts, closed, m = p.data
        sx, sy, rot, sim = _scale_of(m)
        n = len(verts)
        if not any(v[2] for v in verts):
            s = " ".join(f"{_f(a)},{_f(b)}" for a, b in (mp(*_ap(m, x, y)) for x, y, _ in verts))
            return f'<{"polygon" if closed else "polyline"} points="{s}"{stroke}/>'
        X0, Y0 = mp(*_ap(m, verts[0][0], verts[0][1]))
        d = [f"M {_f(X0)} {_f(Y0)}"]
        for i in range(n if closed else n - 1):
            x0, y0, b = verts[i]
            x1, y1, _ = verts[(i + 1) % n]
            X1, Y1 = mp(*_ap(m, x1, y1))
            if b and sim:
                _cx, _cy, r, _a0, _a1 = _bulge_arc((x0, y0), (x1, y1), b)
                R = r * sx * k
                large = 1 if abs(4 * math.atan(b)) > math.pi else 0
                sweep = 0 if (b > 0) == (sy > 0) else 1
                d.append(f"A {_f(R)} {_f(R)} 0 {large} {sweep} {_f(X1)} {_f(Y1)}")
            elif b:
                cx, cy, r, a0, a1 = _bulge_arc((x0, y0), (x1, y1), b)
                arc = _arc_points(cx, cy, r, a0, a1, 16) if b > 0 else list(reversed(_arc_points(cx, cy, r, a1, a0, 16)))
                for x, y in arc[1:]:
                    X, Y = mp(*_ap(m, x, y))
                    d.append(f"L {_f(X)} {_f(Y)}")
            else:
                d.append(f"L {_f(X1)} {_f(Y1)}")
        if closed:
            d.append("Z")
        return f'<path d="{" ".join(d)}"{stroke}/>'
    if p.kind == "text":
        (x, y), h, rot, lines, m, is_mtext = p.data
        sx, sy, mrot, _sim = _scale_of(m)
        X, Y = mp(x, y)
        fs = max(h * sx * k, 1.0)
        ang = -math.degrees(rot + mrot)
        fill = f' fill="{color}"' if color else f' fill="{DEFAULT_STROKE}"'
        tr = f' transform="rotate({_f(ang)} {_f(X)} {_f(Y)})"' if abs(ang) > 1e-6 else ""
        if is_mtext:
            spans = "".join(f'<tspan x="{_f(X)}" y="{_f(Y + fs * (1 + 1.25 * i))}">{_esc(ln)}</tspan>' for i, ln in enumerate(lines))
            return f'<text x="{_f(X)}" y="{_f(Y + fs)}" font-size="{_f(fs)}" stroke="none"{fill}{tr}>{spans}</text>'
        return f'<text x="{_f(X)}" y="{_f(Y)}" font-size="{_f(fs)}" stroke="none"{fill}{tr}>{_esc(lines[0] if lines else "")}</text>'
    return ""


# =================================================================== PDF


def rasterizer() -> Optional[str]:
    """Name of the first PDF rasterizer available, else None."""
    if (os.environ.get("FATHOM_PDF_RASTERIZER") or "").strip():
        return "custom"
    for tool in ("pdftoppm", "mutool", "gs"):
        if shutil.which(tool):
            return tool
    if sys.platform == "darwin" and shutil.which("sips"):
        return "sips"
    return None


def pdf_to_png(path: Path, page: int = 0, dpi: int = 150) -> bytes:
    tool = rasterizer()
    if tool is None:
        raise UnsupportedPlan("pdf_unsupported", PDF_MESSAGE)
    page = max(0, int(page))
    dpi = max(36, min(int(dpi), 600))
    with tempfile.TemporaryDirectory(prefix="fathom-pdf-") as tmp:
        src = Path(tmp) / "in.pdf"
        shutil.copyfile(str(path), str(src))
        out = Path(tmp) / "out.png"
        if tool == "custom":
            tpl = os.environ.get("FATHOM_PDF_RASTERIZER", "")
            args = [a.format(**{"in": str(src), "out": str(out), "page": page, "dpi": dpi}) for a in shlex.split(tpl)]
        elif tool == "pdftoppm":
            args = [shutil.which("pdftoppm") or "pdftoppm", "-png", "-r", str(dpi), "-f", str(page + 1), "-l", str(page + 1), "-singlefile", str(src), str(Path(tmp) / "out")]
        elif tool == "mutool":
            args = [shutil.which("mutool") or "mutool", "draw", "-q", "-o", str(out), "-r", str(dpi), str(src), str(page + 1)]
        elif tool == "gs":
            args = [shutil.which("gs") or "gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=png16m", f"-r{dpi}", f"-dFirstPage={page + 1}", f"-dLastPage={page + 1}", f"-sOutputFile={out}", str(src)]
        else:
            if page:
                raise UnsupportedPlan("pdf_unsupported", "sips only renders the first PDF page. " + PDF_MESSAGE)
            args = [shutil.which("sips") or "sips", "-s", "format", "png", str(src), "--out", str(out)]
        try:
            subprocess.run(args, capture_output=True, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UnsupportedPlan("pdf_unsupported", f"PDF rasterizer failed ({exc}). " + PDF_MESSAGE)
        if not out.is_file():
            cands = sorted(Path(tmp).glob("out*.png"))
            out = cands[0] if cands else out
        if not out.is_file() or not out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n":
            raise UnsupportedPlan("pdf_unsupported", f"{tool} produced no PNG (page {page} may not exist). " + PDF_MESSAGE)
        return out.read_bytes()


# =================================================================== DWG


def dwg_to_dxf(path: Path) -> str:
    """Convert DWG with the ODA File Converter (``FATHOM_ODA``); returns DXF text."""
    oda = (os.environ.get("FATHOM_ODA") or "").strip()
    if not oda:
        raise UnsupportedPlan("dwg_unsupported", DWG_MESSAGE)
    with tempfile.TemporaryDirectory(prefix="fathom-oda-") as tmp:
        in_dir, out_dir = Path(tmp) / "in", Path(tmp) / "out"
        in_dir.mkdir()
        out_dir.mkdir()
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.name) or "plan.dwg"
        if not name.lower().endswith(".dwg"):
            name += ".dwg"
        shutil.copyfile(str(path), str(in_dir / name))
        args = [oda, str(in_dir), str(out_dir), "ACAD2018", "DXF", "0", "1", name]
        if os.environ.get("FATHOM_ODA_XVFB") == "1":
            args = ["xvfb-run", "-a"] + args
        try:
            subprocess.run(args, capture_output=True, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UnsupportedPlan("dwg_unsupported", f"ODA File Converter failed ({exc}). " + DWG_MESSAGE)
        outs = sorted(out_dir.rglob("*.dxf"))
        if not outs:
            raise UnsupportedPlan("dwg_unsupported", "ODA File Converter produced no DXF. " + DWG_MESSAGE)
        return outs[0].read_text(encoding="utf-8", errors="replace")


# =============================================================== convert


def _read_dxf_text(data: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def convert(path: Path, *, page: int = 0, hide_layers: Optional[List[str]] = None) -> ConvertResult:
    path = Path(path)
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise UnsupportedPlan("unsupported_format", "floor plans are limited to 50 MB")
    data = path.read_bytes()
    kind = detect_plan_kind(path.name, data[:8192])
    if kind == "png":
        w, h = png_size(data)
        return ConvertResult("png", "png", data, float(w), float(h))
    if kind == "jpg":
        w, h = jpg_size(data)
        return ConvertResult("jpg", "jpg", data, float(w), float(h))
    if kind == "svg":
        clean = sanitize_svg(data.decode("utf-8", errors="replace"))
        w, h = _svg_size(ET.fromstring(clean.split("\n", 1)[1] if clean.startswith("<?xml") else clean))
        return ConvertResult("svg", "svg", clean.encode("utf-8"), w, h)
    if kind == "drawio":
        res = drawio_to_svg(data.decode("utf-8", errors="replace"), page=page)
        return res
    if kind == "dxf":
        return dxf_to_svg(_read_dxf_text(data), hide_layers=hide_layers)
    if kind == "dxf-binary":
        raise UnsupportedPlan("binary_dxf", "Binary DXF is not supported. Save as ASCII DXF (AutoCAD: SAVEAS → DXF, ASCII).")
    if kind == "dwg":
        res = dxf_to_svg(dwg_to_dxf(path), hide_layers=hide_layers)
        res.kind = "dwg"
        res.warnings.insert(0, "converted from DWG with the ODA File Converter")
        return res
    if kind == "pdf":
        png = pdf_to_png(path, page=page)
        w, h = png_size(png)
        return ConvertResult("pdf", "png", png, float(w), float(h), warnings=[f"page {page + 1} rasterized with {rasterizer()}"])
    raise UnsupportedPlan("unsupported_format", "Unsupported floor-plan format. Use PNG, JPG, SVG, PDF, Draw.io or DXF.")


# ============================================================ plan export


def _attachment_path(doc: Doc, att_id: str, project_dir: Path) -> Optional[Path]:
    att = next((a for a in doc.get("attachments") or [] if a.get("id") == att_id), None)
    if not att or not att.get("file"):
        return None
    p = (Path(project_dir) / att["file"]).resolve()
    try:
        p.relative_to(Path(project_dir).resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


_MIME = {"png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml"}


#: stroke colours of the shared-path kinds in ``plan_svg(runs=True)`` (FR-PLAN-16)
_PATH_COLORS = {"tray": "#6b7a90", "catwalk": "#8a6d3b", "trench": "#5b7f5b", "conduit": "#7a6b90", "floor": "#9a8f6b", "other": "#8a93a6"}


def _runs_layer(doc: Doc, fp: Dict[str, Any], w: float, h: float, r: float, fs: float) -> Tuple[List[str], str]:
    """``<g class="paths">`` + ``<g class="runs">`` markup for a plan and the legend line (FR-PLAN-16)."""
    from .runs import plan_runs
    from .vocab import DISCIPLINES, medium_discipline

    data = plan_runs(doc, str(fp.get("id")))
    unit = "m" if data["unit"] == "m" else "px"
    out: List[str] = ['<g class="paths" fill="none" stroke-linecap="round" stroke-linejoin="round">']
    for p in data["paths"]:
        pts = [(float(q[0]) * w, float(q[1]) * h) for q in p.get("points") or [] if isinstance(q, (list, tuple)) and len(q) >= 2]
        if len(pts) < 2:
            continue
        kind = str(p.get("kind") or "other")
        color = str(p.get("color") or _PATH_COLORS.get(kind, _PATH_COLORS["other"]))
        out.append(f'<polyline data-path="{_esc(p["id"])}" class="path path-{_esc(kind)}" points="{" ".join(f"{_f(x)},{_f(y)}" for x, y in pts)}" '
                   f'stroke="{_esc(color)}" stroke-width="{_f(r * 0.9)}" stroke-opacity="0.55"/>')
        label = str(p.get("name") or p["id"])
        x0, y0 = pts[0]
        out.append(f'<text x="{_f(x0 + r * 0.6)}" y="{_f(y0 - r * 0.6)}" font-size="{_f(fs * 0.85)}" fill="{_esc(color)}" stroke="#ffffff" '
                   f'stroke-width="{_f(fs / 6)}" paint-order="stroke" font-style="italic">{_esc(label)}</text>')
    out.append("</g>")
    out.append('<g class="runs" fill="none" stroke-linecap="round" stroke-linejoin="round">')
    for run in data["runs"]:
        pts = [(float(q[0]) * w, float(q[1]) * h) for q in run["points"]]
        if len(pts) < 2:
            continue
        disc = medium_discipline(str(run.get("medium") or "other"))
        color = DISCIPLINES.get(disc, DISCIPLINES["other"])["color"]
        dash = f' stroke-dasharray="{_f(r)} {_f(r * 0.7)}"' if run.get("auto") else ""
        # label at the arc-length midpoint
        cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        half = cum[-1] / 2
        mx, my = pts[-1]
        for i in range(len(pts) - 1):
            if cum[i] <= half <= cum[i + 1]:
                seg = cum[i + 1] - cum[i]
                u = (half - cum[i]) / seg if seg else 0.0
                mx, my = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * u, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * u
                break
        text = f'{_f(run["length_m"])} {unit}'
        out.append(f'<g data-cable="{_esc(run["cable"])}" data-length="{_f(run["length_m"])}" data-estimate="{_f(run["estimate_m"])}">'
                   f'<polyline points="{" ".join(f"{_f(x)},{_f(y)}" for x, y in pts)}" stroke="{color}" stroke-width="{_f(r / 3)}"{dash}/>'
                   f'<text x="{_f(mx)}" y="{_f(my - r * 0.4)}" text-anchor="middle" font-size="{_f(fs * 0.8)}" fill="#0b0f17" stroke="#ffffff" '
                   f'stroke-width="{_f(fs / 6)}" paint-order="stroke">{_esc(text)}</text></g>')
    out.append("</g>")
    n = data["totals"]["runs"]
    legend = f'Runs: {n} \u00b7 total {_f(data["totals"]["estimate_m"])} {unit} (estimated)'
    return out, legend


def plan_svg(doc: Doc, floorplan_id: str, project_dir: Path, *, runs: bool = False, scene: Optional[str] = None) -> str:
    """Standalone SVG of a plan: the image, one ``<g data-device>`` per marker, and a legend.
    ``runs=True`` adds the shared paths and the cable runs with their lengths (FR-PLAN-16);
    ``scene`` renders that scene's markers and patch (``None`` = the live doc)."""
    from .vocab import DISCIPLINES, kind_discipline

    if scene:
        from .runs import scene_doc

        doc = scene_doc(doc, scene)
    fp = next((f for f in doc.get("floorplans") or [] if f.get("id") == floorplan_id), None)
    if fp is None:
        raise KeyError(floorplan_id)
    img = fp.get("image") or {}
    w, h = float(img.get("width") or 1000), float(img.get("height") or 1000)
    href = ""
    path = _attachment_path(doc, img.get("attachment", ""), project_dir)
    kind = img.get("kind") or "png"
    if path is not None:
        data = path.read_bytes()
        if fp.get("hidden_layers") and (fp.get("source") or {}).get("kind") in ("dxf", "dwg"):
            src = _attachment_path(doc, (fp.get("source") or {}).get("attachment", ""), project_dir)
            if src is not None:
                try:
                    data = convert(src, page=int((fp.get("source") or {}).get("page") or 0), hide_layers=list(fp["hidden_layers"])).data
                except UnsupportedPlan:
                    pass
        if kind == "svg":
            data = sanitize_svg(data.decode("utf-8", errors="replace")).encode("utf-8")
        href = f"data:{_MIME.get(kind, 'image/png')};base64," + base64.b64encode(data).decode("ascii")
    devices = {d.get("id"): d for d in doc.get("devices") or []}
    r = max(6.0, min(w, h) / 90)
    fs = r * 1.5
    used: List[str] = []
    marks: List[str] = []
    for mk in fp.get("markers") or []:
        dev = devices.get(mk.get("device"))
        if dev is None:
            continue
        disc = dev.get("discipline") or kind_discipline(dev.get("kind", ""))
        if disc not in used:
            used.append(disc)
        color = DISCIPLINES.get(disc, DISCIPLINES["other"])["color"]
        x, y = float(mk.get("x", 0)) * w, float(mk.get("y", 0)) * h
        label = mk.get("label") or dev.get("name", dev.get("id"))
        if int(dev.get("count") or 1) > 1:
            label += f" ×{int(dev['count'])}"
        planned = ' stroke-dasharray="3 2"' if dev.get("status") == "planned" else ""
        marks.append(
            f'<g data-device="{_esc(dev["id"])}" transform="translate({_f(x)} {_f(y)})">'
            f'<circle r="{_f(r)}" fill="{color}" stroke="#0b0f17" stroke-width="{_f(r / 4)}"{planned}/>'
            f'<text x="{_f(r * 1.4)}" y="{_f(fs * 0.35)}" font-size="{_f(fs)}" fill="#0b0f17" stroke="#ffffff" stroke-width="{_f(fs / 5)}" paint-order="stroke">{_esc(label)}</text></g>'
        )
    runs_markup: List[str] = []
    runs_legend = ""
    if runs:
        runs_markup, runs_legend = _runs_layer(doc, fp, w, h, r, fs)
    lh = fs * 2.2
    legend_rows = len(used) + (1 if runs_legend else 0)
    legend_h = lh * (1 + max(1, legend_rows)) if legend_rows else 0
    total_h = h + legend_h
    out = [f'<svg xmlns="{SVG_NS}" width="{_f(w)}" height="{_f(total_h)}" viewBox="0 0 {_f(w)} {_f(total_h)}" font-family="Helvetica, Arial, sans-serif" data-floorplan="{_esc(floorplan_id)}">']
    out.append(f"<title>{_esc(fp.get('name', floorplan_id))}</title>")
    out.append(f'<rect width="{_f(w)}" height="{_f(total_h)}" fill="#ffffff"/>')
    if href:
        out.append(f'<image x="0" y="0" width="{_f(w)}" height="{_f(h)}" href="{href}" preserveAspectRatio="none"/>')
    out.append('<g class="markers">')
    out.extend(marks)
    out.append("</g>")
    out.extend(runs_markup)
    if legend_rows:
        out.append(f'<g class="legend" transform="translate({_f(fs)} {_f(h + lh * 0.6)})">')
        out.append(f'<text y="{_f(fs)}" font-size="{_f(fs)}" font-weight="bold" fill="#0b0f17">{_esc(fp.get("name", ""))} · legend</text>')
        for i, disc in enumerate(used, 1):
            d = DISCIPLINES.get(disc, DISCIPLINES["other"])
            out.append(f'<circle cx="{_f(r)}" cy="{_f(i * lh + fs * 0.6)}" r="{_f(r)}" fill="{d["color"]}"/><text x="{_f(r * 3)}" y="{_f(i * lh + fs)}" font-size="{_f(fs)}" fill="#0b0f17">{_esc(d["label"])}</text>')
        if runs_legend:
            i = len(used) + 1
            out.append(f'<text class="runs-legend" x="{_f(r * 3)}" y="{_f(i * lh + fs)}" font-size="{_f(fs)}" fill="#0b0f17">{_esc(runs_legend)}</text>')
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)


__all__ = [
    "UnsupportedPlan", "ConvertResult", "detect_plan_kind", "convert", "sanitize_svg", "drawio_to_svg", "dxf_to_svg",
    "pdf_to_png", "rasterizer", "plan_svg", "dwg_to_dxf", "png_size", "jpg_size", "DWG_MESSAGE", "PDF_MESSAGE",
]
