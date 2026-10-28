"""P4A — fathom.llm providers against recorded fixtures (SPEC §6.9.6a). No sockets are opened anywhere in this module."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _helpers import FIXTURES, fr, requires

LLM_FIX = FIXTURES / "llm"
KEY = "sk-test-SECRET-KEY-91c2"
SYSTEM = "You are Fathom's AV/lighting troubleshooting assistant."
QUESTION = "What feeds the ATEM Mini?"
TOOL_OUT = json.dumps({"paths": ["Audio Rack 1 · Stream → ATEM Mini · Stream"]})

# provider id -> (fixture dir, config, chat path suffix, models path suffix)
CASES = {
    "openai": ("openai", {"provider": "openai", "api_key": KEY, "model": "gpt-4o-mini"}, "/v1/chat/completions", "/v1/models"),
    "openai-responses": ("openai-responses", {"provider": "openai", "api_key": KEY, "model": "gpt-4.1", "api": "responses"}, "/v1/responses", "/v1/models"),
    "anthropic": ("anthropic", {"provider": "anthropic", "api_key": KEY, "model": "claude-sonnet-4-5"}, "/v1/messages", "/v1/models"),
    "xai": ("xai", {"provider": "xai", "api_key": KEY, "model": "grok-4"}, "/v1/chat/completions", "/v1/models"),
    "openai_compat": ("openai_compat", {"provider": "openai_compat", "base_url": "http://localhost:11434/v1", "model": "llama3.1:latest"},
                      "/v1/chat/completions", "/v1/models"),
}


class _NoSocket(socket.socket):
    """Replacement for ``socket.socket`` that refuses to open anything (a subclass, so ``ssl`` keeps importing)."""

    def __init__(self, *a, **k):  # noqa: D401
        raise AssertionError("P4A: socket opened during an LLM provider test")


def subset(expected, actual, path="$"):
    """Every key/element of ``expected`` must be present and equal in ``actual`` (dicts recurse; lists match by index and length)."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), "%s: expected an object, got %r" % (path, actual)
        for k, v in expected.items():
            assert k in actual, "%s: missing key %r (have %s)" % (path, k, sorted(actual))
            subset(v, actual[k], "%s.%s" % (path, k))
    elif isinstance(expected, list):
        assert isinstance(actual, list), "%s: expected a list, got %r" % (path, actual)
        assert len(expected) == len(actual), "%s: expected %d items, got %d: %r" % (path, len(expected), len(actual), actual)
        for i, (e, a) in enumerate(zip(expected, actual)):
            subset(e, a, "%s[%d]" % (path, i))
    else:
        assert expected == actual, "%s: expected %r, got %r" % (path, expected, actual)


class Recorder:
    """Stands in for ``fathom.llm.http.post_json/get_json/post_stream``: asserts the request subset, returns the fixture."""

    def __init__(self, test, fixdir):
        self.test = test
        self.dir = LLM_FIX / fixdir
        self.queue = []
        self.calls = []

    def expect(self, name, path_suffix):
        self.queue.append((name, path_suffix))
        return self

    def load(self, name):
        p = self.dir / name
        if name.endswith(".sse"):
            return {"request": {"stream": True}, "status": 200, "sse": p.read_text(encoding="utf-8")}
        return json.loads(p.read_text(encoding="utf-8"))

    def _next(self, kind, url, body, headers):
        self.test.assertTrue(self.queue, "unexpected %s %s" % (kind, url))
        name, suffix = self.queue.pop(0)
        self.test.assertTrue(url.endswith(suffix), "%s: %s should end with %s" % (name, url, suffix))
        fx = self.load(name)
        if body is not None:
            subset(fx.get("request") or {}, body)
        self.calls.append({"kind": kind, "url": url, "body": body, "headers": dict(headers or {}), "fixture": name})
        return fx

    def post_json(self, url, body, headers, timeout=None):
        fx = self._next("POST", url, body, headers)
        return fx["status"], fx["response"]

    def get_json(self, url, headers, timeout=None):
        fx = self._next("GET", url, None, headers)
        return fx["status"], fx["response"]

    def post_stream(self, url, body, headers, timeout=None):
        from fathom.llm.http import iter_sse

        fx = self._next("STREAM", url, body, headers)
        return iter_sse(fx["sse"])

    def patch(self):
        return mock.patch.multiple("fathom.llm.http", post_json=self.post_json, get_json=self.get_json, post_stream=self.post_stream)


