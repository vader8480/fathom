"""Standalone SVG rendering of a layout (same geometry as the HTML page).

Used for the `diagram.svg` sidecar (import into Visio / Illustrator / Figma)
and for the link overlay inside the HTML page.
"""

from __future__ import annotations

import html
from typing import List

from .layout import GROUP_HEADER_H, GROUP_PAD, KEY_ROW_H, Layout
from .model import BRANDS, KINDS, Project

FONT = "Inter, 'SF Pro Text', system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
BG = "#0b1020"
PANEL = "rgba(255,255,255,0.028)"
PANEL_BORDER = "rgba(255,255,255,0.09)"
TEXT = "#e6eaf4"
MUTED = "#8e97ab"
ACCENT = "#8ea2ff"


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        r, g, b = 150, 160, 180
    return f"rgba({r},{g},{b},{alpha})"


def rgba(hex_color: str, alpha: float) -> str:
    return _hex_to_rgba(hex_color, alpha)


def _all_kinds():
    """v1 kinds (frozen colors) plus the AVL vocabulary's new kinds, for card gradients."""
    merged = dict(KINDS)
    try:
        from .vocab import KINDS as vk

        for k, spec in vk.items():
            merged.setdefault(k, spec)
    except Exception:  # pragma: no cover - vocab not importable
        pass
    return merged


# ------------------------------------------------------------ overlay bits


def svg_defs(project: Project, layout: Layout) -> str:
    parts = ["<defs>"]
    for m in sorted({lg.medium for lg in layout.links} | {"dante"}):
        spec = project.medium(m)
        parts.append(
            f'<marker id="arrow-{esc(m)}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse" markerUnits="userSpaceOnUse">'
            f'<path d="M1,1 L9,5 L1,9 Z" fill="{spec["color"]}"/></marker>'
        )
    parts.append(
        '<linearGradient id="spine-grad" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#7b86ff"/><stop offset="1" stop-color="#8b5cf6"/></linearGradient>'
    )
    for kind, spec in _all_kinds().items():
        c = spec["color"]
        parts.append(
            f'<linearGradient id="card-{kind}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{rgba(c, 0.42)}"/><stop offset="0.55" stop-color="{rgba(c, 0.10)}"/><stop offset="1" stop-color="rgba(20,26,42,0.9)"/></linearGradient>'
        )
    parts.append("</defs>")
    return "".join(parts)


def svg_links(project: Project, layout: Layout, interactive: bool = True) -> str:
    out: List[str] = []
    for i, lg in enumerate(layout.links):
        attrs = f'class="lk" data-s="{esc(lg.link.source)}" data-t="{esc(lg.link.target)}" data-m="{esc(lg.medium)}"' if interactive else ""
        dash = f' stroke-dasharray="{lg.dash}"' if lg.dash else ""
        marker = f' marker-end="url(#arrow-{esc(lg.medium)})"' if lg.arrow else ""
        start_marker = f' marker-start="url(#arrow-{esc(lg.medium)})"' if lg.link.bidirectional and lg.arrow else ""
        cap = ' stroke-linecap="round"' if lg.dash and lg.dash.startswith("1.5") else ""
        out.append(f'<path {attrs} d="{lg.path}" fill="none" stroke="{lg.color}" stroke-width="{lg.width}"{dash}{cap}{marker}{start_marker} opacity="0.92"/>')
        if lg.label:
            lattrs = f'class="ll" data-s="{esc(lg.link.source)}" data-t="{esc(lg.link.target)}"' if interactive else ""
            out.append(
                f'<text {lattrs} x="{lg.label_x:.1f}" y="{lg.label_y:.1f}" text-anchor="{lg.label_anchor}" font-size="9.5" font-family="{FONT}" fill="{MUTED}" '
                f'paint-order="stroke" stroke="{BG}" stroke-width="3" stroke-linejoin="round">{esc(lg.label)}</text>'
            )
    return "".join(out)


