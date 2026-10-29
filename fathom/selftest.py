"""`fathom selftest`: parse the bundled samples, build, and sanity-check the output."""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from .export import build
from .layout import compute_layout
from .merge import apply_imports
from .model import project_from_dict
from .parsers import detect_kind, parse_dante, parse_waves, parse_yamaha
from .parsers.yamaha import parse_port
from .project import SAMPLES_DIR, STATIC_DIR, blank_project_dict, load_project
from .render_html import render_html
from .trace import find_paths, resolve_node

# Appendix C reference vectors (qr.encode(text, "M", mask=2), 1 = dark, no quiet zone)
QR_C1 = (
    "111111100010001111111 100000100110001000001 101110101111001011101 101110101111101011101 101110101111101011101 "
    "100000101010101000001 111111101010101111111 000000001111100000000 101111100010101111100 101000011110100100100 "
    "111110110001010011110 011101000110000111101 010001100001010011110 000000001111111101100 111111100110101100110 "
    "100000101011111001101 101110101110100010110 101110101100100100000 101110101101010000100 100000100110000011100 "
    "111111101101010010110"
)
QR_C2 = (
    "11111110011010100111001111111 10000010001111011100101000001 10111010110110000000101011101 10111010111111011100001011101 "
    "10111010111010100001101011101 10000010101001011010001000001 11111110101010101010101111111 00000000101000001010100000000 "
    "10111110010111000111001111100 00010100010110101111111110001 01111111000100111100001010000 11111000110110010000001001010 "
    "11010110100010000100100001100 00010100011001001011111110001 11010111010011110000101011100 00010101011101000010100110010 "
    "10000110110010111101010101100 11011101011100001011111110101 10110010011110011000101110100 10010101100010101000011010010 "
    "10110110011010000100111110111 00000000111101100110100011111 11111110000111110001101011100 10000010100101011001100010001 "
    "10111010101000110100111110100 10111010110000001110000001111 10111010101111111100111111110 10000010001111001001100001010 "
    "11111110111110100111000110100"
)

PACKAGE_FILES = (
    "index.html", "diagram.svg", "patch-sheet.csv", "project.json", "rooms/index.html", "patch-table.csv", "cable-schedule.csv",
    "cable-labels.html", "ip-schedule.csv", "dmx-schedule.csv", "bom.csv", "inventory.csv", "report.html",
)


