// js/rack-core.js: rack items, shelves, totals, rows, width and start_u
// (docs/notes/rackula.md contract sections B, C and D).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, clone } from './fixtures/helpers.mjs';

const { mod: rk, skip: absent, error } = await loadModule('js/rack-core.js', 'RJS');
const { mod: mc } = await loadModule('js/model-core.js', 'W5');
const skip = absent || (error ? 'rack-core.js failed to import' : false);
const T = (name, fn) => test(name, { skip }, fn);

if (error) test('rack-core.js imports in Node', () => { throw error; });

function apply(doc, ops) {
  return mc.applyOps(doc, ops).doc;
}

// 12U 19" rack R with optional items; devices are given as {id: rackValue}.
function mk(rackExtra, devs, extra) {
  const doc = {
    racks: [Object.assign({ id: 'R', name: 'Main', units: 12 }, rackExtra || {})],
    devices: [],
    templates: [],
  };
  for (const [id, r] of Object.entries(devs || {})) {
    doc.devices.push(Object.assign({ id: id, name: id.toUpperCase() }, r === null ? {} : { rack: Object.assign({ id: 'R' }, r) }));
  }
  return Object.assign(doc, extra || {});
}
const dev = (doc, id) => doc.devices.find((d) => d.id === id);
const rackOf = (doc, id) => doc.racks.find((r) => r.id === id);

// ------------------------------------------------------------------ constants

T('ITEM_TYPES matches the contract table, in order', () => {
  assert.deepEqual(rk.ITEM_TYPES.map((t) => Object.assign({}, t)), [
    { type: 'blank', label: 'Blank panel', height: 1, face: 'front', depth: 'half', color: '#44475a' },
    { type: 'vent', label: 'Vent panel', height: 1, face: 'front', depth: 'half', color: '#44475a' },
    { type: 'shelf', label: 'Shelf', height: 1, face: 'front', depth: 'full', color: '#6272a4', slots: 2 },
    { type: 'drawer', label: 'Drawer', height: 2, face: 'front', depth: 'full', color: '#6272a4' },
    { type: 'cable_manager', label: 'Cable manager', height: 1, face: 'front', depth: 'half', color: '#6272a4' },
    { type: 'brush', label: 'Brush panel', height: 1, face: 'front', depth: 'half', color: '#6272a4' },
    { type: 'lacing_bar', label: 'Lacing bar', height: 1, face: 'rear', depth: 'half', color: '#6272a4' },
    { type: 'other', label: 'Accessory', height: 1, face: 'front', depth: 'half', color: '#6272a4' },
  ]);
  assert.ok(Object.isFrozen(rk.ITEM_TYPES) && Object.isFrozen(rk.ITEM_TYPES[0]));
  assert.equal(rk.RACK_W, 320);
});

// --------------------------------------------------------- labels and width

T('ruLabel honours start_u and numbering', () => {
  const r = { units: 12 };
  assert.equal(rk.ruLabel(r, 1), '1');
  assert.equal(rk.ruLabel(r, 12), '12');
  assert.equal(rk.ruLabel({ units: 12, start_u: 0 }, 1), '0');
  assert.equal(rk.ruLabel({ units: 12, start_u: 0 }, 12), '11');
  assert.equal(rk.ruLabel({ units: 12, start_u: 5 }, 3), '7');
  assert.equal(rk.ruLabel({ units: 12, numbering: 'top_down' }, 12), '1');
  assert.equal(rk.ruLabel({ units: 12, numbering: 'top_down', start_u: 0 }, 12), '0');
  assert.equal(rk.ruLabel({ units: 12, numbering: 'top_down', start_u: 0 }, 1), '11');
  assert.equal(rk.ruLabel({ units: 12, numbering: 'top_down', start_u: 3 }, 10), '5');
  assert.equal(rk.ruLabel({ units: 12, start_u: -2 }, 1), '1', 'negative start_u falls back to 1');
  assert.equal(typeof rk.ruLabel(r, 4), 'string');
});

T('rackWidthPx scales 320 px by width_in / 19', () => {
  assert.equal(rk.rackWidthPx({}), 320);
  assert.equal(rk.rackWidthPx(null), 320);
  assert.equal(rk.rackWidthPx({ width_in: 10 }), 168);
  assert.equal(rk.rackWidthPx({ width_in: 19 }), 320);
  assert.equal(rk.rackWidthPx({ width_in: 21 }), 354);
  assert.equal(rk.rackWidthPx({ width_in: 23 }), 387);
  assert.equal(rk.rackWidthPx({ width_in: 15 }), 320, 'unsupported width reads as 19"');
});

