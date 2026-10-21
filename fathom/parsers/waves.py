"""Waves SuperRack / SuperRack Performer / MultiRack / eMotion LV1 data.

Waves does not publish a routing export. SuperRack sessions are ``.sprk``
files (undocumented; the recovery files next to them are SQLite databases),
rack presets are ``.xps`` XML, MultiRack sessions are XML-ish. This parser
therefore *sniffs* the file:

* **SQLite** (``SQLite format 3`` header): tables whose names mention rack /
  channel / strip / plugin are walked for rack names, I/O and plugin lists.
* **XML** (``.sprk`` / ``.xps`` / ``.mrsession`` / anything starting with
  ``<``): elements whose tag or ``type`` mentions ``rack`` become racks; their
  attributes / children named like ``input`` / ``output`` give the I/O and
  descendants whose tag mentions ``plugin`` / ``processor`` / ``insert`` give
  the plugin chain.
* **JSON**: same idea on dict keys.
* **CSV** (the documented fallback you can type in two minutes)::

      rack,input,output,plugins,notes
      Kick,DVS 1,DVS 1,"C6 > F6 > SSL E-Channel",
      Vox 1,DVS 9,DVS 9,"Scheps Omni Channel > CLA-2A",lead

The result is a list of racks (name, input, output, plugin chain) plus the
host application when it can be told from the file. Anything the sniffers
cannot read is reported in ``notes`` rather than guessed.
"""

from __future__ import annotations

import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .common import ParseResult, cell, column_index, find_header, read_rows, read_text

SQLITE_MAGIC = b"SQLite format 3\x00"

_RACK_WORDS = ("rack", "channelstrip", "strip", "chain", "slot")
_PLUGIN_WORDS = ("plugin", "plug_in", "plug-in", "processor", "insert", "effect")
_INPUT_KEYS = ("input", "inputs", "in", "src", "source", "inputchannel", "input_channel", "inputname", "input_name")
_OUTPUT_KEYS = ("output", "outputs", "out", "dst", "dest", "destination", "outputchannel", "output_channel", "outputname", "output_name")
_NAME_KEYS = ("name", "title", "label", "rackname", "rack_name", "displayname", "display_name")
_PLUGIN_NAME_KEYS = ("pluginname", "plugin_name", "name", "title", "label", "plugin", "product", "productname", "displayname")
_SKIP_PLUGIN_NAMES = {"", "none", "empty", "null", "(empty)", "-"}


@dataclass
class Rack:
    index: int
    name: str
    input: str = ""
    output: str = ""
    plugins: List[str] = field(default_factory=list)
    notes: str = ""

    def chain(self) -> str:
        return " › ".join(self.plugins)


class WavesSession(ParseResult):
    kind = "waves"

    def __init__(self) -> None:
        super().__init__()
        self.app = ""  # SuperRack | SuperRack Performer | MultiRack | eMotion LV1 | ""
        self.session_name = ""
        self.racks: List[Rack] = []
        self.io_devices: List[str] = []

    def add_rack(self, name: str, input: str = "", output: str = "", plugins: Optional[Iterable[str]] = None, notes: str = "") -> Rack:
        plugs = [p.strip() for p in (plugins or []) if p and p.strip().lower() not in _SKIP_PLUGIN_NAMES]
        rack = Rack(index=len(self.racks) + 1, name=name.strip() or f"Rack {len(self.racks) + 1}", input=input.strip(), output=output.strip(), plugins=plugs, notes=notes.strip())
        self.racks.append(rack)
        return rack

    def plugin_names(self) -> List[str]:
        seen: List[str] = []
        for r in self.racks:
            for p in r.plugins:
                if p not in seen:
                    seen.append(p)
        return seen

    def io_channels(self) -> List[str]:
        chans: List[str] = []
        for r in self.racks:
            for v in (r.input, r.output):
                if v and v not in chans:
                    chans.append(v)
        return chans

    def summary(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "app": self.app,
            "session": self.session_name,
            "racks": len(self.racks),
            "plugins": len(self.plugin_names()),
            "plugin_list": self.plugin_names()[:40],
            "io_devices": list(self.io_devices),
            "notes": list(self.notes),
        }


# ------------------------------------------------------------- detection


