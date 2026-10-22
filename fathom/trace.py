"""Signal tracing over the project graph (cards + cables + Dante flows).

``find_paths`` answers "how does X get to Y"; ``downstream`` / ``upstream``
answer "where does X go" / "what feeds Y". Edges come from manual links
(respecting direction, or both ways when ``bidirectional``), Dante
subscriptions (transmitter card → receiver card) and the console's output
patch (console → receiving card).

v2 (port level, SPEC §6.9): ``port_graph`` builds a graph whose nodes are
``dev:port`` refs (plus ``dev:*`` for device-level cable ends) with cable,
device-internal (routing mode per kind) and overlay-route edges;
``upstream_paths`` / ``downstream_paths`` / ``port_paths`` search it and
``path_text`` renders a path the way the assistant shows it.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from .model import Node, Project, norm_name, slug


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    medium: str
    label: str  # "8 ch", "AES · L/R", "Dante · 32 ch"
    via: str  # link | dante | console


def build_graph(project: Project) -> Dict[str, List[Edge]]:
    """Directed edges between *primary* cards (``ref`` cards collapse into their device)."""
    graph: Dict[str, List[Edge]] = {n.id: [] for n in project.nodes if not n.ref}
    seen: Set[Tuple[str, str, str]] = set()
    pairs: Set[Tuple[str, str]] = set()

    def add(src: str, dst: str, medium: str, label: str, via: str, unique_pair: bool = False) -> None:
        src, dst = project.canon_id(src), project.canon_id(dst)
        if src not in graph or dst not in graph or src == dst:
            return
        if unique_pair and (src, dst) in pairs:
            return  # a manual link or Dante flow already covers this hop
        key = (src, dst, medium)
        if key in seen:
            return
        seen.add(key)
        pairs.add((src, dst))
        graph[src].append(Edge(src, dst, medium, label, via))

    for l in project.links:
        label = l.label or (f"{l.count} ch" if l.count else "")
        add(l.source, l.target, l.medium, label, "link")
        if l.bidirectional:
            add(l.target, l.source, l.medium, label, "link")
    for n in project.nodes:
        for f in n.detail.get("dante_flows", []):
            if f.get("dir") == "out" and f.get("peer_id"):
                add(n.id, f["peer_id"], "dante", f"{f['count']} ch", "dante", unique_pair=True)
    for r in project.patch_rows:
        if r.get("source") == "console" and r.get("dir") == "out" and r.get("peer"):
            add(r["device"], r["peer"], r.get("medium", "dante"), r.get("port", ""), "console", unique_pair=True)
    return graph


def reverse_graph(graph: Dict[str, List[Edge]]) -> Dict[str, List[Edge]]:
    rev: Dict[str, List[Edge]] = {k: [] for k in graph}
    for edges in graph.values():
        for e in edges:
            rev.setdefault(e.dst, []).append(e)
    return rev


def resolve_node(project: Project, text: str) -> Optional[Node]:
    """Node by id, exact name / alias, then unique substring match."""
    if not text:
        return None
    n = project.node(text) or project.find_node_by_name(text)
    if n:
        return project.canonical(n)
    key = norm_name(text)
    hits = [n for n in project.nodes if key and (key in norm_name(n.label) or key in norm_name(n.id) or key in norm_name(n.title))]
    hits = list({project.canonical(h).id: project.canonical(h) for h in hits}.values())
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        exact = [h for h in hits if norm_name(h.label) == key]
        if len(exact) == 1:
            return exact[0]
    return None


def find_paths(project: Project, src: str, dst: str, max_depth: int = 8, limit: int = 25) -> List[List[Edge]]:
    graph = build_graph(project)
    paths: List[List[Edge]] = []

    def dfs(node: str, path: List[Edge], visited: Set[str]) -> None:
        if len(paths) >= limit or len(path) > max_depth:
            return
        if node == dst and path:
            paths.append(list(path))
            return
        for e in graph.get(node, []):
            if e.dst in visited:
                continue
            visited.add(e.dst)
            path.append(e)
            dfs(e.dst, path, visited)
            path.pop()
            visited.discard(e.dst)

    dfs(src, [], {src})
    paths.sort(key=len)
    return paths


def downstream(project: Project, src: str, max_depth: int = 8) -> List[List[Edge]]:
    """Every simple path leaving ``src`` that ends at a card with no further outputs."""
    graph = build_graph(project)
    out: List[List[Edge]] = []

    def dfs(node: str, path: List[Edge], visited: Set[str]) -> None:
        edges = [e for e in graph.get(node, []) if e.dst not in visited]
        if (not edges or len(path) >= max_depth) and path:
            out.append(list(path))
            return
        for e in edges:
            visited.add(e.dst)
            path.append(e)
            dfs(e.dst, path, visited)
            path.pop()
            visited.discard(e.dst)

    dfs(src, [], {src})
    return out


def upstream(project: Project, dst: str, max_depth: int = 8) -> List[List[Edge]]:
    rev = reverse_graph(build_graph(project))
    out: List[List[Edge]] = []

    def dfs(node: str, path: List[Edge], visited: Set[str]) -> None:
        edges = [e for e in rev.get(node, []) if e.src not in visited]
        if (not edges or len(path) >= max_depth) and path:
            out.append(list(reversed(path)))
            return
        for e in edges:
            visited.add(e.src)
            path.append(e)
            dfs(e.src, path, visited)
            path.pop()
            visited.discard(e.src)

    dfs(dst, [], {dst})
    return out


def describe_path(project: Project, path: List[Edge]) -> str:
    if not path:
        return ""
    parts = [project.node(path[0].src).label if project.node(path[0].src) else path[0].src]
    for e in path:
        med = project.medium(e.medium)["label"]
        detail = f"{med}{(' · ' + e.label) if e.label and e.label not in med else ''}"
        dst = project.node(e.dst)
        parts.append(f"—[{detail}]→ {dst.label if dst else e.dst}")
    return " ".join(parts)


def graph_json(project: Project) -> List[Dict[str, str]]:
    """Edges for the in-page tracer."""
    return [{"s": e.src, "d": e.dst, "m": e.medium, "l": e.label, "v": e.via} for edges in build_graph(project).values() for e in edges]


# ===================================================================== v2: port-level graph (SPEC §6.9)

Doc = Dict[str, Any]

ALL_DISCIPLINES: Tuple[str, ...] = ("audio", "video", "lighting", "network", "control", "power", "other")
_STEM_DROP = {"in", "input", "inputs", "out", "output", "outputs", "thru", "through", "loop"}


def _vocab() -> Any:
    try:
        from . import vocab  # W2; optional at import time
        return vocab
    except Exception:  # pragma: no cover - vocab not landed yet
        return None


def carries(medium: str) -> Tuple[str, ...]:
    """Disciplines a medium carries (vocab ``carries``; unknown → ``("other",)``)."""
    v = _vocab()
    if v is not None:
        return tuple(v.medium_carries(medium or ""))
    return ALL_DISCIPLINES


def kind_routing(kind: str) -> str:
    v = _vocab()
    if v is not None and hasattr(v, "kind_routing"):
        return str(v.kind_routing(kind or ""))
    return "matrix"


def medium_label(medium: str) -> str:
    v = _vocab()
    if v is not None:
        m = v.MEDIA.get(medium or "")
        if m:
            return str(m.get("label") or medium)
    return medium or ""


def device_discipline(dev: Dict[str, Any]) -> str:
    if dev.get("discipline"):
        return str(dev["discipline"])
    v = _vocab()
    if v is not None:
        return v.kind_discipline(dev.get("kind") or "")
    return "other"


def status_included(status: Optional[str], state: str = "all") -> bool:
    """§4.4.6 state filter for one status value (default ``installed``)."""
    st = status or "installed"
    if state == "everything":
        return True
    if state == "as_built":
        return st == "installed"
    if state == "planned":
        return st in ("planned", "installed")
    return st != "retired"


def doc_devices(doc: Doc, overlay: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Doc devices followed by overlay (auto) devices whose ids are not taken."""
    out = [d for d in (doc.get("devices") or []) if isinstance(d, dict) and d.get("id")]
    if overlay:
        ids = {d["id"] for d in out}
        for d in overlay.get("devices") or []:
            if isinstance(d, dict) and d.get("id") and d["id"] not in ids:
                out.append(d)
                ids.add(d["id"])
    return out


