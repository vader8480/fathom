"""HTTP API contract (SPEC §5): every route group, status codes, shapes, concurrency, v1 routes, PWA, OpenAPI."""

from __future__ import annotations

import copy
import csv
import io
import json
import re
import struct
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from _helpers import (CAMPUS_DIR, FIXTURES, RRC_DIR, call, fixture_path, fr, get_app, has, install_campus, install_project,
                          install_rrc, install_sunday, jbody, jpg_bytes, load_fixture, png_bytes, read_json, requires, sunday_doc,
                          temp_data_dir, temp_env, uniq, upload)
except ImportError:  # pragma: no cover
    from tests._helpers import (CAMPUS_DIR, FIXTURES, RRC_DIR, call, fixture_path, fr, get_app, has, install_campus, install_project,
                                install_rrc, install_sunday, jbody, jpg_bytes, load_fixture, png_bytes, read_json, requires, sunday_doc,
                                temp_data_dir, temp_env, uniq, upload)

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}

PATCH_LABELS = ["Room", "Device", "Section", "Dir", "Port", "Label", "Peer device", "Peer port", "Cable", "Medium", "Source"]
SCHEDULE_KEYS = {
    "patch": ["room", "device", "section", "dir", "port", "label", "peer_device", "peer_port", "cable_tag", "medium", "source"],
    "cables": ["tag", "from_room", "from_device", "from_port", "to_room", "to_device", "to_port", "medium", "type", "length", "length_unit",
               "color", "channels", "signal", "status", "bundle", "note", "id"],
    "ip": ["room", "device", "interface", "role", "ip", "prefix", "gateway", "vlan", "network", "mac", "hostname", "switch", "switch_port",
           "protocol", "dhcp", "source", "note"],
    "dmx": ["universe", "address", "end", "footprint", "device", "room", "mode", "channel", "protocol", "sacn_group", "artnet", "source"],
    "bom": ["category", "manufacturer", "model", "template", "qty", "unit_cost", "extended", "currency", "planned", "installed", "spare", "retired"],
    "inventory": ["id", "name", "room", "location", "kind", "discipline", "manufacturer", "model", "status", "serial", "asset_tag", "firmware",
                  "purchase_date", "warranty_until", "vendor", "cost", "currency", "po", "rack", "ru", "ips", "notes"],
    "racks": ["rack", "room", "units", "face", "u", "height", "side", "device", "model"],
}
CABLE_LABELS = ["Tag", "From room", "From device", "From port", "To room", "To device", "To port", "Medium", "Type", "Length", "Unit", "Color",
                "Channels", "Signal", "Status", "Bundle", "Note", "Id"]


