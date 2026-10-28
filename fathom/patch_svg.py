"""Patch canvas as a standalone SVG (Phase 5 P5C, SPEC §6.9.10).

A static, server-side rendering of what ``static/js/patchview.js`` shows for one
room: a card per device (ports as rows, inputs left / outputs right / I/O below),
one cubic wire per cable, ghost cards for cross-room ends, a title block and a
discipline legend. Geometry comes from :data:`GEOM`, which mirrors
``patchview-core.js`` ``GEOM`` field by field (``tests/test_patch_export.py``
compares the two), so the SVG lines up with the live canvas. No fonts are
embedded and there is no script; the file opens anywhere.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Sequence, Set

from .render_svg import esc, rgba

Doc = Dict[str, Any]

#: Must equal ``GEOM`` in ``fathom/static/js/patchview-core.js`` (card width, header, row pitch, padding, dot radius).
GEOM: Dict[str, Any] = {"cardW": 248, "headerH": 56, "rowH": 22, "sectionH": 18, "ioSectionH": 18, "pad": 8, "dotR": 5, "grid": 8, "maxRows": 12}

BG, PANEL, TEXT, MUTED, ACCENT = "#090d1a", "#111828", "#e6eaf4", "#8e97ab", "#8ea2ff"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
MARGIN, TITLE_H, LEGEND_ROW_H, COL_GAP, ROW_GAP = 40, 64, 26, 96, 24
FALLBACK_MEDIUM = {"label": "Other", "color": "#9aa3b5", "dash": "", "width": 1.2, "discipline": "other"}
FALLBACK_DISC = {"label": "Other", "color": "#9aa3b5", "letter": "X"}


# ------------------------------------------------------------------ vocab


def _vocab(vocab: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if vocab and vocab.get("media") and vocab.get("disciplines"):
        return vocab
    from .vocab import DISCIPLINES, KINDS, MEDIA

    return {"kinds": KINDS, "media": MEDIA, "disciplines": DISCIPLINES}


def _medium(medium: Any, voc: Dict[str, Any]) -> Dict[str, Any]:
    media = voc.get("media") or {}
    return media.get(medium) or media.get("other") or FALLBACK_MEDIUM


def _device_disc(dev: Dict[str, Any], voc: Dict[str, Any]) -> str:
    if dev.get("discipline"):
        return str(dev["discipline"])
    k = (voc.get("kinds") or {}).get(dev.get("kind"))
    return str((k or {}).get("discipline") or "other")


def _disc_info(key: str, voc: Dict[str, Any]) -> Dict[str, Any]:
    d = voc.get("disciplines") or {}
    return d.get(key) or d.get("other") or FALLBACK_DISC


def _status(e: Dict[str, Any]) -> str:
    return str(e.get("status") or "installed")


def _state_ok(status: str, state: str) -> bool:
    if state == "everything":
        return True
    if state == "planned":
        return status in ("planned", "installed")
    if state == "as_built":
        return status == "installed"
    return status != "retired"


def _ports(dev: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [p for p in dev.get("ports") or [] if isinstance(p, dict) and p.get("id")]


def _f(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"


def _fit(text: Any, width: float, font_px: float) -> str:
    """Trim ``text`` to roughly ``width`` px (average glyph 0.55 em) with an ellipsis, like CSS text-overflow."""
    s = str(text if text is not None else "")
    n = max(1, int(width / (font_px * 0.55)))
    return s if len(s) <= n else s[: max(1, n - 1)].rstrip() + "\u2026"


# ------------------------------------------------------------ card layout (port of patchview-core.cardLayout)


def card_layout(dev: Dict[str, Any], connected: Set[str], labels: Dict[str, str], g: Dict[str, Any] = GEOM) -> Dict[str, Any]:
    cols: Dict[str, List[Dict[str, Any]]] = {"left": [], "right": [], "both": []}
    for p in _ports(dev):
        side = "left" if p.get("dir") == "in" else ("right" if p.get("dir") == "out" else "both")
        cols[side].append({"port": p, "pos": len(cols[side]) + 1})
    hidden = {"left": 0, "right": 0, "io": 0}
    vis: Dict[str, List[Dict[str, Any]]] = {}
    for side in ("left", "right", "both"):
        lst = cols[side]
        if len(lst) > g["maxRows"]:
            before = len(lst)
            lst = [e for e in lst if e["port"]["id"] in connected or e["port"].get("label") or labels.get(e["port"]["id"])]
            hidden["io" if side == "both" else side] = before - len(lst)
        vis[side] = lst
    rows: List[Dict[str, Any]] = []
    more: Dict[str, Dict[str, Any]] = {}
    top = g["headerH"] + g["pad"]

    def mk(e: Dict[str, Any], side: str, y: float) -> None:
        p = e["port"]
        ov = not p.get("label") and bool(labels.get(p["id"]))
        rows.append({"port": p, "side": side, "y": y, "index": e["pos"], "overlay": ov,
                     "label": p.get("label") or (labels.get(p["id"]) if ov else "") or p.get("name") or p["id"]})

    for i, e in enumerate(vis["left"]):
        mk(e, "left", top + i * g["rowH"])
    for i, e in enumerate(vis["right"]):
        mk(e, "right", top + i * g["rowH"])
    nl, nr = len(vis["left"]), len(vis["right"])
    if hidden["left"]:
        more["left"] = {"y": top + nl * g["rowH"], "n": hidden["left"]}
        nl += 1
    if hidden["right"]:
        more["right"] = {"y": top + nr * g["rowH"], "n": hidden["right"]}
        nr += 1
    col_rows = max(nl, nr)
    bottom = top + col_rows * g["rowH"]
    io_top = None
    if vis["both"] or hidden["io"]:
        io_top = bottom + (4 if col_rows else 0)
        rows_top = io_top + g["ioSectionH"]
        for i, e in enumerate(vis["both"]):
            mk(e, "both", rows_top + i * g["rowH"])
        bottom = rows_top + len(vis["both"]) * g["rowH"]
        if hidden["io"]:
            more["io"] = {"y": bottom, "n": hidden["io"]}
            bottom += g["rowH"]
    h = bottom + g["pad"] if (col_rows or io_top is not None) else g["headerH"] + 4
    return {"w": g["cardW"], "h": h, "rows": rows, "more": more, "ioTop": io_top, "total": len(_ports(dev))}


# ------------------------------------------------------------ wires (port of portAnchor / wireAnchors / wirePath)


def _row(card: Dict[str, Any], port_id: Optional[str]) -> Optional[Dict[str, Any]]:
    return next((r for r in card["layout"]["rows"] if r["port"]["id"] == port_id), None) if port_id else None


def _anchor(card: Dict[str, Any], row: Optional[Dict[str, Any]], side: str, g: Dict[str, Any]) -> Dict[str, Any]:
    if row is None:
        s = "left" if side == "left" else "right"
        return {"x": card["x"] if s == "left" else card["x"] + card["w"], "y": card["y"] + g["headerH"] / 2, "side": s}
    s = row["side"] if row["side"] != "both" else ("left" if side == "left" else "right")
    return {"x": card["x"] if s == "left" else card["x"] + card["w"], "y": card["y"] + row["y"] + g["rowH"] / 2, "side": s}


def _pick_side(card: Dict[str, Any], row: Optional[Dict[str, Any]], other: Dict[str, Any], default: str) -> str:
    if row is not None and row["side"] != "both":
        return str(row["side"])
    cx, ox = card["x"] + card["w"] / 2, other["x"] + other["w"] / 2
    if abs(ox - cx) < card["w"] * 0.5:
        return "right"
    return "right" if ox > cx else "left"


def wire_path(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    """Cubic with horizontal tangents; control offset ``max(40, |dx| / 2)`` (``patchview-core.wireControls``)."""
    off = max(40.0, abs(b["x"] - a["x"]) / 2)
    c1x = a["x"] - off if a["side"] == "left" else a["x"] + off
    c2x = b["x"] + off if b["side"] == "right" else b["x"] - off
    return f"M {_f(a['x'])} {_f(a['y'])} C {_f(c1x)} {_f(a['y'])} {_f(c2x)} {_f(b['y'])} {_f(b['x'])} {_f(b['y'])}"


# ------------------------------------------------------------ auto layout (port of patchview-core.autoLayout)


def auto_layout(cables: Sequence[Dict[str, Any]], ids: List[str], heights: Dict[str, float], origin: Dict[str, float], g: Dict[str, Any] = GEOM) -> Dict[str, Dict[str, float]]:
    order = {i: n for n, i in enumerate(ids)}
    adj: Dict[str, List[str]] = {i: [] for i in ids}
    for c in cables:
        f, t = (c.get("from") or {}).get("device"), (c.get("to") or {}).get("device")
        if f != t and f in order and t in order and t not in adj[f]:
            adj[f].append(t)
    mark: Dict[str, int] = {}
    post: List[str] = []
    for root in ids:
        if root in mark:
            continue
        stack = [[root, 0]]
        mark[root] = 1
        while stack:
            node, i = stack[-1]
            if i < len(adj[node]):
                stack[-1][1] = i + 1
                v = adj[node][i]
                if v not in mark:
                    mark[v] = 1
                    stack.append([v, 0])
            else:
                post.append(node)
                stack.pop()
    topo = post[::-1]
    t_idx = {n: i for i, n in enumerate(topo)}
    layer = {i: 0 for i in ids}
    preds: Dict[str, List[str]] = {i: [] for i in ids}
    for u in topo:
        for v in adj[u]:
            if t_idx[v] > t_idx[u]:
                layer[v] = max(layer[v], layer[u] + 1)
                preds[v].append(u)
    layers: Dict[int, List[str]] = {}
    for i in ids:
        layers.setdefault(layer[i], []).append(i)
    snap = lambda v: round(v / g["grid"]) * g["grid"]  # noqa: E731
    rank: Dict[str, int] = {}
    out: Dict[str, Dict[str, float]] = {}
    x = origin["x"]
    for L in range(max(layers) + 1 if layers else 0):
        lst = layers.get(L, [])
        key = {}
        for i in lst:
            ps = [rank[p] for p in preds[i] if p in rank]
            key[i] = sum(ps) / len(ps) if ps else float("inf")
        lst.sort(key=lambda i: (key[i], order[i]))
        y = origin["y"]
        for n, i in enumerate(lst):
            rank[i] = n
            out[i] = {"x": snap(x), "y": snap(y)}
            y = snap(y) + heights.get(i, g["headerH"] + 4) + ROW_GAP
        x += g["cardW"] + COL_GAP
    return out


# ------------------------------------------------------------ scene


def build_scene(doc: Doc, room_id: str, overlay: Optional[Dict[str, Any]], voc: Dict[str, Any], flt: Dict[str, Any]) -> Dict[str, Any]:
    """Cards and wires for ``room_id`` (``"*"`` = every room). ``flt``: ``state`` (all | planned | as_built | everything), ``disciplines``."""
    state = str(flt.get("state") or "all")
    discs = [d for d in (flt.get("disciplines") or []) if d]
    rooms = {r.get("id"): r for r in doc.get("rooms") or [] if isinstance(r, dict)}
    devices = [d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id")]
    by_id = {d["id"]: d for d in devices}
    for d in (overlay or {}).get("devices") or []:
        if isinstance(d, dict) and d.get("id") and d["id"] not in by_id:
            od = dict(d, auto=True)
            devices.append(od)
            by_id[od["id"]] = od

    def dev_discs(d: Dict[str, Any]) -> List[str]:
        out = [_device_disc(d, voc)]
        out += [str(_medium(p.get("medium"), voc).get("discipline") or "other") for p in _ports(d)]
        return out

    def primary(d: Dict[str, Any]) -> bool:
        if not _state_ok(_status(d), state) or (room_id != "*" and (d.get("room") or "") != room_id):
            return False
        return not discs or bool(set(dev_discs(d)) & set(discs))

    prim = {d["id"] for d in devices if primary(d)}
    cables = [c for c in doc.get("cables") or [] if isinstance(c, dict) and c.get("id") and isinstance(c.get("from"), dict) and isinstance(c.get("to"), dict)
              and c["from"].get("device") in by_id and c["to"].get("device") in by_id
              and _state_ok(_status(by_id[c["from"]["device"]]), state) and _state_ok(_status(by_id[c["to"]["device"]]), state)
              and _state_ok(_status(c), state)]

    def wire_disc_ok(c: Dict[str, Any]) -> bool:
        if not discs:
            return True
        m = _medium(c.get("medium"), voc)
        return str(m.get("discipline") or "other") in discs or bool(set(m.get("carries") or []) & set(discs))

    connected: Dict[str, Set[str]] = {}
    for c in cables:
        for e in (c["from"], c["to"]):
            if e.get("port"):
                connected.setdefault(e["device"], set()).add(str(e["port"]))
    ghosts: Set[str] = set()
    if room_id != "*":
        for c in cables:
            if not wire_disc_ok(c):
                continue
            f, t = c["from"]["device"], c["to"]["device"]
            if f in prim and t not in prim and (by_id[t].get("room") or "") != room_id:
                ghosts.add(t)
            elif t in prim and f not in prim and (by_id[f].get("room") or "") != room_id:
                ghosts.add(f)
    labels_all = (overlay or {}).get("port_labels") or {}
    cards: List[Dict[str, Any]] = []
    for d in devices:
        ext = d["id"] not in prim and d["id"] in ghosts
        if d["id"] not in prim and not ext:
            continue
        lay = card_layout(d, connected.get(d["id"], set()), labels_all.get(d["id"]) or {})
        pos = d.get("patch") if isinstance(d.get("patch"), dict) and isinstance(d["patch"].get("x"), (int, float)) and isinstance(d["patch"].get("y"), (int, float)) else None
        title = str(d.get("name") or d["id"])
        if isinstance(d.get("count"), (int, float)) and d["count"] > 1:
            title += f" \u00d7{int(d['count'])}"
        if d.get("suffix"):
            title += f" {d['suffix']}"
        room = d.get("room") or ""
        cards.append({"id": d["id"], "device": d, "x": pos["x"] if pos else 0.0, "y": pos["y"] if pos else 0.0, "w": lay["w"], "h": lay["h"],
                      "layout": lay, "external": ext, "auto": bool(d.get("auto")), "discipline": _device_disc(d, voc), "title": title,
                      "model": (f"{d.get('manufacturer') or ''} {d.get('model') or ''}").strip() or str(d.get("sub") or ""), "status": _status(d),
                      "placed": bool(pos), "roomName": (str((rooms.get(room) or {}).get("name") or room) if room else "Shared inventory") if ext else ""})
    missing = [c for c in cards if not c["placed"]]
    if missing:
        placed = [c for c in cards if c["placed"]]
        b = bounds_of(placed)
        origin = {"x": b["x"], "y": b["y"] + b["h"] + 80} if placed else {"x": 40.0, "y": 40.0}
        lay = auto_layout(cables, [c["id"] for c in missing], {c["id"]: c["h"] for c in missing}, origin)
        for c in missing:
            p = lay.get(c["id"], origin)
            c["x"], c["y"] = p["x"], p["y"]
    by_card = {c["id"]: c for c in cards}
    wires: List[Dict[str, Any]] = []
    for c in cables:
        fc, tc = by_card.get(c["from"]["device"]), by_card.get(c["to"]["device"])
        if fc is None or tc is None or not wire_disc_ok(c):
            continue
        m = _medium(c.get("medium"), voc)
        fr, tr = _row(fc, c["from"].get("port")), _row(tc, c["to"].get("port"))
        a = _anchor(fc, fr, _pick_side(fc, fr, tc, "right"), GEOM)
        b = _anchor(tc, tr, _pick_side(tc, tr, fc, "left"), GEOM)
        wires.append({"id": c["id"], "a": a, "b": b, "color": m.get("color") or FALLBACK_MEDIUM["color"], "dash": m.get("dash") or "",
                      "width": float(m.get("width") or 1.2), "external": fc["external"] or tc["external"], "planned": _status(c) == "planned",
                      "discipline": str(m.get("discipline") or "other")})
    return {"cards": cards, "wires": wires, "bounds": bounds_of(cards)}


def bounds_of(cards: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    if not cards:
        return {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
    x0, y0 = min(c["x"] for c in cards), min(c["y"] for c in cards)
    x1, y1 = max(c["x"] + c["w"] for c in cards), max(c["y"] + c["h"] for c in cards)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


# ------------------------------------------------------------ rendering


def _card_svg(card: Dict[str, Any], voc: Dict[str, Any], connected: Set[str], g: Dict[str, Any]) -> str:
    d, L = card["device"], card["layout"]
    di = _disc_info(card["discipline"], voc)
    cls = ["card"] + [k for k, on in (("planned", card["status"] == "planned"), ("ext", card["external"]), ("auto", card["auto"])) if on]
    border = ' stroke-dasharray="6 4"' if card["status"] == "planned" else (' stroke-dasharray="2 3"' if card["auto"] else "")
    op = ' opacity="0.5"' if card["external"] else ""
    o = [f'<g class="{" ".join(cls)}" data-device="{esc(card["id"])}" transform="translate({_f(card["x"])} {_f(card["y"])})"{op}>',
         f'<rect width="{g["cardW"]}" height="{_f(card["h"])}" rx="12" fill="{PANEL}" stroke="rgba(255,255,255,0.11)"{border}/>']
    pill = str(di.get("label") or card["discipline"]).upper()
    pw = len(pill) * 7 + 14
    o.append(f'<rect x="12" y="8" width="{pw}" height="15" rx="5" fill="{rgba(di["color"], 0.12)}" stroke="{rgba(di["color"], 0.45)}"/>'
             f'<text x="{12 + pw / 2:.1f}" y="19" font-size="9.5" font-weight="700" letter-spacing=".07em" text-anchor="middle" fill="{di["color"]}">{esc(pill)}</text>')
    tx = 12 + pw + 5
    for tag in ([f"auto"] if card["auto"] else []) + ([card["status"]] if card["status"] != "installed" else []):
        tw = len(tag) * 6 + 10
        col = {"planned": "#fcd34d", "spare": "#93c5fd", "retired": "#f06aa8"}.get(tag, MUTED)
        o.append(f'<rect x="{tx}" y="8" width="{tw}" height="15" rx="4" fill="none" stroke="{rgba(col, 0.4)}"/>'
                 f'<text x="{tx + tw / 2:.1f}" y="19" font-size="9.5" text-anchor="middle" fill="{col}">{esc(tag)}</text>')
        tx += tw + 5
    if card["external"]:
        o.append(f'<text x="{g["cardW"] - 10}" y="18" font-size="10" text-anchor="end" fill="{ACCENT}">\u2197 {esc(_fit(card["roomName"], 110, 10))}</text>')
    o.append(f'<text x="12" y="41" font-size="13.5" font-weight="650" fill="{TEXT}">{esc(_fit(card["title"], g["cardW"] - 24, 13.5))}</text>')
    if card["model"]:
        o.append(f'<text x="12" y="54" font-size="11.5" fill="{MUTED}">{esc(_fit(card["model"], g["cardW"] - 24, 11.5))}</text>')
    if L["rows"] or L["more"]:
        o.append(f'<rect x="8" y="{g["headerH"]}" width="{g["cardW"] - 16}" height="{_f(card["h"] - g["headerH"] - g["pad"] / 2)}" rx="9" '
                 f'fill="rgba(255,255,255,0.018)" stroke="rgba(255,255,255,0.06)"/>')
    rh = g["rowH"] - 4
    for r in L["rows"]:
        p, side, y = r["port"], r["side"], r["y"]
        m = _medium(p.get("medium"), voc)
        conn = p["id"] in connected
        x, w = (14, 106) if side != "both" else (14, 220)
        if side == "right":
            x = 128
        o.append(f'<rect x="{x}" y="{_f(y + 2)}" width="{w}" height="{rh}" rx="6" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.08)"/>')
        glyph = "\u2190" if side == "left" else ("\u2192" if side == "right" else "\u21c4")
        lbl = _fit(r["label"], w - 44, 11)
        ty, style = _f(y + g["rowH"] / 2 + 3.5), ' font-style="italic"' if r["overlay"] else ""
        if side == "right":
            o.append(f'<text x="{x + w - 6}" y="{ty}" font-size="11" text-anchor="end" fill="{TEXT}"><tspan fill="{MUTED}">{r["index"]}.</tspan> '
                     f'<tspan{style}>{esc(lbl)}</tspan> <tspan fill="{MUTED}" font-size="10">{glyph}</tspan></text>')
        else:
            o.append(f'<text x="{x + 6}" y="{ty}" font-size="11" fill="{TEXT}"><tspan fill="{MUTED}">{r["index"]}.</tspan> '
                     f'<tspan fill="{MUTED}" font-size="10">{glyph}</tspan> <tspan{style}>{esc(lbl)}</tspan></text>')
        fill = m.get("color") if conn else BG
        cy = _f(y + g["rowH"] / 2)
        if side != "right":
            o.append(f'<circle cx="0" cy="{cy}" r="{g["dotR"] - 1}" fill="{fill}" stroke="{m.get("color")}" stroke-width="2"/>')
        if side != "left":
            o.append(f'<circle cx="{g["cardW"]}" cy="{cy}" r="{g["dotR"] - 1}" fill="{fill}" stroke="{m.get("color")}" stroke-width="2"/>')
    for side, mr in L["more"].items():
        x, w = {"left": (14, 106), "right": (128, 106)}.get(side, (14, 220))
        o.append(f'<rect x="{x}" y="{_f(mr["y"] + 2)}" width="{w}" height="{rh}" rx="6" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.08)" stroke-dasharray="3 2"/>'
                 f'<text x="{x + w / 2:.1f}" y="{_f(mr["y"] + g["rowH"] / 2 + 3.5)}" font-size="11" text-anchor="middle" fill="{ACCENT}">+{mr["n"]} more</text>')
    if L["ioTop"] is not None:
        o.append(f'<text x="16" y="{_f(L["ioTop"] + 13)}" font-size="9.5" font-weight="700" letter-spacing=".08em" fill="{MUTED}">I/O</text>')
    o.append("</g>")
    return "".join(o)


def patch_svg(doc: Doc, room_id: str, *, overlay: Optional[Dict[str, Any]] = None, vocab: Optional[Dict[str, Any]] = None,
              scene: Optional[str] = None, filter: Optional[Dict[str, Any]] = None) -> str:
    """The room's patch canvas as SVG text.

    ``scene`` is a scene id (``sc-…`` or ``base``) to render instead of the stored state (``KeyError`` when unknown);
    without it the doc is drawn as is and the active scene, if any, is named in the title. ``filter`` takes ``state``
    (``all`` default, ``planned``, ``as_built``, ``everything``) and ``disciplines``. Cards carry ``data-device``, wires
    ``data-cable``; the ``viewBox`` is the content bounds plus a margin, a title block above and a legend below.
    """
    from . import scenes as S

    voc = _vocab(vocab)
    scene_name = ""
    if scene:
        doc = S.apply(doc, S.scene_data(doc, scene))
        scene_name = S.scene_name(doc, scene)
    elif S.active_id(doc) != S.BASE:
        try:
            scene_name = S.scene_name(doc, S.active_id(doc))
        except KeyError:
            scene_name = ""
    g = GEOM
    rooms = {r.get("id"): r for r in doc.get("rooms") or [] if isinstance(r, dict)}
    room_name = "All rooms" if room_id == "*" else str((rooms.get(room_id) or {}).get("name") or room_id or "Shared inventory")
    sc = build_scene(doc, room_id, overlay, voc, filter or {})
    connected: Dict[str, Set[str]] = {}
    for c in doc.get("cables") or []:
        if not isinstance(c, dict):
            continue
        for e in (c.get("from"), c.get("to")):
            if isinstance(e, dict) and e.get("port"):
                connected.setdefault(str(e.get("device")), set()).add(str(e["port"]))
    used: List[str] = []
    for key in [c["discipline"] for c in sc["cards"]] + [w["discipline"] for w in sc["wires"]]:
        if key not in used:
            used.append(key)
    b = sc["bounds"] if sc["cards"] else {"x": 0.0, "y": 0.0, "w": 480.0, "h": 120.0}
    width = max(b["w"], 480.0) + 2 * MARGIN
    per_row = max(1, int((width - 2 * MARGIN) // 120))
    legend_rows = (len(used) + per_row - 1) // per_row if used else 0
    legend_h = legend_rows * LEGEND_ROW_H + (MARGIN / 2 if used else 0)
    x0, y0 = b["x"] - MARGIN, b["y"] - MARGIN - TITLE_H
    height = TITLE_H + b["h"] + 2 * MARGIN + legend_h
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    title = str(meta.get("org") or meta.get("title") or meta.get("slug") or "Fathom")
    sub = " \u00b7 ".join(s for s in (room_name, f"Scene: {scene_name}" if scene_name else "", datetime.date.today().isoformat(),
                                      f"{len(sc['cards'])} devices \u00b7 {len(sc['wires'])} cables") if s)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(width)}" height="{_f(height)}" viewBox="{_f(x0)} {_f(y0)} {_f(width)} {_f(height)}" '
         f'font-family="{FONT}" data-room="{esc(room_id)}" data-devices="{len(sc["cards"])}" data-cables="{len(sc["wires"])}">',
         f"<title>{esc(title)} \u00b7 {esc(room_name)} \u00b7 patch</title>",
         f'<defs><pattern id="pv-grid" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="rgba(255,255,255,0.09)"/></pattern></defs>',
         f'<rect x="{_f(x0)}" y="{_f(y0)}" width="{_f(width)}" height="{_f(height)}" fill="{BG}"/>',
         f'<rect x="{_f(x0)}" y="{_f(y0)}" width="{_f(width)}" height="{_f(height)}" fill="url(#pv-grid)"/>',
         f'<g class="title"><text x="{_f(x0 + MARGIN / 2)}" y="{_f(y0 + 30)}" font-size="18" font-weight="700" fill="{TEXT}">{esc(title)} \u00b7 {esc(room_name)} \u00b7 Patch</text>',
         f'<text x="{_f(x0 + MARGIN / 2)}" y="{_f(y0 + 50)}" font-size="12" fill="{MUTED}">{esc(sub)}</text></g>']
    if not sc["cards"]:
        o.append(f'<text x="{_f(b["x"] + b["w"] / 2)}" y="{_f(b["y"] + b["h"] / 2)}" font-size="14" text-anchor="middle" fill="{MUTED}">No devices in {esc(room_name)}.</text>')
    o.append('<g class="wires" fill="none" stroke-linecap="round">')
    for w in sc["wires"]:
        extra = (f' stroke-dasharray="{esc(w["dash"])}"' if w["dash"] else "") + (' opacity="0.5"' if w["external"] else (' opacity="0.7"' if w["planned"] else ""))
        o.append(f'<path data-cable="{esc(w["id"])}" d="{wire_path(w["a"], w["b"])}" stroke="{esc(w["color"])}" stroke-width="{_f(w["width"])}"{extra}/>')
    o.append('</g><g class="cards">')
    for c in sc["cards"]:
        o.append(_card_svg(c, voc, connected.get(c["id"], set()), g))
    o.append("</g>")
    if used:
        ly = b["y"] + b["h"] + MARGIN + MARGIN / 2
        o.append('<g class="legend">')
        for i, key in enumerate(used):
            di = _disc_info(key, voc)
            lx, lyy = x0 + MARGIN / 2 + (i % per_row) * 120, ly + (i // per_row) * LEGEND_ROW_H
            o.append(f'<circle cx="{_f(lx + 6)}" cy="{_f(lyy + 8)}" r="5" fill="{di["color"]}"/>'
                     f'<text x="{_f(lx + 18)}" y="{_f(lyy + 12)}" font-size="11.5" fill="{TEXT}">{esc(di.get("label") or key)}</text>')
        o.append("</g>")
    o.append("</svg>")
    return "\n".join(o)


__all__ = ["GEOM", "patch_svg", "build_scene", "card_layout", "wire_path", "auto_layout", "bounds_of"]
