"""Device de-duplication (fathom.dedupe): field combining, reference re-pointing,
conflicts and overrides, duplicate scoring, the HTTP endpoints and undo."""

from __future__ import annotations

import copy
import unittest

try:
    from _helpers import call, get_app, install_campus, install_project, jbody, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import call, get_app, install_campus, install_project, jbody, temp_data_dir

from fathom import dedupe, history, project, schema

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}


def _doc() -> dict:
    """A tiny project with a manual CL5, a second CL5 that mirrors a Dante import,
    and everything that can point at a device."""
    d = schema.new_doc("Test")
    d["venues"] = [{"id": "v", "name": "Venue"}]
    d["rooms"] = [{"id": "main", "name": "Main", "venue": "v", "flow": {"extra_cards": [{"id": "card-1", "device": "cl5-dante", "title": "Dante card"}]}}]
    d["racks"] = [{"id": "rk", "name": "FOH rack", "units": 20}]
    d["networks"] = [{"id": "dante-pri", "name": "Dante primary"}]
    d["devices"] = [
        {"id": "cl5", "name": "FOH CL5", "kind": "console", "room": "main", "manufacturer": "Yamaha", "model": "CL5",
         "tags": ["foh"], "note": "Manual entry.", "aliases": ["Console A"],
         "inventory": {"serial": "CL5-1A2B3C", "vendor": "Full Compass"},
         "interfaces": [{"id": "pri", "role": "dante_primary", "ip": "10.20.0.10"}],
         "rack": {"id": "rk", "u": 10, "height": 4},
         "ports": [
             {"id": "omni-in-1", "name": "Omni in 1", "dir": "in", "medium": "analog"},
             {"id": "omni-out-1", "name": "Omni out 1", "dir": "out", "medium": "analog"},
             {"id": "aux", "name": "Aux", "dir": "out", "medium": "analog"},
         ]},
        {"id": "cl5-dante", "name": "FOH-CL5", "kind": "console", "room": "main", "dante": True, "dante_name": "FOH-CL5",
         "tags": ["dante", "foh"], "note": "From the Dante preset.", "status": "installed",
         "inventory": {"serial": "CL5-1A2B3C", "firmware": "5.10", "vendor": "Other vendor"},
         "interfaces": [{"id": "pri", "role": "dante_primary", "ip": "10.20.0.10", "mac": "00:1b:2c:3d:4e:5f", "switch": "sw"},
                        {"id": "sec", "role": "dante_secondary", "ip": "10.21.0.10"}],
         "rack": {"id": "rk", "u": 2, "height": 4},
         "ports": [
             {"id": "omni-in-1", "name": "Omni in 1", "dir": "in", "medium": "analog", "label": "Lectern"},
             {"id": "dante-in-1", "name": "Dante in 1", "dir": "in", "medium": "dante"},
             {"id": "aux", "name": "Aux", "dir": "in", "medium": "dante"},
         ]},
        {"id": "sw", "name": "Switch", "kind": "switch", "room": "main", "ports": [{"id": "p1", "name": "Port 1", "dir": "io", "medium": "ethernet"}],
         "interfaces": [{"id": "mgmt", "ip": "10.20.0.1", "switch": "cl5-dante"}]},
        {"id": "mic", "name": "Lectern mic", "kind": "mic", "room": "main", "ports": [{"id": "out", "name": "Out", "dir": "out", "medium": "analog"}]},
    ]
    d["cables"] = [
        {"id": "c1", "from": {"device": "mic", "port": "out"}, "to": {"device": "cl5-dante", "port": "omni-in-1"}, "medium": "analog"},
        {"id": "c2", "from": {"device": "cl5-dante", "port": "aux"}, "to": {"device": "sw", "port": "p1"}, "medium": "dante",
         "flow": {"from_card": "cl5-dante"}},
        {"id": "c3", "from": {"device": "cl5", "port": "aux"}, "to": {"device": "cl5-dante", "port": "dante-in-1"}, "medium": "analog"},
    ]
    d["floorplans"] = [
        {"id": "fp-1", "name": "Stage", "room": "main", "source": "plans/stage.png", "image": "plans/stage.png", "markers": [{"device": "cl5", "x": 0.1, "y": 0.1}, {"device": "cl5-dante", "x": 0.9, "y": 0.9}]},
        {"id": "fp-2", "name": "Booth", "room": "main", "source": "plans/booth.png", "image": "plans/booth.png", "markers": [{"device": "cl5-dante", "x": 0.5, "y": 0.5}]},
    ]
    d["attachments"] = [{"id": "att-1", "device": "cl5-dante", "name": "manual.pdf", "file": "files/manual.pdf", "mime": "application/pdf"}]
    d["imports"] = [{"id": "imp-1", "kind": "yamaha", "path": "imports/cl5.csv", "room": "main", "device": "cl5-dante"}]
    return d


