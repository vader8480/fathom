"""Cable tags (§4.8), cable schedule (§5.8.2) and the printable label sheet (FR-CAB-04)."""

from __future__ import annotations

import csv
import html
import io
import re
from typing import Any, Dict, List, Optional, Tuple

from .vocab import DISCIPLINES, MEDIA, discipline_letter, medium_discipline

Doc = Dict[str, Any]
Op = Dict[str, Any]

DEFAULT_PATTERN = "{D}-{n:03}"
_TOKEN_RE = re.compile(r"\{([A-Za-z]+)(?::([^}]*))?\}")
FT_PER_M = 1 / 0.3048

CABLE_COLUMNS: List[Tuple[str, str]] = [
    ("tag", "Tag"), ("from_room", "From room"), ("from_device", "From device"), ("from_port", "From port"),
    ("to_room", "To room"), ("to_device", "To device"), ("to_port", "To port"), ("medium", "Medium"), ("type", "Type"),
    ("length", "Length"), ("length_unit", "Unit"), ("length_est_m", "Est. m"), ("color", "Color"), ("channels", "Channels"), ("signal", "Signal"),
    ("status", "Status"), ("bundle", "Bundle"), ("note", "Note"), ("id", "Id"),
]


# --------------------------------------------------------------- helpers


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-") or "item"


def device_code(dev: Optional[Dict[str, Any]]) -> str:
    if not dev:
        return "X"
    if dev.get("code"):
        return str(dev["code"])
    return _slug(dev.get("id") or dev.get("name", "")).replace("-", "").upper()[:8] or "X"


def room_code(room: Optional[Dict[str, Any]]) -> str:
    if not room:
        return "X"
    if room.get("code"):
        return str(room["code"])
    return re.sub(r"[^A-Za-z]", "", _slug(room.get("id") or room.get("name", ""))).upper()[:4] or "X"


class _Index:
    def __init__(self, doc: Doc) -> None:
        self.devices = {d.get("id"): d for d in doc.get("devices") or [] if isinstance(d, dict)}
        self.rooms = {r.get("id"): r for r in doc.get("rooms") or [] if isinstance(r, dict)}
        self.bundles = {b.get("id"): b for b in doc.get("bundles") or [] if isinstance(b, dict)}

    def port(self, dev_id: str, port_id: str) -> Optional[Dict[str, Any]]:
        for p in (self.devices.get(dev_id) or {}).get("ports") or []:
            if p.get("id") == port_id:
                return p
        return None


def _fmt(value: Any, fmt: str) -> str:
    if fmt and isinstance(value, int):
        m = re.match(r"^0?(\d+)$", fmt)
        if m:
            return str(value).zfill(int(m.group(1)))
    return str(value)


def _token_values(cable: Dict[str, Any], doc: Doc, idx: Optional[_Index] = None) -> Dict[str, str]:
    idx = idx or _Index(doc)
    medium = cable.get("medium") or "other"
    disc = medium_discipline(medium)
    fdev = idx.devices.get((cable.get("from") or {}).get("device"))
    tdev = idx.devices.get((cable.get("to") or {}).get("device"))
    short = (MEDIA.get(medium) or {}).get("short") or medium[:4]
    return {
        "D": discipline_letter(disc), "disc": disc, "DISC": disc.upper(), "M": str(short).upper(),
        "room": room_code(idx.rooms.get((fdev or {}).get("room"))), "from": device_code(fdev), "to": device_code(tdev),
    }


def _render(pattern: str, vals: Dict[str, str], n: Any) -> str:
    def rep(m: "re.Match[str]") -> str:
        name, fmt = m.group(1), m.group(2) or ""
        if name == "n":
            return _fmt(n, fmt) if isinstance(n, int) else str(n)
        return vals.get(name, m.group(0))

    return _TOKEN_RE.sub(rep, pattern)


def render_tag(pattern: str, cable: Dict[str, Any], doc: Doc, n: int) -> str:
    return _render(pattern or DEFAULT_PATTERN, _token_values(cable, doc), n)


