"""Scenes (SPEC FR-SCN §3.29, §4.3.18 ``scenes[]``, §5.6 "Scenes", §5.13 ``?scene=``): capture / apply round trip,
diff shapes and text, activate (Base entry, swap, settings.scene, undo through history restore), create with
copy_from, delete, routes incl. 423 under the editing lock, viewer preview routes and validation warnings."""

from __future__ import annotations

import copy
import unittest

try:
    from _helpers import call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
P = "/api/v2/projects/proj"


def _doc():
    """Sunday fixture, normalized, with one floor plan carrying two markers."""
    schema = requires("schema")
    doc = schema.normalize(sunday_doc())
    doc["floorplans"] = [{"id": "fp-main", "name": "Main", "room": "main", "source": {"kind": "svg"}, "image": {"kind": "svg"},
                          "markers": [{"device": "sound-board", "x": 0.5, "y": 0.8}, {"device": "atem-mini", "x": 0.6, "y": 0.8}]}]
    return doc


def _dev(doc, did):
    return next(d for d in doc["devices"] if d["id"] == did)


def _cable(cid, frm, to, medium="analog"):
    return {"id": cid, "from": {"device": frm}, "to": {"device": to}, "medium": medium}


class CaptureApply(unittest.TestCase):
    def setUp(self):
        self.S = requires("scenes")
        self.schema = requires("schema")

    def test_capture_shape_and_round_trip(self):
        doc = _doc()
        data = self.S.capture(doc)
        self.assertEqual(sorted(data), ["bundles", "cables", "devices", "markers"], fr("FR-SCN-01", "4.3.18", "SceneData keys"))
        self.assertEqual(len(data["cables"]), len(doc["cables"]))
        self.assertEqual(data["markers"], {"fp-main": doc["floorplans"][0]["markers"]})
        self.assertEqual(data["devices"]["shure-wireless"], {"room": "main", "rack": _dev(doc, "shure-wireless")["rack"], "patch": {"x": 40, "y": 220}},
                         "only the four placement fields, only those present")
        self.assertEqual(data["devices"]["spare-ulxd4d"], {}, "a device without placement gets an empty entry")
        self.assertIsNot(data["cables"][0], doc["cables"][0], "deep copies")
        back = self.S.apply(doc, data)
        self.assertEqual(self.schema.diff_docs(doc, back), [], fr("FR-SCN-01", "4.3.18", "capture → apply is the identity"))
        self.assertIsNot(back, doc)
        self.assertEqual(doc, _doc(), "inputs are never mutated")

    def test_apply_replaces_and_removes_placement(self):
        doc = _doc()
        data = self.S.capture(doc)
        data["cables"] = [_cable("c-new", "sound-board", "main-speakers")]
        data["bundles"] = [{"id": "b-1", "kind": "loom"}]
        data["devices"]["shure-wireless"] = {"room": "main", "location": "foh"}  # rack + patch gone, location added
        data["markers"]["fp-main"] = []
        del data["devices"]["sound-board"]  # untouched
        out = self.S.apply(doc, data)
        self.assertEqual([c["id"] for c in out["cables"]], ["c-new"])
        self.assertEqual(out["bundles"], [{"id": "b-1", "kind": "loom"}])
        sw = _dev(out, "shure-wireless")
        self.assertEqual({k: sw.get(k) for k in ("room", "location")}, {"room": "main", "location": "foh"})
        self.assertNotIn("rack", sw, fr("FR-SCN-01", "4.3.18", "a key absent from the entry is removed"))
        self.assertNotIn("patch", sw)
        self.assertEqual(sw["ports"], _dev(doc, "shure-wireless")["ports"], "non-placement fields untouched")
        self.assertEqual(_dev(out, "sound-board"), _dev(doc, "sound-board"), "device missing from data is left unchanged")
        self.assertEqual(out["floorplans"][0]["markers"], [])
        # a floor plan absent from data.markers keeps its markers
        data2 = self.S.capture(doc)
        data2["markers"] = {}
        self.assertEqual(self.S.apply(doc, data2)["floorplans"][0]["markers"], doc["floorplans"][0]["markers"])

    def test_apply_drops_refs_to_deleted_devices(self):
        doc = _doc()
        data = self.S.capture(doc)
        data["cables"].append(_cable("c-ghost", "sound-board", "gone-device"))
        data["markers"]["fp-main"].append({"device": "gone-device", "x": 0.1, "y": 0.1})
        data["devices"]["gone-device"] = {"room": "main"}
        out = self.S.apply(doc, data)
        self.assertNotIn("c-ghost", [c["id"] for c in out["cables"]], "cables to deleted devices are dropped on apply")
        self.assertEqual([m["device"] for m in out["floorplans"][0]["markers"]], ["sound-board", "atem-mini"])
        self.assertEqual(self.schema.errors(self.schema.validate_doc(out)), [])


