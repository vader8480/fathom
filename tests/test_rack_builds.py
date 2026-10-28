"""Rack files in builds, the report Racks section and device-page rack links (SPEC FR-RACK-06, FR-MAP-06, §5.9).

``RealEngines`` builds the campus sample with whatever ``fathom.racks`` / ``fathom.render_rack`` provide and skips the
parts an engine does not support yet. ``FakeEngines`` swaps in a ``rack_svg`` that takes ``face="both", images=True``
and a stub ``render_rack`` so the build side is always exercised.
"""

from __future__ import annotations

import json
import re
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urljoin, urlsplit

try:
    from _helpers import CAMPUS_DIR, call, fr, get_app, install_campus, read_json, requires, temp_data_dir, uniq
except ImportError:  # pragma: no cover
    from tests._helpers import CAMPUS_DIR, call, fr, get_app, install_campus, read_json, requires, temp_data_dir, uniq

RACK = "rk-foh"
DEVICE = "ulxd-main"  # in rk-foh, U10 front
ITEMS = [
    {"id": "ri-1", "type": "blank", "u": 2},
    {"id": "ri-2", "type": "shelf", "u": 4, "slots": 2, "label": "Laptop shelf"},
    {"id": "ri-3", "type": "vent", "u": 11},
]


def install_campus_with_items(data: Path, name: str = "campus") -> Path:
    pdir = install_campus(data, name)
    doc = read_json(pdir / "project.json")
    for rk in doc["racks"]:
        if rk["id"] == RACK:
            rk["items"] = [dict(i) for i in ITEMS]
    (pdir / "project.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return pdir


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links = []  # (tag, attr, value, section id)
        self.section = ""
        self.depth = 0
        self._sec_depth = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section":
            self._sec_depth.append(self.section)
            self.section = a.get("id") or self.section
        for k in ("href", "src"):
            if a.get(k):
                self.links.append((tag, k, a[k], self.section))

    def handle_endtag(self, tag):
        if tag == "section" and self._sec_depth:
            self.section = self._sec_depth.pop()


def links_of(html: str):
    p = _Links()
    p.feed(html)
    return p.links


def local(url: str) -> bool:
    s = urlsplit(url)
    return not (s.scheme or s.netloc or url.startswith("#") or url.startswith("/"))


def resolve(run: Path, page: str, url: str) -> Path:
    """File a relative ``url`` on build page ``page`` (relative to ``run``) points at."""
    path = unquote(urlsplit(url).path)
    return (run / page).parent.joinpath(*path.split("/")).resolve()


def racks_section(html: str) -> str:
    m = re.search(r'<section id="(sec-\d+)"[^>]*><h2>Racks</h2>(.*?)</section>', html, re.S)
    return m.group(2) if m else ""


def both_supported() -> str:
    """"" when ``racks.rack_svg`` takes ``face="both", images=True``, else the skip reason."""
    racks = requires("racks")
    doc = {"racks": [{"id": "r", "units": 2}], "devices": []}
    try:
        racks.rack_svg(doc, "r", face="both", images=True)
    except (TypeError, ValueError) as exc:
        return "awaiting racks.rack_svg(face='both', images=True) (RPY): %s" % exc
    return ""


def render_rack_missing() -> str:
    try:
        from fathom import render_rack  # noqa: F401
    except ImportError:
        return "awaiting fathom.render_rack (VWR)"
    return "" if callable(getattr(render_rack, "rack_page_html", None)) else "awaiting render_rack.rack_page_html (VWR)"


class _BuildCase(unittest.TestCase):
    run_dir: Path
    doc: dict

    @classmethod
    def build(cls):
        export = requires("export")
        requires("export:build_doc")
        cls._ctx = temp_data_dir()
        cls.data = cls._ctx.__enter__()
        install_campus_with_items(cls.data, "campus")
        cls.doc = read_json(cls.data / "projects" / "campus" / "project.json")
        cls.run_dir = Path(export.build_doc(str(cls.data / "projects" / "campus"), run_dir=cls.data / "runs" / uniq("campus"),
                                            base_url="http://localhost:8080"))
        cls.notes = (cls.run_dir / "build-notes.txt").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        ctx = getattr(cls, "_ctx", None)
        if ctx is not None:
            ctx.__exit__(None, None, None)

    def read(self, rel: str) -> str:
        return (self.run_dir / rel).read_text(encoding="utf-8")

    def check_report(self, pages: bool, both: bool):
        sec = racks_section(self.read("report.html"))
        self.assertTrue(sec, fr("FR-RACK-06", "5.9", "report.html has a Racks section"))
        self.assertRegex(self.read("report.html"), r'<li><a href="#sec-\d+">Racks</a></li>', "the Racks section is in the report TOC")
        for rk in self.doc["racks"]:
            self.assertIn('data-rack="%s"' % rk["id"], sec, "one row per rack: %s" % rk["id"])
            self.assertIn(rk["name"], sec)
        links = [u for _t, _k, u, _s in links_of(sec)]
        self.assertTrue(links, "the Racks section links files")
        for u in links:
            self.assertTrue(local(u), "relative link in a build: %s" % u)
            target = resolve(self.run_dir, "report.html", u)
            self.assertTrue(target.is_file(), "report Racks link resolves inside the build: %s" % u)
            self.assertTrue(str(target).startswith(str(self.run_dir.resolve())), u)
        for rk in self.doc["racks"]:
            self.assertIn("racks/%s-front.svg" % rk["id"], links)
            self.assertEqual("racks/%s.html" % rk["id"] in links, pages, "rack page linked only when produced")
            self.assertEqual("racks/%s.svg" % rk["id"] in links, both, "both-faces SVG linked only when produced")
        # rk-foh: 12 U; devices at U1 (rear), U6, U8, U10, U12 (rear) -> 5 used without items, more with them
        row = re.search(r'<tr data-rack="rk-foh">(.*?)</tr>', sec, re.S).group(1)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        self.assertEqual(cells[2], "12", "units")
        self.assertEqual(int(cells[3]) + int(cells[4]), 12, "used + free = units")
        self.assertGreaterEqual(int(cells[3]), 5, "used U counts the racked devices")
        self.assertGreaterEqual(int(cells[5]), 5, "devices count")

    def check_device_link(self, pages: bool):
        page = self.read("devices/%s.html" % DEVICE)
        hrefs = [u for _t, k, u, _s in links_of(page) if k == "href" and "racks/" in u]
        if pages:
            self.assertIn("../racks/%s.html" % RACK, hrefs, fr("FR-MAP-06", "5.9", "build device page links its rack page"))
            self.assertTrue(resolve(self.run_dir, "devices/%s.html" % DEVICE, "../racks/%s.html" % RACK).is_file())
        else:
            self.assertEqual(hrefs, [], "no rack page in the build -> the Rack line is plain text")
        self.assertIn("FOH rack · U10 · front", page, "Rack line text unchanged")


class RealEngines(_BuildCase):
    """Campus build with the engines on this branch."""

    @classmethod
    def setUpClass(cls):
        cls.build()

    def test_face_svgs_unchanged(self):
        for rk in self.doc["racks"]:
            for face in ("front", "rear"):
                f = self.run_dir / "racks" / ("%s-%s.svg" % (rk["id"], face))
                self.assertTrue(f.is_file(), fr("FR-RACK-06", "5.9", f.name))
                root = ET.fromstring(f.read_bytes())
                self.assertEqual(root.get("data-face"), face)

    def test_both_faces_svg(self):
        reason = both_supported()
        if reason:
            for rk in self.doc["racks"]:
                self.assertFalse((self.run_dir / "racks" / ("%s.svg" % rk["id"])).exists())
            self.assertIn("racks/<rack>.svg skipped", self.notes, "build note names the skipped file")
            self.skipTest(reason)
        for rk in self.doc["racks"]:
            f = self.run_dir / "racks" / ("%s.svg" % rk["id"])
            self.assertTrue(f.is_file(), fr("FR-RACK-06", "5.9", f.name))
            ET.fromstring(f.read_bytes())

    def test_rack_pages(self):
        reason = render_rack_missing()
        if reason:
            self.assertFalse(list((self.run_dir / "racks").glob("*.html")), "no rack pages without render_rack")
            self.assertIn("racks/<rack>.html skipped", self.notes)
            self.skipTest(reason)
        for rk in self.doc["racks"]:
            rel = "racks/%s.html" % rk["id"]
            self.assertTrue((self.run_dir / rel).is_file(), fr("FR-RACK-06", "5.9", rel))
            for _t, _k, u, _s in links_of(self.read(rel)):
                if u.startswith("data:"):
                    continue
                self.assertTrue(local(u) or urlsplit(u).scheme in ("http", "https", "mailto"), "%s: no absolute path links (%s)" % (rel, u))
                if local(u) and urlsplit(u).path:
                    self.assertTrue(resolve(self.run_dir, rel, u).is_file(), "%s: link resolves inside the build: %s" % (rel, u))

    def test_report_racks_section(self):
        self.check_report(pages=not render_rack_missing(), both=not both_supported())

    def test_device_page_rack_link_build(self):
        self.check_device_link(pages=not render_rack_missing())

    def test_zip_has_rack_files(self):
        import zipfile

        names = set(zipfile.ZipFile(str(self.run_dir / ("%s.zip" % self.run_dir.name))).namelist())
        for f in (self.run_dir / "racks").iterdir():
            self.assertIn("%s/racks/%s" % (self.run_dir.name, f.name), names)


def _fake_render_rack() -> types.ModuleType:
    mod = types.ModuleType("fathom.render_rack")
    calls = []

    def rack_page_html(doc, project, rack_id, *, base, share="", link_style="viewer"):
        calls.append((project, rack_id, base, share, link_style))
        rack = next((r for r in doc.get("racks") or [] if r.get("id") == rack_id), None)
        if rack is None:
            raise KeyError(rack_id)
        devs = [d for d in doc.get("devices") or [] if (d.get("rack") or {}).get("id") == rack_id]
        items = "".join('<li><a href="../devices/%s.html">%s</a></li>' % (d["id"], d.get("name") or d["id"]) for d in devs)
        return "<!doctype html><title>%s</title><h1>%s</h1><ul>%s</ul>" % (rack.get("name"), rack.get("name"), items)

    mod.rack_page_html = rack_page_html
    mod.calls = calls
    return mod


class FakeEngines(_BuildCase):
    """Campus build with a both-faces ``rack_svg`` and a stub ``render_rack`` patched in."""

    @classmethod
    def setUpClass(cls):
        racks = requires("racks")
        real = racks.rack_svg
        cls.svg_calls = []

        def rack_svg(doc, rack_id, face="front", scale=1.0, **kw):
            cls.svg_calls.append((rack_id, face, kw.get("images")))
            if face != "both":
                return real(doc, rack_id, face=face, scale=scale)
            return ('<svg xmlns="http://www.w3.org/2000/svg" data-rack="%s" data-face="both"><g>%s</g></svg>'
                    % (rack_id, "".join(re.sub(r"^<svg[^>]*>|</svg>\s*$", "", real(doc, rack_id, face=f).strip()) for f in ("front", "rear"))))

        cls.fake = _fake_render_rack()
        with mock.patch.object(racks, "rack_svg", rack_svg), mock.patch.dict(sys.modules, {"fathom.render_rack": cls.fake}):
            cls.build()

    def test_files(self):
        for rk in self.doc["racks"]:
            for name in ("%s.svg", "%s.html", "%s-front.svg", "%s-rear.svg"):
                self.assertTrue((self.run_dir / "racks" / (name % rk["id"])).is_file(), name % rk["id"])
            root = ET.fromstring((self.run_dir / "racks" / ("%s.svg" % rk["id"])).read_bytes())
            self.assertEqual(root.get("data-face"), "both")
        self.assertIn((RACK, "both", True), self.svg_calls, "rack_svg(face='both', images=True)")
        self.assertIn(("campus", RACK, "", "", "build"), self.fake.calls, "rack_page_html(fdoc, project, rack, base='', link_style='build')")
        self.assertNotIn("skipped", " ".join(l for l in self.notes.splitlines() if "rack" in l.lower()))

    def test_report_racks_section(self):
        self.check_report(pages=True, both=True)
        sec = racks_section(self.read("report.html"))
        self.assertIn('<a href="racks/rk-foh.html">FOH rack</a>', sec, "rack name links its page")
        self.assertIn('src="racks/rk-foh.svg"', sec, "the elevation figure uses the both-faces SVG")

    def test_device_page_rack_link_build(self):
        self.check_device_link(pages=True)

    def test_rack_page_links_resolve(self):
        for rk in self.doc["racks"]:
            rel = "racks/%s.html" % rk["id"]
            for _t, _k, u, _s in links_of(self.read(rel)):
                self.assertTrue(resolve(self.run_dir, rel, u).is_file(), u)


class DevicePageViewer(unittest.TestCase):
    """``render_device_page`` in viewer mode and the ``/p/<n>/d/<device>`` route."""

    def setUp(self):
        self.rh = requires("render_html")
        self.doc = read_json(CAMPUS_DIR / "project.json")

    def page(self, doc=None, **kw):
        return self.rh.render_device_page(doc or self.doc, DEVICE, project="campus", **kw)

    def rack_hrefs(self, html):
        return [u for _t, k, u, _s in links_of(html) if k == "href" and ("rk/" in u or "racks/" in u)]

    def test_viewer_link(self):
        html = self.page()
        self.assertEqual(self.rack_hrefs(html), ["../rk/%s" % RACK], fr("FR-MAP-06", "5.13", "viewer device page links /p/<n>/rk/<rack>"))
        self.assertIn(">FOH rack · U10 · front</a>", html)
        self.assertEqual(urljoin("/p/campus/d/%s" % DEVICE, self.rack_hrefs(html)[0]), "/p/campus/rk/%s" % RACK)

    def test_viewer_link_share(self):
        self.assertEqual(self.rack_hrefs(self.page(share="sh-abc_1")), ["../rk/%s?share=sh-abc_1" % RACK], "share token carried")

    def test_build_link(self):
        self.assertEqual(self.rack_hrefs(self.page(link_style="build", base_url="../")), ["../racks/%s.html" % RACK])
        self.assertEqual(self.rack_hrefs(self.page(link_style="build", base_url="../", rack_pages=[])), [], "no page written -> no link")
        self.assertEqual(self.rack_hrefs(self.page(link_style="build", base_url="../", rack_pages=["rk-amp"])), [])

    def test_unknown_rack_keeps_text(self):
        doc = json.loads(json.dumps(self.doc))
        dev = next(d for d in doc["devices"] if d["id"] == DEVICE)
        dev["rack"]["id"] = "rk-gone"
        for style in ("viewer", "build"):
            html = self.page(doc, link_style=style)
            self.assertEqual(self.rack_hrefs(html), [], "unknown rack -> no link (%s)" % style)
            self.assertIn("<dt>Rack</dt><dd>rk-gone · U10 · front</dd>", html)

    def test_escaped(self):
        doc = json.loads(json.dumps(self.doc))
        rk = next(r for r in doc["racks"] if r["id"] == RACK)
        rk["name"] = '<script>"x"</script>'
        html = self.page(doc)
        self.assertNotIn("<script>\"x\"", html)
        self.assertIn("&lt;script&gt;", html)

    def test_route(self):
        with temp_data_dir() as data:
            install_campus_with_items(data, "campus")
            st, _h, body = call(get_app(), "GET", "/p/campus/d/%s" % DEVICE)
            self.assertEqual(st, 200)
            self.assertIn('href="../rk/%s"' % RACK, body.decode("utf-8"), fr("FR-MAP-06", "5.13", "served device page links the rack page"))
            st, _h, body = call(get_app(), "GET", "/p/campus/d/amp-main")
            self.assertIn('href="../rk/rk-amp"', body.decode("utf-8"))


class RackSummary(unittest.TestCase):
    def test_counts(self):
        rh = requires("render_html")
        doc = {"racks": [{"id": "r", "units": 10}], "devices": [
            {"id": "a", "rack": {"id": "r", "u": 1, "height": 2, "face": "front"}},
            {"id": "b", "rack": {"id": "r", "u": 5, "height": 1, "face": "rear", "depth": "half"}},
        ]}
        s = rh.rack_summary(doc, "r")
        self.assertEqual((s["units"], s["used_u"], s["free_u"], s["devices"]), (10, 3, 7, 2))
        with self.assertRaises(KeyError):
            rh.rack_summary(doc, "nope")

    def test_section_empty_and_escaped(self):
        rh = requires("render_html")
        self.assertEqual(rh.render_rack_report_section({"racks": []}, {}), "")
        doc = {"rooms": [{"id": "m", "name": "Main & <b>"}], "racks": [{"id": "r", "name": "<i>R</i>", "room": "m", "units": 4}], "devices": []}
        out = rh.render_rack_report_section(doc, {"r": {"front": "racks/r-front.svg", "rear": "racks/r-rear.svg"}})
        self.assertIn("&lt;i&gt;R&lt;/i&gt;", out)
        self.assertIn("Main &amp; &lt;b&gt;", out)
        self.assertNotIn("racks/r.html", out)
        self.assertIn('src="racks/r-front.svg"', out)


if __name__ == "__main__":
    unittest.main()
