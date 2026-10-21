"""Compatibility guarantees (SPEC §2.3 items 1–9), each as a test."""

from __future__ import annotations

import ast
import contextlib
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from _helpers import (PKG, REPO, RRC_DIR, call, fr, get_app, install_project, jbody, read_json, requires, rrc_dict,
                          temp_data_dir, uniq)
except ImportError:  # pragma: no cover
    from tests._helpers import (PKG, REPO, RRC_DIR, call, fr, get_app, install_project, jbody, read_json, requires, rrc_dict,
                                temp_data_dir, uniq)


# (module, function, v0.2 positional params, v0.2 defaults) — extracted from the 0.2 sources.
V02_SIGNATURES = [
    ("model", "project_from_dict", ["d"], {}),
    ("model", "validate", ["project"], {}),
    ("model", "slug", ["text"], {}),
    ("model", "norm_name", ["text"], {}),
    ("project", "load_project", ["target"], {}),
    ("project", "save_project", ["project", "project_dir"], {}),
    ("project", "new_project", ["name_or_path", "template", "org", "force"], {"template": "blank", "org": "", "force": False}),
    ("project", "list_projects", [], {}),
    ("project", "load_dict", ["path"], {}),
    ("project", "find_project_file", ["target"], {}),
    ("project", "resolve_project", ["target"], {}),
    ("project", "data_root", [], {}),
    ("project", "projects_root", [], {}),
    ("project", "builds_root", [], {}),
    ("project", "blank_project_dict", ["title_org"], {"title_org": ""}),
    ("project", "list_builds", ["project_name"], {}),
    ("project", "new_build_dir", ["project_name", "slug_", "when"], {"when": None}),
    ("merge", "apply_imports", ["project", "project_dir"], {}),
    ("layout", "compute_layout", ["project"], {}),
    ("render_html", "render_html", ["project", "layout"], {}),
    ("render_svg", "render_svg", ["project", "layout"], {}),
    ("patch", "build_patch_sheet", ["project"], {}),
    ("patch", "patch_sheet_csv", ["project"], {}),
    ("trace", "build_graph", ["project"], {}),
    ("trace", "find_paths", ["project", "src", "dst", "max_depth", "limit"], {"max_depth": 8, "limit": 25}),
    ("trace", "downstream", ["project", "src", "max_depth"], {"max_depth": 8}),
    ("trace", "upstream", ["project", "dst", "max_depth"], {"max_depth": 8}),
    ("trace", "resolve_node", ["project", "text"], {}),
    ("trace", "describe_path", ["project", "path"], {}),
    ("trace", "graph_json", ["project"], {}),
    ("parsers", "detect_kind", ["path"], {}),
    ("parsers", "parse_any", ["path", "kind", "device"], {"kind": "auto", "device": ""}),
    ("parsers", "parse_yamaha", ["path"], {}),
    ("parsers", "parse_dante", ["path", "device"], {"device": ""}),
    ("parsers", "parse_waves", ["path"], {}),
    ("parsers.yamaha", "parse_port", ["text"], {}),
    ("parsers.yamaha", "parse_channel_label", ["text"], {}),
    ("parsers.yamaha", "categorize", ["name", "icon"], {}),
    ("export", "build", ["target", "slug", "run_dir", "pdf", "png", "open_after", "quiet"],
     {"slug": "", "run_dir": None, "pdf": False, "png": False, "open_after": False, "quiet": False}),
    ("export", "write_build", ["project", "project_dir", "run_dir", "pdf", "png"], {"pdf": False, "png": False}),
    ("export", "render_project", ["project", "project_dir", "base_url"], {"base_url": ""}),
    ("export", "find_chrome", [], {}),
    ("export", "html_to_pdf", ["html_path", "pdf_path"], {}),
    ("export", "html_to_png", ["html_path", "png_path", "width", "height"], {}),
    ("selftest", "run_selftest", [], {}),
]
V02_NAMES = {
    "model": ["Project", "Node", "Link", "Group", "Column", "Options", "Meta", "ImportSpec", "project_from_dict", "validate", "slug",
              "norm_name", "KINDS", "MEDIA", "BRANDS", "DEFAULT_COLUMNS"],
    "project": ["load_project", "save_project", "new_project", "list_projects", "load_dict", "find_project_file", "resolve_project",
                "data_root", "projects_root", "builds_root", "SAMPLES_DIR", "STATIC_DIR", "blank_project_dict", "list_builds", "new_build_dir"],
    "parsers": ["detect_kind", "parse_any", "parse_yamaha", "parse_dante", "parse_waves", "KINDS"],
}
# v0.2 CLI: command -> flags that must still be accepted
V02_CLI = {
    "serve": ["--host", "--port", "--data", "--open"], "status": [], "new": ["--template", "--org", "--force"],
    "import": ["--kind", "--node", "--device", "--no-copy"], "inspect": ["--kind", "--device", "--json"],
    "build": ["--slug", "--out", "--pdf", "--png", "--open"], "pdf": ["--open"], "trace": ["--max-depth"], "patch": ["--csv"],
    "validate": [], "list": [], "demo": ["--out", "--open", "--pdf", "--png"], "selftest": [],
}


