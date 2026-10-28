"""Troubleshooting assistant (SPEC FR-AST, §5.10, §6.9.5).

Deterministic pipeline, no network needed: parse the question (intent type,
symptom, discipline, target and working devices), trace upstream at port level
from every target input, compare with what the working devices share, pick the
suspect segment, build numbered checks from the checklists (kinds, media,
template ``checks``, generic) and propose a note for the map. The optional LLM
bridge (``llm.py``) only adds ``llm.text``; it never changes the deterministic
fields and its output is never executed. Suggested ops are only proposals the
user must confirm. With a tool-calling provider the grounded loop of
``assistant_tools`` runs afterwards (§6.9.6 "tool loop"); edits it suggests
come back as a ``proposal`` (``assistant_edits``) that is applied only through
``POST …/assistant/apply``.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import trace as T

Doc = Dict[str, Any]

CHECKLIST_DIR = Path(__file__).resolve().parent / "checklists"
CHECKLIST_FILES: Tuple[str, ...] = ("symptoms", "synonyms", "kinds", "media", "generic")
SEPARATORS = {",", ";", "but", "and", "however", "although", "while"}
TARGET_PATH_LIMIT = 500
QUESTION_WORDS = {"what", "whats", "how", "does", "do", "did", "get", "gets", "where", "wheres", "which", "who", "why",
                  "when", "feeds", "feed", "fed", "by", "go", "goes", "trace", "rack", "plugged", "into", "can", "cant",
                  "you", "me", "please", "help", "check", "today", "suddenly", "anymore", "still", "just", "also", "be",
                  "being", "been", "so", "very", "really", "some", "up", "out", "off", "get", "got", "after", "before",
                  "during", "service", "since", "s", "t"}
SOURCE_KINDS_DEFAULT = frozenset({"mic", "source", "video_source", "camera", "computer", "lighting_console", "touch_panel"})
SYMPTOM_DISCIPLINE = {"no_audio": "audio", "noise": "audio", "feedback": "audio", "dropout": "audio", "latency": "audio",
                      "no_video": "video", "flicker": "video", "wrong_source": "video", "lighting_no_response": "lighting",
                      "no_network": "network", "no_power": "power"}

# Appendix F.6, used only when fathom.library cannot provide the template.
_FALLBACK_TEMPLATE_CHECKS: Dict[str, List[Dict[str, Any]]] = {
    tid: [{"id": "audio-on", "symptoms": ["no_audio"], "when": {"port_dir": "in", "medium": ["analog", "hdmi"]},
           "text": "On the {device}'s Audio tab, make sure the **{port}** input is set to ON, not AFV (inputs default to audio-follow-video).",
           "note": "check Audio tab"}]
    for tid in ("blackmagic-atem-mini-pro", "blackmagic-atem-mini-pro-iso")
}

_CACHE: Dict[Tuple[str, ...], Dict[str, Any]] = {}


# ----------------------------------------------------------------------------- checklists

def _ext_dirs() -> List[Path]:
    try:
        from .plugins import checklist_dirs  # W2
        return [Path(p) for p in checklist_dirs()]
    except Exception:
        return [Path(p) for p in (os.environ.get("FATHOM_CHECKLISTS") or "").split(os.pathsep) if p.strip()]


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _merge_checks(base: List[Dict[str, Any]], extra: Any) -> None:
    for c in extra if isinstance(extra, list) else []:
        if not isinstance(c, dict) or not c.get("id") or not c.get("text"):
            continue
        for i, b in enumerate(base):
            if b.get("id") == c["id"]:
                base[i] = c
                break
        else:
            base.append(c)


def _append_unique(base: List[Any], extra: Any) -> None:
    for x in extra if isinstance(extra, list) else []:
        if x not in base:
            base.append(x)


def _merge_file(out: Dict[str, Any], name: str, data: Dict[str, Any]) -> None:
    if name == "symptoms":
        for key, val in (data.get("symptoms") or {}).items():
            if not isinstance(val, dict):
                continue
            cur = out["symptoms"].setdefault(key, {"discipline": val.get("discipline") or "other", "phrases": []})
            if val.get("discipline"):
                cur["discipline"] = val["discipline"]
            _append_unique(cur.setdefault("phrases", []), val.get("phrases"))
        for disc, words in (data.get("discipline_words") or {}).items():
            _append_unique(out["discipline_words"].setdefault(disc, []), words)
        _append_unique(out["positive"], data.get("positive"))
        _append_unique(out["stopwords"], data.get("stopwords"))
    elif name == "synonyms":
        for role in data.get("roles") or []:
            if not isinstance(role, dict) or not role.get("phrases"):
                continue
            if role.get("id"):
                for i, r in enumerate(out["roles"]):
                    if r.get("id") == role["id"]:
                        out["roles"][i] = role
                        break
                else:
                    out["roles"].append(role)
            else:
                out["roles"].append(role)
    elif name in ("kinds", "media"):
        for key, checks in (data.get(name) or {}).items():
            _merge_checks(out[name].setdefault(key, []), checks)
    elif name == "generic":
        _merge_checks(out["generic"], data.get("checks"))


def load_checklists(refresh: bool = False) -> Dict[str, Any]:
    """Built-in ``fathom/checklists`` merged with extension dirs (FATHOM_CHECKLISTS, plugins).

    Returns ``{"symptoms", "discipline_words", "positive", "stopwords", "roles", "kinds", "media", "generic"}``.
    Extension entries are appended; the same ``id`` within the same key replaces.
    """
    dirs = _ext_dirs()
    key = tuple(str(d) for d in dirs)
    if not refresh and key in _CACHE:
        return _CACHE[key]
    out: Dict[str, Any] = {"symptoms": {}, "discipline_words": {}, "positive": [], "stopwords": [], "roles": [],
                           "kinds": {}, "media": {}, "generic": []}
    for d in [CHECKLIST_DIR] + dirs:
        for name in CHECKLIST_FILES:
            f = d / f"{name}.json"
            if f.is_file():
                data = _read_json(f)
                if data is not None:
                    _merge_file(out, name, copy.deepcopy(data))
    _CACHE[key] = out
    return out


# ----------------------------------------------------------------------------- text helpers

def _normalize(text: str) -> str:
    s = (text or "").lower().replace("\u2019", "'").replace("'", "")
    s = re.sub(r"[,;]", " , ", s)
    s = re.sub(r"(?<=\d)\.(?=\d)", "\x00", s)
    s = re.sub(r"[^a-z0-9\s\u00b7:\-\x00,]", " ", s)
    s = s.replace("\x00", ".")
    return " ".join(s.split())


def _toks(text: str) -> List[str]:
    return _normalize(text).split()


def _find(tokens: List[str], phrase: List[str], used: List[bool]) -> List[int]:
    n = len(phrase)
    hits = []
    if not n:
        return hits
    for i in range(len(tokens) - n + 1):
        if tokens[i:i + n] == phrase and not any(used[i:i + n]):
            hits.append(i)
    return hits


def _fill(text: str, values: Dict[str, str]) -> str:
    return re.sub(r"\{([a-z_]+)\}", lambda m: values.get(m.group(1), m.group(0)), text)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _port_display(dev: Optional[Dict[str, Any]], port: Optional[Dict[str, Any]]) -> str:
    if not port:
        return ""
    if port.get("group"):
        return f"{port['group']} {T._port_index(port, T.device_ports(dev))}"
    return str(port.get("name") or port["id"])


def _source_kinds() -> frozenset:
    v = T._vocab()
    return frozenset(getattr(v, "SOURCE_KINDS", SOURCE_KINDS_DEFAULT)) if v is not None else SOURCE_KINDS_DEFAULT


def _room_of(doc: Doc, room: Optional[str]) -> str:
    rooms = [r.get("id") for r in doc.get("rooms") or [] if isinstance(r, dict) and r.get("id")]
    if room and room in rooms:
        return room
    if room == "":
        return ""
    dr = (doc.get("settings") or {}).get("default_room")
    if dr:
        return str(dr)
    return rooms[0] if rooms else ""


# ----------------------------------------------------------------------------- intent

_TRACE_RE = re.compile(r"^(how does|how do|what feeds|where does|what is fed by|trace)\b")
_LOCATE_RE = re.compile(r"^(where is|wheres|which rack|what rack)\b")
_DESCRIBE_RE = re.compile(r"^(what is on|whats on|what is plugged into|whats plugged into)\b")


def _intent_type(qn: str) -> str:
    if _LOCATE_RE.match(qn):
        return "locate"
    if _DESCRIBE_RE.match(qn):
        return "describe"
    if _TRACE_RE.match(qn):
        return "trace"
    return "troubleshoot"


def _parse(doc: Doc, question: str, room: Optional[str], index: Any, cl: Dict[str, Any],
           overlay: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from . import search as S

    qn = _normalize(question)
    tokens = qn.split()
    used = [False] * len(tokens)
    rid = _room_of(doc, room)
    itype = _intent_type(qn)
    devs = [d for d in T.doc_devices(doc, overlay) if T.status_included(d.get("status"), "all")]
    room_devs = [d for d in devs if (d.get("room") or "") == rid]
    byid = {d["id"]: d for d in devs}

    # 1. symptom: longest phrase across all symptoms; ties by discipline words in the question
    dwords = {disc: set(w for ws in [words] for w in ws) for disc, words in cl["discipline_words"].items()}
    tokset = set(tokens)
    best: Optional[Tuple[Tuple[int, int, int, int], str, int, int]] = None
    for sym, spec in cl["symptoms"].items():
        for ph in spec.get("phrases") or []:
            pt = _toks(ph)
            for i in _find(tokens, pt, used):
                bonus = 1 if tokset & dwords.get(spec.get("discipline") or "", set()) else 0
                key = (len(pt), len(" ".join(pt)), bonus, -i)
                if best is None or key > best[0]:
                    best = (key, sym, i, len(pt))
    symptom: Optional[str] = None
    if best is not None:
        symptom = best[1]
        for k in range(best[2], best[2] + best[3]):
            used[k] = True
    if itype == "troubleshoot" and symptom is None:
        symptom = "general"

    mentions: List[Dict[str, Any]] = []  # {"pos", "end", "devices", "port", "text", "via"}

    # 2. exact device names (score-100 hits win over role phrases)
    cands: List[Tuple[List[str], Dict[str, Any]]] = []
    for d in sorted(devs, key=lambda x: 0 if (x.get("room") or "") == rid else 1):
        names = [d.get("name"), d["id"]] + list(d.get("aliases") or [])
        for nm in names:
            pt = _toks(str(nm or ""))
            if pt and len(" ".join(pt)) >= 3:
                cands.append((pt, d))
    cands.sort(key=lambda c: (-len(c[0]), -len(" ".join(c[0]))))
    for pt, d in cands:
        for i in _find(tokens, pt, used):
            for k in range(i, i + len(pt)):
                used[k] = True
            mentions.append({"pos": i, "end": i + len(pt), "devices": [d["id"]], "port": None, "text": " ".join(pt), "via": "name"})

    # 2b. a room name ("chapel", "broadcast suite") scopes kind words to that room and never
    #     selects a device by name on its own (complete device names were matched above)
    notes: List[str] = []
    room_names = {r["id"]: str(r.get("name") or r["id"]) for r in doc.get("rooms") or [] if isinstance(r, dict) and r.get("id")}
    rcands = sorted(((_toks(nm), rid_) for rid_, nm in room_names.items() if len(nm) >= 4),
                    key=lambda c: (-len(c[0]), -len(" ".join(c[0]))))
    mentioned_room: Optional[str] = None
    for pt, rid_ in rcands:
        for i in _find(tokens, pt, used):
            for k in range(i, i + len(pt)):
                used[k] = True
            if mentioned_room is None:
                mentioned_room = rid_
    if mentioned_room and mentioned_room != rid:
        rid = mentioned_room
        room_devs = [d for d in devs if (d.get("room") or "") == rid]

    # 3. role phrases (synonyms.json) → devices of those kinds in the room
    roles: List[Tuple[List[str], Dict[str, Any]]] = []
    for role in cl["roles"]:
        for ph in role.get("phrases") or []:
            pt = _toks(ph)
            if pt:
                roles.append((pt, role))
    roles.sort(key=lambda r: (-len(r[0]), -len(" ".join(r[0]))))
    unresolved: List[Dict[str, Any]] = []
    for pt, role in roles:
        for i in _find(tokens, pt, used):
            end = i + len(pt)
            for k in range(i, end):
                used[k] = True
            kinds = set(role.get("kinds") or [])
            found = _role_devices(role, pt, room_devs)
            if not found:
                found = _role_devices(role, pt, [d for d in devs if (d.get("room") or "") != rid])
                if found:
                    where = ", ".join(f"{byid[f].get('name') or f} ({room_names.get(byid[f].get('room') or '', 'shared inventory')})" for f in found)
                    notes.append(f"No {' '.join(pt)} in {room_names.get(rid, rid or 'this room')}; using {where}.")
            if found:
                mentions.append({"pos": i, "end": end, "devices": found, "port": None, "text": " ".join(pt), "via": "role"})
            else:
                while end < len(tokens) and not used[end] and re.fullmatch(r"\d+[a-z]?", tokens[end]):
                    used[end] = True
                    end += 1
                unresolved.append({"pos": i, "text": " ".join(tokens[i:end]), "role_kinds": sorted(kinds)})

    # 4. remaining words → search hits with score ≥ 60, longest n-grams first
    stop = set(cl["stopwords"]) | QUESTION_WORDS | SEPARATORS
    for ws in cl["discipline_words"].values():
        stop |= set(ws)
    for ph in cl["positive"]:
        stop |= set(_toks(ph))
    runs: List[List[int]] = []
    cur: List[int] = []
    for i, t in enumerate(tokens):
        if used[i] or t in stop or t in ("-", "\u00b7", ":"):
            if cur:
                runs.append(cur)
            cur = []
        else:
            cur.append(i)
    if cur:
        runs.append(cur)
    for run in runs:
        j = 0
        while j < len(run):
            hit = None
            for n in range(min(4, len(run) - j), 0, -1):
                idx = run[j:j + n]
                phrase = " ".join(tokens[k] for k in idx)
                if all(re.fullmatch(r"\d+", tokens[k]) or len(tokens[k]) < 2 for k in idx):
                    continue
                hs = [h for h in S.search(index, phrase, limit=50) if h["score"] >= 60 and h.get("device") in byid and _name_hit_ok(phrase, h)]
                if hs:
                    top = max(h["score"] for h in hs)
                    best_hits = [h for h in hs if h["score"] == top]
                    in_room = [h for h in best_hits if (byid[h["device"]].get("room") or "") == rid]
                    pick = (in_room or best_hits)[0]
                    if not in_room and (byid[pick["device"]].get("room") or "") != rid:
                        notes.append(f"Nothing called '{phrase}' in {room_names.get(rid, rid or 'this room')}; "
                                     f"using {pick['title']} ({room_names.get(byid[pick['device']].get('room') or '', 'shared inventory')}).")
                    hit = (n, pick, phrase)
                    break
            if hit is None:
                j += 1
                continue
            n, h, phrase = hit
            for k in run[j:j + n]:
                used[k] = True
            port = h["port"] if h["kind"] == "port" else None
            mentions.append({"pos": run[j], "end": run[j] + n, "devices": [h["device"]], "port": port, "text": phrase, "via": "search"})
            j += n
        leftover = [k for k in run if not used[k]]
        if leftover and any(re.search(r"\d", tokens[k]) for k in leftover) and any(not re.fullmatch(r"\d+", tokens[k]) for k in leftover):
            unresolved.append({"pos": leftover[0], "text": " ".join(tokens[k] for k in leftover), "role_kinds": []})

    # 5. ports ("input 3") bind to the preceding single-device mention
    for m in sorted(mentions, key=lambda m: m["pos"]):
        if m["port"] or len(m["devices"]) != 1:
            continue
        dev = byid.get(m["devices"][0])
        for n in (3, 2, 1):
            idx = list(range(m["end"], m["end"] + n))
            if idx[-1] >= len(tokens) or any(used[k] for k in idx):
                continue
            if n == 1 and (tokens[idx[0]] in stop or re.fullmatch(r"\d+", tokens[idx[0]])):
                continue
            pid = T._match_port(dev, " ".join(tokens[k] for k in idx)) if dev else None
            if pid:
                for k in idx:
                    used[k] = True
                m["port"] = pid
                m["end"] += n
                break

    # 6. clauses: positive markers → working; the rest are targets
    clause = []
    c = 0
    for t in tokens:
        if t in SEPARATORS:
            c += 1
        clause.append(c)
    positive_clauses: Set[int] = set()
    for ph in cl["positive"] + ["ok"]:
        pt = _toks(ph)
        for i in range(len(tokens) - len(pt) + 1):
            if pt and tokens[i:i + len(pt)] == pt:
                positive_clauses.add(clause[i])
    targets: List[str] = []
    working: List[str] = []
    ports: Dict[str, str] = {}
    for m in sorted(mentions, key=lambda m: m["pos"]):
        is_working = itype == "troubleshoot" and clause[m["pos"]] in positive_clauses
        bucket = working if is_working else targets
        for dev_id in m["devices"]:
            if dev_id not in bucket:
                bucket.append(dev_id)
            if m["port"]:
                ports.setdefault(dev_id, m["port"])
    working = [w for w in working if w not in targets] if itype == "troubleshoot" else working

    discipline = SYMPTOM_DISCIPLINE.get(symptom or "")
    if discipline is None and symptom and symptom in cl["symptoms"] and symptom != "general":
        discipline = cl["symptoms"][symptom].get("discipline")
    if discipline is None:
        for dev_id in targets + working:
            d = byid.get(dev_id)
            if d is not None:
                p = T.find_port(d, ports.get(dev_id))
                discipline = T._vocab().medium_discipline(p.get("medium", "")) if (p and T._vocab()) else T.device_discipline(d)
                break

    for u in unresolved:
        u["suggestions"] = _suggest(doc, index, u, room_devs, discipline)
    unresolved.sort(key=lambda u: u["pos"])
    intent = {"type": itype, "symptom": symptom, "discipline": discipline, "targets": targets, "working": working, "room": rid}
    details = {"ports": ports, "mentions": mentions, "notes": notes, "unresolved": [
        {"text": u["text"], "suggestions": u["suggestions"],
         "message": f"I couldn't find '{u['text']}'." + (f" Did you mean: {', '.join(s['title'] for s in u['suggestions'])}?" if u["suggestions"] else "")}
        for u in unresolved]}
    return intent, details


_NAME_FIELDS = {"name", "id", "alias", "code", "dante_name", "label", "serial", "asset_tag", "ip", "mac", "hostname", "tag"}


def _name_hit_ok(phrase: str, hit: Dict[str, Any]) -> bool:
    """A search hit names an entity only through a name-like field, with every phrase token a
    whole word of the title or a prefix (≥ 4 chars) of one; exact id/alias/ip matches always count."""
    if hit.get("match") not in _NAME_FIELDS:
        return False
    if hit["score"] == 100:
        return True
    words = [w for w in re.split(r"[^a-z0-9.]+", str(hit.get("title") or "").casefold()) if w]
    words += [w for w in re.split(r"[^a-z0-9.]+", str(hit.get("id") or "").casefold()) if w]
    for t in phrase.split():
        if t in words:
            continue
        if len(t) >= 4 and any(w.startswith(t) for w in words):
            continue
        return False
    return True


def _role_devices(role: Dict[str, Any], phrase: List[str], pool: List[Dict[str, Any]]) -> List[str]:
    """Devices a role phrase stands for in ``pool``: the first of the role's kinds (in listed order)
    that has devices, filtered by ``name_contains``, then narrowed to the devices whose name has the
    phrase word (``mains`` → ``Main hang L/R``) when any do."""
    nc = [s.casefold() for s in role.get("name_contains") or []]
    found: List[Dict[str, Any]] = []
    for kind in role.get("kinds") or []:
        found = [d for d in pool if d.get("kind") == kind and (not nc or any(s in str(d.get("name") or "").casefold() for s in nc))]
        if found:
            break
    stems = []
    for w in phrase:
        s = w[:-1] if len(w) > 4 and w.endswith("s") else w
        if len(s) >= 4:
            stems.append(s)
    if stems and len(found) > 1:
        def has_stem(d: Dict[str, Any]) -> bool:
            names = [d.get("name"), d["id"]] + list(d.get("aliases") or [])
            words = {w for nm in names for w in re.split(r"[^a-z0-9]+", str(nm or "").casefold()) if w}
            return any(any(w == s or w.startswith(s) for w in words) for s in stems)
        narrowed = [d for d in found if has_stem(d)]
        if narrowed:
            found = narrowed
    return [d["id"] for d in found]


def _suggest(doc: Doc, index: Any, u: Dict[str, Any], room_devs: List[Dict[str, Any]], discipline: Optional[str]) -> List[Dict[str, Any]]:
    from . import search as S

    out: List[Dict[str, Any]] = []

    def add(dev_id: str, port: Optional[str], title: str) -> None:
        if len(out) < 3 and not any(o["device"] == dev_id and o["port"] == port for o in out):
            out.append({"device": dev_id, "port": port, "title": title})

    words = [w for w in u["text"].split() if not re.fullmatch(r"\d+", w)]
    for q in [u["text"]] + words:
        for h in S.search(index, q, limit=10, kinds=["device"]):
            if h["score"] >= 25 and h.get("device"):
                add(h["device"], None, h["title"])
    if not out:
        disc = None
        v = T._vocab()
        if v is not None and u.get("role_kinds"):
            disc = v.kind_discipline(u["role_kinds"][0])
        disc = disc or discipline
        kinds = set(u.get("role_kinds") or [])
        related = [d for d in room_devs if disc and T.device_discipline(d) == disc and T.routing_mode(d) in ("none", "passthrough")]
        related += [d for d in room_devs if disc and T.device_discipline(d) == disc and d not in related and d.get("kind") not in kinds]
        for d in related:
            add(d["id"], None, str(d.get("name") or d["id"]))
    return out


def parse_intent(doc: Doc, question: str, room: Optional[str] = None, index: Any = None) -> Dict[str, Any]:
    """Intent of §5.10: ``{type, symptom, discipline, targets, working, room}``."""
    from . import search as S

    cl = load_checklists()
    ix = index if index is not None else S.build_index(doc)
    return _parse(doc, question, room, ix, cl)[0]


# ----------------------------------------------------------------------------- tracing helpers

def _input_nodes(g: T.PortGraph, dev_id: str, port: Optional[str] = None) -> List[str]:
    if port:
        n = T.node_ref(dev_id, port)
        return [n] if g.has_node(n) and any(e.kind in ("cable", "route") for e in g.edges_in(n)) else ([n] if g.has_node(n) else [])
    out = []
    dev = g.devices.get(dev_id)
    for p in T.device_ports(dev):
        if p.get("dir") not in ("in", "io"):
            continue
        n = T.node_ref(dev_id, p["id"])
        if any(e.kind in ("cable", "route") for e in g.edges_in(n)):
            out.append(n)
    star = T.node_ref(dev_id, None)
    if g.has_node(star) and any(e.kind in ("cable", "route") for e in g.edges_in(star)):
        out.append(star)
    return out


def _upstream_set(g: T.PortGraph, starts: List[str], max_depth: int = 24) -> Set[str]:
    seen = set(starts)
    frontier = list(starts)
    depth = 0
    while frontier and depth < max_depth:
        nxt = []
        for n in frontier:
            for e in g.edges_in(n):
                if e.src not in seen:
                    seen.add(e.src)
                    nxt.append(e.src)
        frontier = nxt
        depth += 1
    return seen


def _has_incoming_cable(g: T.PortGraph, node: str) -> bool:
    return any(e.kind in ("cable", "route") for e in g.edges_in(node))


def _nodes_of(path: Dict[str, Any]) -> List[str]:
    return [T.hop_ref(h) for h in path["hops"]]


def _seg_path(g: T.PortGraph, nodes: List[str]) -> Dict[str, Any]:
    return T._path_dict(g, nodes)


def _render_path(doc: Doc, g: T.PortGraph, nodes: List[str], role: str, overlay: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    p = _seg_path(g, nodes)
    labels = T.hop_labels(doc, p, overlay)
    hops = [{"device": h["device"], "port": h["port"], "label": lab} for h, lab in zip(p["hops"], labels)]
    return {"hops": hops, "cables": p["cables"], "text": " → ".join(labels), "role": role}


def _template(doc: Doc, template_id: str) -> Optional[Dict[str, Any]]:
    if not template_id:
        return None
    t: Optional[Dict[str, Any]] = None
    try:
        from .library import get_template  # W2
        t = get_template(template_id, doc)
    except Exception:
        t = None
    if t is None:
        for x in doc.get("templates") or []:
            if isinstance(x, dict) and x.get("id") == template_id:
                t = x
    if (t is None or "checks" not in t) and template_id in _FALLBACK_TEMPLATE_CHECKS:
        t = dict(t or {"id": template_id})
        t["checks"] = _FALLBACK_TEMPLATE_CHECKS[template_id]
    return t


def _when_ok(when: Any, port: Optional[Dict[str, Any]], dev: Optional[Dict[str, Any]], has_working: bool) -> bool:
    if not isinstance(when, dict):
        return True
    for k, v in when.items():
        if k == "port_dir":
            allowed = [v] if isinstance(v, str) else list(v or [])
            if not port or port.get("dir") not in allowed:
                return False
        elif k == "medium":
            allowed = [v] if isinstance(v, str) else list(v or [])
            if not port or port.get("medium") not in allowed:
                return False
        elif k == "kind":
            allowed = [v] if isinstance(v, str) else list(v or [])
            if not dev or dev.get("kind") not in allowed:
                return False
        elif k == "has_working":
            if bool(v) != has_working:
                return False
    return True


def _applies(check: Dict[str, Any], symptom: str) -> bool:
    syms = check.get("symptoms") or []
    return "*" in syms or symptom in syms


# ----------------------------------------------------------------------------- answer

def _empty_answer(question: str, intent: Dict[str, Any]) -> Dict[str, Any]:
    return {"question": question, "intent": intent, "summary": "", "paths": [], "branch": None, "suspects": [], "checks": [],
            "notes": [], "suggestion": None, "confidence": "low", "unresolved": [], "llm": {"used": False}}


def answer(doc: Doc, question: str, *, room: Optional[str] = None, overlay: Optional[Dict[str, Any]] = None, use_llm: bool = True,
           history: Optional[List[Dict[str, str]]] = None, base_revision: Optional[int] = None,
           ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Answer a question about the system (§5.10). Raises ``ValueError`` for an empty question.

    ``ctx`` (optional, server-side) feeds the tool-calling LLM path (§6.9.6 tool loop): ``pdir``
    (attachments), ``project``, ``username``, ``role``, ``attachments`` (ids the user attached),
    ``manual_text`` (pasted reference text) and ``provider`` (test injection). The deterministic
    fields never depend on it."""
    from . import search as S

    q = (question or "").strip()
    if not q:
        raise ValueError("empty question")
    cl = load_checklists()
    index = S.build_index(doc, overlay)
    intent, det = _parse(doc, q, room, index, cl, overlay)
    res = _empty_answer(q, intent)
    res["unresolved"] = det["unresolved"]
    res["notes"].extend(det.get("notes") or [])
    devs = T.device_map(doc, overlay)
    ctx = {"doc": doc, "overlay": overlay, "intent": intent, "det": det, "devs": devs, "cl": cl, "room": room, "index": index,
           "base_revision": base_revision if base_revision is not None else doc.get("revision", 0), "extra": dict(ctx or {})}
    if intent["type"] == "troubleshoot":
        _troubleshoot(res, ctx)
    elif intent["type"] == "trace":
        _trace_answer(res, ctx)
    elif intent["type"] == "locate":
        _locate_answer(res, ctx)
    else:
        _describe_answer(res, ctx)
    if not res["summary"]:
        if det["unresolved"]:
            res["summary"] = "Sorry, I couldn't match that to the system. " + " ".join(u["message"] for u in det["unresolved"])
        else:
            res["summary"] = "Sorry, I couldn't tell which device you mean. Try naming it, e.g. \"Restream has no audio\"."
    res["llm"] = _llm_polish(res, ctx, use_llm, history)
    prop = res["llm"].pop("_proposal", None)
    if isinstance(prop, dict):
        # the LLM's confirmable proposal (§5.10) replaces the deterministic suggestion
        res["proposal"] = prop
        res.pop("suggestion", None)
    return res


