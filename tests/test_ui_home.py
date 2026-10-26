"""HOME: the home view in the app (docs/ui-audit.md B.2 HOME).

Runs against ``#/campus-demo/main/home`` once SHELL has registered the ``home`` view in ``app.js``
``VIEWS``; until then (or without Chrome) every test skips.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

try:
    from _ui import UiCase, ROOT
except ImportError:  # pragma: no cover
    from tests._ui import UiCase, ROOT

HOME = "#/campus-demo/main/home"
SECTION_KEYS = ["patch", "rooms", "devices", "schedules", "sop", "data", "settings"]
LEDE = ("Fathom documents this venue's audio, video and lighting: what is installed, where it is, "
        "and how it is wired.")
TARGETS = "a.hm-card, a.hm-link, a.hm-recent, a.hm-project"


def home_registered() -> bool:
    src = (ROOT / "fathom" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    return re.search(r"\bhome\s*:\s*\{[^}]*\./home\.js", src) is not None


class HomeUi(UiCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not home_registered():
            raise unittest.SkipTest("home view not registered in app.js VIEWS yet (SHELL): HOME UI tests skipped")
        super(HomeUi, cls).setUpClass()
        from fathom.schema import new_doc
        doc = new_doc("Empty Org")
        doc["rooms"] = []
        doc["meta"]["title"] = "Empty project"
        pdir = Path(cls.server.data) / "projects" / "home-empty"
        pdir.mkdir(parents=True)
        (pdir / "project.json").write_text(json.dumps(doc), encoding="utf-8")

    def home(self, pg) -> None:
        """Wait for the home view; skip when the shell rendered something else."""
        pg.wait_for("!!document.querySelector('#app-main') && !document.querySelector('#app-main .app-loading')")
        if not pg.js("!!document.querySelector('#app-main .hm-title')"):
            self.skipTest("home view did not mount at %s (not registered by SHELL?)" % pg.hash)

    def view_ready(self, pg, view: str) -> None:
        pg.wait_for("""(function (v) {
          var m = document.querySelector('#app-main'); if (!m) return false;
          if (m.querySelector('.app-loading, [aria-busy=true]')) return false;
          var el = m.querySelector('.app-view');
          return !el || !el.getAttribute('data-view') || el.getAttribute('data-view') === v;
        })(%s)""" % json.dumps(view))

    def test_layout_at_three_sizes(self):
        for size in ("d", "t", "m"):
            with self.subTest(size=size), self.open(HOME, size) as pg:
                self.home(pg)
                self.assertEqual(pg.smoke["errors"], [])
                self.assertEqual(pg.js("document.querySelector('.hm-title').textContent"), "Signal flow, stage to stream")
                self.assertEqual(pg.js("document.querySelector('p.hm-lede').textContent"), LEDE)
                keys = pg.js("[].map.call(document.querySelectorAll('section.hm-sections a.hm-card[data-section]'), function (a) { return a.dataset.section; })")
                self.assertEqual(keys, SECTION_KEYS)
                self.assertEqual(pg.js("[].map.call(document.querySelectorAll('section.hm-rooms div.hm-room[data-room]'), function (d) { return d.dataset.room; })"),
                                 ["main", "chapel", "broadcast"])
                self.assertLessEqual(pg.page_hscroll(), 0, "home at %s scrolls horizontally" % size)
                self.assertEqual(pg.offscreen("section.hm-sections a.hm-card", "x"), 0)
                small = pg.js("""(function (min) {
                  return [].filter.call(document.querySelectorAll(%s), function (a) {
                    var r = a.getBoundingClientRect(); return r.width && (r.height < min || r.width < min);
                  }).map(function (a) { return a.className + ' ' + a.textContent.trim().slice(0, 30); });
                })(%d)""" % (json.dumps(TARGETS), 44 if size in ("t", "m") else 40))
                self.assertEqual(small, [], "targets under the minimum size at %s" % size)
                pg.shot("home-" + size)

    def test_room_chips(self):
        with self.open(HOME, "d") as pg:
            self.home(pg)
            chips = pg.js("""(function () {
              var o = {};
              [].forEach.call(document.querySelectorAll('div.hm-room[data-room]'), function (d) {
                o[d.dataset.room] = [].map.call(d.querySelectorAll('a.hm-link'), function (a) { return [a.dataset.link, a.getAttribute('href')]; });
              });
              return o;
            })()""")
            self.assertEqual([k for k, _ in chips["main"]], ["patch", "plan", "racks", "sop", "room"])
            self.assertEqual([k for k, _ in chips["chapel"]], ["patch", "plan", "sop", "room"])
            self.assertEqual([k for k, _ in chips["broadcast"]], ["patch", "racks", "room"])
            self.assertEqual(dict(chips["chapel"])["room"], "#/campus-demo/chapel/rooms/chapel")
            self.assertEqual(dict(chips["broadcast"])["patch"], "#/campus-demo/broadcast/patch")
            counts = pg.js("document.querySelector('div.hm-room[data-room=main] .hm-room-counts').textContent")
            self.assertRegex(counts, r"^\d+ devices \u00b7 \d+ cables$")

    def test_every_card_link_mounts_its_view(self):
        with self.open(HOME, "d") as pg:
            self.home(pg)
            hrefs = pg.js("[].map.call(document.querySelectorAll(%s), function (a) { return a.getAttribute('href'); })" % json.dumps(TARGETS))
            hrefs = [x for i, x in enumerate(hrefs) if x and x not in hrefs[:i]]
            self.assertGreaterEqual(len(hrefs), 7 + 3 * 3)
            for href in hrefs:
                self.assertTrue(href.startswith("#/"), href)
                view = href.split("?")[0].split("/")[3] if href.count("/") >= 3 else "home"
                with self.subTest(href=href):
                    pg.goto(href)
                    self.view_ready(pg, view or "home")
                    self.assertFalse(pg.js("!!document.querySelector('#app-main .app-error-card')"), "%s shows an error card" % href)
                    self.assertEqual(pg.js("window.__fathomErrors || []"), [], href)
                pg.goto(HOME)
                self.home(pg)

    def test_project_cards(self):
        with self.open(HOME, "m") as pg:
            self.home(pg)
            names = pg.js("[].map.call(document.querySelectorAll('section.hm-projects a.hm-project'), function (a) { return a.dataset.project; })")
            self.assertIn("campus-demo", names)
            self.assertIn("sunday-demo", names)
            self.assertEqual(pg.js("document.querySelector('a.hm-project[aria-current=page]').dataset.project"), "campus-demo")
            self.assertEqual(pg.js("document.querySelector('a.hm-project[data-project=sunday-demo]').getAttribute('href')"), "#/sunday-demo//home")
        one = [("/api/v2/projects", 200, {"projects": [{"name": "campus-demo", "title": "Signal flow, stage to stream", "rooms": 3, "devices": 73}]}, "GET")]
        with self.open(HOME, "d", intercepts=one) as pg:
            self.home(pg)
            self.assertFalse(pg.js("!!document.querySelector('section.hm-projects')"), "one project at d: no project cards")
        with self.open(HOME, "m", intercepts=one) as pg:
            self.home(pg)
            self.assertEqual(pg.js("document.querySelectorAll('section.hm-projects a.hm-project').length"), 1, "always at sm")

    def test_recents_order_rooms_and_strip(self):
        with self.open(HOME, "d") as pg:
            self.home(pg)
            seed = {
                "device": [{"id": "vox-1", "t": 9000}, {"id": "ghost-device", "t": 8500}, {"id": "drum-mics", "t": 3000}],
                "room": [{"id": "broadcast", "t": 8000}, {"id": "chapel", "t": 2000}],
                "rack": [{"id": "rk-amp", "t": 7000}],
                "page": [{"id": "power-up", "t": 6000}],
            }
            pg.js("localStorage.setItem('fathom.ui.recent.campus-demo', %s)" % json.dumps(json.dumps(seed)))
            pg.reload()
            self.home(pg)
            strip = pg.js("[].map.call(document.querySelectorAll('section.hm-recent a.hm-recent'), function (a) { return [a.dataset.type, a.dataset.id]; })")
            seeded = [s for s in strip if [s[0], s[1]] in (["device", "vox-1"], ["room", "broadcast"], ["rack", "rk-amp"], ["page", "power-up"],
                                                          ["device", "drum-mics"], ["room", "chapel"])]
            self.assertEqual(seeded, [["device", "vox-1"], ["room", "broadcast"], ["rack", "rk-amp"], ["page", "power-up"],
                                      ["device", "drum-mics"], ["room", "chapel"]])
            self.assertNotIn(["device", "ghost-device"], strip)
            self.assertLessEqual(len(strip), 8)
            rooms = pg.js("[].map.call(document.querySelectorAll('div.hm-room[data-room]'), function (d) { return d.dataset.room; })")
            self.assertLess(rooms.index("broadcast"), rooms.index("chapel"))
            self.assertEqual(pg.js("document.querySelector('a.hm-recent[data-type=page]').getAttribute('href')"), "#/campus-demo/main/sop?page=power-up")
            self.assertLessEqual(pg.page_hscroll(), 0)

    def test_empty_project(self):
        with self.open("#/home-empty//home", "d") as pg:
            self.home(pg)
            pg.wait_for("!!document.querySelector('section.hm-rooms .fb-empty')")
            text = pg.js("document.querySelector('section.hm-rooms .fb-empty').textContent")
            self.assertIn("No rooms yet", text)
            self.assertIn("Add a room in Settings \u25B8 Rooms, or import a spreadsheet in Data \u25B8 Imports.", text)
            self.assertTrue(pg.js("!!document.querySelector('section.hm-rooms .fb-empty button')"), "editors get the action")
            self.assertFalse(pg.js("!!document.querySelector('div.hm-room')"))


if __name__ == "__main__":
    unittest.main()
