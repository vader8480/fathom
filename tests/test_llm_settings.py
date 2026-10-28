"""P4A — LLM settings: llm.json + llm-secrets.json, env precedence, admin routes, CLI (SPEC §5.10 Assistant settings, §6.9.6a)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import unittest
from unittest import mock

from _helpers import FIXTURES, call, fr, get_app, jbody, requires, temp_data_dir, temp_env
from test_security import users_env

LLM_FIX = FIXTURES / "llm"
KEY = "sk-live-SECRET-5a1b2c3d4e"
JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}


def fixture(provider, name):
    return json.loads((LLM_FIX / provider / name).read_text(encoding="utf-8"))


class ConfigFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.llm = requires("llm")
        cls.cfg = requires("llm.config")
        cls.sec = requires("llm.secrets")

    def test_defaults_and_unconfigured(self):
        with temp_data_dir():
            self.assertFalse(self.llm.configured(), fr("FR-AST-07", "6.9.6", "nothing set → not configured"))
            pub = self.cfg.public()
            self.assertEqual(pub["provider"], "")
            self.assertEqual((pub["temperature"], pub["max_tokens"], pub["web_lookup"], pub["daily_cap"]), (0.2, 700, False, 200))
            self.assertFalse(pub["api_key_set"])
            self.assertEqual(pub["source"]["provider"], "default")
            self.assertNotIn("api_key", pub)
            self.assertEqual(self.llm.info(), {"configured": False, "provider": None, "model": None, "host": None})

    def test_file_and_secret_round_trip(self):
        with temp_data_dir() as data:
            out = self.cfg.save({"provider": "anthropic", "model": "claude-sonnet-4-5", "api_key": KEY, "temperature": 0.5, "max_tokens": 900,
                                 "web_lookup": True, "daily_cap": 50}, by="ada")
            self.assertEqual(out["provider"], "anthropic")
            self.assertTrue(out["api_key_set"])
            self.assertTrue(out["configured"])
            self.assertEqual(out["updated_by"], "ada")
            self.assertTrue(out["updated"].endswith("Z"))
            self.assertEqual(out["effective_base_url"], "https://api.anthropic.com/v1")
            self.assertEqual(out["source"]["model"], "file")
            self.assertEqual(out["source"]["api_key"], "file")
            doc = json.loads((data / "llm.json").read_text())
            self.assertEqual(doc["model"], "claude-sonnet-4-5")
            self.assertNotIn("api_key", doc, fr("FR-SEC-06", "6.9.6a", "key never in llm.json"))
            self.assertNotIn(KEY, (data / "llm.json").read_text())
            sp = data / "llm-secrets.json"
            self.assertEqual(json.loads(sp.read_text()), {"api_key": KEY})
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(sp.stat().st_mode), 0o600, fr("FR-SEC-06", "6.9.6a", "secrets mode 0600"))
            self.assertFalse(list(data.glob(".llm*.tmp")), "atomic write leaves no temp file")
            eff = self.cfg.effective()
            self.assertEqual(eff["api_key"], KEY)
            self.assertEqual(eff["web_lookup"], True)
            self.assertNotIn(KEY, json.dumps(self.cfg.public()), fr("FR-SEC-06", "8.4 #8", "public() never carries the key"))
            self.assertEqual(self.llm.info(), {"configured": True, "provider": "anthropic", "model": "claude-sonnet-4-5", "host": "api.anthropic.com"})
            # api_key "" leaves it, clear_api_key removes it
            self.cfg.save({"api_key": "", "model": "claude-haiku-4-5"}, by="ada")
            self.assertEqual(self.sec.api_key(), KEY)
            self.assertEqual(self.cfg.effective()["model"], "claude-haiku-4-5")
            self.cfg.save({"clear_api_key": True}, by="ada")
            self.assertEqual(self.sec.api_key(), "")
            self.assertFalse(sp.exists(), "empty secrets file is removed")
            self.assertFalse(self.llm.configured(), "needs_key provider without a key → not configured")

    def test_validation(self):
        with temp_data_dir():
            with self.assertRaises(self.cfg.ConfigError) as cm:
                self.cfg.save({"provider": "bard"})
            self.assertEqual(cm.exception.code, "bad_enum")
            with self.assertRaises(self.cfg.ConfigError) as cm:
                self.cfg.save({"base_url": "ftp://x"})
            self.assertEqual(cm.exception.code, "bad_url")
            with self.assertRaises(self.cfg.ConfigError) as cm:
                self.cfg.save({"base_url": "localhost:11434"})
            self.assertEqual(cm.exception.code, "bad_url")
            with self.assertRaises(self.cfg.ConfigError) as cm:
                self.cfg.save({"api": "grpc"})
            self.assertEqual(cm.exception.code, "bad_enum")
            for bad in ({"temperature": 3}, {"temperature": "hot"}, {"max_tokens": 0}, {"daily_cap": -1}):
                with self.assertRaises(self.cfg.ConfigError):
                    self.cfg.save(bad)
            out = self.cfg.save({"provider": "openai_compat", "base_url": "http://localhost:11434/v1/", "model": "llama3.1"})
            self.assertEqual(out["base_url"], "http://localhost:11434/v1", "trailing slash trimmed")
            self.assertTrue(out["configured"], "openai_compat needs no key")
            out = self.cfg.save({"provider": "openai_compat", "base_url": ""})
            self.assertFalse(out["configured"], "openai_compat without a base URL is not configured")

    def test_env_overrides_field_by_field(self):
        with temp_data_dir():
            self.cfg.save({"provider": "openai", "model": "gpt-4o-mini", "api_key": KEY, "api": "responses", "temperature": 0.7})
            with temp_env(FATHOM_LLM_MODEL="gpt-4.1", FATHOM_LLM_API_KEY="sk-env-KEY", FATHOM_LLM_API="chat", FATHOM_LLM_TIMEOUT="7"):
                eff = self.cfg.effective()
                self.assertEqual((eff["provider"], eff["model"], eff["api_key"], eff["api"], eff["temperature"], eff["timeout"]),
                                 ("openai", "gpt-4.1", "sk-env-KEY", "chat", 0.7, 7.0), fr("FR-AST-07", "6.9.6a", "env wins per field"))
                pub = self.cfg.public()
                self.assertEqual(pub["source"], dict(pub["source"], provider="file", model="env", api_key="env", api="env", temperature="file"))
                self.assertNotIn("sk-env-KEY", json.dumps(pub))
                self.assertEqual(self.llm.timeout_default(), 7.0)
            with temp_env(FATHOM_LLM_PROVIDER="xai", FATHOM_LLM_URL="https://api.x.ai/v1", FATHOM_LLM_MODEL="grok-4"):
                eff = self.cfg.effective()
                self.assertEqual((eff["provider"], eff["model"], eff["api_key"]), ("xai", "grok-4", KEY), "file key still applies under an env provider")
                self.assertEqual(self.llm.info()["host"], "api.x.ai")

    def test_legacy_env_only_resolves_to_openai_compat(self):
        with temp_data_dir(FATHOM_LLM_URL="http://127.0.0.1:11434/v1", FATHOM_LLM_MODEL="llama3.1"):
            eff = self.cfg.effective()
            self.assertEqual(eff["provider"], "openai_compat", fr("FR-AST-07", "6.9.6a", "FATHOM_LLM_URL alone → openai_compat"))
            self.assertEqual(eff["source"]["provider"], "default")
            self.assertEqual(eff["source"]["base_url"], "env")
            self.assertTrue(self.llm.configured(), "today's env-only setups keep working")
            self.assertEqual(self.llm.info(), {"configured": True, "provider": "openai_compat", "model": "llama3.1", "host": "127.0.0.1:11434"})
            self.assertEqual(self.cfg.public()["effective_base_url"], "http://127.0.0.1:11434/v1")
        with temp_data_dir(FATHOM_LLM_URL="http://127.0.0.1:11434/v1"):
            self.assertFalse(self.llm.configured(), "URL without a model is not configured")

    def test_probe_config_overlays_form_values(self):
        with temp_data_dir():
            self.cfg.save({"provider": "openai", "model": "gpt-4o-mini", "api_key": KEY})
            cfg = self.cfg.probe_config({"api_key": ""})
            self.assertEqual(cfg["api_key"], KEY, "empty key → stored key")
            cfg = self.cfg.probe_config({"provider": "anthropic", "model": "claude-sonnet-4-5"})
            self.assertEqual(cfg["api_key"], "", "another provider does not inherit the stored key")
            cfg = self.cfg.probe_config({"provider": "anthropic", "api_key": " sk-ant-1 "})
            self.assertEqual(cfg["api_key"], "sk-ant-1")
            cfg = self.cfg.probe_config({"base_url": "http://localhost:1234/v1", "timeout": 3})
            self.assertEqual((cfg["provider"], cfg["base_url"], cfg["timeout"]), ("openai", "http://localhost:1234/v1", 3.0))
            with self.assertRaises(self.cfg.ConfigError):
                self.cfg.probe_config({"base_url": "nope"})


class Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        requires("llm")
        requires("server")

    def test_providers_public_shape(self):
        app = get_app()
        with temp_data_dir():
            st, _, b = call(app, "GET", "/api/v2/llm/providers")
            self.assertEqual(st, 200)
            provs = jbody(b)["providers"]
            self.assertEqual([p["id"] for p in provs], ["openai", "anthropic", "xai", "openai_compat"], fr("FR-AST-10", "5.10", "four providers"))
            for p in provs:
                self.assertTrue({"id", "label", "default_base_url", "needs_key", "lists_models", "presets"} <= set(p), p)
            self.assertEqual(provs[3]["presets"]["ollama"], "http://localhost:11434/v1")

    def test_roles(self):
        with users_env() as (app, data, cookies, pw):
            vic = {"Cookie": cookies["viewer"]}
            st, _, _ = call(app, "GET", "/api/v2/llm/providers", headers=vic)
            self.assertEqual(st, 200, "viewer may read the catalog")
            for method, path in (("GET", "/api/v2/llm/settings"), ("PUT", "/api/v2/llm/settings"), ("POST", "/api/v2/llm/models"), ("POST", "/api/v2/llm/test")):
                st, _, b = call(app, method, path, {} if method != "GET" else None, dict(vic, **JSON_H))
                self.assertEqual(st, 403, fr("FR-USER-01", "5.10", "%s %s viewer → 403" % (method, path)))
                st, _, b = call(app, method, path, {} if method != "GET" else None, {"Cookie": cookies["editor"], **JSON_H})
                self.assertEqual(st, 403, "%s %s editor → 403" % (method, path))
            st, _, b = call(app, "GET", "/api/v2/llm/settings", headers={"Cookie": cookies["admin"]})
            self.assertEqual(st, 200)

    def test_put_get_settings(self):
        with users_env() as (app, data, cookies, pw):
            adm = {"Cookie": cookies["admin"], **JSON_H}
            st, _, b = call(app, "PUT", "/api/v2/llm/settings", {"provider": "openai", "model": "gpt-4o-mini", "api_key": KEY, "api": "responses"}, adm)
            self.assertEqual(st, 200, b[:300])
            j = jbody(b)
            self.assertTrue(j["api_key_set"], fr("FR-AST-10", "5.10", "api_key_set after PUT"))
            self.assertNotIn(KEY, b.decode(), fr("FR-SEC-06", "8.4 #8", "PUT response has no key"))
            self.assertEqual(j["updated_by"], "ada")
            st, _, b = call(app, "GET", "/api/v2/llm/settings", headers={"Cookie": cookies["admin"]})
            j = jbody(b)
            self.assertEqual((j["provider"], j["model"], j["api"], j["api_key_set"], j["configured"]), ("openai", "gpt-4o-mini", "responses", True, True))
            self.assertNotIn(KEY, b.decode())
            self.assertNotIn("api_key", j)
            self.assertEqual(json.loads((data / "llm-secrets.json").read_text())["api_key"], KEY)
            # meta capabilities reflect the file config
            st, _, b = call(app, "GET", "/api/v2/meta", headers={"Cookie": cookies["admin"]})
            self.assertEqual(jbody(b)["capabilities"]["llm"], {"configured": True, "model": "gpt-4o-mini"})
            self.assertNotIn(KEY, b.decode())
            # validation
            st, _, b = call(app, "PUT", "/api/v2/llm/settings", {"provider": "bard"}, adm)
            self.assertEqual((st, jbody(b)["code"]), (400, "bad_enum"), fr("FR-AST-10", "5.10", "unknown provider → 400 bad_enum"))
            st, _, b = call(app, "PUT", "/api/v2/llm/settings", {"base_url": "file:///etc/passwd"}, adm)
            self.assertEqual((st, jbody(b)["code"]), (400, "bad_url"))
            st, _, b = call(app, "PUT", "/api/v2/llm/settings", {"temperature": 9}, adm)
            self.assertEqual(st, 400)
            # unchanged after the bad PUTs; clear the key
            st, _, b = call(app, "PUT", "/api/v2/llm/settings", {"clear_api_key": True}, adm)
            self.assertEqual((st, jbody(b)["api_key_set"], jbody(b)["configured"]), (200, False, False))

    def test_models_and_test_with_recorder(self):
        with users_env() as (app, data, cookies, pw):
            adm = {"Cookie": cookies["admin"], **JSON_H}
            st, _, b = call(app, "POST", "/api/v2/llm/models", {}, adm)
            self.assertEqual((st, jbody(b)["code"]), (400, "not_configured"), "no provider yet → 400, no network")
            st, _, b = call(app, "POST", "/api/v2/llm/models", {"provider": "openai_compat"}, adm)
            self.assertEqual((st, jbody(b)["code"]), (400, "bad_url"), "openai_compat needs a base URL")
            seen = []

            def get_json(url, headers, timeout=None):
                seen.append(("GET", url, headers))
                return 200, fixture("openai", "models.json")["response"]

            def post_json(url, body, headers, timeout=None):
                seen.append(("POST", url, headers, body))
                return 200, fixture("openai", "test-ok.json")["response"]

            with mock.patch.multiple("fathom.llm.http", get_json=get_json, post_json=post_json):
                st, _, b = call(app, "POST", "/api/v2/llm/models", {"provider": "openai", "api_key": KEY}, adm)
                self.assertEqual(st, 200, b[:300])
                self.assertEqual(jbody(b)["models"], ["gpt-4.1", "gpt-4o-mini", "gpt-5"], fr("FR-AST-10", "5.10", "unsaved form values allowed"))
                self.assertEqual(seen[-1][1], "https://api.openai.com/v1/models")
                self.assertEqual(seen[-1][2]["Authorization"], "Bearer " + KEY)
                st, _, b = call(app, "POST", "/api/v2/llm/test", {"provider": "openai", "api_key": KEY, "model": "gpt-4o-mini"}, adm)
                self.assertEqual(st, 200, b[:300])
                j = jbody(b)
                self.assertEqual((j["ok"], j["model"], j["detail"], j["provider"]), (True, "gpt-4o-mini", "OK", "openai"))
                self.assertIsInstance(j["latency_ms"], int)
                self.assertEqual(seen[-1][3]["messages"], [{"role": "user", "content": "Say OK"}])
                # saved key is used when the form sends an empty one
                call(app, "PUT", "/api/v2/llm/settings", {"provider": "openai", "model": "gpt-4o-mini", "api_key": KEY}, adm)
                st, _, b = call(app, "POST", "/api/v2/llm/models", {"provider": "openai", "api_key": ""}, adm)
                self.assertEqual(st, 200)
                self.assertEqual(seen[-1][2]["Authorization"], "Bearer " + KEY, "empty key → stored key")
                self.assertNotIn(KEY, b.decode())

            def get_401(url, headers, timeout=None):
                return 401, fixture("openai", "error-401.json")["response"]

            with mock.patch("fathom.llm.http.get_json", get_401):
                st, _, b = call(app, "POST", "/api/v2/llm/models", {"provider": "openai", "api_key": KEY}, adm)
                self.assertEqual(st, 502, fr("FR-AST-10", "5.10", "upstream error → 502"))
                j = jbody(b)
                self.assertEqual((j["error"], j["code"], j["status"]), ("upstream", "upstream", 401))
                self.assertIn("401", j["detail"])
                self.assertNotIn(KEY, b.decode(), fr("FR-SEC-06", "8.4 #8", "502 detail is redacted"))
                self.assertNotIn("sk-test-SECRET-KEY-91c2", b.decode(), "upstream echo of another key is truncated/redacted too")

    def test_test_unreachable_is_502_and_quick(self):
        import time
        with users_env() as (app, data, cookies, pw):
            adm = {"Cookie": cookies["admin"], **JSON_H}
            t0 = time.monotonic()
            st, _, b = call(app, "POST", "/api/v2/llm/test", {"provider": "openai_compat", "base_url": "http://127.0.0.1:9/v1", "model": "x", "timeout": 2}, adm)
            dt = time.monotonic() - t0
            self.assertEqual(st, 502, b[:300])
            j = jbody(b)
            self.assertFalse(j["ok"])
            self.assertEqual(j["code"], "upstream")
            self.assertIn("unreachable", j["detail"])
            self.assertLess(dt, 5, fr("FR-AST-10", "5.10", "unreachable → 502 quickly (timeout honoured)"))
            st, _, b = call(app, "POST", "/api/v2/llm/test", {"provider": "openai_compat", "base_url": "http://127.0.0.1:9/v1"}, adm)
            self.assertEqual(st, 502, "no model: falls back to listing models, still 502 when unreachable")

    def test_models_not_supported(self):
        with users_env() as (app, data, cookies, pw):
            adm = {"Cookie": cookies["admin"], **JSON_H}
            with mock.patch.object(requires("llm.providers.openai:OpenAIProvider"), "lists_models", False):
                st, _, b = call(app, "POST", "/api/v2/llm/models", {"provider": "openai", "api_key": KEY}, adm)
            self.assertEqual((st, jbody(b)["code"]), (400, "not_supported"))

    def test_no_secret_in_openapi_or_meta(self):
        with users_env(FATHOM_LLM_PROVIDER="anthropic", FATHOM_LLM_MODEL="claude-sonnet-4-5", FATHOM_LLM_API_KEY=KEY) as (app, data, cookies, pw):
            for path in ("/api/v2/meta", "/api/openapi.json", "/api/v2/llm/settings", "/api/v2/llm/providers"):
                st, _, b = call(app, "GET", path, headers={"Cookie": cookies["admin"]})
                self.assertEqual(st, 200, path)
                self.assertNotIn(KEY.encode(), b, fr("FR-SEC-06", "8.4 #8", path))
            st, _, b = call(app, "GET", "/api/openapi.json")
            paths = jbody(b)["paths"]
            for p in ("/api/v2/llm/providers", "/api/v2/llm/settings", "/api/v2/llm/models", "/api/v2/llm/test"):
                self.assertIn(p, paths, fr("FR-EXT-04", "5.14", p))
            self.assertEqual(paths["/api/v2/llm/settings"]["put"]["x-fathom-role"], "admin")
            self.assertEqual(paths["/api/v2/llm/settings"]["put"]["tags"], ["assistant"])
            st, _, b = call(app, "GET", "/api/v2/llm/settings", headers={"Cookie": cookies["admin"]})
            j = jbody(b)
            self.assertEqual((j["provider"], j["api_key_set"], j["source"]["api_key"]), ("anthropic", True, "env"))


class Cli(unittest.TestCase):
    def run_cli(self, argv):
        cli = requires("cli")
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(argv)
            except SystemExit as e:
                code = e.code or 0
        return code, out.getvalue(), err.getvalue()

    def test_show_models_test(self):
        requires("llm")
        with temp_data_dir():
            code, out, err = self.run_cli(["llm", "show"])
            self.assertEqual(code, 0, err)
            self.assertIn("configured          no", out)
            requires("llm.config").save({"provider": "openai", "model": "gpt-4o-mini", "api_key": KEY})
            code, out, err = self.run_cli(["llm", "show", "--json"])
            self.assertEqual(code, 0)
            j = json.loads(out)
            self.assertEqual((j["provider"], j["api_key_set"], j["configured"]), ("openai", True, True))
            self.assertNotIn(KEY, out, fr("FR-SEC-06", "8.4 #8", "CLI never prints the key"))
            code, out, err = self.run_cli(["llm", "show"])
            self.assertNotIn(KEY, out + err)
            self.assertIn("api_key             set", out)

            def get_json(url, headers, timeout=None):
                return 200, fixture("openai", "models.json")["response"]

            def post_json(url, body, headers, timeout=None):
                return 200, fixture("openai", "test-ok.json")["response"]

            with mock.patch.multiple("fathom.llm.http", get_json=get_json, post_json=post_json):
                code, out, err = self.run_cli(["llm", "models"])
                self.assertEqual((code, out.split()), (0, ["gpt-4.1", "gpt-4o-mini", "gpt-5"]))
                code, out, err = self.run_cli(["llm", "test"])
                self.assertEqual(code, 0, err)
                self.assertTrue(out.startswith("ok: OpenAI · gpt-4o-mini ·"), out)
                code, out, err = self.run_cli(["llm", "test", "--json", "--model", "gpt-4.1"])
                self.assertEqual(json.loads(out)["model"], "gpt-4.1")
            code, out, err = self.run_cli(["llm", "test", "--provider", "openai_compat", "--url", "http://127.0.0.1:9/v1", "--model", "x"])
            self.assertEqual(code, 2, "unreachable → exit 2")
            self.assertIn("FAILED", out)
            code, out, err = self.run_cli(["llm", "models", "--provider", "openai_compat"])
            self.assertEqual(code, 1)
            self.assertIn("base URL", err)


if __name__ == "__main__":
    unittest.main()
