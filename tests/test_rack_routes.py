"""Rackula rack routes (contract E): viewer rack page, rack QR, totals, Rackula import, rack templates, NetBox device types,
the extended rack SVG and library routes, and the .webp MIME type.

The engines behind these routes are separate modules; these tests inject fakes so they check the server side only
(status codes, roles, revision handling, content types, the arguments handed to the engines)."""

from __future__ import annotations

import contextlib
import mimetypes
import shutil
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

try:
    from _helpers import basic, call, get_app, install_sunday, jbody, requires, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import basic, call, get_app, install_sunday, jbody, requires, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
P = "/api/v2/projects/proj"
TEMPLATE = {"id": "acme-nb-1u", "manufacturer": "Acme", "model": "NB 1U", "kind": "switch", "ru": 1, "full_depth": False,
            "ports": [{"group": "Port", "dir": "io", "medium": "network", "connector": "RJ45", "count": 8}]}


def fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


@contextlib.contextmanager
def engines(**mods):
    """Install fake ``fathom.<name>`` modules (``None`` makes the import fail) for the duration."""
    with mock.patch.dict(sys.modules, {"fathom." + k.replace("__", "."): v for k, v in mods.items()}):
        yield


class Recorder:
    def __init__(self, result=None, exc=None):
        self.calls, self.result, self.exc = [], result, exc

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.result(*args, **kwargs) if callable(self.result) else self.result


