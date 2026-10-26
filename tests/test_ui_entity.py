"""ENTITY (docs/ui-audit.md B.2 ENTITY, D5): entity header in the dev harness ``/static/dev/entity.html``.

Sticky + compact after scrolling 2000px, compact at m, tabs are real links (click and keyboard), the ⋯ menu
opens from the keyboard and closes on Esc, unknown tab / id handling (D5), targets at m and no page horizontal
scroll at d, t and m. Skips without Chrome (set ``FATHOM_CHROME``); ``$FATHOM_UI_SHOTS`` collects screenshots.
"""
from __future__ import annotations

import json

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

HARNESS = "/static/dev/entity.html"

HEADER_STATE = """(function () {
  var eh = document.querySelector('header.eh'), sc = document.getElementById('h-scroll');
  if (!eh) return null;
  var r = eh.getBoundingClientRect(), s = sc.getBoundingClientRect();
  var hit = document.elementFromPoint(r.left + r.width / 2, r.top + Math.min(20, r.height / 2));
  return {top: r.top, bottom: r.bottom, height: r.height, scTop: s.top, scrollTop: sc.scrollTop,
          compact: eh.classList.contains('eh--compact'), stuck: eh.classList.contains('eh--stuck'),
          onTop: !!hit && eh.contains(hit), layout: eh.getAttribute('data-layout'),
          body: (function () { var b = eh.querySelector('.eh-body'); return b ? getComputedStyle(b).display : null; })(),
          actions: Array.prototype.map.call(eh.querySelectorAll('.eh-actions > .eh-action'), function (a) { return a.getAttribute('data-action'); }),
          menu: Array.prototype.map.call(eh.querySelectorAll('.eh-menu .eh-menu-item'), function (a) { return a.getAttribute('data-action'); })};
})()"""

# Visible interactive controls in the header and their smallest side.
TARGETS = """(function () {
  var out = [];
  document.querySelectorAll('header.eh a, header.eh button, header.eh summary').forEach(function (el) {
    var r = el.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(el).visibility === 'hidden') return;
    out.push({el: el.className || el.tagName, text: el.textContent.trim().slice(0, 20), w: Math.round(r.width), h: Math.round(r.height)});
  });
  return out;
})()"""


