"""“Suggest an improvement” (SPEC FR-USER-13, §5.16 ``kind``): problem reports with ``kind=suggestion``, the
``?kind=`` filter, the device note wording, forwarding to ``settings.suggest_url`` / ``FATHOM_SUGGEST_URL`` and the
server-level admin listing ``GET /api/v2/suggestions``."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    from _helpers import basic, call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir, temp_env
except ImportError:  # pragma: no cover
    from tests._helpers import basic, call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir, temp_env

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}


class _Receiver:
    """A local HTTP endpoint that records the JSON bodies posted to it."""

    def __init__(self, status=200):
        self.received = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                outer.received.append({"path": self.path, "ctype": self.headers.get("Content-Type"),
                                       "body": json.loads(self.rfile.read(n).decode("utf-8") or "null")})
                self.send_response(status)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):  # silence
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/hook" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def _problems(app, name="proj", query=""):
    st, _, b = call(app, "GET", "/api/v2/projects/%s/problems%s" % (name, query))
    assert st == 200, b[:200]
    return jbody(b)


class SuggestionKind(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        requires("server")

    def test_kind_stored_defaulted_filtered(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems", {"text": "Hum on the PA"}, JSON_H)
            self.assertEqual(st, 201, b[:200])
            self.assertEqual(jbody(b)["problem"]["kind"], "problem", fr("FR-USER-13", "5.16", "kind defaults to problem"))
            self.assertNotIn("forwarded", jbody(b), "plain problems are never forwarded")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems", {"text": "Label the stage box ports", "kind": "suggestion"}, JSON_H)
            self.assertEqual(st, 201, b[:200])
            r = jbody(b)
            self.assertEqual((r["problem"]["kind"], r["problem"]["status"], r["forwarded"]), ("suggestion", "open", False))
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems", {"text": "x", "kind": "rant"}, JSON_H)
            self.assertEqual((st, jbody(b)["code"]), (400, "bad_enum"))
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems", {"kind": "suggestion"}, JSON_H)
            self.assertEqual((st, jbody(b)["code"]), (400, "missing_field"))
            allp = _problems(self.app)
            self.assertEqual(sorted(p["kind"] for p in allp["problems"]), ["problem", "suggestion"])
            self.assertEqual((allp["open"], allp["open_suggestions"]), (1, 1), "open counts problems only; suggestions have their own count")
            sug = _problems(self.app, query="?kind=suggestion")
            self.assertEqual([p["text"] for p in sug["problems"]], ["Label the stage box ports"], fr("FR-USER-13", "5.16", "?kind=suggestion filters"))
            self.assertEqual([p["text"] for p in _problems(self.app, query="?kind=problem")["problems"]], ["Hum on the PA"])
            stored = json.loads((data / "projects" / "proj" / "project.json").read_text())
            self.assertEqual(sorted(p["kind"] for p in stored["problems"]), ["problem", "suggestion"], "kind is stored on the entry")
            self.assertEqual(stored["problems"][1]["kind"], "suggestion")
            # legacy entries without a kind count as problems
            self.assertEqual([p["text"] for p in _problems(self.app, query="?kind=problem")["problems"]], ["Hum on the PA"])

    def test_device_note_wording_and_status_ignored(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            dev = sunday_doc()["devices"][0]["id"]
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems",
                            {"text": "Move it to the FOH rack", "kind": "suggestion", "device": dev, "device_status": "retired"}, JSON_H)
            self.assertEqual(st, 201, b[:200])
            self.assertTrue(jbody(b)["noted"], "editors' suggestions on a device are noted on the device")
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj")
            d = next(x for x in jbody(b)["doc"]["devices"] if x["id"] == dev)
            self.assertRegex(d.get("note") or "", r"\[\d{4}-\d\d-\d\d \d\d:\d\d local\] Suggestion: Move it to the FOH rack$",
                             fr("FR-USER-13", "5.16", "note line reads Suggestion:"))
            self.assertNotEqual(d.get("status"), "retired", "device_status is ignored for suggestions")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems", {"text": "Dead channel", "device": dev, "device_status": "retired"}, JSON_H)
            self.assertEqual(st, 201)
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj")
            d = next(x for x in jbody(b)["doc"]["devices"] if x["id"] == dev)
            self.assertIn("] Problem: Dead channel", d["note"], "problems keep the Problem: wording")
            self.assertEqual(d["status"], "retired", "and still set the device status")
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj/history")
            summaries = [h["summary"] for h in jbody(b)["revisions"]] if "revisions" in jbody(b) else [h["summary"] for h in jbody(b)["history"]]
            self.assertTrue(any(s.startswith("Suggestion: Move it") for s in summaries), summaries)


class SuggestionForwarding(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        requires("server")

    def test_forward_to_project_setting_url(self):
        with _Receiver() as rx, temp_data_dir() as data:
            doc = sunday_doc()
            doc["settings"]["suggest_url"] = rx.url
            doc["settings"]["public_url"] = "https://av.example.org"
            install_sunday(data, "proj")
            (data / "projects" / "proj" / "project.json").write_text(json.dumps(doc))
            dev = doc["devices"][0]["id"]
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems",
                            {"text": "Add a spare mic", "kind": "suggestion", "device": dev, "name": "Sam"}, JSON_H)
            self.assertEqual(st, 201, b[:300])
            self.assertTrue(jbody(b)["forwarded"], fr("FR-USER-13", "5.16", "forwarded: true when the hook accepted it"))
            self.assertEqual(len(rx.received), 1)
            got = rx.received[0]
            self.assertEqual(got["path"], "/hook")
            self.assertIn("application/json", got["ctype"])
            body = got["body"]
            self.assertEqual(set(body), {"project", "kind", "text", "name", "device", "page", "url"}, fr("FR-USER-13", "5.16", "forward payload keys"))
            self.assertEqual((body["project"], body["kind"], body["text"], body["device"], body["page"]), ("proj", "suggestion", "Add a spare mic", dev, None))
            self.assertEqual(body["name"], "local", "app reporters are their login (the typed name is for anonymous channels)")
            self.assertTrue(body["url"].startswith("https://av.example.org/"), body["url"])
            self.assertIn(dev, body["url"])
            # a plain problem is not forwarded
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems", {"text": "Hum"}, JSON_H)
            self.assertEqual(st, 201)
            self.assertEqual(len(rx.received), 1)

    def test_forward_env_url_and_failures_ignored(self):
        with _Receiver(status=500) as rx, temp_data_dir() as data, temp_env(FATHOM_SUGGEST_URL=rx.url):
            install_sunday(data, "proj")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems", {"text": "Brighter labels", "kind": "suggestion", "page": None}, JSON_H)
            self.assertEqual(st, 201, b[:300])
            self.assertFalse(jbody(b)["forwarded"], "a 5xx from the hook → forwarded: false, report still stored")
            self.assertEqual(len(rx.received), 1, "FATHOM_SUGGEST_URL is used when the project has no suggest_url")
            self.assertEqual(rx.received[0]["body"]["url"], "http://127.0.0.1/p/proj")
            self.assertEqual(len(_problems(self.app, query="?kind=suggestion")["problems"]), 1)
        with temp_data_dir() as data, temp_env(FATHOM_SUGGEST_URL="http://127.0.0.1:9/nothing-listens-here"):
            install_sunday(data, "proj")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems", {"text": "Unreachable hook", "kind": "suggestion"}, JSON_H)
            self.assertEqual(st, 201, b[:300])
            self.assertFalse(jbody(b)["forwarded"], fr("FR-USER-13", "5.16", "connection errors never fail the request"))
        with temp_data_dir() as data, temp_env(FATHOM_SUGGEST_URL="ftp://example.org/x"):
            install_sunday(data, "proj")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems", {"text": "Bad scheme", "kind": "suggestion"}, JSON_H)
            self.assertEqual((st, jbody(b)["forwarded"]), (201, False), "non-http(s) URLs are ignored")

    def test_suggest_url_validation(self):
        S = requires("schema")
        doc = sunday_doc()
        doc["settings"]["suggest_url"] = "not a url"
        probs = [p for p in S.validate_doc(doc) if p["path"] == "settings/suggest_url"]
        self.assertEqual([(p["level"], p["code"]) for p in probs], [("error", "bad_enum")], fr("FR-USER-13", "4.3.3", "suggest_url must be http(s)"))
        doc["settings"]["suggest_url"] = 5
        probs = [p for p in S.validate_doc(doc) if p["path"] == "settings/suggest_url"]
        self.assertEqual([p["code"] for p in probs], ["bad_type"])
        for ok in ("", "https://hooks.example.org/x?y=1", "http://10.0.0.5:8000/suggest"):
            doc["settings"]["suggest_url"] = ok
            self.assertEqual([p for p in S.validate_doc(doc) if p["path"] == "settings/suggest_url"], [], ok)


class SuggestionListing(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.users = requires("users")

    def test_admin_listing_across_projects(self):
        with temp_data_dir() as data:
            install_sunday(data, "alpha")
            install_sunday(data, "beta")
            self.users.add_user("ada", "ada-password-1", role="admin")
            self.users.add_user("eve", "eve-password-1", role="editor")
            ada = dict(JSON_H, **basic("ada", "ada-password-1"))
            for name, text, kind in (("alpha", "Old problem", "problem"), ("alpha", "First idea", "suggestion"), ("beta", "Second idea", "suggestion")):
                st, _, b = call(self.app, "POST", "/api/v2/projects/%s/problems" % name, {"text": text, "kind": kind}, ada)
                self.assertEqual(st, 201, b[:200])
            st, _, b = call(self.app, "GET", "/api/v2/suggestions", headers=basic("eve", "eve-password-1"))
            self.assertEqual(st, 403, "admin only")
            st, _, b = call(self.app, "GET", "/api/v2/suggestions")
            self.assertEqual(st, 401)
            st, _, b = call(self.app, "GET", "/api/v2/suggestions", headers=basic("ada", "ada-password-1"))
            self.assertEqual(st, 200, b[:200])
            items = jbody(b)["items"]
            self.assertEqual([(i["project"], i["text"]) for i in items], [("beta", "Second idea"), ("alpha", "First idea")],
                             fr("FR-USER-13", "5.16", "suggestions across projects, newest first, no plain problems"))
            self.assertTrue(all(i["kind"] == "suggestion" and i["by"] == "ada" and i["status"] == "open" for i in items))
            # trashed projects drop out
            st, _, b = call(self.app, "DELETE", "/api/v2/projects/beta?confirm=beta", headers=ada)
            self.assertEqual(st, 200, b[:200])
            st, _, b = call(self.app, "GET", "/api/v2/suggestions", headers=basic("ada", "ada-password-1"))
            self.assertEqual([i["project"] for i in jbody(b)["items"]], ["alpha"])


if __name__ == "__main__":
    unittest.main()