class ProviderFixtures(unittest.TestCase):
    """Text, tool call, tool result, finish mapping, models, test_connection, 401 and streaming — for every provider."""

    @classmethod
    def setUpClass(cls):
        cls.llm = requires("llm")
        cls.base = requires("llm.base")
        cls.providers = requires("llm.providers")
        cls._sock = mock.patch.object(socket, "socket", _NoSocket)
        cls._sock.start()

    @classmethod
    def tearDownClass(cls):
        cls._sock.stop()

    def prov(self, case):
        fixdir, cfg, chat, models = CASES[case]
        return self.providers.make(cfg), Recorder(self, fixdir), chat, models

    def tool(self):
        return self.base.ToolSpec(name="trace_device", description="Trace the signal paths that end at a device.",
                                  parameters={"type": "object", "properties": {"device": {"type": "string", "description": "device id"}},
                                              "required": ["device"]})

    def msgs(self):
        return [self.base.Message("system", SYSTEM), self.base.Message("user", QUESTION)]

    def test_catalog(self):
        cat = self.providers.catalog()
        self.assertEqual([c["id"] for c in cat], ["openai", "anthropic", "xai", "openai_compat"], fr("FR-AST-10", "6.9.6a", "four providers"))
        for c in cat:
            self.assertEqual(set(c) >= {"id", "label", "default_base_url", "needs_key", "lists_models", "presets"}, True, c)
        by = {c["id"]: c for c in cat}
        self.assertEqual(by["openai"]["default_base_url"], "https://api.openai.com/v1")
        self.assertEqual(by["anthropic"]["default_base_url"], "https://api.anthropic.com/v1")
        self.assertEqual(by["xai"]["default_base_url"], "https://api.x.ai/v1")
        self.assertEqual(by["openai_compat"]["default_base_url"], "")
        self.assertFalse(by["openai_compat"]["needs_key"])
        self.assertEqual(by["openai_compat"]["presets"], {"ollama": "http://localhost:11434/v1", "lmstudio": "http://localhost:1234/v1",
                                                          "vllm": "http://localhost:8000/v1", "llamacpp": "http://localhost:8080/v1"})
        self.assertEqual(by["openai"]["apis"], ["chat", "responses"])
        with self.assertRaises(self.llm.LLMError) as cm:
            self.providers.make({"provider": "bard"})
        self.assertEqual(cm.exception.code, "bad_enum")

    def test_text_reply_every_provider(self):
        for case in CASES:
            with self.subTest(provider=case):
                p, rec, chat, _ = self.prov(case)
                rec.expect("chat-text.json", chat)
                with rec.patch():
                    reply = p.chat(self.msgs(), model=p.model, temperature=0.2, max_tokens=700)
                self.assertEqual(reply.text, "The ATEM Mini is fed by Audio Rack 1 on its Stream input.")
                self.assertEqual(reply.finish, "stop", fr("FR-AST-10", "6.9.6a", "finish stop"))
                self.assertEqual(reply.tool_calls, [])
                self.assertEqual(reply.usage, {"input": 31, "output": 14})
                self.assertTrue(reply.raw)
                h = rec.calls[0]["headers"]
                self.assertNotIn("stream", {k.lower() for k in h})
                self.assertEqual(h["Content-Type"], "application/json")
                if case == "anthropic":
                    self.assertEqual(h["x-api-key"], KEY)
                    self.assertEqual(h["anthropic-version"], "2023-06-01")
                    self.assertNotIn("Authorization", h)
                elif case == "openai_compat":
                    self.assertNotIn("Authorization", h, "no key → no Authorization header")
                else:
                    self.assertEqual(h["Authorization"], "Bearer " + KEY)

    def test_tool_call_normalised(self):
        for case in CASES:
            with self.subTest(provider=case):
                p, rec, chat, _ = self.prov(case)
                rec.expect("chat-toolcall.json", chat)
                with rec.patch():
                    reply = p.chat(self.msgs(), [self.tool()], model=p.model)
                self.assertEqual(reply.finish, "tool_calls", fr("FR-AST-10", "6.9.6a", "finish tool_calls"))
                self.assertEqual(len(reply.tool_calls), 1)
                tc = reply.tool_calls[0]
                self.assertEqual(tc.name, "trace_device")
                self.assertEqual(tc.arguments, {"device": "atem-mini"}, "arguments parsed to a dict")
                self.assertTrue(tc.id)
                self.assertEqual(tc.raw and json.loads(tc.raw), {"device": "atem-mini"})
                body = rec.calls[0]["body"]
                if case == "anthropic":
                    self.assertEqual(body["tools"][0]["input_schema"]["required"], ["device"])
                    self.assertEqual(body["system"], SYSTEM, "system merged into the top-level string")
                    self.assertEqual(body["messages"][0]["role"], "user")
                    self.assertEqual(reply.text, "Let me trace that.")
                elif case == "openai-responses":
                    self.assertEqual(body["tools"][0]["name"], "trace_device")
                    self.assertEqual(body["instructions"], SYSTEM)
                    self.assertEqual(body["max_output_tokens"], 700)
                else:
                    self.assertEqual(body["tools"][0]["type"], "function")
                    self.assertEqual(body["tools"][0]["function"]["parameters"]["required"], ["device"])
                    self.assertEqual(body["messages"][0], {"role": "system", "content": SYSTEM})

    def test_tool_result_round_trip(self):
        for case in CASES:
            with self.subTest(provider=case):
                p, rec, chat, _ = self.prov(case)
                rec.expect("chat-toolcall.json", chat).expect("chat-toolresult.json", chat)
                with rec.patch():
                    first = p.chat(self.msgs(), [self.tool()], model=p.model)
                    tc = first.tool_calls[0]
                    convo = self.msgs() + [self.base.Message("assistant", first.text, tool_calls=first.tool_calls),
                                           self.base.Message("tool", TOOL_OUT, tool_call_id=tc.id, name=tc.name)]
                    second = p.chat(convo, [self.tool()], model=p.model)
                self.assertEqual(second.text, "Audio Rack 1 feeds the ATEM Mini's Stream input.")
                self.assertEqual(second.finish, "stop")
                body = rec.calls[1]["body"]
                if case == "anthropic":
                    turn = body["messages"][-1]
                    self.assertEqual(turn["role"], "user", "tool results are a user turn")
                    self.assertEqual(turn["content"][0]["type"], "tool_result")
                    self.assertEqual(turn["content"][0]["tool_use_id"], "toolu_01P4A")
                    self.assertEqual(body["messages"][-2]["content"][-1], {"type": "tool_use", "id": "toolu_01P4A", "name": "trace_device",
                                                                           "input": {"device": "atem-mini"}})
                elif case == "openai-responses":
                    self.assertEqual(body["input"][-1], {"type": "function_call_output", "call_id": "call_p4a_1", "output": TOOL_OUT})
                    self.assertEqual(body["input"][-2]["type"], "function_call")
                    self.assertNotIn("system", [i.get("role") for i in body["input"]], "system text travels as instructions")
                else:
                    self.assertEqual(body["messages"][-1], {"role": "tool", "tool_call_id": "call_p4a_1", "content": TOOL_OUT})
                    ast = body["messages"][-2]
                    self.assertEqual(ast["tool_calls"][0]["function"]["name"], "trace_device")
                    self.assertEqual(json.loads(ast["tool_calls"][0]["function"]["arguments"]), {"device": "atem-mini"},
                                     "arguments serialised back as a JSON string")

    def test_anthropic_consecutive_tool_results_collapse(self):
        p, rec, chat, _ = self.prov("anthropic")
        M, TC = self.base.Message, self.base.ToolCall
        convo = [M("system", SYSTEM), M("user", QUESTION),
                 M("assistant", "", tool_calls=[TC("toolu_1", "trace_device", {"device": "a"}), TC("toolu_2", "trace_device", {"device": "b"})]),
                 M("tool", "A", tool_call_id="toolu_1"), M("tool", "B", tool_call_id="toolu_2"), M("user", "And then?")]
        split = requires("llm.providers.anthropic:split_messages")(convo)
        self.assertEqual([m["role"] for m in split["messages"]], ["user", "assistant", "user"], fr("FR-AST-10", "6.9.6a", "one user turn"))
        last = split["messages"][-1]["content"]
        self.assertEqual([b["type"] for b in last], ["tool_result", "tool_result", "text"])
        self.assertEqual(last[1]["tool_use_id"], "toolu_2")
        self.assertEqual(split["system"], SYSTEM)

    def test_finish_length_and_other(self):
        for case in CASES:
            with self.subTest(provider=case):
                p, rec, chat, _ = self.prov(case)
                rec.expect("chat-length.json", chat)
                with rec.patch():
                    reply = p.chat(self.msgs(), model=p.model, max_tokens=5)
                self.assertEqual(reply.finish, "length", fr("FR-AST-10", "6.9.6a", "max_tokens/length → length"))
                self.assertEqual(reply.text, "The ATEM")
        self.assertEqual(self.base.norm_finish("content_filter"), "other")

    def test_invalid_json_arguments(self):
        for case in ("openai", "openai-responses", "xai", "openai_compat"):
            with self.subTest(provider=case):
                p, rec, chat, _ = self.prov(case)
                rec.expect("chat-badjson.json", chat)
                with rec.patch():
                    reply = p.chat(self.msgs(), [self.tool()], model=p.model)
                tc = reply.tool_calls[0]
                self.assertEqual(tc.arguments, {"_raw": '{"device": atem-mini'}, fr("FR-AST-10", "6.9.6a", "invalid JSON → _raw"))
                self.assertEqual(self.base.arguments_string(tc), '{"device": atem-mini', "raw text is what goes back upstream")

    def test_list_models(self):
        want = {"openai": ["gpt-4.1", "gpt-4o-mini", "gpt-5"], "openai-responses": ["gpt-4.1", "gpt-4o-mini"],
                "anthropic": ["claude-haiku-4-5", "claude-sonnet-4-5"], "xai": ["grok-3-mini", "grok-4"],
                "openai_compat": ["llama3.1:latest", "qwen2.5:7b"]}
        for case in CASES:
            with self.subTest(provider=case):
                p, rec, _, models = self.prov(case)
                rec.expect("models.json", models if case != "anthropic" else "/v1/models?limit=1000")
                with rec.patch():
                    self.assertEqual(p.list_models(), want[case], fr("FR-AST-10", "6.9.6a", "ids sorted"))
                self.assertEqual(rec.calls[0]["kind"], "GET")
        p, rec, _, _ = self.prov("openai_compat")
        with mock.patch("fathom.llm.http.get_json", lambda url, headers, timeout=None: (404, {"_text": "not found"})):
            self.assertEqual(p.list_models(), [], "openai_compat tolerates a 404 on /models")
        p, rec, _, _ = self.prov("openai")
        with mock.patch("fathom.llm.http.get_json", lambda url, headers, timeout=None: (404, {"_text": "not found"})):
            with self.assertRaises(self.llm.LLMError):
                p.list_models()

    def test_test_connection(self):
        for case in CASES:
            with self.subTest(provider=case):
                p, rec, chat, _ = self.prov(case)
                rec.expect("test-ok.json", chat)
                with rec.patch():
                    res = p.test_connection()
                self.assertTrue(res["ok"], res)
                self.assertEqual(res["detail"], "OK")
                self.assertEqual(res["model"], p.model)
                self.assertIsInstance(res["latency_ms"], int)
                self.assertTrue(res["detail"])
                self.assertEqual(rec.calls[0]["body"]["model"], p.model)
                sent = json.dumps(rec.calls[0]["body"])
                self.assertIn("Say OK", sent, fr("FR-AST-10", "6.9.6a", "1-token chat"))
                rec.expect("error-401.json", chat)
                with rec.patch():
                    res = p.test_connection()
                self.assertFalse(res["ok"])
                self.assertIn("401", res["detail"])
                self.assertNotIn(KEY, res["detail"])

    def test_401_is_llmerror_without_key(self):
        for case in CASES:
            with self.subTest(provider=case):
                p, rec, chat, _ = self.prov(case)
                rec.expect("error-401.json", chat)
                with rec.patch(), self.assertRaises(self.llm.LLMError) as cm:
                    p.chat(self.msgs(), model=p.model)
                exc = cm.exception
                self.assertEqual(exc.status, 401, fr("FR-SEC-06", "6.9.6a", "status kept"))
                self.assertEqual(exc.code, "unauthorized")
                self.assertIn("401", str(exc))
                self.assertNotIn(KEY, str(exc), fr("FR-SEC-06", "8.4 #8", "key never in the message"))
                if case != "openai_compat":  # the hosted fixtures echo the key back; it must come out masked
                    self.assertIn("••••", str(exc), "echoed key is masked")

    def test_streaming_assembles_same_reply(self):
        for case in CASES:
            with self.subTest(provider=case):
                p, rec, chat, _ = self.prov(case)
                rec.expect("chat-text.json", chat).expect("stream-text.sse", chat)
                deltas = []
                with rec.patch():
                    plain = p.chat(self.msgs(), model=p.model)
                    streamed = p.chat(self.msgs(), model=p.model, stream=True, on_delta=deltas.append)
                self.assertTrue(rec.calls[1]["body"]["stream"] is True)
                self.assertEqual(rec.calls[1]["kind"], "STREAM")
                self.assertEqual(streamed.text, plain.text, fr("FR-AST-10", "6.9.6a", "stream text == plain text"))
                self.assertEqual("".join(deltas), plain.text, "on_delta saw every chunk")
                self.assertEqual(len(deltas), 3)
                self.assertEqual(streamed.finish, "stop")
                self.assertEqual(streamed.tool_calls, [])
                self.assertEqual(streamed.usage, plain.usage)
                rec.expect("chat-toolcall.json", chat).expect("stream-toolcall.sse", chat)
                with rec.patch():
                    plain = p.chat(self.msgs(), [self.tool()], model=p.model)
                    streamed = p.chat(self.msgs(), [self.tool()], model=p.model, stream=True)
                self.assertEqual(streamed.finish, "tool_calls")
                self.assertEqual([(c.id, c.name, c.arguments) for c in streamed.tool_calls],
                                 [(c.id, c.name, c.arguments) for c in plain.tool_calls], "tool-call fragments reassembled")
                self.assertEqual(streamed.text, plain.text)

    def test_sse_parser(self):
        iter_sse = requires("llm.http:iter_sse")
        body = ": comment\nevent: a\ndata: 1\ndata: 2\n\ndata: {\"x\":1}\r\n\r\ndata: [DONE]\n"
        self.assertEqual(list(iter_sse(body)), [("a", "1\n2"), ("", '{"x":1}'), ("", "[DONE]")])
        self.assertEqual(list(iter_sse([b"data: z\n", b"\n"])), [("", "z")])

    def test_openai_reasoning_models_drop_temperature(self):
        p, rec, chat, _ = self.prov("openai")
        captured = {}

        def rec_post(url, body, headers, timeout=None):
            captured.clear()
            captured.update(body)
            return 200, {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

        with mock.patch("fathom.llm.http.post_json", rec_post):
            p.chat(self.msgs(), model="gpt-5-mini")
            self.assertNotIn("temperature", captured)
            self.assertEqual(captured["max_completion_tokens"], 700)
            p.chat(self.msgs(), model="gpt-4o-mini")
            self.assertEqual(captured["temperature"], 0.2)

    def test_legacy_dict_messages_and_chat_tools_facade(self):
        """``llm.chat`` keeps the {role, content} contract; ``llm.chat_tools`` returns a Reply — both through the configured provider."""
        from _helpers import temp_data_dir
        with temp_data_dir(FATHOM_LLM_URL="http://localhost:11434/v1", FATHOM_LLM_MODEL="llama3.1:latest"):
            self.assertTrue(self.llm.configured(), fr("FR-AST-07", "6.9.6", "legacy env-only setup still configured"))
            self.assertEqual(self.llm.info(), {"configured": True, "provider": "openai_compat", "model": "llama3.1:latest", "host": "localhost:11434"})
            rec = Recorder(self, "openai_compat").expect("chat-text.json", "/v1/chat/completions").expect("chat-toolcall.json", "/v1/chat/completions")
            with rec.patch():
                text = self.llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}])
                reply = self.llm.chat_tools(self.msgs(), [self.tool()])
            self.assertEqual(text, "The ATEM Mini is fed by Audio Rack 1 on its Stream input.")
            self.assertIs(rec.calls[0]["body"]["stream"], False)
            self.assertEqual(reply.tool_calls[0].arguments, {"device": "atem-mini"})
            self.assertEqual(rec.calls[1]["body"]["model"], "llama3.1:latest")

    def test_http_guards(self):
        http = requires("llm.http")
        with self.assertRaises(self.llm.LLMError) as cm:
            http.post_json("ftp://example.invalid/x", {}, {}, 1)
        self.assertEqual(cm.exception.code, "bad_url")
        with self.assertRaises(self.llm.LLMError) as cm:
            http.post_json("https://example.invalid/x", {"big": "x" * (http.MAX_REQUEST + 1)}, {"Authorization": "Bearer " + KEY}, 1)
        self.assertEqual(cm.exception.code, "too_large")
        self.assertNotIn(KEY, str(cm.exception))


class NoNetworkGuard(unittest.TestCase):
    def test_module_runs_without_sockets(self):
        """Run this whole module in a child interpreter whose socket.socket raises: every test still passes."""
        requires("llm")
        code = ("import socket, ssl, sys, unittest, unittest.mock\n"
                "class NoSocket(socket.socket):\n"
                "    def __init__(self, *a, **k): raise AssertionError('socket opened')\n"
                "def boom(*a, **k): raise AssertionError('socket opened')\n"
                "socket.socket = NoSocket\n"
                "socket.create_connection = boom\n"
                "sys.path.insert(0, %r)\n"
                "import test_llm_providers as m\n"
                "suite = unittest.defaultTestLoader.loadTestsFromTestCase(m.ProviderFixtures)\n"
                "res = unittest.TextTestRunner(verbosity=0, stream=sys.stderr).run(suite)\n"
                "sys.exit(0 if res.wasSuccessful() and res.testsRun > 10 else 1)\n") % str(Path(__file__).resolve().parent)
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=str(Path(__file__).resolve().parent.parent))
        self.assertEqual(proc.returncode, 0, fr("FR-AST-10", "6.9.6a", "no network in provider tests:\n" + proc.stderr[-3000:]))


if __name__ == "__main__":
    unittest.main()
