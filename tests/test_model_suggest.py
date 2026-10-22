"""Hardware model suggestions (fathom.library.suggest): matcher fixtures with the strings the
Dante / Yamaha / SNMP / UniFi / mDNS sources really report, the library additions, the API, and
the three places that surface suggestions (imports overlay, one-shot preview, discovery findings
+ promote)."""

from __future__ import annotations

import json
import time
import unittest

try:
    from _helpers import FIXTURES, call, get_app, install_campus, jbody, requires, temp_data_dir, upload
except ImportError:  # pragma: no cover
    from tests._helpers import FIXTURES, call, get_app, install_campus, jbody, requires, temp_data_dir, upload

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
FAST = {"FATHOM_DISCOVERY_FIXTURES": str(FIXTURES / "discovery"), "FATHOM_DISCOVERY_FIXTURE_DELAY": "0.1"}

# A Dante Controller preset the way Dante Controller writes it: manufacturer_name is the long corporate
# form and model_name the exact product code. Y004 / Y005 / BCAST are not in the campus project.
STAGE_PRESET = """<?xml version="1.0" encoding="UTF-8"?>
<preset version="3.0.0">
  <name>Stage additions</name>
  <device>
    <name>Y004-Yamaha-Rio1608-STG</name>
    <manufacturer_name>Yamaha Corporation</manufacturer_name>
    <model_name>Rio1608-D</model_name>
    <ipv4_address>10.20.0.23</ipv4_address>
    <txchannel danteId="1"><label>Stage 1</label></txchannel>
    <rxchannel danteId="1"><label>Mon 1</label><subscribed_device>FOH-CL5</subscribed_device><subscribed_channel>Mix 1</subscribed_channel></rxchannel>
  </device>
  <device>
    <name>Y005-Ri8-CHOIR</name>
    <manufacturer_name>Yamaha Corporation</manufacturer_name>
    <model_name>Ri8-D</model_name>
    <txchannel danteId="1"><label>Choir 1</label></txchannel>
  </device>
  <device>
    <name>BCAST-ULXD4Q-2</name>
    <manufacturer_name>Shure Incorporated</manufacturer_name>
    <model_name>ULXD4Q</model_name>
    <txchannel danteId="1"><label>HH 5</label></txchannel>
  </device>
  <device>
    <name>FOH-CL5</name>
    <manufacturer_name>Yamaha</manufacturer_name>
    <model_name>CL5</model_name>
    <txchannel danteId="3"><label>Mix 1</label></txchannel>
  </device>
</preset>
"""

CSV_DEVICES = ("name,kind,manufacturer,model,room,ip\n"
               "Stage Rio,stage_io,Yamaha Corporation,Rio1608-D,main,10.20.0.23\n"
               "Lobby TV,display,Acme Screens,Panelmaster 9000,main,10.20.0.77\n")


def _ids(suggestions):
    return [s["template"] for s in suggestions]