def _name(devs: Dict[str, Dict[str, Any]], dev_id: str) -> str:
    d = devs.get(dev_id)
    return str(d.get("name") or dev_id) if d else dev_id


def _endpoint_targets(g: T.PortGraph, ctx: Dict[str, Any]) -> List[str]:
    rid = ctx["intent"]["room"]
    out = []
    for d in T.doc_devices(ctx["doc"], ctx["overlay"]):
        if (d.get("room") or "") != rid or d["id"] not in g.devices:
            continue
        nodes = g.device_nodes(d["id"])
        has_in = any(_has_incoming_cable(g, n) for n in nodes)
        has_out = any(e.kind in ("cable", "route") for n in nodes for e in g.edges_out(n))
        if has_in and (T.routing_mode(d) == "none" or not has_out):
            out.append(d["id"])
    return out


def _troubleshoot(res: Dict[str, Any], ctx: Dict[str, Any]) -> None:
    doc, overlay, intent, det, devs = ctx["doc"], ctx["overlay"], ctx["intent"], ctx["det"], ctx["devs"]
    D = intent["discipline"]
    g = T.port_graph(doc, overlay, D, "all")
    targets = list(intent["targets"])
    fallback = False
    if not targets and intent["symptom"] not in (None, "general") and not det["unresolved"]:
        targets = _endpoint_targets(g, ctx)
        fallback = bool(targets)
    if not targets:
        return
    working = intent["working"]
    w_sets: List[Tuple[str, Set[str]]] = []
    for w in working:
        starts = _input_nodes(g, w, det["ports"].get(w))
        w_sets.append((w, _upstream_set(g, starts) if starts else set()))
    W: Set[str] = set().union(*[s for _, s in w_sets]) if w_sets else set()
    src_kinds = _source_kinds()

    cands: Dict[Tuple[str, ...], Tuple[Tuple[Any, ...], Dict[str, Any]]] = {}
    noncands: List[List[str]] = []
    for t in targets:
        for start in _input_nodes(g, t, det["ports"].get(t)):
            # wider bounded window: short paths from unpatched inputs must not hide the real feeds
            for p in T.upstream_paths(g, start, limit=TARGET_PATH_LIMIT):
                nodes = _nodes_of(p)
                b = max((i for i, n in enumerate(nodes) if n in W), default=None)
                if b is not None:
                    j = b
                    bdev = T.split_ref(nodes[b])[0]
                    while j + 1 < len(nodes) and T.split_ref(nodes[j + 1])[0] == bdev:
                        j += 1
                    seg = nodes[j:]
                    why = next((w for w, s in w_sets if nodes[b] in s), working[0] if working else None)
                    info = {"seg": seg, "branch_dev": bdev, "working": why, "target": t}
                    key = (0, len(seg), seg)
                else:
                    src_dev, src_port = T.split_ref(nodes[0])
                    sp = T.find_port(g.devices.get(src_dev), src_port)
                    dev_kind = (g.devices.get(src_dev) or {}).get("kind")
                    if sp is not None and sp.get("dir") == "in" and not _has_incoming_cable(g, nodes[0]) and dev_kind not in src_kinds:
                        noncands.append(nodes)
                        continue
                    seg = nodes
                    info = {"seg": seg, "branch_dev": None, "working": None, "target": t}
                    key = (1, len(seg), seg)
                k = tuple(seg)
                if k not in cands or key < cands[k][0]:
                    cands[k] = (key, info)
    from_unpatched = False
    if not cands and noncands:
        # every path starts at an unpatched input: the patched part (from the source device's
        # output onward) is still the suspect; no "not patched" notes in this case
        from_unpatched = True
        for nodes in noncands:
            sdev0 = T.split_ref(nodes[0])[0]
            j = 0
            while j + 1 < len(nodes) and T.split_ref(nodes[j + 1])[0] == sdev0:
                j += 1
            seg = nodes[j:] if j < len(nodes) - 1 else nodes
            key = (2, len(seg), seg)
            k = tuple(seg)
            if k not in cands or key < cands[k][0]:
                cands[k] = (key, {"seg": seg, "branch_dev": None, "working": None, "target": T.split_ref(nodes[-1])[0]})
    ranked = [info for _, info in sorted(cands.values(), key=lambda x: x[0])]
    best = ranked[0] if ranked else None
    has_working = bool(working)

    best_for: Dict[str, Dict[str, Any]] = {}
    for info in ranked:
        best_for.setdefault(T.split_ref(info["seg"][-1])[0], info)

    # notes for unpatched branches that also carry the discipline (one per joining port),
    # each compared with the suspect path of its own target
    seen_notes: Set[Tuple[str, str]] = set()
    for nodes in ([] if (from_unpatched or best is None) else noncands):
        own = best_for.get(T.split_ref(nodes[-1])[0])
        if own is None:
            continue
        best_set = set(own["seg"])
        merge_i = None
        for i in range(len(nodes) - 1, -1, -1):
            if nodes[i] not in best_set:
                merge_i = i
                break
        if merge_i is None:
            continue
        mdev, mport = T.split_ref(nodes[merge_i])
        sdev, sport = T.split_ref(nodes[0])
        if mdev == sdev or (nodes[merge_i], "") in seen_notes:
            continue
        seen_notes.add((nodes[merge_i], ""))
        md = g.devices.get(mdev)
        mp = T.find_port(md, mport)
        sd = g.devices.get(sdev)
        sp = T.find_port(sd, sport)
        v = T._vocab()
        native = v.medium_discipline(mp.get("medium", "")) if (v is not None and mp) else D
        phrase = D if native == D else f"embedded {D}"
        note = (f"{_port_display(md, mp)} on {_name(devs, mdev)} also carries {phrase}, "
                f"but its source ({_name(devs, sdev)} · {T.port_label(sp) or _port_display(sd, sp)}) is not patched.")
        if note not in res["notes"]:
            res["notes"].append(note)

    if best is None:
        t = targets[0]
        tdev = devs.get(t)
        res["summary"] = (f"I couldn't trace {'a ' + D + ' path' if D else 'a path'} into **{_name(devs, t)}**: "
                          f"none of its inputs{' carrying ' + D if D else ''} are patched.")
        hops = [T.node_ref(t, p["id"]) for p in T.device_ports(tdev) if p.get("dir") in ("in", "io")
                and (D is None or D in T.carries(p.get("medium", "")))]
        res["checks"] = _checks(ctx, hops or [T.node_ref(t, None)], [], working_name=_name(devs, working[0]) if working else "")
        res["confidence"] = "medium" if not fallback else "low"
        return

    rendered = [_render_path(doc, g, best["seg"], "suspect", overlay)]
    best_target = T.split_ref(best["seg"][-1])[0]
    others = [best_for[t] for t in targets if t != best_target and t in best_for]
    context = others + [info for info in ranked[1:] if info is not best and all(info is not o for o in others)]
    for info in context[:2]:
        rendered.append(_render_path(doc, g, info["seg"], "context", overlay))
    res["paths"] = rendered
    res["suspects"] = [{"device": h["device"], "port": h["port"]} for h in rendered[0]["hops"]]
    wname = _name(devs, best["working"]) if best["working"] else (_name(devs, working[0]) if working else "")
    if best["branch_dev"]:
        res["branch"] = {"device": best["branch_dev"], "reason": f"Shared with {wname}, which works"}
    res["checks"] = _checks(ctx, best["seg"], rendered[0]["cables"], working_name=wname)

    labels = [h["label"] for h in rendered[0]["hops"]]
    target_id = T.split_ref(best["seg"][-1])[0]
    tdev = devs.get(target_id) or {}
    if best["branch_dev"]:
        if D == "audio":
            noun = "stream audio" if tdev.get("kind") in ("stream", "encoder") else f"{_name(devs, target_id)} audio"
        elif D == "video":
            noun = "picture"
        else:
            noun = f"{D or 'signal'} feed"
        bolded = [f"**{lab}**" for lab in labels[:2]] + labels[2:]
        res["summary"] = f"Your {noun} takes its own path: " + " → ".join(bolded) + "."
    else:
        res["summary"] = f"Here is how the signal reaches {_name(devs, target_id)}: {rendered[0]['text']}."
    for o in others:
        res["summary"] += f" {_name(devs, T.split_ref(o['seg'][-1])[0])}: {_render_path(doc, g, o['seg'], 'context', overlay)['text']}."
    res["suggestion"] = _suggestion(ctx, best, res["checks"], rendered[0])
    if fallback:
        res["confidence"] = "low"
    elif intent["targets"] and working and best["branch_dev"]:
        res["confidence"] = "high"
    else:
        res["confidence"] = "medium"


