"""Fathom command line.

  fathom serve [--host H] [--port N] [--data DIR] [--open]   web app (editor + viewer)
  fathom new <name|path> [--template T] [--org O]           create a project (T: blank | rrc-littleton | campus-demo)
  fathom import <project> <file|folder>... [--kind K] [--node ID] [--device NAME] [--room R] [--apply]
  fathom inspect <file|folder> [--kind K] [--json]          parse an export and show what was found
  fathom build <project> [--pdf] [--png] [--open] [--out DIR] [--state S] [--rooms a,b] [--base-url URL]
  fathom pdf <project|index.html> [--open]                  headless-Chrome PDF
  fathom trace <project> <from> [<to>] [--discipline D] [--up]   signal paths (cards, or dev:port)
  fathom patch <project> [--csv]                            patch sheet in the terminal
  fathom validate <project>                                 check ids, groups, columns, media
  fathom list                                               projects in the data dir
  fathom demo [--open] [--pdf] [--png]                      build the bundled sample system
  fathom status                                             interpreter, Chrome, data dir
  fathom selftest                                           parse samples, build, verify
  fathom migrate <project> [--write]                        v1 → v2 summary (and save)
  fathom user add|list|passwd|role|remove|disable|enable    users and roles
  fathom backup create [--include-builds] | list | restore <zip|name> [--yes]   whole-server backups
  fathom library list [-q Q] | show <id>                    equipment templates
  fathom schedule <kind> <project> [--room R] [--csv]       patch, cables, ip, dmx, bom, inventory, racks, labels
  fathom tags <project> [--scope all] [--apply]             auto cable tags (preview, then apply)
  fathom qr <project> [device] | --text T [--out F]         QR code SVGs
  fathom plan convert <file> [--out F] [--hide L1,L2]       floor plan → SVG/PNG
  fathom ask <project> "<question>" [--room R] [--json]     troubleshooting assistant
  fathom history <project> | restore <project> <rev>        revisions
  fathom vocab [--json]                                     kinds, media, disciplines
  fathom plugins                                            importers and plugin errors
  fathom discovery doctor [--seconds N] [--interface IF]    CAP_NET_RAW, interfaces / VLANs, foreign LLDP heard?

Data lives in FATHOM_DATA (default ~/.fathom): projects/<name>/ and builds/<name>/.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .export import build, find_chrome, html_to_pdf, open_in_browser
from .merge import apply_imports
from .model import KINDS, MEDIA, ImportSpec, validate
from .parsers import KINDS as IMPORT_KINDS, detect_kind, parse_any
from .patch import build_patch_sheet, patch_sheet_csv
from .project import SAMPLES_DIR, data_root, display_path, list_projects, load_project, new_project, projects_root, save_project
from .trace import describe_path, downstream, find_paths, resolve_node, upstream


def _print_summary(summary: dict) -> None:
    for k, v in summary.items():
        if k == "notes":
            continue
        if isinstance(v, (list, dict)) and v:
            print(f"  {k}:")
            if isinstance(v, dict):
                for kk, vv in v.items():
                    print(f"    {kk}: {vv}")
            else:
                for item in v[:40]:
                    print(f"    - {item}")
                if len(v) > 40:
                    print(f"    … {len(v) - 40} more")
        elif v not in ("", [], {}, None):
            print(f"  {k}: {v}")
    for n in summary.get("notes", []):
        print(f"  note: {n}")


def _importer_kinds() -> List[str]:
    try:
        from .plugins import importers

        kinds = [i.kind for i in importers()]
    except Exception:
        kinds = list(IMPORT_KINDS)
    for k in IMPORT_KINDS:
        if k not in kinds:
            kinds.append(k)
    return kinds


def _detect(src: Path) -> str:
    try:
        from .plugins import detect

        kind = detect(src)
    except Exception:
        kind = "unknown"
    return kind if kind != "unknown" else detect_kind(src)


def _load_doc(target: str):
    """(doc, project_dir, source_version) via W1's project.load_doc_info."""
    from .project import load_doc_info

    return load_doc_info(target)


def _die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


# ------------------------------------------------------------ v0.2 commands


def cmd_status(_a: argparse.Namespace) -> None:
    print(f"fathom {__version__} · python {sys.version.split()[0]}")
    chrome = find_chrome()
    print(f"chrome: {chrome or 'not found (server-side PDF/PNG unavailable; the page still prints from the browser)'}")
    try:
        from .floorplan import rasterizer

        print(f"pdf rasterizer: {rasterizer() or 'none (PDF floor plans need pdftoppm, mutool, gs or sips)'}")
    except Exception:
        pass
    print(f"data dir: {data_root()}{' (missing, created on first use)' if not data_root().is_dir() else ''}")
    projs = list_projects()
    print(f"projects: {', '.join(projs) if projs else 'none yet (fathom new my-venue)'}")
    samples = sorted(p.name for p in SAMPLES_DIR.iterdir() if p.is_dir() and (p / "project.json").is_file()) if SAMPLES_DIR.is_dir() else []
    print(f"samples: {', '.join(samples)}")
    print(f"kinds: {', '.join(KINDS)}")
    print(f"media: {', '.join(MEDIA)}")
    print(f"importers: {', '.join(_importer_kinds())}")


def cmd_new(a: argparse.Namespace) -> None:
    pdir = new_project(a.name, template=a.template, org=a.org or "", force=a.force)
    print(f"ok: project created at {pdir}")
    print("next: fathom import <project> <exports>, edit project.json (or fathom serve), then fathom build --open")


def cmd_import(a: argparse.Namespace) -> None:
    kinds = _importer_kinds()
    version = 1
    try:
        _doc, _pdir, version = _load_doc(a.project)
    except SystemExit:
        raise
    except Exception:
        version = 1
    if version < 2:
        return _import_v1(a, kinds)
    return _import_v2(a, kinds)


