"""SEARCH palette in headless Chrome via the dev harness (docs/ui-audit.md B.2 SEARCH).

Drives ``/static/dev/search.html`` (``fathom/static/dev/search-harness.js``), which mounts
``js/search.js`` with a fake ctx and records ``ctx.navigateRoute`` calls in ``window.__sr``.
Online cases search the real ``campus-demo`` endpoint; ``?fixture=1`` is the offline path.
Skips without Chrome (set ``FATHOM_CHROME``).
"""
from __future__ import annotations

import json
import unittest

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

HARNESS = "/static/dev/search.html"
CAMPUS = HARNESS + "?project=campus-demo"
CATEGORY_LABELS = ["Devices", "Inventory", "Rooms", "Racks", "Ports", "Cables", "Networks", "Plans", "Procedures", "Files"]


def typed(pg, text):
    for ch in text:
        pg.press(ch)


def clear(pg):
    pg.js("(function () { var i = document.getElementById('app-palette-input'); i.value = '';"
          " i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()")


def options(pg):
    return pg.js("Array.prototype.map.call(document.querySelectorAll('#app-palette-list [role=option]'),"
                 " function (li) { return [li.getAttribute('data-hit-kind'), li.getAttribute('data-hit-id')]; })")


def groups(pg):
    return pg.js("Array.prototype.map.call(document.querySelectorAll('#app-palette-list .sr-group'), function (g) { return g.textContent; })")


def wait_options(pg, first_id=None):
    if first_id:
        pg.wait_for("(function () { var o = document.querySelector('#app-palette-list [role=option]');"
                    " return !!o && o.getAttribute('data-hit-id') === %s; })()" % json.dumps(first_id))
    else:
        pg.wait_for("!!document.querySelector('#app-palette-list [role=option]')")


def active_id(pg):
    return pg.js("document.getElementById('app-palette-input').getAttribute('aria-activedescendant')")


def wait_active(pg, kind, hit_id):
    pg.wait_for("(function () { var i = document.getElementById('app-palette-input'), id = i && i.getAttribute('aria-activedescendant'),"
                " o = id && document.getElementById(id);"
                " return !!o && o.getAttribute('data-hit-kind') === %s && o.getAttribute('data-hit-id') === %s; })()"
                % (json.dumps(kind), json.dumps(hit_id)))


def wait_settled(pg):
    """The palette is open and its last search finished (results or the no-match line)."""
    pg.wait_for("(function () { var p = document.getElementById('app-palette'); return !!p && !p.hasAttribute('aria-busy')"
                " && !!p.querySelector('.sr-only').textContent; })()")


def last_nav(pg, count):
    pg.wait_for("window.__sr.navigations.length >= %d" % count)
    return pg.js("window.__sr.navigations[%d].hash" % (count - 1))


def palette_open(pg):
    return pg.js("!!document.getElementById('app-palette')")