def _pattern_regex(pattern: str, vals: Dict[str, str]) -> "re.Pattern[str]":
    out = []
    pos = 0
    for m in _TOKEN_RE.finditer(pattern):
        out.append(re.escape(pattern[pos:m.start()]))
        name = m.group(1)
        out.append(r"(\d+)" if name == "n" else re.escape(vals.get(name, m.group(0))))
        pos = m.end()
    out.append(re.escape(pattern[pos:]))
    return re.compile("^" + "".join(out) + "$")


def assign_tags_ops(doc: Doc, scope: str = "missing", pattern: Optional[str] = None) -> List[Op]:
    """Merge ops that give cables (and bundles) tags from the pattern (§4.8)."""
    pattern = pattern or (doc.get("settings") or {}).get("cable_tag_pattern") or DEFAULT_PATTERN
    if "{n" not in pattern:
        pattern = pattern + "-{n:03}"
    idx = _Index(doc)
    cables = [c for c in doc.get("cables") or [] if isinstance(c, dict) and not c.get("auto")]
    bundles = [b for b in doc.get("bundles") or [] if isinstance(b, dict)]
    items: List[Tuple[str, Dict[str, Any], Dict[str, str]]] = []
    for c in cables:
        items.append(("cables", c, _token_values(c, doc, idx)))
    for b in bundles:
        members = [c for c in cables if c.get("bundle") == b.get("id")]
        ref = dict(b)
        if members:
            ref.setdefault("from", members[0].get("from"))
            ref.setdefault("to", members[0].get("to"))
        ref.setdefault("medium", members[0].get("medium") if members else "other")
        items.append(("bundles", b, _token_values(ref, doc, idx)))
    existing = [str(e.get("tag")) for _, e, _ in items if e.get("tag")] if scope != "all" else []
    maxima: Dict[str, int] = {}
    regex_cache: Dict[str, "re.Pattern[str]"] = {}
    ops: List[Op] = []
    for coll, ent, vals in items:
        if scope != "all" and ent.get("tag"):
            continue
        key = _render(pattern, vals, "\x00")
        if key not in maxima:
            rx = regex_cache.setdefault(key, _pattern_regex(pattern, vals))
            best = 0
            for t in existing:
                m = rx.match(t)
                if m:
                    best = max(best, int(m.group(1)))
            maxima[key] = best
        maxima[key] += 1
        tag = _render(pattern, vals, maxima[key])
        if tag != ent.get("tag"):
            ops.append({"op": "merge", "coll": coll, "id": ent["id"], "value": {"tag": tag}})
    return ops


# -------------------------------------------------------------- schedule


def _state_doc(doc: Doc, state: str) -> Doc:
    from .merge import filter_state

    return filter_state(doc, state)


def _units(doc: Doc) -> str:
    return "ft" if (doc.get("settings") or {}).get("units") == "imperial" else "m"


def _len_display(length_m: Any, unit: str) -> Any:
    if not isinstance(length_m, (int, float)) or isinstance(length_m, bool):
        return ""
    v = length_m * FT_PER_M if unit == "ft" else float(length_m)
    return round(v, 2)


def _port_text(p: Optional[Dict[str, Any]], pid: str) -> str:
    if p is None:
        return pid or ""
    return str(p.get("label") or p.get("name") or pid)


def _length_estimates(doc: Doc) -> Dict[str, float]:
    """FR-PLAN-17: ``{cable id: estimated metres}`` from the floor-plan runs (``runs.estimates``); empty when unavailable."""
    try:
        from .runs import estimates

        return estimates(doc)
    except Exception:
        return {}