class EntityHeaderUi(UiCase):
    def harness(self, frag: str, size: str = "d"):
        return self.open(HARNESS + "#" + frag, size)

    def ready(self, pg, frag: str) -> None:
        self.assertEqual(pg.smoke["errors"], [], "harness errors on %s" % frag)
        pg.wait_for("!!document.querySelector('header.eh .eh-title')")

    def state(self, pg):
        return pg.js(HEADER_STATE)

    def scroll(self, pg, y: int) -> None:
        pg.js("document.getElementById('h-scroll').scrollTop = %d" % y)
        pg.wait_for("document.getElementById('h-scroll').scrollTop >= %d" % min(y, 1) if y else "document.getElementById('h-scroll').scrollTop === 0")

    def test_sticky_and_compact_after_scroll_at_d(self):
        with self.harness("/device/atem-mini/ports") as pg:
            self.ready(pg, "ports")
            st = self.state(pg)
            self.assertEqual(st["layout"], "lg")
            self.assertFalse(st["compact"], "B.2 ENTITY: full header before scrolling at lg")
            self.assertEqual(st["actions"], ["edit", "patch", "trace", "public"])
            self.assertEqual(st["menu"], ["duplicate", "merge", "qr", "delete"])
            self.assertEqual(pg.js("document.querySelector('header.eh').getAttribute('data-entity') + ':' + "
                                   "document.querySelector('header.eh').getAttribute('data-id')"), "device:atem-mini")
            self.assertEqual(pg.js("document.querySelector('.eh-fact[data-fact=ports] dd').textContent"), "5 (4 patched)")

            self.scroll(pg, 2000)
            pg.wait_for("document.querySelector('header.eh').classList.contains('eh--compact')")
            st = self.state(pg)
            self.assertGreaterEqual(st["scrollTop"], 1500)
            self.assertAlmostEqual(st["top"], st["scTop"], delta=1, msg="B.2 ENTITY: header sticks to the top of the scroller")
            self.assertTrue(st["onTop"], "the stuck header is painted above the content")
            self.assertEqual(st["body"], "none", "compact at lg hides facts and thumbnail")
            self.assertEqual(st["actions"], ["edit"], "compact keeps only the primary action as a button")
            self.assertEqual(st["menu"][:3], ["patch", "trace", "public"], "the other actions move into the ⋯ menu")
            self.assertEqual(st["menu"][-1], "delete")
            self.assertTrue(pg.js("!!document.querySelector('.eh-tab[aria-selected=true][data-tab=ports]')"), "tabs stay in the compact header")
            pg.shot("entity-device-stuck-d")

            self.scroll(pg, 0)
            pg.wait_for("!document.querySelector('header.eh').classList.contains('eh--compact')")
            self.assertEqual(self.state(pg)["actions"], ["edit", "patch", "trace", "public"])

    def test_tab_click_changes_hash(self):
        for size in ("d", "t"):
            with self.harness("/device/atem-mini", size) as pg:
                self.ready(pg, "device")
                self.assertTrue(pg.hash.endswith("/device/atem-mini/overview"), "D5: missing tab replaced with overview (%s)" % pg.hash)
                pg.click(".eh-tab[data-tab=cables]")
                pg.wait_for("location.hash === '#/device/atem-mini/cables'")
                pg.wait_for("document.getElementById('h-panel').getAttribute('data-tab') === 'cables'")
                self.assertEqual(pg.js("document.querySelector('.eh-tab[aria-selected=true]').getAttribute('data-tab')"), "cables")
                self.assertEqual(pg.js("document.querySelectorAll('.eh-tab[tabindex=\"0\"]').length"), 1, "roving tabindex")
                self.assertIn("tab:cables", pg.js("window.__eh.log"))
                pg.js("history.back()")
                pg.wait_for("location.hash === '#/device/atem-mini/overview'")
                pg.wait_for("document.querySelector('.eh-tab[aria-selected=true]').getAttribute('data-tab') === 'overview'")

    def test_arrow_keys_move_between_tabs(self):
        with self.harness("/device/atem-mini/ports") as pg:
            self.ready(pg, "ports")
            pg.js("document.querySelector('.eh-tab[data-tab=ports]').focus()")
            pg.press("ArrowRight")
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-tab')"), "cables")
            self.assertEqual(pg.hash, "#/device/atem-mini/ports", "arrow keys move focus only")
            pg.press("End")
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-tab')"), "files")
            pg.press("ArrowRight")
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-tab')"), "overview", "wraps around")
            pg.press("ArrowLeft")
            pg.press("Enter")
            pg.wait_for("location.hash === '#/device/atem-mini/files'")

    def test_overflow_menu_keyboard_and_escape(self):
        with self.harness("/device/atem-mini") as pg:
            self.ready(pg, "device")
            self.assertEqual(pg.js("document.querySelector('.eh-more').getAttribute('aria-haspopup')"), "menu")
            pg.js("document.querySelector('.eh-more').focus()")
            pg.press("Enter")
            pg.wait_for("!document.querySelector('.eh-menu').hidden")
            self.assertEqual(pg.js("document.querySelector('.eh-more').getAttribute('aria-expanded')"), "true")
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-action')"), "duplicate", "focus moves to the first item")
            self.assertEqual(pg.js("document.querySelector('.eh-menu').getAttribute('role')"), "menu")
            pg.press("ArrowDown")
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-action')"), "merge")
            pg.press("ArrowUp")
            pg.press("ArrowUp")
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-action')"), "delete", "ArrowUp wraps to the last item")
            pg.press("Escape")
            pg.wait_for("document.querySelector('.eh-menu').hidden")
            self.assertEqual(pg.js("document.activeElement.className"), "eh-more", "Esc returns focus to ⋯")
            self.assertEqual(pg.js("document.querySelector('.eh-more').getAttribute('aria-expanded')"), "false")

            pg.press("ArrowUp")
            pg.wait_for("!document.querySelector('.eh-menu').hidden")
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-action')"), "delete")
            self.assertTrue(pg.js("document.activeElement.classList.contains('danger')"))
            pg.press("Enter")
            pg.wait_for("window.__eh.log.indexOf('action:delete') >= 0")
            self.assertTrue(pg.js("document.querySelector('.eh-menu').hidden"), "running an item closes the menu")

            pg.click(".eh-more")
            pg.wait_for("!document.querySelector('.eh-menu').hidden")
            pg.click("#h-panel .h-card[data-card=cables]")
            pg.wait_for("document.querySelector('.eh-menu').hidden")

    def test_compact_at_m_targets_and_scroll(self):
        with self.harness("/device/atem-mini/overview", "m") as pg:
            self.ready(pg, "m")
            st = self.state(pg)
            self.assertEqual(st["layout"], "sm")
            self.assertTrue(st["compact"], "B.2 ENTITY: compact at sm without scrolling")
            self.assertEqual(st["actions"], [], "at sm every action, the primary too, is in the ⋯ menu")
            self.assertEqual(st["menu"][:4], ["edit", "patch", "trace", "public"])
            self.assertTrue(pg.js("!!document.querySelector('header.eh details.eh-facts-more .eh-facts')"), "facts sit in details at sm")
            self.assertLessEqual(pg.page_hscroll(), 0)
            self.assertEqual(pg.offscreen("header.eh .eh-bar *", "x"), 0, "title row fits at 390")
            small = [t for t in pg.js(TARGETS) if min(t["w"], t["h"]) < 44]
            self.assertEqual(small, [], "targets >= 44px under pointer: coarse (>= 40px rule)")

            pg.click("details.eh-facts-more summary")
            pg.wait_for("document.querySelector('details.eh-facts-more').open")
            self.assertEqual(pg.js("document.querySelector('.eh-fact[data-fact=room] dd').textContent"), "Main Auditorium")
            small = [t for t in pg.js(TARGETS) if t["h"] < 44]
            self.assertEqual(small, [], "fact links are 44px tall too")
            pg.shot("entity-device-m")

            pg.click(".eh-tab[data-tab=files]")
            pg.wait_for("location.hash === '#/device/atem-mini/files'")
            pg.wait_for("(function () { var n = document.querySelector('.eh-tabs'), t = n.querySelector('[data-tab=files]');"
                        " return t.offsetLeft + t.offsetWidth <= n.scrollLeft + n.clientWidth + 1; })()")
            self.assertEqual(pg.offscreen(".eh-tab[aria-selected=true]", "x"), 0, "the active tab is scrolled into view in the strip")
            self.assertLessEqual(pg.page_hscroll(), 0)

            self.scroll(pg, 2000)
            pg.wait_for("document.querySelector('header.eh').classList.contains('eh--stuck')")
            st = self.state(pg)
            self.assertAlmostEqual(st["top"], st["scTop"], delta=1)
            self.assertTrue(st["onTop"])
            self.assertEqual(st["body"], "none", "facts fold away once stuck at sm")

    def test_unknown_tab_unknown_id_update_destroy(self):
        with self.harness("/device/atem-mini/bogus") as pg:
            self.ready(pg, "bogus")
            pg.wait_for("location.hash === '#/device/atem-mini/overview'")
            self.assertIn("redirect:bogus->overview", pg.js("window.__eh.log"))
            before = pg.js("history.length")
            pg.goto("#/device/atem-mini/dmx")
            pg.wait_for("location.hash === '#/device/atem-mini/overview'")
            self.assertEqual(pg.js("history.length"), before + 1, "D5: the unknown tab is replaced, not pushed")
            pg.goto("#/device/nope")
            pg.wait_for("!!document.querySelector('.h-error')")
            self.assertEqual(pg.js("document.querySelector('.h-error h2').textContent"), "Device \u201cnope\u201d not found")
            self.assertFalse(pg.js("!!document.querySelector('header.eh')"))

            pg.goto("#/rack/rk-foh/elevation")
            pg.wait_for("!!document.querySelector('header.eh[data-entity=rack]')")
            self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.eh-tab'), function (t) { return t.getAttribute('data-tab'); })"),
                             ["overview", "elevation", "devices", "cables"])
            facts = pg.js("Array.prototype.map.call(document.querySelectorAll('.eh-fact'), function (f) { return f.getAttribute('data-fact') + '=' + f.querySelector('dd').textContent; })")
            self.assertEqual(facts, ["room=Main Auditorium", "height=12 U", "used=1 U", "free=11 U", "devices=1", "location=FOH booth"])
            self.assertEqual(pg.js("document.querySelector('.eh-fact[data-fact=room] a').getAttribute('href')"), "#/room/main")
            pg.js("window.__eh.handle.update({title: 'Renamed rack', status: {label: 'Planned', level: 'warn'}})")
            self.assertEqual(pg.js("document.querySelector('.eh-title').textContent"), "Renamed rack")
            self.assertEqual(pg.js("document.querySelector('.eh-status').className"), "eh-status eh-warn")
            self.assertEqual(pg.js("document.querySelector('.eh-tab[aria-selected=true]').getAttribute('data-tab')"), "elevation", "update keeps the tab")
            pg.js("window.__eh.handle.destroy()")
            self.assertFalse(pg.js("!!document.querySelector('header.eh, .eh-sentinel')"))
            self.assertEqual(pg.js("JSON.stringify(window.__fathomErrors)"), "[]")

    def test_room_and_rack_at_three_widths(self):
        for size in ("d", "t", "m"):
            with self.harness("/room/main/devices", size) as pg:
                self.ready(pg, "room " + size)
                self.assertLessEqual(pg.page_hscroll(), 0, "no page horizontal scroll at %s" % size)
                self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.eh-tab'), function (t) { return t.getAttribute('data-tab'); })"),
                                 ["overview", "devices", "cables", "racks", "plans", "procedures"])
                self.assertEqual(pg.js("document.querySelector('.eh-fact[data-fact=venue] dd').textContent"), "Hillside Church")
                thumb = pg.rect(".eh-thumb")
                if size == "m":
                    self.assertEqual(thumb["width"], 0, "no thumbnail at sm")
                else:
                    self.assertGreater(thumb["width"], 0, "room thumbnail at %s" % size)
                    self.assertEqual(self.state(pg)["layout"], "md" if size == "t" else "lg")
                    self.assertAlmostEqual(pg.rect(".eh-fact[data-fact=devices] dd")["top"], pg.rect(".eh-fact[data-fact=venue] dd")["top"], delta=1,
                                           msg="linked and plain facts line up")
                if size == "t":
                    self.assertGreaterEqual(pg.rect(".eh-fact[data-fact=devices] a")["height"], 44, "fact links are 44px targets under pointer: coarse")
                pg.shot("entity-room-" + size)
            with self.harness("/rack/rk-foh", size) as pg:
                self.ready(pg, "rack " + size)
                self.assertLessEqual(pg.page_hscroll(), 0)
                self.assertEqual(pg.offscreen("header.eh .eh-bar button", "x"), 0)
                cards = pg.js("JSON.stringify(Array.prototype.map.call(document.querySelectorAll('.h-card'), function (c) { return c.getAttribute('data-card'); }))")
                self.assertEqual(json.loads(cards), ["height", "used", "free", "devices", "cables", "problems"])
                pg.shot("entity-rack-" + size)


