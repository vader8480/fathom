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


def routing_mode(dev: Dict[str, Any]) -> str:
    r = dev.get("routing")
    mode = r.get("mode") if isinstance(r, dict) else (r if isinstance(r, str) else None)
    return str(mode or kind_routing(dev.get("kind") or ""))


def internal_pairs(dev: Dict[str, Any], discipline: Optional[str] = None) -> List[Tuple[str, str]]:
    """Device internal edges ``(in_port, out_port)`` by routing mode (§4.4.5), discipline-filtered."""
    ports = device_ports(dev)
    mode = routing_mode(dev)
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
    kind: str  # cable | internal | route | device
    cable: Optional[str]
    medium: str


def node_ref(device: str, port: Optional[str]) -> str:
    return f"{device}:{port if port else '*'}"


def split_ref(node: str) -> Tuple[str, Optional[str]]:
    dev, _, port = node.partition(":")
    return dev, (None if port in ("", "*") else port)


class PortGraph:
    """Directed port graph. Nodes are ``"dev:port"`` or ``"dev:*"`` (device level)."""

    def __init__(self, doc: Doc, discipline: Optional[str] = None) -> None:
        self.doc = doc
        self.discipline = discipline or None
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.nodes: Dict[str, Tuple[str, Optional[str]]] = {}
        self._out: Dict[str, List[PortEdge]] = {}
        self._in: Dict[str, List[PortEdge]] = {}
        self._seen: Set[Tuple[str, str, str, Optional[str]]] = set()

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

    def is_star(self, node: str) -> bool:
        return node.endswith(":*")

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

    def add_edge(self, src: str, dst: str, kind: str, cable: Optional[str], medium: str) -> None:
        if src == dst:
            return
        key = (src, dst, kind, cable)
        if key in self._seen:
            return
        self._seen.add(key)
        e = PortEdge(src, dst, kind, cable, medium)
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


def port_graph(doc: Doc, overlay: Optional[Dict[str, Any]] = None, discipline: Optional[str] = None, state: str = "all") -> PortGraph:
    """Port graph of ``doc`` (+ overlay devices and routes) filtered by discipline and state (§6.9.1–6.9.3)."""
    g = PortGraph(doc, discipline)
    disc = g.discipline
    for dev in doc_devices(doc, overlay):
        if status_included(dev.get("status"), state):
            g.devices[dev["id"]] = dev
    for dev in g.devices.values():
        for p in device_ports(dev):
            g.add_node(dev["id"], p["id"])
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
        byid = {p["id"]: p for p in device_ports(dev)}
        for a, b in internal_pairs(dev, disc):
            g.add_edge(node_ref(dev["id"], a), node_ref(dev["id"], b), "internal", None, byid[a].get("medium", ""))
    for r in (overlay or {}).get("routes") or []:
        if not isinstance(r, dict):
            continue
        med = r.get("medium") or "dante"
        if disc is not None and disc not in carries(med):
            continue
        a, b = _endpoint(g, r.get("from")), _endpoint(g, r.get("to"))
        if a is not None and b is not None:
            g.add_edge(a, b, "route", None, med)
    return g


def _start_nodes(g: PortGraph, ref: str, side: str) -> List[str]:
    """Nodes a ref stands for. ``dev:port`` is itself; ``dev:*`` or a bare device id expands
    to its ``in``/``io`` ports (``side="in"``) or ``out``/``io`` ports (``side="out"``),
    plus the ``dev:*`` node itself when it exists (device-level cable/route ends)."""
    dev_id, port = split_ref(ref) if ":" in ref else (ref, None)
    if port is not None:
        return [ref] if g.has_node(ref) else []
    dev = g.devices.get(dev_id)
    if dev is None:
        return []
    want = ("in", "io") if side == "in" else ("out", "io")
    out = [node_ref(dev_id, p["id"]) for p in device_ports(dev) if p.get("dir") in want and g.has_node(node_ref(dev_id, p["id"]))]
    star = node_ref(dev_id, None)
    if g.has_node(star):
        out.append(star)
    return out


def _path_dict(g: PortGraph, nodes: List[str]) -> Dict[str, Any]:
    hops = []
    for n in nodes:
        d, p = split_ref(n)
        hops.append({"device": d, "port": p})
    cables: List[str] = []
    for a, b in zip(nodes, nodes[1:]):
        cid = g.cables_between(a, b)
        if cid and cid not in cables:
            cables.append(cid)
    return {"hops": hops, "cables": cables}


def _finish(g: PortGraph, found: List[List[str]], limit: int) -> List[Dict[str, Any]]:
    uniq: Dict[Tuple[str, ...], List[str]] = {}
    for nodes in found:
        uniq.setdefault(tuple(nodes), nodes)
    ordered = sorted(uniq.values(), key=lambda ns: (len(ns), ns))
    return [_path_dict(g, ns) for ns in ordered[:max(0, limit)]]


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


def upstream_paths(g: PortGraph, start: str, max_depth: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
    """Simple paths from a source to ``start`` (source first).

    ``start`` = ``dev:port``, or ``dev:*`` / a device id = union over its ``in``/``io`` ports
    (plus the device node's own cable/route ends)."""
    found: List[List[str]] = []
    for s in _start_nodes(g, start, "in"):
        found.extend(list(reversed(p)) for p in _walk(g, s, False, max_depth, limit))
    return _finish(g, found, limit)


def downstream_paths(g: PortGraph, start: str, max_depth: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
    """Simple paths from ``start`` to an endpoint (no further usable outgoing edge).

    ``dev:*`` / a device id = union over its ``out``/``io`` ports (plus the device node)."""
    found: List[List[str]] = []
    for s in _start_nodes(g, start, "out"):
        found.extend(_walk(g, s, True, max_depth, limit))
    return _finish(g, found, limit)


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
        if port is None:
            out.append(dname)
        elif last and port.get("dir") == "in":
            out.append(dname)
        elif i == 0 or h.get("device") != hops[i - 1].get("device"):
            out.append(f"{dname} · {port_label(port)}")
        else:
            out.append(port_label(port))
    return out


def path_text(doc: Doc, path: Dict[str, Any]) -> str:
    return " → ".join(hop_labels(doc, path))


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


def resolve_ref(doc: Doc, text: str) -> Optional[Tuple[str, Optional[str]]]:
    """``"dev[:port]"``, ``"Device · Port"`` or a device name → ``(device_id, port_id|None)``."""
    t = (text or "").strip()
    if not t:
        return None
    devs = doc_devices(doc)
    if ":" in t:
        d, _, p = t.partition(":")
        dev = _match_device(devs, d)
        if dev is not None:
            if p.strip() in ("", "*"):
                return dev["id"], None
            port = _match_port(dev, p.strip())
            return (dev["id"], port) if port else None
    dev = _match_device(devs, t)
    if dev is not None:
        return dev["id"], None
    if " · " in t:
        d, _, p = t.partition(" · ")
        dev = _match_device(devs, d)
        if dev is not None:
            port = _match_port(dev, p.strip())
            return (dev["id"], port) if port else None
    return None