class SearchUi(UiCase):
    def open_palette(self, pg):
        pg.click("#app-search")
        pg.wait_for("document.activeElement && document.activeElement.id === 'app-palette-input'")

    def test_desktop_dropdown_keyboard_and_recents(self):
        with self.open(CAMPUS, "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self.assertTrue(pg.smoke["ready"])
            self.open_palette(pg)
            attrs = pg.js("(function () { var p = document.getElementById('app-palette'), i = document.getElementById('app-palette-input');"
                          " return [p.getAttribute('role'), p.getAttribute('aria-label'), p.getAttribute('data-layout'), p.hasAttribute('aria-modal'),"
                          " i.getAttribute('role'), i.getAttribute('aria-controls'), document.getElementById('app-palette-list').getAttribute('role'),"
                          " !!document.getElementById('app-search-cat')]; })()")
            self.assertEqual(attrs, ["dialog", "Search", "lg", False, "combobox", "app-palette-list", "listbox", True])
            anchor, box = pg.rect("#app-search"), pg.rect("#app-palette")
            self.assertGreaterEqual(box["top"], anchor["bottom"], "dropdown sits under #app-search")
            self.assertLessEqual(box["width"], 640)
            self.assertLess(abs((box["left"] + box["width"] / 2) - (anchor["left"] + anchor["width"] / 2)), 2, "centred on the field")
            self.assertIn("Go to", groups(pg))
            self.assertEqual(len([o for o in options(pg) if o[0] == "section"]), 8, "Go to lists the 8 sections")

            typed(pg, "foh")
            wait_options(pg, "foh-cl5")
            self.assertEqual(options(pg)[0], ["device", "foh-cl5"])
            labels = groups(pg)
            self.assertEqual(labels, [x for x in CATEGORY_LABELS if x in labels], "groups follow CATEGORIES order")
            self.assertEqual(pg.js("document.getElementById('app-palette-input').getAttribute('aria-expanded')"), "true")
            self.assertEqual(active_id(pg), "sr-hit-0")
            for k in ("ArrowDown", "ArrowDown", "ArrowUp"):
                pg.press(k)
            self.assertEqual(active_id(pg), "sr-hit-1")
            self.assertEqual(pg.js("document.getElementById('sr-hit-1').getAttribute('aria-selected')"), "true")
            pg.press("ArrowUp")
            pg.press("ArrowUp")
            n = len(options(pg))
            self.assertEqual(active_id(pg), "sr-hit-%d" % (n - 1), "ArrowUp from the first option wraps to the last")
            pg.press("ArrowDown")
            self.assertEqual(active_id(pg), "sr-hit-0")
            pg.shot("search-d")
            pg.press("Enter")
            self.assertEqual(last_nav(pg, 1), "#/campus-demo/main/devices/foh-cl5")
            self.assertFalse(palette_open(pg))
            self.assertEqual(pg.js("window.__sr.recents"), ["device:foh-cl5"])

            pg.press("Control+k")
            pg.wait_for("!!document.getElementById('app-palette')")
            self.assertEqual(groups(pg)[0], "Recent")
            self.assertEqual(options(pg)[0], ["device", "foh-cl5"])
            self.assertIsNone(active_id(pg), "nothing is active before the user moves")
            pg.press("Escape")
            pg.wait_for("!document.getElementById('app-palette')")
            self.assertEqual(pg.js("document.activeElement.id"), "app-search", "Esc returns focus to #app-search")

    def test_category_select_and_no_results(self):
        with self.open(CAMPUS, "d") as pg:
            self.open_palette(pg)
            typed(pg, "chapel")
            wait_active(pg, "room", "chapel")
            self.assertEqual(groups(pg)[:2], ["Devices", "Rooms"], "groups keep CATEGORIES order")
            self.assertEqual(options(pg)[0][0], "device")
            pg.press("Tab")
            self.assertEqual(pg.js("document.activeElement.id"), "app-search-cat", "Tab moves to the category select")
            pg.js("(function () { var s = document.getElementById('app-search-cat'); s.value = 'cables';"
                  " s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()")
            pg.wait_for("!document.querySelector('.sr-empty').hidden")
            self.assertEqual(pg.js("document.querySelector('.sr-empty p').textContent"), u"No matches for \u201cchapel\u201d in Cables.")
            self.assertEqual(options(pg), [])
            self.assertEqual(pg.js("document.getElementById('app-palette-input').getAttribute('aria-expanded')"), "false")
            pg.click("button.sr-all")
            wait_active(pg, "room", "chapel")
            self.assertEqual(pg.js("document.getElementById('app-search-cat').value"), "all")
            self.assertEqual(pg.js("document.activeElement.id"), "app-palette-input")
            pg.press("Enter")
            self.assertEqual(last_nav(pg, 1), "#/campus-demo/chapel/rooms/chapel", "Enter opens the best match, not the first row")
            self.open_palette(pg)

            clear(pg)
            pg.js("(function () { var s = document.getElementById('app-search-cat'); s.value = 'cables';"
                  " s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()")
            pg.click("#app-palette-input")
            typed(pg, "A-00")
            wait_options(pg)
            kinds = set(o[0] for o in options(pg))
            self.assertEqual(kinds, {"cable"}, "the Cables category only lists cables")
            self.assertEqual(groups(pg), ["Cables"])
            self.assertGreater(len(options(pg)), 6, "the 6-per-group cap applies only to All")

    def test_viewer_does_not_see_draft_procedures(self):
        url = CAMPUS + "&q=chapel&cat=procedures"
        with self.open(url, "d") as pg:
            wait_options(pg)
            self.assertIn(["page", "chapel-pre-service"], options(pg))
        with self.open(url + "&role=viewer", "d") as pg:
            wait_settled(pg)
            self.assertNotIn(["page", "chapel-pre-service"], options(pg))
            self.assertEqual(pg.js("document.querySelector('.sr-empty p').textContent"), u"No matches for \u201cchapel\u201d in Procedures.")

    def test_offline_fixture_and_inventory_target(self):
        with self.open(HARNESS + "?fixture=1", "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self.open_palette(pg)
            typed(pg, "atem")
            wait_options(pg, "atem-mini")
            self.assertEqual(options(pg)[0], ["device", "atem-mini"])
            self.assertEqual(pg.js("document.querySelector('.sr-foot').getAttribute('data-offline')"), "1")
            clear(pg)
            typed(pg, "SQ5-004211")
            wait_options(pg, "sound-board")
            self.assertEqual(groups(pg)[0], "Inventory")
            pg.press("Enter")
            self.assertEqual(last_nav(pg, 1), "#/sunday-demo/main/inventory?sel=device:sound-board&sec=inventory")

    # FR-SRCH short codes: a query shaped like XXXX-XXXX also asks /api/v2/codes/<code>; a 200 leads the
    # results with the device (deduped against the text hits); a 404 or offline adds nothing.
    def test_short_code_query_leads_with_the_device(self):
        body = {"project": "campus-demo", "device": "foh-cl5", "name": "FOH CL5", "room": "main", "kind": "console"}
        with self.open(CAMPUS, "d", intercepts=[("/api/v2/codes/ABCD2345*", 200, body, "GET"), ("/api/v2/codes/ZZZZ9999*", 404, {"error": "unknown code"}, "GET")]) as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self.open_palette(pg)
            typed(pg, "abcd-2345")
            wait_options(pg, "foh-cl5")
            self.assertEqual(options(pg)[0], ["device", "foh-cl5"])
            self.assertEqual(len([o for o in options(pg) if o == ["device", "foh-cl5"]]), 1, "the code hit is deduped by id")
            self.assertEqual(groups(pg)[0], "Devices")
            self.assertEqual(pg.js("document.getElementById('sr-hit-0').querySelector('.sr-sub').textContent"), "Code ABCD-2345 \u00b7 Main Auditorium")
            self.assertEqual(pg.js("document.getElementById('sr-hit-0').querySelector('.sr-title').textContent"), "FOH CL5")
            pg.shot("search-code-d")
            pg.press("Enter")
            self.assertEqual(last_nav(pg, 1), "#/campus-demo/main/devices/foh-cl5")

            # an unknown code adds nothing (the text search runs as usual)
            self.open_palette(pg)
            typed(pg, "ZZZZ-9999")
            wait_settled(pg)
            self.assertEqual([o for o in options(pg) if o[0] == "device"], [])
            self.assertEqual(pg.js("document.querySelectorAll('#app-palette-list .sr-hit').length"), 0)

    def test_short_code_offline_uses_the_document(self):
        with self.open(HARNESS + "?fixture=1", "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            pg.js("(function () { var d = window.__sr.ctx.store.doc.devices.filter(function (x) { return x.id === 'atem-mini'; })[0]; d.short_code = 'ATEM2345'; return 1; })()")
            self.open_palette(pg)
            typed(pg, "atem2345")
            wait_options(pg, "atem-mini")
            self.assertEqual(options(pg)[0], ["device", "atem-mini"])
            self.assertTrue(pg.js("document.getElementById('sr-hit-0').querySelector('.sr-sub').textContent").startswith("Code ATEM-2345"))
            self.assertEqual(pg.js("document.querySelector('.sr-foot').getAttribute('data-offline')"), "1")

    def test_tablet_dropdown_network_hit(self):
        with self.open(CAMPUS, "t") as pg:
            self.open_palette(pg)
            self.assertEqual(pg.js("document.getElementById('app-palette').getAttribute('data-layout')"), "md")
            anchor, box = pg.rect("#app-search"), pg.rect("#app-palette")
            self.assertGreaterEqual(box["top"], anchor["bottom"])
            self.assertEqual(round(box["width"]), 640)
            typed(pg, "Dante primary")
            pg.wait_for("!!document.querySelector('[role=option][data-hit-kind=network][data-hit-id=av-dante]')")
            self.assertIn("Networks", groups(pg))
            self.assertLessEqual(pg.page_hscroll(), 0)
            pg.shot("search-t")
            pg.click("[role=option][data-hit-kind=network][data-hit-id=av-dante]")
            self.assertEqual(last_nav(pg, 1), "#/campus-demo/main/settings/networks?hl=av-dante")
            self.assertFalse(palette_open(pg))

    def test_phone_full_screen(self):
        with self.open(CAMPUS, "m") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self.open_palette(pg)
            self.assertEqual(pg.js("document.getElementById('app-palette').getAttribute('data-layout')"), "sm")
            self.assertEqual(pg.js("document.getElementById('app-palette').getAttribute('aria-modal')"), "true")
            box = pg.rect("#app-palette")
            self.assertEqual([round(box[k]) for k in ("left", "top", "width", "height")], [0, 0, 390, 844], "full screen at sm")
            typed(pg, "foh")
            wait_options(pg, "foh-cl5")
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.assertEqual(pg.offscreen("#app-palette .sr-bar > *", "x"), 0)
            self.assertEqual(pg.offscreen("#app-palette .sr-hit", "x"), 0)
            heights = pg.js("Array.prototype.map.call(document.querySelectorAll('#app-palette .sr-hit, #app-palette .sr-back, #app-search-cat'),"
                            " function (el) { return el.getBoundingClientRect().height; })")
            self.assertTrue(heights and min(heights) >= 44, "44px touch targets, got %r" % heights)
            pg.shot("search-m")
            pg.click("#sr-hit-0")
            self.assertEqual(last_nav(pg, 1), "#/campus-demo/main/devices/foh-cl5")
            self.assertFalse(palette_open(pg))
            self.open_palette(pg)
            pg.click("#app-palette .sr-back")
            pg.wait_for("!document.getElementById('app-palette')")
            self.assertEqual(pg.js("document.activeElement.id"), "app-search")


if __name__ == "__main__":
    unittest.main()
