"""Geometry: where every group panel, card, link path and Dante stub goes.

Deterministic and renderer-agnostic so the HTML and SVG outputs share one
layout. All units are CSS pixels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .model import KINDS, Link, Node, Project

try:  # v0.3 vocabulary: new kinds bring their colors and v1 "legacy" kind
    from .vocab import KINDS as _VOCAB_KINDS
except Exception:  # pragma: no cover - vocab not importable
    _VOCAB_KINDS = {}


def kind_spec(kind: str) -> Dict[str, str]:
    """Color/label for a card kind: v1 table first (colors frozen), then the AVL vocabulary."""
    if kind in KINDS:
        return KINDS[kind]
    return _VOCAB_KINDS.get(kind) or KINDS.get("other") or {"label": "Other", "color": "#9aa3b5"}


def legacy_kind(kind: str) -> str:
    """The v1 kind whose layout heuristics apply (v1 kinds map to themselves)."""
    if kind in ("source", "stage_io", "computer", "console", "iem", "pa", "network", "video", "other"):
        return kind
    spec = _VOCAB_KINDS.get(kind) or {}
    return str(spec.get("legacy") or "other")

# ---- metrics
PAD = 24
GROUP_PAD = 14
GROUP_HEADER_H = 30
GROUP_GAP = 16
CARD_GAP = 10
CHEV_H = 30
CHEV_GAP = 18
SPINE_W = 28
SPINE_MARGIN = 36
TITLE_FS = 12.5
SUB_FS = 10.5
LINE_H = 14
CARD_PAD_Y = 8
CARD_PAD_X = 11
BADGE_W = 60
TITLE_CHAR_W = 0.6 * TITLE_FS
SUB_CHAR_W = 0.58 * SUB_FS
NOTE_FS = 10.5
NOTE_LINE_H = 14
KEY_ROW_H = 18


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass
class CardGeom:
    node: Node
    box: Box
    side: str
    col_index: int
    title_lines: List[str]
    sub_lines: List[str]
    extra_lines: List[str]
    color: str
    group_id: str


@dataclass
class GroupGeom:
    group_id: str
    label: str
    letter: str
    box: Box
    side: str
    note: str = ""
    note_box: Optional[Box] = None
    auto: bool = False


@dataclass
class ColumnGeom:
    column_id: str
    label: str
    number: str
    box: Box
    side: str


@dataclass
class LinkGeom:
    link: Link
    path: str
    color: str
    dash: str
    width: float
    arrow: bool
    label: str
    label_x: float
    label_y: float
    label_anchor: str
    medium: str


@dataclass
class StubGeom:
    node_id: str
    path: str
    dot_x: float
    dot_y: float
    side: str
    label: str = ""
    label_x: float = 0
    label_y: float = 0


@dataclass
class KeyGeom:
    box: Box
    kinds: List[Tuple[str, str, str]]  # (kind, label, color)
    media: List[Tuple[str, str, str, str]]  # (medium, label, color, dash)
    footnote_lines: List[str]


@dataclass
class Layout:
    width: float
    height: float
    cards: Dict[str, CardGeom] = field(default_factory=dict)
    groups: List[GroupGeom] = field(default_factory=list)
    columns: List[ColumnGeom] = field(default_factory=list)
    links: List[LinkGeom] = field(default_factory=list)
    stubs: List[StubGeom] = field(default_factory=list)
    spine: Optional[Box] = None
    key: Optional[KeyGeom] = None
    card_w: int = 196


# ------------------------------------------------------------ text helpers


def wrap_text(text: str, max_chars: int) -> List[str]:
    words = (text or "").split()
    if not words:
        return []
    lines: List[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) <= max_chars or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def card_text(node: Node, card_w: int) -> Tuple[List[str], List[str], List[str]]:
    inner = card_w - 2 * CARD_PAD_X
    title_avail = inner - (BADGE_W + 6 if node.brand else 0)
    title_lines = wrap_text(node.title, max(8, int(title_avail / TITLE_CHAR_W)))
    sub_lines = wrap_text(node.sub, max(10, int(inner / SUB_CHAR_W)))
    extra: List[str] = []
    for line in node.lines:
        extra.extend(wrap_text(line, max(10, int(inner / SUB_CHAR_W))) or [""])
    return title_lines, sub_lines, extra


def card_height(title_lines: List[str], sub_lines: List[str], extra_lines: List[str]) -> float:
    h = CARD_PAD_Y * 2 + max(1, len(title_lines)) * 16 + (len(sub_lines) + len(extra_lines)) * LINE_H
    if not sub_lines and not extra_lines:
        h += 4
    return max(42, h)


# ------------------------------------------------------------------ layout


def compute_layout(project: Project) -> Layout:
    card_w = project.options.card_width
    col_gap = project.options.column_gap
    left_cols = project.columns_for_side("left")
    right_cols = project.columns_for_side("right")
    spine_cols = project.columns_for_side("spine")
    show_spine = project.spine_show and (any(n.dante for n in project.nodes) or bool(spine_cols))

    def side_width(n_cols: int) -> float:
        return n_cols * card_w + max(0, n_cols - 1) * col_gap + 2 * GROUP_PAD

    left_w = side_width(max(1, len(left_cols)))
    right_w = side_width(max(1, len(right_cols)))
    spine_total = (SPINE_MARGIN * 2 + SPINE_W) if show_spine else GROUP_GAP * 2
    left_x = PAD
    spine_x = left_x + left_w + (SPINE_MARGIN if show_spine else GROUP_GAP)
    right_x = spine_x + (SPINE_W + SPINE_MARGIN if show_spine else GROUP_GAP)
    width = right_x + right_w + PAD

    layout = Layout(width=width, height=0, card_w=card_w)

    # column x positions
    col_x: Dict[str, float] = {}
    col_side: Dict[str, str] = {}
    col_idx: Dict[str, int] = {}
    for i, c in enumerate(left_cols):
        col_x[c.id] = left_x + GROUP_PAD + i * (card_w + col_gap)
        col_side[c.id] = "left"
        col_idx[c.id] = i
    for i, c in enumerate(right_cols):
        col_x[c.id] = right_x + GROUP_PAD + i * (card_w + col_gap)
        col_side[c.id] = "right"
        col_idx[c.id] = i

    # chevrons
    y = 0.0
    num = 1
    for c in left_cols:
        layout.columns.append(ColumnGeom(c.id, c.label, f"{num:02d}", Box(col_x[c.id] - GROUP_PAD + 2, y, card_w + 2 * GROUP_PAD - 4 if len(left_cols) == 1 else card_w + col_gap - 6, CHEV_H), "left"))
        num += 1
    if show_spine:
        label = spine_cols[0].label if spine_cols else "Dante"
        layout.columns.append(ColumnGeom(spine_cols[0].id if spine_cols else "dante", label, f"{num:02d}", Box(spine_x - SPINE_MARGIN + 8, y, SPINE_W + 2 * SPINE_MARGIN - 16, CHEV_H), "spine"))
        num += 1
    for c in right_cols:
        layout.columns.append(ColumnGeom(c.id, c.label, f"{num:02d}", Box(col_x[c.id] - GROUP_PAD + 2, y, card_w + col_gap - 6, CHEV_H), "right"))
        num += 1
    # last chevron of each side ends at the side edge
    for cg in layout.columns:
        if cg.side == "left" and left_cols and cg.column_id == left_cols[-1].id:
            cg.box.w = (left_x + left_w) - cg.box.x - 2
        if cg.side == "right" and right_cols and cg.column_id == right_cols[-1].id:
            cg.box.w = (right_x + right_w) - cg.box.x - 2

    top = CHEV_H + CHEV_GAP

    # default column for nodes without one
    def default_column(node: Node, side: str) -> str:
        cols = left_cols if side == "left" else right_cols
        if not cols:
            return ""
        lk = legacy_kind(node.kind)
        if side == "left":
            return cols[0].id if lk == "source" else cols[-1].id
        if lk in ("console", "computer", "stage_io", "video") or node.dante:
            return cols[0].id
        if lk == "pa" and len(cols) >= 3:
            return cols[2].id if any(w in node.label.lower() for w in ("speaker", "main", "sub", "fill", "delay", "monitor", "wedge", "overhead", "iem", "pack", "ear")) else cols[1].id
        return cols[-1].id

    # nodes by group
    nodes_by_group: Dict[str, List[Node]] = {}
    for n in project.nodes:
        gid = n.group
        if not gid or project.group(gid) is None:
            side = "left" if legacy_kind(n.kind) in ("source", "stage_io", "computer", "video") else "right"
            g = project.ensure_group(f"auto-{side}", "Unplaced", side, auto=True)
            gid = g.id
            n.group = gid
        nodes_by_group.setdefault(gid, []).append(n)

    links_by_node: Dict[str, List[Link]] = {}
    for l in project.links:
        links_by_node.setdefault(l.source, []).append(l)
        links_by_node.setdefault(l.target, []).append(l)

    def place_side(side: str, side_x: float, side_w: float) -> float:
        cols = left_cols if side == "left" else right_cols
        order_cols = list(cols) if side == "left" else list(cols)  # spine-adjacent first on the right
        if side == "right":
            order_cols = list(cols)  # col 0 is spine-adjacent already
        ycur = top
        for g in project.groups_for_side(side):
            members = nodes_by_group.get(g.id, [])
            if not members and not g.note:
                continue
            gbox_y = ycur
            content_top = gbox_y + GROUP_HEADER_H
            # note handling
            note_box = None
            by_col: Dict[int, List[Node]] = {}
            for n in members:
                cid = n.column if n.column in col_x and col_side.get(n.column) == side else default_column(n, side)
                n.column = cid or n.column
                by_col.setdefault(col_idx.get(cid, 0), []).append(n)
            note_lines: List[str] = []
            inner_w = side_w - 2 * GROUP_PAD
            if g.note:
                if 0 not in by_col and cols:
                    note_lines = wrap_text(g.note, max(12, int((card_w - 4) / (0.5 * NOTE_FS))))
                    note_box = Box(side_x + GROUP_PAD, content_top + 2, card_w, len(note_lines) * NOTE_LINE_H + 4)
                else:
                    note_lines = wrap_text(g.note, max(20, int(inner_w / (0.5 * NOTE_FS))))
                    note_box = Box(side_x + GROUP_PAD, content_top, inner_w, len(note_lines) * NOTE_LINE_H + 6)
                    content_top += note_box.h + 6
            placed: Dict[str, CardGeom] = {}
            col_bottoms: Dict[int, float] = {}
            member_ids = {n.id for n in members}
            col_of = {n.id: col_idx.get(n.column, 0) for n in members}

            def pass_bands(ci: int) -> List[float]:
                """y centers of links that run straight through column ``ci`` (source placed earlier, target further right)."""
                ys: List[float] = []
                for l in project.links:
                    a, b = l.source, l.target
                    if a in placed and b in member_ids and b not in placed and col_of.get(b, 0) > ci and col_of.get(a, -1) < ci:
                        ys.append(placed[a].box.cy)
                    if b in placed and a in member_ids and a not in placed and col_of.get(a, 0) > ci and col_of.get(b, -1) < ci:
                        ys.append(placed[b].box.cy)
                return ys

            for ci in sorted(by_col):
                nodes = by_col[ci]
                bands = pass_bands(ci)
                explicit = any(n.order for n in nodes)
                if explicit:
                    nodes = sorted(nodes, key=lambda n: (n.order, project.nodes.index(n)))
                else:
                    def desired(n: Node) -> Optional[float]:
                        ys = []
                        for l in links_by_node.get(n.id, []):
                            other = l.target if l.source == n.id else l.source
                            if other in placed:
                                ys.append(placed[other].box.cy)
                        return sum(ys) / len(ys) if ys else None
                    keyed = []
                    for i, n in enumerate(nodes):
                        d = desired(n)
                        keyed.append((0 if d is not None else 1, d if d is not None else 0.0, i, n))
                    if any(k[0] == 0 for k in keyed):
                        keyed.sort(key=lambda k: (k[1] if k[0] == 0 else float("inf"), k[2]))
                    nodes = [k[3] for k in keyed]
                ycol = content_top
                for n in nodes:
                    tl, sl, el = card_text(n, card_w)
                    h = card_height(tl, sl, el)
                    want = None
                    if not explicit:
                        ys = [placed[l.target if l.source == n.id else l.source].box.cy for l in links_by_node.get(n.id, []) if (l.target if l.source == n.id else l.source) in placed]
                        want = (sum(ys) / len(ys) - h / 2) if ys else None
                    yy = max(ycol, want) if want is not None else ycol
                    # do not sit on a link that passes straight through this column
                    moved = True
                    while moved:
                        moved = False
                        for by in sorted(bands):
                            if yy - 7 < by < yy + h + 7:
                                yy = by + 9
                                moved = True
                    x = col_x[(left_cols if side == "left" else right_cols)[ci].id]
                    color = kind_spec(n.kind)["color"]
                    cg = CardGeom(n, Box(x, yy, card_w, h), side, ci, tl, sl, el, color, g.id)
                    placed[n.id] = cg
                    layout.cards[n.id] = cg
                    ycol = yy + h + CARD_GAP
                col_bottoms[ci] = ycol - CARD_GAP
            content_bottom = max([content_top] + list(col_bottoms.values()) + ([note_box.bottom] if note_box else []))
            gh = (content_bottom - gbox_y) + GROUP_PAD
            layout.groups.append(GroupGeom(g.id, g.label, g.id if len(g.id) <= 2 else "", Box(side_x, gbox_y, side_w, gh), side, g.note, note_box, g.auto))
            ycur = gbox_y + gh + GROUP_GAP
        return ycur

    left_bottom = place_side("left", left_x, left_w)
    right_bottom = place_side("right", right_x, right_w)

    # key panel on the shorter side
    def key_label(k: str) -> str:
        # the network row names the spine when the spine is drawn ("Dante network")
        if k == "network" and show_spine and project.spine_label:
            return project.spine_label
        return str(kind_spec(k)["label"])

    kinds = [(k, key_label(k), kind_spec(k)["color"]) for k in project.used_kinds()]
    media = []
    for m in project.used_media():
        spec = project.medium(m)
        media.append((m, spec["label"], spec["color"], spec.get("dash", "")))
    key_side = "left" if left_bottom <= right_bottom else "right"
    key_x, key_w = (left_x, left_w) if key_side == "left" else (right_x, right_w)
    foot_lines = wrap_text(project.meta.footnote, max(24, int((key_w - 2 * GROUP_PAD) / (0.5 * NOTE_FS))))
    rows = max(len(kinds), len(media), 1)
    key_h = GROUP_HEADER_H + rows * KEY_ROW_H + (len(foot_lines) * 13 + 14 if foot_lines else 0) + GROUP_PAD
    key_y = left_bottom if key_side == "left" else right_bottom
    layout.key = KeyGeom(Box(key_x, key_y, key_w, key_h), kinds, media, foot_lines)
    if key_side == "left":
        left_bottom = key_y + key_h + GROUP_GAP
    else:
        right_bottom = key_y + key_h + GROUP_GAP

    height = max(left_bottom, right_bottom) - GROUP_GAP + PAD
    layout.height = height
    if show_spine:
        layout.spine = Box(spine_x, top, SPINE_W, height - top - PAD)

    _route_links(project, layout, col_gap)
    _route_stubs(project, layout)
    return layout


# ------------------------------------------------------------------ links


def _rounded_orth(sx: float, sy: float, tx: float, ty: float, xm: float) -> str:
    dy = ty - sy
    if abs(dy) < 1.5:
        return f"M{sx:.1f},{sy:.1f} L{tx:.1f},{ty:.1f}"
    r = min(8.0, abs(dy) / 2, abs(xm - sx), abs(tx - xm))
    dirx = 1 if tx > sx else -1
    diry = 1 if dy > 0 else -1
    return (
        f"M{sx:.1f},{sy:.1f} L{xm - dirx * r:.1f},{sy:.1f} "
        f"Q{xm:.1f},{sy:.1f} {xm:.1f},{sy + diry * r:.1f} "
        f"L{xm:.1f},{ty - diry * r:.1f} "
        f"Q{xm:.1f},{ty:.1f} {xm + dirx * r:.1f},{ty:.1f} "
        f"L{tx:.1f},{ty:.1f}"
    )


def _route_links(project: Project, layout: Layout, col_gap: int) -> None:
    cards = layout.cards
    # trunk channels: per (gap key) the ordered list of source cards
    gap_sources: Dict[Tuple[str, int, int], List[str]] = {}
    plans = []
    for l in project.links:
        a, b = cards.get(l.source), cards.get(l.target)
        if a is None or b is None:
            continue
        if b.box.x > a.box.right - 1:  # rightwards: channel in the gap left of the target
            sx, sy, tx, ty = a.box.right, a.box.cy, b.box.x, b.box.cy
            gap_key = (b.side, b.col_index - 1, b.col_index)
            src_key = l.source
        elif a.box.x > b.box.right - 1:  # leftwards: channel in the gap right of the target
            sx, sy, tx, ty = a.box.x, a.box.cy, b.box.right, b.box.cy
            gap_key = (b.side, b.col_index, b.col_index + 1)
            src_key = l.source
        else:  # same column: loop out the right side
            sx, sy, tx, ty = a.box.right, a.box.cy, b.box.right, b.box.cy
            gap_key = ("loop", a.col_index, a.col_index)
            src_key = l.source
        lst = gap_sources.setdefault(gap_key, [])
        if src_key not in lst:
            lst.append(src_key)
        plans.append((l, a, b, sx, sy, tx, ty, gap_key, src_key))
    # order sources in each gap by y so channels do not cross needlessly
    for key, srcs in gap_sources.items():
        srcs.sort(key=lambda sid: cards[sid].box.cy)
    for l, a, b, sx, sy, tx, ty, gap_key, src_key in plans:
        spec = project.medium(l.medium)
        srcs = gap_sources[gap_key]
        n = len(srcs)
        i = srcs.index(src_key)
        if gap_key[0] == "loop":
            xm = sx + 14 + i * 6
            path = f"M{sx:.1f},{sy:.1f} L{xm:.1f},{sy:.1f} L{xm:.1f},{ty:.1f} L{tx + 3:.1f},{ty:.1f}"
        else:
            # vertical channel sits in the gap next to the *target*, so links that skip a
            # column run straight across it at the source's height
            card_w = layout.card_w
            if tx > sx:
                lo, hi = tx - col_gap, tx
            else:
                lo, hi = tx, tx + col_gap
            gap = hi - lo
            frac = (i + 1) / (n + 1)
            xm = lo + gap * (0.15 + 0.7 * frac)
            end_x = tx - 3 if tx > sx else tx + 3
            path = _rounded_orth(sx, sy, end_x if spec.get("arrow") else tx, ty, xm)
        label = l.label
        # label above the horizontal segment that has room for it: target side first,
        # then source side; otherwise right-aligned just before the target card
        seg1 = abs(xm - sx)
        seg2 = abs(tx - xm)
        label_w = len(label) * 5.4 + 8
        if seg2 >= label_w:
            lx, ly, anchor = (xm + tx) / 2, ty - 4, "middle"
        elif seg1 >= label_w:
            lx, ly, anchor = (sx + xm) / 2, sy - 4, "middle"
        elif tx > sx:
            lx, ly, anchor = tx - 5, ty - 4, "end"
        else:
            lx, ly, anchor = tx + 5, ty - 4, "start"
        layout.links.append(LinkGeom(l, path, spec["color"], spec.get("dash", ""), float(spec.get("width", 1.4)), bool(spec.get("arrow")), label, lx, ly, anchor, l.medium))


def _route_stubs(project: Project, layout: Layout) -> None:
    if layout.spine is None:
        return
    sp = layout.spine
    for nid, cg in layout.cards.items():
        if not cg.node.dante:
            continue
        cy = cg.box.cy
        if cg.side == "left":
            sx, tx = cg.box.right, sp.x
            dot_x = sp.x + 1
        else:
            sx, tx = cg.box.x, sp.right
            dot_x = sp.right - 1
        path = f"M{sx:.1f},{cy:.1f} L{tx:.1f},{cy:.1f}"
        label = ""
        if project.options.dante_counts:
            d = cg.node.detail.get("dante") or {}
            if d:
                label = f"tx {d.get('tx', 0)} · rx {d.get('rx', 0)}"
        layout.stubs.append(StubGeom(nid, path, dot_x, cy, cg.side, label, (sx + tx) / 2, cy - 4))
