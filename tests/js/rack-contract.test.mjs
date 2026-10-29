// Rack contract (docs/SPEC.md §4.3.7, §4.4.7) against js/rack-core.js and js/rack-display-core.js.
// Data-driven from tests/fixtures/rack_contract.json, shared with tests/test_rack_contract.py.
// One test per case and expect key; a test skips only while the export it exercises is missing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import * as core from '../../fathom/static/js/rack-core.js';

const FIXTURE = fileURLToPath(new URL('../fixtures/rack_contract.json', import.meta.url));
const DISPLAY_URL = new URL('../../fathom/static/js/rack-display-core.js', import.meta.url);
const CASES = JSON.parse(readFileSync(FIXTURE, 'utf8')).cases;
const PY_ONLY = ['problems'];

// A missing module skips; a module that exists but fails to load fails the annotation tests.
const displayP = existsSync(fileURLToPath(DISPLAY_URL)) ? import(DISPLAY_URL.href) : Promise.resolve(null);

// ruLabel, collisions and fits predate the items contract; their new semantics land with ITEM_TYPES.
const ITEMS_AWARE = ['ruLabel', 'collisions', 'fits'];

function missing(name) {
  if (typeof core[name] !== 'function') return 'awaiting ' + name;
  if (ITEMS_AWARE.indexOf(name) >= 0 && !Array.isArray(core.ITEM_TYPES)) return 'awaiting ITEM_TYPES (items-aware ' + name + ')';
  return '';
}

const clone = (v) => JSON.parse(JSON.stringify(v));
const rackOf = (doc, id) => doc.racks.filter((r) => r.id === id)[0];
const deviceOf = (doc, id) => doc.devices.filter((d) => d.id === id)[0];
const cellDevice = (v) => (v && typeof v === 'object' ? v.id || v.device : v);
const sorted = (a) => a.slice().sort();

const CHECKS = {
  labels(t, c, exp) {
    const why = missing('ruLabel');
    if (why) return t.skip(why);
    const rack = rackOf(c.doc, c.rack);
    Object.keys(exp).forEach((u) => assert.equal(core.ruLabel(rack, parseInt(u, 10)), exp[u], 'U' + u));
  },
  width_px(t, c, exp) {
    const why = missing('rackWidthPx');
    if (why) return t.skip(why);
    assert.equal(core.rackWidthPx(rackOf(c.doc, c.rack)), exp);
  },
  collisions(t, c, exp) {
    const why = missing('collisions');
    if (why) return t.skip(why);
    assert.deepEqual(core.collisions(c.doc, c.rack).map((x) => ({a: x.a, b: x.b, u: x.u, face: x.face})), exp);
  },
  fits(t, c, exp) {
    const whyDev = missing('fits');
    const whyItem = missing('itemFits');
    if (whyDev && whyItem) return t.skip(whyDev + ', ' + whyItem.replace('awaiting ', ''));
    let checked = 0;
    exp.forEach((e) => {
      const rackId = e.rack || c.rack;
      let got;
      if ('item' in e) {
        if (whyItem) return;
        got = core.itemFits(c.doc, rackId, e.item, e.u, e.spec || {});
      } else {
        if (whyDev) return;
        got = core.fits(c.doc, rackId, e.device, e.u, e.opts || {});
      }
      checked++;
      const label = JSON.stringify(e);
      assert.equal(got.ok, e.ok, label);
      assert.equal(got.reason, e.reason, label);
      assert.deepEqual(sorted(got.conflicts), sorted(e.conflicts), label);
    });
    if (whyDev || whyItem) t.diagnostic('partial: ' + (whyDev || whyItem) + ' (' + checked + ' entries checked)');
  },
  shelf(t, c, exp) {
    const why = missing('shelfCells');
    if (why) return t.skip(why);
    const got = core.shelfCells(c.doc, c.rack, exp.item).map((x) => ({slot: x.slot, device: cellDevice(x.device)}));
    assert.deepEqual(got, exp.cells);
  },
  totals(t, c, exp) {
    const why = missing('rackTotals');
    if (why) return t.skip(why);
    const got = core.rackTotals(c.doc, c.rack);
    Object.keys(exp).forEach((k) => {
      assert.ok(k in got, 'missing ' + k);
      if (exp[k] === null) assert.equal(got[k], null, k);
      else assert.ok(Math.abs(got[k] - exp[k]) < 1e-9, k + ': ' + got[k] + ' != ' + exp[k]);
    });
  },
  rows(t, c, exp) {
    const why = missing('racksByRow');
    if (why) return t.skip(why);
    assert.deepEqual(core.racksByRow(c.doc.racks).map((g) => g.racks.map((r) => r.id)), exp);
  },
  add_item(t, c, exp) {
    const why = missing('addItemOps');
    if (why) return t.skip(why);
    const before = (rackOf(c.doc, c.rack).items || []).length;
    const res = core.addItemOps(c.doc, c.rack, exp.spec);
    assert.equal(res.id, exp.id);
    if (exp.u === null) {
      assert.deepEqual(res.ops, []);
      return;
    }
    const op = res.ops.filter((o) => o.coll === 'racks')[0];
    assert.ok(op, 'a racks op');
    assert.equal(op.op, 'merge');
    assert.equal(op.id, c.rack);
    assert.equal(op.value.items.length, before + 1, 'whole items array');
    const item = op.value.items.filter((x) => x.id === exp.id)[0];
    assert.ok(item, 'new item in the merged array');
    assert.equal(item.u, exp.u);
    assert.equal(item.type, exp.spec.type);
  },
  async annotations(t, c, exp) {
    const disp = await displayP;
    if (!disp || typeof disp.annotationValue !== 'function') return t.skip('awaiting annotationValue');
    Object.keys(exp).forEach((id) => {
      const dev = deviceOf(c.doc, id);
      Object.keys(exp[id]).forEach((field) => {
        assert.equal(disp.annotationValue(c.doc, dev, field), exp[id][field], id + '.' + field);
      });
    });
  },
};

test('rack contract fixture has >= 14 named cases', () => {
  assert.ok(CASES.length >= 14);
  const names = CASES.map((c) => c.name);
  assert.equal(new Set(names).size, names.length);
  CASES.forEach((c) => {
    assert.ok(rackOf(c.doc, c.rack), c.name + ': rack');
    Object.keys(c.expect).forEach((k) => assert.ok(k in CHECKS || PY_ONLY.indexOf(k) >= 0, c.name + ': unknown expect key ' + k));
  });
});

CASES.forEach((c) => {
  Object.keys(c.expect).forEach((key) => {
    if (PY_ONLY.indexOf(key) >= 0) return;
    test(c.name + ': ' + key, (t) => CHECKS[key](t, clone(c), c.expect[key]));
  });
});
