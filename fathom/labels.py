"""Device labels sized for the Brady M511 (FR-QR-03..05), standard library only.

The M511 is a 300 dpi thermal-transfer label printer that prints from Brady
Express Labels / Brady Workstation, not from a browser. Fathom therefore makes
print-ready artwork at exact physical size: one SVG per device (``width`` /
``height`` in mm, ``viewBox`` in 300 dpi units) that is imported into the Brady
app, a printable HTML sheet for a 100 % scale print on any sheet printer, a CSV
for Brady Workstation data import and a ZIP of everything (plus PNGs when
headless Chrome is available).

Pure: no I/O apart from ``labels_zip``'s optional PNG rendering through
``fathom.export`` and the temporary files that needs.
"""

from __future__ import annotations

import csv
import html
import io
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union
from urllib.parse import quote

Doc = Dict[str, Any]

DPI = 300.0
MM_PER_INCH = 25.4
PX_PER_MM = DPI / MM_PER_INCH  # 11.811 300-dpi units per mm
MARGIN_MM = 1.5

# Die-cut cartridges (W × H in mm) and continuous tapes; order matters (UI select, docs).
_PRESET_ROWS = (
    ("m511-1x0.5", "1″ × 0.5″ die-cut", 25.4, 12.7, ("M4-47-422", "M4-47-483", "M5-17-351"), False),
    ("m511-1x1", "1″ × 1″ die-cut", 25.4, 25.4, ("M4-49-422", "M4-49-498"), False),
    ("m511-1x2", "1″ × 2″ die-cut", 25.4, 50.8, ("M4-60-483", "M4-60-428", "M5-20-351"), False),
    ("m511-0.5x1", "0.5″ × 1″ die-cut", 12.7, 25.4, ("M4-131-499",), False),
    ("m511-1.9x1", "1.9″ × 1″ die-cut", 48.26, 25.4, ("M5-78-492",), False),
    ("m511-cont-1.5", "1.5″ continuous tape", 38.1, 50.8, ("M5C-1500-*",), True),
    ("m511-cont-1", "1″ continuous tape", 25.4, 38.1, ("M5C-1000-*",), True),
)

PRESETS: Dict[str, Dict[str, Any]] = {}
for _id, _label, _w, _h, _parts, _cont in _PRESET_ROWS:
    PRESETS[_id] = {"id": _id, "label": _label, "width_mm": _w, "height_mm": _h, "parts": list(_parts), "continuous": _cont}
DEFAULT_PRESET = "m511-1x0.5"


def presets() -> List[Dict[str, Any]]:
    """JSON-ready preset list in cartridge order."""
    return [dict(p, parts=list(p["parts"])) for p in PRESETS.values()]


def preset_size_text(preset: Union[str, Dict[str, Any]]) -> str:
    p = PRESETS[preset] if isinstance(preset, str) else preset
    return f"{_mm(p['width_mm'])}×{_mm(p['height_mm'])} mm"


# ------------------------------------------------------------------ fields


def _mm(v: float) -> str:
    s = f"{float(v):.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _px(mm: float) -> int:
    return int(round(mm * PX_PER_MM))


def _esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _name_of(items: Iterable[Any], key: Any) -> str:
    if not key:
        return ""
    for it in items or []:
        if isinstance(it, dict) and it.get("id") == key:
            return str(it.get("name") or key)
    return str(key)


def _formatter() -> Any:
    """``schema.format_short_code`` when that build has short codes, else None."""
    try:
        from . import schema
    except ImportError:
        return None
    fn = getattr(schema, "format_short_code", None)
    return fn if callable(fn) else None


def _project_name(doc: Doc, project: Optional[str]) -> str:
    return str(project or (doc.get("meta") or {}).get("slug") or "project")


def label_fields(doc: Doc, device: Dict[str, Any], base_url: str = "", project: Optional[str] = None) -> Dict[str, str]:
    """Text that goes on a label (and into the CSV): code, name, room, location, url, kind, manufacturer, model.

    ``code`` is the dashed short code (``XXXX-XXXX``) when the device has one and this build formats
    them; else ``""``. ``url`` is ``<base>/c/<code>`` with a code and ``<base>/p/<project>/d/<id>`` without.
    """
    base = str(base_url or "").rstrip("/")
    dev_id = str(device.get("id") or "")
    raw = device.get("short_code")
    code = ""
    fmt = _formatter() if raw else None
    if raw and fmt is not None:
        try:
            code = str(fmt(str(raw)) or "")
        except Exception:
            code = ""
    if code:
        url = f"{base}/c/{quote(str(raw), safe='')}"
    else:
        url = f"{base}/p/{quote(_project_name(doc, project), safe='')}/d/{quote(dev_id, safe='')}"
    loc = device.get("location")
    return {
        "code": code,
        "name": str(device.get("name") or dev_id),
        "room": _name_of(doc.get("rooms") or [], device.get("room")),
        "location": _name_of(doc.get("locations") or [], loc) if loc else "",
        "url": url,
        "kind": str(device.get("kind") or ""),
        "manufacturer": str(device.get("manufacturer") or ""),
        "model": str(device.get("model") or ""),
    }


