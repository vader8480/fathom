"""ELEV: the rack elevation (rack-elevation.js) at d (1280x900 mouse) and m (390x844 touch).

Every test seeds its own copy of campus-demo (``seed``): accessories and a three-cell shelf with two
devices in ``rk-foh``, a 19" rack of catalog devices with photos (``rk-net``), a 10" rack (``rk-ten``)
and an accessory overlapping a device in ``rk-amp``. The landing's elevation api is reached through
``.rk-viewport.__rkElevation``; external drops use a standalone elevation on a fake store. Skips
without Chrome (set ``FATHOM_CHROME``); ``$FATHOM_UI_SHOTS`` collects screenshots.
"""
from __future__ import annotations

import json
import shutil
import time
import urllib.request
from pathlib import Path

try:
    from _ui import UiCase
    from test_frontend_smoke import ROOT
except ImportError:  # pragma: no cover
    from tests._ui import UiCase
    from tests.test_frontend_smoke import ROOT

SIZES = ("d", "m")
API = "document.querySelector('.rk-viewport').__rkElevation"
SHELF_LABEL = "AV shelf"
UDM_REAR = "ubiquiti/ubiquiti-unifi-dream-machine-pro.rear.webp"
ATT_SVG = "att-be0fe3bc69e1"


def _dev(did, name, kind, rack, template=None, **extra):
    d = {"id": did, "name": name, "kind": kind, "room": "main", "rack": rack}
    if template:
        d["template"] = template
    d.update(extra)
    return d


def seeded_doc():
    doc = json.loads((ROOT / "fathom" / "samples" / "campus-demo" / "project.json").read_text(encoding="utf-8"))
    racks = {r["id"]: r for r in doc["racks"]}
    # rk-foh (12U): devices at U1 (rear), U6, U8, U10, U12 (rear), all full depth; U3 and U11 stay free.
    racks["rk-foh"]["items"] = [
        {"id": "ri-1", "type": "blank", "u": 2},
        {"id": "ri-2", "type": "shelf", "u": 4, "slots": 3, "label": SHELF_LABEL},
        {"id": "ri-3", "type": "lacing_bar", "u": 5},
        {"id": "ri-4", "type": "brush", "u": 5},
        {"id": "ri-5", "type": "vent", "u": 7},
        {"id": "ri-6", "type": "cable_manager", "u": 9},
    ]
    racks["rk-amp"]["items"] = [{"id": "ri-1", "type": "other", "u": 12, "label": "Filler"}]
    doc["racks"].append({"id": "rk-net", "name": "Network rack", "room": "main", "units": 10, "numbering": "bottom_up",
                         "faces": ["front", "rear"], "order": 3})
    doc["racks"].append({"id": "rk-ten", "name": "Desk rack", "room": "main", "units": 6, "numbering": "bottom_up",
                         "faces": ["front", "rear"], "width_in": 10, "order": 4,
                         "items": [{"id": "ri-1", "type": "blank", "u": 1}, {"id": "ri-2", "type": "shelf", "u": 3},
                                   {"id": "ri-3", "type": "drawer", "u": 4}]})
    doc["devices"] += [
        _dev("stream-pc", "Stream PC", "computer", {"id": "rk-foh", "u": 4, "height": 1, "face": "front", "shelf": "ri-2", "slot": 0}),
        _dev("atem-mini", "ATEM Mini", "video_switcher", {"id": "rk-foh", "u": 4, "height": 1, "face": "front", "shelf": "ri-2", "slot": 2}),
        _dev("net-48", "Core switch", "switch", {"id": "rk-net", "u": 10, "height": 1, "face": "front"}, "48-port-switch"),
        _dev("net-ecs", "Edge switch", "switch", {"id": "rk-net", "u": 9, "height": 1, "face": "front"}, "ubiquiti-ecs-24-poe"),
        _dev("net-udm", "Gateway", "network", {"id": "rk-net", "u": 8, "height": 1, "face": "front"}, "ubiquiti-unifi-dream-machine-pro",
             interfaces=[{"id": "primary", "role": "primary", "ip": "10.0.0.1"}]),
        _dev("net-nas", "NAS", "computer", {"id": "rk-net", "u": 5, "height": 2, "face": "front"}, "2u-storage"),
        _dev("net-ups", "UPS", "power", {"id": "rk-net", "u": 1, "height": 2, "face": "front", "image_front": ATT_SVG}, "2u-ups"),
        _dev("ten-sw", "Desk switch", "switch", {"id": "rk-ten", "u": 6, "height": 1, "face": "front"}, "netgear-gs108pp"),
    ]
    return doc


EXT_DOC = {
    "racks": [{"id": "x1", "name": "Test rack", "room": "x", "units": 8, "items": [{"id": "ri-1", "type": "shelf", "u": 5, "slots": 2}]}],
    "devices": [
        {"id": "d1", "name": "Amp", "kind": "amp", "rack": {"id": "x1", "u": 1, "height": 1, "face": "front"}},
        {"id": "d2", "name": "Laptop", "kind": "computer", "rack": {"id": "x1", "u": 5, "height": 1, "face": "front", "shelf": "ri-1", "slot": 0}},
    ],
    "cables": [], "templates": [], "attachments": [],
}