class CompatLoading(unittest.TestCase):
    """§2.3 item 1: v1 files with fathom:1, signalflow:1 or no version key load, migrate in memory and render."""

    def setUp(self):
        self.project = requires("project")
        requires("schema")

    def _variant(self, data, mutate, filename="project.json", text=None):
        name = uniq("v1")
        pdir = install_project(data, name, src_dir=RRC_DIR)
        (pdir / "project.json").unlink()
        d = rrc_dict()
        mutate(d)
        (pdir / filename).write_text(text if text is not None else json.dumps(d), encoding="utf-8")
        return name, pdir

    def test_load_fathom1_signalflow1_noversion(self):
        from fathom.layout import compute_layout
        from fathom.merge import apply_imports
        from fathom.render_html import render_html

        variants = {
            "fathom:1": lambda d: None,
            "signalflow:1": lambda d: (d.pop("fathom", None), d.__setitem__("signalflow", 1)),
            "no version key": lambda d: d.pop("fathom", None),
        }
        with temp_data_dir() as data:
            for label, mut in variants.items():
                with self.subTest(variant=label):
                    name, pdir = self._variant(data, mut)
                    before = (pdir / "project.json").read_bytes()
                    doc, _ = self.project.load_doc(name)
                    self.assertEqual(doc["fathom"], 2, fr("FR-MIG-02", "2.3 item 1", label))
                    p, ddir = self.project.load_project(name)
                    apply_imports(p, ddir)
                    html = render_html(p, compute_layout(p))
                    self.assertIn('data-id="foh"', html)
                    self.assertEqual((pdir / "project.json").read_bytes(), before, "2.3 item 1: written as v2 only on the next save")

    def test_load_jsonc_and_toml(self):
        with temp_data_dir() as data:
            text = "// v1 project with comments\n" + json.dumps(rrc_dict(), indent=1)
            name, pdir = self._variant(data, lambda d: None, filename="project.jsonc", text=text)
            doc, _ = self.project.load_doc(name)
            self.assertEqual(doc["fathom"], 2, fr("FR-MIG-02", "2.3 item 1", ".jsonc"))
            if sys.version_info >= (3, 11):
                toml = 'fathom = 1\n[meta]\norg = "Toml Church"\n[[nodes]]\nid = "a"\nlabel = "A"\nkind = "source"\n[[nodes]]\nid = "b"\nlabel = "B"\nkind = "console"\n[[links]]\nfrom = "a"\nto = "b"\nmedium = "analog"\n'
                tname = uniq("toml")
                tdir = install_project(data, tname)
                (tdir / "project.toml").write_text(toml, encoding="utf-8")
                tdoc, _ = self.project.load_doc(tname)
                self.assertEqual([d["id"] for d in tdoc["devices"]], ["a", "b"], fr("FR-MIG-02", "2.3 item 1", ".toml"))
                self.assertEqual(len(tdoc["cables"]), 1)

    def test_first_v2_write_saves_v1_backup(self):
        with temp_data_dir() as data:
            name, pdir = self._variant(data, lambda d: (d.pop("fathom", None), d.__setitem__("signalflow", 1)))
            original = (pdir / "project.json").read_bytes()
            doc, ddir = self.project.load_doc(name)
            self.project.apply_changes(ddir, [{"op": "root", "key": "meta", "value": {"description": "x"}}],
                                       base_revision=doc.get("revision", 0), author="t1")
            self.assertEqual((pdir / "project.v1.json").read_bytes(), original, fr("FR-MIG-04", "2.3 item 1"))
            self.assertEqual(read_json(pdir / "project.json")["fathom"], 2)