def _hop_ctx(devs: Dict[str, Dict[str, Any]], nodes: List[str], i: int) -> Dict[str, str]:
    dev_i = T.split_ref(nodes[i])[0]
    nxt = next((n for n in nodes[i + 1:] if T.split_ref(n)[0] != dev_i), None)
    prv = next((n for n in reversed(nodes[:i]) if T.split_ref(n)[0] != dev_i), None)
    out = {"next_device": "", "next_port": "", "prev_device": ""}
    if nxt:
        nd, np_ = T.split_ref(nxt)
        out["next_device"] = _name(devs, nd)
        out["next_port"] = T.port_label(T.find_port(devs.get(nd), np_))
    if prv:
        out["prev_device"] = _name(devs, T.split_ref(prv)[0])
    return out


def _checks(ctx: Dict[str, Any], nodes: List[str], cables: List[str], working_name: str = "") -> List[Dict[str, Any]]:
    doc, devs, cl, intent = ctx["doc"], ctx["devs"], ctx["cl"], ctx["intent"]
    symptom = intent["symptom"] or "general"
    has_working = bool(intent["working"])
    out: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, ...]] = set()

    def push(key: Tuple[str, ...], text: str, dev: Optional[str], port: Optional[str], source: str, note: Optional[str]) -> None:
        if key in seen or len(out) >= 8:
            return
        seen.add(key)
        item = {"n": len(out) + 1, "text": text, "device": dev, "port": port, "source": source}
        if note:
            item["_note"] = note
        out.append(item)

    for i, n in enumerate(nodes):
        dev_id, port_id = T.split_ref(n)
        dev = devs.get(dev_id)
        port = T.find_port(dev, port_id)
        hc = _hop_ctx(devs, nodes, i)
        vals = {"device": _name(devs, dev_id), "port": T.port_label(port) or "device", "working": working_name,
                "medium": T.medium_label(port.get("medium", "")) if port else "", **hc}
        vals["feeds"] = _fill(" — it feeds {next_device} separately from {working}", vals) if working_name and hc["next_device"] else ""
        tmpl = _template(doc, (dev or {}).get("template") or "")
        lists: List[Tuple[str, List[Dict[str, Any]]]] = []
        if tmpl:
            lists.append((f"template:{tmpl.get('id') or dev.get('template')}", list(tmpl.get("checks") or [])))
        kind = (dev or {}).get("kind") or "other"
        lists.append((f"kinds:{kind}", list(cl["kinds"].get(kind) or [])))
        for prefix, checks in lists:
            for c in checks:
                if not isinstance(c, dict) or not c.get("id") or not c.get("text"):
                    continue
                if _applies(c, symptom) and _when_ok(c.get("when"), port, dev, has_working):
                    push(("hop", str(c["id"]), dev_id), _fill(str(c["text"]), vals), dev_id, port_id, f"{prefix}/{c['id']}", c.get("note"))
    cmap = {c.get("id"): c for c in doc.get("cables") or [] if isinstance(c, dict)}
    for cid in cables:
        c = cmap.get(cid)
        if not c:
            continue
        f, t = c.get("from") or {}, c.get("to") or {}
        fd, td = devs.get(f.get("device") or ""), devs.get(t.get("device") or "")
        fp, tp = T.find_port(fd, f.get("port")), T.find_port(td, t.get("port"))
        med = c.get("medium") or ""
        vals = {"device": _name(devs, f.get("device") or ""), "port": T.port_label(fp) or "device",
                "next_device": _name(devs, t.get("device") or ""), "next_port": T.port_label(tp) or "device",
                "prev_device": "", "working": working_name, "medium": T.medium_label(med), "feeds": ""}
        for mc in cl["media"].get(med) or []:
            if isinstance(mc, dict) and mc.get("id") and mc.get("text") and _applies(mc, symptom) and _when_ok(mc.get("when"), fp, fd, has_working):
                push(("media", str(mc["id"]), f.get("device") or "", t.get("device") or ""), _fill(str(mc["text"]), vals),
                     f.get("device"), f.get("port") or None, f"media:{med}/{mc['id']}", mc.get("note"))
    for gc in cl["generic"]:
        if len(out) >= 3:
            break
        if isinstance(gc, dict) and gc.get("id") and gc.get("text") and _applies(gc, symptom):
            push(("generic", str(gc["id"])), _fill(str(gc["text"]), {"working": working_name}), None, None, f"generic/{gc['id']}", None)
    return out