# ------------------------------------------------------------------ selection


def select_devices(doc: Doc, ids: Union[None, str, Sequence[str]] = None, room: Optional[str] = None, state: Optional[str] = None) -> List[Dict[str, Any]]:
    """Devices to label: explicit ``ids`` (comma list or sequence, order kept), else ``room``, else all;
    ``state`` keeps only devices whose ``status`` (default ``installed``) matches. Auto-generated devices
    are skipped; the default order is room name, then device name."""
    devices = [d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id") and not d.get("auto")]
    if ids:
        wanted = [s.strip() for s in (ids.split(",") if isinstance(ids, str) else ids) if s and s.strip()]
        by_id = {str(d["id"]): d for d in devices}
        out = [by_id[i] for i in wanted if i in by_id]
    else:
        rooms = {str(r.get("id")): str(r.get("name") or r.get("id")) for r in doc.get("rooms") or [] if isinstance(r, dict)}
        out = [d for d in devices if not room or room == "*" or str(d.get("room") or "") == room]
        def key(d: Dict[str, Any]) -> Any:
            rid = str(d.get("room") or "")
            return (not rid, rooms.get(rid, rid).lower(), str(d.get("name") or d["id"]).lower(), str(d["id"]))

        out.sort(key=key)
    if state and state != "all":
        out = [d for d in out if str(d.get("status") or "installed") == state]
    return out


# ------------------------------------------------------------------ SVG


def _qr_path(matrix: List[List[bool]]) -> str:
    parts = []
    for y, row in enumerate(matrix):
        x = 0
        n = len(row)
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                parts.append(f"M{start} {y}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    return "".join(parts)


def _qr_group(text: str, x: float, y: float, size: float) -> str:
    """QR for ``text`` drawn into the ``size`` square at (x, y), one module of quiet zone inside it."""
    from .qr import encode

    try:
        matrix = encode(text, ecl="M")
    except ValueError:
        matrix = encode(text[:200], ecl="L")
    n = len(matrix)
    border = 1
    scale = size / (n + 2 * border)
    off = border * scale
    return (f'<g transform="translate({x + off:.2f} {y + off:.2f}) scale({scale:.4f})" shape-rendering="crispEdges">'
            f'<path d="{_qr_path(matrix)}" fill="#000"/></g>')


def _fit_font(text: str, width: float, em_per_char: float, cap: float, floor: float) -> float:
    n = max(1, len(text))
    return max(floor, min(cap, width / (em_per_char * n)))


def _truncate(text: str, width: float, font: float, em_per_char: float) -> str:
    max_chars = int(width // max(1.0, em_per_char * font))
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return "…"
    return text[:max_chars - 1].rstrip() + "…"


def _text(x: float, y: float, text: str, font: float, family: str, weight: str = "normal", anchor: str = "start") -> str:
    if not text:
        return ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{font:.1f}" font-weight="{weight}" '
            f'text-anchor="{anchor}" fill="#000">{_esc(text)}</text>')


_MONO = "ui-monospace, Menlo, monospace"
_SANS = "system-ui, sans-serif"
_MONO_EM = 0.6   # advance per character, monospace
_SANS_EM = 0.52  # average advance per character, sans


def _text_block(x: float, y: float, width: float, height: float, fields: Dict[str, str], big: str) -> str:
    """Code (mono), name (sans, truncated), room · location (smallest) stacked from the top."""
    gap = max(2.0, height * 0.04)
    code_font = _fit_font(big, width, _MONO_EM, min(height * 0.42, 120.0), 10.0)
    name_font = max(10.0, min(code_font * 0.62, height * 0.2))
    sub_font = max(9.0, min(code_font * 0.46, height * 0.15))
    total = code_font + name_font + sub_font + 2 * gap
    if total > height:  # squeeze proportionally so three lines always fit
        k = height / total
        code_font, name_font, sub_font, gap = code_font * k, name_font * k, sub_font * k, gap * k
    out = []
    cy = y + code_font * 0.8
    out.append(_text(x, cy, big, code_font, _MONO, "700"))
    ny = cy + gap + name_font * 0.85
    name = fields["name"] if fields["name"] != big else ""
    if name:
        out.append(_text(x, ny, _truncate(name, width, name_font, _SANS_EM), name_font, _SANS))
    sub = " · ".join(s for s in (fields["room"], fields["location"]) if s)
    if sub:
        sy = (ny if name else cy) + gap + sub_font * 0.85
        out.append(_text(x, sy, _truncate(sub, width, sub_font, _SANS_EM), sub_font, _SANS))
    return "".join(out)


def _svg(doc: Doc, device: Dict[str, Any], preset: str, base_url: str, project: Optional[str], unit: str) -> str:
    p = PRESETS[preset]
    w_mm, h_mm = float(p["width_mm"]), float(p["height_mm"])
    W, H = _px(w_mm), _px(h_mm)
    m = MARGIN_MM * PX_PER_MM
    fields = label_fields(doc, device, base_url, project=project)
    big = fields["code"] or str(device.get("id") or "")
    inner_w, inner_h = W - 2 * m, H - 2 * m
    gap = 1.0 * PX_PER_MM
    parts = []
    if W >= H * 1.5:
        # landscape: QR on the left, full inner height; text in the remaining width
        qr = inner_h
        parts.append(_qr_group(fields["url"], m, m, qr))
        parts.append(_text_block(m + qr + gap, m, inner_w - qr - gap, inner_h, fields, big))
    else:
        # portrait / square (0.5x1, 1x1, 1x2, continuous): QR on top, text below
        probe_code = _fit_font(big, inner_w, _MONO_EM, min(inner_h * 0.2, 120.0), 10.0)
        text_h = probe_code * (1 + 0.62 + 0.46) + 3 * max(2.0, inner_h * 0.02)
        text_h = min(text_h, inner_h * 0.5)
        qr = min(inner_w, inner_h - text_h - gap)
        parts.append(_qr_group(fields["url"], m + (inner_w - qr) / 2, m, qr))
        parts.append(_text_block(m, m + qr + gap, inner_w, inner_h - qr - gap, fields, big))
    if unit == "px":
        dims = f'width="{W}" height="{H}"'
    else:
        dims = f'width="{_mm(w_mm)}mm" height="{_mm(h_mm)}mm"'
    title = fields["name"] + (f" ({fields['code']})" if fields["code"] else "")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" {dims} viewBox="0 0 {W} {H}" '
            f'data-device="{_esc(device.get("id"))}" data-preset="{_esc(preset)}" role="img" aria-label="{_esc(title)}">'
            f'<title>{_esc(title)}</title><rect width="{W}" height="{H}" fill="#fff"/>{"".join(parts)}</svg>')


def device_label_svg(doc: Doc, device: Dict[str, Any], preset: str = DEFAULT_PRESET, base_url: str = "", project: Optional[str] = None) -> str:
    """One label as SVG at true size (``width``/``height`` in mm, ``viewBox`` in 300 dpi units)."""
    if preset not in PRESETS:
        raise ValueError(f"unknown label preset '{preset}'")
    return _svg(doc, device, preset, base_url, project, "mm")


# ------------------------------------------------------------------ sheet, CSV, ZIP


def label_sheet_html(doc: Doc, devices: Sequence[Dict[str, Any]], preset: str = DEFAULT_PRESET, base_url: str = "", title: str = "", project: Optional[str] = None) -> str:
    """Self-contained printable sheet: every label as an inline SVG at true size. Print at 100 %."""
    if preset not in PRESETS:
        raise ValueError(f"unknown label preset '{preset}'")
    p = PRESETS[preset]
    org = (doc.get("meta") or {}).get("org") or ""
    title = title or " · ".join(s for s in ("Device labels", org) if s)
    head = f"Print at 100 % — {p['label']} ({preset_size_text(p)})"
    labels = [f'<div class="label" data-device="{_esc(d.get("id"))}">{_svg(doc, d, preset, base_url, project, "mm")}</div>' for d in devices]
    css = """
@page { margin: 10mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #fff; color: #000; font-family: system-ui, sans-serif; }
body { padding: 8mm; }
h1 { font-size: 11pt; font-weight: 600; margin: 0 0 2mm; }
p.hint { font-size: 9pt; color: #444; margin: 0 0 5mm; }
.sheet { display: flex; flex-wrap: wrap; gap: 4mm; align-items: flex-start; }
.label { display: inline-block; line-height: 0; border: 0.15mm solid #999; break-inside: avoid; page-break-inside: avoid; }
.label svg { display: block; }
.empty { font-size: 11pt; color: #444; }
@media print { body { padding: 0; } .label { border-color: #bbb; } }
"""
    body = ('<div class="sheet">' + "".join(labels) + "</div>") if labels else '<p class="empty">No devices match.</p>'
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{_esc(title)}</title>'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"><style>{css}</style></head>'
        f'<body data-labels="{len(labels)}" data-preset="{_esc(preset)}"><h1>{_esc(head)}</h1>'
        f'<p class="hint">Import the SVG/PNG files into Brady Express Labels or Brady Workstation, or print this page at 100 % scale (no “fit to page”).</p>'
        f'{body}</body></html>'
    )


