"""Whole-server backups: a zip of the data directory and a restore that swaps it back in.

Layout::

    <data>/backups/fathom-backup-<stamp>.zip      one file per backup (never included in another backup)

Zip contents::

    manifest.json        {"format": "fathom-backup", "version": 1, "created", "app", "kind", "label", "author",
                          "include_builds", "projects", "files", "bytes"}
    data/<path>          every file of the data dir: projects (docs, history, attachments, imports),
                         users.json, secret.key, the custom library, builds when included

A restore verifies the zip, takes a ``pre-restore`` backup of the current state, extracts into a
staging folder and then swaps each top-level entry in with renames, rolling back on failure.
Entries starting with ``.`` and ``backups/`` are never touched; ``builds/`` is only replaced when
the backup includes builds.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import shutil
import stat
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, List, Optional

from . import __version__
from .project import _FileLock, data_root, ensure_data_dirs, project_lock, projects_root, safe_name

FORMAT = "fathom-backup"
VERSION = 1
MANIFEST = "manifest.json"
PREFIX = "data/"
KINDS = ("manual", "pre-restore", "cli", "uploaded")
MAX_MEMBERS = 500_000
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.zip$")
_TMP_RE = re.compile(r"(^\.tmp-|\.tmp$|^\.lock$|^\.lock\.excl$)")
_CHUNK = 1024 * 1024
_THREAD_LOCK = threading.RLock()


class BackupError(Exception):
    """``code``: not_found | invalid | too_large | no_space | busy."""

    def __init__(self, message: str, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


def backups_root() -> Path:
    return data_root() / "backups"


def max_upload_bytes() -> int:
    """Largest backup accepted by upload (``FATHOM_MAX_BACKUP_MB``, default 4096)."""
    return int(float(os.environ.get("FATHOM_MAX_BACKUP_MB") or 4096) * 1024 * 1024)


def _max_unpacked_bytes() -> int:
    return max_upload_bytes() * 10


def generation() -> int:
    """Changes whenever a restore swaps data in; other workers drop their caches when it moves."""
    try:
        return (data_root() / ".generation").stat().st_mtime_ns
    except OSError:
        return 0


def _bump_generation() -> None:
    p = data_root() / ".generation"
    tmp = p.with_name(f".generation.{os.getpid()}.tmp")
    tmp.write_text(secrets.token_hex(8) + "\n", encoding="ascii")
    os.replace(tmp, p)


@contextlib.contextmanager
def _data_lock() -> Iterator[None]:
    """One backup or restore at a time, across threads and worker processes."""
    with _THREAD_LOCK:
        root = data_root()
        root.mkdir(parents=True, exist_ok=True)
        fl = _FileLock(root / ".backup.lock")
        fl.acquire()
        try:
            _clean_leftovers(root)
            yield
        finally:
            fl.release()


def _clean_leftovers(root: Path) -> None:
    """Staging folders and partial zips left by a process killed mid-backup or mid-restore.

    Entries in ``.restore-old-*`` that are missing from the data dir go back first: a kill between
    moving the old data out and the new data in must not lose either.
    """
    for old in root.glob(".restore-old-*"):
        for e in list(old.iterdir()) if old.is_dir() else []:
            if not os.path.lexists(root / e.name):
                with contextlib.suppress(OSError):
                    os.replace(e, root / e.name)
        shutil.rmtree(old, ignore_errors=True)
    for p in root.glob(".restore-*"):
        shutil.rmtree(p, ignore_errors=True)
    for p in backups_root().glob(".partial-*.zip"):
        with contextlib.suppress(OSError):
            p.unlink()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _unique(directory: Path, stem: str) -> Path:
    path = directory / f"{stem}.zip"
    n = 2
    while path.exists():
        path = directory / f"{stem}-{n}.zip"
        n += 1
    return path


# ------------------------------------------------------------------ create


def _skip_top(name: str, include_builds: bool) -> bool:
    return name.startswith(".") or name == "backups" or (name == "builds" and not include_builds)


def _files_under(base: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not os.path.islink(os.path.join(dirpath, d)))
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if _TMP_RE.search(fn) or p.is_symlink() or not p.is_file():
                continue
            yield p


def _add_tree(zf: zipfile.ZipFile, root: Path, base: Path, counts: Dict[str, int]) -> None:
    if base.is_file() and not base.is_symlink():
        items: Iterator[Path] = iter([base])
    elif base.is_dir() and not base.is_symlink():
        items = _files_under(base)
    else:
        return
    for p in items:
        rel = p.relative_to(root).as_posix()
        try:
            zf.write(p, PREFIX + rel)
        except FileNotFoundError:
            continue
        counts["files"] += 1
        counts["bytes"] += p.stat().st_size if p.exists() else 0


def _write_zip(target: Path, *, include_builds: bool, kind: str, label: str, author: str) -> Dict[str, Any]:
    root = data_root()
    counts = {"files": 0, "bytes": 0}
    projects: List[str] = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            if _skip_top(entry.name, include_builds) or entry.is_symlink():
                continue
            if entry.name == "projects" and entry.is_dir():
                for pdir in sorted(entry.iterdir(), key=lambda p: p.name):
                    if pdir.is_symlink():
                        continue
                    if pdir.is_dir() and safe_name(pdir.name):
                        with project_lock(pdir):
                            _add_tree(zf, root, pdir, counts)
                        projects.append(pdir.name)
                    else:
                        _add_tree(zf, root, pdir, counts)
                continue
            _add_tree(zf, root, entry, counts)
        manifest = {
            "format": FORMAT, "version": VERSION, "created": _now().strftime("%Y-%m-%dT%H:%M:%SZ"), "app": __version__,
            "kind": kind, "label": label, "author": author, "include_builds": bool(include_builds),
            "projects": projects, "files": counts["files"], "bytes": counts["bytes"],
        }
        zf.writestr(MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def _create_locked(include_builds: bool, label: str, author: str, kind: str) -> Dict[str, Any]:
    d = backups_root()
    d.mkdir(parents=True, exist_ok=True)
    final = _unique(d, f"fathom-backup-{_now().strftime('%Y%m%d-%H%M%S')}" + ("" if kind in ("manual", "cli") else f"-{kind}"))
    partial = d / f".partial-{secrets.token_hex(6)}.zip"
    try:
        _write_zip(partial, include_builds=include_builds, kind=kind, label=label, author=author)
        os.replace(partial, final)
    finally:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
    return backup_info(final)


def create_backup(include_builds: bool = False, label: str = "", author: str = "", kind: str = "manual") -> Dict[str, Any]:
    """Zip the data dir into ``backups/`` and return its info."""
    if kind not in KINDS:
        raise BackupError(f"unknown backup kind '{kind}'")
    with _data_lock():
        return _create_locked(bool(include_builds), str(label or "")[:200], str(author or ""), kind)


# ------------------------------------------------------------------ inspect


def _read_manifest(zf: zipfile.ZipFile) -> Dict[str, Any]:
    try:
        raw = zf.read(MANIFEST)
    except KeyError:
        raise BackupError("not a Fathom backup (manifest.json missing)")
    try:
        m = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BackupError("manifest.json is not valid JSON")
    if not isinstance(m, dict) or m.get("format") != FORMAT:
        raise BackupError("not a Fathom backup (wrong format)")
    try:
        version = int(m.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version < 1 or version > VERSION:
        raise BackupError(f"backup format version {m.get('version')} is not supported by this Fathom ({__version__})")
    return m


def _member_rel(info: zipfile.ZipInfo) -> Optional[str]:
    """Relative data path of a member, None for the manifest / folders; raises on anything unsafe."""
    name = info.filename
    if name == MANIFEST:
        return None
    if not name.startswith(PREFIX) or "\\" in name or "\x00" in name:
        raise BackupError(f"unexpected entry in backup: {name!r}")
    rel = name[len(PREFIX):]
    if info.is_dir():
        return None
    parts = rel.split("/")
    if not rel or rel.startswith("/") or any(p in ("", ".", "..") for p in parts) or ":" in parts[0]:
        raise BackupError(f"unsafe path in backup: {name!r}")
    if parts[0].startswith(".") or parts[0] == "backups":
        raise BackupError(f"backup may not contain {parts[0]!r}")
    if stat.S_ISLNK(info.external_attr >> 16):
        raise BackupError(f"backup may not contain links: {name!r}")
    return rel


def verify_backup(path: Path, deep: bool = True) -> Dict[str, Any]:
    """Manifest of a valid backup. ``deep`` also checks every CRC."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BackupError(f"not a readable zip file: {exc}")
    with zf:
        m = _read_manifest(zf)
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise BackupError(f"backup has more than {MAX_MEMBERS} entries", "too_large")
        total = 0
        for info in infos:
            _member_rel(info)
            total += info.file_size
        if total > _max_unpacked_bytes():
            raise BackupError("backup unpacks to more than the allowed size (FATHOM_MAX_BACKUP_MB × 10)", "too_large")
        if deep:
            try:
                bad = zf.testzip()
            except (zipfile.BadZipFile, OSError, EOFError) as exc:
                raise BackupError(f"backup is damaged: {exc}")
            if bad:
                raise BackupError(f"backup is damaged (bad checksum in {bad})")
        m["unpacked_bytes"] = total
        return m


