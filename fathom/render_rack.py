"""Public rack page: header, totals, front + rear elevation, devices, accessories, notes and QR.

``rack_page_html`` serves both the viewer route ``/p/<n>/rk/<rack>`` (``link_style="viewer"``) and the
build file ``racks/<rack>.html`` (``link_style="build"``). It reads the document only; newer
``fathom.racks`` features (``rack_totals``, ``ru_label``, ``ITEM_TYPES``, ``rack_items``, the
``images``/``base_url`` keywords of ``rack_svg``) are used when present.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .render_html import _editor_link, _find, _model_line, _page, _q, _title
from .render_svg import esc

FORM_FACTORS: Dict[str, str] = {
    "cabinet": "Cabinet", "open_frame": "Open frame", "two_post": "2-post", "four_post": "4-post",
    "wall_mount": "Wall mount", "road_case": "Road case",
}

# Fallback for ``racks.ITEM_TYPES`` (contract section B), used until the engine provides it.
_ITEM_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "blank": {"label": "Blank panel", "height": 1, "face": "front", "depth": "half"},
    "vent": {"label": "Vent panel", "height": 1, "face": "front", "depth": "half"},
    "shelf": {"label": "Shelf", "height": 1, "face": "front", "depth": "full", "slots": 2},
    "drawer": {"label": "Drawer", "height": 2, "face": "front", "depth": "full"},
    "cable_manager": {"label": "Cable manager", "height": 1, "face": "front", "depth": "half"},
    "brush": {"label": "Brush panel", "height": 1, "face": "front", "depth": "half"},
    "lacing_bar": {"label": "Lacing bar", "height": 1, "face": "rear", "depth": "half"},
    "other": {"label": "Accessory", "height": 1, "face": "front", "depth": "half"},
}

RACK_CSS = """
.rv-head{display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start;margin-top:14px}
.rv-head dl.kv{flex:1 1 200px;max-width:560px;grid-template-columns:110px minmax(0,1fr)}
.qr img{display:block;width:100%;height:auto}
.rv-qr{width:150px}
.rv-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:4px 22px}
@media (min-width:1100px){.rv-grid{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
.rv-svg svg{display:block;max-width:100%;height:auto;margin:0 auto}
.rv-faces{display:flex;gap:10px;align-items:flex-start}
.rv-faces>div{flex:1 1 0;min-width:0}
@media (max-width:699px){.rv-faces{flex-direction:column}.rv-faces>div{width:100%}.rv-qr{width:96px}.rv-head{gap:12px}.rv-head dl.kv{grid-template-columns:92px minmax(0,1fr)}}
.rv-stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.rv-stat{border:1px solid var(--border);border-radius:10px;background:var(--panel);padding:9px 12px}
.rv-stat .k{font-size:10.5px;letter-spacing:.7px;text-transform:uppercase;color:var(--muted);font-weight:600}
.rv-stat .v{font-size:16px;font-weight:600;margin-top:2px}
.rv-stat .s{font-size:11.5px;color:var(--muted)}
.rv-stat.rv-over{border-color:var(--warn)}
.rv-stat.rv-over .v{color:var(--warn)}
.rv-bar{height:5px;border-radius:3px;background:rgba(255,255,255,.08);margin-top:6px;overflow:hidden}
.rv-bar i{display:block;height:100%;background:var(--accent)}
.rv-over .rv-bar i{background:var(--warn)}
.rv-warn{color:var(--warn);margin:8px 0 0}
.rv-notes p{margin:0 0 8px}
.rv-notes pre{white-space:pre-wrap;background:#0f1525;border:1px solid var(--border);border-radius:8px;padding:8px}
.rv-notes table{border-collapse:collapse}
.rv-notes td,.rv-notes th{border:1px solid var(--border);padding:4px 8px}
.rv-sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:middle;border:1px solid rgba(255,255,255,.25)}
td.rv-u{white-space:nowrap;font-variant-numeric:tabular-nums}
@media print{
  @page{margin:10mm}
  html,body{font-size:10px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .wrap{max-width:none;padding:0}
  h1{font-size:16px;margin:0 0 2px}
  h2{margin:8px 0 4px}
  .rv-head{margin-top:4px}
  .rv-head dl.kv{max-width:none;grid-template-columns:max-content minmax(0,1fr) max-content minmax(0,1fr);gap:1px 10px}
  .rv-grid{display:block}
  .rv-faces{flex-direction:row}
  .rv-svg svg{max-height:110mm;width:auto}
  .rv-lists{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0 16px}
  .rv-qr{width:80px}
  .rv-qr .sub{display:none}
  .rv-stats{grid-template-columns:repeat(4,minmax(0,1fr))}
  .rv-stat{padding:3px 8px;border-color:#ccc;background:#fff}
  .rv-stat .v{font-size:11px}
  .rv-bar{display:none}
  table.t{font-size:9.5px}
  table.t td,table.t th{padding:2px 5px}
  .rv-grid section{break-inside:avoid;page-break-inside:avoid}
}
"""


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return ""
    r = round(float(v), 1)
    return str(int(r)) if r == int(r) else f"{r:g}"


def _racks_mod() -> Any:
    from . import racks

    return racks


def _strip_prolog(svg: str) -> str:
    """Inline SVG cannot carry an XML declaration or doctype."""
    return re.sub(r"^\s*(?:<\?xml[^>]*\?>\s*)?(?:<!DOCTYPE[^>]*>\s*)?", "", svg or "")


class _RackLinks:
    """Hrefs from a rack page: viewer tree ``{base}p/<n>/…``, share mirror ``{base}s/<token>/…`` or build ``racks/<rack>.html``.

    ``/p/`` routes need a viewer login and ignore ``?share=``, so share pages link through the mirror only.
    """

    def __init__(self, style: str, base: str, project: str, share: str) -> None:
        self.build = style == "build"
        self.base = base or ""
        self.project = project
        self.share = share if not self.build else ""

    def _p(self, rest: str) -> str:
        if self.share:
            return f"{self.base}s/{_q(self.share)}/{rest}"
        return f"{self.base}p/{_q(self.project)}/{rest}"

    def device(self, dev: str) -> str:
        return f"../devices/{_q(dev)}.html" if self.build else self._p(f"d/{_q(dev)}")

    def room(self, room: str) -> str:
        return f"../rooms/{_q(room)}/index.html" if self.build else self._p(f"r/{_q(room)}")

    def rooms(self) -> str:
        return "../rooms/index.html" if self.build else self._p("rooms")

    def page(self, slug: str) -> Optional[str]:
        return None if self.build else self._p(f"sop/{_q(slug)}")


def _abs_base(doc: Dict[str, Any], base: str) -> str:
    """Absolute public root for an inline QR (builds, share pages): ``base`` when absolute, else ``settings.public_url`` / ``FATHOM_PUBLIC_URL``."""
    if re.match(r"^https?://", base or "", re.I):
        return base.rstrip("/")
    s = (doc.get("settings") or {}).get("public_url") or os.environ.get("FATHOM_PUBLIC_URL") or ""
    s = str(s).strip()
    return s.rstrip("/") if re.match(r"^https?://", s, re.I) else ""


def _qr_html(doc: Dict[str, Any], project: str, rack_id: str, rack_name: str, base: str, share: str, build: bool) -> str:
    alt = f"QR code for rack {rack_name}"
    if not build and not share:
        src = f"{base}api/v2/projects/{_q(project)}/qr/rack/{_q(rack_id)}.svg"
        inner = f'<img src="{esc(src)}" alt="{esc(alt)}" width="150" height="150">'
    else:
        # The QR API needs the viewer role, so share pages (anonymous visitors) get the QR inline, like builds.
        root = _abs_base(doc, base)
        if not root:
            return ""
        url = f"{root}/s/{_q(share)}/rk/{_q(rack_id)}" if share else f"{root}/p/{_q(project)}/rk/{_q(rack_id)}"
        try:
            from .qr import svg as qr_svg

            inner = qr_svg(url, "M", scale=4)
        except Exception:
            return ""
        inner = f'<div role="img" aria-label="{esc(alt)}">{inner}</div>'
    return (f'<div class="rv-qr"><div class="qr">{inner}</div>'
            '<div class="sub" style="font-size:11px;margin-top:4px">Scan to open this rack</div></div>')


def _item_table(R: Any) -> Dict[str, Dict[str, Any]]:
    table = {k: dict(v) for k, v in _ITEM_DEFAULTS.items()}
    types = getattr(R, "ITEM_TYPES", None)
    entries: List[Any] = list(types.values()) if isinstance(types, dict) else list(types or [])
    for t in entries:
        if isinstance(t, dict) and t.get("type"):
            table[str(t["type"])] = dict(table.get(str(t["type"])) or {}, **t)
    return table


def _items(R: Any, doc: Dict[str, Any], rack: Dict[str, Any], types: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    raw: Any = None
    fn = getattr(R, "rack_items", None)
    if callable(fn):
        try:
            raw = fn(doc, rack["id"])
        except Exception:
            raw = None
    if not isinstance(raw, list):
        raw = rack.get("items") if isinstance(rack.get("items"), list) else []
    out = []
    for it in raw:
        if not isinstance(it, dict) or not it.get("id"):
            continue
        # rack_items entries are {id: "item:<id>", item: <raw id>, ...}; raw rack.items carry the id itself.
        ref = it.get("item")
        raw_id = ref.get("id") if isinstance(ref, dict) else ref if isinstance(ref, str) and ref else str(it["id"])
        if raw_id.startswith("item:") and not isinstance(ref, (str, dict)):
            raw_id = raw_id[5:]
        spec = types.get(str(it.get("type") or "")) or types["other"]
        u = it.get("u")
        h = it.get("height")
        out.append(dict(it, id=raw_id, u=u if isinstance(u, int) and not isinstance(u, bool) else None,
                        height=h if isinstance(h, int) and not isinstance(h, bool) and h >= 1 else int(spec.get("height") or 1),
                        face=it.get("face") if it.get("face") in ("front", "rear") else spec.get("face") or "front",
                        type_label=str(it.get("type_label") or spec.get("label") or it.get("type") or "Accessory"),
                        color=it.get("color") or spec.get("color") or ""))
    return out


def _totals(R: Any, doc: Dict[str, Any], rack: Dict[str, Any]) -> Dict[str, Any]:
    fn = getattr(R, "rack_totals", None)
    if callable(fn):
        try:
            t = fn(doc, rack["id"])
            if isinstance(t, dict):
                return dict(t, full=True)
        except KeyError:
            raise
        except Exception:
            pass
    occ = R.rack_occupancy(doc, rack["id"])
    used = sum(1 for s in occ["slots"] if any(s[f][side] for f in ("front", "rear") for side in ("left", "right")))
    units = int(rack.get("units") or 0)
    return {"units": units, "used_u": used, "free_u": max(0, units - used), "devices": len(occ["devices"]),
            "items": len(rack.get("items") or []) if isinstance(rack.get("items"), list) else 0, "full": False}


def _collisions(R: Any, doc: Dict[str, Any], rack_id: str) -> List[Dict[str, Any]]:
    fn = getattr(R, "collisions", None)
    try:
        if callable(fn):
            return list(fn(doc, rack_id) or [])
        return list(R.rack_occupancy(doc, rack_id).get("collisions") or [])
    except Exception:
        return []


def _face_svg(R: Any, doc: Dict[str, Any], rack_id: str, face: str, base: str, build: bool) -> str:
    attempts: List[Dict[str, Any]] = []
    if not build:
        attempts.append({"images": True, "base_url": base})
    attempts += [{"images": True}, {}]
    for kw in attempts:
        try:
            return _strip_prolog(R.rack_svg(doc, rack_id, face=face, **kw))
        except TypeError:
            continue
    return ""


def _elevation(R: Any, doc: Dict[str, Any], rack_id: str, base: str, build: bool) -> str:
    """Front and rear as one SVG each, so they sit side by side from md up and stack (each full width) at sm."""
    faces = "".join(f'<div class="rv-svg" data-face="{f}">{_face_svg(R, doc, rack_id, f, base, build)}</div>' for f in ("front", "rear"))
    return f'<div class="rv-faces">{faces}</div>'


def _stat(key: str, value: str, sub: str = "", *, over: bool = False, frac: Optional[float] = None) -> str:
    bar = ""
    if frac is not None:
        bar = f'<div class="rv-bar" aria-hidden="true"><i style="width:{max(0.0, min(1.0, frac)) * 100:.0f}%"></i></div>'
    cls = "rv-stat rv-over" if over else "rv-stat"
    return (f'<div class="{cls}" data-stat="{esc(key)}"><div class="k">{esc(key)}</div><div class="v">{esc(value)}</div>'
            + (f'<div class="s">{esc(sub)}</div>' if sub else "") + bar + "</div>")


def _totals_html(t: Dict[str, Any]) -> str:
    units = int(t.get("units") or 0)
    used = int(t.get("used_u") or 0)
    cells = [_stat("Space", f"{used} U used", f"{int(t.get('free_u') or 0)} U free of {units} U",
                   frac=(used / units) if units else None)]
    if t.get("full"):
        w, wmax = _num(t.get("weight_kg")), _num(t.get("max_load_kg"))
        over_w = w is not None and wmax is not None and w > wmax
        cells.append(_stat("Weight", f"{_fmt(w or 0)} kg", (f"of {_fmt(wmax)} kg max load" + (" · over" if over_w else "")) if wmax is not None else "no max load set",
                           over=over_w, frac=((w or 0) / wmax) if wmax else None))
        p, pmax = _num(t.get("power_w")), _num(t.get("power_limit_w"))
        over_p = p is not None and pmax is not None and p > pmax
        cells.append(_stat("Power", f"{_fmt(p or 0)} W", (f"of {_fmt(pmax)} W circuit limit" + (" · over" if over_p else "")) if pmax is not None else "no circuit limit set",
                           over=over_p, frac=((p or 0) / pmax) if pmax else None))
    cells.append(_stat("Contents", f"{int(t.get('devices') or 0)} devices", f"{int(t.get('items') or 0)} accessories"))
    return f'<div class="rv-stats">{"".join(cells)}</div>'


def _u_text(label: Callable[[int], str], u: Optional[int], height: int) -> str:
    """``u`` is the physical bottom RU for every numbering; a span reads top RU label – bottom RU label, as on the page."""
    if u is None:
        return "—"
    if height <= 1:
        return f"U{label(u)}"
    return f"U{label(u + height - 1)}–{label(u)}"


def _notes_html(text: str, doc: Dict[str, Any], L: _RackLinks, pages_ok: Callable[[str], bool], device_ok: Callable[[str], bool]) -> str:
    try:
        from . import markdown as md
    except Exception:  # pragma: no cover - markdown module missing
        return f'<p style="white-space:pre-wrap">{esc(text)}</p>'

    def resolver(kind: str, ref: str) -> Optional[Dict[str, Any]]:
        if kind == "device":
            d = _find(doc.get("devices"), ref)
            if d is None:
                return None
            return {"href": L.device(ref) if device_ok(ref) else "", "label": str(d.get("name") or ref)}
        if kind == "room":
            r = _find(doc.get("rooms"), ref)
            return {"href": L.room(ref), "label": str(r.get("name") or ref)} if r else None
        if kind == "page" and pages_ok(ref):
            href = L.page(ref)
            return {"href": href, "label": ref} if href else None
        return None

    try:
        return str(md.render(text, resolver)["html"])
    except Exception:
        return f'<p style="white-space:pre-wrap">{esc(text)}</p>'


def rack_page_html(doc: Dict[str, Any], project: str, rack_id: str, *, base: str, share: str = "", link_style: str = "viewer") -> str:
    """Complete HTML page for one rack. ``base`` is the app root as seen from the page (viewer mode); unknown rack → ``KeyError``."""
    rack = _find(doc.get("racks"), rack_id)
    if rack is None:
        raise KeyError(rack_id)
    R = _racks_mod()
    build = link_style == "build"
    base = base or ""
    share = str(share or "")
    L = _RackLinks(link_style, base, project, share)
    meta = doc.get("meta") or {}
    name = str(rack.get("name") or rack_id)
    room = _find(doc.get("rooms"), str(rack.get("room") or ""))
    loc = _find(doc.get("locations"), str(rack.get("location") or ""))
    units = int(rack.get("units") or 0)
    width_in = rack.get("width_in") if rack.get("width_in") in (10, 19, 21, 23) else 19
    form = FORM_FACTORS.get(str(rack.get("form_factor") or ""), FORM_FACTORS["cabinet"])
    ru_label = getattr(R, "ru_label", None)

    start_u = rack.get("start_u") if isinstance(rack.get("start_u"), int) and not isinstance(rack.get("start_u"), bool) and rack["start_u"] >= 0 else 1

    def label(u: int) -> str:
        if callable(ru_label):
            try:
                return str(ru_label(rack, u))
            except Exception:
                pass
        return str(units - u + start_u if rack.get("numbering") == "top_down" else u - 1 + start_u)

    out: List[str] = []
    room_name = str((room or {}).get("name") or (room or {}).get("id") or "")
    eyebrow = " · ".join(b for b in (str(meta.get("org") or ""), room_name or "Racks") if b)
    out.append(f'<div class="eyebrow">{esc(eyebrow)}</div><h1>{esc(name)}</h1>')
    out.append(f'<div class="sub">{esc(" · ".join([f"{units}U", str(width_in) + chr(0x2033), form]))}</div>')
    out.append('<nav class="nav no-print" aria-label="Viewer">')
    if room:
        out.append(f'<a href="{esc(L.room(str(room["id"])))}">{esc(room_name)} map</a>')
    out.append(f'<a href="{esc(L.rooms())}">All rooms</a>')
    if not build and not share:
        out.append(f'<a href="{esc(_editor_link(base, project, str((room or {}).get("id") or ""), "racks/" + _q(rack_id)))}">Open in editor</a>')
    out.append("</nav>")

    kv: List[Tuple[str, str]] = []
    if room:
        kv.append(("Room", f'<a href="{esc(L.room(str(room["id"])))}">{esc(room_name)}</a>'))
    if loc:
        kv.append(("Location", esc(loc.get("name") or loc["id"])))
    elif rack.get("location"):
        kv.append(("Location", esc(rack["location"])))
    if rack.get("row"):
        kv.append(("Row", esc(rack["row"])))
    numbering = "top down" if rack.get("numbering") == "top_down" else "bottom up"
    kv.append(("Units", esc(f"{units}U · numbered {numbering}" + (f" from {start_u}" if start_u != 1 else ""))))
    kv.append(("Width", esc(f"{width_in}{chr(0x2033)}")))
    kv.append(("Form factor", esc(form)))
    if _num(rack.get("depth_mm")):
        kv.append(("Depth", esc(f"{_fmt(_num(rack.get('depth_mm')))} mm")))
    if _num(rack.get("weight_kg")) is not None:
        kv.append(("Empty weight", esc(f"{_fmt(_num(rack.get('weight_kg')))} kg")))
    body_kv = "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in kv)
    out.append(f'<div class="rv-head"><dl class="kv">{body_kv}</dl>{_qr_html(doc, project, rack_id, name, base, share, build)}</div>')

    totals = _totals(R, doc, rack)
    out.append('<section aria-labelledby="rv-h-totals"><h2 id="rv-h-totals">Totals</h2>' + _totals_html(totals))
    coll = _collisions(R, doc, rack_id)
    if coll:
        out.append(f'<p class="rv-warn" role="note">{len(coll)} overlap{"s" if len(coll) != 1 else ""} in this rack: check the elevation.</p>')
    out.append("</section>")

    def top_key(u: Optional[int], h: int) -> float:
        if u is None:
            return float("inf")
        return float(-(u + h - 1))

    devs = {d["id"]: d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id")}
    paged = {i for i, d in devs.items() if not d.get("auto")}
    items = _items(R, doc, rack, _item_table(R))
    item_by_id = {str(it["id"]): it for it in items}
    placed = [p for p in R.rack_devices(doc, rack_id) if p.get("device") in devs]
    face_rank = {"front": 0, "rear": 1}
    side_rank = {"full": 0, "left": 0, "right": 1}
    placed.sort(key=lambda p: (top_key(p.get("u"), int(p.get("height") or 1)), face_rank.get(str(p.get("face")), 2),
                               side_rank.get(str(p.get("side")), 2), int((p.get("slot") or 0) if isinstance(p.get("slot"), int) else 0),
                               str(devs[p["device"]].get("name") or p["device"]).lower()))
    rows: List[str] = []
    for p in placed:
        d = devs[p["device"]]
        h = int(p.get("height") or 1)
        title = esc(_title(d))
        cell = f'<a href="{esc(L.device(d["id"]))}">{title}</a>' if d["id"] in paged else title
        if d.get("status") == "planned":
            cell += '<span class="planned">planned</span>'
        model = _model_line(d)
        if model:
            cell += f'<div class="sub">{esc(model)}</div>'
        shelf = p.get("shelf")
        if shelf:
            it = item_by_id.get(str(shelf)) or {}
            slot = p.get("slot")
            side = f"Shelf {it.get('label') or it.get('type_label') or shelf}" + (f" · cell {slot + 1}" if isinstance(slot, int) else "")
        else:
            side = {"left": "left half", "right": "right half"}.get(str(p.get("side")), "full")
            if p.get("depth") == "half":
                side += " · half depth"
        rows.append(f'<tr data-device="{esc(d["id"])}"><td class="rv-u">{esc(_u_text(label, p.get("u"), h))}</td><td>{cell}</td>'
                    f'<td>{esc(p.get("face") or "front")}</td><td>{esc(side)}</td></tr>')
    if rows:
        dev_html = ('<div class="scroll"><table class="t"><thead><tr><th scope="col">U</th><th scope="col">Device</th><th scope="col">Face</th>'
                    f'<th scope="col">Position</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    else:
        dev_html = '<p class="sub">No devices in this rack.</p>'

    items.sort(key=lambda it: (top_key(it.get("u"), int(it.get("height") or 1)), face_rank.get(str(it.get("face")), 2), str(it["id"])))
    irows = []
    for it in items:
        sw = f'<span class="rv-sw" style="background:{esc(it["color"])}"></span>' if re.match(r"^#[0-9a-fA-F]{6}$", str(it.get("color") or "")) else ""
        lab = esc(it.get("label") or "")
        if it.get("type") == "shelf":
            slots = it.get("slots") if isinstance(it.get("slots"), int) else 2
            lab = (lab + " · " if lab else "") + esc(f"{slots} cells")
        if it.get("notes"):
            lab += f'<div class="sub">{esc(it["notes"])}</div>'
        irows.append(f'<tr data-item="{esc(it["id"])}"><td>{sw}{esc(it["type_label"])}</td><td class="rv-u">{esc(_u_text(label, it.get("u"), int(it.get("height") or 1)))}</td>'
                     f'<td>{esc(it.get("face") or "front")}</td><td>{lab}</td></tr>')
    items_html = ""
    if irows:
        items_html = ('<section aria-labelledby="rv-h-items"><h2 id="rv-h-items">Accessories</h2><div class="scroll"><table class="t"><thead><tr><th scope="col">Type</th>'
                      f'<th scope="col">U</th><th scope="col">Face</th><th scope="col">Label</th></tr></thead><tbody>{"".join(irows)}</tbody></table></div></section>')

    notes_html = ""
    if str(rack.get("notes") or "").strip():
        published = {str(p.get("slug")) for p in doc.get("pages") or [] if isinstance(p, dict) and (p.get("status") or "published") == "published"}
        notes_html = ('<section aria-labelledby="rv-h-notes"><h2 id="rv-h-notes">Notes</h2><div class="rv-notes">'
                      + _notes_html(str(rack["notes"]), doc, L, lambda s: s in published, lambda i: i in paged) + "</div></section>")

    out.append('<div class="rv-grid">')
    out.append('<section aria-labelledby="rv-h-elev"><h2 id="rv-h-elev">Elevation · front and rear</h2>' + _elevation(R, doc, rack_id, base, build) + "</section>")
    out.append(f'<div class="rv-lists"><section aria-labelledby="rv-h-devs"><h2 id="rv-h-devs">Devices · top down</h2>{dev_html}</section>'
               f'<div>{items_html}{notes_html}</div></div>')
    out.append("</div>")
    return _page(f"{name} · {meta.get('org') or project}", "".join(out), base_url="" if build else base, sw=not build, extra_css=RACK_CSS)


__all__ = ["rack_page_html", "FORM_FACTORS", "RACK_CSS"]
