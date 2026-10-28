"""Device labels sized for the Brady M511 (phase 1 P1B; SPEC §3.24 FR-QR-03..05, §5.8, §5.9).

Pure module ``fathom.labels`` (presets, SVG geometry at 300 dpi, text escaping, URLs, CSV, ZIP) and the two
routes ``GET /api/v2/labels/presets`` and ``GET /api/v2/projects/<n>/labels/devices``. The ZIP tests pass
``png=False`` / ``png=0`` so they never need Chrome.
"""
from __future__ import annotations

import csv
import io
import unittest
import xml.etree.ElementTree as ET
import zipfile

try:
    from _helpers import call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir

SVG_NS = "{http://www.w3.org/2000/svg}"
PRESET_SIZES = {
    "m511-1x0.5": (25.4, 12.7), "m511-1x1": (25.4, 25.4), "m511-1x2": (25.4, 50.8), "m511-0.5x1": (12.7, 25.4),
    "m511-1.9x1": (48.26, 25.4), "m511-cont-1.5": (38.1, 50.8), "m511-cont-1": (25.4, 38.1),
}


def texts(root):
    return [t.text or "" for t in root.iter(SVG_NS + "text")]


class Presets(unittest.TestCase):
    def setUp(self):
        self.L = requires("labels")

    def test_order_default_and_shape(self):
        ps = self.L.presets()
        self.assertEqual([p["id"] for p in ps], list(PRESET_SIZES), fr("FR-QR-03", "3.24", "seven presets in cartridge order"))
        self.assertEqual(self.L.DEFAULT_PRESET, "m511-1x0.5")
        for p in ps:
            self.assertEqual((p["width_mm"], p["height_mm"]), PRESET_SIZES[p["id"]], p["id"])
            self.assertTrue(p["label"] and isinstance(p["parts"], list) and p["parts"], p)
            self.assertIsInstance(p["continuous"], bool)
        self.assertEqual([p["id"] for p in ps if p["continuous"]], ["m511-cont-1.5", "m511-cont-1"])
        self.assertIn("M4-47-422", self.L.PRESETS["m511-1x0.5"]["parts"])


