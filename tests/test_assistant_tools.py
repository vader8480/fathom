"""Grounded tool-calling assistant with confirm-before-edit (SPEC FR-AST-10..13, §5.10 proposal / apply, §6.9.5a, §6.9.6 tool loop).

A scripted ``FakeProvider`` replays ``tests/fixtures/assistant/*.json`` (text → tool_calls → text); every tool runs
against the campus sample; proposals only change the project through ``POST …/assistant/apply``.
"""

from __future__ import annotations

import io
import json
import shutil
import socket
import unittest
from pathlib import Path
from unittest import mock

try:
    from _helpers import FIXTURES, call, fr, get_app, install_campus, jbody, requires, temp_data_dir, temp_env
except ImportError:  # pragma: no cover
    from tests._helpers import FIXTURES, call, fr, get_app, install_campus, jbody, requires, temp_data_dir, temp_env

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
FX = FIXTURES / "assistant"
Q_ULXD = "add a second ULXD4D and patch it to input 5"
READ_TOOLS = ["search", "trace", "device", "schedule", "list_rooms", "list_scenes", "sop_page", "attachment_text"]
DDG_HTML = """<html><body><div id="links">
<div class="result"><a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fpubs.shure.com%2Fguide%2FULXD4D">ULXD4D User Guide - Shure</a></div>
<div class="result"><a class="result__a" href="https://www.shure.com/ulxd4d">ULXD4D Dual Channel Receiver</a></div>
<div class="result"><a class="result__a" href="https://example.com/3">Three</a></div>
<div class="result"><a class="result__a" href="https://example.com/4">Four</a></div>
<div class="result"><a class="result__a" href="https://example.com/5">Five</a></div>
<div class="result"><a class="result__a" href="https://example.com/6">Six</a></div>
</div></body></html>"""


def no_network(*a, **k):
    raise AssertionError("FR-AST-11: a socket / HTTP call was attempted")


class _Guard:
    """No outbound connection at all: urlopen, socket.create_connection and socket.socket.connect raise."""

    def __enter__(self):
        self.p = [mock.patch("urllib.request.urlopen", no_network), mock.patch("socket.create_connection", no_network),
                  mock.patch.object(socket.socket, "connect", no_network)]
        for p in self.p:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.p:
            p.stop()
        return False