class Diff(unittest.TestCase):
    def setUp(self):
        self.S = requires("scenes")

    def test_diff_cases_and_text(self):
        doc = _doc()
        a = self.S.capture(doc)
        b = copy.deepcopy(a)
        b["cables"] = [c for c in b["cables"] if c["id"] != "c-0001"]  # removed
        b["cables"].append(_cable("c-x1", "sound-board", "main-speakers"))  # added
        b["cables"].append(_cable("c-x2", "sound-board", "sub-x2"))
        nxt = next(c for c in b["cables"] if c["id"] == "c-0002")
        nxt["medium"] = "aes3"
        nxt["tag"] = "A-002"
        b["devices"]["sound-board"] = {"room": "main", "location": "stage-left", "patch": {"x": 360, "y": 40}}
        b["devices"]["spare-ulxd4d"] = {"rack": {"id": "rk-foh", "u": 3}}
        b["markers"]["fp-main"] = [{"device": "sound-board", "x": 0.2, "y": 0.8}, {"device": "restream", "x": 0.9, "y": 0.9}]
        d = self.S.diff(a, b)
        self.assertEqual(sorted(d), ["bundles", "cables", "devices", "markers", "summary", "text"])
        self.assertEqual([c["id"] for c in d["cables"]["added"]], ["c-x1", "c-x2"], fr("FR-SCN-02", "4.3.18", "added = only in b"))
        self.assertEqual([c["id"] for c in d["cables"]["removed"]], ["c-0001"])
        self.assertEqual(len(d["cables"]["changed"]), 1)
        ch = d["cables"]["changed"][0]
        self.assertEqual((ch["id"], ch["fields"], ch["before"]["medium"], ch["after"]["medium"]), ("c-0002", ["medium", "tag"], "rf", "aes3"))
        moved = {m["id"]: m for m in d["devices"]["moved"]}
        self.assertEqual(sorted(moved), ["sound-board", "spare-ulxd4d"])
        self.assertEqual(moved["sound-board"]["fields"], ["location"])
        self.assertEqual((moved["sound-board"]["before"]["location"], moved["sound-board"]["after"]["location"]), ("foh", "stage-left"))
        self.assertEqual(moved["spare-ulxd4d"]["before"], {})
        self.assertEqual([(m["fp"], m["device"]) for m in d["markers"]["added"]], [("fp-main", "restream")])
        self.assertEqual([(m["fp"], m["device"]) for m in d["markers"]["removed"]], [("fp-main", "atem-mini")])
        self.assertEqual([(m["fp"], m["device"], m["fields"]) for m in d["markers"]["moved"]], [("fp-main", "sound-board", ["x"])])
        self.assertEqual(d["summary"], {"cables_added": 2, "cables_removed": 1, "cables_changed": 1, "bundles_changed": 0,
                                        "devices_moved": 2, "markers_changed": 3})
        self.assertEqual(d["text"], "+2 cables \u00b7 \u22121 cable \u00b7 1 cable changed \u00b7 2 devices moved \u00b7 3 markers changed",
                         fr("FR-SCN-02", "4.3.18", "text omits zero parts, singular/plural"))
        self.assertEqual(self.S.diff(a, a)["text"], "No differences")
        one = copy.deepcopy(a)
        one["cables"].append(_cable("c-one", "sound-board", "sub-x2"))
        self.assertEqual(self.S.diff(a, one)["text"], "+1 cable")
        self.assertEqual(self.S.diff(one, a)["text"], "\u22121 cable")
        self.assertEqual(self.S.summary_text({}), "No differences")


