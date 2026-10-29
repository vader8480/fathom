// Rack core (pure): RU occupancy, collisions, snapping, faces, rack items, ops.
// `u` is the physical lowest occupied RU, 1 = bottom (FR-RACK-02); `numbering`
// and `start_u` only change the printed RU labels (ruLabel).
// Rack items (blanks, shelves, …) take part in occupancy and collisions as
// `item:<id>`; devices on a shelf (`rack.shelf`) do not.

export const RU_PX = 22;
export const RACK_W = 320;
export const HALF_W = 160;
export const FACES = ['front', 'rear'];

function freeze(o) {
  return Object.freeze(o);
}

export const ITEM_TYPES = Object.freeze([
  freeze({type: 'blank', label: 'Blank panel', height: 1, face: 'front', depth: 'half', color: '#44475a'}),
  freeze({type: 'vent', label: 'Vent panel', height: 1, face: 'front', depth: 'half', color: '#44475a'}),
  freeze({type: 'shelf', label: 'Shelf', height: 1, face: 'front', depth: 'full', color: '#6272a4', slots: 2}),
  freeze({type: 'drawer', label: 'Drawer', height: 2, face: 'front', depth: 'full', color: '#6272a4'}),
  freeze({type: 'cable_manager', label: 'Cable manager', height: 1, face: 'front', depth: 'half', color: '#6272a4'}),
  freeze({type: 'brush', label: 'Brush panel', height: 1, face: 'front', depth: 'half', color: '#6272a4'}),
  freeze({type: 'lacing_bar', label: 'Lacing bar', height: 1, face: 'rear', depth: 'half', color: '#6272a4'}),
  freeze({type: 'other', label: 'Accessory', height: 1, face: 'front', depth: 'half', color: '#6272a4'}),
]);

const TYPE_BY = {};
ITEM_TYPES.forEach(function (t) { TYPE_BY[t.type] = t; });

const WIDTHS_IN = [10, 19, 21, 23];
const ITEM_PREFIX = 'item:';

function list(v) {
  return Array.isArray(v) ? v : [];
}

function isObj(v) {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

function clone(v) {
  return v === undefined ? undefined : JSON.parse(JSON.stringify(v));
}

// Integer from a number or an integer string; NaN otherwise.
function toInt(v) {
  if (typeof v === 'number') return isFinite(v) && Math.floor(v) === v ? v : NaN;
  if (typeof v === 'string' && /^\s*-?\d+\s*$/.test(v)) return parseInt(v, 10);
  return NaN;
}

function num(v) {
  return typeof v === 'number' && isFinite(v) ? v : null;
}

function isColor(v) {
  return typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v);
}

function isFace(v) {
  return v === 'front' || v === 'rear';
}

function isDepth(v) {
  return v === 'full' || v === 'half';
}

function has(o, k) {
  return Object.prototype.hasOwnProperty.call(o, k);
}

// Round to 1 decimal like Python's round(x, 1): exact binary ties (x.25, x.75)
// go to the even digit; everything else rounds the exact value to nearest.
function round1(x) {
  const q = x * 4;
  if (Math.floor(q) === q && Math.abs(q % 2) === 1) {
    const f = Math.floor(x * 10);
    return (Math.abs(f % 2) === 0 ? f : f + 1) / 10;
  }
  return Number(x.toFixed(1));
}

export function findRack(doc, rackId) {
  const racks = list(doc && doc.racks);
  for (let i = 0; i < racks.length; i++) if (racks[i] && racks[i].id === rackId) return racks[i];
  return null;
}

function findDevice(doc, id) {
  const devs = list(doc && doc.devices);
  for (let i = 0; i < devs.length; i++) if (devs[i] && devs[i].id === id) return devs[i];
  return null;
}

function findTemplate(doc, tid, info) {
  if (!tid) return null;
  const ts = list(doc && doc.templates);
  for (let i = 0; i < ts.length; i++) if (ts[i] && ts[i].id === tid) return ts[i];
  return isObj(info) && isObj(info[tid]) ? info[tid] : null;
}

export function rackUnits(rack) {
  const u = parseInt(rack && rack.units, 10);
  return u >= 1 ? Math.min(u, 60) : 1;
}

function startU(rack) {
  const s = toInt(rack && rack.start_u);
  return s >= 0 ? s : 1;
}

function widthIn(rack) {
  const w = toInt(rack && rack.width_in);
  return WIDTHS_IN.indexOf(w) >= 0 ? w : 19;
}

