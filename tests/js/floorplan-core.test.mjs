// T2: js/floorplan-core.js (W4) against SPEC §6.7, FR-PLAN-08, FR-PLAN-10, §4.3.11.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadFixtureDoc, clone, norm, m, need, ids } from './fixtures/helpers.mjs';

const { mod: fp, skip: absent, error } = await loadModule('js/floorplan-core.js', 'W4');
const mcL = await loadModule('js/model-core.js', 'W5');
const S = '§6.7';
const skip = absent || (error ? 'floorplan-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);

if (error) test('floorplan-core.js imports in Node (§6.1 pure module)', () => { throw error; });

const PLAN = {
  id: 'fp-main', name: 'Main floor', room: 'main',
  source: { attachment: 'att-1', kind: 'dxf', page: 0 },
  image: { attachment: 'att-2', kind: 'svg', width: 2000, height: 1000 },
  markers: [{ device: 'atem-mini', x: 0.5, y: 0.5 }, { device: 'sound-board', x: 0.25, y: 0.75 }],
};

function docWithPlan(extra) {
  const d = clone(loadFixtureDoc());
  d.floorplans.push(Object.assign(clone(PLAN), extra || {}));
  return d;
}

// Local RFC 7396 merge so the test does not depend on model-core when it is absent.
function mergePatch(t, p) {
  if (p === null || typeof p !== 'object' || Array.isArray(p)) return clone(p);
  const out = t && typeof t === 'object' && !Array.isArray(t) ? clone(t) : {};
  for (const [k, v] of Object.entries(p)) {
    if (v === null) delete out[k]; else out[k] = mergePatch(out[k], v);
  }
  return out;
}
function apply(doc, ops) {
  if (mcL.mod && mcL.mod.applyOps) return mcL.mod.applyOps(doc, ops).doc;
  const d = clone(doc);
  for (const o of ops) {
    const coll = d[o.coll];
    const i = coll.findIndex((e) => e.id === o.id);
    if (o.op === 'merge') coll[i] = mergePatch(coll[i], o.value);
    else if (o.op === 'put') { if (i >= 0) coll[i] = clone(o.value); else coll.push(clone(o.value)); }
    else if (o.op === 'del' && i >= 0) coll.splice(i, 1);
  }
  return d;
}
const plan = (d) => d.floorplans.find((x) => x.id === 'fp-main');
const near = (a, b, tol, why) => assert.ok(Math.abs(a - b) <= tol, m('FR-PLAN-10', S, `${why}: ${a} vs ${b}`));

T('normToImage / imageToNorm transforms', () => {
  const normToImage = need(fp, 'normToImage', 'FR-PLAN-08', S);
  const imageToNorm = need(fp, 'imageToNorm', 'FR-PLAN-08', S);
  assert.deepEqual(norm(normToImage(PLAN, { x: 0.5, y: 0.25 })), { x: 1000, y: 250 }, m('FR-PLAN-08', '§4.3.11', 'normalized -> image px (width/height)'));
  assert.deepEqual(norm(imageToNorm(PLAN, { x: 1500, y: 1000 })), { x: 0.75, y: 1 }, m('FR-PLAN-08', '§4.3.11', 'image px -> normalized'));
  for (const p of [{ x: 0, y: 0 }, { x: 0.123, y: 0.987 }, { x: 1, y: 1 }]) {
    const back = imageToNorm(PLAN, normToImage(PLAN, p));
    near(back.x, p.x, 1e-9, 'round trip x'); near(back.y, p.y, 1e-9, 'round trip y');
  }
});

T('calibrate 10 m', () => {
  const calibrateOps = need(fp, 'calibrateOps', 'FR-PLAN-10', S);
  const metersPerPx = need(fp, 'metersPerPx', 'FR-PLAN-10', S);
  const distance = need(fp, 'distance', 'FR-PLAN-10', S);
  assert.equal(metersPerPx(PLAN), null, m('FR-PLAN-10', S, 'metersPerPx null without calibration'));
  const p1 = { x: 0.1, y: 0.2 }, p2 = { x: 0.6, y: 0.2 };
  const d0 = docWithPlan();
  const d1 = apply(d0, calibrateOps(d0, 'fp-main', p1, p2, 10, 'm'));
  const cal = plan(d1).calibration;
  assert.ok(cal, m('FR-PLAN-10', '§4.3.11', 'calibration written to the floor plan'));
  assert.equal(cal.distance, 10); assert.equal(cal.unit, 'm');
  near(cal.p1[0], 0.1, 1e-6, 'p1 normalized [x, y]'); near(cal.p2[0], 0.6, 1e-6, 'p2 normalized [x, y]');
  near(metersPerPx(plan(d1)), 10 / 1000, 1e-9, 'scale = 10 m / 1000 px');
  const dm = distance(plan(d1), p1, p2, 'metric');
  near(dm.meters, 10, 0.1, 'measuring the calibration points gives 10 m (±1%)');
  assert.match(dm.text, /^10(\.0+)? m$/, m('FR-PLAN-10', S, `metric text "${dm.text}" shows 10.0 m`));
  const di = distance(plan(d1), p1, p2, 'imperial');
  assert.match(di.text, /^32\.8\d* ft$/, m('FR-PLAN-10', S, `imperial text "${di.text}" = 32.8 ft`));
  const diag = distance(plan(d1), { x: 0, y: 0 }, { x: 0.3, y: 0.4 }, 'metric');
  near(diag.meters, Math.hypot(600, 400) / 100, 1e-6, 'measure in image px space (non-square image)');
  const d2 = apply(d0, calibrateOps(d0, 'fp-main', p1, p2, 10, 'ft'));
  near(distance(plan(d2), p1, p2, 'metric').meters, 3.048, 1e-6, '10 ft calibration = 3.048 m');
});

T('markerOps', () => {
  const markerOps = need(fp, 'markerOps', 'FR-PLAN-08', S);
  const d0 = docWithPlan();
  let d1 = apply(d0, markerOps(d0, 'fp-main', 'restream', { x: 0.3, y: 0.4 }));
  let mk = plan(d1).markers.filter((x) => x.device === 'restream');
  assert.equal(mk.length, 1, m('FR-PLAN-08', S, 'marker added'));
  assert.deepEqual([mk[0].x, mk[0].y], [0.3, 0.4], m('FR-PLAN-08', '§4.3.11', 'normalized x, y'));
  assert.equal(plan(d1).markers.length, 3, m('FR-PLAN-08', S, 'other markers kept'));
  d1 = apply(d1, markerOps(d1, 'fp-main', 'restream', { x: 0.9, y: 0.1 }));
  mk = plan(d1).markers.filter((x) => x.device === 'restream');
  assert.equal(mk.length, 1, m('FR-PLAN-08', '§4.3.11', 'one marker per device per plan (move, not duplicate)'));
  assert.deepEqual([mk[0].x, mk[0].y], [0.9, 0.1], m('FR-PLAN-08', S, 'marker moved'));
  d1 = apply(d1, markerOps(d1, 'fp-main', 'sub-x2', { x: 1.3, y: -0.2 }));
  const sx = plan(d1).markers.find((x) => x.device === 'sub-x2');
  assert.ok(sx.x >= 0 && sx.x <= 1 && sx.y >= 0 && sx.y <= 1, m('FR-PLAN-08', '§4.3.11', 'markers persist with x, y in [0,1]'));
  assert.deepEqual(plan(d0).markers.length, 2, 'input doc untouched');
});

T('removeMarkerOps and unplacedDevices', () => {
  const removeMarkerOps = need(fp, 'removeMarkerOps', 'FR-PLAN-08', S);
  const unplacedDevices = need(fp, 'unplacedDevices', 'FR-PLAN-08', S);
  const d0 = docWithPlan();
  const d1 = apply(d0, removeMarkerOps(d0, 'fp-main', 'atem-mini'));
  assert.deepEqual(plan(d1).markers.map((x) => x.device), ['sound-board'], m('FR-PLAN-08', S, 'marker deleted'));
  const un = ids(unplacedDevices(d0, 'fp-main', 'main'));
  assert.equal(un.length, 9, m('FR-PLAN-08', S, '11 main devices minus 2 placed'));
  assert.ok(!un.includes('atem-mini') && !un.includes('sound-board') && !un.includes('spare-ulxd4d'), m('FR-PLAN-08', S, 'devices in room without a marker on this plan'));
  assert.ok(ids(unplacedDevices(d1, 'fp-main', 'main')).includes('atem-mini'), m('FR-PLAN-08', S, 'removed marker -> unplaced again'));
});

T('marker hit test (non-contract helper)', (t) => {
  if (typeof fp.hitMarker !== 'function') { t.skip('hitMarker not exported (not in the §6.7 contract)'); return; }
  assert.equal(fp.hitMarker(PLAN, { x: 1004, y: 497 }, 12), 'atem-mini', 'nearest marker within radius');
  assert.equal(fp.hitMarker(PLAN, { x: 1100, y: 500 }, 12), null, 'nothing outside the radius');
});

T('viewport transforms (model-core.viewport, used by the floor plan)', { skip: mcL.mod ? false : 'W5 model-core.js not present' }, () => {
  const vp = need(mcL.mod, 'viewport', 'FR-PLAN-09', '§6.2');
  const view = vp.fit({ x: 0, y: 0, w: 2000, h: 1000 }, { w: 1000, h: 600 }, 0);
  const c = vp.worldToScreen(view, { x: 1000, y: 500 });
  near(c.x, 500, 1e-6, 'plan centred x'); near(c.y, 300, 1e-6, 'plan centred y');
  const z = vp.zoomAt(view, { x: 100, y: 100 }, 2, 0.15, 3);
  const a = vp.screenToWorld(view, { x: 100, y: 100 }), b = vp.screenToWorld(z, { x: 100, y: 100 });
  near(a.x, b.x, 1e-6, 'pinch/wheel zoom keeps the pointer fixed'); near(a.y, b.y, 1e-6, 'pinch/wheel zoom keeps the pointer fixed');
});
