"""Data model: project, groups, nodes (cards), links (cables), imports.

Everything renders from a :class:`Project`. Exports (Yamaha CSV, Dante preset
XML, Waves sessions) are parsed into intermediate structures and *merged* into
the project (see ``merge.py``); manual entry edits the project directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------- vocab

#: Card categories. ``color`` drives the card glow and the key.
KINDS: Dict[str, Dict[str, str]] = {
    "source": {"label": "Sources", "color": "#2fd4b4"},
    "stage_io": {"label": "Stage I/O", "color": "#4ea8ff"},
    "computer": {"label": "Computers", "color": "#a98bff"},
    "console": {"label": "Consoles", "color": "#7c5cff"},
    "iem": {"label": "IEM gear", "color": "#f06aa8"},
    "pa": {"label": "PA · amps, speakers", "color": "#ff9548"},
    "network": {"label": "Dante network", "color": "#7b86ff"},
    "video": {"label": "Video", "color": "#c084fc"},
    "other": {"label": "Other", "color": "#9aa3b5"},
}

#: Cable / transport types. ``dash`` is an SVG stroke-dasharray ("" = solid).
MEDIA: Dict[str, Dict[str, Any]] = {
    "dante": {"label": "Dante · Cat6", "color": "#7b86ff", "dash": "", "width": 1.6, "arrow": False},
    "analog": {"label": "Analog · XLR", "color": "#aab3c5", "dash": "", "width": 1.4, "arrow": True},
    "aes3": {"label": "AES3 · 110 Ω", "color": "#2dd4ee", "dash": "7 4", "width": 1.5, "arrow": True},
    "aes50": {"label": "AES50 · Cat5e", "color": "#5ac8fa", "dash": "2 4", "width": 1.6, "arrow": False},
    "madi": {"label": "MADI", "color": "#fbbf24", "dash": "10 4", "width": 1.5, "arrow": True},
    "avb": {"label": "AVB / Milan", "color": "#34d399", "dash": "6 3 2 3", "width": 1.5, "arrow": False},
    "speaker": {"label": "Speaker · NL4/NL8", "color": "#ff9548", "dash": "", "width": 1.8, "arrow": True},
    "iem_wired": {"label": "Wired IEM", "color": "#f472b6", "dash": "1.5 4", "width": 1.6, "arrow": True},
    "iem_wireless": {"label": "Wireless IEM", "color": "#e879f9", "dash": "1.5 6", "width": 1.6, "arrow": True},
    "rf": {"label": "RF · wireless mic", "color": "#f0abfc", "dash": "1.5 6", "width": 1.6, "arrow": True},
    "usb": {"label": "USB", "color": "#cbd5e1", "dash": "4 3", "width": 1.2, "arrow": True},
    "video": {"label": "SDI / HDMI", "color": "#c084fc", "dash": "", "width": 1.2, "arrow": True},
    "network": {"label": "Control · IP", "color": "#94a3b8", "dash": "3 3", "width": 1.0, "arrow": False},
    "other": {"label": "Other", "color": "#9aa3b5", "dash": "", "width": 1.2, "arrow": True},
}

#: Brand badges: text pill drawn on the card's top-right. Text only, no logos.
BRANDS: Dict[str, Dict[str, str]] = {
    "yamaha": {"text": "YAMAHA", "bg": "#1a1a1a", "fg": "#ffffff", "style": "wordmark"},
    "shure": {"text": "SHURE", "bg": "#f3f4f6", "fg": "#111111", "style": "bold-italic"},
    "focusrite": {"text": "Focusrite", "bg": "#f3f4f6", "fg": "#c2410c", "style": "serif"},
    "neve": {"text": "N", "bg": "#d7263d", "fg": "#ffffff", "style": "mono"},
    "ross": {"text": "ROSS", "bg": "#f3f4f6", "fg": "#c01830", "style": "bold"},
    "genelec": {"text": "GENELEC", "bg": "#ffffff", "fg": "#0b6e4f", "style": "bold"},
    "waves": {"text": "W", "bg": "#111111", "fg": "#ffffff", "style": "mono"},
    "ableton": {"text": "▮▮▮", "bg": "#f3f4f6", "fg": "#111111", "style": "mono"},
    "avid": {"text": "AVID", "bg": "#7c3aed", "fg": "#ffffff", "style": "bold"},
    "l-acoustics": {"text": "L-A", "bg": "#f3f4f6", "fg": "#111111", "style": "mono"},
    "lectrosonics": {"text": "LECTRO", "bg": "#1f2937", "fg": "#e5e7eb", "style": "bold"},
    "behringer": {"text": "BEHRINGER", "bg": "#1f2937", "fg": "#facc15", "style": "bold"},
    "midas": {"text": "MIDAS", "bg": "#1f2937", "fg": "#e5e7eb", "style": "bold"},
    "sennheiser": {"text": "SENNHEISER", "bg": "#111111", "fg": "#ffffff", "style": "bold"},
    "allen-heath": {"text": "A&H", "bg": "#111111", "fg": "#ffffff", "style": "bold"},
    "digico": {"text": "DiGiCo", "bg": "#111111", "fg": "#ffffff", "style": "bold"},
    "qsc": {"text": "QSC", "bg": "#111111", "fg": "#60a5fa", "style": "bold"},
    "powersoft": {"text": "POWERSOFT", "bg": "#111111", "fg": "#ffffff", "style": "bold"},
    "d&b": {"text": "d&b", "bg": "#f3f4f6", "fg": "#111111", "style": "bold"},
    "meyer": {"text": "MEYER", "bg": "#f3f4f6", "fg": "#111111", "style": "bold"},
    "audinate": {"text": "Dante", "bg": "#1d4ed8", "fg": "#ffffff", "style": "bold"},
    "blackmagic": {"text": "BMD", "bg": "#111111", "fg": "#f59e0b", "style": "bold"},
    "apple": {"text": "", "bg": "#f3f4f6", "fg": "#111111", "style": "mono"},
    "microsoft": {"text": "MS", "bg": "#f3f4f6", "fg": "#111111", "style": "bold"},
}

DEFAULT_COLUMNS: List[Dict[str, str]] = [
    {"id": "sources", "label": "Sources", "side": "left"},
    {"id": "stage_io", "label": "Stage I/O", "side": "left"},
    {"id": "dante", "label": "Dante", "side": "spine"},
    {"id": "mix", "label": "Mix & Dante", "side": "right"},
    {"id": "amps", "label": "Amps · TX", "side": "right"},
    {"id": "outputs", "label": "Speakers · IEMs", "side": "right"},
]

DEFAULT_INTRO = (
    "Read it left to right. Sources plug into stage boxes, everything meets on "
    "the one Dante network in the middle, and the consoles send mixes out to "
    "the PA, the IEMs and broadcast. Card glow shows the equipment type and "
    "line style shows the cable."
)
DEFAULT_FOOTNOTE = (
    "Arrows show signal direction. Dante is two-way; every dot on the center "
    "bar is one Dante port."
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    """Lowercase identifier: ``'Rio3224-D #1' -> 'rio3224-d-1'``."""
    s = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return s or "item"


def norm_name(text: str) -> str:
    """Loose match key: letters and digits only, lowercase."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


