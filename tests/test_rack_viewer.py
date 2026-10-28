"""Public rack viewer page ``render_rack.rack_page_html`` (viewer ``/p/<n>/rk/<rack>`` and build ``racks/<rack>.html``)."""

from __future__ import annotations

import base64
import copy
import os
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

try:
    from _helpers import CAMPUS_DIR, basic, call, get_app, install_campus, jbody, read_json, requires, temp_data_dir, temp_env
except ImportError:  # pragma: no cover
    from tests._helpers import CAMPUS_DIR, basic, call, get_app, install_campus, jbody, read_json, requires, temp_data_dir, temp_env

from fathom import racks
from fathom import render_rack
from fathom.render_rack import rack_page_html

BASE = "../../../"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Tree(HTMLParser):
    """Collects tags, attributes and text; records unbalanced end tags (HTML void elements and ``<x/>`` excepted)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: List[str] = []
        self.errors: List[str] = []
        self.tags: List[Tuple[str, Dict[str, str]]] = []
        self.text: List[str] = []
        self._rows: List[Dict[str, Any]] = []
        self._row: Optional[Dict[str, Any]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        a = {k: v or "" for k, v in attrs}
        self.tags.append((tag, a))
        if tag == "tr":
            self._row = {"attrs": a, "hrefs": [], "cells": []}
            self._rows.append(self._row)
        if tag == "a" and self._row is not None:
            self._row["hrefs"].append(a.get("href", ""))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.tags.append((tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()
        if tag == "tr":
            self._row = None

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._row is not None:
            self._row["cells"].append(data)

    def rows(self, attr: str) -> List[Dict[str, Any]]:
        return [r for r in self._rows if attr in r["attrs"]]

    def hrefs(self) -> List[str]:
        return [a["href"] for t, a in self.tags if t == "a" and "href" in a]


def parse(html: str) -> _Tree:
    t = _Tree()
    t.feed(html)
    t.close()
    return t


def campus() -> Dict[str, Any]:
    doc = copy.deepcopy(read_json(CAMPUS_DIR / "project.json"))
    foh = next(r for r in doc["racks"] if r["id"] == "rk-foh")
    foh["items"] = [
        {"id": "ri-1", "type": "shelf", "u": 3, "label": "Laptop shelf", "slots": 2},
        {"id": "ri-2", "type": "blank", "u": 2},
        {"id": "ri-3", "type": "vent", "u": 11, "label": "Top vent", "color": "#44475a"},
        {"id": "ri-4", "type": "lacing_bar", "u": 2, "face": "rear"},
    ]
    foh["notes"] = "**Front of house** rack. The switcher is [[device:switcher]]; room [[room:main]].\n\n- check fans\n- label cables"
    foh["width_in"] = 19
    foh["form_factor"] = "road_case"
    return doc


def expected_order(doc: Dict[str, Any], rack_id: str) -> List[str]:
    rack = next(r for r in doc["racks"] if r["id"] == rack_id)
    placed = [p for p in racks.rack_devices(doc, rack_id) if p["u"] is not None]
    if rack.get("numbering") == "top_down":
        return [p["device"] for p in sorted(placed, key=lambda p: p["u"])]
    return [p["device"] for p in sorted(placed, key=lambda p: -(p["u"] + p["height"] - 1))]


class RackViewerPage(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = campus()

    def page(self, rack_id: str = "rk-foh", **kw: Any) -> str:
        kw.setdefault("base", BASE)
        return rack_page_html(self.doc, "campus", rack_id, **kw)

    def test_parses_with_header_and_both_faces(self) -> None:
        html = self.page()
        self.assertTrue(html.startswith("<!doctype html>"))
        t = parse(html)
        self.assertEqual(t.errors, [])
        self.assertEqual(t.stack, [])
        self.assertIn("<h1>FOH rack</h1>", html)
        faces = [a.get("data-face") for tag, a in t.tags if tag == "svg"]
        self.assertIn("front", faces)
        self.assertIn("rear", faces)
        text = " ".join(t.text)
        for want in ("12U", "19\u2033", "Road case", "FOH booth", "Main Auditorium"):
            self.assertIn(want, text)
        self.assertIn(f'href="{BASE}p/campus/r/main"', html)
        self.assertIn(f'href="{BASE}p/campus/rooms"', html)
        self.assertIn(f'href="{BASE}#/campus/main/racks/rk-foh"', html, "editor link to the rack page")
        self.assertIn("max-width:100%", render_rack.RACK_CSS)
        self.assertIn("@media print", html)

    def test_defaults_for_width_and_form_factor(self) -> None:
        text = " ".join(parse(self.page("rk-amp")).text)
        self.assertIn("19\u2033", text)
        self.assertIn("Cabinet", text)

    def test_device_links_viewer_top_down(self) -> None:
        t = parse(self.page())
        rows = t.rows("data-device")
        self.assertEqual([r["attrs"]["data-device"] for r in rows], expected_order(self.doc, "rk-foh"))
        for r in rows:
            self.assertEqual(r["hrefs"], [f"{BASE}p/campus/d/{r['attrs']['data-device']}"])
        first = rows[0]["cells"]
        self.assertEqual(first[0], "U12")
        self.assertIn("NETGEAR M4250-26G4F-PoE+", first)
        self.assertIn("rear", first)

    def test_top_down_numbering_order(self) -> None:
        rows = parse(self.page("rk-bcast")).rows("data-device")
        self.assertEqual([r["attrs"]["data-device"] for r in rows], expected_order(self.doc, "rk-bcast"))
        self.assertEqual(rows[0]["cells"][0], "U10")

    def test_multi_u_span(self) -> None:
        rows = {r["attrs"]["data-device"]: r for r in parse(self.page("rk-amp")).rows("data-device")}
        self.assertEqual(rows["rio-sl"]["cells"][0], "U18–22")
        self.assertEqual(rows["amp-main"]["cells"][0], "U4–5")

    def test_device_links_build(self) -> None:
        with temp_env(FATHOM_PUBLIC_URL=None):
            html = self.page(base="", link_style="build")
        t = parse(html)
        self.assertEqual(t.errors, [])
        rows = t.rows("data-device")
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["hrefs"], [f"../devices/{r['attrs']['data-device']}.html"])
        hrefs = t.hrefs()
        self.assertIn("../rooms/main/index.html", hrefs)
        self.assertIn("../rooms/index.html", hrefs)
        self.assertFalse([h for h in hrefs if "p/campus" in h or "#/" in h], "no viewer or editor links in a build")
        self.assertNotIn("/qr/rack/", html)
        self.assertNotIn("manifest.webmanifest", html)
        self.assertFalse([a for tag, a in t.tags if tag == "div" and a.get("class") == "rv-qr"], "no absolute URL -> no QR")

    def test_build_qr_inlined_when_public_url_known(self) -> None:
        from fathom.qr import svg as qr_svg

        self.doc["settings"]["public_url"] = "https://av.example.org/"
        html = self.page(base="", link_style="build")
        self.assertIn(qr_svg("https://av.example.org/p/campus/rk/rk-foh", "M", scale=4), html)
        with temp_env(FATHOM_PUBLIC_URL="https://env.example.org"):
            self.doc["settings"]["public_url"] = ""
            html = self.page(base="", link_style="build")
        self.assertIn(qr_svg("https://env.example.org/p/campus/rk/rk-foh", "M", scale=4), html)

    def test_viewer_qr_img(self) -> None:
        t = parse(self.page())
        imgs = [a for tag, a in t.tags if tag == "img"]
        self.assertEqual([a["src"] for a in imgs], [f"{BASE}api/v2/projects/campus/qr/rack/rk-foh.svg"])
        self.assertIn("FOH rack", imgs[0]["alt"])

    def test_share_links_go_through_the_mirror(self) -> None:
        self.doc["pages"] = [{"slug": "rack-power", "title": "Rack power", "status": "published", "body": "x"}]
        foh = next(r for r in self.doc["racks"] if r["id"] == "rk-foh")
        foh["notes"] += "\n\nSee [[page:rack-power]]."
        with temp_env(FATHOM_PUBLIC_URL=None):
            html = self.page(share="sh-tok_1")
        t = parse(html)
        mirror = BASE + "s/sh-tok_1/"
        hrefs = [h for h in t.hrefs() if not h.endswith((".webmanifest", ".png"))]
        self.assertTrue(hrefs)
        for h in hrefs:
            self.assertTrue(h.startswith(mirror), h)
            self.assertNotIn("?share=", h)
            self.assertNotIn("/p/", h)
        for r in t.rows("data-device"):
            self.assertEqual(r["hrefs"], [f"{mirror}d/{r['attrs']['data-device']}"])
        for want in ("r/main", "rooms", "sop/rack-power", "d/switcher"):
            self.assertIn(mirror + want, hrefs)
        self.assertNotIn("#/campus", html, "share viewers get no editor link")
        self.assertNotIn("/qr/rack/", html, "the viewer-role QR API is not used on share pages")
        self.assertFalse([a for tag, a in t.tags if tag == "div" and a.get("class") == "rv-qr"], "no public URL -> no QR")

    def test_share_qr_inline_with_public_url(self) -> None:
        from fathom.qr import svg as qr_svg

        self.doc["settings"]["public_url"] = "https://av.example.org/"
        html = self.page(share="sh-tok_1")
        self.assertIn(qr_svg("https://av.example.org/s/sh-tok_1/rk/rk-foh", "M", scale=4), html)
        self.assertFalse([a for tag, a in parse(html).tags if tag == "img"])
        self.assertNotIn("/qr/rack/", html)
        with temp_env(FATHOM_PUBLIC_URL="https://env.example.org"):
            self.doc["settings"]["public_url"] = ""
            html = self.page(share="sh-tok_1")
            self.assertIn(qr_svg("https://env.example.org/s/sh-tok_1/rk/rk-foh", "M", scale=4), html)
            html = self.page(base="https://abs.example.org/", share="sh-tok_1")
        self.assertIn(qr_svg("https://abs.example.org/s/sh-tok_1/rk/rk-foh", "M", scale=4), html)

    def test_non_share_viewer_links_unchanged(self) -> None:
        t = parse(self.page())
        hrefs = [h for h in t.hrefs() if not h.endswith((".webmanifest", ".png"))]
        self.assertFalse([h for h in hrefs if "/s/" in h or "share" in h])
        self.assertTrue(all(h.startswith(BASE + "p/campus/") or h.startswith(BASE + "#/") for h in hrefs), hrefs)

    def test_accessories(self) -> None:
        rows = parse(self.page()).rows("data-item")
        self.assertEqual([r["attrs"]["data-item"] for r in rows], ["ri-3", "ri-1", "ri-2", "ri-4"])
        cells = {r["attrs"]["data-item"]: r["cells"] for r in rows}
        self.assertEqual(cells["ri-3"][:3], ["Vent panel", "U11", "front"])
        self.assertIn("Top vent", cells["ri-3"])
        self.assertEqual(cells["ri-1"][0], "Shelf")
        self.assertIn("Laptop shelf · 2 cells", cells["ri-1"])
        self.assertEqual(cells["ri-4"][:3], ["Lacing bar", "U2", "rear"])

    def test_no_accessories_section_without_items(self) -> None:
        self.assertNotIn("Accessories", self.page("rk-amp"))

    def test_notes_markdown(self) -> None:
        html = self.page()
        self.assertIn("<strong>Front of house</strong>", html)
        self.assertRegex(html, r'<a class="md-ref md-ref-device" href="\.\./\.\./\.\./p/campus/d/switcher"')
        self.assertRegex(html, r'href="\.\./\.\./\.\./p/campus/r/main"[^>]*>Main Auditorium</a>')
        self.assertIn("<li>check fans</li>", html)
        build = self.page(base="", link_style="build")
        self.assertIn('href="../devices/switcher.html"', build)

    def test_totals_fallback_from_occupancy(self) -> None:
        with mock.patch.object(racks, "rack_totals", None, create=True):
            html = self.page()
        occ = racks.rack_occupancy(self.doc, "rk-foh")
        used = sum(1 for s in occ["slots"] if any(s[f][x] for f in ("front", "rear") for x in ("left", "right")))
        self.assertIn(f"{used} U used", html)
        self.assertIn(f"{12 - used} U free of 12 U", html)
        self.assertNotIn('data-stat="Weight"', html)
        self.assertNotIn('data-stat="Power"', html)

    def test_totals_engine_with_warnings(self) -> None:
        fake = mock.Mock(return_value={"units": 12, "used_u": 7, "free_u": 5, "weight_kg": 212.5, "max_load_kg": 200,
                                       "power_w": 900, "power_limit_w": 1800, "devices": 6, "items": 4})
        with mock.patch.object(racks, "rack_totals", fake, create=True):
            html = self.page()
        fake.assert_called_once_with(self.doc, "rk-foh")
        self.assertRegex(html, r'class="rv-stat rv-over" data-stat="Weight"><div class="k">Weight</div><div class="v">212\.5 kg</div><div class="s">of 200 kg max load · over')
        self.assertRegex(html, r'class="rv-stat" data-stat="Power"><div class="k">Power</div><div class="v">900 W</div><div class="s">of 1800 W circuit limit<')
        self.assertIn("7 U used", html)
        fake.return_value = dict(fake.return_value, max_load_kg=None, power_limit_w=None)
        with mock.patch.object(racks, "rack_totals", fake, create=True):
            html = self.page()
        self.assertIn("no max load set", html)
        self.assertIn("no circuit limit set", html)
        self.assertNotIn("rv-over", html.split("</style>", 1)[1])

    def test_new_engine_keywords_and_labels(self) -> None:
        calls: List[Dict[str, Any]] = []

        def fake_svg(doc: Any, rack_id: str, face: str = "front", scale: float = 1.0, *, images: bool = False, annotate: Any = None, base_url: str = "") -> str:
            calls.append({"face": face, "images": images, "base_url": base_url})
            return f'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" data-face="{face}" width="380" height="300"><title>t</title></svg>'

        with mock.patch.object(racks, "rack_svg", fake_svg), \
                mock.patch.object(racks, "ru_label", lambda rack, u: str(u + 99), create=True), \
                mock.patch.object(racks, "ITEM_TYPES", [{"type": "vent", "label": "Vent (perforated)", "height": 1, "face": "front", "depth": "half"}], create=True):
            html = self.page()
            build = self.page(base="", link_style="build")
        self.assertEqual(calls[:2], [{"face": "front", "images": True, "base_url": BASE}, {"face": "rear", "images": True, "base_url": BASE}])
        self.assertEqual(calls[2:], [{"face": "front", "images": True, "base_url": ""}, {"face": "rear", "images": True, "base_url": ""}])
        self.assertNotIn("<?xml", html)
        rows = parse(html).rows("data-device")
        self.assertEqual(rows[0]["cells"][0], "U111")
        self.assertIn("Vent (perforated)", html)
        self.assertNotIn("<?xml", build)

    def test_shelf_children_listed(self) -> None:
        def fake_devices(doc: Any, rack_id: str) -> List[Dict[str, Any]]:
            out = [dict(p) for p in orig(doc, rack_id)]
            if rack_id == "rk-foh":
                out.append({"device": "iem-tx", "rack": "rk-foh", "u": 3, "height": 1, "face": "front", "side": "full", "depth": "full", "shelf": "ri-1", "slot": 1})
            return out

        orig = racks.rack_devices
        with mock.patch.object(racks, "rack_devices", fake_devices):
            rows = {r["attrs"]["data-device"]: r["cells"] for r in parse(self.page()).rows("data-device")}
        self.assertIn("Shelf Laptop shelf · cell 2", rows["iem-tx"])

    def test_escaping(self) -> None:
        bad = "<script>alert(1)</script>"
        foh = next(r for r in self.doc["racks"] if r["id"] == "rk-foh")
        foh["name"] = bad
        foh["notes"] = '<img src=x onerror="alert(2)"> and [x](javascript:alert(3))'
        foh["row"] = '"><b>row</b>'
        foh["items"][0]["label"] = '"><i>shelf</i>'
        foh["items"][1]["color"] = 'red" onclick="x'
        self.doc["meta"]["org"] = "<b>Org</b>"
        sw = next(d for d in self.doc["devices"] if d["id"] == "switcher")
        sw["name"] = "<u>switch</u>"
        for kw in ({}, {"base": "", "link_style": "build"}):
            html = self.page(**kw)
            t = parse(html)
            self.assertEqual(t.errors, [])
            self.assertNotIn(bad, html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
            for raw in ("javascript:", "<b>row</b>", "<i>shelf</i>", "onclick", "<b>Org</b>", "<u>switch</u>", "<img src=x"):
                self.assertNotIn(raw, html)
            self.assertFalse([tag for tag, a in t.tags if tag in ("b", "u") or (tag == "i" and not a.get("style"))], "no injected tags")
            self.assertFalse([(tag, k) for tag, a in t.tags for k in a if k.startswith("on")], "no event-handler attributes")
            self.assertFalse([a["src"] for tag, a in t.tags if tag == "img" and a.get("src") == "x"])
            scripts = [a for tag, a in t.tags if tag == "script"]
            self.assertTrue(all("alert" not in "".join(a.values()) for a in scripts))

    def test_unknown_rack_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            rack_page_html(self.doc, "campus", "rk-nope", base=BASE)
        with self.assertRaises(KeyError):
            rack_page_html({"racks": []}, "campus", "rk-foh", base="", link_style="build")

    def test_empty_rack(self) -> None:
        self.doc["racks"].append({"id": "rk-empty", "name": "Spare", "units": 4})
        html = self.page("rk-empty")
        self.assertEqual(parse(html).errors, [])
        self.assertIn("No devices in this rack.", html)
        self.assertIn("0 U used", html)


class RackSharePageEndToEnd(unittest.TestCase):
    """Login on (a user exists): an anonymous visitor opens ``/s/<token>/rk/<rack>`` and follows its links."""

    def test_anonymous_share_visitor(self) -> None:
        users = requires("users")
        app = get_app()
        with temp_data_dir() as data:
            install_campus(data, "campus")
            users.add_user("ada", "ada-password-1", role="admin")
            admin = dict(basic("ada", "ada-password-1"), **{"Content-Type": "application/json", "X-Fathom": "1"})
            st, _, b = call(app, "POST", "/api/v2/projects/campus/shares", {"scope": "all"}, admin)
            self.assertEqual(st, 201, b)
            token = jbody(b)["share"]["token"]
            st, _, _ = call(app, "GET", "/p/campus/rk/rk-foh")
            self.assertNotEqual(st, 200, "login is on: /p/ needs a viewer")
            st, h, b = call(app, "GET", f"/s/{token}/rk/rk-foh")
            self.assertEqual(st, 200, b[:300])
            self.assertTrue(h["content-type"].startswith("text/html"))
            t = parse(b.decode("utf-8"))
            self.assertEqual(t.errors, [])
            hrefs = [x for x in t.hrefs() if not x.endswith((".webmanifest", ".png"))]
            devices = [r["hrefs"][0] for r in t.rows("data-device") if r["hrefs"]]
            self.assertTrue(devices)
            self.assertIn(f"/s/{token}/rooms", hrefs)
            self.assertIn(f"/s/{token}/r/main", hrefs)
            for href in hrefs:
                self.assertTrue(href.startswith(f"/s/{token}/"), href)
                self.assertNotIn("?share=", href)
            for href in [devices[0], f"/s/{token}/rooms", f"/s/{token}/r/main"]:
                st, _, b = call(app, "GET", href)
                self.assertEqual(st, 200, (href, b[:200]))
            st, _, b = call(app, "GET", devices[0])
            self.assertIn(b"<h1>", b)
            self.assertNotIn(b"/qr/rack/", call(app, "GET", f"/s/{token}/rk/rk-foh")[2], "no viewer-role QR API on share pages")


try:
    import _ui
except ImportError:  # pragma: no cover
    from tests import _ui


def _shot_dir() -> Path:
    if os.environ.get("FATHOM_UI_SHOTS"):
        return Path(os.environ["FATHOM_UI_SHOTS"]) / "vwr"
    if Path("/opt/cursor/artifacts").is_dir():
        return Path("/opt/cursor/artifacts/vwr")
    return Path(tempfile.mkdtemp(prefix="fathom-vwr-shots-"))


def _save(pg: Any, dest: Path, full: bool = False) -> None:
    params: Dict[str, Any] = {"format": "png"}
    if full:
        size = pg.command("Page.getLayoutMetrics")["cssContentSize"]
        params.update(captureBeyondViewport=True, clip={"x": 0, "y": 0, "width": size["width"], "height": size["height"], "scale": 1})
    dest.write_bytes(base64.b64decode(pg.command("Page.captureScreenshot", params)["data"]))


@_ui.skip_without_chrome
class RackViewerScreenshots(unittest.TestCase):
    """A build-mode page (inline QR, offline links) written to a temp file and opened over file:// in headless Chrome."""

    def test_desktop_and_phone(self) -> None:
        doc = campus()
        doc["settings"]["public_url"] = "https://av.example.org"
        html = rack_page_html(doc, "campus", "rk-foh", base="", link_style="build")
        out = _shot_dir()
        out.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="fathom-vwr-"))
        try:
            page = tmp / "rack.html"
            page.write_text(html, encoding="utf-8")
            with _ui.open(page.as_uri(), "d", base="") as pg:
                pg.command("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
                self.assertEqual(pg.js("innerWidth"), 1440)
                self.assertEqual(pg.smoke["errors"], [])
                self.assertLessEqual(pg.page_hscroll(), 0)
                self.assertTrue(pg.js("document.querySelectorAll('.rv-faces svg').length === 2"))
                _save(pg, out / "rack-page-1440x900.png")
            with _ui.open(page.as_uri(), "m", base="") as pg:
                self.assertEqual(pg.js("innerWidth"), 390)
                self.assertEqual(pg.smoke["errors"], [])
                self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll at 390 px")
                widths = pg.js("Array.prototype.map.call(document.querySelectorAll('.rv-faces svg'), function (s) { return Math.round(s.getBoundingClientRect().width); })")
                self.assertEqual(len(widths), 2)
                self.assertTrue(all(w >= 330 for w in widths), f"faces stack at full width on a phone: {widths}")
                _save(pg, out / "rack-page-390x844.png")
                _save(pg, out / "rack-page-390-full.png", full=True)
            for name in ("rack-page-1440x900.png", "rack-page-390x844.png", "rack-page-390-full.png"):
                self.assertEqual((out / name).read_bytes()[:8], b"\x89PNG\r\n\x1a\n", name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
