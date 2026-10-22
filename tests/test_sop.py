"""SOP wiki (SPEC §4.3.15, §5.15): Markdown renderer + sanitizer, pages API, versions, backlinks, search."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

try:
    from _helpers import call, fr, get_app, install_campus, install_sunday, jbody, requires, sunday_doc, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import call, fr, get_app, install_campus, install_sunday, jbody, requires, sunday_doc, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ================================================================== renderer

class Markdown(unittest.TestCase):
    def setUp(self):
        self.md = requires("markdown")

    def render(self, text, resolver=None):
        return self.md.render(text, resolver)

    def test_blocks(self):
        r = self.render("# Title\n\nSome *em* and **strong** and `code` and ~~gone~~.\n\n"
                        "## Steps\n\n1. one\n2. two\n   - nested\n\n- [ ] open\n- [x] done\n\n"
                        "> quote\n\n---\n\n```bash\necho hi\n```\n\n| a | b |\n|---|:-:|\n| 1 | 2 |\n")
        h = r["html"]
        self.assertIn('<h1 id="h-title">Title</h1>', h)
        self.assertIn("<em>em</em>", h)
        self.assertIn("<strong>strong</strong>", h)
        self.assertIn("<code>code</code>", h)
        self.assertIn("<del>gone</del>", h)
        self.assertIn("<ol>", h)
        self.assertIn("<ul>", h)
        self.assertIn('<ul class="md-tasks">', h)
        self.assertIn('<input type="checkbox" data-task="0">', h)
        self.assertIn('<input type="checkbox" data-task="1" checked>', h)
        self.assertEqual(r["tasks"], 2)
        self.assertIn("<blockquote>", h)
        self.assertIn("<hr>", h)
        self.assertIn('<pre><code class="language-bash">echo hi', h)
        self.assertIn('<div class="md-table"><table>', h)
        self.assertIn('<th align="center">b</th>', h)
        self.assertEqual([t["text"] for t in r["toc"]], ["Title", "Steps"])
        self.assertEqual(r["toc"][1]["id"], "h-steps")

    def test_callouts_and_breaks(self):
        r = self.render("> [!WARNING] Mind the amps\n> Never power them first.\n\nline one  \nline two\n")
        self.assertIn('<div class="md-callout md-callout-warning" role="note"><p class="md-callout-title">Mind the amps</p>', r["html"])
        self.assertIn("line one<br>\nline two", r["html"].replace("<br/>", "<br>"))
        r2 = self.render("> [!NOTE]\n> body\n")
        self.assertIn('<p class="md-callout-title">Note</p>', r2["html"])

    def test_entity_links_resolver(self):
        def resolver(kind, ref):
            if kind == "device" and ref == "cl5":
                return {"label": "FOH CL5", "href": "p/x/d/cl5"}
            if kind == "attachment" and ref == "att-1":
                return {"label": "photo.png", "href": "api/v2/projects/x/files/att-1/photo.png"}
            return None

        r = self.render("Turn on [[device:cl5]] then [[device:nope|the missing one]] in [[room:main]].\n\n![Rack](att:att-1)\n\n![Gone](att:att-9)\n", resolver)
        h = r["html"]
        self.assertIn('<a class="md-ref md-ref-device" href="p/x/d/cl5" data-ref="device:cl5">FOH CL5</a>', h)
        self.assertIn('class="md-ref md-ref-device md-missing" data-ref="device:nope"', h)
        self.assertIn("the missing one", h)
        self.assertIn('<figure class="md-figure"><img src="api/v2/projects/x/files/att-1/photo.png" alt="Rack" loading="lazy">', h)
        self.assertIn("<figcaption>Rack</figcaption>", h)
        self.assertEqual(r["refs"]["devices"], ["cl5", "nope"])
        self.assertEqual(r["refs"]["rooms"], ["main"])
        self.assertEqual(r["refs"]["attachments"], ["att-1", "att-9"])
        self.assertEqual(sorted(r["missing"]), ["attachment:att-9", "device:nope", "room:main"])
        self.assertEqual(self.md.find_refs("[[page:a]] [[page:a]] [[device:b]]"), {"devices": ["b"], "rooms": [], "pages": ["a"], "attachments": []})

    def test_raw_html_is_escaped_and_sanitized(self):
        cases = [
            "<script>alert(1)</script>",
            "<img src=x onerror=alert(1)>",
            "<a href='javascript:alert(1)'>x</a>",
            "[xss](javascript:alert(1))",
            "[xss](data:text/html,hi)",
            "![x](javascript:alert(1))",
            "<iframe src='https://evil'></iframe>",
            "<div style='position:fixed'>x</div>",
            "<input type=text>",
        ]
        for c in cases:
            h = self.render(c)["html"]
            low = h.lower()
            self.assertNotIn("<script", low, c)
            self.assertNotIn("<iframe", low, c)
            self.assertNotIn("<input", low, c)
            self.assertNotIn("<div", low, c)
            self.assertNotIn("<img", low, c)
            for a in ("<a ", "<p "):
                for tag in re.findall(r"<[^>]*>", h):
                    self.assertNotRegex(tag.lower(), r"on\w+=|javascript:|data:|style=", "%s rendered unsafe tag %s" % (c, tag))
        # the sanitizer alone also strips when given hostile HTML directly
        s = self.md.sanitize('<p onclick="x()">ok<script>bad()</script><a href="javascript:1" title="t">l</a><input type="checkbox" data-task="0" onchange="x"></p>')
        self.assertEqual(s, '<p>ok<a title="t">l</a><input type="checkbox" data-task="0"></p>')
        self.assertEqual(self.md.safe_url("//evil.example/x"), "")
        self.assertEqual(self.md.safe_url("https://ok.example/x"), "https://ok.example/x")
        self.assertEqual(self.md.safe_url("#h-top"), "#h-top")

    def test_links_autolinks_plain_text(self):
        h = self.render("See [docs](https://example.com/a_(b)) and https://example.org/x.\n")["html"]
        self.assertIn('<a href="https://example.com/a_(b)" rel="noopener">docs</a>', h)
        self.assertIn('<a href="https://example.org/x" rel="noopener">https://example.org/x</a>', h)
        self.assertEqual(self.md.plain_text("# T\n\n- [ ] **bold** [[device:x|Dev]] `c`\n", 100), "T bold Dev c")
        self.assertEqual(self.md.headings("# A\n## B\ntext\n### C"), ["A", "B", "C"])


# ================================================================== schema

class Schema(unittest.TestCase):
    def test_page_validation(self):
        schema = requires("schema")
        doc = sunday_doc()
        doc["pages"] = [
            {"id": "p1", "slug": "ok", "title": "Ok", "body": "x", "parent": "p2", "devices": ["atem-mini", "nope"]},
            {"id": "p2", "slug": "ok", "title": "Dup", "parent": "p1", "kind": "weird"},
            {"id": "p3", "slug": "Bad Slug", "title": "Bad", "body": 5, "review_due": "soon"},
        ]
        probs = schema.validate_doc(schema.normalize(doc))
        codes = {(p["code"], p["level"]) for p in probs if p["ref"].startswith("pages/")}
        self.assertIn(("duplicate_slug", "error"), codes)
        self.assertIn(("page_cycle", "error"), codes)
        self.assertIn(("bad_enum", "error"), codes)
        self.assertIn(("bad_slug", "error"), codes)
        self.assertIn(("bad_type", "error"), codes)
        self.assertIn(("dangling_link", "warning"), codes)
        self.assertIn(("bad_date", "warning"), codes)
        self.assertIn("pages", schema.COLLECTIONS)
        self.assertFalse(schema.is_v1_expressible(schema.normalize(doc)), "pages make a doc v2-only")


# ================================================================== API

class PagesApi(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self._ctx = temp_data_dir()
        self.data = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        install_sunday(self.data, "sunday-demo")
        self.base = "/api/v2/projects/sunday-demo/pages"

    def req(self, method, path, body=None, status=None):
        h = dict(JSON_H) if body is not None else {"X-Fathom": "1"}
        st, hdrs, b = call(self.app, method, path, body, h)
        if status is not None:
            self.assertEqual(st, status, "%s %s -> %s %s" % (method, path, st, b[:400]))
        return st, hdrs, (jbody(b) if b else None)

    def put(self, slug, page, status=None):
        return self.req("PUT", self.base + "/" + slug, page, status)[2]

    def test_crud_tree_versions_restore(self):
        st, h, j = self.req("PUT", self.base + "/power-up", {"title": "Power-up", "body": "## Steps\n\n- [ ] On [[device:atem-mini]] press power\n- [ ] Done\n", "devices": ["atem-mini"], "rooms": ["main"]})
        self.assertEqual(st, 201, fr("SOP-01", "5.15", str(j)))
        self.assertEqual(j["page"]["status"], "draft")
        self.assertEqual(j["page"]["kind"], "sop")
        self.assertEqual(j["page"]["order"], 1)
        self.assertTrue(j["page"]["id"].startswith("pg-"))
        self.assertEqual(j["tasks"], 2)
        self.assertEqual([d["id"] for d in j["links"]["devices"]], ["atem-mini"])
        self.assertIn('data-ref="device:atem-mini"', j["html"])
        self.assertTrue(h.get("etag"))
        pid = j["page"]["id"]
        rev1 = j["revision"]

        # update + publish, children, move, prev/next
        j = self.put("power-up", {"status": "published", "body": "## Steps\n\n- [x] one\n"}, 200)
        self.assertEqual(j["page"]["status"], "published")
        self.assertEqual(j["page"]["id"], pid, "upsert keeps the id")
        self.put("section", {"title": "Section", "kind": "reference"}, 201)
        sec = self.req("GET", self.base + "/section", status=200)[2]
        self.put("shut-down", {"title": "Shut-down", "parent": sec["page"]["id"], "body": "See [[page:power-up]]."}, 201)
        self.req("POST", self.base + "/power-up/move", {"parent": sec["page"]["id"], "before": "shut-down"}, 200)
        pu = self.req("GET", self.base + "/power-up", status=200)[2]
        self.assertEqual(pu["page"]["parent"], sec["page"]["id"])
        self.assertEqual(pu["breadcrumbs"], [{"slug": "section", "title": "Section"}])
        self.assertEqual(pu["next"]["slug"], "shut-down")
        self.assertIsNone(pu["prev"])
        self.assertEqual(pu["backlinks"], [{"slug": "shut-down", "title": "Shut-down"}], "backlinks come from [[page:…]] in other bodies")
        sd = self.req("GET", self.base + "/shut-down", status=200)[2]
        self.assertEqual(sd["prev"]["slug"], "power-up")
        self.assertEqual([p["slug"] for p in sd["links"]["pages"]], ["power-up"])
        tree = self.req("GET", self.base, status=200)[2]["pages"]
        self.assertEqual([p["slug"] for p in tree], ["section", "power-up", "shut-down"])
        self.assertEqual([p["children"] for p in tree], [2, 0, 0])
        self.assertEqual([p["order"] for p in tree if p["parent"]], [1, 2], "move renumbers siblings")

        # versions: entries that touched this page, newest first; restore brings back the old body
        vs = self.req("GET", self.base + "/power-up/versions", status=200)[2]["versions"]
        self.assertGreaterEqual(len(vs), 3)
        self.assertEqual(vs[0]["revision"], max(v["revision"] for v in vs))
        self.assertIn(rev1, [v["revision"] for v in vs])
        old = self.req("GET", self.base + "/power-up/versions/%d" % rev1, status=200)[2]
        self.assertEqual(old["page"]["status"], "draft")
        self.assertIn("press power", old["html"])
        self.assertEqual(old["revision"], rev1)
        self.assertGreater(old["current_revision"], rev1)
        r = self.req("POST", self.base + "/power-up/restore/%d" % rev1, {}, 200)[2]
        now = self.req("GET", self.base + "/power-up", status=200)[2]
        self.assertIn("press power", now["html"])
        self.assertEqual(now["page"]["status"], "draft", "restore brings back the whole page entity")
        self.assertEqual(now["revision"], r["revision"])
        self.assertEqual(now["page"]["parent"], sec["page"]["id"], "…while keeping the page where it lives in the tree today")

        # delete: with children → archived; leaf → removed
        d = self.req("DELETE", self.base + "/section", status=200)[2]
        self.assertTrue(d["archived"])
        self.assertEqual(self.req("GET", self.base + "/section", status=200)[2]["page"]["status"], "archived")
        d = self.req("DELETE", self.base + "/shut-down", status=200)[2]
        self.assertFalse(d["archived"])
        self.req("GET", self.base + "/shut-down", status=404)
        self.assertEqual(len(self.req("GET", self.base, status=200)[2]["pages"]), 2)

    def test_validation_errors(self):
        self.put("a", {"title": "A"}, 201)
        a = self.req("GET", self.base + "/a", status=200)[2]["page"]
        self.put("b", {"title": "B", "parent": a["id"]}, 201)
        b = self.req("GET", self.base + "/b", status=200)[2]["page"]
        st, _, j = self.req("PUT", self.base + "/a", {"parent": b["id"]})
        self.assertEqual((st, j["code"]), (400, "page_cycle"))
        st, _, j = self.req("PUT", self.base + "/b", {"slug": "a"})
        self.assertEqual((st, j["code"]), (409, "duplicate_slug"))
        st, _, j = self.req("PUT", self.base + "/Bad_Slug", {"title": "x"})
        self.assertEqual(st, 404, "the route only matches lowercase slugs")
        st, _, j = self.req("PUT", self.base + "/c", {"title": "   "})
        self.assertEqual((st, j["code"]), (400, "missing_field"))
        st, _, j = self.req("PUT", self.base + "/c", {"title": "c", "kind": "poem"})
        self.assertEqual((st, j["code"]), (400, "bad_enum"))
        st, _, j = self.req("PUT", self.base + "/c", {"title": "c", "parent": "nope"})
        self.assertEqual((st, j["code"]), (400, "dangling_ref"))
        st, _, j = self.req("POST", self.base + "/a/move", {"parent": b["id"]})
        self.assertEqual((st, j["code"]), (400, "page_cycle"))
        self.req("GET", self.base + "/zzz", status=404)
        st, _, j = self.req("PUT", self.base + "/a", {"title": "A2", "base_revision": 1})
        self.assertEqual(st, 409, "stale base_revision on a page PUT conflicts like /changes does")
        # changes API: pages validated like any collection
        st, _, j = self.req("POST", "/api/v2/projects/sunday-demo/changes",
                            {"base_revision": self.req("GET", "/api/v2/projects/sunday-demo", status=200)[2]["revision"],
                             "ops": [{"op": "put", "coll": "pages", "id": "pg-x", "value": {"id": "pg-x", "slug": "a", "title": "Dup"}}]})
        self.assertEqual(st, 422, "duplicate slug through /changes is a validation error")

    def test_preview_and_xss(self):
        st, _, j = self.req("POST", self.base + "/preview", {"body": "# Hi\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n- [ ] step on [[device:atem-mini]]"})
        self.assertEqual(st, 200)
        self.assertNotIn("<script", j["html"])
        self.assertNotIn("javascript:", j["html"])
        self.assertIn("ATEM Mini", j["html"])
        self.assertEqual(j["tasks"], 1)
        self.assertEqual(self.req("POST", self.base + "/preview", {"body": 5})[0], 400)
        # stored page: hostile body never reaches the client un-sanitized
        self.put("evil", {"title": "Evil", "body": "<img src=x onerror=alert(1)>\n\n<iframe src=//x></iframe>"}, 201)
        h = self.req("GET", self.base + "/evil", status=200)[2]["html"]
        self.assertNotIn("<img", h)
        self.assertNotIn("<iframe", h)
        self.assertIn("&lt;img", h, "raw HTML is shown as text, never interpreted")

    def test_backlinks_filter_and_search(self):
        self.put("one", {"title": "One", "body": "Use [[device:atem-mini]].", "status": "published"}, 201)
        self.put("two", {"title": "Two", "devices": ["atem-mini"], "rooms": ["main"], "status": "published"}, 201)
        self.put("three", {"title": "Three", "body": "nothing", "kind": "checklist"}, 201)
        by_dev = self.req("GET", self.base + "?device=atem-mini", status=200)[2]["pages"]
        self.assertEqual(sorted(p["slug"] for p in by_dev), ["one", "two"], "backlinks = explicit devices ∪ [[device:…]] refs")
        self.assertEqual([p["slug"] for p in self.req("GET", self.base + "?room=main", status=200)[2]["pages"]], ["two"])
        self.assertEqual([p["slug"] for p in self.req("GET", self.base + "?status=draft", status=200)[2]["pages"]], ["three"])
        self.assertEqual([p["slug"] for p in self.req("GET", self.base + "?kind=checklist", status=200)[2]["pages"]], ["three"])
        hits = self.req("GET", "/api/v2/projects/sunday-demo/search?q=three", status=200)[2]["hits"]
        self.assertIn(("page", "three"), [(x["kind"], x["id"]) for x in hits], fr("SOP-05", "5.15", "search kind=page"))
        hits = self.req("GET", "/api/v2/projects/sunday-demo/search?q=one&kinds=page", status=200)[2]["hits"]
        self.assertTrue(hits and all(x["kind"] == "page" for x in hits))

    def test_campus_sample_pages(self):
        install_campus(self.data, "campus")
        tree = self.req("GET", "/api/v2/projects/campus/pages", status=200)[2]["pages"]
        slugs = {p["slug"] for p in tree}
        self.assertTrue({"power-up", "shut-down", "no-audio", "main-auditorium"} <= slugs, slugs)
        pu = self.req("GET", "/api/v2/projects/campus/pages/power-up", status=200)[2]
        self.assertEqual(pu["missing"], [], "sample SOPs link only to real devices/rooms/pages")
        self.assertGreater(pu["tasks"], 5)
        self.assertIn("foh-cl5", [d["id"] for d in pu["links"]["devices"]])
        self.assertEqual(pu["next"]["slug"], "shut-down")
        for slug in ("shut-down", "no-audio", "main-auditorium", "chapel-pre-service"):
            self.assertEqual(self.req("GET", "/api/v2/projects/campus/pages/" + slug, status=200)[2]["missing"], [], slug)
        self.assertIn("power-up", [p["slug"] for p in self.req("GET", "/api/v2/projects/campus/pages?device=foh-cl5", status=200)[2]["pages"]])
        # the OpenAPI document knows the pages routes and schemas
        spec = self.req("GET", "/api/openapi.json", status=200)[2]
        self.assertIn("/api/v2/projects/{name}/pages/{slug}/versions/{rev}", spec["paths"])
        self.assertIn("Page", spec["components"]["schemas"])


if __name__ == "__main__":
    unittest.main()
