"""FILES: the project attachments view (``#/<project>/<room>/files``) on the shared DataTable.

Drives the real app on a ``tests/_ui.py`` server: the table lists ``doc.attachments`` with name (opens the
file), kind, device ("Project" when unattached), size, uploaded and by; filters by kind and device; the
Upload control posts to ``/api/v2/projects/<n>/files`` without a device and the new rows appear; Delete
asks first and removes the attachment; viewers see no mutating controls; cards at m with the Upload
button reachable and no horizontal page scroll. Skips without Chrome (set ``FATHOM_CHROME``).
"""
from __future__ import annotations

import json
import os
import tempfile
import urllib.request

try:
    from _ui import UiCase
except ImportError:  # pragma: no cover
    from tests._ui import UiCase

CAMPUS = "#/campus-demo/main/files"
ROWS = "#files-table tbody tr.dt-row"
SAMPLE_FILES = ["chapel.png", "main-floor.dxf", "main-floor.svg", "stage.drawio", "stage.svg"]


def _q(s: str) -> str:
    return json.dumps(s)


class FilesUi(UiCase):

    def _ready(self, pg, rows: int = 1) -> None:
        self.assertEqual(pg.smoke.get("errors"), [], pg.smoke)
        pg.wait_for("document.querySelectorAll(%s).length >= %d" % (_q(ROWS), rows))

    def _count(self, pg) -> str:
        return pg.js("document.querySelector('.files-root .dt-count').textContent")

    def _col(self, pg, col: str):
        return pg.js("Array.prototype.map.call(document.querySelectorAll(%s), function (td) { return td.textContent; })" % _q(ROWS + " td[data-col=%s]" % col))

    def _attachments(self):
        url = self.base + "/api/v2/projects/campus-demo"
        body = json.loads(urllib.request.urlopen(url, timeout=10).read().decode())
        return body["doc"].get("attachments") or []

    def _node_id(self, pg, selector: str) -> int:
        doc = pg.command("DOM.getDocument", {"depth": 1})
        return pg.command("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": selector})["nodeId"]

    def test_table_lists_attachments_with_links_and_filters(self) -> None:
        with self.open(CAMPUS, "d") as pg:
            self._ready(pg, 5)
            self.assertEqual(self._count(pg), "5 files")
            cols = pg.js("Array.prototype.map.call(document.querySelectorAll('#files-table thead th[data-col]'), function (th) { return th.getAttribute('data-col'); })")
            self.assertEqual(cols, ["name", "kind", "device", "size", "uploaded", "by"])
            self.assertEqual(sorted(self._col(pg, "name")), SAMPLE_FILES)
            self.assertEqual(set(self._col(pg, "device")), {"Project"}, "unattached files say Project")
            self.assertEqual(set(self._col(pg, "by")), {"admin"})
            self.assertTrue(all(s.endswith("KB") for s in self._col(pg, "size")), self._col(pg, "size"))
            href = pg.js("document.querySelector('#files-table tr.dt-row a.files-name[data-file]').getAttribute('href')")
            self.assertIn("/api/v2/projects/campus-demo/files/att-", href)
            self.assertEqual(pg.js("document.querySelector('#files-table tr.dt-row a.files-name').getAttribute('target')"), "_blank")
            status = pg.js("fetch(%s).then(function (r) { return r.status; })" % _q(href))
            self.assertEqual(status, 200, "the name link serves the file")
            self.assertEqual(set(self._col(pg, "kind")), {"image", "other"})

            # filter by kind (URL state), then search
            pg.click("#files-kind")
            pg.wait_for("!!document.querySelector('.files-root .dt-pop[data-col=kind]')")
            pg.click(".files-root .dt-pop input[value=other]")
            pg.wait_for("document.querySelector('.files-root .dt-count').textContent === '1 of 5 files'")
            self.assertEqual(self._col(pg, "name"), ["stage.drawio"])
            self.assertIn("f.kind=other", pg.js("location.hash"))
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.files-root .dt-pop')")
            pg.click("#files-kind")
            pg.wait_for("!!document.querySelector('.files-root .dt-pop[data-col=kind]')")
            pg.click(".files-root .dt-pop .dt-pop-clear")
            pg.wait_for("document.querySelector('.files-root .dt-count').textContent === '5 files'")
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.files-root .dt-pop')")
            pg.click("#files-filter")
            for ch in "stage":
                pg.press(ch)
            pg.wait_for("document.querySelector('.files-root .dt-count').textContent === '2 of 5 files'")
            self.assertEqual(sorted(self._col(pg, "name")), ["stage.drawio", "stage.svg"])
            self.assertTrue(pg.js("!!document.getElementById('files-upload')"), "editors see the Upload control")
            self.assertEqual(pg.js("document.getElementById('files-upload').getAttribute('accept')"), "image/*,application/pdf,.txt,.csv,.md")
            self.assertTrue(pg.js("document.getElementById('files-upload').multiple"))
            pg.shot("files-d")

    def test_upload_without_device_and_delete(self) -> None:
        tmp = tempfile.mkdtemp(prefix="files-ui-")
        p1 = os.path.join(tmp, "rider-notes.txt")
        p2 = os.path.join(tmp, "stage-plot.csv")
        with open(p1, "w", encoding="utf-8") as f:
            f.write("Two wedges, one talkback.\n")
        with open(p2, "w", encoding="utf-8") as f:
            f.write("item,qty\nwedge,2\n")
        with self.open(CAMPUS, "d") as pg:
            self._ready(pg, 5)
            node = self._node_id(pg, "#files-upload")
            pg.command("DOM.setFileInputFiles", {"nodeId": node, "files": [p1, p2]})
            pg.wait_for("document.querySelectorAll(%s).length === 7" % _q(ROWS))
            pg.wait_for("fetch('/api/v2/projects/campus-demo', {headers: {Accept: 'application/json'}}).then(function (r) { return r.json(); })"
                        " .then(function (p) { return (p.doc.attachments || []).length === 7; })")
            atts = {a["name"]: a for a in self._attachments()}
            self.assertIn("rider-notes.txt", atts)
            self.assertIn("stage-plot.csv", atts)
            self.assertFalse(atts["rider-notes.txt"].get("device"), "project uploads carry no device")
            self.assertEqual(atts["rider-notes.txt"]["kind"], "document")
            self.assertEqual(atts["stage-plot.csv"]["mime"], "text/csv")
            self.assertEqual(self._count(pg), "7 files")
            row = pg.js("(function () { var tds = document.querySelectorAll('#files-table tr[data-file=%s] td[data-col]');"
                        " return Array.prototype.map.call(tds, function (td) { return td.textContent; }); })()" % atts["rider-notes.txt"]["id"])
            self.assertEqual(row[:3], ["rider-notes.txt", "other", "Project"])

            # delete: confirm first; declining writes nothing
            pg.click("#files-table tr[data-file=%s] .dt-check-hit" % atts["rider-notes.txt"]["id"])
            pg.wait_for("document.querySelectorAll('#files-table tbody .dt-row-check:checked').length === 1")
            pg.click("#files-delete")
            pg.wait_for("!!document.querySelector('.app-dialog')")
            self.assertIn("Delete rider-notes.txt?", pg.js("document.querySelector('.app-dialog .body').textContent"))
            pg.press("Escape")
            pg.wait_for("!document.querySelector('.app-dialog')")
            self.assertEqual(len(self._attachments()), 7)
            pg.click("#files-delete")
            pg.wait_for("!!document.querySelector('.app-dialog')")
            pg.click(".app-dialog footer button:last-child")
            pg.wait_for("document.querySelectorAll(%s).length === 6" % _q(ROWS))
            pg.wait_for("fetch('/api/v2/projects/campus-demo', {headers: {Accept: 'application/json'}}).then(function (r) { return r.json(); })"
                        " .then(function (p) { return (p.doc.attachments || []).length === 6; })")
            self.assertNotIn("rider-notes.txt", [a["name"] for a in self._attachments()])
            self.assertEqual(pg.js("document.querySelectorAll('#files-table tbody .dt-row-check:checked').length"), 0)

    def test_viewer_lists_and_opens_only(self) -> None:
        url = self.base + "/api/v2/projects/campus-demo"
        body = json.loads(urllib.request.urlopen(url, timeout=10).read().decode())
        body["role"] = "viewer"
        with self.open(CAMPUS, "d", intercepts=[("/api/v2/projects/campus-demo", 200, body, "GET")]) as pg:
            self._ready(pg, 5)
            self.assertFalse(pg.js("!!document.getElementById('files-upload')"), "no Upload for viewers")
            self.assertFalse(pg.js("!!document.getElementById('files-delete')"), "no Delete for viewers")
            self.assertEqual(pg.js("document.querySelectorAll('#files-table .dt-check-hit').length"), 0, "no selection column")
            self.assertEqual(pg.js("document.querySelectorAll('#files-table a.files-name').length"), len(self._attachments()), "files still open")

    def test_phone_cards_upload_reachable_no_hscroll(self) -> None:
        with self.open(CAMPUS, "m") as pg:
            self._ready(pg, 5)
            self.assertLessEqual(pg.page_hscroll(), 0, "no horizontal page scroll at m")
            self.assertTrue(pg.js("document.querySelector('.files-root .dt-root').classList.contains('dt-cards')"))
            self.assertEqual(pg.js("getComputedStyle(document.querySelector(%s)).display" % _q(ROWS)), "block", "one card per file")
            shown = pg.js("Array.prototype.map.call(document.querySelectorAll(%s + ':first-child td[data-col]'), function (td) {"
                          " return getComputedStyle(td).display === 'none' ? null : td.getAttribute('data-col'); }).filter(Boolean)" % _q(ROWS))
            self.assertEqual(shown, ["name", "kind", "device", "size"], "cards show name, kind, device and size")
            self.assertEqual(pg.offscreen(".files-upload", "xy"), 0, "Upload is inside the viewport")
            r = pg.rect(".files-upload")
            self.assertGreaterEqual(r["height"], 44 - 0.5, "Upload is a 44px touch target")
            self.assertEqual(pg.js("getComputedStyle(document.querySelector('.files-uploadbox')).position"), "fixed", "Upload stays put while the list scrolls")
            for sel in ("#files-filter", "#files-kind", "#files-device"):
                self.assertEqual(pg.offscreen(sel, "x"), 0, "%s inside the viewport" % sel)
                self.assertGreaterEqual(pg.rect(sel)["height"], 44 - 0.5, "%s is a 44px target" % sel)
            self.assertEqual(pg.offscreen(ROWS + " .dt-check-hit", "x"), 0)
            pg.shot("files-m")


if __name__ == "__main__":  # pragma: no cover
    import unittest
    unittest.main()