T('faceBlocks scale half-width devices with the rack width', () => {
  const d = mk({ width_in: 23 }, { a: { u: 1, side: 'left' }, b: { u: 1, side: 'right' }, c: { u: 2 } });
  const by = Object.fromEntries(rk.faceBlocks(d, 'R', 'front').map((b) => [b.device, b]));
  assert.deepEqual([by.a.x, by.a.w], [0, 193]);
  assert.deepEqual([by.b.x, by.b.w], [193, 194]);
  assert.deepEqual([by.c.x, by.c.w], [0, 387]);
  const d19 = mk({}, { a: { u: 1, side: 'left' }, b: { u: 1, side: 'right' } });
  const b19 = rk.faceBlocks(d19, 'R', 'front');
  assert.deepEqual(b19.map((b) => [b.x, b.w]), [[0, 160], [160, 160]], '19" unchanged');
  assert.equal(rk.sideX('right'), 160);
  assert.equal(rk.sideW('left'), 160);
  assert.equal(rk.sideW('full'), 320);
});

// ------------------------------------------------------------------- items

T('rackItems fills defaults from ITEM_TYPES', () => {
  const d = mk({ items: [
    { id: 'ri-1', type: 'drawer', u: 3 },
    { id: 'ri-2', type: 'shelf', u: 5, slots: 9, label: 'Top shelf', color: '#112233', weight_kg: 2.5 },
    { id: 'ri-3', type: 'lacing_bar', u: 7, face: 'front', depth: 'full', height: 2 },
    { id: 'ri-4', type: 'mystery', u: 8, color: 'red' },
    { type: 'blank', u: 1 },
    'junk',
  ] });
  const items = rk.rackItems(d, 'R');
  assert.equal(items.length, 4, 'entries without an id are skipped');
  assert.deepEqual(items[0], { id: 'ri-1', type: 'drawer', u: 3, height: 2, face: 'front', depth: 'full', label: 'Drawer', color: '#6272a4', slots: null, weight_kg: null, notes: '' });
  assert.deepEqual([items[1].slots, items[1].label, items[1].color, items[1].weight_kg], [4, 'Top shelf', '#112233', 2.5]);
  assert.deepEqual([items[2].face, items[2].depth, items[2].height], ['front', 'full', 2]);
  assert.deepEqual([items[3].type, items[3].color, items[3].label], ['other', '#6272a4', 'Accessory']);
  assert.deepEqual(rk.rackItems(mk({ items: [{ id: 's', type: 'shelf', u: 1 }] }), 'R')[0].slots, 2);
  assert.deepEqual(rk.rackItems(mk(), 'R'), []);
  assert.deepEqual(rk.rackItems(mk(), 'nope'), []);
});

T('itemBlocks: faces, behind, geometry', () => {
  const d = mk({ items: [
    { id: 'b', type: 'blank', u: 1 },
    { id: 's', type: 'shelf', u: 4, slots: 3 },
    { id: 'l', type: 'lacing_bar', u: 12 },
  ] });
  const front = rk.itemBlocks(d, 'R', 'front');
  assert.deepEqual(front.map((b) => b.id), ['item:b', 'item:s']);
  assert.deepEqual(front[0], {
    id: 'item:b', item: 'b', type: 'blank', u: 1, height: 1, face: 'front', depth: 'half', label: 'Blank panel',
    color: '#44475a', slots: null, x: 0, y: 11 * 22, w: 320, h: 22, behind: false,
  });
  assert.equal(front[1].slots, 3);
  const rear = rk.itemBlocks(d, 'R', 'rear');
  assert.deepEqual(rear.map((b) => [b.id, b.behind]), [['item:s', true], ['item:l', false]], 'half-depth blank hidden on the rear; full-depth shelf behind');
  assert.equal(rear[1].y, 0);
  const narrow = mk({ width_in: 10, items: [{ id: 'd', type: 'drawer', u: 1 }] });
  const nb = rk.itemBlocks(narrow, 'R', 'front')[0];
  assert.deepEqual([nb.w, nb.h, nb.y], [168, 44, 10 * 22]);
  assert.deepEqual(rk.itemBlocks(d, 'nope', 'front'), []);
});

// -------------------------------------------------------- occupancy/collisions

T('occupancy counts items and skips shelf children', () => {
  const d = mk({ items: [{ id: 's', type: 'shelf', u: 2 }, { id: 'v', type: 'vent', u: 3 }] }, {
    kid: { u: 2, face: 'front', shelf: 's', slot: 0 },
    a: { u: 5, side: 'left' },
  });
  const f = rk.occupancy(d, 'R', 'front');
  assert.deepEqual(f[2], { left: 'item:s', right: 'item:s' });
  assert.deepEqual(f[3], { left: 'item:v', right: 'item:v' });
  assert.deepEqual(f[5], { left: 'a', right: null });
  const r = rk.occupancy(d, 'R', 'rear');
  assert.deepEqual(r[2], { left: 'item:s', right: 'item:s' }, 'full-depth shelf blocks the rear');
  assert.deepEqual(r[3], { left: null, right: null }, 'half-depth vent leaves the rear free');
});

T('collisions: device vs item on the front', () => {
  const d = mk({ items: [{ id: 'ri-1', type: 'blank', u: 4 }] }, { amp: { u: 4, depth: 'half' } });
  assert.deepEqual(rk.collisions(d, 'R'), [{ a: 'amp', b: 'item:ri-1', u: 4, face: 'front' }]);
});