def detect_app(text: str, path: Path) -> str:
    low = text.lower()
    if "superrack performer" in low or "performer" in low and "superrack" in low:
        return "SuperRack Performer"
    if "superrack" in low or path.suffix.lower() == ".sprk":
        return "SuperRack"
    if "multirack" in low or path.suffix.lower() in (".mrsession", ".mrs", ".mrk"):
        return "MultiRack"
    if "emotion" in low or "lv1" in low or path.suffix.lower() == ".emo":
        return "eMotion LV1"
    return ""


def _lower(s: Any) -> str:
    return str(s or "").strip().lower()


def _has_word(text: str, words: Sequence[str]) -> bool:
    t = _lower(text).replace("-", "").replace("_", "")
    return any(w.replace("-", "").replace("_", "") in t for w in words)


# -------------------------------------------------------------------- CSV


def parse_csv(path: Path) -> WavesSession:
    sess = WavesSession()
    sess.source_files.append(str(path))
    rows = read_rows(path)
    if not rows:
        sess.note(f"{path.name}: empty")
        return sess
    hidx = find_header(rows, ("rack", "name", "input", "output", "plugins", "plugin", "chain"))
    header = rows[hidx] if hidx is not None else []
    data = rows[(hidx + 1) if hidx is not None else 0 :]
    name_i = column_index(header, "rack", "rack name", "name", "channel", "strip") if header else 0
    in_i = column_index(header, "input", "in", "source", "rx") if header else 1
    out_i = column_index(header, "output", "out", "destination", "tx") if header else 2
    plug_i = column_index(header, "plugins", "plugin", "chain", "inserts", "processing") if header else 3
    notes_i = column_index(header, "notes", "note", "comment") if header else None
    app_i = column_index(header, "app", "host", "application") if header else None
    for r in data:
        name = cell(r, name_i)
        if not name:
            continue
        plugs = re.split(r"\s*(?:>|›|→|\||;|,)\s*", cell(r, plug_i)) if cell(r, plug_i) else []
        sess.add_rack(name, cell(r, in_i), cell(r, out_i), plugs, cell(r, notes_i))
        if app_i is not None and cell(r, app_i) and not sess.app:
            sess.app = cell(r, app_i)
    sess.app = sess.app or detect_app(read_text(path), path)
    if not sess.racks:
        sess.note(f"{path.name}: no rack rows (expected columns rack, input, output, plugins)")
    return sess


# -------------------------------------------------------------------- XML


def _attr_or_child(el: ET.Element, keys: Sequence[str]) -> str:
    want = {k.lower() for k in keys}
    for k, v in el.attrib.items():
        if k.lower() in want and (v or "").strip():
            return v.strip()
    for ch in list(el):
        tag = ch.tag.rsplit("}", 1)[-1].lower()
        if tag in want and (ch.text or "").strip():
            return ch.text.strip()
        if tag in want:
            inner = _attr_or_child(ch, ("value", "name", "text"))
            if inner:
                return inner
    return ""


_NOT_RACK = ("session", "preset", "list", "collection", "group", "inventory", "snapshot", "template")


def _is_rack_el(el: ET.Element) -> bool:
    tag = el.tag.rsplit("}", 1)[-1].lower().replace("-", "").replace("_", "")
    if any(x in tag for x in _NOT_RACK) or tag.endswith("s"):
        return False
    if tag in ("rack", "channel", "channelstrip", "strip", "chain", "slot", "rackitem"):
        return True
    if tag.endswith("rack") or tag.startswith("rack"):
        return True
    for k, v in el.attrib.items():
        if k.lower() in ("type", "kind", "class") and _has_word(v, ("rack",)):
            return True
    return False


def _is_plugin_el(el: ET.Element) -> bool:
    tag = el.tag.rsplit("}", 1)[-1]
    if _has_word(tag, _PLUGIN_WORDS) and not tag.lower().endswith("s"):
        return True
    for k, v in el.attrib.items():
        if k.lower() in ("type", "kind", "class") and _has_word(v, _PLUGIN_WORDS):
            return True
    return False