class Matcher(unittest.TestCase):
    """suggest_models against the strings each source produces."""

    @classmethod
    def setUpClass(cls):
        cls.s = requires("library.suggest")

    def top(self, **kw):
        out = self.s.suggest_models(**kw)
        self.assertTrue(out, "no suggestion for %r" % (kw,))
        return out

    def test_vendor_key_normalises_corporate_forms_and_aliases(self):
        vk = self.s.vendor_key
        self.assertEqual(vk("Yamaha Corporation"), "yamaha")
        self.assertEqual(vk("Yamaha"), "yamaha")
        self.assertEqual(vk("Shure Incorporated"), "shure")
        self.assertEqual(vk("Blackmagic Design"), "blackmagic")
        self.assertEqual(vk("Ubiquiti Inc."), "ubiquiti")
        self.assertEqual(vk("UBNT"), "ubiquiti")
        self.assertEqual(vk("Allen & Heath"), "allen heath")
        self.assertEqual(vk("Allen-Heath"), "allen heath")
        self.assertEqual(vk("NETGEAR Inc"), "netgear")
        self.assertEqual(vk("QSC, LLC"), "qsc")
        self.assertEqual(vk(""), "")
        self.assertEqual(vk(None), "")

    def test_dante_preset_strings_rio1608_d_is_exact_and_d2_is_only_a_variant(self):
        # Dante preset XML / Dante Device Info: "Yamaha Corporation" + "Rio1608-D"
        out = self.top(manufacturer="Yamaha Corporation", model="Rio1608-D", text="Y004-Yamaha-Rio1608-STG")
        self.assertEqual(out[0]["template"], "yamaha-rio1608-d")
        self.assertEqual(out[0]["level"], "high")
        self.assertGreaterEqual(out[0]["score"], 0.95)
        self.assertIn("Rio1608-D", out[0]["evidence"])
        self.assertIn("Yamaha", out[0]["evidence"])
        d2 = [s for s in out if s["template"] == "yamaha-rio1608-d2"]
        self.assertTrue(d2, "the -D2 stays available as a lower-ranked alternative")
        self.assertEqual(d2[0]["level"], "low", "-D vs -D2 is a variant, never an exact match: %r" % d2[0])
        self.assertLess(d2[0]["score"], self.s.MEDIUM)
        self.assertIn("variant", d2[0]["evidence"])
        # and the other way round
        out = self.top(manufacturer="Yamaha Corporation", model="Rio1608-D2")
        self.assertEqual(out[0]["template"], "yamaha-rio1608-d2")
        self.assertEqual(out[0]["level"], "high")
        self.assertEqual([s["level"] for s in out if s["template"] == "yamaha-rio1608-d"], ["low"])

    def test_hyphen_space_and_case_folding(self):
        for model in ("Rio1608-D", "rio1608-d", "RIO1608 D", "Rio1608D"):
            out = self.top(manufacturer="Yamaha", model=model)
            self.assertEqual(out[0]["template"], "yamaha-rio1608-d", model)
            self.assertEqual(out[0]["level"], "high", model)

    def test_yamaha_scp_devinfo_product(self):
        # consoles.py: manufacturer="Yamaha", model=info["product"]
        out = self.top(manufacturer="Yamaha", model="CL5", text="FOH console")
        self.assertEqual((out[0]["template"], out[0]["level"]), ("yamaha-cl5", "high"))
        out = self.top(manufacturer="Yamaha", model="DM7 Compact")
        self.assertEqual(out[0]["template"], "yamaha-dm7-compact")
        out = self.top(manufacturer="Yamaha", model="TF-Rack NY64-D")
        self.assertEqual(out[0]["template"], "yamaha-tf-rack")
        self.assertGreaterEqual(out[0]["score"], self.s.HIGH)

    def test_snmp_entity_mib_model_name(self):
        out = self.top(manufacturer="NETGEAR Inc", model="M4250-26G4F-PoE+", text="sw-stage")
        self.assertEqual(out[0]["template"], "netgear-m4250-26g4f-poe")
        self.assertEqual(out[0]["level"], "high")

    def test_unifi_model_field(self):
        out = self.top(manufacturer="Ubiquiti", model="USW-Pro-24-PoE", text="AV Core")
        self.assertEqual((out[0]["template"], out[0]["level"]), ("ubiquiti-usw-pro-24-poe", "high"))

    def test_mdns_dante_txt_record_rio3224_d_not_d2(self):
        out = self.top(manufacturer="Yamaha", model="Rio3224-D", text="RIO-SR Rio3224-D-102022.local")
        self.assertEqual(out[0]["template"], "yamaha-rio3224-d")
        self.assertEqual(out[0]["level"], "high")
        self.assertEqual([s["level"] for s in out if s["template"] == "yamaha-rio3224-d2"], ["low"])

    def test_vendor_inferred_from_the_model_string(self):
        # generic CSV "model" cell holding "Blackmagic ATEM Mini Pro" with an empty manufacturer column
        out = self.top(model="Blackmagic ATEM Mini Pro")
        self.assertEqual((out[0]["template"], out[0]["level"]), ("blackmagic-atem-mini-pro", "high"))
        iso = [s for s in out if s["template"] == "blackmagic-atem-mini-pro-iso"]
        self.assertTrue(iso and iso[0]["score"] < out[0]["score"], "ISO is a variant of the plain Mini Pro")

    def test_text_only_name_gives_low_family_hints(self):
        # discovery sometimes only has a hostname / Dante name
        out = self.s.suggest_models(text="Y004-Yamaha-Rio1608-STG")
        self.assertTrue(out)
        self.assertEqual({s["template"] for s in out[:2]}, {"yamaha-rio1608-d", "yamaha-rio1608-d2"})
        self.assertTrue(all(s["level"] == "low" for s in out), "name-only hints are never auto-accepted: %r" % out)

    def test_manufacturer_disagreement_demotes(self):
        out = self.s.suggest_models(manufacturer="Allen & Heath", model="CL5")
        self.assertFalse([s for s in out if s["template"] == "yamaha-cl5" and s["level"] != "low"], out)

    def test_no_false_positives_and_presets_are_never_suggested(self):
        for mf, model in (("Cisco", "WS-C2960X-24PS-L"), ("Ubiquiti", "U6-Pro"), ("Audinate", "Dante Virtual Soundcard"), ("Apple", "")):
            out = self.s.suggest_models(manufacturer=mf, model=model, text="host")
            self.assertFalse([s for s in out if s["level"] != "low"], (mf, model, out))
        self.assertEqual(self.s.suggest_models(), [])
        lib = requires("library")
        presets = {t["id"] for t in lib.load_library().values() if t.get("source") == "preset"}
        self.assertTrue(presets)
        for name in ("stage box", "switch", "console", "fixture"):
            out = self.s.suggest_models(model=name, text=name, min_score=0.0, limit=50)
            self.assertFalse(presets & set(_ids(out)), name)

    def test_ranking_and_limit(self):
        out = self.s.suggest_models(manufacturer="Yamaha", model="Rio1608-D", limit=1)
        self.assertEqual(len(out), 1)
        out = self.s.suggest_models(manufacturer="Yamaha", model="Rio1608-D", limit=5)
        self.assertEqual(out, sorted(out, key=lambda s: -s["score"]))
        self.assertTrue(all(0.0 <= s["score"] <= 1.0 for s in out))
        self.assertTrue(all(s["level"] == self.s.level_for(s["score"]) for s in out))
        for key in ("template", "manufacturer", "model", "name", "kind", "source", "score", "level", "evidence", "kind_matches"):
            self.assertIn(key, out[0])

    def test_suggest_for_device_skips_templated_devices(self):
        dev = {"id": "x", "name": "Y004-Yamaha-Rio1608-STG", "manufacturer": "Yamaha Corporation", "model": "Rio1608-D", "kind": "stage_io"}
        self.assertEqual(self.s.suggest_for_device(dev)[0]["template"], "yamaha-rio1608-d")
        dev["template"] = "yamaha-rio1608-d2"
        self.assertEqual(self.s.suggest_for_device(dev), [])
        self.assertEqual(self.s.suggest_for_device("not a device"), [])

    def test_apply_template_to_device_sets_what_add_gear_sets(self):
        lib = requires("library")
        t = lib.get_template("yamaha-rio1608-d")
        dev = {"id": "y004", "name": "Y004-Yamaha-Rio1608-STG", "kind": "other", "room": "main", "manufacturer": "Yamaha Corporation",
               "model": "Rio1608-D", "interfaces": [{"ip": "10.20.0.23"}], "notes": "from dante",
               "ports": [{"id": "in-1", "medium": "analog", "index": 1, "label": "Stage 1", "dir": "in"}]}
        out = self.s.apply_template_to_device(dev, t)
        self.assertIs(out, dev)
        self.assertEqual(dev["template"], "yamaha-rio1608-d")
        self.assertEqual((dev["kind"], dev["manufacturer"], dev["model"], dev["brand"]), ("stage_io", "Yamaha", "Rio1608-D", "yamaha"))
        self.assertTrue(dev["dante"])
        self.assertEqual(len(dev["ports"]), len(lib.expand_port_groups(json.loads(json.dumps(t["ports"])))))
        self.assertTrue(len(dev["ports"]) >= 16 + 8 + 2, "16 in, 8 out, two Dante ports")
        kept = [p for p in dev["ports"] if p.get("label") == "Stage 1"]
        self.assertEqual(len(kept), 1, "the label on analog #1 carries over to the template port with the same medium / index")
        self.assertEqual((kept[0]["medium"], kept[0]["index"]), ("analog", 1))
        self.assertEqual((dev["room"], dev["interfaces"], dev["notes"], dev["name"]), ("main", [{"ip": "10.20.0.23"}], "from dante", "Y004-Yamaha-Rio1608-STG"))
        self.assertNotIn("discipline", dev, "no discipline override when the template agrees with the kind's default")


