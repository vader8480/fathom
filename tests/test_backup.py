"""Whole-server backup and restore: contents, download, upload checks, restore round trip, roles, CLI."""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

try:
    from _helpers import basic, call, get_app, install_sunday, jbody, requires, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import basic, call, get_app, install_sunday, jbody, requires, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
ZIP_H = {"Content-Type": "application/zip", "X-Fathom": "1"}


def make_zip(entries, manifest=None):
    """A zip from {name: bytes}; ``manifest`` defaults to a valid one (pass False to omit)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        if manifest is not False:
            zf.writestr("manifest.json", json.dumps(manifest or {"format": "fathom-backup", "version": 1, "projects": []}))
    return buf.getvalue()


class BackupApi(unittest.TestCase):
    def setUp(self):
        requires("backup")
        self.app = get_app()

    def req(self, method, path, body=None, headers=None):
        h = dict(JSON_H if body is not None and not isinstance(body, bytes) else {})
        h.update(headers or {})
        return call(self.app, method, path, body, h)

    def create(self, **body):
        st, _, b = self.req("POST", "/api/v2/backups", body)
        self.assertEqual(st, 201, b)
        return jbody(b)["backup"]

    def test_backup_contents(self):
        with temp_data_dir() as data:
            pdir = install_sunday(data, "proj")
            (pdir / "files" / "att-000000000001").mkdir(parents=True)
            (pdir / "files" / "att-000000000001" / "photo.png").write_bytes(b"png" * 100)
            (pdir / ".lock").write_text("")
            (pdir / ".project.json.1.tmp").write_text("half")
            (data / "users.json").write_text('{"users": []}')
            (data / "builds" / "proj" / "run1").mkdir(parents=True)
            (data / "builds" / "proj" / "run1" / "index.html").write_text("<html></html>")
            (data / "backups").mkdir()
            (data / "backups" / "old.zip").write_bytes(b"old")
            (data / "outside.txt").write_text("secret")
            os.symlink(str(data / "outside.txt"), str(pdir / "link.txt"))

            info = self.create(label="before service")
            self.assertEqual(info["projects"], ["proj"])
            self.assertEqual(info["label"], "before service")
            self.assertFalse(info["include_builds"])
            with zipfile.ZipFile(data / "backups" / info["name"]) as zf:
                names = set(zf.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("data/projects/proj/project.json", names)
            self.assertIn("data/projects/proj/files/att-000000000001/photo.png", names)
            self.assertIn("data/users.json", names)
            self.assertIn("data/outside.txt", names)
            for bad in ("data/projects/proj/.lock", "data/projects/proj/.project.json.1.tmp", "data/projects/proj/link.txt",
                        "data/backups/old.zip", "data/builds/proj/run1/index.html"):
                self.assertNotIn(bad, names)

            with_builds = self.create(include_builds=True)
            with zipfile.ZipFile(data / "backups" / with_builds["name"]) as zf:
                self.assertIn("data/builds/proj/run1/index.html", zf.namelist())

    def test_list_download_delete(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            info = self.create()
            st, _, b = self.req("GET", "/api/v2/backups")
            self.assertEqual(st, 200)
            self.assertEqual([x["name"] for x in jbody(b)["backups"]], [info["name"]])
            st, h, body = self.req("GET", "/api/v2/backups/" + info["name"])
            self.assertEqual(st, 200)
            self.assertEqual(h["content-type"], "application/zip")
            self.assertIn("attachment", h["content-disposition"])
            self.assertEqual(int(h["content-length"]), len(body))
            self.assertEqual(body, (data / "backups" / info["name"]).read_bytes())
            st, h, body = call(self.app, "HEAD", "/api/v2/backups/" + info["name"])
            self.assertEqual((st, body), (200, b""))
            st, _, _ = self.req("DELETE", "/api/v2/backups/" + info["name"])
            self.assertEqual(st, 204)
            st, _, _ = self.req("GET", "/api/v2/backups/" + info["name"])
            self.assertEqual(st, 404)

    def test_round_trip_restore(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            install_sunday(data, "keep")
            info = self.create()
            st, _, zipb = self.req("GET", "/api/v2/backups/" + info["name"])
            # damage the live data: lose a project, add one, change a doc
            st, _, _ = self.req("DELETE", "/api/v2/projects/proj?confirm=proj")
            self.assertEqual(st, 200)
            install_sunday(data, "newer")
            (data / "builds" / "keep").mkdir(parents=True, exist_ok=True)
            (data / "builds" / "keep" / "marker").write_text("x")

            st, _, b = self.req("POST", "/api/v2/backups/upload", zipb, ZIP_H)
            self.assertEqual(st, 201, b)
            up = jbody(b)["backup"]["name"]
            self.assertTrue(up.endswith("-uploaded.zip"), up)

            st, _, b = self.req("POST", f"/api/v2/backups/{up}/restore", {})
            self.assertEqual(st, 400, "restore needs an explicit confirm")
            st, _, b = self.req("POST", f"/api/v2/backups/{up}/restore", {"confirm": up})
            self.assertEqual(st, 200, b)
            res = jbody(b)
            self.assertEqual(sorted(res["projects"]), ["keep", "proj"])
            pre = res["pre_restore_backup"]
            self.assertTrue(pre and pre.endswith("-pre-restore.zip"))

            st, _, b = self.req("GET", "/api/v2/projects")
            self.assertEqual(sorted(p["name"] for p in jbody(b)["projects"]), ["keep", "proj"])
            self.assertTrue((data / "builds" / "keep" / "marker").exists(), "builds untouched when the backup has none")
            self.assertFalse([p for p in data.iterdir() if p.name.startswith(".restore")], "staging folders cleaned up")

            # the pre-restore backup undoes the restore
            st, _, b = self.req("POST", f"/api/v2/backups/{pre}/restore", {"confirm": pre})
            self.assertEqual(st, 200, b)
            st, _, b = self.req("GET", "/api/v2/projects")
            self.assertEqual(sorted(p["name"] for p in jbody(b)["projects"]), ["keep", "newer"])

    def test_restore_replaces_builds_when_included(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            (data / "builds" / "proj").mkdir(parents=True, exist_ok=True)
            (data / "builds" / "proj" / "a.txt").write_text("a")
            info = self.create(include_builds=True)
            (data / "builds" / "proj" / "a.txt").unlink()
            (data / "builds" / "proj" / "b.txt").write_text("b")
            st, _, b = self.req("POST", f"/api/v2/backups/{info['name']}/restore", {"confirm": info["name"]})
            self.assertEqual(st, 200, b)
            self.assertTrue((data / "builds" / "proj" / "a.txt").exists())
            self.assertFalse((data / "builds" / "proj" / "b.txt").exists())

    def test_restore_refreshes_caches(self):
        backup = requires("backup")
        with temp_data_dir() as data:
            pdir = install_sunday(data, "proj")
            original = (pdir / "project.json").read_text()
            doc = json.loads(original)
            doc["devices"][0]["name"] = "Zzqq Unique Device"
            (pdir / "project.json").write_text(json.dumps(doc))
            info = self.create()
            (pdir / "project.json").write_text(original)
            st, _, b = self.req("GET", "/api/v2/projects/proj/search?q=zzqq")
            self.assertEqual((st, jbody(b)["hits"]), (200, []), "search index cached at the same revision number")
            backup.restore_backup(info["name"], safety=False)
            st, _, b = self.req("GET", "/api/v2/projects/proj/search?q=zzqq")
            self.assertTrue(jbody(b)["hits"], "a restore drops caches keyed by revision")

    def test_interrupted_restore_recovers(self):
        backup = requires("backup")
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            (data / "users.json").write_text('{"users": []}')
            old = data / ".restore-old-dead01"
            old.mkdir()
            os.replace(data / "projects", old / "projects")
            (data / ".restore-dead01" / "users.json").parent.mkdir()
            (data / ".restore-dead01" / "users.json").write_text("staged")
            backup.create_backup()
            self.assertTrue((data / "projects" / "proj" / "project.json").is_file(), "data moved out by a killed restore comes back")
            self.assertEqual((data / "users.json").read_text(), '{"users": []}')
            self.assertFalse([p for p in data.iterdir() if p.name.startswith(".restore")])

    def test_upload_rejects_bad_files(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            cases = {
                "not a zip": b"hello",
                "no manifest": make_zip({"data/projects/p/project.json": b"{}"}, manifest=False),
                "wrong format": make_zip({}, manifest={"format": "other", "version": 1}),
                "newer version": make_zip({}, manifest={"format": "fathom-backup", "version": 99}),
                "traversal": make_zip({"data/../../evil.txt": b"x"}),
                "absolute": make_zip({"/etc/evil": b"x"}),
                "outside data/": make_zip({"evil.txt": b"x"}),
                "dot entry": make_zip({"data/.generation": b"x"}),
                "nested backups": make_zip({"data/backups/x.zip": b"x"}),
            }
            for label, payload in cases.items():
                st, _, b = self.req("POST", "/api/v2/backups/upload", payload, ZIP_H)
                self.assertIn(st, (400, 413, 422), f"{label}: {st} {b!r}")
            link = io.BytesIO()
            with zipfile.ZipFile(link, "w") as zf:
                zi = zipfile.ZipInfo("data/projects/p/link")
                zi.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(zi, "/etc/passwd")
                zf.writestr("manifest.json", json.dumps({"format": "fathom-backup", "version": 1}))
            st, _, _ = self.req("POST", "/api/v2/backups/upload", link.getvalue(), ZIP_H)
            self.assertEqual(st, 422, "symlink entries refused")
            st, _, _ = self.req("POST", "/api/v2/backups/upload", make_zip({}), {"Content-Type": "application/json", "X-Fathom": "1"})
            self.assertEqual(st, 415)
            st, _, _ = call(self.app, "POST", "/api/v2/backups/upload", make_zip({}), {"Content-Type": "application/zip"})
            self.assertEqual(st, 403, "CSRF header required")
            self.assertEqual([p.name for p in (data / "backups").iterdir()], [], "rejected uploads leave nothing behind")
            self.assertFalse((data / "evil.txt").exists())

    def test_upload_size_cap(self):
        with temp_data_dir() as data, mock.patch.dict(os.environ, {"FATHOM_MAX_BACKUP_MB": "0.001"}):
            install_sunday(data, "proj")
            st, _, b = self.req("POST", "/api/v2/backups/upload", make_zip({"data/x": os.urandom(4096)}), ZIP_H)
            self.assertEqual(st, 413, b)

    def test_names_and_traversal(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            (data / "users.json").write_text('{"users": []}')
            for path in ("/api/v2/backups/..%2fusers.json", "/api/v2/backups/../users.json", "/api/v2/backups/x.zip", "/api/v2/backups/.partial.zip"):
                st, _, b = self.req("GET", path)
                self.assertIn(st, (404, 405), f"{path}: {st}")

    def test_admin_only(self):
        users = requires("users")
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            users.add_user("ada", "ada-password-1", role="admin")
            users.add_user("eve", "eve-password-1", role="editor")
            st, _, b = call(self.app, "POST", "/api/v2/backups", {}, dict(JSON_H, **basic("ada", "ada-password-1")))
            self.assertEqual(st, 201, b)
            name = jbody(b)["backup"]["name"]
            for method, path, body in (("GET", "/api/v2/backups", None), ("POST", "/api/v2/backups", {}),
                                       ("GET", "/api/v2/backups/" + name, None), ("DELETE", "/api/v2/backups/" + name, None),
                                       ("POST", f"/api/v2/backups/{name}/restore", {"confirm": name})):
                st, _, _ = call(self.app, method, path, body, dict(JSON_H, **basic("eve", "eve-password-1")))
                self.assertEqual(st, 403, f"editor {method} {path}")
                st, _, _ = call(self.app, method, path, body, JSON_H)
                self.assertEqual(st, 401, f"anonymous {method} {path}")

    def test_restore_brings_back_users(self):
        users = requires("users")
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            users.add_user("ada", "ada-password-1", role="admin")
            auth = dict(JSON_H, **basic("ada", "ada-password-1"))
            st, _, b = call(self.app, "POST", "/api/v2/backups", {}, auth)
            name = jbody(b)["backup"]["name"]
            users.add_user("mallory", "mallory-password", role="admin")
            st, _, b = call(self.app, "POST", f"/api/v2/backups/{name}/restore", {"confirm": name}, auth)
            self.assertEqual(st, 200, b)
            st, _, _ = call(self.app, "GET", "/api/v2/backups", None, basic("mallory", "mallory-password"))
            self.assertEqual(st, 401, "accounts added after the backup are gone")
            self.assertEqual(stat.S_IMODE((data / "users.json").stat().st_mode) & 0o077, 0, "users.json stays private")


class BackupCli(unittest.TestCase):
    def test_cli_create_list_restore(self):
        requires("backup")
        cli = requires("cli")
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            out = data.parent / (data.name + "-copy.zip")
            try:
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    cli.main(["backup", "create", "--label", "cli test", "--out", str(out)])
                self.assertIn("ok:", buf.getvalue())
                self.assertTrue(out.is_file())
                (data / "projects" / "proj" / "project.json").unlink()
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    cli.main(["backup", "restore", str(out), "--yes"])
                self.assertIn("restored", buf.getvalue())
                self.assertTrue((data / "projects" / "proj" / "project.json").is_file())
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    cli.main(["backup", "list"])
                self.assertIn("pre-restore", buf.getvalue())
                with mock.patch("builtins.input", return_value="no"), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        cli.main(["backup", "restore", str(out)])
            finally:
                if out.exists():
                    out.unlink()


if __name__ == "__main__":
    unittest.main()