def _copy_in(src: Path, pdir: Path, kind: str, no_copy: bool) -> str:
    if no_copy:
        return str(src.resolve())
    dest_dir = pdir / "exports" / kind
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return str(dest.relative_to(pdir))


def _import_v1(a: argparse.Namespace, kinds: List[str]) -> None:
    project, pdir = load_project(a.project)
    for raw in a.files:
        src = Path(raw).expanduser()
        if not src.exists():
            raise SystemExit(f"error: {src} not found")
        kind = a.kind if a.kind != "auto" else detect_kind(src)
        if kind not in IMPORT_KINDS:
            raise SystemExit(f"error: cannot tell what {src.name} is; pass --kind yamaha|dante|waves (v1 projects; run fathom migrate --write for the other importers)")
        rel = _copy_in(src, pdir, kind, a.no_copy)
        result = parse_any(Path(rel) if Path(rel).is_absolute() else pdir / rel, kind, device=a.device or "")
        print(f"{kind}: {rel}")
        _print_summary(result.summary())
        existing = [i for i in project.imports if i.path == rel]
        if existing:
            for i in existing:
                i.kind = kind
                if a.node:
                    i.node = a.node
        else:
            project.imports.append(ImportSpec(kind=kind, path=rel, node=a.node or ""))
    path = save_project(project, pdir)
    print(f"ok: registered {len(a.files)} import(s) in {path}")


def _import_v2(a: argparse.Namespace, kinds: List[str]) -> None:
    from .plugins import get_importer
    from .project import apply_changes, current_revision

    doc, pdir, _v = _load_doc(a.project)
    room = a.room or (doc.get("settings") or {}).get("default_room") or ""
    ops: List[Dict[str, Any]] = []
    imports = list(doc.get("imports") or [])
    used = {i.get("id") for i in imports}
    for raw in a.files:
        src = Path(raw).expanduser()
        if not src.exists():
            raise SystemExit(f"error: {src} not found")
        kind = a.kind if a.kind != "auto" else _detect(src)
        imp = get_importer(kind)
        if imp is None:
            raise SystemExit(f"error: cannot tell what {src.name} is; pass --kind {'|'.join(kinds)}")
        result = imp.parse(src, device=a.device) if (a.device and kind == "dante") else imp.parse(src)
        print(f"{kind}: {src}")
        _print_summary(result.summary())
        if imp.mode == "oneshot":
            if imp.preview is None:
                continue
            pv = imp.preview(result, doc, {"room": room, "device": a.node or ""})
            print(f"  preview: {pv['summary']}")
            for w in pv.get("warnings") or []:
                print(f"  warning: {w}")
            for op in pv["ops"][:60]:
                print(f"    {op['op']} {op['coll']}/{op['id']}: {', '.join(sorted(op.get('value', {}))) if op['op'] == 'merge' else 'new'}")
            if a.apply:
                ops.extend(pv["ops"])
            else:
                print("  (preview only; pass --apply to write these changes)")
            continue
        rel = _copy_in(src, pdir, kind, a.no_copy)
        existing = next((i for i in imports if i.get("path") == rel), None)
        if existing is not None:
            val = dict(existing, kind=kind, room=existing.get("room") or room)
            if a.node:
                val["device"] = a.node
            ops.append({"op": "put", "coll": "imports", "id": existing["id"], "value": val})
            continue
        n = 1
        while f"imp-{n:04d}" in used:
            n += 1
        iid = f"imp-{n:04d}"
        used.add(iid)
        val = {"id": iid, "kind": kind, "path": rel, "room": room, "label": src.name}
        if a.node:
            val["device"] = a.node
        ops.append({"op": "put", "coll": "imports", "id": iid, "value": val})
    if not ops:
        return
    res = apply_changes(pdir, ops, base_revision=current_revision(pdir), author=os.environ.get("USER", "cli"), summary=f"Imported {len(a.files)} file(s)", source="import")
    print(f"ok: revision {res['revision']} ({len(ops)} change(s))")
    for p in res.get("problems") or []:
        if p.get("level") == "error":
            print(f"  problem: {p.get('message')}")


def cmd_inspect(a: argparse.Namespace) -> None:
    src = Path(a.file).expanduser()
    if not src.exists():
        raise SystemExit(f"error: {src} not found")
    kind = a.kind if a.kind != "auto" else _detect(src)
    print(f"detected: {kind}")
    result = parse_any(src, kind, device=a.device or "")
    if a.json:
        print(json.dumps(result.summary(), indent=2, ensure_ascii=False, default=str))
        return
    _print_summary(result.summary())
    if kind == "yamaha":
        for ch in result.named_inputs[:200]:  # type: ignore[attr-defined]
            patch = f" ← {ch.patch.text}" if ch.patch else ""
            print(f"    {ch.label:9} {ch.name:16} {ch.color:8} {ch.icon:10}{patch}")
    elif kind == "dante":
        for (tx, rx), subs in result.flows().items():  # type: ignore[attr-defined]
            print(f"    {tx} → {rx}: {len(subs)} ch")
    elif kind == "waves":
        for r in result.racks[:200]:  # type: ignore[attr-defined]
            print(f"    {r.index:3} {r.name:18} in {r.input or '—':10} out {r.output or '—':10} {r.chain()}")
    elif kind == "eos":
        for f in result.fixtures[:200]:  # type: ignore[attr-defined]
            print(f"    ch {f['channel']:>5}  {f['universe']}/{f['address']:<3}  {f.get('type', ''):28} {f.get('label', '')}")
    elif kind == "magicq":
        for f in result.heads[:200]:  # type: ignore[attr-defined]
            print(f"    head {f['head']:>5}  {f['universe']}-{f['address']:03d}  {f.get('type', ''):28} {f.get('label', '')}")
    elif kind == "videohub":
        for o, i in sorted(result.routing.items()):  # type: ignore[attr-defined]
            print(f"    out {o + 1:2} {result.output_labels.get(o, ''):14} ← in {i + 1:2} {result.input_labels.get(i, '')}")  # type: ignore[attr-defined]
    elif kind == "csv":
        print(f"    table: {result.table}, {len(result.rows)} rows")  # type: ignore[attr-defined]


