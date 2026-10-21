// Rack core (pure): RU occupancy, collisions, snapping, faces, ops.
// `u` is the physical lowest occupied RU, 1 = bottom (FR-RACK-02); `numbering`
// only changes the printed RU labels (ruLabel).

export const RU_PX = 22;
export const RACK_W = 320;
export const HALF_W = 160;
export const FACES = ['front', 'rear'];

function list(v) {
  return Array.isArray(v) ? v : [];
}

export function findRack(doc, rackId) {
  const racks = list(doc && doc.racks);
  for (let i = 0; i < racks.length; i++) if (racks[i].id === rackId) return racks[i];
  return null;
}

function findDevice(doc, id) {
  const devs = list(doc && doc.devices);
  for (let i = 0; i < devs.length; i++) if (devs[i].id === id) return devs[i];
  return null;
}

export function rackUnits(rack) {
  const u = parseInt(rack && rack.units, 10);
  return u >= 1 ? Math.min(u, 60) : 1;
}

// Default RU height for a device: rack.height, else a project template's ru, else 1.
export function heightOf(doc, device) {
  const r = device && device.rack;
  if (r && parseInt(r.height, 10) >= 1) return parseInt(r.height, 10);
  const tid = device && device.template;
  if (tid) {
    const t = list(doc && doc.templates).filter(function (x) { return x.id === tid; })[0];
    if (t && parseInt(t.ru, 10) >= 1) return parseInt(t.ru, 10);
  }
  return 1;
}

export function placement(doc, device) {
  const r = device.rack || {};
  return {
    device: device.id,
    u: parseInt(r.u, 10) || 0,
    height: heightOf(doc, device),
    face: r.face === 'rear' ? 'rear' : 'front',
    side: r.side === 'left' || r.side === 'right' ? r.side : 'full',
    depth: r.depth === 'half' ? 'half' : 'full',
  };
}

export function rackDevices(doc, rackId) {
  return list(doc && doc.devices)
    .filter(function (d) { return d.rack && d.rack.id === rackId && !d.auto; })
    .map(function (d) { return placement(doc, d); });
}

// Does a placement block `face`? Full-depth devices block both faces.
export function blocksFace(p, face) {
  return p.face === face || p.depth === 'full';
}

function sidesOverlap(a, b) {
  return a === 'full' || b === 'full' || a === b;
}

function sideKeys(side) {
  return side === 'full' ? ['left', 'right'] : [side];
}

// -> array indexed by u (1..units; index 0 unused) of {left, right}.
export function occupancy(doc, rackId, face) {
  const rack = findRack(doc, rackId);
  const units = rackUnits(rack);
  const out = [null];
  for (let u = 1; u <= units; u++) out.push({left: null, right: null});
  const f = face === 'rear' ? 'rear' : 'front';
  rackDevices(doc, rackId).forEach(function (p) {
    if (!blocksFace(p, f)) return;
    for (let u = p.u; u < p.u + p.height; u++) {
      if (u < 1 || u > units) continue;
      sideKeys(p.side).forEach(function (s) { if (!out[u][s]) out[u][s] = p.device; });
    }
  });
  return out;
}

function overlapU(a, b) {
  const lo = Math.max(a.u, b.u);
  const hi = Math.min(a.u + a.height - 1, b.u + b.height - 1);
  return lo <= hi ? lo : 0;
}

function placementsCollide(a, b, face) {
  return blocksFace(a, face) && blocksFace(b, face) && sidesOverlap(a.side, b.side) && overlapU(a, b) > 0;
}

// -> [{a, b, u, face}] one entry per colliding pair and face.
export function collisions(doc, rackId) {
  const ps = rackDevices(doc, rackId);
  const out = [];
  for (let i = 0; i < ps.length; i++) {
    for (let j = i + 1; j < ps.length; j++) {
      FACES.forEach(function (face) {
        if (placementsCollide(ps[i], ps[j], face)) {
          out.push({a: ps[i].device, b: ps[j].device, u: overlapU(ps[i], ps[j]), face: face});
        }
      });
    }
  }
  return out;
}

export function outOfRange(doc, rackId) {
  const rack = findRack(doc, rackId);
  const units = rackUnits(rack);
  return rackDevices(doc, rackId).filter(function (p) { return p.u < 1 || p.u + p.height - 1 > units; })
    .map(function (p) { return p.device; });
}

// Resolve the placement a device would get at (rackId, u) with opts.
function candidate(doc, deviceId, rackId, u, opts) {
  const o = opts || {};
  const dev = findDevice(doc, deviceId);
  const cur = dev ? placement(doc, dev) : {height: 1, face: 'front', side: 'full', depth: 'full'};
  return {
    device: deviceId,
    u: parseInt(u, 10),
    height: parseInt(o.height, 10) >= 1 ? parseInt(o.height, 10) : cur.height,
    face: o.face || cur.face,
    side: o.side || cur.side,
    depth: o.depth || cur.depth,
  };
}

