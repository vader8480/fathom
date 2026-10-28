"""Device short codes (SPEC FR-INV-09, §4.3.8 ``short_code``, §5.6 ``/api/v2/codes``, §5.13 ``/c/<code>``)."""

from __future__ import annotations

import contextlib
import io
import json
import unittest

try:
    from _helpers import basic, call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import basic, call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class Codes(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")

    def test_alphabet_format_parse(self):
        self.assertEqual(self.schema.SHORT_CODE_ALPHABET, ALPHABET, fr("FR-INV-09", "4.3.8", "no 0/1/I/O"))
        for bad in "01IO":
            self.assertNotIn(bad, ALPHABET)
        self.assertEqual(self.schema.format_short_code("ABCD2345"), "ABCD-2345")
        self.assertEqual(self.schema.format_short_code("abcd-2345"), "ABCD-2345")
        for text in ("ABCD2345", "abcd2345", " abcd-2345 ", "ABCD-2345\n", "AB-CD-2345"):
            self.assertEqual(self.schema.parse_short_code(text), "ABCD2345", repr(text))
        for text in ("ABCD234", "ABCD23456", "ABCD234O", "ABCD-234I", "", None, 12345678, "ABCD 2345!"):
            self.assertIsNone(self.schema.parse_short_code(text), repr(text))

    def test_normalize(self):
        doc = sunday_doc()
        doc["devices"][0]["short_code"] = "abcd-2345"
        doc["devices"][1]["short_code"] = "ABCD234O"
        doc["devices"][2]["short_code"] = ""
        n = self.schema.normalize(doc)
        self.assertEqual(n["devices"][0]["short_code"], "ABCD2345", "upper-cased, dash stripped")
        self.assertNotIn("short_code", n["devices"][1], "invalid chars dropped")
        self.assertNotIn("short_code", n["devices"][2])
        self.assertNotIn("short_code", n["devices"][3], "normalize never assigns codes")

    def test_ensure_unique_and_idempotent(self):
        doc = self.schema.normalize(sunday_doc())
        doc["devices"][0]["short_code"] = "ABCD2345"
        doc["devices"][1]["short_code"] = "ABCD2345"
        n = self.schema.ensure_short_codes(doc)
        self.assertEqual(n, len(doc["devices"]) - 1, "every device but the first holder gets a code")
        codes = [d["short_code"] for d in doc["devices"]]
        self.assertEqual(codes[0], "ABCD2345", "the first holder keeps its code")
        self.assertNotEqual(codes[1], "ABCD2345", "the duplicate is re-issued")
        self.assertEqual(len(set(codes)), len(codes), "unique within the doc")
        for c in codes:
            self.assertEqual(len(c), 8)
            self.assertTrue(set(c) <= set(ALPHABET), c)
        self.assertEqual(self.schema.ensure_short_codes(doc), 0, "idempotent")
        self.assertEqual([d["short_code"] for d in doc["devices"]], codes)

    def test_container_kind_gets_codes_too(self):
        doc = self.schema.normalize(sunday_doc())
        doc["devices"].append({"id": "case-1", "name": "Case", "kind": "container", "ports": []})
        self.schema.ensure_short_codes(doc)
        self.assertTrue(doc["devices"][-1]["short_code"])


class Store(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")
        self.project = requires("project")
        self.app = get_app()

    def test_save_doc_assigns_and_keeps(self):
        with temp_data_dir() as data:
            pdir = install_sunday(data, "proj")
            res = self.project.save_doc(sunday_doc(), pdir, base_revision=None, author="t")
            doc, _ = self.project.read_doc(pdir)
            codes = {d["id"]: d["short_code"] for d in doc["devices"]}
            self.assertEqual(len(codes), len(doc["devices"]), fr("FR-INV-09", "4.10", "save_doc assigns codes"))
            self.assertEqual(len(set(codes.values())), len(codes))
            self.assertNotIn("devices/sound-board", res["touched"], "code bookkeeping is not a conflicting touch")
            # a client editing from a copy without codes does not re-roll them
            stale = sunday_doc()
            stale["devices"][3]["name"] = "Renamed board"
            self.project.save_doc(stale, pdir, base_revision=res["revision"], author="t")
            doc2, _ = self.project.read_doc(pdir)
            self.assertEqual({d["id"]: d["short_code"] for d in doc2["devices"]}, codes, "codes are sticky")
            self.assertEqual([d["name"] for d in doc2["devices"] if d["id"] == "sound-board"], ["Renamed board"])
            # history replays to the same doc
            from fathom import history

            self.assertEqual(history.get_revision_doc(pdir, doc2["revision"]), doc2)

    def test_changes_assign_codes_to_new_devices(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            op = {"op": "put", "coll": "devices", "id": "new-1", "value": {"id": "new-1", "name": "New", "kind": "other", "ports": []}}
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": 1, "ops": [op]}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj")
            doc = jbody(b)["doc"]
            new = [d for d in doc["devices"] if d["id"] == "new-1"][0]
            self.assertTrue(self.schema.parse_short_code(new.get("short_code")))
            # a second put of the same device without the code keeps it
            op["value"]["name"] = "New 2"
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": doc["revision"], "ops": [op]}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj")
            again = [d for d in jbody(b)["doc"]["devices"] if d["id"] == "new-1"][0]
            self.assertEqual(again["short_code"], new["short_code"])
            self.assertEqual(again["name"], "New 2")

    def test_opt_out(self):
        with temp_data_dir() as data:
            doc = sunday_doc()
            doc["settings"]["short_codes"] = False
            pdir = install_sunday(data, "proj")
            self.project.save_doc(doc, pdir, base_revision=None)
            stored, _ = self.project.read_doc(pdir)
            self.assertFalse(any("short_code" in d for d in stored["devices"]), "settings.short_codes: false opts out")

    def test_new_project_from_template(self):
        with temp_data_dir():
            pdir = self.project.new_project("camp", template="campus-demo")
            doc, _ = self.project.read_doc(pdir)
            self.assertTrue(all(self.schema.parse_short_code(d.get("short_code")) for d in doc["devices"]), fr("FR-INV-09", "4.10", "project creation assigns codes"))

    def test_find_by_short_code(self):
        with temp_data_dir() as data:
            pdir = install_sunday(data, "proj")
            self.project.save_doc(sunday_doc(), pdir, base_revision=None)
            doc, _ = self.project.read_doc(pdir)
            dev = [d for d in doc["devices"] if d["id"] == "atem-mini"][0]
            code = dev["short_code"]
            hit = self.project.find_by_short_code(code[:4].lower() + "-" + code[4:].lower())
            self.assertEqual(hit, {"project": "proj", "device": "atem-mini", "name": dev["name"], "room": "main", "kind": "video_switcher"})
            self.assertIsNone(self.project.find_by_short_code("ZZZZZZZZ"))
            self.assertIsNone(self.project.find_by_short_code("nonsense"))
            self.project.trash_project("proj")
            self.assertIsNone(self.project.find_by_short_code(code), "trashed projects are not searched")


class Search(unittest.TestCase):
    def test_exact_match_scores_100(self):
        schema = requires("schema")
        search = requires("search")
        doc = schema.normalize(sunday_doc())
        doc["devices"][5]["short_code"] = "ABCD2345"  # atem-mini
        for q in ("ABCD2345", "abcd-2345", "Abcd2345"):
            hits = search.search(doc, q)
            self.assertTrue(hits, q)
            self.assertEqual((hits[0]["kind"], hits[0]["id"], hits[0]["score"], hits[0]["match"]), ("device", "atem-mini", 100, "short_code"), q)
            self.assertTrue(hits[0]["subtitle"].endswith(" · ABCD-2345"), hits[0]["subtitle"])
        self.assertEqual(search.KIND_ORDER[0], "device")
        plain = search.search(schema.normalize(sunday_doc()), "ATEM")[0]
        self.assertNotIn("·  ", plain["subtitle"])
        self.assertFalse(plain["subtitle"].endswith(" · "), "no dangling separator without a code")


class Routes(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.project = requires("project")

    def _coded(self, data):
        pdir = install_sunday(data, "proj")
        self.project.save_doc(sunday_doc(), pdir, base_revision=None)
        doc, _ = self.project.read_doc(pdir)
        return {d["id"]: d["short_code"] for d in doc["devices"]}

    def test_codes_route(self):
        with temp_data_dir() as data:
            codes = self._coded(data)
            code = codes["sound-board"]
            for spelled in (code, code.lower(), code[:4] + "-" + code[4:], code[:4].lower() + "-" + code[4:]):
                st, _, b = call(self.app, "GET", "/api/v2/codes/" + spelled)
                self.assertEqual(st, 200, spelled)
                self.assertEqual(jbody(b), {"project": "proj", "device": "sound-board", "name": "Sound Board", "room": "main", "kind": "console"})
            st, _, b = call(self.app, "GET", "/api/v2/codes/ZZZZ-ZZZZ")
            self.assertEqual(st, 404)
            self.assertEqual((jbody(b)["error"], jbody(b)["code"]), ("not_found", "not_found"), fr("FR-INV-09", "5.6", "404 {error: not_found}"))
            st, _, _ = call(self.app, "GET", "/api/v2/codes/ABC")
            self.assertEqual(st, 404)

    def test_c_redirect_local_admin(self):
        with temp_data_dir() as data:
            codes = self._coded(data)
            code = codes["atem-mini"]
            st, h, _ = call(self.app, "GET", "/c/" + code[:4] + "-" + code[4:])
            self.assertEqual(st, 302)
            self.assertEqual(h["location"], "/#/proj//devices/atem-mini", fr("FR-INV-09", "5.13", "editors land in the app"))
            st, h, b = call(self.app, "GET", "/c/ZZZZZZZZ")
            self.assertEqual(st, 404)
            self.assertTrue(h.get("content-type", "").startswith("text/html"), "unknown code → HTML not-found page")
            self.assertIn(b"No device has that code", b)

    def test_c_redirect_roles(self):
        users = requires("users")
        with temp_data_dir() as data:
            codes = self._coded(data)
            code = codes["atem-mini"]
            users.add_user("ada", "ada-password-1", role="admin")
            users.add_user("eve", "eve-password-1", role="editor")
            users.add_user("vic", "vic-password-1", role="viewer")
            st, h, _ = call(self.app, "GET", "/c/" + code, headers=basic("ada", "ada-password-1"))
            self.assertEqual((st, h["location"]), (302, "/#/proj//devices/atem-mini"))
            st, h, _ = call(self.app, "GET", "/c/" + code, headers=basic("eve", "eve-password-1"))
            self.assertEqual((st, h["location"]), (302, "/#/proj//devices/atem-mini"))
            st, h, _ = call(self.app, "GET", "/c/" + code, headers=basic("vic", "vic-password-1"))
            self.assertEqual((st, h["location"]), (302, "/p/proj/d/atem-mini"), fr("FR-INV-09", "5.13", "viewers land on the device page"))
            st, _, _ = call(self.app, "GET", "/c/" + code)
            self.assertEqual(st, 401, "anonymous with auth on")
            st, _, b = call(self.app, "GET", "/api/v2/codes/" + code, headers=basic("vic", "vic-password-1"))
            self.assertEqual(st, 200)
            self.assertEqual(jbody(b)["device"], "atem-mini")

    def test_script_root(self):
        with temp_data_dir() as data:
            codes = self._coded(data)
            code = codes["atem-mini"]
            st, h, _ = call(self.app, "GET", "/c/" + code, headers={"__script_name__": "/fathom"})
            self.assertEqual((st, h["location"]), (302, "/fathom/#/proj//devices/atem-mini"))


class Cli(unittest.TestCase):
    def test_backfill(self):
        cli = requires("cli")
        project = requires("project")
        schema = requires("schema")
        with temp_data_dir() as data:
            install_sunday(data, "one")
            install_sunday(data, "two")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["codes", "backfill", "one"])
            self.assertIn("one: 12 code(s) assigned", out.getvalue())
            doc1, _ = project.read_doc(data / "projects" / "one")
            self.assertTrue(all(schema.parse_short_code(d.get("short_code")) for d in doc1["devices"]))
            doc2, _ = project.read_doc(data / "projects" / "two")
            self.assertFalse(any("short_code" in d for d in doc2["devices"]), "only the named project")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["codes", "backfill"])
            text = out.getvalue()
            self.assertIn("one: 0 code(s) assigned", text, "idempotent")
            self.assertIn("two: 12 code(s) assigned", text)
            doc1b, _ = project.read_doc(data / "projects" / "one")
            self.assertEqual(doc1b["revision"], doc1["revision"], "nothing to assign → no new revision")
            self.assertEqual([d["short_code"] for d in doc1b["devices"]], [d["short_code"] for d in doc1["devices"]])


if __name__ == "__main__":
    unittest.main()