def backup_info(path: Path) -> Dict[str, Any]:
    st = path.stat()
    out: Dict[str, Any] = {"name": path.name, "size": st.st_size, "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        m = verify_backup(path, deep=False)
    except BackupError as exc:
        out["error"] = str(exc)
        return out
    for k in ("created", "app", "kind", "label", "author", "include_builds", "projects", "files", "bytes"):
        out[k] = m.get(k)
    return out


def list_backups() -> List[Dict[str, Any]]:
    d = backups_root()
    if not d.is_dir():
        return []
    paths = [p for p in d.iterdir() if p.is_file() and not p.is_symlink() and _NAME_RE.match(p.name)]
    paths.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    return [backup_info(p) for p in paths]


def backup_path(name: str) -> Path:
    if not _NAME_RE.match(name or ""):
        raise BackupError("bad backup name", "not_found")
    p = backups_root() / name
    if not p.is_file() or p.is_symlink():
        raise BackupError(f"backup '{name}' not found", "not_found")
    return p


def delete_backup(name: str) -> None:
    with _data_lock():
        backup_path(name).unlink()


# ------------------------------------------------------------------ upload


def save_upload(stream: BinaryIO, length: Optional[int]) -> Dict[str, Any]:
    """Store an uploaded backup (read in chunks) after verifying it; returns its info."""
    cap = max_upload_bytes()
    if length is not None and length > cap:
        raise BackupError(f"backup larger than {cap // (1024 * 1024)} MB (FATHOM_MAX_BACKUP_MB)", "too_large")
    d = backups_root()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".upload-{secrets.token_hex(6)}.zip"
    try:
        n = 0
        with open(tmp, "wb") as fh:
            while length is None or n < length:
                chunk = stream.read(_CHUNK if length is None else min(_CHUNK, length - n))
                if not chunk:
                    break
                n += len(chunk)
                if n > cap:
                    raise BackupError(f"backup larger than {cap // (1024 * 1024)} MB (FATHOM_MAX_BACKUP_MB)", "too_large")
                fh.write(chunk)
        if n == 0:
            raise BackupError("empty upload")
        if length is not None and n < length:
            raise BackupError("upload ended early")
        m = verify_backup(tmp, deep=True)
        stamp = re.sub(r"[^0-9]", "", str(m.get("created") or ""))[:14]
        stem = f"fathom-backup-{stamp[:8]}-{stamp[8:]}" if len(stamp) == 14 else f"fathom-backup-{_now().strftime('%Y%m%d-%H%M%S')}"
        with _data_lock():
            final = _unique(d, stem + "-uploaded")
            os.replace(tmp, final)
        return backup_info(final)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


# ------------------------------------------------------------------ restore


def _dir_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for f in _files_under(p) if p.is_dir() else []:
        with contextlib.suppress(OSError):
            total += f.stat().st_size
    return total


def _extract(path: Path, staging: Path) -> None:
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            rel = _member_rel(info)
            if rel is None:
                continue
            target = staging.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, _CHUNK)
            if rel in ("secret.key", "users.json"):
                with contextlib.suppress(OSError):
                    os.chmod(target, 0o600)