class CompatRRC(unittest.TestCase):
    """§2.3 items 2–3: RRC stays v1, builds, and its map is layout-identical (FR-MIG-03)."""

    def test_rrc_is_still_v1_and_builds(self):
        schema = requires("schema")
        d = rrc_dict()
        self.assertEqual(schema.doc_version(d), 1, "2.3 item 2: RRC sample stays v1 (frozen)")
        from fathom.export import build

        with temp_data_dir() as data:
            out = data / "run"
            run = build(str(RRC_DIR), run_dir=out, quiet=True)
            for f in ("index.html", "diagram.svg", "patch-sheet.csv", "project.json", Path(run).name + ".zip"):
                self.assertTrue((Path(run) / f).exists(), fr("FR-EXP-02", "2.3 item 2", f))
        self.assertEqual(schema.doc_version(rrc_dict()), 1, "build must not rewrite the frozen sample")
        self.assertFalse((RRC_DIR / "project.v1.json").exists(), "2.3 item 2: nobody writes into the frozen sample")
        self.assertFalse((RRC_DIR / "history").exists(), "2.3 item 2: nobody writes into the frozen sample")

    def test_rrc_layout_identity(self):
        schema = requires("schema")
        from fathom.layout import compute_layout
        from fathom.merge import apply_imports
        from fathom.model import project_from_dict

        tmp = Path(tempfile.mkdtemp(prefix="fathom-t1-"))
        try:
            pdir = tmp / "rrc"
            shutil.copytree(str(RRC_DIR), str(pdir))
            p1 = project_from_dict(rrc_dict())
            p2 = schema.flow_project(schema.migrate(rrc_dict()))
            apply_imports(p1, pdir)
            apply_imports(p2, pdir)
            l1, l2 = compute_layout(p1), compute_layout(p2)
            boxes = lambda l: {k: tuple(round(v, 2) for v in (c.box.x, c.box.y, c.box.w, c.box.h)) for k, c in l.cards.items()}  # noqa: E731
            self.assertEqual(boxes(l1), boxes(l2), fr("FR-MIG-03", "2.3 item 3"))
            self.assertEqual(len(l1.links), len(l2.links), fr("FR-MIG-03", "2.3 item 3"))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_rrc_viewer_unchanged_structure(self):
        app = get_app()
        with temp_data_dir() as data:
            install_project(data, "rrc", src_dir=RRC_DIR)
            st, h, body = call(app, "GET", "/p/rrc")
            self.assertEqual(st, 200, fr("FR-MAP-01", "5.12"))
            html = body.decode("utf-8")
            for needle in ('class="card', 'data-id="foh"', "SF_DATA", "Patch sheet"):
                self.assertIn(needle, html, fr("FR-MAP-01", "7.3 W5", "viewer keeps %r" % needle))
            st, _, svg = call(app, "GET", "/p/rrc/diagram.svg")
            self.assertEqual(st, 200)
            self.assertIn(b"<svg", svg)
            st, _, csvb = call(app, "GET", "/p/rrc/patch-sheet.csv")
            self.assertEqual(st, 200)
            self.assertTrue(csvb.strip())
            st, _, pj = call(app, "GET", "/p/rrc/project.json")
            self.assertEqual(st, 200)
            self.assertEqual(json.loads(pj.decode())["fathom"], 2, "5.12 /p/<n>/project.json returns the v2 doc")

    def test_rrc_key_label(self):
        app = get_app()
        with temp_data_dir() as data:
            install_project(data, "rrc", src_dir=RRC_DIR)
            st, _, body = call(app, "GET", "/p/rrc")
            self.assertEqual(st, 200)
            self.assertIn("Dante network", body.decode("utf-8"), fr("FR-MAP-02", "3.7", "RRC key still reads 'Dante network'"))


