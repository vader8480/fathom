// Floor plan core (pure): calibration, measurement, markers, viewport math, ops.
// No DOM, no globals. Runs in Node >= 18 and in the browser (ES2018).

export const FT = 0.3048;
export const ZOOM_MIN = 0.05;
export const ZOOM_MAX = 8;

// ---------------------------------------------------------------- helpers

export function slug(text) {
  const s = String(text == null ? '' : text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return s || 'item';
}

function round(v, digits) {
  const f = Math.pow(10, digits);
  return Math.round(v * f) / f;
}

function clamp01(v) {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

function toPt(p) {
  if (Array.isArray(p)) return {x: Number(p[0]), y: Number(p[1])};
  return {x: Number(p.x), y: Number(p.y)};
}

function list(v) {
  return Array.isArray(v) ? v : [];
}

export function findPlan(doc, fpId) {
  const plans = list(doc && doc.floorplans);
  for (let i = 0; i < plans.length; i++) if (plans[i].id === fpId) return plans[i];
  return null;
}

export function planSize(fp) {
  const img = (fp && fp.image) || {};
  const w = Number(img.width) > 0 ? Number(img.width) : 1000;
  const h = Number(img.height) > 0 ? Number(img.height) : 1000;
  return {w: w, h: h};
}

// ------------------------------------------------------- coordinate spaces

export function normToImage(fp, pt) {
  const s = planSize(fp);
  const p = toPt(pt);
  return {x: p.x * s.w, y: p.y * s.h};
}

export function imageToNorm(fp, pt) {
  const s = planSize(fp);
  const p = toPt(pt);
  return {x: p.x / s.w, y: p.y / s.h};
}

// --------------------------------------------------- calibration & distance

export function unitToMeters(value, unit) {
  return unit === 'ft' ? Number(value) * FT : Number(value);
}

export function metersPerPx(fp) {
  const cal = fp && fp.calibration;
  if (!cal || !cal.p1 || !cal.p2 || !(Number(cal.distance) > 0)) return null;
  const a = normToImage(fp, cal.p1);
  const b = normToImage(fp, cal.p2);
  const px = Math.hypot(b.x - a.x, b.y - a.y);
  if (!(px > 0)) return null;
  return unitToMeters(cal.distance, cal.unit) / px;
}

export function formatLength(meters, units) {
  if (meters == null || !isFinite(meters)) return '';
  if (units === 'imperial') {
    const ft = meters / FT;
    return (ft < 10 ? ft.toFixed(2) : ft.toFixed(1)) + ' ft';
  }
  return (meters < 1 ? meters.toFixed(2) : meters.toFixed(1)) + ' m';
}

// a, b normalized points. Returns {meters|null, px, text}.
export function distance(fp, a, b, units) {
  const pa = normToImage(fp, a);
  const pb = normToImage(fp, b);
  const px = Math.hypot(pb.x - pa.x, pb.y - pa.y);
  const mpp = metersPerPx(fp);
  if (mpp == null) return {meters: null, px: px, text: Math.round(px) + ' px (not calibrated)'};
  const meters = px * mpp;
  return {meters: meters, px: px, text: formatLength(meters, units)};
}

// ------------------------------------------------------------------ markers

export function markerOf(fp, deviceId) {
  const ms = list(fp && fp.markers);
  for (let i = 0; i < ms.length; i++) if (ms[i].device === deviceId) return ms[i];
  return null;
}

export function markerOps(doc, fpId, deviceId, pt) {
  const fp = findPlan(doc, fpId);
  if (!fp) return [];
  const p = toPt(pt);
  const x = round(clamp01(p.x), 5);
  const y = round(clamp01(p.y), 5);
  const markers = list(fp.markers).map(function (m) { return Object.assign({}, m); });
  let found = false;
  for (let i = 0; i < markers.length; i++) {
    if (markers[i].device === deviceId) {
      if (markers[i].x === x && markers[i].y === y) return [];
      markers[i].x = x;
      markers[i].y = y;
      found = true;
    }
  }
  if (!found) markers.push({device: deviceId, x: x, y: y});
  return [{op: 'merge', coll: 'floorplans', id: fpId, value: {markers: markers}}];
}

export function removeMarkerOps(doc, fpId, deviceId) {
  const fp = findPlan(doc, fpId);
  if (!fp || !markerOf(fp, deviceId)) return [];
  const markers = list(fp.markers).filter(function (m) { return m.device !== deviceId; });
  return [{op: 'merge', coll: 'floorplans', id: fpId, value: {markers: markers}}];
}

export function calibrateOps(doc, fpId, p1, p2, dist, unit) {
  const fp = findPlan(doc, fpId);
  const d = Number(dist);
  if (!fp || !(d > 0)) return [];
  const a = toPt(p1);
  const b = toPt(p2);
  return [{op: 'merge', coll: 'floorplans', id: fpId, value: {calibration: {
    p1: [round(a.x, 6), round(a.y, 6)],
    p2: [round(b.x, 6), round(b.y, 6)],
    distance: d,
    unit: unit === 'ft' ? 'ft' : 'm',
  }}}];
}

export function roomDevices(doc, room) {
  return list(doc && doc.devices).filter(function (d) {
    return !d.auto && (room === '*' || (d.room || '') === (room || ''));
  });
}

// Devices in `room` (default: the plan's room) without a marker on this plan.
export function unplacedDevices(doc, fpId, room) {
  const fp = findPlan(doc, fpId);
  const r = room == null ? (fp ? fp.room : '') : room;
  return roomDevices(doc, r).filter(function (d) { return !fp || !markerOf(fp, d.id); });
}

// Hit test: returns the device id of the marker nearest to the image point
// within radiusPx (image px), or null.
export function hitMarker(fp, pt, radiusPx) {
  const p = toPt(pt);
  let best = null;
  let bestD = Infinity;
  list(fp && fp.markers).forEach(function (m) {
    const q = normToImage(fp, m);
    const d = Math.hypot(q.x - p.x, q.y - p.y);
    if (d <= radiusPx && d < bestD) { best = m.device; bestD = d; }
  });
  return best;
}

// Move a normalized point by (dx, dy) normalized units, clamped.
export function nudge(pt, dx, dy) {
  const p = toPt(pt);
  return {x: round(clamp01(p.x + dx), 5), y: round(clamp01(p.y + dy), 5)};
}

// ------------------------------------------------------------ plan entities

export function plansForRoom(doc, room) {
  return list(doc && doc.floorplans)
    .map(function (fp, i) { return {fp: fp, i: i}; })
    .filter(function (e) { return room === '*' || e.fp.room === room; })
    .sort(function (a, b) {
      const oa = a.fp.order == null ? 1e9 : a.fp.order;
      const ob = b.fp.order == null ? 1e9 : b.fp.order;
      return oa - ob || a.i - b.i;
    })
    .map(function (e) { return e.fp; });
}

function uniqueId(base, taken) {
  if (!taken[base]) return base;
  for (let n = 2; ; n++) if (!taken[base + '-' + n]) return base + '-' + n;
}

function idSet(arr) {
  const s = {};
  list(arr).forEach(function (e) { if (e && e.id) s[e.id] = true; });
  return s;
}

// Create a floor plan (and optionally its attachment) locally via ops.
// spec {room, name, image:{kind, width, height}, file?, mime?, source?, layers?}
export function newPlanOps(doc, spec) {
  const fpId = uniqueId('fp-' + slug(spec.name), idSet(doc.floorplans));
  const ops = [];
  let attId = spec.attachment || '';
  if (!attId && spec.file) {
    attId = uniqueId('att-' + slug(spec.name), idSet(doc.attachments));
    ops.push({op: 'put', coll: 'attachments', id: attId, value: {
      id: attId, name: spec.file.split('/').pop(), file: spec.file,
      mime: spec.mime || 'image/svg+xml', kind: 'floorplan',
    }});
  }
  const plans = plansForRoom(doc, spec.room);
  let maxOrder = -1;
  plans.forEach(function (p, i) { maxOrder = Math.max(maxOrder, p.order == null ? i : p.order); });
  const img = spec.image || {};
  const fp = {
    id: fpId, name: spec.name, room: spec.room,
    source: Object.assign({attachment: attId, kind: img.kind || 'svg', page: 0}, spec.source || {}, spec.source && spec.source.attachment ? {} : {attachment: attId}),
    image: {attachment: attId, kind: img.kind || 'svg', width: img.width || 1000, height: img.height || 1000},
    order: maxOrder + 1,
    markers: [],
  };
  if (spec.layers && spec.layers.length) fp.layers = spec.layers;
  ops.push({op: 'put', coll: 'floorplans', id: fpId, value: fp});
  return {ops: ops, id: fpId};
}

export function renamePlanOps(doc, fpId, name) {
  const fp = findPlan(doc, fpId);
  const n = String(name || '').trim();
  if (!fp || !n || n === fp.name) return [];
  return [{op: 'merge', coll: 'floorplans', id: fpId, value: {name: n}}];
}

export function deletePlanOps(doc, fpId) {
  return findPlan(doc, fpId) ? [{op: 'del', coll: 'floorplans', id: fpId}] : [];
}

// Move a plan up (-1) or down (+1) among its room's plans; rewrites `order`.
export function reorderPlanOps(doc, fpId, delta) {
  const fp = findPlan(doc, fpId);
  if (!fp) return [];
  const plans = plansForRoom(doc, fp.room).slice();
  const i = plans.indexOf(fp);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= plans.length) return [];
  plans.splice(i, 1);
  plans.splice(j, 0, fp);
  const ops = [];
  plans.forEach(function (p, k) {
    if (p.order !== k) ops.push({op: 'merge', coll: 'floorplans', id: p.id, value: {order: k}});
  });
  return ops;
}

export function toggleLayerOps(doc, fpId, layer, visible) {
  const fp = findPlan(doc, fpId);
  if (!fp) return [];
  const hidden = list(fp.hidden_layers).filter(function (n) { return n !== layer; });
  if (!visible) hidden.push(layer);
  return [{op: 'merge', coll: 'floorplans', id: fpId, value: {hidden_layers: hidden.length ? hidden : null}}];
}

export function layerVisible(fp, layer) {
  if (list(fp && fp.hidden_layers).indexOf(layer.name) >= 0) return false;
  if (fp && fp.hidden_layers) return true;
  return layer.visible !== false;
}

// ------------------------------------------------- paths & cable runs (P5B)
// Mirror of fathom/runs.py: shared paths (`floorplan.paths[]`, normalised polylines)
// and cable runs between two placed markers (`cable.route` = {plan, points, via,
// slack_m, drop_m, mode}). Geometry is done in normalised plan coordinates; lengths
// come out in metres when the plan is calibrated, else in plan (image) pixels.

export const PATH_KINDS = ['tray', 'catwalk', 'trench', 'conduit', 'floor', 'other'];
export const PATH_KIND_LABELS = {tray: 'Cable tray', catwalk: 'Catwalk', trench: 'Trench', conduit: 'Conduit', floor: 'Floor run', other: 'Other'};
export const SNAP_NORM = 0.02;
export const ESTIMATE_ROUND = 0.5;

function xy(p) {
  if (Array.isArray(p)) return [Number(p[0]), Number(p[1])];
  return [Number(p && p.x), Number(p && p.y)];
}

function num(v, dflt) {
  const n = Number(v);
  return isFinite(n) ? n : (dflt || 0);
}

function samePt(a, b) {
  return Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9;
}

function pathPoints(path) {
  return list(path && path.points).map(xy).filter(function (p) { return isFinite(p[0]) && isFinite(p[1]); });
}

export function pathKind(kind) {
  return PATH_KINDS.indexOf(kind) >= 0 ? kind : 'other';
}

export function pathById(fp, id) {
  const ps = list(fp && fp.paths);
  for (let i = 0; i < ps.length; i++) if (ps[i].id === id) return ps[i];
  return null;
}

// Metres per normalised unit along x and y ({x, y}), null when uncalibrated.
export function metersPerNorm(fp) {
  const mpp = metersPerPx(fp);
  if (mpp == null) return null;
  const s = planSize(fp);
  return {x: mpp * s.w, y: mpp * s.h};
}

// Length of a normalised polyline: metres when calibrated, image px otherwise.
export function polylineLength(points, fp) {
  const pts = list(points).map(xy);
  const mpn = metersPerNorm(fp);
  const s = planSize(fp);
  const sx = mpn ? mpn.x : s.w;
  const sy = mpn ? mpn.y : s.h;
  let total = 0;
  for (let i = 1; i < pts.length; i++) {
    total += Math.hypot((pts[i][0] - pts[i - 1][0]) * sx, (pts[i][1] - pts[i - 1][1]) * sy);
  }
  return total;
}

function projectOnSegment(a, b, p) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const l2 = dx * dx + dy * dy;
  let u = l2 > 0 ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2 : 0;
  u = u < 0 ? 0 : u > 1 ? 1 : u;
  return {point: [a[0] + u * dx, a[1] + u * dy], u: u};
}