def cmd_build(a: argparse.Namespace) -> None:
    run_dir = Path(a.out).expanduser() if a.out else None
    if a.state != "all" or a.rooms or a.base_url:
        from .export import build_doc, open_in_browser as _open

        rooms = [r for r in (a.rooms or "").split(",") if r] or None
        run = build_doc(a.project, state=a.state, rooms=rooms, pdf=a.pdf, png=a.png, base_url=a.base_url or "", run_dir=run_dir)
        print(f"ok: wrote {display_path(run / 'index.html')}")
        if a.open:
            _open(run / "index.html")
        return
    build(a.project, slug=a.slug or "", run_dir=run_dir, pdf=a.pdf, png=a.png, open_after=a.open)


def cmd_pdf(a: argparse.Namespace) -> None:
    target = Path(a.target).expanduser()
    if target.is_file() and target.suffix.lower() in (".html", ".htm"):
        out = target.parent / ("report.pdf" if target.name == "index.html" else target.with_suffix(".pdf").name)
        html_to_pdf(target, out)
        print(f"ok: wrote {display_path(out)}")
        if a.open:
            open_in_browser(out)
        return
    run_dir = build(a.target, pdf=True, open_after=False)
    if a.open:
        open_in_browser(run_dir / "report.pdf")


def cmd_trace(a: argparse.Namespace) -> None:
    port_level = a.up or a.discipline or ":" in a.source or (a.dest and ":" in a.dest)
    if not port_level:
        project, pdir = load_project(a.project)
        apply_imports(project, pdir)
        src = resolve_node(project, a.source)
        if src is not None and (not a.dest or resolve_node(project, a.dest) is not None):
            return _trace_cards(project, src, a)
    return _trace_ports(a)


def _trace_cards(project: Any, src: Any, a: argparse.Namespace) -> None:
    if a.dest:
        dst = resolve_node(project, a.dest)
        paths = find_paths(project, src.id, dst.id, max_depth=a.max_depth)
        if not paths:
            print(f"no path from {src.title} to {dst.title}")
            return
        print(f"{len(paths)} path(s) from {src.title} to {dst.title}:")
        for p in paths:
            print("  " + describe_path(project, p))
        return
    down = downstream(project, src.id, max_depth=a.max_depth)
    up = upstream(project, src.id, max_depth=a.max_depth)
    print(f"{src.title}: {len(down)} downstream path(s), {len(up)} upstream path(s)")
    for p in down[:40]:
        print("  → " + describe_path(project, p))
    for p in up[:40]:
        print("  ← " + describe_path(project, p))


def _trace_ports(a: argparse.Namespace) -> None:
    from . import trace as T
    from .merge import build_overlay

    doc, pdir, _v = _load_doc(a.project)
    try:
        overlay = build_overlay(doc, pdir)
    except Exception:
        overlay = None
    ref = T.resolve_ref(doc, a.source)
    if ref is None:
        raise SystemExit(f"error: no device or port matches '{a.source}' (use <device>:<port>)")
    start = f"{ref[0]}:{ref[1]}" if ref[1] else ref[0]
    depth = max(a.max_depth, 24) if a.max_depth == 8 else a.max_depth
    g = T.port_graph(doc, overlay, discipline=a.discipline or None)
    if a.dest:
        ref2 = T.resolve_ref(doc, a.dest)
        if ref2 is None:
            raise SystemExit(f"error: no device or port matches '{a.dest}'")
        end = f"{ref2[0]}:{ref2[1]}" if ref2[1] else ref2[0]
        paths = T.port_paths(g, start, end, max_depth=depth)
        label = f"from {a.source} to {a.dest}"
    elif a.up:
        paths = T.upstream_paths(g, start, max_depth=depth)
        label = f"upstream of {a.source}"
    else:
        paths = T.downstream_paths(g, start, max_depth=depth)
        label = f"downstream of {a.source}"
    if not paths:
        print(f"no path {label}")
        return
    print(f"{len(paths)} path(s) {label}{' (' + a.discipline + ')' if a.discipline else ''}:")
    for p in paths[:50]:
        print("  " + T.path_text(doc, p))
        if p.get("cables"):
            print("      cables: " + ", ".join(p["cables"]))


def cmd_patch(a: argparse.Namespace) -> None:
    project, pdir = load_project(a.project)
    apply_imports(project, pdir)
    if a.csv:
        sys.stdout.write(patch_sheet_csv(project))
        return
    for sheet in build_patch_sheet(project):
        print(f"\n{sheet.node.title}" + (f"  [{' · '.join(sheet.declared_ports)}]" if sheet.declared_ports else ""))
        for r in sheet.inputs:
            print(f"  in  {r.port:28} {project.medium(r.medium)['label']:20} ← {r.peer}{(' · ' + r.peer_port) if r.peer_port else ''}{('  (' + r.signal + ')') if r.signal else ''}")
        for r in sheet.outputs:
            print(f"  out {r.port:28} {project.medium(r.medium)['label']:20} → {r.peer}{(' · ' + r.peer_port) if r.peer_port else ''}{('  (' + r.signal + ')') if r.signal else ''}")