EXT_PAYLOADS = {
    "ext-tpl2": {"kind": "template", "entry": {"id": "2u-ups", "name": "UPS (2U)", "ru": 2}, "template": {"id": "2u-ups", "name": "UPS (2U)", "ru": 2}},
    "ext-tpl1": {"kind": "template", "entry": {"id": "1u-server", "ru": 1}, "template": {"id": "1u-server", "name": "Server (1U)", "ru": 1}},
    "ext-item": {"kind": "item", "type": "blank"},
}

# A standalone elevation on a fake store; window.__drops records onExternalDrop calls.
MOUNT_EXT = """(function (doc, payloads) {
  var base = document.querySelector('script[src*="js/app.js"]').src.replace(/js\\/app\\.js.*$/, '');
  return import(base + 'js/rack-elevation.js').then(function (m) {
    var host = document.createElement('div');
    host.id = 'ext-host';
    host.style.cssText = 'position:fixed;left:0;top:0;right:0;bottom:0;z-index:9000;background:#0b1020;display:flex;flex-direction:column';
    var pal = document.createElement('div');
    pal.style.cssText = 'display:flex;gap:8px;padding:8px';
    Object.keys(payloads).forEach(function (id) {
      var b = document.createElement('button');
      b.id = id; b.type = 'button'; b.textContent = id; b.style.cssText = 'touch-action:none;min-height:44px';
      pal.appendChild(b);
    });
    var mount = document.createElement('div');
    mount.style.cssText = 'flex:1;min-height:0;display:flex;flex-direction:column';
    host.appendChild(pal); host.appendChild(mount); document.body.appendChild(host);
    var store = new EventTarget();
    store.doc = doc; store.room = 'x'; store.readOnly = false;
    window.__drops = []; window.__toasts = [];
    var ctx = {store: store, vocab: {}, commit: function () {}, select: function () {}, toast: function (msg) { window.__toasts.push(msg); }};
    var api = m.createElevation(mount, ctx, {onExternalDrop: function (p, t) { window.__drops.push({kind: p.kind, target: t}); }});
    pal.addEventListener('pointerdown', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      e.preventDefault();
      window.__started = api.beginExternalDrag(payloads[b.id], e);
    });
    window.__extStore = store;
    return true;
  });
})(%s, %s)"""


