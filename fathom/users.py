"""Users, roles, passwords and session cookies (§3.20, §5.3).

``<data>/users.json`` holds users with PBKDF2-HMAC-SHA256 password hashes
(``pbkdf2_sha256$600000$<b64 salt>$<b64 hash>``). ``FATHOM_AUTH="u:p[,u2:p2]"``
adds in-memory admins. Auth is on iff ``FATHOM_AUTH`` is set or users.json has
at least one enabled user; when off every request acts as the admin ``local``.
Sessions are ``base64url(json) "." base64url(hmac_sha256(secret, base64url(json)))``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROLES: Tuple[str, ...] = ("viewer", "editor", "admin")
ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3}
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$")
ITERATIONS = 600_000
MIN_PASSWORD = 8
SESSION_MAX_AGE = 1_209_600

_LOCK = threading.RLock()
_VERIFY_CACHE: Dict[str, float] = {}


class UserError(ValueError):
    """Bad input for a user operation. ``code``: bad_request | exists | not_found | last_admin | weak_password."""

    def __init__(self, message: str, code: str = "bad_request") -> None:
        super().__init__(message)
        self.code = code


def _data_root() -> Path:
    from .project import data_root

    return data_root()


def users_path() -> Path:
    return _data_root() / "users.json"


def utc_now() -> str:
    from .history import utc_now as _now

    return _now()


# ------------------------------------------------------------- secret


def secret_key() -> bytes:
    """``<data>/secret.key`` (32 random bytes, hex, mode 0600), created on first need."""
    path = _data_root() / "secret.key"
    with _LOCK:
        if path.is_file():
            raw = path.read_text(encoding="ascii").strip()
            try:
                key = bytes.fromhex(raw)
                if len(key) >= 16:
                    return key
            except ValueError:
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(key.hex() + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover
            pass
        return key


# ------------------------------------------------------------ hashing


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(password: str, iterations: int = 600_000) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return f"pbkdf2_sha256${int(iterations)}${_b64(salt)}${_b64(dk)}"


def check_password(stored: str, password: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = str(stored).split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        want = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
    except Exception:
        return False
    return hmac.compare_digest(dk, want)


# ------------------------------------------------------------ storage


def _load() -> List[Dict[str, Any]]:
    p = users_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    users = data.get("users") if isinstance(data, dict) else data
    return [u for u in users or [] if isinstance(u, dict) and u.get("username")]


def _save(users: List[Dict[str, Any]]) -> None:
    p = users_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".users.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"users": users}, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, p)
    _VERIFY_CACHE.clear()


def _public(u: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "username": u.get("username"), "role": u.get("role", "viewer"), "disabled": bool(u.get("disabled")),
        "created": u.get("created", ""), "projects": dict(u.get("projects") or {}),
    }


def env_users() -> List[Tuple[str, str]]:
    raw = (os.environ.get("FATHOM_AUTH") or "").strip()
    pairs = []
    for item in raw.split(","):
        if ":" in item:
            u, p = item.split(":", 1)
            if u.strip():
                pairs.append((u.strip(), p))
    return pairs


def auth_enabled() -> bool:
    if env_users():
        return True
    return any(not u.get("disabled") for u in _load())


def public_view() -> bool:
    return os.environ.get("FATHOM_PUBLIC_VIEW") == "1"


def list_users() -> List[Dict[str, Any]]:
    return [_public(u) for u in _load()]


def get_user(username: str) -> Optional[Dict[str, Any]]:
    """Public view of a users.json user, or an env admin; None when unknown."""
    for u in _load():
        if u.get("username") == username:
            d = _public(u)
            d["epoch"] = int(u.get("epoch") or 0)
            d["source"] = "users"
            return d
    for name, _ in env_users():
        if name == username:
            return {"username": name, "role": "admin", "disabled": False, "created": "", "projects": {}, "epoch": 0, "source": "env"}
    return None


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise UserError(f"role must be one of {', '.join(ROLES)}")
    return role


def _check_projects(projects: Any) -> Dict[str, str]:
    if projects is None:
        return {}
    if not isinstance(projects, dict):
        raise UserError("projects must be an object {project: role}")
    out = {}
    for k, v in projects.items():
        if v not in ("viewer", "editor"):
            raise UserError("per-project roles must be viewer or editor")
        out[str(k)] = str(v)
    return out


def add_user(username: str, password: str, role: str = "editor", projects: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    if not USERNAME_RE.match(username or ""):
        raise UserError("username must be letters, digits, . _ @ - (max 64)")
    if len(password or "") < MIN_PASSWORD:
        raise UserError(f"password must be at least {MIN_PASSWORD} characters", "weak_password")
    _check_role(role)
    proj = _check_projects(projects)
    with _LOCK:
        users = _load()
        if any(u.get("username") == username for u in users):
            raise UserError(f"user '{username}' exists", "exists")
        u = {"username": username, "role": role, "hash": hash_password(password), "disabled": False,
             "created": utc_now(), "epoch": 0}
        if proj:
            u["projects"] = proj
        users.append(u)
        _save(users)
        return _public(u)


def _update(username: str, fn: Any) -> Dict[str, Any]:
    with _LOCK:
        users = _load()
        for u in users:
            if u.get("username") == username:
                fn(u, users)
                _save(users)
                return _public(u)
    raise UserError(f"user '{username}' not found", "not_found")


def _enabled_admins(users: List[Dict[str, Any]]) -> int:
    return sum(1 for u in users if u.get("role") == "admin" and not u.get("disabled"))


def set_password(username: str, password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise UserError(f"password must be at least {MIN_PASSWORD} characters", "weak_password")

    def fn(u: Dict[str, Any], users: List[Dict[str, Any]]) -> None:
        u["hash"] = hash_password(password)
        u["epoch"] = int(u.get("epoch") or 0) + 1

    _update(username, fn)


def set_role(username: str, role: str) -> None:
    _check_role(role)

    def fn(u: Dict[str, Any], users: List[Dict[str, Any]]) -> None:
        if u.get("role") == "admin" and role != "admin" and not u.get("disabled") and _enabled_admins(users) <= 1 and not env_users():
            raise UserError("cannot demote the last enabled admin", "last_admin")
        u["role"] = role

    _update(username, fn)


def set_projects(username: str, projects: Optional[Dict[str, str]]) -> None:
    proj = _check_projects(projects)

    def fn(u: Dict[str, Any], users: List[Dict[str, Any]]) -> None:
        if proj:
            u["projects"] = proj
        else:
            u.pop("projects", None)

    _update(username, fn)


def set_disabled(username: str, disabled: bool) -> None:
    def fn(u: Dict[str, Any], users: List[Dict[str, Any]]) -> None:
        if disabled and u.get("role") == "admin" and not u.get("disabled") and _enabled_admins(users) <= 1 and not env_users():
            raise UserError("cannot disable the last enabled admin", "last_admin")
        u["disabled"] = bool(disabled)
        if disabled:
            u["epoch"] = int(u.get("epoch") or 0) + 1

    _update(username, fn)


def remove_user(username: str) -> None:
    with _LOCK:
        users = _load()
        target = next((u for u in users if u.get("username") == username), None)
        if target is None:
            raise UserError(f"user '{username}' not found", "not_found")
        if target.get("role") == "admin" and not target.get("disabled") and _enabled_admins(users) <= 1 and len(users) > 1 and not env_users():
            raise UserError("cannot delete the last enabled admin", "last_admin")
        _save([u for u in users if u.get("username") != username])


# --------------------------------------------------------------- verify


def _cache_key(username: str, password: str, stored: str) -> str:
    return hashlib.sha256(f"{username}\x00{password}\x00{stored}".encode("utf-8")).hexdigest()


def verify(username: str, password: str) -> Optional[Dict[str, Any]]:
    """users.json (enabled users) then ``FATHOM_AUTH``; returns the public user or None."""
    if not username:
        return None
    for u in _load():
        if u.get("username") != username:
            continue
        if u.get("disabled"):
            return None
        stored = str(u.get("hash") or "")
        key = _cache_key(username, password or "", stored)
        ok = key in _VERIFY_CACHE or check_password(stored, password or "")
        if ok:
            if len(_VERIFY_CACHE) > 1024:
                _VERIFY_CACHE.clear()
            _VERIFY_CACHE[key] = time.time()
            d = _public(u)
            d["epoch"] = int(u.get("epoch") or 0)
            d["source"] = "users"
            return d
        return None
    for name, pw in env_users():
        if hmac.compare_digest(name.encode("utf-8"), username.encode("utf-8")) and hmac.compare_digest(pw.encode("utf-8"), (password or "").encode("utf-8")):
            return {"username": name, "role": "admin", "disabled": False, "created": "", "projects": {}, "epoch": 0, "source": "env"}
    return None


# ------------------------------------------------------------- sessions


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_session(user: Dict[str, Any], max_age: int = 1_209_600) -> str:
    payload = {"u": user["username"], "exp": int(time.time()) + int(max_age), "ep": int(user.get("epoch") or 0)}
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(hmac.new(secret_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_session(cookie_value: str) -> Optional[Dict[str, Any]]:
    try:
        body, sig = str(cookie_value or "").split(".", 1)
        want = _b64url(hmac.new(secret_key(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(want.encode("ascii"), sig.encode("ascii")):
            return None
        payload = json.loads(_unb64url(body))
        if int(payload.get("exp") or 0) <= time.time():
            return None
        user = get_user(str(payload.get("u") or ""))
        if user is None or user.get("disabled"):
            return None
        if int(payload.get("ep") or 0) != int(user.get("epoch") or 0):
            return None
        return user
    except Exception:
        return None


def effective_role(user: Dict[str, Any], project: str = "") -> str:
    role = str((user or {}).get("role") or "viewer")
    if role == "admin":
        return "admin"
    if project:
        override = ((user or {}).get("projects") or {}).get(project)
        if override in ("viewer", "editor"):
            return override
    return role if role in ROLES else "viewer"


def role_at_least(role: str, needed: str) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK.get(needed, 99)


# ------------------------------------------------------------- throttle

_FAILS: Dict[Tuple[str, str], List[float]] = {}
_BLOCKED: Dict[Tuple[str, str], float] = {}
THROTTLE_WINDOW = 300.0
THROTTLE_MAX = 5


def throttled(ip: str, username: str) -> bool:
    key = (ip or "", username or "")
    with _LOCK:
        until = _BLOCKED.get(key)
        if until and until > time.time():
            return True
        if until:
            _BLOCKED.pop(key, None)
        return False


def note_failure(ip: str, username: str) -> None:
    key = (ip or "", username or "")
    now = time.time()
    with _LOCK:
        fails = [t for t in _FAILS.get(key, []) if now - t < THROTTLE_WINDOW]
        fails.append(now)
        _FAILS[key] = fails
        if len(fails) >= THROTTLE_MAX:
            _BLOCKED[key] = now + THROTTLE_WINDOW
            _FAILS.pop(key, None)


def note_success(ip: str, username: str) -> None:
    with _LOCK:
        _FAILS.pop((ip or "", username or ""), None)
