"""Network discovery (FR-DISC): probes from fixtures, correlation, topology, jobs, settings, API, passivity guard.

Every probe replays ``tests/fixtures/discovery/<probe>.json`` when
``FATHOM_DISCOVERY_FIXTURES`` points there, so nothing in this suite touches
the network. The guard suite runs the probes *without* fixtures with the
socket layer patched to prove that.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    from _helpers import FIXTURES, call, get_app, install_campus, jbody, requires, temp_data_dir, temp_env
except ImportError:  # pragma: no cover
    from tests._helpers import FIXTURES, call, get_app, install_campus, jbody, requires, temp_data_dir, temp_env

DISC_FIXTURES = FIXTURES / "discovery"
JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
FAST = {"FATHOM_DISCOVERY_FIXTURES": str(DISC_FIXTURES), "FATHOM_DISCOVERY_FIXTURE_DELAY": "0.1"}

AV_CORE = "78:45:58:aa:00:01"
GATEWAY = "78:45:58:aa:00:00"
RIO_SL = "00:1d:c1:10:20:21"
RIO_SL_SEC = "00:1d:c1:10:21:21"
RIO_SR = "00:1d:c1:10:20:22"
CL5 = "00:a0:de:50:00:05"
SW_STAGE = "28:c6:8e:11:22:33"
BC_SWITCH = "00:1b:54:ab:cd:ef"


def _results():
    """Parsed ProbeResults of the four fixtures."""
    probes = requires("discovery.probes")
    out = []
    for m in probes.all_probes():
        out.append(m.parse(json.loads((DISC_FIXTURES / (m.INFO.id + ".json")).read_text(encoding="utf-8"))))
    return out


def _campus_doc():
    from fathom.project import read_doc

    with temp_data_dir() as data:
        pdir = install_campus(data, "campus")
        doc, _ = read_doc(pdir)
    return doc


def _device_ids(topo, entities, doc):
    """entity id -> document / proposed device id, the way compute_findings does it."""
    taken = {str(d.get("id")) for d in doc.get("devices") or []}
    out = {}
    for e in entities:
        if e.status == "match" and e.match:
            out[e.id] = e.match["device"]
        else:
            dev = topo.propose_device(e, "main", taken, seen=e.seen)
            taken.add(dev["id"])
            out[e.id] = dev["id"]
    return out


def _by(entities, mac):
    for e in entities:
        if mac in e.macs:
            return e
    raise AssertionError("no entity with MAC %s" % mac)


# --------------------------------------------------------------------------- probes


class ProbeFixtures(unittest.TestCase):
    """What each probe yields from its recorded payload (FR-DISC-02)."""

    def setUp(self):
        self.probes = requires("discovery.probes")
        self.by_id = {m.INFO.id: m for m in self.probes.all_probes()}

    def test_all_probes_are_passive_and_declare_maturity(self):
        self.assertEqual(sorted(self.by_id), ["arp", "lldp", "mdns", "unifi"])
        for m in self.by_id.values():
            self.assertEqual(m.INFO.mode, "passive", m.INFO.id)
            self.assertIn(m.INFO.maturity, ("experimental", "tested", "mature"), m.INFO.id)
            self.assertTrue(m.INFO.sends, "%s must say what it puts on the wire" % m.INFO.id)
            self.assertTrue(callable(m.collect) and callable(m.parse) and callable(m.test), m.INFO.id)

    def test_unifi(self):
        r = self.by_id["unifi"].parse(json.loads((DISC_FIXTURES / "unifi.json").read_text()))
        self.assertEqual(r.status, "ok")
        s = r.summary()["stats"]
        self.assertEqual((s["devices"], s["clients"], s["wired_clients"], s["wireless_clients"]), (3, 10, 9, 1))
        by_mac = {o.mac: o for o in r.observations}
        core = by_mac[AV_CORE]
        self.assertEqual((core.name, core.model, core.kind_hint, core.ip), ("AV Core", "USW-Pro-24-PoE", "switch", "10.99.0.2"))
        self.assertEqual(len(core.ports), 26)
        self.assertEqual(by_mac[GATEWAY].kind_hint, "gateway")
        self.assertEqual(by_mac["78:45:58:aa:00:02"].kind_hint, "ap")
        self.assertEqual(by_mac["f0:18:98:aa:bb:cc"].kind_hint, "wireless_client")
        # a MAC only learned on a port (no client record) still becomes an observation
        self.assertIn(RIO_SL_SEC, by_mac)
        self.assertEqual((by_mac[RIO_SL_SEC].vlan, by_mac[RIO_SL_SEC].uplink_port), (21, "Port 24"))
        methods = {}
        for n in r.neighbours:
            methods[n.method] = methods.get(n.method, 0) + 1
        self.assertEqual(methods, {"unifi_lldp": 3, "unifi_uplink": 2, "mac_table": 13, "unifi_client": 9})
        lldp = {(n.local_port, n.remote_mac): n for n in r.neighbours if n.method == "unifi_lldp"}
        self.assertEqual(lldp[("Port 24", SW_STAGE)].remote_port, "gi26")
        vlans = sorted(n.vlan for n in r.networks)
        self.assertEqual(vlans, [20, 21, 30, 40, 50, 99], "the disabled VLAN 77 is skipped")
        self.assertEqual([n.subnet for n in r.networks if n.vlan == 50], ["10.50.0.0/24"])

    def test_mdns(self):
        r = self.by_id["mdns"].parse(json.loads((DISC_FIXTURES / "mdns.json").read_text()))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.summary()["stats"]["dante_devices"], 5)
        dante = [o for o in r.observations if o.dante_name]
        self.assertEqual(sorted(o.dante_name for o in dante), ["FOH-CL5", "QSYS-Core110f", "RIO-SL", "RIO-SL", "RIO-SR", "ULXD4Q-STAGE"])
        sl = [o for o in dante if o.dante_name == "RIO-SL"]
        self.assertEqual(sorted((o.evidence["role"], o.ip) for o in sl), [("primary", "10.20.0.21"), ("secondary", "10.21.0.21")])
        self.assertEqual(sl[0].mac, RIO_SL, "Dante id in the cmc TXT record becomes the MAC")
        self.assertEqual((sl[0].manufacturer, sl[0].model), ("Yamaha", "Rio3224-D"))
        self.assertTrue(all(s.startswith("_netaudio-") for s in sl[0].services))
        atem = [o for o in r.observations if o.name == "ATEM Mini Pro ISO"][0]
        self.assertEqual((atem.kind_hint, atem.manufacturer, atem.mac), ("video_switcher", "Blackmagic Design", ""))
        shure = [o for o in r.observations if "_shure._tcp.local." in o.services][0]
        self.assertEqual((shure.model, shure.serial, shure.kind_hint), ("ULXD4Q", "ULXD4Q-9001", "wireless_rx"))
        dev = [o for o in r.observations if o.name == "Fathom Dev"][0]
        self.assertEqual((dev.mac, dev.ip), ("", "10.30.0.200"))
        self.assertEqual(r.neighbours, [], "mDNS never yields links")

    def test_lldp_and_cdp_frames(self):
        r = self.by_id["lldp"].parse(json.loads((DISC_FIXTURES / "lldp.json").read_text()))
        self.assertEqual(r.status, "ok")
        self.assertEqual((r.summary()["stats"]["lldp"], r.summary()["stats"]["cdp"]), (1, 1))
        by_mac = {o.mac: o for o in r.observations}
        sw = by_mac[SW_STAGE]
        self.assertEqual((sw.hostname, sw.ip, sw.vlan, sw.kind_hint), ("sw-stage", "10.99.0.3", 30, "switch"))
        self.assertEqual((sw.manufacturer, sw.model, sw.serial), ("NETGEAR", "M4250-26G4F-PoE+", "6AF2C5X12345"))
        cisco = by_mac[BC_SWITCH]
        self.assertEqual((cisco.name, cisco.ip, cisco.model), ("bc-switch.campus.local", "10.99.0.4", "WS-C2960X-24PS-L"))
        nb = {n.method: n for n in r.neighbours}
        self.assertEqual((nb["lldp"].local_port, nb["lldp"].remote_mac, nb["lldp"].remote_port, nb["lldp"].vlan), ("eth0", SW_STAGE, "Port 5", 30))
        self.assertEqual((nb["cdp"].local_port, nb["cdp"].remote_mac, nb["cdp"].remote_port), ("eth1", BC_SWITCH, "GigabitEthernet1/0/7"))

    def test_lldp_parser_rejects_short_frames(self):
        lldp = self.by_id["lldp"]
        self.assertEqual(lldp.parse_cdp(b"\x00" * 10), None)
        r = lldp.parse({"frames": [{"hex": "00"}, {"hex": "zz"}], "window": 5})
        self.assertEqual(r.observations, [])

    def test_arp(self):
        r = self.by_id["arp"].parse(json.loads((DISC_FIXTURES / "arp.json").read_text()))
        self.assertEqual(r.status, "ok")
        st = r.summary()["stats"]
        self.assertEqual((st["entries"], st["format"]), (9, "proc"))
        by_mac = {o.mac: o for o in r.observations}
        self.assertEqual((by_mac[GATEWAY].ip, by_mac[GATEWAY].hostname, by_mac[GATEWAY].manufacturer), ("10.30.0.1", "gateway", "Ubiquiti"))
        self.assertEqual(by_mac["b8:27:eb:11:22:33"].manufacturer, "Raspberry Pi Foundation")
        self.assertEqual(by_mac["00:17:c8:0a:0b:0c"].manufacturer, "", "unknown OUI stays blank")

    def test_arp_table_formats(self):
        arp = self.by_id["arp"]
        proc = "IP address       HW type     Flags       HW address            Mask     Device\n10.0.0.5         0x1         0x2         aa:bb:cc:dd:ee:01     *        eth0\n10.0.0.6         0x1         0x0         00:00:00:00:00:00     *        eth0\n"
        self.assertEqual([r["ip"] for r in arp.parse_table("proc", proc)], ["10.0.0.5"])
        neigh = "10.0.0.7 dev eth0 lladdr aa:bb:cc:dd:ee:02 REACHABLE\n10.0.0.8 dev eth0  FAILED\n224.0.0.251 dev eth0 lladdr 01:00:5e:00:00:fb NOARP\n"
        self.assertEqual([r["mac"] for r in arp.parse_table("ip-neigh", neigh)], ["aa:bb:cc:dd:ee:02"])
        arp_an = "? (10.0.0.9) at aa:bb:cc:dd:ee:03 [ether] on en0\n? (10.0.0.10) at (incomplete) on en0\n"
        self.assertEqual([r["ip"] for r in arp.parse_table("arp-an", arp_an)], ["10.0.0.9"])

    def test_oui_lookup(self):
        oui = requires("discovery.oui")
        self.assertIn("Audinate", oui.vendor("00:1d:c1:10:20:21"), "Dante modules carry Audinate's OUI")
        self.assertTrue(oui.vendor("78:45:58:aa:00:01").startswith("Ubiquiti"))
        self.assertEqual(oui.vendor("ff:ff:ff:00:00:00"), "")
        self.assertTrue(oui.is_multicast("01:00:5e:00:00:fb"))
        self.assertFalse(oui.is_multicast(AV_CORE))


# --------------------------------------------------------------------------- correlation


class Correlation(unittest.TestCase):
    """Identity resolution and matching against the document (FR-DISC-03)."""

    @classmethod
    def setUpClass(cls):
        cls.corr = requires("discovery.correlate")
        cls.results = _results()
        cls.doc = _campus_doc()
        cls.entities = cls.corr.correlate(cls.results, cls.doc)
        cls.by_id = {e.id: e for e in cls.entities}

    def test_entities_merge_across_sources_by_mac(self):
        gw = _by(self.entities, GATEWAY)
        self.assertEqual(gw.sources, ["unifi", "arp"])
        self.assertEqual(sorted(gw.ips), ["10.30.0.1", "10.99.0.1"])
        self.assertEqual(gw.name, "Gateway")
        self.assertEqual(gw.level, "high")
        qsys = _by(self.entities, "00:60:74:12:34:56")
        self.assertEqual(qsys.sources, ["unifi", "mdns", "arp"])
        self.assertEqual((qsys.dante_name, qsys.manufacturer, qsys.model), ("QSYS-Core110f", "QSC", "Core 110f"))

    def test_dante_secondary_joins_by_name_and_same_run_ip(self):
        sl = _by(self.entities, RIO_SL)
        self.assertEqual(sorted(sl.macs), [RIO_SL, RIO_SL_SEC], "secondary MAC learned on the switch joins through the mDNS secondary address")
        self.assertEqual(sorted(sl.ips), ["10.20.0.21", "10.21.0.21"])
        self.assertEqual(sl.dante_name, "RIO-SL")
        self.assertEqual(sl.kind, "stage_io")

    def test_mac_less_mdns_records_join_by_ip(self):
        atem = _by(self.entities, "7c:2e:0d:aa:bb:01")
        self.assertIn("mdns", atem.sources)
        self.assertEqual((atem.name, atem.kind), ("ATEM Mini Pro ISO", "video_switcher"))
        shure = _by(self.entities, "00:0e:dd:44:55:66")
        self.assertEqual((shure.serial, shure.dante_name), ("ULXD4Q-9001", "ULXD4Q-STAGE"))

    def test_entity_confidence_formula(self):
        e = self.corr.Entity(id="x")
        self.corr.score_entity(e)
        self.assertEqual(e.confidence, 0.25)
        self.assertEqual(e.status, "unresolved", "no MAC and no name")
        e = self.corr.Entity(id="x", macs=[AV_CORE], sources=["unifi", "arp"], name="n", manufacturer="m", serial="s1234")
        self.corr.score_entity(e)
        self.assertEqual(e.confidence, 1.0)
        self.assertEqual(e.level, "high")
        e = self.corr.Entity(id="x", macs=[AV_CORE], sources=["arp"])
        self.corr.score_entity(e)
        self.assertEqual((e.confidence, e.level), (0.5, "medium"))
        dev = [x for x in self.entities if x.name == "Fathom Dev"][0]
        self.assertEqual(dev.macs, [])
        self.assertEqual((round(dev.confidence, 2), dev.level), (0.4, "low"))

    def test_generic_hostnames_do_not_merge(self):
        Obs = requires("discovery.probes:Observation")
        PR = requires("discovery.probes:ProbeResult")
        res = PR(probe="arp", observations=[Obs(source="arp", mac="aa:aa:aa:00:00:01", ip="10.1.0.1", hostname="localhost"),
                                            Obs(source="mdns", ip="10.1.0.2", hostname="localhost"),
                                            Obs(source="arp", mac="aa:aa:aa:00:00:03", ip="10.1.0.3", hostname="stage-left-box"),
                                            Obs(source="mdns", ip="10.1.0.4", hostname="Stage-Left-Box.local")])
        ents = self.corr.correlate([res], {})
        self.assertEqual(len(ents), 3)
        box = _by(ents, "aa:aa:aa:00:00:03")
        self.assertEqual(sorted(box.ips), ["10.1.0.3", "10.1.0.4"], "hostnames compare loosely (case, .local)")

    def test_match_against_document(self):
        sl = _by(self.entities, RIO_SL)
        self.assertEqual((sl.status, sl.match["device"]), ("match", "rio-sl"))
        self.assertGreaterEqual(sl.match["score"], 0.6)
        sw = _by(self.entities, SW_STAGE)
        self.assertEqual((sw.status, sw.match["device"]), ("match", "sw-stage"), "IP + hostname (= document id) with no MAC in the document")
        cl5 = _by(self.entities, CL5)
        self.assertEqual((cl5.status, cl5.match["device"]), ("possible", "foh-cl5"), "Dante name + model but a different MAC / IP")
        self.assertTrue(any("Dante" in r for r in cl5.match["reasons"]), cl5.match["reasons"])
        gw = _by(self.entities, GATEWAY)
        self.assertEqual(gw.status, "new")
        counts = {}
        for e in self.entities:
            counts[e.status] = counts.get(e.status, 0) + 1
        self.assertEqual(counts, {"new": 13, "match": 2, "possible": 3})

    def test_doc_index_scores(self):
        idx = self.corr.DocIndex({"devices": [{"id": "d1", "name": "Rack DSP", "model": "Core 110f", "interfaces": [{"mac": "AA:BB:CC:00:00:01", "ip": "10.9.0.1"}],
                                               "inventory": {"serial": "SER-12345"}}]})
        e = self.corr.Entity(id="x", macs=["aa:bb:cc:00:00:01"])
        scores, why = idx.score(e)
        self.assertGreaterEqual(scores["d1"], 0.6)
        self.assertEqual(why["d1"], ["MAC aa:bb:cc:00:00:01"])
        e = self.corr.Entity(id="x", macs=["aa:bb:cc:00:00:99"], ips=["10.9.0.1"])
        scores, _ = idx.score(e)
        self.assertTrue(0.3 <= scores["d1"] < 0.6, scores)
        e = self.corr.Entity(id="x", model="Core 110f")
        self.assertEqual(idx.score(e)[0], {}, "model alone never matches")
        e = self.corr.Entity(id="x", ips=["10.9.0.1"], model="Core 110f")
        self.assertAlmostEqual(idx.score(e)[0]["d1"], 0.4, msg="model adds 0.10 only next to another hit")
        e = self.corr.Entity(id="x", serial="SER-12345")
        self.assertGreaterEqual(idx.score(e)[0]["d1"], 0.6)


# --------------------------------------------------------------------------- topology


class Topology(unittest.TestCase):
    """Connections, flags and confidence from port tables and LLDP (FR-DISC-04)."""

    @classmethod
    def setUpClass(cls):
        cls.topo = requires("discovery.topology")
        corr = requires("discovery.correlate")
        cls.results = _results()
        cls.doc = _campus_doc()
        cls.entities = corr.correlate(cls.results, cls.doc)
        cls.conns = cls.topo.build_connections(cls.entities, cls.results, cls.doc, _device_ids(cls.topo, cls.entities, cls.doc))
        cls.by_port = {}
        for c in cls.conns:
            cls.by_port.setdefault((c.switch["label"], c.port), []).append(c)

    def one(self, switch, port, flag=None):
        rows = [c for c in self.by_port[(switch, port)] if flag is None or c.flag == flag]
        self.assertEqual(len(rows), 1, (switch, port, flag, [c.peer["label"] for c in rows]))
        return rows[0]

    def test_lldp_plus_client_table_agree(self):
        c = self.one("AV Core", "Port 3")
        self.assertEqual(c.peer["label"], "FOH console")
        self.assertEqual(c.confidence, 0.95)
        self.assertEqual(c.level, "high")
        self.assertIn("unifi_lldp", c.methods)
        self.assertIn("unifi_client", c.methods)
        self.assertEqual(c.peer["port"], "Dante Primary", "the peer's own LLDP port id")
        self.assertEqual(c.cable["medium"], "dante")

    def test_single_mac_on_port(self):
        c = self.one("AV Core", "Port 1")
        self.assertEqual((c.peer["mac"], c.flag, c.confidence), (RIO_SL, "", 0.85))
        self.assertEqual(c.cable["from"], {"device": "av-core", "port": "p1"})
        self.assertEqual(c.cable["to"], {"device": "rio-sl", "port": "dante-primary"}, "matched document device → its real port")
        self.assertEqual((c.cable["medium"], c.cable["type"]), ("dante", "cat6"))

    def test_mac_table_only_is_medium(self):
        Nb = requires("discovery.probes:Neighbour")
        Obs = requires("discovery.probes:Observation")
        PR = requires("discovery.probes:ProbeResult")
        corr = requires("discovery.correlate")
        res = PR(probe="unifi", observations=[Obs(source="unifi", mac="aa:00:00:00:00:01", name="SW", kind_hint="switch", ports=[{"idx": 1, "name": "Port 1"}]),
                                              Obs(source="unifi", mac="aa:00:00:00:00:02", ip="10.0.0.2")],
                 neighbours=[Nb(source="unifi", method="mac_table", local_mac="aa:00:00:00:00:01", local_name="SW", local_port="Port 1", remote_mac="aa:00:00:00:00:02")])
        ents = corr.correlate([res], {})
        conns = self.topo.build_connections(ents, [res], {}, {})
        self.assertEqual(len(conns), 1)
        self.assertEqual((conns[0].confidence, conns[0].level, conns[0].flag), (0.6, "medium", ""))

    def test_unmanaged_switch_behind_port(self):
        rows = self.by_port[("AV Core", "Port 7")]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(c.flag == "unmanaged" for c in rows))
        self.assertTrue(all(c.peers_on_port == 3 for c in rows))
        self.assertTrue(all(c.cable is None for c in rows), "no cable proposed for a shared port")
        self.assertEqual(rows[0].confidence, 0.65)

    def test_uplinks_and_via(self):
        up = self.one("AV Core", "Port 24", "uplink")
        self.assertEqual((up.peer["label"], up.peer["port"], up.confidence), ("sw-stage", "gi26", 0.9))
        self.assertEqual(up.cable["to"]["device"], "sw-stage")
        self.assertEqual(up.cable["to"].get("port"), None, "gi26 is not a port of the document switch; no guess")
        via = [c for c in self.by_port[("AV Core", "Port 24")] if c.flag == "via"]
        self.assertEqual(sorted(c.peer["label"] for c in via), ["RIO-SL", "ULXD4Q-STAGE"])
        self.assertTrue(all(c.cable is None for c in via))
        self.assertTrue(all(c.confidence < 0.6 for c in via))
        ap = self.one("AV Core", "Port 12")
        self.assertEqual((ap.flag, ap.confidence, ap.peer["label"]), ("uplink", 0.95, "Lobby AP"))
        gw = self.one("Gateway", "Port 9")
        self.assertEqual((gw.flag, gw.confidence, gw.peer["port"]), ("uplink", 0.85, "Port 26"))

    def test_sniffed_lldp_becomes_host_rows(self):
        host = [c for c in self.conns if c.flag == "host"]
        self.assertEqual(sorted((c.switch["label"], c.port, c.peer["port"]) for c in host),
                         [("bc-switch.campus.local", "Port 7", "eth1"), ("sw-stage", "Port 5", "eth0")])
        self.assertTrue(all(c.confidence == 0.9 and c.cable is None for c in host))

    def test_existing_cable_marks_connection(self):
        doc = json.loads(json.dumps(self.doc))
        doc.setdefault("cables", []).append({"id": "c-9999", "from": {"device": "av-core", "port": "p1"}, "to": {"device": "rio-sl", "port": "dante-primary"}, "medium": "dante"})
        doc["devices"].append({"id": "av-core", "name": "AV Core", "kind": "switch", "room": doc["devices"][0]["room"], "ports": [{"id": "p1", "medium": "network"}],
                               "interfaces": [{"id": "m", "mac": AV_CORE}]})
        corr = requires("discovery.correlate")
        ents = corr.correlate(self.results, doc)
        conns = self.topo.build_connections(ents, self.results, doc, _device_ids(self.topo, ents, doc))
        c = [x for x in conns if x.switch["label"] == "AV Core" and x.port == "Port 1"][0]
        self.assertEqual(c.status, "exists")

    def test_networks(self):
        nets = self.topo.build_networks(self.results, self.entities, self.doc)
        by_vlan = {n["vlan"]: n for n in nets}
        self.assertEqual(sorted(by_vlan), [20, 21, 30, 40, 50, 99])
        self.assertEqual(by_vlan[50]["status"], "new")
        self.assertEqual(by_vlan[20]["status"], "match")
        self.assertTrue(by_vlan[20]["match"], "VLAN 20 is the sample's Dante primary network")
        self.assertGreaterEqual(by_vlan[30]["hosts"], 5)

    def test_port_helpers(self):
        self.assertEqual(self.topo.canonical_port("Port 3"), "Port 3")
        self.assertEqual(self.topo.canonical_port("3"), "Port 3")
        self.assertEqual(self.topo.port_index("gi26"), 26)
        dev = {"ports": [{"id": "p1", "name": "GbE PoE+ 1", "medium": "network"}, {"id": "p2", "name": "GbE PoE+ 2", "medium": "network"}]}
        self.assertEqual(self.topo.doc_port_for(dev, index=2), "p2")
        self.assertEqual(self.topo.doc_port_for(dev, label="GbE PoE+ 1"), "p1")
        self.assertEqual(self.topo.doc_port_for(dev, label="xyz"), "", "a known label that does not match is not guessed")
        self.assertEqual(self.topo.doc_port_for(dev), "p1", "nothing known: first network port")

    def test_connection_rows_mirror_cable_schedule(self):
        rows = self.topo.connection_rows(self.conns, self.doc, {})
        self.assertEqual(len(rows), len(self.conns))
        for key in ("tag", "from_room", "from_device", "from_port", "to_room", "to_device", "to_port", "medium", "type", "length", "confidence", "level", "flag"):
            self.assertIn(key, rows[0], key)


# --------------------------------------------------------------------------- jobs


class Jobs(unittest.TestCase):
    """In-process runner: one per key, cancel, hard time limit (FR-DISC-01)."""

    def setUp(self):
        self.jobs = requires("jobs")
        self.runner = self.jobs.JobRunner(workers=2, grace=0.5)

    def _wait(self, job, timeout=10.0):
        t0 = time.time()
        while job.status in self.jobs.ACTIVE and time.time() - t0 < timeout:
            time.sleep(0.02)
        return job.status

    def test_runs_and_reports(self):
        def body(job):
            job.log("hello")
            job.set_progress(0.5, "half")
            return {"n": 1}

        job = self.runner.submit("t", "k1", body)
        self.assertEqual(self._wait(job), "done")
        d = job.to_dict()
        self.assertEqual((job.result, d["progress"], d["active"]), ({"n": 1}, 1.0, False))
        self.assertEqual([x["msg"] for x in d["log"]], ["hello"])

    def test_one_active_job_per_key(self):
        gate = threading.Event()
        job = self.runner.submit("t", "k2", lambda j: gate.wait(5))
        with self.assertRaises(self.jobs.JobBusy) as cm:
            self.runner.submit("t", "k2", lambda j: None)
        self.assertIs(cm.exception.job, job)
        other = self.runner.submit("t", "k3", lambda j: 1)
        self.assertEqual(self._wait(other), "done")
        gate.set()
        self.assertEqual(self._wait(job), "done")
        self.assertIsNone(self.runner.active("k2"))

    def test_cancel(self):
        def body(job):
            while True:
                job.check()
                job.wait(0.05)

        job = self.runner.submit("t", "k4", body)
        time.sleep(0.1)
        self.runner.cancel(job.id, "stop")
        self.assertEqual(self._wait(job), "cancelled")
        self.assertEqual(job.error, "stop")

    def test_time_limit(self):
        def body(job):
            while not job.wait(0.05):
                pass
            return "partial"

        job = self.runner.submit("t", "k5", body, time_limit=0.3)
        self.assertEqual(self._wait(job), "timeout")
        self.assertEqual(job.result, "partial", "a cooperative job keeps its partial result")

    def test_time_limit_on_a_stuck_job(self):
        gate = threading.Event()
        job = self.runner.submit("t", "k6", lambda j: gate.wait(10), time_limit=0.3)
        self.assertEqual(self._wait(job, 5), "timeout", "the grace timer marks a non-cooperative job finished")
        gate.set()

    def test_failure_is_the_jobs_not_the_servers(self):
        def body(job):
            raise ValueError("boom")

        job = self.runner.submit("t", "k7", body)
        self.assertEqual(self._wait(job), "failed")
        self.assertIn("boom", job.error)

    def test_pool_starts_lazily(self):
        self.assertIsNone(self.runner._pool, "a runner creates its pool on first submit only")
        self.assertEqual(self.runner.list(), [])


# --------------------------------------------------------------------------- settings


class Settings(unittest.TestCase):
    """Per-project settings, secrets in a side file, env fallbacks, redaction (FR-DISC-07)."""

    def setUp(self):
        self.s = requires("discovery.settings")

    def test_secrets_never_enter_the_document(self):
        with temp_data_dir() as data:
            pdir = install_campus(data, "campus")
            doc = {"settings": {}}
            value = self.s.apply_update(doc, pdir, {"window": 45, "probes": {"unifi": {"url": "https://10.0.0.1", "api_key": "k-secret-123", "verify_tls": True}}})
            self.assertEqual(value["window"], 45)
            self.assertEqual(value["probes"]["unifi"]["url"], "https://10.0.0.1")
            self.assertNotIn("api_key", json.dumps(value))
            self.assertNotIn("k-secret-123", json.dumps(value))
            sp = self.s.secrets_path(pdir)
            self.assertTrue(sp.is_file())
            self.assertEqual(stat.S_IMODE(sp.stat().st_mode), 0o600)
            doc["settings"]["discovery"] = value
            pub = self.s.public(doc, pdir)
            self.assertNotIn("k-secret-123", json.dumps(pub))
            self.assertTrue(pub["probes"]["unifi"]["api_key_set"])
            eff = self.s.effective(doc, pdir)
            self.assertEqual(eff["probes"]["unifi"]["api_key"], "k-secret-123")
            # None keeps, "" clears
            value = self.s.apply_update(doc, pdir, {"probes": {"unifi": {"api_key": None}}})
            self.assertEqual(self.s.effective(doc, pdir)["probes"]["unifi"]["api_key"], "k-secret-123")
            value = self.s.apply_update(doc, pdir, {"probes": {"unifi": {"api_key": ""}}})
            self.assertFalse(self.s.public(doc, pdir)["probes"]["unifi"]["api_key_set"])
            self.assertEqual(self.s.redact("key k-secret-123 leaked", pdir), "key k-secret-123 leaked", "cleared secrets are not redacted")

    def test_validation(self):
        with temp_data_dir() as data:
            pdir = install_campus(data, "campus")
            for body in ({"probes": {"nope": {}}}, {"probes": {"unifi": {"bogus": 1}}}, {"probes": {"unifi": {"api_key": 5}}}, {"probes": []}, {"room": 3}):
                with self.assertRaises(ValueError, msg=body):
                    self.s.apply_update({}, pdir, body)
            self.assertEqual(self.s.apply_update({}, pdir, {"window": 1})["window"], self.s.MIN_WINDOW)
            self.assertEqual(self.s.apply_update({}, pdir, {"window": 99999})["window"], self.s.MAX_WINDOW)
            self.assertEqual(self.s.apply_update({}, pdir, {"window": "abc"})["window"], self.s.DEFAULT_WINDOW)

    def test_env_fallback_and_redaction(self):
        with temp_data_dir() as data:
            pdir = install_campus(data, "campus")
            with temp_env(FATHOM_UNIFI_URL="https://env.example", FATHOM_UNIFI_PASSWORD="env-pass-9", FATHOM_UNIFI_VERIFY_TLS="1"):
                eff = self.s.effective({}, pdir)
                self.assertEqual((eff["probes"]["unifi"]["url"], eff["probes"]["unifi"]["password"], eff["probes"]["unifi"]["verify_tls"]), ("https://env.example", "env-pass-9", True))
                pub = self.s.public({}, pdir)
                self.assertTrue(pub["probes"]["unifi"]["password_from_env"])
                self.assertEqual(pub["probes"]["unifi"]["url_env"], "https://env.example")
                self.assertNotIn("env-pass-9", json.dumps(pub))
                self.assertEqual(self.s.redact("login env-pass-9 failed", pdir), "login " + self.s.REDACTED + " failed")
                # a stored value wins over the environment
                doc = {"settings": {"discovery": {"probes": {"unifi": {"url": "https://stored.example"}}}}}
                self.assertEqual(self.s.effective(doc, pdir)["probes"]["unifi"]["url"], "https://stored.example")

    def test_stored_ignores_secrets_leaked_into_doc(self):
        doc = {"settings": {"discovery": {"probes": {"unifi": {"api_key": "oops", "url": "u"}}}}}
        st = self.s.stored(doc)
        self.assertNotIn("api_key", st["probes"]["unifi"])
        self.assertEqual(st["probes"]["unifi"]["url"], "u")


# --------------------------------------------------------------------------- API end to end


class DiscoveryApi(unittest.TestCase):
    """start → 409 → poll → findings → promote → re-run without duplicates (FR-DISC-01/05/06)."""

    def setUp(self):
        requires("discovery")
        self.app = get_app()

    def req(self, method, path, body=None, headers=None):
        h = dict(JSON_H if body is not None else {})
        h.update(headers or {})
        return call(self.app, method, path, body, h)

    def run_and_wait(self, base, body=None, timeout=30.0):
        st, _, b = self.req("POST", base + "/discovery/runs", body if body is not None else {"window": 10})
        self.assertEqual(st, 202, b)
        rid = jbody(b)["run"]["id"]
        t0 = time.time()
        while time.time() - t0 < timeout:
            st, _, b = self.req("GET", base + "/discovery/runs/" + rid)
            self.assertEqual(st, 200, b)
            run = jbody(b)["run"]
            if not run["active"]:
                return run
            time.sleep(0.1)
        self.fail("run %s did not finish: %s" % (rid, run))

    def test_full_cycle(self):
        with temp_data_dir(**FAST) as data:
            install_campus(data, "campus")
            base = "/api/v2/projects/campus"
            st, _, b = self.req("GET", base + "/discovery/runs")
            self.assertEqual(st, 200, b)
            listing = jbody(b)
            self.assertEqual((listing["runs"], listing["active"], listing["mode"]), ([], None, "passive"))
            self.assertEqual([s["id"] for s in listing["sources"]], ["unifi", "mdns", "lldp", "arp"])
            self.assertTrue(all(s["mode"] == "passive" and s["available"] for s in listing["sources"]))

            st, _, b = self.req("POST", base + "/discovery/runs", {"window": 10})
            self.assertEqual(st, 202, b)
            run = jbody(b)["run"]
            rid = run["id"]
            self.assertIn(run["status"], ("queued", "running"))
            st, _, b = self.req("POST", base + "/discovery/runs", {"window": 10})
            self.assertEqual(st, 409, b)
            err = jbody(b)
            self.assertEqual(err["code"], "run_active")
            self.assertEqual(err["details"]["run"], rid)
            st, _, b = self.req("GET", base + "/discovery/runs")
            self.assertEqual(jbody(b)["active"], rid)

            t0 = time.time()
            while time.time() - t0 < 30:
                st, _, b = self.req("GET", base + "/discovery/runs/" + rid)
                run = jbody(b)["run"]
                if not run["active"]:
                    break
                time.sleep(0.1)
            self.assertEqual(run["status"], "done", run)
            self.assertEqual(run["progress"], 1.0)
            self.assertEqual(run["counts"]["probes"], {"unifi": "ok", "mdns": "ok", "lldp": "ok", "arp": "ok"})
            self.assertEqual((run["counts"]["entities"], run["counts"]["new"], run["counts"]["matched"], run["counts"]["possible"]), (18, 13, 2, 3))
            self.assertTrue(any("passive only" in x["msg"] for x in run["log"]), run["log"])
            rdir = data / "projects" / "campus" / "exports" / "discovery" / rid
            for f in ("run.json", "findings.json", "raw/unifi.json", "raw/mdns.json", "raw/lldp.json", "raw/arp.json"):
                self.assertTrue((rdir / f).is_file(), f)
            self.assertFalse((rdir.parent / ".lock").exists(), "the run lock is released")

            # the run is registered as the project's discovery import and feeds the overlay
            st, _, b = self.req("GET", base)
            doc = jbody(b)["doc"] if "doc" in jbody(b) else jbody(b)
            imps = [i for i in doc.get("imports", []) if i.get("kind") == "discovery"]
            self.assertEqual(len(imps), 1, doc.get("imports"))
            st, _, b = self.req("GET", base + "/overlay")
            self.assertEqual(st, 200, b)
            ov = jbody(b)
            auto = [d for d in ov.get("devices", []) if d.get("source") == "discovery"]
            self.assertGreaterEqual(len(auto), 8, "high-confidence new hosts become overlay devices")
            self.assertFalse(any(d.get("name") == "iPhone" for d in auto), "wireless-only clients stay out of the overlay")
            self.assertTrue(any(r.get("kind") == "network" for r in ov.get("routes", [])), "proposed links are network routes")
            self.assertTrue(any(i.get("source") == "discovery" for i in ov.get("interfaces", {}).get("rio-sl", [])), ov.get("interfaces", {}).keys())

            # findings
            st, _, b = self.req("GET", base + "/discovery/runs/" + rid + "/findings")
            self.assertEqual(st, 200, b)
            f = jbody(b)
            ents = {e["id"]: e for e in f["entities"]}
            by_mac = {m: e for e in f["entities"] for m in e["macs"]}
            self.assertEqual(by_mac[RIO_SL]["status"], "match")
            self.assertEqual(by_mac[RIO_SR]["status"], "possible")
            self.assertEqual(by_mac[AV_CORE]["status"], "new")
            self.assertTrue(by_mac[AV_CORE]["proposed"]["ports"], "a proposed switch carries its ports")
            conn_p2 = [c for c in f["connections"] if c["switch"]["mac"] == AV_CORE and c["port"] == "Port 2"][0]
            conn_p4 = [c for c in f["connections"] if c["switch"]["mac"] == AV_CORE and c["port"] == "Port 4"][0]
            guest = [n for n in f["networks"] if n["vlan"] == 50][0]
            iphone = by_mac["f0:18:98:aa:bb:cc"]
            self.assertEqual(len(f["rows"]), len(f["connections"]))

            # promote: one new switch, one new device, merge RIO-SR, two cables, the guest network; ignore the phone
            body = {"entities": [by_mac[AV_CORE]["id"], by_mac["00:60:74:12:34:56"]["id"]], "merge": {by_mac[RIO_SR]["id"]: "rio-sr"},
                    "connections": [conn_p2["id"], conn_p4["id"]], "networks": [guest["id"]], "ignore": {"entities": [iphone["id"]]}, "room": "theatre"}
            st, _, b = self.req("POST", base + "/discovery/runs/" + rid + "/findings/promote", body)
            self.assertEqual(st, 200, b)
            res = jbody(b)
            self.assertEqual(res["summary"], {"devices": 2, "merged": 1, "cables": 2, "networks": 1, "ignored": 1})
            st, _, b = self.req("GET", base)
            doc = jbody(b)["doc"] if "doc" in jbody(b) else jbody(b)
            devs = {d["id"]: d for d in doc["devices"]}
            self.assertIn("av-core", devs)
            self.assertEqual(devs["av-core"]["room"], "theatre")
            self.assertIn("discovered", devs["av-core"].get("tags", []))
            self.assertEqual(devs["av-core"]["interfaces"][0]["source"], "discovery")
            self.assertNotIn("_switch_mac", devs["av-core"]["interfaces"][0])
            sr = devs["rio-sr"]
            self.assertEqual(sr["dante_name"], "RIO-SR", "merge never overwrites")
            disc_itf = [i for i in sr["interfaces"] if i.get("source") == "discovery"]
            self.assertEqual(len(disc_itf), 1)
            self.assertEqual((disc_itf[0]["mac"], disc_itf[0]["switch"], disc_itf[0]["switch_port"]), (RIO_SR, "av-core", "p2"))
            cables = [c for c in doc["cables"] if str(c.get("note", "")).startswith("Discovered")]
            self.assertEqual(len(cables), 2)
            ends = sorted((c["from"]["device"], c["from"]["port"], c["to"]["device"], c["to"]["port"]) for c in cables)
            self.assertEqual(ends[0], ("av-core", "p2", "rio-sr", "dante-primary"), "the merged device's real port is used")
            self.assertEqual(ends[1][:3], ("av-core", "p4", "qsys-core110f"))
            self.assertTrue(all(c["status"] == "planned" and c["type"] == "cat6" for c in cables))
            self.assertIn("guest-wi-fi", [n["id"] for n in doc["networks"]])
            self.assertNotIn("api_key", json.dumps(doc))
            hist_st, _, hb = self.req("GET", base + "/history")
            self.assertEqual(hist_st, 200)
            self.assertIn("Discovery:", json.dumps(jbody(hb)))

            # findings re-read against the live document: promoted things now match / exist
            st, _, b = self.req("GET", base + "/discovery/runs/" + rid + "/findings")
            f2 = jbody(b)
            by_mac2 = {m: e for e in f2["entities"] for m in e["macs"]}
            self.assertEqual((by_mac2[AV_CORE]["status"], by_mac2[AV_CORE]["match"]["device"]), ("match", "av-core"))
            self.assertEqual((by_mac2[RIO_SR]["status"], by_mac2[RIO_SR]["match"]["device"]), ("match", "rio-sr"))
            self.assertEqual(by_mac2["f0:18:98:aa:bb:cc"]["status"], "ignored")
            conn2 = {c["id"]: c for c in f2["connections"]}
            self.assertEqual(conn2[conn_p2["id"]]["status"], "exists")
            self.assertEqual(conn2[conn_p4["id"]]["status"], "exists")
            self.assertEqual(f2["counts"]["ignored"], 1)

            # a second run proposes nothing twice
            run2 = self.run_and_wait(base)
            self.assertEqual(run2["status"], "done")
            self.assertEqual(run2["counts"]["new"], 13 - 2 - 1, "two promoted, one ignored")
            self.assertEqual(run2["counts"]["matched"], 2 + 3)
            st, _, b = self.req("GET", base + "/discovery/runs/" + run2["id"] + "/findings")
            f3 = jbody(b)
            self.assertFalse(any(e["status"] == "new" and e.get("proposed", {}).get("id") in ("av-core", "qsys-core110f") for e in f3["entities"]))
            st, _, b = self.req("GET", base)
            doc = jbody(b)["doc"] if "doc" in jbody(b) else jbody(b)
            ids = [d["id"] for d in doc["devices"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(len([i for i in doc["imports"] if i.get("kind") == "discovery"]), 1, "still one discovery import")
            # promoting an ignored/unpromotable thing is a 400, an unknown run a 404
            st, _, b = self.req("POST", base + "/discovery/runs/" + rid + "/findings/promote", {"entities": [by_mac[RIO_SL]["id"]]})
            self.assertEqual(st, 400, b)
            st, _, b = self.req("GET", base + "/discovery/runs/run-20000101-000000-dead/findings")
            self.assertEqual(st, 404, b)
            st, _, b = self.req("GET", base + "/discovery/runs")
            self.assertEqual(len(jbody(b)["runs"]), 2)

    def test_cancel_keeps_partial_results(self):
        env = dict(FAST, FATHOM_DISCOVERY_FIXTURE_DELAY="20")
        with temp_data_dir(**env) as data:
            install_campus(data, "campus")
            base = "/api/v2/projects/campus"
            st, _, b = self.req("POST", base + "/discovery/runs", {"window": 30, "probes": ["mdns", "arp"]})
            self.assertEqual(st, 202, b)
            rid = jbody(b)["run"]["id"]
            time.sleep(0.5)
            st, _, b = self.req("DELETE", base + "/discovery/runs/" + rid)
            self.assertEqual(st, 200, b)
            t0 = time.time()
            while time.time() - t0 < 15:
                st, _, b = self.req("GET", base + "/discovery/runs/" + rid)
                run = jbody(b)["run"]
                if not run["active"]:
                    break
                time.sleep(0.1)
            self.assertEqual(run["status"], "cancelled", run)
            self.assertLess(time.time() - t0, 10, "cancel does not wait for the window")
            self.assertEqual(run["probes"], ["mdns", "arp"])
            self.assertGreaterEqual(run["counts"]["entities"], 9, "the ARP probe had finished; its hosts are kept")
            st, _, b = self.req("POST", base + "/discovery/runs", {"window": 10})
            self.assertEqual(st, 202, "a cancelled run frees the slot")
            rid2 = jbody(b)["run"]["id"]
            self.req("DELETE", base + "/discovery/runs/" + rid2)
            t0 = time.time()
            while time.time() - t0 < 15 and jbody(self.req("GET", base + "/discovery/runs/" + rid2)[2])["run"]["active"]:
                time.sleep(0.1)

    def test_validation_and_roles(self):
        with temp_data_dir(**FAST) as data:
            install_campus(data, "campus")
            base = "/api/v2/projects/campus"
            st, _, b = self.req("POST", base + "/discovery/runs", {"window": "soon"})
            self.assertEqual(st, 400, b)
            st, _, b = self.req("POST", base + "/discovery/runs", {"probes": "mdns"})
            self.assertEqual(st, 400, b)
            st, _, b = self.req("POST", base + "/discovery/runs", {"probes": ["nope"]})
            self.assertEqual(st, 400, b)
            st, _, b = call(self.app, "POST", base + "/discovery/runs", "{}", {"Content-Type": "text/plain"})
            self.assertEqual(st, 403, "CSRF guard applies")
            st, _, b = self.req("GET", "/api/v2/projects/nope/discovery/runs")
            self.assertEqual(st, 404)

    def test_settings_and_test_endpoints(self):
        with temp_data_dir(**FAST) as data:
            pdir = install_campus(data, "campus")
            base = "/api/v2/projects/campus"
            st, _, b = self.req("GET", base + "/discovery/settings")
            self.assertEqual(st, 200, b)
            s = jbody(b)
            self.assertEqual(s["settings"]["window"], 60)
            self.assertEqual(s["limits"], {"min_window": 10, "max_window": 300})
            st, _, b = self.req("PUT", base + "/discovery/settings",
                                {"window": 120, "probes": {"unifi": {"url": "https://10.0.0.1", "api_key": "k-abc-12345", "enabled": True}, "lldp": {"enabled": False}}})
            self.assertEqual(st, 200, b)
            s = jbody(b)["settings"]
            self.assertEqual((s["window"], s["probes"]["unifi"]["url"], s["probes"]["unifi"]["api_key_set"], s["probes"]["lldp"]["enabled"]), (120, "https://10.0.0.1", True, False))
            self.assertNotIn("k-abc-12345", b.decode())
            project = (pdir / "project.json").read_text(encoding="utf-8")
            self.assertNotIn("k-abc-12345", project)
            self.assertIn('"discovery"', project)
            st, _, b = self.req("GET", base + "/history")
            self.assertNotIn("k-abc-12345", b.decode())
            for p in (pdir / "history").rglob("*"):
                if p.is_file():
                    self.assertNotIn("k-abc-12345", p.read_text(encoding="utf-8", errors="replace"), p)
            st, _, b = self.req("PUT", base + "/discovery/settings", {"probes": {"unifi": {"bogus": 1}}})
            self.assertEqual(st, 400, b)
            # a run with lldp disabled only runs three probes
            run = self.run_and_wait(base, {})
            self.assertEqual(run["probes"], ["unifi", "mdns", "arp"])
            self.assertEqual(run["window"], 120, "the stored window is used when the request has none")
            # test endpoint
            st, _, b = self.req("POST", base + "/discovery/test", {"probe": "unifi"})
            self.assertEqual(st, 200, b)
            self.assertTrue(jbody(b)["result"]["ok"])
            self.assertTrue(jbody(b)["result"].get("fixture"))
            st, _, b = self.req("POST", base + "/discovery/test", {"probe": "nope"})
            self.assertEqual(st, 400, b)
        with temp_data_dir() as data:  # no fixtures: the UniFi test needs a URL and must not leak the key
            install_campus(data, "campus")
            base = "/api/v2/projects/campus"
            st, _, b = self.req("POST", base + "/discovery/test", {"probe": "unifi", "settings": {"api_key": "k-abc-12345"}})
            self.assertEqual(st, 200, b)
            self.assertFalse(jbody(b)["result"]["ok"])
            self.assertIn("URL", jbody(b)["result"]["message"])


# --------------------------------------------------------------------------- passivity guard


class _SocketGuard:
    """Records every outbound socket operation and refuses it."""

    def __init__(self):
        self.connects = []
        self.sendto = []
        self.sends = []
        self.lookups = []
        self.lock = threading.Lock()

    def __enter__(self):
        g = self

        def connect(sock, addr, *a, **k):
            with g.lock:
                g.connects.append(addr)
            raise OSError("guard: outbound connect blocked")

        def create_connection(addr, *a, **k):
            with g.lock:
                g.connects.append(addr)
            raise OSError("guard: outbound connect blocked")

        def sendto(sock, data, *args):
            addr = args[-1] if args else None
            with g.lock:
                g.sendto.append(addr)
            return len(data)

        orig_send, orig_sendall = socket.socket.send, socket.socket.sendall

        def send(sock, data, *a, **k):
            if sock.family == getattr(socket, "AF_UNIX", -1):  # asyncio's self-pipe, not the network
                return orig_send(sock, data, *a, **k)
            with g.lock:
                g.sends.append(len(data))
            raise OSError("guard: send blocked")

        def sendall(sock, data, *a, **k):
            if sock.family == getattr(socket, "AF_UNIX", -1):
                return orig_sendall(sock, data, *a, **k)
            with g.lock:
                g.sends.append(len(data))
            raise OSError("guard: send blocked")

        def gethostbyaddr(ip):
            with g.lock:
                g.lookups.append(ip)
            raise socket.herror(1, "guard")

        self._patches = [
            mock.patch.object(socket.socket, "connect", connect),
            mock.patch.object(socket.socket, "connect_ex", connect),
            mock.patch.object(socket.socket, "sendto", sendto),
            mock.patch.object(socket.socket, "send", send),
            mock.patch.object(socket.socket, "sendall", sendall),
            mock.patch.object(socket, "create_connection", create_connection),
            mock.patch.object(socket, "gethostbyaddr", gethostbyaddr),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


class PassiveGuard(unittest.TestCase):
    """With no fixtures, the probes open no outbound connection except to the configured UniFi controller
    (and standard mDNS multicast); nothing is sent to a device (FR-DISC-02)."""

    def setUp(self):
        self.probes = requires("discovery.probes")
        self.by_id = {m.INFO.id: m for m in self.probes.all_probes()}

    def test_unifi_talks_only_to_the_configured_controller(self):
        unifi = self.by_id["unifi"]
        with temp_env(FATHOM_DISCOVERY_FIXTURES=None), _SocketGuard() as g:
            with self.assertRaises(unifi.UnifiError):
                unifi.collect({"url": "https://unifi.test.invalid:8443", "api_key": "k"})
            res = unifi.test({"url": "https://unifi.test.invalid:8443", "username": "u", "password": "p"})
        self.assertFalse(res["ok"])
        hosts = {a[0] for a in g.connects if isinstance(a, tuple)}
        self.assertEqual(hosts, {"unifi.test.invalid"}, g.connects)
        self.assertEqual(g.sendto, [])
        with temp_env(FATHOM_DISCOVERY_FIXTURES=None), _SocketGuard() as g:
            with self.assertRaises(unifi.UnifiError):
                unifi.collect({})  # no URL configured: nothing at all happens
        self.assertEqual((g.connects, g.sendto, g.lookups), ([], [], []))

    def test_arp_only_reads_the_host_table(self):
        arp = self.by_id["arp"]
        with temp_env(FATHOM_DISCOVERY_FIXTURES=None), _SocketGuard() as g:
            raw = arp.collect({"reverse_dns": False})
        self.assertEqual((g.connects, g.sendto, g.sends, g.lookups), ([], [], [], []))
        self.assertIn(raw["format"], ("proc", "ip-neigh", "arp-an", "windows", "none"))
        with temp_env(FATHOM_DISCOVERY_FIXTURES=None), _SocketGuard() as g:
            raw = arp.collect({})
        self.assertEqual((g.connects, g.sendto, g.sends), ([], [], []), "reverse DNS goes through the system resolver only")
        table_ips = {r["ip"] for r in arp.parse_table(raw["format"], raw["text"])}
        self.assertTrue(set(g.lookups) <= table_ips, "names are only looked up for addresses in the table")

    def test_lldp_listener_sends_nothing(self):
        lldp = self.by_id["lldp"]
        job = requires("jobs:Job")("t", "k", 10)
        job.request_cancel("test")  # the listen loop exits at once when it can open a socket
        with temp_env(FATHOM_DISCOVERY_FIXTURES=None), _SocketGuard() as g:
            raw = lldp.collect({}, job, window=5)
        self.assertEqual((g.connects, g.sendto, g.sends, g.lookups), ([], [], [], []))
        self.assertIn("frames", raw)
        if raw.get("status") == "skipped":
            self.assertTrue(raw["notes"], "no CAP_NET_RAW is reported, not hidden")

    def test_mdns_sends_only_multicast_queries(self):
        mdns = self.by_id["mdns"]
        ok, _ = mdns.available()
        if not ok:
            self.skipTest("zeroconf not installed (fathom[discovery] extra)")
        job = requires("jobs:Job")("t", "k", 30)
        with temp_env(FATHOM_DISCOVERY_FIXTURES=None), _SocketGuard() as g:
            threading.Timer(1.5, job.request_cancel, args=("test",)).start()
            raw = mdns.collect({"discover_types": False}, job, window=5)
        self.assertIn("records", raw)
        self.assertEqual(g.connects, [], "mDNS never opens a connection")
        self.assertEqual(g.sends, [])
        targets = {a for a in g.sendto if isinstance(a, tuple)}
        bad = {a for a in targets if not (a[0] in ("224.0.0.251", "ff02::fb") and a[1] == 5353)}
        self.assertEqual(bad, set(), "only standard multicast queries: %r" % (g.sendto,))

    def test_no_background_activity_from_importing_the_package(self):
        before = {t.name for t in threading.enumerate()}
        import fathom.discovery  # noqa: F401
        import fathom.server  # noqa: F401
        from fathom import plugins

        plugins.get_importer("discovery")
        after = {t.name for t in threading.enumerate()}
        self.assertEqual(after - before, set(), "no listener or scheduler thread starts on import")
        src = Path(fathom.discovery.__file__).parent
        text = "\n".join(p.read_text(encoding="utf-8") for p in src.rglob("*.py"))
        self.assertNotIn("sched.scheduler", text)
        self.assertNotIn("while True", text.replace("while True:\n                job.check()", ""), "no unbounded loops in the discovery package")


# --------------------------------------------------------------------------- importer registration


class ImporterRegistration(unittest.TestCase):
    def test_discovery_importer_is_registered(self):
        plugins = requires("plugins")
        imp = plugins.get_importer("discovery")
        self.assertIsNotNone(imp)
        self.assertEqual((imp.mode, imp.folder, imp.accepts), ("discovery", True, ()))
        self.assertEqual(imp.detect(Path("/nonexistent")), 0.0)

    def test_overlay_contribution_from_a_run_dir(self):
        disc = requires("discovery")
        with temp_data_dir(**FAST) as data:
            pdir = install_campus(data, "campus")
            from fathom.project import read_doc

            doc, _ = read_doc(pdir)
            run = disc.start_run(pdir, doc, by="test", window=10)
            t0 = time.time()
            while disc.get_run(pdir, run["id"])["active"] and time.time() - t0 < 30:
                time.sleep(0.1)
            rdir = disc.run_dir(pdir, run["id"])
            imp = requires("plugins").get_importer("discovery")
            self.assertGreater(imp.detect(rdir), 0.9)
            snap = imp.parse(rdir)
            self.assertEqual(snap.summary()["counts"]["entities"], 18)
            doc, _ = read_doc(pdir)
            ov = imp.contribute(snap, doc, {"import": {"id": "imp-test"}, "room": "", "device": ""})
            self.assertTrue(ov["devices"])
            self.assertTrue(all(d.get("source") == "discovery" for d in ov["devices"]))
            self.assertTrue(all(r.get("kind") == "network" for r in ov["routes"]))
            self.assertIn("rio-sl", ov["interfaces"])


if __name__ == "__main__":
    unittest.main()
