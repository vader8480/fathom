"""Invite links (SPEC FR-USER-11, §5.3 invites): ``users.create_invite`` & co, the public invite page / check / accept
routes, the session cookie set on accept, expiry, revocation and the ``fathom invite`` CLI."""

from __future__ import annotations

import contextlib
import io
import json
import time
import unittest

try:
    from _helpers import basic, call, fr, get_app, install_sunday, jbody, requires, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import basic, call, fr, get_app, install_sunday, jbody, requires, temp_data_dir

JSON_H = {"Content-Type": "application/json", "X-Fathom": "1"}
ADMIN = ("ada", "ada-password-1")
TOKEN_HINT = "inv-000000000000000000000000"


def _auth(username, password):
    h = dict(JSON_H)
    h.update(basic(username, password))
    return h


def _session_cookie(headers):
    return [c for c in headers.all("set-cookie") if c.startswith("fathom_session=")]


class InviteModule(unittest.TestCase):
    def setUp(self):
        self.users = requires("users")

    def test_create_list_get_revoke(self):
        U = self.users
        with temp_data_dir() as data:
            inv = U.create_invite("editor", {"proj": "viewer"}, created_by="ada", ttl_hours=1, note="for Sam")
            self.assertRegex(inv["token"], r"^inv-[A-Za-z0-9_-]{26}$", fr("FR-USER-11", "5.3", "token shape"))
            self.assertTrue(U.INVITE_RE.match(TOKEN_HINT), "the test_security PARAM_HINTS token matches the route regex")
            self.assertEqual((inv["role"], inv["projects"], inv["created_by"], inv["note"]), ("editor", {"proj": "viewer"}, "ada", "for Sam"))
            self.assertIsNone(inv["used_by"])
            self.assertTrue((data / "invites.json").is_file(), "stored in <data>/invites.json")
            self.assertEqual(json.loads((data / "invites.json").read_text())["invites"][0]["token"], inv["token"])
            self.assertEqual([i["token"] for i in U.list_invites()], [inv["token"]])
            self.assertEqual(U.get_invite(inv["token"])["role"], "editor")
            self.assertIsNone(U.get_invite("inv-nope"))
            self.assertIsNone(U.get_invite("sh-abc"))
            self.assertTrue(U.revoke_invite(inv["token"]))
            self.assertFalse(U.revoke_invite(inv["token"]), "second revoke → False")
            self.assertEqual(U.list_invites(), [])

    def test_validation(self):
        U = self.users
        with temp_data_dir():
            with self.assertRaises(U.UserError):
                U.create_invite("root")
            with self.assertRaises(U.UserError):
                U.create_invite("editor", {"proj": "admin"})
            with self.assertRaises(U.UserError):
                U.create_invite("editor", ttl_hours=0)
            with self.assertRaises(U.UserError):
                U.create_invite("editor", ttl_hours="soon")

    def test_redeem_marks_used_and_rejects_reuse(self):
        U = self.users
        with temp_data_dir():
            inv = U.create_invite("viewer", {"proj": "editor"})
            user = U.redeem_invite(inv["token"], "sam", "sam-password-1")
            self.assertEqual((user["username"], user["role"], user["projects"]), ("sam", "viewer", {"proj": "editor"}))
            self.assertEqual(U.effective_role(U.get_user("sam"), "proj"), "editor", "per-project override honoured")
            self.assertEqual(U.effective_role(U.get_user("sam"), "other"), "viewer")
            self.assertIsNone(U.get_invite(inv["token"]), "a used invite is no longer open")
            used = U.list_invites(include_used=True)[0]
            self.assertEqual(used["used_by"], "sam")
            self.assertTrue(used["used_at"])
            self.assertEqual(U.list_invites(), [], "used invites are not listed by default")
            with self.assertRaises(U.UserError) as cm:
                U.redeem_invite(inv["token"], "sam2", "sam2-password-1")
            self.assertEqual(cm.exception.code, "not_found")

    def test_redeem_duplicate_username_keeps_invite_open(self):
        U = self.users
        with temp_data_dir():
            U.add_user("sam", "sam-password-1", role="editor")
            inv = U.create_invite("editor")
            with self.assertRaises(U.UserError) as cm:
                U.redeem_invite(inv["token"], "sam", "another-password-1")
            self.assertEqual(cm.exception.code, "exists")
            with self.assertRaises(U.UserError) as cm:
                U.redeem_invite(inv["token"], "sam2", "short")
            self.assertEqual(cm.exception.code, "weak_password")
            self.assertIsNotNone(U.get_invite(inv["token"]), "a failed redeem leaves the invite open")

    def test_expired_pruned(self):
        U = self.users
        with temp_data_dir() as data:
            inv = U.create_invite("editor", ttl_hours=1)
            raw = json.loads((data / "invites.json").read_text())
            raw["invites"][0]["expires"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
            (data / "invites.json").write_text(json.dumps(raw))
            self.assertIsNone(U.get_invite(inv["token"]), "expired → None")
            self.assertEqual(U.list_invites(), [])
            self.assertEqual(json.loads((data / "invites.json").read_text())["invites"], [], "expired entries are pruned on list")
            with self.assertRaises(U.UserError):
                U.redeem_invite(inv["token"], "sam", "sam-password-1")


class InviteApi(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.users = requires("users")

    @contextlib.contextmanager
    def _admin(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            self.users.add_user(ADMIN[0], ADMIN[1], role="admin")
            yield data

    def test_create_check_accept_sets_cookie(self):
        with self._admin():
            st, _, b = call(self.app, "POST", "/api/v2/invites", {"role": "editor", "projects": {"proj": "viewer"}, "ttl_hours": 48, "note": "Sam"}, _auth(*ADMIN))
            self.assertEqual(st, 201, b[:300])
            inv = jbody(b)
            tok = inv["token"]
            self.assertEqual(inv["url"], "http://127.0.0.1/invite/" + tok, fr("FR-USER-11", "5.3", "absolute url from the request host"))
            self.assertEqual((inv["role"], inv["projects"], inv["created_by"], inv["note"]), ("editor", {"proj": "viewer"}, "ada", "Sam"))
            st, _, b = call(self.app, "GET", "/api/v2/invites", headers=basic(*ADMIN))
            self.assertEqual(st, 200)
            self.assertEqual([i["token"] for i in jbody(b)["invites"]], [tok])
            self.assertEqual(jbody(b)["accept_url"], "/invite/{token}")
            # the page and the check are public
            st, h, b = call(self.app, "GET", "/invite/" + tok)
            self.assertEqual(st, 200)
            self.assertIn(b"invite-form", b)
            self.assertIn("script-src 'self'", h.get("content-security-policy", ""), "app CSP (no inline scripts)")
            self.assertNotIn(b"onclick", b)
            st, _, b = call(self.app, "GET", "/invite/inv-doesnotexist000000000")
            self.assertEqual(st, 200, "the page renders for any token; the API decides")
            st, _, b = call(self.app, "GET", "/api/v2/invites/%s/check" % tok)
            self.assertEqual(st, 200, b[:200])
            chk = jbody(b)
            self.assertEqual((chk["ok"], chk["role"], chk["auth_enabled"]), (True, "editor", True))
            self.assertTrue(chk["expires"])
            st, _, b = call(self.app, "GET", "/api/v2/invites/inv-doesnotexist000000000/check")
            self.assertEqual((st, jbody(b)["code"]), (404, "invalid_invite"))
            # accept: creates the user, signs them in
            st, h, b = call(self.app, "POST", "/api/v2/invites/%s/accept" % tok, {"username": "sam", "password": "sam-password-1"}, JSON_H)
            self.assertEqual(st, 200, b[:300])
            self.assertEqual(jbody(b)["user"], {"username": "sam", "role": "editor", "projects": {"proj": "viewer"}})
            cookies = _session_cookie(h)
            self.assertEqual(len(cookies), 1, fr("FR-USER-03", "5.3", "accept sets the session cookie"))
            self.assertIn("HttpOnly", cookies[0])
            st, _, b = call(self.app, "GET", "/api/v2/session", headers={"Cookie": cookies[0].split(";")[0]})
            self.assertEqual(jbody(b)["user"]["username"], "sam", "the cookie is a live session")
            st, _, b = call(self.app, "GET", "/api/v2/projects", headers={"Cookie": cookies[0].split(";")[0]})
            self.assertEqual(jbody(b)["projects"][0]["role"], "viewer", "per-project override from the invite applies")
            # the link is one-time
            st, _, b = call(self.app, "GET", "/api/v2/invites/%s/check" % tok)
            self.assertEqual(st, 404)
            st, _, b = call(self.app, "POST", "/api/v2/invites/%s/accept" % tok, {"username": "sam2", "password": "sam2-password-1"}, JSON_H)
            self.assertEqual((st, jbody(b)["code"]), (404, "invalid_invite"))
            st, _, b = call(self.app, "GET", "/api/v2/users", headers=basic(*ADMIN))
            sam = next(u for u in jbody(b)["users"] if u["username"] == "sam")
            self.assertEqual((sam["role"], sam["projects"], sam["disabled"]), ("editor", {"proj": "viewer"}, False), "users list carries projects + disabled")

    def test_accept_errors(self):
        with self._admin():
            st, _, b = call(self.app, "POST", "/api/v2/invites", {"role": "viewer"}, _auth(*ADMIN))
            tok = jbody(b)["token"]
            st, _, b = call(self.app, "POST", "/api/v2/invites/%s/accept" % tok, {"username": "ada", "password": "whatever-123"}, JSON_H)
            self.assertEqual((st, jbody(b)["code"]), (409, "exists"), "duplicate username")
            st, _, b = call(self.app, "POST", "/api/v2/invites/%s/accept" % tok, {"username": "sam", "password": "short"}, JSON_H)
            self.assertEqual((st, jbody(b)["code"]), (400, "weak_password"))
            st, _, b = call(self.app, "POST", "/api/v2/invites/%s/accept" % tok, {"username": "bad name!", "password": "long-enough-1"}, JSON_H)
            self.assertEqual(st, 400)
            st, _, b = call(self.app, "GET", "/api/v2/invites/%s/check" % tok)
            self.assertEqual(st, 200, "failed accepts leave the invite open")
            st, _, b = call(self.app, "POST", "/api/v2/invites", {"role": "root"}, _auth(*ADMIN))
            self.assertEqual(st, 400)
            st, _, b = call(self.app, "POST", "/api/v2/invites", {"role": "editor", "ttl_hours": -1}, _auth(*ADMIN))
            self.assertEqual(st, 400)

    def test_accept_throttled_by_token(self):
        with self._admin():
            bad = "inv-guess000000000000000000"
            for _ in range(5):
                st, _, b = call(self.app, "POST", "/api/v2/invites/%s/accept" % bad, {"username": "x1", "password": "long-enough-1"},
                                dict(JSON_H, __remote_addr__="10.9.9.9"))
                self.assertEqual(st, 404)
            st, _, b = call(self.app, "POST", "/api/v2/invites/%s/accept" % bad, {"username": "x1", "password": "long-enough-1"},
                            dict(JSON_H, __remote_addr__="10.9.9.9"))
            self.assertEqual((st, jbody(b)["code"]), (429, "throttled"), fr("FR-USER-10", "5.3", "accept attempts are throttled per token"))

    def test_revoke_and_roles(self):
        with self._admin():
            self.users.add_user("eve", "eve-password-1", role="editor")
            st, _, b = call(self.app, "POST", "/api/v2/invites", {"role": "editor"}, _auth("eve", "eve-password-1"))
            self.assertEqual(st, 403, "editors cannot invite")
            st, _, b = call(self.app, "GET", "/api/v2/invites", headers=basic("eve", "eve-password-1"))
            self.assertEqual(st, 403)
            st, _, b = call(self.app, "POST", "/api/v2/invites", {}, _auth(*ADMIN))
            self.assertEqual(st, 201)
            self.assertEqual(jbody(b)["role"], "editor", "default role editor")
            tok = jbody(b)["token"]
            st, _, b = call(self.app, "DELETE", "/api/v2/invites/" + tok, headers=_auth(*ADMIN))
            self.assertEqual((st, jbody(b)), (200, {"ok": True}))
            st, _, b = call(self.app, "DELETE", "/api/v2/invites/" + tok, headers=_auth(*ADMIN))
            self.assertEqual(st, 404)
            st, _, b = call(self.app, "GET", "/api/v2/invites/%s/check" % tok)
            self.assertEqual(st, 404, "revoked → invalid")

    def test_expired_invite_404(self):
        with self._admin() as data:
            st, _, b = call(self.app, "POST", "/api/v2/invites", {"role": "editor", "ttl_hours": 1}, _auth(*ADMIN))
            tok = jbody(b)["token"]
            raw = json.loads((data / "invites.json").read_text())
            raw["invites"][0]["expires"] = "2000-01-01T00:00:00Z"
            (data / "invites.json").write_text(json.dumps(raw))
            st, _, b = call(self.app, "GET", "/api/v2/invites/%s/check" % tok)
            self.assertEqual((st, jbody(b)["code"]), (404, "invalid_invite"))
            st, _, b = call(self.app, "GET", "/api/v2/invites", headers=basic(*ADMIN))
            self.assertEqual(jbody(b)["invites"], [], "expired invites are pruned from the list")

    def test_accept_bootstraps_logins_when_auth_off(self):
        with temp_data_dir() as data:
            install_sunday(data, "proj")
            st, _, b = call(self.app, "GET", "/api/v2/session")
            self.assertFalse(jbody(b)["auth_enabled"], "control: no users → login off")
            st, _, b = call(self.app, "POST", "/api/v2/invites", {"role": "admin"}, JSON_H)
            self.assertEqual(st, 201, b[:200])
            tok = jbody(b)["token"]
            self.assertEqual(jbody(b)["created_by"], "local")
            st, _, b = call(self.app, "GET", "/api/v2/invites/%s/check" % tok)
            self.assertFalse(jbody(b)["auth_enabled"])
            st, h, b = call(self.app, "POST", "/api/v2/invites/%s/accept" % tok, {"username": "first", "password": "first-password-1"}, JSON_H)
            self.assertEqual(st, 200, b[:200])
            self.assertTrue(_session_cookie(h))
            st, _, b = call(self.app, "GET", "/api/v2/session")
            self.assertTrue(jbody(b)["auth_enabled"], fr("FR-USER-11", "5.3", "accepting an invite with login off creates the first user and turns login on"))

    def test_public_url_env_and_subpath(self):
        with self._admin():
            with_env = {"FATHOM_PUBLIC_URL": "https://av.example.org/fathom"}
            import os

            old = os.environ.get("FATHOM_PUBLIC_URL")
            os.environ.update(with_env)
            try:
                st, _, b = call(self.app, "POST", "/api/v2/invites", {"role": "viewer"}, _auth(*ADMIN))
                self.assertEqual(jbody(b)["url"], "https://av.example.org/fathom/invite/" + jbody(b)["token"])
            finally:
                if old is None:
                    os.environ.pop("FATHOM_PUBLIC_URL", None)
                else:
                    os.environ["FATHOM_PUBLIC_URL"] = old
            st, _, b = call(self.app, "GET", "/api/v2/invites", headers=dict(basic(*ADMIN), __script_name__="/fathom"))
            self.assertEqual(jbody(b)["accept_url"], "/fathom/invite/{token}")
            st, h, b = call(self.app, "GET", "/invite/inv-abcdefghijklmnopqrstuvwxyz/", headers={"__script_name__": "/fathom"})
            self.assertEqual((st, h.get("location")), (302, "/fathom/invite/inv-abcdefghijklmnopqrstuvwxyz"), "trailing slash is redirected away so ../static resolves")

    def test_patch_projects_round_trip(self):
        with self._admin():
            self.users.add_user("eve", "eve-password-1", role="editor")
            st, _, b = call(self.app, "PATCH", "/api/v2/users/eve", {"projects": {"proj": "viewer"}}, _auth(*ADMIN))
            self.assertEqual(st, 200, b[:200])
            self.assertEqual(jbody(b)["user"]["projects"], {"proj": "viewer"})
            st, _, b = call(self.app, "GET", "/api/v2/users", headers=basic(*ADMIN))
            eve = next(u for u in jbody(b)["users"] if u["username"] == "eve")
            self.assertEqual(eve["projects"], {"proj": "viewer"}, fr("FR-USER-01", "5.3", "projects round-trips through GET /users"))
            st, _, b = call(self.app, "GET", "/api/v2/projects", headers=basic("eve", "eve-password-1"))
            self.assertEqual(jbody(b)["projects"][0]["role"], "viewer", "effective_role honours the override")
            st, _, b = call(self.app, "GET", "/api/v2/session", headers=basic("eve", "eve-password-1"))
            self.assertEqual(jbody(b)["user"]["projects"], {"proj": "viewer"}, "session user carries the overrides")
            st, _, b = call(self.app, "POST", "/api/v2/projects/proj/changes", {"base_revision": 1, "ops": []}, _auth("eve", "eve-password-1"))
            self.assertEqual(st, 403, "viewer override blocks writes")
            st, _, b = call(self.app, "PATCH", "/api/v2/users/eve", {"projects": {}}, _auth(*ADMIN))
            self.assertEqual(jbody(b)["user"]["projects"], {})


class InviteCli(unittest.TestCase):
    def test_create_list_revoke(self):
        cli = requires("cli")
        U = requires("users")
        with temp_data_dir():
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["invite", "create", "--role", "viewer", "--project", "proj=editor", "--hours", "2", "--note", "Sam"])
            first = out.getvalue().splitlines()[0]
            self.assertRegex(first, r"^/invite/inv-[A-Za-z0-9_-]{26}$", fr("FR-USER-07", "3.20", "prints the path"))
            tok = first.split("/")[-1]
            inv = U.get_invite(tok)
            self.assertEqual((inv["role"], inv["projects"], inv["note"]), ("viewer", {"proj": "editor"}, "Sam"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["invite", "list"])
            self.assertIn(tok, out.getvalue())
            self.assertIn("proj:editor", out.getvalue())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["invite", "revoke", tok])
            self.assertIn("ok", out.getvalue())
            self.assertIsNone(U.get_invite(tok))
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    cli.main(["invite", "revoke", tok])
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    cli.main(["invite", "create", "--project", "proj"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["invite", "list"])
            self.assertIn("no open invites", out.getvalue())


if __name__ == "__main__":
    unittest.main()