# ------------------------------------------------------------- dataclasses


@dataclass
class Column:
    id: str
    label: str
    side: str = "left"  # left | spine | right

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "label": self.label, "side": self.side}


@dataclass
class Group:
    id: str
    label: str
    side: str = "left"  # left | right
    note: str = ""
    order: int = 0
    auto: bool = False  # created by merge for unplaced imported devices

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"id": self.id, "label": self.label, "side": self.side}
        if self.note:
            d["note"] = self.note
        if self.order:
            d["order"] = self.order
        if self.auto:
            d["auto"] = True
        return d


@dataclass
class Node:
    id: str
    label: str
    sub: str = ""
    lines: List[str] = field(default_factory=list)  # extra card lines (tall cards)
    kind: str = "other"
    brand: str = ""
    group: str = ""
    column: str = ""
    dante: bool = False
    dante_name: str = ""
    aliases: List[str] = field(default_factory=list)
    count: Optional[int] = None
    suffix: str = ""
    order: int = 0
    icon: str = ""  # optional small glyph key (e.g. "amp", "speaker", "laptop")
    note: str = ""  # tooltip-only free text
    #: id of another node this card *is* (same physical device drawn twice,
    #: e.g. a stage box shown on the input side and again on the output side)
    ref: str = ""
    #: declared port groups (optional, Knox-style patch sheets):
    #: [{"name": "Analog In", "direction": "in", "medium": "analog", "count": 32}]
    #: or with explicit labels: {"name": "AES Out", "direction": "out", "medium": "aes3", "labels": ["L/R", "Sub"]}
    ports: List[Dict[str, Any]] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)  # filled by merge (channels, racks, dante)
    auto: bool = False  # created by merge

    @property
    def title(self) -> str:
        t = self.label
        if self.count:
            t += f" ×{self.count}"
        if self.suffix:
            t += f" {self.suffix}"
        return t

    def match_keys(self) -> List[str]:
        keys = [self.id, self.label, self.dante_name] + list(self.aliases)
        return [norm_name(k) for k in keys if k]

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"id": self.id, "label": self.label}
        for k in ("sub", "kind", "brand", "group", "column", "dante_name", "suffix", "icon", "note", "ref"):
            v = getattr(self, k)
            if v:
                d[k] = v
        if self.lines:
            d["lines"] = list(self.lines)
        if self.dante:
            d["dante"] = True
        if self.aliases:
            d["aliases"] = list(self.aliases)
        if self.count is not None:
            d["count"] = self.count
        if self.order:
            d["order"] = self.order
        if self.ports:
            d["ports"] = [dict(p) for p in self.ports]
        if self.auto:
            d["auto"] = True
        return d