def device_map(doc: Doc, overlay: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    return {d["id"]: d for d in doc_devices(doc, overlay)}


def device_ports(dev: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not dev:
        return []
    return [p for p in (dev.get("ports") or []) if isinstance(p, dict) and p.get("id")]


def find_port(dev: Optional[Dict[str, Any]], port_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not port_id:
        return None
    for p in device_ports(dev):
        if p["id"] == port_id:
            return p
    return None


def port_label(port: Optional[Dict[str, Any]]) -> str:
    if not port:
        return ""
    return str(port.get("label") or port.get("name") or port.get("id") or "")


def _stem(group: str) -> str:
    return "-".join(t for t in slug(group or "").split("-") if t and t not in _STEM_DROP)


def _port_index(p: Dict[str, Any], ports: List[Dict[str, Any]]) -> int:
    if isinstance(p.get("index"), int) and p["index"] > 0:
        return int(p["index"])
    n = 0
    for q in ports:
        if (q.get("group") or "") == (p.get("group") or ""):
            n += 1
        if q is p:
            return n
    return n


def routing_mode(dev: Dict[str, Any], doc: Optional[Doc] = None) -> str:
    """Device routing mode: its own ``routing``, else its library template's, else the kind default."""
    r = dev.get("routing")
    mode = r.get("mode") if isinstance(r, dict) else (r if isinstance(r, str) else None)
    if not mode and dev.get("template"):
        try:
            from .library import get_template

            t = get_template(str(dev["template"]), doc)
        except Exception:  # pragma: no cover
            t = None
        tr = (t or {}).get("routing")
        mode = tr.get("mode") if isinstance(tr, dict) else (tr if isinstance(tr, str) else None)
    return str(mode or kind_routing(dev.get("kind") or ""))


def internal_pairs(dev: Dict[str, Any], discipline: Optional[str] = None, mode: Optional[str] = None) -> List[Tuple[str, str]]:
    """Device internal edges ``(in_port, out_port)`` by routing mode (§4.4.5), discipline-filtered."""
    ports = device_ports(dev)
    mode = mode or routing_mode(dev)
    if mode == "none":
        return []
    byid = {p["id"]: p for p in ports}

    def ok_both(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        if discipline is None:
            return True
        return discipline in carries(a.get("medium", "")) and discipline in carries(b.get("medium", ""))

    out: List[Tuple[str, str]] = []
    if mode == "explicit":
        r = dev.get("routing") if isinstance(dev.get("routing"), dict) else {}
        for pair in r.get("map") or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] in byid and pair[1] in byid and pair[0] != pair[1]:
                if ok_both(byid[pair[0]], byid[pair[1]]):
                    out.append((str(pair[0]), str(pair[1])))
        return out
    ins = [p for p in ports if p.get("dir") in ("in", "io")]
    outs = [p for p in ports if p.get("dir") in ("out", "io")]
    if mode == "passthrough":
        in_count: Dict[str, int] = {}
        for p in ports:
            if p.get("dir") == "in":
                g = p.get("group") or ""
                in_count[g] = in_count.get(g, 0) + 1
        for a in ins:
            for b in outs:
                if a is b or a.get("medium") != b.get("medium"):
                    continue
                ga, gb = a.get("group") or "", b.get("group") or ""
                if ga == gb:
                    pair_ok = in_count.get(ga, 0) == 1
                else:
                    pair_ok = _port_index(a, ports) == _port_index(b, ports) and _stem(ga) == _stem(gb)
                if pair_ok and ok_both(a, b):
                    out.append((a["id"], b["id"]))
        return out
    # matrix (default for unknown modes)
    for a in ins:
        ca = set(carries(a.get("medium", "")))
        for b in outs:
            if a is b:
                continue
            common = ca & set(carries(b.get("medium", "")))
            if discipline is not None:
                common &= {discipline}
            if common:
                out.append((a["id"], b["id"]))
    return out


@dataclass(frozen=True)
class PortEdge:
    src: str
    dst: str
    kind: str  # cable | internal | route | device | link
    cable: Optional[str]
    medium: str
    label: str = ""  # link kind for ``link`` edges (input_patch, send, …)


def node_ref(device: str, port: Optional[str]) -> str:
    return f"{device}:{port if port else '*'}"


def chan_ref(device: str, port: str, ch: int, direction: str) -> str:
    """Sub-channel node of a multichannel port: ``rio:dante-primary#tx6`` (signal leaving the device
    on channel 6) or ``foh:dante-primary#rx17`` (signal entering on channel 17)."""
    return f"{device}:{port}#{'rx' if direction == 'in' else 'tx'}{int(ch)}"


def console_ref(device: str, channel: str, tag: str = "") -> str:
    """Console channel node (§4.3.17): ``foh:@in-12``; rack sides carry their tag: ``foh:@fx-1.A``."""
    return f"{device}:@{channel}" + (f".{tag}" if tag else "")


def text_ref(device: str, text: str) -> str:
    return f"{device}:~{text}"


def hop_ref(hop: Dict[str, Any]) -> str:
    """Node ref of a path hop (inverse of ``parse_ref`` / ``_hop``)."""
    d = str(hop.get("device") or "")
    if hop.get("kind") in ("channel", "dca") and hop.get("channel"):
        return console_ref(d, str(hop["channel"]), str(hop.get("tag") or ""))
    if hop.get("kind") == "text" and hop.get("text") is not None:
        return text_ref(d, str(hop["text"]))
    if hop.get("port") and hop.get("ch") is not None:
        return chan_ref(d, str(hop["port"]), int(hop["ch"]), str(hop.get("dir") or "in"))
    return node_ref(d, hop.get("port"))


def parse_ref(node: str) -> Dict[str, Any]:
    """``{"device", "port", "ch", "dir", "channel", "text"}`` for any node ref (missing parts are ``None``)."""
    dev, _, rest = node.partition(":")
    out: Dict[str, Any] = {"device": dev, "port": None, "ch": None, "dir": None, "channel": None, "tag": None, "text": None}
    if rest in ("", "*"):
        return out
    if rest.startswith("@"):
        cid, _, tag = rest[1:].partition(".")
        out["channel"], out["tag"] = cid, (tag or None)
        return out
    if rest.startswith("~"):
        out["text"] = rest[1:]
        return out
    port, _, sub = rest.partition("#")
    out["port"] = port
    if sub:
        if sub.startswith("rx") or sub.startswith("tx"):
            out["dir"] = "in" if sub.startswith("rx") else "out"
            sub = sub[2:]
        if sub.isdigit():
            out["ch"] = int(sub)
    return out


def split_ref(node: str) -> Tuple[str, Optional[str]]:
    """``(device, port)``; sub-channel nodes report their port, console-channel and text nodes ``None``."""
    info = parse_ref(node)
    return info["device"], info["port"]


class PortGraph:
    """Directed port graph. Nodes are ``"dev:port"`` or ``"dev:*"`` (device level), plus sub-channel
    nodes ``dev:port#tx6`` / ``dev:port#rx17``, console channels ``dev:@in-12`` and unmapped console
    ports ``dev:~REC 1`` (§6.9.1)."""

    def __init__(self, doc: Doc, discipline: Optional[str] = None) -> None:
        self.doc = doc
        self.discipline = discipline or None
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.nodes: Dict[str, Tuple[str, Optional[str]]] = {}
        self._out: Dict[str, List[PortEdge]] = {}
        self._in: Dict[str, List[PortEdge]] = {}
        self._seen: Set[Tuple[str, str, str, Optional[str]]] = set()
        self.channels: Dict[str, Dict[str, Dict[str, Any]]] = {}  # device → channel id → channel
        self.control: Dict[str, Dict[str, List[str]]] = {}  # device → channel id → [dca / mute channel ids]
        self.channel_labels: Dict[str, Any] = {}  # overlay channel_labels (Dante names)
        self.sub_nodes: Dict[str, List[str]] = {}  # "dev:port" → its sub-channel node refs

    # -- queries
    def edges_out(self, node: str) -> List[PortEdge]:
        return list(self._out.get(node, ()))

    def edges_in(self, node: str) -> List[PortEdge]:
        return list(self._in.get(node, ()))

    def has_node(self, node: str) -> bool:
        return node in self.nodes

    def device_nodes(self, device: str) -> List[str]:
        return [n for n, (d, _) in self.nodes.items() if d == device]

    def edge_between(self, a: str, b: str) -> Optional[PortEdge]:
        best = None
        for e in self._out.get(a, ()):
            if e.dst == b:
                if e.kind == "cable":
                    return e
                best = best or e
        return best

    def cables_between(self, a: str, b: str) -> Optional[str]:
        e = self.edge_between(a, b)
        return e.cable if e and e.kind == "cable" else None

    # -- building
    def add_node(self, device: str, port: Optional[str]) -> str:
        ref = node_ref(device, port)
        if ref not in self.nodes:
            self.nodes[ref] = (device, port)
            self._out.setdefault(ref, [])
            self._in.setdefault(ref, [])
            if port is None:
                self._wire_device_node(device)
        return ref

    def _wire_device_node(self, device: str) -> None:
        """Directional device-level wiring: ``in``/``io`` port → ``dev:*`` → ``out``/``io`` port.

        Never ``out`` → ``dev:*`` and never ``dev:*`` → ``in``; routing mode ``none``
        gets no internal wiring (``dev:*`` then only carries its cable/route ends).
        """
        dev = self.devices.get(device)
        if dev is None or routing_mode(dev) == "none":
            return
        star = node_ref(device, None)
        for p in device_ports(dev):
            med = p.get("medium", "")
            if self.discipline is not None and self.discipline not in carries(med):
                continue
            ref = self.add_node(device, p["id"])
            if p.get("dir") in ("in", "io"):
                self.add_edge(ref, star, "device", None, med)
            if p.get("dir") in ("out", "io"):
                self.add_edge(star, ref, "device", None, med)

    def add_sub_node(self, ref: str) -> str:
        """Register a sub-channel / console-channel / text node (its device must be in the graph)."""
        if ref not in self.nodes:
            info = parse_ref(ref)
            self.nodes[ref] = (info["device"], info["port"])
            self._out.setdefault(ref, [])
            self._in.setdefault(ref, [])
            if info["port"] and info["ch"] is not None:
                self.sub_nodes.setdefault(node_ref(info["device"], info["port"]), []).append(ref)
            elif info["channel"] and info.get("tag"):
                self.sub_nodes.setdefault(console_ref(info["device"], info["channel"]), []).append(ref)
        return ref

    def chan_node(self, device: str, port: str, ch: Any, direction: str) -> Optional[str]:
        """Sub-channel node for ``port`` of ``device`` (``None`` for an unknown port, a bad channel
        number, a direction the port does not have, or a port with one channel)."""
        dev = self.devices.get(device)
        p = find_port(dev, port)
        if p is None or not isinstance(ch, int) or isinstance(ch, bool) or ch < 1 or int(p.get("channels") or 1) < 2:
            return None
        if ch > int(p.get("channels") or 1):
            return None
        pdir = p.get("dir", "io")
        if direction == "in" and pdir == "out" or direction == "out" and pdir == "in":
            return None
        if self.discipline is not None and self.discipline not in carries(p.get("medium", "")):
            return None
        return self.add_sub_node(chan_ref(device, port, ch, direction))

    def is_star(self, node: str) -> bool:
        return node.endswith(":*")

    def is_sub(self, node: str) -> bool:
        _, _, rest = node.partition(":")
        return "#" in rest or rest[:1] in ("@", "~")

    def walk_edges(self, path: Tuple[str, ...], forward: bool) -> List[PortEdge]:
        """Usable next edges from ``path[-1]`` for path search.

        At a ``dev:*`` node that was the start or was entered through a device edge,
        only cable/route edges continue (``port → dev:* → port`` would duplicate the
        device's own internal edges). A device edge into ``dev:*`` is only taken when
        ``dev:*`` can continue through a cable/route in the walk direction.
        """
        node = path[-1]
        edges = self._out.get(node, ()) if forward else self._in.get(node, ())
        if self.is_star(node) and (len(path) == 1 or split_ref(path[-2])[0] == split_ref(node)[0]):
            return [e for e in edges if e.kind != "device"]
        out = []
        for e in edges:
            nxt = e.dst if forward else e.src
            if e.kind == "device" and self.is_star(nxt):
                onward = self._out.get(nxt, ()) if forward else self._in.get(nxt, ())
                if not any(x.kind != "device" for x in onward):
                    continue
            out.append(e)
        return out

    def add_edge(self, src: str, dst: str, kind: str, cable: Optional[str], medium: str, label: str = "") -> None:
        if src == dst:
            return
        key = (src, dst, kind, cable or label or None)
        if key in self._seen:
            return
        self._seen.add(key)
        e = PortEdge(src, dst, kind, cable, medium, label)
        self._out.setdefault(src, []).append(e)
        self._in.setdefault(dst, []).append(e)


def _endpoint(g: PortGraph, end: Any) -> Optional[str]:
    if not isinstance(end, dict) or not end.get("device"):
        return None
    dev = g.devices.get(end["device"])
    if dev is None:
        return None
    port = end.get("port") or None
    if port and find_port(dev, port) is None:
        port = None  # dangling port → device level (§4.7 dangling_port)
    return g.add_node(dev["id"], port)


def _single_channel(p: Dict[str, Any]) -> bool:
    return int(p.get("channels") or 1) < 2


def _is_stream_port(p: Dict[str, Any]) -> bool:
    """A multichannel network / stream port (Dante 64, MADI 64, AES50 48 …) as opposed to a numbered
    connector that happens to carry two channels (AES3 out 1/2)."""
    if _single_channel(p):
        return False
    v = _vocab()
    net = set(getattr(v, "NETWORK_MEDIA", ())) if v is not None else set()
    return p.get("medium") in net or int(p.get("channels") or 1) > 2


def _indexed_edges(g: PortGraph, dev: Dict[str, Any]) -> None:
    """§4.4.5 ``indexed``: in connector *n* → sub-channel *n* of every multichannel out/io stream port,
    and sub-channel *n* of every multichannel in/io stream port → out connector *n*. *n* counts the
    device's connectors on that side in port order (a 2-channel AES connector takes two numbers)."""
    ports = device_ports(dev)
    disc = g.discipline

    def usable(p: Dict[str, Any]) -> bool:
        return disc is None or disc in carries(p.get("medium", ""))

    def first_per_medium(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Dante Primary / Secondary carry the same channels: wire the first (primary) port only
        seen_media: Set[str] = set()
        out = []
        for p in cands:
            if p.get("medium") not in seen_media:
                seen_media.add(str(p.get("medium")))
                out.append(p)
        return out

    multi_out = first_per_medium([p for p in ports if p.get("dir") in ("out", "io") and _is_stream_port(p) and usable(p)])
    multi_in = first_per_medium([p for p in ports if p.get("dir") in ("in", "io") and _is_stream_port(p) and usable(p)])
    for side, multis in (("in", multi_out), ("out", multi_in)):
        n = 0
        for p in ports:
            if p.get("dir") != side or not usable(p) or _is_stream_port(p):
                continue
            width = int(p.get("channels") or 1)
            for k in range(width):
                n += 1
                for m in multis:
                    if n > int(m.get("channels") or 1):
                        continue
                    pref = node_ref(dev["id"], p["id"])
                    if side == "in":
                        sub = g.chan_node(dev["id"], m["id"], n, "out")
                        if sub:
                            g.add_edge(pref, sub, "internal", None, p.get("medium", ""))
                    else:
                        sub = g.chan_node(dev["id"], m["id"], n, "in")
                        if sub:
                            g.add_edge(sub, pref, "internal", None, p.get("medium", ""))


def _link_node(g: PortGraph, dev_id: str, ep: Any, end: str) -> Optional[str]:
    """Node for a channel-link endpoint (§4.3.17): console channel, port sub-channel (``from`` = the
    signal enters → rx, ``to`` = leaves → tx), mono port, or a text node for unmapped console ports."""
    if not isinstance(ep, dict):
        return None
    if ep.get("channel"):
        cid = str(ep["channel"])
        if cid not in g.channels.get(dev_id, {}):
            return None
        return g.add_sub_node(console_ref(dev_id, cid, str(ep.get("tag") or "")))
    if ep.get("port"):
        dev = g.devices.get(dev_id)
        p = find_port(dev, str(ep["port"]))
        if p is None:
            return g.add_sub_node(text_ref(dev_id, str(ep["port"]) + (f" {ep['ch']}" if ep.get("ch") else "")))
        if g.discipline is not None and g.discipline not in carries(p.get("medium", "")):
            return None
        if ep.get("ch") and not _single_channel(p):
            return g.chan_node(dev_id, p["id"], int(ep["ch"]), "in" if end == "from" else "out")
        return g.add_node(dev_id, p["id"])
    if ep.get("text"):
        return g.add_sub_node(text_ref(dev_id, str(ep["text"])))
    return None


def _add_console(g: PortGraph, dev_id: str, channels: List[Dict[str, Any]], links: List[Dict[str, Any]]) -> None:
    """Console channel nodes and link edges for one device; ``dca`` / ``mute`` links are control only."""
    g.channels[dev_id] = {str(c["id"]): c for c in channels if isinstance(c, dict) and c.get("id")}
    for cid in g.channels[dev_id]:
        g.add_sub_node(console_ref(dev_id, cid))
    ctrl = g.control.setdefault(dev_id, {})
    for ln in links:
        if not isinstance(ln, dict):
            continue
        kind = str(ln.get("kind") or "")
        if kind in ("dca", "mute"):
            src, dst = ln.get("from") or {}, ln.get("to") or {}
            if isinstance(src, dict) and src.get("channel") and isinstance(dst, dict) and dst.get("channel"):
                lst = ctrl.setdefault(str(src["channel"]), [])
                if str(dst["channel"]) not in lst:
                    lst.append(str(dst["channel"]))
            continue
        a, b = _link_node(g, dev_id, ln.get("from"), "from"), _link_node(g, dev_id, ln.get("to"), "to")
        if a is not None and b is not None:
            g.add_edge(a, b, "link", None, "analog", kind or "link")


def _console_sets(doc: Doc, overlay: Optional[Dict[str, Any]], dev_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    try:
        from .console import effective_channels
    except Exception:  # pragma: no cover
        return [], []
    eff = effective_channels(doc, overlay, dev_id)
    return list(eff.get("channels") or []), list(eff.get("links") or [])


def port_graph(doc: Doc, overlay: Optional[Dict[str, Any]] = None, discipline: Optional[str] = None, state: str = "all") -> PortGraph:
    """Port graph of ``doc`` (+ overlay devices and routes) filtered by discipline and state (§6.9.1–6.9.3)."""
    g = PortGraph(doc, discipline)
    disc = g.discipline
    g.channel_labels = dict((overlay or {}).get("channel_labels") or {})
    for dev in doc_devices(doc, overlay):
        if status_included(dev.get("status"), state):
            g.devices[dev["id"]] = dev
    for dev in g.devices.values():
        for p in device_ports(dev):
            g.add_node(dev["id"], p["id"])
    consoles: Dict[str, Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]] = {}
    if disc in (None, "audio"):
        ov_ch = (overlay or {}).get("channels") or {}
        for dev in g.devices.values():
            if dev.get("channels") or dev.get("channel_links") or dev["id"] in ov_ch:
                chans, links = _console_sets(doc, overlay, dev["id"])
                if chans or links:
                    consoles[dev["id"]] = (chans, links)
    for c in doc.get("cables") or []:
        if not isinstance(c, dict) or not status_included(c.get("status"), state):
            continue
        a, b = _endpoint(g, c.get("from")), _endpoint(g, c.get("to"))
        if a is None or b is None:
            continue
        med = c.get("medium") or ""
        if disc is not None and disc not in carries(med):
            continue
        g.add_edge(a, b, "cable", c.get("id"), med)
        pa = find_port(g.devices[split_ref(a)[0]], split_ref(a)[1])
        pb = find_port(g.devices[split_ref(b)[0]], split_ref(b)[1])
        both_io = bool(pa and pb and pa.get("dir") == "io" and pb.get("dir") == "io")
        if c.get("bidirectional") or both_io:
            g.add_edge(b, a, "cable", c.get("id"), med)
    for dev in g.devices.values():
        if dev["id"] in consoles and consoles[dev["id"]][1]:
            continue  # the console's channel links are its routing (§6.9.3)
        mode = routing_mode(dev, doc)
        if mode == "indexed":
            _indexed_edges(g, dev)
            continue
        byid = {p["id"]: p for p in device_ports(dev)}
        for a, b in internal_pairs(dev, disc, mode):
            g.add_edge(node_ref(dev["id"], a), node_ref(dev["id"], b), "internal", None, byid[a].get("medium", ""))
    for dev_id, (chans, links) in consoles.items():
        _add_console(g, dev_id, chans, links)
    for r in (overlay or {}).get("routes") or []:
        if not isinstance(r, dict):
            continue
        med = r.get("medium") or "dante"
        if disc is not None and disc not in carries(med):
            continue
        a, b = _endpoint(g, r.get("from")), _endpoint(g, r.get("to"))
        if a is None or b is None:
            continue
        g.add_edge(a, b, "route", None, med)
        fr, to = r.get("from") or {}, r.get("to") or {}
        if isinstance(fr.get("ch"), int) and isinstance(to.get("ch"), int) and split_ref(a)[1] and split_ref(b)[1]:
            sa = g.chan_node(split_ref(a)[0], split_ref(a)[1] or "", fr["ch"], "out")
            sb = g.chan_node(split_ref(b)[0], split_ref(b)[1] or "", to["ch"], "in")
            if sa and sb:
                g.add_edge(sa, sb, "route", None, med)
    return g


def _start_nodes(g: PortGraph, ref: str, side: str) -> List[str]:
    """Nodes a ref stands for. ``dev:port`` is itself; ``dev:*`` or a bare device id expands
    to its ``in``/``io`` ports (``side="in"``) or ``out``/``io`` ports (``side="out"``),
    plus the ``dev:*`` node itself when it exists (device-level cable/route ends)."""
    info = parse_ref(ref) if ":" in ref else {"device": ref, "port": None, "ch": None, "dir": None, "channel": None, "text": None}
    dev_id, port = info["device"], info["port"]
    if info["channel"] is not None and not info.get("tag"):
        # an untagged rack ref stands for both of its sides (``@fx-1`` → ``@fx-1.A``, ``@fx-1.B``)
        out = [ref] if g.has_node(ref) else []
        return out + sorted(g.sub_nodes.get(ref, ()))
    if info["channel"] is not None or info["text"] is not None:
        return [ref] if g.has_node(ref) else []
    if port is not None and info["ch"] is not None:
        if info["dir"] is None:  # ``dev:port#17``: the side decides (leaving = tx, arriving = rx)
            first, second = ("out", "in") if side == "out" else ("in", "out")
            for d in (first, second):
                n = chan_ref(dev_id, port, info["ch"], d)
                if g.has_node(n):
                    return [n]
            return []
        return [ref] if g.has_node(ref) else []
    if port is not None:
        if not g.has_node(ref):
            return []
        want_dir = "out" if side == "out" else "in"
        subs = [n for n in g.sub_nodes.get(ref, ()) if parse_ref(n)["dir"] == want_dir]
        return [ref] + sorted(subs, key=lambda n: parse_ref(n)["ch"] or 0)
    dev = g.devices.get(dev_id)
    if dev is None:
        return []
    want = ("in", "io") if side == "in" else ("out", "io")
    out: List[str] = []
    for p in device_ports(dev):
        pref = node_ref(dev_id, p["id"])
        if p.get("dir") in want and g.has_node(pref):
            out.append(pref)
            out.extend(sorted((n for n in g.sub_nodes.get(pref, ()) if parse_ref(n)["dir"] == ("out" if side == "out" else "in")), key=lambda n: parse_ref(n)["ch"] or 0))
    star = node_ref(dev_id, None)
    if g.has_node(star):
        out.append(star)
    return out


def _console_mod() -> Any:
    try:
        from . import console
        return console
    except Exception:  # pragma: no cover
        return None


def _dante_name(g: PortGraph, device: str, port: str, ch: int, direction: str) -> str:
    labels = ((g.channel_labels.get(device) or {}).get(port) or {}).get(direction) or {}
    return str(labels.get(str(ch)) or "")


def _hop(g: PortGraph, node: str) -> Dict[str, Any]:
    """Hop dict for a node: ``{device, port}`` plus ``kind`` and, for sub-channel / console-channel
    hops, ``ch``/``dir``/``name`` or ``channel``/``title``/``name``/``dca`` (§6.9.4)."""
    info = parse_ref(node)
    d = info["device"]
    hop: Dict[str, Any] = {"device": d, "port": info["port"]}
    C = _console_mod()
    if info["channel"] is not None:
        ch = (g.channels.get(d) or {}).get(info["channel"]) or {"id": info["channel"], "kind": ""}
        hop.update({"kind": "channel", "channel": info["channel"], "channel_kind": ch.get("kind") or ""})
        hop["title"] = C.channel_title(ch) if C else info["channel"]
        if info.get("tag"):
            hop["tag"] = info["tag"]
            hop["title"] += f" {info['tag']}"
        if ch.get("name"):
            hop["name"] = str(ch["name"])
        ctrl = (g.control.get(d) or {}).get(info["channel"]) or []
        if ctrl:
            hop["dca"] = [{"channel": c, "title": (C.channel_title((g.channels.get(d) or {}).get(c) or {"id": c, "kind": "dca"}) if C else c)} for c in ctrl]
    elif info["text"] is not None:
        hop.update({"kind": "text", "text": info["text"]})
    elif info["ch"] is not None:
        hop.update({"kind": "port_channel", "ch": info["ch"], "dir": info["dir"]})
        name = _dante_name(g, d, info["port"] or "", info["ch"], info["dir"] or "in")
        if name:
            hop["name"] = name
    # plain port / device hops stay exactly ``{device, port}`` (§6.9.4, client traceLocal)
    return hop


def _via(e: Optional[PortEdge]) -> str:
    if e is None:
        return ""
    if e.kind == "cable":
        return f"cable:{e.cable}" if e.cable else "cable"
    if e.kind == "link":
        return f"link:{e.label or 'link'}"
    if e.kind == "route":
        return f"route:{e.medium or 'dante'}"
    return e.kind


def _path_dict(g: PortGraph, nodes: List[str]) -> Dict[str, Any]:
    """``{"hops", "cables", "via"}``; ``via[i]`` names the edge into hop *i* (``cable:<id>``, ``internal``,
    ``route:dante``, ``link:input_patch`` …; ``via[0]`` is ``""``)."""
    hops = [_hop(g, n) for n in nodes]
    cables: List[str] = []
    via: List[str] = [""]
    for a, b in zip(nodes, nodes[1:]):
        e = g.edge_between(a, b) or g.edge_between(b, a)
        via.append(_via(e))
        cid = g.cables_between(a, b) or g.cables_between(b, a)
        if cid and cid not in cables:
            cables.append(cid)
    return {"hops": hops, "cables": cables, "via": via}


_BUS_KINDS = ("mix", "aux", "group", "matrix", "stereo", "mono", "monitor", "cue")
_INPUT_KINDS = ("input", "stereo_input")


def gap_reason(g: PortGraph, node: str, forward: bool) -> str:
    """Why a path that dead-ends at ``node`` is incomplete (``""`` when the node is a natural end):
    a sub-channel with no Dante subscription, an input channel without recorded sends, a bus without an
    output patch, a receive channel that is not patched, or an output / input connector with no cable
    on a device that normally passes signal on."""
    info = parse_ref(node)
    dev = g.devices.get(info["device"]) or {}
    dname = str(dev.get("name") or info["device"])
    C = _console_mod()
    if info["channel"] is not None:
        ch = (g.channels.get(info["device"]) or {}).get(info["channel"]) or {"id": info["channel"], "kind": ""}
        title = (C.channel_title(ch) if C else info["channel"]) + (f" {info['tag']}" if info.get("tag") else "")
        kind = str(ch.get("kind") or "")
        if kind in _INPUT_KINDS:
            return f"no sends recorded for {title}" if forward else f"no input patch for {title}"
        if kind in _BUS_KINDS:
            return f"no output patch for {title}" if forward else f"nothing sent to {title}"
        if kind == "rack":
            return f"{title} return is not patched anywhere" if forward else f"nothing patched into {title}"
        return ""
    if info["text"] is not None:
        return ""
    port = find_port(dev, info["port"])
    plabel = port_label(port) or str(info["port"] or "")
    if info["ch"] is not None:
        name = _dante_name(g, info["device"], info["port"] or "", info["ch"], info["dir"] or "in")
        where = f"{dname} · {plabel} {info['ch']}" + (f" “{name}”" if name else "")
        net = (port or {}).get("medium") == "dante"
        has_console = bool(g.channels.get(info["device"]))
        if info["dir"] == "out":
            if forward:
                return f"no {'Dante subscriber' if net else 'route'} recorded for {where}"
            if has_console:
                return f"nothing patched to {where}"
            return f"no console patch data for {dname}" if dev.get("kind") == "console" else ""
        if forward:
            if has_console:
                return f"{where} is not patched to a channel"
            # a receiver without console data: the trace legitimately ends here unless it is a console
            return f"no console patch data for {dname}" if dev.get("kind") == "console" else ""
        return f"no {'Dante transmitter' if net else 'route'} recorded for {where}"
    if port is None:
        return ""
    if routing_mode(dev) in ("none", "passthrough"):
        return ""
    if forward and port.get("dir") in ("out", "io"):
        return f"nothing cabled from {dname} · {plabel}"
    if not forward and port.get("dir") in ("in", "io"):
        return f"nothing cabled into {dname} · {plabel}"
    return ""


def _finish(g: PortGraph, found: List[List[str]], limit: int, forward: Optional[bool] = None) -> List[Dict[str, Any]]:
    uniq: Dict[Tuple[str, ...], List[str]] = {}
    for nodes in found:
        uniq.setdefault(tuple(nodes), nodes)
    ordered = sorted(uniq.values(), key=lambda ns: (len(ns), ns))
    out = []
    for ns in ordered[:max(0, limit)]:
        p = _path_dict(g, ns)
        if forward is not None and ns:
            end = ns[-1] if forward else ns[0]
            walk = tuple(ns) if forward else tuple(reversed(ns))
            # a dead end is a gap; an end whose only continuation loops back into the path (insert
            # send/return) is a natural end
            if not g.walk_edges(walk, forward):
                reason = gap_reason(g, end, forward)
                if reason:
                    p["incomplete"] = reason
        out.append(p)
    return out


def _walk(g: PortGraph, start: str, forward: bool, max_depth: int, limit: int, targets: Optional[Set[str]] = None) -> List[List[str]]:
    """Bounded breadth-first enumeration of simple node paths from ``start``.

    Without ``targets`` a path ends where no unvisited usable edge remains (or at
    ``max_depth``); with ``targets`` only paths reaching a target are kept.
    Paths come out shortest first; once ``limit`` paths exist the current length
    level is finished so ties can be ordered lexically by the caller.
    """
    budget = 200_000
    queue_cap = 200_000
    found: List[List[str]] = []
    done_len: Optional[int] = None
    queue: "deque[Tuple[str, ...]]" = deque([(start,)])
    while queue and budget > 0:
        path = queue.popleft()
        budget -= 1
        if done_len is not None and len(path) > done_len:
            break
        node = path[-1]
        if targets is not None and node in targets and len(path) > 1:
            found.append(list(path))
            if done_len is None and len(found) >= limit:
                done_len = len(path)
            continue
        nxt: List[str] = []
        for e in g.walk_edges(path, forward):
            n = e.dst if forward else e.src
            if n not in path and n not in nxt:
                nxt.append(n)
        if not nxt or len(path) - 1 >= max_depth:
            if targets is None and len(path) > 1:
                found.append(list(path))
                if done_len is None and len(found) >= limit:
                    done_len = len(path)
            continue
        if len(queue) < queue_cap:
            for n in nxt:
                queue.append(path + (n,))
    return found


def _stranded(g: PortGraph, starts: List[str], forward: bool) -> List[List[str]]:
    """Single-hop "paths" for channel-level starts that have no edge at all in the walk direction, so
    the caller sees *why* (``incomplete``) instead of an empty result; plain ports keep returning nothing."""
    return [[s] for s in starts if g.is_sub(s) and gap_reason(g, s, forward)]


def upstream_paths(g: PortGraph, start: str, max_depth: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
    """Simple paths from a source to ``start`` (source first).

    ``start`` = ``dev:port``, or ``dev:*`` / a device id = union over its ``in``/``io`` ports
    (plus the device node's own cable/route ends)."""
    found: List[List[str]] = []
    starts = _start_nodes(g, start, "in")
    for s in starts:
        found.extend(list(reversed(p)) for p in _walk(g, s, False, max_depth, limit))
    if not found:
        found = _stranded(g, starts, False)
    return _finish(g, found, limit, forward=False)


def downstream_paths(g: PortGraph, start: str, max_depth: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
    """Simple paths from ``start`` to an endpoint (no further usable outgoing edge).

    ``dev:*`` / a device id = union over its ``out``/``io`` ports (plus the device node)."""
    found: List[List[str]] = []
    starts = _start_nodes(g, start, "out")
    for s in starts:
        found.extend(_walk(g, s, True, max_depth, limit))
    if not found:
        found = _stranded(g, starts, True)
    return _finish(g, found, limit, forward=True)


def port_paths(g: PortGraph, a: str, b: str, max_depth: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
    """Simple paths A → B. ``dev:*`` / a device id means its outputs on the A side and its inputs on the B side."""
    targets = set(_start_nodes(g, b, "in"))
    if not targets:
        return []
    found: List[List[str]] = []
    for s in _start_nodes(g, a, "out"):
        if s in targets:
            continue
        found.extend(_walk(g, s, True, max_depth, limit, targets))
    return _finish(g, found, limit)


def hop_labels(doc: Doc, path: Dict[str, Any], overlay: Optional[Dict[str, Any]] = None) -> List[str]:
    """One label per hop following the path-text rule of §6.9.4."""
    devs = device_map(doc, overlay)
    hops = path.get("hops") or []
    out: List[str] = []
    for i, h in enumerate(hops):
        dev = devs.get(h.get("device") or "")
        dname = str(dev.get("name") or dev.get("id")) if dev else str(h.get("device") or "")
        port = find_port(dev, h.get("port"))
        last = i == len(hops) - 1
        new_dev = i == 0 or h.get("device") != hops[i - 1].get("device")
        if h.get("kind") == "channel":
            local = str(h.get("title") or h.get("channel") or "")
            if h.get("dca") and not (i + 1 < len(hops) and hops[i + 1].get("kind") == "dca"):
                local += " (via " + ", ".join(str(d.get("title") or d.get("channel")) for d in h["dca"]) + ")"
        elif h.get("kind") == "dca":
            local = f"(via {h.get('title') or h.get('channel')})"
        elif h.get("kind") == "text":
            local = str(h.get("text") or "")
        elif h.get("kind") == "port_channel" and port is not None:
            local = f"{port_label(port)} {h.get('ch')}" + (f" “{h['name']}”" if h.get("name") else "")
        elif port is None:
            out.append(dname)
            continue
        elif last and port.get("dir") == "in":
            out.append(dname)
            continue
        else:
            local = port_label(port)
        out.append(f"{dname} · {local}" if new_dev else local)
    return out


def path_text(doc: Doc, path: Dict[str, Any], overlay: Optional[Dict[str, Any]] = None) -> str:
    text = " → ".join(hop_labels(doc, path, overlay))
    if path.get("incomplete"):
        text += f" ⚠ {path['incomplete']}"
    return text


def with_dca_hops(path: Dict[str, Any]) -> Dict[str, Any]:
    """Copy of ``path`` where an input channel's DCA membership becomes a control hop after it
    (``CH 12 · Bass → (via DCA 1 · BAND) → ST L``); the channel hop keeps its ``dca`` list."""
    hops: List[Dict[str, Any]] = []
    via: List[str] = []
    old_via = list(path.get("via") or [])
    for i, h in enumerate(path.get("hops") or []):
        hops.append(h)
        via.append(old_via[i] if i < len(old_via) else "")
        for d in h.get("dca") or []:
            hops.append({"device": h.get("device"), "port": None, "kind": "dca", "channel": d.get("channel"), "title": d.get("title"), "control": True})
            via.append("link:dca")
    out = dict(path)
    out["hops"], out["via"] = hops, via
    return out


def _match_port(dev: Dict[str, Any], text: str) -> Optional[str]:
    if not text:
        return None
    key = norm_name(text)
    ports = device_ports(dev)
    for p in ports:
        if p["id"] == text:
            return p["id"]
    for field in ("label", "name"):
        hits = [p for p in ports if key and norm_name(str(p.get(field) or "")) == key]
        if len(hits) == 1:
            return hits[0]["id"]
    hits = [p for p in ports if key and norm_name(f"{p.get('group') or ''} {_port_index(p, ports)}") == key]
    if len(hits) == 1:
        return hits[0]["id"]
    if key and len([p for p in ports if norm_name(str(p.get("name") or "")) == key]) > 1:
        return [p for p in ports if norm_name(str(p.get("name") or "")) == key][0]["id"]
    return None


def _match_device(devs: List[Dict[str, Any]], text: str) -> Optional[Dict[str, Any]]:
    t = (text or "").strip()
    if not t:
        return None
    for d in devs:
        if d["id"] == t:
            return d
    low = t.casefold()
    for d in devs:
        if str(d.get("name") or "").casefold() == low:
            return d
    key = norm_name(t)
    if not key:
        return None
    for d in devs:
        names = [d.get("name"), d.get("code"), d.get("dante_name")] + list(d.get("aliases") or [])
        if any(key == norm_name(str(n or "")) for n in names):
            return d
    hits = [d for d in devs if key in norm_name(str(d.get("name") or "")) or key in norm_name(d["id"])]
    return hits[0] if len(hits) == 1 else None


_SUB_RE = re.compile(r"^(.*?)\s*[#·]?\s*(\d+)$")


def _match_channel(doc: Doc, overlay: Optional[Dict[str, Any]], dev: Dict[str, Any], text: str) -> Optional[str]:
    """Console channel by id (``in-12``), label (``CH 12``, ``ST L``) or unique name (``Bass``) → ``@in-12``."""
    C = _console_mod()
    if C is None:
        return None
    chans, _ = _console_sets(doc, overlay, dev["id"])
    if not chans:
        return None
    key = norm_name(text)
    for c in chans:
        if c.get("id") == text:
            return "@" + str(c["id"])
    hits = [c for c in chans if key and norm_name(C.channel_label(c)) == key]
    if len(hits) == 1:
        return "@" + str(hits[0]["id"])
    hits = [c for c in chans if key and norm_name(str(c.get("name") or "")) == key]
    if len(hits) == 1:
        return "@" + str(hits[0]["id"])
    hits = [c for c in chans if key and norm_name(C.channel_title(c)) == key]
    if len(hits) == 1:
        return "@" + str(hits[0]["id"])
    return None


def _match_sub_channel(dev: Dict[str, Any], text: str) -> Optional[str]:
    """``Dante 17``, ``Dante Primary 17``, ``dante-primary#17``, ``dante-primary#rx17`` → ``dante-primary#17`` (direction decided by the trace)."""
    t = text.strip()
    if "#" in t:
        port, _, sub = t.partition("#")
        pid = _match_port(dev, port.strip())
        digits = sub[2:] if sub[:2] in ("rx", "tx") else sub
        if pid and digits.isdigit():
            return f"{pid}#{sub}" if sub[:2] in ("rx", "tx") else f"{pid}#{int(digits)}"
        return None
    m = _SUB_RE.match(t)
    if not m:
        return None
    head, n = m.group(1).strip(), int(m.group(2))
    if not head or n < 1:
        return None
    ports = [p for p in device_ports(dev) if not _single_channel(p) and n <= int(p.get("channels") or 1)]
    key = norm_name(head)
    hits = [p for p in ports if p["id"] == head or key in (norm_name(str(p.get(f) or "")) for f in ("label", "name", "group"))]
    if len(hits) != 1:
        # "Dante 17" on a device with Primary + Secondary: prefer the first (primary) match by group
        hits = [p for p in ports if key and key == norm_name(str(p.get("group") or ""))][:1]
    return f"{hits[0]['id']}#{n}" if hits else None


def _resolve_sub(doc: Doc, overlay: Optional[Dict[str, Any]], dev: Dict[str, Any], text: str) -> Optional[str]:
    """Port id / label / name first, then a console channel, then a stream-port sub-channel
    (``Dante 1`` is channel 1 of the Dante port, not the port whose group index is 1), then the
    group-index port rule."""
    key = norm_name(text)
    for p in device_ports(dev):
        if p["id"] == text or (key and key in (norm_name(str(p.get("label") or "")), norm_name(str(p.get("name") or "")))):
            return p["id"]
    return _match_channel(doc, overlay, dev, text) or _match_sub_channel(dev, text) or _match_port(dev, text)


def resolve_ref(doc: Doc, text: str, overlay: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, Optional[str]]]:
    """``"dev[:port]"``, ``"Device · Port"`` or a device name → ``(device_id, port_id|None)``.

    The second element can also be a console channel (``@in-12`` from ``CL5 · CH 12`` / ``CL5 · Bass`` /
    ``foh:in-12``) or a port sub-channel (``dante-primary#17`` from ``Rio · Dante 17`` / ``rio:dante-primary#17``),
    ready to be joined into a node ref with ``:``."""
    t = (text or "").strip()
    if not t:
        return None
    devs = doc_devices(doc, overlay)
    if ":" in t:
        d, _, p = t.partition(":")
        dev = _match_device(devs, d)
        if dev is not None:
            if p.strip() in ("", "*"):
                return dev["id"], None
            sub = _resolve_sub(doc, overlay, dev, p.strip())
            return (dev["id"], sub) if sub else None
    dev = _match_device(devs, t)
    if dev is not None:
        return dev["id"], None
    if " · " in t:
        d, _, p = t.partition(" · ")
        dev = _match_device(devs, d)
        if dev is not None:
            sub = _resolve_sub(doc, overlay, dev, p.strip())
            return (dev["id"], sub) if sub else None
    return None