class FieldCombining(unittest.TestCase):
    def setUp(self):
        self.doc = _doc()
        self.plan = dedupe.merge_plan(self.doc, "cl5", ["cl5-dante"], author="tester", now=0)
        self.res = self.plan["result"]
        self.rows = {r["key"]: r for r in self.plan["fields"]}

    def test_survivor_explicit_values_win(self):
        self.assertEqual(self.res["name"], "FOH CL5")
        self.assertEqual(self.rows["name"]["winner"], "cl5")
        self.assertTrue(self.rows["name"]["conflict"])
        self.assertEqual(self.res["inventory"]["vendor"], "Full Compass")
        self.assertTrue(self.rows["inventory.vendor"]["conflict"])
        self.assertEqual(self.res["rack"], {"id": "rk", "u": 10, "height": 4})

    def test_blanks_filled_from_duplicate(self):
        self.assertEqual(self.res["dante_name"], "FOH-CL5")
        self.assertEqual(self.rows["dante_name"]["winner"], "cl5-dante")
        self.assertFalse(self.rows["dante_name"]["conflict"])
        self.assertEqual(self.res["inventory"]["firmware"], "5.10")
        self.assertEqual(self.res["status"], "installed")
        self.assertIs(self.res["dante"], True)
        self.assertEqual(self.res["manufacturer"], "Yamaha")
        self.assertEqual(self.res["model"], "CL5")

    def test_lists_union_and_notes_concatenate(self):
        self.assertEqual(self.res["tags"], ["foh", "dante"])
        self.assertEqual(self.res["note"], "Manual entry.\n\nFrom the Dante preset.")
        self.assertEqual(self.rows["tags"]["winner"], "union")
        self.assertEqual(self.rows["note"]["winner"], "union")

    def test_duplicate_names_become_aliases(self):
        al = [a.lower() for a in self.res["aliases"]]
        self.assertIn("console a", al)
        self.assertIn("cl5-dante", al, "duplicate id kept so importers that matched it still resolve")
        self.assertNotIn("foh-cl5", al, "the dante name is already carried by dante_name")

    def test_ports_union_unify_and_rename(self):
        ids = [p["id"] for p in self.res["ports"]]
        self.assertEqual(ids[:3], ["omni-in-1", "omni-out-1", "aux"], "survivor's ports keep their order")
        self.assertIn("dante-in-1", ids, "new port added")
        self.assertIn("aux-b", ids, "same id but in/dante vs out/analog -> renamed, not clobbered")
        omni = next(p for p in self.res["ports"] if p["id"] == "omni-in-1")
        self.assertEqual(omni["label"], "Lectern", "blank label filled from the duplicate's port")
        self.assertEqual(self.plan["ports"]["kept"], 3)
        self.assertEqual([x["port"] for x in self.plan["ports"]["added"]], ["dante-in-1"])
        self.assertEqual([x["port"] for x in self.plan["ports"]["unified"]], ["omni-in-1"])
        self.assertEqual(self.plan["ports"]["renamed"][0]["to"], "aux-b")

    def test_interfaces_union_by_ip_and_fill(self):
        ifs = {i["id"]: i for i in self.res["interfaces"]}
        self.assertEqual(set(ifs), {"pri", "sec"})
        self.assertEqual(ifs["pri"]["mac"], "00:1b:2c:3d:4e:5f", "blank MAC filled on the matching interface")
        self.assertEqual(ifs["pri"]["switch"], "sw", "switch link filled from the duplicate's interface")

    def test_switch_link_to_the_duplicate_itself_is_dropped(self):
        d = _doc()
        d["devices"][0]["interfaces"][0]["switch"] = "cl5-dante"
        plan = dedupe.merge_plan(d, "cl5", ["cl5-dante"])
        pri = next(i for i in plan["result"]["interfaces"] if i["id"] == "pri")
        self.assertNotIn("switch", pri, "a device cannot be its own switch after the merge")
        self.assertTrue(any("switch" in w for w in plan["warnings"]))

    def test_provenance_recorded(self):
        prov = self.res["merged_from"]
        self.assertEqual(len(prov), 1)
        self.assertEqual(prov[0]["id"], "cl5-dante")
        self.assertEqual(prov[0]["by"], "tester")
        self.assertEqual(prov[0]["at"], "1970-01-01T00:00:00Z")
        for k in ("dante_name", "status", "tags", "note", "ports", "interfaces", "inventory.firmware"):
            self.assertIn(k, prov[0]["fields"])
        self.assertNotIn("name", prov[0]["fields"])

    def test_result_is_valid_and_summary(self):
        new, _ = schema.apply_ops(self.doc, self.plan["ops"])
        self.assertEqual(schema.errors(schema.validate_doc(schema.normalize(new))), [])
        self.assertEqual(self.plan["summary"], "Merged 'FOH-CL5' into 'FOH CL5'")
        self.assertEqual([d["id"] for d in new["devices"]], ["cl5", "sw", "mic"])