def _suggestion(ctx: Dict[str, Any], best: Dict[str, Any], checks: List[Dict[str, Any]], path: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    doc, devs, intent = ctx["doc"], ctx["devs"], ctx["intent"]
    seg = best["seg"]
    pick = None
    for want in ("in", "io"):
        for n in seg:
            d, p = T.split_ref(n)
            port = T.find_port(devs.get(d), p)
            if port and port.get("dir") == want:
                pick = (d, p, port)
                break
        if pick:
            break
    if not pick:
        return None
    dev_id, port_id, port = pick
    dev = next((d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id") == dev_id), None)
    if dev is None:
        return None  # overlay-only device: nothing to write in the doc
    keyword = None
    for pred in (lambda c: c["device"] == dev_id and c["port"] == port_id,
                 lambda c: c["device"] == dev_id,
                 lambda c: True):
        keyword = next((c["_note"] for c in checks if c.get("_note") and pred(c)), None)
        if keyword:
            break
    keyword = keyword or f"check {T.port_label(port)}"
    D = intent["discipline"] or "signal"
    lead = port.get("label") or D.capitalize()
    origin = best["branch_dev"] or T.split_ref(seg[0])[0]
    head = f"{lead} feed: " + (f"{_name(devs, origin)} → " if origin != dev_id else "")
    note = f"{head}{_name(devs, dev_id)} · {keyword}"
    existing = str(port.get("note") or "")
    if note in existing:
        return None
    ports = copy.deepcopy(dev.get("ports") or [])
    for p in ports:
        if isinstance(p, dict) and p.get("id") == port_id:
            p["note"] = f"{existing}; {note}" if existing else note
    return {"text": f"Add note \"{note}\" to {_name(devs, dev_id)} · {T.port_label(port)}",
            "ops": [{"op": "merge", "coll": "devices", "id": dev_id, "value": {"ports": ports}}],
            "base_revision": ctx["base_revision"]}


def _trace_answer(res: Dict[str, Any], ctx: Dict[str, Any]) -> None:
    doc, overlay, intent, det, devs = ctx["doc"], ctx["overlay"], ctx["intent"], ctx["det"], ctx["devs"]
    ents = intent["targets"]
    if not ents:
        return
    g = T.port_graph(doc, overlay, intent["discipline"], "all")

    def ref(dev_id: str) -> str:
        p = det["ports"].get(dev_id)
        return T.node_ref(dev_id, p) if p else dev_id

    qn = _normalize(res["question"])
    if len(ents) >= 2:
        a, b = ents[0], ents[-1]
        paths = T.port_paths(g, ref(a), ref(b))
        head = f"{_plural(len(paths), 'path')} from {_name(devs, a)} to {_name(devs, b)}"
    else:
        a = ents[0]
        up = qn.startswith("what feeds") or qn.startswith("how do")
        paths = T.upstream_paths(g, ref(a)) if up else T.downstream_paths(g, ref(a))
        paths.sort(key=lambda p: (-len(p["cables"]), len(p["hops"]), _nodes_of(p)))
        head = f"{_plural(len(paths), 'path')} {'feed' if len(paths) != 1 else 'feeds'} {_name(devs, a)}" if up else \
            f"{_plural(len(paths), 'path')} {'leave' if len(paths) != 1 else 'leaves'} {_name(devs, a)}"
    shown = [_render_path(doc, g, _nodes_of(p), "trace", overlay) for p in paths[:3]]
    res["paths"] = shown
    res["summary"] = head + (f": {shown[0]['text']}." if shown else ".")
    res["confidence"] = "high" if shown else "medium"


def _rack_text(doc: Doc, dev: Dict[str, Any]) -> str:
    r = dev.get("rack")
    if not isinstance(r, dict) or not r.get("id"):
        return ""
    rack = next((k for k in doc.get("racks") or [] if isinstance(k, dict) and k.get("id") == r["id"]), None)
    side = {"left": ", left half", "right": ", right half"}.get(r.get("side") or "", "")
    return f"{(rack or {}).get('name') or r['id']}, U{r.get('u')} ({r.get('face') or 'front'}{side})"


def _locate_answer(res: Dict[str, Any], ctx: Dict[str, Any]) -> None:
    doc, intent, det, devs = ctx["doc"], ctx["intent"], ctx["det"], ctx["devs"]
    if not intent["targets"]:
        return
    rooms = {r.get("id"): r for r in doc.get("rooms") or [] if isinstance(r, dict)}
    locs = {x.get("id"): x for x in doc.get("locations") or [] if isinstance(x, dict)}
    parts = []
    for dev_id in intent["targets"][:3]:
        d = devs.get(dev_id) or {}
        where = []
        if d.get("room"):
            where.append(f"in {(rooms.get(d['room']) or {}).get('name') or d['room']}")
        else:
            where.append("in shared inventory (no room assigned)")
        if d.get("location"):
            where.append(f"at {(locs.get(d['location']) or {}).get('name') or d['location']}")
        rt = _rack_text(doc, d)
        if rt:
            where.append(f"racked in {rt}")
        extra = []
        if d.get("status") and d.get("status") != "installed":
            extra.append(f"status {d['status']}")
        inv = d.get("inventory") if isinstance(d.get("inventory"), dict) else {}
        if inv.get("serial"):
            extra.append(f"serial {inv['serial']}")
        port = det["ports"].get(dev_id)
        title = _name(devs, dev_id) + (f" · {T.port_label(T.find_port(d, port))}" if port else "")
        parts.append(f"**{title}** is " + ", ".join(where) + (f"; {', '.join(extra)}" if extra else "") + ".")
    res["summary"] = " ".join(parts)
    res["confidence"] = "high"


def _connections(doc: Doc, devs: Dict[str, Dict[str, Any]], dev_id: str, port_id: Optional[str]) -> List[str]:
    out = []
    for c in doc.get("cables") or []:
        if not isinstance(c, dict):
            continue
        f, t = c.get("from") or {}, c.get("to") or {}
        tag = f" (cable {c['tag']})" if c.get("tag") else ""
        if t.get("device") == dev_id and (port_id is None or t.get("port") == port_id):
            pd = devs.get(f.get("device") or "")
            pl = T.port_label(T.find_port(pd, f.get("port")))
            out.append(f"fed by {_name(devs, f.get('device') or '')}{' · ' + pl if pl else ''}{tag}")
        if f.get("device") == dev_id and (port_id is None or f.get("port") == port_id):
            pd = devs.get(t.get("device") or "")
            pl = T.port_label(T.find_port(pd, t.get("port")))
            out.append(f"feeds {_name(devs, t.get('device') or '')}{' · ' + pl if pl else ''}{tag}")
    return out


def _describe_answer(res: Dict[str, Any], ctx: Dict[str, Any]) -> None:
    doc, intent, det, devs = ctx["doc"], ctx["intent"], ctx["det"], ctx["devs"]
    if not intent["targets"]:
        return
    dev_id = intent["targets"][0]
    d = devs.get(dev_id) or {}
    port_id = det["ports"].get(dev_id)
    if port_id:
        p = T.find_port(d, port_id) or {}
        lab = f" is labelled \"{p['label']}\"" if p.get("label") else " has no label"
        conns = _connections(doc, devs, dev_id, port_id)
        note = f" Note: {p['note']}." if p.get("note") else ""
        res["summary"] = (f"**{_name(devs, dev_id)} · {p.get('name') or port_id}**{lab}"
                          + (f"; it is {' and '.join(conns)}." if conns else "; nothing is patched to it.") + note)
    else:
        bits = []
        for p in T.device_ports(d)[:16]:
            conns = _connections(doc, devs, dev_id, p["id"])
            if p.get("label") or conns:
                lab = f" \"{p['label']}\"" if p.get("label") else ""
                bits.append(f"{p.get('name') or p['id']}{lab}" + (f" ({'; '.join(conns)})" if conns else ""))
        res["summary"] = f"**{_name(devs, dev_id)}**: " + ("; ".join(bits) if bits else "no labelled or patched ports") + "."
    res["confidence"] = "high"


# ----------------------------------------------------------------------------- LLM polish

_SYSTEM_PROMPT = ("You are Fathom's AV/lighting troubleshooting assistant. Answer ONLY from the SYSTEM DATA. Name devices and "
                  "ports exactly as given. If the data does not say, say you don't know. Keep the numbered checks; you may add "
                  "at most 3 more, marked 'extra'. Never invent equipment.")


def _llm_data(res: Dict[str, Any], ctx: Dict[str, Any], drop_context: bool = False, drop_ports: bool = False) -> Dict[str, Any]:
    doc, devs = ctx["doc"], ctx["devs"]
    cmap = {c.get("id"): c for c in doc.get("cables") or [] if isinstance(c, dict)}
    paths = []
    for p in res["paths"]:
        if drop_context and p.get("role") == "context":
            continue
        paths.append({"role": p.get("role"), "hops": [h["label"] for h in p["hops"]],
                      "cables": [{k: cmap[c].get(k) for k in ("id", "medium", "type", "tag") if cmap.get(c, {}).get(k)} for c in p["cables"] if c in cmap]})
    suspects = []
    for dev_id in dict.fromkeys(s["device"] for s in res["suspects"]):
        d = devs.get(dev_id) or {}
        item = {"device": d.get("name") or dev_id, "kind": d.get("kind"), "model": f"{d.get('manufacturer') or ''} {d.get('model') or ''}".strip()}
        if not drop_ports:
            item["ports"] = [{k: p.get(k) for k in ("name", "label", "dir", "medium", "note") if p.get(k)} for p in T.device_ports(d)]
        suspects.append(item)
    return {"room": ctx["intent"]["room"], "intent": ctx["intent"], "paths": paths, "suspects": suspects,
            "checks": [{"n": c["n"], "text": c["text"]} for c in res["checks"]],
            "working": [_name(devs, w) for w in ctx["intent"]["working"]], "notes": res["notes"]}


def _llm_messages(res: Dict[str, Any], ctx: Dict[str, Any], history: Optional[List[Dict[str, str]]], limit: int) -> List[Dict[str, str]]:
    blob = ""
    for dc, dp in ((False, False), (True, False), (True, True)):
        blob = json.dumps(_llm_data(res, ctx, dc, dp), ensure_ascii=False)
        if len(blob) <= limit:
            break
    blob = blob[:limit]
    msgs = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for h in (history or [])[-6:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("text"), str):
            msgs.append({"role": h["role"], "content": h["text"][:4000]})
    msgs.append({"role": "user", "content": res["question"] + "\n\nSYSTEM DATA (JSON):\n" + blob})
    return msgs


def _llm_polish(res: Dict[str, Any], ctx: Dict[str, Any], use_llm: bool, history: Optional[List[Dict[str, str]]]) -> Dict[str, Any]:
    for c in res["checks"]:
        c.pop("_note", None)
    settings = ctx["doc"].get("settings") or {}
    assistant_cfg = settings.get("assistant") if isinstance(settings.get("assistant"), dict) else {}
    if not use_llm or assistant_cfg.get("llm") is False:
        return {"used": False}
    try:
        from . import assistant_tools as AT
        from . import llm
    except Exception:  # pragma: no cover
        return {"used": False}
    extra = ctx.get("extra") or {}
    prov = extra.get("provider") or AT.provider()
    if prov is not None:
        # grounded tool loop (§6.9.6 tool loop): the model reads the project through tools and may propose edits
        tctx = {"doc": ctx["doc"], "overlay": ctx["overlay"], "index": ctx.get("index"), "room": ctx["intent"].get("room") or ctx.get("room") or "",
                "base_revision": ctx["base_revision"], "deterministic": {"summary": res.get("summary"), "paths": res.get("paths"), "checks": res.get("checks")}}
        for k in ("pdir", "project", "username", "role", "attachments", "manual_text"):
            if extra.get(k) is not None:
                tctx[k] = extra[k]
        out = AT.answer_with_tools(ctx["doc"], res["question"], history, tctx, provider_=prov)
        if out.get("reason") == "cap":
            return {"used": False, "reason": "cap"}
        if out.get("error"):
            r: Dict[str, Any] = {"used": False, "error": str(out["error"])}
            if out.get("proposal"):
                r["_proposal"] = out["proposal"]
            return r
        r = {"used": True, "model": out.get("model"), "text": str(out.get("text") or ""), "tools": list(out.get("used_tools") or []),
             "steps": out.get("steps"), "finish": out.get("finish")}
        if out.get("proposal"):
            r["_proposal"] = out["proposal"]
        return r
    if not llm.configured():
        return {"used": False}
    if not AT.reserve_request(AT.effective_config().get("daily_cap")):
        return {"used": False, "reason": "cap"}
    try:
        text = llm.chat(_llm_messages(res, ctx, history, llm.max_context()))
        return {"used": True, "model": llm.info().get("model"), "text": text}
    except llm.LLMError as e:
        return {"used": False, "error": str(e)}
    except Exception as e:  # never fail the request because of the LLM
        return {"used": False, "error": f"LLM call failed ({type(e).__name__})"}


__all__ = ["answer", "parse_intent", "load_checklists"]