def _fixture(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def _doc(app, name="campus"):
    st, _, b = call(app, "GET", "/api/v2/projects/" + name)
    assert st == 200, b[:200]
    return jbody(b)


def _add_text_attachment(pdir: Path, att_id: str, filename: str, text: str, mime: str = "text/plain") -> None:
    pf = pdir / "project.json"
    doc = json.loads(pf.read_text(encoding="utf-8"))
    d = pdir / "files" / att_id
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(text, encoding="utf-8")
    doc.setdefault("attachments", []).append({"id": att_id, "name": filename, "file": f"files/{att_id}/{filename}", "mime": mime,
                                              "size": len(text.encode()), "kind": "other", "uploaded": "2026-10-28T00:00:00Z", "by": "test"})
    pf.write_text(json.dumps(doc, indent=1), encoding="utf-8")


class Tools(unittest.TestCase):
    """§6.9.6 tool loop: registry, every tool against the campus fixture, output cap."""

    def setUp(self):
        self.AT = requires("assistant_tools")
        self.E = requires("assistant_edits")

    def _ctx(self, data):
        from fathom.project import read_doc

        pdir = install_campus(data, "campus")
        doc, _ = read_doc(pdir)
        return pdir, doc, {"doc": doc, "overlay": None, "pdir": pdir, "base_revision": doc.get("revision", 1)}

    def test_registry(self):
        names = [t.name for t in self.AT.TOOLS]
        for n in READ_TOOLS + ["web_lookup", "propose_changes"]:
            self.assertIn(n, names, fr("FR-AST-10", "6.9.6", "tool %s registered" % n))
        api = self.AT._Api(None)
        off = [t.name for t in self.AT.tool_specs(api, {"web_lookup": False})]
        on = [t.name for t in self.AT.tool_specs(api, {"web_lookup": True})]
        self.assertNotIn("web_lookup", off, fr("FR-AST-11", "6.9.6", "web_lookup absent when the setting is off"))
        self.assertIn("web_lookup", on)
        for t in self.AT.tool_specs(api, {"web_lookup": True}):
            self.assertEqual(t.parameters.get("type"), "object", t.name)
            self.assertTrue(t.description)
        self.assertFalse(self.AT.effective_config().get("web_lookup"), "6.9.6 default: web lookup off")

    def test_every_tool_on_campus(self):
        with temp_data_dir() as data:
            pdir, doc, ctx = self._ctx(data)
            run = lambda n, a: json.loads(self.AT.run_tool(n, a, ctx))  # noqa: E731
            s = run("search", {"query": "ULXD4D", "kinds": ["device"]})
            self.assertEqual([h["id"] for h in s["hits"]][:2], ["ch-wireless", "spare-ulxd4d"], fr("FR-AST-10", "6.9.6", "search tool"))
            t = run("trace", {"device": "Chapel wireless", "port": "Analog Out 1", "direction": "down"})
            self.assertEqual(t["port"], "analog-out-1")
            self.assertTrue([p for p in t["downstream"] if "Chapel mixer · Analog In 3" in p], fr("FR-AST-10", "6.9.4", "trace path text: %s" % t))
            self.assertNotIn("upstream", t)
            both = run("trace", {"device": "ch-mixer", "direction": "both"})
            self.assertIn("upstream", both)
            self.assertIn("downstream", both)
            d = run("device", {"id_or_name": "ch-wireless"})
            self.assertEqual((d["id"], d["model"], d["room_name"]), ("ch-wireless", "ULXD4D", "Chapel"))
            out1 = [p for p in d["ports"] if p["id"] == "analog-out-1"][0]
            self.assertTrue([c for c in out1["connections"] if "Chapel mixer" in c and "A-025" in c], "device tool lists port connections")
            full = run("device", {"id_or_name": "Wireless RX 1-4"})
            self.assertEqual(full["rack_name"], "FOH rack")
            self.assertTrue(full.get("interfaces") and full.get("inventory"), "device tool: interfaces, inventory")
            for kind in ("patch", "cables", "ip", "dmx", "bom", "inventory", "racks"):
                raw = self.AT.run_tool("schedule", {"kind": kind, "room": "chapel" if kind in ("patch", "cables") else "*"}, ctx)
                self.assertLessEqual(len(raw), 6000, fr("FR-AST-10", "6.9.6", "%s schedule ≤ 6 kB" % kind))
                sch = json.loads(raw)
                self.assertEqual(sch["kind"], kind)
                self.assertLessEqual(sch["shown"], 60, "first 60 rows")
                self.assertTrue(sch["rows"], kind)
            byname = run("schedule", {"kind": "patch", "room": "Chapel"})
            self.assertEqual(byname["room"], "chapel", "room by name")
            self.assertIn("error", run("schedule", {"kind": "labels"}))
            rooms = run("list_rooms", {})
            self.assertEqual([r["id"] for r in rooms["rooms"]], ["main", "chapel", "broadcast"])
            self.assertEqual(rooms["shared_inventory_devices"], 2)
            sc = run("list_scenes", {})
            self.assertEqual(sc["scenes"][0]["id"], "base")
            page = run("sop_page", {"slug": "power-up"})
            self.assertEqual(page["title"], "Power-up: Main Auditorium")
            self.assertNotIn("#", page["text"][:5])
            self.assertIn("Amplifiers", page["text"])
            bytitle = run("sop_page", {"slug": "Chapel pre-service"})
            self.assertEqual(bytitle["slug"], "chapel-pre-service")
            self.assertIn("pages", run("sop_page", {"slug": "nope"}))
            dxf = run("attachment_text", {"att_id": "att-1b944312bc63"})
            self.assertIn("no text extraction", dxf["text"])
            self.assertIn("error", run("attachment_text", {"att_id": "att-000000000000"}), "attachment outside the project")
            self.assertIn("error", run("nonsense", {}))
            self.assertIn("error", run("device", {"id_or_name": "zzz-no-such"}))
            big = self.AT._text({"x": "y" * 10000})
            self.assertLessEqual(len(big), 6000 + 80)
            self.assertIn("truncated", big, "6.9.6 outputs over 6 kB are cut with a note")

    def test_loop_replays_script_and_grounds_messages(self):
        with temp_data_dir() as data:
            pdir, doc, ctx = self._ctx(data)
            prov = self.AT.FakeProvider(_fixture("tools-tour.json"))
            ctx.update({"project": "campus", "role": "editor", "room": "chapel"})
            with _Guard():
                out = self.AT.answer_with_tools(doc, "where does the chapel wireless go?", [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello"}], ctx, provider_=prov)
            self.assertNotIn("error", out, out)
            self.assertEqual(out["finish"], "stop")
            self.assertEqual(out["steps"], 4, "text after three rounds of tool calls")
            self.assertEqual([u["name"] for u in out["used_tools"]], ["search", "trace", "device", "schedule", "list_rooms", "list_scenes", "sop_page", "web_lookup"],
                             fr("FR-AST-10", "6.9.6", "used_tools in call order"))
            self.assertTrue(all("args_summary" in u for u in out["used_tools"]))
            self.assertIn("Chapel mixer", out["text"])
            first = prov.calls[0]["messages"]
            self.assertEqual(first[0].role, "system")
            self.assertIn("(campus)", first[0].content, "project name")
            self.assertIn("Signal flow, stage to stream", first[0].content, "project title")
            self.assertIn("Chapel", first[0].content)
            self.assertIn("editor", first[0].content)
            self.assertIn("propose_changes", first[0].content, "6.9.6 the rule: propose edits with propose_changes")
            self.assertEqual([m.role for m in first[1:]], ["user", "assistant", "user"], "history turns then the question")
            self.assertNotIn("web_lookup", prov.calls[0]["tools"], fr("FR-AST-11", "6.9.6", "web_lookup not offered when off"))
            last = prov.calls[-1]["messages"]
            tool_msgs = [m for m in last if m.role == "tool"]
            self.assertEqual(len(tool_msgs), 8)
            self.assertEqual(tool_msgs[0].tool_call_id, "c1")
            self.assertEqual(tool_msgs[0].name, "search")
            self.assertIn("disabled", tool_msgs[-1].content, "a scripted web_lookup while off answers 'disabled' and opens no socket")
            self.assertTrue(all(len(m.content) <= 6100 for m in tool_msgs))

    def test_web_lookup_on_parses_top5(self):
        with temp_data_dir() as data:
            pdir, doc, ctx = self._ctx(data)
            seen = []

            class Resp(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            def fake_open(req, timeout=None):
                seen.append((req.full_url, timeout))
                return Resp(DDG_HTML.encode("utf-8"))

            prov = self.AT.FakeProvider(_fixture("web-lookup-on.json"))
            with mock.patch("urllib.request.urlopen", fake_open):
                out = self.AT.answer_with_tools(doc, "find the ULXD4D manual", None, ctx, provider_=prov)
            self.assertIn("web_lookup", prov.calls[0]["tools"], fr("FR-AST-11", "6.9.6", "offered when on"))
            self.assertEqual(len(seen), 1, "one GET")
            self.assertTrue(seen[0][0].startswith("https://html.duckduckgo.com/html/?q=Shure+ULXD4D"), seen)
            self.assertEqual(seen[0][1], 5.0, "5 s timeout")
            res = json.loads([m for m in prov.calls[-1]["messages"] if m.role == "tool"][0].content)
            self.assertEqual(len(res["results"]), 5, "top 5 only")
            self.assertEqual(res["results"][0], {"title": "ULXD4D User Guide - Shure", "url": "https://pubs.shure.com/guide/ULXD4D"}, "redirect unwrapped")
            self.assertEqual(out["used_tools"], [{"name": "web_lookup", "args_summary": "query=Shure ULXD4D user guide"}])
            import urllib.error

            def down(*a, **k):
                raise urllib.error.URLError("no route")

            with mock.patch("urllib.request.urlopen", down):
                self.assertIn("error", self.AT.web_lookup("x"), "network failure → error object, never an exception")

    def test_provider_error_never_raises(self):
        with temp_data_dir() as data:
            pdir, doc, ctx = self._ctx(data)
            prov = self.AT.FakeProvider(_fixture("provider-error.json"))
            out = self.AT.answer_with_tools(doc, "rooms?", None, ctx, provider_=prov)
            self.assertIn("502", out["error"])
            self.assertEqual([u["name"] for u in out["used_tools"]], ["list_rooms"])
            A = requires("assistant")
            a = A.answer(doc, "which rooms are there", room="chapel", use_llm=True, ctx={"provider": self.AT.FakeProvider(_fixture("provider-error.json"))})
            self.assertEqual(a["llm"]["used"], False)
            self.assertIn("502", a["llm"]["error"])
            self.assertIn("summary", a)

    def test_max_steps_bound(self):
        with temp_data_dir() as data:
            pdir, doc, ctx = self._ctx(data)
            looping = {"steps": [{"tool_calls": [{"id": "l%d" % i, "name": "list_rooms", "arguments": {}}]} for i in range(20)]}
            prov = self.AT.FakeProvider(looping)
            out = self.AT.answer_with_tools(doc, "loop", None, ctx, max_steps=6, provider_=prov)
            self.assertEqual(out["steps"], 6)
            self.assertEqual(out["finish"], "max_steps")
            self.assertEqual(len(prov.calls), 6, "6.9.6 the loop stops at max_steps")

    def test_attachment_quoting(self):
        A = requires("assistant")
        with temp_data_dir() as data:
            pdir = install_campus(data, "campus")
            _add_text_attachment(pdir, "att-0000000000aa", "chapel-notes.txt", "Chapel notes: wireless gain at 12 o'clock.\n" * 8)
            _add_text_attachment(pdir, "att-0000000000bb", "levels.csv", "device,level\nChapel mixer,-6\n", mime="text/csv")
            from fathom.project import read_doc

            doc, _ = read_doc(pdir)
            got = self.AT.attachment_text(pdir, doc, "att-0000000000aa", 2000)
            self.assertIn("gain at 12 o'clock", got["text"], fr("FR-AST-12", "6.9.6", ".txt attachment is read"))
            self.assertFalse(got["truncated"])
            short = self.AT.attachment_text(pdir, doc, "att-0000000000aa", 200)
            self.assertTrue(short["truncated"])
            self.assertEqual(len(short["text"]), 200)
            csv = self.AT.attachment_text(pdir, doc, "att-0000000000bb")
            self.assertIn("Chapel mixer,-6", csv["text"])
            self.assertIn("error", self.AT.attachment_text(pdir, doc, "att-0000000000cc"), "6.9.6 not in the project → refused")
            other = dict(doc, attachments=[])
            self.assertIn("error", self.AT.attachment_text(pdir, other, "att-0000000000aa"), "attachment must belong to the given project doc")
            prov = self.AT.FakeProvider(_fixture("attachment-quote.json"))
            a = A.answer(doc, "what do my notes say about the wireless gain?", room="chapel", use_llm=True,
                         ctx={"pdir": pdir, "project": "campus", "role": "viewer", "attachments": ["att-0000000000aa"], "provider": prov,
                              "manual_text": "Pasted: the choir mic is on channel 2."})
            self.assertTrue(a["llm"]["used"])
            self.assertIn("gain at 12", a["llm"]["text"])
            self.assertEqual([t["name"] for t in a["llm"]["tools"]], ["attachment_text", "attachment_text"])
            msgs = prov.calls[0]["messages"]
            hint = [m for m in msgs if m.role == "user" and "att-0000000000aa" in m.content]
            self.assertTrue(hint, "the attached ids are announced so the model reads them with attachment_text")
            pasted = [m for m in msgs if m.role == "user" and m.content.startswith("Reference text pasted by the user:")]
            self.assertTrue(pasted, fr("FR-AST-12", "5.10", "manual_text goes in as a prefixed user message"))
            self.assertIn("choir mic", pasted[0].content)
            tool_out = json.loads([m for m in prov.calls[1]["messages"] if m.role == "tool"][0].content)
            self.assertIn("gain at 12", tool_out["text"])
            # PDF: extracted when pdftotext exists, else the documented placeholder
            pdf = pdir / "files" / "att-0000000000dd"
            pdf.mkdir()
            (pdf / "spec.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
            doc["attachments"].append({"id": "att-0000000000dd", "name": "spec.pdf", "file": "files/att-0000000000dd/spec.pdf", "mime": "application/pdf"})
            with mock.patch("shutil.which", lambda name: None):
                self.assertEqual(self.AT.attachment_text(pdir, doc, "att-0000000000dd")["text"], "(PDF text extraction unavailable)")
            if shutil.which("pdftotext") is None:
                self.skipTest("pdftotext not installed: PDF extraction path not exercised")
            got = self.AT.attachment_text(pdir, doc, "att-0000000000dd")
            self.assertIn("text", got)

    def test_daily_cap_fallback(self):
        A = requires("assistant")
        with temp_data_dir() as data:
            pdir = install_campus(data, "campus")
            from fathom.project import read_doc

            doc, _ = read_doc(pdir)
            script = {"config": {"daily_cap": 2}, "steps": [{"text": "ok", "finish": "stop"}]}
            first = A.answer(doc, "rooms?", room="chapel", use_llm=True, ctx={"provider": self.AT.FakeProvider(script)})
            self.assertTrue(first["llm"]["used"])
            second = A.answer(doc, "rooms?", room="chapel", use_llm=True, ctx={"provider": self.AT.FakeProvider(script)})
            self.assertTrue(second["llm"]["used"])
            third = A.answer(doc, "rooms?", room="chapel", use_llm=True, ctx={"provider": self.AT.FakeProvider(script)})
            self.assertEqual(third["llm"], {"used": False, "reason": "cap"}, fr("FR-AST-13", "6.9.6", "over the cap → deterministic answer, reason cap"))
            self.assertTrue(third["summary"] is not None and "intent" in third)
            usage = json.loads((data / "llm-usage.json").read_text())
            self.assertEqual(usage["count"], 2, "6.9.6 counter in <FATHOM_DATA>/llm-usage.json")
            self.assertRegex(usage["day"], r"^\d{4}-\d\d-\d\d$")
            self.assertTrue(self.AT.reserve_request(0), "cap ≤ 0 means no limit")
            self.assertTrue(self.AT.reserve_request(None))


class Proposals(unittest.TestCase):
    """§5.10 proposal: typed changes → ops, applied only through /apply."""

    def setUp(self):
        self.AT = requires("assistant_tools")
        self.E = requires("assistant_edits")
        self.app = get_app()

    def _campus_doc(self, data):
        from fathom.project import read_doc

        pdir = install_campus(data, "campus")
        return pdir, read_doc(pdir)[0]

    def test_to_ops_add_and_connect(self):
        schema = requires("schema")
        with temp_data_dir() as data:
            pdir, doc = self._campus_doc(data)
            r = self.E.to_ops(doc, [{"action": "add_device", "template": "ULXD4D", "name": "Chapel wireless 2", "room": "chapel"},
                                   {"action": "connect", "from": {"device": "Chapel wireless 2"}, "to": {"device": "Chapel mixer", "port": "input 5"}}])
            self.assertEqual(r["problems"], [])
            self.assertTrue(r["applicable"], fr("FR-AST-13", "5.10", "proposal validates"))
            self.assertEqual([(o["op"], o["coll"], o["id"]) for o in r["ops"]], [("put", "devices", "chapel-wireless-2"), ("put", "cables", "c-0110")])
            dev = r["ops"][0]["value"]
            self.assertEqual((dev["template"], dev["kind"], dev["room"], dev["model"]), ("shure-ulxd4d", "wireless_rx", "chapel", "ULXD4D"), "library template instantiated")
            self.assertTrue([p for p in dev["ports"] if p["id"] == "analog-out-1"])
            cable = r["ops"][1]["value"]
            self.assertEqual(cable["from"], {"device": "chapel-wireless-2", "port": "analog-out-1"}, "first free analog output allocated")
            self.assertEqual(cable["to"], {"device": "ch-mixer", "port": "analog-in-5"}, "'input 5' resolves to Analog In 5")
            self.assertEqual(cable["medium"], "analog")
            self.assertEqual(cable["tag"], "A-053", "§4.8 pattern continues the existing numbering")
            self.assertEqual(len(r["summary"]), 2)
            self.assertIn("Chapel wireless 2", r["summary"][0])
            self.assertIn("Analog In 5", r["summary"][1])
            new, _ = schema.apply_ops(doc, r["ops"])
            self.assertFalse(schema.errors(schema.validate_doc(schema.normalize(new))))
            # the deterministic doc is untouched by to_ops
            self.assertEqual(len(doc["devices"]), 73)
            self.assertEqual(len(doc["cables"]), 109)

    def test_to_ops_other_actions_and_problems(self):
        with temp_data_dir() as data:
            pdir, doc = self._campus_doc(data)
            r = self.E.to_ops(doc, [{"action": "remove_device", "device": "Chapel wireless"}])
            self.assertEqual([o["op"] for o in r["ops"]], ["del"] * 4, "cables of the device go with it")
            self.assertEqual(r["ops"][-1], {"op": "del", "coll": "devices", "id": "ch-wireless"})
            r = self.E.to_ops(doc, [{"action": "disconnect", "cable": "A-025"}])
            self.assertEqual(r["ops"], [{"op": "del", "coll": "cables", "id": "c-0084"}])
            r = self.E.to_ops(doc, [{"action": "disconnect", "from": {"device": "Chapel wireless", "port": "Analog Out 2"}, "to": {"device": "Chapel mixer"}}])
            self.assertEqual(r["ops"], [{"op": "del", "coll": "cables", "id": "c-0085"}])
            r = self.E.to_ops(doc, [{"action": "move_device", "device": "SM58 (spare)", "room": "Chapel"}])
            self.assertEqual(r["ops"], [{"op": "merge", "coll": "devices", "id": "spare-sm58", "value": {"room": "chapel"}}])
            r = self.E.to_ops(doc, [{"action": "move_device", "device": "spare-ulxd4d", "rack": {"id": "FOH rack", "u": 3}}])
            self.assertEqual(r["ops"][0]["value"]["rack"]["u"], 3)
            self.assertTrue(r["applicable"], r["problems"])
            r = self.E.to_ops(doc, [{"action": "set_field", "device": "Chapel mixer", "port": "Analog In 5", "field": "label", "value": "Wireless 3"}])
            ports = {p["id"]: p for p in r["ops"][0]["value"]["ports"]}
            self.assertEqual(ports["analog-in-5"]["label"], "Wireless 3")
            self.assertEqual(len(ports), 37, "full ports array merged (§6.9.5 step 11 style)")
            r = self.E.to_ops(doc, [{"action": "set_field", "device": "Chapel mixer", "field": "serial", "value": "X1"}])
            self.assertEqual(r["ops"][0]["value"], {"inventory": {"serial": "X1"}})
            r = self.E.to_ops(doc, [{"action": "set_field", "cable": "A-025", "field": "length_m", "value": 3}])
            self.assertEqual(r["ops"][0], {"op": "merge", "coll": "cables", "id": "c-0084", "value": {"length_m": 3}})
            r = self.E.to_ops(doc, [{"action": "set_field", "device": "Chapel mixer", "field": "password", "value": "x"}])
            self.assertEqual(r["ops"], [])
            self.assertFalse(r["applicable"])
            self.assertTrue(r["problems"])
            # ambiguity → a problem line and no op
            r = self.E.to_ops(doc, [{"action": "remove_device", "device": "Vocal mic"}])
            self.assertEqual(r["ops"], [])
            self.assertIn("ambiguous", r["problems"][0], fr("FR-AST-13", "6.9.5a", "ambiguous name → problem, no op: %s" % r["problems"]))
            r = self.E.to_ops(doc, [{"action": "connect", "from": {"device": "Chapel wireless", "port": "Analog Out 9"}, "to": {"device": "Chapel mixer"}}])
            self.assertEqual(r["ops"], [])
            self.assertIn("no port", r["problems"][0])
            r = self.E.to_ops(doc, [{"action": "teleport", "device": "x"}, "junk"])
            self.assertEqual(len(r["problems"]), 2)
            # a change that produces an invalid doc → applicable false with the validation message
            r = self.E.to_ops(doc, [{"action": "set_field", "device": "Chapel mixer", "field": "status", "value": "broken"}])
            self.assertFalse(r["applicable"])
            r = self.E.to_ops(doc, [{"action": "set_field", "device": "Chapel mixer", "field": "name", "value": ""}])
            self.assertFalse(r["applicable"], "validation errors → applicable false")
            self.assertTrue([p for p in r["problems"] if p.startswith("validation:")], r["problems"])
            # presets and bare kinds for add_device
            r = self.E.to_ops(doc, [{"action": "add_device", "template": "wireless receiver", "name": "Spare RX", "room": "main"}])
            self.assertEqual(r["ops"][0]["value"]["kind"], "wireless_rx")
            self.assertTrue(r["ops"][0]["value"]["ports"], "preset ports expanded")
            r = self.E.to_ops(doc, [{"action": "add_device", "kind": "display", "name": "Lobby TV", "room": "main"}])
            self.assertEqual(r["ops"][0]["value"]["kind"], "display")
            r = self.E.to_ops(doc, [{"action": "add_device", "template": "no-such-thing-9000"}])
            self.assertEqual(r["ops"], [])
            self.assertTrue(r["problems"])

    def test_proposal_cache(self):
        with temp_data_dir() as data:
            pdir, doc = self._campus_doc(data)
            p = self.E.new_proposal(doc, [{"action": "move_device", "device": "spare-sm58", "room": "chapel"}], note="Move the spare", base_revision=1)
            self.assertRegex(p["id"], r"^pp-[0-9a-f]{8}$", fr("FR-AST-13", "5.10", "proposal id"))
            for k in ("summary", "ops", "applicable", "problems", "expires", "note", "base_revision"):
                self.assertIn(k, p)
            self.assertRegex(p["expires"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            self.assertEqual(self.E.get_proposal(p["id"])["ops"], p["ops"])
            self.assertIsNone(self.E.get_proposal("pp-nope0000"))
            with mock.patch("time.time", lambda: 10 ** 10):
                self.assertIsNone(self.E.get_proposal(p["id"]), "5.10 expires after 15 min")
            for i in range(self.E.PROPOSAL_CACHE_MAX + 5):
                self.E.remember({"id": "pp-%08d" % i, "ops": []})
            self.assertLessEqual(len(self.E._CACHE), self.E.PROPOSAL_CACHE_MAX, "bounded cache")

    def test_api_proposal_then_apply_then_undo(self):
        """FR-AST-13 acceptance: the question returns a proposal with ops, nothing changes before /apply, /apply is one revision, undo via restore."""
        with temp_data_dir(FATHOM_LLM_FAKE=str(FX / "propose-ulxd4d.json")) as data:
            install_campus(data, "campus")
            before = _doc(self.app)
            rev0 = before["revision"]
            with _Guard():
                st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant", {"question": Q_ULXD, "room": "chapel"}, JSON_H)
            self.assertEqual(st, 200, b[:400])
            a = jbody(b)
            self.assertTrue(a["llm"]["used"], a["llm"])
            self.assertEqual(a["llm"]["model"], "fake-tools")
            self.assertEqual([t["name"] for t in a["llm"]["tools"]], ["search", "device", "propose_changes"], fr("FR-AST-13", "5.10", "llm.tools"))
            self.assertIn("Chapel wireless 2", a["llm"]["text"])
            self.assertNotIn("suggestion", a, fr("FR-AST-13", "5.10", "proposal replaces suggestion"))
            p = a["proposal"]
            self.assertRegex(p["id"], r"^pp-[0-9a-f]{8}$")
            self.assertTrue(p["applicable"], p["problems"])
            self.assertEqual(len(p["ops"]), 2)
            self.assertEqual(p["summary"][1].split("(")[0].strip(), "Patch **Chapel wireless 2 · Analog Out 1** → **Chapel mixer · Analog In 5**")
            self.assertEqual(p["note"], "Second ULXD4D in the Chapel, patched to mixer input 5")
            self.assertEqual(p["base_revision"], rev0)
            for k in ("question", "intent", "summary", "paths", "checks", "confidence", "llm"):
                self.assertIn(k, a, "deterministic fields still present")
            blob = json.dumps(a)
            self.assertNotIn("raw", a["llm"], "5.10 provider payloads are never returned")
            self.assertLessEqual(max(len(json.dumps(t)) for t in a["llm"]["tools"]), 400)
            self.assertNotIn("FATHOM_LLM", blob)
            # nothing changed yet
            mid = _doc(self.app)
            self.assertEqual(mid["revision"], rev0, fr("FR-AST-13", "5.10", "nothing is applied before /apply"))
            self.assertEqual(len(mid["doc"]["devices"]), len(before["doc"]["devices"]))
            self.assertEqual(len(mid["doc"]["cables"]), len(before["doc"]["cables"]))
            # apply by id
            st, h, b = call(self.app, "POST", "/api/v2/projects/campus/assistant/apply", {"id": p["id"], "base_revision": rev0}, JSON_H)
            self.assertEqual(st, 200, b[:400])
            r = jbody(b)
            self.assertEqual((r["revision"], r["applied"]), (rev0 + 1, 2))
            self.assertEqual(r["summary"], p["summary"])
            self.assertEqual(h.get("etag"), '"r%d"' % (rev0 + 1))
            after = _doc(self.app)
            devs = {d["id"]: d for d in after["doc"]["devices"]}
            self.assertIn("chapel-wireless-2", devs, fr("FR-AST-13", "5.10", "/apply adds the device"))
            self.assertEqual(devs["chapel-wireless-2"]["room"], "chapel")
            cab = [c for c in after["doc"]["cables"] if c["id"] == "c-0110"]
            self.assertEqual(cab[0]["to"], {"device": "ch-mixer", "port": "analog-in-5"})
            self.assertEqual(cab[0]["tag"], "A-053")
            st, _, b = call(self.app, "GET", "/api/v2/projects/campus/history")
            entries = jbody(b)
            entries = entries.get("revisions") if isinstance(entries, dict) else entries
            top = entries[0] if entries[0].get("revision") == rev0 + 1 else [e for e in entries if e.get("revision") == rev0 + 1][0]
            self.assertEqual(top["source"], "assistant", fr("FR-AST-13", "5.10", "history source assistant"))
            self.assertTrue(top["summary"].startswith("Assistant: Second ULXD4D"), top["summary"])
            # applying the same cached id twice is just a second normal revision attempt: the put ops are idempotent
            # undo = restore the previous revision (a normal revision)
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/history/%d/restore" % rev0, {"base_revision": rev0 + 1}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            undone = _doc(self.app)
            self.assertNotIn("chapel-wireless-2", {d["id"] for d in undone["doc"]["devices"]}, fr("FR-AST-13", "5.10", "undo via history restore"))
            self.assertEqual(len(undone["doc"]["cables"]), len(before["doc"]["cables"]))
            # a stateless client can send the proposal back in full
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant/apply", {"proposal": p, "base_revision": undone["revision"]}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            self.assertIn("chapel-wireless-2", {d["id"] for d in _doc(self.app)["doc"]["devices"]})
            # unknown / expired id, bad bodies
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant/apply", {"id": "pp-deadbeef"}, JSON_H)
            self.assertEqual(st, 404)
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant/apply", {}, JSON_H)
            self.assertEqual(st, 400)
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant/apply", {"proposal": {"ops": [{"op": "zap"}]}}, JSON_H)
            self.assertEqual(st, 400)
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant/apply", {"proposal": p, "base_revision": 1}, JSON_H)
            self.assertIn(st, (200, 409), "base_revision goes through the normal conflict rules")

    def test_api_default_script_and_request_validation(self):
        with temp_data_dir(FATHOM_LLM_FAKE=str(FX / "propose-ulxd4d.json")) as data:
            install_campus(data, "campus")
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant", {"question": "what is in the chapel?", "room": "chapel"}, JSON_H)
            a = jbody(b)
            self.assertEqual(st, 200)
            self.assertTrue(a["llm"]["used"])
            self.assertNotIn("proposal", a)
            self.assertIn("suggestion", a, "no proposal → the deterministic suggestion key stays")
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant", {"question": "x", "manual_text": "y" * (20 * 1024 + 1)}, JSON_H)
            self.assertEqual(st, 400, "manual_text over 20 kB")
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant", {"question": "x", "attachments": ["att-000000000000"]}, JSON_H)
            self.assertEqual(st, 404, "attachment not in this project")
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant", {"question": "x", "attachments": "att"}, JSON_H)
            self.assertEqual(st, 400)
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant", {"question": "x", "use_llm": False}, JSON_H)
            self.assertEqual(jbody(b)["llm"], {"used": False}, "use_llm false → no provider call even with the fake wired")

    def test_apply_locked_and_viewer(self):
        users = requires("users")
        with temp_data_dir(FATHOM_LLM_FAKE=str(FX / "propose-ulxd4d.json")) as data:
            install_campus(data, "campus")
            rev0 = _doc(self.app)["revision"]
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant", {"question": Q_ULXD, "room": "chapel"}, JSON_H)
            p = jbody(b)["proposal"]
            lock = {"op": "root", "key": "settings", "value": {"locked": True}}
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/changes", {"base_revision": rev0, "ops": [lock]}, JSON_H)
            self.assertEqual(st, 200, b[:200])
            rev1 = jbody(b)["revision"]
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant/apply", {"id": p["id"], "base_revision": rev1}, JSON_H)
            self.assertEqual(st, 423, fr("FR-USER-12", "5.10", "/apply honours the editing lock: %s" % b[:200]))
            self.assertEqual(jbody(b)["code"], "locked")
            self.assertEqual(_doc(self.app)["revision"], rev1, "nothing written")
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/changes", {"base_revision": rev1, "ops": [{"op": "root", "key": "settings", "value": {"locked": False}}]}, JSON_H)
            self.assertEqual(st, 200)
        with temp_data_dir(FATHOM_LLM_FAKE=str(FX / "propose-ulxd4d.json")) as data:
            install_campus(data, "campus")
            users.add_user("vic", "vic-password-1", role="viewer")
            users.add_user("eve", "eve-password-1", role="editor")
            st, h, b = call(self.app, "POST", "/api/v2/session", {"username": "vic", "password": "vic-password-1"}, {"Content-Type": "application/json"})
            self.assertEqual(st, 200)
            vic = {"Cookie": [c for c in h.all("set-cookie") if c.startswith("fathom_session=")][0].split(";")[0], "X-Fathom": "1", "Content-Type": "application/json"}
            st, h, b = call(self.app, "POST", "/api/v2/session", {"username": "eve", "password": "eve-password-1"}, {"Content-Type": "application/json"})
            eve = {"Cookie": [c for c in h.all("set-cookie") if c.startswith("fathom_session=")][0].split(";")[0], "X-Fathom": "1", "Content-Type": "application/json"}
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant", {"question": Q_ULXD, "room": "chapel"}, vic)
            self.assertEqual(st, 200, "viewers may ask")
            a = jbody(b)
            p = a["proposal"]
            self.assertTrue(p["ops"], "a viewer still sees the proposal; applying needs editor")
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant/apply", {"id": p["id"]}, vic)
            self.assertEqual(st, 403, fr("FR-USER-02", "5.10", "viewer cannot /apply"))
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant/apply", {"proposal": p}, vic)
            self.assertEqual(st, 403)
            st, _, b = call(self.app, "POST", "/api/v2/projects/campus/assistant/apply", {"id": p["id"]}, eve)
            self.assertEqual(st, 200, b[:300])
            st, _, b = call(self.app, "GET", "/api/v2/projects/campus/history", headers=eve)
            entries = jbody(b)
            entries = entries.get("revisions") if isinstance(entries, dict) else entries
            self.assertEqual(entries[0]["author"], "eve", "the applying editor is the revision author")


if __name__ == "__main__":
    unittest.main()