class ReferenceRepointing(unittest.TestCase):
    def setUp(self):
        self.doc = _doc()
        self.plan = dedupe.merge_plan(self.doc, "cl5", ["cl5-dante"])
        self.new, _ = schema.apply_ops(self.doc, self.plan["ops"])
        self.idx = schema.index(self.new)

    def test_cables_follow_the_survivor_with_port_remap(self):
        c1 = self.idx.get("cables", "c1")
        self.assertEqual(c1["to"], {"device": "cl5", "port": "omni-in-1"})
        c2 = self.idx.get("cables", "c2")
        self.assertEqual(c2["from"], {"device": "cl5", "port": "aux-b"}, "renamed port is remapped on the cable")
        self.assertEqual(c2["flow"]["from_card"], "cl5")
        self.assertEqual(sorted(self.plan["references"]["cables"]), ["c1", "c2", "c3"])
        for c in self.new["cables"]:
            self.assertNotEqual(c["from"]["device"], "cl5-dante")
            self.assertNotEqual(c["to"]["device"], "cl5-dante")

    def test_cable_between_the_two_becomes_a_warned_self_loop(self):
        c3 = self.idx.get("cables", "c3")
        self.assertEqual(c3["from"]["device"], "cl5")
        self.assertEqual(c3["to"], {"device": "cl5", "port": "dante-in-1"})
        self.assertEqual(self.plan["references"]["self_loops"], ["c3"])
        self.assertTrue(any("start and end" in w for w in self.plan["warnings"]))

    def test_markers_attachments_imports_cards_switch(self):
        fp1 = self.idx.get("floorplans", "fp-1")
        self.assertEqual([m["device"] for m in fp1["markers"]], ["cl5"], "survivor already had a marker: duplicate's dropped")
        fp2 = self.idx.get("floorplans", "fp-2")
        self.assertEqual([m["device"] for m in fp2["markers"]], ["cl5"], "duplicate's marker re-pointed")
        self.assertEqual(self.plan["references"]["markers"], ["fp-2"])
        self.assertEqual(self.plan["references"]["markers_dropped"], ["fp-1:cl5-dante"])
        self.assertEqual(self.idx.get("attachments", "att-1")["device"], "cl5")
        self.assertEqual(self.idx.get("imports", "imp-1")["device"], "cl5")
        self.assertEqual(self.idx.room("main")["flow"]["extra_cards"][0]["device"], "cl5")
        self.assertEqual(self.idx.device("sw")["interfaces"][0]["switch"], "cl5")
        self.assertEqual(self.plan["references"]["switch_links"], ["sw"])

    def test_nothing_dangles_and_ops_are_undoable(self):
        self.assertEqual(schema.errors(schema.validate_doc(schema.normalize(self.new))), [])
        inverse = schema.invert_ops(self.doc, self.plan["ops"])
        back, _ = schema.apply_ops(self.new, inverse)
        a, b = schema.normalize(back), schema.normalize(self.doc)
        for d in (a, b):
            d["devices"].sort(key=lambda x: x["id"])  # a re-created entity is appended, order aside the doc is identical
        self.assertEqual(a, b, "inverting the merge ops restores the document")