class Activate(unittest.TestCase):
    def setUp(self):
        self.S = requires("scenes")
        self.schema = requires("schema")

    def test_activate_creates_base_swaps_and_sets_setting(self):
        S = self.S
        doc = _doc()
        self.assertEqual(S.active_id(doc), "base")
        self.assertIsNone(S.base_entry(doc))
        doc1, xmas = S.create(doc, "Christmas", note="Extra choir mics", by="pat")
        self.assertRegex(xmas["id"], r"^sc-[0-9a-f]{8}$", fr("FR-SCN-01", "4.2", "scene ids"))
        self.assertEqual((xmas["name"], xmas["note"], xmas["by"]), ("Christmas", "Extra choir mics", "pat"))
        self.assertRegex(xmas["created"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(xmas["data"], S.capture(doc), "a new scene holds the current state")
        self.assertEqual(S.active_id(doc1), "base", "create does not activate")
        self.assertEqual(doc, _doc(), "create does not mutate its input")
        doc2, info = S.activate(doc1, xmas["id"], by="pat")
        self.assertEqual((info["from"], info["to"], info["diff"]["text"]), ("base", xmas["id"], "No differences"))
        self.assertEqual(doc2["settings"]["scene"], xmas["id"], fr("FR-SCN-03", "4.3.3", "settings.scene"))
        base = S.base_entry(doc2)
        self.assertIsNotNone(base, fr("FR-SCN-03", "4.3.18", "first activation creates the Base entry"))
        self.assertEqual((base["name"], base["base"], base["by"]), ("Base", True, "pat"))
        self.assertEqual(base["data"], S.capture(doc), "Base holds the state that was left")
        self.assertEqual(len([s for s in doc2["scenes"] if s.get("base")]), 1)
        self.assertEqual(S.scene_name(doc2, "base"), "Base")
        # edit while Christmas is active: add a cable, move a device
        doc3 = copy.deepcopy(doc2)
        doc3["cables"].append(_cable("c-choir", "stage-box-1", "sound-board"))
        _dev(doc3, "atem-mini")["location"] = "stage-left"
        summ = S.summarize(doc3)
        self.assertEqual([s["id"] for s in summ][0], "base", "Base first")
        self.assertEqual([(s["name"], s["base"], s["active"]) for s in summ], [("Base", True, False), ("Christmas", False, True)])
        self.assertEqual(summ[1]["text"], "+1 cable \u00b7 1 device moved", "the active scene is compared live, not from its stale copy")
        self.assertEqual(summ[1]["diff"]["cables_added"], 1)
        self.assertEqual(summ[0]["text"], "\u22121 cable \u00b7 1 device moved", "Base shows what switching back would do")
        self.assertEqual(summ[1]["note"], "Extra choir mics")
        # back to Base: the cable is gone and the device is back
        doc4, info = S.activate(doc3, "base")
        self.assertEqual((info["from"], info["to"]), (xmas["id"], "base"))
        self.assertEqual(info["diff"]["text"], "\u22121 cable \u00b7 1 device moved")
        self.assertEqual(doc4["settings"]["scene"], "", fr("FR-SCN-03", "4.3.3", "'' = Base"))
        self.assertNotIn("c-choir", [c["id"] for c in doc4["cables"]])
        self.assertEqual(_dev(doc4, "atem-mini")["location"], "foh")
        self.assertEqual(S.find(doc4, xmas["id"])["data"]["cables"][-1]["id"], "c-choir", "leaving a scene captures its state")
        self.assertEqual(S.summarize(doc4)[1]["text"], "+1 cable \u00b7 1 device moved")
        # and forward again
        doc5, info = S.activate(doc4, xmas["id"])
        self.assertEqual(info["diff"]["text"], "+1 cable \u00b7 1 device moved")
        self.assertIn("c-choir", [c["id"] for c in doc5["cables"]])
        self.assertEqual(_dev(doc5, "atem-mini")["location"], "stage-left")
        # no-op and unknown
        same, info = S.activate(doc5, xmas["id"])
        self.assertIs(same, doc5)
        self.assertEqual(info["diff"]["text"], "No differences")
        with self.assertRaises(KeyError):
            S.activate(doc5, "sc-deadbeef")
        self.assertEqual(self.schema.errors(self.schema.validate_doc(self.schema.normalize(doc5))), [])
        n = self.schema.normalize(doc5)
        self.assertEqual(n["scenes"][0]["data"], doc5["scenes"][0]["data"], fr("FR-SCN-01", "4.4.1", "normalize keeps scene data verbatim"))
        self.assertFalse(self.schema.is_v1_expressible(n), fr("FR-SCN-01", "4.6.7", "scenes make a doc v2-only"))

    def test_create_copy_from_save_delete_rename(self):
        S = self.S
        doc = _doc()
        doc, a = S.create(doc, "A")
        doc, _ = S.activate(doc, a["id"])
        doc["cables"].append(_cable("c-a", "stage-box-1", "sound-board"))
        doc, b = S.create(doc, "B", copy_from=a["id"])
        self.assertIn("c-a", [c["id"] for c in b["data"]["cables"]], "copy_from the active scene copies the live state")
        doc, c = S.create(doc, "C", copy_from="base")
        self.assertNotIn("c-a", [c_["id"] for c_ in c["data"]["cables"]], "copy_from base copies the Base entry")
        with self.assertRaises(KeyError):
            S.create(doc, "D", copy_from="sc-00000000")
        for bad in ("", "   ", "x" * 81):
            with self.assertRaises(ValueError):
                S.create(doc, bad)
        # save_current overwrites a non-active scene's data
        doc["cables"].append(_cable("c-a2", "stage-box-1", "sound-board"))
        doc = S.save_current(doc, c["id"])
        self.assertEqual([x["id"] for x in S.find(doc, c["id"])["data"]["cables"]][-2:], ["c-a", "c-a2"])
        # rename / note
        doc = S.rename(doc, c["id"], name="C2", note="n")
        self.assertEqual((S.find(doc, c["id"])["name"], S.find(doc, c["id"])["note"]), ("C2", "n"))
        doc = S.rename(doc, c["id"], note="")
        self.assertNotIn("note", S.find(doc, c["id"]))
        # delete the active scene → Base
        self.assertEqual(S.active_id(doc), a["id"])
        doc = S.delete(doc, a["id"])
        self.assertEqual(S.active_id(doc), "base", fr("FR-SCN-04", "4.3.18", "deleting the active scene activates Base"))
        self.assertNotIn("c-a", [x["id"] for x in doc["cables"]])
        self.assertIsNone(S.find(doc, a["id"]))
        self.assertEqual([s["name"] for s in S.summarize(doc)], ["Base", "B", "C2"])
        with self.assertRaises(ValueError):
            S.delete(doc, "base")
        with self.assertRaises(ValueError):
            S.delete(doc, S.base_entry(doc)["id"])
        with self.assertRaises(KeyError):
            S.delete(doc, a["id"])


class Validation(unittest.TestCase):
    def setUp(self):
        self.S = requires("scenes")
        self.schema = requires("schema")

    def test_collection_and_schema(self):
        s = self.schema
        self.assertIn("scenes", s.COLLECTIONS)
        self.assertEqual(s.new_doc("X")["scenes"], [])
        self.assertIn("scenes", s.JSON_SCHEMA["properties"])
        self.assertNotIn("scenes", s.JSON_SCHEMA["required"], "optional on disk")
        self.assertIn("scene", s.JSON_SCHEMA["properties"]["settings"]["properties"])

    def test_warnings_and_errors(self):
        S, s = self.S, self.schema
        doc = _doc()
        doc, a = S.create(doc, "Christmas")
        doc, _ = S.activate(doc, a["id"])
        doc, b = S.create(doc, "christmas ")
        codes = lambda d: [(p["level"], p["code"], p["path"]) for p in s.validate_doc(d) if p["ref"].startswith("scenes") or p["path"].startswith("settings/scene")]
        self.assertEqual(codes(doc), [("warning", "duplicate_name", f"scenes/{b['id']}/name")], fr("FR-SCN-05", "4.7", "duplicate names warn"))
        bad = copy.deepcopy(doc)
        bad["settings"]["scene"] = "sc-deadbeef"
        self.assertIn(("warning", "dangling_link", "settings/scene"), codes(bad))
        bad = copy.deepcopy(doc)
        bad["scenes"][-1]["base"] = True
        self.assertIn(("error", "bad_enum", f"scenes/{b['id']}/base"), codes(bad), "two base entries is an error")
        bad = copy.deepcopy(doc)
        bad["scenes"][-1]["data"]["cables"].append(_cable("c-g", "gone", "sound-board"))
        bad["scenes"][-1]["data"]["cables"].append({"id": "c-p", "from": {"device": "sound-board", "port": "nope"}, "to": {"device": "sub-x2"}, "medium": "analog"})
        bad["scenes"][-1]["data"]["markers"]["fp-main"].append({"device": "gone", "x": 0, "y": 0})
        bad["scenes"][-1]["data"]["devices"]["gone"] = {"room": "main"}
        got = codes(bad)
        self.assertEqual([c for c in got if c[1] == "dangling_link"],
                         [("warning", "dangling_link", f"scenes/{b['id']}/data/cables/15/from/device"),
                          ("warning", "dangling_link", f"scenes/{b['id']}/data/cables/16/from/port"),
                          ("warning", "dangling_link", f"scenes/{b['id']}/data/markers/fp-main/2/device"),
                          ("warning", "dangling_link", f"scenes/{b['id']}/data/devices/gone")],
                         fr("FR-SCN-05", "4.7", "stale refs inside scene data are warnings, not errors"))
        self.assertEqual(s.errors(s.validate_doc(bad)), [], "still saveable")
        bad = copy.deepcopy(doc)
        bad["scenes"][-1]["name"] = "x" * 81
        bad["scenes"][-1]["data"] = []
        self.assertEqual(sorted(c[1] for c in codes(bad) if c[0] == "error"), ["bad_enum", "bad_type"])
        bad = copy.deepcopy(doc)
        del bad["scenes"][-1]["name"]
        self.assertIn("missing_field", [p["code"] for p in s.validate_doc(bad) if p["ref"] == f"scenes/{b['id']}"])


class Routes(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        requires("scenes")

    def _get(self, path, status=200):
        st, _, b = call(self.app, "GET", path)
        self.assertEqual(st, status, b[:300])
        return jbody(b)

    def _post(self, path, body=None, status=200, method="POST"):
        st, _, b = call(self.app, method, path, body if body is not None else {}, JSON_H)
        self.assertEqual(st, status, b[:300])
        return jbody(b)

    def _cables(self):
        return [c["id"] for c in self._get(P)["doc"]["cables"]]

    def test_scene_flow_over_http(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            lst = self._get(P + "/scenes")
            self.assertEqual((lst["active"], [s["id"] for s in lst["scenes"]]), ("base", ["base"]), fr("FR-SCN-06", "5.6", "Base synthesised"))
            self.assertEqual(lst["scenes"][0]["text"], "No differences")
            self.assertIn("revision", lst)
            r = self._post(P + "/scenes", {"name": "Christmas", "note": "Choir", "activate": True}, 201)
            sid = r["scene"]["id"]
            self.assertRegex(sid, r"^sc-[0-9a-f]{8}$")
            self.assertEqual((r["scene"]["name"], r["scene"]["note"], r["scene"]["active"], r["scene"]["base"]), ("Christmas", "Choir", True, False))
            self.assertNotIn("data", r["scene"], "summaries never carry the data")
            rev = r["revision"]
            doc = self._get(P)["doc"]
            self.assertEqual(doc["settings"]["scene"], sid)
            self.assertEqual([s.get("base") for s in doc["scenes"]], [True, None], "Base entry + Christmas")
            hist = self._get(P + "/history")["revisions"]
            self.assertEqual((hist[0]["revision"], hist[0]["source"], hist[0]["summary"]), (rev, "scene", "Created scene Christmas"), fr("FR-SCN-06", "5.6", "one revision"))
            # add a cable while Christmas is active (plain /changes)
            self._post(P + "/changes", {"base_revision": rev, "ops": [{"op": "put", "coll": "cables", "id": "c-choir", "value": _cable("c-choir", "stage-box-1", "sound-board")}]})
            self.assertIn("c-choir", self._cables())
            lst = self._get(P + "/scenes")
            self.assertEqual([(s["name"], s["text"]) for s in lst["scenes"]], [("Base", "\u22121 cable"), ("Christmas", "+1 cable")], fr("FR-SCN-06", "5.6", "text reads +1 cable"))
            # viewer-only previews do not change anything
            d = self._get(P + f"/scenes/{sid}/diff")
            self.assertEqual((d["scene"], d["against"], d["summary"]["cables_added"], d["text"]), (sid, "base", 1, "+1 cable"))
            d = self._get(P + f"/scenes/base/diff?against={sid}")
            self.assertEqual(d["text"], "\u22121 cable")
            self._get(P + f"/scenes/{sid}/diff?against=sc-00000000", 404)
            pre = self._get(P + "/scenes/base/doc")
            self.assertEqual(pre["scene"], "base")
            self.assertNotIn("c-choir", [c["id"] for c in pre["doc"]["cables"]], fr("FR-SCN-07", "5.6", "/doc previews Base without switching"))
            self.assertIn("c-choir", [c["id"] for c in self._get(P + f"/scenes/{sid}/doc")["doc"]["cables"]])
            self.assertIn("c-choir", self._cables(), "preview changed nothing")
            self._get(P + "/scenes/sc-00000000/doc", 404)
            # switch to Base: the cable is gone; back to Christmas: it is back
            r = self._post(P + "/scenes/base/activate")
            self.assertEqual((r["active"], r["from"], r["diff"]["text"]), ("base", sid, "\u22121 cable"))
            self.assertNotIn("c-choir", self._cables())
            hist = self._get(P + "/history")["revisions"]
            self.assertEqual(hist[0]["summary"], "Switched to scene Base (\u22121 cable)")
            r = self._post(P + f"/scenes/{sid}/activate")
            self.assertEqual((r["active"], r["from"], r["diff"]["text"]), (sid, "base", "+1 cable"))
            self.assertIn("c-choir", self._cables())
            self.assertEqual(self._get(P + "/history")["revisions"][0]["summary"], "Switched to scene Christmas (+1 cable)")
            again = self._post(P + f"/scenes/{sid}/activate")
            self.assertEqual((again["revision"], again["diff"]["text"]), (r["revision"], "No differences"), "re-activating the active scene writes nothing")
            self._post(P + "/scenes/sc-00000000/activate", status=404)
            # undo the switch through history restore
            restore = self._post(P + f"/history/{r['revision'] - 1}/restore", {"base_revision": r["revision"]})
            self.assertNotIn("c-choir", self._cables(), fr("FR-HIST", "5.6", "a scene switch is undoable"))
            self.assertEqual(self._get(P + "/scenes")["active"], "base")
            self._post(P + f"/history/{r['revision']}/restore", {"base_revision": restore["revision"]})
            self.assertIn("c-choir", self._cables())
            self.assertEqual(self._get(P + "/scenes")["active"], sid)
            # rename, save, copy_from, delete
            r = self._post(P + f"/scenes/{sid}", {"name": "Xmas", "note": ""}, method="PATCH")
            self.assertEqual((r["scene"]["name"], r["scene"]["note"]), ("Xmas", ""))
            self._post(P + f"/scenes/{sid}", {"name": ""}, status=400, method="PATCH")
            self._post(P + "/scenes/sc-00000000", {"name": "x"}, status=404, method="PATCH")
            r2 = self._post(P + "/scenes", {"name": "Easter", "copy_from": sid}, 201)
            self.assertEqual((r2["scene"]["active"], r2["scene"]["text"]), (False, "+1 cable"), "copy of the live Christmas state")
            self._post(P + "/scenes", {"name": "Bad", "copy_from": "sc-00000000"}, status=404)
            self._post(P + "/scenes", {"name": ""}, status=400)
            self._post(P + "/scenes", {"name": "x" * 81}, status=400)
            cur = self._get(P)
            self._post(P + "/changes", {"base_revision": cur["revision"], "ops": [{"op": "del", "coll": "cables", "id": "c-choir"}]})
            r = self._post(P + f"/scenes/{r2['scene']['id']}/save")
            self.assertEqual(r["scene"]["text"], "No differences", "save_current overwrote Easter with the live state")
            self._post(P + "/scenes/sc-00000000/save", status=404)
            self._post(P + "/scenes/base/activate")
            r = self._post(P + f"/scenes/{sid}", method="DELETE")
            self.assertEqual((r["ok"], r["active"]), (True, "base"))
            self._post(P + "/scenes/base", status=400, method="DELETE")
            self._post(P + f"/scenes/{sid}", status=404, method="DELETE")
            self.assertEqual([s["name"] for s in self._get(P + "/scenes")["scenes"]], ["Base", "Easter"])
            # deleting the active scene lands on Base
            self._post(P + f"/scenes/{r2['scene']['id']}/activate")
            r = self._post(P + f"/scenes/{r2['scene']['id']}", method="DELETE")
            self.assertEqual(r["active"], "base")
            self.assertEqual(self._get(P)["doc"]["settings"]["scene"], "")

    def test_locked_project_refuses_scene_writes(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            r = self._post(P + "/scenes", {"name": "A"}, 201)
            sid = r["scene"]["id"]
            cur = self._get(P)
            self._post(P + "/changes", {"base_revision": cur["revision"], "ops": [{"op": "root", "key": "settings", "value": {"locked": True}}]})
            for method, path, body in (("POST", P + "/scenes", {"name": "B"}), ("PATCH", P + f"/scenes/{sid}", {"name": "C"}),
                                       ("DELETE", P + f"/scenes/{sid}", None), ("POST", P + f"/scenes/{sid}/activate", None),
                                       ("POST", P + f"/scenes/{sid}/save", None)):
                st, _, b = call(self.app, method, path, body if body is not None else {}, JSON_H)
                self.assertEqual(st, 423, "%s %s: %s" % (method, path, b[:200]))
                self.assertEqual(jbody(b)["code"], "locked", fr("FR-USER-12", "5.3", "scene writes honour the editing lock"))
            self.assertEqual(self._get(P + "/scenes")["active"], "base", "nothing changed")
            self._get(P + f"/scenes/{sid}/diff")
            self._get(P + f"/scenes/{sid}/doc")

    def test_viewer_pages_render_a_scene(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            r = self._post(P + "/scenes", {"name": "Christmas", "activate": True}, 201)
            sid = r["scene"]["id"]
            # a scene-only cable: the speakers' Thru 1 feeds the TV's (otherwise empty) HDMI 1
            cable = {"id": "c-choir", "from": {"device": "main-speakers", "port": "thru-1"}, "to": {"device": "samsung-tv-1", "port": "hdmi-in-1"}, "medium": "hdmi"}
            self._post(P + "/changes", {"base_revision": r["revision"], "ops": [{"op": "put", "coll": "cables", "id": "c-choir", "value": cable}]})
            self._post(P + "/scenes/base/activate")
            link = b'href="../../d/main-speakers"'
            st, _, live = call(self.app, "GET", "/p/proj/r/main/patch")
            self.assertEqual(st, 200)
            st, h, scene = call(self.app, "GET", f"/p/proj/r/main/patch?scene={sid}")
            self.assertEqual(st, 200, scene[:300])
            self.assertEqual(scene.count(link), live.count(link) + 1, fr("FR-SCN-07", "5.13", "?scene= renders the scene-only cable (one more link to the speakers)"))
            self.assertIn("Scene: Christmas".encode(), scene, "caption names the scene")
            self.assertNotIn(b"Scene:", live)
            st, _, base_page = call(self.app, "GET", "/p/proj/r/main/patch?scene=base")
            self.assertEqual(st, 200)
            self.assertEqual(base_page.count(link), live.count(link))
            self.assertIn(b"Scene: Base", base_page)
            for path in ("/p/proj/r/main", "/p/proj/r/main/diagram.svg", "/p/proj/d/sound-board", "/p/proj"):
                st, _, b = call(self.app, "GET", f"{path}?scene={sid}")
                self.assertEqual(st, 200, "%s: %s" % (path, b[:200]))
            st, _, b = call(self.app, "GET", "/p/proj/r/main/patch?scene=sc-00000000")
            self.assertEqual(st, 404, "unknown scene → 404")
            self.assertNotIn("c-choir", self._cables(), "rendering a scene stores nothing")


if __name__ == "__main__":
    unittest.main()