// -> {ok, reason, conflicts:[ids]}; reason ∈ '', rack_unknown, out_of_range, occupied
export function fits(doc, rackId, deviceId, u, opts) {
  const rack = findRack(doc, rackId);
  if (!rack) return {ok: false, reason: 'rack_unknown', conflicts: []};
  const c = candidate(doc, deviceId, rackId, u, opts);
  const units = rackUnits(rack);
  if (!(c.u >= 1) || c.u + c.height - 1 > units) return {ok: false, reason: 'out_of_range', conflicts: []};
  const conflicts = [];
  rackDevices(doc, rackId).forEach(function (p) {
    if (p.device === deviceId) return;
    if (FACES.some(function (f) { return placementsCollide(c, p, f); })) conflicts.push(p.device);
  });
  return conflicts.length ? {ok: false, reason: 'occupied', conflicts: conflicts} : {ok: true, reason: '', conflicts: []};
}

// opts {face, height, side, depth, force}. Returns [] when it does not fit and
// force is not set (the UI refuses the drop).
export function placeOps(doc, deviceId, rackId, u, opts) {
  const o = opts || {};
  if (!findDevice(doc, deviceId)) return [];
  const f = fits(doc, rackId, deviceId, u, o);
  if (!f.ok && !(o.force && f.reason === 'occupied')) return [];
  const c = candidate(doc, deviceId, rackId, u, o);
  const value = {id: rackId, u: c.u, height: c.height, face: c.face, side: c.side};
  if (o.depth || c.depth === 'half') value.depth = c.depth;
  return [{op: 'merge', coll: 'devices', id: deviceId, value: {rack: value}}];
}

export function unplaceOps(doc, deviceId) {
  const d = findDevice(doc, deviceId);
  if (!d || !d.rack) return [];
  return [{op: 'merge', coll: 'devices', id: deviceId, value: {rack: null}}];
}

// First u (from the top) where the device fits, or 0.
export function firstFit(doc, rackId, deviceId, opts) {
  const rack = findRack(doc, rackId);
  if (!rack) return 0;
  const c = candidate(doc, deviceId, rackId, 1, opts);
  for (let u = rackUnits(rack) - c.height + 1; u >= 1; u--) {
    if (fits(doc, rackId, deviceId, u, opts).ok) return u;
  }
  return 0;
}

// ----------------------------------------------------------------- geometry

export function uToY(rack, u, height) {
  const h = height || 1;
  return (rackUnits(rack) - (u + h - 1)) * RU_PX;
}

export function yToU(rack, y, height) {
  const units = rackUnits(rack);
  const h = Math.max(1, Math.min(height || 1, units));
  const u = units - h + 1 - Math.round(y / RU_PX);
  return Math.max(1, Math.min(units - h + 1, u));
}

export function ruLabel(rack, u) {
  const n = rack && rack.numbering === 'top_down' ? rackUnits(rack) - u + 1 : u;
  return String(n);
}

export function sideX(side) {
  return side === 'right' ? HALF_W : 0;
}

export function sideW(side) {
  return side === 'full' ? RACK_W : HALF_W;
}

// Blocks to draw on one face: [{device, u, height, face, side, depth, x, y, w, h, behind}]
// `behind` = a full-depth device mounted on the other face (seen from its back).
export function faceBlocks(doc, rackId, face) {
  const rack = findRack(doc, rackId);
  if (!rack) return [];
  const f = face === 'rear' ? 'rear' : 'front';
  return rackDevices(doc, rackId).filter(function (p) { return blocksFace(p, f); }).map(function (p) {
    return Object.assign({}, p, {
      x: sideX(p.side), y: uToY(rack, p.u, p.height), w: sideW(p.side), h: p.height * RU_PX,
      behind: p.face !== f,
    });
  });
}

// --------------------------------------------------------------- rack ops

function slug(text) {
  const s = String(text == null ? '' : text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return s || 'item';
}

// spec {name, units, room, location, numbering, notes}
export function newRackOps(doc, spec) {
  const taken = {};
  list(doc && doc.racks).forEach(function (r) { taken[r.id] = true; });
  let id = 'rk-' + slug(spec.name);
  for (let n = 2; taken[id]; n++) id = 'rk-' + slug(spec.name) + '-' + n;
  const units = Math.max(1, Math.min(60, parseInt(spec.units, 10) || 12));
  const value = {id: id, name: String(spec.name || id), units: units};
  if (spec.room) value.room = spec.room;
  if (spec.location) value.location = spec.location;
  if (spec.numbering === 'top_down') value.numbering = 'top_down';
  if (spec.notes) value.notes = spec.notes;
  return {ops: [{op: 'put', coll: 'racks', id: id, value: value}], id: id};
}

// Deleting a rack also unracks its devices (avoids rack_unknown warnings).
export function deleteRackOps(doc, rackId) {
  if (!findRack(doc, rackId)) return [];
  const ops = rackDevices(doc, rackId).map(function (p) {
    return {op: 'merge', coll: 'devices', id: p.device, value: {rack: null}};
  });
  ops.push({op: 'del', coll: 'racks', id: rackId});
  return ops;
}