class LibraryAdditions(unittest.TestCase):
    def test_r_series_siblings_present_and_distinct(self):
        lib = requires("library")
        all_ = lib.load_library()
        for tid, model in (("yamaha-rio1608-d", "Rio1608-D"), ("yamaha-rio3224-d", "Rio3224-D"), ("yamaha-rio1608-d2", "Rio1608-D2"),
                           ("yamaha-rio3224-d2", "Rio3224-D2"), ("yamaha-ri8-d", "Ri8-D"), ("yamaha-ro8-d", "Ro8-D"), ("yamaha-tio1608-d", "Tio1608-D")):
            self.assertIn(tid, all_, tid)
            t = all_[tid]
            self.assertEqual((t["manufacturer"], t["model"], t["kind"], t["brand"]), ("Yamaha", model, "stage_io", "yamaha"), tid)
            self.assertTrue(t.get("dante"), tid)
            self.assertTrue(t.get("ports"), tid)
            lib.expand_port_groups(json.loads(json.dumps(t["ports"])))  # groups expand
            self.assertTrue({"stagebox", "dante"} <= set(t.get("tags", [])), tid)
        self.assertNotEqual(all_["yamaha-rio1608-d"]["id"], all_["yamaha-rio1608-d2"]["id"])
        rio = lib.expand_port_groups(json.loads(json.dumps(all_["yamaha-rio1608-d"]["ports"])))
        self.assertEqual(len([p for p in rio if p.get("medium") == "analog" and p.get("dir") == "in"]), 16)
        self.assertEqual(len([p for p in rio if p.get("medium") == "analog" and p.get("dir") == "out"]), 8)
        rio3224 = lib.expand_port_groups(json.loads(json.dumps(all_["yamaha-rio3224-d"]["ports"])))
        self.assertEqual(len([p for p in rio3224 if p.get("medium") == "analog" and p.get("dir") == "in"]), 32)
        self.assertEqual(len([p for p in rio3224 if p.get("medium") == "analog" and p.get("dir") == "out"]), 16)
        self.assertEqual(len([p for p in rio3224 if p.get("medium") == "aes3"]), 4)


