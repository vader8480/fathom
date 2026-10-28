"""Grounded tool calling for the assistant (SPEC §6.9.5 step 12, §6.9.6 "tool loop", FR-AST-10..13).

Read-only tools that look things up in the project (search, trace, device,
schedule, rooms, scenes, SOP pages, attachment text, optional web lookup) and
one tool, ``propose_changes``, that turns typed edits into a confirmable
proposal (``assistant_edits``). The loop never writes to the project; the
client confirms a proposal through ``POST …/assistant/apply``.

Provider: the ``fathom.llm`` package (``chat_tools`` + ``Message`` /
``ToolSpec`` / ``ToolCall`` / ``Reply``). While only the legacy ``llm.chat``
exists, minimal stand-ins below keep the loop importable; the loop is then
driven by the test-only fake provider (``FATHOM_LLM_FAKE=<fixture.json>``,
see ``FakeProvider``) and the deterministic assistant is otherwise unchanged.

Daily cap: ``llm.config.effective()["daily_cap"]`` LLM requests per server per
UTC day, counted in ``<FATHOM_DATA>/llm-usage.json`` (atomic write).
"""

from __future__ import annotations

import datetime as _dt
import html.parser
import json
import os
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

Doc = Dict[str, Any]

TOOL_OUTPUT_LIMIT = 6000
MANUAL_TEXT_LIMIT = 20 * 1024
SCHEDULE_ROWS = 60
WEB_LOOKUP_URL = "https://html.duckduckgo.com/html/?q="
WEB_LOOKUP_TIMEOUT = 5.0
DEFAULT_CONFIG: Dict[str, Any] = {"web_lookup": False, "daily_cap": 200}
SCHEDULE_KINDS = ("patch", "cables", "ip", "dmx", "bom", "inventory", "racks")
_USAGE_LOCK = threading.Lock()


# ----------------------------------------------------------------------------- provider types (shim)

@dataclass
class Message:
    role: str
    content: str = ""
    tool_calls: List[Any] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Reply:
    text: str = ""
    tool_calls: List[Any] = field(default_factory=list)
    finish: str = "stop"
    usage: Dict[str, Any] = field(default_factory=dict)
    raw: Any = None


class LLMError(Exception):
    pass


class _Api:
    """The provider's message / tool types: the real ``fathom.llm`` ones when it has ``chat_tools``, else the shim."""

    def __init__(self, mod: Any) -> None:
        real = mod is not None and callable(getattr(mod, "chat_tools", None))
        self.Message = getattr(mod, "Message", None) if real else None
        self.ToolSpec = getattr(mod, "ToolSpec", None) if real else None
        self.ToolCall = getattr(mod, "ToolCall", None) if real else None
        self.Reply = getattr(mod, "Reply", None) if real else None
        self.Message = self.Message or Message
        self.ToolSpec = self.ToolSpec or ToolSpec
        self.ToolCall = self.ToolCall or ToolCall
        self.Reply = self.Reply or Reply
        self.LLMError = getattr(mod, "LLMError", None) or LLMError


def _llm_module() -> Any:
    try:
        from . import llm
        return llm
    except Exception:  # pragma: no cover
        return None


def effective_config() -> Dict[str, Any]:
    """``llm.config.effective()`` when the package provides it, else the shim defaults
    (the fake provider's fixture may override, see :class:`FakeProvider`)."""
    out = dict(DEFAULT_CONFIG)
    mod = _llm_module()
    cfg = getattr(mod, "config", None)
    eff = getattr(cfg, "effective", None)
    if callable(eff):
        try:
            got = eff()
            if isinstance(got, dict):
                out.update(got)
        except Exception:
            pass
    return out


class LLMProvider:
    """Adapter over the real ``fathom.llm`` package."""

    name = "llm"

    def __init__(self, mod: Any) -> None:
        self.mod = mod
        self.api = _Api(mod)

    def configured(self) -> bool:
        try:
            return bool(self.mod.configured())
        except Exception:
            return False

    def info(self) -> Dict[str, Any]:
        try:
            return dict(self.mod.info())
        except Exception:
            return {"configured": self.configured()}

    def config(self) -> Dict[str, Any]:
        return effective_config()

    def chat_tools(self, messages: List[Any], tools: List[Any], **kw: Any) -> Any:
        return self.mod.chat_tools(messages, tools, **kw)


