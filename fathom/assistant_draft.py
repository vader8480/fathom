"""Draft a room from a free-text description (SPEC §6.9.5b, FR-AST-15..17; Knox "Quick setup" parity).

``draft(doc, text, room)`` tokenises a description such as *"X32 with an S16 stage
box, 4 ULXD wireless, 2 K12.2 on stands, ATEM Mini, QuickQ 10"* into equipment
mentions, resolves each one to a library template, a preset or a bare vocabulary
kind (never an invented device), and returns typed ``add_device`` + ``connect``
changes for ``assistant_edits.to_ops`` plus what was recognised and what was not.
The default links come from :data:`SIGNAL_FLOW`, a small table of who feeds whom
per discipline; a link is only emitted when both sides have a suitable free port
on the resolved template / preset, otherwise it is listed in ``note``.

``from_items`` is the same pipeline for the structured list the LLM passes to the
``draft_room`` tool; ``answer_draft`` is the server-side orchestration for
``POST …/assistant`` with ``mode: "draft"`` (deterministic proposal, or the tool
loop when a model is configured). Nothing here writes: the proposal is applied
only through ``POST …/assistant/apply``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

Doc = Dict[str, Any]

MAX_CHANGES = 40
MAX_COUNT = 16
DRAFT_NOTE = "Drafted from your description"
SUGGEST_MIN = 0.45

# ----------------------------------------------------------------------------- tokeniser

_WORD_NUMBERS = {"one": 1, "single": 1, "two": 2, "pair": 2, "couple": 2, "three": 3, "few": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "dozen": 12, "sixteen": 16}
_SPLIT_RE = re.compile(r"\s*(?:\r?\n|;|,|\+|&|\u2022|\s+and\s+|\s+with\s+|\s+plus\s+|\s+also\s+|\s+then\s+|\s+feeding\s+|\s+driving\s+|\s+powering\s+)\s*", re.IGNORECASE)
_LEAD_RE = re.compile(r"^(?:we have|we've got|we got|there (?:is|are)|i have|i've got|running|using|the room has|it has|has|our|some|"
                      r"the|an|a)\s+", re.IGNORECASE)
_TAIL_RE = re.compile(r"\s+(?:on (?:stands|sticks|the wall|the ceiling|a truss|truss)|at foh|at the back|in the booth|in the rack|"
                      r"for (?:the )?(?:stage|foh|stream|lobby|monitors|the band)|each|total|in total|please)$", re.IGNORECASE)
# "2 K12.2", "4 × ULXD", "2x K12.2" — but not "32 channel mixer", "4 way DSP", "2U rack"
_Q_LEAD = re.compile(r"^(\d{1,3})(?!\d)\s*(?:x|\u00d7|\*|pcs|pieces|units(?:\s+of)?)?\s*(?!(?:ch|channels?|way|inputs?|ins?|outs?|zones?|ports?|u|ru|inch|k|p|m|mm|w|ft|m)\b)(?=\S)", re.IGNORECASE)
_Q_LEAD_WORD = re.compile(r"^(" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")\s+(?:of\s+)?", re.IGNORECASE)
_Q_TAIL = re.compile(r"\s*(?:\(\s*(?:x|\u00d7)?\s*(\d{1,3})\s*\)|(?:x|\u00d7)\s*(\d{1,3})|(\d{1,3})\s*(?:pcs|pieces|units|of them))\s*$", re.IGNORECASE)
_NOISE = {"", "nothing else", "that's it", "thats it", "etc", "etc.", "and", "with", "plus"}
_STOP = {"on", "stands", "stand", "with", "for", "the", "a", "an", "in", "at", "of", "new", "old", "existing", "our", "some", "to", "from",
         "and", "plus", "each", "per", "side", "sides", "left", "right", "front", "rear", "stage", "foh", "booth", "lobby", "room", "ceiling",
         "wall", "mounted", "mount", "flown", "ground", "stacked", "powered", "active", "passive", "digital", "analog", "analogue", "small",
         "big", "large", "little", "pro", "channel", "ch", "unit", "units", "set", "pair", "rack", "rackmount", "portable"}


def _count_text(text: str) -> Tuple[int, str]:
    """``("2x K12.2", ) -> (2, "K12.2")``: leading / trailing quantities in digits or words."""
    t = " ".join(str(text or "").split())
    n = 1
    m = _Q_LEAD.match(t)
    if m and int(m.group(1)) <= MAX_COUNT and len(t) > m.end():
        n = int(m.group(1))
        t = t[m.end():].strip()
    else:
        m = _Q_LEAD_WORD.match(t)
        if m and len(t) > m.end():
            n = _WORD_NUMBERS[m.group(1).lower()]
            t = t[m.end():].strip()
    m = _Q_TAIL.search(t)
    if m and m.start() > 0:
        n2 = next((g for g in m.groups() if g), None)
        if n2 and int(n2) <= MAX_COUNT:
            n = int(n2)
            t = t[: m.start()].strip()
    t = t.strip(" .:-\u2013\u2014")
    return max(1, min(n, MAX_COUNT)), t


def tokenize(text: str) -> List[Dict[str, Any]]:
    """Equipment mentions of a description: ``[{"text", "count"}]`` (quantities stripped, filler removed)."""
    out: List[Dict[str, Any]] = []
    for raw in _SPLIT_RE.split(str(text or "")):
        seg = " ".join((raw or "").split()).strip(" .:-\u2013\u2014\u00b7")
        if not seg:
            continue
        seg = re.sub(r"^[-*\u2013\u2014\u00b7]\s*", "", seg)
        for _ in range(2):
            seg = _LEAD_RE.sub("", seg).strip()
        n, body = _count_text(seg)
        body = _LEAD_RE.sub("", body).strip()
        body = _TAIL_RE.sub("", body).strip()
        if body.lower() in _NOISE or len(body) < 2:
            continue
        out.append({"text": body, "count": n})
    return out


# ----------------------------------------------------------------------------- roles (words → kind / preset)

#: (regex, kind, preset id or None, default device name). First match wins, so longer phrases come first.
ROLES: Tuple[Tuple[str, str, Optional[str], str], ...] = (
    (r"\b(?:lighting|lx|light) (?:console|desk|board|controller)\b|\bquick ?q\b|\bhog\b|\bgrand ?ma\b|\bgrandma\b|\beos\b|\bion\b|\bcolou?rsource\b|\bavolites\b|\bchamsys\b", "lighting_console", "generic-lighting-console", "Lighting console"),
    (r"\bdmx (?:node|gateway)\b|\bart-?net node\b|\bsacn node\b|\bnode\b|\bgateway\b", "dmx_node", "generic-dmx-node", "DMX node"),
    (r"\bdimmer(?: pack| rack)?s?\b|\brelay packs?\b", "dimmer", "generic-dimmer-pack", "Dimmer pack"),
    (r"\b(?:led )?(?:pars?|washe?s?|spots?|profiles?|fresnels?|fixtures?|moving heads?|movers?|led bars?|lekos?|cyc lights?|house lights?|lights?|lamps?|strobes?|blinders?)\b", "fixture", None, "Fixture"),
    (r"\bstage ?box(?:es)?\b|\bstage racks?\b|\bi/?o racks?\b|\bio box(?:es)?\b|\bsnakes?\b|\bdigital snakes?\b", "stage_io", "generic-stagebox", "Stage box"),
    (r"\bdante (?:interface|box|converter|io)\b|\baes67\b", "stage_io", "generic-dante-interface", "Dante interface"),
    (r"\bvideo (?:switcher|mixer)\b|\bvision mixer\b|\bswitchers?\b|\batem\b|\bproduction switcher\b", "video_switcher", "generic-video-switcher", "Video switcher"),
    (r"\b(?:network |poe |ethernet |core |access |managed )?switch(?:es)?\b", "switch", "generic-switch-24", "Network switch"),
    (r"\bwi-?fi\b|\baccess points?\b|\bwaps?\b|\baps?\b|\bwireless (?:ap|access point)\b", "network", "generic-wifi-ap", "Wireless access point"),
    (r"\brouters?\b|\bfirewalls?\b", "network", "generic-router", "Router"),
    (r"\bups\b|\bbattery backup\b", "power", "generic-ups", "UPS"),
    (r"\bpdus?\b|\bpower strips?\b", "power", "generic-pdu", "PDU"),
    (r"\b(?:in-?ears?|iems?|in-?ear (?:monitors?|transmitters?)|ear ?monitors?)\b", "iem", "generic-iem-transmitter", "IEM transmitter"),
    (r"\b(?:stage|floor) monitors?\b|\bwedges?\b|\bmonitor wedges?\b", "speaker", None, "Stage monitor"),
    (r"\bsub(?:woofer)?s?\b|\bsubs\b", "speaker", None, "Subwoofer"),
    (r"\b(?:main )?speakers?\b|\bmains\b|\bloudspeakers?\b|\bpa\b|\btops\b|\bline arrays?\b|\bfills?\b|\bdelays\b|\bcolumn speakers?\b", "speaker", None, "Speaker"),
    (r"\b(?:power )?amp(?:lifier)?s?\b", "amp", "generic-amplifier", "Power amplifier"),
    (r"\bdsps?\b|\b(?:audio |loudspeaker |signal )?processors?\b", "processor", "generic-dsp", "DSP processor"),
    (r"\b(?:wireless|radio) (?:mics?|microphones?|receivers?|systems?|handhelds?|lavs?)\b|\bwireless\b|\bhandhelds?\b|\blav(?:alier)?s?\b|\bbelt ?packs?\b|\bbody ?packs?\b|\breceivers?\b", "wireless_rx", "generic-wireless-mic-rx", "Wireless receiver"),
    (r"\b(?:mixing |audio |sound |digital )?(?:console|mixer|desk|board)s?\b|\bsound ?boards?\b|\bmixing desks?\b", "console", "generic-audio-console", "Audio console"),
    (r"\bmics?\b|\bmicrophones?\b|\bpodium mics?\b|\bchoir mics?\b|\bheadsets?\b|\bgooseneck\b", "mic", None, "Microphone"),
    (r"\bprojectors?\b|\bbeamers?\b", "projector", "generic-projector", "Projector"),
    (r"\b(?:tvs?|displays?|flat ?panels?|confidence monitors?|monitors?|screens?|signage)\b", "display", "generic-display", "Display"),
    (r"\b(?:ptz|cameras?|cams?|camcorders?)\b", "camera", "generic-camera", "Camera"),
    (r"\b(?:streaming )?encoders?\b|\bdecoders?\b|\bstream(?:er|ing)?(?: box)?\b|\blivestream\b", "encoder", "generic-encoder-decoder", "Streaming encoder"),
    (r"\blaptops?\b|\bmacbooks?\b|\bmacs?\b|\bpcs?\b|\bcomputers?\b|\bpropresenter\b|\bplayback (?:machine|computer)\b|\bmedia servers?\b", "computer", None, "Laptop"),
    (r"\brecorders?\b", "recorder", None, "Recorder"),
    (r"\bintercoms?\b|\bcomms\b|\bclearcom\b", "intercom", None, "Intercom"),
    (r"\bservers?\b|\bnas\b", "computer", "generic-server", "Server"),
)
_ROLE_RE = [(re.compile(rx, re.IGNORECASE), kind, preset, name) for rx, kind, preset, name in ROLES]


def _role_of(text: str) -> Optional[Tuple[str, Optional[str], str, str]]:
    """``(kind, preset_id, name, rest)`` for the first role phrase in ``text``; ``rest`` is the text without it."""
    for rx, kind, preset, name in _ROLE_RE:
        m = rx.search(text)
        if m:
            rest = (text[: m.start()] + " " + text[m.end():]).strip()
            return kind, preset, name, rest
    return None


def _model_words(text: str) -> str:
    words = [w for w in re.split(r"\s+", text) if w and w.lower().strip("()") not in _STOP]
    return " ".join(words).strip(" -\u2013()")


def _looks_like_model(text: str) -> bool:
    t = _model_words(text)
    return bool(re.search(r"[a-z]", t, re.IGNORECASE)) and (any(ch.isdigit() for ch in t) or len(t) >= 4)


# ----------------------------------------------------------------------------- resolution

def _expanded_ports(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    from . import library

    try:
        return [p for p in library.expand_port_groups(t.get("ports") or []) if isinstance(p, dict)]
    except Exception:
        return []


def _pick_template(found: List[Dict[str, Any]], kind: Optional[str]) -> Optional[Dict[str, Any]]:
    """One of several ``list_templates`` hits: the kind's, then the shortest model name (the plain variant), then id order."""
    cands = [f for f in found if (f.get("source") or "builtin") != "preset"]
    if kind:
        same = [f for f in cands if f.get("kind") == kind]
        cands = same or cands
    if not cands:
        return None
    cands.sort(key=lambda f: (len(str(f.get("model") or f.get("name") or "")), str(f.get("manufacturer") or "").lower(), str(f.get("id"))))
    return cands[0]