class Svg(unittest.TestCase):
    def setUp(self):
        self.L = requires("labels")
        self.doc = sunday_doc()
        self.dev = [d for d in self.doc["devices"] if d["id"] == "atem-mini"][0]

    def test_root_attributes_for_every_preset(self):
        for pid, (w, hh) in PRESET_SIZES.items():
            with self.subTest(preset=pid):
                root = ET.fromstring(self.L.device_label_svg(self.doc, self.dev, pid, base_url="https://av.example.org"))
                self.assertEqual(root.get("width"), ("%g" % w) + "mm", fr("FR-QR-03", "3.24", "physical width"))
                self.assertEqual(root.get("height"), ("%g" % hh) + "mm")
                vb = [int(float(x)) for x in root.get("viewBox").split()]
                self.assertEqual(vb, [0, 0, round(w * 300 / 25.4), round(hh * 300 / 25.4)], fr("FR-QR-03", "3.24", "viewBox in 300 dpi units"))
                self.assertTrue(root.findall(SVG_NS + "g") and root.find(SVG_NS + "g").find(SVG_NS + "path") is not None, "QR path present")
                self.assertNotIn("http", root.get("style") or "", "no external resources")

    def test_default_preset_is_300_by_150(self):
        root = ET.fromstring(self.L.device_label_svg(self.doc, self.dev))
        self.assertEqual(root.get("viewBox"), "0 0 300 150")
        self.assertEqual((root.get("width"), root.get("height")), ("25.4mm", "12.7mm"))

    def test_qr_fits_inside_the_label(self):
        for pid, (w, hh) in PRESET_SIZES.items():
            svg = self.L.device_label_svg(self.doc, self.dev, pid)
            root = ET.fromstring(svg)
            g = root.find(SVG_NS + "g")
            tr = g.get("transform")
            x, y = [float(v) for v in tr.split("translate(")[1].split(")")[0].split()]
            scale = float(tr.split("scale(")[1].split(")")[0])
            n = max(int(seg.split(" ")[0][1:]) for seg in g.find(SVG_NS + "path").get("d").split("z") if seg.startswith("M")) + 1
            size = (n + 2) * scale  # modules plus one quiet-zone module each side
            W, H = round(w * 300 / 25.4), round(hh * 300 / 25.4)
            self.assertLessEqual(x + size, W + 0.5, pid)
            self.assertLessEqual(y + size, H + 0.5, pid)
            self.assertGreaterEqual(min(x, y), 10, "1.5 mm margin (17.7 units) keeps the QR off the edge")

    def test_text_is_escaped_and_present(self):
        dev = dict(self.dev, name="T&J <mix>", short_code="AB23CD45")
        svg = self.L.device_label_svg(self.doc, dev, base_url="https://av.example.org")
        root = ET.fromstring(svg)  # valid XML
        tx = texts(root)
        self.assertIn("T&J <mix>", tx, "name line (escaped in the markup, intact after parsing)")
        self.assertIn("T&amp;J &lt;mix&gt;", svg)
        self.assertTrue([t for t in tx if "Main" in t or "Sanctuary" in t or t], "room line present")
        mono = [t for t in root.iter(SVG_NS + "text") if "monospace" in (t.get("font-family") or "")]
        self.assertTrue(mono, "code in a monospace font")
        for t in root.iter(SVG_NS + "text"):
            self.assertIn(t.get("font-family"), ("ui-monospace, Menlo, monospace", "system-ui, sans-serif"))
            self.assertEqual(t.get("fill"), "#000", "black on white only")

    def test_code_line_or_device_id(self):
        fmt = getattr(requires("schema"), "format_short_code", None)
        no_code = ET.fromstring(self.L.device_label_svg(self.doc, self.dev))
        self.assertIn("atem-mini", texts(no_code), "without a short code the device id is the big line")
        with_code = ET.fromstring(self.L.device_label_svg(self.doc, dict(self.dev, short_code="AB23CD45")))
        if fmt is None:
            self.assertIn("atem-mini", texts(with_code), "no formatter in this build: the id is printed")
        else:
            self.assertIn(fmt("AB23CD45"), texts(with_code), "the dashed short code is the big line")
            self.assertNotIn("atem-mini", texts(with_code))

    def test_long_name_is_truncated_with_ellipsis(self):
        dev = dict(self.dev, name="A very very long device name that cannot possibly fit on a one inch label at all")
        tx = texts(ET.fromstring(self.L.device_label_svg(self.doc, dev)))
        cut = [t for t in tx if t.endswith("…")]
        self.assertTrue(cut, tx)
        self.assertTrue(all(len(t) < 40 for t in cut), cut)

    def test_url_prefers_the_short_code_route(self):
        f = self.L.label_fields(self.doc, self.dev, "https://av.example.org/", project="sunday")
        self.assertEqual(f["url"], "https://av.example.org/p/sunday/d/atem-mini", fr("FR-QR-03", "3.24", "no code: device page URL"))
        self.assertEqual(f["code"], "")
        self.assertEqual(f["name"], self.dev["name"])
        self.assertEqual(set(f), {"code", "name", "room", "location", "url", "kind", "manufacturer", "model"})
        fc = self.L.label_fields(self.doc, dict(self.dev, short_code="AB23CD45"), "https://av.example.org")
        if getattr(requires("schema"), "format_short_code", None) is None:
            self.assertEqual(fc["url"], "https://av.example.org/p/%s/d/atem-mini" % self.doc["meta"].get("slug", "project"))
        else:
            self.assertEqual(fc["url"], "https://av.example.org/c/AB23CD45", fr("FR-QR-03", "3.24", "/c/<code> with a short code"))
            self.assertEqual(fc["code"], "AB23-CD45")

    def test_room_and_location_names(self):
        doc = dict(self.doc)
        doc["locations"] = [{"id": "foh", "name": "FOH booth", "room": "main"}]
        f = self.L.label_fields(doc, dict(self.dev, location="foh"))
        self.assertEqual(f["location"], "FOH booth", "location ids resolve to names")
        self.assertEqual(f["room"], [r for r in doc["rooms"] if r["id"] == self.dev["room"]][0]["name"])
        self.assertEqual(self.L.label_fields(doc, dict(self.dev, location="under the desk"))["location"], "under the desk", "free text stays")

    def test_bad_preset_raises(self):
        with self.assertRaises(ValueError):
            self.L.device_label_svg(self.doc, self.dev, "avery-5160")