class ElevationUi(UiCase):
    # ------------------------------------------------------------ helpers

    def seed(self, name, mutate=None):
        pdir = Path(self.server.data) / "projects" / name
        if pdir.exists():
            shutil.rmtree(str(pdir))
        shutil.copytree(str(ROOT / "fathom" / "samples" / "campus-demo"), str(pdir))
        doc = seeded_doc()
        doc["meta"]["slug"] = name
        if mutate:
            mutate(doc)
        (pdir / "project.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
        return name

    def doc(self, name):
        body = json.loads(urllib.request.urlopen(self.base + "/api/v2/projects/" + name).read().decode("utf-8"))
        return body["doc"]

    def wait_doc(self, name, pred, what, timeout=10.0):
        t0 = time.time()
        last = None
        while time.time() - t0 < timeout:
            last = self.doc(name)
            if pred(last):
                return last
            time.sleep(0.15)
        self.fail("server doc never satisfied: %s" % what)

    @staticmethod
    def device(doc, did):
        return [d for d in doc["devices"] if d["id"] == did][0]

    @staticmethod
    def item(doc, rack, iid):
        r = [k for k in doc["racks"] if k["id"] == rack][0]
        return ([i for i in r.get("items", []) if i["id"] == iid] or [None])[0]

    def landing(self, name, size, **kw):
        cm = self.open("#/%s/main/racks" % name, size, **kw)
        pg = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.assertEqual(pg.smoke["errors"], [], "errors on the %s landing at %s" % (name, size))
        pg.wait_for("document.querySelectorAll('.rk-rack').length === 4 && !!(%s)" % API)
        return pg

    def point(self, pg, sel, fx=0.5, fy=0.5, scroll=True):
        r = pg.js("""(function (sel, fx, fy, scroll) {
          var el = document.querySelector(sel); if (!el) return null;
          if (scroll) el.scrollIntoView({block: 'center', inline: 'nearest'});
          var r = el.getBoundingClientRect();
          return [r.left + r.width * fx, r.top + r.height * fy];
        })(%s, %s, %s, %s)""" % (json.dumps(sel), fx, fy, "true" if scroll else "false"))
        self.assertIsNotNone(r, "no element " + sel)
        return r

    def ru_y(self, pg, slots_sel, units, u, height=1):
        """Client y of the middle of a block at U ``u`` (bottom-up numbering)."""
        r = pg.js("""(function (sel) {
          var s = document.querySelector(sel), root = s.closest('.rk-root');
          return [s.getBoundingClientRect().top, parseFloat(getComputedStyle(root).getPropertyValue('--rk-ru'))];
        })(%s)""" % json.dumps(slots_sel))
        top, ru = r
        return top + (units - (u + height - 1)) * ru + height * ru / 2

    def drag(self, pg, a, b, steps=8, alt=False):
        (x0, y0), (x1, y1) = a, b
        if pg.touch:
            pg.command("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]})
            for i in range(1, steps + 1):
                f = float(i) / steps
                pg.command("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x0 + (x1 - x0) * f, "y": y0 + (y1 - y0) * f}]})
            pg.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        else:
            mods = 1 if alt else 0
            pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x0, "y": y0})
            pg.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x0, "y": y0, "button": "left", "buttons": 1, "clickCount": 1})
            for i in range(1, steps + 1):
                f = float(i) / steps
                pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x0 + (x1 - x0) * f, "y": y0 + (y1 - y0) * f,
                                                        "button": "left", "buttons": 1, "modifiers": mods})
            pg.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x1, "y": y1, "button": "left", "buttons": 0,
                                                    "clickCount": 1, "modifiers": mods})

    def focus(self, pg, sel):
        pg.wait_for("!!document.querySelector(%s)" % json.dumps(sel))
        pg.js("(function (el) { el.scrollIntoView({block: 'center'}); el.focus(); })(document.querySelector(%s))" % json.dumps(sel))

    def label_of(self, pg, sel):
        return pg.js("(document.querySelector(%s) || {getAttribute: function () { return ''; }}).getAttribute('aria-label')" % json.dumps(sel))

    # ------------------------------------------------------------ display

    def test_image_mode_and_airflow(self):
        for size in SIZES:
            with self.subTest(size=size):
                name = self.seed("elev-img-" + size)
                pg = self.landing(name, size)
                pg.js(API + ".setOptions({display: 'image'})")
                pg.js("document.querySelector('.rk-rack[data-rack=rk-net]').scrollIntoView({block: 'start'})")   # photos load lazily
                pg.wait_for("Array.prototype.every.call(document.querySelectorAll('.rk-block[data-rack=rk-net] img.rk-img'), function (i) {"
                            " return i.complete && i.naturalWidth > 0; }) && document.querySelectorAll('.rk-block[data-rack=rk-net] img.rk-img').length === 5")
                src = pg.js("document.querySelector('.rk-block[data-device=net-48] img').getAttribute('src')")
                self.assertTrue(src.endswith("static/rack-images/generic/48-port-switch.front.webp"), src)
                self.assertTrue(pg.js("document.querySelector('.rk-block[data-device=net-48]').classList.contains('rk-showimg')"))
                self.assertEqual(pg.js("getComputedStyle(document.querySelector('.rk-block[data-device=net-48] .rk-bname')).visibility"), "hidden",
                                 "image mode hides the label")
                ups = pg.js("document.querySelector('.rk-block[data-device=net-ups] img').getAttribute('src')")
                self.assertTrue(ups.endswith("/files/%s/main-floor.svg" % ATT_SVG), "an attachment overrides the catalog photo: " + ups)
                self.assertFalse(pg.js("!!document.querySelector('.rk-block[data-device=switcher] img')"), "no photo: the label block stays")
                self.assertEqual(pg.js(API + ".getState().display"), "image")
                pg.shot("elev-image-" + size)

                pg.js(API + ".setOptions({display: 'both', face: 'both'})")
                if size == "d":
                    pg.wait_for("!!document.querySelector('.rk-slots[data-face=rear] .rk-block[data-device=net-udm] img')")
                    rear = pg.js("document.querySelector('.rk-slots[data-face=rear] .rk-block[data-device=net-udm] img').getAttribute('src')")
                    self.assertTrue(rear.endswith(UDM_REAR), rear)
                    self.assertEqual(pg.js("document.querySelector('.rk-slots[data-face=rear] .rk-block[data-device=net-ecs] .rk-air').textContent"), "\u21a6")
                pg.wait_for("!!document.querySelector('.rk-slots[data-face=front] .rk-block[data-device=net-ecs] .rk-air')")
                blk = ".rk-slots[data-face=front] .rk-block[data-device=net-ecs]"
                self.assertEqual(pg.js("document.querySelector('%s .rk-air').textContent" % blk), "\u21e5", "front-to-rear: intake on the front")
                self.assertTrue(pg.js("document.querySelector('%s').classList.contains('rk-imglabel')" % blk))
                self.assertEqual(pg.js("getComputedStyle(document.querySelector('%s .rk-bname')).visibility" % blk), "visible",
                                 "both: the label sits over the photo")
                self.assertIn("Intake", self.label_of(pg, blk))
                self.assertLessEqual(pg.page_hscroll(), 0)

    def test_annotate_column(self):
        for size in SIZES:
            with self.subTest(size=size):
                name = self.seed("elev-anno-" + size)
                pg = self.landing(name, size)
                self.assertFalse(pg.js("!!document.querySelector('.rk-annot')"))
                pg.js(API + ".setOptions({annotate: 'ip'})")
                pg.wait_for("document.querySelectorAll('.rk-annot[data-field=ip]').length === 4")
                self.assertEqual(pg.js("document.querySelector('.rk-rack[data-rack=rk-foh] .rk-anno[data-device=switcher] span').textContent"), "10.30.0.40")
                self.assertEqual(pg.js("document.querySelector('.rk-anno[data-device=net-udm] span').textContent"), "10.0.0.1")
                top = pg.js("[document.querySelector('.rk-anno[data-device=switcher]').getBoundingClientRect().top,"
                            " document.querySelector('.rk-block[data-device=switcher]').getBoundingClientRect().top]")
                self.assertAlmostEqual(top[0], top[1], delta=1.5, msg="the note lines up with its block")
                pg.js(API + ".setOptions({annotate: 'name'})")
                pg.wait_for("!!document.querySelector('.rk-annot[data-field=name]')")
                self.assertEqual(pg.js("document.querySelector('.rk-anno[data-device=net-nas] span').textContent"), "NAS")
                width = pg.js("document.querySelector('.rk-annot').getBoundingClientRect().width")
                self.assertEqual(round(width), 96 if size == "m" else 132)
                self.assertEqual(pg.js(API + ".getState().annotate"), "name")
                self.assertLessEqual(pg.page_hscroll(), 0, "no page horizontal scroll with the annotate column at " + size)
                self.assertEqual(pg.offscreen(".rk-annot", "x"), 0, "the annotate column fits at " + size)
                pg.shot("elev-annotate-" + size)

    def test_faces(self):
        for size in SIZES:
            with self.subTest(size=size):
                name = self.seed("elev-faces-" + size)
                pg = self.landing(name, size)
                pg.js(API + ".setOptions({face: 'both'})")
                self.assertEqual(pg.js(API + ".getState().face"), "both")
                if size == "d":
                    pg.wait_for("document.querySelectorAll('.rk-rack[data-rack=rk-foh] .rk-slots').length === 2")
                    self.assertEqual(pg.js("Array.prototype.map.call(document.querySelectorAll('.rk-rack[data-rack=rk-foh] .rk-slots'),"
                                           " function (s) { return s.getAttribute('data-face'); })"), ["front", "rear"])
                    self.assertEqual(pg.js("document.querySelectorAll('.rk-slots').length"), 8)
                    self.assertFalse(pg.js("!!document.querySelector('.rk-facetoggle')"))
                    self.assertTrue(pg.js("document.querySelector('.rk-slots[data-face=rear] .rk-block[data-device=sw-foh]').classList.contains('rk-behind') === false"))
                    self.assertTrue(pg.js("document.querySelector('.rk-slots[data-face=front] .rk-block[data-device=sw-foh]').classList.contains('rk-behind')"))
                    self.assertTrue(pg.js("!!document.querySelector('.rk-slots[data-face=rear] .rk-item[data-type=lacing_bar]:not(.rk-behind)')"))
                else:
                    pg.wait_for("!!document.querySelector('.rk-rack[data-rack=rk-foh] .rk-facetoggle[data-face=rear]')")
                    self.assertEqual(pg.js("document.querySelectorAll('.rk-slots').length"), 4, "one face per rack at sm")
                    self.assertEqual(pg.js("document.querySelector('.rk-rack[data-rack=rk-foh] .rk-slots').getAttribute('data-face')"), "front")
                    self.assertGreaterEqual(pg.rect(".rk-rack[data-rack=rk-foh] .rk-facetoggle")["height"], 44)
                    pg.click(".rk-rack[data-rack=rk-foh] .rk-facetoggle")
                    pg.wait_for("document.querySelector('.rk-rack[data-rack=rk-foh] .rk-slots').getAttribute('data-face') === 'rear'")
                    self.assertTrue(pg.js("!!document.querySelector('.rk-rack[data-rack=rk-foh] .rk-facetoggle[data-face=front]')"))
                    self.assertEqual(pg.js("document.activeElement.className.indexOf('rk-facetoggle') >= 0"), True, "the toggle keeps focus")
                self.assertLessEqual(pg.js("(function (v) { return v.scrollWidth - v.clientWidth; })(document.querySelector('.rk-viewport'))"), 1)
                self.assertLessEqual(pg.page_hscroll(), 0)
                self.assertEqual(pg.offscreen(".rk-slots", "x"), 0, "both faces fit horizontally at " + size)
                pg.shot("elev-faces-" + size)

    def test_ten_inch_width_and_item_looks(self):
        for size in SIZES:
            with self.subTest(size=size):
                name = self.seed("elev-ten-" + size)
                pg = self.landing(name, size)
                w = pg.js("[document.querySelector('.rk-slots[data-rack=rk-ten]').getBoundingClientRect().width,"
                          " document.querySelector('.rk-slots[data-rack=rk-foh]').getBoundingClientRect().width,"
                          " document.querySelector('.rk-block[data-device=ten-sw]').getBoundingClientRect().width,"
                          " document.querySelector('.rk-rack[data-rack=rk-ten] .rk-item[data-type=drawer]').getBoundingClientRect().width]")
                self.assertAlmostEqual(w[0] / w[1], 168.0 / 320.0, delta=0.01, msg="a 10\" rack is 168/320 of a 19\" one")
                self.assertAlmostEqual(w[2], w[0], delta=1.5, msg="a full-width block fills its 10\" rack")
                self.assertAlmostEqual(w[3], w[0], delta=1.5)
                self.assertIn("10\u2033", pg.js("document.querySelector('.rk-rack[data-rack=rk-ten] .rk-sub').textContent"))
                looks = pg.js("""(function () {
                  var out = {};
                  Array.prototype.forEach.call(document.querySelectorAll('.rk-rack[data-rack=rk-foh] .rk-item'), function (el) {
                    var cs = getComputedStyle(el), a = getComputedStyle(el, '::after'), b = getComputedStyle(el, '::before');
                    out[el.getAttribute('data-type')] = [cs.backgroundImage, cs.borderStyle, a.content, b.content].join('|');
                  });
                  return out;
                })()""")
                self.assertEqual(sorted(looks), ["blank", "brush", "cable_manager", "shelf", "vent"])
                self.assertEqual(len(set(looks.values())), len(looks), "each accessory type looks different: %r" % looks)
                self.assertEqual(pg.js("document.querySelectorAll('.rk-item[data-item=ri-2][data-rack=rk-foh] .rk-cell').length"), 3)
                if size == "m":
                    self.assertGreaterEqual(pg.rect(".rk-item[data-type=blank]")["height"], 44, "44 px targets under a coarse pointer")
                warn = pg.js("document.querySelector('.rk-rack[data-rack=rk-amp] .rk-warnings').textContent")
                self.assertIn("Filler", warn)
                self.assertIn("IEM transmitter", warn)
                self.assertNotIn("item:", warn)
                self.assertLessEqual(pg.page_hscroll(), 0)

    def test_cable_highlight(self):
        for size in SIZES:
            with self.subTest(size=size):
                name = self.seed("elev-hl-" + size)
                pg = self.landing(name, size)
                self.assertFalse(pg.js("!!document.querySelector('.rk-hl,.rk-dim')"))
                pg.click(".rk-block[data-device=switcher]")
                pg.wait_for("document.querySelector('.rk-block[data-device=switcher]').classList.contains('rk-selected')")
                hl = pg.js("Array.prototype.map.call(document.querySelectorAll('.rk-block.rk-hl'), function (b) { return b.getAttribute('data-device'); }).sort()")
                self.assertEqual(hl, ["pdu-foh", "sw-foh"], "devices sharing a cable with the switcher (campus-demo cables)")
                self.assertTrue(pg.js("document.querySelector('.rk-block[data-device=ctrl-main]').classList.contains('rk-dim')"))
                self.assertTrue(pg.js("document.querySelector('.rk-block[data-device=net-48]').classList.contains('rk-dim')"))
                self.assertTrue(pg.js("document.querySelector('.rk-item[data-rack=rk-foh][data-item=ri-1]').classList.contains('rk-dim')"))
                self.assertFalse(pg.js("document.querySelector('.rk-block[data-device=switcher]').classList.contains('rk-dim')"))

    # ------------------------------------------------------------ editing

    def test_blank_by_keyboard(self):
        for size in SIZES:
            with self.subTest(size=size):
                name = self.seed("elev-blank-" + size)
                pg = self.landing(name, size)
                blank = ".rk-item[data-rack=rk-foh][data-item=ri-1]"
                self.focus(pg, blank)
                pg.press("Control+d")
                pg.wait_for("document.querySelectorAll('.rk-rack[data-rack=rk-foh] .rk-item[data-type=blank]').length === 2")
                new_id = pg.js("document.activeElement.getAttribute('data-item')")
                self.assertNotEqual(new_id, "ri-1", "focus moves to the copy")
                self.assertTrue(self.label_of(pg, ".rk-item[data-rack=rk-foh][data-item=%s]" % new_id).startswith("Blank panel, U11,"),
                                "the copy takes the first free RU from the top")
                d = self.wait_doc(name, lambda d: self.item(d, "rk-foh", new_id) is not None, "the added blank is saved")
                self.assertEqual(self.item(d, "rk-foh", new_id)["u"], 11)

                self.focus(pg, blank)
                pg.press("ArrowUp")
                pg.wait_for("(document.querySelector(%s).getAttribute('aria-label') || '').indexOf('Blank panel, U3,') === 0" % json.dumps(blank))
                self.assertEqual(pg.js("document.activeElement.getAttribute('data-item')"), "ri-1", "the moved item keeps focus")
                self.wait_doc(name, lambda d: self.item(d, "rk-foh", "ri-1")["u"] == 3, "the move is saved")
                pg.press("ArrowUp")   # U4 holds the shelf
                time.sleep(0.3)
                self.assertTrue(self.label_of(pg, blank).startswith("Blank panel, U3,"), "a move onto the shelf is refused")
                pg.press("ArrowDown")
                pg.wait_for("document.querySelector(%s).getAttribute('aria-label').indexOf('Blank panel, U2,') === 0" % json.dumps(blank))
                pg.press("Delete")
                pg.wait_for("!document.querySelector(%s)" % json.dumps(blank))
                self.wait_doc(name, lambda d: self.item(d, "rk-foh", "ri-1") is None, "the delete is saved")

                shelf = ".rk-item[data-rack=rk-foh][data-item=ri-2]"
                self.focus(pg, shelf)
                pg.press("Delete")
                pg.wait_for("(document.getElementById('app-dialog') || {}).textContent && "
                            "document.getElementById('app-dialog').textContent.indexOf('2 devices on it become unracked') >= 0")
                pg.press("Escape")
                pg.wait_for("document.getElementById('app-dialog').textContent.indexOf('devices on it become') < 0")
                self.assertTrue(pg.js("!!document.querySelector(%s)" % json.dumps(shelf)), "cancel keeps the shelf")

    def test_shelf_cells_by_drag(self):
        for size in SIZES:
            with self.subTest(size=size):
                name = self.seed("elev-shelf-" + size)
                pg = self.landing(name, size)
                kids = pg.js("Array.prototype.map.call(document.querySelectorAll('.rk-block.rk-onshelf'), function (b) {"
                             " return [b.getAttribute('data-device'), b.getAttribute('data-shelf'), b.getAttribute('data-slot')]; })")
                self.assertEqual(sorted(kids), [["atem-mini", "ri-2", "2"], ["stream-pc", "ri-2", "0"]])
                shelf = ".rk-item[data-rack=rk-foh][data-item=ri-2]"
                pg.shot("elev-shelf-" + size)
                self.point(pg, shelf)
                src = self.point(pg, ".rk-block[data-device=ctrl-main]", 0.3, 0.5, scroll=False)
                dst = self.point(pg, shelf, 0.5, 0.5, scroll=False)   # the middle of cell 2 of 3
                self.drag(pg, src, dst)
                pg.wait_for("!!document.querySelector('.rk-block.rk-onshelf[data-device=ctrl-main][data-shelf=ri-2][data-slot=\"1\"]')")
                d = self.wait_doc(name, lambda d: self.device(d, "ctrl-main")["rack"].get("shelf") == "ri-2", "the shelf drop is saved")
                self.assertEqual(self.device(d, "ctrl-main")["rack"].get("slot"), 1)
                self.assertEqual(self.device(d, "ctrl-main")["rack"].get("u"), 4)

                self.point(pg, shelf)
                src = self.point(pg, ".rk-block[data-device=stream-pc]", 0.5, 0.4, scroll=False)
                x = self.point(pg, ".rk-slots[data-rack=rk-foh]", 0.5, 0.5, scroll=False)[0]
                y = self.ru_y(pg, ".rk-slots[data-rack=rk-foh]", 12, 3)
                self.drag(pg, src, (x, y))
                pg.wait_for("!!document.querySelector('.rk-block[data-device=stream-pc]:not(.rk-onshelf)')")
                self.assertTrue(self.label_of(pg, ".rk-block[data-device=stream-pc]").startswith("Stream PC, U3, 1U, front"))
                d = self.wait_doc(name, lambda d: "shelf" not in self.device(d, "stream-pc")["rack"], "dragging off the shelf is saved")
                self.assertEqual(self.device(d, "stream-pc")["rack"]["u"], 3)
                self.assertNotIn("slot", self.device(d, "stream-pc")["rack"])

                kid = ".rk-block[data-device=atem-mini]"
                self.focus(pg, kid)
                pg.press("ArrowLeft")
                pg.wait_for("!!document.querySelector('.rk-block[data-device=atem-mini][data-slot=\"0\"]')")
                self.assertEqual(pg.js("document.activeElement.getAttribute('data-device')"), "atem-mini")

    def test_block_menu(self):
        for size in SIZES:
            with self.subTest(size=size):
                name = self.seed("elev-menu-" + size)
                pg = self.landing(name, size)
                blk = ".rk-block[data-device=switcher]"
                before = pg.js("document.querySelectorAll('.rk-rack[data-rack=rk-foh] .rk-block').length")
                x, y = self.point(pg, blk, 0.3, 0.5)
                if size == "d":
                    pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
                    pg.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "right", "buttons": 2, "clickCount": 1})
                    pg.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "right", "buttons": 0, "clickCount": 1})
                    pg.wait_for("!!document.querySelector('.rk-menu')")
                    self.assertFalse(pg.js("document.querySelector('.rk-menu').classList.contains('rk-sheet')"))
                else:
                    pg.command("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
                    time.sleep(0.8)
                    pg.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                    pg.wait_for("!!document.querySelector('.rk-menu.rk-sheet') && !!document.querySelector('.rk-menu-back')")
                    r = pg.rect(".rk-menu")
                    self.assertAlmostEqual(r["bottom"], 844, delta=1, msg="a bottom sheet at sm")
                    self.assertAlmostEqual(r["width"], 390, delta=1)
                    small = pg.js("Array.prototype.filter.call(document.querySelectorAll('.rk-menu button, .rk-menu select'), function (b) {"
                                  " var q = b.getBoundingClientRect(); return q.height < 44 || q.width < 44; }).length")
                    self.assertEqual(small, 0, "44 px targets in the sheet")
                self.assertIn("Main switcher", pg.js("document.querySelector('.rk-menu').getAttribute('aria-label')"))
                acts = pg.js("Array.prototype.map.call(document.querySelectorAll('.rk-menu [data-act]'), function (b) { return b.getAttribute('data-act'); })")
                for act in ("face", "side", "depth", "color", "rack", "shelf", "dup", "unrack", "open"):
                    self.assertIn(act, acts)
                self.assertTrue(pg.js("!!document.querySelector('.rk-menu .rk-menu-rack')"), "move to rack")
                pg.shot("elev-menu-" + size)
                pg.click(".rk-menu [data-act=dup]")
                pg.wait_for("!document.querySelector('.rk-menu') && document.querySelectorAll('.rk-rack[data-rack=rk-foh] .rk-block').length === %d" % (before + 1))
                copy = pg.js("document.activeElement.getAttribute('data-device')")
                self.assertNotEqual(copy, "switcher", "the copy is selected")
                self.assertIn(", U11,", self.label_of(pg, ".rk-block[data-device=\"%s\"]" % copy))
                self.wait_doc(name, lambda d: any(x["id"] == copy for x in d["devices"]), "the duplicate is saved")

                self.focus(pg, blk)
                pg.click(blk + " .rk-more")
                pg.wait_for("!!document.querySelector('.rk-menu .rk-swatch')")
                sw = pg.js("document.querySelectorAll('.rk-menu .rk-swatch')[2].getAttribute('data-v')")
                pg.click(".rk-menu .rk-swatch[data-v=\"%s\"]" % sw)
                pg.wait_for("document.querySelector(%s).style.getPropertyValue('--rk-color').trim() === %s" % (json.dumps(blk), json.dumps(sw)))
                pg.wait_for("document.querySelector('.rk-menu .rk-swatch[data-v=\"%s\"]').getAttribute('aria-pressed') === 'true'" % sw)
                self.wait_doc(name, lambda d: self.device(d, "switcher")["rack"].get("color") == sw, "the colour is saved")
                pg.click(".rk-menu .rk-swclear")
                pg.wait_for("document.querySelector(%s).style.getPropertyValue('--rk-color').trim() !== %s" % (json.dumps(blk), json.dumps(sw)))
                self.wait_doc(name, lambda d: "color" not in self.device(d, "switcher")["rack"], "clearing the colour is saved")
                if size == "d":
                    pg.press("Escape")
                    pg.wait_for("!document.querySelector('.rk-menu')")
                else:
                    pg.click(".rk-menu [data-act=close]")
                    pg.wait_for("!document.querySelector('.rk-menu') && !document.querySelector('.rk-menu-back')")

                shelf = ".rk-item[data-rack=rk-foh][data-item=ri-2]"
                self.focus(pg, shelf)
                pg.press("Enter")
                pg.wait_for("!!document.querySelector('.rk-menu [data-act=slots]')")
                acts = pg.js("Array.prototype.map.call(document.querySelectorAll('.rk-menu [data-act]'), function (b) { return b.getAttribute('data-act'); })")
                for act in ("label", "icolor", "slots", "height", "iface", "idepth", "idel"):
                    self.assertIn(act, acts)
                pg.click(".rk-menu [data-act=slots][data-v=\"4\"]")
                pg.wait_for("document.querySelectorAll('.rk-item[data-rack=rk-foh][data-item=ri-2] .rk-cell').length === 4")
                pg.js("(function (i) { i.value = 'Gear shelf'; i.dispatchEvent(new Event('change', {bubbles: true})); })(document.querySelector('.rk-menu-label'))")
                pg.wait_for("document.querySelector('.rk-item[data-rack=rk-foh][data-item=ri-2] .rk-iname').textContent === 'Gear shelf'")
                d = self.wait_doc(name, lambda d: self.item(d, "rk-foh", "ri-2").get("label") == "Gear shelf", "the item edits are saved")
                self.assertEqual(self.item(d, "rk-foh", "ri-2")["slots"], 4)
                if size == "d":
                    pg.press("Escape")
                    pg.wait_for("!document.querySelector('.rk-menu') && document.activeElement.getAttribute('data-item') === 'ri-2'")

    def test_flip_and_rack_keys(self):
        for size in SIZES:
            with self.subTest(size=size):
                name = self.seed("elev-keys-" + size)
                pg = self.landing(name, size)
                blk = ".rk-block[data-device=ctrl-main]"
                self.focus(pg, blk)
                pg.press("r")
                pg.wait_for("document.querySelector(%s).classList.contains('rk-behind')" % json.dumps(blk))
                self.assertEqual(pg.js("document.activeElement.getAttribute('data-device')"), "ctrl-main")
                self.wait_doc(name, lambda d: self.device(d, "ctrl-main")["rack"]["face"] == "rear", "the flip is saved")
                pg.press("r")
                pg.wait_for("!document.querySelector(%s).classList.contains('rk-behind')" % json.dumps(blk))

                self.focus(pg, ".rk-block[data-device=ulxd-main]")
                pg.press("]")
                pg.wait_for("!!document.querySelector('.rk-rack[data-rack=rk-amp] .rk-block[data-device=ulxd-main]')")
                self.assertTrue(self.label_of(pg, ".rk-block[data-device=ulxd-main]").startswith("Wireless RX 1-4, U10,"), "same U in the next rack")
                self.assertEqual(pg.js("document.activeElement.getAttribute('data-device')"), "ulxd-main")
                self.wait_doc(name, lambda d: self.device(d, "ulxd-main")["rack"]["id"] == "rk-amp", "the rack move is saved")
                pg.press("[")
                pg.wait_for("!!document.querySelector('.rk-rack[data-rack=rk-foh] .rk-block[data-device=ulxd-main]')")

                self.focus(pg, ".rk-block[data-device=amp-fill]")
                pg.press("Shift+ArrowUp")
                pg.wait_for("document.querySelector('.rk-block[data-device=amp-fill]').getAttribute('aria-label').indexOf('Fill amp, U7,') === 0")

    def test_viewer_cannot_edit(self):
        name = self.seed("elev-viewer")
        body = json.loads(urllib.request.urlopen(self.base + "/api/v2/projects/" + name).read().decode("utf-8"))
        body["role"] = "viewer"
        for size in SIZES:
            with self.subTest(size=size):
                pg = self.landing(name, size, intercepts=[("/api/v2/projects/" + name, 200, body, "GET")])
                self.assertTrue(pg.js("document.querySelector('.rk-root').classList.contains('rk-readonly')"))
                blk = ".rk-block[data-device=ctrl-main]"
                self.focus(pg, blk)
                pg.press("ArrowUp")
                pg.press("r")
                pg.press("Delete")
                time.sleep(0.3)
                self.assertTrue(self.label_of(pg, blk).startswith("Room control, U6, 1U, front"), "viewers cannot move")
                src = self.point(pg, blk)
                y = self.ru_y(pg, ".rk-slots[data-rack=rk-foh]", 12, 3)
                self.drag(pg, src, (src[0], y))
                time.sleep(0.3)
                self.assertTrue(self.label_of(pg, blk).startswith("Room control, U6,"), "viewers cannot drag")
                self.assertFalse(pg.js(API + ".beginExternalDrag({kind: 'item', type: 'blank'}, {clientX: 0, clientY: 0})"))
                self.focus(pg, ".rk-item[data-rack=rk-foh][data-item=ri-1]")
                pg.press("Enter")
                pg.wait_for("!!document.querySelector('.rk-menu .rk-menu-label')")
                self.assertTrue(pg.js("document.querySelector('.rk-menu .rk-menu-label').readOnly"))
                self.assertTrue(pg.js("Array.prototype.every.call(document.querySelectorAll('.rk-menu .rk-swatch'), function (b) { return b.disabled; })"))
                self.assertFalse(pg.js("!!document.querySelector('.rk-menu [data-act=idel]')"))
                pg.click(".rk-menu [data-act=close]")
                pg.wait_for("!document.querySelector('.rk-menu')")
                self.focus(pg, blk)
                pg.press("Enter")
                pg.wait_for("document.getElementById('app-inspector').classList.contains('dr-open')")
        d = self.doc(name)
        self.assertEqual(self.device(d, "ctrl-main")["rack"], {"id": "rk-foh", "u": 6, "height": 1, "face": "front"})

    # ------------------------------------------------------------ external drop

    def test_external_drop_api(self):
        for size in SIZES:
            with self.subTest(size=size):
                name = self.seed("elev-ext-" + size)
                cm = self.open("#/%s/main/racks" % name, size)
                pg = cm.__enter__()
                self.addCleanup(cm.__exit__, None, None, None)
                self.assertTrue(pg.js(MOUNT_EXT % (json.dumps(EXT_DOC), json.dumps(EXT_PAYLOADS))))
                pg.wait_for("!!document.querySelector('#ext-host .rk-slots[data-rack=x1]')")
                slots = "#ext-host .rk-slots[data-rack=x1]"
                cx = self.point(pg, slots, 0.5, 0.5, scroll=False)[0]
                cell1 = self.point(pg, "#ext-host .rk-item[data-item=ri-1]", 0.75, 0.5, scroll=False)
                cell0 = self.point(pg, "#ext-host .rk-item[data-item=ri-1]", 0.25, 0.5, scroll=False)
                right = pg.js("document.querySelector(%s).getBoundingClientRect().right" % json.dumps(slots))
                outside = (min(right + 120, pg.js("innerWidth") - 4), cell1[1])

                def ext(btn, to, check=None, cancel=False):
                    start = self.point(pg, "#" + btn, scroll=False)
                    if pg.touch:
                        pg.command("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": start[0], "y": start[1]}]})
                    else:
                        pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": start[0], "y": start[1]})
                        pg.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": start[0], "y": start[1], "button": "left", "buttons": 1, "clickCount": 1})
                    self.assertTrue(pg.js("window.__started"), "beginExternalDrag starts")
                    for i in range(1, 7):
                        f = i / 6.0
                        x, y = start[0] + (to[0] - start[0]) * f, start[1] + (to[1] - start[1]) * f
                        if pg.touch:
                            pg.command("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
                        else:
                            pg.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "left", "buttons": 1})
                    if check:
                        check()
                    if cancel:
                        pg.press("Escape")
                        self.assertTrue(pg.js("document.querySelector('#ext-host .rk-ghost').hidden"), "Esc hides the ghost")
                    if pg.touch:
                        pg.command("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                    else:
                        pg.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": to[0], "y": to[1], "button": "left", "buttons": 0, "clickCount": 1})
                    time.sleep(0.1)
                    pg.js("window.__started = null")

                def ghost_ok():
                    pg.wait_for("document.querySelector('#ext-host .rk-ghost').textContent.indexOf('U3') >= 0")
                    self.assertEqual(pg.js("(function (g) { return g.hidden ? 'hidden' : g.className; })(document.querySelector('#ext-host .rk-ghost'))"),
                                     "rk-ghost rk-ok")
                    self.assertIn("U3", pg.js("document.querySelector('#ext-host .rk-ghost').textContent"))

                ext("ext-tpl2", (cx, self.ru_y(pg, slots, 8, 3, 2)), check=ghost_ok)
                self.assertEqual(pg.js("window.__drops"), [{"kind": "template", "target": {"rackId": "x1", "u": 3, "face": "front"}}])
                ext("ext-item", (cx, self.ru_y(pg, slots, 8, 7)))
                self.assertEqual(pg.js("window.__drops[1]"), {"kind": "item", "target": {"rackId": "x1", "u": 7, "face": "front"}})
                ext("ext-tpl1", cell1)
                self.assertEqual(pg.js("window.__drops[2]"),
                                 {"kind": "template", "target": {"rackId": "x1", "u": 5, "face": "front", "shelf": "ri-1", "slot": 1}})
                ext("ext-tpl1", cell0)
                ext("ext-tpl2", (cx, self.ru_y(pg, slots, 8, 1, 2)))
                ext("ext-tpl2", (cx, self.ru_y(pg, slots, 8, 3, 2)), cancel=True)
                ext("ext-tpl2", outside)
                self.assertEqual(pg.js("window.__drops.length"), 3, "taken spots, Esc and drops outside call nothing")
                self.assertIn("That shelf cell is taken.", pg.js("window.__toasts"))
                self.assertTrue(any("occupied by Amp" in t for t in pg.js("window.__toasts")))
                self.assertTrue(pg.js("document.querySelector('#ext-host .rk-ghost').hidden"))
                pg.js("window.__extStore.readOnly = true")
                start = self.point(pg, "#ext-item", scroll=False)
                pg.js("window.__started = null")
                self.drag(pg, start, (cx, self.ru_y(pg, slots, 8, 7)), steps=3)
                self.assertFalse(pg.js("window.__started"), "read-only elevations refuse external drags")
                self.assertEqual(pg.js("window.__drops.length"), 3)