def cmd_validate(a: argparse.Namespace) -> None:
    project, pdir = load_project(a.project)
    problems = validate(project)
    apply_imports(project, pdir)
    for p in problems:
        print(f"problem: {p}")
    for n in project.notes:
        print(f"note: {n}")
    v2_errors = 0
    try:
        from .schema import validate_doc

        doc, _pdir, version = _load_doc(a.project)
        if version == 2:
            for p in validate_doc(doc):
                print(f"{p.get('level')}: {p.get('code')} {p.get('ref', '')}: {p.get('message', '')}")
                v2_errors += p.get("level") == "error"
    except Exception:
        pass
    print(f"{'ok' if not problems and not v2_errors else 'error'}: {len(project.nodes)} cards, {len(project.links)} links, {len(project.groups)} groups, {len(project.imports)} imports")
    if problems or v2_errors:
        sys.exit(1)


def cmd_list(_a: argparse.Namespace) -> None:
    projs = list_projects()
    if not projs:
        print(f"no projects under {projects_root()} (fathom new my-venue)")
        return
    for p in projs:
        print(f"{p}\t{projects_root() / p}")


def cmd_demo(a: argparse.Namespace) -> None:
    sample = SAMPLES_DIR / "rrc-littleton"
    build(str(sample), slug="signal-flow-demo", run_dir=Path(a.out).expanduser() if a.out else None, pdf=a.pdf, png=a.png, open_after=a.open)


def cmd_serve(a: argparse.Namespace) -> None:
    if a.data:
        os.environ["FATHOM_DATA"] = str(Path(a.data).expanduser().resolve())
    from .server import serve

    serve(host=a.host, port=a.port, open_browser=a.open)


def cmd_selftest(_a: argparse.Namespace) -> None:
    from .selftest import run_selftest

    sys.exit(run_selftest())


# --------------------------------------------------------------- new in 0.3


def cmd_migrate(a: argparse.Namespace) -> None:
    from . import schema
    from .project import load_dict, resolve_project, save_doc

    path = resolve_project(a.project)
    data = load_dict(path)
    version = schema.doc_version(data)
    doc = schema.load_any(data)
    ports = [p for d in doc.get("devices") or [] for p in d.get("ports") or []]
    declared = sum(1 for p in ports if p.get("origin") == "declared")
    generated = sum(1 for p in ports if p.get("origin") == "link")
    problems = schema.validate_doc(doc)
    warn = [p for p in problems if p.get("level") == "warning"]
    errs = [p for p in problems if p.get("level") == "error"]
    print(f"{path}: schema {version} → 2")
    print(f"  devices: {len(doc.get('devices') or [])}")
    print(f"  ports: {len(ports)} ({declared} declared, {generated} generated from link text)")
    print(f"  cables: {len(doc.get('cables') or [])}")
    print(f"  bundles: {len(doc.get('bundles') or [])}")
    extra = sum(len((r.get("flow") or {}).get("extra_cards") or []) for r in doc.get("rooms") or [])
    if extra:
        print(f"  extra map cards: {extra}")
    print(f"  warnings: {len(warn)}")
    for p in warn[:30]:
        print(f"    {p.get('code')} {p.get('ref', '')}: {p.get('message', '')}")
    for p in errs[:30]:
        print(f"  error: {p.get('code')} {p.get('ref', '')}: {p.get('message', '')}")
    if a.write:
        if version == 2:
            print("ok: already schema 2; nothing to write")
            return
        res = save_doc(doc, path.parent, base_revision=None, author=os.environ.get("USER", "cli"), summary="Migrated to schema 2", source="migrate")
        print(f"ok: wrote schema 2 (revision {res['revision']}); original kept as {display_path(path.parent / 'project.v1.json')}")
    elif version < 2:
        print("(dry run; pass --write to save as schema 2)")


def _read_password(a: argparse.Namespace, confirm: bool = True) -> str:
    if getattr(a, "password_stdin", False):
        pw = sys.stdin.readline().rstrip("\r\n")
    else:
        pw = getpass.getpass("password: ")
        if confirm and getpass.getpass("again: ") != pw:
            _die("passwords do not match")
    if not pw:
        _die("empty password")
    return pw


def cmd_user(a: argparse.Namespace) -> None:
    from . import users

    try:
        if a.action == "list":
            rows = users.list_users()
            if not rows:
                print("no users (the app is open to everyone unless FATHOM_AUTH is set)")
            for u in rows:
                flags = " (disabled)" if u.get("disabled") else ""
                proj = ", ".join(f"{k}:{v}" for k, v in sorted((u.get("projects") or {}).items()))
                print(f"{u['username']}\t{u.get('role', '')}{flags}{chr(9) + proj if proj else ''}")
            return
        if not a.name:
            _die(f"user {a.action} needs a user name")
        if a.action == "add":
            u = users.add_user(a.name, _read_password(a), role=a.role or "editor")
            print(f"ok: added {u['username']} ({u.get('role')})")
        elif a.action == "passwd":
            users.set_password(a.name, _read_password(a))
            print(f"ok: password changed for {a.name} (their sessions are signed out)")
        elif a.action == "role":
            role = a.value or a.role
            if not role:
                _die("user role <name> <viewer|editor|admin>")
            users.set_role(a.name, role)
            print(f"ok: {a.name} is now {role}")
        elif a.action == "remove":
            users.remove_user(a.name)
            print(f"ok: removed {a.name}")
        elif a.action in ("disable", "enable"):
            users.set_disabled(a.name, a.action == "disable")
            print(f"ok: {a.name} {a.action}d")
    except (ValueError, KeyError, LookupError) as exc:
        _die(str(exc).strip("'\""))


