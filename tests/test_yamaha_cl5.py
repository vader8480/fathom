"""Yamaha CL5 V4.1 console export (real SAVE/LOAD CSV folder, 9 section files).

Fixtures: ``tests/fixtures/imports/yamaha-cl5/*.csv`` — kept byte-for-byte
(CRLF, four header lines, trailing commas). Expected values come from the
export's routing guide (resolved tables, Section 6) and its anomaly list
(Section 5).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

try:
    from _helpers import call, fixture_path, get_app, install_rrc, jbody, requires, temp_data_dir, upload
except ImportError:  # pragma: no cover
    from tests._helpers import call, fixture_path, get_app, install_rrc, jbody, requires, temp_data_dir, upload

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

CL5 = fixture_path("imports", "yamaha-cl5")
FILES = ("DCAName.csv", "InName.csv", "InPatch.csv", "MixName.csv", "MtxName.csv", "OutPatch.csv", "PortRackPatch.csv", "StMonoName.csv", "StName.csv")


def _parse():
    from fathom.parsers import parse_yamaha

    return parse_yamaha(CL5)


class Fixture(unittest.TestCase):
    def test_files_are_the_raw_console_export(self):
        for f in FILES:
            raw = (CL5 / f).read_bytes()
            self.assertTrue(raw.startswith(b"[Information]\r\nCL5\r\nV4.1\r\n["), "%s keeps the 4 header lines + CRLF" % f)
            data_line = raw.split(b"\r\n")[5]
            self.assertTrue(data_line.endswith(b","), "%s rows end with a trailing comma" % f)


class Detection(unittest.TestCase):
    def test_folder_and_files_detect_as_yamaha(self):
        from fathom.parsers import detect_kind

        plugins = requires("plugins")
        self.assertEqual(detect_kind(CL5), "yamaha", "folder of [Section] CSVs is a console export, not Waves (PortRackPatch mentions 'rack')")
        self.assertEqual(plugins.detect(CL5), "yamaha")
        for f in FILES:
            self.assertEqual(detect_kind(CL5 / f), "yamaha", f)


class ParsePorts(unittest.TestCase):
    def test_new_notation(self):
        from fathom.parsers.yamaha import parse_channel_label, parse_port

        p = parse_port("INS2 CH 6")
        self.assertEqual((p.bus, p.insert, p.channel, p.text), ("INS", 2, "CH 6", "INS2 CH 6"))
        p = parse_port("INS MATRIX 7")
        self.assertEqual((p.bus, p.insert, p.channel, p.text), ("INS", 1, "MATRIX 7", "INS MATRIX 7"))
        p = parse_port("INS STEREO L")
        self.assertEqual((p.insert, p.channel, p.text), (1, "ST L", "INS ST L"))
        self.assertEqual(parse_port("INS MONO").channel, "MONO")
        self.assertEqual(parse_port("Insert1 Input Channel 5").text, "INS CH 5")
        p = parse_port("DIR CH 43")
        self.assertEqual((p.bus, p.number, p.channel, p.text), ("DIRECT", 43, "CH 43", "DIR CH 43"))
        self.assertEqual(parse_port("REC 2").text, "REC 2")
        self.assertEqual(parse_port("PRFX 6A").text, "PRFX 6A")
        self.assertEqual(parse_port("GEQ 1B").text, "GEQ 1B")
        self.assertTrue(parse_port("FX 4A").is_rack)
        self.assertTrue(parse_port("SLOT1 9").is_physical_output)
        self.assertEqual(parse_channel_label("STEREO INPUT 4L"), ("stin", 4, "ST IN 4 L"))
        self.assertEqual(parse_channel_label("STEREO INPUT 8R"), ("stin", 8, "ST IN 8 R"))
        self.assertIsNone(parse_channel_label("INS CH 1"))


class ResolvedTables(unittest.TestCase):
    """Spot checks against Section 6 of the routing guide."""

    @classmethod
    def setUpClass(cls):
        cls.data = _parse()

    def ch(self, label):
        return self.data.channels[label]

    def test_header_and_roles(self):
        d = self.data
        self.assertEqual((d.model, d.firmware), ("CL5", "V4.1"))
        self.assertEqual(sorted(d.sections), sorted(f[:-4] for f in FILES))
        roles = d.files_by_role
        self.assertEqual(sorted(roles["names"]), ["DCAName.csv", "InName.csv", "MixName.csv", "MtxName.csv", "StMonoName.csv", "StName.csv"])
        self.assertEqual(roles["input_patch"], ["InPatch.csv"])
        self.assertEqual(roles["insert_patch"], ["OutPatch.csv"], "OutPatch only holds bus insert returns")
        self.assertEqual(roles["output_patch"], ["PortRackPatch.csv"], "bus → port patching comes from PortRackPatch")
        self.assertNotIn("unknown", roles)
        self.assertEqual(d.notes, [], "anomalies are warnings, not notes/errors")

    # 6.1 input channels
    def test_input_channels(self):
        d = self.data
        self.assertEqual(len(d.mono_inputs), 72)
        self.assertEqual([c.label for c in d.mono_inputs][:3], ["CH 1", "CH 2", "CH 3"], "_NN keys normalise to CH n")
        c = self.ch("CH 17")
        self.assertEqual((c.name, c.color, c.icon, c.patch.text), ("Kick In", "Yellow", "Kick", "DANTE 1"))
        self.assertEqual(c.insert1.text, "PRFX 6A")
        self.assertIsNone(c.insert2)
        self.assertEqual(c.direct_outs, [])
        self.assertEqual(self.ch("CH 2").name, "Vox1_M", "trailing space trimmed")
        c = self.ch("CH 6")
        self.assertEqual((c.name, c.patch.text, c.insert1, c.insert2.text), ("Headset", "DANTE 31", None, "GEQ 5A"))
        c = self.ch("CH 25")
        self.assertEqual((c.name, c.patch.text, c.insert1.text, [p.text for p in c.direct_outs]), ("Choir L", "DANTE 19", "GEQ 1A", ["SLOT1 14"]))
        c = self.ch("CH 43")
        self.assertEqual((c.name, c.icon, c.patch.text, [p.text for p in c.direct_outs]), ("Video L", "PC", "OMNI 1", ["DANTE 43"]))
        c = self.ch("CH 49")
        self.assertEqual((c.name, c.patch.text, [p.text for p in c.direct_outs]), ("LEAD_R", "SLOT1 1", ["DANTE 49"]))
        self.assertEqual([p.text for p in self.ch("CH 67").direct_outs], ["SLOT1 9"])
        self.assertEqual([p.text for p in self.ch("CH 10").direct_outs], [], "Key L is not sent anywhere")
        c = self.ch("CH 66")
        self.assertEqual((c.name, c.color, c.icon, c.patch.text), ("", "Orange", "E.Guitar", "NONE"))
        self.assertEqual((self.ch("CH 57").name, self.ch("CH 57").patch.text), ("Aud IL", "NONE"))
        self.assertEqual((self.ch("CH 28").patch.text, self.ch("CH 46").patch.text), ("DANTE 13", "DANTE 13"))
        self.assertEqual(sum(len(c.direct_outs) for c in d.inputs), 28)

    # 6.2 stereo inputs (FX returns)
    def test_stereo_inputs_pair_up(self):
        d = self.data
        st = d.stereo_inputs
        self.assertEqual(len(st), 16)
        self.assertEqual([c.label for c in st][:4], ["ST IN 1 L", "ST IN 1 R", "ST IN 2 L", "ST IN 2 R"])
        self.assertEqual((self.ch("ST IN 4 L").name, self.ch("ST IN 4 L").patch.text), ("DrumVerb", "FX 4A"))
        self.assertEqual((self.ch("ST IN 4 R").name, self.ch("ST IN 4 R").patch.text), ("DrumVerb", "FX 4B"))
        self.assertEqual((self.ch("ST IN 6 L").name, self.ch("ST IN 6 R").name), ("S_DELAY", "S_DELY"), "_11/_12 are ST IN 6 L/R, typo kept")
        self.assertEqual((self.ch("ST IN 8 L").patch.text, self.ch("ST IN 8 R").patch.text), ("FX 8A", "FX 8B"))

    # 6.3 mix buses
    def test_mix_buses(self):
        b = self.ch("MIX 9")
        self.assertEqual((b.name, [p.text for p in b.outputs]), ("9 IEM", ["DANTE 10"]), "bus numbers and Dante numbers are not 1:1")
        self.assertEqual([p.text for p in self.ch("MIX 12").outputs], ["DANTE 9"])
        self.assertEqual([p.text for p in self.ch("MIX 15").outputs], ["DANTE 11"])
        self.assertEqual(self.ch("MIX 3").name, "PAT GTR")
        b = self.ch("MIX 10")
        self.assertEqual((b.name, b.icon, b.insert1.text, b.feeds_text()), ("BGV I", "Wedge", "GEQ 7A", "DANTE 28, GEQ 7A (via insert send)"))
        b = self.ch("MIX 17")
        self.assertEqual((b.name, b.outputs, [p.text for p in b.rack_feeds]), ("HALLfx", [], ["FX 1A", "FX 1B"]))
        self.assertEqual([p.text for p in self.ch("MIX 18").rack_feeds], ["FX 2A"], "FX 2B input is NONE (mono-in)")
        b = self.ch("MIX 20")
        self.assertEqual(b.feeds_text(), "DANTE 20, FX 4B, FX 4A (via insert send)")
        self.assertIsNone(b.insert1)
        self.assertEqual(self.ch("MIX 22").feeds_text(), "DANTE 22, FX 6A, FX 6B, FX 8A, FX 8B")
        self.assertEqual((self.ch("MIX 24").name, self.ch("MIX 24").feeds_text()), ("SUBS", "DANTE 27"))

    # 6.4 matrix and main buses
    def test_matrix_and_mains(self):
        b = self.ch("MATRIX 7")
        self.assertEqual((b.name, b.insert1.text, [p.text for p in b.outputs]), ("Stream L", "PRFX 1A", ["DANTE 63", "OMNI 7"]))
        self.assertEqual(b.feeds_text(), "DANTE 63, OMNI 7, PRFX 1A (via insert send)")
        b = self.ch("MATRIX 8")
        self.assertEqual((b.name, b.insert1.text, [p.text for p in b.outputs]), ("Stream R", "PRFX 1B", ["DANTE 64", "OMNI 8"]))
        b = self.ch("MATRIX 5")
        self.assertEqual((b.name, b.has_output), ("", False), "Matrix 5: no name, not patched")
        b = self.ch("ST L")
        self.assertEqual((b.name, b.insert1.text, [p.text for p in b.outputs]), ("ST L", "PRFX 2A", ["DANTE 25", "REC 1"]))
        b = self.ch("ST R")
        self.assertEqual((b.insert1.text, [p.text for p in b.outputs]), ("PRFX 2B", ["DANTE 26", "REC 2"]))
        self.assertFalse(self.ch("MONO").has_output)
        self.assertEqual(len(self.data.buses), 35)

    # 6.5 DCA names only
    def test_dca_names_only(self):
        d = self.data
        self.assertEqual(d.dca_names(), {
            "DCA 1": "CHOIR", "DCA 2": "VOX", "DCA 3": "BAND", "DCA 4": "DRUM", "DCA 5": "LOOP", "DCA 6": "IPAD", "DCA 7": "Video", "DCA 8": "VFX",
            "DCA 9": "Choir", "DCA 10": "DCA10", "DCA 11": "DCA11", "DCA 12": "DCA12", "DCA 13": "DCA13", "DCA 14": "DCA14", "DCA 15": "DCA15", "DCA 16": "DCA16",
        })
        for dca in d.dcas:
            self.assertIsNone(dca.patch)
            self.assertFalse(dca.outputs or dca.insert_returns, "no DCA membership is invented")
        self.assertNotIn("DCA 1", [c.label for c in d.inputs] + [b.label for b in d.buses])

    # 6.6 rack I/O
    def test_rack_loops(self):
        d = self.data
        rows = {r["rack"]: r for r in d.rack_table()}
        self.assertEqual(len(rows), 36)
        closed = [r for r in rows.values() if r["status"].startswith("OK")]
        self.assertEqual(len(closed), 20)
        self.assertEqual(sum(1 for r in rows.values() if r["status"].startswith("OPEN")), 0)
        self.assertEqual(rows["PRFX 6A"], {"rack": "PRFX 6A", "fed_by": "INS CH 17", "returns_to": "INS CH 17", "status": "OK closed insert loop"})
        self.assertEqual(rows["GEQ 5A"]["fed_by"], "INS2 CH 6")
        self.assertEqual(rows["GEQ 5A"]["returns_to"], "INS2 CH 6")
        self.assertEqual((rows["PRFX 1A"]["fed_by"], rows["PRFX 2B"]["fed_by"]), ("INS MATRIX 7", "INS ST R"))
        self.assertEqual((rows["FX 1A"]["fed_by"], rows["FX 1A"]["returns_to"], rows["FX 1A"]["status"]), ("MIX 17", "ST IN 1 L", "FX send/return"))
        self.assertEqual((rows["FX 2B"]["fed_by"], rows["FX 2B"]["returns_to"]), ("NONE", "ST IN 2 R"))
        self.assertEqual(rows["FX 4A"]["fed_by"], "INS MIX 20")
        self.assertIn("insert", rows["FX 4A"]["status"])
        self.assertEqual((rows["FX 8A"]["fed_by"], rows["FX 8B"]["fed_by"]), ("MIX 22", "MIX 22"), "Echo is fed by Mix 22, not its own bus")
        self.assertNotIn("PRFX 7A", rows, "PRFX 7 unused")
        self.assertEqual(len(d.rack_patches), 34)

    # 6.7 output ports and Rule D
    def test_output_ports_from_portrackpatch(self):
        d = self.data
        om = d.output_port_map()
        self.assertEqual(len(om), 62)
        self.assertTrue(all(op.port.is_physical_output for op in d.output_patches), "racks are not output ports")
        self.assertEqual((om["DANTE 10"].source.text, d.source_name(om["DANTE 10"].source)), ("MIX 9", "9 IEM"))
        self.assertEqual((om["DANTE 9"].source.text, d.source_name(om["DANTE 9"].source)), ("MIX 12", "Choir"))
        self.assertEqual((om["DANTE 25"].source.text, d.source_name(om["DANTE 25"].source)), ("STEREO L", "ST L"))
        self.assertEqual((om["REC 2"].source.text, om["OMNI 8"].source.text), ("STEREO R", "MATRIX 8"))
        self.assertEqual((om["SLOT1 9"].source.text, d.source_name(om["SLOT1 9"].source)), ("DIR CH 67", "WD"))
        self.assertEqual((om["DANTE 47"].source.text, d.source_name(om["DANTE 47"].source)), ("DIR CH 47", "iPad"))
        self.assertEqual((om["DANTE 63"].source.text, om["DANTE 64"].source.text), ("MATRIX 7", "MATRIX 8"))
        for port in ("DANTE 13", "DANTE 33", "OMNI 1", "SLOT2 1", "SLOT1 17"):
            self.assertNotIn(port, om, "%s is NONE in PortRackPatch" % port)
        self.assertEqual([op.port.text for op in d.output_patches if op.source and op.source.bus == "INS"], [],
                         "insert returns from OutPatch never become output ports")
        # Rule D: Dante in n and Dante out n are different namespaces
        self.assertEqual(d.dante_input_map()[1].name, "Kick In")
        self.assertEqual(d.dante_output_map()[1].source.text, "MIX 1")
        self.assertEqual(d.dante_input_map()[47].name, "Aud OL")
        self.assertEqual(d.dante_output_map()[47].source.text, "DIR CH 47")
        self.assertNotIn(13, d.dante_output_map())
        self.assertEqual(d.dante_input_map()[13].label, "CH 28", "first channel wins; the duplicate is a warning")

    def test_summary_counts(self):
        s = self.data.summary()
        self.assertEqual((s["model"], s["firmware"]), ("CL5", "V4.1"))
        self.assertEqual((s["mono_inputs"], s["stereo_inputs"], s["inputs"]), (72, 16, 88))
        self.assertEqual(s["patch_by_bus"], {"DANTE": 54, "OMNI": 4, "SLOT1": 8, "FX": 16})
        self.assertEqual((s["buses"], s["buses_patched"], s["dcas"]), (35, 33, 16))
        self.assertEqual((s["output_patches"], s["rack_patches"], s["direct_outs"]), (62, 34, 28))
        self.assertEqual((s["insert_loops_closed"], s["insert_loops_open"], s["fx_returns"]), (20, 0, 16))
        self.assertEqual(s["notes"], [])
        self.assertGreaterEqual(len(s["warnings"]), 8)


class Anomalies(unittest.TestCase):
    """Section 5 of the guide surfaces as warnings (never errors, never notes)."""

    @classmethod
    def setUpClass(cls):
        cls.warnings = _parse().warnings

    def has(self, *needles):
        hits = [w for w in self.warnings if all(n in w for n in needles)]
        self.assertTrue(hits, "no warning mentioning %r in %r" % (needles, self.warnings))
        return hits[0]

    def test_duplicate_dante_13(self):
        self.has("DANTE 13", "CH 28", "CH 46")

    def test_fx_4a_open_insert_send(self):
        self.has("FX 4A", "MIX 20", "NONE")

    def test_fx_buses_also_leave_on_dante(self):
        for mix, dnt in (("MIX 19", "DANTE 19"), ("MIX 22", "DANTE 22")):
            self.has(mix, dnt)

    def test_unpatched_buses(self):
        w = self.has("not patched", "MATRIX 5", "MONO")
        self.assertNotIn("MIX 17", w, "a bus feeding only FX racks is patched")

    def test_named_without_source_and_placeholders(self):
        self.has("Aud IL", "Aud IR")
        self.has("default name", "ch28", "ch59")

    def test_duplicate_names(self):
        self.has("CH 14", "CH 15", "EG Lead")
        self.has("CH 47", "CH 48", "iPad")
        self.has("DCA 1", "DCA 9")
        self.assertFalse([w for w in self.warnings if "ST IN" in w and "same name" in w], "stereo halves may share a name")


class ApiFlow(unittest.TestCase):
    """Upload the 9 files through the real import route, inspect, and read the overlay."""

    def setUp(self):
        requires("plugins")
        self.app = get_app()
        self._ctx = temp_data_dir()
        self.data = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        install_rrc(self.data, "rrc")

    def test_upload_auto_detect_and_overlay(self):
        files = [(f, (CL5 / f).read_bytes(), "text/csv") for f in FILES]
        st, _, b = upload(self.app, "/api/v2/projects/rrc/imports?kind=auto&folder=cl5-live", files)
        self.assertEqual(st, 201, b[:400])
        j = jbody(b)
        self.assertEqual(j["import"]["kind"], "yamaha", "auto-detect picks the console importer")
        self.assertEqual(j["import"]["path"], "exports/yamaha/cl5-live")
        s = j["summary"]
        self.assertEqual((s["model"], s["mono_inputs"], s["stereo_inputs"], s["buses"], s["dcas"], s["output_patches"]), ("CL5", 72, 16, 35, 16, 62))
        self.assertTrue(any("DANTE 13" in w for w in s["warnings"]))
        st, _, b = upload(self.app, "/api/v2/projects/rrc/imports?kind=yamaha&folder=cl5-explicit", files)
        self.assertEqual(st, 201, b[:400])
        self.assertEqual(jbody(b)["summary"]["insert_loops_closed"], 20)

        st, _, b = call(self.app, "GET", "/api/v2/projects/rrc/imports/%s/inspect" % j["import"]["id"])
        self.assertEqual(st, 200, b[:300])
        self.assertEqual(jbody(b)["summary"]["direct_outs"], 28)

        st, _, b = call(self.app, "GET", "/api/v2/projects/rrc/overlay")
        self.assertEqual(st, 200, b[:300])
        ov = jbody(b)
        consoles = [v["console"] for v in ov["detail"].values() if isinstance(v, dict) and v.get("console", {}).get("firmware") == "V4.1"]
        self.assertTrue(consoles, "the CL5 export attaches to a console card and lands in overlay detail")
        c = consoles[0]
        kick = next(r for r in c["channels"] if r["channel"] == "CH 17")
        self.assertEqual((kick["name"], kick["patch"], kick["insert1"]), ("Kick In", "DANTE 1", "PRFX 6A"))
        st4 = next(r for r in c["channels"] if r["channel"] == "ST IN 4 L")
        self.assertEqual(st4["patch"], "FX 4A")
        mix9 = next(r for r in c["buses"] if r["bus"] == "MIX 9")
        self.assertEqual((mix9["name"], mix9["outputs"]), ("9 IEM", "DANTE 10"))
        mtx7 = next(r for r in c["buses"] if r["bus"] == "MATRIX 7")
        self.assertEqual((mtx7["insert1"], mtx7["feeds"]), ("PRFX 1A", "DANTE 63, OMNI 7, PRFX 1A (via insert send)"))
        self.assertEqual(len(c["racks"]), 36)
        self.assertEqual([d["name"] for d in c["dcas"]][:3], ["CHOIR", "VOX", "BAND"])
        self.assertTrue(any("DANTE 13" in w for w in c["warnings"]))
        self.assertTrue(any(n.startswith("yamaha: warning:") for n in ov["notes"]), "anomalies reach the overlay notes as warnings")
        self.assertFalse(any("not recognised" in n for n in ov["notes"]))
        outs = [r for r in ov["patch_rows"] if r.get("source") == "console" and r.get("dir") == "out"]
        self.assertTrue(any(r["port"].startswith("DANTE 10 ← MIX 9") for r in outs))
        self.assertTrue(any(r["port"].startswith("SLOT1 9 ← DIR CH 67") for r in outs))
        ins = [r for r in ov["patch_rows"] if r.get("source") == "console" and r.get("dir") == "in"]
        self.assertFalse(any("FX " in r["port"] for r in ins), "FX returns are internal, not patch-sheet inputs")


if __name__ == "__main__":
    unittest.main()