// Default RU height for a device: rack.height, else a project template's ru, else 1.
export function heightOf(doc, device) {
  const r = device && device.rack;
  if (r && parseInt(r.height, 10) >= 1) return parseInt(r.height, 10);
  const tid = device && device.template;
  if (tid) {
    const t = list(doc && doc.templates).filter(function (x) { return x && x.id === tid; })[0];
    if (t && parseInt(t.ru, 10) >= 1) return parseInt(t.ru, 10);
  }
  return 1;
}

function slotOf(v) {
  const s = toInt(v);
  return s >= 0 ? s : null;
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
    shelf: r.shelf ? String(r.shelf) : '',
    slot: slotOf(r.slot),
    color: isColor(r.color) ? r.color : '',
  };
}

// Every device in the rack, shelf children included (marked by `shelf`).
export function rackDevices(doc, rackId) {
  return list(doc && doc.devices)
    .filter(function (d) { return d && d.rack && d.rack.id === rackId && !d.auto; })
    .map(function (d) { return placement(doc, d); });
}

// Devices that occupy RUs themselves (not standing on a shelf).
function rackLevel(doc, rackId) {
  return rackDevices(doc, rackId).filter(function (p) { return !p.shelf; });
}

// ------------------------------------------------------------------ items

function normItem(raw) {
  const t = TYPE_BY[raw.type] || TYPE_BY.other;
  const u = toInt(raw.u);
  const h = toInt(raw.height);
  const out = {
    id: String(raw.id),
    type: t.type,
    u: isNaN(u) ? 0 : u,
    height: h >= 1 ? h : t.height,
    face: isFace(raw.face) ? raw.face : t.face,
    depth: isDepth(raw.depth) ? raw.depth : t.depth,
    label: typeof raw.label === 'string' && raw.label ? raw.label : t.label,
    color: isColor(raw.color) ? raw.color : t.color,
    slots: null,
    weight_kg: num(raw.weight_kg),
    notes: typeof raw.notes === 'string' ? raw.notes : '',
  };
  if (t.type === 'shelf') {
    const s = toInt(raw.slots);
    out.slots = s >= 1 ? Math.min(s, 4) : t.slots;
  }
  return out;
}

function validRaw(it) {
  return isObj(it) && it.id != null && it.id !== '';
}

// -> [{id, type, u, height, face, depth, label, color, slots, weight_kg, notes}]
// with ITEM_TYPES defaults filled in (unknown types read as `other`).
export function rackItems(doc, rackId) {
  const rack = findRack(doc, rackId);
  return list(rack && rack.items).filter(validRaw).map(normItem);
}

function findItem(doc, rackId, itemId) {
  const items = rackItems(doc, rackId);
  for (let i = 0; i < items.length; i++) if (items[i].id === itemId) return items[i];
  return null;
}

function itemPlacement(it) {
  return {device: ITEM_PREFIX + it.id, u: it.u, height: it.height, face: it.face, side: 'full', depth: it.depth};
}

// Rack-level devices (doc order) then items (array order).
function participants(doc, rackId) {
  return rackLevel(doc, rackId).concat(rackItems(doc, rackId).map(itemPlacement));
}

// Devices standing on shelf `itemId` of the rack, in doc order.
function shelfChildren(doc, rackId, itemId) {
  return list(doc && doc.devices).filter(function (d) {
    return d && d.rack && d.rack.id === rackId && d.rack.shelf != null && String(d.rack.shelf) === itemId;
  });
}

// ---------------------------------------------------------- occupancy, fits

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