class Selection(unittest.TestCase):
    def setUp(self):
        self.L = requires("labels")
        self.doc = sunday_doc()

    def test_default_all_sorted_by_room_then_name(self):
        devs = self.L.select_devices(self.doc)
        self.assertEqual(len(devs), len([d for d in self.doc["devices"] if not d.get("auto")]))
        rooms = {r["id"]: r["name"] for r in self.doc["rooms"]}
        keys = [(not d.get("room"), rooms.get(d.get("room"), "").lower(), (d.get("name") or d["id"]).lower()) for d in devs]
        self.assertEqual(keys, sorted(keys))

    def test_ids_room_and_status(self):
        ids = self.L.select_devices(self.doc, ids="samsung-tv-1,atem-mini,ghost")
        self.assertEqual([d["id"] for d in ids], ["samsung-tv-1", "atem-mini"], "explicit order kept, unknown ids dropped")
        self.assertEqual([d["id"] for d in self.L.select_devices(self.doc, ids=["atem-mini"])], ["atem-mini"])
        room = self.doc["devices"][0]["room"]
        self.assertTrue(all(d["room"] == room for d in self.L.select_devices(self.doc, room=room)))
        spare = self.L.select_devices(self.doc, state="spare")
        self.assertTrue(spare and all(d.get("status") == "spare" for d in spare))
        self.assertTrue(all((d.get("status") or "installed") == "installed" for d in self.L.select_devices(self.doc, state="installed")))


class CsvZipSheet(unittest.TestCase):
    def setUp(self):
        self.L = requires("labels")
        self.doc = sunday_doc()
        self.devs = self.L.select_devices(self.doc, ids="atem-mini,samsung-tv-1")

    def test_csv_header_and_crlf(self):
        text = self.L.labels_csv(self.doc, self.devs, "https://av.example.org", project="sunday")
        self.assertTrue(text.endswith("\r\n"))
        self.assertEqual(text.count("\r\n"), 3, "header + two rows, CRLF")
        self.assertNotIn("\n", text.replace("\r\n", ""), "no bare LF (RFC 4180)")
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], ["device_id", "short_code", "name", "room", "location", "url", "kind", "manufacturer", "model"], fr("FR-QR-04", "3.24"))
        self.assertEqual(rows[1][0], "atem-mini")
        self.assertEqual(rows[1][5], "https://av.example.org/p/sunday/d/atem-mini")

    def test_zip_members(self):
        data = self.L.labels_zip(self.doc, self.devs, "m511-1x1", "https://av.example.org", project="sunday", png=False)
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        self.assertEqual(sorted(names), ["README.txt", "atem-mini.svg", "labels.csv", "samsung-tv-1.svg"], fr("FR-QR-04", "3.24", "zip members"))
        readme = zf.read("README.txt").decode("utf-8")
        self.assertIn("m511-1x1", readme)
        self.assertIn("25.4×25.4 mm", readme)
        self.assertIn("Brady Express Labels or Brady Workstation", readme)
        self.assertIn("100 %", readme)
        root = ET.fromstring(zf.read("atem-mini.svg"))
        self.assertEqual(root.get("viewBox"), "0 0 300 300")
        self.assertTrue(zf.read("labels.csv").startswith(b"device_id,short_code,"))

    def test_sheet_html(self):
        page = self.L.label_sheet_html(self.doc, self.devs, "m511-1.9x1", "https://av.example.org", "Test sheet")
        self.assertIn("<title>Test sheet</title>", page)
        self.assertIn("@page { margin: 10mm; }", page)
        self.assertIn("break-inside: avoid", page)
        self.assertIn("Print at 100 % — 1.9″ × 1″ die-cut (48.26×25.4 mm)", page)
        self.assertEqual(page.count('<div class="label"'), 2)
        self.assertEqual(page.count("<svg "), 2, "inline SVGs at true size")
        self.assertIn('width="48.26mm" height="25.4mm"', page)
        self.assertIn('data-labels="2"', page)
        low = page.lower()
        self.assertNotIn("<script", low, "CSP_FILES: no scripts")
        self.assertNotIn("<link", low, "CSP_FILES: no external resources")
        self.assertNotIn("@import", low)
        self.assertNotIn("url(", low)
        self.assertNotIn("No devices match", page)
        self.assertIn("No devices match", self.L.label_sheet_html(self.doc, [], "m511-1x0.5"))


