"""SVG → PNG / PDF through headless Chrome (Phase 5 P5C).

Used by the ``…/patch.png|pdf`` and ``…/floorplans/<fp>.png|pdf`` routes and by builds. The SVG is wrapped in a
minimal HTML page in a temporary folder and Chrome prints or screenshots it with the flags ``export.find_chrome`` /
``export._chrome_flags`` already use. Errors are :class:`RasterError` with ``code`` ``chrome_missing`` (no browser on
the host) or ``chrome_failed`` (non-zero exit, timeout, empty output) and a short redacted ``detail``.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

TIMEOUT = 60
PAPERS = {"A4": (210, 297), "A3": (297, 420), "letter": (216, 279), "tabloid": (279, 432)}
MAX_PNG_WIDTH = 6000


class RasterError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


def viewbox_size(svg_text: str) -> Tuple[float, float]:
    """``(width, height)`` from the root ``viewBox`` (falls back to ``width`` / ``height`` attributes, then 1000×700)."""
    head = svg_text[:4000]
    m = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)\s*"', head)
    if m:
        w, h = float(m.group(1)), float(m.group(2))
        if w > 0 and h > 0:
            return w, h
    mw = re.search(r'<svg[^>]*\swidth="([\d.]+)', head)
    mh = re.search(r'<svg[^>]*\sheight="([\d.]+)', head)
    if mw and mh and float(mw.group(1)) > 0 and float(mh.group(1)) > 0:
        return float(mw.group(1)), float(mh.group(1))
    return 1000.0, 700.0


def _redact(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip() and "dbus" not in ln.lower()]
    last = lines[-1] if lines else ""
    last = re.sub(r"/[^\s:]+", "<path>", last)
    return last[:200]


def _wrap(svg_text: str, css: str) -> str:
    return ('<!doctype html><html><head><meta charset="utf-8"><style>' + css + "</style></head><body>" + svg_text + "</body></html>")


def _run(args: list, out_path: Path) -> None:
    from .export import _run_chrome, find_chrome

    if not find_chrome():
        raise RasterError("chrome_missing")
    try:
        res = _run_chrome(args, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RasterError("chrome_failed", f"timed out after {TIMEOUT} s")
    except (OSError, SystemExit) as exc:
        raise RasterError("chrome_failed", _redact(str(exc)))
    if res.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        raise RasterError("chrome_failed", _redact(res.stderr or res.stdout) or f"exit {res.returncode}")


def svg_to_png(svg_text: str, out_path: Path, *, width: int = 2000, scale: float = 1) -> Path:
    """Screenshot ``svg_text`` into ``out_path`` at ``width`` px (height from the viewBox ratio, ``scale`` = device pixels per CSS px)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vw, vh = viewbox_size(svg_text)
    width = max(200, min(int(width), MAX_PNG_WIDTH))
    height = max(100, int(round(width * vh / vw)))
    css = f"html,body{{margin:0;padding:0;background:#fff;overflow:hidden}}svg{{display:block;width:{width}px;height:{height}px}}"
    with tempfile.TemporaryDirectory(prefix="fathom-raster-") as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(_wrap(svg_text, css), encoding="utf-8")
        args = [f"--screenshot={out_path.resolve()}", f"--window-size={width},{height}", "--virtual-time-budget=2000", page.resolve().as_uri()]
        if scale and float(scale) != 1:
            args.insert(0, f"--force-device-scale-factor={float(scale):g}")
        _run(args, out_path)
    return out_path


def svg_to_pdf(svg_text: str, out_path: Path, *, paper: str = "A3", landscape: bool = True) -> Path:
    """Print ``svg_text`` into ``out_path`` on one ``paper`` page (``A4``, ``A3``, ``letter``, ``tabloid``), 8 mm margins, scaled to fit."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    size = paper if paper in PAPERS else "A3"
    pw, ph = PAPERS[size]
    if landscape:
        pw, ph = ph, pw
    css = (f"@page{{size:{size} {'landscape' if landscape else 'portrait'};margin:8mm}}html,body{{margin:0;padding:0;background:#fff}}"
           f"svg{{display:block;width:{pw - 16}mm;height:{ph - 16}mm}}")
    with tempfile.TemporaryDirectory(prefix="fathom-raster-") as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(_wrap(svg_text, css), encoding="utf-8")
        _run(["--no-pdf-header-footer", f"--print-to-pdf={out_path.resolve()}", "--virtual-time-budget=2000", page.resolve().as_uri()], out_path)
    return out_path


def render_bytes(svg_text: str, fmt: str, *, width: int = 2000, paper: str = "A3", landscape: bool = True) -> bytes:
    """``svg_to_png`` / ``svg_to_pdf`` into a temp file, returned as bytes (``fmt`` ``png`` or ``pdf``)."""
    with tempfile.TemporaryDirectory(prefix="fathom-raster-") as tmp:
        out = Path(tmp) / f"out.{fmt}"
        if fmt == "pdf":
            svg_to_pdf(svg_text, out, paper=paper, landscape=landscape)
        else:
            svg_to_png(svg_text, out, width=width)
        return out.read_bytes()


def available() -> bool:
    from .export import find_chrome

    return bool(find_chrome())


__all__ = ["RasterError", "svg_to_png", "svg_to_pdf", "render_bytes", "viewbox_size", "available", "MAX_PNG_WIDTH", "PAPERS"]