@dataclass
class Link:
    source: str
    target: str
    medium: str = "analog"
    label: str = ""
    count: Optional[int] = None
    note: str = ""
    bidirectional: bool = False
    from_port: str = ""  # e.g. "Analog Out 1-8", "AES 1/2", "Dante 12"
    to_port: str = ""  # e.g. "Omni In 1-8", "AES In A"
    signal: str = ""  # what travels on it: "Kick, Snare, ...", "Main L/R"
    auto: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"from": self.source, "to": self.target, "medium": self.medium}
        for k in ("label", "note", "from_port", "to_port", "signal"):
            v = getattr(self, k)
            if v:
                d[k] = v
        if self.count is not None:
            d["count"] = self.count
        if self.bidirectional:
            d["bidirectional"] = True
        if self.auto:
            d["auto"] = True
        return d


@dataclass
class ImportSpec:
    kind: str  # yamaha | dante | waves | auto
    path: str  # relative to the project folder (or absolute)
    node: str = ""  # node id the data attaches to (yamaha / waves)
    label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"kind": self.kind, "path": self.path}
        if self.node:
            d["node"] = self.node
        if self.label:
            d["label"] = self.label
        return d


@dataclass
class Options:
    auto_dante_nodes: bool = True  # add cards for Dante devices that are not in nodes
    auto_sources: bool = False  # build source cards from the console channel list
    dante_counts: bool = False  # label Dante stubs with tx/rx channel counts
    appendix: bool = True  # tables under the diagram (channels, routing, racks)
    appendix_print: bool = False  # include the appendix when printing
    card_width: int = 196
    column_gap: int = 72

    def to_dict(self) -> Dict[str, Any]:
        return {
            "auto_dante_nodes": self.auto_dante_nodes,
            "auto_sources": self.auto_sources,
            "dante_counts": self.dante_counts,
            "appendix": self.appendix,
            "appendix_print": self.appendix_print,
            "card_width": self.card_width,
            "column_gap": self.column_gap,
        }


