"""Hardware model suggestions: match manufacturer / model strings from imports and
discovery against the equipment library.

Discovery probes (mDNS / Dante TXT records, Yamaha SCP ``devinfo product``,
SNMP ENTITY-MIB ``entPhysicalModelName``, UniFi ``model``, LLDP system
description) and importers (Dante preset XML ``manufacturer_name`` /
``model_name``, Dante Device Info ``Model Name``, generic CSV ``manufacturer`` /
``model`` columns, MagicQ head types) all produce free-text identity strings.
:func:`suggest_models` turns them into ranked library templates so the UI can
offer "Suggested model: Yamaha Rio1608-D (high)" next to a device about to be
created, and :func:`apply_template_to_device` sets the device up exactly the way
the "Add gear" dialog does when the suggestion is accepted.

Scoring (0–1, best first):

- the normalised model equals the template's model or name ..... 0.95
  (``Rio1608-D`` = ``Rio1608 D`` = ``rio1608-d``; a vendor prefix repeated in the
  model string is ignored: ``Blackmagic Videohub 20x20 12G`` = ``Videohub 20x20 12G``)
- the template's model tokens appear in order inside the model string ... 0.80
  (``TF-Rack NY64-D`` → ``TF-Rack``)
- the template's model appears in free text (device name, Dante name,
  subtitle) ................................................... 0.70
- the model is a *variant* of the template (same base, suffix differs:
  ``Rio1608-D`` vs ``Rio1608-D2``, ``DM7`` vs ``DM7 Compact``) ........ 0.50
  Variants are never reported as exact matches; they rank below the exact hit
  so the user can still pick them deliberately.
- the family token matches (``Rio1608`` inside ``Y004-Yamaha-Rio1608-STG``) .. 0.45
- fuzzy string similarity ≥ 0.80 .................... 0.40–0.60 (capped)

A manufacturer that agrees adds +0.05 (``Yamaha Corporation`` → ``Yamaha``,
``Ubiquiti Inc`` → ``Ubiquiti``, ``Allen & Heath`` → ``Allen-Heath``); one that
clearly disagrees multiplies the score by 0.4. ``high`` ≥ 0.85, ``medium`` ≥ 0.60,
else ``low``. Generic presets (``source: preset``) are never suggested: they
are types, not models.
"""

from __future__ import annotations

import copy
import difflib
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

Doc = Dict[str, Any]

HIGH, MEDIUM = 0.85, 0.60
MIN_SCORE = 0.40

#: irregular vendor spellings -> canonical key (after :func:`_norm`)
VENDOR_ALIASES: Dict[str, str] = {
    "a h": "allen heath", "allen and heath": "allen heath", "ah": "allen heath",
    "ubnt": "ubiquiti", "unifi": "ubiquiti",
    "bmd": "blackmagic",
    "lacoustics": "l acoustics",
    "ams neve": "neve",
    "etc": "etc", "electronic theatre controls": "etc",
    "ma": "ma", "ma lighting": "ma",
    "chamsys": "chamsys",
    "music tribe": "behringer",
    "harman": "harman", "jbl professional": "jbl",
    "netgear inc": "netgear",
    "audinate": "audinate",
}

#: corporate / descriptive words that do not identify a vendor
_VENDOR_NOISE = frozenset((
    "corporation", "corp", "inc", "incorporated", "ltd", "limited", "llc", "gmbh", "co", "company", "pty", "plc", "ag", "bv", "sa",
    "the", "professional", "pro", "design", "designs", "video", "audio", "electronics", "systems", "system", "networks", "network",
    "technology", "technologies", "engineering", "products", "group", "international", "lighting", "sound", "communications",
    "america", "usa", "europe", "uk", "japan", "kk",
))