CSV_COLUMNS = ("device_id", "short_code", "name", "room", "location", "url", "kind", "manufacturer", "model")


def labels_csv(doc: Doc, devices: Sequence[Dict[str, Any]], base_url: str = "", project: Optional[str] = None) -> str:
    """RFC 4180 CSV (CRLF) for Brady Workstation data import."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for d in devices:
        f = label_fields(doc, d, base_url, project=project)
        w.writerow([str(d.get("id") or ""), f["code"], f["name"], f["room"], f["location"], f["url"], f["kind"], f["manufacturer"], f["model"]])
    return buf.getvalue()


def _render_pngs(svgs: Dict[str, str], preset: str) -> Dict[str, bytes]:
    """PNG per device through fathom.export's headless Chrome; {} when Chrome is unavailable or fails."""
    try:
        from . import export
    except ImportError:
        return {}
    find_chrome = getattr(export, "find_chrome", None)
    html_to_png = getattr(export, "html_to_png", None)
    run_chrome = getattr(export, "_run_chrome", None)
    if not callable(find_chrome) or not callable(html_to_png) or not find_chrome():
        return {}
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    p = PRESETS[preset]
    W, H = _px(float(p["width_mm"])), _px(float(p["height_mm"]))
    out: Dict[str, bytes] = {}
    with tempfile.TemporaryDirectory(prefix="fathom-labels-") as tmp:
        root = Path(tmp)

        def one(item: Any) -> None:
            n, (dev_id, svg) = item
            page = root / f"{dev_id}.html"
            png = root / f"{dev_id}.png"
            page.write_text(f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;padding:0;background:#fff}}svg{{display:block}}</style></head><body>{svg}</body></html>', encoding="utf-8")
            try:
                if callable(run_chrome):
                    # Concurrent headless Chromes must not share a profile (the second one waits on the first's lock).
                    run_chrome([f"--user-data-dir={root / ('profile-%d' % (n % 4))}", f"--screenshot={png}", f"--window-size={W},{H}",
                                "--virtual-time-budget=4000", page.resolve().as_uri()], timeout=60)
                else:
                    html_to_png(page, png, W, H)
                if png.is_file() and png.stat().st_size:
                    out[dev_id] = png.read_bytes()
            except (SystemExit, Exception):
                return

        if callable(run_chrome):
            # one worker per profile directory; items are dealt round-robin so a profile is never shared concurrently
            items = list(enumerate(svgs.items()))
            with ThreadPoolExecutor(max_workers=4) as pool:
                for lane in range(4):
                    pool.submit(lambda chunk: [one(it) for it in chunk], items[lane::4])
        else:
            for it in enumerate(svgs.items()):
                one(it)
    return out


def labels_zip(doc: Doc, devices: Sequence[Dict[str, Any]], preset: str = DEFAULT_PRESET, base_url: str = "", project: Optional[str] = None, png: bool = True) -> bytes:
    """``labels.csv``, ``<device_id>.svg`` per device, ``<device_id>.png`` per device when Chrome renders, ``README.txt``."""
    if preset not in PRESETS:
        raise ValueError(f"unknown label preset '{preset}'")
    p = PRESETS[preset]
    svgs = {str(d.get("id")): _svg(doc, d, preset, base_url, project, "mm") for d in devices}
    pngs = _render_pngs({k: _svg(doc, d, preset, base_url, project, "px") for k, d in ((str(d.get("id")), d) for d in devices)}, preset) if png and devices else {}
    readme = (
        f"Fathom device labels\r\n\r\nPreset: {preset} — {p['label']} ({preset_size_text(p)})\r\n"
        f"Parts: {', '.join(p['parts'])}\r\nLabels: {len(svgs)}\r\n\r\n"
        "Import the SVG (or PNG, 300 dpi) files into Brady Express Labels or Brady Workstation; print at 100 % scale.\r\n"
        "labels.csv holds the same text per device for Brady Workstation data import.\r\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", readme)
        zf.writestr("labels.csv", labels_csv(doc, devices, base_url, project=project))
        for dev_id, svg in svgs.items():
            zf.writestr(f"{dev_id}.svg", svg)
        for dev_id, data in pngs.items():
            zf.writestr(f"{dev_id}.png", data)
    return buf.getvalue()


__all__ = ["PRESETS", "DEFAULT_PRESET", "CSV_COLUMNS", "presets", "preset_size_text", "label_fields", "select_devices",
           "device_label_svg", "label_sheet_html", "labels_csv", "labels_zip"]
