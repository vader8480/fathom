"""The "Discovered connections" section of the generated report.

Mirrors the cable-schedule columns and adds confidence, the sources that
saw each link and the run it came from. Two things feed it, both read from
disk (nothing here probes anything):

* cables in the document that were promoted from a discovery run (they carry
  ``source: "discovery"`` and a ``discovery`` block with run / confidence /
  methods), taken from the cable schedule so state and room scoping behave
  exactly like the Cable schedule section;
* the latest *completed* run's connections that are not (yet) such a cable:
  what was seen on the wire and is still only a proposal, plus links that
  are already documented by a hand-drawn cable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

Doc = Dict[str, Any]

REPORT_COLUMNS: List[Tuple[str, str]] = [
    ("tag", "Tag"), ("from_room", "From room"), ("from_device", "From device"), ("from_port", "From port"),
    ("to_room", "To room"), ("to_device", "To device"), ("to_port", "To port"), ("medium", "Medium"), ("type", "Type"),
    ("signal", "Signal"), ("status", "Status"), ("confidence", "Confidence"), ("sources", "Sources"), ("run", "Run"), ("note", "Note"), ("id", "Id"),
]
#: connection flags listed in the report (``via`` rows are derived from other rows and stay out)
REPORT_FLAGS = ("", "uplink", "unmanaged", "host")
FLAG_NOTES = {"uplink": "switch-to-switch uplink", "unmanaged": "several hosts behind this port (unmanaged switch?)", "host": "seen from the Fathom host itself"}


def confidence_text(value: Any, level: str = "") -> str:
    """``high (92%)`` for the HTML / CSV cells."""
    try:
        pct = int(round(float(value) * 100))
    except (TypeError, ValueError):
        return level or ""
    return f"{level} ({pct}%)" if level else f"{pct}%"


def discovery_cables(doc: Doc) -> Dict[str, Dict[str, Any]]:
    """Cable id -> cable for the document cables that came out of a discovery promote."""
    return {str(c.get("id")): c for c in doc.get("cables") or [] if isinstance(c, dict) and c.get("source") == "discovery"}


def _rooms_of_run_row(row: Dict[str, Any], conn: Dict[str, Any], doc_rooms: Dict[str, str], proposed_rooms: Dict[str, str]) -> List[str]:
    out = []
    for side in ("switch", "peer"):
        did = str((conn.get(side) or {}).get("device") or "")
        rid = doc_rooms.get(did) or proposed_rooms.get(did) or ""
        if rid:
            out.append(rid)
    return out


def discovered_connections(doc: Doc, pdir: Optional[Path], *, state: str = "all", rooms: Optional[Iterable[str]] = None, run_id: str = "") -> Dict[str, Any]:
    """``{"columns", "rows", "run", "totals", "notes"}`` for the report section (``rows`` empty when there is nothing to show).

    ``rooms``: restrict to connections with at least one end in these rooms (``None`` = all). ``state`` applies to the
    promoted cables exactly as it does to the cable schedule; observed-but-unpromoted links are listed for every state
    because they are observations, not plans.
    """
    from .. import cables as cab_mod

    notes: List[str] = []
    room_set = set(rooms) if rooms is not None else None
    rows: List[Dict[str, Any]] = []
    cabs = discovery_cables(doc)
    covered: set = set()
    if cabs:
        sched = cab_mod.cable_schedule(doc, state=state)
        for r in sched["rows"]:
            cab = cabs.get(str(r.get("id")))
            if cab is None:
                continue
            if room_set is not None and not ({r.get("from_room_id"), r.get("to_room_id")} & room_set):
                continue
            info = cab.get("discovery") if isinstance(cab.get("discovery"), dict) else {}
            rows.append(dict(
                {k: r.get(k, "") for k, _ in REPORT_COLUMNS if k in r}, status=r.get("status") or "planned",
                confidence=confidence_text(info.get("confidence"), str(info.get("level") or "")), sources=", ".join(info.get("methods") or []),
                run=str(info.get("run") or ""), note=r.get("note") or "", origin="cable",
            ))
            covered.add(frozenset([(r.get("from_device_id"), r.get("from_port_id")), (r.get("to_device_id"), r.get("to_port_id"))]))
            covered.add(frozenset([r.get("from_device_id"), r.get("to_device_id")]))
    run_brief: Optional[Dict[str, Any]] = None
    if pdir is not None:
        from . import RunNotFound, completed_runs, findings

        rid = run_id or next((str(r["id"]) for r in completed_runs(pdir)), "")
        if rid:
            try:
                f = findings(pdir, doc, rid)
            except RunNotFound:
                f, rid = None, ""
            if f is not None:
                run_brief = {"id": rid, "computed": f.get("computed"), "revision": f.get("revision"), "counts": f.get("counts") or {}}
                doc_rooms = {str(d.get("id")): str(d.get("room") or "") for d in doc.get("devices") or [] if isinstance(d, dict)}
                proposed_rooms = {str((e.get("proposed") or {}).get("id")): str((e.get("proposed") or {}).get("room") or "") for e in f.get("entities") or [] if e.get("proposed")}
                frows = {str(r.get("id")): r for r in f.get("rows") or []}
                for c in f.get("connections") or []:
                    if c.get("status") == "ignored" or c.get("flag", "") not in REPORT_FLAGS:
                        continue
                    r = frows.get(str(c.get("id")))
                    if r is None:
                        continue
                    cab = c.get("cable") or {}
                    fr, to = cab.get("from") or {}, cab.get("to") or {}
                    key = frozenset([(fr.get("device"), fr.get("port")), (to.get("device"), to.get("port"))])
                    if cab and (key in covered or (c.get("status") == "exists" and frozenset([fr.get("device"), to.get("device")]) in covered)):
                        continue  # the promoted cable above already lists this link
                    if room_set is not None and not (set(_rooms_of_run_row(r, c, doc_rooms, proposed_rooms)) & room_set):
                        continue
                    note = FLAG_NOTES.get(c.get("flag") or "", "")
                    if c.get("status") == "exists":
                        status, note = "documented", (note + "; " if note else "") + "matches a cable in the document"
                    elif c.get("cable"):
                        status = "proposed"
                    else:
                        status, note = "observed", (note + "; " if note else "") + "not promotable (one end is not a document device or confidence is low)"
                    rows.append({
                        "tag": "", "from_room": _room_name(doc, doc_rooms.get(str((c.get("switch") or {}).get("device") or "")) or proposed_rooms.get(str((c.get("switch") or {}).get("device") or ""), "")),
                        "from_device": r.get("from_device", ""), "from_port": r.get("from_port", ""),
                        "to_room": _room_name(doc, doc_rooms.get(str((c.get("peer") or {}).get("device") or "")) or proposed_rooms.get(str((c.get("peer") or {}).get("device") or ""), "")),
                        "to_device": r.get("to_device", ""), "to_port": r.get("to_port", ""), "medium": c.get("medium") or "network", "type": r.get("type") or "",
                        "signal": "", "status": status, "confidence": confidence_text(c.get("confidence"), str(c.get("level") or "")), "sources": ", ".join(c.get("methods") or []),
                        "run": rid, "note": note, "id": c.get("id", ""), "origin": "run",
                    })
        else:
            notes.append("discovered connections: no completed discovery run yet")
    rows.sort(key=lambda r: (0 if r.get("origin") == "cable" else 1, str(r.get("from_device") or ""), _port_sort(r.get("from_port")), str(r.get("to_device") or "")))
    totals = {"rows": len(rows), "promoted": sum(1 for r in rows if r.get("origin") == "cable"), "proposed": sum(1 for r in rows if r.get("status") == "proposed"),
              "documented": sum(1 for r in rows if r.get("status") == "documented"), "observed": sum(1 for r in rows if r.get("status") == "observed")}
    return {"kind": "discovered", "columns": [{"key": k, "label": lab} for k, lab in REPORT_COLUMNS], "rows": rows, "run": run_brief, "totals": totals, "notes": notes}


def _room_name(doc: Doc, rid: str) -> str:
    for r in doc.get("rooms") or []:
        if isinstance(r, dict) and r.get("id") == rid:
            return str(r.get("name") or rid)
    return rid or ""


def _port_sort(label: Any) -> Tuple[int, str]:
    from .topology import port_index

    n = port_index(str(label or ""))
    return (n if n is not None else 10 ** 6, str(label or ""))


def section_intro(sched: Dict[str, Any]) -> str:
    """The paragraph above the table: which run, when, and how to read the status column."""
    import html

    t = sched.get("totals") or {}
    run = sched.get("run") or {}
    if run.get("id"):
        head = f"From discovery run <code>{html.escape(str(run['id']))}</code>"
        if run.get("computed"):
            head += f" (findings computed {html.escape(str(run['computed']))})"
    else:
        head = "No completed discovery run; promoted cables only"
    counts = (f"{t.get('rows', 0)} rows: {t.get('promoted', 0)} promoted into the document, {t.get('proposed', 0)} proposed, "
              f"{t.get('documented', 0)} matching hand-drawn cables, {t.get('observed', 0)} observed only")
    return (f'<p class="mut">{head} · {html.escape(counts)}. Confidence is the correlation score of the link and Sources lists the probes that saw it '
            "(unifi, lldp, snmp, snmp_lldp, mdns, arp …); nothing in this section was written to a device.</p>")


__all__ = ["FLAG_NOTES", "REPORT_COLUMNS", "REPORT_FLAGS", "confidence_text", "discovered_connections", "discovery_cables", "section_intro"]
