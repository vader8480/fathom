"""Search additions for the UI uplift (docs/ui-audit.md B.4): ``network`` hits and ``status`` on every hit."""

from __future__ import annotations

import copy
import unittest

try:
    from _helpers import CAMPUS_DIR, call, get_app, install_campus, install_sunday, jbody, read_json, requires, sunday_doc, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import (CAMPUS_DIR, call, get_app, install_campus, install_sunday, jbody, read_json, requires, sunday_doc,
                                temp_data_dir)

HIT_KEYS = ("kind", "id", "device", "port", "title", "subtitle", "room", "score", "match", "status")


def campus_doc():
    return read_json(CAMPUS_DIR / "project.json")


class ModuleSearch(unittest.TestCase):
    def setUp(self):
        self.S = requires("search")
        self.doc = campus_doc()
        self.ix = self.S.build_index(self.doc)

    def test_kind_order_has_network_after_interface(self):
        ko = list(self.S.KIND_ORDER)
        self.assertEqual(ko.index("network"), ko.index("interface") + 1)

    def test_network_found_by_name(self):
        hits = self.S.search(self.ix, "Dante primary", limit=40)
        net = [h for h in hits if h["kind"] == "network"]
        self.assertTrue(net, "av-dante found by name")
        h = net[0]
        self.assertEqual(h["id"], "av-dante")
        self.assertEqual(h["title"], "Dante primary")
        self.assertEqual(h["subtitle"], "VLAN 20 · 10.20.0.0/24")
        self.assertEqual((h["score"], h["match"]), (100, "name"))
        self.assertEqual((h["device"], h["port"], h["room"], h["status"]), (None, None, "", ""))
        for k in HIT_KEYS:
            self.assertIn(k, h)

    def test_network_found_by_vlan_subnet_protocol_id(self):
        top = self.S.search(self.ix, "20", limit=5)[0]
        self.assertEqual((top["kind"], top["id"], top["match"], top["score"]), ("network", "av-dante", "vlan", 100))
        ids = lambda q: [h["id"] for h in self.S.search(self.ix, q, limit=40, kinds=["network"])]  # noqa: E731
        self.assertEqual(ids("10.20.0.0/24"), ["av-dante"])
        self.assertEqual(ids("sacn"), ["lx-sacn"])
        self.assertEqual(ids("mgmt"), ["mgmt"])
        self.assertEqual(ids("dante"), ["av-dante", "av-dante-sec"])

    def test_kinds_network_returns_only_networks(self):
        hits = self.S.search(self.ix, "dante", limit=200, kinds=["network"])
        self.assertTrue(hits)
        self.assertEqual({h["kind"] for h in hits}, {"network"})
        self.assertTrue(any(h["kind"] != "network" for h in self.S.search(self.ix, "dante", limit=200)))

    def test_network_subtitle_omits_missing_parts(self):
        doc = {"networks": [{"id": "n-a", "name": "A", "vlan": 7}, {"id": "n-b", "subnet": "10.9.0.0/16"}, {"id": "n-c"},
                            {"name": "no id"}, "junk"]}
        hits = {h["id"]: h for h in self.S.search(self.S.build_index(doc), "n", limit=20, kinds=["network"])}
        self.assertEqual(sorted(hits), ["n-a", "n-b", "n-c"])
        self.assertEqual(hits["n-a"]["subtitle"], "VLAN 7")
        self.assertEqual((hits["n-b"]["title"], hits["n-b"]["subtitle"]), ("n-b", "10.9.0.0/16"))
        self.assertEqual((hits["n-c"]["title"], hits["n-c"]["subtitle"]), ("n-c", ""))

    def test_every_hit_has_status(self):
        for q in ("spare", "chapel", "dante", "10.20", "a"):
            for h in self.S.search(self.ix, q, limit=200):
                self.assertIsInstance(h.get("status"), str, "%s %s" % (h["kind"], h["id"]))
                if h["kind"] not in ("device", "page"):
                    self.assertEqual(h["status"], "", "%s %s" % (h["kind"], h["id"]))

    def test_device_hits_carry_status(self):
        byid = {h["id"]: h for h in self.S.search(self.ix, "spare", limit=50, kinds=["device"])}
        self.assertEqual(byid["spare-ulxd4d"]["status"], "spare")
        h = self.S.search(self.ix, "bc-ultrix", limit=1, kinds=["device"])[0]
        self.assertEqual((h["id"], h["status"]), ("bc-ultrix", "planned"))
        h = self.S.search(self.ix, "foh-cl5", limit=1, kinds=["device"])[0]
        self.assertEqual((h["id"], h["status"]), ("foh-cl5", ""), "unset device status is ''")
        h = self.S.search(sunday_doc(), "atem-mini", limit=1, kinds=["device"])[0]
        self.assertEqual(h["status"], "installed")

    def test_page_hits_carry_status(self):
        h = self.S.search(self.ix, "chapel-pre-service", limit=1, kinds=["page"])[0]
        self.assertEqual((h["id"], h["status"]), ("chapel-pre-service", "draft"))
        h = self.S.search(self.ix, "power-up", limit=1, kinds=["page"])[0]
        self.assertEqual((h["id"], h["status"]), ("power-up", "published"))

    def test_ranking_unchanged(self):
        sunday = sunday_doc()
        hits = self.S.search(sunday, "atem", limit=3)
        self.assertEqual((hits[0]["kind"], hits[0]["id"], hits[0]["title"]), ("device", "atem-mini", "ATEM Mini"))
        ip = self.S.search(sunday, "10.20.0.40", limit=20)
        self.assertTrue([h for h in ip if h["kind"] == "interface" and h["device"] == "atem-mini"])
        self.assertFalse([h for h in ip if h["kind"] == "network"], "a host address does not match the subnet")

    def test_networks_do_not_reorder_other_hits(self):
        bare = copy.deepcopy(self.doc)
        bare["networks"] = []
        ix0 = self.S.build_index(bare)
        for q in ("atem", "dante", "dante primary", "control", "10.20.0", "mgmt", "switch", "primary", "sacn"):
            with self.subTest(q=q):
                key = lambda hs: [(h["kind"], h["id"], h["score"], h["match"]) for h in hs if h["kind"] != "network"]  # noqa: E731
                self.assertEqual(key(self.S.search(self.ix, q, limit=1000)), key(self.S.search(ix0, q, limit=1000)))