def cmd_backup(a: argparse.Namespace) -> None:
    from . import backup as B

    try:
        if a.action == "list":
            rows = B.list_backups()
            if not rows:
                print(f"no backups in {display_path(B.backups_root())}")
            for b in rows:
                desc = b.get("error") or f"{len(b.get('projects') or [])} projects{' + builds' if b.get('include_builds') else ''}"
                print(f"{b['name']}\t{B.human_size(b['size'])}\t{b.get('kind') or ''}\t{desc}\t{b.get('label') or ''}")
            return
        if a.action == "create":
            info = B.create_backup(include_builds=a.include_builds, label=a.label or "", author=getpass.getuser(), kind="cli")
            path = B.backups_root() / info["name"]
            if a.out:
                out = Path(a.out).expanduser()
                out = out / info["name"] if out.is_dir() else out
                if out.resolve() != path.resolve():
                    shutil.copy2(path, out)
                    path = out
            print(f"ok: {display_path(path)} ({B.human_size(info['size'])}, {len(info.get('projects') or [])} projects)")
            return
        if not a.target:
            _die("backup restore <file.zip | backup name>")
        target = Path(a.target).expanduser()
        if not a.yes:
            print(f"This replaces every project, user and custom template in {display_path(data_root())} with {a.target}.")
            if input("Type RESTORE to continue: ").strip().upper() != "RESTORE":
                _die("not restored")
        if target.is_file():
            res = B.restore_file(target, author=getpass.getuser(), safety=not a.no_safety)
        else:
            res = B.restore_backup(a.target, author=getpass.getuser(), safety=not a.no_safety)
        print(f"ok: restored {res['restored']} ({len(res['projects'])} projects)")
        if res.get("pre_restore_backup"):
            print(f"  previous data saved as {res['pre_restore_backup']}")
    except B.BackupError as exc:
        _die(str(exc))


def cmd_library(a: argparse.Namespace) -> None:
    from .library import get_template, list_templates, ports_summary

    if a.action == "show":
        if not a.id:
            _die("library show <template-id>")
        t = get_template(a.id)
        if t is None:
            _die(f"no template '{a.id}' (fathom library list -q …)")
        if a.json:
            print(json.dumps(t, indent=2, ensure_ascii=False))
            return
        print(f"{t['id']}: {t.get('manufacturer', '')} {t.get('model', '')} · {t.get('kind', '')}{(' · ' + str(t['ru']) + 'U') if t.get('ru') else ''} [{t.get('source', 'builtin')}]")
        print(f"  ports: {ports_summary(t)}")
        from .library import expand_port_groups

        for p in expand_port_groups(t.get("ports") or []):
            print(f"    {p['id']:24} {p['name']:28} {p['dir']:3} {p['medium']}{(' ×' + str(p['channels'])) if p.get('channels') else ''}")
        for k in ("source_url", "notes"):
            if t.get(k):
                print(f"  {k}: {t[k]}")
        return
    rows = list_templates(a.q or "", discipline=a.discipline or "", kind=a.kind or "")
    if a.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    for r in rows:
        print(f"{r['id']:40} {r['manufacturer'] + ' ' + r['model']:44} {r['kind']:16} {r['source']}")
    print(f"{len(rows)} template(s)")


_SCHEDULES = ("patch", "cables", "ip", "dmx", "bom", "inventory", "racks", "labels")


def cmd_schedule(a: argparse.Namespace) -> None:
    from . import cables as C
    from .merge import build_overlay, filter_state

    doc, pdir, _v = _load_doc(a.project)
    room = a.room or "*"
    fdoc = filter_state(doc, a.state)
    if a.kind == "labels":
        sys.stdout.write(C.label_sheet_html(fdoc, room=room, qr=bool(a.base_url), base_url=a.base_url or ""))
        return
    overlay = None
    if a.kind in ("patch", "ip", "dmx"):
        try:
            overlay = build_overlay(doc, pdir)
        except Exception:
            overlay = None
    if a.kind == "patch":
        from .patch import patch_schedule, patch_table, patch_table_csv

        if a.csv:
            sys.stdout.write(patch_table_csv(patch_table(fdoc, overlay, room=room, discipline=a.discipline or "")))
            return
        data = patch_schedule(fdoc, overlay, room=room, discipline=a.discipline or "")
    elif a.kind == "cables":
        data = C.cable_schedule(doc, room=room, state=a.state, discipline=a.discipline or "")
    elif a.kind == "ip":
        from .network import ip_schedule

        data = ip_schedule(fdoc, overlay, room=room)
    elif a.kind == "dmx":
        from .dmx import dmx_schedule

        data = dmx_schedule(fdoc, overlay, room=room)
    elif a.kind == "bom":
        from .bom import bom

        data = bom(doc, state=a.state, room=room)
    elif a.kind == "inventory":
        from .bom import inventory_schedule

        data = inventory_schedule(doc, room=room)
    else:
        from .racks import rack_schedule

        data = rack_schedule(fdoc, room=room)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return
    if a.csv:
        sys.stdout.write(C.to_csv(data))
        return
    cols = data.get("columns") or []
    rows = data.get("rows") or []
    widths = {c["key"]: min(28, max([len(str(c["label"]))] + [len(str(r.get(c["key"], "") or "")) for r in rows[:500]])) for c in cols}
    keep = [c for c in cols if any(str(r.get(c["key"], "") or "") for r in rows)] or cols
    print("  ".join(str(c["label"]).ljust(widths[c["key"]]) for c in keep))
    for r in rows:
        print("  ".join(str(r.get(c["key"], "") if r.get(c["key"]) is not None else "")[:28].ljust(widths[c["key"]]) for c in keep))
    for k, v in (data.get("totals") or {}).items():
        print(f"total {k}: {v}")
    for p in data.get("problems") or []:
        print(f"{p.get('level')}: {p.get('code')} {p.get('message', '')}")