// Nearest point of a path to `pt` (normalised): {point, t, dist}; t = segment index + fraction.
export function nearestPointOnPath(path, pt) {
  const pts = pathPoints(path);
  const p = xy(pt);
  if (!pts.length) return null;
  if (pts.length === 1) return {point: pts[0].slice(), t: 0, dist: Math.hypot(pts[0][0] - p[0], pts[0][1] - p[1])};
  let best = null;
  for (let i = 1; i < pts.length; i++) {
    const r = projectOnSegment(pts[i - 1], pts[i], p);
    const d = Math.hypot(r.point[0] - p[0], r.point[1] - p[1]);
    if (!best || d < best.dist) best = {point: r.point, t: i - 1 + r.u, dist: d};
  }
  return best;
}

// Point of a path at parameter t (see nearestPointOnPath).
export function pathAt(path, t) {
  const pts = pathPoints(path);
  if (!pts.length) return null;
  if (pts.length === 1 || t <= 0) return pts[0].slice();
  if (t >= pts.length - 1) return pts[pts.length - 1].slice();
  const i = Math.floor(t);
  const u = t - i;
  return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * u, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * u];
}

// The part of a path between parameters t1 and t2 (either order), endpoints included.
export function subPath(path, t1, t2) {
  const pts = pathPoints(path);
  if (pts.length < 2) return pts;
  const lo = Math.min(t1, t2);
  const hi = Math.max(t1, t2);
  const out = [pathAt(path, lo)];
  for (let i = Math.floor(lo) + 1; i <= Math.ceil(hi) - 1 && i < pts.length; i++) {
    if (i > lo && i < hi) out.push(pts[i].slice());
  }
  out.push(pathAt(path, hi));
  return t1 <= t2 ? out : out.reverse();
}