def tiny_pdf() -> bytes:
    """A valid one-page PDF (letter, a filled rectangle) with a correct xref table."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Contents 4 0 R /Resources << >> >>"]
    stream = b"0.2 0.4 0.8 rg 10 10 180 80 re f"
    objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def big_doc(devices=150, cables=600):
    """Deterministic valid v2 doc with N devices / M cables (stand-in for fixture-gen 150/600)."""
    d = sunday_doc()
    d["devices"], d["cables"] = [], []
    for i in range(devices):
        d["devices"].append({"id": "d%03d" % i, "name": "Device %d" % i, "kind": "stage_io", "room": "main",
                             "ports": [{"id": "in-%d" % k, "name": "In %d" % k, "dir": "in", "medium": "analog", "group": "In"} for k in range(1, 9)]
                             + [{"id": "out-%d" % k, "name": "Out %d" % k, "dir": "out", "medium": "analog", "group": "Out"} for k in range(1, 9)]})
    n = 0
    for i in range(devices):
        for k in range(1, 5):
            if n >= cables:
                break
            j = (i + k) % devices
            d["cables"].append({"id": "c-%05d" % n, "from": {"device": "d%03d" % i, "port": "out-%d" % k},
                                "to": {"device": "d%03d" % j, "port": "in-%d" % k}, "medium": "analog"})
            n += 1
    return d


class ApiCase(unittest.TestCase):
    """Base: fresh data dir per test with the fixture installed as ``sunday-demo``."""

    env = {}

    def setUp(self):
        self.app = get_app()
        self._ctx = temp_data_dir(**self.env)
        self.data = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.name = "sunday-demo"
        install_sunday(self.data, self.name)

    def req(self, method, path, body=None, headers=None):
        h = dict(JSON_H) if body is not None and not isinstance(body, (bytes, str)) else {"X-Fathom": "1"}
        h.update(headers or {})
        return call(self.app, method, path, body, h)

    def ok(self, method, path, body=None, headers=None, status=200):
        st, h, b = self.req(method, path, body, headers)
        self.assertEqual(st, status, "%s %s -> %s %s" % (method, path, st, b[:400]))
        ctype = h.get("content-type", "").split(";")[0].strip()
        return h, (jbody(b) if b and ctype.startswith("application/") and ctype.endswith("json") else b)

    def doc(self, name=None):
        h, j = self.ok("GET", "/api/v2/projects/%s" % (name or self.name))
        return j["doc"], h.get("etag"), j["revision"]

    def change(self, ops, base, name=None, status=200):
        st, h, b = self.req("POST", "/api/v2/projects/%s/changes" % (name or self.name), {"base_revision": base, "ops": ops, "summary": "t1"})
        self.assertEqual(st, status, "changes -> %s %s" % (st, b[:400]))
        return jbody(b)


# ================================================================== meta, schema, library (§5.5)


class MetaAndLibrary(ApiCase):
    def test_meta_v1_and_v2(self):
        vocab = requires("vocab")
        _, m = self.ok("GET", "/api/v2/meta")
        for k in ("version", "vocab", "importers", "plugins_errors", "samples", "capabilities", "auth", "limits", "library_count"):
            self.assertIn(k, m, fr("FR-VOC-04", "5.5", k))
        self.assertEqual(m["vocab"], json.loads(json.dumps(vocab.as_dict())), fr("FR-VOC-04", "5.5", "vocab == vocab.as_dict()"))
        for k in ("chrome", "pdf_rasterizer", "oda", "llm", "secure_context_hint"):
            self.assertIn(k, m["capabilities"], "5.5 capabilities.%s" % k)
        self.assertEqual(set(m["llm"] if "llm" in m else m["capabilities"]["llm"]) >= {"configured", "model"}, True)
        self.assertEqual(m["limits"], {"max_upload_mb": 50, "max_json_mb": 20, "max_backup_mb": 4096}, "5.5 limits defaults")
        self.assertEqual(set(m["auth"]), {"enabled", "public_view"})
        kinds = {i["kind"] for i in m["importers"]}
        self.assertTrue({"yamaha", "dante", "waves"} <= kinds, "FR-IMP-01 legacy importers registered")
        for i in m["importers"]:
            for k in ("kind", "label", "mode", "accepts", "folder", "help"):
                self.assertIn(k, i, "5.5 importer.%s" % k)
        _, v1 = self.ok("GET", "/api/meta")
        for k in ("version", "kinds", "media", "brands", "import_kinds", "default_columns", "samples", "chrome", "auth", "public_view", "max_upload_mb"):
            self.assertIn(k, v1, fr("FR-VOC-04", "5.12", "v1 meta key %s" % k))
        self.assertIsInstance(v1["kinds"], dict)
        self.assertEqual(len(v1["kinds"]), 35, fr("FR-VOC-04", "5.12", "v1 kinds keyed dict, now larger"))
        self.assertEqual(len(v1["media"]), 41)
        self.assertEqual(v1["max_upload_mb"], 50)

    def test_schema_json(self):
        schema = requires("schema")
        h, js = self.ok("GET", "/api/v2/schema.json")
        self.assertEqual(js, json.loads(json.dumps(schema.JSON_SCHEMA)), "5.5 schema.json serves JSON_SCHEMA")

    def test_library_search_rio(self):
        requires("library")
        _, j = self.ok("GET", "/api/v2/library?q=rio")
        ids = [t["id"] for t in j["templates"]]
        self.assertIn("yamaha-rio3224-d2", ids, fr("FR-LIB-03", "3.13"))
        self.assertIn("yamaha-rio1608-d2", ids, fr("FR-LIB-03", "3.13"))
        for t in j["templates"]:
            for k in ("id", "manufacturer", "model", "name", "kind", "discipline", "ru", "ports_summary", "source"):
                self.assertIn(k, t, "5.5 library list item %s" % k)
        rio = [t for t in j["templates"] if t["id"] == "yamaha-rio3224-d2"][0]
        self.assertIn("32", rio["ports_summary"])
        self.assertEqual(rio["source"], "builtin")
        _, t = self.ok("GET", "/api/v2/library/yamaha-rio3224-d2")
        self.assertEqual(t["id"], "yamaha-rio3224-d2")
        self.assertEqual(t["kind"], "stage_io")
        st, _, _ = self.req("GET", "/api/v2/library/nope-not-real")
        self.assertEqual(st, 404)
        _, j = self.ok("GET", "/api/v2/library?discipline=lighting")
        self.assertTrue(j["templates"])
        self.assertTrue(all(t["discipline"] == "lighting" for t in j["templates"]), "5.5 discipline filter")

    def test_custom_template_precedence(self):
        requires("library")
        custom = {"id": "t1-custom-box", "manufacturer": "T1", "model": "Box", "kind": "stage_io",
                  "ports": [{"group": "Analog In", "dir": "in", "medium": "analog", "count": 2}]}
        self.ok("POST", "/api/v2/library", custom, status=201)
        self.assertTrue((self.data / "library" / "t1-custom-box.json").exists(), fr("FR-LIB-04", "5.5", "written to <data>/library"))
        _, t = self.ok("GET", "/api/v2/library/t1-custom-box")
        self.assertEqual(t["model"], "Box")
        builtin = dict(custom, id="qsc-k12-2", model="K12.2 (global custom)")
        st, _, b = self.req("POST", "/api/v2/library", builtin)
        self.assertEqual(st, 409, fr("FR-LIB-04", "5.5", "built-in id without ?override=1 -> 409"))
        self.ok("POST", "/api/v2/library?override=1", builtin, status=201)
        _, t = self.ok("GET", "/api/v2/library/qsc-k12-2")
        self.assertEqual(t["model"], "K12.2 (global custom)", fr("FR-LIB-04", "3.13", "global custom > built-in"))
        doc, etag, rev = self.doc()
        proj_t = dict(custom, id="qsc-k12-2", model="K12.2 (project)")
        self.change([{"op": "put", "coll": "templates", "id": "qsc-k12-2", "value": proj_t}], rev)
        _, t = self.ok("GET", "/api/v2/library/qsc-k12-2?project=%s" % self.name)
        self.assertEqual(t["model"], "K12.2 (project)", fr("FR-LIB-04", "3.13", "project > global custom"))
        _, t = self.ok("GET", "/api/v2/library/qsc-k12-2")
        self.assertEqual(t["model"], "K12.2 (global custom)", fr("FR-LIB-04", "3.13", "project template only in that project"))
        _, lst = self.ok("GET", "/api/v2/library?q=k12&project=%s" % self.name)
        self.assertIn("project", [x["source"] for x in lst["templates"] if x["id"] == "qsc-k12-2"])
        self.ok("DELETE", "/api/v2/library/t1-custom-box", status=204)
        st, _, _ = self.req("DELETE", "/api/v2/library/yamaha-rio3224-d2")
        self.assertEqual(st, 409, "5.5 deleting a built-in -> 409")
        st, _, b = self.req("POST", "/api/v2/library", {"id": "Bad Id!", "manufacturer": "x", "model": "y", "kind": "other", "ports": []})
        self.assertEqual(st, 422, "5.5 invalid template -> 422")


# ================================================================== projects, docs, changes, history (§5.4, §5.6)


class Projects(ApiCase):
    def test_project_crud_shapes(self):
        _, j = self.ok("GET", "/api/v2/projects")
        p = [x for x in j["projects"] if x["name"] == self.name]
        self.assertTrue(p)
        for k in ("name", "org", "title", "schema", "revision", "rooms", "devices", "cables", "updated", "builds", "role"):
            self.assertIn(k, p[0], "5.6 project list item %s" % k)
        self.assertEqual(p[0]["devices"], 12)
        self.assertEqual(p[0]["cables"], 15)
        self.assertEqual(p[0]["schema"], 2)
        _, j = self.ok("POST", "/api/v2/projects", {"name": "fresh", "template": "blank", "org": "Hillside"}, status=201)
        self.assertEqual(j["name"], "fresh")
        self.assertIn("revision", j)
        st, _, b = self.req("POST", "/api/v2/projects", {"name": "fresh", "template": "blank"})
        self.assertEqual((st, jbody(b).get("code")), (409, "exists"), "5.6 duplicate -> 409 exists")
        st, _, _ = self.req("POST", "/api/v2/projects", {"name": "../evil", "template": "blank"})
        self.assertEqual(st, 400, "5.6 bad name -> 400")
        self.ok("POST", "/api/v2/projects", {"name": "rrc-copy", "template": "rrc-littleton"}, status=201)
        h, j = self.ok("GET", "/api/v2/projects/rrc-copy")
        self.assertEqual(j["migrated_from"], 1, "5.6 migrated_from for a v1 sample copy")
        h, j = self.ok("GET", "/api/v2/projects/%s" % self.name)
        for k in ("name", "revision", "doc", "problems", "role", "migrated_from"):
            self.assertIn(k, j, "5.6 GET project %s" % k)
        self.assertIsNone(j["migrated_from"])
        self.assertEqual(h.get("etag"), '"r%d"' % j["revision"], fr("FR-HIST-03", "5.4", "ETag r<rev>"))
        self.assertEqual(h.get("cache-control"), "no-store", "5.1 API responses no-store")
        self.assertEqual(j["role"], "admin", "auth off = admin")
        st, _, _ = self.req("GET", "/api/v2/projects/nope")
        self.assertEqual(st, 404)
        st, _, _ = self.req("DELETE", "/api/v2/projects/fresh")
        self.assertEqual(st, 400, "5.6 delete without confirm -> 400")
        self.ok("DELETE", "/api/v2/projects/fresh?confirm=fresh")
        st, _, _ = self.req("GET", "/api/v2/projects/fresh")
        self.assertEqual(st, 404)

    def test_doc_download(self):
        h, b = self.ok("GET", "/api/v2/projects/%s/doc.json" % self.name)
        self.assertIn('attachment; filename="%s-project.json"' % self.name, h.get("content-disposition", ""), "5.6 doc.json download")
        d = json.loads(b if isinstance(b, (bytes, str)) else json.dumps(b))
        self.assertEqual(d["fathom"], 2)

    def test_unknown_medium_is_warning(self):
        doc, etag, rev = self.doc()
        cable = {"id": "c-laser", "from": {"device": "atem-mini", "port": "hdmi-out-1"}, "to": {"device": "samsung-tv-1", "port": "hdmi-in-1"}, "medium": "laser"}
        j = self.change([{"op": "put", "coll": "cables", "id": "c-laser", "value": cable}], rev)
        self.assertIn("unknown_medium", [p["code"] for p in j["problems"] if p["level"] == "warning"], fr("FR-VOC-07", "3.2"))
        doc2, _, _ = self.doc()
        self.assertEqual([c for c in doc2["cables"] if c["id"] == "c-laser"][0]["medium"], "laser", "FR-VOC-07 unknown value preserved")

    def test_validation_error_422(self):
        doc, etag, rev = self.doc()
        st, _, b = self.req("POST", "/api/v2/projects/%s/changes" % self.name,
                            {"base_revision": rev, "ops": [{"op": "put", "coll": "devices", "id": "x", "value": {"id": "x", "kind": "other", "ports": "nope"}}]})
        self.assertEqual(st, 422, "4.7 errors block writes")
        j = jbody(b)
        self.assertEqual(j["code"], "invalid")
        self.assertTrue(j["details"]["problems"])
        _, _, rev2 = self.doc()
        self.assertEqual(rev2, rev, "rejected write creates no revision")
        st, _, b = self.req("POST", "/api/v2/projects/%s/changes" % self.name,
                            {"base_revision": rev, "ops": [{"op": "merge", "coll": "devices", "id": "ghost", "value": {"name": "G"}}]})
        self.assertEqual(st, 409, "4.9 merge into missing entity -> 409 conflict class")
        ops = [{"op": "merge", "coll": "devices", "id": "atem-mini", "value": {"note": str(i)}} for i in range(2001)]
        st, _, _ = self.req("POST", "/api/v2/projects/%s/changes" % self.name, {"base_revision": rev, "ops": ops})
        self.assertTrue(400 <= st < 500, "5.6 more than 2000 ops is rejected (got %s)" % st)

    def test_put_requires_if_match(self):
        doc, etag, rev = self.doc()
        doc["devices"][5]["note"] = "put"
        st, _, b = self.req("PUT", "/api/v2/projects/%s" % self.name, {"doc": doc})
        self.assertEqual(st, 428, fr("FR-HIST-03", "5.4", "PUT without If-Match/base_revision"))
        self.assertEqual(jbody(b)["code"], "precondition_required")
        h, j = self.ok("PUT", "/api/v2/projects/%s" % self.name, {"doc": doc, "summary": "via if-match"}, headers={"If-Match": etag})
        self.assertEqual(j["revision"], rev + 1, fr("FR-HIST-03", "5.4"))
        self.assertIs(j["rebased"], False)
        self.assertIn("problems", j)
        doc2, etag2, rev2 = self.doc()
        self.assertEqual(etag2, '"r%d"' % (rev + 1))
        doc2["devices"][5]["note"] = "put2"
        h, j = self.ok("PUT", "/api/v2/projects/%s" % self.name, {"doc": doc2, "base_revision": rev2})
        self.assertEqual(j["revision"], rev2 + 1, fr("FR-HIST-03", "5.4", "body base_revision accepted"))
        st, _, b = self.req("PUT", "/api/v2/projects/%s" % self.name, {"doc": doc2}, headers={"If-Match": '"r%d"' % (rev2 + 50)})
        self.assertEqual(st, 409, fr("FR-HIST-04", "5.4", "base > cur -> 409"))

    def test_stale_put_rebase_and_conflict(self):
        doc0, etag0, rev0 = self.doc()
        a = copy.deepcopy(doc0)
        a["devices"][5]["note"] = "client A"
        self.ok("PUT", "/api/v2/projects/%s" % self.name, {"doc": a}, headers={"If-Match": etag0})
        b = copy.deepcopy(doc0)
        b["devices"][9]["note"] = "client B"
        _, j = self.ok("PUT", "/api/v2/projects/%s" % self.name, {"doc": b}, headers={"If-Match": etag0})
        self.assertIs(j["rebased"], True, fr("FR-HIST-04", "5.4", "disjoint stale PUT is rebased"))
        self.assertEqual(j["revision"], rev0 + 2)
        final, _, _ = self.doc()
        notes = {d["id"]: d.get("note") for d in final["devices"]}
        self.assertEqual(notes["atem-mini"], "client A", fr("FR-HIST-04", "5.4", "rebase keeps the other client's change"))
        self.assertEqual(notes["samsung-tv-1"], "client B")
        c = copy.deepcopy(doc0)
        c["devices"][5]["note"] = "client C"
        st, _, body = self.req("PUT", "/api/v2/projects/%s" % self.name, {"doc": c}, headers={"If-Match": etag0})
        self.assertEqual(st, 409, fr("FR-HIST-04", "5.4", "intersecting stale PUT -> 409"))
        err = jbody(body)
        self.assertEqual(err["code"], "conflict")
        self.assertIn("devices/atem-mini", err["details"]["conflicts"])
        self.assertNotIn("devices/samsung-tv-1", err["details"]["conflicts"], "5.4 T_client computed against the base doc")
        self.assertEqual(err["details"]["revision"], rev0 + 2)
        self.assertIn("by", err["details"])

    def test_changes_rebase_and_conflict(self):
        doc0, etag0, rev0 = self.doc()
        self.change([{"op": "merge", "coll": "devices", "id": "atem-mini", "value": {"note": "A"}}], rev0)
        j = self.change([{"op": "merge", "coll": "devices", "id": "restream", "value": {"note": "B"}}], rev0)
        self.assertIs(j["rebased"], True, fr("FR-HIST-05", "5.4"))
        self.assertEqual(j["touched"], ["devices/restream"])
        j = self.change([{"op": "merge", "coll": "devices", "id": "atem-mini", "value": {"note": "C"}}], rev0, status=409)
        self.assertEqual(j["code"], "conflict", fr("FR-HIST-05", "5.4"))
        self.assertEqual(j["details"]["conflicts"], ["devices/atem-mini"])
        st, _, b = self.req("POST", "/api/v2/projects/%s/changes" % self.name, {"ops": []})
        self.assertIn(st, (400, 428), "5.4 /changes requires base_revision")
        final, _, rev = self.doc()
        self.assertEqual({d["id"]: d.get("note") for d in final["devices"]}["atem-mini"], "A")
        self.assertEqual(rev, rev0 + 2)

    def test_history_entries(self):
        _, _, rev = self.doc()
        rev = self.change([{"op": "merge", "coll": "devices", "id": "atem-mini", "value": {"note": "prime"}}], rev)["revision"]
        _, h0 = self.ok("GET", "/api/v2/projects/%s/history" % self.name)
        n0 = len(h0["revisions"])
        for i in range(3):
            rev = self.change([{"op": "merge", "coll": "devices", "id": "atem-mini", "value": {"note": "w%d" % i}}], rev)["revision"]
        _, h = self.ok("GET", "/api/v2/projects/%s/history" % self.name)
        self.assertEqual(len(h["revisions"]) - n0, 3, fr("FR-HIST-01", "3.19", "three writes -> three history entries"))
        top = h["revisions"][0]
        self.assertEqual(top["revision"], rev, "newest first")
        for k in ("revision", "time", "author", "summary", "source", "touched"):
            self.assertIn(k, top, fr("FR-HIST-01", "4.10", k))
        self.assertEqual(top["source"], "changes")
        self.assertEqual(top["author"], "local", "auth off acts as admin 'local'")
        self.assertEqual(top["touched"], ["devices/atem-mini"])
        self.assertTrue(re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", top["time"]))
        _, h2 = self.ok("GET", "/api/v2/projects/%s/history?limit=2" % self.name)
        self.assertEqual(len(h2["revisions"]), 2)
        _, h3 = self.ok("GET", "/api/v2/projects/%s/history?before=%d" % (self.name, rev))
        self.assertTrue(all(x["revision"] < rev for x in h3["revisions"]))
        _, one = self.ok("GET", "/api/v2/projects/%s/history/%d" % (self.name, rev - 1))
        self.assertEqual(one["revision"], rev - 1)
        self.assertIn("entry", one)
        self.assertEqual({d["id"]: d.get("note") for d in one["doc"]["devices"]}["atem-mini"], "w1")
        st, _, b = self.req("GET", "/api/v2/projects/%s/history/%d" % (self.name, rev + 100))
        self.assertEqual(st, 404)

    def test_restore_revision(self):
        _, _, rev = self.doc()
        r1 = self.change([{"op": "merge", "coll": "devices", "id": "atem-mini", "value": {"note": "one"}}], rev)["revision"]
        _, snap = self.ok("GET", "/api/v2/projects/%s/history/%d" % (self.name, r1))
        r2 = self.change([{"op": "merge", "coll": "devices", "id": "atem-mini", "value": {"note": "two"}},
                          {"op": "del", "coll": "cables", "id": "c-0015"}], r1)["revision"]
        _, j = self.ok("POST", "/api/v2/projects/%s/history/%d/restore" % (self.name, r1), {"base_revision": r2})
        self.assertEqual(j["revision"], r2 + 1, fr("FR-HIST-02", "5.6", "restore creates a new revision"))
        now, _, rev_now = self.doc()
        a = dict(now)
        b = dict(snap["doc"])
        a.pop("revision", None)
        b.pop("revision", None)
        self.assertEqual(a, b, fr("FR-HIST-02", "3.19", "restored doc equals rev content except revision"))
        _, h = self.ok("GET", "/api/v2/projects/%s/history?limit=1" % self.name)
        self.assertEqual(h["revisions"][0]["source"], "restore")
        self.assertEqual(h["revisions"][0]["summary"], "Restored revision %d" % r1)

    def test_history_diff(self):
        _, _, rev = self.doc()
        r1 = self.change([{"op": "merge", "coll": "devices", "id": "atem-mini", "value": {"note": "x"}},
                          {"op": "put", "coll": "devices", "id": "new-dev", "value": {"id": "new-dev", "name": "New", "kind": "other", "room": "main", "ports": []}}], rev)["revision"]
        _, d = self.ok("GET", "/api/v2/projects/%s/history/%d/diff?against=%d" % (self.name, r1, rev))
        for k in ("added", "removed", "changed"):
            self.assertIn(k, d, fr("FR-HIST-07", "5.6", k))
        self.assertIn("devices/atem-mini", d["changed"], fr("FR-HIST-07", "5.6", "changed device id"))
        self.assertIn("devices/new-dev", d["added"] + d["removed"])

    def test_overlay_and_offline_manifest(self):
        requires("merge:build_overlay")
        h, o = self.ok("GET", "/api/v2/projects/%s/overlay" % self.name)
        for k in ("revision", "imports_hash", "devices", "detail", "routes", "port_labels", "interfaces", "dmx", "notes"):
            self.assertIn(k, o, "4.11 overlay key %s" % k)
        self.assertTrue(re.match(r'^"r\d+-[0-9a-f]*"$', h.get("etag", "")), "5.6 overlay ETag r<rev>-<imports_hash>: %r" % h.get("etag"))
        _, m = self.ok("GET", "/api/v2/projects/%s/offline-manifest" % self.name)
        urls = m["urls"]
        for u in ("p/%s" % self.name, "p/%s/rooms" % self.name, "p/%s/r/main" % self.name, "p/%s/r/main/patch" % self.name,
                  "p/%s/d/atem-mini" % self.name, "api/v2/projects/%s" % self.name, "api/v2/meta"):
            self.assertIn(u, urls, fr("FR-MOB-06", "5.6", u))
        self.assertFalse([u for u in urls if u.startswith("/") or "://" in u], "5.6 offline-manifest URLs are relative")

    def test_perf_soft_targets(self):
        """§8.2 soft timings: warn above target, fail above 1000 ms (overlay: 4.5 s)."""
        name = uniq("big")
        install_project(self.data, name, doc=big_doc())
        t = time.perf_counter()
        h, j = self.ok("GET", "/api/v2/projects/%s" % name)
        ms = (time.perf_counter() - t) * 1000
        if ms > 200:
            sys.stderr.write("\n[T1 soft] GET 150/600 doc took %.0f ms (target 200)\n" % ms)
        self.assertLess(ms, 1000, "8.2 GET /api/v2/projects/<n> 150/600 fail above 1000 ms (%.0f)" % ms)
        rev = j["revision"]
        ops = [{"op": "merge", "coll": "devices", "id": "d%03d" % i, "value": {"note": "n"}} for i in range(10)]
        t = time.perf_counter()
        self.change(ops, rev, name=name)
        ms = (time.perf_counter() - t) * 1000
        if ms > 150:
            sys.stderr.write("\n[T1 soft] POST changes (10 ops, 150/600) took %.0f ms (target 150)\n" % ms)
        self.assertLess(ms, 1000, "8.2 POST changes 10 ops fail above 1000 ms (%.0f)" % ms)
        if has("merge:build_overlay"):
            install_rrc(self.data, "rrc-perf")
            t = time.perf_counter()
            self.ok("GET", "/api/v2/projects/rrc-perf/overlay")
            ms = (time.perf_counter() - t) * 1000
            if ms > 1500:
                sys.stderr.write("\n[T1 soft] RRC overlay cold took %.0f ms (target 1500)\n" % ms)
            self.assertLess(ms, 4500, "8.2 RRC overlay cold (%.0f ms)" % ms)
            t = time.perf_counter()
            self.ok("GET", "/api/v2/projects/rrc-perf/overlay")
            warm = (time.perf_counter() - t) * 1000
            self.assertLess(warm, max(500, ms), "8.2 overlay cached afterwards (%.0f ms)" % warm)


class Shares(ApiCase):
    env = {"FATHOM_AUTH": "root:env-secret-1"}

    def test_share_links(self):
        auth = {"Authorization": "Basic cm9vdDplbnYtc2VjcmV0LTE="}
        st, _, b = self.req("POST", "/api/v2/projects/%s/shares" % self.name, {"label": "t1 share"}, headers=auth)
        self.assertEqual(st, 201, fr("FR-USER-09", "5.6", b[:300]))
        j = jbody(b)
        tok = j["share"]["token"]
        self.assertTrue(re.fullmatch(r"sh-[A-Za-z0-9_-]{22}", tok), "4.2 share token sh-<22 base64url>: %s" % tok)
        self.assertEqual(j["url"], "s/%s/" % tok)
        for k in ("token", "label", "created", "expires", "by"):
            self.assertIn(k, j["share"], "5.6 share %s" % k)
        _, lst = self.ok("GET", "/api/v2/projects/%s/shares" % self.name, headers=auth)
        self.assertIn(tok, [x["token"] for x in lst["shares"]])
        st, _, html = call(self.app, "GET", "/s/%s/" % tok)
        self.assertEqual(st, 200, fr("FR-USER-09", "3.20", "share link is public and mirrors /p/<project>"))
        self.assertIn(b"data-id=", html)
        st, _, _ = call(self.app, "GET", "/s/%s/rooms" % tok)
        self.assertEqual(st, 200, "5.13 /s/<token>/... mirrors /p/<project>/...")
        st, _, _ = call(self.app, "GET", "/api/v2/projects/%s" % self.name)
        self.assertEqual(st, 401, "the API stays private")
        self.ok("DELETE", "/api/v2/projects/%s/shares/%s" % (self.name, tok), headers=auth, status=204)
        st, _, _ = call(self.app, "GET", "/s/%s/" % tok)
        self.assertEqual(st, 404, fr("FR-USER-09", "3.20", "revoked token -> 404"))
        st, _, b = self.req("POST", "/api/v2/projects/%s/shares" % self.name, {"label": "old", "expires": "2001-01-01T00:00:00Z"}, headers=auth)
        self.assertEqual(st, 201)
        st, _, _ = call(self.app, "GET", "/s/%s/" % jbody(b)["share"]["token"])
        self.assertEqual(st, 404, "3.20 expired share -> 404")
        st, _, _ = call(self.app, "GET", "/s/sh-AAAAAAAAAAAAAAAAAAAAAA/")
        self.assertEqual(st, 404)


# ================================================================== v1 endpoints (§5.12)


class V1Routes(ApiCase):
    def test_v1_put_expressible_and_409(self):
        install_rrc(self.data, "rrc")
        _, j = self.ok("GET", "/api/projects/rrc")
        for k in ("name", "data", "problems", "exports", "builds", "schema", "v1_expressible"):
            self.assertIn(k, j, fr("FR-MIG-06", "5.12", k))
        self.assertEqual(j["schema"], 2)
        self.assertIs(j["v1_expressible"], True)
        self.assertTrue(all(isinstance(p, str) for p in j["problems"]), "5.12 v1 problems are strings")
        data = j["data"]
        self.assertTrue([n for n in data["nodes"] if n["id"] == "foh"])
        for n in data["nodes"]:
            if n["id"] == "drums":
                n["label"] = "Drum kit"
        data.pop("imports", None)
        st, _, b = call(self.app, "PUT", "/api/projects/rrc", data, {"Content-Type": "application/json"})
        self.assertEqual(st, 200, fr("FR-MIG-06", "5.12", "v1 PUT on a v1-expressible doc (no If-Match needed): %s" % b[:300]))
        doc, _, _ = self.doc("rrc")
        self.assertEqual([d for d in doc["devices"] if d["id"] == "drums"][0]["name"], "Drum kit")
        self.assertEqual(len(doc["imports"]), 3, "5.12 v1 PUT keeps imports if absent")
        _, h = self.ok("GET", "/api/v2/projects/rrc/history?limit=1")
        self.assertEqual(h["revisions"][0]["source"], "put")
        _, j = self.ok("GET", "/api/projects/%s" % self.name)
        self.assertIs(j["v1_expressible"], False)
        st, _, b = call(self.app, "PUT", "/api/projects/%s" % self.name, j["data"], {"Content-Type": "application/json"})
        self.assertEqual(st, 409, fr("FR-MIG-06", "5.12", "non-expressible doc -> 409"))
        self.assertEqual(jbody(b)["code"], "v2_required")

    def test_v1_list_create_delete(self):
        _, j = self.ok("GET", "/api/projects")
        p = [x for x in j["projects"] if x["name"] == self.name][0]
        for k in ("name", "org", "title", "cards", "updated", "builds"):
            self.assertIn(k, p, "5.12 v1 list %s" % k)
        self.assertEqual(p["cards"], 12, "5.12 cards = device count")
        _, j = self.ok("POST", "/api/projects", {"name": "v1new", "template": "blank"}, status=201)
        self.assertTrue(j.get("ok"))
        doc, _, _ = self.doc("v1new")
        self.assertEqual(doc["fathom"], 2, "5.12 v1 POST creates a v2 project")
        self.ok("DELETE", "/api/projects/v1new?confirm=v1new")

    def test_v1_imports_inspect_trace_build(self):
        install_rrc(self.data, "rrc")
        xml = (RRC_DIR / "exports" / "dante" / "rrc-littleton-preset.xml").read_bytes()
        st, _, b = upload(self.app, "/api/projects/rrc/imports?kind=dante", [("extra-preset.xml", xml, "text/xml")])
        self.assertEqual(st, 201 if st == 201 else 200, b[:300])
        j = jbody(b)
        for k in ("ok", "kind", "path", "summary"):
            self.assertIn(k, j, "5.12 v1 import response %s" % k)
        self.assertEqual(j["kind"], "dante")
        _, ins = self.ok("GET", "/api/projects/rrc/inspect?path=%s&kind=dante" % j["path"])
        self.assertIn("summary", ins)
        self.ok("DELETE", "/api/projects/rrc/imports?path=%s&delete=1" % j["path"])
        doc, _, _ = self.doc("rrc")
        self.assertNotIn(j["path"], [i["path"] for i in doc["imports"]])
        _, t = self.ok("GET", "/api/projects/rrc/trace?from=drums&to=mains")
        self.assertTrue(t["paths"], "5.12 v1 card-level trace")
        self.assertTrue(all(isinstance(p, str) for p in t["paths"]))
        st, _, b = self.req("POST", "/api/projects/rrc/build", {})
        self.assertEqual(st, 201, b[:300])
        j = jbody(b)
        for k in ("ok", "build", "files", "url", "zip"):
            self.assertIn(k, j, "5.12 v1 build shape %s" % k)
        _, bl = self.ok("GET", "/api/projects/rrc/builds")
        self.assertIn(j["build"], [x["name"] for x in bl["builds"]])
        self.ok("DELETE", "/api/projects/rrc/builds/%s" % j["build"])


# ================================================================== imports, files, floor plans (§5.7)


class ImportsFilesPlans(ApiCase):
    def test_imports_multipart(self):
        requires("plugins")
        install_rrc(self.data, "rrc")
        xml = (RRC_DIR / "exports" / "dante" / "rrc-littleton-preset.xml").read_bytes()
        st, _, b = upload(self.app, "/api/v2/projects/rrc/imports?kind=dante", [("preset-2.xml", xml, "text/xml")])
        self.assertEqual(st, 201, "5.7 import upload: %s" % b[:300])
        j = jbody(b)
        for k in ("import", "summary", "revision"):
            self.assertIn(k, j, "5.7 import response %s" % k)
        imp = j["import"]
        self.assertEqual(imp["kind"], "dante")
        self.assertTrue(imp["id"].startswith("imp-"))
        _, ins = self.ok("GET", "/api/v2/projects/rrc/imports/%s/inspect" % imp["id"])
        self.assertEqual(ins["kind"], "dante")
        self.assertIn("summary", ins)
        path = self.data / "projects" / "rrc" / imp["path"]
        self.assertTrue(path.exists(), "import file stored in the project dir")
        _, d = self.ok("DELETE", "/api/v2/projects/rrc/imports/%s?delete_files=1" % imp["id"])
        self.assertIn("revision", d)
        self.assertFalse(path.exists(), "5.7 delete_files=1 removes files")
        doc, _, _ = self.doc("rrc")
        self.assertNotIn(imp["id"], [i["id"] for i in doc["imports"]])
        before = sorted(p.name for p in (self.data / "projects" / "rrc").rglob("*") if p.is_file())
        st, _, b = upload(self.app, "/api/v2/projects/rrc/imports", [("mystery.bin", b"\x00\x01garbage" * 10, "application/octet-stream")])
        self.assertEqual(st, 400, "5.7 undetectable kind -> 400")
        after = sorted(p.name for p in (self.data / "projects" / "rrc").rglob("*") if p.is_file())
        self.assertEqual(before, after, "5.7 undetectable upload files removed")

    def test_imports_preview_csv_no_write(self):
        requires("parsers.generic_csv")
        _, _, rev = self.doc()
        st, _, b = upload(self.app, "/api/v2/projects/%s/imports/preview?kind=csv" % self.name,
                          [("devices.csv", fixture_path("csv", "devices.csv").read_bytes(), "text/csv")])
        self.assertEqual(st, 200, b[:300])
        j = jbody(b)
        for k in ("kind", "ops", "summary", "warnings", "base_revision"):
            self.assertIn(k, j, fr("FR-IMP-08", "5.7", k))
        self.assertEqual(j["base_revision"], rev)
        self.assertEqual(j["summary"]["create"], 1)
        self.assertEqual(j["summary"]["update"], 1)
        _, _, rev2 = self.doc()
        self.assertEqual(rev2, rev, fr("FR-IMP-08", "5.7", "preview never writes"))

    def test_file_upload_download(self):
        st, _, b = upload(self.app, "/api/v2/projects/%s/files?device=atem-mini&kind=photo" % self.name,
                          [("rack photo.jpg", jpg_bytes(), "image/jpeg"), ("manual.pdf", tiny_pdf(), "application/pdf")])
        self.assertEqual(st, 201, fr("FR-INV-03", "5.7", b[:300].decode("latin-1")))
        j = jbody(b)
        atts = j["attachments"]
        self.assertEqual(len(atts), 2)
        for a in atts:
            self.assertTrue(re.match(r"^att-[0-9a-f]{12}$", a["id"]), "4.2 attachment id att-<12 hex>")
            self.assertTrue(a["file"].startswith("files/%s/" % a["id"]))
            self.assertEqual(a["device"], "atem-mini")
            for k in ("name", "mime", "size"):
                self.assertIn(k, a)
        doc, _, _ = self.doc()
        self.assertEqual(sorted(a["id"] for a in doc["attachments"]), sorted(a["id"] for a in atts))
        jpg, pdf = atts[0], atts[1]
        h, data = self.ok("GET", "/api/v2/projects/%s/files/%s/%s" % (self.name, jpg["id"], jpg["file"].split("/")[-1]))
        self.assertEqual(data, jpg_bytes())
        self.assertTrue(h.get("content-type", "").startswith("image/jpeg"), fr("FR-SEC-05", "3.26", "image served inline"))
        self.assertNotIn("attachment", h.get("content-disposition", ""))
        h, data = self.ok("GET", "/api/v2/projects/%s/files/%s/%s" % (self.name, pdf["id"], pdf["file"].split("/")[-1]))
        self.assertIn("attachment", h.get("content-disposition", ""), fr("FR-SEC-05", "3.26", "non-image as attachment"))
        _, j = self.ok("DELETE", "/api/v2/projects/%s/files/%s" % (self.name, jpg["id"]))
        self.assertIn("revision", j)
        doc, _, _ = self.doc()
        self.assertNotIn(jpg["id"], [a["id"] for a in doc["attachments"]])
        self.assertFalse((self.data / "projects" / self.name / "files" / jpg["id"]).exists(), "5.7 delete removes the folder")

    def _plan(self, filename, data, ctype, query="room=main&name=Plan"):
        return upload(self.app, "/api/v2/projects/%s/floorplans?%s" % (self.name, query), [(filename, data, ctype)])

    def test_floorplan_uploads(self):
        requires("floorplan")
        cases = [("plan.png", png_bytes(40, 30), "image/png", "png"), ("plan.jpg", jpg_bytes(), "image/jpeg", "jpg"),
                 ("plan.svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="10" height="10"/></svg>', "image/svg+xml", "svg"),
                 ("stage.drawio", fixture_path("plans", "compressed.drawio").read_bytes(), "application/xml", "svg"),
                 ("main.dxf", fixture_path("plans", "fixture.dxf").read_bytes(), "application/dxf", "svg")]
        for fn, data, ctype, image_kind in cases:
            with self.subTest(file=fn):
                st, _, b = self._plan(fn, data, ctype, "room=main&name=%s" % fn.split(".")[0])
                self.assertEqual(st, 201, fr("FR-PLAN-01", "5.7", "%s: %s" % (fn, b[:300])))
                j = jbody(b)
                fp = j["floorplan"]
                for k in ("id", "name", "room", "source", "image"):
                    self.assertIn(k, fp, "4.3.11 floorplan %s" % k)
                self.assertEqual(fp["room"], "main")
                self.assertEqual(fp["image"]["kind"], image_kind, fr("FR-PLAN-01", "4.3.11", fn))
                self.assertIn("warnings", j)
                h, img = self.ok("GET", "/api/v2/projects/%s/floorplans/%s/image" % (self.name, fp["id"]))
                self.assertTrue(img)
                if image_kind == "svg":
                    ET.fromstring(img)
                if fn == "plan.png":
                    self.assertEqual((fp["image"]["width"], fp["image"]["height"]), (40, 30))
        floorplan = requires("floorplan")
        n_expected = 5
        if floorplan.rasterizer():
            st, _, b = self._plan("rcp.pdf", tiny_pdf(), "application/pdf", "room=main&name=rcp")
            self.assertEqual(st, 201, fr("FR-PLAN-05", "3.8", "PDF with a rasterizer (%s) -> PNG plan: %s" % (floorplan.rasterizer(), b[:300])))
            self.assertEqual(jbody(b)["floorplan"]["image"]["kind"], "png")
            n_expected += 1
        doc, _, _ = self.doc()
        self.assertEqual(len(doc["floorplans"]), n_expected)
        dxf = [f for f in doc["floorplans"] if f["source"]["kind"] == "dxf"][0]
        self.assertEqual([l["name"] for l in dxf.get("layers", [])], ["WALLS", "SEATS", "HIDDEN"], "4.3.11 DXF layers")
        self.assertEqual(dxf.get("units"), {"insunits": 6, "meters_per_unit": 1.0})

    def test_floorplan_hide_layers(self):
        requires("floorplan")
        st, _, b = self._plan("main.dxf", fixture_path("plans", "fixture.dxf").read_bytes(), "application/dxf")
        self.assertEqual(st, 201, b[:300])
        fp = jbody(b)["floorplan"]
        _, full = self.ok("GET", "/api/v2/projects/%s/floorplans/%s/image" % (self.name, fp["id"]))
        self.assertIn(b'data-layer="WALLS"', full)
        _, hidden = self.ok("GET", "/api/v2/projects/%s/floorplans/%s/image?hide=WALLS" % (self.name, fp["id"]))
        self.assertNotIn(b'data-layer="WALLS"', hidden, fr("FR-PLAN-11", "5.7", "?hide= removes the layer"))
        self.assertIn(b'data-layer="SEATS"', hidden)

    def test_floorplan_export_svg_markers(self):
        requires("floorplan")
        st, _, b = self._plan("plan.png", png_bytes(40, 30), "image/png")
        fp = jbody(b)["floorplan"]
        _, _, rev = self.doc()
        self.change([{"op": "merge", "coll": "floorplans", "id": fp["id"], "value": {"markers": [{"device": "atem-mini", "x": 0.5, "y": 0.5},
                                                                                                {"device": "restream", "x": 0.1, "y": 0.9}]}}], rev)
        h, svg = self.ok("GET", "/api/v2/projects/%s/floorplans/%s.svg" % (self.name, fp["id"]))
        root = ET.fromstring(svg)
        groups = [e for e in root.iter() if e.get("data-device")]
        self.assertEqual(sorted(e.get("data-device") for e in groups), ["atem-mini", "restream"], fr("FR-PLAN-13", "5.7"))

    def test_dwg_415(self):
        requires("floorplan")
        st, _, b = self._plan("plan.dwg", b"AC1032" + b"\x00" * 200, "application/acad")
        self.assertEqual(st, 415, fr("FR-PLAN-06", "3.8"))
        j = jbody(b)
        self.assertEqual(j["code"], "dwg_unsupported")
        self.assertIn("DXF", j["error"], fr("FR-PLAN-06", "3.8", "message mentions DXF"))
        st, _, b = self._plan("plan.dxf", b"AutoCAD Binary DXF\r\n\x1a\x00" + b"\x00" * 100, "application/dxf")
        self.assertEqual(st, 415, fr("FR-PLAN-03", "3.8", "binary DXF -> 415"))
        st, _, b = self._plan("plan.xyz", b"hello", "application/octet-stream")
        self.assertEqual((st, jbody(b).get("code")), (415, "unsupported_format"))

    def test_pdf_plan_without_rasterizer_422(self):
        requires("floorplan")
        with temp_env(PATH="", FATHOM_PDF_RASTERIZER=None):
            st, _, b = self._plan("rcp.pdf", tiny_pdf(), "application/pdf")
        self.assertEqual(st, 422, fr("FR-PLAN-05", "3.8", "no rasterizer -> 422"))
        j = jbody(b)
        self.assertEqual(j["code"], "pdf_unsupported")
        self.assertIn("PNG or SVG", j["error"], fr("FR-PLAN-05", "3.8", "guidance text"))


# ================================================================== schedules, trace, search, qr, assistant (§5.8)


class Schedules(ApiCase):
    def test_schedule_json_shapes(self):
        for kind, keys in SCHEDULE_KEYS.items():
            with self.subTest(kind=kind):
                _, j = self.ok("GET", "/api/v2/projects/%s/schedules/%s" % (self.name, kind))
                for k in ("kind", "columns", "rows", "problems"):
                    self.assertIn(k, j, "5.8 schedule %s.%s" % (kind, k))
                self.assertEqual(j["kind"], kind)
                got = [c["key"] for c in j["columns"]]
                self.assertEqual(got[:len(keys)], keys, "5.8.2 %s columns in order" % kind)
                if kind == "bom":
                    self.assertIn("length_total_m", got, "5.8.2 bom cable lines column")
        _, j = self.ok("GET", "/api/v2/projects/%s/schedules/patch" % self.name)
        r = j["rows"][0]
        for k in ("device", "device_id", "port", "port_id"):
            self.assertIn(k, r, "5.8.2 JSON rows carry names and *_id keys")
        st, _, _ = self.req("GET", "/api/v2/projects/%s/schedules/nonsense" % self.name)
        self.assertIn(st, (400, 404))

    def test_schedule_patch_csv(self):
        h, b = self.ok("GET", "/api/v2/projects/%s/schedules/patch?format=csv" % self.name)
        self.assertTrue(h.get("content-type", "").startswith("text/csv"))
        self.assertIn('filename="%s-patch.csv"' % self.name, h.get("content-disposition", ""), "5.8 CSV attachment name")
        text = b.decode("utf-8")
        self.assertEqual(text.split("\r\n")[0], ",".join(PATCH_LABELS), fr("FR-PT-05", "5.8.2", "header"))
        golden = fixture_path("patchtable-sunday.csv").read_bytes().decode("utf-8")
        self.assertEqual(text, golden, fr("FR-PT-05", "6.6", "server patch CSV equals tests/fixtures/patchtable-sunday.csv"))

    def test_schedule_cables_csv_header(self):
        h, b = self.ok("GET", "/api/v2/projects/%s/schedules/cables?format=csv" % self.name)
        text = b.decode("utf-8")
        self.assertTrue(text.endswith("\r\n"))
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], CABLE_LABELS, fr("FR-CAB-03", "5.8.2"))
        self.assertEqual(len(rows) - 1, 15, "one row per cable")
        _, j = self.ok("GET", "/api/v2/projects/%s/schedules/cables?discipline=video" % self.name)
        self.assertEqual(sorted(r.get("id") for r in j["rows"]), ["c-0012", "c-0013", "c-0014"], fr("FR-CAB-03", "3.10", "discipline filter"))

    def test_schedule_inventory_csv(self):
        h, b = self.ok("GET", "/api/v2/projects/%s/schedules/inventory?format=csv" % self.name)
        rows = list(csv.reader(io.StringIO(b.decode("utf-8"))))
        header = [re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_") for c in rows[0]]
        self.assertIn("serial", header, fr("FR-INV-04", "3.14"))
        self.assertIn("asset_tag", header, fr("FR-INV-04", "3.14"))
        self.assertEqual(len(rows) - 1, 12, "one row per device (incl. spare)")

    def test_labels_html_and_tag_preview(self):
        h, b = self.ok("GET", "/api/v2/projects/%s/schedules/labels?format=html" % self.name)
        self.assertTrue(h.get("content-type", "").startswith("text/html"))
        _, j = self.ok("GET", "/api/v2/projects/%s/cables/tag-preview?scope=missing" % self.name)
        for k in ("ops", "count", "base_revision"):
            self.assertIn(k, j, "5.8 tag-preview %s" % k)
        self.assertEqual(j["count"], 10, "FR-CAB-02 ten untagged cables")
        tags = {o["id"]: o["value"]["tag"] for o in j["ops"]}
        self.assertEqual(tags["c-0015"], "X-001")

    def test_rack_svg(self):
        h, b = self.ok("GET", "/api/v2/projects/%s/racks/rk-foh.svg?face=front" % self.name)
        ET.fromstring(b)
        self.assertIn(b"shure-wireless", b, "FR-RACK-06 rack SVG shows the racked device")
        h, b = self.ok("GET", "/api/v2/projects/%s/racks/rk-foh.svg?face=rear" % self.name)
        ET.fromstring(b)

    def test_trace(self):
        _, j = self.ok("GET", "/api/v2/projects/%s/trace?from=samsung-tv-1:sdi-in-1&direction=up&discipline=video" % self.name)
        self.assertTrue(j["paths"], "5.8 trace returns paths")
        for p in j["paths"]:
            for k in ("hops", "cables", "text"):
                self.assertIn(k, p)
            for hop in p["hops"]:
                self.assertEqual(set(hop) >= {"device", "port", "label"}, True)
        refs = {(h["device"], h["port"]) for p in j["paths"] for h in p["hops"]}
        self.assertIn(("atem-mini", "hdmi-in-1"), refs, fr("FR-TRC-02", "3.17"))
        self.assertNotIn(("atem-mini", "analog-in-1"), refs, fr("FR-TRC-02", "3.17"))
        _, j = self.ok("GET", "/api/v2/projects/%s/trace?from=stage-box-1:hdmi-out-1&to=samsung-tv-1:sdi-in-1" % self.name)
        self.assertTrue(j["paths"])
        st, _, _ = self.req("GET", "/api/v2/projects/%s/trace?from=nope:zz" % self.name)
        self.assertEqual(st, 400, "5.8 unknown endpoint -> 400")

    def test_search(self):
        _, j = self.ok("GET", "/api/v2/projects/%s/search?q=10.20.0.40" % self.name)
        hits = j["hits"]
        self.assertTrue([h for h in hits if h["kind"] == "interface" and h["device"] == "atem-mini"], fr("FR-SRCH-01", "5.8"))
        for h in hits:
            for k in ("kind", "id", "device", "port", "title", "subtitle", "room", "score", "match"):
                self.assertIn(k, h, "5.11 hit %s" % k)
        _, j = self.ok("GET", "/api/v2/projects/%s/search?q=atem&limit=3" % self.name)
        self.assertLessEqual(len(j["hits"]), 3)
        self.assertEqual(j["hits"][0]["id"], "atem-mini", fr("FR-SRCH-04", "3.18"))
        _, j = self.ok("GET", "/api/v2/projects/%s/search?q=atem&kinds=port" % self.name)
        self.assertTrue(all(h["kind"] == "port" for h in j["hits"]))

    def test_qr_endpoint(self):
        qr = requires("qr")
        export = requires("export")
        requires("export:device_url")
        h, b = self.ok("GET", "/api/v2/projects/%s/qr/atem-mini.svg" % self.name)
        root = ET.fromstring(b)
        vb = [float(x) for x in root.get("viewBox").split()]
        n = int(vb[2]) - 8
        self.assertTrue(n >= 21 and (n - 17) % 4 == 0, fr("FR-QR-02", "3.24", "module count = 17 + 4*version (got %d)" % n))
        _, _, rev = self.doc()
        self.change([{"op": "root", "key": "settings", "value": {"public_url": "https://av.example.org"}}], rev)
        h, b = self.ok("GET", "/api/v2/projects/%s/qr/atem-mini.svg" % self.name)
        expected = qr.svg(export.device_url("https://av.example.org", self.name, "atem-mini"), ecl="M", scale=4)
        self.assertEqual(b.decode("utf-8"), expected, fr("FR-EXP-04", "7.4.5", "QR encodes <public_url>/p/<n>/d/<device>"))
        self.assertEqual(export.device_url("https://av.example.org", self.name, "atem-mini"), "https://av.example.org/p/%s/d/atem-mini" % self.name)
        st, _, _ = self.req("GET", "/api/v2/projects/%s/qr/ghost.svg" % self.name)
        self.assertEqual(st, 404)

    def test_assistant_endpoint(self):
        _, j = self.ok("POST", "/api/v2/projects/%s/assistant" % self.name, {"question": "House sound is fine, but the livestream has no audio.", "room": "main", "use_llm": True})
        for k in ("question", "intent", "summary", "paths", "checks", "suggestion", "confidence", "unresolved", "llm"):
            self.assertIn(k, j, fr("FR-AST-02", "5.10", k))
        self.assertEqual(j["llm"], {"used": False}, "5.10 not configured -> used false")
        self.assertEqual(j["suggestion"]["base_revision"], 1)
        st, _, b = self.req("POST", "/api/v2/projects/%s/assistant" % self.name, {"question": "  "})
        self.assertEqual(st, 400, "5.10 empty question -> 400")


# ================================================================== builds (§5.9)


class Builds(ApiCase):
    def test_build_list_delete(self):
        st, _, b = self.req("POST", "/api/v2/projects/%s/builds" % self.name, {"pdf": False, "png": False, "state": "all", "rooms": None})
        self.assertEqual(st, 201, b[:400])
        j = jbody(b)
        for k in ("build", "files", "url", "zip"):
            self.assertIn(k, j, "5.9 build response %s" % k)
        self.assertEqual(j["url"], "builds/%s/%s/index.html" % (self.name, j["build"]))
        self.assertEqual(j["zip"], "builds/%s/%s/%s.zip" % (self.name, j["build"], j["build"]))
        for f in ("index.html", "rooms/main/index.html", "devices/atem-mini.html", "cable-schedule.csv"):
            self.assertIn(f, j["files"], "5.9 %s" % f)
        _, lst = self.ok("GET", "/api/v2/projects/%s/builds" % self.name)
        entry = [x for x in lst["builds"] if x["name"] == j["build"]]
        self.assertTrue(entry)
        self.assertIn("rooms/main/index.html", entry[0]["files"], "5.9 builds list files recursive")
        self.assertIn("created", entry[0])
        h, html = self.ok("GET", "/builds/%s/%s/rooms/main/index.html" % (self.name, j["build"]))
        self.assertIn(b"<html", html.lower())
        st, _, _ = self.req("GET", "/builds/%s/%s/../../secret" % (self.name, j["build"]))
        self.assertIn(st, (400, 404))
        self.ok("DELETE", "/api/v2/projects/%s/builds/%s" % (self.name, j["build"]))
        st, _, _ = self.req("GET", "/builds/%s/%s/index.html" % (self.name, j["build"]))
        self.assertEqual(st, 404)

    def test_build_rooms_subset(self):
        install_campus(self.data, "campus")
        doc, _, _ = self.doc("campus")
        rooms = [r["id"] for r in doc["rooms"]]
        self.assertGreaterEqual(len(rooms), 3)
        st, _, b = self.req("POST", "/api/v2/projects/campus/builds", {"rooms": [rooms[0]]})
        self.assertEqual(st, 201, b[:300])
        files = jbody(b)["files"]
        self.assertTrue([f for f in files if f.startswith("rooms/%s/" % rooms[0])], fr("FR-EXP-03", "3.23"))
        for other in rooms[1:]:
            self.assertFalse([f for f in files if f.startswith("rooms/%s/" % other)], fr("FR-EXP-03", "3.23", "only the requested room folder (%s)" % other))

    def test_build_pdf_without_chrome_400(self):
        export = requires("export")
        if export.find_chrome():
            return  # positive PDF path is covered by test_exports.test_report_pdf (needs Chrome)
        st, _, b = self.req("POST", "/api/v2/projects/%s/builds" % self.name, {"pdf": True})
        self.assertEqual(st, 400, "5.9 PDF without Chrome -> 400")


# ================================================================== viewer, static, PWA, OpenAPI (§5.13, §5.14)


class ViewerAndStatic(ApiCase):
    def test_viewer_room_maps(self):
        install_campus(self.data, "campus")
        doc, _, _ = self.doc("campus")
        rooms = [r["id"] for r in doc["rooms"]]
        self.assertGreaterEqual(len(rooms), 3, fr("FR-ROOM-07", "3.1", "campus-demo has 3 rooms"))
        maps = {}
        for r in rooms:
            st, h, b = self.req("GET", "/p/campus/r/%s" % r)
            self.assertEqual(st, 200, fr("FR-ROOM-07", "5.13", r))
            maps[r] = frozenset(re.findall(r'data-id="([^"]+)"', b.decode("utf-8")))
            self.assertTrue(maps[r], "room %s map has cards" % r)
        self.assertEqual(len(set(maps.values())), len(rooms), fr("FR-ROOM-07", "3.1", "each room renders a different map"))
        st, _, b = self.req("GET", "/p/campus")
        self.assertEqual(st, 200, fr("FR-MAP-01", "3.7", "/p/<n> = default room"))
        st, _, _ = self.req("GET", "/p/campus/r/%s/diagram.svg" % rooms[0])
        self.assertEqual(st, 200)
        st, _, _ = self.req("GET", "/p/campus/r/no-such-room")
        self.assertEqual(st, 404)

    def test_room_index_and_device_page(self):
        st, h, b = self.req("GET", "/p/%s/rooms" % self.name)
        self.assertEqual(st, 200, fr("FR-MAP-06", "5.13"))
        self.assertIn(b"Main Auditorium", b)
        st, h, b = self.req("GET", "/p/%s/d/atem-mini" % self.name)
        self.assertEqual(st, 200, fr("FR-MAP-06", "5.13"))
        html = b.decode("utf-8")
        self.assertIn("ATEM Mini", html)
        self.assertIn("10.20.0.40", html, "FR-MAP-06 device page shows interfaces")
        st, _, b = self.req("GET", "/p/%s/r/main/patch" % self.name)
        self.assertEqual(st, 200, fr("FR-PT-08", "5.13"))
        self.assertIn(b"Audio Rack 1", b)
        st, _, _ = self.req("GET", "/p/%s/d/ghost" % self.name)
        self.assertEqual(st, 404)

    def test_app_pages_and_static(self):
        st, h, b = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertTrue(h.get("content-type", "").startswith("text/html"))
        st, h, b = self.req("GET", "/login")
        self.assertEqual(st, 200)
        st, h, b = self.req("GET", "/static/app.html")
        self.assertEqual(st, 200)
        etag = h.get("etag")
        self.assertTrue(etag, "5.1 static ETag")
        self.assertEqual(h.get("cache-control"), "no-cache", "5.1 static no-cache")
        st, _, _ = self.req("GET", "/static/app.html", headers={"If-None-Match": etag})
        self.assertEqual(st, 304, "5.1 304 support")
        js = sorted((Path(__file__).resolve().parent.parent / "fathom" / "static" / "js").glob("*.js"))
        if js:
            st, h, _ = self.req("GET", "/static/js/%s" % js[0].name)
            self.assertEqual(st, 200)
            self.assertEqual(h.get("content-type"), "text/javascript; charset=utf-8", "5.13 .js content type")
        st, _, _ = self.req("GET", "/static/dev/fixture-v2.json")
        self.assertEqual(st, 200, "5.13 dev files served from loopback")
        st, _, _ = call(self.app, "GET", "/static/dev/fixture-v2.json", headers={"__remote_addr__": "10.9.8.7"})
        self.assertIn(st, (403, 404), "5.13 dev files not served to non-loopback without FATHOM_DEV")
        st, _, _ = self.req("GET", "/static/nothing-here.js")
        self.assertEqual(st, 404)
        st, h, b = self.req("GET", "/api/docs")
        self.assertEqual(st, 200)
        self.assertIn(b"/api/v2/meta", b, "5.14 /api/docs lists routes")

    def test_manifest(self):
        st, h, b = self.req("GET", "/manifest.webmanifest")
        self.assertEqual(st, 200, fr("FR-MOB-04", "3.21"))
        self.assertTrue(h.get("content-type", "").startswith("application/manifest+json"), fr("FR-MOB-04", "5.13"))
        m = json.loads(b.decode("utf-8"))
        exp = {"name": "Fathom", "short_name": "Fathom", "id": "/", "start_url": "./", "scope": "./", "display": "standalone",
               "theme_color": "#0b1020", "background_color": "#0b1020"}
        for k, v in exp.items():
            self.assertEqual(m.get(k), v, fr("FR-MOB-04", "3.21", k))
        icons = m["icons"]
        self.assertTrue([i for i in icons if i.get("sizes") == "192x192" and "png" in i.get("type", "")], "FR-MOB-04 192 png")
        self.assertTrue([i for i in icons if i.get("sizes") == "512x512" and "maskable" not in i.get("purpose", "any")], "FR-MOB-04 512 any")
        self.assertTrue([i for i in icons if i.get("sizes") == "512x512" and "maskable" in i.get("purpose", "")], "FR-MOB-04 512 maskable")
        for i in icons:
            src = i["src"].lstrip("./")
            st, h2, png = self.req("GET", "/" + src)
            self.assertEqual(st, 200, "icon %s served" % i["src"])
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            w, hh = struct.unpack(">II", png[16:24])
            self.assertEqual("%dx%d" % (w, hh), i["sizes"], "icon %s has its declared size" % src)
        st, h, png = self.req("GET", "/apple-touch-icon.png")
        self.assertEqual(st, 200)
        self.assertEqual(struct.unpack(">II", png[16:24]), (180, 180), "FR-MOB-04 apple-touch-icon 180")
        st, h, b = self.req("GET", "/sw.js")
        self.assertEqual(st, 200, fr("FR-MOB-05", "5.13"))
        self.assertEqual(h.get("service-worker-allowed"), "/", "5.13 Service-Worker-Allowed")
        self.assertIn("javascript", h.get("content-type", ""))
        self.assertIn(b"fathom-shell-", b, "6.10 cache names")
        st, h, _ = self.req("GET", "/favicon.ico")
        self.assertEqual(st, 200)

    def test_openapi_covers_routes(self):
        server = requires("server")
        st, h, b = self.req("GET", "/api/openapi.json")
        self.assertEqual(st, 200)
        spec = jbody(b)
        self.assertEqual(spec["openapi"], "3.1.0", fr("FR-EXT-04", "5.14"))
        self.assertEqual(spec["info"]["title"], "Fathom API")
        self.assertEqual(spec["info"]["version"], "0.3.0")
        self.assertEqual(spec["servers"], [{"url": "./"}])
        self.assertTrue({"basic", "session"} <= set(spec["components"]["securitySchemes"]))
        for s in ("Doc", "Op", "Problem", "Hit", "Answer", "Error", "Floorplan", "Attachment", "Import", "User"):
            self.assertIn(s, spec["components"]["schemas"], "5.14 components.schemas.%s" % s)
        missing = []
        for method, pattern in route_patterns(server):
            cands = openapi_paths(pattern)
            op = None
            for c in cands:
                op = spec["paths"].get(c, {}).get(method.lower())
                if op:
                    break
            if not op:
                missing.append("%s %s" % (method, cands[0]))
                continue
            for k in ("summary", "tags", "x-fathom-role", "responses"):
                self.assertIn(k, op, "5.14 %s %s has %s" % (method, cands[0], k))
        self.assertEqual(missing, [], fr("FR-EXT-04", "5.14", "every registered route documented"))
        self.assertGreaterEqual(len(spec["paths"]), 60)


def route_patterns(server):
    """(method, regex pattern) of every registered route, from the server route table."""
    table = getattr(server, "ROUTES", None) or getattr(server, "_ROUTES", [])
    out = []
    for r in table:
        if hasattr(r, "method"):
            pat = getattr(r, "pattern", None) or r.regex.pattern
        else:
            method, rx = r[0], r[1]
            pat = rx.pattern if hasattr(rx, "pattern") else rx
            r = type("R", (), {"method": method})
        out.append((r.method, pat))
    return out


def _named_groups_to_params(p):
    out, i = "", 0
    while i < len(p):
        if p.startswith("(?P<", i):
            j = p.index(">", i)
            name = p[i + 4:j]
            depth, k = 1, j + 1
            while depth:
                if p[k] == "\\":
                    k += 2
                    continue
                depth += {"(": 1, ")": -1}.get(p[k], 0)
                k += 1
            out += "{%s}" % name
            i = k
        else:
            out += p[i]
            i += 1
    return out


def openapi_paths(pattern):
    """Candidate OpenAPI paths for a route regex (with and without optional groups)."""
    p = pattern.strip("^$")
    p = _named_groups_to_params(p)
    with_opt = re.sub(r"\(\?:([^()]*)\)\?", r"\1", p).replace("\\", "")
    without_opt = re.sub(r"\(\?:[^()]*\)\?", "", p).replace("\\", "")
    return [with_opt, without_opt]


if __name__ == "__main__":
    unittest.main()
