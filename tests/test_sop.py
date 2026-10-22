"""SOP wiki (SPEC §4.3.15, §5.15): Markdown renderer + sanitizer, pages API, versions, backlinks, search."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

try:
    from _helpers import call, fr, get_app, install_campus, install_sunday, jbody, multipart, requires, sunday_doc, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import call, fr, get_app, install_campus, install_sunday, jbody, multipart, requires, sunday_doc, temp_data_dir

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

    def test_problem_validation(self):
        schema = requires("schema")
        doc = sunday_doc()
        doc["problems"] = [
            {"id": "pr-00000001", "text": "ok", "device": "atem-mini", "status": "open", "via": "app"},
            {"id": "pr-00000002", "text": "", "status": "weird", "device": "nope", "page": "nope", "attachment": "att-000000000000"},
        ]
        probs = schema.validate_doc(schema.normalize(doc))
        codes = {(p["ref"], p["code"], p["level"]) for p in probs if p["ref"].startswith("problems/")}
        self.assertIn(("problems/pr-00000002", "missing_field", "error"), codes)
        self.assertIn(("problems/pr-00000002", "bad_enum", "error"), codes)
        self.assertIn(("problems/pr-00000002", "dangling_link", "warning"), codes)
        self.assertFalse([c for c in codes if c[0] == "problems/pr-00000001"], "a well-formed report has no problems")
        self.assertIn("problems", schema.COLLECTIONS)
        self.assertFalse(schema.is_v1_expressible(schema.normalize(doc)), "problem reports make a doc v2-only")


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


# ================================================================== public pages, share scope, QR, report (phase 2)

class PublicPages(unittest.TestCase):
    """Chrome-free SOP pages under /p/… and share links, procedures-only share scope, QR codes, report section."""

    def setUp(self):
        self.app = get_app()
        self._ctx = temp_data_dir()
        self.data = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        install_campus(self.data, "campus")

    def get(self, path, status=None, headers=None):
        st, hdrs, b = call(self.app, "GET", path, None, headers or {})
        if status is not None:
            self.assertEqual(st, status, "GET %s -> %s %s" % (path, st, b[:300]))
        return st, hdrs, b

    def share(self, scope="sop"):
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/shares", {"label": "labels", "scope": scope}, JSON_H)
        self.assertEqual(st, 201, b[:300])
        return jbody(b)["share"]["token"]

    def test_public_page_and_index(self):
        st, h, b = self.get("/p/campus/sop/power-up", 200)
        html = b.decode("utf-8")
        self.assertIn("text/html", h.get("content-type", ""))
        self.assertIn('data-sop-page="power-up"', html)
        self.assertIn("<h1 id=\"sop-title\">Power-up: Main Auditorium</h1>", html)
        self.assertIn('class="sop-body md"', html, "the pages API renderer is reused")
        self.assertIn('<input type="checkbox" data-task="0">', html)
        self.assertIn('href="../d/foh-cl5"', html, "device refs link to the viewer device page")
        self.assertIn('href="../sop/no-audio"', html, "page refs link to sibling public pages")
        self.assertIn('class="sop-applies"', html)
        self.assertIn('class="sop-prevnext"', html)
        self.assertIn("sessionStorage", html, "checklist state is kept on the phone")
        self.assertIn("sop-lightbox", html, "tap-to-zoom images")
        self.assertNotIn("data-action=\"edit\"", html, "no edit controls on the public page")
        self.assertIn('content="width=device-width, initial-scale=1, viewport-fit=cover"', html)
        for bad in ("<script src=", "http://", "https://"):
            self.assertNotIn(bad, html.replace("https://example", ""), "self-contained page: no external assets")
        # drafts are not public
        self.get("/p/campus/sop/chapel-pre-service", 404)
        self.get("/p/campus/sop/does-not-exist", 404)
        # the index lists published pages in tree order and skips drafts
        st, _, b = self.get("/p/campus/sop", 200)
        idx = b.decode("utf-8")
        order = [m for m in re.findall(r'href="sop/([a-z0-9-]+)"', idx)]
        self.assertEqual(order, ["main-auditorium", "power-up", "shut-down", "no-audio"])
        self.assertNotIn("chapel-pre-service", idx)
        # review-due badge is rendered server-side too
        st, _, b = call(self.app, "PUT", "/api/v2/projects/campus/pages/power-up", {"review_due": "2001-01-01"}, JSON_H)
        self.assertEqual(st, 200)
        self.assertIn("Review overdue", self.get("/p/campus/sop/power-up", 200)[2].decode("utf-8"))

    def test_share_scope(self):
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/shares", {"scope": "everything"}, JSON_H)
        self.assertEqual((st, jbody(b)["code"]), (400, "bad_enum"))
        tok = self.share("sop")
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/shares")
        self.assertEqual([s["scope"] for s in jbody(b)["shares"] if s["token"] == tok], ["sop"])
        # procedures-only: /sop/… and the files they embed, nothing else
        st, _, b = self.get("/s/%s/sop/power-up" % tok, 200)
        html = b.decode("utf-8")
        self.assertNotIn('href="../d/', html, "device pages are not reachable through a procedures-only link")
        self.assertIn('<span class="md-ref md-ref-device" data-ref="device:pdu-foh">', html, "…so device refs are plain chips")
        self.assertIn('<span class="chip sop-chip-device">', html)
        self.assertIn('href="../sop/no-audio"', html)
        self.get("/s/%s/sop" % tok, 200)
        st, _, b = self.get("/s/%s" % tok, 200)
        self.assertIn("Procedures", b.decode("utf-8"), "the bare share URL opens the procedures index")
        self.get("/s/%s/files/att-b249b8bb7f21/chapel.png" % tok, 200)
        for path in ("rooms", "d/foh-cl5", "r/main", "r/main/patch", "project.json", "diagram.svg"):
            st, _, b = self.get("/s/%s/%s" % (tok, path))
            self.assertEqual((st, jbody(b).get("code")), (403, "share_scope"), path)
        # the default scope still mirrors the whole viewer tree
        full = self.share("all")
        self.get("/s/%s/rooms" % full, 200)
        self.get("/s/%s/d/foh-cl5" % full, 200)
        self.get("/s/%s/sop/power-up" % full, 200)
        self.assertIn('href="../d/foh-cl5"', self.get("/s/%s/sop/power-up" % full, 200)[2].decode("utf-8"))
        # a /p/ attachment route exists so share links can mirror embedded images
        self.get("/p/campus/files/att-b249b8bb7f21/chapel.png", 200)
        self.get("/p/campus/files/att-000000000000/x.png", 404)

    def test_qr_code_and_sheet(self):
        st, h, b = self.get("/api/v2/projects/campus/qr/page/power-up.svg", 200)
        self.assertIn("image/svg+xml", h.get("content-type", ""))
        self.assertIn(b"<svg", b)
        tok = self.share("sop")
        st, h, b2 = self.get("/api/v2/projects/campus/qr/page/power-up.svg?share=%s" % tok, 200)
        self.assertNotEqual(b, b2, "the code encodes the share URL when ?share= is given")
        self.get("/api/v2/projects/campus/qr/page/power-up.svg?share=sh-nope", 404)
        st, _, b = self.get("/api/v2/projects/campus/qr/page/chapel-pre-service.svg")
        self.assertEqual((st, jbody(b)["code"]), (409, "not_published"))
        self.get("/api/v2/projects/campus/qr/page/zzz.svg", 404)
        self.get("/api/v2/projects/campus/qr/page/power-up.svg?ecl=Z", 400)
        # sheet: one label per published page of the room, in tree order
        st, h, b = self.get("/api/v2/projects/campus/qr/pages.html?room=main&share=%s" % tok, 200)
        sheet = b.decode("utf-8")
        self.assertIn("text/html", h.get("content-type", ""))
        self.assertEqual(sheet.count('class="qr-card"'), 4)
        self.assertLess(sheet.index("Main Auditorium procedures"), sheet.index("Power-up: Main Auditorium"))
        self.assertLess(sheet.index("Power-up: Main Auditorium"), sheet.index("Shut-down: Main Auditorium"))
        self.assertIn("/s/%s/sop/power-up" % tok, sheet)
        self.assertNotIn("Chapel", sheet)
        self.get("/api/v2/projects/campus/qr/pages.html?room=zzz", 404)
        st, _, b = self.get("/api/v2/projects/campus/qr/pages.html?room=chapel", 200)
        self.assertEqual(b.decode("utf-8").count('class="qr-card"'), 0, "the chapel page is a draft")
        # OpenAPI knows the share scope
        spec = jbody(self.get("/api/openapi.json", 200)[2])
        self.assertEqual(spec["components"]["schemas"]["Share"]["properties"]["scope"]["enum"], ["all", "sop"])
        self.assertIn("/api/v2/projects/{name}/qr/page/{slug}.svg", spec["paths"])

    def test_report_section(self):
        from fathom.export import build_doc

        pdir = Path(self.data) / "projects" / "campus"
        # publish the chapel checklist so a page with an embedded image is included
        st, _, b = call(self.app, "PUT", "/api/v2/projects/campus/pages/chapel-pre-service", {"status": "published"}, JSON_H)
        self.assertEqual(st, 200, b[:300])
        run = build_doc(str(pdir), run_dir=Path(self.data) / "build-all")
        html = (run / "report.html").read_text(encoding="utf-8")
        self.assertIn("Standard operating procedures", html)
        slugs = re.findall(r'<article class="sop-report-page" id="sop-([a-z0-9-]+)"', html)
        self.assertEqual(slugs, ["main-auditorium", "power-up", "shut-down", "no-audio", "chapel-pre-service"], "tree order, one block per page")
        self.assertIn('href="devices/foh-cl5.html"', html, "device refs link to the build's device pages")
        self.assertIn('href="#sop-no-audio"', html, "page refs link within the report")
        self.assertIn('src="files/att-b249b8bb7f21/', html, "embedded images are copied into the package")
        self.assertTrue(list((run / "files" / "att-b249b8bb7f21").iterdir()))
        self.assertIn(".md .md-task-label", html, "the SOP stylesheet is inlined so the PDF renders the checklists")
        self.assertIn('class="sop-report-page"', html)
        # room-scoped build: pages for other rooms drop out
        run2 = build_doc(str(pdir), rooms=["chapel"], run_dir=Path(self.data) / "build-chapel")
        html2 = (run2 / "report.html").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'<article class="sop-report-page" id="sop-([a-z0-9-]+)"', html2), ["chapel-pre-service"])
        # drafts never appear
        call(self.app, "PUT", "/api/v2/projects/campus/pages/chapel-pre-service", {"status": "draft"}, JSON_H)
        run3 = build_doc(str(pdir), run_dir=Path(self.data) / "build-draft")
        self.assertNotIn("chapel-pre-service", (run3 / "report.html").read_text(encoding="utf-8"))


# ================================================================== phase 3

def _png(w: int = 4, h: int = 3) -> bytes:
    import struct
    import zlib

    raw = b"".join(b"\x00" + b"\xff\x80\x00" * w for _ in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class Problems(unittest.TestCase):
    """§4.3.16 / §5.16: "Report a problem" from app, public page and share link; inspector data; resolve."""

    def setUp(self):
        self.app = get_app()
        self._ctx = temp_data_dir()
        self.data = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        install_campus(self.data, "campus")

    def doc(self):
        return jbody(call(self.app, "GET", "/api/v2/projects/campus")[2])["doc"]

    def device(self, did):
        return next(d for d in self.doc()["devices"] if d["id"] == did)

    def test_editor_report_notes_the_device(self):
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/problems",
                        {"text": "  Lectern mic dead; red light on ch 3 ", "device": "foh-cl5", "page": "power-up", "device_status": "spare"}, JSON_H)
        self.assertEqual(st, 201, b[:300])
        r = jbody(b)
        self.assertTrue(r["noted"])
        pr = r["problem"]
        self.assertTrue(pr["id"].startswith("pr-"))
        self.assertEqual((pr["text"], pr["status"], pr["via"], pr["device"], pr["room"], pr["page"]), ("Lectern mic dead; red light on ch 3", "open", "app", "foh-cl5", "main", "power-up"))
        dev = self.device("foh-cl5")
        self.assertEqual(dev["status"], "spare")
        self.assertRegex(dev["note"], r"^\[\d{4}-\d\d-\d\d \d\d:\d\d local\] Problem: Lectern mic dead; red light on ch 3$")
        # a second report appends, keeping the earlier note
        call(self.app, "POST", "/api/v2/projects/campus/problems", {"text": "Still dead", "device": "foh-cl5"}, JSON_H)
        self.assertEqual(self.device("foh-cl5")["note"].count("Problem:"), 2)
        self.assertEqual(self.device("foh-cl5")["status"], "spare", "no device_status → status untouched")
        # the problems collection is in the doc and on the list endpoint, newest first with names resolved
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/problems")
        lst = jbody(b)
        self.assertEqual(lst["open"], 2)
        self.assertEqual([p["text"] for p in lst["problems"]], ["Still dead", "Lectern mic dead; red light on ch 3"])
        self.assertEqual((lst["problems"][1]["device_name"], lst["problems"][1]["page_title"]), ("FOH CL5", "Power-up: Main Auditorium"))
        self.assertEqual(len(jbody(call(self.app, "GET", "/api/v2/projects/campus/problems?page=power-up")[2])["problems"]), 1)
        self.assertEqual(len(self.doc()["problems"]), 2)
        # history records the source
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/history?limit=1")
        self.assertEqual(jbody(b)["revisions"][0]["source"], "problems")

    def test_photo_multipart_and_validation(self):
        body, ctype = multipart([("photo", "fault.png", _png(), "image/png")], {"text": "Projector flickers", "device": "projector", "page": "power-up"})
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/problems", body, {"Content-Type": ctype, "X-Fathom": "1"})
        self.assertEqual(st, 201, b[:300])
        pr = jbody(b)["problem"]
        self.assertTrue(pr["attachment"].startswith("att-"))
        att = next(a for a in self.doc()["attachments"] if a["id"] == pr["attachment"])
        self.assertEqual((att["device"], att["kind"], att["note"]), ("projector", "photo", "Problem report " + pr["id"]))
        self.assertTrue((Path(self.data) / "projects" / "campus" / att["file"]).is_file())
        st, _, b = call(self.app, "GET", "/api/v2/projects/campus/problems")
        self.assertIn("api/v2/projects/campus/files/" + pr["attachment"] + "/fault.png", jbody(b)["problems"][0]["photo"])
        # validation
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/problems", {"text": "  "}, JSON_H)
        self.assertEqual((st, jbody(b)["code"]), (400, "missing_field"))
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/problems", {"text": "x", "device": "nope"}, JSON_H)
        self.assertEqual((st, jbody(b)["code"]), (400, "dangling_ref"))
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/problems", {"text": "x", "page": "nope"}, JSON_H)
        self.assertEqual((st, jbody(b)["code"]), (400, "dangling_ref"))
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/problems", {"text": "x", "device": "projector", "device_status": "broken"}, JSON_H)
        self.assertEqual((st, jbody(b)["code"]), (400, "bad_enum"))
        body, ctype = multipart([("photo", "notes.txt", b"hello", "text/plain")], {"text": "x"})
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/problems", body, {"Content-Type": ctype, "X-Fathom": "1"})
        self.assertEqual((st, jbody(b)["code"]), (400, "bad_type"))
        self.assertEqual(len(self.doc()["problems"]), 1, "rejected reports leave nothing behind")

    def test_public_and_share_reports(self):
        # anonymous via the public page route: entry only, no device note, reporter's name is kept
        st, _, b = call(self.app, "POST", "/p/campus/problems", {"text": "Stage box sync light red", "device": "rio-sl", "page": "no-audio", "name": "Sam  (volunteer)"}, JSON_H)
        self.assertEqual(st, 201, b[:300])
        r = jbody(b)
        self.assertFalse(r["noted"])
        self.assertEqual((r["problem"]["via"], r["problem"]["by"]), ("public", "Sam (volunteer)"))
        self.assertFalse(self.device("rio-sl").get("note"), "public reports never write device notes")
        # through a procedures-only share link (role public)
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/shares", {"label": "labels", "scope": "sop"}, JSON_H)
        tok = jbody(b)["share"]["token"]
        st, _, b = call(self.app, "POST", "/s/%s/problems" % tok, {"text": "Loose XLR", "page": "power-up"}, JSON_H)
        self.assertEqual(st, 201, b[:300])
        self.assertEqual((jbody(b)["problem"]["via"], jbody(b)["problem"]["by"]), ("share", "anonymous"))
        st, _, b = call(self.app, "POST", "/s/sh-nope/problems", {"text": "x"}, JSON_H)
        self.assertEqual(st, 404)
        # the public page carries the sheet, posts to ../problems and knows the mailto fallback once configured
        html = call(self.app, "GET", "/p/campus/sop/no-audio")[2].decode("utf-8")
        self.assertIn('id="sop-report"', html)
        self.assertIn('data-action="../problems"', html)
        self.assertIn('<option value="rio-sl"', html, "devices the page applies to are offered")
        self.assertIn('capture="environment"', html, "phones open the camera")
        self.assertNotIn("Email the AV team instead", html, "no mailto fallback until settings.problem_email is set")
        rev = jbody(call(self.app, "GET", "/api/v2/projects/campus")[2])["revision"]
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/changes", {"base_revision": rev, "ops": [{"op": "root", "key": "settings", "value": {"problem_email": "av@example.org"}}]}, JSON_H)
        self.assertEqual(st, 200, b[:300])
        html = call(self.app, "GET", "/s/%s/sop/no-audio" % tok)[2].decode("utf-8")
        self.assertIn('data-email="av@example.org"', html)
        self.assertIn('href="mailto:av@example.org"', html)
        self.assertIn('data-action="../problems"', html, "share pages post to the share's problems route")

    def test_resolve_and_reopen(self):
        pid = jbody(call(self.app, "POST", "/api/v2/projects/campus/problems", {"text": "Hum on the PA"}, JSON_H)[2])["problem"]["id"]
        st, _, b = call(self.app, "PATCH", "/api/v2/projects/campus/problems/" + pid, {"status": "resolved", "note": "Ground lift"}, JSON_H)
        self.assertEqual(st, 200, b[:300])
        pr = jbody(b)["problem"]
        self.assertEqual((pr["status"], pr["note"], pr["resolved_by"]), ("resolved", "Ground lift", "local"))
        self.assertTrue(pr["resolved"])
        self.assertEqual(jbody(call(self.app, "GET", "/api/v2/projects/campus/problems")[2])["open"], 0)
        self.assertEqual(len(jbody(call(self.app, "GET", "/api/v2/projects/campus/problems?status=resolved")[2])["problems"]), 1)
        st, _, b = call(self.app, "PATCH", "/api/v2/projects/campus/problems/" + pid, {"status": "open"}, JSON_H)
        self.assertEqual(st, 200)
        stored = next(p for p in self.doc()["problems"] if p["id"] == pid)
        self.assertEqual(stored["status"], "open")
        self.assertNotIn("resolved", stored)
        st, _, b = call(self.app, "PATCH", "/api/v2/projects/campus/problems/" + pid, {"status": "maybe"}, JSON_H)
        self.assertEqual((st, jbody(b)["code"]), (400, "bad_enum"))
        self.assertEqual(call(self.app, "PATCH", "/api/v2/projects/campus/problems/pr-00000000", {"status": "open"}, JSON_H)[0], 404)
        spec = jbody(call(self.app, "GET", "/api/openapi.json")[2])
        self.assertIn("ProblemReport", spec["components"]["schemas"])
        self.assertIn("/api/v2/projects/{name}/problems", spec["paths"])


class ChecklistsArchiveBundle(unittest.TestCase):
    """Mark complete (who / when), archived pages hidden from volunteers and public routes, offline bundle + CLI."""

    def setUp(self):
        self.app = get_app()
        self._ctx = temp_data_dir()
        self.data = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        install_campus(self.data, "campus")
        self.pdir = Path(self.data) / "projects" / "campus"

    def test_mark_complete(self):
        st, _, b = call(self.app, "POST", "/api/v2/projects/campus/pages/power-up/complete", {}, JSON_H)
        self.assertEqual(st, 200, b[:300])
        r = jbody(b)
        self.assertEqual(r["completion"]["by"], "local")
        self.assertEqual(len(r["completions"]), 1)
        for _ in range(25):
            call(self.app, "POST", "/api/v2/projects/campus/pages/power-up/complete", {}, JSON_H)
        page = jbody(call(self.app, "GET", "/api/v2/projects/campus/pages/power-up")[2])["page"]
        self.assertEqual(len(page["completions"]), 20, "capped at the last 20")
        self.assertEqual(call(self.app, "POST", "/api/v2/projects/campus/pages/nope/complete", {}, JSON_H)[0], 404)
        html = call(self.app, "GET", "/p/campus/sop/power-up")[2].decode("utf-8")
        self.assertIn("Last completed", html)
        self.assertIn("Mark complete", html)
        self.assertIn("Reset checklist", html)
        self.assertIn("fathom.sop.done.", html, "public pages keep the mark in sessionStorage only")

    def test_archived_pages_are_hidden(self):
        from fathom.export import build_doc

        st, _, b = call(self.app, "PUT", "/api/v2/projects/campus/pages/no-audio", {"status": "archived"}, JSON_H)
        self.assertEqual(st, 200, b[:300])
        self.assertEqual(call(self.app, "GET", "/p/campus/sop/no-audio")[0], 404)
        idx = call(self.app, "GET", "/p/campus/sop")[2].decode("utf-8")
        self.assertNotIn("no-audio", idx)
        # page refs to an archived page render as "missing" rather than dead links
        html = call(self.app, "GET", "/p/campus/sop/power-up")[2].decode("utf-8")
        self.assertNotIn('href="../sop/no-audio"', html)
        self.assertNotIn("no-audio", call(self.app, "GET", "/api/v2/projects/campus/qr/pages.html")[2].decode("utf-8"))
        run = build_doc(str(self.pdir), run_dir=Path(self.data) / "build")
        self.assertNotIn('id="sop-no-audio"', (run / "report.html").read_text(encoding="utf-8"))
        # the API still returns it so editors can filter / restore
        self.assertIn("no-audio", [p["slug"] for p in jbody(call(self.app, "GET", "/api/v2/projects/campus/pages?status=archived")[2])["pages"]])
        st, _, b = call(self.app, "PUT", "/api/v2/projects/campus/pages/no-audio", {"status": "published"}, JSON_H)
        self.assertEqual(st, 200)
        self.assertEqual(call(self.app, "GET", "/p/campus/sop/no-audio")[0], 200)

    def test_offline_bundle(self):
        import io
        import zipfile

        from fathom.export import write_sop_bundle

        # publish the chapel page so an embedded image is included
        call(self.app, "PUT", "/api/v2/projects/campus/pages/chapel-pre-service", {"status": "published"}, JSON_H)
        call(self.app, "PUT", "/api/v2/projects/campus/pages/no-audio", {"status": "archived"}, JSON_H)
        st, h, b = call(self.app, "GET", "/api/v2/projects/campus/sop/bundle.zip")
        self.assertEqual(st, 200, b[:300])
        self.assertEqual(h.get("content-type"), "application/zip")
        self.assertIn('filename="campus-procedures.zip"', h.get("content-disposition", ""))
        zf = zipfile.ZipFile(io.BytesIO(b))
        names = sorted(zf.namelist())
        self.assertIn("campus-procedures/index.html", names)
        self.assertIn("campus-procedures/pages/power-up.html", names)
        self.assertIn("campus-procedures/pages/chapel-pre-service.html", names)
        self.assertNotIn("campus-procedures/pages/no-audio.html", names, "archived pages stay out of the bundle")
        self.assertTrue([n for n in names if n.startswith("campus-procedures/files/att-b249b8bb7f21/")], "embedded images are copied")
        idx = zf.read("campus-procedures/index.html").decode("utf-8")
        self.assertIn('href="pages/power-up.html"', idx)
        self.assertNotIn("no-audio", idx)
        self.assertIn("Offline copy from", idx)
        page = zf.read("campus-procedures/pages/power-up.html").decode("utf-8")
        self.assertIn('href="main-auditorium.html"', page, "parent / sibling links are relative files")
        self.assertIn('href="shut-down.html"', page)
        self.assertIn('<span class="chip sop-chip-device">', page, "device chips are plain text offline")
        self.assertNotIn('href="../d/', page)
        self.assertIn("sessionStorage", page, "checklists work offline")
        self.assertIn('data-sop-page="power-up"', page)
        self.assertNotIn("manifest.webmanifest", page, "no service worker / manifest: works from file://")
        self.assertNotIn('data-app-root', page)
        for bad in ("<script src=", 'href="http', 'src="http'):
            self.assertNotIn(bad, page)
        chapel = zf.read("campus-procedures/pages/chapel-pre-service.html").decode("utf-8")
        self.assertIn('src="../files/att-b249b8bb7f21/', chapel)
        self.assertNotIn('id="sop-report"', page, "no e-mail configured → no report sheet offline")
        # with a problem e-mail the sheet is there as a mailto-only form
        rev = jbody(call(self.app, "GET", "/api/v2/projects/campus")[2])["revision"]
        call(self.app, "POST", "/api/v2/projects/campus/changes", {"base_revision": rev, "ops": [{"op": "root", "key": "settings", "value": {"problem_email": "av@example.org"}}]}, JSON_H)
        out = Path(self.data) / "bundle-dir"
        from fathom.project import read_doc

        files = write_sop_bundle(self.pdir, read_doc(self.pdir)[0], out)
        self.assertIn("pages/power-up.html", files)
        page = (out / "pages" / "power-up.html").read_text(encoding="utf-8")
        self.assertIn('data-action=""', page)
        self.assertIn("Send by email", page)
        self.assertIn('data-email="av@example.org"', page)
        self.assertNotIn("Email the AV team instead", page, "offline the e-mail is the only channel, not an alternative")

    def test_cli_sop_bundle(self):
        import io
        import zipfile
        from contextlib import redirect_stdout

        from fathom.cli import main

        out = io.StringIO()
        zpath = Path(self.data) / "out" / "procs.zip"
        with redirect_stdout(out):
            main(["sop-bundle", str(self.pdir), "-o", str(zpath)])
        self.assertIn("4 published pages", out.getvalue())
        self.assertIn("campus-procedures/pages/power-up.html", zipfile.ZipFile(zpath).namelist())
        folder = Path(self.data) / "out" / "folder"
        with redirect_stdout(out):
            main(["sop-bundle", str(self.pdir), "-o", str(folder)])
        self.assertTrue((folder / "index.html").is_file())
        self.assertTrue((folder / "pages" / "power-up.html").is_file())


if __name__ == "__main__":
    unittest.main()
