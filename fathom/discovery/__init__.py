"""Network discovery (ad hoc runs: passive probes, plus opt-in read-only active ones).

A *run* is started by a person from the Discovery view (or the API) and
nothing else: there is no scheduler, no always-on listener and no periodic
polling anywhere in this package. For the run window the enabled passive
probes read a controller that already has the data (UniFi), listen to what
devices already announce (mDNS / Dante, LLDP / CDP) and read the host's ARP
table. Nothing passive sends a unicast packet to an AV device.

Active probes (Phase 2: SNMP on managed switches, Yamaha SCP, Blackmagic
Videohub, Q-SYS QRC) are off until a person enables them per project. They
contact only the hosts listed in their settings, one at a time, with
documented read-only queries, a pause between requests and a timeout per
request; a run that includes one is marked ``mode: "active"``. Nothing
writes to any device in either mode.

Runs are persisted under ``<project>/exports/discovery/<run-id>/``::

    run.json          status, progress, log tail, per-probe summaries
    raw/<probe>.json  what the probe collected (replayable as a fixture)
    findings.json     entities / connections / networks at the time the run finished

The findings served by the API are recomputed against the *live* document,
so a device promoted after the run shows up as "matches existing" on the next
read and a re-run never proposes it again. One ``imports`` entry of kind
``discovery`` per project points at the latest completed run; the
``discovery`` importer registered here contributes the high-confidence
findings to the imports overlay (auto devices, interfaces with switch and
port, ``network`` routes) exactly like a console or Dante export would.

Decisions (ignored entities / connections) live in
``exports/discovery/decisions.json`` and apply to every run.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .. import jobs
from . import settings as dsettings
from .correlate import Entity, correlate
from .probes import ACTIVE, ProbeResult, all_probes, host_list, probe_by_id
from .topology import Connection, build_connections, build_networks, canonical_port, connection_rows, doc_port_for, entity_interfaces, propose_device

Doc = Dict[str, Any]

RUNS_SUBDIR = Path("exports") / "discovery"
RUN_ID_RE = re.compile(r"^run-\d{8}-\d{6}-[0-9a-f]{4}$")
LOCK_NAME = ".lock"
CANCEL_NAME = "cancel"
DECISIONS_NAME = "decisions.json"
IMPORT_KIND = "discovery"
MAX_RUNS_KEPT = 20
EXTRA_TIME = 90.0  # beyond the listen window: controller fetch, DNS, correlation
OVERLAY_MIN_CONFIDENCE = 0.5
MODE = "passive"  # what a run is unless an active probe is enabled for it
LISTEN_PROBES = ("mdns", "lldp")  # probes that take the run window; everything else is read once


class RunBusy(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"a discovery run is already active ({run_id})")
        self.run_id = run_id


class RunNotFound(Exception):
    pass


# ------------------------------------------------------------------ paths & small io


def runs_root(pdir: Path) -> Path:
    return Path(pdir) / RUNS_SUBDIR


def run_dir(pdir: Path, run_id: str) -> Path:
    if not RUN_ID_RE.match(run_id or ""):
        raise RunNotFound(run_id)
    return runs_root(pdir) / run_id


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_decisions(pdir: Path) -> Dict[str, Any]:
    d = _read_json(runs_root(pdir) / DECISIONS_NAME, {}) or {}
    return {"entities": list(d.get("entities") or []), "connections": list(d.get("connections") or []), "networks": list(d.get("networks") or [])}


def write_decisions(pdir: Path, data: Dict[str, Any]) -> None:
    _write_json(runs_root(pdir) / DECISIONS_NAME, {k: sorted(set(v)) for k, v in data.items()})


# ------------------------------------------------------------------ availability


def extra_installed() -> Dict[str, Any]:
    """Which optional pieces of ``fathom-audio[discovery]`` are present."""
    from .probes import lldp, mdns, snmp

    zc_ok, zc_ver = mdns.available()
    raw_ok, raw_msg = lldp.capability()
    snmp_ok, snmp_ver = snmp.available()
    return {"zeroconf": zc_ok, "zeroconf_version": zc_ver, "net_raw": raw_ok, "net_raw_message": raw_msg, "puresnmp": snmp_ok, "puresnmp_version": snmp_ver,
            "fixtures": bool(os.environ.get("FATHOM_DISCOVERY_FIXTURES")), "install_hint": "pip install 'fathom-audio[discovery]'" if not (zc_ok and snmp_ok) else ""}


def run_mode(wanted: Iterable[str]) -> str:
    """``active`` when any of the probe ids is an active probe, else ``passive``."""
    for pid in wanted:
        m = probe_by_id(pid)
        if m is not None and m.INFO.mode == ACTIVE:
            return ACTIVE
    return MODE


def active_targets(cfg: Dict[str, Any], wanted: Iterable[str]) -> Dict[str, List[str]]:
    """Probe id -> hosts an enabled active probe is allowed to contact (from its ``targets`` field)."""
    out: Dict[str, List[str]] = {}
    for pid in wanted:
        m = probe_by_id(pid)
        if m is None or m.INFO.mode != ACTIVE:
            continue
        key = m.INFO.targets
        out[pid] = host_list((cfg.get("probes", {}).get(pid) or {}).get(key)) if key else []
    return out


def sources(doc: Doc, pdir: Optional[Path]) -> List[Dict[str, Any]]:
    """Probe descriptors for the Sources panel (mode, maturity, settings fields, availability)."""
    pub = dsettings.public(doc, pdir)
    caps = extra_installed()
    out = []
    for m in all_probes():
        info = m.INFO.to_dict()
        avail, why = True, ""
        if "zeroconf" in m.INFO.needs and not caps["zeroconf"]:
            avail, why = False, "zeroconf is not installed: " + caps["install_hint"]
        if "net_raw" in m.INFO.needs and not caps["net_raw"]:
            avail, why = False, caps["net_raw_message"]
        if "puresnmp" in m.INFO.needs and not caps["puresnmp"]:
            avail, why = False, "puresnmp is not installed: " + (caps["install_hint"] or "pip install 'fathom-audio[discovery]'")
        if caps["fixtures"]:
            avail, why = True, "fixture replay"
        info.update({"available": avail, "unavailable_reason": why, "settings": pub["probes"].get(m.INFO.id, {})})
        out.append(info)
    return out


# ------------------------------------------------------------------ runs


class _Run:
    """run.json on disk plus the live job (when this process owns it)."""

    def __init__(self, pdir: Path, run_id: str) -> None:
        self.pdir = Path(pdir)
        self.id = run_id
        self.dir = run_dir(pdir, run_id)
        self.data: Dict[str, Any] = _read_json(self.dir / "run.json", {}) or {}
        self._lock = threading.Lock()

    def save(self) -> None:
        with self._lock:
            _write_json(self.dir / "run.json", self.data)

    def update_from_job(self, job: jobs.Job) -> None:
        with self._lock:
            d = job.to_dict(log_lines=jobs.MAX_LOG)
            self.data.update({
                "status": d["status"], "progress": d["progress"], "stage": d["stage"], "started": d["started"] or self.data.get("started"),
                "finished": d["finished"], "elapsed": d["elapsed"], "remaining": d["remaining"], "error": dsettings.redact(d["error"], self.pdir),
                "log": [dict(x, msg=dsettings.redact(x["msg"], self.pdir)) for x in d["log"]], "active": d["active"],
            })
        self.save()


def _lock_path(pdir: Path) -> Path:
    return runs_root(pdir) / LOCK_NAME


def active_run_id(pdir: Path) -> str:
    """Id of the run currently holding the project's discovery lock, or ``""`` (stale locks are cleared)."""
    lp = _lock_path(pdir)
    if not lp.is_file():
        return ""
    info = _read_json(lp, {}) or {}
    rid = str(info.get("run") or "")
    job = jobs.RUNNER.active(_job_key(pdir))
    if job is not None and job.id == rid:
        return rid
    # another process may own it: trust run.json while it is fresh
    try:
        rd = run_dir(pdir, rid)
    except RunNotFound:
        lp.unlink(missing_ok=True)
        return ""
    data = _read_json(rd / "run.json", {}) or {}
    if data.get("status") in jobs.FINAL:
        lp.unlink(missing_ok=True)
        return ""
    deadline = float(info.get("deadline") or 0)
    if deadline and time.time() > deadline + 30:
        data.update({"status": "timeout", "active": False, "error": "lock expired (server restarted during the run?)", "finished": time.time()})
        _write_json(rd / "run.json", data)
        lp.unlink(missing_ok=True)
        return ""
    return rid


