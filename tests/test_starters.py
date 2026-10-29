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


# ---------------------------------------------------------------- user starters (phase6 P6A, FR-ROOM-11)


class RoomExtraction(unittest.TestCase):
    """``room_to_starter_doc``: the room's slice of campus-demo, cross-room cables and attachments dropped, inventory cleared."""

    def setUp(self):
        self.schema = requires("schema")
        self.starters = requires("starters")

    def test_main_room_slice_validates_and_keeps_ids(self):
        base = _campus()
        out, info = self.starters.room_to_starter_doc(base, "main", "Big room")
        self.assertEqual(len(base["rooms"]), 3, "the input doc is not modified")
        self.assertEqual(_errors(self.schema.validate_doc(out)), [], fr("FR-ROOM-11", "3.1", "the extracted doc validates"))
        self.assertEqual([r["id"] for r in out["rooms"]], ["main"], "ids are kept; merge_room re-prefixes on use")
        self.assertEqual(out["settings"]["default_room"], "main")
        self.assertEqual(out["meta"]["title"], "Main Auditorium")
        self.assertEqual(out["meta"]["description"], "Big room")
        self.assertEqual(out["meta"]["org"], base["meta"]["org"])
        self.assertEqual([v["id"] for v in out["venues"]], ["riverside"])
        src_devs = [d for d in base["devices"] if d.get("room") == "main"]
        self.assertEqual(info["devices"], len(src_devs))
        self.assertEqual({d["id"] for d in out["devices"]}, {d["id"] for d in src_devs})
        for coll in ("systems", "racks"):
            self.assertTrue(all(e["room"] == "main" for e in out[coll]), coll)
        self.assertEqual(out["attachments"], [], "attachments are never copied")
        self.assertEqual(out["floorplans"], [], "a floor plan whose image is a file goes with the file")
        self.assertEqual(out["problems"], [])
        self.assertEqual(out["scenes"], [])
        self.assertEqual(out["imports"], [])

    def test_cables_need_both_ends_in_the_room(self):
        base = _campus()
        out, info = self.starters.room_to_starter_doc(base, "main")
        main_ids = {d["id"] for d in base["devices"] if d.get("room") == "main"}
        both = [c for c in base["cables"] if c["from"]["device"] in main_ids and c["to"]["device"] in main_ids]
        one = [c for c in base["cables"] if (c["from"]["device"] in main_ids) != (c["to"]["device"] in main_ids)]
        self.assertTrue(one, "campus-demo has cross-room cables to test with")
        self.assertEqual(info["cables"], len(both))
        self.assertEqual(info["dropped_cables"], len(one), fr("FR-ROOM-11", "5.6", "cables with one end elsewhere are dropped and counted"))
        kept = {c["id"] for c in out["cables"]}
        self.assertTrue(all(c["id"] in kept for c in both))
        self.assertFalse(any(c["id"] in kept for c in one))
        bundle_ids = {b["id"] for b in out["bundles"]}
        self.assertTrue(all(c.get("bundle") in bundle_ids for c in out["cables"] if c.get("bundle")), "kept cables only reference kept bundles")
        self.assertTrue(all(any(c.get("bundle") == b for c in out["cables"]) for b in bundle_ids), "bundles without members are dropped")

    def test_attachments_dropped_and_counted(self):
        base = _campus()
        main_ids = {d["id"] for d in base["devices"] if d.get("room") == "main"}
        fps = [f for f in base["floorplans"] if f["room"] == "main"]
        refs = set()
        for f in fps:
            for k in ("source", "image"):
                if isinstance(f.get(k), dict) and f[k].get("attachment"):
                    refs.add(f[k]["attachment"])
        refs |= {a["id"] for a in base["attachments"] if a.get("device") in main_ids}
        for p in base["pages"]:
            if "main" in (p.get("rooms") or []):
                refs |= set(p.get("attachments") or [])
        self.assertTrue(refs, "campus-demo has files attached to the main room")
        out, info = self.starters.room_to_starter_doc(base, "main")
        self.assertEqual(info["dropped_files"], len(refs), fr("FR-ROOM-11", "5.6", "each attachment left behind counts once"))
        self.assertTrue(all(not p.get("attachments") for p in out["pages"]))
        # a floor plan without a file keeps only the markers of kept devices
        doc = json.loads(json.dumps(base))
        doc["floorplans"].append({"id": "fp-sketch", "name": "Sketch", "room": "main", "source": {"kind": "svg"}, "image": {"kind": "svg", "width": 10, "height": 10},
                                  "markers": [{"device": "foh-cl5", "x": 0.5, "y": 0.5}, {"device": "chapel-mixer", "x": 0.1, "y": 0.1}]})
        out2, _ = self.starters.room_to_starter_doc(doc, "main")
        fp = [f for f in out2["floorplans"] if f["id"] == "fp-sketch"]
        self.assertEqual(len(fp), 1)
        self.assertEqual([m["device"] for m in fp[0]["markers"]], ["foh-cl5"])

    def test_inventory_status_and_codes_are_cleared(self):
        base = _campus()
        dev = [d for d in base["devices"] if d.get("room") == "main"][0]
        dev["status"] = "installed"
        dev["code"] = "A1"
        dev["short_code"] = "ABCD2345"
        dev["inventory"] = {"serial": "SN-1", "asset_tag": "AT-1", "price": 999, "cost": 999.5, "condition": "good", "firmware": "1.2"}
        out, _ = self.starters.room_to_starter_doc(base, "main")
        x = [d for d in out["devices"] if d["id"] == dev["id"]][0]
        self.assertEqual(x["status"], "planned", fr("FR-ROOM-11", "3.1", "templates are not inventories"))
        self.assertNotIn("code", x)
        self.assertNotIn("short_code", x)
        self.assertEqual(x["inventory"], {"condition": "good", "firmware": "1.2"})
        self.assertTrue(all(d["status"] == "planned" and "short_code" not in d for d in out["devices"]))

    def test_pages_networks_templates_follow_the_room(self):
        base = _campus()
        out, info = self.starters.room_to_starter_doc(base, "chapel")
        self.assertEqual(_errors(self.schema.validate_doc(out)), [])
        self.assertEqual([p["slug"] for p in out["pages"]], ["chapel-pre-service"])
        self.assertEqual(out["pages"][0]["rooms"], ["chapel"])
        chapel_ids = {d["id"] for d in out["devices"]}
        used = {i.get("network") for d in out["devices"] for i in d.get("interfaces") or [] if i.get("network")}
        self.assertEqual({n["id"] for n in out["networks"]}, used, "only networks kept devices use are copied")
        self.assertEqual(info["networks"], len(used))
        tpls = {d.get("template") for d in out["devices"] if d.get("template")}
        self.assertEqual({t["id"] for t in out["templates"]}, {t["id"] for t in base["templates"] if t["id"] in tpls})
        self.assertTrue(all(x in chapel_ids for p in out["pages"] for x in p.get("devices") or []), "page device links point at kept devices")

    def test_unknown_room(self):
        with self.assertRaises(self.starters.StarterError) as cm:
            self.starters.room_to_starter_doc(_campus(), "nope")
        self.assertEqual(cm.exception.code, "not_found")