class FakeProvider:
    """Scripted provider for tests and the ``FATHOM_LLM_FAKE`` hook (test-only).

    Fixture: ``{"config": {...overrides...}, "model": "fake", "steps": [step, ...]}`` or
    ``{"scripts": [{"match": "<substring of the question>", "steps": [...]}, ...], "steps": [...default...]}``.
    A step is ``{"text": "...", "finish": "stop"}`` or ``{"tool_calls": [{"id", "name", "arguments"}], "text"?: ""}``.
    Every call records the messages it received in ``calls``; an exhausted script answers with an empty stop.
    """

    name = "fake"

    def __init__(self, script: Dict[str, Any], api: Optional[_Api] = None) -> None:
        self.script = script if isinstance(script, dict) else {"steps": list(script or [])}
        self.api = api or _Api(_llm_module())
        self.calls: List[Dict[str, Any]] = []
        self._steps: Optional[List[Dict[str, Any]]] = None
        self._pos = 0

    @classmethod
    def from_file(cls, path: str) -> "FakeProvider":
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def configured(self) -> bool:
        return True

    def info(self) -> Dict[str, Any]:
        return {"configured": True, "provider": "fake", "model": str(self.script.get("model") or "fake"), "host": None}

    def config(self) -> Dict[str, Any]:
        out = effective_config()
        if isinstance(self.script.get("config"), dict):
            out.update(self.script["config"])
        return out

    def _pick(self, messages: List[Any]) -> List[Dict[str, Any]]:
        if self._steps is not None:
            return self._steps
        question = ""
        for m in messages:
            if getattr(m, "role", "") == "user":
                question = str(getattr(m, "content", "") or "")
        steps = self.script.get("steps") or []
        for s in self.script.get("scripts") or []:
            if isinstance(s, dict) and str(s.get("match") or "").casefold() in question.casefold():
                steps = s.get("steps") or []
                break
        self._steps = [s for s in steps if isinstance(s, dict)]
        return self._steps

    def chat_tools(self, messages: List[Any], tools: List[Any], **kw: Any) -> Any:
        self.calls.append({"messages": list(messages), "tools": [getattr(t, "name", None) for t in tools], "kw": kw})
        steps = self._pick(messages)
        if self._pos >= len(steps):
            return self.api.Reply(text="", tool_calls=[], finish="stop", usage={})
        step = steps[self._pos]
        self._pos += 1
        if step.get("error"):
            raise self.api.LLMError(str(step["error"]))
        calls = []
        for i, c in enumerate(step.get("tool_calls") or []):
            args = c.get("arguments")
            calls.append(self.api.ToolCall(id=str(c.get("id") or f"call_{self._pos}_{i}"), name=str(c.get("name") or ""),
                                           arguments=args if isinstance(args, dict) else {}))
        finish = str(step.get("finish") or ("tool_calls" if calls else "stop"))
        return self.api.Reply(text=str(step.get("text") or ""), tool_calls=calls, finish=finish, usage=dict(step.get("usage") or {}))


def provider() -> Optional[Any]:
    """The tool-calling provider: the fake when ``FATHOM_LLM_FAKE`` names a fixture (tests only),
    the real package when it has ``chat_tools`` and is configured, else ``None`` (legacy ``llm.chat`` path)."""
    fake = (os.environ.get("FATHOM_LLM_FAKE") or "").strip()
    if fake:
        try:
            return FakeProvider.from_file(fake)
        except (OSError, ValueError):
            return None
    mod = _llm_module()
    if mod is not None and callable(getattr(mod, "chat_tools", None)):
        p = LLMProvider(mod)
        return p if p.configured() else None
    return None


# ----------------------------------------------------------------------------- daily cap

def _usage_path() -> Path:
    from .project import data_root

    return data_root() / "llm-usage.json"


def usage_today() -> Dict[str, Any]:
    path = _usage_path()
    day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or data.get("day") != day:
        data = {"day": day, "count": 0}
    try:
        data["count"] = int(data.get("count") or 0)
    except (TypeError, ValueError):
        data["count"] = 0
    return data


def reserve_request(cap: Any) -> bool:
    """Count one LLM request against today's cap; False when the cap is already reached.
    A missing / non-positive cap means no limit. Storage failures never block the request."""
    try:
        limit = int(cap) if cap is not None else 0
    except (TypeError, ValueError):
        limit = 0
    with _USAGE_LOCK:
        data = usage_today()
        if limit > 0 and data["count"] >= limit:
            return False
        data["count"] += 1
        try:
            from .project import _atomic_write_json

            _atomic_write_json(_usage_path(), data)
        except Exception:
            pass
    return True