// -> array indexed by u (1..units; index 0 unused) of {left, right}; items
// appear as `item:<id>`.
export function occupancy(doc, rackId, face) {
  const rack = findRack(doc, rackId);
  const units = rackUnits(rack);
  const out = [null];
  for (let u = 1; u <= units; u++) out.push({left: null, right: null});
  const f = face === 'rear' ? 'rear' : 'front';
  participants(doc, rackId).forEach(function (p) {
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

function cmp(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

// -> [{a, b, u, face}] one entry per colliding pair and face, a < b, sorted by
// (u, face, a, b). Items are written `item:<id>`; shelf children never collide.
export function collisions(doc, rackId) {
  const ps = participants(doc, rackId);
  const out = [];
  for (let i = 0; i < ps.length; i++) {
    for (let j = i + 1; j < ps.length; j++) {
      FACES.forEach(function (face) {
        if (!placementsCollide(ps[i], ps[j], face)) return;
        const x = ps[i].device;
        const y = ps[j].device;
        out.push({a: x < y ? x : y, b: x < y ? y : x, u: overlapU(ps[i], ps[j]), face: face});
      });
    }
  }
  return out.sort(function (p, q) {
    return (p.u - q.u) || cmp(p.face, q.face) || cmp(p.a, q.a) || cmp(p.b, q.b);
  });
}

export function outOfRange(doc, rackId) {
  const rack = findRack(doc, rackId);
  const units = rackUnits(rack);
  return rackLevel(doc, rackId).filter(function (p) { return p.u < 1 || p.u + p.height - 1 > units; })
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

function conflictsOf(doc, rackId, c, self) {
  return participants(doc, rackId).filter(function (p) {
    return p.device !== self && FACES.some(function (f) { return placementsCollide(c, p, f); });
  }).map(function (p) { return p.device; });
}

function fitResult(rack, c, conflicts) {
  if (!rack) return {ok: false, reason: 'rack_unknown', conflicts: []};
  if (!(c.u >= 1) || c.u + c.height - 1 > rackUnits(rack)) return {ok: false, reason: 'out_of_range', conflicts: []};
  return conflicts.length ? {ok: false, reason: 'occupied', conflicts: conflicts} : {ok: true, reason: '', conflicts: []};
}

// -> {ok, reason, conflicts:[ids]}; reason ∈ '', rack_unknown, out_of_range, occupied.
// Conflicts list rack-level devices (doc order) then items (`item:<id>`).
export function fits(doc, rackId, deviceId, u, opts) {
  const rack = findRack(doc, rackId);
  if (!rack) return fitResult(null);
  const c = candidate(doc, deviceId, rackId, u, opts);
  return fitResult(rack, c, conflictsOf(doc, rackId, c, deviceId));
}

function itemCandidate(doc, rackId, itemId, u, spec) {
  const s = spec || {};
  const rack = findRack(doc, rackId);
  let raw = null;
  if (itemId) {
    const items = list(rack && rack.items);
    for (let i = 0; i < items.length; i++) if (validRaw(items[i]) && String(items[i].id) === itemId) { raw = items[i]; break; }
  }
  const t = TYPE_BY[s.type] || (raw && TYPE_BY[raw.type]) || TYPE_BY.other;
  function pick(k, ok) {
    if (ok(s[k])) return s[k];
    if (raw && ok(raw[k])) return raw[k];
    return t[k];
  }
  return {
    device: ITEM_PREFIX + (itemId || ''),
    u: parseInt(u, 10),
    height: toInt(pick('height', function (v) { return toInt(v) >= 1; })),
    face: pick('face', isFace),
    depth: pick('depth', isDepth),
    side: 'full',
    type: t.type,
  };
}

// -> {ok, reason, conflicts}. itemId is null for a new item; spec
// {type, height, face, depth} defaults from the existing item, then ITEM_TYPES.
export function itemFits(doc, rackId, itemId, u, spec) {
  const rack = findRack(doc, rackId);
  if (!rack) return fitResult(null);
  const c = itemCandidate(doc, rackId, itemId, u, spec);
  return fitResult(rack, c, conflictsOf(doc, rackId, c, itemId ? ITEM_PREFIX + itemId : null));
}

function itemFirstFit(doc, rackId, itemId, spec) {
  const rack = findRack(doc, rackId);
  if (!rack) return 0;
  const c = itemCandidate(doc, rackId, itemId, 1, spec);
  for (let u = rackUnits(rack) - c.height + 1; u >= 1; u--) {
    if (itemFits(doc, rackId, itemId, u, spec).ok) return u;
  }
  return 0;
}

// opts {face, height, side, depth, force}. Returns [] when it does not fit and
// force is not set (the UI refuses the drop). Taking a device off a shelf clears
// `shelf`/`slot`.
export function placeOps(doc, deviceId, rackId, u, opts) {
  const o = opts || {};
  const dev = findDevice(doc, deviceId);
  if (!dev) return [];
  const f = fits(doc, rackId, deviceId, u, o);
  if (!f.ok && !(o.force && f.reason === 'occupied')) return [];
  const c = candidate(doc, deviceId, rackId, u, o);
  const value = {id: rackId, u: c.u, height: c.height, face: c.face, side: c.side};
  if (o.depth || c.depth === 'half') value.depth = c.depth;
  if (dev.rack && dev.rack.shelf != null) { value.shelf = null; value.slot = null; }
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

// Printed label of RU `u`: start_u (default 1) is the label of the first RU
// counted from the bottom (bottom_up) or the top (top_down).
export function ruLabel(rack, u) {
  const s = startU(rack);
  const n = rack && rack.numbering === 'top_down' ? rackUnits(rack) - u + s : u - 1 + s;
  return String(n);
}

// Drawn inner width: 320 px for 19", scaled for 10/21/23".
export function rackWidthPx(rack) {
  return Math.round(RACK_W * widthIn(rack) / 19);
}

export function sideX(side, rack) {
  return side === 'right' ? Math.floor(rackWidthPx(rack) / 2) : 0;
}

export function sideW(side, rack) {
  const w = rackWidthPx(rack);
  if (side === 'full') return w;
  return side === 'right' ? w - Math.floor(w / 2) : Math.floor(w / 2);
}

// Blocks to draw on one face: [{device, u, height, face, side, depth, shelf, slot, color, x, y, w, h, behind}]
// `behind` = a full-depth device mounted on the other face (seen from its back).
// Shelf children are drawn by shelfChildBlocks instead.
export function faceBlocks(doc, rackId, face) {
  const rack = findRack(doc, rackId);
  if (!rack) return [];
  const f = face === 'rear' ? 'rear' : 'front';
  return rackLevel(doc, rackId).filter(function (p) { return blocksFace(p, f); }).map(function (p) {
    return Object.assign({}, p, {
      x: sideX(p.side, rack), y: uToY(rack, p.u, p.height), w: sideW(p.side, rack), h: p.height * RU_PX,
      behind: p.face !== f,
    });
  });
}

// Item blocks on one face (items are always full width).
export function itemBlocks(doc, rackId, face) {
  const rack = findRack(doc, rackId);
  if (!rack) return [];
  const f = face === 'rear' ? 'rear' : 'front';
  const w = rackWidthPx(rack);
  return rackItems(doc, rackId).filter(function (it) { return blocksFace(it, f); }).map(function (it) {
    return {
      id: ITEM_PREFIX + it.id, item: it.id, type: it.type, u: it.u, height: it.height, face: it.face, depth: it.depth,
      label: it.label, color: it.color, slots: it.slots,
      x: 0, y: uToY(rack, it.u, it.height), w: w, h: it.height * RU_PX, behind: it.face !== f,
    };
  });
}

// -> [{slot, device}] with length = slots; device = the first device (doc order)
// on that cell or null. Devices with a slot outside 0..slots-1 are left out.
export function shelfCells(doc, rackId, itemId) {
  const it = findItem(doc, rackId, itemId);
  if (!it || it.type !== 'shelf') return [];
  const cells = [];
  for (let s = 0; s < it.slots; s++) cells.push({slot: s, device: null});
  shelfChildren(doc, rackId, itemId).forEach(function (d) {
    if (d.auto) return;
    const s = slotOf(d.rack.slot);
    if (s !== null && s < it.slots && !cells[s].device) cells[s].device = d.id;
  });
  return cells;
}

// Devices drawn inside the cells of the shelves visible on `face`:
// [{device, item, slot, x, y, w, h, behind}].
export function shelfChildBlocks(doc, rackId, face) {
  const rack = findRack(doc, rackId);
  if (!rack) return [];
  const f = face === 'rear' ? 'rear' : 'front';
  const w = rackWidthPx(rack);
  const out = [];
  rackItems(doc, rackId).forEach(function (it) {
    if (it.type !== 'shelf' || !blocksFace(it, f)) return;
    const cw = w / it.slots;
    const y = uToY(rack, it.u, it.height);
    shelfCells(doc, rackId, it.id).forEach(function (c) {
      if (!c.device) return;
      out.push({device: c.device, item: it.id, slot: c.slot, x: c.slot * cw, y: y, w: cw, h: it.height * RU_PX, behind: it.face !== f});
    });
  });
  return out;
}

// --------------------------------------------------------------- summaries

// -> {units, used_u, free_u, weight_kg, max_load_kg, power_w, power_limit_w, devices, items}
// or null for an unknown rack. `info` = optional {templateId: {weight_kg, power_w}};
// doc.templates win over it. Numbers are rounded to 1 decimal.
export function rackTotals(doc, rackId, info) {
  const rack = findRack(doc, rackId);
  if (!rack) return null;
  const units = rackUnits(rack);
  const used = {};
  participants(doc, rackId).forEach(function (p) {
    for (let u = p.u; u < p.u + p.height; u++) if (u >= 1 && u <= units) used[u] = true;
  });
  const usedU = Object.keys(used).length;
  const devs = list(doc && doc.devices).filter(function (d) { return d && d.rack && d.rack.id === rackId && !d.auto; });
  const items = rackItems(doc, rackId);
  let devW = 0;
  let devP = 0;
  devs.forEach(function (d) {
    const t = findTemplate(doc, d.template, info) || {};
    const w = num(d.weight_kg) !== null ? d.weight_kg : num(t.weight_kg) !== null ? t.weight_kg : 0;
    const p = num(d.power_w) !== null ? d.power_w : num(t.power_w) !== null ? t.power_w : 0;
    devW += w;
    devP += p;
  });
  let itemW = 0;
  items.forEach(function (it) { if (it.weight_kg !== null) itemW += it.weight_kg; });
  const rackW = num(rack.weight_kg) !== null ? rack.weight_kg : 0;
  const maxLoad = num(rack.max_load_kg);
  const powerLimit = num(rack.power_limit_w);
  return {
    units: units,
    used_u: usedU,
    free_u: units - usedU,
    weight_kg: round1(rackW + devW + itemW),
    max_load_kg: maxLoad === null ? null : round1(maxLoad),
    power_w: round1(devP),
    power_limit_w: powerLimit === null ? null : round1(powerLimit),
    devices: devs.length,
    items: items.length,
  };
}

// -> [{row, racks}]: racks sorted by (order ?? 1e9, name); racks sharing a
// non-empty row are grouped where the first of them sorts; no row = own group.
export function racksByRow(racks) {
  const rs = list(racks).filter(isObj).map(function (r, i) { return {r: r, i: i}; });
  function ord(r) { return num(r.order) !== null ? r.order : 1e9; }
  function name(r) { return r.name == null ? '' : String(r.name); }
  rs.sort(function (a, b) {
    return (ord(a.r) - ord(b.r)) || cmp(name(a.r), name(b.r)) || (a.i - b.i);
  });
  const out = [];
  const byRow = {};
  rs.forEach(function (x) {
    const row = x.r.row == null ? '' : String(x.r.row);
    if (!row) { out.push({row: '', racks: [x.r]}); return; }
    if (has(byRow, row)) { byRow[row].racks.push(x.r); return; }
    byRow[row] = {row: row, racks: [x.r]};
    out.push(byRow[row]);
  });
  return out;
}

// --------------------------------------------------------------- rack ops

function slug(text) {
  const s = String(text == null ? '' : text).trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+/, '').replace(/-+$/, '');
  return s || 'item';
}

function dedupe(base, taken) {
  let id = base;
  for (let n = 2; has(taken, id); n++) id = base + '-' + n;
  return id;
}

function idSet(arr, extra) {
  const taken = {};
  list(arr).forEach(function (x) { if (x && x.id != null) taken[x.id] = true; });
  if (isObj(extra)) Object.keys(extra).forEach(function (k) { taken[k] = true; });
  return taken;
}

// spec {name, units, room, location, numbering, notes}
export function newRackOps(doc, spec) {
  const taken = idSet(doc && doc.racks);
  const id = dedupe('rk-' + slug(spec.name), taken);
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

// ---------------------------------------------------------------- item ops

function rawItems(rack) {
  return list(rack && rack.items).map(clone);
}

function rawIndex(items, itemId) {
  for (let i = 0; i < items.length; i++) if (validRaw(items[i]) && String(items[i].id) === itemId) return i;
  return -1;
}

function itemsOp(rackId, items) {
  return {op: 'merge', coll: 'racks', id: rackId, value: {items: items}};
}

function devMerge(id, rack) {
  return {op: 'merge', coll: 'devices', id: id, value: {rack: rack}};
}

function nextItemId(rack) {
  const taken = {};
  list(rack && rack.items).forEach(function (it) { if (validRaw(it)) taken[String(it.id)] = true; });
  let n = 1;
  while (taken['ri-' + n]) n++;
  return 'ri-' + n;
}

// Keep shelf children at their shelf's u/face; unrack the ones whose cell is
// gone (`dropped(device)` true).
function syncChildren(doc, rackId, itemId, shelf, dropped) {
  const ops = [];
  shelfChildren(doc, rackId, itemId).forEach(function (d) {
    if (!shelf || dropped(d)) { ops.push(devMerge(d.id, null)); return; }
    if (d.rack.u !== shelf.u || (d.rack.face === 'rear' ? 'rear' : 'front') !== shelf.face) ops.push(devMerge(d.id, {u: shelf.u, face: shelf.face}));
  });
  return ops;
}

// spec {type, u?, height?, face?, depth?, label?, color?, slots?, weight_kg?, notes?, force?}
// -> {ops, id}. Without u: the first fit from the top. {ops: [], id: ''} when
// the type is unknown or nothing fits.
export function addItemOps(doc, rackId, spec) {
  const none = {ops: [], id: ''};
  const rack = findRack(doc, rackId);
  const s = spec || {};
  const t = TYPE_BY[s.type];
  if (!rack || !t) return none;
  const h = toInt(s.height);
  const fit = {type: t.type, height: h >= 1 ? h : t.height, face: isFace(s.face) ? s.face : t.face, depth: isDepth(s.depth) ? s.depth : t.depth};
  let u;
  if (s.u != null && s.u !== '') {
    u = parseInt(s.u, 10);
    const f = itemFits(doc, rackId, null, u, fit);
    if (!f.ok && !(s.force && f.reason === 'occupied')) return none;
  } else {
    u = itemFirstFit(doc, rackId, null, fit);
    if (!u) return none;
  }
  const id = nextItemId(rack);
  const item = {id: id, type: t.type, u: u, height: fit.height, face: fit.face, depth: fit.depth};
  if (typeof s.label === 'string' && s.label) item.label = s.label;
  if (isColor(s.color)) item.color = s.color;
  if (t.type === 'shelf') {
    const n = toInt(s.slots);
    item.slots = n >= 1 ? Math.min(n, 4) : t.slots;
  }
  if (num(s.weight_kg) !== null) item.weight_kg = s.weight_kg;
  if (typeof s.notes === 'string' && s.notes) item.notes = s.notes;
  return {ops: [itemsOp(rackId, rawItems(rack).concat([item]))], id: id};
}

// opts {face?, force?}. Refuses ([]) on a collision unless force, and always
// when out of range. Shelf children follow their shelf.
export function moveItemOps(doc, rackId, itemId, u, opts) {
  const o = opts || {};
  const rack = findRack(doc, rackId);
  const items = rawItems(rack);
  const i = rawIndex(items, itemId);
  if (i < 0) return [];
  const spec = isFace(o.face) ? {face: o.face} : {};
  const f = itemFits(doc, rackId, itemId, u, spec);
  if (!f.ok && !(o.force && f.reason === 'occupied')) return [];
  items[i].u = parseInt(u, 10);
  if (spec.face) items[i].face = spec.face;
  const it = normItem(items[i]);
  const ops = [itemsOp(rackId, items)];
  if (it.type === 'shelf') return ops.concat(syncChildren(doc, rackId, itemId, it, function () { return false; }));
  return ops;
}

// patch: item fields; null removes a field, `id` is ignored. A shelf that
// loses cells (or stops being a shelf) unracks the devices on them.
export function updateItemOps(doc, rackId, itemId, patch) {
  const rack = findRack(doc, rackId);
  const items = rawItems(rack);
  const i = rawIndex(items, itemId);
  if (i < 0) return [];
  const before = normItem(items[i]);
  const p = patch || {};
  Object.keys(p).forEach(function (k) {
    if (k === 'id' || p[k] === undefined) return;
    if (p[k] === null) delete items[i][k];
    else items[i][k] = clone(p[k]);
  });
  const after = normItem(items[i]);
  const ops = [itemsOp(rackId, items)];
  if (before.type !== 'shelf') return ops;
  return ops.concat(syncChildren(doc, rackId, itemId, after.type === 'shelf' ? after : null, function (d) {
    const s = slotOf(d.rack.slot);
    return s !== null && s < before.slots && s >= after.slots;
  }));
}

// Deleting an item also unracks the devices standing on it.
export function delItemOps(doc, rackId, itemId) {
  const rack = findRack(doc, rackId);
  const items = rawItems(rack);
  const i = rawIndex(items, itemId);
  if (i < 0) return [];
  items.splice(i, 1);
  return [itemsOp(rackId, items)].concat(syncChildren(doc, rackId, itemId, null));
}

// Put a device into cell `slot` of shelf `itemId`. [] if the item is not a
// shelf, the slot is out of range or another device holds the cell.
export function placeOnShelfOps(doc, deviceId, rackId, itemId, slot) {
  if (!findDevice(doc, deviceId)) return [];
  const it = findItem(doc, rackId, itemId);
  if (!it || it.type !== 'shelf') return [];
  const s = toInt(slot);
  if (!(s >= 0 && s < it.slots)) return [];
  const taken = shelfChildren(doc, rackId, itemId).some(function (d) {
    return d.id !== deviceId && slotOf(d.rack.slot) === s;
  });
  if (taken) return [];
  return [devMerge(deviceId, {id: rackId, u: it.u, height: 1, face: it.face, side: 'full', shelf: itemId, slot: s})];
}

// Where a copy of device `d` goes in rack `rackId`: a free cell of the same
// shelf, else the first rack-level fit from the top; null when nothing fits.
function copyPlacement(doc, d, rackId) {
  const r = d.rack || {};
  if (r.shelf != null && r.id === rackId) {
    const it = findItem(doc, rackId, String(r.shelf));
    const free = shelfCells(doc, rackId, String(r.shelf)).filter(function (c) { return !c.device; })[0];
    if (it && free) return Object.assign(clone(r), {id: rackId, u: it.u, face: it.face, slot: free.slot});
  }
  const rack = findRack(doc, rackId);
  const p = placement(doc, d);
  const c = {device: null, u: 0, height: p.height, face: p.face, side: p.side, depth: p.depth};
  for (let u = rackUnits(rack) - c.height + 1; u >= 1; u--) {
    c.u = u;
    if (!conflictsOf(doc, rackId, c, null).length) {
      const out = Object.assign(clone(r), {id: rackId, u: u, height: c.height, face: c.face, side: c.side});
      delete out.shelf;
      delete out.slot;
      return out;
    }
  }
  return null;
}

// -> {ops, id}. opts {rackId?: target rack (default the device's), rack?: an
// explicit rack value (null = unracked), taken?: {id: true} extra ids in use}.
export function duplicateDeviceOps(doc, deviceId, opts) {
  const o = opts || {};
  const d = findDevice(doc, deviceId);
  if (!d) return {ops: [], id: ''};
  const id = dedupe(slug(d.name || d.id), idSet(doc && doc.devices, o.taken));
  const copy = clone(d);
  copy.id = id;
  copy.name = String(d.name || d.id) + ' (copy)';
  delete copy.merged_from;
  delete copy.patch;
  delete copy.auto;
  delete copy.rack;
  if (isObj(copy.inventory)) {
    delete copy.inventory.serial;
    delete copy.inventory.asset_tag;
  }
  list(copy.interfaces).forEach(function (itf) {
    if (!isObj(itf)) return;
    delete itf.ip;
    delete itf.mac;
    delete itf.hostname;
  });
  if (has(o, 'rack')) {
    if (o.rack) copy.rack = clone(o.rack);
  } else {
    const rackId = o.rackId || (d.rack && d.rack.id) || '';
    const r = rackId && findRack(doc, rackId) ? copyPlacement(doc, d, rackId) : null;
    if (r) copy.rack = r;
  }
  return {ops: [{op: 'put', coll: 'devices', id: id, value: copy}], id: id};
}

// -> {ops, id}. Copies the rack (name + " (copy)", new rk- id, same items);
// opts.devices also copies its devices into the new rack at the same positions.
export function duplicateRackOps(doc, rackId, opts) {
  const o = opts || {};
  const rack = findRack(doc, rackId);
  if (!rack) return {ops: [], id: ''};
  const name = String(rack.name || rack.id) + ' (copy)';
  const id = dedupe('rk-' + slug(name), idSet(doc && doc.racks));
  const copy = clone(rack);
  copy.id = id;
  copy.name = name;
  const ops = [{op: 'put', coll: 'racks', id: id, value: copy}];
  if (o.devices) {
    const taken = {};
    list(doc && doc.devices).forEach(function (d) {
      if (!d || !d.rack || d.rack.id !== rackId || d.auto) return;
      const r = duplicateDeviceOps(doc, d.id, {rack: Object.assign(clone(d.rack), {id: id}), taken: taken});
      taken[r.id] = true;
      Array.prototype.push.apply(ops, r.ops);
    });
  }
  return {ops: ops, id: id};
}