TAB_LIST = """Array.prototype.map.call(document.querySelectorAll('header.eh .eh-tab'), function (a) {
  var c = a.querySelector('.eh-count');
  return {key: a.getAttribute('data-tab'), label: a.querySelector('.eh-tab-label').textContent, count: c ? c.textContent : null,
          href: a.getAttribute('href'), selected: a.getAttribute('aria-selected')};
})"""


class EntityHeaderPrimFixUi(UiCase):
    """Live tab updates and link-action styling added for the wave-2 view migrations (PRIM-FIX)."""

    harness = EntityHeaderUi.harness
    ready = EntityHeaderUi.ready

    def test_set_tabs_updates_in_place_and_keeps_focus(self):
        with self.harness("/device/atem-mini/ports") as pg:
            self.ready(pg, "ports")
            before = pg.js(TAB_LIST)
            keys = [t["key"] for t in before]
            self.assertIn("cables", keys)
            pg.js("window.__bar = document.querySelector('header.eh .eh-bar'); window.__cab = document.querySelector('.eh-tab[data-tab=cables]');"
                  " __cab.focus(); 1")
            pg.js("__eh.handle.setTabs(%s.map(function (t) { return t.key === 'cables' ? {key: t.key, label: 'Wires', count: 99, href: '#/device/atem-mini/cables?x=1'}"
                  " : {key: t.key, label: t.label, count: null, href: t.href}; })); 1" % TAB_LIST)
            after = pg.js(TAB_LIST)
            cab = [t for t in after if t["key"] == "cables"][0]
            self.assertEqual((cab["label"], cab["count"], cab["href"]), ("Wires", "99", "#/device/atem-mini/cables?x=1"))
            self.assertTrue(all(t["count"] is None for t in after if t["key"] != "cables"), "a null count removes the badge")
            self.assertEqual([t["selected"] for t in after], [t["selected"] for t in before], "the active tab is kept")
            self.assertTrue(pg.js("document.querySelector('.eh-tab[data-tab=cables]') === __cab && document.activeElement === __cab"),
                            "same tab element, focus untouched")
            self.assertTrue(pg.js("document.querySelector('header.eh .eh-bar') === __bar"), "the header was not rebuilt")

            pg.js("__eh.handle.update({tabs: %s.filter(function (t) { return t.key !== 'files'; }), activeTab: 'cables'}); 1" % TAB_LIST)
            after = pg.js(TAB_LIST)
            self.assertNotIn("files", [t["key"] for t in after])
            self.assertEqual([t["key"] for t in after if t["selected"] == "true"], ["cables"])
            self.assertTrue(pg.js("document.activeElement.getAttribute('data-tab') === 'cables' && document.activeElement !== __cab"),
                            "a new tab strip puts focus back on the same tab")
            self.assertTrue(pg.js("document.querySelector('header.eh .eh-bar') === __bar"), "only the tab strip was replaced")

            pg.js("__eh.handle.update({activeTab: 'ports'}); 1")
            self.assertEqual(pg.js("document.querySelector('.eh-tab[aria-selected=true]').getAttribute('data-tab')"), "ports")

            pg.js("document.querySelector('header.eh .eh-action[data-action=patch]').focus(); __eh.handle.update({title: 'Renamed ATEM'}); 1")
            self.assertEqual(pg.js("document.querySelector('header.eh .eh-title').textContent"), "Renamed ATEM")
            self.assertTrue(pg.js("document.querySelector('header.eh .eh-bar') !== __bar"), "other keys re-render")
            self.assertEqual(pg.js("document.activeElement.getAttribute('data-action')"), "patch", "focus returns to the same action")
            self.assertEqual(pg.smoke["errors"], [])
            pg.shot("prim-entity-tabs")

    def test_link_actions_look_like_button_actions(self):
        with self.harness("/device/atem-mini") as pg:
            self.ready(pg, "overview")
            pg.js("__eh.handle.update({actions: [{key: 'edit', label: 'Edit', primary: true, href: '#edit'},"
                  " {key: 'save', label: 'Save', primary: true, run: function () {}},"
                  " {key: 'drop', label: 'Remove', danger: true, href: '#drop'}, {key: 'kill', label: 'Delete', danger: true, run: function () {}}]}); 1")
            look = ("(function (sel) { var s = getComputedStyle(document.querySelector('header.eh ' + sel));"
                    " return [s.backgroundColor, s.borderTopColor, s.color]; })(%s)")
            self.assertEqual(pg.js(look % json.dumps("a.eh-action.eh-primary")), pg.js(look % json.dumps("button.eh-action.eh-primary")))
            self.assertEqual(pg.js(look % json.dumps("a.eh-action.danger"))[2], pg.js(look % json.dumps("button.eh-action.danger"))[2])
            pg.shot("prim-entity-link-actions")


if __name__ == "__main__":  # pragma: no cover
    import unittest
    unittest.main()
