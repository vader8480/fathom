"""Build driver (render → build folder + zip) and headless-Chrome PDF / PNG.

v0.2 artifacts (``index.html``, ``diagram.svg``, ``patch-sheet.csv``,
``project.json``, ``build-notes.txt``, ``<run>.zip``, optional ``report.pdf`` /
``diagram.png``) keep their names. With a v2 doc the run folder also holds the
§5.9 package: per-room maps and patch pages, device pages, schedules (CSV),
label sheet, rack and floor-plan SVGs, QR codes and ``report.html``. Pages
come from the W5 renderers and the analysis from W6 when those modules are
importable; otherwise compact built-in fallbacks are used and a build note
says so.
"""

from __future__ import annotations

import html
import inspect
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from .layout import compute_layout
from .merge import apply_imports
from .model import Project, slug as make_slug, validate
from .patch import patch_sheet_csv
from .project import display_path, load_project, new_build_dir
from .render_html import render_html
from .render_svg import render_svg

Doc = Dict[str, Any]


def find_chrome() -> Optional[str]:
    candidates = [
        os.environ.get("FATHOM_CHROME"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("chrome"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def _chrome_flags() -> list:
    flags = ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--disable-dev-shm-usage"]
    # containers usually run as root, where Chromium refuses to start without this
    if os.environ.get("FATHOM_CHROME_NO_SANDBOX") == "1" or (hasattr(os, "geteuid") and os.geteuid() == 0):
        flags.append("--no-sandbox")
    return flags


def _run_chrome(args: list, timeout: int = 120) -> subprocess.CompletedProcess:
    chrome = find_chrome()
    if not chrome:
        raise SystemExit("error: no Chrome / Chromium / Edge found (set FATHOM_CHROME=/path/to/binary), or use the page's Print / PDF button")
    return subprocess.run([chrome] + _chrome_flags() + args, capture_output=True, text=True, timeout=timeout)


def html_to_pdf(html_path: Path, pdf_path: Path) -> Path:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    res = _run_chrome(["--no-pdf-header-footer", f"--print-to-pdf={pdf_path.resolve()}", "--virtual-time-budget=4000", html_path.resolve().as_uri()])
    if res.returncode != 0 or not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        err = (res.stderr or res.stdout or "").strip().splitlines()
        raise SystemExit(f"error: PDF export failed{(': ' + err[-1]) if err else ''}")
    return pdf_path


def html_to_png(html_path: Path, png_path: Path, width: int, height: int) -> Path:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    res = _run_chrome([f"--screenshot={png_path.resolve()}", f"--window-size={int(width)},{int(height)}", "--virtual-time-budget=4000", html_path.resolve().as_uri()])
    if res.returncode != 0 or not png_path.is_file() or png_path.stat().st_size == 0:
        err = (res.stderr or res.stdout or "").strip().splitlines()
        raise SystemExit(f"error: PNG export failed{(': ' + err[-1]) if err else ''}")
    return png_path


def open_in_browser(target: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    if shutil.which(opener):
        subprocess.run([opener, str(target)], check=False)
    else:
        print(f"open manually: {target}")


# ------------------------------------------------------------------ build


def prepare(project: Project, project_dir: Path) -> Project:
    """Merge imports and check the model. Returns the same project (mutated)."""
    apply_imports(project, project_dir)
    for p in validate(project):
        project.notes.append(f"validation: {p}")
    return project


def render_project(project: Project, project_dir: Path, base_url: str = "") -> Dict[str, str]:
    """Rendered artifacts as strings (html, svg, csv) plus the page size."""
    prepare(project, project_dir)
    layout = compute_layout(project)
    return {
        "html": render_html(project, layout),
        "svg": render_svg(project, layout),
        "csv": patch_sheet_csv(project),
        "width": str(int(layout.width + 48)),
        "height": str(int(layout.height + 190)),
    }


def device_url(base_url: str, project: str, device_id: str) -> str:
    """Public device page URL encoded in QR codes (FR-EXP-04)."""
    return f"{(base_url or '').rstrip('/')}/p/{quote(project, safe='')}/d/{quote(device_id, safe='')}"


def public_base(doc: Optional[Doc], base_url: str = "") -> str:
    """``base_url`` or ``settings.public_url`` or ``FATHOM_PUBLIC_URL`` ("" when none)."""
    return (base_url or ((doc or {}).get("settings") or {}).get("public_url") or os.environ.get("FATHOM_PUBLIC_URL") or "").strip().rstrip("/")


# ---------------------------------------------------- optional modules


def _optional(module: str, name: str) -> Optional[Callable[..., Any]]:
    try:
        mod = __import__(f"fathom.{module}", fromlist=[name])
    except Exception:
        return None
    fn = getattr(mod, name, None)
    return fn if callable(fn) else None


def _call(fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    """Call with only the keyword arguments ``fn`` accepts (renderers may be older)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*args, **kw)
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kw)
    return fn(*args, **{k: v for k, v in kw.items() if k in params})


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _zip(run_dir: Path) -> Path:
    zpath = run_dir / f"{run_dir.name}.zip"
    files = sorted(p for p in run_dir.rglob("*") if p.is_file() and p != zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f"{run_dir.name}/{f.relative_to(run_dir).as_posix()}")
    return zpath


def _normalized(doc: Doc) -> Doc:
    try:
        from .schema import normalize

        return normalize(doc)
    except Exception:
        return {k: v for k, v in doc.items()}


def _flow(doc: Doc, room: str, state: str) -> Project:
    from .merge import flow_project

    return flow_project(doc, room, state=state)


def _scope(doc: Doc, rooms: Optional[List[str]]) -> Doc:
    """Doc restricted to devices in ``rooms`` (cables kept when either end stays)."""
    if not rooms:
        return doc
    keep = {d.get("id") for d in doc.get("devices") or [] if d.get("room") in rooms}
    out = dict(doc)
    out["devices"] = [d for d in doc.get("devices") or [] if d.get("id") in keep]
    out["cables"] = [c for c in doc.get("cables") or [] if (c.get("from") or {}).get("device") in keep or (c.get("to") or {}).get("device") in keep]
    out["racks"] = [r for r in doc.get("racks") or [] if r.get("room") in rooms]
    out["floorplans"] = [f for f in doc.get("floorplans") or [] if f.get("room") in rooms]
    return out


def write_build(project: Project, project_dir: Path, run_dir: Path, pdf: bool = False, png: bool = False, *, doc: Optional[Doc] = None,
                state: str = "all", rooms: Optional[List[str]] = None, base_url: str = "", discovery: bool = True) -> Dict[str, str]:
    """Render into ``run_dir`` and zip it. Returns the artifact strings (plus ``files``).

    ``discovery=False`` leaves the "Discovered connections" section (and its CSV) out of the report.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    notes: List[str] = []
    room_ids = [r.get("id") for r in (doc or {}).get("rooms") or [] if isinstance(r, dict)]
    if doc is not None:
        from .merge import default_room

        sel = [r for r in (rooms or room_ids) if r in room_ids] or room_ids[:1]
        droom = default_room(doc) if default_room(doc) in sel else (sel[0] if sel else "main")
        if state != "all" or droom != default_room(doc):
            project = _flow(doc, droom, state)
    arts = render_project(project, project_dir)
    index_html = arts["html"]
    if doc is not None:
        nav = _nav(doc, sel, droom, prefix="")
        layout = compute_layout(project)
        index_html = _call(render_html, project, layout, nav=nav, base_url="", sw=False, link_style="build")
    _write(run_dir / "index.html", index_html)
    _write(run_dir / "diagram.svg", arts["svg"])
    _write(run_dir / "patch-sheet.csv", arts["csv"])
    notes.extend(project.notes)
    if doc is not None:
        _write(run_dir / "project.json", json.dumps(_normalized(doc), indent=2, ensure_ascii=False) + "\n")
        try:
            notes.extend(_write_package(doc, project_dir, run_dir, state=state, rooms=sel, droom=droom, base_url=base_url, discovery=discovery))
        except Exception as exc:  # the v0.2 part of the build must survive
            notes.append(f"build package incomplete: {type(exc).__name__}: {exc}")
    else:
        _write(run_dir / "project.json", json.dumps(project.to_dict(), indent=2, ensure_ascii=False) + "\n")
    if pdf:
        src = run_dir / "report.html" if (run_dir / "report.html").is_file() else run_dir / "index.html"
        html_to_pdf(src, run_dir / "report.pdf")
    if png:
        html_to_png(run_dir / "index.html", run_dir / "diagram.png", int(arts["width"]), int(arts["height"]))
    if doc is not None:
        meta = doc.get("meta") or {}
        head = f"build: {meta.get('org') or project_dir.name} · state {state} · rooms {', '.join(sel)} · {len(doc.get('devices') or [])} devices, {len(doc.get('cables') or [])} cables"
        notes.insert(0, head)
    if notes:
        _write(run_dir / "build-notes.txt", "\n".join(dict.fromkeys(notes)) + "\n")
    _zip(run_dir)
    arts["files"] = "\n".join(sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file()))
    arts["notes"] = "\n".join(notes)
    return arts


def _nav(doc: Doc, sel: List[str], current: str, prefix: str) -> Dict[str, Any]:
    """Relative navigation for build pages. ``prefix`` = path from the page to the run root."""
    rooms = [r for r in doc.get("rooms") or [] if r.get("id") in sel]
    return {
        "project": (doc.get("meta") or {}).get("slug", ""),
        "rooms": [{"id": r["id"], "name": r.get("name", r["id"]), "url": f"{prefix}rooms/{r['id']}/index.html"} for r in rooms],
        "current": current,
        "links": [
            {"label": "Rooms", "url": f"{prefix}rooms/index.html"},
            {"label": "Patch table", "url": f"{prefix}rooms/{current}/patch.html"},
            {"label": "Cable labels", "url": f"{prefix}cable-labels.html"},
            {"label": "Report", "url": f"{prefix}report.html"},
        ],
    }


def _write_package(doc: Doc, project_dir: Path, run_dir: Path, *, state: str, rooms: List[str], droom: str, base_url: str, discovery: bool = True) -> List[str]:
    from . import bom as bom_mod
    from . import cables as cab_mod
    from . import network as net_mod
    from .merge import build_overlay, filter_state

    notes: List[str] = []
    name = project_dir.name
    try:
        overlay = build_overlay(doc, project_dir)
    except Exception as exc:
        overlay = {"devices": [], "routes": [], "port_labels": {}, "interfaces": {}, "dmx": {}, "detail": {}, "notes": []}
        notes.append(f"overlay failed: {type(exc).__name__}: {exc}")
    fdoc = _scope(filter_state(doc, state), rooms if set(rooms) != {r.get("id") for r in doc.get("rooms") or []} else None)
    sdoc = _scope(doc, rooms if set(rooms) != {r.get("id") for r in doc.get("rooms") or []} else None)
    room_map = {r.get("id"): r for r in doc.get("rooms") or []}

    # ---- per-room maps and patch pages
    patch_table = _optional("patch", "patch_table")
    patch_table_csv = _optional("patch", "patch_table_csv")
    render_patch_page = _optional("render_html", "render_patch_page")
    if patch_table is None or render_patch_page is None:
        notes.append("patch pages: built-in fallback (fathom.patch.patch_table / render_html.render_patch_page not available)")
    for rid in rooms:
        rdir = run_dir / "rooms" / rid
        try:
            proj = _flow(doc, rid, state)
            prepare(proj, project_dir)
            lay = compute_layout(proj)
            _write(rdir / "index.html", _call(render_html, proj, lay, nav=_nav(doc, rooms, rid, prefix="../../"), base_url="../../", sw=False, link_style="build"))
            _write(rdir / "diagram.svg", render_svg(proj, lay))
        except Exception as exc:
            notes.append(f"room {rid}: map failed: {type(exc).__name__}: {exc}")
            _write(rdir / "index.html", _page(f"{room_map.get(rid, {}).get('name', rid)}", f"<p>The map could not be rendered: {html.escape(str(exc))}</p>", "../../"))
        try:
            if patch_table is not None and render_patch_page is not None:
                blocks = _call(patch_table, fdoc, overlay, room=rid)
                page = _call(render_patch_page, fdoc, rid, blocks, project=name, base_url="../../", sw=False, link_style="build")
            else:
                page = _fallback_patch_page(fdoc, rid)
            _write(rdir / "patch.html", page)
        except Exception as exc:
            notes.append(f"room {rid}: patch page failed: {type(exc).__name__}: {exc}")
            _write(rdir / "patch.html", _fallback_patch_page(fdoc, rid))
    render_room_index = _optional("render_html", "render_room_index")
    if render_room_index is not None:
        try:
            _write(run_dir / "rooms" / "index.html", _call(render_room_index, sdoc, project=name, base_url="../", sw=False, link_style="build"))
        except Exception as exc:
            notes.append(f"room index: {type(exc).__name__}: {exc}; built-in fallback used")
            _write(run_dir / "rooms" / "index.html", _fallback_room_index(sdoc, rooms))
    else:
        notes.append("room index: built-in fallback (render_html.render_room_index not available)")
        _write(run_dir / "rooms" / "index.html", _fallback_room_index(sdoc, rooms))

    # ---- QR + device pages
    base = public_base(doc, base_url)
    qr_svgs: Dict[str, str] = {}
    devices = [d for d in sdoc.get("devices") or [] if isinstance(d, dict) and not d.get("auto")]
    if base:
        from .qr import svg as qr_svg

        for d in devices:
            try:
                qr_svgs[d["id"]] = qr_svg(device_url(base, name, d["id"]), "M", scale=4)
                _write(run_dir / "qr" / f"{d['id']}.svg", qr_svgs[d["id"]])
            except ValueError as exc:
                notes.append(f"qr {d['id']}: {exc}")
    else:
        notes.append("QR codes skipped: no public URL (set settings.public_url or FATHOM_PUBLIC_URL)")
    render_device_page = _optional("render_html", "render_device_page")
    if render_device_page is None:
        notes.append("device pages: built-in fallback (render_html.render_device_page not available)")
    for d in devices:
        try:
            if render_device_page is not None:
                page = _call(render_device_page, sdoc, d["id"], project=name, overlay=overlay, base_url="../", qr_svg=qr_svgs.get(d["id"], ""), sw=False, link_style="build")
            else:
                page = _fallback_device_page(sdoc, d, overlay, qr_svgs.get(d["id"], ""))
        except Exception as exc:
            notes.append(f"device {d['id']}: page failed ({type(exc).__name__}: {exc}); fallback used")
            page = _fallback_device_page(sdoc, d, overlay, qr_svgs.get(d["id"], ""))
        _write(run_dir / "devices" / f"{d['id']}.html", page)

    # ---- schedules
    sections: Dict[str, str] = {}
    if patch_table is not None and patch_table_csv is not None:
        try:
            _write(run_dir / "patch-table.csv", patch_table_csv(_call(patch_table, fdoc, overlay)))
        except Exception as exc:
            notes.append(f"patch-table.csv: {type(exc).__name__}: {exc}; fallback used")
            _write(run_dir / "patch-table.csv", cab_mod.to_csv(_fallback_patch_schedule(fdoc)))
    else:
        _write(run_dir / "patch-table.csv", cab_mod.to_csv(_fallback_patch_schedule(fdoc)))
    cs = cab_mod.cable_schedule(sdoc, state=state)
    _write(run_dir / "cable-schedule.csv", cab_mod.to_csv(cs))
    sections["Cable schedule"] = _html_table(cs)
    if discovery:
        try:
            from .discovery import report as disc_report

            all_rooms = set(rooms) == {r.get("id") for r in doc.get("rooms") or []}
            ds = disc_report.discovered_connections(doc, project_dir, state=state, rooms=None if all_rooms else rooms)
            notes.extend(ds.get("notes") or [])
            if ds["rows"]:
                _write(run_dir / "discovered-connections.csv", cab_mod.to_csv(ds))
                sections["Discovered connections"] = disc_report.section_intro(ds) + _html_table(ds)
        except Exception as exc:
            notes.append(f"discovered connections: {type(exc).__name__}: {exc}; section skipped")
    _write(run_dir / "cable-labels.html", cab_mod.label_sheet_html(fdoc, qr=False, base_url=base))
    ips = net_mod.ip_schedule(fdoc, overlay)
    _write(run_dir / "ip-schedule.csv", cab_mod.to_csv(ips))
    sections["IP schedule"] = _html_table(ips)
    dmx_schedule = _optional("dmx", "dmx_schedule")
    try:
        dm = dmx_schedule(fdoc, overlay) if dmx_schedule is not None else _fallback_dmx(fdoc, overlay)
    except Exception as exc:
        notes.append(f"dmx schedule: {type(exc).__name__}: {exc}; fallback used")
        dm = _fallback_dmx(fdoc, overlay)
    if dmx_schedule is None:
        notes.append("dmx-schedule.csv: built-in fallback (fathom.dmx not available)")
    _write(run_dir / "dmx-schedule.csv", cab_mod.to_csv(dm))
    sections["DMX schedule"] = _html_table(dm)
    bm = bom_mod.bom(sdoc, state=state)
    _write(run_dir / "bom.csv", cab_mod.to_csv(bm))
    totals = " · ".join(f"{v:,.2f} {k}" for k, v in sorted(bm.get("totals", {}).items()))
    sections["Bill of materials"] = _html_table(bm) + f"<p class=total>Total: {html.escape(totals)}</p>"
    inv = bom_mod.inventory_schedule(sdoc)
    _write(run_dir / "inventory.csv", cab_mod.to_csv(inv))
    sections["Inventory"] = _html_table(inv)

    # ---- racks
    rack_svg = _optional("racks", "rack_svg")
    if rack_svg is None:
        notes.append("rack SVGs: built-in fallback (fathom.racks not available)")
    rack_parts = []
    for rk in fdoc.get("racks") or []:
        for face in ("front", "rear"):
            try:
                svg = rack_svg(fdoc, rk["id"], face=face) if rack_svg is not None else _fallback_rack_svg(fdoc, rk, face)
            except Exception as exc:
                notes.append(f"rack {rk['id']} {face}: {type(exc).__name__}: {exc}; fallback used")
                svg = _fallback_rack_svg(fdoc, rk, face)
            _write(run_dir / "racks" / f"{rk['id']}-{face}.svg", svg)
            rack_parts.append(f'<figure><img src="racks/{html.escape(rk["id"])}-{face}.svg" alt="{html.escape(rk.get("name", rk["id"]))} {face}"><figcaption>{html.escape(rk.get("name", rk["id"]))} · {face}</figcaption></figure>')
    if rack_parts:
        sections["Racks"] = '<div class="grid">' + "".join(rack_parts) + "</div>"

    # ---- floor plans
    from .floorplan import plan_svg

    plan_parts = []
    for fp in sdoc.get("floorplans") or []:
        try:
            _write(run_dir / "floorplans" / f"{fp['id']}.svg", plan_svg(fdoc if fdoc.get("floorplans") else sdoc, fp["id"], project_dir))
            plan_parts.append(f'<figure><img src="floorplans/{html.escape(fp["id"])}.svg" alt="{html.escape(fp.get("name", fp["id"]))}"><figcaption>{html.escape(fp.get("name", fp["id"]))}</figcaption></figure>')
        except Exception as exc:
            notes.append(f"floor plan {fp.get('id')}: {type(exc).__name__}: {exc}")
    if plan_parts:
        sections["Floor plans"] = "".join(plan_parts)

    # ---- standard operating procedures (published pages, tree order, one per printed page)
    report_css = ""
    try:
        sop_html, sop_css_text = _sop_section(doc, project_dir, run_dir, rooms=rooms, all_rooms=set(rooms) == {r.get("id") for r in doc.get("rooms") or []})
    except Exception as exc:
        notes.append(f"procedures section: {type(exc).__name__}: {exc}")
        sop_html, sop_css_text = "", ""
    if sop_html:
        sections["Standard operating procedures"] = sop_html
        report_css = sop_css_text

    # ---- report
    maps = "".join(f'<figure class="map"><img src="rooms/{html.escape(r)}/diagram.svg" alt="{html.escape(room_map.get(r, {}).get("name", r))} signal flow"><figcaption>{html.escape(room_map.get(r, {}).get("name", r))}</figcaption></figure>' for r in rooms)
    sections = dict([("Signal flow", maps)] + list(sections.items()))
    render_report = _optional("render_html", "render_report")
    try:
        report = _call(render_report, sdoc, project=name, sections=sections, extra_css=report_css) if render_report is not None else _fallback_report(sdoc, sections)
    except Exception as exc:
        notes.append(f"report.html: {type(exc).__name__}: {exc}; fallback used")
        report = _fallback_report(sdoc, sections)
    _write(run_dir / "report.html", report)
    notes.extend(overlay.get("notes") or [])
    return notes


def _sop_section(doc: Doc, project_dir: Path, run_dir: Path, *, rooms: List[str], all_rooms: bool) -> Tuple[str, str]:
    """HTML for the "Standard operating procedures" report section plus the CSS it needs ("" when there are no pages).

    Published pages in tree order; when the build is scoped to some rooms only pages that apply to those rooms
    (or to no room at all) are included. Links point at the build's device/room pages and other included pages;
    images referenced as ``att:`` are copied to ``files/<att>/<name>`` so the package stays self-contained."""
    from .markdown import render
    from .render_html import SOP_REPORT_CSS, sop_css, sop_link_resolver, sop_tree

    from . import markdown as md_mod

    rows = sop_tree(doc)
    if not all_rooms:
        keep = set(rooms)

        def applies(p: Dict[str, Any]) -> bool:
            refs = set(p.get("rooms") or []) | set(md_mod.find_refs(str(p.get("body") or "")).get("rooms") or [])
            return not refs or bool(refs & keep)

        rows = [(p, d) for p, d in rows if applies(p)]
    if not rows:
        return "", ""
    included = {p["slug"] for p, _ in rows}
    devices = {d.get("id"): d for d in doc.get("devices") or [] if isinstance(d, dict) and not d.get("auto")}
    room_set = set(rooms)
    resolver = sop_link_resolver(
        doc,
        device=lambda i, d: f"devices/{quote(i, safe='')}.html" if (i in devices and (all_rooms or d.get("room") in room_set)) else "",
        room=lambda i, _r: f"rooms/{quote(i, safe='')}/index.html" if i in room_set else "",
        page=lambda s, _p: f"#sop-{quote(s, safe='')}" if s in included else None,
        attachment=_attachment_copier(doc, project_dir, run_dir),
    )
    rmap = {r.get("id"): str(r.get("name") or r.get("id")) for r in doc.get("rooms") or [] if isinstance(r, dict)}
    entries = []
    for p, depth in rows:
        rendered = render(str(p.get("body") or ""), resolver)
        found = md_mod.find_refs(str(p.get("body") or ""))
        applies_to = [rmap[r] for r in list(p.get("rooms") or []) + found["rooms"] if r in rmap]
        applies_to += [str(devices[d].get("name") or d) for d in list(p.get("devices") or []) + found["devices"] if d in devices]
        entries.append({"page": p, "html": rendered["html"], "depth": depth, "applies": list(dict.fromkeys(applies_to))})
    from .render_html import render_sop_report_section

    return render_sop_report_section(doc, entries), sop_css() + SOP_REPORT_CSS


def _attachment_copier(doc: Doc, project_dir: Path, run_dir: Path, prefix: str = "") -> Callable[[str, Dict[str, Any]], Optional[str]]:
    """``sop_link_resolver`` attachment callback that copies ``files/<att>/<name>`` into ``run_dir`` once and links it."""
    files_root = project_dir / "files"
    copied: Dict[str, str] = {}

    def attachment(att_id: str, att: Dict[str, Any]) -> Optional[str]:
        from .render_html import attachment_filename

        if att_id in copied:
            return prefix + copied[att_id]
        src = project_dir / str(att.get("file") or "")
        try:
            inside = src.resolve().is_relative_to(files_root.resolve())
        except OSError:
            inside = False
        if not str(att.get("file") or "").startswith("files/") or not inside or not src.is_file():
            return None
        rel = f"files/{att_id}/{attachment_filename(att)}"
        dest = run_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        copied[att_id] = rel
        return prefix + rel

    return attachment


def write_sop_bundle(project_dir: Path, doc: Doc, out_dir: Path) -> List[str]:
    """Standalone offline copy of the published procedures (§5.16): ``index.html``, ``pages/<slug>.html`` and the
    images they embed under ``files/``. Pages are the same phone-first renderers as ``/p/<n>/sop``, with CSS and JS
    inlined so the folder works from ``file://`` or any static host: navigation, TOC, tap-to-zoom and sessionStorage
    checklists need no server. Device and room chips are plain text; "Report a problem" falls back to e-mail when
    ``settings.problem_email`` is set. Returns the files written (relative, sorted)."""
    import datetime

    from .render_html import render_sop_index, render_sop_page, sop_link_resolver, sop_tree
    from .server import _page_payload

    pub = dict(doc)
    pub["pages"] = [p for p in doc.get("pages") or [] if isinstance(p, dict) and p.get("id") and p.get("slug")
                    and (p.get("status") or "published") == "published"]
    project = project_dir.name
    rows = sop_tree(pub)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    note = f"Offline copy from {stamp}. It may be out of date; the live procedures are the reference."
    email = str((doc.get("settings") or {}).get("problem_email") or "")
    report = {"action": "", "email": email} if email else None
    page_href = lambda s: f"{quote(s, safe='')}.html"  # noqa: E731
    resolver = sop_link_resolver(
        pub,
        device=lambda _i, _d: "",
        room=lambda _i, _r: "",
        page=lambda s, p: page_href(s) if (p.get("status") or "published") == "published" else None,
        attachment=_attachment_copier(pub, project_dir, out_dir, prefix="../"),
    )
    _write(out_dir / "index.html", render_sop_index(pub, project=project, sop_only=True, offline_note=note,
                                                    page_href=lambda s: f"pages/{quote(s, safe='')}.html"))
    for p, _depth in rows:
        data = _page_payload(project, pub, p, 0, resolver=resolver)
        _write(out_dir / "pages" / f"{p['slug']}.html",
               render_sop_page(pub, data, project=project, sop_only=True, page_href=page_href, index_href="../index.html",
                               report=report, offline_note=note))
    return sorted(f.relative_to(out_dir).as_posix() for f in out_dir.rglob("*") if f.is_file())


def sop_bundle_zip(project_dir: Path, doc: Doc) -> bytes:
    """:func:`write_sop_bundle` as a zip (entries under ``<project>-procedures/``)."""
    import io
    import tempfile

    with tempfile.TemporaryDirectory(prefix="fathom-sop-") as tmp:
        root = Path(tmp) / f"{project_dir.name}-procedures"
        files = write_sop_bundle(project_dir, doc, root)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in files:
                zf.write(root / rel, arcname=f"{root.name}/{rel}")
        return buf.getvalue()


def build(target: str, slug: str = "", run_dir: Optional[Path] = None, pdf: bool = False, png: bool = False, open_after: bool = False, quiet: bool = False) -> Path:
    project, project_dir = load_project(target)
    doc = _try_load_doc(target)
    if doc is not None:
        meta = doc.get("meta") or {}
        if not project.meta.slug and meta.get("slug"):
            project.meta.slug = meta["slug"]
    slug_ = make_slug(slug or project.meta.slug or f"{project.meta.org or project_dir.name}-signal-flow")
    run_dir = run_dir or new_build_dir(project_dir.name, slug_)
    if doc is not None:
        from .merge import default_room

        project = _flow(doc, default_room(doc), "all")
    write_build(project, project_dir, run_dir, pdf=pdf, png=png, doc=doc, base_url=public_base(doc))
    if not quiet:
        print(f"ok: wrote {display_path(run_dir / 'index.html')} ({len(project.nodes)} cards, {len(project.links)} links, {len(project.patch_rows)} patch rows)")
        notes_file = run_dir / "build-notes.txt"
        for n in (notes_file.read_text(encoding="utf-8").splitlines() if notes_file.is_file() else []):
            print(f"  note: {n}")
        if pdf:
            print(f"ok: wrote {display_path(run_dir / 'report.pdf')}")
        if png:
            print(f"ok: wrote {display_path(run_dir / 'diagram.png')}")
    if open_after:
        open_in_browser(run_dir / "index.html")
    return run_dir


def _try_load_doc(target: str) -> Optional[Doc]:
    """The project as a v2 doc (migrating v1 when ``fathom.schema`` is there), else None."""
    try:
        from .project import load_doc

        return load_doc(target)[0]
    except SystemExit:
        raise
    except Exception:
        pass
    try:
        from .merge import doc_version, load_any
        from .project import load_dict, resolve_project

        d = load_dict(resolve_project(target))
        if doc_version(d) == 2:
            return d
        return load_any(d)
    except Exception:
        return None


def build_doc(name_or_dir: str, *, state: str = "all", rooms: Optional[List[str]] = None, pdf: bool = False, png: bool = False,
              base_url: str = "", run_dir: Optional[Path] = None, discovery: bool = True) -> Path:
    """Build a project's full package from its v2 doc. Returns the run folder."""
    from .merge import default_room
    from .project import resolve_project

    doc = _try_load_doc(name_or_dir)
    if doc is None:
        raise SystemExit(f"error: could not load {name_or_dir} as a v2 document")
    project_dir = resolve_project(name_or_dir).parent
    slug_ = make_slug((doc.get("meta") or {}).get("slug") or project_dir.name)
    run_dir = run_dir or new_build_dir(project_dir.name, slug_)
    project = _flow(doc, default_room(doc), state)
    write_build(project, project_dir, run_dir, pdf=pdf, png=png, doc=doc, state=state, rooms=rooms, base_url=public_base(doc, base_url), discovery=discovery)
    return run_dir


# ======================================================= fallback pages

_CSS = """
:root{color-scheme:light dark;--bg:#0f1420;--fg:#e8ecf3;--mut:#9aa3b5;--line:#273044;--card:#161d2c}
@media (prefers-color-scheme: light){:root{--bg:#f7f8fb;--fg:#141a26;--mut:#5b6476;--line:#d9dee8;--card:#fff}}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:1100px;margin:0 auto;padding:20px}a{color:#4ea8ff}h1{font-size:22px;margin:.2em 0}h2{font-size:16px;margin:1.4em 0 .4em}
.mut{color:var(--mut)}table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
th{font-weight:600;color:var(--mut)}.pill{display:inline-block;border-radius:9px;padding:0 7px;font-size:11px;font-weight:700;color:#0b0f17;text-transform:uppercase}
.grid{display:flex;flex-wrap:wrap;gap:16px}figure{margin:0 0 16px}figure img{max-width:100%;background:#fff;border:1px solid var(--line)}
nav.top{display:flex;gap:14px;flex-wrap:wrap;padding:8px 20px;border-bottom:1px solid var(--line);background:var(--card)}
.qr svg{width:160px;height:160px}@media print{nav.top{display:none}main{max-width:none}}
"""


def _page(title: str, body: str, prefix: str, nav: str = "") -> str:
    nav = nav or f'<nav class="top"><a href="{prefix}index.html">Map</a><a href="{prefix}rooms/index.html">Rooms</a><a href="{prefix}report.html">Report</a></nav>'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>{nav}<main>{body}</main></body></html>")


def _html_table(sched: Dict[str, Any], limit: int = 2000) -> str:
    cols = sched.get("columns") or []
    rows = (sched.get("rows") or [])[:limit]
    if not rows:
        return '<p class="mut">Nothing to list.</p>'
    head = "".join(f"<th>{html.escape(str(c['label']))}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{html.escape('' if r.get(c['key']) is None else str(r.get(c['key'])))}</td>" for c in cols) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _disc_pill(disc: str) -> str:
    from .vocab import DISCIPLINES

    d = DISCIPLINES.get(disc) or DISCIPLINES["other"]
    return f'<span class="pill" style="background:{d["color"]}">{html.escape(d["label"])}</span>'


def _fallback_room_index(doc: Doc, rooms: List[str]) -> str:
    from .vocab import kind_discipline

    items = []
    for r in doc.get("rooms") or []:
        if r.get("id") not in rooms:
            continue
        devs = [d for d in doc.get("devices") or [] if d.get("room") == r["id"]]
        discs = sorted({d.get("discipline") or kind_discipline(d.get("kind", "")) for d in devs})
        items.append(f'<li><a href="{html.escape(r["id"])}/index.html">{html.escape(r.get("name", r["id"]))}</a> '
                     f'<span class="mut">{len(devs)} devices</span> {"".join(_disc_pill(x) for x in discs)} · <a href="{html.escape(r["id"])}/patch.html">patch table</a></li>')
    meta = doc.get("meta") or {}
    return _page(f"{meta.get('org', '')} · rooms", f"<h1>{html.escape(meta.get('org', 'Rooms'))}</h1><ul>{''.join(items)}</ul>", "../")


def _ports_of(dev: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {p.get("id"): p for p in dev.get("ports") or []}


def _fallback_patch_schedule(doc: Doc, room: str = "*") -> Dict[str, Any]:
    devs = {d.get("id"): d for d in doc.get("devices") or []}
    rooms = {r.get("id"): r.get("name", r.get("id")) for r in doc.get("rooms") or []}
    by_port: Dict[Tuple[str, str], List[Tuple[Dict[str, Any], str, str]]] = {}
    for c in doc.get("cables") or []:
        a, b = c.get("from") or {}, c.get("to") or {}
        by_port.setdefault((a.get("device"), a.get("port", "")), []).append((c, b.get("device"), b.get("port", "")))
        by_port.setdefault((b.get("device"), b.get("port", "")), []).append((c, a.get("device"), a.get("port", "")))
    rows = []
    for d in doc.get("devices") or []:
        if room != "*" and d.get("room") != room:
            continue
        for p in d.get("ports") or []:
            links = by_port.get((d["id"], p.get("id"))) or [(None, "", "")]
            for c, peer, pport in links:
                pd = devs.get(peer) or {}
                pp = _ports_of(pd).get(pport) or {}
                rows.append({
                    "room": rooms.get(d.get("room"), d.get("room", "")), "device": d.get("name", d["id"]), "device_id": d["id"],
                    "section": p.get("group", ""), "dir": p.get("dir", ""), "port": p.get("label") or p.get("name", p.get("id")), "port_id": p.get("id"),
                    "label": p.get("label", ""), "peer_device": pd.get("name", peer or ""), "peer_port": pp.get("label") or pp.get("name", pport or ""),
                    "cable_tag": (c or {}).get("tag", ""), "medium": p.get("medium", ""), "source": "doc",
                })
    cols = [("room", "Room"), ("device", "Device"), ("section", "Section"), ("dir", "Dir"), ("port", "Port"), ("label", "Label"),
            ("peer_device", "Peer device"), ("peer_port", "Peer port"), ("cable_tag", "Cable"), ("medium", "Medium"), ("source", "Source")]
    return {"kind": "patch", "columns": [{"key": k, "label": lab} for k, lab in cols], "rows": rows}


def _fallback_patch_page(doc: Doc, room: str) -> str:
    rname = next((r.get("name", room) for r in doc.get("rooms") or [] if r.get("id") == room), room)
    sched = _fallback_patch_schedule(doc, room)
    sched["rows"] = [r for r in sched["rows"] if r["peer_device"] or r["label"]]
    return _page(f"{rname} · patch table", f"<h1>{html.escape(rname)} · patch table</h1>{_html_table(sched)}", "../../")


def _fallback_device_page(doc: Doc, dev: Dict[str, Any], overlay: Optional[Dict[str, Any]], qr: str) -> str:
    from .vocab import KINDS, kind_discipline

    rooms = {r.get("id"): r.get("name", r.get("id")) for r in doc.get("rooms") or []}
    disc = dev.get("discipline") or kind_discipline(dev.get("kind", ""))
    sched = _fallback_patch_schedule({"devices": doc.get("devices"), "cables": doc.get("cables"), "rooms": doc.get("rooms")}, "*")
    rows = [r for r in sched["rows"] if r["device_id"] == dev["id"]]
    sched["rows"] = rows
    labels = ((overlay or {}).get("port_labels") or {}).get(dev["id"]) or {}
    for r in rows:
        if not r["label"] and labels.get(r["port_id"]):
            r["label"] = labels[r["port_id"]] + " (import)"
    model = " ".join(x for x in (dev.get("manufacturer", ""), dev.get("model", "")) if x)
    info = [("Kind", (KINDS.get(dev.get("kind", "")) or {}).get("label", dev.get("kind", ""))), ("Model", model), ("Room", rooms.get(dev.get("room"), dev.get("room") or "shared inventory")),
            ("Status", dev.get("status", "installed")), ("Location", dev.get("location", ""))]
    inv = dev.get("inventory") or {}
    info += [(k.replace("_", " ").title(), str(v)) for k, v in inv.items() if v not in ("", None)]
    ifs = list(dev.get("interfaces") or []) + list(((overlay or {}).get("interfaces") or {}).get(dev["id"]) or [])
    info += [(f"IP {i.get('id', '')}", f"{i.get('ip', '')} {('(' + i['source'] + ')') if i.get('source') else ''}") for i in ifs if i.get("ip")]
    dl = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in info if v)
    room_link = f'<a href="../rooms/{html.escape(dev.get("room", ""))}/index.html">{html.escape(rooms.get(dev.get("room"), ""))} map</a>' if dev.get("room") else ""
    body = (f"<p>{_disc_pill(disc)} {room_link}</p><h1>{html.escape(dev.get('name', dev['id']))}</h1>"
            f"<table>{dl}</table>{'<div class=qr>' + qr + '</div>' if qr else ''}<h2>Ports</h2>{_html_table(sched)}")
    return _page(dev.get("name", dev["id"]), body, "../")


def _fallback_dmx(doc: Doc, overlay: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rooms = {r.get("id"): r.get("name", r.get("id")) for r in doc.get("rooms") or []}
    devs = {d.get("id"): d for d in list(doc.get("devices") or []) + list((overlay or {}).get("devices") or [])}
    rows = []
    seen = set()
    for d in doc.get("devices") or []:
        dm = d.get("dmx") or {}
        if dm.get("universe") and dm.get("address"):
            seen.add(d["id"])
            rows.append((d, dm, "manual"))
    for did, dm in sorted(((overlay or {}).get("dmx") or {}).items()):
        if did not in seen and did in devs:
            rows.append((devs[did], dm, dm.get("source", "import")))
    out = []
    for d, dm, src in rows:
        u, a, fp = int(dm.get("universe") or 0), int(dm.get("address") or 0), int(dm.get("footprint") or 1)
        out.append({"universe": u, "address": a, "end": a + fp - 1, "footprint": dm.get("footprint", ""), "device": d.get("name", d.get("id")), "device_id": d.get("id"),
                    "room": rooms.get(d.get("room"), d.get("room", "")), "mode": dm.get("mode", ""), "channel": dm.get("channel", ""), "protocol": dm.get("protocol", ""),
                    "sacn_group": f"239.255.{u >> 8}.{u & 255}", "artnet": f"{(u - 1) >> 8}:{((u - 1) >> 4) & 15}:{(u - 1) & 15}", "source": src})
    out.sort(key=lambda r: (r["universe"], r["address"], str(r["device"])))
    cols = [("universe", "Universe"), ("address", "Address"), ("end", "End"), ("footprint", "Footprint"), ("device", "Device"), ("room", "Room"), ("mode", "Mode"),
            ("channel", "Console channel"), ("protocol", "Protocol"), ("sacn_group", "sACN group"), ("artnet", "Art-Net (net:sub:uni)"), ("source", "Source")]
    return {"kind": "dmx", "columns": [{"key": k, "label": lab} for k, lab in cols], "rows": out, "problems": []}


def _fallback_rack_svg(doc: Doc, rack: Dict[str, Any], face: str) -> str:
    from .vocab import DISCIPLINES, kind_discipline

    units = int(rack.get("units") or 1)
    U, W, X = 22, 300, 30
    h = units * U + 50
    top_down = rack.get("numbering") == "top_down"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W + 2 * X}" height="{h}" viewBox="0 0 {W + 2 * X} {h}" font-family="Helvetica, Arial, sans-serif" data-rack="{html.escape(rack["id"])}" data-face="{face}">',
             f'<rect width="{W + 2 * X}" height="{h}" fill="#ffffff"/><text x="{X}" y="18" font-size="13" font-weight="bold">{html.escape(rack.get("name", rack["id"]))} · {face}</text>',
             f'<rect x="{X}" y="30" width="{W}" height="{units * U}" fill="#f1f3f7" stroke="#333"/>']
    for u in range(1, units + 1):
        y = 30 + (units - u) * U
        num = units - u + 1 if top_down else u
        parts.append(f'<text x="{X - 6}" y="{y + 15}" font-size="10" text-anchor="end" fill="#666">{num}</text><line x1="{X}" y1="{y}" x2="{X + W}" y2="{y}" stroke="#ddd"/>')
    for d in doc.get("devices") or []:
        rk = d.get("rack") or {}
        if rk.get("id") != rack["id"] or not rk.get("u"):
            continue
        full_depth = (rk.get("depth") or "full") == "full"
        if (rk.get("face") or "front") != face and not full_depth:
            continue
        height = int(rk.get("height") or 1)
        u = int(rk["u"])
        y = 30 + (units - (u + height - 1)) * U
        side = rk.get("side") or "full"
        x, w = (X, W) if side == "full" else ((X, W / 2) if side == "left" else (X + W / 2, W / 2))
        color = (DISCIPLINES.get(d.get("discipline") or kind_discipline(d.get("kind", ""))) or DISCIPLINES["other"])["color"]
        ghost = ' opacity="0.45"' if (rk.get("face") or "front") != face else ""
        parts.append(f'<g data-device="{html.escape(d["id"])}"{ghost}><rect x="{x + 1}" y="{y + 1}" width="{w - 2}" height="{height * U - 2}" fill="#fff" stroke="#333"/>'
                     f'<rect x="{x + 1}" y="{y + 1}" width="6" height="{height * U - 2}" fill="{color}"/>'
                     f'<text x="{x + 12}" y="{y + 15}" font-size="11">{html.escape(d.get("name", d["id"]))} <tspan fill="#666">{height}U</tspan></text></g>')
    parts.append("</svg>")
    return "".join(parts)


def _fallback_report(doc: Doc, sections: Dict[str, str]) -> str:
    meta = doc.get("meta") or {}
    toc = "".join(f'<li><a href="#s{i}">{html.escape(k)}</a></li>' for i, k in enumerate(sections))
    body = "".join(f'<section id="s{i}" style="break-before:page"><h2>{html.escape(k)}</h2>{v}</section>' for i, (k, v) in enumerate(sections.items()))
    title = f"{meta.get('org', '')} · {meta.get('title', 'Documentation')}"
    return _page(title, f"<h1>{html.escape(title)}</h1><p class=mut>{html.escape(meta.get('description', ''))}</p><ol>{toc}</ol>{body}", "")


__all__ = [
    "find_chrome", "html_to_pdf", "html_to_png", "open_in_browser", "prepare", "render_project", "write_build", "build", "build_doc",
    "device_url", "public_base",
]