T('collisions: half-depth item vs rear device do not collide', () => {
  const d = mk({ items: [{ id: 'ri-1', type: 'blank', u: 4 }] }, { psu: { u: 4, face: 'rear', depth: 'half' } });
  assert.deepEqual(rk.collisions(d, 'R'), []);
});

T('collisions: full-depth shelf vs rear device collide on the rear', () => {
  const d = mk({ items: [{ id: 'ri-1', type: 'shelf', u: 4 }] }, { psu: { u: 4, face: 'rear', depth: 'half' } });
  assert.deepEqual(rk.collisions(d, 'R'), [{ a: 'item:ri-1', b: 'psu', u: 4, face: 'rear' }]);
});

T('collisions: half-width devices vs a full-width item, ordered and sorted', () => {
  const d = mk({ items: [{ id: 'ri-1', type: 'drawer', u: 6 }] }, {
    zz: { u: 7, side: 'right', depth: 'half' },
    aa: { u: 6, side: 'left', depth: 'half' },
  });
  assert.deepEqual(rk.collisions(d, 'R'), [
    { a: 'aa', b: 'item:ri-1', u: 6, face: 'front' },
    { a: 'item:ri-1', b: 'zz', u: 7, face: 'front' },
  ]);
  const both = mk({}, { b: { u: 3, height: 2 }, a: { u: 4 } });
  assert.deepEqual(rk.collisions(both, 'R'), [
    { a: 'a', b: 'b', u: 4, face: 'front' },
    { a: 'a', b: 'b', u: 4, face: 'rear' },
  ], 'full-depth pair: one entry per face, lowest overlapping RU');
});

T('collisions and faceBlocks leave shelf children out', () => {
  const d = mk({ items: [{ id: 's', type: 'shelf', u: 2, slots: 2 }] }, {
    k1: { u: 2, shelf: 's', slot: 0 },
    k2: { u: 2, shelf: 's', slot: 0 },
    over: { u: 9, shelf: 'gone', slot: 0 },
  });
  assert.deepEqual(rk.collisions(d, 'R'), []);
  assert.deepEqual(rk.faceBlocks(d, 'R', 'front'), []);
  assert.deepEqual(rk.outOfRange(mk({ units: 4 }, { k: { u: 9, shelf: 's', slot: 0 } }), 'R'), []);
  assert.deepEqual(rk.rackDevices(d, 'R').map((p) => [p.device, p.shelf, p.slot]), [['k1', 's', 0], ['k2', 's', 0], ['over', 'gone', 0]], 'rackDevices keeps shelf children, marked');
});

T('placement adds shelf, slot and color', () => {
  const d = mk({}, { a: { u: 1, shelf: 's', slot: 1, color: '#abcdef' }, b: { u: 2, color: 'blue', slot: -1 } });
  const p = rk.placement(d, dev(d, 'a'));
  assert.deepEqual([p.shelf, p.slot, p.color], ['s', 1, '#abcdef']);
  const q = rk.placement(d, dev(d, 'b'));
  assert.deepEqual([q.shelf, q.slot, q.color], ['', null, '']);
});

// ----------------------------------------------------------------------- fits

T('fits and firstFit count items', () => {
  const d = mk({ items: [{ id: 'ri-1', type: 'blank', u: 12 }, { id: 'ri-2', type: 'shelf', u: 10 }] }, {
    a: { u: 10, face: 'rear', depth: 'half' },
    x: null,
  });
  const f = rk.fits(d, 'R', 'x', 10, { height: 1, side: 'full' });
  assert.deepEqual(f, { ok: false, reason: 'occupied', conflicts: ['a', 'item:ri-2'] }, 'devices first, then items');
  assert.deepEqual(rk.fits(d, 'R', 'x', 12, { depth: 'half', face: 'rear' }), { ok: true, reason: '', conflicts: [] }, 'half-depth rear device beside a front blank');
  assert.equal(rk.firstFit(d, 'R', 'x', { height: 1 }), 11);
  assert.equal(rk.firstFit(d, 'R', 'x', { height: 2 }), 8);
});