class Api(unittest.TestCase):
    def setUp(self):
        requires("library.suggest")
        self.app = get_app()

    def test_library_suggest_endpoint(self):
        with temp_data_dir():
            st, _, b = call(self.app, "GET", "/api/v2/library/suggest?manufacturer=Yamaha%20Corporation&model=Rio1608-D&text=Y004-Yamaha-Rio1608-STG&kind=stage_io")
            self.assertEqual(st, 200, b)
            out = jbody(b)
            self.assertEqual(out["query"], {"manufacturer": "Yamaha Corporation", "model": "Rio1608-D", "text": "Y004-Yamaha-Rio1608-STG", "kind": "stage_io"})
            self.assertEqual(out["suggestions"][0]["template"], "yamaha-rio1608-d")
            self.assertEqual(out["suggestions"][0]["level"], "high")
            self.assertTrue(out["suggestions"][0]["kind_matches"])
            st, _, b = call(self.app, "GET", "/api/v2/library/suggest?model=Rio1608-D&limit=1")
            self.assertEqual(len(jbody(b)["suggestions"]), 1)
            st, _, b = call(self.app, "GET", "/api/v2/library/suggest")
            self.assertEqual((st, jbody(b)["suggestions"]), (200, []))
            st, _, b = call(self.app, "GET", "/api/v2/library/suggest?model=" + "x" * 400)
            self.assertEqual(st, 200)
            self.assertEqual(len(jbody(b)["query"]["model"]), 200, "query strings are clipped")

    def test_project_templates_are_candidates(self):
        with temp_data_dir() as data:
            install_campus(data, "campus")
            tpl = {"id": "acme-box-9000", "manufacturer": "Acme", "model": "Box 9000", "name": "Acme Box 9000", "kind": "processor", "ports": []}
            st, _, b = call(self.app, "GET", "/api/v2/projects/campus")
            rev = jbody(b)["revision"]
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/changes",
                            {"base_revision": rev, "ops": [{"op": "put", "coll": "templates", "id": tpl["id"], "value": tpl}], "summary": "template"}, JSON_H)
            self.assertEqual(st, 200, b)
            st, _, b = call(self.app, "GET", "/api/v2/library/suggest?project=campus&manufacturer=Acme&model=Box%209000")
            self.assertEqual(st, 200, b)
            self.assertEqual(jbody(b)["suggestions"][0]["template"], "acme-box-9000")
            st, _, b = call(self.app, "GET", "/api/v2/library/suggest?manufacturer=Acme&model=Box%209000")
            self.assertEqual(jbody(b)["suggestions"], [], "without ?project= only the shared library is searched")

    def test_dante_import_overlay_carries_suggestions(self):
        with temp_data_dir() as data:
            install_campus(data, "campus")
            st, _, b = upload(self.app, "/api/v2/projects/campus/imports?kind=dante", [("stage-preset.xml", STAGE_PRESET.encode("utf-8"), "text/xml")])
            self.assertEqual(st, 201, b)
            st, _, b = call(self.app, "GET", "/api/v2/projects/campus/overlay")
            self.assertEqual(st, 200, b)
            ov = jbody(b)
            auto = {d["name"]: d for d in ov["devices"] if d.get("source") == "dante"}
            self.assertIn("Y004-Yamaha-Rio1608-STG", auto)
            dev = auto["Y004-Yamaha-Rio1608-STG"]
            self.assertEqual((dev.get("manufacturer"), dev.get("model")), ("Yamaha Corporation", "Rio1608-D"), "identity strings are lifted onto the overlay device")
            sug = ov["suggestions"]
            self.assertIsInstance(sug, dict)
            self.assertEqual(sug[dev["id"]][0]["template"], "yamaha-rio1608-d")
            self.assertEqual(sug[dev["id"]][0]["level"], "high")
            self.assertEqual(sug[auto["Y005-Ri8-CHOIR"]["id"]][0]["template"], "yamaha-ri8-d")
            self.assertEqual(sug[auto["BCAST-ULXD4Q-2"]["id"]][0]["template"], "shure-ulxd4q")
            self.assertTrue(all(k in {d["id"] for d in ov["devices"]} for k in sug), "suggestions only for overlay devices")

    def test_csv_preview_carries_suggestions(self):
        with temp_data_dir() as data:
            install_campus(data, "campus")
            st, _, b = upload(self.app, "/api/v2/projects/campus/imports/preview?kind=csv", [("devices.csv", CSV_DEVICES.encode("utf-8"), "text/csv")])
            self.assertEqual(st, 200, b)
            out = jbody(b)
            puts = {op["id"]: op for op in out["ops"] if op.get("coll") == "devices" and op.get("op") == "put"}
            self.assertTrue(puts, out)
            rio = [i for i, op in puts.items() if op["value"].get("model") == "Rio1608-D"]
            self.assertEqual(len(rio), 1, puts)
            self.assertEqual(out["suggestions"][rio[0]][0]["template"], "yamaha-rio1608-d")
            tv = [i for i, op in puts.items() if op["value"].get("model") == "Panelmaster 9000"]
            self.assertNotIn(tv[0], out["suggestions"], "nothing suggested for a model the library does not know")


