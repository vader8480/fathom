"""Project trash (SPEC FR-INV-07, §4.10 ``trash/``, §5.6 ``/api/v2/trash``)."""

from __future__ import annotations

import contextlib
import io
import json
import unittest

try:
    from _helpers import call, fr, get_app, install_sunday, jbody, requires, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import call, fr, get_app, install_sunday, jbody, requires, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}


def _names(app):
    st, _, b = call(app, "GET", "/api/v2/projects")
    assert st == 200, b[:200]
    return [p["name"] for p in jbody(b)["projects"]]


class TrashApi(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.project = requires("project")

    def test_trash_list_restore(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            run = data / "builds" / "proj" / "2026-01-01_000000_x"
            run.mkdir(parents=True)
            (run / "index.html").write_text("<html>ok</html>")
            st, _, b = call(self.app, "DELETE", "/api/v2/projects/proj", headers={"X-Fathom": "1"})
            self.assertEqual(st, 400, "confirm required")
            st, _, b = call(self.app, "DELETE", "/api/v2/projects/proj?confirm=proj", headers={"X-Fathom": "1"})
            self.assertEqual(st, 200, b[:300])
            self.assertEqual(jbody(b), {"ok": True, "trashed": True}, fr("FR-INV-07", "5.6"))
            self.assertNotIn("proj", _names(self.app), "trashed projects are not listed")
            self.assertFalse((data / "projects" / "proj").exists())
            self.assertFalse((data / "builds" / "proj").exists(), "builds move with the project")
            tdir = data / "trash" / "proj"
            self.assertTrue((tdir / "project.json").is_file())
            self.assertTrue((tdir / ".builds" / run.name / "index.html").is_file())
            marker = json.loads((tdir / ".trashed").read_text())
            self.assertEqual(marker["name"], "proj")
            self.assertEqual(marker["by"], "local")
            self.assertTrue(marker["at"].endswith("Z"))
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj")
            self.assertEqual(st, 404)

            st, _, b = call(self.app, "GET", "/api/v2/trash")
            self.assertEqual(st, 200, b[:300])
            j = jbody(b)
            self.assertEqual(j["retention_days"], 30)
            self.assertEqual(len(j["items"]), 1)
            item = j["items"][0]
            self.assertEqual((item["name"], item["dir"], item["trashed_by"], item["rooms"], item["devices"]), ("proj", "proj", "local", 1, 12))
            self.assertEqual(item["trashed_at"], marker["at"])

            st, _, b = call(self.app, "POST", "/api/v2/trash/proj/restore", headers={"X-Fathom": "1"})
            self.assertEqual(st, 200, b[:300])
            self.assertEqual(jbody(b), {"ok": True, "name": "proj"})
            self.assertIn("proj", _names(self.app))
            self.assertFalse((data / "trash" / "proj").exists())
            self.assertTrue((data / "builds" / "proj" / run.name / "index.html").is_file(), "builds come back")
            self.assertFalse((data / "projects" / "proj" / ".trashed").exists())
            st, _, b = call(self.app, "GET", "/api/v2/projects/proj")
            self.assertEqual(st, 200)
            self.assertEqual(len(jbody(b)["doc"]["devices"]), 12)
            st, _, b = call(self.app, "GET", "/api/v2/trash")
            self.assertEqual(jbody(b)["items"], [])

    def test_purge_and_unknown(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            st, _, _ = call(self.app, "DELETE", "/api/v2/projects/proj?confirm=proj", headers={"X-Fathom": "1"})
            self.assertEqual(st, 200)
            st, _, b = call(self.app, "DELETE", "/api/v2/trash/proj", headers={"X-Fathom": "1"})
            self.assertEqual(st, 200, b[:300])
            self.assertEqual(jbody(b), {"ok": True})
            self.assertFalse((data / "trash" / "proj").exists())
            st, _, _ = call(self.app, "DELETE", "/api/v2/trash/proj", headers={"X-Fathom": "1"})
            self.assertEqual(st, 404)
            st, _, _ = call(self.app, "POST", "/api/v2/trash/proj/restore", headers={"X-Fathom": "1"})
            self.assertEqual(st, 404)
            st, _, _ = call(self.app, "POST", "/api/v2/trash/..%2fprojects/restore", headers={"X-Fathom": "1"})
            self.assertIn(st, (400, 404))

    def test_purge_flag_deletes_for_good(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            st, _, b = call(self.app, "DELETE", "/api/v2/projects/proj?confirm=proj&purge=1", headers={"X-Fathom": "1"})
            self.assertEqual(st, 200, b[:300])
            self.assertEqual(jbody(b), {"ok": True, "trashed": False})
            self.assertFalse((data / "projects" / "proj").exists())
            self.assertFalse((data / "trash").exists() and any((data / "trash").iterdir()))
            st, _, b = call(self.app, "GET", "/api/v2/trash")
            self.assertEqual(jbody(b)["items"], [])

    def test_name_collision(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            st, _, _ = call(self.app, "DELETE", "/api/v2/projects/proj?confirm=proj", headers={"X-Fathom": "1"})
            self.assertEqual(st, 200)
            install_sunday(data, "proj")  # a new live project with the same name
            st, _, b = call(self.app, "POST", "/api/v2/trash/proj/restore", headers={"X-Fathom": "1"})
            self.assertEqual(st, 409, b[:300])
            self.assertEqual(jbody(b)["code"], "exists")
            self.assertTrue((data / "trash" / "proj" / "project.json").is_file(), "still in the trash")
            # trashing the second one suffixes the trash dir and keeps the original name in the marker
            st, _, _ = call(self.app, "DELETE", "/api/v2/projects/proj?confirm=proj", headers={"X-Fathom": "1"})
            self.assertEqual(st, 200)
            st, _, b = call(self.app, "GET", "/api/v2/trash")
            items = jbody(b)["items"]
            self.assertEqual(len(items), 2)
            self.assertEqual({i["name"] for i in items}, {"proj"})
            dirs = sorted(i["dir"] for i in items)
            self.assertEqual(dirs[0], "proj")
            self.assertRegex(dirs[1], r"^proj-\d{14}$")
            st, _, b = call(self.app, "POST", "/api/v2/trash/%s/restore" % dirs[1], headers={"X-Fathom": "1"})
            self.assertEqual(st, 200, b[:300])
            self.assertEqual(jbody(b)["name"], "proj")
            self.assertIn("proj", _names(self.app))


class TrashStore(unittest.TestCase):
    def setUp(self):
        self.project = requires("project")

    def test_purge_expired(self):
        with temp_data_dir() as data:
            install_sunday(data, "old")
            install_sunday(data, "fresh")
            self.project.trash_project("old", by="t")
            self.project.trash_project("fresh", by="t")
            marker = data / "trash" / "old" / ".trashed"
            meta = json.loads(marker.read_text())
            meta["at"] = "2020-01-01T00:00:00Z"
            marker.write_text(json.dumps(meta))
            self.assertEqual(self.project.purge_expired(days=30), ["old"])
            self.assertFalse((data / "trash" / "old").exists())
            self.assertTrue((data / "trash" / "fresh").exists())
            self.assertEqual(self.project.purge_expired(days=30), [])
            # list_trashed purges opportunistically
            marker = data / "trash" / "fresh" / ".trashed"
            meta = json.loads(marker.read_text())
            meta["at"] = "2020-01-01T00:00:00Z"
            marker.write_text(json.dumps(meta))
            self.assertEqual(self.project.list_trashed(), [])
            self.assertFalse((data / "trash" / "fresh").exists())

    def test_delete_project_signature(self):
        with temp_data_dir() as data:
            install_sunday(data, "a")
            install_sunday(data, "b")
            self.project.delete_project("a")
            self.assertTrue((data / "trash" / "a" / ".trashed").is_file(), "delete_project trashes by default")
            self.project.delete_project("b", purge=True)
            self.assertFalse((data / "trash" / "b").exists())
            self.assertFalse((data / "projects" / "b").exists())
            self.assertEqual(self.project.list_projects(), [])

    def test_restore_errors(self):
        with temp_data_dir() as data:
            install_sunday(data, "a")
            self.project.trash_project("a")
            install_sunday(data, "a")
            with self.assertRaises(self.project.ProjectExists):
                self.project.restore_project("a")
            with self.assertRaises(FileNotFoundError):
                self.project.restore_project("nope")
            with self.assertRaises(FileNotFoundError):
                self.project.purge_project("nope")
            with self.assertRaises(FileNotFoundError):
                self.project.trash_project("nope")

    def test_cli(self):
        cli = requires("cli")
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            self.project.trash_project("proj", by="cli")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["trash", "list"])
            self.assertIn("proj\tproj\t", out.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["trash", "restore", "proj"])
            self.assertEqual(self.project.list_projects(), ["proj"])
            self.project.trash_project("proj")
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["trash", "purge", "proj"])
            self.assertFalse((data / "trash" / "proj").exists())
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["trash", "purge", "--expired"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["trash", "list"])
            self.assertIn("trash is empty", out.getvalue())


if __name__ == "__main__":
    unittest.main()
