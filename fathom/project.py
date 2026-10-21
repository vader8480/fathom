"""Storage: the data directory, project folders, builds, scaffolding, and the
v2 document store (atomic writes, per-project lock, revisions).

Layout (``FATHOM_DATA``, default ``~/.fathom``; Docker uses ``/data``)::

    <data>/projects/<name>/project.json      the model (a v2 doc with "revision")
    <data>/projects/<name>/project.v1.json   original v1 file, written once on the first v2 save
    <data>/projects/<name>/exports/<kind>/   copies of the console / Dante / Waves exports
    <data>/projects/<name>/files/<att-id>/   attachments (photos, documents, floor plans)
    <data>/projects/<name>/history/          revision log (see ``history.py``)
    <data>/builds/<name>/<stamp>_<slug>/     rendered snapshots (index.html, svg, csv, pdf ...)

``project.json`` is the canonical format. Hand-written projects may also be
``.jsonc`` (comments, trailing commas), ``.toml`` (Python 3.11+) or
``.yaml`` (when PyYAML is importable); v1 files (``"fathom": 1``,
``"signalflow": 1`` or no version key) load and migrate in memory and are
written as v2 on the next save. The app and CLI always write JSON.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from .model import Project, project_from_dict, slug

PACKAGE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = PACKAGE_DIR / "samples"
STATIC_DIR = PACKAGE_DIR / "static"

PROJECT_FILENAMES = ("project.json", "project.jsonc", "project.toml", "project.yaml", "project.yml")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_FILE_RE = re.compile(r"[^A-Za-z0-9._ -]+")

Doc = Dict[str, Any]
Op = Dict[str, Any]


# ------------------------------------------------------------- errors


class ConflictError(Exception):
    """The write touches entities someone else changed since the client's base revision."""

    def __init__(self, message: str, revision: int = 0, conflicts: Optional[List[str]] = None, by: Optional[List[str]] = None, code: str = "conflict") -> None:
        super().__init__(message)
        self.revision = revision
        self.conflicts = list(conflicts or [])
        self.by = list(by or [])
        self.code = code


class ValidationError(Exception):
    """The resulting doc has (new) validation errors."""

    def __init__(self, problems: List[Dict[str, Any]], message: str = "") -> None:
        errs = [p for p in problems if p.get("level") == "error"]
        super().__init__(message or (f"{len(errs)} validation error(s): " + "; ".join(p.get("message", "") for p in errs[:3])))
        self.problems = problems


class PreconditionError(Exception):
    """A full write without a base revision (If-Match / base_revision)."""


# ------------------------------------------------------------- locations


def data_root() -> Path:
    raw = (os.environ.get("FATHOM_DATA") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".fathom").resolve()


def projects_root() -> Path:
    return data_root() / "projects"


def builds_root() -> Path:
    return data_root() / "builds"


def ensure_data_dirs() -> None:
    projects_root().mkdir(parents=True, exist_ok=True)
    builds_root().mkdir(parents=True, exist_ok=True)


def safe_name(name: str) -> bool:
    return bool(SAFE_NAME_RE.match(name or ""))


def safe_filename(name: str) -> str:
    base = Path(str(name).replace("\\", "/")).name
    base = _SAFE_FILE_RE.sub("_", base).strip(" .")
    return base or "upload"