class UserStarterStore(unittest.TestCase):
    """``save_starter`` / ``delete_starter`` / ``list_starters`` on ``FATHOM_DATA/starters``: ids, dedupe, replace, bundled protection, lock, corrupt entries."""

    def setUp(self):
        self.schema = requires("schema")
        self.starters = requires("starters")

    def test_save_lists_loads_merges_and_deletes(self):
        with temp_data_dir() as data:
            entry, info = self.starters.save_starter(_campus(), "main", "  Main Auditorium ", "Big room", ["Audio", "video", "x y", "audio"], author="ada", source_project="campus")
            self.assertEqual(entry["id"], "user-main-auditorium", fr("FR-ROOM-11", "5.6", "id = user-<slug(label)>"))
            self.assertEqual(entry["source"], "user")
            self.assertEqual(entry["label"], "Main Auditorium")
            self.assertEqual(entry["tags"], ["audio", "video", "x-y"])
            self.assertEqual(entry["room"], "main")
            self.assertEqual(entry["room_name"], "Main Auditorium")
            self.assertEqual(entry["devices"], info["devices"])
            self.assertEqual(entry["created_by"], "ada")
            self.assertEqual(entry["source_project"], "campus")
            sdir = data / "starters" / "user-main-auditorium"
            self.assertTrue((sdir / "starter.json").is_file() and (sdir / "project.json").is_file())
            self.assertTrue((data / "starters" / ".lock").exists(), "writes go under FATHOM_DATA/starters/.lock")
            meta = json.loads((sdir / "starter.json").read_text(encoding="utf-8"))
            self.assertEqual(set(meta), {"id", "label", "blurb", "room", "tags", "created", "created_by", "source_project", "source_room"})
            self.assertEqual(meta["source_room"], "main")
            rows = self.starters.list_starters()
            self.assertEqual([r["id"] for r in rows], STARTER_IDS + ["user-main-auditorium"], "bundled first, then user starters")
            self.assertEqual([r["source"] for r in rows], ["bundled"] * 5 + ["user"])
            self.assertEqual(self.starters.get_starter("user-main-auditorium")["room"], "main")
            self.assertEqual(self.starters.get_starter("church-chapel")["source"], "bundled")
            doc = self.starters.load_starter_doc("user-main-auditorium")
            self.assertEqual(_errors(self.schema.validate_doc(doc)), [])
            # merge_room accepts the user id transparently and the result validates
            merged, minfo = self.starters.merge_room(_campus(), "user-main-auditorium", "Second hall")
            self.assertEqual(minfo["room"], "second-hall")
            self.assertEqual(minfo["devices"], info["devices"])
            self.assertEqual(_errors(self.schema.validate_doc(merged)), [])
            self.assertTrue(all(d["id"].startswith("second-hall-") for d in merged["devices"] if d["room"] == "second-hall"))
            self.starters.delete_starter("user-main-auditorium")
            self.assertFalse(sdir.exists())
            self.assertEqual([r["id"] for r in self.starters.list_starters()], STARTER_IDS)
            self.assertIsNone(self.starters.get_starter("user-main-auditorium"))
            with self.assertRaises(self.starters.StarterError) as cm:
                self.starters.load_starter_doc("user-main-auditorium")
            self.assertEqual(cm.exception.code, "not_found")

    def test_exists_dedupe_replace_and_bundled(self):
        with temp_data_dir():
            base = _campus()
            self.starters.save_starter(base, "main", "Hall")
            with self.assertRaises(self.starters.StarterError) as cm:
                self.starters.save_starter(base, "main", "Hall")
            self.assertEqual(cm.exception.code, "exists")
            e2, _ = self.starters.save_starter(base, "main", "Hall", dedupe=True)
            self.assertEqual(e2["id"], "user-hall-2", fr("FR-ROOM-11", "5.6", "deduped with -2, -3…"))
            e3, _ = self.starters.save_starter(base, "main", "Hall", dedupe=True)
            self.assertEqual(e3["id"], "user-hall-3")
            e4, _ = self.starters.save_starter(base, "chapel", "Hall", "now the chapel", replace=True)
            self.assertEqual(e4["id"], "user-hall")
            self.assertEqual(e4["room"], "chapel")
            self.assertEqual(e4["blurb"], "now the chapel")
            self.assertEqual(self.starters.load_starter_doc("user-hall")["rooms"][0]["id"], "chapel")
            for code, kw in (("bundled", {"starter_id": "church-chapel"}), ("bad_id", {"starter_id": "hall"}), ("missing_field", {})):
                with self.assertRaises(self.starters.StarterError) as cm:
                    self.starters.save_starter(base, "main", "" if code == "missing_field" else "Hall", replace=True, **kw)
                self.assertEqual(cm.exception.code, code)
            with self.assertRaises(self.starters.StarterError) as cm:
                self.starters.delete_starter("church-chapel")
            self.assertEqual(cm.exception.code, "bundled", fr("FR-ROOM-11", "5.6", "bundled starters cannot be deleted"))
            self.assertTrue((SAMPLES / "church-chapel" / "project.json").is_file())
            with self.assertRaises(self.starters.StarterError) as cm:
                self.starters.delete_starter("user-nope")
            self.assertEqual(cm.exception.code, "not_found")
            with self.assertRaises(self.starters.StarterError):
                self.starters.delete_starter("../projects")

    def test_corrupt_user_starters_are_skipped(self):
        with temp_data_dir() as data:
            self.starters.save_starter(_campus(), "main", "Good")
            bad = data / "starters" / "user-bad"
            bad.mkdir(parents=True)
            (bad / "starter.json").write_text("{not json", encoding="utf-8")
            (bad / "project.json").write_text("{}", encoding="utf-8")
            nometa = data / "starters" / "user-nometa"
            nometa.mkdir()
            (nometa / "project.json").write_text("{}", encoding="utf-8")
            (data / "starters" / "Not-A-Starter").mkdir()
            self.assertEqual([r["id"] for r in self.starters.list_starters()], STARTER_IDS + ["user-good"], fr("FR-ROOM-11", "5.6", "corrupt entries are skipped"))
            for sid in ("user-bad", "user-nometa", "user-missing"):
                self.assertIsNone(self.starters.get_starter(sid))
                with self.assertRaises(self.starters.StarterError) as cm:
                    self.starters.load_starter_doc(sid)
                self.assertEqual(cm.exception.code, "not_found", sid)
                with self.assertRaises(self.starters.StarterError) as cm:
                    self.starters.merge_room(_campus(), sid)
            # a descriptor that parses but points at a corrupt doc
            (bad / "starter.json").write_text(json.dumps({"id": "user-bad", "label": "Bad", "room": "main"}), encoding="utf-8")
            (bad / "project.json").write_text("{nope", encoding="utf-8")
            self.assertEqual([r["id"] for r in self.starters.list_starters()], STARTER_IDS + ["user-good"])
            with self.assertRaises(self.starters.StarterError) as cm:
                self.starters.starter_entry("user-bad")
            self.assertEqual(cm.exception.code, "not_found")

    def test_save_holds_the_starters_lock(self):
        import threading

        project = requires("project")
        with temp_data_dir() as data:
            root = data / "starters"
            starters = self.starters
            got = {}

            def worker():
                starters.save_starter(_campus(), "chapel", "Locked")
                got["done"] = True

            with project.project_lock(root):
                t = threading.Thread(target=worker)
                t.start()
                t.join(0.6)
                self.assertTrue(t.is_alive(), fr("FR-ROOM-11", "5.6", "save_starter waits for FATHOM_DATA/starters/.lock"))
                self.assertFalse(got)
            t.join(10)
            self.assertTrue(got.get("done"))
            self.assertEqual(self.starters.get_starter("user-locked")["room"], "chapel")