@dataclass
class Meta:
    org: str = ""
    system: str = "Audio system"
    title: str = "Signal flow, mic to speaker"
    intro: str = DEFAULT_INTRO
    footnote: str = DEFAULT_FOOTNOTE
    slug: str = ""
    version: str = ""
    author: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {"org": self.org, "system": self.system, "title": self.title, "intro": self.intro, "footnote": self.footnote}
        for k in ("slug", "version", "author"):
            v = getattr(self, k)
            if v:
                d[k] = v
        return d


@dataclass
class Project:
    meta: Meta = field(default_factory=Meta)
    columns: List[Column] = field(default_factory=list)
    groups: List[Group] = field(default_factory=list)
    nodes: List[Node] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    imports: List[ImportSpec] = field(default_factory=list)
    options: Options = field(default_factory=Options)
    spine_label: str = "Dante network"
    spine_show: bool = True
    #: per-project overrides of MEDIA entries, e.g. {"analog": {"label": "Analog · XLR/TRS"}}
    media_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: merge diagnostics (not persisted)
    notes: List[str] = field(default_factory=list)
    #: appendix tables filled by merge: {"console": [...], "dante": [...], "waves": [...]}
    appendix: Dict[str, Any] = field(default_factory=dict)
    #: channel-level patch rows gathered by merge (Dante subscriptions, console patch);
    #: each: {"device": node_id, "dir": "in"|"out", "port": str, "medium": str,
    #:        "peer": node_id or "", "peer_name": str, "peer_port": str, "signal": str, "source": "dante"|"console"}
    patch_rows: List[Dict[str, Any]] = field(default_factory=list)

    def medium(self, key: str) -> Dict[str, Any]:
        base = dict(MEDIA.get(key, MEDIA["other"]))
        base.update(self.media_overrides.get(key, {}))
        return base

    # ---- lookups
    def node(self, node_id: str) -> Optional[Node]:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def group(self, group_id: str) -> Optional[Group]:
        for g in self.groups:
            if g.id == group_id:
                return g
        return None

    def column(self, column_id: str) -> Optional[Column]:
        for c in self.columns:
            if c.id == column_id:
                return c
        return None

    def columns_for_side(self, side: str) -> List[Column]:
        return [c for c in self.columns if c.side == side]

    def groups_for_side(self, side: str) -> List[Group]:
        gs = [g for g in self.groups if g.side == side]
        return sorted(gs, key=lambda g: (g.order, self.groups.index(g)))

    def find_node_by_name(self, name: str) -> Optional[Node]:
        key = norm_name(name)
        if not key:
            return None
        for n in self.nodes:
            if key in n.match_keys():
                return self.canonical(n)
        return None

    def canonical(self, node: Node) -> Node:
        """Follow ``ref`` to the primary card of a device drawn more than once."""
        seen = set()
        while node.ref and node.ref not in seen:
            seen.add(node.id)
            target = self.node(node.ref)
            if target is None:
                break
            node = target
        return node

    def canon_id(self, node_id: str) -> str:
        n = self.node(node_id)
        return self.canonical(n).id if n else node_id

    def ref_map(self) -> Dict[str, str]:
        """ref card id → primary card id."""
        return {n.id: self.canon_id(n.id) for n in self.nodes if n.ref}

    def ensure_group(self, group_id: str, label: str, side: str, note: str = "", auto: bool = False) -> Group:
        g = self.group(group_id)
        if g:
            return g
        g = Group(id=group_id, label=label, side=side, note=note, order=999, auto=auto)
        self.groups.append(g)
        return g

    def used_kinds(self) -> List[str]:
        seen: List[str] = []
        for n in self.nodes:
            k = n.kind if n.kind in KINDS else "other"
            if k not in seen:
                seen.append(k)
        if any(n.dante for n in self.nodes) and self.spine_show and "network" not in seen:
            seen.append("network")
        return [k for k in KINDS if k in seen]

    def used_media(self) -> List[str]:
        seen = {l.medium if l.medium in MEDIA else "other" for l in self.links}
        if any(n.dante for n in self.nodes) and self.spine_show:
            seen.add("dante")
        return [m for m in MEDIA if m in seen]

    # ---- (de)serialisation
    def to_dict(self) -> Dict[str, Any]:
        return {
            "fathom": 1,
            "meta": self.meta.to_dict(),
            "spine": {"label": self.spine_label, "show": self.spine_show},
            "columns": [c.to_dict() for c in self.columns],
            "groups": [g.to_dict() for g in self.groups if not g.auto],
            "nodes": [n.to_dict() for n in self.nodes if not n.auto],
            "links": [l.to_dict() for l in self.links if not l.auto],
            "imports": [i.to_dict() for i in self.imports],
            "options": self.options.to_dict(),
            **({"media": self.media_overrides} if self.media_overrides else {}),
        }