_NORM_RE = re.compile(r"[^a-z0-9]+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _norm(text: Any) -> str:
    return _NORM_RE.sub(" ", str(text or "").lower()).strip()


def _tokens(text: Any) -> List[str]:
    return _TOKEN_RE.findall(str(text or "").lower())


def _compact(tokens: Iterable[str]) -> str:
    return "".join(tokens)


def vendor_key(text: Any) -> str:
    """Canonical vendor key: ``Yamaha Corporation`` → ``yamaha``, ``Allen & Heath`` → ``allen heath``, ``""`` when unknown."""
    n = _norm(text)
    if not n:
        return ""
    if n in VENDOR_ALIASES:
        return VENDOR_ALIASES[n]
    words = [w for w in n.split() if w not in _VENDOR_NOISE]
    key = " ".join(words) if words else n
    return VENDOR_ALIASES.get(key, key)


def _vendor_tokens(*keys: str) -> set:
    out: set = set()
    for k in keys:
        out.update(k.split())
    return out


def _model_tokens(text: Any, vendors: set) -> List[str]:
    toks = _tokens(text)
    # drop a leading vendor prefix ("Blackmagic Videohub 20x20 12G", "Yamaha Rio1608-D") but keep vendor words inside a model
    while toks and toks[0] in vendors:
        toks = toks[1:]
    return toks


def _variant_of(a: List[str], b: List[str]) -> bool:
    """``a`` and ``b`` share a base and differ in a short trailing suffix (``rio1608 d`` / ``rio1608 d2``, ``x32`` / ``x32 compact``)."""
    if not a or not b or a == b:
        return False
    ca, cb = _compact(a), _compact(b)
    if ca == cb:
        return False
    short, long_ = (a, b) if len(ca) <= len(cb) else (b, a)
    cs, cl = _compact(short), _compact(long_)
    if cl.startswith(cs) and len(cs) >= 3 and (len(cl) - len(cs) <= 2 or long_[: len(short)] == short):
        return True
    if len(a) == len(b) and a[:-1] == b[:-1] and len(a) >= 2:  # same tokens except the last, and the lasts share a prefix
        la, lb = a[-1], b[-1]
        return bool(la and lb) and (la.startswith(lb) or lb.startswith(la))
    return False


def _in_order(needle: List[str], hay: List[str]) -> bool:
    """``needle`` occurs in ``hay`` as a contiguous run of tokens."""
    n = len(needle)
    if not n or n > len(hay):
        return False
    return any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def level_for(score: float) -> str:
    return "high" if score >= HIGH else ("medium" if score >= MEDIUM else "low")


def _candidates(doc: Optional[Doc]) -> List[Dict[str, Any]]:
    from . import _merged

    return [t for t in _merged(doc).values() if isinstance(t, dict) and t.get("id") and (t.get("source") or "builtin") != "preset"]


def _score_template(t: Dict[str, Any], q_vendor: str, model_toks: List[str], text_toks: List[str], all_vendors: set, shown: str = "") -> Optional[Tuple[float, str]]:
    t_vendor = vendor_key(t.get("manufacturer")) or vendor_key(t.get("brand"))
    vendors = all_vendors | _vendor_tokens(t_vendor)
    variants: List[List[str]] = []
    for key in ("model", "name"):
        toks = _model_tokens(t.get(key), vendors)
        if toks and toks not in variants:
            variants.append(toks)
    if not variants:
        return None
    q_model = _model_tokens(_compact_join(model_toks), vendors) if model_toks else []
    shown = shown or _compact_join(model_toks)
    q_text = [tok for tok in text_toks if tok not in vendors]
    best: Optional[Tuple[float, str]] = None

    def consider(score: float, why: str) -> None:
        nonlocal best
        if best is None or score > best[0]:
            best = (score, why)

    label = str(t.get("model") or t.get("name") or t["id"])
    for tt in variants:
        ct = _compact(tt)
        if q_model:
            cq = _compact(q_model)
            if cq == ct:
                consider(0.95, 'model "%s" = %s' % (shown, label))
                continue
            if len(ct) >= 3 and _in_order(tt, q_model):
                consider(0.80, 'model "%s" contains %s' % (shown, label))
                continue
            if _variant_of(q_model, tt):
                consider(0.50, 'variant: "%s" vs %s' % (shown, label))
                continue
            ratio = difflib.SequenceMatcher(None, cq, ct).ratio()
            if ratio >= 0.80 and min(len(cq), len(ct)) >= 4:
                consider(round(0.40 + (ratio - 0.80), 2), 'model "%s" resembles %s (%d%%)' % (shown, label, round(ratio * 100)))
        if q_text:
            if len(ct) >= 3 and _in_order(tt, q_text):
                consider(0.70, 'name mentions %s' % label)
            elif len(ct) >= 3 and ct in _compact(q_text) and any(c.isdigit() for c in ct):
                consider(0.70, 'name mentions %s' % label)
            elif len(tt) >= 2 and tt[0] in q_text and any(c.isdigit() for c in tt[0]) and len(tt[0]) >= 4:
                consider(0.45, 'name mentions the %s family' % tt[0])
    if best is None:
        return None
    score, why = best
    if q_vendor and t_vendor:
        if q_vendor == t_vendor or q_vendor in t_vendor.split() or t_vendor in q_vendor.split():
            score = min(1.0, score + 0.05)
            why += " · manufacturer %s" % (t.get("manufacturer") or t_vendor)
        else:
            score *= 0.4
            why += " · but manufacturer differs (%s vs %s)" % (q_vendor, t.get("manufacturer") or t_vendor)
    elif t_vendor and not q_vendor and t_vendor in " ".join(text_toks):
        score = min(1.0, score + 0.05)
        why += " · name mentions %s" % (t.get("manufacturer") or t_vendor)
    return round(score, 2), why


def _compact_join(tokens: List[str]) -> str:
    return " ".join(tokens)


def suggest_models(manufacturer: str = "", model: str = "", text: str = "", kind: str = "", doc: Optional[Doc] = None,
                   limit: int = 5, min_score: float = MIN_SCORE) -> List[Dict[str, Any]]:
    """Ranked library templates for identity strings from a probe or import.

    ``manufacturer`` / ``model`` are the structured fields when the source has them; ``text`` is
    everything else that may name the box (device name, Dante name, subtitle, hostname). Returns
    ``[{template, manufacturer, model, name, kind, source, score, level, evidence}, ...]``.
    """
    q_vendor = vendor_key(manufacturer)
    model_toks = _tokens(model)
    text_toks = _tokens(text)
    if not model_toks and not text_toks:
        return []
    if not q_vendor:  # "Yamaha Rio1608-D" in a model cell: take the vendor from the string when the library knows it
        known = {vendor_key(t.get("manufacturer")) for t in _candidates(doc)} - {""}
        for toks in (model_toks, text_toks):
            for i in range(len(toks)):
                for n in (2, 1):
                    cand = " ".join(toks[i:i + n])
                    if cand in known:
                        q_vendor = cand
                        break
                if q_vendor:
                    break
            if q_vendor:
                break
    all_vendors = _vendor_tokens(q_vendor, vendor_key(manufacturer))
    out: List[Dict[str, Any]] = []
    for t in _candidates(doc):
        res = _score_template(t, q_vendor, model_toks, text_toks, all_vendors, shown=str(model or "").strip())
        if res is None or res[0] < min_score:
            continue
        score, why = res
        out.append({
            "template": t["id"], "manufacturer": t.get("manufacturer", ""), "model": t.get("model", ""), "name": t.get("name") or t.get("model", ""),
            "kind": t.get("kind", ""), "source": t.get("source") or "builtin", "score": score, "level": level_for(score), "evidence": why,
            "kind_matches": (not kind or not t.get("kind") or kind in ("other", "") or t.get("kind") == kind),
        })
    out.sort(key=lambda s: (-s["score"], not s["kind_matches"], str(s["manufacturer"]).lower(), str(s["model"]).lower(), s["template"]))
    return out[: max(1, int(limit or 5))]


def suggest_for_device(dev: Dict[str, Any], doc: Optional[Doc] = None, limit: int = 5) -> List[Dict[str, Any]]:
    """Suggestions for a document-shaped (overlay / proposed) device; ``[]`` when it already has a template."""
    if not isinstance(dev, dict) or dev.get("template"):
        return []
    text = " ".join(str(dev.get(k) or "") for k in ("name", "sub", "dante_name", "hostname"))
    text += " " + " ".join(str(a) for a in dev.get("aliases") or [])
    for itf in dev.get("interfaces") or []:
        if isinstance(itf, dict) and itf.get("hostname"):
            text += " " + str(itf["hostname"])
    return suggest_models(str(dev.get("manufacturer") or ""), str(dev.get("model") or ""), text, kind=str(dev.get("kind") or ""), doc=doc, limit=limit)


def apply_template_to_device(dev: Dict[str, Any], t: Dict[str, Any]) -> Dict[str, Any]:
    """Set a device up from a template the way the "Add gear" dialog does (in place; returns ``dev``).

    Kind, discipline, manufacturer, model, brand, ``template``, Dante flag, DMX footprint and the
    expanded port groups come from the template; labels on existing ports carry over to the template
    port with the same medium and index. Identity (id, name, room, interfaces, inventory, notes) stays.
    """
    from . import expand_port_groups
    from ..vocab import kind_discipline

    dev["kind"] = t.get("kind") or dev.get("kind") or "other"
    if t.get("discipline") and t["discipline"] != kind_discipline(dev["kind"]):
        dev["discipline"] = t["discipline"]
    else:
        dev.pop("discipline", None)
    for k in ("manufacturer", "model", "brand"):
        if t.get(k):
            dev[k] = t[k]
    dev["template"] = t["id"]
    if t.get("dante"):
        dev["dante"] = True
    if t.get("dmx_footprint"):
        dmx = dict(dev.get("dmx") or {})
        dmx["footprint"] = t["dmx_footprint"]
        dev["dmx"] = dmx
    old = [p for p in dev.get("ports") or [] if isinstance(p, dict)]
    ports = expand_port_groups(copy.deepcopy(t.get("ports") or []))
    labels = {(p.get("medium"), p.get("dir"), p.get("index")): p.get("label") for p in old if p.get("label") and p.get("index") is not None}
    for p in ports:
        lab = labels.get((p.get("medium"), p.get("dir"), p.get("index")))
        if lab and not p.get("label"):
            p["label"] = lab
    dev["ports"] = ports
    return dev


__all__ = ["HIGH", "MEDIUM", "MIN_SCORE", "VENDOR_ALIASES", "apply_template_to_device", "level_for", "suggest_for_device", "suggest_models", "vendor_key"]