class UserStarterRoutes(unittest.TestCase):
    """``POST …/rooms/<room>/save-starter``, ``GET`` / ``DELETE /api/v2/starters/<id>``; roles."""

    def setUp(self):
        requires("server")
        self.app = get_app()

    def test_save_get_list_merge_delete(self):
        with temp_data_dir() as data:
            install_project(data, "proj", src_dir=CAMPUS_DIR)
            body = {"label": "Main hall", "blurb": "Our big room", "tags": ["audio", "video"]}
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/main/save-starter", body, JSON_H)
            self.assertEqual(st, 201, b[:300])
            out = jbody(b)
            self.assertEqual(set(out), {"starter", "dropped_cables", "dropped_files"}, fr("FR-ROOM-11", "5.6", "201 body"))
            s = out["starter"]
            self.assertEqual(s["id"], "user-main-hall")
            self.assertEqual(s["source"], "user")
            self.assertEqual(s["tags"], ["audio", "video"])
            self.assertEqual(s["source_project"], "proj")
            self.assertEqual(s["source_room"], "main")
            self.assertGreater(out["dropped_cables"], 0)
            self.assertGreater(out["dropped_files"], 0)
            self.assertTrue((data / "starters" / "user-main-hall" / "project.json").is_file())
            # GET one (user and bundled)
            st, _, b = call(self.app, "GET", "/api/v2/starters/user-main-hall")
            self.assertEqual(st, 200)
            self.assertEqual(jbody(b)["starter"]["devices"], s["devices"])
            st, _, b = call(self.app, "GET", "/api/v2/starters/church-chapel")
            self.assertEqual(st, 200)
            self.assertEqual(jbody(b)["starter"]["source"], "bundled")
            st, _, b = call(self.app, "GET", "/api/v2/starters/user-nope")
            self.assertEqual(st, 404)
            st, _, b = call(self.app, "GET", "/api/v2/starters")
            rows = jbody(b)["starters"]
            self.assertEqual([r["id"] for r in rows], STARTER_IDS + ["user-main-hall"])
            # the project revision did not move: saving a starter is not a project write
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj/history?limit=1")
            self.assertEqual(jbody(b)["revisions"], [])
            # from-starter accepts the user id
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/from-starter", {"starter": "user-main-hall", "name": "Hall two"}, JSON_H)
            self.assertEqual(st, 201, b[:300])
            self.assertEqual(jbody(b)["room"], "hall-two")
            self.assertEqual(jbody(b)["info"]["devices"], s["devices"])
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj/history?limit=1")
            self.assertEqual(jbody(b)["revisions"][0]["summary"], "Added room Hall two from starter Main hall")
            # exists → 409, replace → 201 with the same id
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/chapel/save-starter", {"label": "Main hall"}, JSON_H)
            self.assertEqual(st, 409)
            self.assertEqual(jbody(b)["code"], "exists")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/chapel/save-starter", {"label": "Main hall", "replace": True}, JSON_H)
            self.assertEqual(st, 201, b[:300])
            self.assertEqual(jbody(b)["starter"]["room"], "chapel")
            # bundled ids can never be replaced
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/chapel/save-starter", {"label": "Chapel", "id": "church-chapel", "replace": True}, JSON_H)
            self.assertEqual(st, 409)
            self.assertEqual(jbody(b)["code"], "bundled")
            # 400 empty label / bad tags, 404 unknown room / project
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/main/save-starter", {"label": "  "}, JSON_H)
            self.assertEqual(st, 400)
            self.assertEqual(jbody(b)["code"], "missing_field")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/main/save-starter", {"label": "x", "tags": "audio"}, JSON_H)
            self.assertEqual(st, 400)
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/nope/save-starter", {"label": "x"}, JSON_H)
            self.assertEqual(st, 404)
            st, _, b = call(self.app, "POST", "/api/v2/projects/nope/rooms/main/save-starter", {"label": "x"}, JSON_H)
            self.assertEqual(st, 404)
            # CSRF guard
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/main/save-starter", '{"label": "x"}', {"Content-Type": "text/plain"})
            self.assertEqual(st, 403)
            # DELETE: 409 bundled, 204 user, 404 after
            st, _, b = call(self.app, "DELETE", "/api/v2/starters/church-chapel", None, JSON_H)
            self.assertEqual(st, 409)
            self.assertEqual(jbody(b)["code"], "bundled")
            st, _, b = call(self.app, "DELETE", "/api/v2/starters/user-main-hall", None, JSON_H)
            self.assertEqual(st, 204, b[:200])
            self.assertFalse((data / "starters" / "user-main-hall").exists())
            st, _, b = call(self.app, "DELETE", "/api/v2/starters/user-main-hall", None, JSON_H)
            self.assertEqual(st, 404)
            st, _, b = call(self.app, "GET", "/api/v2/starters")
            self.assertEqual([r["id"] for r in jbody(b)["starters"]], STARTER_IDS)

    def test_roles_editor_saves_admin_deletes(self):
        from fathom.users import add_user

        with temp_data_dir(FATHOM_AUTH="1") as data:
            install_project(data, "proj", src_dir=CAMPUS_DIR)
            add_user("v", "viewer-password-1", "viewer")
            add_user("e", "editor-password-1", "editor")
            add_user("a", "admin-password-01", "admin")
            from _helpers import basic  # type: ignore
            v, e, a = basic("v", "viewer-password-1"), basic("e", "editor-password-1"), basic("a", "admin-password-01")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/main/save-starter", {"label": "Hall"}, dict(JSON_H, **v))
            self.assertEqual(st, 403, fr("FR-ROOM-11", "5.6", "viewers cannot save"))
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/rooms/main/save-starter", {"label": "Hall"}, dict(JSON_H, **e))
            self.assertEqual(st, 201, b[:200])
            self.assertEqual(jbody(b)["starter"]["created_by"], "e")
            st, _, b = call(self.app, "GET", "/api/v2/starters/user-hall", None, v)
            self.assertEqual(st, 200, "viewers can read")
            st, _, b = call(self.app, "DELETE", "/api/v2/starters/user-hall", None, dict(JSON_H, **e))
            self.assertEqual(st, 403, fr("FR-ROOM-11", "5.6", "only admins delete"))
            st, _, b = call(self.app, "DELETE", "/api/v2/starters/user-hall", None, dict(JSON_H, **a))
            self.assertEqual(st, 204)

    def test_openapi_has_the_schemas_and_routes(self):
        st, _, b = call(self.app, "GET", "/api/openapi.json")
        spec = jbody(b)
        for name in ("StarterSave", "StarterInfo"):
            self.assertIn(name, spec["components"]["schemas"])
        self.assertIn("post", spec["paths"]["/api/v2/projects/{name}/rooms/{room}/save-starter"])
        self.assertEqual(set(spec["paths"]["/api/v2/starters/{starter}"]), {"get", "delete"})


