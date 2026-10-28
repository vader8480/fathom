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

// ------------------------------------------------------- P5B: paths & cable runs (§6.7)
// CAL plan: 2000 x 1000 px, calibration 1000 px = 10 m -> 0.01 m/px; 0.1 norm x = 2 m, 0.1 norm y = 1 m.
const CAL = Object.assign(clone(PLAN), {
  calibration: { p1: [0, 0.5], p2: [0.5, 0.5], distance: 10, unit: 'm' },
  markers: [{ device: 'atem-mini', x: 0.25, y: 0.5 }, { device: 'sound-board', x: 0.75, y: 0.5 }],
});
const CABLE = { id: 'c-run', medium: 'hdmi', from: { device: 'atem-mini', port: 'HDMI OUT' }, to: { device: 'sound-board', port: 'HDMI IN' }, length_m: 7 };
function runDoc(fpExtra, cableExtra) {
  const d = clone(loadFixtureDoc());
  d.floorplans.push(Object.assign(clone(CAL), fpExtra || {}));
  d.cables.push(Object.assign(clone(CABLE), cableExtra || {}));
  return d;
}
const calPlan = (d) => d.floorplans.find((x) => x.id === 'fp-main');
const pct = (a, b, why) => assert.ok(Math.abs(a - b) <= Math.abs(b) * 0.01 + 1e-9, m('FR-PLAN-10', S, `${why}: ${a} vs ${b} (±1%)`));

T('P5B polylineLength: straight 10 m, 3-corner path within 1%, uncalibrated px', () => {
  const polylineLength = need(fp, 'polylineLength', 'FR-PLAN-10', S);
  const metersPerNorm = need(fp, 'metersPerNorm', 'FR-PLAN-10', S);
  assert.deepEqual(norm(metersPerNorm(CAL)), { x: 20, y: 10 }, 'metres per normalised unit along x and y');
  assert.equal(metersPerNorm(PLAN), null, 'null when uncalibrated');
  near(polylineLength([[0.25, 0.5], [0.75, 0.5]], CAL), 10, 1e-9, 'straight run 1000 px = 10 m');
  // 3 corners: 4 m right, 3 m down, then a 3-4-5 diagonal (0.2 norm x = 4 m, 0.3 norm y = 3 m) = 4 + 3 + 5 = 12 m
  pct(polylineLength([[0.1, 0.1], [0.3, 0.1], [0.3, 0.4], [0.5, 0.1]], CAL), 12, '3-corner path');
  near(polylineLength([[0, 0], [0.5, 0]], PLAN), 1000, 1e-9, 'uncalibrated: plan px');
  assert.equal(polylineLength([[0.5, 0.5]], CAL), 0, 'a single point has no length');
});

T('P5B resolveRun: straight run, labels in m / ft / ? and estimate with slack + drop', () => {
  const resolveRun = need(fp, 'resolveRun', 'FR-PLAN-10', S);
  const runLabel = need(fp, 'runLabel', 'FR-PLAN-10', S);
  const estimateOf = need(fp, 'estimateOf', 'FR-PLAN-10', S);
  const d = runDoc();
  const run = resolveRun(d, calPlan(d), d.cables.find((c) => c.id === 'c-run'));
  assert.ok(run, 'both ends placed -> a run');
  assert.equal(run.unit, 'm'); assert.equal(run.auto, true); assert.deepEqual(run.via, []);
  assert.deepEqual(norm(run.points), [[0.25, 0.5], [0.75, 0.5]], 'straight line between the markers');
  near(run.length_m, 10, 1e-9, 'length 10 m'); near(run.estimate_m, 10, 1e-9, 'estimate = length without slack/drop');
  assert.equal(runLabel(run, 'metric'), '10.0 m'); assert.equal(runLabel(run, 'imperial'), '32.8 ft');
  const d2 = runDoc({}, { route: { plan: 'fp-main', slack_m: 1.5, drop_m: 2 } });
  const r2 = resolveRun(d2, calPlan(d2), d2.cables.find((c) => c.id === 'c-run'));
  near(r2.estimate_m, 10 + 1.5 + 4, 1e-9, 'estimate = length + slack + 2 x drop');
  near(estimateOf(r2, d2.cables.find((c) => c.id === 'c-run'), calPlan(d2)), 15.5, 1e-9, 'estimateOf agrees');
  const d3 = runDoc({ calibration: null });
  const r3 = resolveRun(d3, calPlan(d3), d3.cables.find((c) => c.id === 'c-run'));
  assert.equal(r3.unit, 'px'); assert.equal(r3.estimate_m, null, 'no estimate without calibration');
  assert.equal(runLabel(r3, 'metric'), '?', 'label shows ? when uncalibrated');
  near(r3.length_m, 1000, 1e-9, 'length in plan px');
  const d4 = runDoc({ markers: [{ device: 'atem-mini', x: 0.25, y: 0.5 }] });
  assert.equal(resolveRun(d4, calPlan(d4), d4.cables.find((c) => c.id === 'c-run')), null, 'one end off the plan -> no run');
  const d5 = runDoc({}, { route: { plan: 'fp-other', mode: 'manual', points: [[0.5, 0.9]] } });
  assert.equal(resolveRun(d5, calPlan(d5), d5.cables.find((c) => c.id === 'c-run')).points.length, 2, 'a route for another plan is ignored');
});