def run_selftest() -> int:
    fails: List[str] = []

    def check(cond: bool, msg: str) -> None:
        print(("ok:   " if cond else "FAIL: ") + msg)
        if not cond:
            fails.append(msg)

    def skip(msg: str) -> None:
        print("skip: " + msg)

    sample = SAMPLES_DIR / "rrc-littleton"
    ex = sample / "exports"

    # ---- parsers on the bundled exports
    y = parse_yamaha(ex / "cl5")
    check(y.model == "CL5", f"yamaha: model detected ({y.model or 'none'})")
    check(len(y.named_inputs) >= 50, f"yamaha: {len(y.named_inputs)} named inputs")
    check(sum(1 for c in y.inputs if c.patch and c.patch.bus == "DANTE") >= 50, "yamaha: Dante input patches read")
    check(len(y.output_patches) >= 40, f"yamaha: {len(y.output_patches)} output patches")
    check("unknown" not in y.files_by_role, f"yamaha: every CSV classified ({y.files_by_role})")

    d = parse_dante(ex / "dante" / "rrc-littleton-preset.xml")
    check(len(d.devices) == 33, f"dante: {len(d.devices)} devices")
    check(len(d.subscriptions()) > 200, f"dante: {len(d.subscriptions())} subscriptions")
    check(not d.summary()["unresolved_tx"], "dante: every subscription resolves to a device")

    w_csv = parse_waves(ex / "waves" / "superrack-racks.csv")
    w_xml = parse_waves(ex / "waves" / "superrack-session.xml")
    check(len(w_csv.racks) == 18, f"waves csv: {len(w_csv.racks)} racks")
    check(len(w_xml.racks) == 18 and w_xml.racks[0].plugins, f"waves xml: {len(w_xml.racks)} racks, first chain {w_xml.racks[0].chain()!r}")
    check(detect_kind(ex / "cl5") == "yamaha" and detect_kind(ex / "dante" / "rrc-littleton-preset.xml") == "dante" and detect_kind(ex / "waves" / "superrack-racks.csv") == "waves", "auto-detect picks the right parser for each sample")

    # ---- notation variants
    check(parse_port("DNT 12").text == "DANTE 12" and parse_port("SL1 3").text == "SLOT1 3" and parse_port("MX 4").text == "MIX 4" and parse_port("Mix Channel 7").text == "MIX 7", "yamaha: Short format and synonyms normalise")

    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        # Dante Receive-tab paste
        tsv = tmpd / "FOH-CL5.txt"
        tsv.write_text("Channel\tConnected To\tSignal\tStatus\n01\tKick In@1073OPX-1\t-\tok\n02\tKick Out@1073OPX-1\t-\tok\n03\t\t\t\n", encoding="utf-8")
        t = parse_dante(tsv)
        check(len(t.subscriptions()) == 2 and "FOH-CL5" in t.devices, "dante: Receive-tab table paste parsed")
        # Yamaha hand-made CSV with a header row
        hand = tmpd / "channels.csv"
        hand.write_text("Channel,Name,Color,Icon,Patch\nCH 1,Kick,Red,Kick,Dante 1\nCH 2,Snare,Red,Snare,Omni 2\n", encoding="utf-8")
        hy = parse_yamaha(hand)
        check(len(hy.named_inputs) == 2 and hy.inputs[1].patch is not None and hy.inputs[1].patch.bus == "OMNI", "yamaha: single hand-made CSV with header")

        # ---- build the sample into a temp folder
        run_dir = tmpd / "run"
        build(str(sample), run_dir=run_dir, quiet=True)
        html = (run_dir / "index.html").read_text(encoding="utf-8")
        check((run_dir / "index.html").is_file() and (run_dir / "diagram.svg").is_file() and (run_dir / "patch-sheet.csv").is_file(), "build: index.html, diagram.svg, patch-sheet.csv written")
        n_cards = html.count('class="card')
        check(n_cards >= 50, f"build: {n_cards} cards in the page")
        check("SF_DATA" in html and "Patch sheet" in html, "build: tracer data and patch sheet embedded")
        try:
            ET.fromstring((run_dir / "diagram.svg").read_text(encoding="utf-8"))
            check(True, "build: diagram.svg is well-formed XML")
        except ET.ParseError as exc:
            check(False, f"build: diagram.svg parse error {exc}")
        rows = list(csv.reader(io.StringIO((run_dir / "patch-sheet.csv").read_text(encoding="utf-8"))))
        check(len(rows) > 300, f"build: patch sheet has {len(rows) - 1} rows")

        # ---- layout sanity: no overlapping cards in a group, every link resolves
        project, pdir = load_project(str(sample))
        apply_imports(project, pdir)
        layout = compute_layout(project)
        overlaps = 0
        cards = list(layout.cards.values())
        for i, a in enumerate(cards):
            for b in cards[i + 1 :]:
                if a.box.x < b.box.right and b.box.x < a.box.right and a.box.y < b.box.bottom and b.box.y < a.box.bottom:
                    overlaps += 1
        check(overlaps == 0, f"layout: {overlaps} overlapping cards")
        check(len(layout.links) == len(project.links), "layout: every link routed")
        check(all(st.node_id in layout.cards for st in layout.stubs), "layout: Dante stubs belong to cards")
        drums = resolve_node(project, "drums")
        mains = resolve_node(project, "mains")
        paths = find_paths(project, drums.id, mains.id) if drums and mains else []
        check(bool(paths), f"trace: drums → mains found {len(paths)} path(s)")
        check(not any(n.startswith("validation:") for n in project.notes), "merge: sample project validates clean")

        # ---- blank project renders
        blank = project_from_dict(blank_project_dict("Test"))
        blank_html = render_html(blank, compute_layout(blank))
        check("<html" in blank_html, "blank project renders")

        # ================================================ 0.3 checks
        _check_v2(check, skip, sample, tmpd)

    # ================================================ racks (Rackula features)
    try:
        _check_racks(check, skip)
    except Exception as exc:
        check(False, f"racks: checks crashed ({type(exc).__name__}: {exc})")

    if fails:
        print(f"error: {len(fails)} selftest check(s) failed")
        return 1
    print("ok: fathom selftest passed")
    return 0


