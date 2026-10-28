"""Church room starters (SPEC §3.1 FR-ROOM-09/10, §5.6 *Starters*; ``fathom/starters.py``, ``fathom/samples/church-*``).

Every starter validates with zero errors and has the promised shape; ``list_starters`` reports counts;
``merge_room`` adds a starter to campus-demo twice with unique ids and zero errors; the routes answer
201 / 400 / 423; ``fathom new x --template church-sanctuary`` goes through ``project.new_project``.
"""
from __future__ import annotations

import json
import re
import unittest

try:
    from _helpers import CAMPUS_DIR, SAMPLES, call, fr, get_app, install_project, jbody, requires, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import CAMPUS_DIR, SAMPLES, call, fr, get_app, install_project, jbody, requires, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
STARTER_IDS = ["church-sanctuary", "church-youth-room", "church-chapel", "church-portable", "church-broadcast"]


def _errors(problems):
    return [p for p in problems if p.get("level") == "error"]


def _campus():
    return json.loads((CAMPUS_DIR / "project.json").read_text(encoding="utf-8"))


class StarterSamples(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")
        self.starters = requires("starters")

    def test_starter_list_and_order(self):
        self.assertEqual(self.starters.starter_ids(), STARTER_IDS, fr("FR-ROOM-09", "3.1", "five starters in the documented order"))
        for sid in STARTER_IDS:
            self.assertTrue((SAMPLES / sid / "project.json").is_file(), sid)

    def test_every_starter_validates_and_has_the_promised_shape(self):
        for sid in STARTER_IDS:
            with self.subTest(starter=sid):
                doc = self.starters.load_starter_doc(sid)
                self.assertEqual(self.schema.doc_version(doc), 2)
                self.assertEqual(_errors(self.schema.validate_doc(doc)), [], fr("FR-ROOM-09", "3.1", sid + " validates"))
                meta = self.starters.get_starter(sid)
                room_ids = [r["id"] for r in doc["rooms"]]
                self.assertEqual(room_ids, [meta["room"]], "one room whose id is the starter's prefix")
                self.assertEqual(doc["settings"]["default_room"], meta["room"])
                self.assertEqual(doc["meta"]["org"], "Your church")
                self.assertTrue(doc["meta"].get("description"))
                self.assertGreaterEqual(len(doc["racks"]), 1)
                self.assertGreaterEqual(len(doc["devices"]), 8)
                self.assertGreaterEqual(len(doc["cables"]), 6)
                self.assertEqual(len(doc["pages"]), 1)
                self.assertEqual(doc["pages"][0]["kind"], "sop")
                self.assertIn("power-up", doc["pages"][0]["slug"])
                prefix = meta["room"] + "-"
                for coll in ("systems", "locations", "racks", "devices", "cables", "bundles", "pages"):
                    for e in doc.get(coll) or []:
                        self.assertTrue(e["id"].startswith(prefix), "%s/%s is not prefixed with %s" % (coll, e["id"], prefix))
                for d in doc["devices"]:
                    self.assertEqual(d["room"], meta["room"])
                    self.assertNotIn("short_code", d, "short codes are assigned by the store on first save")
                racked = [d for d in doc["devices"] if isinstance(d.get("rack"), dict) and d["rack"].get("u")]
                self.assertTrue(racked, "devices are placed in U positions")
                tags = [c.get("tag") for c in doc["cables"]]
                self.assertTrue(all(tags), "every cable carries a tag")
                self.assertEqual(len(set(tags)), len(tags), "tags are unique")
                self.assertTrue(all(t.startswith(doc["rooms"][0]["code"] + "-") for t in tags), "tags follow {room}-{D}-{n:03}")
                conds = [d.get("inventory", {}).get("condition") for d in doc["devices"]]
                self.assertTrue(any(conds), "inventory.condition is filled")

    def test_portable_uses_containers(self):
        doc = self.starters.load_starter_doc("church-portable")
        containers = [d for d in doc["devices"] if d["kind"] == "container"]
        self.assertGreaterEqual(len(containers), 4, fr("FR-INV-08", "3.14", "road cases are containers"))
        contents = self.schema.container_contents(doc)
        self.assertTrue(all(c["id"] in contents for c in containers), "every case holds something")
        inside = [d for d in doc["devices"] if d.get("container")]
        self.assertGreaterEqual(len(inside), 12)
        self.assertTrue(all("load-in" in (d.get("tags") or []) for d in doc["devices"]), "everything is flagged for load-in")

    def test_sanctuary_broadcast_have_networks_with_vlans(self):
        for sid in ("church-sanctuary", "church-broadcast"):
            doc = self.starters.load_starter_doc(sid)
            vlans = [n.get("vlan") for n in doc["networks"]]
            self.assertTrue(vlans and all(isinstance(v, int) for v in vlans), sid)
            self.assertTrue(any(d.get("interfaces") for d in doc["devices"]), sid)

    def test_list_starters_counts(self):
        rows = self.starters.list_starters()
        self.assertEqual([r["id"] for r in rows], STARTER_IDS)
        for r in rows:
            doc = self.starters.load_starter_doc(r["id"])
            self.assertEqual(r["devices"], len(doc["devices"]))
            self.assertEqual(r["cables"], len(doc["cables"]))
            self.assertEqual(r["racks"], len(doc["racks"]))
            self.assertEqual(r["pages"], 1)
            self.assertEqual(r["room_name"], doc["rooms"][0]["name"])
            for k in ("label", "blurb", "tags", "room"):
                self.assertTrue(r.get(k), k)

    def test_flow_project_loads(self):
        for sid in STARTER_IDS:
            doc = self.starters.load_starter_doc(sid)
            project = self.schema.flow_project(doc)
            self.assertTrue(project.nodes, sid)
            self.assertTrue(project.links, sid)


class MergeRoom(unittest.TestCase):
    def setUp(self):
        self.schema = requires("schema")
        self.starters = requires("starters")

    def test_merge_each_starter_twice_into_campus_demo(self):
        base = _campus()
        base_errors = _errors(self.schema.validate_doc(base))
        for sid in STARTER_IDS:
            with self.subTest(starter=sid):
                doc1, info1 = self.starters.merge_room(base, sid)
                doc2, info2 = self.starters.merge_room(doc1, sid)
                self.assertEqual(len(base["rooms"]), 3, "the input doc is not modified")
                self.assertEqual(len(doc2["rooms"]), 5)
                self.assertNotEqual(info1["room"], info2["room"], "a starter can be added twice")
                self.assertEqual(_errors(self.schema.validate_doc(doc2)), base_errors, fr("FR-ROOM-10", "3.1", "zero errors after merging twice"))
                src = self.starters.load_starter_doc(sid)
                self.assertEqual(info1["devices"], len(src["devices"]))
                self.assertEqual(info1["cables"], len(src["cables"]))
                self.assertEqual(info1["racks"], len(src["racks"]))
                self.assertEqual(info1["pages"], 1)
                ids = [e["id"] for coll in self.schema.COLLECTIONS for e in doc2.get(coll) or []]
                self.assertEqual(len(ids), len(set(ids)), "ids are unique across the doc")
                for coll in ("devices", "cables", "racks", "systems", "locations", "pages"):
                    mine = [e for e in doc2[coll] if e["id"].startswith(info2["room"] + "-")]
                    self.assertEqual(len(mine), len(src[coll]), coll)
                for d in doc2["devices"]:
                    if d["id"].startswith(info2["room"] + "-"):
                        self.assertEqual(d["room"], info2["room"])
                        if isinstance(d.get("rack"), dict):
                            self.assertTrue(d["rack"]["id"].startswith(info2["room"] + "-"))
                page = [p for p in doc2["pages"] if p["id"].startswith(info2["room"] + "-")][0]
                self.assertTrue(page["slug"].startswith(info2["room"] + "-"))
                self.assertEqual(page["rooms"], [info2["room"]])
                linked = re.findall(r"\[\[device:([^\]|]+)", page["body"])
                dev_ids = {d["id"] for d in doc2["devices"]}
                self.assertTrue(linked and all(l in dev_ids for l in linked), "page links are re-prefixed to existing devices")
                self.assertTrue(all(l.startswith(info2["room"] + "-") for l in linked))
                tags = [c.get("tag") for c in doc2["cables"] if c.get("tag")]
                self.assertEqual(len(tags), len(set(tags)), "cable tags stay unique")

    def test_networks_are_shared_and_room_name_slug_prefix(self):
        base = _campus()
        before = {n["id"] for n in base["networks"]}
        doc, info = self.starters.merge_room(base, "church-broadcast", "Stream Room")
        self.assertEqual(info["room"], "stream-room", fr("FR-ROOM-10", "3.1", "room id is the slug of the name"))
        self.assertEqual(info["name"], "Stream Room")
        after = {n["id"] for n in doc["networks"]}
        self.assertTrue(before <= after)
        self.assertIn("av-stream", after - before)
        self.assertEqual(len([n for n in doc["networks"] if n["id"] == "av-dante"]), 1, "existing networks are kept once")
        room = [r for r in doc["rooms"] if r["id"] == "stream-room"][0]
        self.assertEqual(room["venue"], "riverside", "attached to the project's venue")
        self.assertEqual(room["code"], "STRE")
        # the room name of an existing room gets a deduped id and code
        doc2, info2 = self.starters.merge_room(base, "church-chapel", "Chapel")
        self.assertEqual(info2["room"], "chapel-2")
        self.assertNotEqual(info2["code"], "CHPL")
        self.assertEqual(_errors(self.schema.validate_doc(doc2)), [])

    def test_explicit_prefix_and_blank_doc(self):
        doc = self.schema.new_doc("Blank")
        merged, info = self.starters.merge_room(doc, "church-youth-room", prefix="yr")
        self.assertEqual(info["room"], "yr")
        self.assertTrue(all(d["id"].startswith("yr-") for d in merged["devices"]))
        self.assertEqual(_errors(self.schema.validate_doc(merged)), [])
        self.assertEqual(len(merged["venues"]), 1)

    def test_unknown_starter(self):
        with self.assertRaises(self.starters.StarterError):
            self.starters.merge_room(_campus(), "church-nope")


class StarterRoutes(unittest.TestCase):
    def setUp(self):
        requires("server")
        self.app = get_app()

    def test_list_route(self):
        st, _, b = call(self.app, "GET", "/api/v2/starters")
        self.assertEqual(st, 200, b[:200])
        rows = jbody(b)["starters"]
        self.assertEqual([r["id"] for r in rows], STARTER_IDS, fr("FR-ROOM-09", "5.6", "GET /api/v2/starters"))
        self.assertTrue(all(r["devices"] >= 8 for r in rows))

    def test_meta_samples_include_starters(self):
        st, _, b = call(self.app, "GET", "/api/v2/meta")
        self.assertEqual(st, 200)
        samples = jbody(b)["samples"]
        for sid in STARTER_IDS:
            self.assertIn(sid, samples, fr("FR-ROOM-09", "5.5", "starters are project templates"))

    def test_from_starter_201_400_423(self):
        with temp_data_dir() as data:
            install_project(data, "proj", src_dir=CAMPUS_DIR)
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj")
            rev0 = jbody(b)["revision"]
            st, h, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/from-starter", {"starter": "church-youth-room", "name": "Youth loft"}, JSON_H)
            self.assertEqual(st, 201, b[:300])
            out = jbody(b)
            self.assertEqual(out["room"], "youth-loft", fr("FR-ROOM-10", "5.6", "201 with the new room id"))
            self.assertEqual(out["info"]["devices"], 18)
            self.assertGreater(out["revision"], rev0)
            self.assertEqual(h.get("ETag"), '"r%d"' % out["revision"])
            self.assertEqual([p for p in out["problems"] if p["level"] == "error"], [])
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj")
            doc = jbody(b)["doc"]
            self.assertIn("youth-loft", [r["id"] for r in doc["rooms"]])
            self.assertEqual(len([d for d in doc["devices"] if d.get("room") == "youth-loft"]), 18)
            self.assertTrue(all(d.get("short_code") for d in doc["devices"] if d.get("room") == "youth-loft"), "the store assigned short codes")
            # one history revision with source starter
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj/history?limit=1")
            entry = jbody(b)["revisions"][0]
            self.assertEqual(entry["source"], "starter")
            self.assertEqual(entry["summary"], "Added room Youth loft from starter Youth room / multipurpose")
            # unknown starter
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/from-starter", {"starter": "church-nope"}, JSON_H)
            self.assertEqual(st, 400)
            self.assertEqual(jbody(b)["code"], "bad_enum")
            # locked project
            rev = out["revision"]
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes",
                            {"base_revision": rev, "ops": [{"op": "root", "key": "settings", "value": {"locked": True}}]}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/from-starter", {"starter": "church-chapel"}, JSON_H)
            self.assertEqual(st, 423, fr("FR-USER-12", "5.6", "starters respect the editing lock"))
            self.assertEqual(jbody(b)["code"], "locked")
            # simple-request body without the CSRF header
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/from-starter", '{"starter": "church-chapel"}', {"Content-Type": "text/plain"})
            self.assertEqual(st, 403)
            self.assertEqual(jbody(b)["code"], "csrf")
            # unknown project
            st, _, b = call(self.app, "POST", "/api/v2/projects/nope/rooms/from-starter", {"starter": "church-chapel"}, JSON_H)
            self.assertEqual(st, 404)

    def test_default_name_and_twice(self):
        with temp_data_dir() as data:
            install_project(data, "proj", src_dir=CAMPUS_DIR)
            for expect in ("portable-church", "portable-church-2"):
                st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/from-starter", {"starter": "church-portable"}, JSON_H)
                self.assertEqual(st, 201, b[:300])
                self.assertEqual(jbody(b)["room"], expect)
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj")
            doc = jbody(b)["doc"]
            self.assertEqual(len(doc["rooms"]), 5)
            self.assertEqual([p for p in jbody(b)["problems"] if p["level"] == "error"], [])

    def test_viewer_cannot_add_but_can_list(self):
        from fathom.users import add_user

        with temp_data_dir(FATHOM_AUTH="1") as data:
            install_project(data, "proj", src_dir=CAMPUS_DIR)
            add_user("v", "viewer-password-1", "viewer")
            from _helpers import basic  # type: ignore
            st, _, b = call(self.app, "GET", "/api/v2/starters", None, basic("v", "viewer-password-1"))
            self.assertEqual(st, 200)
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/from-starter", {"starter": "church-chapel"}, dict(JSON_H, **basic("v", "viewer-password-1")))
            self.assertEqual(st, 403)


class StarterAsTemplate(unittest.TestCase):
    def test_new_project_from_starter(self):
        project = requires("project")
        schema = requires("schema")
        with temp_data_dir():
            pdir = project.new_project("x", template="church-sanctuary")
            doc = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["rooms"][0]["id"], "sanc")
            self.assertEqual(_errors(schema.validate_doc(doc)), [])
            self.assertTrue(all(d.get("short_code") for d in doc["devices"]), "short codes assigned on creation")
            loaded, _ = project.load_project("x")
            self.assertTrue(loaded.nodes)
            with self.assertRaises(SystemExit):
                project.new_project("y", template="church-nope")

    def test_create_project_route_accepts_starter_template(self):
        requires("server")
        app = get_app()
        with temp_data_dir():
            st, _, b = call(app, "POST", "/api/v2/projects", {"name": "chapel", "template": "church-chapel"}, JSON_H)
            self.assertEqual(st, 201, b[:300])
            st, _, b = call(app, "GET", "/api/v2/projects/chapel")
            self.assertEqual(jbody(b)["doc"]["rooms"][0]["id"], "chpl")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
