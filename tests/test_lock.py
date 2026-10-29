"""Editing lock (SPEC FR-USER-12, §4.3.3 ``settings.locked``, §5.3 lock semantics): 423 on ``/changes`` and PUT while
locked, the unlock batch goes through, ``locked_by`` / ``locked_at`` are stamped and cleared server-side, the
project list carries the flags, validation of the settings keys."""

from __future__ import annotations

import copy
import unittest

try:
    from _helpers import basic, call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import basic, call, fr, get_app, install_sunday, jbody, requires, sunday_doc, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}


def _rev(app, name="proj"):
    st, _, b = call(app, "GET", "/api/v2/projects/" + name)
    assert st == 200, b[:200]
    return jbody(b)


def _lock_op(locked, extra=None):
    value = {"locked": locked}
    value.update(extra or {})
    return {"op": "root", "key": "settings", "value": value}


class LockChanges(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        requires("server")

    def _lock(self, rev):
        st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": rev, "ops": [_lock_op(True)]}, JSON_H)
        self.assertEqual(st, 200, b[:300])
        return jbody(b)["revision"]

    def test_lock_sets_by_at_and_blocks_edits(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            p = _rev(self.app)
            self.assertNotIn("locked", p["doc"]["settings"], "control: unlocked by default")
            rev = self._lock(p["revision"])
            s = _rev(self.app)["doc"]["settings"]
            self.assertIs(s["locked"], True)
            self.assertEqual(s["locked_by"], "local", fr("FR-USER-12", "5.3", "locked_by is stamped server-side"))
            self.assertRegex(s["locked_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            # any model edit is refused with 423
            op = {"op": "merge", "coll": "devices", "id": "wireless-mics", "value": {"note": "x"}}
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": rev, "ops": [op]}, JSON_H)
            self.assertEqual(st, 423, b[:300])
            e = jbody(b)
            self.assertEqual(e["code"], "locked", fr("FR-USER-12", "5.3", "423 code locked"))
            self.assertIn("locked", e["error"])
            self.assertEqual(e["details"]["locked_by"], "local")
            self.assertEqual(e["details"]["locked_at"], s["locked_at"])
            # a batch mixing the unlock with an edit is still refused
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": rev, "ops": [_lock_op(False), op]}, JSON_H)
            self.assertEqual(st, 423)
            # a settings patch touching other keys is refused
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": rev, "ops": [_lock_op(False, {"units": "metric"})]}, JSON_H)
            self.assertEqual(st, 423)
            self.assertEqual(_rev(self.app)["revision"], rev, "nothing was written")
            # the unlock itself goes through (any editor) and clears by / at
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": rev, "ops": [_lock_op(False)]}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            s = _rev(self.app)["doc"]["settings"]
            self.assertIs(s["locked"], False)
            self.assertNotIn("locked_by", s, "unlock clears locked_by")
            self.assertNotIn("locked_at", s)
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": jbody(b)["revision"], "ops": [op]}, JSON_H)
            self.assertEqual(st, 200, "edits work again")

    def test_client_sent_by_at_are_overridden_and_relock_keeps_them(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            p = _rev(self.app)
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes",
                            {"base_revision": p["revision"], "ops": [_lock_op(True, {"locked_by": "mallory", "locked_at": "1999-01-01T00:00:00Z"})]}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            s = _rev(self.app)["doc"]["settings"]
            self.assertEqual(s["locked_by"], "local", "the server decides who locked")
            self.assertNotEqual(s["locked_at"], "1999-01-01T00:00:00Z")
            first = (s["locked_by"], s["locked_at"])
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": jbody(b)["revision"], "ops": [_lock_op(True)]}, JSON_H)
            self.assertEqual(st, 200, "re-locking a locked project is a lock-only batch")
            s = _rev(self.app)["doc"]["settings"]
            self.assertEqual((s["locked_by"], s["locked_at"]), first, "re-lock keeps the original stamp")

    def test_lock_only_replace_op_allowed(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            p = _rev(self.app)
            rev = self._lock(p["revision"])
            settings = _rev(self.app)["doc"]["settings"]
            unlocked = dict(settings, locked=False)
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes",
                            {"base_revision": rev, "ops": [{"op": "root", "key": "settings", "value": unlocked, "replace": True}]}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            s = _rev(self.app)["doc"]["settings"]
            self.assertEqual((s["locked"], "locked_by" in s), (False, False))
            rev = self._lock(jbody(b)["revision"])
            settings = _rev(self.app)["doc"]["settings"]
            changed = dict(settings, locked=False, units="metric")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes",
                            {"base_revision": rev, "ops": [{"op": "root", "key": "settings", "value": changed, "replace": True}]}, JSON_H)
            self.assertEqual(st, 423, "a replace that also changes another key is refused")

    def test_other_writes_unaffected(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            p = _rev(self.app)
            rev = self._lock(p["revision"])
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/problems", {"text": "Hum on the PA"}, JSON_H)
            self.assertEqual(st, 201, "problem reports are not model edits: %s" % b[:200])
            st, _, b = call(self.app, "PUT", "/api/v2/projects/proj/pages/power-up", {"title": "Power up", "body": "# Hi", "base_revision": jbody(b)["revision"]}, JSON_H)
            self.assertIn(st, (200, 201), "SOP pages stay editable: %s" % b[:200])
            self.assertIs(_rev(self.app)["doc"]["settings"]["locked"], True)
            del rev


class LockPut(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        requires("server")

    def _put(self, doc, rev, **extra):
        body = {"doc": doc, "base_revision": rev}
        body.update(extra)
        return call(self.app, "PUT", "/api/v2/projects/proj", body, JSON_H)

    def test_put_423_unless_only_lock_keys_differ(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            p = _rev(self.app)
            doc = copy.deepcopy(p["doc"])
            doc["settings"]["locked"] = True
            st, _, b = self._put(doc, p["revision"])
            self.assertEqual(st, 200, b[:300])
            s = _rev(self.app)["doc"]["settings"]
            self.assertEqual((s["locked"], s["locked_by"]), (True, "local"), fr("FR-USER-12", "5.3", "PUT lock stamps by/at"))
            self.assertTrue(s["locked_at"])
            cur = _rev(self.app)
            edited = copy.deepcopy(cur["doc"])
            edited["devices"][0]["note"] = "changed"
            st, _, b = self._put(edited, cur["revision"])
            self.assertEqual(st, 423, b[:300])
            self.assertEqual(jbody(b)["code"], "locked")
            self.assertEqual(jbody(b)["details"]["locked_by"], "local")
            stale = copy.deepcopy(cur["doc"])
            stale["settings"]["units"] = "metric"
            stale["settings"]["locked"] = False
            st, _, b = self._put(stale, cur["revision"])
            self.assertEqual(st, 423, "unlock plus another settings change is refused")
            # the unlock itself (only lock keys differ) goes through; by/at are cleared
            unlock = copy.deepcopy(cur["doc"])
            unlock["settings"]["locked"] = False
            st, _, b = self._put(unlock, cur["revision"])
            self.assertEqual(st, 200, b[:300])
            s = _rev(self.app)["doc"]["settings"]
            self.assertEqual((s["locked"], "locked_by" in s, "locked_at" in s), (False, False, False))
            cur = _rev(self.app)
            edited = copy.deepcopy(cur["doc"])
            edited["devices"][0]["note"] = "changed"
            st, _, b = self._put(edited, cur["revision"])
            self.assertEqual(st, 200, "edits work again")

    def test_put_unlock_by_dropping_the_key(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            p = _rev(self.app)
            doc = copy.deepcopy(p["doc"])
            doc["settings"]["locked"] = True
            st, _, b = self._put(doc, p["revision"])
            self.assertEqual(st, 200)
            cur = _rev(self.app)
            doc = copy.deepcopy(cur["doc"])
            for k in ("locked", "locked_by", "locked_at"):
                doc["settings"].pop(k, None)
            st, _, b = self._put(doc, cur["revision"])
            self.assertEqual(st, 200, b[:300])
            s = _rev(self.app)["doc"]["settings"]
            self.assertFalse(s.get("locked"))
            self.assertNotIn("locked_by", s)


class LockListingAndSchema(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.schema = requires("schema")

    def test_project_list_carries_flags(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            doc = sunday_doc()
            doc["settings"].update({"locked": True, "locked_by": "ada", "locked_at": "2026-01-02T03:04:05Z"})
            install_sunday(data, "locked-proj")
            (data / "projects" / "locked-proj" / "project.json").write_text(__import__("json").dumps(doc))
            st, _, b = call(self.app, "GET", "/api/v2/projects")
            self.assertEqual(st, 200)
            rows = {p["name"]: p for p in jbody(b)["projects"]}
            self.assertEqual((rows["proj"]["locked"], rows["proj"]["locked_by"], rows["proj"]["locked_at"]), (False, "", ""))
            self.assertEqual((rows["locked-proj"]["locked"], rows["locked-proj"]["locked_by"], rows["locked-proj"]["locked_at"]),
                             (True, "ada", "2026-01-02T03:04:05Z"), fr("FR-USER-12", "5.6", "project list exposes the lock"))
            self.assertIn("role", rows["locked-proj"], "role is still there")

    def test_validation(self):
        S = self.schema
        doc = sunday_doc()
        doc["settings"]["locked"] = "yes"
        probs = [p for p in S.validate_doc(doc) if p["path"] == "settings/locked"]
        self.assertEqual([(p["level"], p["code"]) for p in probs], [("error", "bad_type")], fr("FR-USER-12", "4.3.3", "locked must be bool"))
        doc["settings"]["locked"] = True
        doc["settings"]["locked_by"] = 7
        probs = [p for p in S.validate_doc(doc) if p["path"].startswith("settings/locked")]
        self.assertEqual([p["path"] for p in probs], ["settings/locked_by"])
        doc["settings"]["locked_by"] = "ada"
        doc["settings"]["locked_at"] = "2026-01-02T03:04:05Z"
        self.assertEqual([p for p in S.validate_doc(doc) if p["path"].startswith("settings/locked")], [])
        props = S.JSON_SCHEMA["properties"]["settings"]["properties"]
        self.assertEqual(props["locked"], {"type": "boolean"})
        for k in ("locked_by", "locked_at", "suggest_url"):
            self.assertEqual(props[k]["type"], "string", k)

    def test_viewer_cannot_unlock_editor_can(self):
        users = requires("users")
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            users.add_user("ada", "ada-password-1", role="admin")
            users.add_user("eve", "eve-password-1", role="editor")
            users.add_user("vic", "vic-password-1", role="viewer")
            p = _rev_auth(self.app, "ada")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": p["revision"], "ops": [_lock_op(True)]},
                            dict(JSON_H, **basic("ada", "ada-password-1")))
            self.assertEqual(st, 200, b[:200])
            rev = jbody(b)["revision"]
            self.assertEqual(_rev_auth(self.app, "ada")["doc"]["settings"]["locked_by"], "ada")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": rev, "ops": [_lock_op(False)]},
                            dict(JSON_H, **basic("vic", "vic-password-1")))
            self.assertEqual(st, 403, "viewers never write")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": rev, "ops": [_lock_op(False)]},
                            dict(JSON_H, **basic("eve", "eve-password-1")))
            self.assertEqual(st, 200, fr("FR-USER-12", "5.3", "any editor may unlock: %s" % b[:200]))


def _rev_auth(app, user):
    st, _, b = call(app, "GET", "/api/v2/projects/proj", headers=basic(user, user + "-password-1"))
    assert st == 200, b[:200]
    return jbody(b)


if __name__ == "__main__":
    unittest.main()