# ----------------------------------------------------------------------------- helpers

def _text(obj: Any, limit: int = TOOL_OUTPUT_LIMIT) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    if len(s) <= limit:
        return s
    return s[:limit] + f"\u2026 (truncated: {len(s) - limit} more characters; narrow the query)"


def _devices(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    from . import trace as T

    return [d for d in T.doc_devices(ctx["doc"], ctx.get("overlay")) if isinstance(d, dict) and d.get("id")]


def _index(ctx: Dict[str, Any]) -> Any:
    if ctx.get("index") is None:
        from . import search as S

        ctx["index"] = S.build_index(ctx["doc"], ctx.get("overlay"))
    return ctx["index"]


def _room_name(doc: Doc, rid: str) -> str:
    for r in doc.get("rooms") or []:
        if isinstance(r, dict) and r.get("id") == rid:
            return str(r.get("name") or rid)
    return rid


def find_device(ctx: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
    """Device by id, exact name / alias / code, unique substring, then the best device search hit (score ≥ 60)."""
    from . import search as S
    from . import trace as T

    devs = _devices(ctx)
    d = T._match_device(devs, str(text or ""))
    if d is not None:
        return d
    hits = [h for h in S.search(_index(ctx), str(text or ""), limit=5, kinds=["device"]) if h.get("score", 0) >= 60]
    if hits:
        return next((x for x in devs if x["id"] == hits[0].get("id")), None)
    return None


def _call_compat(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    import inspect

    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # pragma: no cover
        return fn(*args, **kwargs)
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


# ----------------------------------------------------------------------------- tools

def t_search(args: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    from . import search as S

    q = str(args.get("query") or "").strip()
    if not q:
        return {"error": "query is required"}
    kinds = args.get("kinds")
    kinds = [str(k) for k in kinds if k] if isinstance(kinds, list) and kinds else None
    hits = S.search(_index(ctx), q, limit=20, kinds=kinds)
    return {"query": q, "hits": [{k: h.get(k) for k in ("kind", "id", "title", "subtitle", "room", "device", "port", "score", "match") if h.get(k) not in (None, "")}
                                 for h in hits]}


def t_trace(args: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    from . import trace as T

    doc, overlay = ctx["doc"], ctx.get("overlay")
    name = str(args.get("device") or "").strip()
    port = str(args.get("port") or "").strip()
    direction = str(args.get("direction") or "both").lower()
    if direction not in ("up", "down", "both"):
        return {"error": "direction must be up, down or both"}
    dev = find_device(ctx, name)
    if dev is None:
        return {"error": f"no device matches '{name}'"}
    pid = None
    if port:
        pid = T._match_port(dev, port)
        if pid is None:
            return {"error": f"no port '{port}' on {dev.get('name') or dev['id']}",
                    "ports": [T.port_label(p) or p["id"] for p in T.device_ports(dev)][:40]}
    g = T.port_graph(doc, overlay, None, "all")
    start = T.node_ref(dev["id"], pid) if pid else f"{dev['id']}:*"
    out: Dict[str, Any] = {"device": dev["id"], "name": dev.get("name") or dev["id"], "port": pid}
    if direction in ("up", "both"):
        out["upstream"] = [T.path_text(doc, p, overlay) for p in T.upstream_paths(g, start, limit=10)]
    if direction in ("down", "both"):
        out["downstream"] = [T.path_text(doc, p, overlay) for p in T.downstream_paths(g, start, limit=10)]
    return out


def _connections(doc: Doc, dev_id: str) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    names = {d.get("id"): str(d.get("name") or d.get("id")) for d in doc.get("devices") or [] if isinstance(d, dict)}
    for c in doc.get("cables") or []:
        if not isinstance(c, dict):
            continue
        f, t = c.get("from") or {}, c.get("to") or {}
        tag = f" [{c['tag']}]" if c.get("tag") else ""
        if f.get("device") == dev_id:
            out.setdefault(str(f.get("port") or "*"), []).append(f"→ {names.get(t.get('device'), t.get('device'))} · {t.get('port') or '*'}{tag}")
        if t.get("device") == dev_id:
            out.setdefault(str(t.get("port") or "*"), []).append(f"← {names.get(f.get('device'), f.get('device'))} · {f.get('port') or '*'}{tag}")
    return out


def t_device(args: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    from . import trace as T

    doc = ctx["doc"]
    name = str(args.get("id_or_name") or args.get("device") or "").strip()
    dev = find_device(ctx, name)
    if dev is None:
        return {"error": f"no device matches '{name}'"}
    conns = _connections(doc, dev["id"])
    out = {k: dev.get(k) for k in ("id", "name", "kind", "manufacturer", "model", "template", "room", "status", "location", "rack",
                                   "container", "short_code", "code", "inventory", "interfaces", "dante_name", "aliases", "note", "notes")
           if dev.get(k) not in (None, "", [], {})}
    if dev.get("room"):
        out["room_name"] = _room_name(doc, str(dev["room"]))
    if isinstance(dev.get("rack"), dict):
        rack = next((r for r in doc.get("racks") or [] if isinstance(r, dict) and r.get("id") == dev["rack"].get("id")), None)
        if rack:
            out["rack_name"] = rack.get("name") or rack.get("id")
    out["ports"] = [{k: v for k, v in (("id", p.get("id")), ("name", p.get("name")), ("label", p.get("label")), ("dir", p.get("dir")),
                                        ("medium", p.get("medium")), ("note", p.get("note")), ("connections", conns.get(p["id"])))
                     if v not in (None, "", [])} for p in T.device_ports(dev)]
    contents = [d["id"] for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("container") == dev["id"]]
    if contents:
        out["contains"] = contents
    return out


def t_schedule(args: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    doc, overlay = ctx["doc"], ctx.get("overlay")
    kind = str(args.get("kind") or "").strip().lower()
    room = str(args.get("room") or "*").strip() or "*"
    if kind not in SCHEDULE_KINDS:
        return {"error": f"kind must be one of {', '.join(SCHEDULE_KINDS)}"}
    if room != "*":
        rooms = {str(r.get("id")): r for r in doc.get("rooms") or [] if isinstance(r, dict)}
        if room not in rooms:
            hit = next((rid for rid, r in rooms.items() if str(r.get("name") or "").casefold() == room.casefold()), None)
            if hit is None:
                return {"error": f"unknown room '{room}'", "rooms": sorted(rooms)}
            room = hit
    if kind == "patch":
        from .patch import patch_schedule
        data = _call_compat(patch_schedule, doc, overlay, room=room)
    elif kind == "cables":
        from .cables import cable_schedule
        data = _call_compat(cable_schedule, doc, room=room)
    elif kind == "ip":
        from .network import ip_schedule
        data = _call_compat(ip_schedule, doc, overlay, room=room)
    elif kind == "dmx":
        from .dmx import dmx_schedule
        data = _call_compat(dmx_schedule, doc, overlay, room=room)
    elif kind == "bom":
        from .bom import bom
        data = _call_compat(bom, doc, room=room)
    elif kind == "inventory":
        from .bom import inventory_schedule
        data = _call_compat(inventory_schedule, doc, room=room)
    else:
        from .racks import rack_schedule
        data = _call_compat(rack_schedule, doc, room=room)
    data = dict(data or {})
    rows = list(data.get("rows") or [])
    cols = data.get("columns") or []
    keys = [c.get("key") if isinstance(c, dict) else c for c in cols]
    slim = []
    for r in rows[:SCHEDULE_ROWS]:
        if isinstance(r, dict):
            slim.append({k: v for k, v in r.items() if (not keys or k in keys) and v not in (None, "", [])})
        else:
            slim.append(r)
    out = {"kind": kind, "room": room, "columns": keys, "rows": slim, "total": len(rows), "shown": len(slim)}
    while len(slim) > 5 and len(json.dumps(out, ensure_ascii=False, default=str)) > TOOL_OUTPUT_LIMIT - 200:
        slim = slim[: max(5, len(slim) * 3 // 4)]  # whole rows instead of a cut JSON tail
        out.update(rows=slim, shown=len(slim))
    if out["shown"] < out["total"]:
        out["note"] = f"{out['total'] - out['shown']} more rows: filter by room or use search"
    return out


def t_list_rooms(args: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    doc = ctx["doc"]
    counts: Dict[str, int] = {}
    for d in doc.get("devices") or []:
        if isinstance(d, dict):
            counts[str(d.get("room") or "")] = counts.get(str(d.get("room") or ""), 0) + 1
    rooms = [{"id": r.get("id"), "name": r.get("name") or r.get("id"), "code": r.get("code"), "kind": r.get("kind"), "venue": r.get("venue"),
              "devices": counts.get(str(r.get("id")), 0)} for r in doc.get("rooms") or [] if isinstance(r, dict)]
    return {"rooms": rooms, "shared_inventory_devices": counts.get("", 0), "default_room": (doc.get("settings") or {}).get("default_room")}


def t_list_scenes(args: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    try:
        from . import scenes as SC
    except Exception:  # pragma: no cover
        return {"error": "scenes are not available"}
    out = []
    for s in SC.summarize(ctx["doc"]):
        out.append({k: s.get(k) for k in ("id", "name", "note", "active", "updated", "diff", "text") if s.get(k) not in (None, "")})
    return {"scenes": out}


def t_sop_page(args: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    from .markdown import plain_text

    doc = ctx["doc"]
    slug = str(args.get("slug") or "").strip()
    pages = [p for p in doc.get("pages") or [] if isinstance(p, dict)]
    page = next((p for p in pages if p.get("slug") == slug or p.get("id") == slug), None)
    if page is None:
        key = slug.casefold()
        cands = [p for p in pages if key and (key in str(p.get("title") or "").casefold() or key in str(p.get("slug") or ""))]
        if len(cands) == 1:
            page = cands[0]
        else:
            return {"error": f"no page '{slug}'", "pages": [{"slug": p.get("slug"), "title": p.get("title")} for p in pages][:40]}
    return {"slug": page.get("slug"), "title": page.get("title"), "kind": page.get("kind"), "status": page.get("status"),
            "rooms": page.get("rooms") or [], "devices": page.get("devices") or [], "text": plain_text(str(page.get("body") or ""))}


_TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log"}
_TEXT_MIME = ("text/", "application/json", "application/csv")


def attachment_text(pdir: Optional[Path], doc: Doc, att_id: str, max_chars: int = TOOL_OUTPUT_LIMIT) -> Dict[str, Any]:
    """Text of a project attachment (txt/md/csv directly, PDF via ``pdftotext``); the attachment must be in ``doc``."""
    att = next((a for a in doc.get("attachments") or [] if isinstance(a, dict) and a.get("id") == att_id), None)
    if att is None or pdir is None:
        return {"error": f"attachment '{att_id}' is not part of this project"}
    rel = str(att.get("file") or "")
    root = (Path(pdir) / "files").resolve()
    target = (Path(pdir) / rel).resolve()
    if not rel.startswith("files/") or root not in target.parents or not target.is_file():
        return {"error": f"attachment '{att_id}' has no file"}
    limit = max(200, min(int(max_chars or TOOL_OUTPUT_LIMIT), TOOL_OUTPUT_LIMIT))
    name = str(att.get("name") or target.name)
    mime = str(att.get("mime") or "")
    ext = target.suffix.lower()
    out = {"id": att_id, "name": name, "mime": mime}
    if ext == ".pdf" or mime == "application/pdf":
        tool = shutil.which("pdftotext")
        if not tool:
            out["text"] = "(PDF text extraction unavailable)"
            return out
        try:
            res = subprocess.run([tool, "-layout", "-l", "20", str(target), "-"], capture_output=True, timeout=20)
            text = res.stdout.decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            out["text"] = "(PDF text extraction failed)"
            return out
    elif ext in _TEXT_EXT or mime.startswith(_TEXT_MIME):
        try:
            text = target.read_bytes()[: limit * 4].decode("utf-8", "replace")
        except OSError:
            out["text"] = "(could not read the attachment)"
            return out
    else:
        out["text"] = f"(no text extraction for {mime or ext or 'this file type'})"
        return out
    text = text.replace("\x00", "")
    out["truncated"] = len(text) > limit
    out["text"] = text[:limit]
    return out


def t_attachment_text(args: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    att_id = str(args.get("att_id") or args.get("id") or "").strip()
    try:
        max_chars = int(args.get("max_chars") or TOOL_OUTPUT_LIMIT)
    except (TypeError, ValueError):
        max_chars = TOOL_OUTPUT_LIMIT
    return attachment_text(ctx.get("pdir"), ctx["doc"], att_id, max_chars)


class _DDGParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: List[Dict[str, str]] = []
        self._in = False
        self._href = ""
        self._buf: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Any]) -> None:
        a = dict(attrs)
        if tag == "a" and "result__a" in str(a.get("class") or "").split():
            self._in = True
            self._href = str(a.get("href") or "")
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in:
            self._in = False
            href = self._href
            try:
                q = urllib.parse.urlsplit(href)
                if q.path.endswith("/l/") or q.path.startswith("/l/"):
                    href = urllib.parse.parse_qs(q.query).get("uddg", [href])[0]
            except ValueError:
                pass
            title = " ".join("".join(self._buf).split())
            if title and href:
                self.results.append({"title": title, "url": href})


def web_lookup(query: str, timeout: float = WEB_LOOKUP_TIMEOUT) -> Dict[str, Any]:
    """Top 5 DuckDuckGo HTML results (titles + URLs), one GET, 5 s timeout."""
    q = str(query or "").strip()
    if not q:
        return {"error": "query is required"}
    url = WEB_LOOKUP_URL + urllib.parse.quote_plus(q)
    req = urllib.request.Request(url, headers={"User-Agent": "Fathom assistant (+https://github.com/vader8480/fathom)", "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(512 * 1024)
    except urllib.error.HTTPError as e:
        return {"query": q, "error": f"web lookup failed (HTTP {e.code})"}
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        return {"query": q, "error": f"web lookup failed ({type(e).__name__})"}
    parser = _DDGParser()
    try:
        parser.feed(raw.decode("utf-8", "replace"))
    except Exception:
        return {"query": q, "error": "web lookup returned an unreadable page"}
    return {"query": q, "results": parser.results[:5]}


def t_web_lookup(args: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    return web_lookup(str(args.get("query") or ""))


def t_propose_changes(args: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    from . import assistant_edits as E

    changes = args.get("changes")
    if not isinstance(changes, list) or not changes:
        return {"error": "changes must be a non-empty list of typed changes"}
    note = str(args.get("note") or "").strip()
    prop = E.new_proposal(ctx["doc"], changes, note=note, base_revision=ctx.get("base_revision"))
    ctx["proposal"] = prop
    return {"proposal_id": prop["id"], "applicable": prop["applicable"], "summary": prop["summary"], "problems": prop["problems"],
            "note": "Nothing is applied yet: the user must confirm this proposal in the app."}


_OBJ = {"type": "object"}
_STR = {"type": "string"}


def _spec(api: _Api, name: str, description: str, props: Dict[str, Any], required: Optional[List[str]] = None) -> Any:
    return api.ToolSpec(name=name, description=description,
                        parameters={"type": "object", "properties": props, "required": list(required or [])})


def tool_specs(api: _Api, config: Optional[Dict[str, Any]] = None) -> List[Any]:
    """The tool list offered to the model; ``web_lookup`` only when ``config["web_lookup"]`` is true."""
    cfg = config if config is not None else effective_config()
    out = [
        _spec(api, "search", "Search devices, ports, cables, interfaces, rooms, racks, floorplans, attachments and SOP pages by name, label, serial, IP or tag.",
              {"query": _STR, "kinds": {"type": "array", "items": _STR, "description": "optional filter: device, port, cable, interface, room, rack, floorplan, attachment, page"}}, ["query"]),
        _spec(api, "trace", "Signal paths into (up) and out of (down) a device or one of its ports, as 'Device · Port → …' text.",
              {"device": _STR, "port": {"type": "string", "description": "port label, name or id (optional)"},
               "direction": {"type": "string", "enum": ["up", "down", "both"]}}, ["device"]),
        _spec(api, "device", "Full record of one device: ports with their connections, inventory, rack position, interfaces, short code, container.",
              {"id_or_name": _STR}, ["id_or_name"]),
        _spec(api, "schedule", "A schedule table (first %d rows): patch, cables, ip, dmx, bom, inventory or racks; optionally for one room." % SCHEDULE_ROWS,
              {"kind": {"type": "string", "enum": list(SCHEDULE_KINDS)}, "room": {"type": "string", "description": "room id or name (optional)"}}, ["kind"]),
        _spec(api, "list_rooms", "Rooms of the project with device counts.", {}),
        _spec(api, "list_scenes", "Saved scenes (event setups) and what each changes against the base state.", {}),
        _spec(api, "sop_page", "Text of a procedure / SOP page by slug or title.", {"slug": _STR}, ["slug"]),
        _spec(api, "attachment_text", "Text content of a project attachment (txt, md, csv; PDF when extraction is available).",
              {"att_id": _STR, "max_chars": {"type": "integer", "minimum": 200, "maximum": TOOL_OUTPUT_LIMIT}}, ["att_id"]),
        _spec(api, "propose_changes",
              "Propose documentation edits for the user to confirm (nothing is applied by this call). Actions: add_device {template|model, name, room, id?}, "
              "remove_device {device}, connect {from: {device, port?}, to: {device, port?}, medium?}, disconnect {cable | from, to}, "
              "move_device {device, room?, rack?: {id, u, face?}, location?}, set_field {device|cable|room, port?, field, value}. "
              "Name devices and ports as the project knows them.",
              {"changes": {"type": "array", "items": {"type": "object", "properties": {"action": {"type": "string", "enum": [
                  "add_device", "remove_device", "connect", "disconnect", "move_device", "set_field"]}}, "required": ["action"]}},
               "note": {"type": "string", "description": "one line describing the change, shown to the user"}}, ["changes"]),
    ]
    if cfg.get("web_lookup"):
        out.append(_spec(api, "web_lookup", "Web search (DuckDuckGo): top 5 titles and URLs. Use only for manuals / specs the project does not contain.",
                         {"query": _STR}, ["query"]))
    return out


TOOLS: List[ToolSpec] = tool_specs(_Api(None), {"web_lookup": True})  # the full registry (for docs / tests); the loop filters by config

_RUNNERS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Any]] = {
    "search": t_search, "trace": t_trace, "device": t_device, "schedule": t_schedule, "list_rooms": t_list_rooms,
    "list_scenes": t_list_scenes, "sop_page": t_sop_page, "attachment_text": t_attachment_text, "web_lookup": t_web_lookup,
    "propose_changes": t_propose_changes,
}


def run_tool(name: str, args: Any, ctx: Dict[str, Any]) -> str:
    """Run one tool and return its JSON text (≤ 6 kB, truncated with a note). Unknown or disabled tools return an error object."""
    fn = _RUNNERS.get(str(name or ""))
    if fn is None:
        return _text({"error": f"unknown tool '{name}'"})
    if name == "web_lookup" and not (ctx.get("config") or effective_config()).get("web_lookup"):
        return _text({"error": "web_lookup is disabled on this server"})
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except ValueError:
            return _text({"error": "arguments must be a JSON object"})
    if not isinstance(args, dict):
        args = {}
    try:
        return _text(fn(args, ctx))
    except Exception as e:  # a broken tool is reported to the model, never raised
        return _text({"error": f"{name} failed ({type(e).__name__})"})


def args_summary(args: Any, limit: int = 80) -> str:
    if isinstance(args, dict):
        parts = []
        for k, v in args.items():
            if isinstance(v, (str, int, float, bool)):
                parts.append(f"{k}={v}")
            elif isinstance(v, list):
                parts.append(f"{k}[{len(v)}]")
            elif isinstance(v, dict):
                parts.append(f"{k}{{{len(v)}}}")
        s = ", ".join(parts)
    else:
        s = str(args or "")
    return s if len(s) <= limit else s[: limit - 1] + "\u2026"


# ----------------------------------------------------------------------------- the loop

SYSTEM_PROMPT = (
    "You are Fathom's AV/lighting documentation assistant for the project \"{project}\" (room: {room}; the user's role: {role}). "
    "Answer ONLY from tool results: look things up with the tools before answering and name devices and ports exactly as the tools "
    "return them. If the tools do not say, say you don't know. Never invent equipment, cables or settings. "
    "To change the documentation, call propose_changes with typed changes; the user confirms before anything is applied, so never "
    "claim a change was made. Keep answers short and concrete; use **bold** for device and port names."
)


def _history_messages(api: _Api, history: Optional[List[Dict[str, Any]]]) -> List[Any]:
    out = []
    for h in (history or [])[-6:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("text"), str) and h["text"].strip():
            out.append(api.Message(role=str(h["role"]), content=h["text"][:4000]))
    return out


def build_messages(api: _Api, doc: Doc, question: str, history: Optional[List[Dict[str, Any]]], ctx: Dict[str, Any]) -> List[Any]:
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    project = str(meta.get("title") or meta.get("org") or ctx.get("project") or "project")
    if ctx.get("project") and str(ctx["project"]) != project:
        project += f" ({ctx['project']})"
    rid = str(ctx.get("room") or "")
    room = _room_name(doc, rid) if rid else "all rooms"
    msgs = [api.Message(role="system", content=SYSTEM_PROMPT.format(project=project, room=room, role=str(ctx.get("role") or "viewer")))]
    msgs.extend(_history_messages(api, history))
    manual = str(ctx.get("manual_text") or "")
    if manual.strip():
        msgs.append(api.Message(role="user", content="Reference text pasted by the user:\n" + manual[:MANUAL_TEXT_LIMIT]))
    atts = [a for a in (ctx.get("attachments") or []) if isinstance(a, str) and a]
    if atts:
        known = {a.get("id"): a for a in doc.get("attachments") or [] if isinstance(a, dict)}
        lines = [f"- {aid}: {known[aid].get('name')}" if aid in known else f"- {aid}: (not in this project)" for aid in atts[:10]]
        msgs.append(api.Message(role="user", content="The user attached these files; read them with attachment_text when relevant:\n" + "\n".join(lines)))
    q = str(question or "").strip()
    det = ctx.get("deterministic")
    if isinstance(det, dict) and det.get("summary"):
        extra = {"summary": det.get("summary"), "paths": [p.get("text") for p in det.get("paths") or [] if isinstance(p, dict)][:3],
                 "checks": [c.get("text") for c in det.get("checks") or [] if isinstance(c, dict)][:8]}
        q += "\n\n(Fathom's built-in analysis of this question, from the project data: " + _text(extra, 2000) + ")"
    msgs.append(api.Message(role="user", content=q))
    return msgs


def _call_args(call: Any) -> Dict[str, Any]:
    args = getattr(call, "arguments", None)
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except ValueError:
            args = {}
    return args if isinstance(args, dict) else {}


def answer_with_tools(doc: Doc, question: str, history: Optional[List[Dict[str, Any]]], ctx: Dict[str, Any], max_steps: int = 6,
                      provider_: Optional[Any] = None) -> Dict[str, Any]:
    """Run the tool loop. Returns ``{"text", "used_tools", "steps", "finish", "model", "proposal", "usage"}``
    or ``{"error"}`` / ``{"reason": "cap"}`` when the LLM could not be used."""
    prov = provider_ if provider_ is not None else provider()
    if prov is None:
        return {"error": "no tool-calling LLM provider"}
    api = getattr(prov, "api", None) or _Api(_llm_module())
    cfg = dict(prov.config() if hasattr(prov, "config") else effective_config())
    ctx = dict(ctx)
    ctx["config"] = cfg
    ctx.setdefault("doc", doc)
    tools = tool_specs(api, cfg)
    msgs = build_messages(api, doc, question, history, ctx)
    used: List[Dict[str, str]] = []
    usage: Dict[str, int] = {}
    text = ""
    finish = "max_steps"
    steps = 0
    try:
        for step in range(max(1, int(max_steps))):
            if not reserve_request(cfg.get("daily_cap")):
                if step == 0:
                    return {"reason": "cap"}
                finish = "cap"
                break
            reply = prov.chat_tools(msgs, tools, temperature=0.2, max_tokens=700, tool_choice="auto")
            steps += 1
            for k, v in (getattr(reply, "usage", None) or {}).items():
                if isinstance(v, int):
                    usage[k] = usage.get(k, 0) + v
            rtext = str(getattr(reply, "text", "") or "")
            calls = list(getattr(reply, "tool_calls", None) or [])
            if rtext:
                text = rtext
            if not calls:
                finish = str(getattr(reply, "finish", "") or "stop")
                break
            msgs.append(api.Message(role="assistant", content=rtext, tool_calls=calls))
            for call in calls:
                name = str(getattr(call, "name", "") or "")
                args = _call_args(call)
                out = run_tool(name, args, ctx)
                used.append({"name": name, "args_summary": args_summary(args)})
                msgs.append(api.Message(role="tool", content=out, tool_call_id=str(getattr(call, "id", "") or ""), name=name))
    except api.LLMError as e:
        return {"error": str(e) or "LLM request failed", "used_tools": used, "proposal": ctx.get("proposal")}
    except Exception as e:  # never fail the request because of the LLM
        return {"error": f"LLM call failed ({type(e).__name__})", "used_tools": used, "proposal": ctx.get("proposal")}
    if not text and ctx.get("proposal"):
        text = "I prepared a change proposal for you to review."
    return {"text": text, "used_tools": used, "steps": steps, "finish": finish, "model": prov.info().get("model"),
            "proposal": ctx.get("proposal"), "usage": usage}


__all__ = ["TOOLS", "tool_specs", "run_tool", "answer_with_tools", "build_messages", "provider", "FakeProvider", "LLMProvider",
           "effective_config", "reserve_request", "usage_today", "attachment_text", "web_lookup", "Message", "ToolSpec", "ToolCall", "Reply"]