def svg_spine(project: Project, layout: Layout) -> str:
    if layout.spine is None:
        return ""
    sp = layout.spine
    out = [f'<rect x="{sp.x:.1f}" y="{sp.y:.1f}" width="{sp.w:.1f}" height="{sp.h:.1f}" rx="{sp.w / 2:.1f}" fill="url(#spine-grad)" opacity="0.95"/>']
    label = project.spine_label.upper()
    for frac in (0.26, 0.74):
        cy = sp.y + sp.h * frac
        out.append(
            f'<text transform="translate({sp.cx + 3.5:.1f},{cy:.1f}) rotate(-90)" text-anchor="middle" font-size="9.5" letter-spacing="2.2" font-weight="700" '
            f'font-family="{FONT}" fill="#ffffff" opacity="0.95">{esc(label)}</text>'
        )
    for st in layout.stubs:
        out.append(f'<path class="stub" data-n="{esc(st.node_id)}" d="{st.path}" stroke="{project.medium("dante")["color"]}" stroke-width="1.6" fill="none" opacity="0.9"/>')
        out.append(f'<circle class="dot" data-n="{esc(st.node_id)}" cx="{st.dot_x:.1f}" cy="{st.dot_y:.1f}" r="3.6" fill="#dbe1ff" stroke="{BG}" stroke-width="1.5"/>')
        if st.label:
            out.append(f'<text x="{st.label_x:.1f}" y="{st.label_y:.1f}" text-anchor="middle" font-size="8.5" font-family="{FONT}" fill="{MUTED}" paint-order="stroke" stroke="{BG}" stroke-width="3">{esc(st.label)}</text>')
    return "".join(out)


# ------------------------------------------------------------ standalone


def planned_ids(project: Project, doc=None) -> set:
    """Card ids drawn as planned (FR-PLN-02): device ``status: planned`` from the v2 doc
    (``doc`` argument or ``project.doc``) or the node itself; extra cards follow their device."""
    out = set()
    src = doc if isinstance(doc, dict) else getattr(project, "doc", None)
    if isinstance(src, dict):
        for d in src.get("devices") or []:
            if isinstance(d, dict) and d.get("status") == "planned" and d.get("id"):
                out.add(str(d["id"]))
    for n in project.nodes:
        status = getattr(n, "status", None) or (n.detail.get("status") if isinstance(n.detail, dict) else None)
        if status == "planned":
            out.add(n.id)
    for n in project.nodes:
        if n.ref and n.ref in out:
            out.add(n.id)
    return out


