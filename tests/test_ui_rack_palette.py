"""PAL: the rack library palette harness ``/static/dev/rack-palette.html`` in headless Chrome.

Search narrows the list (ranked, fuzzy), category chips filter, a star persists across a reload through
localStorage ``fathom.ui.rack.palette``, Add calls ``onPick`` with the full template (fetched through
``ctx.api.template`` when the summary has no ports) and records a recent, keyboard (arrows, Enter, ``f``),
pointer drags call ``onDragStart`` (mouse after a move, touch after a long press), the no-API, error and
"Show more" states, missing images degrade to swatches, 44 px targets at m. Skips without Chrome.
"""
from __future__ import annotations

import json
import time

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

HARNESS = "/static/dev/rack-palette.html"
RACKABLE = 16  # 14 library summaries with ru >= 1 plus 2 presets the library lacks


def q(s: str) -> str:
    return json.dumps(s)


class RackPaletteUi(UiCase):
    def ids(self, pg, sec="results"):
        return pg.js("Array.prototype.map.call(document.querySelectorAll('.rpal-row[data-sec=%s]'), function (r) { return r.dataset.id; })" % sec)

    def row(self, sec, rid):
        return ".rpal-row[data-sec=%s][data-id=%s]" % (sec, q(rid))

    def type(self, pg, text):
        pg.js("""(function (t) { var i = document.querySelector('.rpal-search'); i.focus(); i.value = t;
          i.dispatchEvent(new Event('input', {bubbles: true})); })(%s)""" % q(text))

    def open_ready(self, size, query=""):
        pg = self.open(HARNESS + query, size)
        return pg

    def test_search_categories_and_layout(self) -> None:
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(HARNESS, size) as pg:
                self.assertEqual(pg.smoke.get("errors"), [], pg.smoke)
                self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll")
                ids = self.ids(pg)
                self.assertEqual(len(ids), RACKABLE, ids)
                self.assertNotIn("shure-blx88", ids, "templates without ru are not rack gear")
                self.assertEqual(ids[0], "sanctuary-atem", "project templates first")
                self.assertEqual(pg.js("document.querySelector('.rpal-sec[data-sec=results] .rpal-count').textContent"), str(RACKABLE))
                self.assertEqual(pg.js("document.querySelector(%s).textContent" % q(self.row("results", "apc-smt1500rmi2uc") + " .rpal-ru")), "2U")
                # Search narrows and ranks.
                self.type(pg, "rio")
                self.assertEqual(self.ids(pg), ["yamaha-rio3224-d2"])
                self.type(pg, "netgeer")
                self.assertEqual(self.ids(pg), ["netgear-gs724t"], "fuzzy edit distance 1")
                self.type(pg, "power")
                got = self.ids(pg)
                self.assertEqual(got[:2], ["generic-pdu", "generic-ups"], got)
                self.assertIn("dell-poweredge-r640", got)
                self.type(pg, "zzzz")
                self.assertEqual(self.ids(pg), [])
                self.assertIn("No matches for", pg.js("document.querySelector('.rpal-body .fb-empty-title').textContent"))
                self.type(pg, "")
                # Category chips.
                pg.click(".rpal-chip[data-cat=power]")
                self.assertEqual(pg.js("document.querySelector('.rpal-chip[data-cat=power]').getAttribute('aria-pressed')"), "true")
                cats = pg.js("Array.prototype.map.call(document.querySelectorAll('.rpal-row'), function (r) { return r.dataset.category; })")
                self.assertEqual(set(cats), {"power"})
                self.assertEqual(len(cats), 3)
                self.type(pg, "gs724")
                self.assertIn("in Power", pg.js("document.querySelector('.rpal-body .fb-empty-title').textContent"))
                pg.click(".rpal-body .fb-empty-action")
                self.assertEqual(self.ids(pg), ["netgear-gs724t"], "Search all categories")
                self.assertEqual(pg.js("document.querySelector('.rpal-chip[data-cat=all]').getAttribute('aria-pressed')"), "true")
                self.type(pg, "")
                # A missing catalog image degrades to the category swatch.
                pg.wait_for("""(function () { var t = document.querySelector(%s);
                  var img = t.querySelector('img'); return !img || (img.complete && img.naturalWidth > 0); })()"""
                            % q(self.row("results", "generic-1u-server") + " .rpal-thumb"))
                self.assertTrue(pg.js("!!document.querySelector(%s)" % q(self.row("results", "church-patch-24") + " .rpal-swatch")), "no image: swatch")
                floor = 44 if size == "m" else 28
                for sel in (".rpal-row", ".rpal-row .rpal-add", ".rpal-row .rpal-star", ".rpal-chip", ".rpal-search"):
                    self.assertGreaterEqual(round(pg.rect(sel)["height"]), floor, "%s at %s" % (sel, size))
                self.assertEqual(pg.offscreen(".rpal-row .rpal-add, .rpal-row .rpal-star, .rpal-search", "x"), 0)
                pg.shot("rack-palette-" + size)

    def test_star_persists_across_reload(self) -> None:
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(HARNESS, size) as pg:
                star = self.row("results", "netgear-gs724t") + " .rpal-star"
                self.assertEqual(pg.js("document.querySelector(%s).getAttribute('aria-pressed')" % q(star)), "false")
                pg.click(star)
                self.assertEqual(pg.js("document.querySelector(%s).getAttribute('aria-pressed')" % q(star)), "true")
                self.assertEqual(self.ids(pg, "favs"), ["netgear-gs724t"])
                stored = json.loads(pg.js("localStorage.getItem('fathom.ui.rack.palette')"))
                self.assertEqual(stored, {"v": 1, "favs": ["netgear-gs724t"], "recents": []})
                pg.reload()
                pg.wait_for("document.querySelectorAll('.rpal-row').length > 0")
                self.assertEqual(self.ids(pg, "favs"), ["netgear-gs724t"], "favourite survives a reload")
                self.assertEqual(pg.js("document.querySelector(%s).getAttribute('aria-pressed')" % q(self.row("favs", "netgear-gs724t") + " .rpal-star")), "true")
                pg.click(self.row("favs", "netgear-gs724t") + " .rpal-star")
                self.assertEqual(self.ids(pg, "favs"), [])
                self.assertEqual(json.loads(pg.js("localStorage.getItem('fathom.ui.rack.palette')"))["favs"], [])

    def test_add_calls_on_pick(self) -> None:
        for size in ("d", "m"):
            with self.subTest(size=size), self.open(HARNESS, size) as pg:
                pg.click(self.row("results", "yamaha-rio3224-d2") + " .rpal-add")
                pg.wait_for("window.__rpal.picks.length === 1")
                pick = pg.js("window.__rpal.picks[0]")
                self.assertEqual(pick, {"id": "yamaha-rio3224-d2", "template": "yamaha-rio3224-d2", "ports": 4, "device": "rio3224-d2", "devicePorts": 54})
                self.assertEqual(pg.js("window.__rpal.templateCalls"), [["yamaha-rio3224-d2", "harness"]], "summary has no ports: fetched")
                self.assertEqual(pg.js("window.__rpal.libraryCalls"), [{"source": "all", "rack": 1, "project": "harness"}])
                self.assertEqual(self.ids(pg, "recent"), ["yamaha-rio3224-d2"])
                pg.click(self.row("recent", "yamaha-rio3224-d2") + " .rpal-add")
                pg.wait_for("window.__rpal.picks.length === 2")
                self.assertEqual(pg.js("window.__rpal.picks[1].device"), "rio3224-d2-2", "ids dedupe against the doc")
                self.assertEqual(len(pg.js("window.__rpal.templateCalls")), 1, "template cached")
                pg.click(self.row("results", "generic-ups") + " .rpal-add")
                pg.wait_for("window.__rpal.picks.length === 3")
                self.assertEqual(pg.js("window.__rpal.picks[2]"), {"id": "generic-ups", "template": "generic-ups", "ports": 3, "device": "ups", "devicePorts": 8})
                self.assertEqual(len(pg.js("window.__rpal.templateCalls")), 1, "presets carry their ports")
                self.assertEqual(self.ids(pg, "recent"), ["generic-ups", "yamaha-rio3224-d2"])
                self.assertEqual(json.loads(pg.js("localStorage.getItem('fathom.ui.rack.palette')"))["recents"], ["generic-ups", "yamaha-rio3224-d2"])

    def test_keyboard(self) -> None:
        with self.open(HARNESS, "d") as pg:
            self.type(pg, "gs724")
            pg.press("ArrowDown")
            self.assertEqual(pg.js("document.activeElement.dataset.id"), "netgear-gs724t")
            pg.press("f")
            self.assertEqual(pg.js("document.querySelector(%s).getAttribute('aria-pressed')" % q(self.row("results", "netgear-gs724t") + " .rpal-star")), "true")
            self.assertEqual(pg.js("document.activeElement.dataset.id"), "netgear-gs724t", "focus kept after the re-render")
            pg.press("Enter")
            pg.wait_for("window.__rpal.picks.length === 1")
            self.assertEqual(pg.js("window.__rpal.picks[0].devicePorts"), 26)
            pg.press("ArrowUp")
            self.assertTrue(pg.js("document.activeElement.classList.contains('rpal-search')"))
            self.type(pg, "")
            pg.press("ArrowDown")
            first = pg.js("document.activeElement.dataset.id + '/' + document.activeElement.dataset.sec")
            self.assertEqual(first, "netgear-gs724t/favs")
            pg.press("ArrowDown")
            self.assertEqual(pg.js("document.activeElement.dataset.sec"), "recent")
            pg.press("End")
            self.assertEqual(pg.js("document.activeElement.dataset.id"), self.ids(pg)[-1])
            pg.press("Home")
            self.assertEqual(pg.js("document.activeElement.dataset.sec"), "favs")
            pg.js("document.querySelector('.rpal-search').focus()")
            self.type(pg, "rio")
            pg.press("Escape")
            self.assertEqual(pg.js("document.querySelector('.rpal-search').value"), "")
            self.assertEqual(len(self.ids(pg)), RACKABLE)

    def test_drag_calls_on_drag_start(self) -> None:
        with self.open(HARNESS, "d") as pg:
            r = pg.rect(self.row("results", "apc-smt1500rmi2uc") + " .rpal-name")
            x, y = r["left"] + 10, r["top"] + r["height"] / 2
            pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            pg.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1})
            pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x + 2, "y": y + 1, "buttons": 1})
            self.assertEqual(pg.js("window.__rpal.drags.length"), 0, "no drag below the threshold")
            pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x + 40, "y": y + 12, "buttons": 1})
            pg.wait_for("window.__rpal.drags.length === 1")
            self.assertEqual(pg.js("window.__rpal.drags[0]"), {"id": "apc-smt1500rmi2uc", "type": "pointermove", "pointerType": "mouse"})
            self.assertTrue(pg.js("!!document.querySelector('.rpal-row.rpal-dragging')"))
            pg.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x + 40, "y": y + 12, "button": "left", "buttons": 0, "clickCount": 1})
            pg.wait_for("!document.querySelector('.rpal-row.rpal-dragging')")
            self.assertEqual(pg.js("window.__rpal.picks.length"), 0, "a drag is not a pick")
        with self.open(HARNESS, "m") as pg:
            pg.js("document.querySelector(%s).scrollIntoView({block: 'center'})" % q(self.row("results", "netgear-gs724t")))
            r = pg.rect(self.row("results", "netgear-gs724t") + " .rpal-name")
            x, y = r["left"] + 10, r["top"] + r["height"] / 2
            pg.command("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
            time.sleep(0.6)
            pg.wait_for("window.__rpal.drags.length === 1")
            self.assertEqual(pg.js("window.__rpal.drags[0]"), {"id": "netgear-gs724t", "type": "pointerdown", "pointerType": "touch"})
            pg.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            # A quick tap is not a drag.
            pg.command("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
            pg.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            time.sleep(0.5)
            self.assertEqual(pg.js("window.__rpal.drags.length"), 1)

    def test_states(self) -> None:
        with self.open(HARNESS + "?api=0", "m") as pg:
            self.assertEqual(pg.smoke.get("errors"), [])
            self.assertEqual(sorted(self.ids(pg)), ["generic-pdu", "generic-switch-24", "generic-ups"], "no API: presets only")
            pg.click(self.row("results", "generic-pdu") + " .rpal-add")
            pg.wait_for("window.__rpal.picks.length === 1")
            self.assertEqual(pg.js("window.__rpal.picks[0].devicePorts"), 9)
        with self.open(HARNESS + "?fail=1", "d") as pg:
            self.assertEqual(pg.js("document.querySelector('.rpal-body .fb-error').getAttribute('role')"), "alert")
            self.assertIn("Library unavailable", pg.js("document.querySelector('.rpal-body .fb-error-msg').textContent"))
            pg.click(".rpal-body .fb-retry")
            pg.wait_for("document.querySelectorAll('.rpal-row').length === %d" % RACKABLE)
        with self.open(HARNESS + "?many=450", "d") as pg:
            self.assertEqual(len(self.ids(pg)), 200)
            pg.click(".rpal-more")
            self.assertEqual(len(self.ids(pg)), 400)
            pg.click(".rpal-more")
            self.assertEqual(len(self.ids(pg)), RACKABLE + 450)
            self.assertIsNone(pg.rect(".rpal-more"))

    def test_real_api_catalog(self) -> None:
        for size, (w, hgt) in (("d", (1440, 900)), ("m", (390, 844))):
            with self.subTest(size=size), self.open(HARNESS + "?api=real&project=campus-demo", size) as pg:
                self.assertEqual(pg.smoke.get("errors"), [], pg.smoke)
                if size == "d":
                    pg.command("Emulation.setDeviceMetricsOverride", {"width": w, "height": hgt, "deviceScaleFactor": 1, "mobile": False})
                    pg.wait_for("window.innerWidth === %d" % w)
                self.assertEqual(pg.js("window.__rpal.libraryCalls"), [{"source": "all", "rack": 1, "project": "campus-demo"}])
                total = int(pg.js("document.querySelector('.rpal-sec[data-sec=results] .rpal-count').textContent"))
                self.assertGreaterEqual(total, 600, "catalog tier is listed")
                self.assertEqual(len(self.ids(pg)), 200, "capped at 200")
                self.assertTrue(pg.js("!!document.querySelector('.rpal-row[data-source=catalog]')"))
                # Catalog twins (same maker + model) are one row each.
                pg.click(".rpal-chip[data-cat=all]")
                twins = pg.js("""(function () {
                  var seen = {}, dup = [];
                  Array.prototype.forEach.call(document.querySelectorAll('.rpal-row[data-sec=results][data-source=catalog]'), function (r) {
                    var k = (r.getAttribute('aria-label') || '').toLowerCase(); if (seen[k]) dup.push(k); seen[k] = 1; });
                  return dup; })()""")
                self.assertEqual(twins, [])
                self.type(pg, "smt1500")
                self.assertEqual(len([i for i in self.ids(pg) if i in ("apc-smt1500rmi2uc", "smt1500rmi2uc")]), 1)
                self.type(pg, "")
                # Thumbnails come from /static/rack-images and decode.
                pg.click(".rpal-chip[data-cat=server]")
                pg.wait_for("""Array.prototype.some.call(document.querySelectorAll('.rpal-row img.rpal-img'),
                  function (i) { return i.complete && i.naturalWidth > 0; })""")
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("rack-palette-catalog-%dx%d" % (w, hgt))

    def test_screenshots(self) -> None:
        for size, (w, hgt) in (("d", (1440, 900)), ("m", (390, 844))):
            with self.subTest(size=size), self.open(HARNESS, size) as pg:
                if size == "d":
                    pg.command("Emulation.setDeviceMetricsOverride", {"width": w, "height": hgt, "deviceScaleFactor": 1, "mobile": False})
                    pg.wait_for("window.innerWidth === %d" % w)
                pg.click(self.row("results", "netgear-gs724t") + " .rpal-star")
                pg.click(self.row("results", "yamaha-rio3224-d2") + " .rpal-add")
                pg.wait_for("window.__rpal.picks.length === 1")
                self.assertLessEqual(pg.page_hscroll(), 0)
                pg.shot("rack-palette-%dx%d" % (w, hgt))
                self.type(pg, "power")
                pg.shot("rack-palette-%dx%d-search" % (w, hgt))


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