T('itemFits reasons and defaults', () => {
  const d = mk({ items: [{ id: 'ri-1', type: 'drawer', u: 5 }] }, { amp: { u: 1, face: 'rear', depth: 'half' } });
  assert.deepEqual(rk.itemFits(d, 'nope', null, 1, { type: 'blank' }), { ok: false, reason: 'rack_unknown', conflicts: [] });
  assert.deepEqual(rk.itemFits(d, 'R', null, 0, { type: 'blank' }), { ok: false, reason: 'out_of_range', conflicts: [] });
  assert.deepEqual(rk.itemFits(d, 'R', null, 12, { type: 'drawer' }), { ok: false, reason: 'out_of_range', conflicts: [] }, 'drawer default height 2');
  assert.deepEqual(rk.itemFits(d, 'R', null, 6, { type: 'blank' }), { ok: false, reason: 'occupied', conflicts: ['item:ri-1'] });
  assert.deepEqual(rk.itemFits(d, 'R', null, 1, { type: 'blank' }), { ok: true, reason: '', conflicts: [] }, 'front half-depth blank vs rear half-depth device');
  assert.deepEqual(rk.itemFits(d, 'R', null, 1, { type: 'shelf' }), { ok: false, reason: 'occupied', conflicts: ['amp'] }, 'full-depth shelf vs rear device');
  assert.deepEqual(rk.itemFits(d, 'R', null, 1, { type: 'blank', face: 'rear' }), { ok: false, reason: 'occupied', conflicts: ['amp'] });
  assert.equal(rk.itemFits(d, 'R', 'ri-1', 4, {}).ok, true, 'an item does not collide with itself');
  assert.equal(rk.itemFits(d, 'R', 'ri-1', 11, {}).ok, true, 'existing item keeps its height (2U at 11-12)');
  assert.equal(rk.itemFits(d, 'R', 'ri-1', 12, {}).reason, 'out_of_range');
  assert.equal(rk.itemFits(d, 'R', 'ri-1', 12, { height: 1 }).ok, true, 'spec overrides the item');
});

// -------------------------------------------------------------------- shelves

T('shelfCells: occupied cells, out-of-range slots, two devices in a cell', () => {
  const d = mk({ items: [{ id: 's', type: 'shelf', u: 3, slots: 3 }, { id: 'b', type: 'blank', u: 1 }] }, {
    first: { u: 3, shelf: 's', slot: 1 },
    second: { u: 3, shelf: 's', slot: 1 },
    far: { u: 3, shelf: 's', slot: 3 },
    neg: { u: 3, shelf: 's', slot: -1 },
    none: { u: 3, shelf: 's' },
    zero: { u: 3, shelf: 's', slot: 0 },
  });
  assert.deepEqual(rk.shelfCells(d, 'R', 's'), [
    { slot: 0, device: 'zero' }, { slot: 1, device: 'first' }, { slot: 2, device: null },
  ]);
  assert.deepEqual(rk.shelfCells(d, 'R', 'b'), [], 'not a shelf');
  assert.deepEqual(rk.shelfCells(d, 'R', 'zz'), []);
  assert.deepEqual(rk.shelfCells(mk({ items: [{ id: 's', type: 'shelf', u: 1 }] }), 'R', 's'), [{ slot: 0, device: null }, { slot: 1, device: null }]);
});

T('shelfChildBlocks: cell geometry and faces', () => {
  const d = mk({ width_in: 10, items: [{ id: 's', type: 'shelf', u: 2, slots: 2 }, { id: 'h', type: 'shelf', u: 5, depth: 'half', face: 'rear', slots: 4 }] }, {
    left: { u: 2, shelf: 's', slot: 0 },
    right: { u: 2, shelf: 's', slot: 1 },
    back: { u: 5, shelf: 'h', slot: 3 },
  });
  assert.deepEqual(rk.shelfChildBlocks(d, 'R', 'front'), [
    { device: 'left', item: 's', slot: 0, x: 0, y: 10 * 22, w: 84, h: 22, behind: false },
    { device: 'right', item: 's', slot: 1, x: 84, y: 10 * 22, w: 84, h: 22, behind: false },
  ]);
  const rear = rk.shelfChildBlocks(d, 'R', 'rear');
  assert.deepEqual(rear.map((b) => [b.device, b.x, b.w, b.behind]), [['left', 0, 84, true], ['right', 84, 84, true], ['back', 126, 42, false]]);
});

// --------------------------------------------------------------------- totals

T('rackTotals: weights, power, templates, info, rounding', () => {
  const d = mk({ weight_kg: 20.05, max_load_kg: 100, power_limit_w: 1800, items: [
    { id: 's', type: 'shelf', u: 1, weight_kg: 1.2 },
    { id: 'b', type: 'blank', u: 12 },
    { id: 'd', type: 'drawer', u: 5, weight_kg: 3 },
  ] }, {
    own: { u: 8, height: 2 },
    tpl: { u: 10 },
    inf: { u: 11, side: 'left' },
    zero: { u: 11, side: 'right' },
    kid: { u: 1, shelf: 's', slot: 0 },
    other: null,
  }, { templates: [{ id: 't-amp', weight_kg: 7.33, power_w: 350.04 }] });
  Object.assign(dev(d, 'own'), { weight_kg: 10.11, power_w: 100.2 });
  dev(d, 'tpl').template = 't-amp';
  dev(d, 'inf').template = 't-info';
  Object.assign(dev(d, 'zero'), { template: 't-amp', weight_kg: 0, power_w: 0 });
  Object.assign(dev(d, 'kid'), { weight_kg: 0.25 });
  Object.assign(dev(d, 'other'), { weight_kg: 999 });
  const info = { 't-info': { weight_kg: 2, power_w: 15.5 }, 't-amp': { weight_kg: 1000, power_w: 1000 } };
  assert.deepEqual(rk.rackTotals(d, 'R', info), {
    units: 12, used_u: 8, free_u: 4,
    weight_kg: 43.9, // 20.05 + 10.11 + 7.33 + 2 + 0 + 0.25 + 1.2 + 3 = 43.94
    max_load_kg: 100, power_w: 465.7, power_limit_w: 1800, devices: 5, items: 3,
  });
  const t = rk.rackTotals(mk({}, { a: { u: 1 } }), 'R');
  assert.deepEqual(t, { units: 12, used_u: 1, free_u: 11, weight_kg: 0, max_load_kg: null, power_w: 0, power_limit_w: null, devices: 1, items: 0 });
  assert.equal(rk.rackTotals(mk({ weight_kg: 0.25 }), 'R').weight_kg, 0.2, 'ties round half-even like Python');
  assert.equal(rk.rackTotals(mk({ weight_kg: 0.75 }), 'R').weight_kg, 0.8);
  assert.equal(rk.rackTotals(mk({ weight_kg: 1.15 }), 'R').weight_kg, 1.1, '1.15 is just below the tie in binary');
  assert.equal(rk.rackTotals(mk({ items: [{ id: 'x', type: 'blank', u: 20 }] }), 'R').used_u, 0, 'out-of-range RUs are not counted');
  assert.equal(rk.rackTotals(mk(), 'nope'), null);
});