class HttpSearch(unittest.TestCase):
    def setUp(self):
        requires("search")
        self.app = get_app()
        self._ctx = temp_data_dir()
        self.data = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        install_campus(self.data, "campus")
        install_sunday(self.data, "sunday-demo")

    def hits(self, name, query):
        st, _, b = call(self.app, "GET", "/api/v2/projects/%s/search?%s" % (name, query))
        self.assertEqual(st, 200, b[:300])
        hits = jbody(b)["hits"]
        for h in hits:
            for k in HIT_KEYS:
                self.assertIn(k, h, "5.11 hit %s" % k)
        return hits

    def test_network_by_name_and_vlan(self):
        hits = self.hits("campus", "q=Dante%20primary&limit=40")
        self.assertIn(("network", "av-dante"), [(h["kind"], h["id"]) for h in hits])
        top = self.hits("campus", "q=20&limit=5")[0]
        self.assertEqual((top["kind"], top["id"], top["subtitle"]), ("network", "av-dante", "VLAN 20 · 10.20.0.0/24"))

    def test_kinds_network(self):
        hits = self.hits("campus", "q=dante&kinds=network&limit=50")
        self.assertEqual([h["id"] for h in hits], ["av-dante", "av-dante-sec"])
        both = self.hits("campus", "q=dante&kinds=network,interface&limit=200")
        self.assertTrue({h["kind"] for h in both} <= {"network", "interface"})

    def test_status_on_hits(self):
        dev = {h["id"]: h for h in self.hits("campus", "q=spare&kinds=device")}
        self.assertEqual(dev["spare-ulxd4d"]["status"], "spare")
        page = self.hits("campus", "q=chapel-pre-service&kinds=page")[0]
        self.assertEqual((page["id"], page["status"]), ("chapel-pre-service", "draft"))
        for h in self.hits("campus", "q=chapel&limit=200"):
            if h["kind"] not in ("device", "page"):
                self.assertEqual(h["status"], "")

    def test_ranking_unchanged(self):
        hits = self.hits("sunday-demo", "q=atem&limit=3")
        self.assertEqual(hits[0]["id"], "atem-mini")
        hits = [h for h in self.hits("sunday-demo", "q=10.20.0.40") if h["kind"] == "interface" and h["device"] == "atem-mini"]
        self.assertTrue(hits)
        self.assertEqual(hits[0]["status"], "")


if __name__ == "__main__":
    unittest.main()