def cable_schedule(doc: Doc, room: str = "*", state: str = "all", discipline: str = "") -> Dict[str, Any]:
    d = _state_doc(doc, state)
    idx = _Index(d)
    unit = _units(doc)
    est = _length_estimates(d)
    rows: List[Dict[str, Any]] = []
    tag_seen: Dict[str, str] = {}
    problems: List[Dict[str, Any]] = []
    for c in d.get("cables") or []:
        if not isinstance(c, dict) or c.get("auto"):
            continue
        fr, to = c.get("from") or {}, c.get("to") or {}
        fdev, tdev = idx.devices.get(fr.get("device")), idx.devices.get(to.get("device"))
        froom, troom = (fdev or {}).get("room", ""), (tdev or {}).get("room", "")
        if room not in ("*", None) and room not in (froom, troom):
            continue
        medium = c.get("medium") or "other"
        disc = medium_discipline(medium)
        if discipline and disc != discipline:
            continue
        fp, tp = idx.port(fr.get("device"), fr.get("port", "")), idx.port(to.get("device"), to.get("port", ""))
        b = idx.bundles.get(c.get("bundle")) if c.get("bundle") else None
        row = {
            "tag": c.get("tag", ""),
            "from_room": (idx.rooms.get(froom) or {}).get("name", froom), "from_room_id": froom,
            "from_device": (fdev or {}).get("name", fr.get("device", "")), "from_device_id": fr.get("device", ""),
            "from_port": _port_text(fp, fr.get("port", "")), "from_port_id": fr.get("port", ""),
            "to_room": (idx.rooms.get(troom) or {}).get("name", troom), "to_room_id": troom,
            "to_device": (tdev or {}).get("name", to.get("device", "")), "to_device_id": to.get("device", ""),
            "to_port": _port_text(tp, to.get("port", "")), "to_port_id": to.get("port", ""),
            "medium": medium, "medium_label": (MEDIA.get(medium) or {}).get("label", medium), "discipline": disc,
            "type": c.get("type", ""), "length": _len_display(c.get("length_m"), unit),
            "length_unit": unit if isinstance(c.get("length_m"), (int, float)) else "", "length_m": c.get("length_m"),
            "length_est_m": est.get(str(c.get("id"))),
            "color": c.get("color", ""), "channels": c.get("channels", ""), "signal": c.get("signal", ""),
            "status": c.get("status", "installed"), "bundle": (b or {}).get("tag") or c.get("bundle", ""),
            "bundle_id": c.get("bundle", ""), "note": c.get("note", ""), "id": c.get("id", ""),
        }
        rows.append(row)
        t = c.get("tag")
        if t:
            if t in tag_seen:
                problems.append({"level": "warning", "code": "tag_duplicate", "ref": f"cables/{c.get('id')}", "path": f"cables/{c.get('id')}/tag", "message": f"tag {t} is also used by {tag_seen[t]}"})
            else:
                tag_seen[t] = str(c.get("id"))
    bundles = []
    for b in d.get("bundles") or []:
        members = [r["id"] for r in rows if r["bundle_id"] == b.get("id")]
        if members:
            bundles.append({"id": b.get("id"), "tag": b.get("tag", ""), "kind": b.get("kind", "link"), "medium": b.get("medium", ""), "label": b.get("label", ""), "members": members, "count": len(members)})
    return {
        "kind": "cables", "columns": [{"key": k, "label": lab} for k, lab in CABLE_COLUMNS], "rows": rows,
        "problems": problems, "bundles": bundles, "totals": {"cables": len(rows), "length_m": round(sum(r["length_m"] for r in rows if isinstance(r["length_m"], (int, float))), 2)},
    }


def to_csv(schedule: Dict[str, Any]) -> str:
    """CSV of a ``{"columns", "rows"}`` schedule: header = column labels, ``\\r\\n`` line ends."""
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = schedule.get("columns") or []
    w.writerow([c["label"] for c in cols])
    for r in schedule.get("rows") or []:
        w.writerow(["" if r.get(c["key"]) is None else r.get(c["key"]) for c in cols])
    return buf.getvalue()


# ------------------------------------------------------------ label sheet

_PAGES = {"letter": (8.5, 11.0), "a4": (8.27, 11.69)}