T('racksByRow groups by row at the first rack position', () => {
  const racks = [
    { id: 'e', name: 'E', order: 5 },
    { id: 'b2', name: 'B2', row: 'Row B', order: 4 },
    { id: 'a', name: 'A', order: 1, row: 'Row A' },
    { id: 'none', name: 'Zed' },
    { id: 'c', name: 'C', order: 2 },
    { id: 'b1', name: 'B1', row: 'Row B', order: 3 },
    { id: 'a2', name: 'A0', row: 'Row A' },
    { id: 'n2', name: 'Alpha' },
  ];
  const groups = rk.racksByRow(racks);
  assert.deepEqual(groups.map((g) => [g.row, g.racks.map((r) => r.id)]), [
    ['Row A', ['a', 'a2']],
    ['', ['c']],
    ['Row B', ['b1', 'b2']],
    ['', ['e']],
    ['', ['n2']],
    ['', ['none']],
  ]);
  assert.deepEqual(rk.racksByRow([]), []);
  assert.deepEqual(rk.racksByRow(null), []);
  assert.deepEqual(rk.racksByRow([{ id: 'x', name: 'b', order: 1 }, { id: 'y', name: 'B', order: 1 }]).map((g) => g.racks[0].id), ['y', 'x'], 'names compare by code unit');
});

// ------------------------------------------------------------------- item ops

T('addItemOps: smallest unused ri-n, first fit from the top, op shape', () => {
  const d = mk({ items: [{ id: 'ri-1', type: 'blank', u: 12 }, { id: 'ri-3', type: 'vent', u: 11 }, { id: 'x', type: 'brush', u: 9 }] });
  const before = clone(d);
  const r = rk.addItemOps(d, 'R', { type: 'blank' });
  assert.equal(r.id, 'ri-2');
  assert.deepEqual(r.ops, [{ op: 'merge', coll: 'racks', id: 'R', value: { items: [
    { id: 'ri-1', type: 'blank', u: 12 }, { id: 'ri-3', type: 'vent', u: 11 }, { id: 'x', type: 'brush', u: 9 },
    { id: 'ri-2', type: 'blank', u: 10, height: 1, face: 'front', depth: 'half' },
  ] } }]);
  assert.deepEqual(d, before, 'input doc untouched');
  const d2 = apply(d, r.ops);
  assert.equal(rk.addItemOps(d2, 'R', { type: 'blank' }).id, 'ri-4');
  const sh = rk.addItemOps(mk(), 'R', { type: 'shelf', label: 'Tray', color: '#123456', weight_kg: 1.5, notes: 'n' });
  assert.equal(sh.id, 'ri-1');
  assert.deepEqual(sh.ops[0].value.items[0], { id: 'ri-1', type: 'shelf', u: 12, height: 1, face: 'front', depth: 'full', label: 'Tray', color: '#123456', slots: 2, weight_kg: 1.5, notes: 'n' });
  assert.equal(rk.addItemOps(mk(), 'R', { type: 'drawer' }).ops[0].value.items[0].u, 11, '2U drawer from the top');
  assert.equal(rk.addItemOps(mk(), 'R', { type: 'shelf', slots: 7 }).ops[0].value.items[0].slots, 4);
});