T('P5B resolveRun via paths: ordering, segments, elevation; manual routes; runsForPlan', () => {
  const resolveRun = need(fp, 'resolveRun', 'FR-PLAN-10', S);
  const runsForPlan = need(fp, 'runsForPlan', 'FR-PLAN-10', S);
  // Tray along y = 0.3 from x 0.25 to 0.75 (10 m), 2 m above the markers (0.2 norm y = 2 m).
  const tray = { id: 'pt-tray0001', name: 'Tray', kind: 'tray', points: [[0.25, 0.3], [0.75, 0.3]], elevation_m: 3 };
  const d = runDoc({ paths: [tray] }, { route: { plan: 'fp-main', via: ['pt-tray0001'], slack_m: 1, drop_m: 0.5 } });
  const run = resolveRun(d, calPlan(d), d.cables.find((c) => c.id === 'c-run'));
  assert.deepEqual(run.via, ['pt-tray0001'], 'the path is followed');
  assert.deepEqual(run.segments.map((s) => s.kind), ['drop', 'path', 'drop'], 'drop onto the tray, along it, drop off');
  near(run.segments[0].length_m, 2, 1e-9, 'drop up 2 m'); near(run.segments[1].length_m, 10, 1e-9, 'along the tray 10 m'); near(run.segments[2].length_m, 2, 1e-9, 'drop down 2 m');
  near(run.length_m, 14, 1e-9, 'total 14 m');
  near(run.estimate_m, 14 + 1 + 2 * 0.5 + 3, 1e-9, 'estimate = length + slack + 2 x drop + path elevation');
  // Two paths: a short trench reached first, then the tray; via order is kept.
  const trench = { id: 'pt-trench01', name: 'Trench', kind: 'trench', points: [[0.25, 0.6], [0.45, 0.45]] };
  const d2 = runDoc({ paths: [tray, trench] }, { route: { plan: 'fp-main', via: ['pt-trench01', 'pt-tray0001'] } });
  const r2 = resolveRun(d2, calPlan(d2), d2.cables.find((c) => c.id === 'c-run'));
  assert.deepEqual(r2.via, ['pt-trench01', 'pt-tray0001'], 'via order preserved');
  assert.deepEqual(r2.segments.filter((s) => s.kind === 'path').map((s) => s.path), ['pt-trench01', 'pt-tray0001']);
  assert.ok(r2.length_m > 10, 'the detour is longer than the straight run');
  const d3 = runDoc({ paths: [tray] }, { route: { plan: 'fp-main', via: ['pt-tray0001', 'pt-missing'] } });
  assert.deepEqual(resolveRun(d3, calPlan(d3), d3.cables.find((c) => c.id === 'c-run')).via, ['pt-tray0001'], 'unknown path ids are skipped');
  // Manual route: stored corners are used verbatim.
  const d4 = runDoc({}, { route: { plan: 'fp-main', mode: 'manual', points: [[0.25, 0.8]] } });
  const r4 = resolveRun(d4, calPlan(d4), d4.cables.find((c) => c.id === 'c-run'));
  assert.equal(r4.auto, false);
  assert.deepEqual(norm(r4.points), [[0.25, 0.5], [0.25, 0.8], [0.75, 0.5]]);
  near(r4.length_m, 3 + Math.hypot(10, 3), 1e-9, 'down 3 m then the diagonal');
  // runsForPlan: both-ends-placed cables only; auto (virtual) cables excluded.
  const d5 = runDoc();
  d5.cables.push(Object.assign(clone(CABLE), { id: 'c-virtual', auto: true }));
  d5.cables.push(Object.assign(clone(CABLE), { id: 'c-half', to: { device: 'nobody', port: '1' } }));
  assert.deepEqual(runsForPlan(d5, 'fp-main').map((r) => r.cable), ['c-run'], 'one run on the plan');
  assert.deepEqual(runsForPlan(d5, 'fp-none'), [], 'unknown plan');
  assert.ok(need(fp, 'halfPlaced', 'FR-PLAN-10', S)(d5, 'fp-main').includes('c-half'), 'half-placed cables');
});