# ------------------------------------------------------------ dict -> model


def _as_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [p.strip() for p in v.split("\n") if p.strip()] if "\n" in v else [v]
    return [str(x) for x in v]


def project_from_dict(d: Dict[str, Any]) -> Project:
    """Build a Project from a plain dict (JSON / TOML / YAML). Tolerant of gaps."""
    d = d or {}
    meta_d = d.get("meta") or {}
    meta = Meta(
        org=str(meta_d.get("org", "") or ""),
        system=str(meta_d.get("system", "Audio system") or "Audio system"),
        title=str(meta_d.get("title", "Signal flow, mic to speaker") or "Signal flow, mic to speaker"),
        intro=str(meta_d.get("intro", DEFAULT_INTRO) if meta_d.get("intro") is not None else DEFAULT_INTRO),
        footnote=str(meta_d.get("footnote", DEFAULT_FOOTNOTE) if meta_d.get("footnote") is not None else DEFAULT_FOOTNOTE),
        slug=str(meta_d.get("slug", "") or ""),
        version=str(meta_d.get("version", "") or ""),
        author=str(meta_d.get("author", "") or ""),
    )
    cols_raw = d.get("columns") or DEFAULT_COLUMNS
    columns = [Column(id=str(c["id"]), label=str(c.get("label", c["id"])), side=str(c.get("side", "left"))) for c in cols_raw]
    groups = []
    for i, g in enumerate(d.get("groups") or []):
        groups.append(
            Group(
                id=str(g.get("id") or chr(ord("A") + i)),
                label=str(g.get("label", "")),
                side=str(g.get("side", "left")),
                note=str(g.get("note", "") or ""),
                order=_as_int(g.get("order")) or 0,
                auto=bool(g.get("auto", False)),
            )
        )
    nodes = []
    for n in d.get("nodes") or []:
        if not n.get("id") and not n.get("label"):
            continue
        nid = str(n.get("id") or slug(str(n.get("label"))))
        nodes.append(
            Node(
                id=nid,
                label=str(n.get("label") or nid),
                sub=str(n.get("sub", "") or ""),
                lines=_as_list(n.get("lines")),
                kind=str(n.get("kind", "other") or "other"),
                brand=str(n.get("brand", "") or "").lower(),
                group=str(n.get("group", "") or ""),
                column=str(n.get("column", "") or ""),
                dante=bool(n.get("dante", False)),
                dante_name=str(n.get("dante_name", "") or ""),
                aliases=_as_list(n.get("aliases")),
                count=_as_int(n.get("count")),
                suffix=str(n.get("suffix", "") or ""),
                order=_as_int(n.get("order")) or 0,
                icon=str(n.get("icon", "") or ""),
                note=str(n.get("note", "") or ""),
                ref=str(n.get("ref", "") or ""),
                ports=[dict(p) for p in (n.get("ports") or []) if isinstance(p, dict)],
                auto=bool(n.get("auto", False)),
            )
        )
    links = []
    for l in d.get("links") or []:
        src = l.get("from") or l.get("source")
        dst = l.get("to") or l.get("target")
        if not src or not dst:
            continue
        links.append(
            Link(
                source=str(src),
                target=str(dst),
                medium=str(l.get("medium", "analog") or "analog"),
                label=str(l.get("label", "") or ""),
                count=_as_int(l.get("count")),
                note=str(l.get("note", "") or ""),
                bidirectional=bool(l.get("bidirectional", False)),
                from_port=str(l.get("from_port", "") or l.get("source_port", "") or ""),
                to_port=str(l.get("to_port", "") or l.get("target_port", "") or ""),
                signal=str(l.get("signal", "") or ""),
                auto=bool(l.get("auto", False)),
            )
        )
    imports = []
    for i in d.get("imports") or []:
        if not i.get("path"):
            continue
        imports.append(
            ImportSpec(
                kind=str(i.get("kind", "auto") or "auto"),
                path=str(i["path"]),
                node=str(i.get("node", "") or ""),
                label=str(i.get("label", "") or ""),
            )
        )
    opt_d = d.get("options") or {}
    options = Options(
        auto_dante_nodes=bool(opt_d.get("auto_dante_nodes", True)),
        auto_sources=bool(opt_d.get("auto_sources", False)),
        dante_counts=bool(opt_d.get("dante_counts", False)),
        appendix=bool(opt_d.get("appendix", True)),
        appendix_print=bool(opt_d.get("appendix_print", False)),
        card_width=_as_int(opt_d.get("card_width")) or 196,
        column_gap=_as_int(opt_d.get("column_gap")) or 72,
    )
    spine = d.get("spine") or {}
    proj = Project(
        meta=meta,
        columns=columns,
        groups=groups,
        nodes=nodes,
        links=links,
        imports=imports,
        options=options,
        spine_label=str(spine.get("label", "Dante network") or "Dante network"),
        spine_show=bool(spine.get("show", True)),
        media_overrides={str(k): dict(v) for k, v in (d.get("media") or {}).items() if isinstance(v, dict)},
    )
    return proj