class Discovery(unittest.TestCase):
    """Findings carry model_suggestions; promote accepts ``templates`` for new devices and merges."""

    def setUp(self):
        requires("discovery")
        requires("library.suggest")
        self.app = get_app()

    def req(self, method, path, body=None):
        return call(self.app, method, path, body, dict(JSON_H) if body is not None else None)

    def run_and_wait(self, base):
        st, _, b = self.req("POST", base + "/discovery/runs", {"window": 10})
        self.assertEqual(st, 202, b)
        rid = jbody(b)["run"]["id"]
        t0 = time.time()
        while time.time() - t0 < 30:
            st, _, b = self.req("GET", base + "/discovery/runs/" + rid)
            run = jbody(b)["run"]
            if not run["active"]:
                self.assertEqual(run["status"], "done", run)
                return rid
            time.sleep(0.1)
        self.fail("run did not finish")

    def test_findings_suggest_and_promote_applies_templates(self):
        with temp_data_dir(**FAST) as data:
            install_campus(data, "campus")
            base = "/api/v2/projects/campus"
            # rio-sr is modelled without a template (a hand-entered device): the merge may then adopt one
            st, _, b = self.req("GET", base)
            j = jbody(b)
            sr = [d for d in j["doc"]["devices"] if d["id"] == "rio-sr"][0]
            sr = dict(sr)
            sr.pop("template", None)
            st, _, b = self.req("POST", base + "/changes", {"base_revision": j["revision"], "ops": [{"op": "put", "coll": "devices", "id": "rio-sr", "value": sr}], "summary": "untemplated"})
            self.assertEqual(st, 200, b)
            rid = self.run_and_wait(base)
            st, _, b = self.req("GET", base + "/discovery/runs/" + rid + "/findings")
            self.assertEqual(st, 200, b)
            f = jbody(b)
            by_name = {e["name"]: e for e in f["entities"]}
            ulxd, core, rio_sr = by_name["ULXD4Q-STAGE"], by_name["QSYS-Core110f"], by_name["RIO-SR"]
            self.assertEqual(ulxd["status"], "new")
            self.assertEqual(ulxd["model_suggestions"][0]["template"], "shure-ulxd4q")
            self.assertEqual(ulxd["model_suggestions"][0]["level"], "high")
            self.assertEqual(core["model_suggestions"][0]["template"], "qsc-core-110f")
            self.assertEqual(by_name["AV Core"]["model_suggestions"][0]["template"], "ubiquiti-usw-pro-24-poe", "UniFi model field")
            self.assertEqual(rio_sr["status"], "possible")
            self.assertEqual(rio_sr["model_suggestions"][0]["template"], "yamaha-rio3224-d", "mDNS Dante TXT model")
            self.assertEqual([s["level"] for s in rio_sr["model_suggestions"] if s["template"] == "yamaha-rio3224-d2"], ["low"])
            for e in f["entities"]:
                self.assertIn("model_suggestions", e)
                if e["status"] in ("unresolved", "ignored"):
                    self.assertEqual(e["model_suggestions"], [])
            self.assertEqual(by_name["iPhone"]["model_suggestions"], [])

            # promote with templates: a new device gets the template's ports / identity, the merge target too
            body = {"entities": [ulxd["id"], core["id"]], "merge": {rio_sr["id"]: "rio-sr"},
                    "templates": {ulxd["id"]: "shure-ulxd4q", rio_sr["id"]: "yamaha-rio3224-d"}, "room": "chapel"}
            st, _, b = self.req("POST", base + "/discovery/runs/" + rid + "/findings/promote", body)
            self.assertEqual(st, 200, b)
            self.assertEqual(jbody(b)["summary"]["devices"], 2)
            self.assertEqual(jbody(b)["summary"]["merged"], 1)
            st, _, b = self.req("GET", base)
            doc = jbody(b)["doc"] if "doc" in jbody(b) else jbody(b)
            devs = {d["id"]: d for d in doc["devices"]}
            lib = requires("library")
            new = [d for d in devs.values() if d.get("name") == "ULXD4Q-STAGE"]
            self.assertEqual(len(new), 1, [d.get("id") for d in devs.values()])
            dev = new[0]
            self.assertEqual(dev.get("template"), "shure-ulxd4q")
            self.assertEqual((dev["kind"], dev["manufacturer"], dev["model"], dev["room"]), ("wireless_rx", "Shure", "ULXD4Q", "chapel"))
            self.assertEqual(len(dev["ports"]), len(lib.expand_port_groups(json.loads(json.dumps(lib.get_template("shure-ulxd4q")["ports"])))))
            self.assertTrue(any(i.get("source") == "discovery" for i in dev.get("interfaces", [])), "discovery interface kept")
            self.assertIn("discovered", dev.get("tags", []))
            untouched = [d for d in devs.values() if d.get("name") == "QSYS-Core110f"][0]
            self.assertFalse(untouched.get("template"), "no template requested → promoted as before")
            sr = devs["rio-sr"]
            self.assertEqual(sr["template"], "yamaha-rio3224-d")
            self.assertEqual(sr["dante_name"], "RIO-SR", "merge never overwrites identity")
            self.assertTrue(len(sr["ports"]) >= 32 + 16 + 2)
            # validation
            st, _, b = self.req("POST", base + "/discovery/runs/" + rid + "/findings/promote", {"entities": [], "templates": "nope"})
            self.assertEqual(st, 400, b)
            fresh = [e for e in jbody(self.req("GET", base + "/discovery/runs/" + rid + "/findings")[2])["entities"] if e["status"] == "new"][0]
            st, _, b = self.req("POST", base + "/discovery/runs/" + rid + "/findings/promote", {"entities": [fresh["id"]], "templates": {fresh["id"]: "no-such-template"}})
            self.assertEqual(st, 400, b)
            self.assertIn("template", jbody(b).get("error", "") + json.dumps(jbody(b)))

    def test_openapi_lists_the_route_and_body_field(self):
        with temp_data_dir():
            st, _, b = call(self.app, "GET", "/api/openapi.json")
            self.assertEqual(st, 200, b)
            spec = jbody(b)
            self.assertIn("/api/v2/library/suggest", spec["paths"])
            promote = spec["components"]["schemas"]["DiscoveryPromote"]["properties"]
            self.assertIn("templates", promote)


if __name__ == "__main__":
    unittest.main()