T('P5B snapToPaths / nearestPointOnPath / estimateChanges', () => {
  const snapToPaths = need(fp, 'snapToPaths', 'FR-PLAN-10', S);
  const nearestPointOnPath = need(fp, 'nearestPointOnPath', 'FR-PLAN-10', S);
  const estimateChanges = need(fp, 'estimateChanges', 'FR-PLAN-10', S);
  const roundUp = need(fp, 'roundUp', 'FR-PLAN-10', S);
  const tray = { id: 'pt-a', name: 'A', kind: 'tray', points: [[0.2, 0.2], [0.6, 0.2], [0.6, 0.8]] };
  const n = nearestPointOnPath(tray, [0.4, 0.25]);
  assert.deepEqual(norm(n.point), [0.4, 0.2]); near(n.t, 0.5, 1e-9, 't = segment 0 at half'); near(n.dist, 0.05, 1e-9);
  const corner = nearestPointOnPath(tray, [0.7, 0.5]);
  assert.deepEqual(norm(corner.point), [0.6, 0.5]); near(corner.t, 1.5, 1e-9, 'second segment');
  const plan2 = Object.assign(clone(CAL), { paths: [tray, { id: 'pt-b', name: 'B', kind: 'floor', points: [[0.2, 0.9], [0.9, 0.9]] }] });
  const s = snapToPaths(plan2, [0.4, 0.21], 0.02);
  assert.equal(s.path, 'pt-a'); assert.deepEqual(norm(s.point), [0.4, 0.2]);
  assert.equal(snapToPaths(plan2, [0.4, 0.5], 0.02), null, 'nothing within the radius');
  assert.equal(snapToPaths(plan2, [0.5, 0.88], 0.05).path, 'pt-b', 'nearest wins');
  assert.equal(roundUp(12.01, 0.5), 12.5); assert.equal(roundUp(12.5, 0.5), 12.5); assert.equal(roundUp(10, 0.5), 10);
  const d = runDoc({}, { route: { plan: 'fp-main', slack_m: 0.3 } });
  assert.deepEqual(estimateChanges(d, 'fp-main', null, 0.5), [{ cable: 'c-run', from_m: 7, to_m: 10.5 }], 'rounded-up estimate vs entered length');
  assert.deepEqual(estimateChanges(d, 'fp-main', ['c-other'], 0.5), [], 'limited to the given cables');
  const d2 = runDoc({}, { length_m: 10 });
  assert.deepEqual(estimateChanges(d2, 'fp-main', ['c-run'], 0.5), [], 'already matching -> nothing to do');
});