def _swap_in(root: Path, staging: Path, old: Path, include_builds: bool) -> List[str]:
    names = {p.name for p in staging.iterdir()} | {p.name for p in root.iterdir()}
    names = sorted(n for n in names if not _skip_top(n, include_builds))
    moved: List[str] = []
    placed: List[str] = []
    try:
        for n in names:
            if os.path.lexists(root / n):
                os.replace(root / n, old / n)
                moved.append(n)
            if (staging / n).exists():
                os.replace(staging / n, root / n)
                placed.append(n)
    except BaseException:
        for n in placed:
            with contextlib.suppress(OSError):
                os.replace(root / n, staging / n)
        for n in moved:
            with contextlib.suppress(OSError):
                os.replace(old / n, root / n)
        raise
    return names


def restore_backup(name: str, author: str = "", safety: bool = True) -> Dict[str, Any]:
    """Replace the data dir with a backup's contents; a ``pre-restore`` backup is taken first."""
    path = backup_path(name)
    m = verify_backup(path, deep=True)
    include_builds = bool(m.get("include_builds"))
    root = data_root()
    with _data_lock():
        need = int(m.get("unpacked_bytes") or 0) + (sum(_dir_size(root / n) for n in os.listdir(root) if not _skip_top(n, include_builds)) if safety else 0)
        free = shutil.disk_usage(root).free
        if free < need * 1.05 + 16 * 1024 * 1024:
            raise BackupError(f"not enough free disk space to restore (need about {need // (1024 * 1024) + 16} MB, {free // (1024 * 1024)} MB free)", "no_space")
        pre = _create_locked(include_builds, f"Before restoring {name}", author, "pre-restore") if safety else None
        token = secrets.token_hex(6)
        staging = root / f".restore-{token}"
        old = root / f".restore-old-{token}"
        staging.mkdir()
        old.mkdir()
        try:
            _extract(path, staging)
            with contextlib.ExitStack() as stack:
                pr = projects_root()
                if pr.is_dir():
                    for pdir in sorted(pr.iterdir()):
                        if pdir.is_dir() and not pdir.is_symlink() and safe_name(pdir.name):
                            stack.enter_context(project_lock(pdir))
                replaced = _swap_in(root, staging, old, include_builds)
            _bump_generation()
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(old, ignore_errors=True)
        ensure_data_dirs()
    return {"restored": name, "pre_restore_backup": pre["name"] if pre else None, "replaced": replaced,
            "projects": m.get("projects") or [], "include_builds": include_builds, "created": m.get("created")}


def restore_file(path: Path, author: str = "", safety: bool = True) -> Dict[str, Any]:
    """Restore a zip from anywhere on disk (CLI): copied into ``backups/`` first, then restored."""
    verify_backup(path, deep=True)
    d = backups_root()
    d.mkdir(parents=True, exist_ok=True)
    try:
        inside = path.resolve().parent == d.resolve() and _NAME_RE.match(path.name)
    except OSError:
        inside = False
    if inside:
        return restore_backup(path.name, author=author, safety=safety)
    with open(path, "rb") as fh:
        info = save_upload(fh, path.stat().st_size)
    return restore_backup(info["name"], author=author, safety=safety)


def human_size(n: Any) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} GB"