class Routes(unittest.TestCase):
    def setUp(self):
        requires("labels")
        self.app = get_app()
        self._ctx = temp_data_dir()
        self.data = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        install_sunday(self.data, "sunday-demo")
        self.base = "/api/v2/projects/sunday-demo/labels/devices"

    def get(self, path, headers=None):
        return call(self.app, "GET", path, None, headers or {})

    def test_presets_route(self):
        st, h, b = self.get("/api/v2/labels/presets")
        self.assertEqual(st, 200, b[:200])
        j = jbody(b)
        self.assertEqual(j["default"], "m511-1x0.5")
        self.assertEqual([p["id"] for p in j["presets"]], list(PRESET_SIZES), fr("FR-QR-03", "5.8"))
        self.assertEqual(j["presets"][0]["parts"], ["M4-47-422", "M4-47-483", "M5-17-351"])

    def test_html_sheet_default(self):
        st, h, b = self.get(self.base)
        self.assertEqual(st, 200, b[:200])
        self.assertTrue(h.get("content-type", "").startswith("text/html"))
        self.assertIn("script-src 'self' 'unsafe-inline'", h.get("content-security-policy", ""), "viewer page CSP like the labels schedule")
        page = b.decode("utf-8")
        n = len([d for d in sunday_doc()["devices"] if not d.get("auto")])
        self.assertIn('data-labels="%d"' % n, page, "all devices by default")
        self.assertIn('data-preset="m511-1x0.5"', page)
        st, h, b = self.get(self.base + "?format=csv&devices=atem-mini")
        self.assertIn(b"http://127.0.0.1/p/sunday-demo/d/atem-mini", b, fr("FR-EXP-04", "5.8", "QR URL from the request's public base and the project name"))
        st, h, b = self.get(self.base + "?preset=m511-1x2&devices=atem-mini,samsung-tv-1")
        self.assertEqual(st, 200)
        self.assertIn('data-labels="2"', b.decode("utf-8"))
        self.assertIn('width="25.4mm" height="50.8mm"', b.decode("utf-8"))
        st, h, b = self.get(self.base + "?room=main")
        self.assertEqual(st, 200)
        st, h, b = self.get(self.base + "?room=nope")
        self.assertEqual(st, 404)

    def test_csv_route(self):
        st, h, b = self.get(self.base + "?format=csv&devices=atem-mini")
        self.assertEqual(st, 200, b[:200])
        self.assertTrue(h.get("content-type", "").startswith("text/csv"))
        self.assertEqual(h.get("content-disposition"), 'attachment; filename="device-labels.csv"')
        self.assertEqual(b.split(b"\r\n")[0], b"device_id,short_code,name,room,location,url,kind,manufacturer,model")
        self.assertEqual(b.count(b"\r\n"), 2)

    def test_zip_route(self):
        st, h, b = self.get(self.base + "?format=zip&preset=m511-0.5x1&devices=atem-mini,samsung-tv-1&png=0")
        self.assertEqual(st, 200, b[:200])
        self.assertEqual(h.get("content-type"), "application/zip")
        self.assertEqual(h.get("content-disposition"), 'attachment; filename="device-labels-m511-0.5x1.zip"')
        names = sorted(zipfile.ZipFile(io.BytesIO(b)).namelist())
        self.assertEqual(names, ["README.txt", "atem-mini.svg", "labels.csv", "samsung-tv-1.svg"])

    def test_svg_route_needs_exactly_one_device(self):
        st, h, b = self.get(self.base + "?format=svg&devices=atem-mini&preset=m511-1x1")
        self.assertEqual(st, 200, b[:200])
        self.assertTrue(h.get("content-type", "").startswith("image/svg+xml"))
        self.assertEqual(h.get("content-security-policy"), "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox")
        root = ET.fromstring(b)
        self.assertEqual(root.get("viewBox"), "0 0 300 300")
        self.assertEqual(root.get("data-device"), "atem-mini")
        for bad in ("?format=svg", "?format=svg&devices=atem-mini,samsung-tv-1", "?format=svg&devices=ghost"):
            st, h, b = self.get(self.base + bad)
            self.assertEqual(st, 400, bad)

    def test_bad_preset_and_format(self):
        st, h, b = self.get(self.base + "?preset=avery-5160")
        self.assertEqual(st, 400)
        self.assertEqual(jbody(b)["error"], "bad_preset", fr("FR-QR-04", "5.8"))
        self.assertEqual(jbody(b)["code"], "bad_preset")
        st, h, b = self.get(self.base + "?format=pdf")
        self.assertEqual(st, 400)
        st, h, b = self.get("/api/v2/projects/ghost/labels/devices")
        self.assertEqual(st, 404)

    def test_viewer_role_allowed(self):
        users = requires("users")
        users.add_user("vic", "vic-password-1", role="viewer")
        st, h, b = call(self.app, "POST", "/api/v2/session", {"username": "vic", "password": "vic-password-1"}, {"Content-Type": "application/json"})
        self.assertEqual(st, 200, b[:200])
        cookie = [c for c in h.all("set-cookie") if c.startswith("fathom_session=")][0].split(";")[0]
        st, _, b = self.get("/api/v2/labels/presets")
        self.assertEqual(st, 401, "auth on: anonymous is refused")
        st, _, b = self.get("/api/v2/labels/presets", {"Cookie": cookie})
        self.assertEqual(st, 200, fr("FR-QR-04", "5.8", "viewer may list presets"))
        st, _, b = self.get(self.base + "?format=csv&devices=atem-mini", {"Cookie": cookie})
        self.assertEqual(st, 200, fr("FR-QR-04", "5.8", "viewer may download labels"))
        self.assertTrue(b.startswith(b"device_id,"))


class Builds(unittest.TestCase):
    def test_build_writes_device_labels_html(self):
        export = requires("export")
        requires("labels")
        with temp_data_dir() as data:
            pdir = install_sunday(data, "sunday-demo")
            run = export.build_doc("sunday-demo", base_url="https://av.example.org", run_dir=data / "builds" / "sunday-demo" / "run-labels")
            files = sorted(str(p.relative_to(run)) for p in run.rglob("*") if p.is_file())
            self.assertIn("device-labels.html", files, fr("FR-QR-04", "5.9", "build file index"))
            self.assertIn("run-labels/device-labels.html", zipfile.ZipFile(run / "run-labels.zip").namelist())
            page = (run / "device-labels.html").read_text(encoding="utf-8")
            self.assertIn('data-preset="m511-1x0.5"', page)
            self.assertIn("https://av.example.org/p/sunday-demo/d/atem-mini", page)
            self.assertIn("device-labels.html", (run / "index.html").read_text(encoding="utf-8"), "build nav links the sheet")


if __name__ == "__main__":
    unittest.main()