def _check_v2(check, skip, sample: Path, tmpd: Path) -> None:
    from . import cables, library, qr, vocab
    from .floorplan import convert, drawio_to_svg
    from .merge import build_overlay
    from .plugins import get_importer, importers

    # ---- vocabulary
    check(len(vocab.KINDS) == 35 and len(vocab.MEDIA) == 41 and len(vocab.DISCIPLINES) == 7, "vocab: 35 kinds, 41 media, 7 disciplines")
    json.dumps(vocab.as_dict())

    # ---- RRC migration identity
    try:
        from .schema import flow_project, migrate, validate_doc
        from .project import load_dict
    except Exception as exc:
        skip(f"RRC migration identity (fathom.schema not importable: {exc})")
    else:
        v1 = load_dict(sample / "project.json")
        doc = migrate(json.loads(json.dumps(v1)))
        errs = [p for p in validate_doc(doc) if p.get("level") == "error"]
        check(not errs, f"migrate: RRC migrates with {len(errs)} errors")
        p1, p2 = project_from_dict(v1), flow_project(doc)
        apply_imports(p1, sample)
        apply_imports(p2, sample)
        l1, l2 = compute_layout(p1), compute_layout(p2)

        def boxes(lay):
            return {k: tuple(round(v, 2) for v in (c.box.x, c.box.y, c.box.w, c.box.h)) for k, c in lay.cards.items()}

        check(boxes(l1) == boxes(l2) and len(l1.links) == len(l2.links), f"migrate: RRC layout identical ({len(l1.cards)} cards, {len(l1.links)} links)")
        try:
            ov = build_overlay(doc, sample)
            n = sum(1 for r in ov["routes"] if r.get("kind") == "dante")
            check(n > 200, f"overlay: RRC has {n} Dante routes")
        except Exception as exc:
            check(False, f"overlay: RRC failed ({exc})")

    # ---- per-room maps: preset devices of other rooms are not drawn as standalone cards (FR-MAP-01)
    try:
        from .merge import flow_project as room_project

        cdoc = json.loads((SAMPLES_DIR / "campus-demo" / "project.json").read_text(encoding="utf-8"))
        where = {d["id"]: d.get("room", "") for d in cdoc["devices"]}
        foreign = []
        for room in cdoc["rooms"]:
            rp = room_project(cdoc, room["id"])
            apply_imports(rp, SAMPLES_DIR / "campus-demo")
            foreign += [n.label for n in rp.nodes if where.get(rp.canon_id(n.id), room["id"]) != room["id"] and n.group not in ("ext-left", "ext-right")]
        check(not foreign, f"maps: no cards of other rooms on a room map{(' (' + ', '.join(foreign) + ')') if foreign else ''}")
    except Exception as exc:
        check(False, f"maps: per-room check failed ({type(exc).__name__}: {exc})")

    # ---- importers & samples
    kinds = [i.kind for i in importers()]
    check(all(k in kinds for k in ("yamaha", "dante", "waves", "eos", "videohub", "csv")), f"plugins: importers registered ({', '.join(kinds)})")
    campus = SAMPLES_DIR / "campus-demo"
    cx = campus / "exports"
    eos = get_importer("eos")
    r = eos.parse(cx / "eos" / "main-patch.csv")
    check(len(r.fixtures) == 22 and r.fixtures[4]["address"] == 101, f"eos csv: {len(r.fixtures)} fixtures")
    ra = eos.parse(cx / "eos" / "chapel.asc")
    got = {f["channel"]: (f["universe"], f["address"]) for f in ra.fixtures}
    check(got.get("5") == (1, 8) and got.get("2") == (1, 9) and "0" not in got and "99" not in got, f"usitt ascii: patch triplets ({len(ra.fixtures)} channels)")
    rl = eos.parse(cx / "eos" / "lightwright.txt")
    check(len(rl.fixtures) == 4 and rl.fixtures[0].get("position") == "FOH Truss", "lightwright: position / unit / purpose read")
    vh = get_importer("videohub").parse(cx / "videohub" / "broadcast-router.txt")
    labels = len(vh.input_labels) + len(vh.output_labels)
    check(labels == 40 and len(vh.routing) == 20, f"videohub: {labels} labels, {len(vh.routing)} routes")
    info = parse_dante(cx / "dante" / "device-info.txt")
    check(info.devices["RIO-SL"].primary_ip == "10.20.0.21" and info.devices["RIO-SL"].secondary_ip == "10.21.0.21", "dante: Device Info primary / secondary addresses")

    # ---- library
    lib = library.load_library(refresh=True)
    bad = [tid for tid, t in lib.items() if library.validate_template(t)]
    check(len(lib) >= 48 and not bad, f"library: {len(lib)} templates, {len(bad)} invalid")
    check([t["id"] for t in library.list_templates("rio")] == ["yamaha-rio1608-d", "yamaha-rio1608-d2", "yamaha-rio3224-d", "yamaha-rio3224-d2"],
          "library: search 'rio'")

    # ---- QR
    m1 = qr.matrix_text(qr.encode("FATHOM", "M", mask=2)).split()
    m2 = qr.matrix_text(qr.encode("https://fathom.example/p/demo/d/rio3224", "M", mask=2)).split()
    check(m1 == QR_C1.split() and m2 == QR_C2.split(), "qr: Appendix C vectors match bit for bit")
    check(len(qr.encode("A" * 100, "M")) == 41, "qr: 100 bytes at M → version 6")

    # ---- floor plans
    fx = drawio_to_svg((SAMPLES_DIR / "floorplans" / "fixture-compressed.drawio").read_text(encoding="utf-8"))
    svg = fx.data.decode("utf-8")
    root = ET.fromstring(svg)
    tags = [e.tag.rsplit("}", 1)[-1] for e in root.iter()]
    check(tags.count("rect") == 1 and tags.count("ellipse") == 1 and "240 300" in svg and "stroke-dasharray" in svg and "FOH booth" in svg, "drawio: compressed fixture → rect, ellipse, dashed edge, labels")
    dx = convert(SAMPLES_DIR / "floorplans" / "main-floor.dxf")
    names = [(L["name"], L["visible"]) for L in dx.layers]
    seats = dx.data.decode("utf-8").split('data-layer="SEATS"')[1].split("</g>")[0].count("<circle")
    check(dx.image_kind == "svg" and dx.width == 2080 and ("GRID", False) in names and ("HIDDEN", False) in names and seats == 160 and dx.units == {"insunits": 6, "meters_per_unit": 1.0},
          f"dxf: main-floor.dxf → {int(dx.width)}×{int(dx.height)}, {len(names)} layers, {seats} seats")

    # ---- fixture: tags, BOM
    fixture = STATIC_DIR / "dev" / "fixture-v2.json"
    if fixture.is_file():
        fdoc = json.loads(fixture.read_text(encoding="utf-8"))
        tags_ = {o["id"]: o["value"]["tag"] for o in cables.assign_tags_ops(fdoc)}
        check(tags_.get("c-0001") == "A-006" and tags_.get("c-0011") == "A-011" and tags_.get("c-0014") == "V-003" and tags_.get("c-0015") == "X-001", "cables: tag preview on the fixture")
        from .bom import bom

        check(bom(fdoc)["totals"] == {"USD": 6498.0}, "bom: fixture total 6498.00 USD")
        try:
            from .assistant import answer
        except Exception as exc:
            skip(f"assistant answer ({exc})")
        else:
            a = answer(fdoc, "House sound is fine, but the livestream has no audio.", use_llm=False)
            check(a.get("confidence") == "high" and len(a.get("checks") or []) >= 3, f"assistant: fixture answer ({a.get('confidence')}, {len(a.get('checks') or [])} checks)")
    else:
        skip("fixture checks (static/dev/fixture-v2.json missing)")

    # ---- campus-demo build: every §5.9 file
    try:
        from .export import build_doc
        from .project import load_doc  # noqa: F401
    except Exception as exc:
        skip(f"campus-demo build ({exc})")
        return
    run = tmpd / "campus-run"
    old = os.environ.get("FATHOM_PUBLIC_URL")
    try:
        os.environ["FATHOM_PUBLIC_URL"] = "http://localhost:8080"
        build_doc(str(campus), run_dir=run)
    finally:
        if old is None:
            os.environ.pop("FATHOM_PUBLIC_URL", None)
        else:
            os.environ["FATHOM_PUBLIC_URL"] = old
    missing = [f for f in PACKAGE_FILES if not (run / f).is_file()]
    for rid in ("main", "chapel", "broadcast"):
        missing += [f"rooms/{rid}/{f}" for f in ("index.html", "diagram.svg", "patch.html") if not (run / "rooms" / rid / f).is_file()]
    missing += [f for f in ("racks/rk-foh-front.svg", "racks/rk-foh-rear.svg", "racks/rk-foh.svg", "racks/rk-foh.html", "floorplans/fp-main-floor.svg", "devices/foh-cl5.html", "qr/foh-cl5.svg", f"{run.name}.zip") if not (run / f).is_file()]
    check(not missing, f"campus-demo build: §5.9 package complete{(' (missing ' + ', '.join(missing) + ')') if missing else ''}")
    if (run / "floorplans" / "fp-main-floor.svg").is_file():
        plan = (run / "floorplans" / "fp-main-floor.svg").read_text(encoding="utf-8")
        check(plan.count("data-device=") >= 20, f"campus-demo build: floor plan markers ({plan.count('data-device=')})")
    if (run / "qr" / "foh-cl5.svg").is_file():
        ET.fromstring((run / "qr" / "foh-cl5.svg").read_text(encoding="utf-8"))
    hdr = (run / "cable-schedule.csv").read_text(encoding="utf-8").splitlines()[0] if (run / "cable-schedule.csv").is_file() else ""
    check(hdr == ",".join(lab for _, lab in cables.CABLE_COLUMNS), "campus-demo build: cable schedule header")
    shutil.rmtree(run, ignore_errors=True)


