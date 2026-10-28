"""Rack templates: ready-made church AV racks (a rack, planned placeholder devices and accessories).

A rack template is plain Python data: the rack fields (``units``, ``width_in``, ``form_factor``),
device placements that name a library template id (``fathom/presets.py`` or
``fathom/library/templates/*.json``) and RackItems (blanks, vents, shelves, drawers, cable
managers). :func:`apply_ops` turns one into change ops (§4.9) for ``POST …/racks/from-template``:
one ``put`` of the rack, carrying its ``items``, and one ``put`` per device, each made with
:func:`fathom.library.instantiate` and marked ``status: "planned"``.

Placement rules (``fathom/racks.py``): ``u`` is the lowest RU (1 = bottom); full depth blocks both
faces, half depth only its face; items are full width. Devices on a shelf carry ``rack.shelf`` +
``rack.slot`` and the shelf's ``u``/``face``; on a two-cell shelf their ``side`` is left/right by
slot so clients without shelf support draw them side by side instead of overlapping.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Set

Doc = Dict[str, Any]
Op = Dict[str, Any]

#: Defaults per RackItem type (contract B ``ITEM_TYPES``): height, face, depth, slots.
ITEM_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "blank": {"height": 1, "face": "front", "depth": "half"},
    "vent": {"height": 1, "face": "front", "depth": "half"},
    "shelf": {"height": 1, "face": "front", "depth": "full", "slots": 2},
    "drawer": {"height": 2, "face": "front", "depth": "full"},
    "cable_manager": {"height": 1, "face": "front", "depth": "half"},
    "brush": {"height": 1, "face": "front", "depth": "half"},
    "lacing_bar": {"height": 1, "face": "rear", "depth": "half"},
    "other": {"height": 1, "face": "front", "depth": "half"},
}


def _dev(template: str, name: str, u: int, height: int = 1, face: str = "front", side: str = "full",
         depth: str = "full") -> Dict[str, Any]:
    """A rack-level device placement; ``height`` is the library template's ``ru`` (1 when it has none)."""
    return {"template": template, "name": name, "u": u, "height": height, "face": face, "side": side, "depth": depth}


def _child(template: str, name: str, slot: int) -> Dict[str, Any]:
    return {"template": template, "name": name, "slot": slot}


def _item(type_: str, u: int, label: str = "", children: Optional[List[Dict[str, Any]]] = None, **fields: Any) -> Dict[str, Any]:
    it: Dict[str, Any] = {"item": type_, "u": u}
    if label:
        it["label"] = label
    it.update(fields)
    if children:
        it["children"] = children
    return it


#: The rack templates, in display order.
TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "church-audio-12u", "name": "Church audio rack · 12U", "units": 12, "width_in": 19, "form_factor": "cabinet",
        "description": "Sanctuary audio cabinet: power conditioner, digital stagebox, wireless mic receivers, "
                       "a two-cell shelf for small gear, blanks and a vent.",
        "layout": [
            _dev("generic-pdu", "Power conditioner", 1),
            _item("vent", 2),
            _dev("generic-stagebox", "Stagebox", 3, height=3),
            _item("blank", 6),
            _dev("generic-wireless-mic-rx", "Wireless RX 1", 7),
            _dev("generic-wireless-mic-rx", "Wireless RX 2", 8),
            _item("blank", 9),
            _item("shelf", 10, "Small gear", slots=2, children=[
                _child("shure-ulxd4d", "Wireless RX 3", 0),
                _child("generic-media-converter", "Fibre converter", 1),
            ]),
            _item("blank", 11),
            _item("blank", 12),
        ],
    },
    {
        "id": "road-case-8u", "name": "Wireless road case · 8U", "units": 8, "width_in": 19, "form_factor": "road_case",
        "description": "Portable wireless rig for youth, outreach and pop-up services: PDU, wireless receivers, "
                       "a blank and a drawer for batteries and spares.",
        "layout": [
            _dev("generic-pdu", "PDU", 1),
            _dev("generic-wireless-mic-rx", "Wireless RX 1", 2),
            _dev("generic-wireless-mic-rx", "Wireless RX 2", 3),
            _item("blank", 4),
            _item("drawer", 7, "Batteries & spares"),
        ],
    },
    {
        "id": "video-stream-16u", "name": "Video & streaming rack · 16U", "units": 16, "width_in": 19, "form_factor": "cabinet",
        "description": "Broadcast / livestream cabinet: UPS, streaming computer on a shelf, encoder, video router "
                       "and production switcher.",
        "layout": [
            _dev("generic-ups", "UPS", 1, height=2),
            _item("blank", 3),
            _item("shelf", 4, "Computer shelf", slots=2, children=[
                _child("generic-server", "Stream computer", 0),
            ]),
            _item("blank", 7),
            _dev("generic-encoder-decoder", "Encoder", 8, side="left"),
            _item("vent", 9),
            _dev("blackmagic-videohub-20x20-12g", "Video router", 10),
            _item("blank", 11),
            _dev("generic-video-switcher", "Video switcher", 12),
            _item("blank", 13),
        ],
    },
    {
        "id": "network-closet-24u", "name": "Network closet · 24U", "units": 24, "width_in": 19, "form_factor": "four_post",
        "description": "Four-post network rack: copper and fibre patch panels with cable managers, a 48-port switch, "
                       "router / firewall, UPS and a rear PDU.",
        "layout": [
            _dev("generic-ups", "UPS", 1, height=2),
            _item("blank", 3),
            _dev("generic-pdu", "PDU", 3, face="rear", depth="half"),
            _item("blank", 4),
            _dev("generic-router", "Router / firewall", 16),
            _item("blank", 17),
            _dev("generic-patch-panel-fibre", "Fibre patch panel", 18, depth="half"),
            _item("cable_manager", 19),
            _dev("generic-patch-panel-copper", "Patch panel B", 20, depth="half"),
            _item("cable_manager", 21),
            _dev("generic-switch-48", "Core switch", 22),
            _item("cable_manager", 23),
            _dev("generic-patch-panel-copper", "Patch panel A", 24, depth="half"),
        ],
    },
    {
        "id": "desk-10in-6u", "name": "Desk rack · 10in 6U", "units": 6, "width_in": 10, "form_factor": "open_frame",
        "description": "10-inch desktop rack for a small stream or chapel desk: PDU, network switch and a shelf "
                       "holding a compact switcher and stream encoder.",
        "layout": [
            _dev("generic-pdu", "PDU", 1),
            _dev("generic-switch-24", "Network switch", 2),
            _item("blank", 3),
            _item("shelf", 4, "Desk shelf", slots=2, children=[
                _child("blackmagic-atem-mini-pro", "ATEM Mini", 0),
                _child("blackmagic-web-presenter-hd", "Stream encoder", 1),
            ]),
        ],
    },
]