class ConflictsAndOverrides(unittest.TestCase):
    def test_conflicts_flagged_and_overridable(self):
        plan = dedupe.merge_plan(_doc(), "cl5", ["cl5-dante"])
        rows = {r["key"]: r for r in plan["fields"]}
        self.assertTrue(rows["inventory.vendor"]["conflict"])
        self.assertTrue(rows["inventory.vendor"]["overridable"])
        self.assertFalse(rows["inventory.serial"]["conflict"], "equal values are not a conflict")
        self.assertFalse(rows["manufacturer"]["overridable"], "only one device has it")
        self.assertEqual(rows["inventory.vendor"]["values"], {"cl5": "Full Compass", "cl5-dante": "Other vendor"})

    def test_choices_override_winner(self):
        plan = dedupe.merge_plan(_doc(), "cl5", ["cl5-dante"], choices={"name": "cl5-dante", "inventory.vendor": "cl5-dante", "note": "cl5", "rack": "cl5-dante"})
        res = plan["result"]
        self.assertEqual(res["name"], "FOH-CL5")
        self.assertEqual(res["inventory"]["vendor"], "Other vendor")
        self.assertEqual(res["note"], "Manual entry.")
        self.assertEqual(res["rack"]["u"], 2)
        rows = {r["key"]: r for r in plan["fields"]}
        self.assertEqual(rows["name"]["reason"], "chosen by you")
        self.assertNotIn("foh cl5", [a.lower() for a in res["aliases"]], "FOH-CL5 is already carried by dante_name")
        prov = res["merged_from"][0]
        self.assertIn("name", prov["fields"])
        d = _doc()
        d["devices"][1]["name"] = "Console B"
        del d["devices"][1]["dante_name"]
        res = dedupe.merge_plan(d, "cl5", ["cl5-dante"], choices={"name": "cl5-dante"})["result"]
        self.assertEqual(res["name"], "Console B")
        self.assertIn("FOH CL5", res["aliases"], "the survivor's old name is kept as an alias when the duplicate's name wins")

    def test_choice_of_blank_value_is_ignored(self):
        plan = dedupe.merge_plan(_doc(), "cl5", ["cl5-dante"], choices={"manufacturer": "cl5-dante"})
        self.assertEqual(plan["result"]["manufacturer"], "Yamaha")

    def test_three_way_merge_and_order(self):
        d = _doc()
        d["devices"].append({"id": "cl5-3", "name": "CL5 (old)", "kind": "console", "room": "main", "model": "CL5", "code": "FOH",
                             "inventory": {"firmware": "4.0"}, "tags": ["legacy"], "ports": []})
        plan = dedupe.merge_plan(d, "cl5", ["cl5-dante", "cl5-3"])
        res = plan["result"]
        self.assertEqual(res["inventory"]["firmware"], "5.10", "first duplicate in order fills the blank")
        self.assertEqual(res["code"], "FOH")
        self.assertEqual(res["tags"], ["foh", "dante", "legacy"])
        self.assertEqual(plan["summary"], "Merged 2 devices into 'FOH CL5'")
        self.assertEqual([p["id"] for p in res["merged_from"]], ["cl5-dante", "cl5-3"])
        new, _ = schema.apply_ops(d, plan["ops"])
        self.assertEqual(schema.errors(schema.validate_doc(schema.normalize(new))), [])
        self.assertNotIn("cl5-3", [x["id"] for x in new["devices"]])

    def test_routing_map_union_and_extra_keys(self):
        d = _doc()
        d["devices"][0]["routing"] = {"mode": "matrix", "map": [["omni-in-1", "omni-out-1"]]}
        d["devices"][1]["routing"] = {"mode": "fixed", "map": [["dante-in-1", "aux"], ["omni-in-1", "omni-out-1"]]}
        d["devices"][1]["custom_field"] = "kept"
        plan = dedupe.merge_plan(d, "cl5", ["cl5-dante"])
        self.assertEqual(plan["result"]["routing"]["mode"], "matrix")
        self.assertEqual(plan["result"]["routing"]["map"], [["omni-in-1", "omni-out-1"], ["dante-in-1", "aux"]])
        self.assertEqual(plan["result"]["custom_field"], "kept")

    def test_errors(self):
        d = _doc()
        with self.assertRaises(dedupe.MergeError) as cm:
            dedupe.merge_plan(d, "cl5", ["cl5"])
        self.assertEqual(cm.exception.code, "self_merge")
        with self.assertRaises(dedupe.MergeError) as cm:
            dedupe.merge_plan(d, "nope", ["cl5"])
        self.assertEqual(cm.exception.code, "not_found")
        with self.assertRaises(dedupe.MergeError) as cm:
            dedupe.merge_plan(d, "cl5", ["nope"])
        self.assertEqual(cm.exception.code, "not_found")
        with self.assertRaises(dedupe.MergeError) as cm:
            dedupe.merge_plan(d, "cl5", [])
        self.assertEqual(cm.exception.code, "no_duplicates")

    def test_overlay_duplicate_enriches_survivor_without_delete(self):
        d = _doc()
        d["devices"] = [d["devices"][0], d["devices"][2], d["devices"][3]]
        d["cables"] = []
        d["floorplans"] = d["attachments"] = d["imports"] = []
        d["rooms"][0]["flow"] = {}
        overlay = {"devices": [{"id": "foh-cl5", "name": "FOH-CL5", "kind": "console", "room": "main", "auto": True, "source": "dante",
                                "dante": True, "dante_name": "FOH-CL5", "ports": [{"id": "dante-in-1", "name": "Dante in 1", "dir": "in", "medium": "dante", "auto": True}]}],
                   "interfaces": {"foh-cl5": [{"id": "pri", "ip": "10.20.0.10", "mac": "aa:bb", "source": "dante"}]},
                   "dmx": {}, "port_labels": {}}
        with self.assertRaises(dedupe.MergeError) as cm:
            dedupe.merge_plan(d, "foh-cl5", ["cl5"], overlay=overlay)
        self.assertEqual(cm.exception.code, "auto_survivor")
        plan = dedupe.merge_plan(d, "cl5", ["foh-cl5"], overlay=overlay)
        self.assertEqual([op["op"] for op in plan["ops"]], ["put"], "overlay devices are not persisted, so nothing is deleted")
        res = plan["result"]
        self.assertEqual(res["dante_name"], "FOH-CL5")
        self.assertIn("dante-in-1", [p["id"] for p in res["ports"]])
        self.assertFalse(any(p.get("auto") for p in res["ports"]))
        self.assertEqual(res["interfaces"][0]["mac"], "aa:bb")
        self.assertNotIn("source", res["interfaces"][0])
        self.assertEqual(res["merged_from"][0]["source"], "dante")
        self.assertTrue(any("import" in w for w in plan["warnings"]))