def _job_key(pdir: Path) -> str:
    return "discovery:" + str(Path(pdir).resolve())


def list_runs(pdir: Path, limit: int = MAX_RUNS_KEPT) -> List[Dict[str, Any]]:
    root = runs_root(pdir)
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.iterdir(), reverse=True):
        if p.is_dir() and RUN_ID_RE.match(p.name):
            data = _read_json(p / "run.json", None)
            if isinstance(data, dict):
                out.append(_brief(data))
        if len(out) >= limit:
            break
    return out


def _brief(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: data.get(k) for k in ("id", "status", "active", "started", "finished", "elapsed", "window", "probes", "by", "counts", "error", "progress", "stage", "mode", "diff")}


def get_run(pdir: Path, run_id: str) -> Dict[str, Any]:
    rd = run_dir(pdir, run_id)
    data = _read_json(rd / "run.json", None)
    if not isinstance(data, dict):
        raise RunNotFound(run_id)
    job = jobs.RUNNER.get(run_id)
    if job is not None and job.status in jobs.ACTIVE:
        live = job.to_dict()
        data.update({"status": live["status"], "progress": live["progress"], "stage": live["stage"], "elapsed": live["elapsed"], "remaining": live["remaining"],
                     "log": [dict(x, msg=dsettings.redact(x["msg"], pdir)) for x in live["log"]], "active": True})
    data["active"] = data.get("status") in jobs.ACTIVE
    data["findings_ready"] = (rd / "findings.json").is_file() or (rd / "raw").is_dir()
    return data