def parse_xml(path: Path) -> WavesSession:
    sess = WavesSession()
    sess.source_files.append(str(path))
    text = read_text(path)
    sess.app = detect_app(text, path)
    try:
        root = ET.fromstring(text.encode("utf-8") if text.lstrip().startswith("<?xml") else text)
    except ET.ParseError as exc:
        sess.note(f"{path.name}: XML parse error: {exc}")
        return sess
    sess.session_name = _attr_or_child(root, ("sessionname", "session_name", "name", "title"))
    racks = [el for el in root.iter() if _is_rack_el(el)]
    # drop racks nested inside other racks (sub-elements that also say "rack")
    nested = set()
    for r in racks:
        for sub in r.iter():
            if sub is not r and sub in racks:
                nested.add(sub)
    racks = [r for r in racks if r not in nested]
    for el in racks:
        name = _attr_or_child(el, _NAME_KEYS)
        inp = _attr_or_child(el, _INPUT_KEYS)
        out = _attr_or_child(el, _OUTPUT_KEYS)
        plugs: List[str] = []
        for sub in el.iter():
            if sub is el or not _is_plugin_el(sub):
                continue
            pname = _attr_or_child(sub, _PLUGIN_NAME_KEYS)
            if pname:
                plugs.append(pname)
        if not (name or inp or out or plugs):
            continue
        sess.add_rack(name or f"Rack {len(sess.racks) + 1}", inp, out, plugs)
    if not sess.racks:
        # .xps preset or unknown layout: at least harvest plugin names
        names = []
        for el in root.iter():
            if _is_plugin_el(el):
                n = _attr_or_child(el, _PLUGIN_NAME_KEYS)
                if n and n not in names:
                    names.append(n)
        for k, v in root.attrib.items():
            if k.lower() in ("pluginname", "plugin") and v and v not in names:
                names.append(v)
        if names:
            sess.add_rack(sess.session_name or path.stem, plugins=names, notes="plugins only (no rack I/O in file)")
            sess.note(f"{path.name}: no rack structure found; listed {len(names)} plugin name(s)")
        else:
            sess.note(f"{path.name}: no rack / plugin elements recognised")
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower()
        if tag in ("iodevice", "io_device", "device", "soundgriddevice", "interface"):
            n = _attr_or_child(el, ("name", "model", "devicename", "device_name"))
            if n and n not in sess.io_devices:
                sess.io_devices.append(n)
    return sess


# ------------------------------------------------------------------- JSON


def _walk_json(obj: Any, sess: WavesSession, parent_key: str = "") -> None:
    if isinstance(obj, dict):
        keys_l = {k.lower(): k for k in obj}
        looks_rack = _has_word(parent_key, _RACK_WORDS) or any(_has_word(k, ("plugins", "inserts", "chain")) for k in keys_l)
        if looks_rack and any(k in keys_l for k in _NAME_KEYS + _INPUT_KEYS + _OUTPUT_KEYS):
            name = next((str(obj[keys_l[k]]) for k in _NAME_KEYS if k in keys_l and obj[keys_l[k]]), "")
            inp = next((str(obj[keys_l[k]]) for k in _INPUT_KEYS if k in keys_l and isinstance(obj[keys_l[k]], (str, int))), "")
            out = next((str(obj[keys_l[k]]) for k in _OUTPUT_KEYS if k in keys_l and isinstance(obj[keys_l[k]], (str, int))), "")
            plugs: List[str] = []
            for k in keys_l:
                if _has_word(k, ("plugins", "inserts", "chain", "processors")):
                    val = obj[keys_l[k]]
                    if isinstance(val, list):
                        for item in val:
                            if isinstance(item, str):
                                plugs.append(item)
                            elif isinstance(item, dict):
                                il = {ik.lower(): ik for ik in item}
                                pn = next((str(item[il[pk]]) for pk in _PLUGIN_NAME_KEYS if pk in il and item[il[pk]]), "")
                                if pn:
                                    plugs.append(pn)
            sess.add_rack(name or f"Rack {len(sess.racks) + 1}", inp, out, plugs)
            return
        for k, v in obj.items():
            _walk_json(v, sess, k)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json(item, sess, parent_key)


def parse_json(path: Path) -> WavesSession:
    sess = WavesSession()
    sess.source_files.append(str(path))
    text = read_text(path)
    sess.app = detect_app(text, path)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        sess.note(f"{path.name}: JSON parse error: {exc}")
        return sess
    if isinstance(obj, dict):
        for k in ("sessionName", "session_name", "name", "title"):
            if isinstance(obj.get(k), str):
                sess.session_name = obj[k]
                break
    _walk_json(obj, sess)
    if not sess.racks:
        sess.note(f"{path.name}: no rack-like objects found")
    return sess


# ----------------------------------------------------------------- SQLite