def _template_by_text(doc: Optional[Doc], text: str, kind: Optional[str]) -> Optional[Dict[str, Any]]:
    """Library template for a model-ish string: id, then ``suggest_models``, then ``list_templates``."""
    from . import library
    from .library.suggest import suggest_models

    q = str(text or "").strip()
    if not q:
        return None
    t = library.get_template(q.lower(), doc)
    if t and (t.get("source") or "builtin") != "preset":
        return t
    try:
        sugg = suggest_models(text=q, kind=kind or "", doc=doc, limit=5, min_score=SUGGEST_MIN)
    except Exception:
        sugg = []
    if kind:
        same = [s for s in sugg if s.get("kind") == kind]
        sugg = same or sugg
    if sugg:
        top = [s for s in sugg if s["score"] == sugg[0]["score"]]
        # equal scores: the longest model name covers most of the query ("ATEM Mini Pro ISO" over "ATEM Mini Pro")
        best = sorted(top, key=lambda s: (-len(str(s.get("model") or "")), str(s["template"])))[0]
        t = library.get_template(best["template"], doc)
        if t:
            return t
    if _looks_like_model(q):
        words = _model_words(q).lower().split()
        found = []
        for f in library.list_templates(q=_model_words(q), doc=doc):
            # the identity fields only: a tag such as "wireless" must not turn a generic word into a specific model
            hay = " ".join(str(f.get(k) or "") for k in ("id", "manufacturer", "model", "name")).lower()
            if all(w in hay for w in words):
                found.append(f)
        pick = _pick_template(found, kind)
        if pick:
            return library.get_template(pick["id"], doc)
    return None


