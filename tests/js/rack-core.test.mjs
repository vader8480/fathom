// T2: js/rack-core.js (W4) against SPEC §6.7, FR-RACK-02/04/05, §4.3.7.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadFixtureDoc, clone, norm, m, need, device } from './fixtures/helpers.mjs';

const { mod: rk, skip: absent, error } = await loadModule('js/rack-core.js', 'W4');
const mcL = await loadModule('js/model-core.js', 'W5');
const S = '§6.7';
const skip = absent || (error ? 'rack-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);

if (error) test('rack-core.js imports in Node (§6.1 pure module)', () => { throw error; });

const fixture = loadFixtureDoc();
const fx = () => clone(fixture);
const RACK = (n) => fx().racks[0] && Object.assign(clone(fixture.racks[0]), n || {});

function mergePatch(t, p) {
  if (p === null || typeof p !== 'object' || Array.isArray(p)) return clone(p);
  const out = t && typeof t === 'object' && !Array.isArray(t) ? clone(t) : {};
  for (const [k, v] of Object.entries(p)) { if (v === null) delete out[k]; else out[k] = mergePatch(out[k], v); }
  return out;
}
function apply(doc, ops) {
  if (mcL.mod && mcL.mod.applyOps) return mcL.mod.applyOps(doc, ops).doc;
  const d = clone(doc);
  for (const o of ops) {
    const coll = d[o.coll]; const i = coll.findIndex((e) => e.id === o.id);
    if (o.op === 'merge') coll[i] = mergePatch(coll[i], o.value);
    else if (o.op === 'put') { if (i >= 0) coll[i] = clone(o.value); else coll.push(clone(o.value)); }
    else if (o.op === 'del' && i >= 0) coll.splice(i, 1);
  }
  return d;
}
function rack(d, devId, r) {
  device(d, devId).rack = Object.assign({ id: 'rk-foh' }, r);
  return d;
}
const slot = (o) => (o ? { left: o.left || null, right: o.right || null } : o);

T('fixture placement U10 left', () => {
  const rackDevices = need(rk, 'rackDevices', 'FR-RACK-02', S);
  const occupancy = need(rk, 'occupancy', 'FR-RACK-02', S);
  const list = rackDevices(fx(), 'rk-foh');
  assert.equal(list.length, 1, m('FR-RACK-03', S, 'FOH rack holds one device'));
  const p = list[0];
  const dev = p.device && typeof p.device === 'object' ? p.device.id : p.device;
  assert.equal(dev, 'shure-wireless');
  assert.deepEqual([p.u, p.height, p.face, p.side], [10, 1, 'front', 'left'], m('FR-RACK-02', S, 'shure-wireless at U10, 1U, front, left half'));
  const occ = occupancy(fx(), 'rk-foh', 'front');
  assert.deepEqual(slot(occ[10]), { left: 'shure-wireless', right: null }, m('FR-RACK-02', S, 'occupancy[10] = left half'));
  for (let u = 1; u <= 12; u++) if (u !== 10) assert.deepEqual(slot(occ[u]), { left: null, right: null }, m('FR-RACK-03', S, `U${u} empty`));
  assert.ok(occ.length >= 13, m('FR-RACK-02', S, 'occupancy indexed by u 1..units'));
});

T('occupancy: height, faces, depth', () => {
  const occupancy = need(rk, 'occupancy', 'FR-RACK-02', S);
  const d = rack(fx(), 'sound-board', { u: 3, height: 2, face: 'rear', side: 'full', depth: 'half' });
  const rear = occupancy(d, 'rk-foh', 'rear');
  const front = occupancy(d, 'rk-foh', 'front');
  for (const u of [3, 4]) assert.deepEqual(slot(rear[u]), { left: 'sound-board', right: 'sound-board' }, m('FR-RACK-02', S, `2U full-width rear device fills U${u}`));
  assert.deepEqual(slot(rear[5]), { left: null, right: null }, m('FR-RACK-02', S, 'u = lowest occupied RU, height upwards'));
  assert.deepEqual(slot(front[3]), { left: null, right: null }, m('FR-RACK-02', S, 'half-depth rear device leaves the front free'));
  const d2 = rack(fx(), 'sound-board', { u: 3, height: 1, face: 'rear', side: 'full', depth: 'full' });
  assert.equal(slot(occupancy(d2, 'rk-foh', 'front')[3]).left, 'sound-board', m('FR-RACK-02', S, 'full-depth blocks both faces'));
});

T('collisions', () => {
  const collisions = need(rk, 'collisions', 'FR-RACK-05', S);
  assert.deepEqual(collisions(fx(), 'rk-foh'), [], m('FR-RACK-05', S, 'fixture rack has no collisions'));
  let d = rack(fx(), 'sound-board', { u: 5, height: 1, face: 'front', side: 'full' });
  d = rack(d, 'atem-mini', { u: 5, height: 1, face: 'front', side: 'full' });
  const c = collisions(d, 'rk-foh');
  const front = c.filter((x) => x.face === 'front');
  assert.ok(front.length >= 1, m('FR-RACK-05', S, 'two full-width devices at the same U/face collide'));
  assert.deepEqual([front[0].a, front[0].b].sort(), ['atem-mini', 'sound-board']);
  assert.equal(front[0].u, 5, m('FR-RACK-05', S, 'collision reports the U'));
  let h = rack(fx(), 'sound-board', { u: 10, height: 1, face: 'front', side: 'right' });
  assert.deepEqual(collisions(h, 'rk-foh'), [], m('FR-RACK-02', S, 'left + right halves at the same U do not collide'));
  h = rack(fx(), 'sound-board', { u: 9, height: 2, face: 'front', side: 'full' });
  assert.ok(collisions(h, 'rk-foh').some((x) => x.u === 10), m('FR-RACK-05', S, 'multi-U overlap detected at U10'));
});

T('fits refuses overlap', () => {
  const fits = need(rk, 'fits', 'FR-RACK-04', S);
  const f = (d, dev, u, o) => fits(d, 'rk-foh', dev, u, o || {});
  assert.equal(f(fx(), 'sound-board', 10, { side: 'full', height: 1 }).ok, false, m('FR-RACK-04', S, 'occupied RU refused'));
  assert.ok(f(fx(), 'sound-board', 10, { side: 'full', height: 1 }).reason, m('FR-RACK-04', S, 'refusal has a reason'));
  assert.equal(f(fx(), 'sound-board', 10, { side: 'right', height: 1 }).ok, true, m('FR-RACK-04', S, 'free right half fits'));
  assert.equal(f(fx(), 'sound-board', 9, { side: 'full', height: 2 }).ok, false, m('FR-RACK-04', S, '2U block over U10 refused'));
  assert.equal(f(fx(), 'sound-board', 12, { side: 'full', height: 2 }).ok, false, m('FR-RACK-04', S, 'out of range refused'));
  assert.equal(f(fx(), 'sound-board', 11, { side: 'full', height: 2 }).ok, true, m('FR-RACK-04', S, 'U11-12 free'));
  assert.equal(f(fx(), 'sound-board', 1, { side: 'full', height: 1 }).ok, true);
  assert.equal(f(fx(), 'shure-wireless', 10, { side: 'left', height: 1 }).ok, true, m('FR-RACK-04', S, 'a device does not collide with itself'));
  assert.equal(fits(fx(), 'rk-nope', 'sound-board', 1, {}).ok, false, m('FR-RACK-05', S, 'unknown rack refused'));
});

T('placeOps / unplaceOps', () => {
  const placeOps = need(rk, 'placeOps', 'FR-RACK-04', S);
  const unplaceOps = need(rk, 'unplaceOps', 'FR-RACK-04', S);
  const d = apply(fx(), placeOps(fx(), 'sound-board', 'rk-foh', 4, { face: 'front', height: 2, side: 'full' }));
  const r = device(d, 'sound-board').rack;
  assert.deepEqual([r.id, r.u, r.height, r.face], ['rk-foh', 4, 2, 'front'], m('FR-RACK-02', S, 'placeOps writes device.rack'));
  const forced = placeOps(fx(), 'sound-board', 'rk-foh', 10, { face: 'front', height: 1, side: 'full', force: true });
  const df = apply(fx(), forced);
  assert.equal(device(df, 'sound-board').rack.u, 10, m('FR-RACK-04', S, 'force places onto an occupied RU'));
  assert.ok(need(rk, 'collisions', 'FR-RACK-04', S)(df, 'rk-foh').length > 0, m('FR-RACK-04', S, 'forced placement shows as a collision'));
  const du = apply(fx(), unplaceOps(fx(), 'shure-wireless'));
  assert.ok(!device(du, 'shure-wireless').rack, m('FR-RACK-04', S, 'unplaceOps removes device.rack'));
});

T('RU snapping uToY / yToU', () => {
  const uToY = need(rk, 'uToY', 'FR-RACK-04', S);
  const yToU = need(rk, 'yToU', 'FR-RACK-04', S);
  const RU = typeof rk.RU_PX === 'number' ? rk.RU_PX : 22;
  if ('RU_PX' in rk) assert.equal(rk.RU_PX, 22, m('FR-RACK-03', S, 'RU_PX = 22'));
  if ('RACK_W' in rk) assert.equal(rk.RACK_W, 320, m('FR-RACK-03', S, 'RACK_W = 320'));
  const r = RACK();
  assert.equal(uToY(r, 12, 1), 0, m('FR-RACK-03', S, 'top RU (U12, bottom_up) drawn at y 0'));
  assert.equal(uToY(r, 1, 1), 11 * RU, m('FR-RACK-03', S, 'U1 at the bottom'));
  assert.equal(uToY(r, 1, 2), 10 * RU, m('FR-RACK-03', S, 'top px of a 2U block at U1'));
  for (let h = 1; h <= 3; h++) for (let u = 1; u <= 12 - h + 1; u++) {
    assert.equal(yToU(r, uToY(r, u, h), h), u, m('FR-RACK-04', S, `yToU(uToY(u=${u}, h=${h})) round trip`));
    assert.equal(yToU(r, uToY(r, u, h) + 9, h), u, m('FR-RACK-04', S, 'snaps to the nearest RU (+9 px)'));
  }
  assert.equal(yToU(r, -500, 1), 12, m('FR-RACK-04', S, 'clamped to units'));
  assert.equal(yToU(r, 5000, 2), 1, m('FR-RACK-04', S, 'clamped to 1'));
  assert.equal(yToU(r, -500, 3), 10, m('FR-RACK-04', S, 'clamped to units - height + 1'));
});

T('ruLabel numbering', () => {
  const ruLabel = need(rk, 'ruLabel', 'FR-RACK-03', S);
  assert.equal(String(ruLabel(RACK(), 1)), '1', m('FR-RACK-03', S, 'bottom_up: U1 label 1'));
  assert.equal(String(ruLabel(RACK(), 12)), '12');
  assert.equal(String(ruLabel(RACK({ numbering: 'top_down' }), 12)), '1', m('FR-RACK-03', S, 'top_down: top RU labelled 1'));
  assert.equal(String(ruLabel(RACK({ numbering: 'top_down' }), 1)), '12', m('FR-RACK-03', S, 'top_down: bottom RU labelled 12'));
});
