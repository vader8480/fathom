"""Revision history: an append-only ops log plus periodic snapshots (§4.10).

Layout under a project folder::

    history/index.jsonl            one JSON line per revision (append-only)
    history/ops/<rev:06d>.json     ops that produced <rev> from <rev-1>
    history/snap/<rev:06d>.json    full normalized doc at <rev> (rev 1 and every 25th)

Callers hold the project lock (``project.project_lock``) while writing.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

SNAPSHOT_EVERY = 25


def history_dir(project_dir: Path) -> Path:
    return Path(project_dir) / "history"


def _index_path(project_dir: Path) -> Path:
    return history_dir(project_dir) / "index.jsonl"


def has_history(project_dir: Path) -> bool:
    p = _index_path(project_dir)
    return p.is_file() and p.stat().st_size > 0


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_new(path: Path, data: Any) -> None:
    """Write a JSON file atomically (tmp + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:  # pragma: no cover
            pass
    os.replace(tmp, path)


def _read_index(project_dir: Path) -> List[Dict[str, Any]]:
    p = _index_path(project_dir)
    if not p.is_file():
        return []
    out = []
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and isinstance(row.get("revision"), int):
                out.append(row)
    return out


def record(project_dir: Path, revision: int, ops: List[Dict[str, Any]], doc_after: Dict[str, Any], *, author: str,
           summary: str, source: str, touched: Set[str]) -> None:
    """Append revision ``revision`` (ops file, optional snapshot, index line)."""
    hdir = history_dir(project_dir)
    _write_new(hdir / "ops" / f"{revision:06d}.json", ops)
    snapshot = revision == 1 or revision % SNAPSHOT_EVERY == 0
    if snapshot:
        _write_new(hdir / "snap" / f"{revision:06d}.json", doc_after)
    line = {
        "revision": revision,
        "time": utc_now(),
        "author": author or "",
        "summary": summary or "",
        "source": source or "put",
        "touched": sorted(touched or []),
        "ops": len(ops or []),
        "snapshot": snapshot,
    }
    hdir.mkdir(parents=True, exist_ok=True)
    with open(_index_path(project_dir), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:  # pragma: no cover
            pass


def list_revisions(project_dir: Path, limit: int = 50, before: Optional[int] = None) -> List[Dict[str, Any]]:
    """Index lines, newest first."""
    rows = _read_index(project_dir)
    if before is not None:
        rows = [r for r in rows if r["revision"] < before]
    rows.sort(key=lambda r: r["revision"], reverse=True)
    return rows[: max(0, int(limit))] if limit is not None else rows


def get_entry(project_dir: Path, revision: int) -> Dict[str, Any]:
    for r in _read_index(project_dir):
        if r["revision"] == revision:
            return r
    raise KeyError(revision)


def get_revision_doc(project_dir: Path, revision: int) -> Dict[str, Any]:
    """Doc at ``revision``: nearest snapshot ≤ revision plus ops replay. KeyError when the chain is broken."""
    from .schema import apply_ops

    revs = {r["revision"] for r in _read_index(project_dir)}
    if revision not in revs:
        raise KeyError(revision)
    snap_dir = history_dir(project_dir) / "snap"
    base = None
    for r in range(revision, 0, -1):
        p = snap_dir / f"{r:06d}.json"
        if p.is_file() and r in revs:
            base = r
            break
    if base is None:
        raise KeyError(revision)
    with open(snap_dir / f"{base:06d}.json", "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    ops_dir = history_dir(project_dir) / "ops"
    for r in range(base + 1, revision + 1):
        p = ops_dir / f"{r:06d}.json"
        if r not in revs or not p.is_file():
            raise KeyError(revision)
        with open(p, "r", encoding="utf-8") as fh:
            ops = json.load(fh)
        doc = apply_ops(doc, ops)[0]
    doc["revision"] = revision
    return doc


def touched_since(project_dir: Path, base_revision: int) -> Set[str]:
    out: Set[str] = set()
    for r in _read_index(project_dir):
        if r["revision"] > base_revision:
            out.update(r.get("touched") or [])
    return out


def authors_since(project_dir: Path, base_revision: int, refs: Optional[Set[str]] = None) -> List[str]:
    """Authors of revisions after ``base_revision`` (that touched ``refs`` when given)."""
    out: List[str] = []
    for r in _read_index(project_dir):
        if r["revision"] <= base_revision:
            continue
        if refs is not None and not (set(r.get("touched") or []) & refs):
            continue
        a = r.get("author") or ""
        if a and a not in out:
            out.append(a)
    return out


def diff_revisions(project_dir: Path, a: int, b: int) -> Dict[str, List[str]]:
    """``{"added", "removed", "changed"}`` entity refs between revisions a → b."""
    from .schema import COLLECTIONS, diff_docs

    da, db = get_revision_doc(project_dir, a), get_revision_doc(project_dir, b)
    ids_a = {f"{c}/{e.get('id')}" for c in COLLECTIONS for e in da.get(c) or [] if isinstance(e, dict)}
    added, removed, changed = [], [], []
    for op in diff_docs(da, db):
        if op["op"] == "root":
            changed.append(op["key"])
            continue
        ref = f"{op['coll']}/{op['id']}"
        if op["op"] == "del":
            removed.append(ref)
        elif ref in ids_a:
            changed.append(ref)
        else:
            added.append(ref)
    return {"added": sorted(added), "removed": sorted(removed), "changed": sorted(changed)}