def _kind_name(kind: str) -> str:
    from .vocab import KINDS

    label = str((KINDS.get(kind) or {}).get("label") or kind).split(" \u00b7")[0].strip()
    return label[:-1] if label.endswith("s") and not label.endswith("ss") and " " not in label else label


def _preset_template(preset_id: Optional[str]) -> Optional[Dict[str, Any]]:
    from . import presets

    p = presets.get_preset(preset_id) if preset_id else None
    return presets.as_template(p) if p else None


def resolve_item(doc: Optional[Doc], item: Dict[str, Any]) -> Dict[str, Any]:
    """One mention → ``{"text", "count", "kind", "template"|"preset"|None, "name", "label", "ports"}`` or ``{"unknown": text}``.

    ``item`` may carry the LLM's hints: ``model``, ``kind`` (vocab kind, preset id / alias or role word), ``role``.
    """
    from . import presets
    from .vocab import KINDS

    text = " ".join(str(item.get("text") or item.get("model") or "").split())
    try:
        count = int(item.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    parsed, text = _count_text(text)
    count = max(1, min(count if count > 0 else parsed, MAX_COUNT))
    hint_model = " ".join(str(item.get("model") or "").split())
    hint_kind = str(item.get("kind") or item.get("role") or "").strip()
    kind: Optional[str] = None
    preset: Optional[str] = None
    name: Optional[str] = None
    if hint_kind:
        if hint_kind in KINDS:
            kind = hint_kind
        else:
            hr = _role_of(hint_kind)
            if hr:
                kind, preset, name = hr[0], hr[1], hr[2]
            else:
                k, pid = presets.resolve_kind(hint_kind)
                if k:
                    kind, preset = k, pid
    role = _role_of(text)
    rest = ""
    if role:
        kind = kind or role[0]
        preset = preset or role[1]
        name = name or role[2]
        rest = _model_words(role[3])
    queries = [hint_model]
    if role:
        if rest:  # "S16 stage box": the model-ish remainder, with the whole phrase first
            queries.extend([text, rest])
    else:
        queries.append(text)
    tmpl = None
    for q in queries:
        if q and q.lower() not in _STOP:
            tmpl = _template_by_text(doc, q, kind)
            if tmpl:
                break
    out: Dict[str, Any] = {"text": text or hint_model, "count": count}
    if tmpl:
        out.update(kind=str(tmpl.get("kind") or kind or "other"), template=str(tmpl["id"]), name=str(tmpl.get("name") or tmpl.get("model") or tmpl["id"]),
                   label=" ".join(x for x in (str(tmpl.get("manufacturer") or ""), str(tmpl.get("model") or tmpl.get("name") or "")) if x), ports=_expanded_ports(tmpl))
        return out
    if not kind:
        p = presets.find_preset(text) or presets.find_preset(_model_words(text))
        if p is None:
            k, pid = presets.resolve_kind(_model_words(text) or text)
            p = presets.get_preset(pid) if pid else None
            kind = k or None
        if p:
            kind, preset, name = str(p["kind"]), str(p["id"]), str(p["label"])
    if preset:
        pt = _preset_template(preset)
        if pt:
            out.update(kind=str(pt.get("kind") or kind), preset=preset, name=name or str(pt.get("name") or preset), label=str(pt.get("name") or name), ports=_expanded_ports(pt))
            return out
    if kind:
        out.update(kind=kind, name=name or _kind_name(kind), label=_kind_name(kind), ports=[])
        return out
    return {"unknown": text or hint_model, "count": count}


# ----------------------------------------------------------------------------- default links

#: Who feeds whom. ``policy``: ``each-from`` = every source device → the first destination device;
#: ``each-to`` = the first source device → every destination device; ``spread`` = destinations round-robin
#: over the sources; ``daisy`` = first source → first destination → next destination … (DMX chains);
#: ``fan`` = like each-from but one link per matching output of the source (receiver channels).
#: ``unless``: the rule is skipped when the draft has a device of one of those kinds (the chain goes through it instead).
SIGNAL_FLOW: Tuple[Dict[str, Any], ...] = (
    {"from": ("mic",), "to": ("stage_io",), "media": ("analog",), "policy": "each-from"},
    {"from": ("mic",), "to": ("console",), "media": ("analog",), "policy": "each-from", "unless": ("stage_io",)},
    {"from": ("wireless_rx",), "to": ("console",), "media": ("analog", "dante"), "policy": "fan"},
    {"from": ("stage_io",), "to": ("console",), "media": ("aes50", "dante", "network"), "policy": "each-from"},
    {"from": ("console",), "to": ("processor",), "media": ("dante", "aes3", "analog"), "policy": "each-to"},
    {"from": ("console",), "to": ("amp",), "media": ("dante", "aes3", "analog"), "policy": "each-to", "unless": ("processor",)},
    {"from": ("console",), "to": ("speaker", "pa"), "media": ("analog",), "policy": "each-to", "unless": ("processor", "amp")},
    {"from": ("processor",), "to": ("amp",), "media": ("analog", "dante", "aes3"), "policy": "each-to"},
    {"from": ("processor",), "to": ("speaker", "pa"), "media": ("analog",), "policy": "each-to", "unless": ("amp",)},
    {"from": ("amp",), "to": ("speaker", "pa"), "media": ("speaker",), "policy": "spread"},
    {"from": ("console",), "to": ("iem",), "media": ("analog",), "policy": "each-to"},
    {"from": ("camera",), "to": ("video_switcher",), "media": ("sdi", "hdmi"), "policy": "each-from"},
    {"from": ("camera",), "to": ("encoder",), "media": ("sdi", "hdmi"), "policy": "each-from", "unless": ("video_switcher",)},
    {"from": ("computer",), "to": ("video_switcher",), "media": ("hdmi",), "policy": "each-from"},
    {"from": ("computer",), "to": ("projector", "display"), "media": ("hdmi",), "policy": "each-from", "unless": ("video_switcher",)},
    {"from": ("video_switcher",), "to": ("projector",), "media": ("hdmi", "sdi", "hdbaset"), "policy": "each-to"},
    {"from": ("video_switcher",), "to": ("display",), "media": ("hdmi", "sdi", "hdbaset"), "policy": "each-to"},
    {"from": ("video_switcher",), "to": ("encoder",), "media": ("sdi", "hdmi", "usb"), "policy": "each-to"},
    {"from": ("lighting_console",), "to": ("dmx_node",), "media": ("sacn", "network"), "policy": "each-to"},
    {"from": ("lighting_console",), "to": ("dimmer",), "media": ("dmx",), "policy": "daisy", "unless": ("dmx_node",)},
    {"from": ("lighting_console",), "to": ("fixture",), "media": ("dmx",), "policy": "daisy", "unless": ("dmx_node", "dimmer")},
    {"from": ("dmx_node",), "to": ("dimmer",), "media": ("dmx",), "policy": "daisy"},
    {"from": ("dmx_node",), "to": ("fixture",), "media": ("dmx",), "policy": "daisy", "unless": ("dimmer",)},
    {"from": ("dimmer",), "to": ("fixture",), "media": ("dmx",), "policy": "daisy"},
    {"from": ("*",), "to": ("switch",), "media": ("network",), "policy": "each-from"},
)


class _Dev:
    """A planned device: its name, kind and the free-port budget per (side, medium)."""

    def __init__(self, name: str, kind: str, ports: List[Dict[str, Any]], mention: int) -> None:
        self.name = name
        self.kind = kind
        self.mention = mention
        self.cap: Dict[Tuple[str, str], int] = {}
        self.groups: Dict[Tuple[str, str], Dict[str, int]] = {}
        for p in ports:
            d = str(p.get("dir") or "io")
            m = str(p.get("medium") or "")
            if m in ("power", "rf", "power_dc", ""):
                continue
            for side in (("out", "in") if d == "io" else (d,)):
                self.cap[(side, m)] = self.cap.get((side, m), 0) + 1
                g = self.groups.setdefault((side, m), {})
                g[str(p.get("group") or p.get("id"))] = g.get(str(p.get("group") or p.get("id")), 0) + 1

    def free(self, side: str, medium: str) -> int:
        return self.cap.get((side, medium), 0)

    def channels(self, side: str, medium: str) -> int:
        """Size of the largest port group of that side / medium (a receiver's channel outputs, not its mix out)."""
        return max(self.groups.get((side, medium), {}).values() or [0])

    def take(self, side: str, medium: str) -> None:
        self.cap[(side, medium)] = self.cap.get((side, medium), 0) - 1


def _link(a: _Dev, b: _Dev, media: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
    for m in media:
        if a.free("out", m) > 0 and b.free("in", m) > 0:
            a.take("out", m)
            b.take("in", m)
            return {"action": "connect", "from": {"device": a.name}, "to": {"device": b.name}, "medium": m}
    return None


def default_links(devs: List[_Dev]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """``connect`` changes from :data:`SIGNAL_FLOW` and the human lines for links that had no matching ports."""
    kinds = {d.kind for d in devs}
    links: List[Dict[str, Any]] = []
    skipped: List[str] = []
    seen = set()

    def add(a: _Dev, b: _Dev, media: Tuple[str, ...], again: bool = False) -> bool:
        if a is b or ((a.name, b.name) in seen and not again):
            return False
        ch = _link(a, b, media)
        if ch is None:
            if not again:
                skipped.append("%s \u2192 %s (no matching free %s port)" % (a.name, b.name, "/".join(media)))
            return False
        seen.add((a.name, b.name))
        links.append(ch)
        return True

    for rule in SIGNAL_FLOW:
        if any(k in kinds for k in rule.get("unless") or ()):
            continue
        dst = [d for d in devs if d.kind in rule["to"]]
        if not dst:
            continue
        if rule["from"] == ("*",):
            src = [d for d in devs if d.kind not in rule["to"] and d.free("out", "network") > 0]
        else:
            src = [d for d in devs if d.kind in rule["from"]]
        if not src:
            continue
        policy = rule["policy"]
        media = tuple(rule["media"])
        if policy == "each-from":
            for a in src:
                add(a, dst[0], media)
        elif policy == "fan":  # one link per receiver channel (at most 4), all into the same console
            for a in src:
                n = max(1, min(4, max(a.channels("out", m) for m in media)))
                for i in range(n):
                    if not add(a, dst[0], media, again=i > 0):
                        break
        elif policy == "each-to":
            for b in dst:
                add(src[0], b, media)
        elif policy == "spread":
            for i, b in enumerate(dst):
                add(src[i % len(src)], b, media)
        elif policy == "daisy":
            prev = src[0]
            for b in dst:
                if add(prev, b, media):
                    prev = b
    return links, skipped


# ----------------------------------------------------------------------------- public API

def resolve_room(doc: Doc, text: Any) -> Optional[str]:
    """Room id for an id / name / code; ``None`` when the project has no such room."""
    t = str(text or "").strip()
    if not t:
        return None
    rooms = [r for r in doc.get("rooms") or [] if isinstance(r, dict) and r.get("id")]
    for r in rooms:
        if str(r["id"]) == t:
            return str(r["id"])
    low = t.casefold()
    for r in rooms:
        if str(r.get("name") or "").casefold() == low or str(r.get("code") or "").casefold() == low:
            return str(r["id"])
    hits = [r for r in rooms if low in str(r.get("name") or "").casefold()]
    return str(hits[0]["id"]) if len(hits) == 1 else None


def _taken_names(doc: Optional[Doc]) -> set:
    return {str(d.get("name") or "").casefold() for d in (doc or {}).get("devices") or [] if isinstance(d, dict)}


def _unique_names(base: str, count: int, taken: set) -> List[str]:
    out: List[str] = []
    if count == 1 and base.casefold() not in taken:
        taken.add(base.casefold())
        return [base]
    i = 1 if count > 1 else 2
    while len(out) < count:
        cand = "%s %d" % (base, i)
        i += 1
        if cand.casefold() in taken:
            continue
        taken.add(cand.casefold())
        out.append(cand)
    return out


def from_items(doc: Optional[Doc], items: List[Dict[str, Any]], room: Optional[str] = None) -> Dict[str, Any]:
    """Structured mentions → ``{"changes", "recognised", "unknown", "note"}`` (the ``draft_room`` tool and :func:`draft`)."""
    doc = doc if isinstance(doc, dict) else {}
    rid = resolve_room(doc, room) or (str(room).strip() if room else "")
    recognised: List[Dict[str, Any]] = []
    unknown: List[str] = []
    devs: List[_Dev] = []
    adds: List[Dict[str, Any]] = []
    taken = _taken_names(doc)
    for i, raw in enumerate(items or []):
        item = raw if isinstance(raw, dict) else {"text": str(raw)}
        if not str(item.get("text") or item.get("model") or "").strip():
            continue
        r = resolve_item(doc, item)
        if r.get("unknown"):
            if r["unknown"] not in unknown:
                unknown.append(r["unknown"])
            continue
        rec = {"text": r["text"], "count": r["count"], "kind": r["kind"], "label": r["label"]}
        if r.get("template"):
            rec["template"] = r["template"]
        elif r.get("preset"):
            rec["preset"] = r["preset"]
        recognised.append(rec)
        for name in _unique_names(r["name"], r["count"], taken):
            ch: Dict[str, Any] = {"action": "add_device", "name": name, "room": rid}
            if r.get("template"):
                ch["template"] = r["template"]
            elif r.get("preset"):
                ch["template"] = r["preset"]
            else:
                ch["kind"] = r["kind"]
            adds.append(ch)
            devs.append(_Dev(name, r["kind"], r.get("ports") or [], i))
    links, skipped = default_links(devs)
    notes: List[str] = []
    changes = adds[:MAX_CHANGES]
    left_adds = [c["name"] for c in adds[MAX_CHANGES:]]
    room_left = MAX_CHANGES - len(changes)
    changes.extend(links[:room_left])
    left_links = links[room_left:]
    if left_adds or left_links:
        bits = []
        if left_adds:
            bits.append("%d device%s (%s%s)" % (len(left_adds), "s" if len(left_adds) != 1 else "", ", ".join(left_adds[:6]), "\u2026" if len(left_adds) > 6 else ""))
        if left_links:
            bits.append("%d connection%s" % (len(left_links), "s" if len(left_links) != 1 else ""))
        notes.append("Only the first %d changes are in this draft; left out: %s. Apply, then describe the rest." % (MAX_CHANGES, " and ".join(bits)))
    if skipped:
        notes.append("Not patched (no matching ports on the chosen type): " + "; ".join(skipped[:8]) + ("\u2026" if len(skipped) > 8 else "") + ".")
    bare = [r["label"] for r in recognised if not r.get("template") and not r.get("preset")]
    if bare:
        notes.append("Added without ports (no template or preset for the type): " + ", ".join(dict.fromkeys(bare)) + ".")
    return {"changes": changes, "recognised": recognised, "unknown": unknown, "note": " ".join(notes)}


def draft(doc: Optional[Doc], text: str, room: Optional[str] = None) -> Dict[str, Any]:
    """Free text → ``{"changes", "recognised", "unknown", "note"}``; pure apart from reading the equipment library."""
    return from_items(doc, tokenize(text), room)


def summary_text(doc: Doc, res: Dict[str, Any], room: str) -> str:
    adds = [c for c in res.get("changes") or [] if c.get("action") == "add_device"]
    links = [c for c in res.get("changes") or [] if c.get("action") == "connect"]
    rname = next((str(r.get("name") or r.get("id")) for r in doc.get("rooms") or [] if isinstance(r, dict) and r.get("id") == room), room or "the room")
    if not adds:
        return ("I couldn't recognise any equipment in that description. Name models (X32, ULXD4D, K12.2) or kinds "
                "(mixer, wireless, speakers, projector, lighting console) separated by commas.")
    s = "Drafted **%d device%s** and **%d connection%s** for **%s**." % (len(adds), "s" if len(adds) != 1 else "", len(links), "s" if len(links) != 1 else "", rname)
    if res.get("unknown"):
        s += " Couldn't place: " + ", ".join(res["unknown"][:8]) + ("\u2026" if len(res["unknown"]) > 8 else "") + "."
    return s


def answer_draft(doc: Doc, text: str, room: str, *, use_llm: bool = True, history: Optional[List[Dict[str, Any]]] = None,
                 base_revision: Optional[int] = None, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The §5.10 answer for ``mode: "draft"``: a proposal of ``add_device`` + ``connect`` changes plus ``draft`` details.

    With a tool-calling provider the model drives ``draft_room`` → ``propose_changes`` (§6.9.6 tool loop);
    without one (or on cap / error / no proposal) the deterministic :func:`draft` is proposed directly.
    """
    from . import assistant_edits as E
    from . import assistant_tools as AT

    q = str(text or "").strip()
    rid = resolve_room(doc, room) or str(room or "")
    base = base_revision if base_revision is not None else int(doc.get("revision") or 0)
    extra = dict(ctx or {})
    res: Dict[str, Any] = {"question": q, "intent": {"type": "draft", "symptom": None, "discipline": None, "targets": [], "working": [], "room": rid},
                           "summary": "", "paths": [], "branch": None, "suspects": [], "checks": [], "notes": [], "suggestion": None,
                           "confidence": "low", "unresolved": [], "llm": {"used": False}}
    settings = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
    acfg = settings.get("assistant") if isinstance(settings.get("assistant"), dict) else {}
    prov = None
    if use_llm and acfg.get("llm") is not False:
        prov = extra.get("provider") or AT.provider()
    det: Optional[Dict[str, Any]] = None
    prop: Optional[Dict[str, Any]] = None
    llm: Dict[str, Any] = {"used": False}
    if prov is not None:
        holder: Dict[str, Any] = {}
        tctx = {"doc": doc, "overlay": extra.get("overlay"), "room": rid, "mode": "draft", "base_revision": base, "draft": holder}
        for k in ("pdir", "project", "username", "role", "attachments", "manual_text"):
            if extra.get(k) is not None:
                tctx[k] = extra[k]
        out = AT.answer_with_tools(doc, q, history, tctx, provider_=prov)
        if out.get("reason") == "cap":
            llm = {"used": False, "reason": "cap"}
        elif out.get("error"):
            llm = {"used": False, "error": str(out["error"])}
        else:
            llm = {"used": True, "model": out.get("model"), "text": str(out.get("text") or ""), "tools": list(out.get("used_tools") or []),
                   "steps": out.get("steps"), "finish": out.get("finish")}
        if isinstance(out.get("proposal"), dict):
            prop = out["proposal"]
            if holder.get("recognised") is not None:
                det = holder
    if prop is None:
        det = draft(doc, q, rid)
        prop = E.new_proposal(doc, det["changes"], note=DRAFT_NOTE, base_revision=base) if det["changes"] else None
    if det is None:
        det = draft(doc, q, rid)
    res["draft"] = {"recognised": det.get("recognised") or [], "unknown": det.get("unknown") or [], "note": det.get("note") or ""}
    res["summary"] = summary_text(doc, {"changes": (prop or {}).get("changes") or [], "unknown": res["draft"]["unknown"]}, rid)
    if res["draft"]["note"]:
        res["notes"].append(res["draft"]["note"])
    res["llm"] = llm
    if prop is not None:
        res["proposal"] = prop
        res.pop("suggestion", None)
        res["confidence"] = "high" if prop.get("applicable") and not res["draft"]["unknown"] else "medium"
    return res


__all__ = ["MAX_CHANGES", "DRAFT_NOTE", "ROLES", "SIGNAL_FLOW", "tokenize", "resolve_item", "resolve_room", "from_items", "draft",
           "default_links", "answer_draft", "summary_text"]
