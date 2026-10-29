"""Security checklist (SPEC §8.4, FR-SEC, FR-USER): traversal, caps, CSRF, headers, secrets, roles, sessions."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import inspect
import io
import json
import os
import re
import stat
import sys
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

try:
    from _helpers import (basic, call, fixture_path, fr, get_app, install_project, install_sunday, jbody, jpg_bytes, multipart,
                          png_bytes, requires, sunday_doc, temp_data_dir, temp_env, uniq, upload)
except ImportError:  # pragma: no cover
    from tests._helpers import (basic, call, fixture_path, fr, get_app, install_project, install_sunday, jbody, jpg_bytes, multipart,
                                png_bytes, requires, sunday_doc, temp_data_dir, temp_env, uniq, upload)

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
SECRET = "T1-OUTSIDE-SECRET-7f3a"
CSP_APP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
           "frame-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
CSP_VIEWER = CSP_APP.replace("script-src 'self';", "script-src 'self' 'unsafe-inline';")
CSP_FILES = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"

# §5.2 + §5.3–5.13 roles. Paths use {} for every parameter.
SPEC_ROLES = {
    ("GET", "/api/v2/session"): "public", ("POST", "/api/v2/session"): "public", ("DELETE", "/api/v2/session"): "any",
    ("GET", "/api/v2/users"): "admin", ("POST", "/api/v2/users"): "admin", ("PATCH", "/api/v2/users/{}"): "admin",
    ("DELETE", "/api/v2/users/{}"): "admin", ("POST", "/api/v2/users/me/password"): "any", ("GET", "/login"): "public",
    # phase2 P2A
    ("GET", "/api/v2/invites"): "admin", ("POST", "/api/v2/invites"): "admin", ("DELETE", "/api/v2/invites/{}"): "admin",
    ("GET", "/invite/{}"): "public", ("GET", "/api/v2/invites/{}/check"): "public", ("POST", "/api/v2/invites/{}/accept"): "public",
    ("GET", "/api/v2/suggestions"): "admin",
    ("GET", "/api/v2/backups"): "admin", ("POST", "/api/v2/backups"): "admin", ("POST", "/api/v2/backups/upload"): "admin",
    ("GET", "/api/v2/backups/{}"): "admin", ("DELETE", "/api/v2/backups/{}"): "admin", ("POST", "/api/v2/backups/{}/restore"): "admin",
    ("GET", "/healthz"): "public", ("GET", "/api/v2/schema.json"): "public",
    ("GET", "/api/v2/meta"): "viewer", ("GET", "/api/v2/library"): "viewer", ("GET", "/api/v2/library/{}"): "viewer",
    ("GET", "/api/v2/library/suggest"): "viewer",
    ("POST", "/api/v2/library"): "editor", ("DELETE", "/api/v2/library/{}"): "editor", ("GET", "/api/v2/presets"): "viewer",
    ("GET", "/api/v2/projects"): "viewer", ("POST", "/api/v2/projects"): "editor", ("GET", "/api/v2/projects/{}"): "viewer",
    # phase3 P3C
    ("GET", "/api/v2/starters"): "viewer", ("POST", "/api/v2/projects/{}/rooms/from-starter"): "editor",
    ("PUT", "/api/v2/projects/{}"): "editor", ("POST", "/api/v2/projects/{}/changes"): "editor", ("DELETE", "/api/v2/projects/{}"): "admin",
    # phase1 P1A
    ("GET", "/api/v2/trash"): "admin", ("POST", "/api/v2/trash/{}/restore"): "admin", ("DELETE", "/api/v2/trash/{}"): "admin",
    ("GET", "/api/v2/codes/{}"): "viewer", ("GET", "/c/{}"): "viewer",
    ("GET", "/api/v2/projects/{}/devices/duplicates"): "viewer", ("POST", "/api/v2/projects/{}/devices/merge/preview"): "editor",
    ("POST", "/api/v2/projects/{}/devices/merge"): "editor",
    ("GET", "/api/v2/projects/{}/devices/{}/channels"): "viewer", ("POST", "/api/v2/projects/{}/devices/{}/channels/apply"): "editor",
    ("GET", "/api/v2/projects/{}/doc.json"): "viewer", ("GET", "/api/v2/projects/{}/history"): "viewer",
    ("GET", "/api/v2/projects/{}/history/{}"): "viewer", ("GET", "/api/v2/projects/{}/history/{}/diff"): "viewer",
    ("POST", "/api/v2/projects/{}/history/{}/restore"): "editor", ("GET", "/api/v2/projects/{}/overlay"): "viewer",
    ("GET", "/api/v2/projects/{}/offline-manifest"): "viewer", ("GET", "/api/v2/projects/{}/shares"): "editor",
    ("POST", "/api/v2/projects/{}/shares"): "editor", ("DELETE", "/api/v2/projects/{}/shares/{}"): "editor",
    ("POST", "/api/v2/projects/{}/imports"): "editor", ("DELETE", "/api/v2/projects/{}/imports/{}"): "editor",
    ("GET", "/api/v2/projects/{}/imports/{}/inspect"): "viewer", ("POST", "/api/v2/projects/{}/imports/preview"): "editor",
    ("GET", "/api/v2/projects/{}/imports/templates/{}/{}.csv"): "viewer",
    ("GET", "/api/v2/projects/{}/discovery/runs"): "viewer", ("POST", "/api/v2/projects/{}/discovery/runs"): "editor",
    ("GET", "/api/v2/projects/{}/discovery/runs/{}"): "viewer", ("DELETE", "/api/v2/projects/{}/discovery/runs/{}"): "editor",
    ("GET", "/api/v2/projects/{}/discovery/runs/{}/findings"): "viewer", ("POST", "/api/v2/projects/{}/discovery/runs/{}/findings/promote"): "editor",
    ("GET", "/api/v2/projects/{}/discovery/runs/{}/diff"): "viewer", ("GET", "/api/v2/projects/{}/discovery/settings"): "viewer", ("PUT", "/api/v2/projects/{}/discovery/settings"): "editor",
    ("POST", "/api/v2/projects/{}/discovery/test"): "editor",
    ("POST", "/api/v2/projects/{}/files"): "editor", ("GET", "/api/v2/projects/{}/files/{}/{}"): "viewer",
    ("DELETE", "/api/v2/projects/{}/files/{}"): "editor", ("POST", "/api/v2/projects/{}/floorplans"): "editor",
    ("POST", "/api/v2/projects/{}/floorplans/{}/reconvert"): "editor", ("GET", "/api/v2/projects/{}/floorplans/{}/image"): "viewer",
    ("GET", "/api/v2/projects/{}/floorplans/{}.svg"): "viewer", ("GET", "/api/v2/projects/{}/schedules/{}"): "viewer",
    ("GET", "/api/v2/projects/{}/cables/tag-preview"): "editor", ("GET", "/api/v2/projects/{}/racks/{}.svg"): "viewer",
    ("GET", "/api/v2/projects/{}/qr/{}.svg"): "viewer", ("GET", "/api/v2/projects/{}/trace"): "viewer",
    # phase3 P3A
    ("GET", "/api/v2/projects/{}/scenes"): "viewer", ("POST", "/api/v2/projects/{}/scenes"): "editor",
    ("PATCH", "/api/v2/projects/{}/scenes/{}"): "editor", ("DELETE", "/api/v2/projects/{}/scenes/{}"): "editor",
    ("POST", "/api/v2/projects/{}/scenes/{}/activate"): "editor", ("POST", "/api/v2/projects/{}/scenes/{}/save"): "editor",
    ("GET", "/api/v2/projects/{}/scenes/{}/diff"): "viewer", ("GET", "/api/v2/projects/{}/scenes/{}/doc"): "viewer",
    # phase4 P4A
    ("GET", "/api/v2/llm/providers"): "viewer", ("GET", "/api/v2/llm/settings"): "admin", ("PUT", "/api/v2/llm/settings"): "admin",
    ("POST", "/api/v2/llm/models"): "admin", ("POST", "/api/v2/llm/test"): "admin",
    # phase1 P1B
    ("GET", "/api/v2/labels/presets"): "viewer", ("GET", "/api/v2/projects/{}/labels/devices"): "viewer",
    ("GET", "/api/v2/projects/{}/search"): "viewer", ("POST", "/api/v2/projects/{}/assistant"): "viewer",
    # phase4 P4B
    ("POST", "/api/v2/projects/{}/assistant/apply"): "editor",
    ("GET", "/api/v2/projects/{}/pages"): "viewer", ("POST", "/api/v2/projects/{}/pages/preview"): "editor",
    ("GET", "/api/v2/projects/{}/pages/{}"): "viewer", ("PUT", "/api/v2/projects/{}/pages/{}"): "editor",
    ("DELETE", "/api/v2/projects/{}/pages/{}"): "editor", ("POST", "/api/v2/projects/{}/pages/{}/move"): "editor",
    ("GET", "/api/v2/projects/{}/pages/{}/versions"): "viewer", ("GET", "/api/v2/projects/{}/pages/{}/versions/{}"): "viewer",
    ("POST", "/api/v2/projects/{}/pages/{}/restore/{}"): "editor", ("POST", "/api/v2/projects/{}/pages/{}/complete"): "editor",
    ("GET", "/api/v2/projects/{}/sop/bundle.zip"): "editor", ("POST", "/api/v2/projects/{}/problems"): "viewer",
    ("GET", "/api/v2/projects/{}/problems"): "viewer", ("PATCH", "/api/v2/projects/{}/problems/{}"): "editor",
    ("GET", "/api/v2/projects/{}/qr/page/{}.svg"): "viewer", ("GET", "/api/v2/projects/{}/qr/pages.html"): "viewer",
    # phase5 P5C
    ("GET", "/api/v2/projects/{}/rooms/{}/patch.svg"): "viewer", ("GET", "/api/v2/projects/{}/rooms/{}/patch.{}"): "viewer",
    ("GET", "/api/v2/projects/{}/floorplans/{}.{}"): "viewer",
    ("POST", "/api/v2/projects/{}/builds"): "editor", ("GET", "/api/v2/projects/{}/builds"): "viewer",
    ("DELETE", "/api/v2/projects/{}/builds/{}"): "editor", ("GET", "/builds/{}/{}/{}"): "viewer",
    ("GET", "/api/meta"): "viewer", ("GET", "/api/projects"): "viewer", ("POST", "/api/projects"): "editor",
    ("GET", "/api/projects/{}"): "viewer", ("PUT", "/api/projects/{}"): "editor", ("DELETE", "/api/projects/{}"): "admin",
    ("POST", "/api/projects/{}/imports"): "editor", ("DELETE", "/api/projects/{}/imports"): "editor",
    ("GET", "/api/projects/{}/inspect"): "viewer", ("GET", "/api/projects/{}/trace"): "viewer", ("POST", "/api/projects/{}/build"): "editor",
    ("GET", "/api/projects/{}/builds"): "viewer", ("DELETE", "/api/projects/{}/builds/{}"): "editor",
    ("GET", "/"): "viewer", ("GET", "/p/{}"): "viewer", ("GET", "/p/{}/{}"): "viewer", ("GET", "/p/{}/rooms"): "viewer",
    ("GET", "/p/{}/r/{}"): "viewer", ("GET", "/p/{}/r/{}/diagram.svg"): "viewer", ("GET", "/p/{}/r/{}/patch"): "viewer",
    ("GET", "/p/{}/d/{}"): "viewer", ("GET", "/p/{}/sop"): "viewer", ("GET", "/p/{}/sop/{}"): "viewer",
    ("POST", "/p/{}/problems"): "viewer", ("POST", "/s/{}/problems"): "public",
    ("GET", "/p/{}/files/{}/{}"): "viewer", ("GET", "/s/{}"): "public", ("GET", "/s/{}/{}"): "public", ("GET", "/static/{}"): "public",
    ("GET", "/sw.js"): "public", ("GET", "/manifest.webmanifest"): "public", ("GET", "/favicon.ico"): "public",
    ("GET", "/apple-touch-icon.png"): "public",     ("GET", "/api/openapi.json"): "public", ("GET", "/api/docs"): "public",
    # phase5 P5A
    ("GET", "/api/v2/projects/{}/floorplans/{}/runs"): "viewer", ("POST", "/api/v2/projects/{}/floorplans/{}/runs/snap"): "viewer",
    ("POST", "/api/v2/projects/{}/floorplans/{}/runs/estimate"): "editor",
}
RANK = {"viewer": 1, "editor": 2, "admin": 3}
SAMPLES = ["proj", "main", "atem-mini", "rk-foh", "cables", "1", "nobody", "imp-0001", "att-000000000000", "sh-abc123", "fp-none",
           "run1", "index.html", "diagram.svg", "x.png", "app.html", "nope"]
PARAM_HINTS = {"name": "proj", "room": "main", "device": "atem-mini", "rack": "rk-foh", "kind": "cables", "rev": "1", "username": "nobody",
               "iid": "imp-0001", "att": "att-000000000000", "token": "sh-abc123", "fp": "fp-none", "run": "run1", "file": "index.html",
               "filename": "x.png", "path": "app.html", "tid": "nope", "backup": "fathom-backup-none.zip", "table": "devices", "slug": "power-up",
               "rid": "run-20260101-000000-0000", "pid": "pr-00000000", "code": "ABCD2345", "tname": "proj",
               "invite": "inv-000000000000000000000000",  # phase2 P2A
               "sid": "sc-00000000",  # phase3 P3A
               "fmt": "png"}  # phase5 P5C
DISCOVERY_FIXTURES = str(Path(__file__).parent / "fixtures" / "discovery")


def _groups(pattern):
    """[(name, inner_regex, start, end)] for named groups in a route regex."""
    out, i = [], 0
    while True:
        i = pattern.find("(?P<", i)
        if i < 0:
            return out
        j = pattern.index(">", i)
        depth, k = 1, j + 1
        while depth:
            if pattern[k] == "\\":
                k += 2
                continue
            depth += {"(": 1, ")": -1}.get(pattern[k], 0)
            k += 1
        out.append((pattern[i + 4:j], pattern[j + 1:k - 1], i, k))
        i = k


def concrete(pattern):
    """A concrete URL path matching the route regex, plus its normalized spec template."""
    p = pattern.strip("^$")
    url, tmpl, last = "", "", 0
    for name, inner, a, b in _groups(p):
        url += p[last:a]
        tmpl += p[last:a]
        cands = [PARAM_HINTS.get(name)] + SAMPLES
        val = next((c for c in cands if c and re.fullmatch(inner, c)), "x")
        url += val
        tmpl += "{}"
        last = b
    url += p[last:]
    tmpl += p[last:]
    clean = lambda s: re.sub(r"\(\?:([^()]*)\)\?", "", s).replace("\\", "")  # noqa: E731
    return clean(url), clean(tmpl)


def routes(server):
    out = []
    for r in getattr(server, "ROUTES", None) or getattr(server, "_ROUTES", []):
        if hasattr(r, "method"):
            out.append((r.method, getattr(r, "pattern", None) or r.regex.pattern, getattr(r, "role", None)))
        else:
            out.append((r[0], r[1].pattern if hasattr(r[1], "pattern") else r[1], None))
    return out


def spec_role(method, tmpl):
    if (method, tmpl) in SPEC_ROLES:
        return SPEC_ROLES[(method, tmpl)], True
    return ("viewer" if method in ("GET", "HEAD") else "editor"), False


@contextlib.contextmanager
def users_env(**env):
    """Data dir with auth on via users.json (admin ada, editor eve, viewer vic) + logged-in cookies."""
    users = requires("users")
    app = get_app()
    env.setdefault("FATHOM_DISCOVERY_FIXTURES", DISCOVERY_FIXTURES)  # the role matrix starts a discovery run: replay fixtures, never touch the network
    with temp_data_dir(**env) as data:
        install_sunday(data, "proj")
        pw = {"ada": "ada-password-1", "eve": "eve-password-1", "vic": "vic-password-1"}
        users.add_user("ada", pw["ada"], role="admin")
        users.add_user("eve", pw["eve"], role="editor")
        users.add_user("vic", pw["vic"], role="viewer")
        cookies = {}
        for u, role in (("ada", "admin"), ("eve", "editor"), ("vic", "viewer")):
            st, h, b = call(app, "POST", "/api/v2/session", {"username": u, "password": pw[u]}, {"Content-Type": "application/json"})
            assert st == 200, (st, b)
            sc = [c for c in h.all("set-cookie") if c.startswith("fathom_session=")]
            assert sc, h.pairs
            cookies[role] = sc[0].split(";")[0]
        yield app, data, cookies, pw


class Traversal(unittest.TestCase):
    def test_path_traversal(self):
        app = get_app()
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            (data / "outside.txt").write_text(SECRET)
            run = data / "builds" / "proj" / "run1"
            run.mkdir(parents=True)
            (run / "index.html").write_text("<html>ok</html>")
            os.symlink(str(data / "outside.txt"), str(run / "evil.txt"))
            os.symlink(str(data), str(run / "evil-dir"))
            att = data / "projects" / "proj" / "files" / "att-00000000beef"
            att.mkdir(parents=True)
            os.symlink(str(data / "outside.txt"), str(att / "x.png"))
            os.symlink(str(data / "outside.txt"), str(data / "projects" / "proj" / "exports-link.txt"))
            st, _, b = call(app, "GET", "/builds/proj/run1/index.html")
            self.assertEqual(st, 200, "control: a normal build file is served")
            bad = [
                "/builds/proj/run1/../../../outside.txt", "/builds/proj/run1/%2e%2e/%2e%2e/%2e%2e/outside.txt",
                "/builds/proj/run1/..%2f..%2f..%2foutside.txt", "/builds/proj/run1/evil.txt", "/builds/proj/run1/evil-dir/outside.txt",
                "/builds/proj/..%2f..%2foutside.txt/x", "/builds/..%2f/run1/index.html",
                "/static/../../outside.txt", "/static/%2e%2e/%2e%2e/outside.txt", "/static/..%2f..%2foutside.txt",
                "/static//etc/passwd", "/static/%2Fetc%2Fpasswd", "/static/app.html%00.js",
                "/api/v2/projects/..%2f..%2foutside.txt", "/api/v2/projects/%2e%2e", "/p/..%2f..%2fprojects",
                "/api/v2/projects/proj/files/att-00000000beef/x.png", "/api/v2/projects/proj/files/att-00000000beef/..%2f..%2fproject.json",
                "/api/v2/projects/proj%00/doc.json", "/p/proj/d/..%2f..%2fproject",
            ]
            for path in bad:
                with self.subTest(path=path):
                    st, h, body = call(app, "GET", path)
                    self.assertIn(st, (400, 403, 404), fr("FR-SEC-01", "8.4 #1", "%s -> %s" % (path, st)))
                    self.assertNotIn(SECRET.encode(), body, fr("FR-SEC-01", "8.4 #1", path))
                    self.assertNotIn(b"root:", body)
            # raw (undecoded) PATH_INFO variants, as some servers pass them through
            for raw in ("/builds/proj/run1/%2e%2e/%2e%2e/%2e%2e/outside.txt", "/static/%2e%2e/%2e%2e/outside.txt"):
                st, _, body = call(app, "GET", raw, headers={"__path_info__": raw})
                self.assertIn(st, (400, 403, 404), fr("FR-SEC-01", "8.4 #1", "raw " + raw))
                self.assertNotIn(SECRET.encode(), body)

    def test_upload_filename_sanitized(self):
        app = get_app()
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            st, _, b = upload(app, "/api/v2/projects/proj/files", [("../../../evil name.jpg", jpg_bytes(), "image/jpeg")])
            self.assertEqual(st, 201, b[:300])
            att = jbody(b)["attachments"][0]
            self.assertNotIn("..", att["file"], "8.4 #2 filenames sanitized")
            target = (data / "projects" / "proj" / att["file"]).resolve()
            self.assertTrue(str(target).startswith(str((data / "projects" / "proj" / "files" / att["id"]).resolve())))
            self.assertFalse((data / "evil name.jpg").exists())


class Caps(unittest.TestCase):
    def test_body_caps(self):
        app = get_app()
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            body, ctype = multipart([("file", "a.png", png_bytes(), "image/png")])
            st, _, b = call(app, "POST", "/api/v2/projects/proj/files",
                            body, {"Content-Type": ctype, "X-Fathom": "1", "Content-Length": str(51 * 1024 * 1024)})
            self.assertEqual(st, 413, fr("FR-SEC-02", "3.26", "multipart over 50 MB by Content-Length"))
            self.assertEqual(jbody(b).get("code"), "too_large")
            st, _, b = call(app, "POST", "/api/v2/projects/proj/changes", b'{"ops": []}',
                            {"Content-Type": "application/json", "Content-Length": str(21 * 1024 * 1024)})
            self.assertEqual(st, 413, fr("FR-SEC-02", "3.26", "JSON over 20 MB by Content-Length"))
            self.assertFalse(list((data / "projects" / "proj").glob("files/*")), "nothing stored for a rejected upload")


class Csrf(unittest.TestCase):
    def test_csrf_rule(self):
        app = get_app()
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            body, ctype = multipart([("file", "a.png", png_bytes(), "image/png")])
            st, _, b = call(app, "POST", "/api/v2/projects/proj/files", body, {"Content-Type": ctype})
            self.assertEqual(st, 403, fr("FR-SEC-03", "8.4 #4", "multipart without X-Fathom"))
            self.assertEqual(jbody(b).get("code"), "csrf")
            st, _, _ = call(app, "POST", "/api/v2/projects/proj/changes", "base_revision=1", {"Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(st, 403, fr("FR-SEC-03", "3.26", "urlencoded without X-Fathom"))
            st, _, _ = call(app, "POST", "/api/v2/projects/proj/changes", '{"base_revision": 1, "ops": []}', {"Content-Type": "text/plain"})
            self.assertEqual(st, 403, fr("FR-SEC-03", "3.26", "text/plain without X-Fathom"))
            st, _, b = call(app, "POST", "/api/v2/projects/proj/changes", {"base_revision": 1, "ops": []}, {"Content-Type": "application/json"})
            self.assertNotEqual(st, 403, fr("FR-SEC-03", "3.26", "JSON POST is non-simple and allowed: %s" % b[:200]))
            st, _, _ = call(app, "POST", "/api/v2/projects/proj/files", body, {"Content-Type": ctype, "X-Fathom": "1"})
            self.assertEqual(st, 201, "multipart with X-Fathom accepted")

    def test_csrf_cookie_origin(self):
        with users_env() as (app, data, cookies, pw):
            h = {"Cookie": cookies["editor"], "Content-Type": "application/json", "X-Fathom": "1"}
            st, _, _ = call(app, "POST", "/api/v2/projects/proj/changes", {"base_revision": 1, "ops": []}, dict(h, Origin="https://evil.example"))
            self.assertEqual(st, 403, fr("FR-SEC-03", "3.26", "cookie session with a foreign Origin"))
            st, _, b = call(app, "POST", "/api/v2/projects/proj/changes", {"base_revision": 1, "ops": []}, dict(h, Origin="http://127.0.0.1"))
            self.assertNotEqual(st, 403, fr("FR-SEC-03", "3.26", "same Origin allowed: %s" % b[:200]))


class Headers(unittest.TestCase):
    def _common(self, h, what):
        self.assertEqual(h.get("x-content-type-options"), "nosniff", fr("FR-SEC-04", "3.26", what))
        self.assertEqual(h.get("referrer-policy"), "same-origin", fr("FR-SEC-04", "3.26", what))
        self.assertEqual(h.get("x-frame-options"), "SAMEORIGIN", fr("FR-SEC-04", "3.26", what))

    def test_security_headers(self):
        app = get_app()
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            for path in ("/api/v2/meta", "/healthz", "/api/v2/projects/nope", "/static/app.html", "/manifest.webmanifest"):
                st, h, _ = call(app, "GET", path)
                self._common(h, path)
            st, h, _ = call(app, "GET", "/")
            self._common(h, "/")
            self.assertEqual(h.get("content-security-policy"), CSP_APP, fr("FR-SEC-04", "3.26", "app page CSP"))
            st, h, _ = call(app, "GET", "/p/proj")
            self.assertEqual(st, 200)
            self._common(h, "/p/proj")
            self.assertEqual(h.get("content-security-policy"), CSP_VIEWER, fr("FR-SEC-04", "3.26", "viewer page CSP"))

    def test_user_file_headers(self):
        app = get_app()
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            svg = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="10" height="10">'
                   b'<script>alert(1)</script><rect onclick="alert(2)" width="5" height="5"/>'
                   b'<image xlink:href="https://evil.example/x.png"/></svg>')
            st, _, b = upload(app, "/api/v2/projects/proj/files", [("a.svg", svg, "image/svg+xml"), ("b.jpg", jpg_bytes(), "image/jpeg"),
                                                                    ("c.html", b"<script>alert(1)</script>", "text/html")])
            self.assertEqual(st, 201, b[:300])
            atts = {a["name"]: a for a in jbody(b)["attachments"]}
            for name, a in atts.items():
                st, h, body = call(app, "GET", "/api/v2/projects/proj/files/%s/%s" % (a["id"], a["file"].split("/")[-1]))
                self.assertEqual(st, 200)
                self._common(h, name)
                self.assertEqual(h.get("content-security-policy"), CSP_FILES, fr("FR-SEC-04", "3.26", "user file CSP " + name))
                if name == "a.svg":
                    self.assertNotIn(b"<script", body, fr("FR-SEC-05", "3.26", "SVG served only after sanitization"))
                    self.assertNotIn(b"onclick", body)
                    self.assertNotIn(b"evil.example", body)
                if name == "c.html":
                    self.assertIn("attachment", h.get("content-disposition", ""), fr("FR-SEC-05", "3.26", "non-image as attachment"))
                    self.assertFalse(h.get("content-type", "").startswith("text/html") and "attachment" not in h.get("content-disposition", ""))


class Secrets(unittest.TestCase):
    def test_no_secrets_exposed(self):
        key = "sk-t1-sentinel-DO-NOT-LEAK-91c2"
        with users_env(FATHOM_LLM_URL="http://127.0.0.1:9/v1", FATHOM_LLM_MODEL="t1-model", FATHOM_LLM_API_KEY=key) as (app, data, cookies, pw):
            secret_file = data / "secret.key"
            self.assertTrue(secret_file.exists(), fr("FR-SEC-06", "3.26", "secret.key created on first need"))
            sk = secret_file.read_text().strip()
            self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", sk), fr("FR-SEC-06", "4.10", "32 random bytes hex"))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(secret_file.stat().st_mode), 0o600, fr("FR-SEC-06", "3.26", "mode 0600"))
            hashes = [u["hash"] if "hash" in u else u.get("password", "") for u in json.loads((data / "users.json").read_text()).get("users", [])] \
                if isinstance(json.loads((data / "users.json").read_text()), dict) else []
            admin = {"Cookie": cookies["admin"]}
            bodies = []
            for path in ("/api/v2/meta", "/api/openapi.json", "/api/v2/session", "/api/v2/users", "/api/meta", "/api/docs", "/api/v2/projects/proj"):
                st, h, b = call(app, "GET", path, headers=admin)
                self.assertEqual(st, 200, path)
                bodies.append((path, b))
            for path, b in bodies:
                self.assertNotIn(key.encode(), b, fr("FR-SEC-06", "8.4 #8", "LLM API key in %s" % path))
                self.assertNotIn(sk.encode(), b, fr("FR-SEC-06", "8.4 #8", "secret.key in %s" % path))
                self.assertNotIn(b"pbkdf2_sha256$", b, fr("FR-SEC-06", "8.4 #8", "password hash in %s" % path))
                for pwd in pw.values():
                    self.assertNotIn(pwd.encode(), b)
            st, h, b = call(app, "GET", "/api/v2/meta", headers=admin)
            llm = jbody(b)["capabilities"]["llm"]
            self.assertTrue(llm["configured"])
            self.assertEqual(llm["model"], "t1-model")
            st, h, b = call(app, "POST", "/api/v2/projects/proj/builds", {}, dict(admin, **JSON_H))
            if st == 201:
                run = data / "builds" / "proj" / jbody(b)["build"]
                for f in run.rglob("*"):
                    if f.is_file() and f.suffix != ".zip":
                        content = f.read_bytes()
                        self.assertNotIn(key.encode(), content, fr("FR-SEC-06", "8.4 #8", "build file %s" % f.name))
                        self.assertNotIn(sk.encode(), content)
                        self.assertNotIn(b"pbkdf2_sha256$", content)


class Locking(unittest.TestCase):
    def test_concurrent_changes_lock(self):
        project = requires("project")
        with temp_data_dir() as data:
            pdir = install_sunday(data, uniq("lock"))
            doc, _ = project.load_doc(pdir.name)
            start = doc["revision"]
            devices = [d["id"] for d in doc["devices"]][:10]
            revs, errors = [], []
            lock = threading.Lock()

            def worker(dev):
                base = start
                for j in range(10):
                    for attempt in range(50):
                        try:
                            res = project.apply_changes(pdir, [{"op": "merge", "coll": "devices", "id": dev, "value": {"patch": {"k%d" % j: j}}}],
                                                        base_revision=base, author="t-" + dev, summary="%s %d" % (dev, j))
                            with lock:
                                revs.append(res["revision"])
                            base = res["revision"]
                            break
                        except project.ConflictError as e:  # pragma: no cover - disjoint refs should rebase
                            base = getattr(e, "revision", base)
                        except Exception as e:  # pragma: no cover
                            with lock:
                                errors.append(repr(e))
                            return

            threads = [threading.Thread(target=worker, args=(d,)) for d in devices]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
            self.assertEqual(errors, [], fr("FR-SEC-07", "3.26"))
            self.assertEqual(sorted(revs), list(range(start + 1, start + 101)), fr("FR-SEC-07", "3.26", "10x10 changes -> revisions %d..%d" % (start + 1, start + 100)))
            final, _ = project.load_doc(pdir.name)
            self.assertEqual(final["revision"], start + 100)
            by_id = {d["id"]: d for d in final["devices"]}
            for dev in devices:
                patch = by_id[dev].get("patch", {})
                for j in range(10):
                    self.assertEqual(patch.get("k%d" % j), j, fr("FR-SEC-07", "3.26", "lost update on %s k%d" % (dev, j)))
            lines = (pdir / "history" / "index.jsonl").read_text().strip().splitlines()
            self.assertEqual(len({json.loads(x)["revision"] for x in lines}), len(lines), "history revisions unique")


class Errors(unittest.TestCase):
    def test_500_has_no_trace(self):
        app = get_app()
        search = requires("search")
        with temp_data_dir() as data:
            name = uniq("boom")
            install_sunday(data, name)
            err = io.StringIO()

            def boom(*a, **k):
                raise RuntimeError("t1-boom-internal-detail")

            with mock.patch.object(search, "build_index", boom), mock.patch.object(search, "search", boom), contextlib.redirect_stderr(err):
                st, h, b = call(app, "GET", "/api/v2/projects/%s/search?q=zzz-%s" % (name, uniq()))
            self.assertEqual(st, 500, fr("FR-SEC-08", "3.26", "forced handler error -> 500"))
            j = jbody(b)
            self.assertEqual(set(j), {"error", "id"} | ({"code"} if "code" in j else set()), fr("FR-SEC-08", "3.26", "body keys %s" % sorted(j)))
            self.assertEqual(j["error"], "internal error")
            self.assertTrue(re.fullmatch(r"[0-9a-f]{8}", j["id"]), fr("FR-SEC-08", "3.26", "8-hex id"))
            self.assertNotIn(b"Traceback", b, fr("FR-SEC-08", "8.4 #9"))
            self.assertNotIn(b"t1-boom", b, fr("FR-SEC-08", "8.4 #9"))
            self.assertIn(j["id"], err.getvalue(), fr("FR-SEC-08", "3.26", "traceback with id goes to stderr"))

    def test_error_bodies_shape(self):
        app = get_app()
        with temp_data_dir():
            for method, path, status in (("GET", "/api/v2/projects/nope", 404), ("GET", "/no/such/route", 404), ("DELETE", "/api/v2/meta", 405)):
                st, h, b = call(app, method, path)
                self.assertEqual(st, status)
                j = jbody(b)
                self.assertIn("error", j, "5.1 error shape")
                self.assertIn("code", j, "5.1 error shape")
                self.assertNotIn(b"Traceback", b)


class Roles(unittest.TestCase):
    def test_role_matrix(self):
        server = requires("server")
        table = routes(server)
        self.assertGreater(len(table), 50, "route table available")
        with users_env() as (app, data, cookies, pw):
            unknown, mismatched, failures = [], [], []
            for method, pattern, declared in table:
                url, tmpl = concrete(pattern)
                need, known = spec_role(method, tmpl)
                if not known:
                    unknown.append("%s %s" % (method, tmpl))
                if declared is not None and declared != need and not (need in ("public", "any") and declared in ("public", "any")):
                    mismatched.append("%s %s declared %s, spec %s" % (method, tmpl, declared, need))
                if need in ("public", "any"):
                    continue
                if method == "GET" and tmpl.startswith("/static"):
                    continue
                body = None if method in ("GET", "DELETE") else {}
                for role in ("viewer", "editor", "admin"):
                    h = {"Cookie": cookies[role], "X-Fathom": "1"}
                    if body is not None:
                        h["Content-Type"] = "application/json"
                    st, _, b = call(app, method, url, body, h)
                    if RANK[role] < RANK[need]:
                        if st != 403:
                            failures.append("%s %s as %s -> %s (expected 403)" % (method, url, role, st))
                    elif st in (401, 403):
                        failures.append("%s %s as %s -> %s (expected access)" % (method, url, role, st))
                st, _, _ = call(app, method, url, body, {"X-Fathom": "1", "Content-Type": "application/json"} if body is not None else None)
                if st not in (401, 302):
                    failures.append("%s %s unauthenticated -> %s (expected 401/302)" % (method, url, st))
            self.assertEqual(failures, [], fr("FR-USER-01", "5.2 / 8.4 #7", "\n" + "\n".join(failures)))
            self.assertEqual(mismatched, [], fr("FR-USER-01", "5.2", "declared route roles differ from the spec:\n" + "\n".join(mismatched)))
            if unknown:
                sys.stderr.write("\n[T1] routes not named in SPEC §5 (checked with default roles): %s\n" % ", ".join(unknown))

    def test_viewer_put_403_and_users_admin_only(self):
        with users_env() as (app, data, cookies, pw):
            st, h, b = call(app, "GET", "/api/v2/projects/proj", headers={"Cookie": cookies["viewer"]})
            self.assertEqual(st, 200)
            j = jbody(b)
            self.assertEqual(j["role"], "viewer")
            st, _, _ = call(app, "PUT", "/api/v2/projects/proj", {"doc": j["doc"]}, {"Cookie": cookies["viewer"], "If-Match": h["etag"], "Content-Type": "application/json"})
            self.assertEqual(st, 403, fr("FR-USER-01", "3.20", "viewer PUT -> 403"))
            st, _, b = call(app, "GET", "/api/v2/users", headers={"Cookie": cookies["admin"]})
            self.assertEqual(st, 200)
            for u in jbody(b)["users"]:
                self.assertEqual(set(u) >= {"username", "role", "disabled", "created", "projects"}, True, "5.3 user shape")
                self.assertFalse([k for k in u if "hash" in k or "password" in k], "5.3 never hashes")
            adm = {"Cookie": cookies["admin"], "Content-Type": "application/json"}
            st, _, b = call(app, "POST", "/api/v2/users", {"username": "neo", "password": "short", "role": "viewer"}, adm)
            self.assertEqual(st, 400, "5.3 weak password (< 8 chars) -> 400")
            st, _, b = call(app, "POST", "/api/v2/users", {"username": "neo", "password": "long-enough-pw", "role": "viewer"}, adm)
            self.assertEqual(st, 201)
            st, _, b = call(app, "POST", "/api/v2/users", {"username": "neo", "password": "long-enough-pw", "role": "viewer"}, adm)
            self.assertEqual((st, jbody(b).get("code")), (409, "exists"))
            st, _, b = call(app, "PATCH", "/api/v2/users/neo", {"role": "editor"}, adm)
            self.assertEqual((st, jbody(b)["user"]["role"]), (200, "editor"))
            st, _, _ = call(app, "PATCH", "/api/v2/users/ghost", {"role": "editor"}, adm)
            self.assertEqual(st, 404)
            st, _, _ = call(app, "DELETE", "/api/v2/users/neo", headers=adm)
            self.assertEqual(st, 204)
            st, _, _ = call(app, "DELETE", "/api/v2/users/ada", headers=adm)
            self.assertEqual(st, 409, "5.3 deleting the last enabled admin -> 409")
            st, _, b = call(app, "POST", "/api/v2/users/me/password", {"old": "wrong-old-pw", "new": "brand-new-pw-1"},
                            {"Cookie": cookies["viewer"], "Content-Type": "application/json"})
            self.assertEqual(st, 403, "5.3 wrong old password -> 403")


class Passwords(unittest.TestCase):
    def test_password_hash_format(self):
        users = requires("users")
        with temp_data_dir() as data:
            h = users.hash_password("correct horse battery")
            m = re.fullmatch(r"pbkdf2_sha256\$600000\$([A-Za-z0-9+/=_-]+)\$([A-Za-z0-9+/=_-]+)", h)
            self.assertTrue(m, fr("FR-USER-02", "3.20", "stored format %r" % h))
            dec = lambda s: base64.b64decode(s + "=" * (-len(s) % 4), altchars=b"-_" if ("-" in s or "_" in s) else None)  # noqa: E731
            salt, digest = dec(m.group(1)), dec(m.group(2))
            self.assertEqual(len(salt), 16, fr("FR-USER-02", "3.20", "16-byte salt"))
            self.assertEqual(digest, hashlib.pbkdf2_hmac("sha256", b"correct horse battery", salt, 600000), fr("FR-USER-02", "3.20", "PBKDF2-HMAC-SHA256"))
            self.assertTrue(users.check_password(h, "correct horse battery"))
            self.assertFalse(users.check_password(h, "wrong"))
            self.assertNotEqual(h, users.hash_password("correct horse battery"), "random salt")
            users.add_user("pat", "plain-text-pw-123", role="editor")
            raw = (data / "users.json").read_text()
            self.assertNotIn("plain-text-pw-123", raw, fr("FR-USER-02", "3.20", "users.json never contains a plaintext password"))
            self.assertIn("pbkdf2_sha256$600000$", raw)
            self.assertIsNotNone(users.verify("pat", "plain-text-pw-123"))
            self.assertIsNone(users.verify("pat", "nope"))
        src = inspect.getsource(users)
        self.assertIn("compare_digest", src, fr("FR-USER-02", "8.4 #5", "constant-time comparisons"))
        server = requires("server")
        self.assertTrue("compare_digest" in src or "compare_digest" in inspect.getsource(server))

    def test_session_cookie_flags_and_epoch(self):
        with users_env() as (app, data, cookies, pw):
            users = requires("users")
            st, h, b = call(app, "POST", "/api/v2/session", {"username": "eve", "password": pw["eve"]}, {"Content-Type": "application/json"})
            self.assertEqual(st, 200)
            self.assertEqual(jbody(b)["user"], {"username": "eve", "role": "editor"})
            sc = [c for c in h.all("set-cookie") if c.startswith("fathom_session=")][0]
            attrs = [a.strip().lower() for a in sc.split(";")]
            self.assertIn("httponly", attrs, fr("FR-USER-03", "8.4 #6"))
            self.assertIn("samesite=lax", attrs, fr("FR-USER-03", "8.4 #6"))
            self.assertIn("max-age=1209600", attrs, fr("FR-USER-03", "3.20", "14 days"))
            self.assertIn("path=/", attrs, fr("FR-USER-03", "3.20", "Path = app root"))
            self.assertNotIn("secure", attrs, "no Secure flag on plain HTTP")
            value = sc.split(";")[0].split("=", 1)[1]
            payload_b64, sig = value.split(".")
            payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
            self.assertEqual(set(payload), {"u", "exp", "ep"}, fr("FR-USER-03", "5.3", "cookie payload"))
            self.assertEqual(payload["u"], "eve")
            self.assertGreater(payload["exp"], time.time() + 13 * 86400)
            st, h, b = call(app, "POST", "/api/v2/session", {"username": "eve", "password": pw["eve"]},
                            {"Content-Type": "application/json", "__https__": "1"})
            sc2 = [c for c in h.all("set-cookie") if c.startswith("fathom_session=")][0]
            self.assertIn("secure", [a.strip().lower() for a in sc2.split(";")], fr("FR-USER-03", "3.20", "Secure on HTTPS"))
            st, h, b = call(app, "POST", "/api/v2/session", {"username": "eve", "password": pw["eve"]},
                            {"Content-Type": "application/json", "__script_name__": "/fathom"})
            sc3 = [c for c in h.all("set-cookie") if c.startswith("fathom_session=")][0]
            self.assertIn("path=/fathom", [a.strip().lower().rstrip("/") for a in sc3.split(";")], fr("FR-USER-03", "3.20", "Path = app root under a prefix"))
            ck = {"Cookie": "fathom_session=" + value}
            st, _, b = call(app, "GET", "/api/v2/session", headers=ck)
            s = jbody(b)
            self.assertTrue(s["auth_enabled"])
            self.assertTrue(s["authenticated"])
            self.assertEqual(s["user"], {"username": "eve", "role": "editor"})
            tampered = {"Cookie": "fathom_session=" + payload_b64 + "." + ("A" * len(sig))}
            st, _, b = call(app, "GET", "/api/v2/projects", headers=tampered)
            self.assertEqual(st, 401, "bad signature rejected")
            st, _, b = call(app, "POST", "/api/v2/session", {"username": "eve", "password": "wrong-password"}, {"Content-Type": "application/json"})
            self.assertEqual((st, jbody(b).get("code")), (401, "bad_credentials"), "5.3")
            users.set_password("eve", "eve-password-2")
            st, _, _ = call(app, "GET", "/api/v2/projects", headers=ck)
            self.assertEqual(st, 401, fr("FR-USER-03", "3.20", "password change bumps epoch; old sessions invalid"))
            st, h, b = call(app, "DELETE", "/api/v2/session", headers={"Cookie": cookies["viewer"]})
            self.assertEqual(st, 200)
            self.assertEqual(jbody(b), {"ok": True})
            out = [c for c in h.all("set-cookie") if c.startswith("fathom_session=")]
            self.assertTrue(out and ("max-age=0" in out[0].lower() or "expires=" in out[0].lower()), "5.3 logout expires the cookie")
            users.set_disabled("vic", True)
            st, _, _ = call(app, "GET", "/api/v2/projects", headers={"Cookie": cookies["viewer"]})
            self.assertEqual(st, 401, "5.3 disabled user's session invalid")

    def test_login_flow_and_stale_duplicate_cookies(self):
        """Login over plain http and a stale duplicate fathom_session cookie must not cause a /login <-> / loop."""
        with users_env() as (app, data, cookies, pw):
            html = {"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
            st, h, _ = call(app, "GET", "/", headers=html)
            self.assertEqual(st, 302)
            self.assertEqual(h.get("location"), "/login?next=%2F")
            st, h, b = call(app, "GET", "/login?next=%2F", headers=html)
            self.assertEqual(st, 200, "login page is public")
            self.assertIn(b'id="login-form"', b)
            self.assertIn(b"static/js/app.js", b)
            st, h, b = call(app, "POST", "/api/v2/session", {"username": "eve", "password": pw["eve"]}, {"Content-Type": "application/json"})
            self.assertEqual(st, 200)
            sc = [c for c in h.all("set-cookie") if c.startswith("fathom_session=")][0]
            value = sc.split(";")[0].split("=", 1)[1]
            self.assertNotIn("secure", [a.strip().lower() for a in sc.split(";")], "cookie usable over http://")
            # browsers send every cookie of that name, most specific Path first; a stale one must not win
            for header in ("fathom_session=stale.sig; fathom_session=" + value,
                           "fathom_session=" + value + "; fathom_session=stale.sig",
                           "fathom_session=; other=1; fathom_session=" + value):
                st, h, _ = call(app, "GET", "/", headers=dict(html, Cookie=header))
                self.assertEqual(st, 200, "app page with cookies %r" % header)
                st, _, b = call(app, "GET", "/api/v2/session", headers={"Cookie": header})
                self.assertTrue(jbody(b)["authenticated"], "session with cookies %r" % header)
            st, h, _ = call(app, "GET", "/login", headers=dict(html, Cookie="fathom_session=" + value))
            self.assertEqual(st, 200, "login page never redirects server-side (the client decides)")
            st, _, b = call(app, "GET", "/api/v2/session", headers={"Cookie": "fathom_session=stale.sig; fathom_session=also.bad"})
            self.assertFalse(jbody(b)["authenticated"])
            st, _, _ = call(app, "GET", "/", headers=dict(html, Cookie="fathom_session=stale.sig"))
            self.assertEqual(st, 302)

    def test_basic_auth_users_and_env(self):
        app = get_app()
        users = requires("users")
        with temp_data_dir(FATHOM_AUTH="root:env-secret-1,ops:env-secret-2") as data:
            install_sunday(data, "proj")
            users.add_user("ulla", "ulla-password-1", role="viewer")
            st, _, b = call(app, "GET", "/api/v2/projects", headers=basic("ulla", "ulla-password-1"))
            self.assertEqual(st, 200, fr("FR-USER-04", "3.20", "Basic for a users.json user"))
            st, _, b = call(app, "GET", "/api/v2/session", headers=basic("ops", "env-secret-2"))
            s = jbody(b)
            self.assertEqual(s["user"], {"username": "ops", "role": "admin"}, fr("FR-USER-05", "3.20", "FATHOM_AUTH users are admins"))
            st, _, _ = call(app, "DELETE", "/api/v2/projects/proj?confirm=proj", headers=basic("root", "env-secret-1"))
            self.assertEqual(st, 200)
            st, h, _ = call(app, "GET", "/api/v2/projects", headers=basic("root", "wrong"))
            self.assertEqual(st, 401)
            self.assertEqual(h.get("www-authenticate"), 'Basic realm="Fathom"', "5.1 WWW-Authenticate when a Basic header was sent")
            st, h, _ = call(app, "GET", "/api/v2/projects", headers={"Accept": "text/html"})
            self.assertEqual(st, 401)
            self.assertIsNone(h.get("www-authenticate"), "5.1 no WWW-Authenticate for HTML requests without Basic")
            st, h, _ = call(app, "GET", "/", headers={"Accept": "text/html"})
            self.assertEqual(st, 302, "5.1 unauthenticated app page -> 302 /login")
            self.assertTrue(h.get("location", "").endswith("login?next=/") or "login?next=" in h.get("location", ""))
            self.assertFalse((data / "users.json").read_text().count("env-secret"), "FATHOM_AUTH users are in memory only")

    def test_auth_off_is_admin(self):
        app = get_app()
        users = requires("users")
        with temp_data_dir() as data:
            self.assertFalse(users.auth_enabled(), fr("FR-USER-05", "3.20"))
            st, _, b = call(app, "GET", "/api/v2/session")
            s = jbody(b)
            self.assertFalse(s["auth_enabled"])
            self.assertEqual((s.get("user") or {"role": "admin"}).get("role"), "admin")
            install_sunday(data, "proj")
            st, _, _ = call(app, "DELETE", "/api/v2/projects/proj?confirm=proj")
            self.assertEqual(st, 200, fr("FR-USER-05", "2.3 item 8", "auth off -> admin 'local'"))
        with temp_data_dir(FATHOM_AUTH="a:b"):
            self.assertTrue(users.auth_enabled())
        with temp_data_dir():
            users.add_user("solo", "solo-password-1", role="viewer")
            self.assertTrue(users.auth_enabled(), "auth on when users.json has an enabled user")
            users.set_disabled("solo", True)
            self.assertFalse(users.auth_enabled(), "auth off when no enabled user")

    def test_public_view(self):
        app = get_app()
        with temp_data_dir(FATHOM_AUTH="root:env-secret-1", FATHOM_PUBLIC_VIEW="1") as data:
            install_sunday(data, "proj")
            run = data / "builds" / "proj" / "run1"
            run.mkdir(parents=True)
            (run / "index.html").write_text("<html>ok</html>")
            st, _, _ = call(app, "GET", "/p/proj")
            self.assertEqual(st, 200, fr("FR-USER-06", "3.20", "/p/** public"))
            st, _, _ = call(app, "GET", "/builds/proj/run1/index.html")
            self.assertEqual(st, 200, fr("FR-USER-06", "3.20", "/builds/** public"))
            st, _, _ = call(app, "GET", "/api/v2/projects")
            self.assertEqual(st, 401, "API stays private")
            st, _, b = call(app, "GET", "/api/v2/session")
            self.assertTrue(jbody(b)["public_view"])
        with temp_data_dir(FATHOM_AUTH="root:env-secret-1") as data:
            install_sunday(data, "proj")
            st, _, _ = call(app, "GET", "/p/proj")
            self.assertIn(st, (401, 302), "without PUBLIC_VIEW the viewer needs auth")

    def test_login_throttle(self):
        app = get_app()
        users = requires("users")
        with temp_data_dir():
            users.add_user("tess", "tess-password-1", role="viewer")
            for i in range(5):
                st, _, _ = call(app, "POST", "/api/v2/session", {"username": "tess", "password": "bad-%d" % i},
                                {"Content-Type": "application/json", "__remote_addr__": "10.1.2.3"})
                self.assertEqual(st, 401)
            st, _, b = call(app, "POST", "/api/v2/session", {"username": "tess", "password": "tess-password-1"},
                            {"Content-Type": "application/json", "__remote_addr__": "10.1.2.3"})
            self.assertEqual(st, 429, fr("FR-USER-10", "3.20", "6th attempt within 5 min -> 429"))
            self.assertEqual(jbody(b).get("code"), "throttled")
            st, _, _ = call(app, "POST", "/api/v2/session", {"username": "tess", "password": "tess-password-1"},
                            {"Content-Type": "application/json", "__remote_addr__": "10.9.9.9"})
            self.assertEqual(st, 200, "throttle is per (IP, username)")

    def test_cli_user_commands(self):
        cli = requires("cli")
        users = requires("users")

        def run(args, stdin=""):
            out = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO(stdin)), mock.patch("getpass.getpass", lambda *a, **k: stdin.splitlines()[0] if stdin else ""), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                try:
                    cli.main(args)
                except SystemExit as e:
                    if e.code not in (0, None):
                        raise AssertionError("fathom %s exited %r: %s" % (" ".join(args), e.code, out.getvalue()))
            return out.getvalue()

        with temp_data_dir() as data:
            run(["user", "add", "carol", "--role", "viewer", "--password-stdin"], "carol-password-1\n")
            self.assertEqual([(u["username"], u["role"]) for u in users.list_users()], [("carol", "viewer")], fr("FR-USER-07", "3.20", "user add"))
            self.assertIn("carol", run(["user", "list"]))
            run(["user", "role", "carol", "editor"])
            self.assertEqual(users.list_users()[0]["role"], "editor", fr("FR-USER-07", "3.20", "user role"))
            run(["user", "passwd", "carol"], "carol-password-2\ncarol-password-2\n")
            self.assertIsNotNone(users.verify("carol", "carol-password-2"), fr("FR-USER-07", "3.20", "user passwd"))
            run(["user", "remove", "carol"])
            self.assertEqual(users.list_users(), [], fr("FR-USER-07", "3.20", "user remove"))


class Sanitize(unittest.TestCase):
    def test_svg_sanitize(self):
        floorplan = requires("floorplan")
        evil = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="100" height="100" onload="alert(1)">'
                '<script>alert("x")</script><script type="text/javascript"><![CDATA[alert(2)]]></script>'
                '<rect id="r" width="10" height="10" onclick="alert(3)" onmouseover="alert(4)"/>'
                '<a href="javascript:alert(5)"><text>link</text></a><a xlink:href="JaVaScRiPt:alert(6)"><text>l2</text></a>'
                '<image href="https://evil.example/a.png"/><image xlink:href="http://evil.example/b.png"/>'
                '<use href="#r"/><image href="data:image/png;base64,iVBORw0KGgo="/><image href="data:text/html;base64,PHNjcmlwdD4="/>'
                '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">hi</div></foreignObject>'
                '<iframe src="https://evil.example"/><embed src="x.swf"/><object data="x"/>'
                '<style>@import url(https://evil.example/x.css);</style><circle r="5" style="fill:red"/></svg>')
        out = floorplan.sanitize_svg(evil)
        root = ET.fromstring(out)
        low = out.lower()
        for bad in ("<script", "onload", "onclick", "onmouseover", "javascript:", "foreignobject", "<iframe", "<embed", "<object",
                    "evil.example", "data:text/html"):
            self.assertNotIn(bad, low, fr("FR-PLAN-04", "3.8", "sanitize_svg drops %s" % bad))
        tags = [e.tag.split("}")[-1] for e in root.iter()]
        self.assertIn("rect", tags, "harmless content kept")
        self.assertIn("circle", tags)
        self.assertIn("#r", out, "FR-PLAN-04 #frag references kept")
        self.assertIn("data:image/png", out, "FR-PLAN-04 data:image/png kept")


class ParserSafety(unittest.TestCase):
    def test_xml_external_entity(self):
        floorplan = requires("floorplan")
        with temp_data_dir() as data:
            secret = data / "xxe.txt"
            secret.write_text(SECRET)
            evil = ('<?xml version="1.0"?><!DOCTYPE m [<!ENTITY x SYSTEM "file://%s">]>'
                    '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
                    '<mxCell id="a" value="&x;" style="rounded=0;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="10" height="10" as="geometry"/></mxCell>'
                    '</root></mxGraphModel>' % secret)
            try:
                res = floorplan.drawio_to_svg(evil)
                self.assertNotIn(SECRET.encode(), res.data, fr("FR-SEC-01", "8.4 #11", "external entities never resolved"))
            except Exception as e:  # a clean rejection is fine
                self.assertNotIn(SECRET, str(e))
            svg = '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file://%s">]><svg xmlns="http://www.w3.org/2000/svg"><text>&x;</text></svg>' % secret
            try:
                out = floorplan.sanitize_svg(svg)
                self.assertNotIn(SECRET, out, fr("FR-PLAN-04", "8.4 #11"))
            except Exception as e:
                self.assertNotIn(SECRET, str(e))

    def test_dxf_caps(self):
        floorplan = requires("floorplan")
        loop = ("0\nSECTION\n2\nBLOCKS\n0\nBLOCK\n8\n0\n2\nLOOP\n70\n0\n10\n0.0\n20\n0.0\n0\nLINE\n8\n0\n10\n0\n20\n0\n11\n1\n21\n1\n"
                "0\nINSERT\n8\n0\n2\nLOOP\n10\n1.0\n20\n1.0\n0\nENDBLK\n8\n0\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n"
                "0\nINSERT\n8\n0\n2\nLOOP\n10\n0.0\n20\n0.0\n0\nENDSEC\n0\nEOF\n")
        t = time.perf_counter()
        res = floorplan.dxf_to_svg(loop)
        self.assertLess(time.perf_counter() - t, 10, fr("FR-PLAN-03", "8.4 #11", "self-referencing INSERT terminates"))
        lines = res.data.count(b"<line") + res.data.count(b"<path")
        self.assertLessEqual(lines, 9 + 2, fr("FR-PLAN-03", "3.8", "INSERT nesting <= 8 (got %d drawn elements)" % lines))
        n = 50000
        body = "".join("0\nLINE\n8\nWALLS\n10\n%d\n20\n0\n11\n%d\n21\n1\n" % (i % 1000, i % 1000) for i in range(n))
        big = "0\nSECTION\n2\nENTITIES\n" + body + "0\nENDSEC\n0\nEOF\n"
        t = time.perf_counter()
        res = floorplan.dxf_to_svg(big)
        dt = time.perf_counter() - t
        if dt > 5:
            sys.stderr.write("\n[T1 soft] DXF 50k entities took %.1f s (target 5 s)\n" % dt)
        self.assertLess(dt, 15, "8.2 DXF 50 000 entities (soft target 5 s): %.1f s" % dt)
        self.assertLess(len(res.data), 30 * 1024 * 1024, "8.2 SVG <= 30 MB")


if __name__ == "__main__":
    unittest.main()
