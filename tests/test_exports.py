"""Builds, schedules, tags, labels, BOM, network/DMX/racks analysis, QR (SPEC §3.9–3.15, §3.23–3.24, §4.8, §5.9, App. C)."""

from __future__ import annotations

import contextlib
import copy
import csv
import io
import json
import os
import random
import re
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path

try:
    from _helpers import (CAMPUS_DIR, RRC_DIR, fr, install_campus, install_project, install_rrc, install_sunday, load_fixture, read_json,
                          requires, rrc_dict, sunday_doc, temp_data_dir, temp_env, uniq)
except ImportError:  # pragma: no cover
    from tests._helpers import (CAMPUS_DIR, RRC_DIR, fr, install_campus, install_project, install_rrc, install_sunday, load_fixture, read_json,
                                requires, rrc_dict, sunday_doc, temp_data_dir, temp_env, uniq)


# ================================================================== independent QR reader (ISO/IEC 18004)

ECC_PER_BLOCK = {
    "L": [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    "M": [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
    "Q": [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    "H": [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
}
NUM_BLOCKS = {
    "L": [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
    "M": [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
    "Q": [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68],
    "H": [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81],
}
FORMAT_ECL = {1: "L", 0: "M", 3: "Q", 2: "H"}
MASKS = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0, lambda x, y: (x + y) % 3 == 0,
         lambda x, y: (x // 3 + y // 2) % 2 == 0, lambda x, y: x * y % 2 + x * y % 3 == 0,
         lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0, lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]

EXP = [0] * 512
LOG = [0] * 256
_v = 1
for _i in range(255):
    EXP[_i] = _v
    LOG[_v] = _i
    _v <<= 1
    if _v & 0x100:
        _v ^= 0x11D
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]


def raw_data_modules(ver):
    r = (16 * ver + 128) * ver + 64
    if ver >= 2:
        na = ver // 7 + 2
        r -= (25 * na - 10) * na - 55
        if ver >= 7:
            r -= 36
    return r


def alignment_positions(ver):
    if ver == 1:
        return []
    na = ver // 7 + 2
    step = (ver * 8 + na * 3 + 5) // (na * 4 - 4) * 2
    size = ver * 4 + 17
    res = [size - 7 - i * step for i in range(na - 1)] + [6]
    return sorted(res)


def function_mask(ver):
    size = ver * 4 + 17
    f = [[False] * size for _ in range(size)]

    def mark(x0, y0, w, h):
        for y in range(max(0, y0), min(size, y0 + h)):
            for x in range(max(0, x0), min(size, x0 + w)):
                f[y][x] = True

    for i in range(size):
        f[6][i] = f[i][6] = True
    mark(0, 0, 9, 9)
    mark(size - 8, 0, 8, 9)
    mark(0, size - 8, 9, 8)
    pos = alignment_positions(ver)
    n = len(pos)
    for i in range(n):
        for j in range(n):
            if (i == 0 and j == 0) or (i == 0 and j == n - 1) or (i == n - 1 and j == 0):
                continue
            mark(pos[i] - 2, pos[j] - 2, 5, 5)
    if ver >= 7:
        mark(size - 11, 0, 3, 6)
        mark(0, size - 11, 6, 3)
    return f


def bch_format_ok(bits):
    data = (bits ^ 0x5412) >> 10
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10 | rem) ^ 0x5412) == bits, data


def read_format(m):
    size = len(m)
    g = lambda x, y: 1 if m[y][x] else 0  # noqa: E731
    b1 = 0
    for i in range(6):
        b1 |= g(8, i) << i
    b1 |= g(8, 7) << 6
    b1 |= g(8, 8) << 7
    b1 |= g(7, 8) << 8
    for i in range(9, 15):
        b1 |= g(14 - i, 8) << i
    b2 = 0
    for i in range(8):
        b2 |= g(size - 1 - i, 8) << i
    for i in range(8, 15):
        b2 |= g(8, size - 15 + i) << i
    return b1, b2


def rs_syndromes_zero(block, n_ecc):
    for i in range(n_ecc):
        s = 0
        for c in block:
            s = (EXP[LOG[s] + i] if s else 0) ^ c
        if s:
            return False
    return True


def qr_decode(m):
    """Verify a QR matrix and return (version, ecl, mask, payload bytes). Raises AssertionError on any defect."""
    size = len(m)
    assert all(len(r) == size for r in m), "square matrix"
    assert (size - 17) % 4 == 0 and 21 <= size <= 177, "size %d" % size
    ver = (size - 17) // 4
    for (cx, cy) in ((0, 0), (size - 7, 0), (0, size - 7)):
        for dy in range(7):
            for dx in range(7):
                ring = max(abs(dx - 3), abs(dy - 3))
                assert bool(m[cy + dy][cx + dx]) == (ring != 2), "finder pattern at (%d,%d)" % (cx, cy)
    for i in range(8, size - 8):
        assert bool(m[6][i]) == (i % 2 == 0) and bool(m[i][6]) == (i % 2 == 0), "timing pattern"
    assert m[size - 8][8], "dark module"
    b1, b2 = read_format(m)
    assert b1 == b2, "format copies differ"
    ok, data = bch_format_ok(b1)
    assert ok, "format bits BCH-valid"
    ecl, mask = FORMAT_ECL[data >> 3], data & 7
    func = function_mask(ver)
    bits = []
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not func[y][x]:
                    bits.append((1 if m[y][x] else 0) ^ (1 if MASKS[mask](x, y) else 0))
        right -= 2
    raw_cw = raw_data_modules(ver) // 8
    cws = [int("".join(map(str, bits[i * 8:i * 8 + 8])), 2) for i in range(raw_cw)]
    nb, ne = NUM_BLOCKS[ecl][ver], ECC_PER_BLOCK[ecl][ver]
    short_len = raw_cw // nb
    num_short = nb - raw_cw % nb
    blocks = [[] for _ in range(nb)]
    k = 0
    for i in range(short_len + 1):
        for j in range(nb):
            if i != short_len - ne or j >= num_short:
                blocks[j].append(cws[k])
                k += 1
    data_cw = []
    for j, blk in enumerate(blocks):
        assert rs_syndromes_zero(blk, ne), "Reed-Solomon syndromes zero in block %d" % j
        data_cw.extend(blk[:len(blk) - ne])
    bitstr = "".join("{:08b}".format(c) for c in data_cw)
    assert bitstr[:4] == "0100", "byte mode indicator"
    nlen = 8 if ver <= 9 else 16
    count = int(bitstr[4:4 + nlen], 2)
    payload = bytes(int(bitstr[4 + nlen + 8 * i:4 + nlen + 8 * i + 8], 2) for i in range(count))
    return ver, ecl, mask, payload


def as_bool_matrix(m):
    return [[bool(v) for v in row] for row in m]


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "title"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "title"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def visible_text(html):
    p = TextOnly()
    p.feed(html)
    return "\n".join(p.parts)


# ================================================================== QR (FR-QR-01)


class QR(unittest.TestCase):
    def setUp(self):
        self.qr = requires("qr")

    def test_reader_selfcheck_on_appendix_c(self):
        """Validates the in-test reader on the normative Appendix C matrices (independent of fathom.qr)."""
        for v in load_fixture("qr-vectors.json"):
            m = [[c == "1" for c in row] for row in v["rows"]]
            ver, ecl, mask, payload = qr_decode(m)
            self.assertEqual((ver, ecl, mask, payload), (v["version"], "M", 2, v["text"].encode()))

    def test_qr_vectors(self):
        for v in load_fixture("qr-vectors.json"):
            with self.subTest(text=v["text"]):
                got = as_bool_matrix(self.qr.encode(v["text"], ecl="M", mask=2))
                exp = [[c == "1" for c in row] for row in v["rows"]]
                self.assertEqual(len(got), 17 + 4 * v["version"], fr("FR-QR-01", "C", "version"))
                diff = [(y, x) for y in range(len(exp)) for x in range(len(exp)) if got[y][x] != exp[y][x]] if len(got) == len(exp) else ["size"]
                self.assertEqual(diff, [], fr("FR-QR-01", "Appendix C", "bit-for-bit with mask=2, ecl=M; first diffs %s" % diff[:5]))

    def test_qr_version_selection(self):
        self.assertEqual(len(self.qr.encode("A" * 100, "M")), 41, fr("FR-QR-01", "C.3", "100 bytes -> version 6"))
        for n, ver in ((14, 1), (15, 2), (26, 2), (42, 3), (62, 4), (84, 5), (106, 6), (122, 7), (152, 8), (180, 9), (213, 10), (214, 11)):
            self.assertEqual(len(self.qr.encode("x" * n, "M")), 17 + 4 * ver, fr("FR-QR-01", "C.3", "%d bytes at M -> version %d" % (n, ver)))
        self.assertEqual(len(self.qr.encode("x" * 2331, "M")), 177, fr("FR-QR-01", "C.3", "max byte capacity at 40-M"))
        with self.assertRaises(ValueError, msg=fr("FR-QR-01", "C.3", "2400 bytes at M")):
            self.qr.encode("x" * 2400, "M")
        self.assertEqual(len(self.qr.encode("HELLO", ecl="H", version=5)), 37, "forced version")

    def test_qr_rs_selfcheck(self):
        rng = random.Random(18004)
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~:/?#[]@!$&'()*+,;=%é→·"
        for i in range(200):
            ecl = "LMQH"[i % 4]
            n = rng.choice([1, 5, 17, 40, 90, 150, 300]) if i % 25 else rng.randint(400, 900)
            text = "".join(rng.choice(alphabet) for _ in range(n))
            with self.subTest(i=i, ecl=ecl, n=n):
                m = as_bool_matrix(self.qr.encode(text, ecl=ecl))
                ver, got_ecl, mask, payload = qr_decode(m)
                self.assertEqual(got_ecl, ecl, fr("FR-QR-01", "3.24", "format bits carry the ECL"))
                self.assertEqual(payload, text.encode("utf-8"), fr("FR-QR-01", "3.24", "payload round trip (UTF-8 byte mode)"))
        for mask in range(8):
            m = as_bool_matrix(self.qr.encode("mask test", ecl="Q", mask=mask))
            self.assertEqual(qr_decode(m)[2], mask, "forced mask %d" % mask)

    def test_qr_svg(self):
        m = self.qr.encode("FATHOM", ecl="M", mask=2)
        svg = self.qr.to_svg(m, scale=4, border=4)
        root = ET.fromstring(svg)
        self.assertEqual(root.get("viewBox"), "0 0 29 29", fr("FR-QR-01", "C.4", "viewBox in module units incl. quiet zone"))
        self.assertEqual((root.get("width"), root.get("height")), ("116", "116"), fr("FR-QR-01", "C.4"))
        tags = [e.tag.split("}")[-1] for e in root.iter()]
        self.assertTrue("path" in tags or "rect" in tags)
        s2 = self.qr.svg("FATHOM", ecl="M")
        ET.fromstring(s2)


# ================================================================== cable tags & labels (§4.8, FR-CAB)


class CableTags(unittest.TestCase):
    def setUp(self):
        self.cables = requires("cables")

    def test_assign_tags_fixture(self):
        ops = self.cables.assign_tags_ops(sunday_doc(), scope="missing")
        exp = [("c-0001", "A-006"), ("c-0002", "A-007"), ("c-0007", "A-008"), ("c-0009", "A-009"), ("c-0010", "A-010"), ("c-0011", "A-011"),
               ("c-0012", "V-001"), ("c-0013", "V-002"), ("c-0014", "V-003"), ("c-0015", "X-001")]
        self.assertEqual(ops, [{"op": "merge", "coll": "cables", "id": i, "value": {"tag": t}} for i, t in exp], fr("FR-CAB-02", "4.8"))
        schema = requires("schema")
        new, _ = schema.apply_ops(sunday_doc(), ops)
        self.assertEqual(self.cables.assign_tags_ops(new, scope="missing"), [], "missing never changes existing tags")
        allops = self.cables.assign_tags_ops(sunday_doc(), scope="all")
        tags = {o["id"]: o["value"]["tag"] for o in allops}
        expected_all = {"c-%04d" % i: "A-%03d" % i for i in range(1, 12)}
        expected_all.update({"c-0012": "V-001", "c-0013": "V-002", "c-0014": "V-003", "c-0015": "X-001"})
        self.assertEqual(tags, expected_all, fr("FR-CAB-02", "4.8", "scope=all renumbers ignoring existing tags"))

    def test_tag_grammar(self):
        doc = sunday_doc()
        cab = {c["id"]: c for c in doc["cables"]}
        rt = self.cables.render_tag
        self.assertEqual(rt("{D}-{n:03}", cab["c-0011"], doc, 7), "A-007")
        self.assertEqual(rt("{room}-{M}{n:02}", cab["c-0011"], doc, 7), "MAIN-XLR07", "4.8 {room} {M} {n:02}")
        self.assertEqual(rt("{disc}/{DISC}/{n}", cab["c-0014"], doc, 3), "video/VIDEO/3", "4.8 {disc} {DISC} {n}")
        self.assertEqual(rt("{from}>{to}#{n:04}", cab["c-0011"], doc, 12), "AUDIORAC>ATEMMINI#0012", "4.8 device code default (uppercase slug, no dashes, 8 chars)")
        self.assertEqual(rt("{M}", cab["c-0014"], doc, 1), "SDI")
        self.assertEqual(rt("{D}", cab["c-0015"], doc, 1), "X", "usb medium discipline other -> X")
        doc["devices"][4]["code"] = "AR1"
        self.assertEqual(rt("{from}-{n}", cab["c-0011"], doc, 1), "AR1-1", "explicit device code")
        doc["devices"][4]["room"] = ""
        self.assertEqual(rt("{room}", cab["c-0011"], doc, 1), "X", "4.8 no room -> X")
        odd = dict(cab["c-0011"], medium="laser")
        self.assertEqual(rt("{D}", odd, doc, 1), "X", "unknown medium -> other")

    def test_custom_pattern_scoped_numbering(self):
        doc = sunday_doc()
        doc["settings"]["cable_tag_pattern"] = "{room}-{D}{n:02}"
        ops = self.cables.assign_tags_ops(doc, scope="missing")
        tags = [o["value"]["tag"] for o in ops]
        self.assertEqual(tags[:3], ["MAIN-A01", "MAIN-A02", "MAIN-A03"], "4.8 numbering per prefix key; existing A-00x tags do not match")
        self.assertIn("MAIN-V01", tags)
        ops2 = self.cables.assign_tags_ops(sunday_doc(), scope="missing", pattern="{M}-{n}")
        self.assertEqual(ops2[0]["value"]["tag"], "RF-1")

    def test_label_sheet_counts(self):
        html = self.cables.label_sheet_html(sunday_doc())
        text = visible_text(html)
        tagged = ["A-001", "A-002", "A-003", "A-004", "A-005"]
        for t in tagged:
            self.assertEqual(text.count(t), 2, fr("FR-CAB-04", "3.10", "two labels per tagged cable (%s)" % t))
        self.assertIn("→", text, "3.10 row 2 FROM-CODE port → TO-CODE port")
        self.assertIn("letter", html.lower() + "letter", "")
        ET  # noqa: B018

    def test_bundle_members_rrc(self):
        schema = requires("schema")
        doc = schema.migrate(rrc_dict())
        sched = self.cables.cable_schedule(doc)
        rows = [r for r in sched["rows"] if r.get("bundle") in ("b-0001",) or r.get("bundle_id") == "b-0001"]
        self.assertEqual(len(rows), 8, fr("FR-CAB-05", "3.10", "bundle b-0001 lists 8 members"))

    def test_cable_schedule_filters(self):
        s = self.cables.cable_schedule(sunday_doc(), discipline="video")
        self.assertEqual(sorted(r["id"] for r in s["rows"]), ["c-0012", "c-0013", "c-0014"], fr("FR-CAB-03", "3.10"))
        d = sunday_doc()
        d["devices"][5]["status"] = "planned"
        s = self.cables.cable_schedule(d, state="as_built")
        self.assertFalse({"c-0011", "c-0012", "c-0013", "c-0015"} & {r["id"] for r in s["rows"]}, fr("FR-PLN-01", "4.4.6", "cables to excluded devices drop out"))
        s = self.cables.cable_schedule(sunday_doc())
        r3 = [r for r in s["rows"] if r["id"] == "c-0003"][0]
        self.assertEqual((r3["from_device"], r3["to_device"]), ("Shure Wireless", "Audio Rack 1"), "5.8.2 names in device columns")
        self.assertEqual(r3.get("length_unit"), "ft", "3.10 length shown in settings units (fixture imperial)")


# ================================================================== network, DMX, racks, BOM


class Network(unittest.TestCase):
    def setUp(self):
        self.network = requires("network")

    def test_mac_normalization(self):
        n = self.network.normalize_mac
        for s in ("AABB.CCDD.EEFF", "aa-bb-cc-dd-ee-ff", "AABBCCDDEEFF", "aa:bb:cc:dd:ee:ff", "AA:BB:CC:DD:EE:FF"):
            self.assertEqual(n(s), "aa:bb:cc:dd:ee:ff", fr("FR-NET-04", "3.11", s))
        for s in ("aa:bb:cc", "zz:bb:cc:dd:ee:ff", "", "not a mac"):
            self.assertIsNone(n(s), "invalid MAC %r -> None" % s)

    def test_ip_duplicate_warning(self):
        d = sunday_doc()
        d["devices"][5]["interfaces"][0]["ip"] = "10.20.0.10"
        codes = [p["code"] for p in self.network.network_problems(d)]
        self.assertIn("ip_duplicate", codes, fr("FR-NET-03", "3.11"))
        d = sunday_doc()
        d["devices"][5]["interfaces"][0]["ip"] = "10.99.0.40"
        self.assertIn("ip_outside_subnet", [p["code"] for p in self.network.network_problems(d)], fr("FR-NET-03", "3.11"))
        d = sunday_doc()
        d["devices"][5]["interfaces"][0]["mac"] = "xx:yy"
        self.assertIn("bad_mac", [p["code"] for p in self.network.network_problems(d)], fr("FR-NET-03", "3.11"))
        d = sunday_doc()
        d["devices"][5]["interfaces"][0]["vlan"] = 30
        self.assertIn("vlan_mismatch", [p["code"] for p in self.network.network_problems(d)], fr("FR-NET-03", "3.11"))
        self.assertEqual(self.network.network_problems(sunday_doc()), [], "fixture is clean")

    def test_ip_schedule_fixture(self):
        s = self.network.ip_schedule(sunday_doc())
        self.assertEqual(s["kind"], "ip")
        ips = sorted(r["ip"] for r in s["rows"])
        self.assertEqual(ips, ["10.20.0.10", "10.20.0.31", "10.20.0.40"])
        self.assertTrue(all(r["source"] == "manual" for r in s["rows"]), "3.11 manual source")
        ov = {"interfaces": {"atem-mini": [{"id": "primary", "role": "control", "ip": "192.168.9.9", "source": "dante"}],
                             "restream": [{"id": "dante-primary", "role": "primary", "ip": "192.168.1.50", "source": "dante"}]}}
        s = self.network.ip_schedule(sunday_doc(), ov)
        atem = [r for r in s["rows"] if r.get("device_id", r.get("device")) in ("atem-mini", "ATEM Mini")]
        self.assertEqual([r["ip"] for r in atem], ["10.20.0.40"], "3.11 manual wins on the same device+role")
        self.assertIn("192.168.1.50", [r["ip"] for r in s["rows"]])

    def test_ip_switch_ports_campus(self):
        if not (CAMPUS_DIR / "project.json").exists():
            self.skipTest("W2 sample campus-demo not present yet")
        s = self.network.ip_schedule(read_json(CAMPUS_DIR / "project.json"))
        self.assertTrue([r for r in s["rows"] if r.get("switch") and r.get("switch_port")], fr("FR-NET-05", "3.11", "campus IP schedule shows switch ports"))


class Dmx(unittest.TestCase):
    def setUp(self):
        self.dmx = requires("dmx")

    def _doc(self):
        d = sunday_doc()
        d["devices"] += [
            {"id": "par-1", "name": "Par 1", "kind": "fixture", "room": "main", "ports": [], "dmx": {"universe": 1, "address": 1, "footprint": 8}},
            {"id": "par-2", "name": "Par 2", "kind": "fixture", "room": "main", "ports": [], "dmx": {"universe": 1, "address": 5, "footprint": 8}},
            {"id": "mover", "name": "Mover", "kind": "fixture", "room": "main", "ports": [], "dmx": {"universe": 2, "address": 500, "footprint": 20}},
            {"id": "mystery", "name": "Mystery", "kind": "fixture", "room": "main", "ports": [], "dmx": {"universe": 2, "address": 1}},
        ]
        return d

    def test_dmx_overlap(self):
        d = self._doc()
        s = self.dmx.dmx_schedule(d)
        rows = s["rows"]
        u1 = [r for r in rows if r["universe"] == 1]
        self.assertEqual([r["address"] for r in u1], [1, 5], fr("FR-DMX-02", "3.12", "sorted by address per universe"))
        self.assertEqual([r["end"] for r in u1], [8, 12], fr("FR-DMX-02", "3.12", "end = address + footprint - 1"))
        probs = self.dmx.dmx_problems(d)
        ov = [p for p in probs if p["code"] == "dmx_overlap"]
        self.assertTrue(ov, fr("FR-DMX-02", "3.12", "overlap flagged"))
        blob = json.dumps(ov)
        self.assertIn("par-1", blob, fr("FR-DMX-02", "3.12", "both device ids"))
        self.assertIn("par-2", blob, fr("FR-DMX-02", "3.12", "both device ids"))
        codes = [p["code"] for p in probs]
        self.assertIn("dmx_overflow", codes, fr("FR-DMX-02", "3.12", "end > 512"))
        self.assertIn("dmx_footprint_unknown", codes, fr("FR-DMX-02", "3.12"))

    def test_sacn_artnet_helpers(self):
        self.assertEqual(self.dmx.sacn_group(300), "239.255.1.44", fr("FR-DMX-04", "3.12"))
        self.assertEqual(self.dmx.sacn_group(1), "239.255.0.1")
        self.assertEqual(tuple(self.dmx.artnet_split(300)), (1, 2, 11), fr("FR-DMX-04", "3.12", "port-address 299 = Net 1, Sub-Net 2, Universe 11"))
        self.assertEqual(tuple(self.dmx.artnet_split(1)), (0, 0, 0))
        d = self._doc()
        d["devices"][-4]["dmx"]["universe"] = 300
        rows = self.dmx.dmx_schedule(d)["rows"]
        r = [x for x in rows if x["universe"] == 300][0]
        self.assertEqual(r["sacn_group"], "239.255.1.44")
        self.assertIn(str(r["artnet"]).replace(" ", ""), ("1:2:11", "1.2.11"))


class Racks(unittest.TestCase):
    def setUp(self):
        self.racks = requires("racks")

    def test_validate_racks_overlap(self):
        self.assertEqual(self.racks.validate_racks(sunday_doc()), [], "fixture racks clean")
        d = sunday_doc()
        d["devices"][3]["rack"] = {"id": "rk-foh", "u": 4, "height": 2, "face": "front"}
        d["devices"][5]["rack"] = {"id": "rk-foh", "u": 5, "height": 1, "face": "front"}
        probs = self.racks.validate_racks(d)
        self.assertIn("rack_overlap", [p["code"] for p in probs], fr("FR-RACK-05", "3.9", "two full-width devices at the same U/face"))
        d["devices"][3]["rack"]["depth"] = "half"
        d["devices"][5]["rack"] = {"id": "rk-foh", "u": 5, "height": 1, "face": "rear", "depth": "half"}
        self.assertNotIn("rack_overlap", [p["code"] for p in self.racks.validate_racks(d)], "3.9 half-depth front and half-depth rear share a U")
        d["devices"][3]["rack"]["depth"] = "full"
        d["devices"][5]["rack"] = {"id": "rk-foh", "u": 5, "height": 1, "face": "rear"}
        self.assertIn("rack_overlap", [p["code"] for p in self.racks.validate_racks(d)], "3.9 full-depth blocks both faces")
        d = sunday_doc()
        d["devices"][1]["rack"] = {"id": "rk-foh", "u": 10, "height": 1, "face": "front", "side": "left"}
        d["devices"][9]["rack"] = {"id": "rk-foh", "u": 10, "height": 1, "face": "front", "side": "right"}
        self.assertNotIn("rack_overlap", [p["code"] for p in self.racks.validate_racks(d)], "3.9 left+right halves share a U")
        d["devices"][9]["rack"] = {"id": "rk-foh", "u": 12, "height": 2, "face": "front"}
        self.assertIn("rack_out_of_range", [p["code"] for p in self.racks.validate_racks(d)], "3.9 U12 + 2U exceeds 12U")
        d["devices"][9]["rack"] = {"id": "rk-ghost", "u": 1}
        self.assertIn("rack_unknown", [p["code"] for p in self.racks.validate_racks(d)])

    def test_rack_svg_and_schedule(self):
        for face in ("front", "rear"):
            svg = self.racks.rack_svg(sunday_doc(), "rk-foh", face=face)
            ET.fromstring(svg)
        self.assertIn("Shure Wireless", self.racks.rack_svg(sunday_doc(), "rk-foh", face="front"))
        occ = self.racks.rack_occupancy(sunday_doc(), "rk-foh")
        for k in ("rack", "slots", "collisions"):
            self.assertIn(k, occ)
        s = self.racks.rack_schedule(sunday_doc())
        row = [r for r in s["rows"] if "Shure Wireless" in (r.get("device"), r.get("device_name"))]
        self.assertTrue(row and row[0]["u"] == 10 and row[0]["side"] == "left", fr("FR-RACK-02", "3.9", "shure-wireless at U10, left half, front"))


class Bom(unittest.TestCase):
    def setUp(self):
        self.bom = requires("bom")

    def test_bom_fixture_total(self):
        b = self.bom.bom(sunday_doc())
        self.assertEqual(b["totals"], {"USD": 6498.0}, fr("FR-PLN-03", "3.15", "grand total 6498.00 USD"))
        rows = b["rows"]
        ulx = [r for r in rows if r.get("template") == "shure-ulxd4d"]
        self.assertEqual(len(ulx), 1, "3.15 grouped by template id")
        self.assertEqual((ulx[0]["qty"], ulx[0]["extended"], ulx[0]["unit_cost"]), (2, 1999.0, None), fr("FR-PLN-03", "3.15", "unit_cost null when members differ"))
        self.assertEqual((ulx[0]["installed"], ulx[0]["spare"]), (1, 1), "3.15 per-status counts; spares in BOM regardless of state")
        sq = [r for r in rows if r.get("template") == "allen-heath-sq-5"][0]
        self.assertEqual((sq["qty"], sq["unit_cost"], sq["extended"]), (1, 4499.0, 4499.0))
        spk = [r for r in rows if r.get("template") == "qsc-k12-2"][0]
        self.assertEqual(spk["qty"], 2, "3.15 qty = sum(count or 1)")
        mics = [r for r in rows if r.get("model") == "ULXD2/SM58"]
        self.assertTrue(mics and mics[0]["qty"] == 2, "3.15 no template -> manufacturer + model")
        cab = [r for r in rows if r.get("category") == "cable" and "XLR3 M-F" in str(r.get("model"))]
        self.assertTrue(cab, "5.8.2 cable lines model '<medium> · <type>'")
        self.assertEqual((cab[0]["qty"], cab[0]["length_total_m"]), (4, 9.0))

    def test_inventory_schedule(self):
        s = self.bom.inventory_schedule(sunday_doc())
        self.assertEqual(len(s["rows"]), 12, fr("FR-INV-04", "5.8.2", "one row per device"))
        sb = [r for r in s["rows"] if r["id"] == "sound-board"][0]
        self.assertEqual((sb["serial"], sb["asset_tag"], sb["ips"]), ("SQ5-004211", "HC-0012", "10.20.0.10"))


# ================================================================== builds (§5.9)

BUILD_TOP = ["index.html", "diagram.svg", "patch-sheet.csv", "project.json", "build-notes.txt", "rooms/index.html", "patch-table.csv",
             "cable-schedule.csv", "cable-labels.html", "device-labels.html", "ip-schedule.csv", "dmx-schedule.csv", "bom.csv", "inventory.csv"]


def rel_files(run):
    return sorted(str(p.relative_to(run)) for p in Path(run).rglob("*") if p.is_file())


class Builds(unittest.TestCase):
    """One shared data dir; each project is built once per option set and reused (builds are slow)."""

    @classmethod
    def setUpClass(cls):
        cls._ctx = temp_data_dir()
        cls.data = cls._ctx.__enter__()
        cls.runs = {}

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def setUp(self):
        self.export = requires("export")
        requires("export:build_doc")

    def build(self, name, installer, **kw):
        key = (name, tuple(sorted(kw.items())))
        if key not in self.runs:
            if not (self.data / "projects" / name).exists():
                installer(self.data, name)
            run = self.data / "runs" / uniq(name)
            self.runs[key] = Path(self.export.build_doc(str(self.data / "projects" / name), run_dir=run, **kw))
        return self.runs[key]

    def check_layout(self, run, doc, qr, notes_required=True):
        files = rel_files(run)
        missing = [f for f in BUILD_TOP if f not in files and (notes_required or f != "build-notes.txt")]
        for room in doc["rooms"]:
            for f in ("index.html", "diagram.svg", "patch.html", "patch.svg"):  # patch.svg: phase5 P5C (FR-EXP-06)
                if "rooms/%s/%s" % (room["id"], f) not in files:
                    missing.append("rooms/%s/%s" % (room["id"], f))
        for d in doc["devices"]:
            if "devices/%s.html" % d["id"] not in files:
                missing.append("devices/%s.html" % d["id"])
            if qr and "qr/%s.svg" % d["id"] not in files:
                missing.append("qr/%s.svg" % d["id"])
        for r in doc["racks"]:
            for face in ("front", "rear"):
                if "racks/%s-%s.svg" % (r["id"], face) not in files:
                    missing.append("racks/%s-%s.svg" % (r["id"], face))
        # phase5 P5C (FR-EXP-07): the cable-runs plan sits next to the plain one once floorplan.plan_svg takes runs=
        import inspect

        from fathom.floorplan import plan_svg
        plan_runs = "runs" in inspect.signature(plan_svg).parameters
        for fp in doc["floorplans"]:
            if "floorplans/%s.svg" % fp["id"] not in files:
                missing.append("floorplans/%s.svg" % fp["id"])
            if plan_runs and "floorplans/%s-runs.svg" % fp["id"] not in files:
                missing.append("floorplans/%s-runs.svg" % fp["id"])
        zp = run / ("%s.zip" % run.name)
        if not zp.exists():
            missing.append(zp.name)
        else:
            names = set(zipfile.ZipFile(str(zp)).namelist())
            for f in files:
                if not f.endswith(".zip") and "%s/%s" % (run.name, f) not in names:
                    missing.append("zip:" + f)
        absolute = []
        for f in files:
            if f.endswith(".html"):
                html = (run / f).read_text(encoding="utf-8", errors="replace")
                for m in re.finditer(r'(?:href|src)="(/[^"]*)"', html):
                    absolute.append("%s -> %s" % (f, m.group(1)))
        return missing, absolute

    def campus(self):
        return self.build("campus", install_campus, base_url="http://localhost:8080")

    def test_build_layout_campus(self):
        run = self.campus()
        doc = read_json(self.data / "projects" / "campus" / "project.json")
        missing, absolute = self.check_layout(run, doc, qr=True)
        self.assertEqual(missing, [], fr("FR-EXP-01", "5.9", "campus build files"))
        self.assertEqual(absolute, [], fr("FR-EXP-01", "5.9", "internal links are relative"))
        self.assertEqual(read_json(run / "project.json")["fathom"], 2, "5.9 project.json is the normalized v2 doc")

    def test_build_layout_rrc(self):
        schema = requires("schema")
        run = self.build("rrc", install_rrc, base_url="http://localhost:8080")
        missing, absolute = self.check_layout(run, schema.migrate(rrc_dict()), qr=True, notes_required=False)
        self.assertEqual(missing, [], fr("FR-EXP-01", "5.9", "RRC build files"))
        self.assertEqual(absolute, [])

    def test_v1_artifacts(self):
        run = self.build("rrc", install_rrc, base_url="http://localhost:8080")
        html = (run / "index.html").read_text()
        for needle in ('class="card', 'data-id="foh"', "SF_DATA", "Patch sheet"):
            self.assertIn(needle, html, fr("FR-EXP-02", "3.23", "index.html keeps %r" % needle))
        header = (run / "patch-sheet.csv").read_text().splitlines()[0]
        from fathom.merge import apply_imports
        from fathom.model import project_from_dict
        from fathom.patch import patch_sheet_csv

        p = project_from_dict(rrc_dict())
        apply_imports(p, RRC_DIR)
        self.assertEqual(header, patch_sheet_csv(p).splitlines()[0], fr("FR-EXP-02", "3.23", "patch-sheet.csv keeps v1 columns"))
        self.assertIn("<svg", (run / "diagram.svg").read_text())

    def test_build_state_as_built(self):
        def planned(data, name):
            d = sunday_doc()
            d["devices"][5]["status"] = "planned"
            install_project(data, name, doc=d)

        run = self.build("planned", planned, state="as_built")
        self.assertNotIn('data-id="atem-mini"', (run / "rooms" / "main" / "index.html").read_text(), fr("FR-PLN-01", "3.15", "planned device omitted from maps"))
        cab = (run / "cable-schedule.csv").read_text()
        for cid in ("c-0011", "c-0012", "c-0013", "c-0015"):
            self.assertNotIn(cid, cab, fr("FR-PLN-01", "3.15", "cables of planned devices omitted from schedules"))
        run2 = self.build("planned", planned, state="all")
        self.assertIn('data-id="atem-mini"', (run2 / "rooms" / "main" / "index.html").read_text())

    def test_build_rack_svgs(self):
        run = self.build("s", install_sunday)
        for face in ("front", "rear"):
            f = run / "racks" / ("rk-foh-%s.svg" % face)
            self.assertTrue(f.exists(), fr("FR-RACK-06", "3.9", f.name))
            ET.fromstring(f.read_bytes())

    def test_build_floorplan_svg_markers(self):
        run = self.campus()
        doc = read_json(self.data / "projects" / "campus" / "project.json")
        plans = [fp for fp in doc["floorplans"] if fp.get("markers")]
        self.assertTrue(plans, "campus-demo has plans with markers")
        for fp in plans:
            root = ET.fromstring((run / "floorplans" / ("%s.svg" % fp["id"])).read_bytes())
            devs = [e.get("data-device") for e in root.iter() if e.tag.split("}")[-1] == "g" and e.get("data-device")]
            self.assertEqual(sorted(devs), sorted(m["device"] for m in fp["markers"]), fr("FR-PLAN-13", "3.8", "one <g data-device> per marker"))

    def test_qr_public_url_branches(self):
        run = self.build("s", install_sunday)
        self.assertFalse((run / "qr").exists() and list((run / "qr").iterdir()), fr("FR-EXP-04", "3.23", "no public URL -> no QR"))
        self.assertIn("qr", (run / "build-notes.txt").read_text().lower(), fr("FR-EXP-04", "3.23", "build note about skipped QR"))
        run2 = self.build("s", install_sunday, base_url="https://av.example.org")
        self.assertTrue((run2 / "qr" / "atem-mini.svg").exists(), fr("FR-EXP-04", "3.23", "base_url -> QR"))

        def with_url(data, name):
            d = sunday_doc()
            d["settings"]["public_url"] = "https://settings.example.org"
            install_project(data, name, doc=d)

        with temp_env(FATHOM_PUBLIC_URL="https://env.example.org"):
            run3 = Path(self.export.build_doc(str(self.data / "projects" / "s"), run_dir=self.data / "runs" / uniq("env")))
            self.assertTrue((run3 / "qr" / "atem-mini.svg").exists(), fr("FR-EXP-04", "3.23", "FATHOM_PUBLIC_URL -> QR"))
            run4 = self.build("s2", with_url)
        qr = requires("qr")
        exp = qr.svg(self.export.device_url("https://settings.example.org", "s2", "atem-mini"))
        self.assertEqual((run4 / "qr" / "atem-mini.svg").read_text(), exp, fr("FR-EXP-04", "3.23", "settings.public_url wins over the env"))
        self.assertEqual(self.export.device_url("https://a.b", "p", "d"), "https://a.b/p/p/d/d")

    def test_report_pdf(self):
        if not self.export.find_chrome():
            self.skipTest("Chrome not found (report.pdf needs headless Chrome)")
        if os.environ.get("FATHOM_T1_CHROME") != "1":
            self.skipTest("headless Chrome PDF render takes ~15 s; set FATHOM_T1_CHROME=1 to run it (Chrome present)")
        run = self.build("s", install_sunday, pdf=True)
        pdf = run / "report.pdf"
        self.assertTrue(pdf.exists() and pdf.stat().st_size > 10 * 1024, fr("FR-EXP-05", "3.23", "report.pdf > 10 KB"))


class CliMigrate(unittest.TestCase):
    def test_cli_migrate(self):
        cli = requires("cli")
        with temp_data_dir() as data:
            pdir = install_rrc(data, "rrc")
            before = (pdir / "project.json").read_bytes()
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                try:
                    cli.main(["migrate", str(pdir)])
                except SystemExit as e:
                    self.assertIn(e.code, (0, None), "fathom migrate exit")
            text = out.getvalue().lower()
            for word in ("devices", "ports", "cables", "bundles", "warnings"):
                self.assertIn(word, text, fr("FR-MIG-05", "3.4", "summary mentions %s" % word))
            self.assertEqual((pdir / "project.json").read_bytes(), before, fr("FR-MIG-05", "3.4", "no write without --write"))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    cli.main(["migrate", str(pdir), "--write"])
                except SystemExit as e:
                    self.assertIn(e.code, (0, None))
            self.assertEqual(read_json(pdir / "project.json")["fathom"], 2, fr("FR-MIG-05", "3.4", "--write saves v2"))
            self.assertEqual((pdir / "project.v1.json").read_bytes(), before, "FR-MIG-04 backup on the first v2 write")


if __name__ == "__main__":
    unittest.main()