// Snap a normalised point to the nearest path within maxNorm: {path, point, t, dist} or null.
export function snapToPaths(fp, pt, maxNorm) {
  const max = maxNorm == null ? SNAP_NORM : maxNorm;
  let best = null;
  list(fp && fp.paths).forEach(function (path) {
    if (pathPoints(path).length < 2) return;
    const r = nearestPointOnPath(path, pt);
    if (r && r.dist <= max && (!best || r.dist < best.dist)) best = {path: path.id, point: r.point, t: r.t, dist: r.dist};
  });
  return best;
}

// Point (and parameter) on `path` nearest to another path `other`.
function nearestToPath(path, other) {
  let best = null;
  pathPoints(other).forEach(function (v) {
    const r = nearestPointOnPath(path, v);
    if (r && (!best || r.dist < best.dist)) best = r;
  });
  pathPoints(path).forEach(function (v, i) {
    const r = nearestPointOnPath(other, v);
    if (r && (!best || r.dist < best.dist)) best = {point: v.slice(), t: i, dist: r.dist};
  });
  return best;
}

function routeFor(fp, entity) {
  const r = entity && entity.route;
  if (!r || typeof r !== 'object') return null;
  if (r.plan && r.plan !== fp.id) return null;
  return r;
}

// The run of a cable (or bundle with device ends) on a plan, or null unless both ends are placed.
// {cable, plan, points, segments [{kind drop|path|free, path, length_m}], length_m, estimate_m,
//  unit 'm'|'px', auto, via [used path ids], from, to}
export function resolveRun(doc, fp, cable) {
  if (!fp || !cable || !cable.from || !cable.to) return null;
  const ma = markerOf(fp, cable.from.device);
  const mb = markerOf(fp, cable.to.device);
  if (!ma || !mb) return null;
  const a = [Number(ma.x), Number(ma.y)];
  const b = [Number(mb.x), Number(mb.y)];
  const route = routeFor(fp, cable);
  const manual = !!(route && route.mode === 'manual');
  const pts = [a];
  const segs = [];
  const used = [];
  function addLeg(kind, pathId, legPts) {
    const leg = [pts[pts.length - 1]];
    legPts.forEach(function (p) { if (!samePt(leg[leg.length - 1], p)) leg.push(p); });
    if (leg.length < 2) return;
    leg.slice(1).forEach(function (p) { pts.push(p); });
    segs.push({kind: kind, path: pathId || null, length_m: polylineLength(leg, fp)});
  }
  if (manual) {
    addLeg('free', null, list(route.points).map(xy).concat([b]));
  } else {
    const via = route ? list(route.via).map(function (id) { return pathById(fp, id); })
      .filter(function (p) { return p && pathPoints(p).length >= 2; }) : [];
    if (!via.length) {
      addLeg('free', null, [b]);
    } else {
      let cur = a;
      via.forEach(function (path, i) {
        const entry = nearestPointOnPath(path, cur);
        const next = via[i + 1];
        const exit = next ? nearestToPath(path, next) : nearestPointOnPath(path, b);
        addLeg(i === 0 ? 'drop' : 'free', null, [entry.point]);
        addLeg('path', path.id, subPath(path, entry.t, exit.t));
        cur = exit.point;
        used.push(path.id);
      });
      addLeg('drop', null, [b]);
    }
  }
  if (pts.length === 1) { pts.push(b); segs.push({kind: 'free', path: null, length_m: 0}); }
  let length = 0;
  segs.forEach(function (s) { length += s.length_m; });
  const unit = metersPerNorm(fp) ? 'm' : 'px';
  const run = {
    cable: cable.id, plan: fp.id, points: pts, segments: segs, length_m: length, estimate_m: null,
    unit: unit, auto: !manual, via: used, from: cable.from.device, to: cable.to.device,
  };
  run.estimate_m = estimateOf(run, cable, fp);
  return run;
}

