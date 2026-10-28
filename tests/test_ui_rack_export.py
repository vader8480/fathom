"""XPT: the rack export dialog (``js/rack-export.js``) on the dev harness ``/static/dev/rack-export.html``.

The harness opens ``openRackExport`` on an inline two-rack doc with a stub ctx (a stub library API and an
attachment panel image). Downloads are caught by stubbing ``URL.createObjectURL`` and anchor ``click()``
in the page, so the produced blobs can be read back. Covered: the dialog opens with every rack listed and
the given ones checked; SVG download (name, type, both faces, the embedded image, well-formed XML); PNG at
2x (a real PNG blob, canvas not tainted); Print/PDF (an iframe holding the SVG); remembered choices in
``fathom.ui.rack.export``; Esc closes and returns focus; full screen with 44 px targets at 390 px.
Set ``FATHOM_UI_SHOTS`` to save screenshots (1440x900 and 390x844). Skips without Chrome.
"""
from __future__ import annotations

import json

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

HARNESS = "/static/dev/rack-export.html"

STUB = """(function () {
  if (window.__rxDl) return 1;
  window.__rxDl = []; window.__rxBlobs = {};
  var create = URL.createObjectURL.bind(URL);
  URL.createObjectURL = function (b) { var u = create(b); window.__rxBlobs[u] = b; return u; };
  var click = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (this.hasAttribute('download')) {
      window.__rxDl.push({name: this.getAttribute('download'), href: this.href, blob: window.__rxBlobs[this.href] || null});
      return;
    }
    return click.call(this);
  };
  return 1;
})()"""