# A tiny current-format (1/6-U positions) Rackula layout: two devices and a blank, which becomes a RackItem.
RACKULA_LAYOUT = {
    "version": "26.9.2", "name": "Selftest",
    "racks": [{"id": "rack-a", "name": "Selftest rack", "height": 8, "width": 19, "desc_units": False, "form_factor": "4-post-cabinet",
               "starting_unit": 1, "position": 0, "devices": [
                   {"id": "d1", "device_type": "sw-1u", "name": "Core switch", "position": 6, "face": "front"},
                   {"id": "d2", "device_type": "srv-2u", "name": "Media server", "position": 18, "face": "front"},
                   {"id": "d3", "device_type": "blank-1u", "position": 36, "face": "front"}]}],
    "device_types": [{"slug": "sw-1u", "u_height": 1, "manufacturer": "Acme", "model": "S24", "category": "network"},
                     {"slug": "srv-2u", "u_height": 2, "manufacturer": "Acme", "model": "R2", "category": "server"},
                     {"slug": "blank-1u", "u_height": 1, "category": "blank"}],
}
RACKULA_FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rackula" / "media-server.rackula.yaml"


def _check_racks(check, skip) -> None:
    from . import library, rack_templates, racks
    from .parsers import rackula
    from .schema import apply_ops, new_doc, validate_doc

    def errors(doc):
        return [p for p in validate_doc(doc) if p.get("level") == "error"]

    # ---- catalog tier
    cat = library.catalog_templates()
    unresolved = [t["id"] for t in cat if library.get_template(t["id"]) is None]
    check(len(cat) >= 600 and not unresolved, f"racks: catalog has {len(cat)} templates, {len(unresolved)} unresolved by get_template")
    imaged = [t for t in cat if t.get("image_front") and t.get("image_rear")]
    missing_img = [t["id"] for t in imaged if not (STATIC_DIR / "rack-images" / t["image_front"]).is_file()]
    check(bool(imaged) and not missing_img, f"racks: {len(imaged)} catalog templates with images, {len(missing_img)} image files missing")
    if not imaged:
        return

    # ---- a rack with items and a shelf child: totals, collisions, SVG with images
    tpl = imaged[0]
    ru = int(tpl.get("ru") or 1)
    doc = new_doc("Selftest")
    doc, _ = apply_ops(doc, [
        {"op": "put", "coll": "racks", "id": "rk-st", "value": {
            "id": "rk-st", "name": "Selftest rack", "units": 12, "width_in": 19, "form_factor": "cabinet",
            "weight_kg": 20, "max_load_kg": 100, "power_limit_w": 500, "items": [
                {"id": "ri-1", "type": "blank", "u": 1, "height": 1, "face": "front", "depth": "half", "weight_kg": 0.5},
                {"id": "ri-2", "type": "shelf", "u": 2 + ru, "height": 1, "face": "front", "depth": "full", "slots": 2},
                {"id": "ri-3", "type": "vent", "u": 12, "height": 1, "face": "front", "depth": "half"}]}},
        {"op": "put", "coll": "devices", "id": "st-cat", "value": {
            "id": "st-cat", "name": "Catalog device", "kind": tpl.get("kind") or "other", "template": tpl["id"], "weight_kg": 10, "power_w": 50,
            "rack": {"id": "rk-st", "u": 2, "height": ru, "face": "front", "side": "full", "depth": "full"}}},
        {"op": "put", "coll": "devices", "id": "st-shelf", "value": {
            "id": "st-shelf", "name": "Shelf player", "kind": "other", "weight_kg": 2, "power_w": 15,
            "rack": {"id": "rk-st", "u": 2 + ru, "height": 1, "face": "front", "side": "full", "shelf": "ri-2", "slot": 0}}},
    ])
    check(not errors(doc), f"racks: rack with items and a shelf validates ({len(errors(doc))} errors)")
    warn = [p["code"] for p in racks.validate_racks(doc)]
    check(not racks.collisions(doc, "rk-st") and not warn, f"racks: no collisions or rack warnings ({', '.join(warn) or 'none'})")
    cells = racks.shelf_contents(doc, "rk-st", "ri-2")
    check(cells == [{"slot": 0, "device": "st-shelf"}, {"slot": 1, "device": None}],
          "racks: shelf cells hold the shelf child")
    tot = racks.rack_totals(doc, "rk-st")
    want = {"units": 12, "used_u": ru + 3, "free_u": 12 - ru - 3, "weight_kg": 32.5, "max_load_kg": 100, "power_w": 65.0, "power_limit_w": 500,
            "devices": 2, "items": 3}
    check(all(tot.get(k) == v for k, v in want.items()), f"racks: rack_totals {tot}")
    try:
        svg = racks.rack_svg(doc, "rk-st", face="both", images=True)
        ET.fromstring(svg)
        check("data:image/webp;base64," in svg and "Shelf player" in svg and "Selftest rack" in svg,
              "racks: rack_svg(face='both', images=True) parses, embeds the image and draws the shelf child")
    except ET.ParseError as exc:
        check(False, f"racks: rack_svg parse error {exc}")
    linked = racks.rack_svg(doc, "rk-st", face="rear", images=True, base_url="/")
    check("/static/rack-images/" + tpl["image_rear"] in linked and tpl["image_front"] not in linked, "racks: rear face links only the rear image")

    # ---- Rackula import preview
    pv = rackula.preview(new_doc("Selftest"), {"text": json.dumps(RACKULA_LAYOUT)})
    got, _ = apply_ops(new_doc("Selftest"), pv["ops"])
    rk = (got.get("racks") or [{}])[0]
    pos = sorted((d["name"], d["rack"]["u"], d["rack"]["height"]) for d in got.get("devices") or [] if d.get("rack"))
    check(len(pv["racks"]) == 1 and not errors(got) and pos == [("Core switch", 1, 1), ("Media server", 3, 2)]
          and [i["type"] for i in rk.get("items") or []] == ["blank"], f"racks: Rackula layout previews ({len(pv['ops'])} ops, {pos})")
    if RACKULA_FIXTURE.is_file():
        pv = rackula.preview(new_doc("Selftest"), {"text": RACKULA_FIXTURE.read_text(encoding="utf-8")})
        got, _ = apply_ops(new_doc("Selftest"), pv["ops"])
        rid = got["racks"][0]["id"] if got.get("racks") else ""
        check(len(pv["devices"]) == 6 and not errors(got) and rid and not racks.collisions(got, rid),
              f"racks: {RACKULA_FIXTURE.name} previews ({len(pv['devices'])} devices, {len(pv['warnings'])} warnings)")
    else:
        skip(f"racks: {RACKULA_FIXTURE.name} preview (not a source checkout)")

    # ---- rack templates apply cleanly to a new project and to the campus sample
    campus = json.loads((SAMPLES_DIR / "campus-demo" / "project.json").read_text(encoding="utf-8"))
    bad = []
    tids = [t["id"] for t in rack_templates.list_templates()]
    for tid in tids:
        for label, base in (("new", new_doc("Selftest")), ("campus", json.loads(json.dumps(campus)))):
            try:
                res = rack_templates.apply_ops(base, tid)
                out, _ = apply_ops(base, res["ops"])
                if errors(out) or racks.collisions(out, res["rack_id"]):
                    bad.append(f"{tid}@{label}")
            except Exception as exc:
                bad.append(f"{tid}@{label}: {type(exc).__name__}: {exc}")
    check(len(tids) >= 5 and not bad, f"racks: {len(tids)} rack templates apply cleanly{(' (failed ' + ', '.join(bad) + ')') if bad else ''}")