def render_svg(project: Project, layout: Layout, *, doc=None) -> str:
    planned = planned_ids(project, doc)
    W, H = layout.width, layout.height
    header_h = 118
    out: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H + header_h:.0f}" viewBox="0 0 {W:.0f} {H + header_h:.0f}" font-family="{FONT}">',
        svg_defs(project, layout),
        f'<rect width="100%" height="100%" fill="{BG}"/>',
    ]
    # header
    eyebrow = " · ".join(p for p in (project.meta.org, project.meta.system) if p).upper()
    out.append(f'<text x="24" y="30" font-size="9.5" letter-spacing="1.8" fill="{MUTED}">{esc(eyebrow)}</text>')
    out.append(f'<text x="24" y="62" font-size="24" font-weight="700" fill="{TEXT}">{esc(project.meta.title)}</text>')
    intro_lines = _wrap(project.meta.intro, int((W - 48) / 6.3))
    for i, line in enumerate(intro_lines[:3]):
        out.append(f'<text x="24" y="{84 + i * 15}" font-size="11" fill="{MUTED}">{esc(line)}</text>')
    out.append(f'<g transform="translate(0,{header_h})">')
    # groups
    for g in layout.groups:
        b = g.box
        out.append(f'<rect x="{b.x:.1f}" y="{b.y:.1f}" width="{b.w:.1f}" height="{b.h:.1f}" rx="10" fill="{PANEL}" stroke="{PANEL_BORDER}"/>')
        out.append(f'<text x="{b.x + GROUP_PAD:.1f}" y="{b.y + 19:.1f}" font-size="10" font-weight="700" letter-spacing="1.6" fill="{ACCENT}">{esc(g.letter)}</text>')
        out.append(f'<text x="{b.x + GROUP_PAD + (16 if g.letter else 0):.1f}" y="{b.y + 19:.1f}" font-size="10" font-weight="600" letter-spacing="1.4" fill="{TEXT}">{esc(g.label.upper())}</text>')
        if g.note_box and g.note:
            nb = g.note_box
            for i, line in enumerate(_wrap(g.note, max(12, int(nb.w / 5.4)))):
                out.append(f'<text x="{nb.x + 2:.1f}" y="{nb.y + 12 + i * 14:.1f}" font-size="10.5" fill="{MUTED}">{esc(line)}</text>')
    # chevrons
    for c in layout.columns:
        b = c.box
        tip = 12
        pts = f"{b.x:.1f},{b.y:.1f} {b.right - tip:.1f},{b.y:.1f} {b.right:.1f},{b.cy:.1f} {b.right - tip:.1f},{b.bottom:.1f} {b.x:.1f},{b.bottom:.1f} {b.x + tip:.1f},{b.cy:.1f}"
        out.append(f'<polygon points="{pts}" fill="rgba(255,255,255,0.05)" stroke="{PANEL_BORDER}"/>')
        out.append(f'<text x="{b.x + tip + 8:.1f}" y="{b.cy + 3.5:.1f}" font-size="10" font-weight="700" fill="{ACCENT}">{esc(c.number)}</text>')
        out.append(f'<text x="{b.x + tip + 30:.1f}" y="{b.cy + 3.5:.1f}" font-size="9.5" font-weight="600" letter-spacing="1.3" fill="{TEXT}">{esc(c.label.upper())}</text>')
    out.append(svg_spine(project, layout))
    out.append(svg_links(project, layout, interactive=False))
    # cards
    for cg in layout.cards.values():
        b = cg.box
        dashed = ' stroke-dasharray="5 3" data-planned="1"' if cg.node.id in planned else ""
        out.append(f'<rect x="{b.x:.1f}" y="{b.y:.1f}" width="{b.w:.1f}" height="{b.h:.1f}" rx="8" fill="url(#card-{esc(cg.node.kind if cg.node.kind in _all_kinds() else "other")})" stroke="{rgba(cg.color, 0.45)}"{dashed}/>')
        ty = b.y + 8 + 12
        for line in cg.title_lines:
            out.append(f'<text x="{b.x + 11:.1f}" y="{ty:.1f}" font-size="12.5" font-weight="600" fill="{TEXT}">{esc(line)}</text>')
            ty += 16
        for line in cg.sub_lines + cg.extra_lines:
            out.append(f'<text x="{b.x + 11:.1f}" y="{ty - 2:.1f}" font-size="10.5" fill="{MUTED}">{esc(line)}</text>')
            ty += 14
        if cg.node.brand:
            spec = BRANDS.get(cg.node.brand, {"text": cg.node.brand.upper(), "bg": "#1f2937", "fg": "#e5e7eb"})
            bw = max(26, 7 * len(spec["text"]) + 12)
            bx = b.right - bw - 8
            out.append(f'<rect x="{bx:.1f}" y="{b.y + 8:.1f}" width="{bw:.1f}" height="14" rx="3" fill="{spec["bg"]}"/>')
            out.append(f'<text x="{bx + bw / 2:.1f}" y="{b.y + 18.5:.1f}" text-anchor="middle" font-size="8.5" font-weight="700" letter-spacing="0.6" fill="{spec["fg"]}">{esc(spec["text"])}</text>')
    # key
    if layout.key:
        k = layout.key
        b = k.box
        out.append(f'<rect x="{b.x:.1f}" y="{b.y:.1f}" width="{b.w:.1f}" height="{b.h:.1f}" rx="10" fill="{PANEL}" stroke="{PANEL_BORDER}"/>')
        out.append(f'<text x="{b.x + GROUP_PAD:.1f}" y="{b.y + 19:.1f}" font-size="10" font-weight="700" letter-spacing="1.6" fill="{TEXT}">KEY</text>')
        y0 = b.y + GROUP_HEADER_H + 4
        for i, (kind, label, color) in enumerate(k.kinds):
            yy = y0 + i * KEY_ROW_H
            out.append(f'<rect x="{b.x + GROUP_PAD:.1f}" y="{yy:.1f}" width="12" height="12" rx="3" fill="{rgba(color, 0.9)}"/>')
            out.append(f'<text x="{b.x + GROUP_PAD + 18:.1f}" y="{yy + 10:.1f}" font-size="10.5" fill="{TEXT}">{esc(label)}</text>')
        mx = b.x + b.w / 2
        for i, (m, label, color, dash) in enumerate(k.media):
            yy = y0 + i * KEY_ROW_H + 6
            d = f' stroke-dasharray="{dash}"' if dash else ""
            out.append(f'<line x1="{mx:.1f}" y1="{yy:.1f}" x2="{mx + 34:.1f}" y2="{yy:.1f}" stroke="{color}" stroke-width="2"{d}/>')
            out.append(f'<text x="{mx + 42:.1f}" y="{yy + 4:.1f}" font-size="10.5" fill="{TEXT}">{esc(label)}</text>')
        fy = y0 + max(len(k.kinds), len(k.media)) * KEY_ROW_H + 14
        for i, line in enumerate(k.footnote_lines):
            out.append(f'<text x="{b.x + GROUP_PAD:.1f}" y="{fy + i * 13:.1f}" font-size="9.5" fill="{MUTED}">{esc(line)}</text>')
    out.append("</g></svg>")
    return "".join(out)


def _wrap(text: str, max_chars: int) -> List[str]:
    from .layout import wrap_text

    return wrap_text(text, max_chars)