class DuplicateScoring(unittest.TestCase):
    def dev(self, **kw):
        d = {"id": kw.pop("id", "x"), "name": kw.pop("name", "X"), "ports": []}
        d.update(kw)
        return d

    def test_strong_identifiers(self):
        a = self.dev(id="a", name="Console", inventory={"serial": "S1"})
        b = self.dev(id="b", name="Unrelated name", inventory={"serial": "s1"})
        score, reasons = dedupe.score_pair(a, b)
        self.assertGreaterEqual(score, dedupe.HIGH)
        self.assertEqual(reasons[0]["signal"], "serial")
        a = self.dev(id="a", name="Alpha", interfaces=[{"ip": "10.0.0.5"}])
        b = self.dev(id="b", name="Beta", interfaces=[{"ip": "10.0.0.5"}])
        self.assertGreaterEqual(dedupe.score_pair(a, b)[0], dedupe.HIGH)
        a = self.dev(id="a", name="Alpha", interfaces=[{"mac": "00-11-22-33-44-55"}])
        b = self.dev(id="b", name="Beta", interfaces=[{"mac": "00:11:22:33:44:55"}])
        self.assertGreaterEqual(dedupe.score_pair(a, b)[0], dedupe.HIGH)
        a = self.dev(id="a", name="Alpha", interfaces=[{"hostname": "foh-cl5.local"}])
        b = self.dev(id="b", name="Beta", interfaces=[{"hostname": "FOH-CL5.local"}])
        self.assertGreaterEqual(dedupe.score_pair(a, b)[0], dedupe.HIGH)

    def test_dante_name_and_alias_match_names(self):
        a = self.dev(id="a", name="FOH CL5", dante_name="FOH-CL5")
        b = self.dev(id="b", name="FOH-CL5")
        score, reasons = dedupe.score_pair(a, b)
        self.assertGreaterEqual(score, dedupe.HIGH)
        self.assertIn("dante_name", [r["signal"] for r in reasons])
        a = self.dev(id="a", name="Main console", aliases=["Yamaha CL5"])
        b = self.dev(id="b", name="Yamaha CL5")
        score, reasons = dedupe.score_pair(a, b)
        self.assertGreaterEqual(score, dedupe.HIGH)
        self.assertIn("alias", [r["signal"] for r in reasons])

    def test_name_model_and_room_signals(self):
        a = self.dev(id="a", name="FOH CL5", kind="console", room="main")
        b = self.dev(id="b", name="Yamaha CL5", kind="console", room="main", manufacturer="Yamaha", model="CL5")
        score, reasons = dedupe.score_pair(a, b)
        self.assertGreaterEqual(score, dedupe.MEDIUM)
        signals = [r["signal"] for r in reasons]
        self.assertIn("name_token", signals)
        self.assertIn("model_in_name", signals)
        self.assertIn("room", signals)
        self.assertIn("kind", signals)
        self.assertLess(score, dedupe.HIGH, "no hard identifier -> not high")
        b2 = dict(b, room="other")
        self.assertLess(dedupe.score_pair(a, b2)[0], score, "different rooms lower the score")

    def test_rack_position(self):
        a = self.dev(id="a", name="Amp", rack={"id": "rk", "u": 5})
        b = self.dev(id="b", name="Power amp", rack={"id": "rk", "u": 5})
        self.assertIn("rack", [r["signal"] for r in dedupe.score_pair(a, b)[1]])
        self.assertGreaterEqual(dedupe.score_pair(a, b)[0], 0.5)

    def test_series_and_contradictions_are_penalised(self):
        a = self.dev(id="lustr-1", name="Lustr 1", kind="fixture", room="main", manufacturer="ETC", model="Lustr X8")
        b = self.dev(id="lustr-2", name="Lustr 2", kind="fixture", room="main", manufacturer="ETC", model="Lustr X8")
        score, reasons = dedupe.score_pair(a, b)
        self.assertLess(score, 0.5)
        self.assertIn("series", [r["signal"] for r in reasons])
        l_ = self.dev(id="mon-l", name="Monitor L", kind="speaker", manufacturer="QSC", model="K12.2")
        r_ = self.dev(id="mon-r", name="Monitor R", kind="speaker", manufacturer="QSC", model="K12.2")
        self.assertLess(dedupe.score_pair(l_, r_)[0], 0.5)
        a = self.dev(id="a", name="FOH CL5", kind="console", model="CL5", inventory={"serial": "A"})
        b = self.dev(id="b", name="FOH CL5", kind="console", model="CL5", inventory={"serial": "B"})
        score, reasons = dedupe.score_pair(a, b)
        self.assertLess(score, 0.5, "same name but different serials -> probably two units")
        self.assertIn("serial_differs", [r["signal"] for r in reasons])
        a = self.dev(id="a", name="Stage box", kind="stagebox", model="Rio3224-D2")
        b = self.dev(id="b", name="Stage box", kind="switch", model="SG300")
        score, reasons = dedupe.score_pair(a, b)
        self.assertLess(score, 0.5)
        self.assertIn("kind_differs", [r["signal"] for r in reasons])
        self.assertIn("model_differs", [r["signal"] for r in reasons])
        self.assertEqual(dedupe.score_pair(self.dev(id="a", name="Alpha"), self.dev(id="b", name="Beta")), (0.0, []))

    def test_find_duplicates_orders_and_picks_survivor(self):
        d = _doc()
        found = dedupe.find_duplicates(d)
        self.assertTrue(found)
        top = found[0]
        self.assertEqual({x["id"] for x in top["devices"]}, {"cl5", "cl5-dante"})
        self.assertEqual(top["confidence"], "high")
        self.assertEqual(top["suggested_survivor"], top["devices"][0]["id"])
        self.assertIn("serial", [r["signal"] for r in top["reasons"]])
        self.assertTrue(all(s["score"] >= 0.5 for s in found))
        self.assertEqual(found, sorted(found, key=lambda s: -s["score"]))
        only = dedupe.find_duplicates(d, device_id="sw")
        self.assertTrue(all("sw" in {x["id"] for x in s["devices"]} for s in only))
        with self.assertRaises(dedupe.MergeError):
            dedupe.find_duplicates(d, device_id="nope")

    def test_overlay_devices_are_candidates_but_never_survivor(self):
        d = _doc()
        d["devices"] = [d["devices"][0]]
        d["cables"] = []
        d["floorplans"] = d["attachments"] = d["imports"] = []
        d["rooms"][0]["flow"] = {}
        ov = {"devices": [{"id": "foh-cl5", "name": "FOH-CL5", "kind": "console", "room": "main", "auto": True, "source": "dante",
                           "dante_name": "FOH-CL5", "ports": []},
                          {"id": "foh-cl5-b", "name": "FOH-CL5", "kind": "console", "room": "main", "auto": True, "source": "yamaha", "ports": []}],
              "interfaces": {"foh-cl5": [{"id": "pri", "ip": "10.20.0.10", "source": "dante"}]}, "dmx": {}, "port_labels": {}}
        found = dedupe.find_duplicates(d, overlay=ov)
        pairs = [tuple(x["id"] for x in s["devices"]) for s in found]
        self.assertIn(("cl5", "foh-cl5"), pairs, "survivor first; the IP shared with the overlay device counts")
        self.assertNotIn(("foh-cl5", "foh-cl5-b"), pairs)
        self.assertNotIn(("foh-cl5-b", "foh-cl5"), pairs)
        for s in found:
            self.assertEqual(s["suggested_survivor"], "cl5")
            self.assertTrue(s["devices"][1]["auto"])