class Base(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self._ctx = temp_data_dir()
        self.data = self._ctx.__enter__()
        install_sunday(self.data, "proj")

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def get(self, path, headers=None):
        return call(self.app, "GET", path, headers=headers)

    def post(self, path, body, headers=None):
        return call(self.app, "POST", path, body, dict(JSON_H, **(headers or {})))

    def rev(self):
        return jbody(self.get(P)[2])["revision"]

    def share(self, scope="all"):
        st, _, b = self.post(P + "/shares", {"scope": scope})
        self.assertEqual(st, 201, b)
        return jbody(b)["share"]["token"]

    def assert_501(self, st, b):
        self.assertEqual(st, 501, b[:300])
        self.assertEqual(jbody(b), {"error": "not available", "code": "not_available"})


class ViewerRackPage(Base):
    def page(self):
        return Recorder(lambda doc, project, rack_id, **kw: "<!doctype html><title>%s</title>" % rack_id)

    def test_renders_with_viewer_args(self):
        fake = self.page()
        with engines(render_rack=fake_module("fathom.render_rack", rack_page_html=fake)):
            st, h, b = self.get("/p/proj/rk/rk-foh")
            self.assertEqual(st, 200, b[:300])
            self.assertTrue(h["content-type"].startswith("text/html"))
            self.assertIn("script-src 'self' 'unsafe-inline'", h["content-security-policy"], "viewer CSP")
            self.assertIn(b"rk-foh", b)
            (doc, project, rack_id), kw = fake.calls[-1]
            self.assertEqual((project, rack_id), ("proj", "rk-foh"))
            self.assertEqual(kw, {"base": "/", "share": "", "link_style": "viewer"})
            self.assertTrue(any(r["id"] == "rk-foh" for r in doc["racks"]))
            st, _, _ = self.get("/p/proj/rk/rk-foh", headers={"__script_name__": "/fathom"})
            self.assertEqual(st, 200)
            self.assertEqual(fake.calls[-1][1]["base"], "/fathom/", "base = script root + /")

    def test_share_token(self):
        fake = self.page()
        token = self.share()
        with engines(render_rack=fake_module("fathom.render_rack", rack_page_html=fake)):
            self.assertEqual(self.get("/p/proj/rk/rk-foh?share=" + token)[0], 200)
            self.assertEqual(fake.calls[-1][1]["share"], token, "a valid ?share= token is carried")
            self.assertEqual(self.get("/p/proj/rk/rk-foh?share=sh-not-a-token")[0], 200)
            self.assertEqual(fake.calls[-1][1]["share"], "", "an unknown token is dropped")
            st, _, b = self.get("/s/%s/rk/rk-foh" % token)
            self.assertEqual(st, 200, b[:300])
            self.assertEqual(fake.calls[-1][1]["share"], token, "share-link mirror passes its token")
            sop = self.share("sop")
            self.assertEqual(self.get("/s/%s/rk/rk-foh" % sop)[0], 403, "procedures-only links do not open racks")

    def test_unknown_rack_and_missing_engine(self):
        with engines(render_rack=fake_module("fathom.render_rack", rack_page_html=self.page())):
            self.assertEqual(self.get("/p/proj/rk/rk-nope")[0], 404)
        with engines(render_rack=fake_module("fathom.render_rack", rack_page_html=Recorder(exc=KeyError("rk-foh")))):
            self.assertEqual(self.get("/p/proj/rk/rk-foh")[0], 404, "KeyError from the renderer -> 404")
        with engines(render_rack=None):
            self.assert_501(*self.get("/p/proj/rk/rk-foh")[::2])
            self.assertEqual(self.get("/p/proj/rk/rk-nope")[0], 404, "unknown rack is 404 even without the engine")
        with engines(render_rack=fake_module("fathom.render_rack")):
            self.assert_501(*self.get("/p/proj/rk/rk-foh")[::2])

    def test_public_view_and_auth(self):
        fake = self.page()
        with engines(render_rack=fake_module("fathom.render_rack", rack_page_html=fake)):
            with temp_data_dir(FATHOM_AUTH="root:env-secret-1") as data:
                install_sunday(data, "proj")
                self.assertIn(self.get("/p/proj/rk/rk-foh")[0], (401, 302), "viewer page needs auth")
                self.assertEqual(self.get("/p/proj/rk/rk-foh", basic("root", "env-secret-1"))[0], 200)
            with temp_data_dir(FATHOM_AUTH="root:env-secret-1", FATHOM_PUBLIC_VIEW="1") as data:
                install_sunday(data, "proj")
                self.assertEqual(self.get("/p/proj/rk/rk-foh")[0], 200, "FATHOM_PUBLIC_VIEW opens /p/<n>/rk/<rack>")


class RackSvg(Base):
    def test_new_kwargs_forwarded(self):
        racks = requires("racks")
        fake = Recorder('<svg xmlns="http://www.w3.org/2000/svg"/>')
        with mock.patch.object(racks, "rack_svg", fake):
            st, h, b = self.get(P + "/racks/rk-foh.svg?face=both&images=1&annotate=ip")
            self.assertEqual(st, 200, b[:300])
            self.assertTrue(h["content-type"].startswith("image/svg+xml"))
            self.assertEqual(h["content-security-policy"], "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox")
            self.assertEqual(fake.calls[-1], ((mock.ANY, "rk-foh"), {"face": "both", "images": True, "annotate": "ip", "base_url": ""}))
            self.assertEqual(self.get(P + "/racks/rk-foh.svg")[0], 200)
            self.assertEqual(fake.calls[-1][1], {"face": "front", "images": False, "annotate": None, "base_url": ""})
            self.assertEqual(self.get(P + "/racks/rk-foh.svg?face=side")[0], 400)
            self.assertEqual(self.get(P + "/racks/rk-foh.svg?annotate=nope")[0], 400)
            self.assertEqual(self.get(P + "/racks/rk-nope.svg")[0], 404)

    def test_old_engine_fallback(self):
        racks = requires("racks")
        seen = []

        def old(doc, rack_id, face="front", scale=1.0):
            seen.append(face)
            return '<svg xmlns="http://www.w3.org/2000/svg"/>'

        with mock.patch.object(racks, "rack_svg", old):
            st, _, b = self.get(P + "/racks/rk-foh.svg?face=rear&images=1")
            self.assertEqual(st, 200, b[:300])
            self.assertEqual(seen, ["rear"])
            self.assert_501(*self.get(P + "/racks/rk-foh.svg?face=both")[::2])

    def test_real_engine(self):
        for face in ("front", "rear"):
            st, _, b = self.get(P + "/racks/rk-foh.svg?face=" + face)
            self.assertEqual(st, 200, b[:300])
            ET.fromstring(b)


class RackQr(Base):
    def qr_text(self, path):
        qr = requires("qr")
        seen = []
        real = qr.svg

        def spy(text, *a, **k):
            seen.append(text)
            return real(text, *a, **k)

        with mock.patch.object(qr, "svg", spy):
            st, h, b = self.get(path)
        return st, h, b, (seen[-1] if seen else None)

    def test_urls(self):
        st, h, b, url = self.qr_text(P + "/qr/rack/rk-foh.svg")
        self.assertEqual(st, 200, b[:300])
        self.assertTrue(h["content-type"].startswith("image/svg+xml"))
        ET.fromstring(b)
        self.assertEqual(url, "http://127.0.0.1/p/proj/rk/rk-foh")
        token = self.share()
        st, _, _, url = self.qr_text(P + "/qr/rack/rk-foh.svg?share=" + token)
        self.assertEqual((st, url), (200, "http://127.0.0.1/s/%s/rk/rk-foh" % token))
        rev = self.rev()
        st, _, b = self.post(P + "/changes", {"base_revision": rev, "ops": [{"op": "root", "key": "settings", "value": {"public_url": "https://av.example.org/"}}]})
        self.assertEqual(st, 200, b)
        self.assertEqual(self.qr_text(P + "/qr/rack/rk-foh.svg")[3], "https://av.example.org/p/proj/rk/rk-foh", "settings.public_url wins")

    def test_errors(self):
        st, _, b, _ = self.qr_text(P + "/qr/rack/rk-foh.svg?share=sh-unknown")
        self.assertEqual((st, jbody(b)["code"]), (404, "share_missing"))
        st, _, b, _ = self.qr_text(P + "/qr/rack/rk-foh.svg?share=" + self.share("sop"))
        self.assertEqual((st, jbody(b)["code"]), (409, "share_scope"))
        self.assertEqual(self.get(P + "/qr/rack/rk-nope.svg")[0], 404)
        self.assertEqual(self.get(P + "/qr/rack/rk-foh.svg?ecl=Z")[0], 400)
        self.assertEqual(self.get(P + "/qr/atem-mini.svg")[0], 200, "device QR route unchanged")


class RackTotals(Base):
    def test_totals(self):
        racks = requires("racks")
        out = {"units": 12, "used_u": 1, "free_u": 11, "weight_kg": 0, "max_load_kg": None, "power_w": 0, "power_limit_w": None, "devices": 1, "items": 0}
        fake = Recorder(out)
        with mock.patch.object(racks, "rack_totals", fake, create=True):
            st, h, b = self.get(P + "/racks/rk-foh/totals")
            self.assertEqual(st, 200, b[:300])
            self.assertTrue(h["content-type"].startswith("application/json"))
            self.assertEqual(jbody(b), out)
            self.assertEqual(fake.calls[-1][0][1], "rk-foh")
            self.assertEqual(self.get(P + "/racks/rk-nope/totals")[0], 404)
        with mock.patch.object(racks, "rack_totals", None, create=True):
            self.assert_501(*self.get(P + "/racks/rk-foh/totals")[::2])


class RackImport(Base):
    RACK = {"id": "rk-imported", "name": "Imported", "units": 12}

    def preview_fake(self, ops=None, exc=None):
        ops = [{"op": "put", "coll": "racks", "id": "rk-imported", "value": self.RACK}] if ops is None else ops
        return Recorder({"racks": [self.RACK], "devices": [], "items": [], "warnings": ["w1"], "ops": ops}, exc=exc)

    def mod(self, fake):
        return fake_module("fathom.parsers.rackula", preview=fake)

    def test_preview_and_apply(self):
        fake = self.preview_fake()
        rev = self.rev()
        with engines(parsers__rackula=self.mod(fake)):
            st, _, b = self.post(P + "/racks/import", {"text": "racks: []", "base_revision": rev, "ignored": 1})
            self.assertEqual(st, 200, b)
            self.assertEqual(jbody(b)["racks"], [self.RACK])
            self.assertEqual(jbody(b)["warnings"], ["w1"])
            self.assertEqual(fake.calls[-1][0][1], {"text": "racks: []"}, "only text/zip_b64/url reach the parser")
            self.assertEqual(self.rev(), rev, "preview writes nothing")
            st, _, b = self.post(P + "/racks/import", {"url": "https://count.racku.la/?l=abc", "apply": True})
            self.assertEqual((st, jbody(b)["code"]), (428, "precondition_required"))
            st, h, b = self.post(P + "/racks/import", {"zip_b64": "UEsDBA==", "apply": True, "base_revision": rev})
            self.assertEqual(st, 200, b)
            self.assertEqual(jbody(b), {"revision": rev + 1, "applied": 1, "warnings": ["w1"]})
            self.assertEqual(h["etag"], '"r%d"' % (rev + 1))
        doc = jbody(self.get(P)[2])["doc"]
        self.assertTrue(any(r["id"] == "rk-imported" for r in doc["racks"]))
        newest = jbody(self.get(P + "/history")[2])["revisions"][0]
        self.assertEqual((newest["revision"], newest["summary"]), (rev + 1, "Import from Rackula"))

    def test_conflict(self):
        rev = self.rev()
        st, _, b = self.post(P + "/changes", {"base_revision": rev, "ops": [{"op": "merge", "coll": "racks", "id": "rk-foh", "value": {"name": "Moved"}}]})
        self.assertEqual(st, 200, b)
        fake = self.preview_fake([{"op": "merge", "coll": "racks", "id": "rk-foh", "value": {"notes": "x"}}])
        with engines(parsers__rackula=self.mod(fake)):
            st, _, b = self.post(P + "/racks/import", {"text": "x", "apply": True, "base_revision": rev})
            self.assertEqual(st, 409, b)
            self.assertEqual(jbody(b)["code"], "conflict")
            st, _, b = self.post(P + "/racks/import", {"text": "x", "apply": True, "base_revision": rev + 1})
            self.assertEqual(st, 200, b)
            self.assertEqual(jbody(b)["revision"], rev + 2)

    def test_errors(self):
        with engines(parsers__rackula=self.mod(self.preview_fake(exc=ValueError("line 3: anchors are not supported")))):
            st, _, b = self.post(P + "/racks/import", {"text": "a: &x 1"})
            self.assertEqual((st, jbody(b)["code"]), (422, "invalid"))
            self.assertIn("line 3", jbody(b)["error"])
            self.assertEqual(self.post(P + "/racks/import", {})[0], 400)
        with engines(parsers__rackula=self.mod(self.preview_fake(ops=[]))):
            rev = self.rev()
            st, _, b = self.post(P + "/racks/import", {"text": "x", "apply": True, "base_revision": rev})
            self.assertEqual(jbody(b), {"revision": rev, "applied": 0, "warnings": ["w1"]}, "nothing to apply -> no new revision")
        with engines(parsers__rackula=None):
            self.assert_501(*self.post(P + "/racks/import", {"text": "x"})[::2])
        self.assertEqual(self.post("/api/v2/projects/nope/racks/import", {"text": "x"})[0], 404)


class RackTemplates(Base):
    def fakes(self, exc=None):
        listing = Recorder([{"id": "church-audio-12u", "name": "Church audio", "description": "", "units": 12, "width_in": 19, "form_factor": "cabinet"}])

        def ops(doc, template, name="", room="", location=""):
            return {"ops": [{"op": "put", "coll": "racks", "id": "rk-new", "value": {"id": "rk-new", "name": name or "New", "units": 12, "room": room,
                                                                                  "location": location}}], "rack_id": "rk-new"}

        return listing, Recorder(ops, exc=exc)

    def test_list_and_apply(self):
        listing, apply = self.fakes()
        with engines(rack_templates=fake_module("fathom.rack_templates", list_templates=listing, apply_ops=apply)):
            st, _, b = self.get("/api/v2/rack-templates")
            self.assertEqual(st, 200, b)
            self.assertEqual(jbody(b)["templates"][0]["id"], "church-audio-12u")
            rev = self.rev()
            body = {"template": "church-audio-12u", "name": "FOH 2", "room": "main", "location": "booth", "base_revision": rev}
            st, h, b = self.post(P + "/racks/from-template", body)
            self.assertEqual(st, 201, b)
            self.assertEqual(jbody(b), {"revision": rev + 1, "rack": "rk-new"})
            self.assertEqual(apply.calls[-1][0][1], "church-audio-12u")
            self.assertEqual(apply.calls[-1][1], {"name": "FOH 2", "room": "main", "location": "booth"})
        doc = jbody(self.get(P)[2])["doc"]
        self.assertEqual(next(r for r in doc["racks"] if r["id"] == "rk-new")["name"], "FOH 2")

    def test_errors(self):
        listing, apply = self.fakes(exc=KeyError("nope"))
        with engines(rack_templates=fake_module("fathom.rack_templates", list_templates=listing, apply_ops=apply)):
            rev = self.rev()
            self.assertEqual(self.post(P + "/racks/from-template", {"template": "nope", "base_revision": rev})[0], 404)
            self.assertEqual(self.post(P + "/racks/from-template", {"base_revision": rev})[0], 400)
            self.assertEqual(self.post(P + "/racks/from-template", {"template": "x", "room": "attic", "base_revision": rev})[0], 404)
        _, apply = self.fakes()
        with engines(rack_templates=fake_module("fathom.rack_templates", apply_ops=apply)):
            st, _, b = self.post(P + "/racks/from-template", {"template": "church-audio-12u"})
            self.assertEqual((st, jbody(b)["code"]), (428, "precondition_required"))
            self.assert_501(*self.get("/api/v2/rack-templates")[::2])
        with engines(rack_templates=None):
            self.assert_501(*self.post(P + "/racks/from-template", {"template": "x", "base_revision": 1})[::2])


class NetboxDeviceTypes(Base):
    def mod(self, to=None, frm=None):
        return fake_module("fathom.parsers.netbox_devicetype", to_template=to or Recorder(lambda text: dict(TEMPLATE)),
                           from_template=frm or Recorder(lambda t: "manufacturer: %s\nmodel: %s\n" % (t["manufacturer"], t["model"])))

    def test_import(self):
        with engines(parsers__netbox_devicetype=self.mod()):
            st, _, b = self.post("/api/v2/library/import/netbox", {"text": "manufacturer: Acme\nmodel: NB 1U\n"})
            self.assertEqual(st, 201, b)
            self.assertEqual(jbody(b)["id"], "acme-nb-1u")
        st, _, b = self.get("/api/v2/library/acme-nb-1u")
        self.assertEqual(st, 200)
        self.assertEqual(jbody(b)["source"], "custom")

    def test_import_errors(self):
        builtin = sorted(p.stem for p in (Path(requires("library").__file__).parent / "templates").glob("*.json"))[0]
        clash = Recorder(lambda text: dict(TEMPLATE, id=builtin))
        with engines(parsers__netbox_devicetype=self.mod(to=clash)):
            st, _, b = self.post("/api/v2/library/import/netbox", {"text": "x"})
            self.assertEqual((st, jbody(b)["code"]), (409, "exists"), "built-in id without override")
            self.assertEqual(self.post("/api/v2/library/import/netbox", {"text": "x", "override": True})[0], 201)
        with engines(parsers__netbox_devicetype=self.mod(to=Recorder(exc=ValueError("u_height must be a number")))):
            st, _, b = self.post("/api/v2/library/import/netbox", {"text": "x"})
            self.assertEqual((st, jbody(b)["code"]), (422, "invalid"))
            self.assertEqual(self.post("/api/v2/library/import/netbox", {})[0], 400)
        with engines(parsers__netbox_devicetype=self.mod(to=Recorder(lambda text: dict(TEMPLATE, kind="spaceship")))):
            st, _, b = self.post("/api/v2/library/import/netbox", {"text": "x"})
            self.assertEqual(st, 422)
            self.assertTrue(jbody(b)["details"]["problems"])
        with engines(parsers__netbox_devicetype=None):
            self.assert_501(*self.post("/api/v2/library/import/netbox", {"text": "x"})[::2])

    def test_export(self):
        tid = sorted(p.stem for p in (Path(requires("library").__file__).parent / "templates").glob("*.json"))[0]
        frm = Recorder(lambda t: "model: %s\n" % t["model"])
        with engines(parsers__netbox_devicetype=self.mod(frm=frm)):
            st, h, b = self.get("/api/v2/library/%s/netbox.yaml" % tid)
            self.assertEqual(st, 200, b)
            self.assertTrue(h["content-type"].startswith("application/yaml"))
            self.assertEqual(h["content-disposition"], 'attachment; filename="%s.yaml"' % tid)
            self.assertEqual(frm.calls[-1][0][0]["id"], tid)
            self.assertTrue(b.startswith(b"model: "))
            self.assertEqual(self.get("/api/v2/library/nope-nope/netbox.yaml")[0], 404)
        st, h, b = self.get("/api/v2/library/" + tid)
        self.assertEqual((st, jbody(b)["id"]), (200, tid), "GET /library/<tid> is not shadowed")
        with engines(parsers__netbox_devicetype=None):
            self.assert_501(*self.get("/api/v2/library/%s/netbox.yaml" % tid)[::2])

    def test_routes_do_not_shadow(self):
        server = requires("server")
        for path, handler in (("/api/v2/library/a.b", server.r_library_get), ("/api/v2/library/a.b/netbox.yaml", server.r_library_netbox),
                              ("/api/v2/library/netbox.yaml", server.r_library_get), ("/api/v2/library/suggest", server.r_library_suggest)):
            req = server.Request({"REQUEST_METHOD": "GET", "PATH_INFO": path})
            rt, _ = server._match(req)
            self.assertIs(rt.handler, handler, path)
        req = server.Request({"REQUEST_METHOD": "POST", "PATH_INFO": "/api/v2/library/import/netbox"})
        self.assertIs(server._match(req)[0].handler, server.r_library_import_netbox)


class LibraryKwargs(Base):
    def test_kwargs_forwarded(self):
        library = requires("library")
        fake = Recorder([dict(TEMPLATE, source="catalog", airflow="front-to-rear", rack_category="network", image_front="acme/nb.front.webp",
                              weight_kg=2.5, power_w=30, width="full", depth_mm=250, part_number="NB-1", cost=99)])
        with mock.patch.object(library, "list_templates", lambda q="", discipline="", kind="", doc=None, **kw: fake(q=q, **kw)):
            st, _, b = self.get("/api/v2/library?source=all&ids=a,%20b,,c&rack=1")
            self.assertEqual(st, 200, b)
            self.assertEqual(fake.calls[-1][1], {"q": "", "source": "all", "ids": ["a", "b", "c"], "rack": True})
            self.get("/api/v2/library?q=x")
            self.assertEqual(fake.calls[-1][1], {"q": "x"}, "kwargs only when given")
            self.get("/api/v2/library?rack=0")
            self.assertEqual(fake.calls[-1][1]["rack"], False)
            t = jbody(self.get("/api/v2/library")[2])["templates"][0]
            for k, v in (("full_depth", False), ("airflow", "front-to-rear"), ("rack_category", "network"), ("image_front", "acme/nb.front.webp"),
                         ("weight_kg", 2.5), ("power_w", 30), ("width", "full"), ("depth_mm", 250), ("part_number", "NB-1"), ("source", "catalog")):
                self.assertEqual(t.get(k), v, k)
            self.assertNotIn("image_rear", t, "absent keys stay absent")
            self.assertNotIn("cost", t)
            self.assertNotIn("ports", t)

    def test_old_library_ignores_kwargs(self):
        library = requires("library")
        seen = []

        def old(q="", discipline="", kind="", doc=None):
            seen.append(q)
            return [dict(TEMPLATE)]

        with mock.patch.object(library, "list_templates", old):
            st, _, b = self.get("/api/v2/library?q=nb&source=catalog&ids=a&rack=1")
            self.assertEqual(st, 200, b)
            self.assertEqual(seen, ["nb"])
            self.assertEqual(jbody(b)["templates"][0]["id"], "acme-nb-1u")

    def test_default_listing_unchanged(self):
        st, _, b = self.get("/api/v2/library")
        self.assertEqual(st, 200)
        self.assertTrue(jbody(b)["templates"])


class Webp(Base):
    def test_webp_mime(self):
        server = requires("server")
        self.assertEqual(mimetypes.guess_type("x.front.webp")[0], "image/webp")
        tmp = Path(tempfile.mkdtemp(prefix="fathom-webp-"))
        try:
            (tmp / "rack-images" / "apc").mkdir(parents=True)
            (tmp / "rack-images" / "apc" / "apc-x.front.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
            with mock.patch.object(server, "STATIC_DIR", tmp):
                st, h, b = self.get("/static/rack-images/apc/apc-x.front.webp")
            self.assertEqual(st, 200)
            self.assertEqual(h["content-type"], "image/webp")
            self.assertTrue(b.startswith(b"RIFF"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _has(module, name):
    try:
        mod = __import__("fathom." + module, fromlist=[name])
    except ImportError:
        return False
    return callable(getattr(mod, name, None))


class RealEngines(Base):
    """The same routes over the real engines; each test is skipped until its engine is installed."""

    def test_totals(self):
        if not _has("racks", "rack_totals"):
            self.skipTest("awaiting racks.rack_totals")
        st, _, b = self.get(P + "/racks/rk-foh/totals")
        self.assertEqual(st, 200, b)
        self.assertEqual(jbody(b)["units"], 12)

    def test_viewer_page_and_both_faces(self):
        if not _has("render_rack", "rack_page_html"):
            self.skipTest("awaiting render_rack.rack_page_html")
        st, h, b = self.get("/p/proj/rk/rk-foh")
        self.assertEqual(st, 200, b[:300])
        self.assertIn(b"FOH rack", b)
        st, _, b = self.get(P + "/racks/rk-foh.svg?face=both&images=1")
        if st != 501:
            self.assertEqual(st, 200, b[:300])
            ET.fromstring(b)

    def test_template_roundtrip(self):
        if not _has("rack_templates", "apply_ops"):
            self.skipTest("awaiting rack_templates")
        tid = jbody(self.get("/api/v2/rack-templates")[2])["templates"][0]["id"]
        st, _, b = self.post(P + "/racks/from-template", {"template": tid, "room": "main", "base_revision": self.rev()})
        self.assertEqual(st, 201, b)
        rid = jbody(b)["rack"]
        self.assertTrue(any(r["id"] == rid for r in jbody(self.get(P)[2])["doc"]["racks"]))

    def test_netbox_roundtrip(self):
        if not _has("parsers.netbox_devicetype", "to_template"):
            self.skipTest("awaiting parsers.netbox_devicetype")
        yaml = "manufacturer: Acme\nmodel: NB 24\nslug: acme-nb-24\nu_height: 1\ninterfaces:\n  - name: eth1\n    type: 1000base-t\n"
        st, _, b = self.post("/api/v2/library/import/netbox", {"text": yaml})
        self.assertEqual(st, 201, b)
        tid = jbody(b)["id"]
        st, h, b = self.get("/api/v2/library/%s/netbox.yaml" % tid)
        self.assertEqual(st, 200, b)
        self.assertIn(b"NB 24", b)


class Roles(unittest.TestCase):
    def test_viewer_cannot_post(self):
        users = requires("users")
        app = get_app()
        listing = Recorder([])
        mods = {"render_rack": fake_module("fathom.render_rack", rack_page_html=Recorder("<!doctype html>")),
                "rack_templates": fake_module("fathom.rack_templates", list_templates=listing,
                                              apply_ops=Recorder({"ops": [{"op": "put", "coll": "racks", "id": "rk-t", "value": {"id": "rk-t", "name": "T", "units": 6}}],
                                                                  "rack_id": "rk-t"})),
                "parsers__rackula": fake_module("fathom.parsers.rackula", preview=Recorder({"racks": [], "devices": [], "items": [], "warnings": [], "ops": []})),
                "parsers__netbox_devicetype": fake_module("fathom.parsers.netbox_devicetype", to_template=Recorder(lambda text: dict(TEMPLATE)))}
        with temp_data_dir() as data, engines(**mods):
            install_sunday(data, "proj")
            users.add_user("vic", "vic-password-1", role="viewer")
            users.add_user("eve", "eve-password-1", role="editor")
            vic, eve = basic("vic", "vic-password-1"), basic("eve", "eve-password-1")
            posts = ((P + "/racks/import", {"text": "x"}), (P + "/racks/from-template", {"template": "t", "base_revision": 1}),
                     ("/api/v2/library/import/netbox", {"text": "x"}))
            for path, body in posts:
                st, _, b = call(app, "POST", path, body, dict(JSON_H, **vic))
                self.assertEqual(st, 403, "viewer POST %s -> %s" % (path, st))
                st, _, b = call(app, "POST", path, body, dict(JSON_H, **eve))
                self.assertIn(st, (200, 201), "editor POST %s -> %s %s" % (path, st, b[:200]))
                self.assertEqual(call(app, "POST", path, body, JSON_H)[0], 401)
            for path in ("/p/proj/rk/rk-foh", P + "/qr/rack/rk-foh.svg", "/api/v2/rack-templates"):
                self.assertEqual(call(app, "GET", path, headers=vic)[0], 200, path)


if __name__ == "__main__":
    unittest.main()