// length + slack + 2·drop + Σ elevation of the paths used; null when the plan is uncalibrated.
export function estimateOf(run, cable, fp) {
  if (!run || run.unit !== 'm') return null;
  const route = (cable && cable.route) || {};
  let elev = 0;
  list(run.via).forEach(function (id) { const p = pathById(fp, id); if (p) elev += Math.max(0, num(p.elevation_m)); });
  return run.length_m + Math.max(0, num(route.slack_m)) + 2 * Math.max(0, num(route.drop_m)) + elev;
}

function routables(doc) {
  return list(doc && doc.cables).filter(function (c) { return c && !c.auto; })
    .concat(list(doc && doc.bundles).filter(function (b) { return b && b.from && b.to && b.from.device && b.to.device; }));
}

// Runs of every cable (and bundle with device ends) whose two ends are placed on the plan.
export function runsForPlan(doc, fpId) {
  const fp = findPlan(doc, fpId);
  if (!fp) return [];
  const out = [];
  routables(doc).forEach(function (c) {
    const r = resolveRun(doc, fp, c);
    if (r) out.push(r);
  });
  return out;
}

// Cables with exactly one end on the plan (the server's `unplaced`).
export function halfPlaced(doc, fpId) {
  const fp = findPlan(doc, fpId);
  if (!fp) return [];
  return routables(doc).filter(function (c) {
    const a = !!markerOf(fp, c.from && c.from.device);
    const b = !!markerOf(fp, c.to && c.to.device);
    return a !== b;
  }).map(function (c) { return c.id; });
}