class MergeApi(unittest.TestCase):
    def setUp(self):
        self._ctx = temp_data_dir()
        self.data = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.pdir = install_project(self.data, "merge-t", _doc())
        self.app = get_app()

    def req(self, method, path, body=None, status=200):
        st, hdr, raw = call(self.app, method, "/api/v2/projects/merge-t" + path, body, headers=JSON_H if body is not None else None)
        self.assertEqual(st, status, raw[:300])
        return jbody(raw), hdr

    def test_duplicates_endpoint(self):
        j, _ = self.req("GET", "/devices/duplicates")
        self.assertIn("duplicates", j)
        self.assertIn("revision", j)
        self.assertEqual({x["id"] for x in j["duplicates"][0]["devices"]}, {"cl5", "cl5-dante"})
        j, _ = self.req("GET", "/devices/duplicates?device=cl5&min=0.9")
        self.assertTrue(all("cl5" in {x["id"] for x in s["devices"]} for s in j["duplicates"]))
        self.assertEqual(j["min_score"], 0.9)
        self.req("GET", "/devices/duplicates?device=nope", status=404)
        self.req("GET", "/devices/duplicates?min=abc", status=400)

    def test_preview_does_not_write(self):
        rev0 = project.current_revision(self.pdir)
        j, _ = self.req("POST", "/devices/merge/preview", {"survivor": "cl5", "duplicates": ["cl5-dante"]})
        self.assertEqual(j["survivor"], "cl5")
        self.assertEqual(j["revision"], rev0)
        self.assertTrue(j["fields"] and j["ops"])
        self.assertEqual(project.current_revision(self.pdir), rev0)
        doc, _ = project.read_doc(self.pdir)
        self.assertEqual(len(doc["devices"]), 4)
        self.req("POST", "/devices/merge/preview", {"survivor": "cl5"}, status=400)
        self.req("POST", "/devices/merge/preview", {"survivor": "cl5", "duplicates": ["nope"]}, status=404)
        self.req("POST", "/devices/merge/preview", {"survivor": "cl5", "duplicates": ["cl5"]}, status=400)
        self.req("POST", "/devices/merge/preview", {"survivor": "cl5", "duplicates": ["cl5-dante"], "choices": {"name": 3}}, status=400)

    def test_merge_is_one_undoable_revision(self):
        # a first write gives the project a history; the merge must then be exactly one more revision
        rev0 = self.req("POST", "/changes", {"base_revision": project.current_revision(self.pdir),
                                              "ops": [{"op": "merge", "coll": "devices", "id": "mic", "value": {"note": "pre"}}]})[0]["revision"]
        j, hdr = self.req("POST", "/devices/merge", {"survivor": "cl5", "duplicates": ["cl5-dante"], "choices": {"inventory.vendor": "cl5-dante"}})
        self.assertEqual(j["revision"], rev0 + 1)
        self.assertEqual(j["survivor"], "cl5")
        self.assertEqual(j["duplicates"], ["cl5-dante"])
        self.assertEqual(hdr.get("ETag"), '"r%d"' % (rev0 + 1))
        doc, _ = project.read_doc(self.pdir)
        ids = [d["id"] for d in doc["devices"]]
        self.assertNotIn("cl5-dante", ids)
        cl5 = next(d for d in doc["devices"] if d["id"] == "cl5")
        self.assertEqual(cl5["inventory"]["vendor"], "Other vendor", "override applied")
        self.assertEqual(cl5["dante_name"], "FOH-CL5")
        self.assertEqual(cl5["merged_from"][0]["id"], "cl5-dante")
        self.assertEqual(cl5["merged_from"][0]["by"], "local")
        self.assertTrue(all(c["from"]["device"] != "cl5-dante" and c["to"]["device"] != "cl5-dante" for c in doc["cables"]))
        revs = history.list_revisions(self.pdir, limit=1)
        top = revs[0] if isinstance(revs, list) else revs["revisions"][0]
        self.assertEqual(top["source"], "merge")
        self.assertEqual(top["summary"], "Merged 'FOH-CL5' into 'FOH CL5'")
        self.assertIn("devices/cl5-dante", top["touched"])
        # undo: restoring the previous revision brings the duplicate back untouched
        j, _ = self.req("POST", "/history/%d/restore" % rev0, {"base_revision": rev0 + 1})
        self.assertEqual(j["revision"], rev0 + 2)
        doc2, _ = project.read_doc(self.pdir)
        doc2.pop("revision", None)
        expect = schema.normalize(_doc())
        expect.pop("revision", None)
        next(d for d in expect["devices"] if d["id"] == "mic")["note"] = "pre"
        self.assertEqual(doc2, expect)

    def test_merge_conflict_on_stale_base(self):
        rev0 = project.current_revision(self.pdir)
        self.req("POST", "/changes", {"base_revision": rev0, "ops": [{"op": "merge", "coll": "devices", "id": "cl5", "value": {"note": "edited meanwhile"}}]})
        j, _ = self.req("POST", "/devices/merge", {"survivor": "cl5", "duplicates": ["cl5-dante"], "base_revision": rev0}, status=409)
        self.assertEqual(j["code"], "conflict")
        self.assertIn("devices/cl5", j["details"]["conflicts"])

    def test_viewer_cannot_merge(self):
        # role matrix lives in test_security; here: the merge route is editor-only via SPEC_ROLES
        try:
            from test_security import SPEC_ROLES
        except ImportError:
            from tests.test_security import SPEC_ROLES
        self.assertEqual(SPEC_ROLES[("POST", "/api/v2/projects/{}/devices/merge")], "editor")
        self.assertEqual(SPEC_ROLES[("GET", "/api/v2/projects/{}/devices/duplicates")], "viewer")


class CampusSample(unittest.TestCase):
    def test_sample_has_no_false_positive_duplicates(self):
        with temp_data_dir() as data:
            pdir = install_campus(data)
            doc, _ = project.read_doc(pdir)
            found = [s for s in dedupe.find_duplicates(doc) if s["confidence"] != "low"]
            self.assertEqual(found, [], "the demo project's numbered fixtures / L-R speakers are not duplicates")
            d2 = copy.deepcopy(doc)
            d2["devices"].append({"id": "cl5-manual", "name": "Yamaha CL5", "kind": "console", "room": "main", "manufacturer": "Yamaha",
                                  "model": "CL5", "dante_name": "FOH-CL5", "ports": []})
            top = dedupe.find_duplicates(d2, device_id="cl5-manual")[0]
            self.assertEqual({x["id"] for x in top["devices"]}, {"foh-cl5", "cl5-manual"})
            self.assertEqual(top["confidence"], "high")
            plan = dedupe.merge_plan(d2, "foh-cl5", ["cl5-manual"])
            new, _ = schema.apply_ops(d2, plan["ops"])
            self.assertEqual(schema.errors(schema.validate_doc(schema.normalize(new))), [])


if __name__ == "__main__":
    unittest.main()