def start_run(pdir: Path, doc: Doc, by: str = "", window: Optional[int] = None, probes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Start a run for the project. Raises :class:`RunBusy` when one is active."""
    pdir = Path(pdir)
    cfg = dsettings.effective(doc, pdir)
    win = dsettings._clamp_window(window if window is not None else cfg["window"])
    wanted = [m.INFO.id for m in all_probes() if (cfg["probes"].get(m.INFO.id) or {}).get("enabled", True)]
    if probes:
        wanted = [p for p in wanted if p in probes]
    if not wanted:
        raise ValueError("no probes enabled")
    targets = active_targets(cfg, wanted)
    for pid, hosts in targets.items():
        if not hosts:  # an active probe with nothing to contact is left out rather than failing the run
            wanted.remove(pid)
    if not wanted:
        raise ValueError("no probes enabled (active sources need at least one host)")
    root = runs_root(pdir)
    root.mkdir(parents=True, exist_ok=True)
    busy = active_run_id(pdir)
    if busy:
        raise RunBusy(busy)
    rid = time.strftime("run-%Y%m%d-%H%M%S-", time.gmtime()) + secrets.token_hex(2)
    deadline = time.time() + win + EXTRA_TIME
    try:
        fd = os.open(str(_lock_path(pdir)), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        raise RunBusy(active_run_id(pdir) or "unknown")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"run": rid, "pid": os.getpid(), "started": time.time(), "deadline": deadline}, fh)
    run = _Run(pdir, rid)
    run.data = {
        "id": rid, "kind": IMPORT_KIND, "project": pdir.name, "status": "queued", "active": True, "window": win, "probes": wanted, "by": by,
        "created": time.time(), "started": None, "finished": None, "progress": 0.0, "stage": "queued", "log": [], "error": "",
        "summaries": {}, "counts": {}, "room": cfg.get("room") or "", "mode": run_mode(wanted), "targets": {k: v for k, v in targets.items() if v},
    }
    run.save()
    _prune_runs(pdir)

    def body(job: jobs.Job) -> Dict[str, Any]:
        return _execute(job, run, cfg, win, wanted, by)

    try:
        job = jobs.RUNNER.submit(IMPORT_KIND, _job_key(pdir), body, time_limit=win + EXTRA_TIME, job_id=rid)
    except jobs.JobBusy as exc:
        _lock_path(pdir).unlink(missing_ok=True)
        raise RunBusy(exc.job.id)
    job.on_change(run.update_from_job)
    run.update_from_job(job)  # catch up on anything that happened before the listener was attached
    return get_run(pdir, rid)


def cancel_run(pdir: Path, run_id: str) -> Dict[str, Any]:
    rd = run_dir(pdir, run_id)
    data = _read_json(rd / "run.json", None)
    if not isinstance(data, dict):
        raise RunNotFound(run_id)
    job = jobs.RUNNER.get(run_id)
    if job is not None:
        job.request_cancel("cancelled by user")
    else:
        (rd / CANCEL_NAME).write_text(str(time.time()), encoding="utf-8")  # another worker process owns the run
        if data.get("status") not in jobs.FINAL and active_run_id(pdir) != run_id:
            data.update({"status": "cancelled", "active": False, "finished": time.time(), "error": "cancelled by user"})
            _write_json(rd / "run.json", data)
    return get_run(pdir, run_id)


def _prune_runs(pdir: Path, keep: int = MAX_RUNS_KEPT) -> None:
    import shutil

    root = runs_root(pdir)
    dirs = sorted((p for p in root.iterdir() if p.is_dir() and RUN_ID_RE.match(p.name)), reverse=True)
    for p in dirs[keep:]:
        try:
            shutil.rmtree(p)
        except OSError:
            pass


def _execute(job: jobs.Job, run: _Run, cfg: Dict[str, Any], window: int, wanted: List[str], by: str) -> Dict[str, Any]:
    pdir = run.pdir
    raw_dir = run.dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    targets = run.data.get("targets") or {}
    if targets:
        detail = "; ".join(f"{pid} → {', '.join(hosts)}" for pid, hosts in targets.items())
        job.log(f"discovery run {run.id}: {', '.join(wanted)}; listen window {window} s; active read-only queries go to the listed hosts only ({detail}); nothing is written to any device")
    else:
        job.log(f"discovery run {run.id}: {', '.join(wanted)}; listen window {window} s; passive only — nothing is sent to AV devices")
    job.set_progress(0.02, "starting probes")
    results: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, str] = {}
    threads: List[threading.Thread] = []
    started = time.time()

    def runner(pid: str) -> None:
        mod = probe_by_id(pid)
        if mod is None:
            errors[pid] = "unknown probe"
            return
        psettings = dict(cfg["probes"].get(pid) or {})
        try:
            job.log(f"{pid}: collecting")
            if pid in LISTEN_PROBES:
                raw = mod.collect(psettings, job, window=float(window))
            else:
                raw = mod.collect(psettings, job)
            results[pid] = raw if isinstance(raw, dict) else {"payload": raw}
            _write_json(raw_dir / f"{pid}.json", results[pid])
            job.log(f"{pid}: done")
        except jobs.JobCancelled:
            errors[pid] = "cancelled"
        except Exception as exc:  # a failing probe never fails the run
            errors[pid] = dsettings.redact(f"{type(exc).__name__}: {exc}", pdir)
            job.log(f"{pid}: {errors[pid]}", "warn")

    for pid in wanted:
        t = threading.Thread(target=runner, args=(pid,), name=f"discovery-{pid}", daemon=True)
        t.start()
        threads.append(t)
    while any(t.is_alive() for t in threads):
        if (run.dir / CANCEL_NAME).exists() and not job.cancelled:
            job.request_cancel("cancelled by user")
        elapsed = time.time() - started
        job.set_progress(min(0.9, 0.05 + 0.85 * elapsed / max(1.0, float(window))), f"listening ({int(max(0, window - elapsed))} s left)" if elapsed < window else "finishing probes")
        if job.cancelled:  # probes poll the cancel flag; give them a moment to wind down, then move on with what we have
            for t in threads:
                t.join(timeout=3.0)
            break
        job.wait(0.5)
    job.set_progress(0.92, "correlating")
    probe_results = parse_results(run.dir)
    try:
        from ..project import read_doc

        doc, _ = read_doc(pdir)
    except Exception:
        doc = {}
    findings = compute_findings(run.id, probe_results, doc, read_decisions(pdir), room=cfg.get("room") or "")
    _write_json(run.dir / "findings.json", findings)
    run.data["summaries"] = {r.probe: r.summary() for r in probe_results}
    run.data["errors"] = errors
    run.data["counts"] = findings["counts"]
    if not job.cancelled:
        try:
            run.data["diff"] = _persist_diff(pdir, run, doc, findings)
        except Exception as exc:  # a diff that cannot be computed never fails the run
            job.log(f"could not diff against the previous run: {type(exc).__name__}: {exc}", "warn")
        else:
            d = run.data["diff"]
            if d.get("against"):
                c = d["counts"]
                job.log(f"compared with {d['against']}: {c['new_devices']} new, {c['missing_devices']} missing, {c['moved']} moved, {c['changed']} changed, "
                        f"{c['new_links']} new links, {c['lost_links']} lost links")
    for r in probe_results:
        for n in r.notes:
            job.log(n, "info")
    for pid, err in errors.items():
        if err != "cancelled":
            job.log(f"{pid} failed: {err}", "warn")
    c = findings["counts"]
    job.log(f"found {c['entities']} hosts ({c['new']} new, {c['matched']} match existing devices), {c['connections']} connections, {c['networks']} networks")
    if not job.cancelled or results:
        try:
            _register_import(pdir, run, by)
        except Exception as exc:
            job.log(f"could not register the run as an import: {type(exc).__name__}: {exc}", "warn")
    job.set_progress(1.0, "done")
    try:
        _lock_path(pdir).unlink(missing_ok=True)
    except OSError:
        pass
    return {"counts": findings["counts"]}


def _register_import(pdir: Path, run: _Run, by: str) -> None:
    """Point the project's single ``discovery`` import at this run (creates it on first use)."""
    from ..history import utc_now
    from ..project import apply_changes, current_revision, read_doc
    from ..schema import default_room_id

    doc, _ = read_doc(pdir)
    rel = run.dir.relative_to(pdir).as_posix()
    imports = [i for i in doc.get("imports") or [] if isinstance(i, dict)]
    ent = next((i for i in imports if i.get("kind") == IMPORT_KIND), None)
    if ent is None:
        taken = {i.get("id") for i in imports}
        n = 1
        while "imp-%04d" % n in taken:
            n += 1
        ent = {"id": "imp-%04d" % n, "kind": IMPORT_KIND, "room": run.data.get("room") or default_room_id(doc) or "main", "label": "Network discovery"}
    ent = dict(ent, path=rel, added=utc_now())
    if by:
        ent["by"] = by
    apply_changes(pdir, [{"op": "put", "coll": "imports", "id": ent["id"], "value": ent}], base_revision=current_revision(pdir), author=by,
                  summary=f"Discovery run {run.id}", source="discovery")


# ------------------------------------------------------------------ findings


def parse_results(rdir: Path) -> List[ProbeResult]:
    """Parse the raw payloads saved under ``<run>/raw`` with the probes' pure parsers."""
    out: List[ProbeResult] = []
    raw_dir = Path(rdir) / "raw"
    if not raw_dir.is_dir():
        return out
    for m in all_probes():
        p = raw_dir / f"{m.INFO.id}.json"
        if not p.is_file():
            continue
        raw = _read_json(p, None)
        try:
            out.append(m.parse(raw))
        except Exception as exc:
            out.append(ProbeResult(probe=m.INFO.id, status="error", notes=[f"{m.INFO.id}: parse failed: {type(exc).__name__}: {exc}"]))
    return out


def _unique_id(base: str, taken: set) -> str:
    did, i = base, 2
    while did in taken:
        did = f"{base}-{i}"
        i += 1
    taken.add(did)
    return did


def compute_findings(run_id: str, results: List[ProbeResult], doc: Doc, decisions: Optional[Dict[str, Any]] = None, room: str = "") -> Dict[str, Any]:
    """Entities, connections and networks for ``results`` against the (live) ``doc``."""
    from ..history import utc_now
    from ..schema import default_room_id

    decisions = decisions or {"entities": [], "connections": [], "networks": []}
    room = room or default_room_id(doc) or "main"
    entities = correlate(results, doc)
    ignored_e = set(decisions.get("entities") or [])
    taken = {str(d.get("id")) for d in doc.get("devices") or [] if isinstance(d, dict)}
    device_ids: Dict[str, str] = {}
    proposed: Dict[str, Dict[str, Any]] = {}
    for e in entities:
        if e.id in ignored_e:
            e.status = "ignored"
        if e.match and e.status in ("match",):
            device_ids[e.id] = str(e.match["device"])
        elif e.status in ("new", "possible", "ignored"):
            dev = propose_device(e, room, taken, seen=e.seen)
            taken.add(dev["id"])
            proposed[e.id] = dev
            device_ids[e.id] = dev["id"]
    by_mac: Dict[str, str] = {}
    for e in entities:
        for m in e.macs:
            by_mac.setdefault(m, e.id)
    devices = {str(d["id"]): d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id")}
    # resolve interface uplinks (switch MAC -> device id / port id) on proposed devices
    for e in entities:
        dev = proposed.get(e.id)
        if dev is None:
            continue
        for itf in dev.get("interfaces") or []:
            _resolve_uplink(itf, by_mac, device_ids, devices, proposed)
    connections = build_connections(entities, results, doc, device_ids)
    ignored_c = set(decisions.get("connections") or [])
    for c in connections:
        if c.id in ignored_c:
            c.status = "ignored"
    networks = build_networks(results, entities, doc)
    for n in networks:
        if n["id"] in set(decisions.get("networks") or []):
            n["status"] = "ignored"
    ents = []
    for e in entities:
        d = e.to_dict()
        d["device_id"] = device_ids.get(e.id, "")
        d["label"] = e.label
        d["proposed"] = proposed.get(e.id)
        d["interfaces"] = [{k: v for k, v in itf.items() if not k.startswith("_")} for itf in (proposed.get(e.id) or {}).get("interfaces") or entity_interfaces(e)]
        if e.match:
            d["interfaces"] = _matched_interfaces(e, devices.get(str(e.match["device"])), by_mac, device_ids, devices, proposed)
        d["connections"] = [c.id for c in connections if c.peer.get("entity") == e.id or c.switch.get("entity") == e.id]
        ents.append(d)
    counts = {
        "entities": len(entities), "new": sum(1 for e in entities if e.status == "new"), "matched": sum(1 for e in entities if e.status == "match"),
        "possible": sum(1 for e in entities if e.status == "possible"), "unresolved": sum(1 for e in entities if e.status == "unresolved"),
        "ignored": sum(1 for e in entities if e.status == "ignored"), "connections": len(connections),
        "cables": sum(1 for c in connections if c.cable and c.status == "new"), "networks": len(networks),
        "new_networks": sum(1 for n in networks if n["status"] == "new"), "probes": {r.probe: r.status for r in results},
    }
    return {
        "run": run_id, "computed": utc_now(), "revision": doc.get("revision", 0), "room": room, "counts": counts, "entities": ents,
        "connections": [c.to_dict() for c in connections], "rows": connection_rows(connections, doc, {d["id"]: d for d in proposed.values()}), "networks": networks,
        "notes": [n for r in results for n in r.notes], "probes": [r.summary() for r in results],
    }


def _resolve_uplink(itf: Dict[str, Any], by_mac: Dict[str, str], device_ids: Dict[str, str], devices: Dict[str, Dict[str, Any]], proposed: Dict[str, Dict[str, Any]]) -> None:
    smac = itf.pop("_switch_mac", "")
    sport = itf.pop("_switch_port", "")
    if not smac:
        return
    eid = by_mac.get(smac)
    did = device_ids.get(eid or "", "")
    if not did:
        return
    itf["switch"] = did
    sw_doc = devices.get(did)
    idx = int(sport.split()[-1]) if sport and sport.split()[-1].isdigit() else None
    if sw_doc is not None:
        itf["switch_port"] = doc_port_for(sw_doc, index=idx) or sport
    else:
        itf["switch_port"] = f"p{idx}" if idx is not None else sport


def _matched_interfaces(e: Entity, dev: Optional[Dict[str, Any]], by_mac: Dict[str, str], device_ids: Dict[str, str], devices: Dict[str, Dict[str, Any]],
                        proposed: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Interfaces the entity adds to a matched document device (those not already recorded by MAC or IP)."""
    from ..network import normalize_mac

    have_mac = {normalize_mac(str(i.get("mac") or "")) for i in (dev or {}).get("interfaces") or [] if isinstance(i, dict)}
    have_ip = {str(i.get("ip") or "") for i in (dev or {}).get("interfaces") or [] if isinstance(i, dict)}
    have_ids = {str(i.get("id") or "") for i in (dev or {}).get("interfaces") or [] if isinstance(i, dict)}
    out = []
    for itf in entity_interfaces(e):
        _resolve_uplink(itf, by_mac, device_ids, devices, proposed)
        known = (itf.get("mac") and itf["mac"] in have_mac) or (itf.get("ip") and itf["ip"] in have_ip)
        itf["known"] = bool(known)
        if itf["id"] in have_ids:
            itf["id"] = itf["id"] + "-d"
        out.append(itf)
    return out


_FINDINGS_CACHE: Dict[str, Tuple[Tuple[Any, ...], Dict[str, Any]]] = {}
_FINDINGS_LOCK = threading.Lock()


def findings(pdir: Path, doc: Doc, run_id: str) -> Dict[str, Any]:
    """Findings for a run recomputed against the live document (cached per revision / decisions)."""
    rd = run_dir(pdir, run_id)
    if not (rd / "raw").is_dir():
        data = _read_json(rd / "findings.json", None)
        if data is None:
            raise RunNotFound(run_id)
        return data
    dec_p = runs_root(pdir) / DECISIONS_NAME
    key = (str(rd), doc.get("revision", 0), dec_p.stat().st_mtime_ns if dec_p.is_file() else 0, (rd / "run.json").stat().st_mtime_ns if (rd / "run.json").is_file() else 0)
    with _FINDINGS_LOCK:
        hit = _FINDINGS_CACHE.get(str(rd))
        if hit and hit[0] == key:
            return hit[1]
    run_data = _read_json(rd / "run.json", {}) or {}
    out = compute_findings(run_id, parse_results(rd), doc, read_decisions(pdir), room=str(run_data.get("room") or ""))
    out["status"] = run_data.get("status")
    with _FINDINGS_LOCK:
        if len(_FINDINGS_CACHE) > 16:
            _FINDINGS_CACHE.clear()
        _FINDINGS_CACHE[str(rd)] = (key, out)
    return out


def latest_run_id(pdir: Path) -> str:
    runs = list_runs(pdir, limit=1)
    return str(runs[0]["id"]) if runs else ""


def completed_runs(pdir: Path, exclude: str = "") -> List[Dict[str, Any]]:
    """Briefs of the runs that finished normally (newest first), optionally without ``exclude``."""
    return [r for r in list_runs(pdir) if r.get("status") == "done" and r.get("id") != exclude]


def latest_completed_run_id(pdir: Path) -> str:
    runs = completed_runs(pdir)
    return str(runs[0]["id"]) if runs else ""


def previous_completed_run_id(pdir: Path, run_id: str) -> str:
    """The completed run just before ``run_id`` (by id, which sorts by start time), or ``""``."""
    for r in completed_runs(pdir, exclude=run_id):
        if str(r.get("id")) < run_id:
            return str(r["id"])
    return ""


# ------------------------------------------------------------------ run-to-run diff


def _persist_diff(pdir: Path, run: _Run, doc: Doc, cur: Dict[str, Any]) -> Dict[str, Any]:
    """Diff the finished run against the previous completed one and store it as ``diff.json``; returns the brief."""
    from .diff import compute_diff, empty_diff

    prev_id = previous_completed_run_id(pdir, run.id)
    if prev_id:
        d = compute_diff(cur, findings(pdir, doc, prev_id), run.id, prev_id)
    else:
        d = empty_diff(run.id, cur)
    _write_json(run.dir / "diff.json", d)
    return {"against": d["against"], "counts": d["counts"]}


def run_diff(pdir: Path, doc: Doc, run_id: str, against: str = "") -> Dict[str, Any]:
    """What changed between ``against`` (default: the previous completed run) and ``run_id``.

    Recomputed against the live document so the two sides are comparable; the diff persisted when the
    run finished is served as-is only when it was made against the same run and nothing else is asked.
    """
    from .diff import compute_diff, empty_diff

    rd = run_dir(pdir, run_id)
    if not (rd / "run.json").is_file():
        raise RunNotFound(run_id)
    candidates = completed_runs(pdir, exclude=run_id)
    if against:
        if against == run_id or not any(str(r.get("id")) == against for r in candidates):
            raise ValueError(f"{against} is not another completed run of this project")
        prev_id = against
    else:
        prev_id = previous_completed_run_id(pdir, run_id)
    stored = _read_json(rd / "diff.json", None)
    persisted = isinstance(stored, dict) and stored.get("against") == (prev_id or None)
    cur = findings(pdir, doc, run_id)
    d = compute_diff(cur, findings(pdir, doc, prev_id), run_id, prev_id) if prev_id else empty_diff(run_id, cur)
    return {"run": run_id, "against": prev_id or None, "candidates": candidates, "diff": d, "persisted": bool(persisted)}


# ------------------------------------------------------------------ promote


def promote_ops(pdir: Path, doc: Doc, run_id: str, body: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Change ops for a promote request.

    ``body``: ``{"entities": [ids], "merge": {entity: device}, "connections": [ids], "networks": [ids],
    "ignore": {"entities": [...], "connections": [...], "networks": [...]}, "room": ""}``.
    Ignore decisions are persisted here (they are not document changes).
    """
    f = findings(pdir, doc, run_id)
    ents = {e["id"]: e for e in f["entities"]}
    conns = {c["id"]: c for c in f["connections"]}
    nets = {n["id"]: n for n in f["networks"]}
    ops: List[Dict[str, Any]] = []
    summary = {"devices": 0, "merged": 0, "cables": 0, "networks": 0, "ignored": 0}
    devices = {str(d["id"]): d for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("id")}
    taken = set(devices)
    room = str(body.get("room") or "")
    created: Dict[str, str] = {}  # entity -> device id created in this request

    for eid in body.get("entities") or []:
        e = ents.get(str(eid))
        if e is None:
            raise ValueError(f"unknown entity {eid}")
        dev = e.get("proposed")
        if not dev:
            if e.get("status") == "match":
                raise ValueError(f"{e.get('label')} matches an existing device; use merge")
            raise ValueError(f"{e.get('label')} cannot be promoted (unresolved)")
        dev = json.loads(json.dumps(dev))
        if dev["id"] in taken:
            dev["id"] = _unique_id(dev["id"], taken)
        else:
            taken.add(dev["id"])
        if room:
            dev["room"] = room
        dev["interfaces"] = [{k: v for k, v in itf.items() if not k.startswith("_") and k != "known"} for itf in dev.get("interfaces") or []]
        created[str(eid)] = dev["id"]
        ops.append({"op": "put", "coll": "devices", "id": dev["id"], "value": dev})
        summary["devices"] += 1

    merge = body.get("merge") or {}
    if not isinstance(merge, dict):
        raise ValueError("merge must be an object")
    for eid, did in merge.items():
        e = ents.get(str(eid))
        if e is None:
            raise ValueError(f"unknown entity {eid}")
        target = devices.get(str(did))
        if target is None:
            raise ValueError(f"unknown device {did}")
        patch: Dict[str, Any] = {}
        existing = [dict(i) for i in target.get("interfaces") or [] if isinstance(i, dict)]
        ids = {str(i.get("id")) for i in existing}
        added = 0
        for itf in e.get("interfaces") or []:
            if itf.get("known"):
                for cur in existing:  # refresh switch / port / hostname on the interface we already have
                    if (itf.get("mac") and cur.get("mac") and str(cur["mac"]).lower() == itf["mac"]) or (itf.get("ip") and cur.get("ip") == itf["ip"]):
                        for k in ("switch", "switch_port", "hostname", "mac", "vlan"):
                            if itf.get(k) and not cur.get(k):
                                cur[k] = itf[k]
                        cur["source"] = "discovery"
                        cur["last_seen"] = itf.get("last_seen") or e.get("seen") or ""
                continue
            row = {k: v for k, v in itf.items() if not k.startswith("_") and k != "known"}
            if row["id"] in ids:
                row["id"] = _unique_id(row["id"], ids)
            ids.add(row["id"])
            existing.append(row)
            added += 1
        patch["interfaces"] = existing
        for k in ("manufacturer", "model"):
            if e.get(k) and not target.get(k):
                patch[k] = e[k]
        inv = dict(target.get("inventory") or {})
        if e.get("serial") and not inv.get("serial"):
            inv["serial"] = e["serial"]
        if e.get("firmware") and not inv.get("firmware"):
            inv["firmware"] = e["firmware"]
        if inv != (target.get("inventory") or {}):
            patch["inventory"] = inv
        if e.get("dante_name") and not target.get("dante_name"):
            patch["dante_name"] = e["dante_name"]
            patch["dante"] = True
        ops.append({"op": "merge", "coll": "devices", "id": str(did), "value": patch})
        created[str(eid)] = str(did)
        summary["merged"] += 1

    cable_ids = {str(c.get("id")) for c in doc.get("cables") or [] if isinstance(c, dict)}
    n = 1
    for cid in body.get("connections") or []:
        c = conns.get(str(cid))
        if c is None:
            raise ValueError(f"unknown connection {cid}")
        cable = c.get("cable")
        if not cable:
            raise ValueError(f"connection {cid} has no cable proposal (flagged {c.get('flag') or 'low confidence'})")
        cable = json.loads(json.dumps(cable))
        for end, side, is_switch in ((cable["from"], c["switch"], True), (cable["to"], c["peer"], False)):
            ent = side.get("entity")
            if ent in created and created[ent] != end["device"]:  # merged into an existing device in this request: re-pick its port
                end["device"] = created[ent]
                target = devices.get(end["device"])
                port = doc_port_for(target, index=c.get("port_index")) if is_switch else doc_port_for(target, label=str(side.get("port") or ""))
                end.pop("port", None)
                if port:
                    end["port"] = port
            if end["device"] not in taken and end["device"] not in created.values():
                raise ValueError(f"{side.get('label')} is not in the document yet; promote or merge it first")
        while "c-%04d" % n in cable_ids:
            n += 1
        cable["id"] = "c-%04d" % n
        cable_ids.add(cable["id"])
        cable["status"] = "planned"
        cable["source"] = IMPORT_KIND  # the report's "Discovered connections" section picks these up
        cable["discovery"] = {"run": run_id, "confidence": c.get("confidence"), "level": c.get("level") or "", "methods": list(c.get("methods") or [])}
        ops.append({"op": "put", "coll": "cables", "id": cable["id"], "value": cable})
        summary["cables"] += 1

    net_ids = {str(x.get("id")) for x in doc.get("networks") or [] if isinstance(x, dict)}
    for nid in body.get("networks") or []:
        net = nets.get(str(nid))
        if net is None:
            raise ValueError(f"unknown network {nid}")
        if net.get("match"):
            raise ValueError(f"network {net.get('name')} already exists as {net['match'].get('network')}")
        from ..model import slug

        did = _unique_id(slug(net.get("name") or ("vlan-%s" % net.get("vlan"))), net_ids)
        value: Dict[str, Any] = {"id": did, "name": net.get("name") or f"VLAN {net.get('vlan')}"}
        if net.get("vlan") is not None:
            value["vlan"] = int(net["vlan"])
        for k in ("subnet", "gateway", "dhcp_range"):
            if net.get(k):
                value[k] = net[k]
        if net.get("purpose"):
            value["notes"] = f"Discovered ({net['purpose']})"
        ops.append({"op": "put", "coll": "networks", "id": did, "value": value})
        summary["networks"] += 1

    ignore = body.get("ignore") or {}
    if ignore:
        if not isinstance(ignore, dict):
            raise ValueError("ignore must be an object")
        dec = read_decisions(pdir)
        for key in ("entities", "connections", "networks"):
            for x in ignore.get(key) or []:
                if str(x) not in dec[key]:
                    dec[key].append(str(x))
                    summary["ignored"] += 1
        for key in ("entities", "connections", "networks"):
            for x in (body.get("unignore") or {}).get(key) or []:
                if str(x) in dec[key]:
                    dec[key].remove(str(x))
        write_decisions(pdir, dec)
    elif body.get("unignore"):
        dec = read_decisions(pdir)
        for key in ("entities", "connections", "networks"):
            for x in (body.get("unignore") or {}).get(key) or []:
                if str(x) in dec[key]:
                    dec[key].remove(str(x))
        write_decisions(pdir, dec)
    return ops, summary


# ------------------------------------------------------------------ importer (overlay contribution)


class RunSnapshot:
    """Parse result for the ``discovery`` importer: a run folder."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.run = _read_json(self.path / "run.json", {}) or {}
        self.results = parse_results(self.path)

    def summary(self) -> Dict[str, Any]:
        return {"kind": IMPORT_KIND, "run": self.run.get("id"), "status": self.run.get("status"), "window": self.run.get("window"),
                "probes": [r.summary() for r in self.results], "counts": self.run.get("counts") or {}, "notes": [n for r in self.results for n in r.notes]}


def _detect(path: Path) -> float:
    p = Path(path)
    if p.is_dir() and (p / "run.json").is_file():
        data = _read_json(p / "run.json", {}) or {}
        return 0.95 if data.get("kind") == IMPORT_KIND else 0.0
    return 0.0


def _parse(path: Path, **_options: Any) -> RunSnapshot:
    p = Path(path)
    if not p.is_dir():
        raise ValueError("a discovery import is a run folder (exports/discovery/<run-id>), not a file")
    return RunSnapshot(p)


def _contribute(result: RunSnapshot, doc: Doc, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay contribution: medium+ confidence new hosts as auto devices, interfaces for matched devices, ``network`` routes."""
    pdir = result.path.parent.parent.parent if result.path.parent.name == "discovery" else None
    decisions = read_decisions(pdir) if pdir is not None else None
    f = compute_findings(str(result.run.get("id") or result.path.name), result.results, doc, decisions, room=str(ctx.get("room") or ""))
    out: Dict[str, Any] = {"devices": [], "interfaces": {}, "routes": [], "notes": []}
    for e in f["entities"]:
        if e["status"] == "new" and e["confidence"] >= OVERLAY_MIN_CONFIDENCE and e.get("proposed") and not _wireless_only(e):
            dev = json.loads(json.dumps(e["proposed"]))
            dev["source"] = IMPORT_KIND
            dev["interfaces"] = [{k: v for k, v in itf.items() if not k.startswith("_") and k != "known"} for itf in dev.get("interfaces") or []]
            for p in dev.get("ports") or []:
                p["auto"] = True
            out["devices"].append(dev)
            if dev["interfaces"]:
                out["interfaces"][dev["id"]] = list(dev["interfaces"])
        elif e["status"] == "match" and e.get("device_id"):
            rows = [{k: v for k, v in itf.items() if k != "known"} for itf in e.get("interfaces") or [] if not itf.get("known")]
            if rows:
                out["interfaces"][e["device_id"]] = rows
    for c in f["connections"]:
        if c.get("cable") and c["status"] == "new" and c["confidence"] >= OVERLAY_MIN_CONFIDENCE and c["flag"] in ("", "uplink"):
            cab = c["cable"]
            out["routes"].append({"kind": "network", "from": dict(cab["from"]), "to": dict(cab["to"]), "label": c["port"], "medium": cab.get("medium", "network"),
                                  "source": IMPORT_KIND, "confidence": c["confidence"]})
    cnt = f["counts"]
    out["notes"].append(f"discovery {f['run']}: {cnt['entities']} hosts seen ({cnt['new']} new, {cnt['matched']} matched), {len(out['routes'])} links in overlay")
    return out


def _wireless_only(e: Dict[str, Any]) -> bool:
    ups = e.get("uplinks") or []
    return bool(ups) and all(u.get("port") == "wifi" for u in ups)


def register() -> None:
    from .. import plugins

    plugins.register_importer(plugins.Importer(
        kind=IMPORT_KIND, label="Network discovery run", detect=_detect, parse=_parse, contribute=_contribute, mode="discovery", accepts=(), folder=True,
        help="Network discovery (UniFi controller, mDNS / Dante, LLDP / CDP, ARP; opt-in read-only SNMP, Yamaha SCP, Videohub, Q-SYS and Dante Domain Manager queries). "
             "Runs are started from the Discovery view; the latest completed run feeds the overlay.",
    ))


__all__ = [
    "IMPORT_KIND", "LISTEN_PROBES", "MODE", "RunBusy", "RunNotFound", "RunSnapshot", "active_run_id", "active_targets", "cancel_run", "completed_runs", "compute_findings",
    "extra_installed", "findings", "get_run", "latest_completed_run_id", "latest_run_id", "list_runs", "previous_completed_run_id", "run_diff", "parse_results", "promote_ops", "read_decisions", "register", "run_dir", "run_mode",
    "runs_root", "sources", "start_run", "write_decisions",
]