export function roundUp(v, step) {
  const s = step > 0 ? step : ESTIMATE_ROUND;
  return Math.round(Math.ceil(v / s - 1e-9) * s * 1000) / 1000;
}

// [{cable, from_m, to_m}] for the runs whose rounded-up estimate differs from length_m.
// `only` limits it to those cable ids.
export function estimateChanges(doc, fpId, only, roundTo) {
  const want = only ? idSet(list(only).map(function (id) { return {id: id}; })) : null;
  const out = [];
  runsForPlan(doc, fpId).forEach(function (r) {
    if (want && !want[r.cable]) return;
    if (r.estimate_m == null) return;
    const to = roundUp(r.estimate_m, roundTo);
    const ent = entityById(doc, r.cable);
    const from = ent && ent.length_m != null && isFinite(Number(ent.length_m)) ? Number(ent.length_m) : null;
    if (from !== null && Math.abs(from - to) < 1e-9) return;
    out.push({cable: r.cable, from_m: from, to_m: to});
  });
  return out;
}

export function runLabel(run, units) {
  if (!run) return '';
  if (run.unit !== 'm') return '?';
  return formatLength(run.length_m, units);
}

function entityById(doc, id) {
  const cs = list(doc && doc.cables);
  for (let i = 0; i < cs.length; i++) if (cs[i].id === id) return cs[i];
  const bs = list(doc && doc.bundles);
  for (let i = 0; i < bs.length; i++) if (bs[i].id === id) return bs[i];
  return null;
}