def cmd_tags(a: argparse.Namespace) -> None:
    from .cables import assign_tags_ops
    from .project import apply_changes, current_revision

    doc, pdir, _v = _load_doc(a.project)
    ops = assign_tags_ops(doc, scope=a.scope, pattern=a.pattern or None)
    names = {c.get("id"): c for c in (doc.get("cables") or []) + (doc.get("bundles") or [])}
    for op in ops:
        old = names.get(op["id"], {}).get("tag") or "—"
        print(f"  {op['coll'][:-1]} {op['id']}: {old} → {op['value']['tag']}")
    print(f"{len(ops)} tag(s)")
    if a.apply and ops:
        res = apply_changes(pdir, ops, base_revision=current_revision(pdir), author=os.environ.get("USER", "cli"), summary=f"Assigned {len(ops)} cable tags", source="cli")
        print(f"ok: revision {res['revision']}")
    elif ops:
        print("(preview only; pass --apply to write)")


def cmd_qr(a: argparse.Namespace) -> None:
    from . import qr as Q
    from .export import device_url, public_base

    if a.text:
        mat = Q.encode(a.text, ecl=a.ecl)
        if a.ascii:
            _print_qr(mat)
            return
        svg = Q.to_svg(mat, scale=a.scale)
        if a.out:
            Path(a.out).expanduser().write_text(svg, encoding="utf-8")
            print(f"ok: wrote {a.out} (version {(len(mat) - 17) // 4}, {len(mat)}×{len(mat)})")
        else:
            print(svg)
        return
    if not a.project:
        _die("qr <project> [device] or qr --text TEXT")
    doc, pdir, _v = _load_doc(a.project)
    base = public_base(doc, a.base_url or "")
    if not base:
        _die("no public URL: pass --base-url https://… or set settings.public_url / FATHOM_PUBLIC_URL", 2)
    devs = [d for d in doc.get("devices") or [] if not a.device or d.get("id") == a.device]
    if a.device and not devs:
        _die(f"no device '{a.device}'")
    if a.device and not a.out:
        url = device_url(base, pdir.name, a.device)
        if a.ascii:
            _print_qr(Q.encode(url, ecl=a.ecl))
            print(url)
        else:
            print(Q.svg(url, ecl=a.ecl, scale=a.scale))
        return
    out = Path(a.out or "qr").expanduser()
    if a.device and out.suffix == ".svg":
        out.write_text(Q.svg(device_url(base, pdir.name, a.device), ecl=a.ecl, scale=a.scale), encoding="utf-8")
        print(f"ok: wrote {out}")
        return
    out.mkdir(parents=True, exist_ok=True)
    for d in devs:
        (out / f"{d['id']}.svg").write_text(Q.svg(device_url(base, pdir.name, d["id"]), ecl=a.ecl, scale=a.scale), encoding="utf-8")
    print(f"ok: wrote {len(devs)} QR code(s) to {out}")


def _print_qr(mat: List[List[bool]]) -> None:
    n = len(mat)
    pad = [[False] * (n + 4) for _ in range(2)]
    rows = pad + [[False, False] + r + [False, False] for r in mat] + pad
    if len(rows) % 2:
        rows.append([False] * (n + 4))
    for y in range(0, len(rows), 2):
        line = ""
        for x in range(n + 4):
            top, bot = rows[y][x], rows[y + 1][x]
            line += "█" if not top and not bot else ("▄" if top and not bot else ("▀" if bot and not top else " "))
        print(line)


def cmd_plan(a: argparse.Namespace) -> None:
    from .floorplan import UnsupportedPlan, convert

    src = Path(a.file).expanduser()
    if not src.is_file():
        _die(f"{src} not found")
    hide = [h for h in (a.hide or "").split(",") if h]
    try:
        res = convert(src, page=a.page, hide_layers=hide or None)
    except UnsupportedPlan as exc:
        _die(f"{exc.code}: {exc.message}", 2)
        return
    out = Path(a.out).expanduser() if a.out else src.with_name(src.stem + "." + res.image_kind)
    if out.resolve() == src.resolve():
        out = src.with_name(src.stem + ".converted." + res.image_kind)
    out.write_bytes(res.data)
    print(f"{src.name}: {res.kind} → {res.image_kind} {int(round(res.width))}×{int(round(res.height))} px, {len(res.data)} bytes")
    if res.units:
        print(f"  units: {res.units}")
    for L in res.layers:
        print(f"  layer {L['name']}: {'visible' if L['visible'] else 'hidden'}, {L['count']} entities")
    for w in res.warnings:
        print(f"  warning: {w}")
    print(f"ok: wrote {display_path(out)}")


def cmd_ask(a: argparse.Namespace) -> None:
    try:
        from .assistant import answer
    except ImportError:
        _die("the assistant module is not available in this build")
        return
    from .merge import build_overlay

    doc, pdir, _v = _load_doc(a.project)
    try:
        overlay = build_overlay(doc, pdir)
    except Exception:
        overlay = None
    res = answer(doc, a.question, room=a.room, overlay=overlay, use_llm=not a.no_llm, base_revision=doc.get("revision"))
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        return
    print(res.get("summary") or "(no summary)")
    for p in res.get("paths") or []:
        print(f"  path ({p.get('role', '')}): {p.get('text', '')}")
    if res.get("branch"):
        print(f"  branch: {res['branch'].get('reason', '')}")
    for c in res.get("checks") or []:
        print(f"  {c.get('n')}. {c.get('text', '')}")
    for n in res.get("notes") or []:
        print(f"  note: {n}")
    if res.get("suggestion"):
        print(f"  suggestion: {res['suggestion'].get('text', '')}")
    llm = res.get("llm") or {}
    if llm.get("used"):
        print(f"\n{llm.get('model', 'LLM')}: {llm.get('text', '')}")
    print(f"  confidence: {res.get('confidence', '')}")