def label_sheet_html(doc: Doc, *, room: str = "*", layout: Optional[Dict[str, Any]] = None, qr: bool = False, base_url: str = "") -> str:
    """Printable sheet: two labels per tagged cable (end A, end B)."""
    lay = {"cols": 3, "rows": 10, "width_in": 2.625, "height_in": 1.0, "page": "letter"}
    lay.update((doc.get("settings") or {}).get("labels") or {})
    lay.update(layout or {})
    cols, rows_n = max(1, int(lay["cols"])), max(1, int(lay["rows"]))
    w_in, h_in = float(lay["width_in"]), float(lay["height_in"])
    page = str(lay.get("page") or "letter").lower()
    pw, ph = _PAGES.get(page, _PAGES["letter"])
    gap_x = max(0.0, (pw - cols * w_in) / (cols + 1)) if cols > 1 else 0.0
    margin_x = max(0.0, (pw - cols * w_in - (cols - 1) * gap_x) / 2)
    margin_y = max(0.0, (ph - rows_n * h_in) / 2)
    idx = _Index(doc)
    sched = cable_schedule(doc, room=room, state="everything")
    labels: List[str] = []
    project = (doc.get("meta") or {}).get("slug", "")
    for r in sched["rows"]:
        if not r["tag"]:
            continue
        fdev, tdev = idx.devices.get(r["from_device_id"]), idx.devices.get(r["to_device_id"])
        fp = r["from_port"].upper()
        tp = r["to_port"].upper()
        line2 = f"{device_code(fdev)} {fp} → {device_code(tdev)} {tp}".strip()
        disc = r["discipline"]
        color = (DISCIPLINES.get(disc) or DISCIPLINES["other"])["color"]
        for end, dev_id in (("A", r["from_device_id"]), ("B", r["to_device_id"])):
            qr_html = ""
            if qr and base_url:
                try:
                    from .export import device_url
                    from .qr import svg as qr_svg

                    qr_html = f'<div class="qr">{qr_svg(device_url(base_url, project or "project", dev_id), "M", scale=1, border=1)}</div>'
                except Exception:
                    qr_html = ""
            labels.append(
                f'<div class="label" data-cable="{html.escape(r["id"])}" data-end="{end}" style="border-left-color:{color}">'
                f'{qr_html}<div class="t">{html.escape(r["tag"].upper())}</div>'
                f'<div class="r">{html.escape(line2)}</div>'
                f'<div class="e">{end}</div></div>'
            )
    per_page = cols * rows_n
    pages = [labels[i:i + per_page] for i in range(0, len(labels), per_page)] or [[]]
    title = html.escape(f"Cable labels · {(doc.get('meta') or {}).get('org', '')}".strip(" ·"))
    css = f"""
@page {{ size: {page}; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; color: #000; background: #eee; }}
.page {{ width: {pw}in; height: {ph}in; padding: {margin_y:.4f}in {margin_x:.4f}in; background: #fff; margin: 0 auto 16px;
  display: grid; grid-template-columns: repeat({cols}, {w_in}in); grid-auto-rows: {h_in}in; column-gap: {gap_x:.4f}in; page-break-after: always; break-after: page; }}
.label {{ position: relative; overflow: hidden; padding: 0.06in 0.1in 0.06in 0.14in; border-left: 0.06in solid #999; text-transform: uppercase; outline: 1px dashed #ddd; }}
.label .t {{ font-weight: 700; font-size: 16pt; line-height: 1.05; letter-spacing: 0.02em; }}
.label .r {{ font-size: 9pt; line-height: 1.15; margin-top: 0.03in; }}
.label .e {{ position: absolute; right: 0.1in; top: 0.06in; font-weight: 700; font-size: 14pt; }}
.label .qr {{ position: absolute; right: 0.08in; bottom: 0.05in; width: 0.5in; height: 0.5in; }}
.label .qr svg {{ width: 100%; height: 100%; }}
.empty {{ padding: 1in; font-size: 14pt; }}
@media print {{ body {{ background: #fff; }} .page {{ margin: 0; }} .label {{ outline: none; }} }}
"""
    body = []
    for pg in pages:
        body.append('<section class="page">' + ("".join(pg) if pg else '<div class="empty">No tagged cables yet. Assign tags first.</div>') + "</section>")
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"><style>{css}</style></head>'
        f'<body data-labels="{len(labels)}">{"".join(body)}</body></html>'
    )


__all__ = ["assign_tags_ops", "render_tag", "cable_schedule", "label_sheet_html", "to_csv", "device_code", "room_code", "CABLE_COLUMNS", "DEFAULT_PATTERN"]