T('addItemOps: explicit u, refusals', () => {
  const d = mk({ units: 2 }, { a: { u: 2 } });
  assert.equal(rk.addItemOps(d, 'R', { type: 'blank', u: 1 }).ops[0].value.items[0].u, 1);
  assert.deepEqual(rk.addItemOps(d, 'R', { type: 'blank', u: 2 }), { ops: [], id: '' }, 'explicit u that collides');
  assert.equal(rk.addItemOps(d, 'R', { type: 'blank', u: 2, force: true }).id, 'ri-1', 'force places onto an occupied RU');
  assert.deepEqual(rk.addItemOps(d, 'R', { type: 'blank', u: 3, force: true }), { ops: [], id: '' }, 'out of range even with force');
  assert.deepEqual(rk.addItemOps(d, 'R', { type: 'drawer' }), { ops: [], id: '' }, 'nothing fits');
  assert.deepEqual(rk.addItemOps(d, 'R', { type: 'spaceship' }), { ops: [], id: '' });
  assert.deepEqual(rk.addItemOps(d, 'nope', { type: 'blank' }), { ops: [], id: '' });
  assert.equal(rk.addItemOps(d, 'R', { type: 'blank', face: 'rear', depth: 'half', u: 2 }).id, '', 'full-depth device blocks the rear');
});

T('moveItemOps refuses collisions unless force; shelf children follow', () => {
  const d = mk({ items: [{ id: 's', type: 'shelf', u: 2 }, { id: 'b', type: 'blank', u: 8 }] }, {
    a: { u: 6 },
    k: { u: 2, face: 'front', shelf: 's', slot: 1 },
  });
  assert.deepEqual(rk.moveItemOps(d, 'R', 's', 6), [], 'collides with a');
  assert.deepEqual(rk.moveItemOps(d, 'R', 's', 13, { force: true }), [], 'out of range');
  assert.deepEqual(rk.moveItemOps(d, 'R', 'zz', 3), []);
  const forced = rk.moveItemOps(d, 'R', 's', 6, { force: true });
  assert.equal(forced[0].value.items[0].u, 6);
  const ops = rk.moveItemOps(d, 'R', 's', 4, { face: 'rear' });
  assert.deepEqual(ops, [
    { op: 'merge', coll: 'racks', id: 'R', value: { items: [{ id: 's', type: 'shelf', u: 4, face: 'rear' }, { id: 'b', type: 'blank', u: 8 }] } },
    { op: 'merge', coll: 'devices', id: 'k', value: { rack: { u: 4, face: 'rear' } } },
  ]);
  const d2 = apply(d, ops);
  assert.deepEqual(dev(d2, 'k').rack, { id: 'R', u: 4, face: 'rear', shelf: 's', slot: 1 });
  assert.deepEqual(rk.shelfCells(d2, 'R', 's')[1], { slot: 1, device: 'k' });
  assert.equal(rk.moveItemOps(d, 'R', 'b', 9).length, 1, 'non-shelf move is one op');
});

T('updateItemOps patches the item; lost cells unrack their devices', () => {
  const d = mk({ items: [{ id: 's', type: 'shelf', u: 2, slots: 3, label: 'Old' }] }, {
    k0: { u: 2, shelf: 's', slot: 0 },
    k2: { u: 2, shelf: 's', slot: 2 },
    bad: { u: 2, shelf: 's', slot: 7 },
  });
  const ops = rk.updateItemOps(d, 'R', 's', { label: null, color: '#ffffff', id: 'hijack', slots: 2 });
  assert.deepEqual(ops, [
    { op: 'merge', coll: 'racks', id: 'R', value: { items: [{ id: 's', type: 'shelf', u: 2, slots: 2, color: '#ffffff' }] } },
    { op: 'merge', coll: 'devices', id: 'k2', value: { rack: null } },
  ]);
  const moved = rk.updateItemOps(d, 'R', 's', { u: 5 });
  assert.deepEqual(moved.slice(1).map((o) => [o.id, o.value.rack]), [['k0', { u: 5, face: 'front' }], ['k2', { u: 5, face: 'front' }], ['bad', { u: 5, face: 'front' }]]);
  const retyped = rk.updateItemOps(d, 'R', 's', { type: 'blank' });
  assert.deepEqual(retyped.slice(1).map((o) => [o.id, o.value.rack]), [['k0', null], ['k2', null], ['bad', null]]);
  assert.deepEqual(rk.updateItemOps(d, 'R', 'zz', { u: 1 }), []);
  const blank = mk({ items: [{ id: 'b', type: 'blank', u: 1 }] });
  assert.deepEqual(rk.updateItemOps(blank, 'R', 'b', { notes: 'x' }), [{ op: 'merge', coll: 'racks', id: 'R', value: { items: [{ id: 'b', type: 'blank', u: 1, notes: 'x' }] } }]);
});

T('delItemOps: deleting a shelf unracks its children', () => {
  const d = mk({ items: [{ id: 'b', type: 'blank', u: 1 }, { id: 's', type: 'shelf', u: 2 }] }, {
    k: { u: 2, shelf: 's', slot: 0 },
    a: { u: 5 },
  });
  const ops = rk.delItemOps(d, 'R', 's');
  assert.deepEqual(ops, [
    { op: 'merge', coll: 'racks', id: 'R', value: { items: [{ id: 'b', type: 'blank', u: 1 }] } },
    { op: 'merge', coll: 'devices', id: 'k', value: { rack: null } },
  ]);
  const d2 = apply(d, ops);
  assert.equal(dev(d2, 'k').rack, undefined);
  assert.deepEqual(dev(d2, 'a').rack, { id: 'R', u: 5 });
  assert.deepEqual(rk.delItemOps(d, 'R', 'b'), [{ op: 'merge', coll: 'racks', id: 'R', value: { items: [{ id: 's', type: 'shelf', u: 2 }] } }]);
  assert.deepEqual(rk.delItemOps(d, 'R', 'zz'), []);
});