class CompatCLI(unittest.TestCase):
    """§2.3 item 4: existing CLI commands and flags keep working."""

    def _help(self, args):
        cli = requires("cli")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                cli.main(args)
        return cm.exception.code, out.getvalue() + err.getvalue()

    def test_cli_commands_exist(self):
        for cmd, flags in V02_CLI.items():
            with self.subTest(cmd=cmd):
                code, text = self._help([cmd, "--help"])
                self.assertIn(code, (0, None), "2.3 item 4: `fathom %s --help` exits 0" % cmd)
                for flag in flags:
                    self.assertIn(flag, text, "2.3 item 4: `fathom %s` keeps flag %s" % (cmd, flag))

    def test_cli_kind_choices_from_registry(self):
        code, text = self._help(["import", "--help"])
        for k in ("yamaha", "dante", "waves"):
            self.assertIn(k, text, "7.3 W2 item 8: --kind choices include %s" % k)

    def test_cli_new_commands_exist(self):
        for cmd in ("migrate", "user", "library", "schedule", "qr", "plan", "ask", "history", "restore", "vocab", "plugins"):
            with self.subTest(cmd=cmd):
                code, _ = self._help([cmd, "--help"])
                self.assertIn(code, (0, None), "7.3 W2 item 8: new command %s" % cmd)