def cmd_sop_bundle(a: argparse.Namespace) -> None:
    """Offline HTML bundle of the published procedures (a folder, or a zip when --out ends in .zip)."""
    from .export import sop_bundle_zip, write_sop_bundle

    doc, pdir, _v = _load_doc(a.project)
    pages = [p for p in doc.get("pages") or [] if isinstance(p, dict) and (p.get("status") or "published") == "published"]
    out = Path(a.out or f"{pdir.name}-procedures.zip").expanduser()
    if out.suffix.lower() == ".zip":
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(sop_bundle_zip(pdir, doc))
        print(f"ok: wrote {out} ({len(pages)} published page{'s' if len(pages) != 1 else ''}; unzip and open index.html)")
    else:
        files = write_sop_bundle(pdir, doc, out)
        print(f"ok: wrote {len(files)} files to {out} ({len(pages)} published page{'s' if len(pages) != 1 else ''}; open index.html)")


def cmd_history(a: argparse.Namespace) -> None:
    from .history import list_revisions
    from .project import resolve_project

    pdir = resolve_project(a.project).parent
    revs = list_revisions(pdir, limit=a.limit)
    if not revs:
        print("no history yet (revisions start with the first save)")
        return
    for r in revs:
        print(f"r{r.get('revision'):<5} {r.get('time', '')}  {r.get('author', '') or '-':12} {r.get('source', ''):8} {r.get('summary', '')}  ({r.get('ops', 0)} ops)")


def cmd_restore(a: argparse.Namespace) -> None:
    from .project import current_revision, resolve_project, restore_revision

    pdir = resolve_project(a.project).parent
    try:
        res = restore_revision(pdir, a.revision, base_revision=current_revision(pdir), author=os.environ.get("USER", "cli"))
    except KeyError:
        _die(f"revision {a.revision} is not in the history")
        return
    print(f"ok: restored revision {a.revision} as revision {res['revision']}")


def cmd_vocab(a: argparse.Namespace) -> None:
    from .vocab import as_dict

    v = as_dict()
    if a.json:
        print(json.dumps(v, indent=2, ensure_ascii=False))
        return
    for section in ("disciplines", "kinds", "media"):
        print(f"{section} ({len(v[section])}):")
        for k, e in v[section].items():
            extra = e.get("discipline") or e.get("letter", "")
            print(f"  {k:18} {e['label']:32} {e['color']}  {extra}")


def cmd_plugins(_a: argparse.Namespace) -> None:
    from .plugins import importers, load_plugins, plugin_errors

    load_plugins()
    for i in importers():
        print(f"{i.kind:10} {i.label:48} {i.mode:8} {i.source}")
    errs = plugin_errors()
    for e in errs:
        print(f"error: {e}")
    if not errs:
        print(f"{len(importers())} importer(s); plugin dirs: {os.environ.get('FATHOM_PLUGINS') or '(none; set FATHOM_PLUGINS)'}")


# ------------------------------------------------------------------ main