T('placeOnShelfOps: exact op and refusals', () => {
  const d = mk({ items: [{ id: 's', type: 'shelf', u: 7, face: 'rear', slots: 2 }, { id: 'b', type: 'blank', u: 1 }] }, {
    k: { u: 7, shelf: 's', slot: 0 },
    x: null,
    y: { u: 3, depth: 'half' },
  });
  assert.deepEqual(rk.placeOnShelfOps(d, 'x', 'R', 's', 1), [
    { op: 'merge', coll: 'devices', id: 'x', value: { rack: { id: 'R', u: 7, height: 1, face: 'rear', side: 'full', shelf: 's', slot: 1 } } },
  ]);
  assert.deepEqual(rk.placeOnShelfOps(d, 'x', 'R', 's', 0), [], 'cell occupied');
  assert.equal(rk.placeOnShelfOps(d, 'k', 'R', 's', 0).length, 1, 'a device may be re-placed on its own cell');
  assert.deepEqual(rk.placeOnShelfOps(d, 'x', 'R', 's', 2), [], 'slot out of range');
  assert.deepEqual(rk.placeOnShelfOps(d, 'x', 'R', 's', -1), []);
  assert.deepEqual(rk.placeOnShelfOps(d, 'x', 'R', 'b', 0), [], 'not a shelf');
  assert.deepEqual(rk.placeOnShelfOps(d, 'ghost', 'R', 's', 1), []);
  const d2 = apply(d, rk.placeOnShelfOps(d, 'y', 'R', 's', 1));
  assert.deepEqual(rk.collisions(d2, 'R'), []);
  assert.deepEqual(rk.shelfCells(d2, 'R', 's').map((c) => c.device), ['k', 'y']);
  const back = rk.placeOps(d2, 'y', 'R', 3, {});
  assert.deepEqual(back[0].value.rack, { id: 'R', u: 3, height: 1, face: 'rear', side: 'full', depth: 'half', shelf: null, slot: null }, 'placeOps clears shelf/slot');
  assert.equal(apply(d2, back).devices.find((x) => x.id === 'y').rack.shelf, undefined);
  assert.deepEqual(rk.placeOps(d, 'x', 'R', 4, {})[0].value.rack, { id: 'R', u: 4, height: 1, face: 'front', side: 'full' }, 'unchanged for plain devices');
});

// ------------------------------------------------------------ duplicate ops

T('duplicateDeviceOps strips identity fields and places at the first fit', () => {
  const d = mk({ units: 4 }, { amp: { u: 1, height: 2, depth: 'half', color: '#010203' } });
  Object.assign(dev(d, 'amp'), {
    name: 'Amp', kind: 'amp', code: 'A1', merged_from: ['old'], patch: { x: 10, y: 20 }, note: 'keep',
    inventory: { serial: 'S1', asset_tag: 'T1', purchase: '2024' },
    interfaces: [{ name: 'eth0', ip: '10.0.0.5', mac: 'aa', hostname: 'amp', vlan: 10, role: 'primary' }],
    ports: [{ id: 'in-1', name: 'In 1' }],
  });
  d.devices.push({ id: 'amp-2', name: 'Other' });
  const before = clone(d);
  const r = rk.duplicateDeviceOps(d, 'amp');
  assert.equal(r.id, 'amp-3', 'slug of the name, deduped');
  assert.equal(r.ops.length, 1);
  assert.deepEqual(r.ops[0], { op: 'put', coll: 'devices', id: 'amp-3', value: {
    id: 'amp-3', name: 'Amp (copy)', kind: 'amp', code: 'A1', note: 'keep',
    rack: { id: 'R', u: 3, height: 2, face: 'front', side: 'full', depth: 'half', color: '#010203' },
    inventory: { purchase: '2024' },
    interfaces: [{ name: 'eth0', vlan: 10, role: 'primary' }],
    ports: [{ id: 'in-1', name: 'In 1' }],
  } });
  assert.deepEqual(d, before, 'input doc untouched');
  const full = apply(d, r.ops);
  assert.equal(rk.duplicateDeviceOps(full, 'amp').ops[0].value.rack, undefined, 'unracked when nothing fits');
  assert.equal(rk.duplicateDeviceOps(full, 'amp').id, 'amp-4');
  assert.deepEqual(rk.duplicateDeviceOps(d, 'amp', { taken: { 'amp-3': true } }).id, 'amp-4');
  assert.deepEqual(rk.duplicateDeviceOps(d, 'ghost'), { ops: [], id: '' });
  const loose = mk({}, { loose: null });
  assert.equal(rk.duplicateDeviceOps(loose, 'loose').ops[0].value.rack, undefined, 'unracked original stays unracked');
});