def validate(project: Project) -> List[str]:
    """Return human-readable problems (empty list = fine)."""
    problems: List[str] = []
    ids = [n.id for n in project.nodes]
    dupes = {i for i in ids if ids.count(i) > 1}
    for dup in sorted(dupes):
        problems.append(f"duplicate node id: {dup}")
    group_ids = {g.id for g in project.groups}
    col_ids = {c.id for c in project.columns}
    for n in project.nodes:
        if n.group and n.group not in group_ids:
            problems.append(f"node {n.id}: unknown group '{n.group}'")
        if n.column and n.column not in col_ids:
            problems.append(f"node {n.id}: unknown column '{n.column}'")
        if n.kind not in KINDS:
            problems.append(f"node {n.id}: unknown kind '{n.kind}' (one of {', '.join(KINDS)})")
        if n.ref and n.ref not in ids:
            problems.append(f"node {n.id}: ref '{n.ref}' is not a node id")
    node_ids = set(ids)
    for l in project.links:
        if l.source not in node_ids:
            problems.append(f"link {l.source} → {l.target}: unknown node '{l.source}'")
        if l.target not in node_ids:
            problems.append(f"link {l.source} → {l.target}: unknown node '{l.target}'")
        if l.medium not in MEDIA:
            problems.append(f"link {l.source} → {l.target}: unknown medium '{l.medium}' (one of {', '.join(MEDIA)})")
    for g in project.groups:
        if g.side not in ("left", "right"):
            problems.append(f"group {g.id}: side must be left or right")
    return problems


# ------------------------------------------------------- vocab (0.3, W2)
# The full AVL vocabulary lives in ``fathom.vocab``; the inline dicts above are
# the v1 fallback used until it is importable. Imported last so ``vocab`` may
# itself import helpers from this module.

try:
    from .vocab import BRANDS as _V_BRANDS, KINDS as _V_KINDS, MEDIA as _V_MEDIA  # type: ignore

    if _V_KINDS and _V_MEDIA and _V_BRANDS:
        KINDS = _V_KINDS  # type: ignore[assignment]
        MEDIA = _V_MEDIA
        BRANDS = _V_BRANDS  # type: ignore[assignment]
except Exception:  # pragma: no cover - vocab not there yet / broken
    pass