class CompatAPI(unittest.TestCase):
    """§2.3 items 5–8."""

    def test_public_v1_functions_exist(self):
        for mod, names in V02_NAMES.items():
            m = requires(mod)
            for n in names:
                self.assertTrue(hasattr(m, n), "2.3 item 6: fathom.%s.%s" % (mod, n))
        for mod, fn, params, defaults in V02_SIGNATURES:
            with self.subTest(fn="%s.%s" % (mod, fn)):
                f = getattr(requires(mod), fn, None)
                self.assertTrue(callable(f), "2.3 item 6: fathom.%s.%s missing" % (mod, fn))
                sig = inspect.signature(f)
                ps = list(sig.parameters.values())
                positional = [p for p in ps if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
                self.assertEqual([p.name for p in positional[:len(params)]], params,
                                 "2.3 item 6: fathom.%s.%s keeps its v0.2 positional parameters %s, got %s" % (mod, fn, params, sig))
                for p in positional[:len(params)]:
                    if p.name in defaults:
                        self.assertEqual(p.default, defaults[p.name], "2.3 item 6: %s.%s default of %s" % (mod, fn, p.name))
                    else:
                        self.assertIs(p.default, inspect.Parameter.empty, "2.3 item 6: %s.%s %s stays required" % (mod, fn, p.name))
                for p in ps:
                    if p.name in params or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                        continue
                    self.assertIsNot(p.default, inspect.Parameter.empty,
                                     "2.3 item 6: new parameter %s of %s.%s must be optional" % (p.name, mod, fn))

    def test_wsgi_entry_point(self):
        server = requires("server")
        import fathom

        self.assertTrue(callable(server.app), "2.3 item 7: fathom.server:app")
        self.assertEqual(fathom.__version__, "0.3.0", "7.2 W1 version 0.3.0")
        with temp_data_dir():
            st, h, body = call(server.app, "GET", "/healthz")
            self.assertEqual(st, 200)
            self.assertEqual(jbody(body), {"ok": True, "version": "0.3.0"}, "2.3 item 7 /healthz")
        dockerfile = REPO / "Dockerfile"
        if dockerfile.exists():
            text = dockerfile.read_text()
            self.assertIn("fathom.server:app", text, "2.3 item 7 Docker keeps gunicorn fathom.server:app")
            self.assertIn("8080", text)

    def test_no_auth_is_full_access(self):
        app = get_app()
        with temp_data_dir() as data:
            st, _, body = call(app, "GET", "/api/v2/session")
            self.assertEqual(st, 200)
            s = jbody(body)
            self.assertFalse(s["auth_enabled"], fr("FR-USER-05", "2.3 item 8"))
            self.assertEqual((s.get("user") or {}).get("role", "admin"), "admin")
            st, _, body = call(app, "POST", "/api/v2/projects", {"name": "open", "template": "blank", "org": "X"})
            self.assertEqual(st, 201, fr("FR-USER-05", "2.3 item 8", "anyone may create a project when auth is off: %s" % body[:200]))
            st, _, body = call(app, "DELETE", "/api/v2/projects/open?confirm=open")
            self.assertEqual(st, 200, fr("FR-USER-05", "2.3 item 8", "admin-only delete works with auth off"))


class Py39(unittest.TestCase):
    """§2.3 item 9: Python 3.9 compatibility (G5)."""

    def _files(self):
        return sorted(list((PKG).rglob("*.py")) + list((REPO / "tests").rglob("*.py")))

    def test_future_annotations_everywhere(self):
        missing = []
        for f in PKG.rglob("*.py"):
            if f.name == "__main__.py":  # frozen (§7.2), never had the import
                continue
            src = f.read_text(encoding="utf-8")
            if not src.strip():
                continue
            if "from __future__ import annotations" not in src:
                missing.append(str(f.relative_to(REPO)))
        self.assertEqual(missing, [], "2.3 item 9: every module keeps `from __future__ import annotations`")

    def test_py39_forbidden_syntax(self):
        problems = []
        for f in self._files():
            src = f.read_text(encoding="utf-8")
            rel = str(f.relative_to(REPO))
            try:
                tree = ast.parse(src)
            except SyntaxError as e:
                problems.append("%s: syntax error %s" % (rel, e))
                continue
            for node in ast.walk(tree):
                name = type(node).__name__
                if name in ("Match", "TryStar"):
                    problems.append("%s:%d %s statement" % (rel, node.lineno, name))
                if isinstance(node, ast.Call):
                    fn = node.func
                    fname = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
                    if fname == "zip" and any(k.arg == "strict" for k in node.keywords):
                        problems.append("%s:%d zip(strict=)" % (rel, node.lineno))
                    if fname in ("pairwise", "bit_count"):
                        problems.append("%s:%d %s()" % (rel, node.lineno, fname))
                    if fname in ("isinstance", "issubclass") and len(node.args) == 2 and isinstance(node.args[1], ast.BinOp) \
                            and isinstance(node.args[1].op, ast.BitOr):
                        problems.append("%s:%d isinstance(x, A | B)" % (rel, node.lineno))
                if isinstance(node, (ast.With, ast.AsyncWith)) and len(node.items) > 1:
                    seg = ast.get_source_segment(src, node) or ""
                    if re.match(r"(async\s+)?with\s*\(", seg) and re.match(r"(async\s+)?with\s*\([^\n]*\n", seg):
                        problems.append("%s:%d parenthesized context managers" % (rel, node.lineno))
            for node in tree.body:
                targets = []
                if isinstance(node, ast.Import):
                    targets = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    targets = [node.module or ""]
                if "tomllib" in targets:
                    problems.append("%s:%d top-level import tomllib" % (rel, node.lineno))
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    # runtime-evaluated PEP 604 unions in module-level aliases, e.g. X = int | None
                    val = node.value
                    if isinstance(val, ast.BinOp) and isinstance(val.op, ast.BitOr) and \
                            all(isinstance(s, (ast.Name, ast.Attribute, ast.Subscript, ast.Constant)) for s in (val.left, val.right)) and \
                            any(isinstance(s, ast.Constant) and s.value is None for s in (val.left, val.right)):
                        problems.append("%s:%d PEP 604 union evaluated at runtime" % (rel, node.lineno))
        self.assertEqual(problems, [], "2.3 item 9 forbidden syntax")

    def test_compileall_py39(self):
        """G5: compile with a 3.9 interpreter when one is available (this one, or /usr/bin/python3)."""
        exe = None
        if sys.version_info[:2] == (3, 9):
            exe = sys.executable
        elif os.path.exists("/usr/bin/python3"):
            try:
                v = subprocess.run(["/usr/bin/python3", "-c", "import sys;print(sys.version_info[:2]==(3,9))"],
                                   capture_output=True, text=True, timeout=20).stdout.strip()
                if v == "True":
                    exe = "/usr/bin/python3"
            except Exception:
                exe = None
        if exe is None:
            return  # ast checks above still apply; G5 is run by QA with a 3.9 interpreter
        prefix = tempfile.mkdtemp(prefix="fathom-t1-pyc-")
        try:
            env = dict(os.environ, PYTHONPYCACHEPREFIX=prefix)
            r = subprocess.run([exe, "-m", "compileall", "-q", "fathom", "tests"], cwd=str(REPO), env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, "G5 / 2.3 item 9: py3.9 compileall failed:\n%s%s" % (r.stdout[-3000:], r.stderr[-2000:]))
        finally:
            shutil.rmtree(prefix, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