T('P5B ops builders: addPathOps / updatePathOps / deletePathOps strips via / set & clear route', () => {
  const addPathOps = need(fp, 'addPathOps', 'FR-PLAN-10', S);
  const updatePathOps = need(fp, 'updatePathOps', 'FR-PLAN-10', S);
  const deletePathOps = need(fp, 'deletePathOps', 'FR-PLAN-10', S);
  const setRouteOps = need(fp, 'setRouteOps', 'FR-PLAN-10', S);
  const clearRouteOps = need(fp, 'clearRouteOps', 'FR-PLAN-10', S);
  const pathUsers = need(fp, 'pathUsers', 'FR-PLAN-10', S);
  const d0 = runDoc();
  const added = addPathOps(d0, 'fp-main', { name: ' Catwalk ', kind: 'catwalk', points: [[0.1, 0.1], [0.1, 0.1], [0.5, 0.1], [1.2, -0.1]], elevation_m: 4 });
  assert.match(added.id, /^pt-[0-9a-f]{8}$/, 'id pt-xxxxxxxx');
  assert.equal(added.ops.length, 1); assert.equal(added.ops[0].op, 'merge'); assert.equal(added.ops[0].coll, 'floorplans');
  const d1 = apply(d0, added.ops);
  const p = calPlan(d1).paths[0];
  assert.equal(p.id, added.id); assert.equal(p.name, 'Catwalk'); assert.equal(p.kind, 'catwalk'); assert.equal(p.elevation_m, 4);
  assert.deepEqual(p.points, [[0.1, 0.1], [0.5, 0.1], [1, 0]], 'duplicates dropped, points clamped to [0,1]');
  assert.equal(addPathOps(d0, 'fp-main', { points: [[0.1, 0.1]] }).ops.length, 0, 'a path needs two corners');
  assert.equal(addPathOps(d0, 'fp-main', { kind: 'weird', points: [[0, 0], [1, 1]] }).ops[0].value.paths[0].kind, 'other', 'unknown kinds -> other');
  const d2 = apply(d1, addPathOps(d1, 'fp-main', { points: [[0, 0.9], [1, 0.9]] }).ops);
  assert.equal(calPlan(d2).paths[1].name, 'Path 2', 'default name');
  const up = updatePathOps(d2, 'fp-main', p.id, { name: 'Catwalk SL', elevation_m: '' });
  const d3 = apply(d2, up);
  assert.equal(calPlan(d3).paths[0].name, 'Catwalk SL'); assert.equal(calPlan(d3).paths[0].elevation_m, undefined, 'blank clears the elevation');
  assert.deepEqual(updatePathOps(d3, 'fp-main', p.id, { name: 'Catwalk SL' }), [], 'no-op when unchanged');
  // routes
  const set = setRouteOps(d3, 'c-run', { plan: 'fp-main', via: [p.id, p.id, calPlan(d3).paths[1].id], slack_m: '1.5', drop_m: -2 });
  assert.equal(set.length, 1); assert.equal(set[0].coll, 'cables');
  const d4 = apply(d3, set);
  const route = d4.cables.find((c) => c.id === 'c-run').route;
  assert.deepEqual(route, { plan: 'fp-main', points: [], via: [p.id, calPlan(d3).paths[1].id], slack_m: 1.5, drop_m: 0, mode: 'auto' }, 'normalised route (dupes removed, negatives clamped)');
  assert.deepEqual(setRouteOps(d4, 'c-run', route), [], 'same route -> no op');
  assert.deepEqual(setRouteOps(d4, 'c-nope', route), [], 'unknown cable -> no op');
  assert.deepEqual(pathUsers(d4, p.id), ['c-run']);
  const del = deletePathOps(d4, 'fp-main', p.id);
  assert.equal(del.length, 2, 'path removal + one via strip');
  assert.deepEqual(del[1], { op: 'merge', coll: 'cables', id: 'c-run', value: { route: { via: [calPlan(d3).paths[1].id] } } }, 'deletePathOps strips the path from route.via');
  const d5 = apply(d4, del);
  assert.deepEqual(calPlan(d5).paths.map((x) => x.id), [calPlan(d3).paths[1].id]);
  assert.deepEqual(pathUsers(d5, p.id), []);
  assert.deepEqual(deletePathOps(d5, 'fp-main', p.id), [], 'already gone');
  const clr = clearRouteOps(d5, 'c-run');
  assert.deepEqual(clr, [{ op: 'merge', coll: 'cables', id: 'c-run', value: { route: null } }]);
  assert.equal(apply(d5, clr).cables.find((c) => c.id === 'c-run').route, undefined, 'route removed');
  assert.deepEqual(clearRouteOps(apply(d5, clr), 'c-run'), [], 'nothing to clear');
  // bundles with device ends are routable too
  const d6 = clone(d5);
  d6.bundles = [{ id: 'b-1', kind: 'multicore', from: { device: 'atem-mini' }, to: { device: 'sound-board' }, medium: 'analog' }];
  assert.equal(setRouteOps(d6, 'b-1', { plan: 'fp-main', slack_m: 2 })[0].coll, 'bundles');
  assert.deepEqual(need(fp, 'runsForPlan', 'FR-PLAN-10', S)(d6, 'fp-main').map((r) => r.cable).sort(), ['b-1', 'c-run']);
});