function collOf(doc, id) {
  if (list(doc && doc.cables).some(function (c) { return c.id === id; })) return 'cables';
  if (list(doc && doc.bundles).some(function (b) { return b.id === id; })) return 'bundles';
  return null;
}

// Cables / bundles whose route.via names the path.
export function pathUsers(doc, pathId) {
  return list(doc && doc.cables).concat(list(doc && doc.bundles)).filter(function (c) {
    return c && c.route && list(c.route.via).indexOf(pathId) >= 0;
  }).map(function (c) { return c.id; });
}

function normPoints(points) {
  const out = [];
  list(points).map(xy).forEach(function (p) {
    if (!isFinite(p[0]) || !isFinite(p[1])) return;
    const q = [round(clamp01(p[0]), 5), round(clamp01(p[1]), 5)];
    if (!out.length || !samePt(out[out.length - 1], q)) out.push(q);
  });
  return out;
}

function newPathId(fp) {
  const taken = idSet(fp && fp.paths);
  for (;;) {
    let s = '';
    for (let i = 0; i < 8; i++) s += Math.floor(Math.random() * 16).toString(16);
    if (!taken['pt-' + s]) return 'pt-' + s;
  }
}

function pathFields(target, spec) {
  if (spec.name !== undefined) target.name = String(spec.name || '').trim();
  if (spec.kind !== undefined) target.kind = pathKind(spec.kind);
  if (spec.points !== undefined) target.points = normPoints(spec.points);
  ['color', 'note'].forEach(function (k) {
    if (spec[k] === undefined) return;
    if (spec[k] === null || spec[k] === '') delete target[k]; else target[k] = String(spec[k]);
  });
  if (spec.elevation_m !== undefined) {
    const e = Number(spec.elevation_m);
    if (spec.elevation_m === null || spec.elevation_m === '' || !(e > 0)) delete target.elevation_m; else target.elevation_m = e;
  }
  return target;
}

// Add a path: spec {name, kind, points, color?, elevation_m?, note?} -> {ops, id}.
export function addPathOps(doc, fpId, spec) {
  const fp = findPlan(doc, fpId);
  const pts = normPoints(spec && spec.points);
  if (!fp || pts.length < 2) return {ops: [], id: ''};
  const id = (spec.id && !pathById(fp, spec.id)) ? spec.id : newPathId(fp);
  const path = pathFields({id: id, name: '', kind: 'other', points: pts}, Object.assign({}, spec, {points: pts}));
  if (!path.name) path.name = 'Path ' + (list(fp.paths).length + 1);
  return {ops: [{op: 'merge', coll: 'floorplans', id: fpId, value: {paths: list(fp.paths).concat([path])}}], id: id};
}

export function updatePathOps(doc, fpId, pathId, patch) {
  const fp = findPlan(doc, fpId);
  if (!fp || !pathById(fp, pathId)) return [];
  let changed = false;
  const paths = list(fp.paths).map(function (p) {
    if (p.id !== pathId) return p;
    const next = pathFields(Object.assign({}, p), patch || {});
    if (next.points && next.points.length < 2) next.points = p.points;
    if (!next.name) next.name = p.name;
    if (JSON.stringify(next) !== JSON.stringify(p)) changed = true;
    return next;
  });
  return changed ? [{op: 'merge', coll: 'floorplans', id: fpId, value: {paths: paths}}] : [];
}