_BY_ID: Dict[str, Dict[str, Any]] = {t["id"]: t for t in TEMPLATES}


def list_templates() -> List[Dict[str, Any]]:
    """Summaries for ``GET /api/v2/rack-templates``: ``[{id, name, description, units, width_in, form_factor}]``."""
    return [{k: t[k] for k in ("id", "name", "description", "units", "width_in", "form_factor")} for t in TEMPLATES]


def get_rack_template(template_id: str) -> Optional[Dict[str, Any]]:
    """A deep copy of one rack template definition, or None."""
    t = _BY_ID.get(template_id or "")
    return copy.deepcopy(t) if t else None


def template_ids(template_id: str) -> List[str]:
    """Library template ids used by a rack template (rack level and shelf children), in layout order."""
    out: List[str] = []
    for e in _BY_ID[template_id]["layout"]:
        if "template" in e:
            out.append(e["template"])
        for c in e.get("children") or []:
            out.append(c["template"])
    return out


def _unique(base: str, taken: Set[str]) -> str:
    """``base``, else ``base-2``, ``base-3``, … (the ``model-core.slug`` dedupe); adds the result to ``taken``."""
    eid, n = base, 2
    while eid in taken:
        eid = f"{base}-{n}"
        n += 1
    taken.add(eid)
    return eid


def _ids(doc: Doc, coll: str) -> Set[str]:
    return {str(e["id"]) for e in doc.get(coll) or [] if isinstance(e, dict) and e.get("id")}


def apply_ops(doc: Doc, template_id: str, *, name: str = "", room: str = "", location: str = "") -> Dict[str, Any]:
    """Ops that create a rack from a template: ``{"ops": [put rack, put device…], "rack_id": id}``.

    The rack id is ``rk-<slug of name>`` deduped against ``doc.racks``; ``name`` defaults to the template
    name. Devices get ``status: "planned"``, ``room``/``location`` when given, and ids from their name slug
    deduped against ``doc.devices`` and each other. Raises KeyError for an unknown template.
    """
    from . import library
    from .model import slug

    t = _BY_ID.get(template_id or "")
    if t is None:
        raise KeyError(template_id)
    rack_name = (name or "").strip() or t["name"]
    rack_id = _unique("rk-" + slug(rack_name), _ids(doc, "racks"))
    taken = _ids(doc, "devices")
    rack: Dict[str, Any] = {"id": rack_id, "name": rack_name}
    if room:
        rack["room"] = room
    if location:
        rack["location"] = location
    rack.update({"units": t["units"], "width_in": t["width_in"], "form_factor": t["form_factor"]})
    items: List[Dict[str, Any]] = []
    devices: List[Dict[str, Any]] = []

    def device(e: Dict[str, Any], placement: Dict[str, Any]) -> None:
        lt = library.get_template(e["template"])
        if lt is None:
            raise RuntimeError(f"rack template {template_id}: library template {e['template']!r} is missing")
        dev = library.instantiate(lt, device_id=_unique(slug(e["name"]), taken), name=e["name"], room=room)
        if location:
            dev["location"] = location
        dev["status"] = "planned"
        dev["rack"] = placement
        devices.append(dev)

    for e in t["layout"]:
        if "template" in e:
            device(e, {"id": rack_id, "u": e["u"], "height": e["height"], "face": e["face"], "side": e["side"], "depth": e["depth"]})
            continue
        spec = dict(ITEM_DEFAULTS[e["item"]])
        spec.update({k: v for k, v in e.items() if k in ("height", "face", "depth", "slots")})
        item: Dict[str, Any] = {"id": f"ri-{len(items) + 1}", "type": e["item"], "u": e["u"],
                                "height": spec["height"], "face": spec["face"], "depth": spec["depth"]}
        if e.get("label"):
            item["label"] = e["label"]
        if e["item"] == "shelf":
            item["slots"] = spec["slots"]
        items.append(item)
        for c in e.get("children") or []:
            side = ("left", "right")[c["slot"]] if item.get("slots") == 2 else "full"
            device(c, {"id": rack_id, "u": item["u"], "height": 1, "face": item["face"], "side": side,
                       "depth": "full", "shelf": item["id"], "slot": c["slot"]})
    rack["items"] = items
    ops: List[Op] = [{"op": "put", "coll": "racks", "id": rack_id, "value": rack}]
    ops += [{"op": "put", "coll": "devices", "id": d["id"], "value": d} for d in devices]
    return {"ops": ops, "rack_id": rack_id}


__all__ = ["ITEM_DEFAULTS", "TEMPLATES", "list_templates", "get_rack_template", "template_ids", "apply_ops"]