class RackExportUi(UiCase):

    # ------------------------------------------------------------ helpers

    def _open(self, pg, button="#rx-h-open"):
        pg.click(button)
        pg.wait_for("!!document.querySelector('.rx[role=dialog] .rx-go')")
        pg.wait_for("document.querySelector('.rx').getAnimations().every(function (a) { return a.playState !== 'running'; })")
        pg.wait_for("(document.querySelector('.rx-preview-img').getAttribute('src') || '').indexOf('data:image/svg+xml') === 0")

    def _choose(self, pg, group, key):
        pg.click(".rx [data-group=%s] input[value=%s]" % (group, key))
        pg.wait_for("document.querySelector('.rx [data-group=%s] input[value=%s]').checked" % (group, key))

    def _preview_svg(self, pg):
        return pg.js("decodeURIComponent(document.querySelector('.rx-preview-img').getAttribute('src').split(',').slice(1).join(','))")

    def _wait_images(self, pg):
        pg.wait_for("decodeURIComponent(document.querySelector('.rx-preview-img').getAttribute('src')).indexOf('<image ') > 0")

    def _export(self, pg):
        pg.js(STUB)
        n = pg.js("window.__rxDl.length")
        pg.click(".rx .rx-go")
        pg.wait_for("window.__rxDl.length > %d && !document.querySelector('.rx')" % n)
        return pg.js("(function (d) { return {name: d.name, type: d.blob && d.blob.type, size: d.blob && d.blob.size}; })(window.__rxDl[window.__rxDl.length - 1])")

    def _prefs(self, pg):
        raw = pg.js("localStorage.getItem('fathom.ui.rack.export')")
        return json.loads(raw) if raw else None

    def _big_shot(self, pg, name):
        pg.command("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        pg.wait_for("window.innerWidth === 1440")
        pg.shot(name)
        pg.command("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False})

    # ------------------------------------------------------------ tests

    def test_dialog_opens_and_svg_download(self):
        with self.open(HARNESS, "d") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self._open(pg)
            dlg = pg.js("""(function () { var w = document.querySelector('.rx');
              var t = document.getElementById(w.getAttribute('aria-labelledby'));
              var boxes = Array.prototype.map.call(w.querySelectorAll('.rx-rack-list input'), function (c) { return [c.value, c.checked]; });
              return {role: w.getAttribute('role'), modal: w.getAttribute('aria-modal'), title: t && t.textContent, boxes: boxes,
                      focus: w.contains(document.activeElement), go: w.querySelector('.rx-go').textContent,
                      fields: Array.prototype.map.call(w.querySelectorAll('select[data-field=annotate] option'), function (o) { return o.value; })}; })()""")
            self.assertEqual(dlg["role"], "dialog")
            self.assertEqual(dlg["modal"], "true")
            self.assertEqual(dlg["title"], "Export racks")
            self.assertEqual(dlg["boxes"], [["rk-audio", True], ["rk-video", True]])
            self.assertTrue(dlg["focus"], "focus moves into the dialog")
            self.assertEqual(dlg["go"], "Download SVG")
            self.assertEqual(dlg["fields"][:3], ["", "name", "model"])

            self._choose(pg, "face", "both")
            pg.js("(function () { var s = document.querySelector('.rx select[data-field=annotate]'); s.value = 'model';"
                  " s.dispatchEvent(new Event('change', {bubbles: true})); })()")
            self._wait_images(pg)
            svg = self._preview_svg(pg)
            self.assertIn('data-face="rear"', svg)
            self.assertIn('class="rx-annotations" data-field="model"', svg)
            self.assertIn("Audio rack &lt;A&gt;", svg)
            self._big_shot(pg, "rack-export-desktop")

            got = self._export(pg)
            self.assertEqual(got["name"], "harness-demo-racks-both.svg")
            self.assertEqual(got["type"], "image/svg+xml")
            check = pg.js("""window.__rxDl[window.__rxDl.length - 1].blob.text().then(function (t) {
              var x = new DOMParser().parseFromString(t, 'image/svg+xml');
              var root = x.documentElement;
              return {err: !!x.querySelector('parsererror'), ns: root.namespaceURI, w: root.getAttribute('width'),
                      vb: root.getAttribute('viewBox'), faces: x.querySelectorAll('g.rx-face').length,
                      images: x.querySelectorAll('image').length, legend: !!x.querySelector('g.rx-legend'),
                      footer: (x.querySelector('g.rx-footer') || {}).textContent || ''};
            })""")
            self.assertFalse(check["err"], "the SVG parses as XML")
            self.assertEqual(check["ns"], "http://www.w3.org/2000/svg")
            self.assertEqual(check["vb"].split()[:3], ["0", "0", check["w"]])
            self.assertEqual(check["faces"], 4, "two racks x front + rear")
            self.assertGreaterEqual(check["images"], 1, "the attachment panel image is embedded")
            self.assertTrue(check["legend"])
            self.assertIn("Harness Chapel & Hall", check["footer"])
            self.assertTrue(pg.js("document.activeElement && document.activeElement.id === 'rx-h-open'"), "focus returns to the opener")
            self.assertEqual(pg.js("window.__rx.results[window.__rx.results.length - 1].filename"), "harness-demo-racks-both.svg")
            self.assertEqual(self._prefs(pg), {"v": 1, "face": "both", "format": "svg", "legend": True, "annotate": "model"})
            calls = pg.js("window.__rx.calls")
            self.assertTrue(calls and calls[0]["ids"] == "demo-sw8" and calls[0]["project"] == "harness-demo", calls)

    def test_choices_are_remembered_and_single_rack_filename(self):
        with self.open(HARNESS, "d") as pg:
            self._open(pg, "#rx-h-open-one")
            boxes = pg.js("Array.prototype.map.call(document.querySelectorAll('.rx-rack-list input'), function (c) { return c.checked; })")
            self.assertEqual(boxes, [True, False])
            self.assertTrue(pg.js("document.querySelector('.rx [data-group=face] input[value=rear]').checked"), "the given face wins")
            pg.click(".rx-check input[data-field=legend]")
            pg.wait_for("decodeURIComponent(document.querySelector('.rx-preview-img').getAttribute('src')).indexOf('rx-legend') < 0")
            got = self._export(pg)
            self.assertEqual(got["name"], "harness-demo-rk-audio-rear.svg")
            self.assertEqual(self._prefs(pg)["legend"], False)
            pg.reload()
            self._open(pg)
            st = pg.js("""(function () { var w = document.querySelector('.rx');
              return {face: w.querySelector('[data-group=face] input:checked').value, legend: w.querySelector('input[data-field=legend]').checked}; })()""")
            self.assertEqual(st, {"face": "rear", "legend": False}, "remembered across a reload")
            pg.click(".rx .rx-none")
            self.assertTrue(pg.js("document.querySelector('.rx .rx-go').disabled"), "no rack, no export")
            self.assertIn("at least one rack", pg.js("document.querySelector('.rx .rx-msg').textContent"))
            pg.click(".rx .rx-all")
            self.assertFalse(pg.js("document.querySelector('.rx .rx-go').disabled"))

    def test_print_opens_an_iframe_with_the_svg(self):
        with self.open(HARNESS, "d") as pg:
            self._open(pg)
            self._choose(pg, "format", "print")
            self.assertEqual(pg.js("document.querySelector('.rx .rx-go').textContent"), "Print")
            pg.click(".rx .rx-go")
            pg.wait_for("!document.querySelector('.rx') && !!document.querySelector('iframe.rx-print-frame')")
            frame = pg.js("""(function () { var d = document.querySelector('iframe.rx-print-frame').contentDocument;
              return {svg: !!d.querySelector('body > svg g.rx-rack'), title: d.title}; })()""")
            self.assertTrue(frame["svg"])
            self.assertEqual(frame["title"], "harness-demo-racks-front")
            self.assertEqual(pg.js("window.__rx.results[window.__rx.results.length - 1].format"), "print")

    def test_phone_full_screen_png_and_escape(self):
        with self.open(HARNESS, "m") as pg:
            self.assertEqual(pg.smoke["errors"], [])
            self._open(pg)
            r = pg.rect(".rx")
            self.assertEqual((round(r["width"]), round(r["left"])), (390, 0), "full-screen sheet at sm")
            self.assertGreaterEqual(r["height"], 840)
            self.assertLessEqual(pg.page_hscroll(), 0)
            small = pg.js("""Array.prototype.filter.call(document.querySelectorAll('.rx button, .rx select, .rx-seg-opt, .rx-rack-opt, .rx-check'),
              function (e) { var q = e.getBoundingClientRect(); return q.width > 0 && q.height < 43.5; }).map(function (e) { return e.className || e.tagName; })""")
            self.assertEqual(small, [], "44 px targets under a coarse pointer")
            self._wait_images(pg)
            pg.shot("rack-export-phone")

            self._choose(pg, "format", "png")
            svg_w = int(pg.js("document.querySelector('.rx-preview-img').getAttribute('width')"))
            got = self._export(pg)
            self.assertEqual(got["name"], "harness-demo-racks-front.png")
            self.assertEqual(got["type"], "image/png")
            self.assertGreater(got["size"], 2000)
            png = pg.js("""window.__rxDl[window.__rxDl.length - 1].blob.arrayBuffer().then(function (b) {
              var a = new Uint8Array(b); var dv = new DataView(b);
              return {sig: Array.prototype.slice.call(a, 0, 8), w: dv.getUint32(16), h: dv.getUint32(20)}; })""")
            self.assertEqual(png["sig"], [137, 80, 78, 71, 13, 10, 26, 10])
            self.assertEqual(png["w"], 2 * svg_w, "2x scale")
            self.assertEqual(self._prefs(pg)["format"], "png")

            self._open(pg)
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.rx')")
            self.assertTrue(pg.js("document.activeElement && document.activeElement.id === 'rx-h-open'"), "focus returns after Esc")
            self.assertIsNone(pg.js("window.__rx.results[window.__rx.results.length - 1]"))

    def test_escape_on_desktop_and_focus_trap(self):
        with self.open(HARNESS, "d") as pg:
            self._open(pg)
            for _ in range(30):
                pg.press("Tab")
            self.assertTrue(pg.js("document.querySelector('.rx').contains(document.activeElement)"), "Tab stays inside the dialog")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.rx')")
            self.assertTrue(pg.js("document.activeElement && document.activeElement.id === 'rx-h-open'"))
            self.assertFalse(pg.js("document.documentElement.classList.contains('rx-open')"))


if __name__ == "__main__":  # pragma: no cover
    import unittest
    unittest.main()