# ----------------------------------------------------------------- loading


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas (outside strings)."""
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(ch)
        i += 1
    cleaned = "".join(out)
    return re.sub(r",(\s*[}\]])", r"\1", cleaned)


def load_dict(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    suffix = path.suffix.lower()
    if suffix in (".json", ".jsonc"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return json.loads(_strip_jsonc(text))
    if suffix == ".toml":
        try:
            import tomllib  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("error: TOML projects need Python 3.11+ (tomllib)") from exc
        return tomllib.loads(text)
    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("error: YAML projects need PyYAML (pip install pyyaml) or use project.json") from exc
        return yaml.safe_load(text) or {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_strip_jsonc(text))


def find_project_file(target: Path) -> Optional[Path]:
    """``target`` may be a project folder, a project file, or a name under the projects root."""
    if target.is_file():
        return target
    if target.is_dir():
        for name in PROJECT_FILENAMES:
            p = target / name
            if p.is_file():
                return p
        return None
    cand = projects_root() / str(target)
    if cand.is_dir():
        return find_project_file(cand)
    sample = SAMPLES_DIR / str(target)
    if sample.is_dir():
        return find_project_file(sample)
    return None


def resolve_project(target: str) -> Path:
    """Return the project *file* path or exit with a helpful message."""
    p = find_project_file(Path(target).expanduser())
    if p is None:
        avail = list_projects()
        hint = f" (projects: {', '.join(avail)})" if avail else " (create one: fathom new <name>)"
        raise SystemExit(f"error: project not found: {target}{hint}")
    return p


def load_project(target: str) -> Tuple[Project, Path]:
    """Load a project; returns (project, project_dir). v2 docs come back as the
    default room's flow project (``schema.flow_project``)."""
    path = resolve_project(target)
    data = load_dict(path)
    from . import schema

    if isinstance(data, dict) and schema.doc_version(data) == 2:
        project = schema.flow_project(schema.normalize(data))
    else:
        project = project_from_dict(data)
    if not project.meta.slug:
        project.meta.slug = slug(project.meta.org or path.parent.name)
    return project, path.parent


