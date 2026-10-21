"""Unit tests for Fathom (stdlib unittest; pytest also picks them up)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from fathom.layout import compute_layout  # noqa: E402
from fathom.merge import apply_imports  # noqa: E402
from fathom.model import Link, Node, Project, project_from_dict, validate  # noqa: E402
from fathom.parsers import detect_kind, parse_dante, parse_waves, parse_yamaha  # noqa: E402
from fathom.parsers.yamaha import categorize, parse_channel_label, parse_port  # noqa: E402
from fathom.patch import build_patch_sheet  # noqa: E402
from fathom.project import SAMPLES_DIR, blank_project_dict, load_project  # noqa: E402
from fathom.render_html import render_html  # noqa: E402
from fathom.trace import find_paths  # noqa: E402

SAMPLE = SAMPLES_DIR / "rrc-littleton"


class YamahaNotation(unittest.TestCase):
    def test_ports_normal_short_and_synonyms(self):
        self.assertEqual(parse_port("DANTE 12").text, "DANTE 12")
        self.assertEqual(parse_port("DNT 12").text, "DANTE 12")
        self.assertEqual(parse_port("Dante 12").text, "DANTE 12")
        self.assertEqual(parse_port("AD 3").text, "OMNI 3")
        self.assertEqual(parse_port("SL2 7").text, "SLOT2 7")
        self.assertEqual(parse_port("MT 4").text, "MATRIX 4")
        self.assertEqual(parse_port("STL").bus, "STEREO")
        self.assertEqual(parse_port("Insert1 Input Channel 5").bus, "INS")
        self.assertEqual(parse_port("NONE").bus, "NONE")
        self.assertIsNone(parse_port("Kick"))

    def test_channel_labels(self):
        self.assertEqual(parse_channel_label("CH 7"), ("in", 7, "CH 7"))
        self.assertEqual(parse_channel_label("ch7"), ("in", 7, "CH 7"))
        self.assertEqual(parse_channel_label("ST IN 2 L")[0], "stin")
        self.assertEqual(parse_channel_label("MIX 16"), ("mix", 16, "MIX 16"))
        self.assertIsNone(parse_channel_label("Kick In"))

    def test_categories(self):
        self.assertEqual(categorize("Kick In", "Kick"), "Drums")
        self.assertEqual(categorize("Drum TB", "Dynamic"), "Ambience & talkback")
        self.assertEqual(categorize("Lead Vox", "Wireless"), "Wireless mics")
        self.assertEqual(categorize("Trax 1", "Media2"), "Playback")
        self.assertEqual(categorize("Mystery", "Blank"), "Other inputs")


class Parsers(unittest.TestCase):
    def test_yamaha_folder(self):
        data = parse_yamaha(SAMPLE / "exports" / "cl5")
        self.assertEqual(data.model, "CL5")
        self.assertGreaterEqual(len(data.named_inputs), 50)
        self.assertEqual(data.dante_input_map()[1].name, "Kick In")
        self.assertIn("DANTE", data.patch_counts())
        self.assertTrue(data.dante_output_map()[1].source.bus == "STEREO")

    def test_dante_preset(self):
        net = parse_dante(SAMPLE / "exports" / "dante" / "rrc-littleton-preset.xml")
        self.assertEqual(len(net.devices), 33)
        flows = net.flows()
        self.assertEqual(len(flows[("1073OPX-1", "FOH-CL5")]), 8)
        self.assertEqual(net.devices["FOH-CL5"].model_text, "Yamaha CL5")

    def test_dante_receive_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "MON-QL5.txt"
            p.write_text("Channel\tConnected To\tSignal\n01\tEG1 L@Rio3224\t-\n02\tEG1 R@Rio3224\t-\n", encoding="utf-8")
            net = parse_dante(p)
            self.assertEqual(len(net.subscriptions()), 2)
            self.assertEqual(net.subscriptions()[0].tx_device, "Rio3224")

    def test_waves_csv_and_xml(self):
        csv_sess = parse_waves(SAMPLE / "exports" / "waves" / "superrack-racks.csv")
        xml_sess = parse_waves(SAMPLE / "exports" / "waves" / "superrack-session.xml")
        self.assertEqual(len(csv_sess.racks), 18)
        self.assertEqual(len(xml_sess.racks), 18)
        self.assertEqual(xml_sess.racks[0].plugins[0], "C6")
        self.assertIn("SuperRack", xml_sess.app)

    def test_detect(self):
        self.assertEqual(detect_kind(SAMPLE / "exports" / "cl5"), "yamaha")
        self.assertEqual(detect_kind(SAMPLE / "exports" / "dante" / "rrc-littleton-preset.xml"), "dante")
        self.assertEqual(detect_kind(SAMPLE / "exports" / "waves" / "superrack-racks.csv"), "waves")


class ModelAndLayout(unittest.TestCase):
    def test_validate_catches_bad_refs(self):
        p = Project()
        p.nodes.append(Node(id="a", label="A", kind="nope", group="Z"))
        p.links.append(Link(source="a", target="b", medium="laser"))
        problems = validate(p)
        self.assertTrue(any("unknown kind" in x for x in problems))
        self.assertTrue(any("unknown node 'b'" in x for x in problems))
        self.assertTrue(any("unknown medium" in x for x in problems))

    def test_sample_builds_without_overlap(self):
        project, pdir = load_project(str(SAMPLE))
        apply_imports(project, pdir)
        self.assertFalse([n for n in project.notes if n.startswith("validation:")])
        layout = compute_layout(project)
        cards = list(layout.cards.values())
        for i, a in enumerate(cards):
            for b in cards[i + 1 :]:
                overlap = a.box.x < b.box.right and b.box.x < a.box.right and a.box.y < b.box.bottom and b.box.y < a.box.bottom
                self.assertFalse(overlap, f"{a.node.id} overlaps {b.node.id}")
        self.assertEqual(len(layout.links), len(project.links))
        html = render_html(project, layout)
        self.assertIn('data-id="foh"', html)
        self.assertIn("Patch sheet", html)

    def test_ref_card_is_same_device(self):
        project, pdir = load_project(str(SAMPLE))
        apply_imports(project, pdir)
        self.assertEqual(project.canon_id("rio3224-out"), "rio3224")
        sheets = {s.node.id: s for s in build_patch_sheet(project)}
        self.assertNotIn("rio3224-out", sheets)
        self.assertTrue(any(r.peer_id == "la7-1" for r in sheets["rio3224"].outputs))
        self.assertTrue(find_paths(project, "drums", "mains"))

    def test_blank_project_with_imports_builds_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = blank_project_dict("Test")
            d["imports"] = [
                {"kind": "yamaha", "path": str(SAMPLE / "exports" / "cl5")},
                {"kind": "dante", "path": str(SAMPLE / "exports" / "dante" / "rrc-littleton-preset.xml")},
            ]
            project = project_from_dict(d)
            apply_imports(project, Path(tmp))
            labels = {n.label for n in project.nodes}
            self.assertIn("Drums", labels)
            self.assertIn("FOH-CL5", labels)
            drums = next(n for n in project.nodes if n.label == "Drums")
            self.assertEqual(drums.count, 12)
            consoles = [n for n in project.nodes if n.kind == "console"]
            self.assertTrue(all(project.group(n.group).side == "right" for n in consoles))
            self.assertTrue(find_paths(project, drums.id, next(n for n in project.nodes if n.label == "Rio3224").id))


if __name__ == "__main__":
    unittest.main()
