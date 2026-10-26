"""Patch view UI (docs/ui-audit.md B.3 PV): drag patching on the harness with real CDP input.

Run alone: ``FATHOM_CHROME=/usr/bin/google-chrome-stable .venv/bin/python -m unittest discover -s tests -p test_ui_pv.py``.
Skips without Chrome.
"""
from __future__ import annotations

import json
import time
import unittest

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

HARNESS = "/static/dev/patchview.html"

# Screen point of a port's connection dot ('l' or 'r'), or null when it is outside the canvas.
DOT_JS = """(function (sel, side) {
  var el = document.querySelector(sel); if (!el) return null;
  var d = el.querySelector('.pv-dot-' + side) || el.querySelector('.pv-dot'); if (!d) return null;
  var r = d.getBoundingClientRect(), v = document.querySelector('.pv-viewport').getBoundingClientRect();
  var x = r.left + r.width / 2, y = r.top + r.height / 2;
  if (x < v.left + 2 || x > v.right - 2 || y < v.top + 2 || y > v.bottom - 2) return null;
  return {x: x, y: y};
})(%s, %s)"""

# A free output port on an editable card whose dot is on screen.
SOURCE_JS = """(function () {
  var v = document.querySelector('.pv-viewport').getBoundingClientRect();
  var ps = document.querySelectorAll('.pv-card:not(.pv-auto):not(.pv-ext) .pv-port.pv-right:not(.pv-conn)');
  for (var i = 0; i < ps.length; i++) {
    var d = ps[i].querySelector('.pv-dot-r'); if (!d) continue;
    var r = d.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (x > v.left + 4 && x < v.right - 4 && y > v.top + 4 && y < v.bottom - 4) {
      return {device: ps[i].closest('.pv-card').getAttribute('data-device'), port: ps[i].getAttribute('data-port'), x: x, y: y};
    }
  }
  return null;
})()"""

# While a wire drag is in progress: a highlighted (compatible) free input on screen, nearest first.
TARGET_JS = """(function (sx, sy, src) {
  var v = document.querySelector('.pv-viewport').getBoundingClientRect(), best = null;
  document.querySelectorAll('.pv-port.pv-ok.pv-left:not(.pv-conn)').forEach(function (p) {
    var card = p.closest('.pv-card'); if (!card || card.getAttribute('data-device') === src) return;
    var d = p.querySelector('.pv-dot-l'); if (!d) return;
    var r = d.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (x < v.left + 4 || x > v.right - 4 || y < v.top + 4 || y > v.bottom - 4) return;
    var el = document.elementFromPoint(x, y);
    if (el && el.closest('.pv-menu, .pv-toolbar')) return;
    var dd = Math.hypot(x - sx, y - sy);
    if (!best || dd < best.d) best = {x: x, y: y, d: dd, device: card.getAttribute('data-device'), port: p.getAttribute('data-port')};
  });
  return best;
})(%s, %s, %s)"""

COUNTS_JS = """({dom: document.querySelectorAll('.pv-wires path[data-cable]').length,
  store: window.__pv.store.doc.cables.length})"""


class PatchViewDrag(UiCase):
    """A.4 #1: port-to-port drag patching (mouse at d, touch at m) creates exactly one cable."""

    def _drag(self, pg, touch):
        pg.wait_for("window.__pv && document.querySelectorAll('.pv-card').length > 0")
        before = pg.js(COUNTS_JS)
        self.assertEqual(before["dom"], before["store"])
        src = pg.wait_for(SOURCE_JS)
        sx, sy = src["x"], src["y"]

        def send(kind, x, y):
            if touch:
                if kind == "up":
                    pg.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                else:
                    pg.command("Input.dispatchTouchEvent", {"type": "touchStart" if kind == "down" else "touchMove",
                                                            "touchPoints": [{"x": x, "y": y, "id": 1}]})
            else:
                typ = {"down": "mousePressed", "move": "mouseMoved", "up": "mouseReleased"}[kind]
                p = {"type": typ, "x": x, "y": y, "button": "left", "buttons": 0 if kind == "up" else 1}
                if kind != "move":
                    p["clickCount"] = 1
                pg.command("Input.dispatchMouseEvent", p)

        if not touch:
            pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": sx, "y": sy})
        send("down", sx, sy)
        for i in range(1, 6):
            send("move", sx + 4 * i, sy + 3 * i)
        pg.wait_for("document.querySelector('.pv-root').classList.contains('pv-connecting')", 5)
        tgt = pg.wait_for(TARGET_JS % (json.dumps(sx), json.dumps(sy), json.dumps(src["device"])), 5)
        tx, ty = tgt["x"], tgt["y"]
        cx, cy = sx + 20, sy + 15
        for i in range(1, 9):
            send("move", cx + (tx - cx) * i / 8.0, cy + (ty - cy) * i / 8.0)
        time.sleep(0.05)
        send("up", tx, ty)
        pg.wait_for("(%s).store === %d" % (COUNTS_JS, before["store"] + 1), 5)
        after = pg.wait_for("(function (c) { return c.dom === c.store ? c : null; })(%s)" % COUNTS_JS, 5)
        self.assertEqual(after["store"], before["store"] + 1)
        self.assertEqual(after["dom"], before["dom"] + 1)
        cable = pg.js("window.__pv.store.doc.cables[window.__pv.store.doc.cables.length - 1]")
        ends = {(cable["from"]["device"], cable["from"]["port"]), (cable["to"]["device"], cable["to"]["port"])}
        self.assertEqual(ends, {(src["device"], src["port"]), (tgt["device"], tgt["port"])})
        self.assertFalse(pg.js("document.querySelector('.pv-root').classList.contains('pv-connecting')"))
        self.assertEqual(pg.js("window.__fathomErrors"), [])

    def test_mouse_drag_patch_at_d(self):
        with self.open(HARNESS, "d") as pg:
            self._drag(pg, touch=False)

    def test_touch_drag_patch_at_m(self):
        with self.open(HARNESS, "m") as pg:
            self._drag(pg, touch=True)


if __name__ == "__main__":
    unittest.main()