// Delete a path and strip its id from every route.via that names it.
export function deletePathOps(doc, fpId, pathId) {
  const fp = findPlan(doc, fpId);
  if (!fp || !pathById(fp, pathId)) return [];
  const ops = [{op: 'merge', coll: 'floorplans', id: fpId, value: {paths: list(fp.paths).filter(function (p) { return p.id !== pathId; })}}];
  pathUsers(doc, pathId).forEach(function (id) {
    const ent = entityById(doc, id);
    ops.push({op: 'merge', coll: collOf(doc, id), id: id, value: {route: {via: list(ent.route.via).filter(function (v) { return v !== pathId; })}}});
  });
  return ops;
}

// Normalised route object: {plan, points, via, slack_m, drop_m, mode}.
export function normalizeRoute(route) {
  const r = route || {};
  const via = [];
  list(r.via).forEach(function (v) { if (typeof v === 'string' && v && via.indexOf(v) < 0) via.push(v); });
  return {
    plan: String(r.plan || ''),
    points: normPoints(r.points),
    via: via,
    slack_m: Math.max(0, num(r.slack_m)),
    drop_m: Math.max(0, num(r.drop_m)),
    mode: r.mode === 'manual' ? 'manual' : 'auto',
  };
}

export function setRouteOps(doc, cableId, route) {
  const coll = collOf(doc, cableId);
  if (!coll) return [];
  const value = normalizeRoute(route);
  if (!value.plan) return [];
  const cur = entityById(doc, cableId).route;
  if (cur && JSON.stringify(normalizeRoute(cur)) === JSON.stringify(value) && JSON.stringify(cur) === JSON.stringify(value)) return [];
  return [{op: 'merge', coll: coll, id: cableId, value: {route: value}}];
}

export function clearRouteOps(doc, cableId) {
  const coll = collOf(doc, cableId);
  if (!coll || !entityById(doc, cableId).route) return [];
  return [{op: 'merge', coll: coll, id: cableId, value: {route: null}}];
}

// ----------------------------------------------------------------- viewport
// view = {x, y, k}: screen = world * k + (x, y); world = image px.

export function clampK(k, min, max) {
  const lo = min == null ? ZOOM_MIN : min;
  const hi = max == null ? ZOOM_MAX : max;
  return Math.max(lo, Math.min(hi, k));
}

export function fitView(imgW, imgH, viewW, viewH, margin) {
  const m = margin == null ? 16 : margin;
  const k = clampK(Math.min((viewW - 2 * m) / imgW, (viewH - 2 * m) / imgH));
  return {x: (viewW - imgW * k) / 2, y: (viewH - imgH * k) / 2, k: k};
}

export function screenToWorld(view, pt) {
  return {x: (pt.x - view.x) / view.k, y: (pt.y - view.y) / view.k};
}

export function worldToScreen(view, pt) {
  return {x: pt.x * view.k + view.x, y: pt.y * view.k + view.y};
}

export function zoomAt(view, pt, factor, min, max) {
  const k = clampK(view.k * factor, min, max);
  const w = screenToWorld(view, pt);
  return {x: pt.x - w.x * k, y: pt.y - w.y * k, k: k};
}

export function panBy(view, dx, dy) {
  return {x: view.x + dx, y: view.y + dy, k: view.k};
}

// Two-pointer pinch: start {a, b, view} and current points a2, b2 (screen).
export function pinchView(start, a2, b2, min, max) {
  const d0 = Math.hypot(start.b.x - start.a.x, start.b.y - start.a.y) || 1;
  const d1 = Math.hypot(b2.x - a2.x, b2.y - a2.y) || 1;
  const m0 = {x: (start.a.x + start.b.x) / 2, y: (start.a.y + start.b.y) / 2};
  const m1 = {x: (a2.x + b2.x) / 2, y: (a2.y + b2.y) / 2};
  const k = clampK(start.view.k * d1 / d0, min, max);
  const w = screenToWorld(start.view, m0);
  return {x: m1.x - w.x * k, y: m1.y - w.y * k, k: k};
}