def parse_sqlite(path: Path) -> WavesSession:
    sess = WavesSession()
    sess.source_files.append(str(path))
    sess.app = detect_app("", path)
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        sess.note(f"{path.name}: cannot open SQLite file: {exc}")
        return sess
    try:
        cur = con.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        rack_tables = [t for t in tables if _has_word(t, _RACK_WORDS)]
        plugin_tables = [t for t in tables if _has_word(t, _PLUGIN_WORDS)]
        racks_by_id: Dict[Any, Rack] = {}
        for t in rack_tables:
            cols = [c[1] for c in cur.execute(f'PRAGMA table_info("{t}")')]
            lc = [c.lower() for c in cols]
            name_c = next((cols[i] for i, c in enumerate(lc) if c in _NAME_KEYS), None)
            in_c = next((cols[i] for i, c in enumerate(lc) if c in _INPUT_KEYS), None)
            out_c = next((cols[i] for i, c in enumerate(lc) if c in _OUTPUT_KEYS), None)
            id_c = next((cols[i] for i, c in enumerate(lc) if c in ("id", "rackid", "rack_id", "index", "idx")), None)
            if not (name_c or in_c or out_c):
                continue
            for row in cur.execute(f'SELECT * FROM "{t}"'):
                rec = dict(zip(cols, row))
                rack = sess.add_rack(str(rec.get(name_c, "") or ""), str(rec.get(in_c, "") or "") if in_c else "", str(rec.get(out_c, "") or "") if out_c else "")
                if id_c is not None:
                    racks_by_id[rec.get(id_c)] = rack
        for t in plugin_tables:
            cols = [c[1] for c in cur.execute(f'PRAGMA table_info("{t}")')]
            lc = [c.lower() for c in cols]
            name_c = next((cols[i] for i, c in enumerate(lc) if c in _PLUGIN_NAME_KEYS), None)
            rack_c = next((cols[i] for i, c in enumerate(lc) if c in ("rackid", "rack_id", "rack", "parent", "parentid", "parent_id", "channel", "channelid")), None)
            order_c = next((cols[i] for i, c in enumerate(lc) if c in ("slot", "position", "order", "idx", "index")), None)
            if not name_c:
                continue
            order_sql = f' ORDER BY "{order_c}"' if order_c else ""
            for row in cur.execute(f'SELECT * FROM "{t}"{order_sql}'):
                rec = dict(zip(cols, row))
                pname = str(rec.get(name_c) or "").strip()
                if not pname or pname.lower() in _SKIP_PLUGIN_NAMES:
                    continue
                rack = racks_by_id.get(rec.get(rack_c)) if rack_c else None
                if rack is None and sess.racks:
                    rack = sess.racks[-1]
                if rack is None:
                    rack = sess.add_rack("Session plugins")
                rack.plugins.append(pname)
        if not sess.racks:
            sess.note(f"{path.name}: SQLite file but no rack / plugin tables recognised (tables: {', '.join(tables[:12])})")
    except sqlite3.Error as exc:
        sess.note(f"{path.name}: SQLite read error: {exc}")
    finally:
        con.close()
    return sess


# -------------------------------------------------------------- dispatch


def parse_waves(path: Path) -> WavesSession:
    if path.is_dir():
        merged = WavesSession()
        for f in sorted(path.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                part = parse_waves(f)
                merged.notes.extend(part.notes)
                merged.source_files.extend(part.source_files)
                merged.app = merged.app or part.app
                merged.session_name = merged.session_name or part.session_name
                for r in part.racks:
                    merged.add_rack(r.name, r.input, r.output, r.plugins, r.notes)
                for d in part.io_devices:
                    if d not in merged.io_devices:
                        merged.io_devices.append(d)
        return merged
    head = path.read_bytes()[:64]
    if head.startswith(SQLITE_MAGIC):
        return parse_sqlite(path)
    text_head = head.decode("utf-8", errors="ignore").lstrip().lstrip("\ufeff")
    suffix = path.suffix.lower()
    if text_head.startswith("<") or suffix in (".xml", ".xps", ".sprk", ".mrsession", ".mrs", ".emo"):
        if text_head.startswith("<"):
            return parse_xml(path)
        if text_head.startswith(("{", "[")):
            return parse_json(path)
        sess = WavesSession()
        sess.source_files.append(str(path))
        sess.app = detect_app("", path)
        sess.note(f"{path.name}: binary {suffix} session; this format is not documented by Waves. Export racks to CSV (rack,input,output,plugins) instead.")
        return sess
    if text_head.startswith(("{", "[")) or suffix == ".json":
        return parse_json(path)
    return parse_csv(path)