def cmd_discovery_doctor(a: argparse.Namespace) -> None:
    from .discovery import doctor

    do_listen = a.seconds > 0
    if do_listen and not a.json:
        print(f"listening for LLDP / CDP for {a.seconds:.0f} s (nothing is sent) …", file=sys.stderr)
    rep = doctor.report(seconds=a.seconds, interface=a.interface, do_listen=do_listen)
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        print(doctor.format_report(rep))
    sys.exit(1 if rep["advice"] else 0)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="fathom", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"fathom {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    kinds = ["auto"] + _importer_kinds()

    s = sub.add_parser("serve", help="web app (editor + viewer)")
    s.add_argument("--host", default=os.environ.get("FATHOM_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(os.environ.get("FATHOM_PORT") or 8080))
    s.add_argument("--data", help="data directory (default FATHOM_DATA or ~/.fathom)")
    s.add_argument("--open", action="store_true", help="open the browser")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("status", help="interpreter, Chrome, data dir")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("new", help="create a project")
    s.add_argument("name", help="project name (in the data dir) or a path")
    s.add_argument("--template", default="blank", help="blank or a sample name (rrc-littleton, campus-demo)")
    s.add_argument("--org", help="organisation / venue name for the header")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_new)

    s = sub.add_parser("import", help="copy exports into a project and register them")
    s.add_argument("project")
    s.add_argument("files", nargs="+")
    s.add_argument("--kind", default="auto", choices=kinds)
    s.add_argument("--node", help="card / device id the data belongs to (console for yamaha, FOH computer for waves, router for videohub)")
    s.add_argument("--device", help="Dante device name for a Receive-tab table paste")
    s.add_argument("--room", help="room the import belongs to (v2 projects; default: the default room)")
    s.add_argument("--apply", action="store_true", help="one-shot importers (csv): write the previewed changes")
    s.add_argument("--no-copy", action="store_true", help="reference the file where it is instead of copying")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("inspect", help="parse an export and show what was found")
    s.add_argument("file")
    s.add_argument("--kind", default="auto", choices=kinds)
    s.add_argument("--device")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser("build", help="render a project into builds/<name>/<stamp>/")
    s.add_argument("project")
    s.add_argument("--slug")
    s.add_argument("--out", help="explicit output folder")
    s.add_argument("--pdf", action="store_true")
    s.add_argument("--png", action="store_true")
    s.add_argument("--open", action="store_true")
    s.add_argument("--state", default="all", choices=["all", "planned", "as_built", "everything"])
    s.add_argument("--rooms", help="comma-separated room ids (default: all rooms)")
    s.add_argument("--base-url", help="public URL for QR codes (else settings.public_url / FATHOM_PUBLIC_URL)")
    s.set_defaults(func=cmd_build)

    s = sub.add_parser("pdf", help="PDF via headless Chrome")
    s.add_argument("target", help="project or an index.html")
    s.add_argument("--open", action="store_true")
    s.set_defaults(func=cmd_pdf)

    s = sub.add_parser("trace", help="signal paths between cards, or from a device port (dev:port)")
    s.add_argument("project")
    s.add_argument("source")
    s.add_argument("dest", nargs="?")
    s.add_argument("--max-depth", type=int, default=8)
    s.add_argument("--discipline", help="audio, video, lighting, network, control, power")
    s.add_argument("--up", action="store_true", help="trace upstream (toward the sources)")
    s.set_defaults(func=cmd_trace)

    s = sub.add_parser("patch", help="patch sheet in the terminal")
    s.add_argument("project")
    s.add_argument("--csv", action="store_true")
    s.set_defaults(func=cmd_patch)

    s = sub.add_parser("validate", help="check the project file")
    s.add_argument("project")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("list", help="projects in the data dir")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("demo", help="build the bundled sample")
    s.add_argument("--out")
    s.add_argument("--open", action="store_true")
    s.add_argument("--pdf", action="store_true")
    s.add_argument("--png", action="store_true")
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("selftest", help="parse samples, build, verify")
    s.set_defaults(func=cmd_selftest)

    s = sub.add_parser("migrate", help="summarise (and save) the v1 → v2 migration")
    s.add_argument("project")
    s.add_argument("--write", action="store_true", help="save as schema 2 (keeps project.v1.json)")
    s.set_defaults(func=cmd_migrate)

    s = sub.add_parser("user", help="users and roles (FATHOM_DATA/users.json)")
    s.add_argument("action", choices=["add", "list", "passwd", "role", "remove", "disable", "enable"])
    s.add_argument("name", nargs="?")
    s.add_argument("value", nargs="?", help="role for 'user role <name> <role>'")
    s.add_argument("--role", choices=["viewer", "editor", "admin"])
    s.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    s.set_defaults(func=cmd_user)

    s = sub.add_parser("backup", help="whole-server backups (FATHOM_DATA/backups)")
    s.add_argument("action", choices=["create", "list", "restore"])
    s.add_argument("target", nargs="?", help="restore: a backup .zip path or a name from 'backup list'")
    s.add_argument("--include-builds", action="store_true", help="create: also back up rendered builds")
    s.add_argument("--label", help="create: a note stored in the backup")
    s.add_argument("--out", help="create: also copy the zip here (file or folder)")
    s.add_argument("--yes", action="store_true", help="restore: do not ask for confirmation")
    s.add_argument("--no-safety", action="store_true", help="restore: skip the pre-restore backup of the current data")
    s.set_defaults(func=cmd_backup)

    s = sub.add_parser("library", help="equipment templates")
    s.add_argument("action", choices=["list", "show"])
    s.add_argument("id", nargs="?")
    s.add_argument("-q", "--q", help="search text")
    s.add_argument("--discipline")
    s.add_argument("--kind")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_library)

    s = sub.add_parser("schedule", help="schedules: " + ", ".join(_SCHEDULES))
    s.add_argument("kind", choices=_SCHEDULES)
    s.add_argument("project")
    s.add_argument("--room")
    s.add_argument("--state", default="all", choices=["all", "planned", "as_built", "everything"])
    s.add_argument("--discipline")
    s.add_argument("--base-url", help="labels: add QR codes pointing here")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--csv", action="store_true")
    g.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_schedule)

    s = sub.add_parser("tags", help="auto cable tags from settings.cable_tag_pattern")
    s.add_argument("project")
    s.add_argument("--scope", default="missing", choices=["missing", "all"])
    s.add_argument("--pattern")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_tags)

    s = sub.add_parser("qr", help="QR code SVGs for device pages (or any text)")
    s.add_argument("project", nargs="?")
    s.add_argument("device", nargs="?")
    s.add_argument("--text")
    s.add_argument("--base-url")
    s.add_argument("--ecl", default="M", choices=["L", "M", "Q", "H"])
    s.add_argument("--scale", type=int, default=4)
    s.add_argument("--out")
    s.add_argument("--ascii", action="store_true", help="print the code in the terminal")
    s.set_defaults(func=cmd_qr)

    s = sub.add_parser("plan", help="floor plans")
    s.add_argument("action", choices=["convert"])
    s.add_argument("file")
    s.add_argument("--out")
    s.add_argument("--page", type=int, default=0)
    s.add_argument("--hide", help="comma-separated DXF layers to hide")
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("ask", help="troubleshooting assistant")
    s.add_argument("project")
    s.add_argument("question")
    s.add_argument("--room")
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-llm", action="store_true")
    s.set_defaults(func=cmd_ask)

    s = sub.add_parser("sop-bundle", help="offline HTML bundle of the published procedures (zip or folder)")
    s.add_argument("project")
    s.add_argument("-o", "--out", help="<name>-procedures.zip by default; a path without .zip writes a folder")
    s.set_defaults(func=cmd_sop_bundle)

    s = sub.add_parser("history", help="revisions of a project")
    s.add_argument("project")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_history)

    s = sub.add_parser("restore", help="restore a revision as a new revision")
    s.add_argument("project")
    s.add_argument("revision", type=int)
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser("vocab", help="device kinds, media and disciplines")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_vocab)

    s = sub.add_parser("plugins", help="importers and plugin errors")
    s.set_defaults(func=cmd_plugins)

    s = sub.add_parser("discovery", help="network discovery helpers")
    ds = s.add_subparsers(dest="discovery_cmd", required=True)
    d = ds.add_parser("doctor", help="can this host see the AV network? capabilities, interfaces / VLANs, LLDP listen")
    d.add_argument("--seconds", type=float, default=35.0, help="how long to listen for LLDP / CDP (default 35; 0 skips the listen)")
    d.add_argument("--interface", default="", help="listen on one interface only")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_discovery_doctor)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