def save_project(project: Project, project_dir: Path) -> Path:
    """Save a v1 ``Project``. A folder that already holds a v2 doc is updated
    through the revision store instead of being overwritten with v1 JSON."""
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / "project.json"
    existing = find_project_file(project_dir) if project_dir.is_dir() else None
    if existing is not None:
        from . import schema

        try:
            cur = load_dict(existing)
        except Exception:
            cur = {}
        if isinstance(cur, dict) and schema.doc_version(cur) == 2:
            doc = schema.normalize(cur)
            v1 = project.to_dict()
            if schema.is_v1_expressible(doc):
                new = schema.migrate(v1)
            else:
                new = _sync_v1_into(doc, project)
            save_doc(new, project_dir, base_revision=None, source="cli", summary="Saved from the command line")
            return path
    path.write_text(json.dumps(project.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _sync_v1_into(doc: Doc, project: Project) -> Doc:
    """Carry what a v1 Project can express (meta, imports of the default room) into a rich v2 doc."""
    from . import schema

    new = dict(doc)
    new["meta"] = dict(doc.get("meta") or {}, **project.meta.to_dict())
    room = schema.default_room_id(doc)
    keep = [i for i in doc.get("imports") or [] if str(i.get("room") or room) != room]
    by_path = {i.get("path"): i for i in doc.get("imports") or []}
    taken = {i.get("id") for i in doc.get("imports") or []}
    n = 1
    for spec in project.imports:
        old = by_path.get(spec.path)
        if old is not None and str(old.get("room") or room) == room:
            ent = dict(old, kind=spec.kind)
        else:
            while "imp-%04d" % n in taken:
                n += 1
            ent = {"id": "imp-%04d" % n, "kind": spec.kind, "path": spec.path, "room": room}
            taken.add(ent["id"])
        if spec.node:
            ent["device"] = spec.node
        if spec.label:
            ent["label"] = spec.label
        keep.append(ent)
    new["imports"] = keep
    return new


def list_projects() -> List[str]:
    root = projects_root()
    names = []
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if p.is_dir() and find_project_file(p):
                names.append(p.name)
    return names


def project_info(name: str) -> Dict[str, Any]:
    pdir = projects_root() / name
    pf = find_project_file(pdir)
    info: Dict[str, Any] = {"name": name, "org": "", "title": "", "cards": 0, "updated": ""}
    if pf:
        try:
            d = load_dict(pf)
            info["org"] = str((d.get("meta") or {}).get("org", ""))
            info["title"] = str((d.get("meta") or {}).get("title", ""))
            info["cards"] = len(d.get("devices") or []) if d.get("fathom") == 2 else len(d.get("nodes") or [])
        except Exception:  # pragma: no cover - corrupt file still listed
            pass
        info["updated"] = datetime.fromtimestamp(pf.stat().st_mtime).isoformat(timespec="seconds")
    info["builds"] = len(list_builds(name))
    return info


def project_info_v2(name: str) -> Dict[str, Any]:
    """Row for ``GET /api/v2/projects``."""
    pdir = projects_root() / name
    pf = find_project_file(pdir)
    info: Dict[str, Any] = {"name": name, "org": "", "title": "", "schema": 1, "revision": 0, "rooms": 0,
                            "devices": 0, "cables": 0, "updated": "", "builds": len(list_builds(name))}
    if pf:
        try:
            from . import schema

            d = load_dict(pf)
            v = schema.doc_version(d)
            doc = schema.load_any(d)
            info.update({
                "org": str((doc.get("meta") or {}).get("org", "")), "title": str((doc.get("meta") or {}).get("title", "")),
                "schema": 2 if v == 2 else 1, "revision": int(doc.get("revision") or 0), "rooms": len(doc.get("rooms") or []),
                "devices": len(doc.get("devices") or []), "cables": len(doc.get("cables") or []),
            })
        except Exception:  # pragma: no cover
            pass
        info["updated"] = datetime.fromtimestamp(pf.stat().st_mtime).isoformat(timespec="seconds")
    return info


def delete_project(name: str) -> None:
    if not safe_name(name):
        raise SystemExit("error: bad project name")
    pdir = projects_root() / name
    if pdir.is_dir():
        shutil.rmtree(pdir)
    bdir = builds_root() / name
    if bdir.is_dir():
        shutil.rmtree(bdir)


# ------------------------------------------------------------------ builds


def build_stamp(when: Optional[datetime] = None) -> str:
    when = when or datetime.now()
    return f"{when:%Y-%m-%d_%H%M%S}"


def new_build_dir(project_name: str, slug_: str, when: Optional[datetime] = None) -> Path:
    d = builds_root() / project_name / f"{build_stamp(when)}_{slug(slug_)}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_builds(project_name: str, recursive: bool = False) -> List[Dict[str, Any]]:
    bdir = builds_root() / project_name
    out: List[Dict[str, Any]] = []
    if not bdir.is_dir():
        return out
    for run in sorted(bdir.iterdir(), reverse=True):
        if not run.is_dir() or not (run / "index.html").is_file():
            continue
        if recursive:
            files = sorted(p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file())
        else:
            files = sorted(p.name for p in run.iterdir() if p.is_file())
        out.append({"name": run.name, "files": files, "created": datetime.fromtimestamp(run.stat().st_mtime).isoformat(timespec="seconds")})
    return out


# -------------------------------------------------------------- scaffolding


def blank_project_dict(title_org: str = "") -> Dict[str, Any]:
    from .model import DEFAULT_COLUMNS, DEFAULT_FOOTNOTE, DEFAULT_INTRO

    return {
        "fathom": 1,
        "meta": {
            "org": title_org,
            "system": "Audio system",
            "title": "Signal flow, mic to speaker",
            "intro": DEFAULT_INTRO,
            "footnote": DEFAULT_FOOTNOTE,
        },
        "spine": {"label": "Dante network", "show": True},
        "columns": DEFAULT_COLUMNS,
        "groups": [
            {"id": "A", "label": "Wired inputs", "side": "left"},
            {"id": "B", "label": "Wireless mics", "side": "left"},
            {"id": "C", "label": "Playback & computers", "side": "left"},
            {"id": "E", "label": "Mix", "side": "right"},
            {"id": "F", "label": "IEMs", "side": "right"},
            {"id": "G", "label": "PA & zones", "side": "right"},
        ],
        "nodes": [],
        "links": [],
        "imports": [],
        "options": {
            "auto_dante_nodes": True,
            "auto_sources": True,
            "dante_counts": False,
            "appendix": True,
        },
    }


def new_project(name_or_path: str, template: str = "blank", org: str = "", force: bool = False) -> Path:
    """Create a project folder. ``template`` is ``blank`` (a v2 doc) or a sample folder name (copied verbatim)."""
    raw = name_or_path.strip()
    if os.sep in raw or raw.startswith((".", "~", "/")):
        project_dir = Path(raw).expanduser().resolve()
    else:
        if not safe_name(raw):
            raise SystemExit(f"error: project name must be letters, digits, . _ - (got {raw!r})")
        project_dir = projects_root() / raw
    if project_dir.exists() and any(project_dir.iterdir()) and not force:
        raise SystemExit(f"error: {project_dir} exists and is not empty (use --force to overwrite project.json)")
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "exports").mkdir(exist_ok=True)
    if template == "blank":
        from .schema import new_doc

        data = new_doc(org or project_dir.name.replace("-", " ").title())
        _atomic_write_json(project_dir / "project.json", data)
    else:
        if not safe_name(template) or not (SAMPLES_DIR / template).is_dir():
            avail = ", ".join(sorted(p.name for p in SAMPLES_DIR.iterdir() if p.is_dir())) if SAMPLES_DIR.is_dir() else ""
            raise SystemExit(f"error: unknown template '{template}' (blank or one of: {avail})")
        sample = SAMPLES_DIR / template
        for item in sample.iterdir():
            dest = project_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        if org:
            pf = find_project_file(project_dir) or (project_dir / "project.json")
            data = load_dict(pf)
            data.setdefault("meta", {})["org"] = org
            (project_dir / "project.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return project_dir


def display_path(path: Path) -> str:
    path = Path(path).resolve()
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


# =================================================================== v2 store


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:  # pragma: no cover
            pass
    os.replace(tmp, path)


# ---- lock

_RLOCKS: Dict[str, "threading.RLock"] = {}
_RLOCKS_GUARD = threading.Lock()
_LOCAL = threading.local()
_STALE_SECONDS = 10.0


def _rlock(key: str) -> "threading.RLock":
    with _RLOCKS_GUARD:
        lk = _RLOCKS.get(key)
        if lk is None:
            lk = threading.RLock()
            _RLOCKS[key] = lk
        return lk


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fh: Any = None
        self.mode = ""

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import fcntl  # type: ignore

            self.fh = open(self.path, "a+")
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
            self.mode = "fcntl"
            return
        except ImportError:
            pass
        try:
            import msvcrt  # type: ignore

            self.fh = open(self.path, "a+")
            while True:
                try:
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
                    break
                except OSError:
                    time.sleep(0.05)
            self.mode = "msvcrt"
            return
        except ImportError:  # pragma: no cover
            pass
        excl = self.path.with_name(self.path.name + ".excl")  # pragma: no cover - exotic platforms
        while True:
            try:
                fd = os.open(str(excl), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self.mode = "excl"
                self.fh = excl
                return
            except FileExistsError:
                try:
                    if time.time() - excl.stat().st_mtime > _STALE_SECONDS:
                        excl.unlink()
                        continue
                except OSError:
                    pass
                time.sleep(0.05)

    def release(self) -> None:
        if self.mode == "fcntl":
            import fcntl  # type: ignore

            fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            self.fh.close()
        elif self.mode == "msvcrt":  # pragma: no cover
            import msvcrt  # type: ignore

            self.fh.seek(0)
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            self.fh.close()
        elif self.mode == "excl":  # pragma: no cover
            try:
                os.unlink(str(self.fh))
            except OSError:
                pass
        self.fh = None
        self.mode = ""


@contextlib.contextmanager
def project_lock(project_dir: Path) -> Iterator[None]:
    """Exclusive per-project lock (threads and processes); re-entrant per thread."""
    key = str(Path(project_dir).resolve())
    rl = _rlock(key)
    rl.acquire()
    depth: Dict[str, Any] = getattr(_LOCAL, "depth", None) or {}
    _LOCAL.depth = depth
    fl = None
    try:
        if not depth.get(key):
            fl = _FileLock(Path(project_dir) / ".lock")
            fl.acquire()
            depth[key + "#lock"] = fl
        depth[key] = depth.get(key, 0) + 1
        yield
    finally:
        depth[key] = depth.get(key, 1) - 1
        if depth[key] <= 0:
            depth.pop(key, None)
            held = depth.pop(key + "#lock", None)
            if held is not None:
                held.release()
        rl.release()


# ---- documents


def files_dir(project_dir: Path) -> Path:
    return Path(project_dir) / "files"


def project_dir_for(name: str) -> Path:
    """Folder of project ``name`` under the projects root (ValueError: bad name, FileNotFoundError: missing)."""
    if not safe_name(name):
        raise ValueError("bad project name")
    pdir = projects_root() / name
    if find_project_file(pdir) is None:
        raise FileNotFoundError(f"project '{name}' not found")
    return pdir


def read_doc(project_dir: Path) -> Tuple[Doc, int]:
    """(doc, source_version) for a project folder; v1 migrated in memory."""
    from . import schema

    pf = find_project_file(Path(project_dir))
    if pf is None:
        raise FileNotFoundError(f"no project file in {project_dir}")
    data = load_dict(pf)
    version = schema.doc_version(data)
    doc = schema.load_any(data)
    return doc, version


def load_doc(target: str) -> Tuple[Doc, Path]:
    """Load any project as a v2 doc (v1 migrated in memory, nothing written)."""
    doc, pdir, _ = load_doc_info(target)
    return doc, pdir


def load_doc_info(target: str) -> Tuple[Doc, Path, int]:
    """(doc, project_dir, source_version 0|1|2)."""
    from . import schema

    path = resolve_project(target)
    data = load_dict(path)
    version = schema.doc_version(data)
    return schema.load_any(data), path.parent, version


def _guard_writable(project_dir: Path) -> None:
    pdir = Path(project_dir).resolve()
    try:
        pdir.relative_to(SAMPLES_DIR.resolve())
    except ValueError:
        return
    raise PermissionError("bundled samples are read-only; create a project from the sample first (fathom new <name> --template <sample>)")


def _err_keys(problems: List[Dict[str, Any]]) -> Set[Tuple[str, str, str]]:
    return {(p.get("code", ""), p.get("ref", ""), p.get("path", "")) for p in problems if p.get("level") == "error"}


class _State:
    """Current stored state of a project under the lock."""

    def __init__(self, project_dir: Path) -> None:
        from . import history

        self.dir = Path(project_dir)
        self.doc, self.version = read_doc(self.dir)
        self.stored_rev = int(self.doc.get("revision") or 0)
        self.has_history = history.has_history(self.dir)
        self.rev = self.stored_rev if self.has_history else max(1, self.stored_rev)
        if not self.has_history:
            self.doc = dict(self.doc, revision=self.rev)

    def map_base(self, base: Optional[int]) -> Optional[int]:
        if base is not None and not self.has_history and base == self.stored_rev:
            return self.rev
        return base


def _conflict(state: _State, base: int, refs: Set[str]) -> ConflictError:
    from . import history

    by = history.authors_since(state.dir, base, refs)
    return ConflictError(f"Someone else changed {len(refs)} item{'s' if len(refs) != 1 else ''} since your revision {base}",
                         revision=state.rev, conflicts=sorted(refs), by=by)


def _commit(state: _State, new_doc: Doc, ops: List[Op], *, rebased: bool, author: str, summary: str, source: str) -> Dict[str, Any]:
    from . import history, schema

    new_doc = schema.normalize(new_doc)
    problems = schema.validate_doc(new_doc)
    old_errs = _err_keys(schema.validate_doc(state.doc)) if schema.errors(problems) else set()
    fresh = [p for p in schema.errors(problems) if (p.get("code", ""), p.get("ref", ""), p.get("path", "")) not in old_errs]
    if fresh:
        raise ValidationError(problems)
    touched = schema.touched_refs(ops)
    new_rev = state.rev + 1
    new_doc["revision"] = new_rev
    if state.version < 2:
        pf = find_project_file(state.dir)
        backup = state.dir / "project.v1.json"
        if pf is not None and not backup.exists():
            if pf.suffix.lower() == ".json":
                shutil.copy2(pf, backup)
            else:
                _atomic_write_json(backup, load_dict(pf))
    if not state.has_history:
        history.record(state.dir, state.rev, [], state.doc, author=author, summary="Initial revision",
                       source="migrate" if state.version < 2 else "put", touched=set())
    history.record(state.dir, new_rev, ops, new_doc, author=author, summary=summary, source=source, touched=touched)
    _atomic_write_json(state.dir / "project.json", new_doc)
    return {"revision": new_rev, "rebased": rebased, "problems": problems, "touched": sorted(touched)}


def save_doc(doc: Doc, project_dir: Path, *, base_revision: Optional[int], author: str = "", summary: str = "", source: str = "put") -> Dict[str, Any]:
    """Store a full doc as the next revision (§5.4 rules). ``base_revision=None``
    skips the concurrency check (CLI / internal use; the HTTP API requires one)."""
    from . import history, schema

    _guard_writable(project_dir)
    if not isinstance(doc, dict):
        raise ValidationError([{"level": "error", "code": "bad_type", "ref": "", "path": "", "message": "doc must be an object"}])
    with project_lock(project_dir):
        st = _State(project_dir)
        base = st.map_base(base_revision)
        client = schema.load_any(doc) if schema.doc_version(doc) != 2 else schema.normalize(doc)
        client["revision"] = st.rev
        if base is None or base == st.rev:
            ops = schema.diff_docs(st.doc, client)
            return _commit(st, client, ops, rebased=False, author=author, summary=summary, source=source)
        if base > st.rev or base < 0:
            raise ConflictError(f"your revision {base} is ahead of the stored revision {st.rev}", revision=st.rev)
        try:
            base_doc = history.get_revision_doc(st.dir, base)
        except KeyError:
            base_doc = st.doc
        ops = schema.diff_docs(base_doc, client)
        hit = schema.touched_refs(ops) & history.touched_since(st.dir, base)
        if hit:
            raise _conflict(st, base, hit)
        new_doc = schema.apply_ops(st.doc, ops)[0]
        return _commit(st, new_doc, ops, rebased=True, author=author, summary=summary, source=source)


def apply_changes(project_dir: Path, ops: List[Op], *, base_revision: int, author: str = "", summary: str = "", source: str = "changes") -> Dict[str, Any]:
    """Apply change ops on top of ``base_revision`` (rebased when untouched since)."""
    from . import history, schema

    _guard_writable(project_dir)
    if base_revision is None:
        raise PreconditionError("base_revision is required")
    with project_lock(project_dir):
        st = _State(project_dir)
        base = st.map_base(int(base_revision))
        if base > st.rev or base < 0:
            raise ConflictError(f"your revision {base} is ahead of the stored revision {st.rev}", revision=st.rev)
        rebased = False
        if base < st.rev:
            hit = schema.touched_refs(ops) & history.touched_since(st.dir, base)
            if hit:
                raise _conflict(st, base, hit)
            rebased = True
        try:
            new_doc = schema.apply_ops(st.doc, ops)[0]
        except schema.SchemaError as exc:
            if exc.code == "missing_entity":
                raise ConflictError(str(exc), revision=st.rev, conflicts=[exc.ref] if exc.ref else [], code="missing_entity")
            raise
        return _commit(st, new_doc, list(ops), rebased=rebased, author=author, summary=summary, source=source)


def restore_revision(project_dir: Path, revision: int, *, base_revision: Optional[int], author: str = "") -> Dict[str, Any]:
    """Make revision ``revision`` the content of a new revision (source ``restore``)."""
    from . import history

    with project_lock(project_dir):
        target = history.get_revision_doc(Path(project_dir), revision)
        return save_doc(target, project_dir, base_revision=base_revision, author=author,
                        summary=f"Restored revision {revision}", source="restore")


def current_revision(project_dir: Path) -> int:
    st = _State(project_dir)
    return st.rev if st.has_history else st.stored_rev


# ---- attachments


def add_attachment(project_dir: Path, filename: str, data: bytes, *, mime: str, device: str = "", kind: str = "other", author: str = "") -> Dict[str, Any]:
    """Write ``files/<att-id>/<safe-name>``; returns the attachment entity (not yet in the doc)."""
    from .history import utc_now

    _guard_writable(project_dir)
    att_id = "att-" + secrets.token_hex(6)
    name = safe_filename(filename)
    target = files_dir(project_dir) / att_id / name
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{name}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, target)
    ent: Dict[str, Any] = {
        "id": att_id, "name": str(filename)[:255] or name, "file": f"files/{att_id}/{name}", "mime": mime or "application/octet-stream",
        "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "kind": kind or "other", "uploaded": utc_now(),
    }
    if device:
        ent["device"] = device
    if author:
        ent["by"] = author
    return ent
