"""Importer registry and plugin loader.

Built-in importers register themselves when ``fathom.parsers`` is imported.
Extra plugin modules live in the directories named by ``FATHOM_PLUGINS``
(``os.pathsep``-separated). Each ``*.py`` file or package there is imported
and its ``register(api)`` called with a :class:`PluginAPI`. Errors are caught,
printed to stderr and listed by :func:`plugin_errors` (``/api/v2/meta``).

Extension directories for templates and checklists come from
``FATHOM_LIBRARY`` / ``FATHOM_CHECKLISTS`` plus whatever plugins register.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

API_VERSION = "1"


@dataclass
class Importer:
    kind: str
    label: str
    detect: Callable[[Path], float]  # 0..1 confidence
    parse: Callable[..., Any]  # parse(path, **options) -> ParseResult
    contribute: Optional[Callable[[Any, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None
    preview: Optional[Callable[[Any, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None
    mode: str = "live"  # live | oneshot
    accepts: Tuple[str, ...] = ()
    folder: bool = False
    help: str = ""
    source: str = "builtin"

    def info(self) -> Dict[str, Any]:
        return {
            "kind": self.kind, "label": self.label, "mode": self.mode, "accepts": list(self.accepts),
            "folder": self.folder, "help": self.help, "source": self.source,
        }


_REGISTRY: Dict[str, Importer] = {}
_ERRORS: List[str] = []
_LOADED: Dict[str, str] = {}  # resolved file path -> module name
_TEMPLATE_DIRS: List[Path] = []
_CHECKLIST_DIRS: List[Path] = []
_BUILTINS_DONE = False


def _ensure_builtins() -> None:
    global _BUILTINS_DONE
    if _BUILTINS_DONE:
        return
    _BUILTINS_DONE = True
    try:
        from . import parsers  # noqa: F401  (registers the built-ins)
    except Exception as exc:  # pragma: no cover - would be a packaging bug
        _ERRORS.append(f"fathom.parsers: {exc}")


def register_importer(imp: Importer) -> None:
    """Add or replace an importer (a plugin may override a built-in kind)."""
    if not isinstance(imp, Importer):
        raise TypeError("register_importer expects a fathom.plugins.Importer")
    if not imp.kind or not isinstance(imp.kind, str):
        raise ValueError("importer kind must be a non-empty string")
    _REGISTRY[imp.kind] = imp


def get_importer(kind: str) -> Optional[Importer]:
    _ensure_builtins()
    load_plugins()
    return _REGISTRY.get(kind or "")


def importers() -> List[Importer]:
    """All importers: built-ins first (registration order), then plugins."""
    _ensure_builtins()
    load_plugins()
    return list(_REGISTRY.values())


def detect(path: Path) -> str:
    """Best importer kind for a file or folder (confidence ≥ 0.3), else ``unknown``."""
    best, score = "unknown", 0.0
    for imp in importers():
        try:
            s = float(imp.detect(Path(path)) or 0.0)
        except Exception:
            s = 0.0
        if s > score:
            best, score = imp.kind, s
    return best if score >= 0.3 else "unknown"


class PluginAPI:
    """What ``register(api)`` receives."""

    version = API_VERSION

    def __init__(self, module: str = "") -> None:
        self.module = module

    def register_importer(self, imp: Importer) -> None:
        if imp.source == "builtin":
            imp.source = self.module or "plugin"
        register_importer(imp)

    def register_template_dir(self, path: Any) -> None:
        p = Path(path).expanduser()
        if p not in _TEMPLATE_DIRS:
            _TEMPLATE_DIRS.append(p)

    def register_checklist_dir(self, path: Any) -> None:
        p = Path(path).expanduser()
        if p not in _CHECKLIST_DIRS:
            _CHECKLIST_DIRS.append(p)

    # convenience for plugin authors
    Importer = Importer


def _env_dirs(var: str) -> List[Path]:
    raw = os.environ.get(var) or ""
    return [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]


def _load_one(file: Path, mod_name: str, is_pkg: bool) -> None:
    if is_pkg:
        spec = importlib.util.spec_from_file_location(mod_name, str(file / "__init__.py"), submodule_search_locations=[str(file)])
    else:
        spec = importlib.util.spec_from_file_location(mod_name, str(file))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    reg = getattr(module, "register", None)
    if callable(reg):
        reg(PluginAPI(mod_name))


def load_plugins(paths: Optional[List[str]] = None) -> List[str]:
    """Import plugin modules from ``paths`` (default ``FATHOM_PLUGINS``). Idempotent."""
    _ensure_builtins()
    dirs = [Path(p).expanduser() for p in paths] if paths is not None else _env_dirs("FATHOM_PLUGINS")
    loaded: List[str] = []
    for d in dirs:
        if not d.is_dir():
            msg = f"plugin dir not found: {d}"
            if msg not in _ERRORS:
                _ERRORS.append(msg)
            continue
        for entry in sorted(d.iterdir()):
            if entry.name.startswith(("_", ".")):
                continue
            is_pkg = entry.is_dir() and (entry / "__init__.py").is_file()
            if not is_pkg and not (entry.is_file() and entry.suffix == ".py"):
                continue
            key = str(entry.resolve())
            if key in _LOADED:
                loaded.append(_LOADED[key])
                continue
            mod_name = "fathom_plugin_" + "".join(c if c.isalnum() else "_" for c in entry.stem)
            _LOADED[key] = mod_name
            try:
                _load_one(entry, mod_name, is_pkg)
                loaded.append(mod_name)
            except Exception as exc:
                msg = f"plugin {entry.name}: {type(exc).__name__}: {exc}"
                _ERRORS.append(msg)
                print(f"fathom: {msg}", file=sys.stderr)
                if os.environ.get("FATHOM_DEBUG"):
                    traceback.print_exc()
    return loaded


def plugin_errors() -> List[str]:
    return list(_ERRORS)


def template_dirs() -> List[Path]:
    """Extension template dirs: ``FATHOM_LIBRARY`` then plugin-registered."""
    load_plugins()
    out: List[Path] = []
    for p in _env_dirs("FATHOM_LIBRARY") + _TEMPLATE_DIRS:
        if p not in out:
            out.append(p)
    return out


def checklist_dirs() -> List[Path]:
    """Extension checklist dirs: ``FATHOM_CHECKLISTS`` then plugin-registered."""
    load_plugins()
    out: List[Path] = []
    for p in _env_dirs("FATHOM_CHECKLISTS") + _CHECKLIST_DIRS:
        if p not in out:
            out.append(p)
    return out


def _reset_for_tests() -> None:  # pragma: no cover - test helper
    """Forget plugin modules/dirs (built-ins stay registered)."""
    for k in [k for k, v in _REGISTRY.items() if v.source != "builtin"]:
        del _REGISTRY[k]
    _ERRORS.clear()
    _LOADED.clear()
    _TEMPLATE_DIRS.clear()
    _CHECKLIST_DIRS.clear()


__all__ = [
    "API_VERSION", "Importer", "PluginAPI", "register_importer", "get_importer", "importers", "detect",
    "load_plugins", "plugin_errors", "template_dirs", "checklist_dirs",
]