T('duplicateDeviceOps: rackId override and shelf children', () => {
  const d = mk({ items: [{ id: 's', type: 'shelf', u: 12, slots: 2 }] }, { k: { u: 12, shelf: 's', slot: 0 } });
  d.racks.push({ id: 'R2', name: 'Two', units: 3, items: [{ id: 'b', type: 'blank', u: 3 }] });
  const same = rk.duplicateDeviceOps(d, 'k');
  assert.deepEqual(same.ops[0].value.rack, { id: 'R', u: 12, face: 'front', shelf: 's', slot: 1 }, 'next free cell on the same shelf');
  const d2 = apply(d, same.ops);
  const full = rk.duplicateDeviceOps(d2, 'k').ops[0].value.rack;
  assert.deepEqual(full, { id: 'R', u: 11, height: 1, face: 'front', side: 'full' }, 'shelf full: first rack-level fit');
  const other = rk.duplicateDeviceOps(d, 'k', { rackId: 'R2' }).ops[0].value.rack;
  assert.deepEqual(other, { id: 'R2', u: 2, height: 1, face: 'front', side: 'full' });
  const explicit = rk.duplicateDeviceOps(d, 'k', { rack: null }).ops[0].value;
  assert.equal(explicit.rack, undefined);
});

T('duplicateRackOps copies the rack and, with devices, keeps positions', () => {
  const d = mk({ name: 'FOH rack', order: 2, row: 'A', items: [{ id: 's', type: 'shelf', u: 3 }, { id: 'b', type: 'blank', u: 1 }] }, {
    amp: { u: 5, height: 2 },
    kid: { u: 3, shelf: 's', slot: 1 },
    elsewhere: null,
  });
  d.racks.push({ id: 'rk-foh-rack-copy', name: 'Taken', units: 4 });
  const before = clone(d);
  const bare = rk.duplicateRackOps(d, 'R');
  assert.equal(bare.id, 'rk-foh-rack-copy-2');
  assert.deepEqual(bare.ops, [{ op: 'put', coll: 'racks', id: 'rk-foh-rack-copy-2', value: Object.assign(clone(rackOf(d, 'R')), { id: 'rk-foh-rack-copy-2', name: 'FOH rack (copy)' }) }]);
  const r = rk.duplicateRackOps(d, 'R', { devices: true });
  assert.deepEqual(d, before, 'input doc untouched');
  assert.deepEqual(r.ops.map((o) => [o.op, o.coll, o.id]), [
    ['put', 'racks', 'rk-foh-rack-copy-2'], ['put', 'devices', 'amp-2'], ['put', 'devices', 'kid-2'],
  ]);
  const d2 = apply(d, r.ops);
  assert.deepEqual(dev(d2, 'amp-2').rack, { id: 'rk-foh-rack-copy-2', u: 5, height: 2 });
  assert.deepEqual(dev(d2, 'kid-2').rack, { id: 'rk-foh-rack-copy-2', u: 3, shelf: 's', slot: 1 });
  assert.deepEqual(rk.collisions(d2, 'rk-foh-rack-copy-2'), []);
  assert.deepEqual(rk.shelfCells(d2, 'rk-foh-rack-copy-2', 's'), [{ slot: 0, device: null }, { slot: 1, device: 'kid-2' }]);
  assert.deepEqual(rk.faceBlocks(d2, 'rk-foh-rack-copy-2', 'front').map((b) => [b.device, b.u]), [['amp-2', 5]]);
  const twins = mk({}, { 'x': { u: 1 } });
  twins.devices.push({ id: 'y', name: 'X', rack: { id: 'R', u: 2 } });
  const tw = rk.duplicateRackOps(twins, 'R', { devices: true });
  assert.deepEqual(tw.ops.slice(1).map((o) => o.id), ['x-2', 'x-3'], 'copied ids dedupe against each other');
  assert.deepEqual(rk.duplicateRackOps(d, 'nope', { devices: true }), { ops: [], id: '' });
});

T('docs without the new fields behave as before', () => {
  const d = mk({}, { a: { u: 1 }, b: { u: 1 } });
  assert.deepEqual(rk.collisions(d, 'R'), [{ a: 'a', b: 'b', u: 1, face: 'front' }, { a: 'a', b: 'b', u: 1, face: 'rear' }]);
  assert.deepEqual(rk.fits(d, 'R', 'a', 2, {}), { ok: true, reason: '', conflicts: [] });
  assert.equal(rk.firstFit(d, 'R', 'a', {}), 12);
  const fb = rk.faceBlocks(d, 'R', 'front')[0];
  assert.deepEqual([fb.x, fb.y, fb.w, fb.h, fb.behind], [0, 11 * 22, 320, 22, false]);
  assert.deepEqual(rk.newRackOps(d, { name: 'Main' }).id, 'rk-main');
  assert.deepEqual(rk.deleteRackOps(d, 'R').length, 3);
});