class UserStarterCli(unittest.TestCase):
    def test_new_project_from_user_starter_and_starters_listing(self):
        import io
        from contextlib import redirect_stdout

        cli = requires("cli")
        project = requires("project")
        schema = requires("schema")
        starters = requires("starters")
        with temp_data_dir():
            starters.save_starter(_campus(), "chapel", "Our chapel", "small")
            with redirect_stdout(io.StringIO()):
                cli.main(["new", "fromstarter", "--template", "user-our-chapel", "--org", "St Mary"])
            pdir = project.projects_root() / "fromstarter"
            doc = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["rooms"][0]["id"], "chapel", fr("FR-ROOM-11", "5.6", "fathom new --template user-<slug>"))
            self.assertEqual(doc["meta"]["org"], "St Mary")
            self.assertEqual(_errors(schema.validate_doc(doc)), [])
            self.assertTrue(all(d.get("short_code") for d in doc["devices"]), "short codes assigned on creation")
            loaded, _ = project.load_project("fromstarter")
            self.assertTrue(loaded.nodes)
            with self.assertRaises(SystemExit):
                cli.main(["new", "y", "--template", "user-nope"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.main(["starters"])
            lines = buf.getvalue().splitlines()
            ids = [ln.split()[0] for ln in lines[1:-1]]
            self.assertEqual(ids, STARTER_IDS + ["user-our-chapel"])
            row = [ln for ln in lines if ln.startswith("user-our-chapel")][0].split()
            self.assertEqual(row[1], "user")
            self.assertEqual(row[-2:], [str(len(doc["devices"])), str(len(doc["cables"]))])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
