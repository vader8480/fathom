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
