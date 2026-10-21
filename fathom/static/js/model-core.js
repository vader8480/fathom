// Fathom model core: doc helpers, change ops (§4.9), port-group expansion
// (§4.4.3), editing helpers, local search, viewport math and the shared store.
// Pure module: no window / document / fetch / timers. Imports in Node >= 18.

export const COLLECTIONS = ['venues', 'rooms', 'systems', 'locations', 'racks', 'networks', 'devices', 'cables', 'bundles', 'floorplans', 'attachments', 'templates', 'imports'];
export const ROOTS = ['meta', 'settings', 'media'];
export const NETWORK_MEDIA = ['dante', 'avb', 'aes67', 'aes50', 'madi', 'snake', 'network', 'qlan'];
export const STATUSES = ['installed', 'planned', 'spare', 'retired'];
export const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

const HAS = Object.prototype.hasOwnProperty;

export class OpError extends Error {
  constructor(code, message) {
    super(message || code);
    this.name = 'OpError';
    this.code = code;
  }
}

export class ReadOnlyError extends Error {
  constructor(message) {
    super(message || 'This view is read-only');
    this.name = 'ReadOnlyError';
    this.code = 'read_only';
  }
}

// ------------------------------------------------------------ small utils

export function isObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

export function deepClone(v) {
  if (Array.isArray(v)) return v.map(deepClone);
  if (isObject(v)) {
    const out = {};
    for (const k of Object.keys(v)) out[k] = deepClone(v[k]);
    return out;
  }
  return v;
}

export function canonicalJson(v) {
  if (Array.isArray(v)) return '[' + v.map(canonicalJson).join(',') + ']';
  if (isObject(v)) {
    const keys = Object.keys(v).sort();
    return '{' + keys.map(function (k) { return JSON.stringify(k) + ':' + canonicalJson(v[k]); }).join(',') + '}';
  }
  if (v === undefined) return 'null';
  return JSON.stringify(v);
}

export function deepEqual(a, b) {
  return canonicalJson(a) === canonicalJson(b);
}

function toSet(taken) {
  if (!taken) return new Set();
  if (taken instanceof Set) return taken;
  if (Array.isArray(taken)) {
    return new Set(taken.map(function (t) { return isObject(t) ? t.id : t; }));
  }
  if (isObject(taken)) return new Set(Object.keys(taken));
  return new Set();
}

// ------------------------------------------------------------ identifiers

export function slug(text) {
  const s = String(text == null ? '' : text).trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+/, '').replace(/-+$/, '');
  return s || 'item';
}

function randomToken(n) {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let s = '';
  for (let i = 0; i < n; i++) s += chars.charAt(Math.floor(Math.random() * chars.length));
  return s;
}

export function newId(prefix, taken, base) {
  const set = toSet(taken);
  if (base) {
    const b = slug(base);
    if (!set.has(b)) return b;
    let i = 2;
    while (set.has(b + '-' + i)) i++;
    return b + '-' + i;
  }
  let id;
  do { id = (prefix ? prefix + '-' : '') + randomToken(8); } while (set.has(id));
  return id;
}

export function portRef(device, port) {
  return port ? device + ':' + port : String(device);
}

export function parsePortRef(ref) {
  const s = String(ref == null ? '' : ref);
  const i = s.indexOf(':');
  if (i < 0) return { device: s, port: null };
  return { device: s.slice(0, i), port: s.slice(i + 1) || null };
}

export function entityRef(coll, id) {
  return id === undefined || id === null ? coll : coll + '/' + id;
}

// ------------------------------------------------------------ indexing

export function devicePorts(device) {
  return device && Array.isArray(device.ports) ? device.ports : [];
}

export function indexDoc(doc) {
  const idx = { byId: {}, ports: {}, cablesByDevice: {}, cablesByPort: {}, devicesByRoom: {} };
  for (const c of COLLECTIONS) {
    const m = {};
    const list = (doc && Array.isArray(doc[c])) ? doc[c] : [];
    for (const e of list) if (e && e.id !== undefined) m[e.id] = e;
    idx.byId[c] = m;
  }
  const devices = (doc && Array.isArray(doc.devices)) ? doc.devices : [];
  for (const d of devices) {
    const pm = {};
    for (const p of devicePorts(d)) pm[p.id] = p;
    idx.ports[d.id] = pm;
    const room = d.room || '';
    (idx.devicesByRoom[room] = idx.devicesByRoom[room] || []).push(d);
    idx.cablesByDevice[d.id] = idx.cablesByDevice[d.id] || [];
  }
  const cables = (doc && Array.isArray(doc.cables)) ? doc.cables : [];
  for (const c of cables) {
    const ends = [c.from || {}, c.to || {}];
    const seen = {};
    for (const e of ends) {
      if (!e.device) continue;
      if (!seen[e.device]) {
        (idx.cablesByDevice[e.device] = idx.cablesByDevice[e.device] || []).push(c);
        seen[e.device] = true;
      }
      const k = portRef(e.device, e.port);
      (idx.cablesByPort[k] = idx.cablesByPort[k] || []).push(c);
    }
  }
  return idx;
}

export function portLabel(port) {
  if (!port) return '';
  return port.label || port.name || port.id || '';
}

export function deviceTitle(device) {
  if (!device) return '';
  let t = device.name || device.id || '';
  if (device.count) t += ' \u00d7' + device.count;
  if (device.suffix) t += ' ' + device.suffix;
  return t;
}

export function disciplineOf(device, vocab) {
  if (!device) return 'other';
  if (device.discipline) return device.discipline;
  const k = vocab && vocab.kinds ? vocab.kinds[device.kind] : null;
  return (k && k.discipline) || 'other';
}

export function mediumInfo(medium, vocab) {
  const media = (vocab && vocab.media) || {};
  return media[medium] || media.other || { label: medium || 'Other', color: '#9aa3b5', dash: '', width: 1.2, arrow: true, discipline: 'other', carries: ['other'], short: 'OTH' };
}

export function carries(medium, vocab) {
  const media = vocab && vocab.media;
  if (!media) return medium ? [medium] : ['other'];
  const m = media[medium];
  return m && Array.isArray(m.carries) ? m.carries.slice() : ['other'];
}

export function mediumDiscipline(medium, vocab) {
  const media = vocab && vocab.media;
  const m = media ? media[medium] : null;
  return (m && m.discipline) || 'other';
}

// ------------------------------------------------------------ port groups (§4.4.3)

const V1_DIRS = { in: 'in', out: 'out', bi: 'io', io: 'io' };

function v1ToGroups(groups) {
  const out = [];
  for (const g of groups || []) {
    if (!g) continue;
    const dir = V1_DIRS[g.direction] || V1_DIRS[g.dir] || 'io';
    const ng = { group: g.name || g.group || 'Ports', dir: dir, medium: g.medium || 'other', _origin: 'declared' };
    if (g.connector) ng.connector = g.connector;
    const labels = Array.isArray(g.labels) ? g.labels : null;
    const count = Number(g.count) || 0;
    if (labels && labels.length) {
      ng.names = labels.map(String);
    } else if (NETWORK_MEDIA.indexOf(ng.medium) >= 0 && count > 1) {
      ng._single = true;
      ng.channels = count;
    } else if (count) {
      ng.count = count;
    }
    if (g.channels && !ng.channels) ng.channels = g.channels;
    out.push(ng);
  }
  return out;
}

export function expandPortGroups(groups, opts) {
  const v1 = !!(opts && opts.v1);
  const list = v1 ? v1ToGroups(groups) : (groups || []);
  const out = [];
  const used = new Set();
  function dedupe(id) {
    if (!used.has(id)) { used.add(id); return id; }
    let code = 98; // 'b'
    let cand = id + '-' + String.fromCharCode(code);
    while (used.has(cand)) {
      code++;
      cand = id + '-' + (code <= 122 ? String.fromCharCode(code) : String(code - 96));
    }
    used.add(cand);
    return cand;
  }
  for (const g of list) {
    if (!g) continue;
    const gname = g.group || g.name || 'Ports';
    const base = slug(gname);
    const origin = g._origin || (v1 ? 'declared' : 'template');
    const labels = Array.isArray(g.labels) ? g.labels : null;
    const emitted = [];
    function emit(id, name, index, nm, pos) {
      const dir = (g.dirs && nm !== undefined && HAS.call(g.dirs, nm)) ? g.dirs[nm] : (g.dir || 'io');
      const p = { id: dedupe(id), name: name, dir: dir, medium: g.medium || 'other' };
      if (g.connector) p.connector = g.connector;
      p.group = gname;
      p.index = index;
      if (g.channels && Number(g.channels) > 1) p.channels = Number(g.channels);
      p.origin = origin;
      let label;
      if (labels && pos <= labels.length) label = labels[pos - 1];
      else if (g.label) label = g.label;
      if (label) p.label = String(label);
      emitted.push(p);
    }
    if (g._single) {
      emit(base, gname, 1, undefined, 1);
    } else if (Array.isArray(g.names) && g.names.length) {
      g.names.forEach(function (nm, i) { emit(base + '-' + slug(nm), gname + ' ' + nm, i + 1, nm, i + 1); });
    } else if ((Number(g.count) || 1) > 1 || g.start) {
      const s = Number(g.start) || 1;
      const count = Number(g.count) || 1;
      for (let k = 0; k < count; k++) {
        const n = s + k;
        emit(base + '-' + n, gname + ' ' + n, n, undefined, k + 1);
      }
    } else {
      emit(base, gname, 1, undefined, 1);
    }
    for (const p of emitted) out.push(p);
  }
  return out;
}

// ------------------------------------------------------------ ops (§4.9)

export function mergePatch(target, patch) {
  if (!isObject(patch)) return deepClone(patch);
  const out = isObject(target) ? Object.assign({}, target) : {};
  for (const k of Object.keys(patch)) {
    const v = patch[k];
    if (v === null) delete out[k];
    else out[k] = mergePatch(out[k], v);
  }
  return out;
}

function opRef(op) {
  if (!op) return '';
  if (op.op === 'root') return op.key;
  return op.coll + '/' + op.id;
}

export function touchedRefs(ops) {
  const s = new Set();
  for (const op of ops || []) s.add(opRef(op));
  return Array.from(s).sort();
}

function checkOp(op) {
  if (!isObject(op)) throw new OpError('bad_op', 'op must be an object');
  if (op.op === 'root') {
    if (ROOTS.indexOf(op.key) < 0) throw new OpError('bad_op', 'unknown root key: ' + op.key);
    return;
  }
  if (['put', 'merge', 'del', 'move'].indexOf(op.op) < 0) throw new OpError('bad_op', 'unknown op: ' + op.op);
  if (COLLECTIONS.indexOf(op.coll) < 0) throw new OpError('bad_op', 'unknown collection: ' + op.coll);
  if (typeof op.id !== 'string' || !op.id) throw new OpError('bad_op', 'op needs an id');
  if (op.op === 'put') {
    if (!isObject(op.value)) throw new OpError('bad_op', 'put needs an object value');
    if (op.value.id !== op.id) throw new OpError('bad_op', 'put value.id must equal id');
  }
  if (op.op === 'merge' && !isObject(op.value)) throw new OpError('bad_op', 'merge needs an object value');
}

function findIndex(list, id) {
  for (let i = 0; i < list.length; i++) if (list[i] && list[i].id === id) return i;
  return -1;
}

// Applies ops onto a shallow working copy; collections are copied once when first touched.
function applyInPlace(work, ops, copied) {
  for (const op of ops || []) {
    checkOp(op);
    if (op.op === 'root') {
      const cur = work[op.key];
      work[op.key] = op.replace ? deepClone(op.value || {}) : mergePatch(isObject(cur) ? cur : {}, op.value || {});
      continue;
    }
    if (!copied[op.coll]) {
      work[op.coll] = Array.isArray(work[op.coll]) ? work[op.coll].slice() : [];
      copied[op.coll] = true;
    }
    const list = work[op.coll];
    const i = findIndex(list, op.id);
    if (op.op === 'put') {
      const v = deepClone(op.value);
      if (i >= 0) list[i] = v; else list.push(v);
    } else if (op.op === 'merge') {
      if (i < 0) throw new OpError('missing_entity', 'cannot merge into missing ' + op.coll + '/' + op.id);
      const merged = mergePatch(list[i], op.value);
      merged.id = op.id;
      list[i] = merged;
    } else if (op.op === 'del') {
      if (i >= 0) list.splice(i, 1);
    } else if (op.op === 'move') {
      if (i < 0) throw new OpError('missing_entity', 'cannot move missing ' + op.coll + '/' + op.id);
      const ent = list.splice(i, 1)[0];
      let j = op.before === null || op.before === undefined ? -1 : findIndex(list, op.before);
      if (j < 0) list.push(ent); else list.splice(j, 0, ent);
    }
  }
  return work;
}

export function invertOps(doc, ops) {
  const work = Object.assign({}, doc || {});
  const copied = {};
  const inv = [];
  for (const op of ops || []) {
    checkOp(op);
    if (op.op === 'root') {
      inv.push({ op: 'root', key: op.key, value: deepClone(isObject(work[op.key]) ? work[op.key] : {}), replace: true });
    } else {
      const list = Array.isArray(work[op.coll]) ? work[op.coll] : [];
      const i = findIndex(list, op.id);
      const step = [];
      if (op.op === 'put' || op.op === 'merge') {
        step.push(i >= 0 ? { op: 'put', coll: op.coll, id: op.id, value: deepClone(list[i]) } : { op: 'del', coll: op.coll, id: op.id });
      } else if (op.op === 'del') {
        if (i >= 0) {
          step.push({ op: 'put', coll: op.coll, id: op.id, value: deepClone(list[i]) });
          if (i < list.length - 1) step.push({ op: 'move', coll: op.coll, id: op.id, before: list[i + 1].id });
        }
      } else if (op.op === 'move') {
        if (i >= 0) step.push({ op: 'move', coll: op.coll, id: op.id, before: i < list.length - 1 ? list[i + 1].id : null });
      }
      // undo runs in reverse order; keep the step's own order intact
      for (let s = step.length - 1; s >= 0; s--) inv.push(step[s]);
    }
    applyInPlace(work, [op], copied);
  }
  inv.reverse();
  return inv;
}

export function applyOps(doc, ops) {
  const inverse = invertOps(doc, ops);
  const work = applyInPlace(Object.assign({}, doc || {}), ops, {});
  return { doc: work, inverse: inverse, touched: touchedRefs(ops) };
}

export function diffDocs(a, b) {
  const ops = [];
  a = a || {};
  b = b || {};
  for (const c of COLLECTIONS) {
    const la = Array.isArray(a[c]) ? a[c] : [];
    const lb = Array.isArray(b[c]) ? b[c] : [];
    const ma = {};
    const mb = {};
    for (const e of la) if (e) ma[e.id] = e;
    for (const e of lb) if (e) mb[e.id] = e;
    for (const e of la) if (e && !HAS.call(mb, e.id)) ops.push({ op: 'del', coll: c, id: e.id });
    for (const e of lb) {
      if (!e) continue;
      if (!HAS.call(ma, e.id) || canonicalJson(ma[e.id]) !== canonicalJson(e)) ops.push({ op: 'put', coll: c, id: e.id, value: deepClone(e) });
    }
  }
  for (const r of ROOTS) {
    const va = isObject(a[r]) ? a[r] : {};
    const vb = isObject(b[r]) ? b[r] : {};
    if (canonicalJson(va) !== canonicalJson(vb)) ops.push({ op: 'root', key: r, value: deepClone(vb), replace: true });
  }
  return ops;
}

// ------------------------------------------------------------ connection rules (§4.4.4)

function findDevice(doc, id) {
  const list = (doc && doc.devices) || [];
  for (const d of list) if (d.id === id) return d;
  return null;
}

function findPort(device, portId) {
  if (!device || !portId) return null;
  for (const p of devicePorts(device)) if (p.id === portId) return p;
  return null;
}

function mediumLabelShort(medium, vocab) {
  const m = vocab && vocab.media ? vocab.media[medium] : null;
  return (m && m.short) || String(medium || '').toUpperCase();
}

export function canConnect(doc, from, to, vocab) {
  from = from || {};
  to = to || {};
  const fd = findDevice(doc, from.device);
  const td = findDevice(doc, to.device);
  if (!fd || !td) return { ok: false, level: 'error', code: 'dangling_ref', reason: 'Unknown device' };
  if (from.device === to.device && (from.port || null) === (to.port || null)) {
    return { ok: false, level: 'error', code: 'self_loop', reason: 'A port cannot connect to itself' };
  }
  const fp = findPort(fd, from.port);
  const tp = findPort(td, to.port);
  if (from.port && !fp) return { ok: false, level: 'error', code: 'dangling_port', reason: 'Unknown port ' + from.port + ' on ' + (fd.name || fd.id) };
  if (to.port && !tp) return { ok: false, level: 'error', code: 'dangling_port', reason: 'Unknown port ' + to.port + ' on ' + (td.name || td.id) };
  if (fp && fp.dir === 'in') return { ok: false, level: 'error', code: 'bad_direction', reason: portLabel(fp) + ' is an input; signal cannot start there' };
  if (tp && tp.dir === 'out') return { ok: false, level: 'error', code: 'bad_direction', reason: portLabel(tp) + ' is an output; signal cannot end there' };
  if (fp && tp && fp.medium && tp.medium && fp.medium !== tp.medium) {
    const ca = carries(fp.medium, vocab);
    const cb = carries(tp.medium, vocab);
    const shared = ca.some(function (x) { return cb.indexOf(x) >= 0; });
    const txt = mediumLabelShort(fp.medium, vocab) + ' \u2192 ' + mediumLabelShort(tp.medium, vocab);
    if (shared) return { ok: true, level: 'warn', code: 'medium_mismatch', reason: txt + ': needs a converter?' };
    return { ok: true, level: 'warn', code: 'medium_incompatible', reason: txt + ': these do not carry the same signal' };
  }
  if (tp && tp.dir === 'in') {
    const ch = Number(tp.channels) || 1;
    let n = 0;
    for (const c of (doc.cables || [])) if (c.to && c.to.device === to.device && c.to.port === to.port) n++;
    if (n >= ch) return { ok: true, level: 'warn', code: 'port_overuse', reason: portLabel(tp) + ' on ' + (td.name || td.id) + ' is already patched' };
  }
  return { ok: true, level: 'ok', code: 'ok', reason: '' };
}

// ------------------------------------------------------------ editing helpers -> ops

function endpoint(e) {
  const out = { device: e.device };
  if (e.port) out.port = e.port;
  return out;
}

export function connectOps(doc, from, to, opts, vocab) {
  opts = opts || {};
  const fd = findDevice(doc, from.device);
  const td = findDevice(doc, to.device);
  const fp = findPort(fd, from.port);
  const tp = findPort(td, to.port);
  const id = opts.id || newId('c', (doc && doc.cables) || []);
  const cable = { id: id, from: endpoint(from), to: endpoint(to), medium: opts.medium || (fp && fp.medium) || (tp && tp.medium) || 'analog' };
  if (opts.tag) cable.tag = opts.tag;
  if (opts.type) cable.type = opts.type;
  if (opts.length_m !== undefined && opts.length_m !== null && opts.length_m !== '') cable.length_m = Number(opts.length_m);
  if (opts.status) cable.status = opts.status;
  if (fp && tp && fp.dir === 'io' && tp.dir === 'io' && opts.bidirectional !== false) cable.bidirectional = true;
  return [{ op: 'put', coll: 'cables', id: id, value: cable }];
}

export function disconnectOps(doc, cableId) {
  return [{ op: 'del', coll: 'cables', id: cableId }];
}

export function repatchOps(doc, cableId, end, target) {
  const value = {};
  value[end === 'from' ? 'from' : 'to'] = { device: target.device, port: target.port || null };
  return [{ op: 'merge', coll: 'cables', id: cableId, value: value }];
}

export function deleteDeviceOps(doc, deviceId) {
  const ops = [{ op: 'del', coll: 'devices', id: deviceId }];
  for (const c of (doc.cables || [])) {
    if ((c.from && c.from.device === deviceId) || (c.to && c.to.device === deviceId)) ops.push({ op: 'del', coll: 'cables', id: c.id });
  }
  for (const fp of (doc.floorplans || [])) {
    const ms = fp.markers || [];
    if (ms.some(function (m) { return m.device === deviceId; })) {
      ops.push({ op: 'merge', coll: 'floorplans', id: fp.id, value: { markers: deepClone(ms.filter(function (m) { return m.device !== deviceId; })) } });
    }
  }
  for (const r of (doc.rooms || [])) {
    const ex = (r.flow && r.flow.extra_cards) || [];
    if (ex.some(function (x) { return x.device === deviceId; })) {
      ops.push({ op: 'merge', coll: 'rooms', id: r.id, value: { flow: { extra_cards: deepClone(ex.filter(function (x) { return x.device !== deviceId; })) } } });
    }
  }
  return ops;
}

export function duplicateDeviceOps(doc, deviceId, opts) {
  opts = opts || {};
  const d = findDevice(doc, deviceId);
  if (!d) return { ops: [], id: null };
  const copy = deepClone(d);
  const name = opts.name || (d.name + ' copy');
  const id = opts.id || newId(null, doc.devices || [], name);
  copy.id = id;
  copy.name = name;
  delete copy.rack;
  delete copy.interfaces;
  delete copy.auto;
  delete copy.source;
  if (copy.inventory) {
    delete copy.inventory.serial;
    delete copy.inventory.asset_tag;
    if (!Object.keys(copy.inventory).length) delete copy.inventory;
  }
  if (copy.flow) delete copy.flow.seq;
  const px = d.patch && typeof d.patch.x === 'number' ? d.patch.x : 0;
  const py = d.patch && typeof d.patch.y === 'number' ? d.patch.y : 0;
  if (d.patch || opts.offset !== false) copy.patch = Object.assign({}, d.patch || {}, { x: px + 24, y: py + 24 });
  return { ops: [{ op: 'put', coll: 'devices', id: id, value: copy }], id: id };
}

export function setPortsOps(doc, deviceId, ports) {
  return [{ op: 'merge', coll: 'devices', id: deviceId, value: { ports: deepClone(ports) } }];
}

export function renameOps(doc, ref, value) {
  const coll = ref.coll || 'devices';
  const text = value == null ? '' : String(value).trim();
  if (coll === 'devices' && ref.port) {
    const d = findDevice(doc, ref.id);
    if (!d) return [];
    let changed = false;
    const ports = devicePorts(d).map(function (p) {
      if (p.id !== ref.port) return p;
      const np = Object.assign({}, p);
      if (text && text !== p.name) np.label = text; else delete np.label;
      changed = (np.label || '') !== (p.label || '');
      return np;
    });
    return changed ? setPortsOps(doc, d.id, ports) : [];
  }
  if (!text) return [];
  const list = doc[coll] || [];
  const i = findIndex(list, ref.id);
  if (i < 0 || list[i].name === text) return [];
  return [{ op: 'merge', coll: coll, id: ref.id, value: { name: text } }];
}

export function addDeviceFromTemplateOps(doc, template, opts) {
  opts = opts || {};
  const t = template || {};
  const name = opts.name || t.name || t.model || t.id || 'Device';
  const id = opts.id || newId(null, (doc && doc.devices) || [], name);
  const dev = { id: id, name: name, kind: t.kind || 'other' };
  const vocab = opts.vocab;
  if (t.discipline && vocab && vocab.kinds && vocab.kinds[dev.kind] && vocab.kinds[dev.kind].discipline !== t.discipline) dev.discipline = t.discipline;
  if (opts.room !== undefined) dev.room = opts.room;
  if (t.manufacturer) dev.manufacturer = t.manufacturer;
  if (t.model) dev.model = t.model;
  if (t.brand) dev.brand = t.brand;
  if (t.id) dev.template = t.id;
  else if (parseInt(t.ru, 10) >= 1) dev.rack = { height: parseInt(t.ru, 10) };  // no template to look the height up from
  if (opts.count) dev.count = opts.count;
  if (t.dante) dev.dante = true;
  if (t.dmx_footprint) dev.dmx = { footprint: t.dmx_footprint };
  if (opts.status) dev.status = opts.status;
  if (typeof opts.x === 'number' && typeof opts.y === 'number') dev.patch = { x: Math.round(opts.x), y: Math.round(opts.y) };
  dev.ports = expandPortGroups(t.ports || []);
  return { ops: [{ op: 'put', coll: 'devices', id: id, value: dev }], id: id };
}

// ------------------------------------------------------------ filtering

export function stateIncludes(status, state) {
  const s = status || 'installed';
  const st = state || 'all';
  if (st === 'everything') return true;
  if (st === 'as_built') return s === 'installed';
  if (st === 'planned') return s === 'installed' || s === 'planned';
  return s !== 'retired';
}

function deviceText(d) {
  const inv = d.inventory || {};
  return [d.id, d.name, d.code, d.manufacturer, d.model, d.sub, inv.serial, inv.asset_tag, d.note].concat(d.aliases || []).filter(Boolean).join(' ').toLowerCase();
}

export function externalDevices(doc, room) {
  if (room === '*' || room === undefined || room === null) return [];
  const inRoom = {};
  for (const d of (doc.devices || [])) if ((d.room || '') === room) inRoom[d.id] = true;
  const ext = {};
  for (const c of (doc.cables || [])) {
    const a = c.from && c.from.device;
    const b = c.to && c.to.device;
    if (inRoom[a] && b && !inRoom[b]) ext[b] = true;
    if (inRoom[b] && a && !inRoom[a]) ext[a] = true;
  }
  return (doc.devices || []).filter(function (d) { return ext[d.id]; });
}

export function filterDevices(doc, filter, vocab) {
  filter = filter || {};
  const room = filter.room;
  const discs = filter.disciplines || [];
  const statuses = filter.statuses || [];
  const q = String(filter.query || '').trim().toLowerCase();
  const list = (doc && doc.devices) || [];
  const ext = filter.includeExternal ? externalDevices(doc, room) : [];
  const extIds = {};
  for (const d of ext) extIds[d.id] = true;
  return list.filter(function (d) {
    if (room !== undefined && room !== null && room !== '*' && (d.room || '') !== room && !extIds[d.id]) return false;
    if (statuses.length) {
      if (statuses.indexOf(d.status || 'installed') < 0) return false;
    } else if (!stateIncludes(d.status, filter.state)) return false;
    if (discs.length && discs.indexOf(disciplineOf(d, vocab)) < 0) {
      // mixed devices: a port carrying one of the chosen disciplines also qualifies
      const portMatch = devicePorts(d).some(function (p) { return discs.indexOf(mediumDiscipline(p.medium, vocab)) >= 0; });
      if (!portMatch) return false;
    }
    if (filter.system && d.system !== filter.system) return false;
    if (q && deviceText(d).indexOf(q) < 0) return false;
    return true;
  });
}

// ------------------------------------------------------------ local search (§5.11, FR-SRCH-04)

const KIND_ORDER = ['device', 'port', 'cable', 'interface', 'room', 'rack', 'floorplan', 'attachment'];

function tokens(s) {
  return String(s || '').toLowerCase().split(/[^a-z0-9.:]+/).filter(Boolean);
}

function editDistanceLE1(a, b) {
  if (a === b) return true;
  const la = a.length;
  const lb = b.length;
  if (Math.abs(la - lb) > 1) return false;
  let i = 0;
  let j = 0;
  let edits = 0;
  while (i < la && j < lb) {
    if (a.charAt(i) === b.charAt(j)) { i++; j++; continue; }
    if (++edits > 1) return false;
    if (la > lb) i++;
    else if (lb > la) j++;
    else { i++; j++; }
  }
  return edits + (la - i) + (lb - j) <= 1;
}

export function scoreText(text, q) {
  const t = String(text || '').trim().toLowerCase();
  const qq = String(q || '').trim().toLowerCase();
  if (!t || !qq) return 0;
  if (t === qq) return 100;
  if (t.indexOf(qq) === 0) return 80;
  const tt = tokens(t);
  const qt = tokens(qq);
  if (qt.length && qt.every(function (x) { return tt.indexOf(x) >= 0; })) return 60;
  if (t.indexOf(qq) >= 0) return 40;
  if (qt.length && qt.every(function (x) {
    if (tt.indexOf(x) >= 0) return true;
    return x.length >= 4 && tt.some(function (y) { return y.length >= 4 && editDistanceLE1(x, y); });
  })) return 25;
  return 0;
}

function bestField(fields, q) {
  let best = 0;
  let match = '';
  for (const f of fields) {
    const s = scoreText(f[1], q);
    if (s > best) { best = s; match = f[0]; }
  }
  return { score: best, match: match };
}

export function searchLocal(doc, q, limit) {
  const query = String(q || '').trim();
  if (!query || !doc) return [];
  const lim = limit || 20;
  const idx = indexDoc(doc);
  const roomName = function (id) { const r = idx.byId.rooms[id]; return r ? r.name : (id ? id : 'Shared inventory'); };
  const hits = [];
  function add(kind, id, fields, extra) {
    const b = bestField(fields, query);
    if (!b.score) return;
    hits.push(Object.assign({ kind: kind, id: id, device: null, port: null, title: '', subtitle: '', room: null, score: b.score, match: b.match }, extra));
  }
  for (const d of (doc.devices || [])) {
    const inv = d.inventory || {};
    const fields = [['name', d.name], ['code', d.code], ['manufacturer', d.manufacturer], ['model', d.model], ['serial', inv.serial], ['asset_tag', inv.asset_tag], ['note', d.note], ['id', d.id]];
    for (const a of (d.aliases || [])) fields.push(['alias', a]);
    const sub = [((d.manufacturer || '') + ' ' + (d.model || '')).trim() || d.sub || '', roomName(d.room || '')].filter(Boolean).join(' \u00b7 ');
    add('device', d.id, fields, { device: d.id, title: d.name || d.id, subtitle: sub, room: d.room || '' });
    for (const p of devicePorts(d)) {
      add('port', d.id + ':' + p.id, [['name', p.name], ['label', p.label], ['note', p.note]], { device: d.id, port: p.id, title: (d.name || d.id) + ' \u00b7 ' + portLabel(p), subtitle: p.label && p.name ? p.name : (p.group || ''), room: d.room || '' });
    }
    for (const it of (d.interfaces || [])) {
      add('interface', d.id + '/' + it.id, [['ip', it.ip], ['mac', it.mac], ['hostname', it.hostname]], { device: d.id, title: it.ip || it.hostname || it.mac || it.id, subtitle: (d.name || d.id) + ' \u00b7 ' + (it.role || it.id), room: d.room || '' });
    }
  }
  for (const c of (doc.cables || [])) {
    const fd = idx.byId.devices[c.from && c.from.device];
    const td = idx.byId.devices[c.to && c.to.device];
    add('cable', c.id, [['tag', c.tag], ['label', c.label], ['signal', c.signal], ['note', c.note], ['id', c.id]], { title: c.tag || c.id, subtitle: (fd ? fd.name : (c.from && c.from.device)) + ' \u2192 ' + (td ? td.name : (c.to && c.to.device)), room: fd ? (fd.room || '') : null });
  }
  for (const r of (doc.rooms || [])) add('room', r.id, [['name', r.name], ['code', r.code], ['id', r.id]], { title: r.name || r.id, subtitle: r.code || '', room: r.id });
  for (const r of (doc.racks || [])) add('rack', r.id, [['name', r.name], ['id', r.id]], { title: r.name || r.id, subtitle: (r.units || '') + 'U \u00b7 ' + roomName(r.room || ''), room: r.room || '' });
  for (const f of (doc.floorplans || [])) add('floorplan', f.id, [['name', f.name], ['id', f.id]], { title: f.name || f.id, subtitle: roomName(f.room || ''), room: f.room || '' });
  for (const a of (doc.attachments || [])) add('attachment', a.id, [['name', a.name]], { device: a.device || null, title: a.name, subtitle: a.kind || '', room: null });
  hits.sort(function (a, b) {
    if (b.score !== a.score) return b.score - a.score;
    const ka = KIND_ORDER.indexOf(a.kind);
    const kb = KIND_ORDER.indexOf(b.kind);
    if (ka !== kb) return ka - kb;
    const ta = String(a.title).toLowerCase();
    const tb = String(b.title).toLowerCase();
    return ta < tb ? -1 : ta > tb ? 1 : 0;
  });
  return hits.slice(0, lim);
}

// ------------------------------------------------------------ local validation (subset of §4.7)

function problem(level, code, ref, path, message) {
  return { level: level, code: code, ref: ref, path: path, message: message };
}

export function validateLocal(doc, vocab) {
  const out = [];
  if (!doc) return out;
  for (const c of COLLECTIONS) {
    const seen = {};
    (doc[c] || []).forEach(function (e, i) {
      if (!e || typeof e.id !== 'string' || !ID_RE.test(e.id)) { out.push(problem('error', 'bad_id', c + '/' + (e && e.id), c + '/' + i + '/id', 'Bad id in ' + c)); return; }
      if (seen[e.id]) out.push(problem('error', 'duplicate_id', c + '/' + e.id, c + '/' + e.id, 'Duplicate id ' + e.id + ' in ' + c));
      seen[e.id] = true;
    });
  }
  const idx = indexDoc(doc);
  for (const d of (doc.devices || [])) {
    const seenP = {};
    for (const p of devicePorts(d)) {
      if (seenP[p.id]) out.push(problem('error', 'duplicate_port', 'devices/' + d.id, 'devices/' + d.id + '/ports/' + p.id, 'Duplicate port ' + p.id + ' on ' + d.name));
      seenP[p.id] = true;
    }
  }
  const inCount = {};
  for (const c of (doc.cables || [])) {
    const ref = 'cables/' + c.id;
    let fp = null;
    let tp = null;
    let ok = true;
    for (const end of ['from', 'to']) {
      const e = c[end] || {};
      if (!e.device || !idx.byId.devices[e.device]) {
        out.push(problem('error', 'dangling_ref', ref, ref + '/' + end + '/device', 'Cable ' + c.id + ' points at missing device ' + (e.device || '(none)')));
        ok = false;
        continue;
      }
      if (e.port) {
        const p = idx.ports[e.device][e.port];
        if (!p) out.push(problem('warning', 'dangling_port', ref, ref + '/' + end + '/port', 'Port ' + e.port + ' is not on ' + e.device));
        if (end === 'from') fp = p || null; else tp = p || null;
      }
    }
    if (!ok) continue;
    if ((fp && fp.dir === 'in') || (tp && tp.dir === 'out')) out.push(problem('warning', 'bad_direction', ref, ref, 'Cable ' + c.id + ' runs against port direction'));
    if (fp && tp && fp.medium && tp.medium && fp.medium !== tp.medium) {
      const ca = carries(fp.medium, vocab);
      const cb = carries(tp.medium, vocab);
      const shared = ca.some(function (x) { return cb.indexOf(x) >= 0; });
      out.push(problem('warning', shared ? 'medium_mismatch' : 'medium_incompatible', ref, ref, mediumLabelShort(fp.medium, vocab) + ' \u2192 ' + mediumLabelShort(tp.medium, vocab) + (shared ? ': needs a converter?' : ': incompatible media')));
    }
    if (tp && tp.dir === 'in') {
      const k = c.to.device + ':' + c.to.port;
      inCount[k] = (inCount[k] || 0) + 1;
      if (inCount[k] === (Number(tp.channels) || 1) + 1) out.push(problem('warning', 'port_overuse', 'devices/' + c.to.device, 'devices/' + c.to.device + '/ports/' + c.to.port, portLabel(tp) + ' has more cables than channels'));
    }
  }
  if (vocab && vocab.kinds) {
    for (const d of (doc.devices || [])) if (d.kind && !vocab.kinds[d.kind]) out.push(problem('warning', 'unknown_kind', 'devices/' + d.id, 'devices/' + d.id + '/kind', 'Unknown kind ' + d.kind));
  }
  return out;
}

// FR-NET-04: colon, dash, dotted Cisco or bare 12 hex -> "aa:bb:cc:dd:ee:ff"; null if unparseable
// (same rules as fathom.network.normalize_mac)
export function normalizeMac(text) {
  const t = String(text == null ? '' : text).trim().toLowerCase();
  if (!t) return null;
  let hex;
  if (/^[0-9a-f]{1,2}([:-])[0-9a-f]{1,2}(\1[0-9a-f]{1,2}){4}$/.test(t)) {
    hex = t.split(/[:-]/).map(function (p) { return p.length === 1 ? '0' + p : p; }).join('');
  } else if (/^[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}$/.test(t)) {
    hex = t.replace(/\./g, '');
  } else {
    hex = t;
  }
  if (!/^[0-9a-f]{12}$/.test(hex)) return null;
  return hex.match(/../g).join(':');
}

export function formatLength(m, units) {
  if (m === undefined || m === null || m === '' || isNaN(Number(m))) return '';
  const v = Number(m);
  if (units === 'imperial') {
    const ft = Math.round(v * 3.28084 * 10) / 10;
    return String(ft) + ' ft';
  }
  return String(Math.round(v * 100) / 100) + ' m';
}

export function parseLength(text, units) {
  const s = String(text == null ? '' : text).trim().toLowerCase();
  if (!s) return null;
  const n = parseFloat(s.replace(',', '.'));
  if (isNaN(n)) return null;
  let unit = units === 'imperial' ? 'ft' : 'm';
  if (/ft|'/.test(s)) unit = 'ft';
  else if (/cm/.test(s)) unit = 'cm';
  else if (/in|"/.test(s)) unit = 'in';
  else if (/m/.test(s)) unit = 'm';
  const f = { m: 1, ft: 0.3048, cm: 0.01, in: 0.0254 }[unit];
  return Math.round(n * f * 1000) / 1000;
}

// ------------------------------------------------------------ viewport math

export const viewport = {
  clampK: function (k, min, max) {
    const lo = min === undefined ? 0.15 : min;
    const hi = max === undefined ? 3 : max;
    return Math.max(lo, Math.min(hi, k));
  },
  fit: function (bounds, size, margin) {
    const m = margin === undefined ? 24 : margin;
    const bw = Math.max(1, bounds.w);
    const bh = Math.max(1, bounds.h);
    const k = viewport.clampK(Math.min((size.w - 2 * m) / bw, (size.h - 2 * m) / bh), 0.15, 3);
    return { x: (size.w - bw * k) / 2 - bounds.x * k, y: (size.h - bh * k) / 2 - bounds.y * k, k: k };
  },
  zoomAt: function (view, pt, factor, min, max) {
    const k2 = viewport.clampK(view.k * factor, min, max);
    const wx = (pt.x - view.x) / view.k;
    const wy = (pt.y - view.y) / view.k;
    return { x: pt.x - wx * k2, y: pt.y - wy * k2, k: k2 };
  },
  screenToWorld: function (view, pt) {
    return { x: (pt.x - view.x) / view.k, y: (pt.y - view.y) / view.k };
  },
  worldToScreen: function (view, pt) {
    return { x: pt.x * view.k + view.x, y: pt.y * view.k + view.y };
  },
};

// ------------------------------------------------------------ store

const UNDO_CAP = 200;

function makeEvent(type, detail) {
  const e = new Event(type);
  try { e.detail = detail; } catch (err) { Object.defineProperty(e, 'detail', { value: detail }); }
  return e;
}

class Store extends EventTarget {
  constructor(opts) {
    super();
    opts = opts || {};
    this._doc = opts.doc || { fathom: 2, revision: 0, meta: {}, settings: {} };
    this._vocab = opts.vocab || null;
    this._overlay = opts.overlay || null;
    this._room = opts.room !== undefined ? opts.room : ((this._doc.settings && this._doc.settings.default_room) || '');
    this._readOnly = !!opts.readOnly;
    this._revision = opts.revision !== undefined ? opts.revision : (this._doc.revision || 0);
    this._selection = null;
    this._highlight = null;
    this._filter = { disciplines: [], statuses: [], query: '', state: 'all', showUnconnected: true, system: '' };
    this._undo = [];
    this._redo = [];
    this._index = null;
  }
  get doc() { return this._doc; }
  get vocab() { return this._vocab; }
  get overlay() { return this._overlay; }
  get room() { return this._room; }
  get selection() { return this._selection; }
  get highlighted() { return this._highlight; }
  get filter() { return this._filter; }
  get readOnly() { return this._readOnly; }
  get revision() { return this._revision; }
  get index() {
    if (!this._index) this._index = indexDoc(this._doc);
    return this._index;
  }
  get canUndo() { return !this._readOnly && this._undo.length > 0; }
  get canRedo() { return !this._readOnly && this._redo.length > 0; }
  get undoLabel() { return this._undo.length ? this._undo[this._undo.length - 1].label : ''; }
  get redoLabel() { return this._redo.length ? this._redo[this._redo.length - 1].label : ''; }

  emit(type, detail) {
    this.dispatchEvent(makeEvent(type, detail));
  }
  _setDoc(doc) {
    this._doc = doc;
    this._index = null;
  }
  commit(ops, label) {
    if (this._readOnly) throw new ReadOnlyError();
    if (!ops || !ops.length) return this._doc;
    const r = applyOps(this._doc, ops);
    this._setDoc(r.doc);
    this._undo.push({ label: label || 'Edit', ops: ops, inverse: r.inverse });
    if (this._undo.length > UNDO_CAP) this._undo.shift();
    this._redo = [];
    this.emit('doc', { ops: ops, inverse: r.inverse, touched: r.touched, source: 'local', label: label || 'Edit' });
    return this._doc;
  }
  applyRemote(ops, source) {
    if (!ops || !ops.length) return this._doc;
    const r = applyOps(this._doc, ops);
    this._setDoc(r.doc);
    this.emit('doc', { ops: ops, inverse: r.inverse, touched: r.touched, source: source || 'remote' });
    return this._doc;
  }
  replaceDoc(doc, revision, source) {
    this._setDoc(doc);
    if (revision !== undefined && revision !== null) this._revision = revision;
    else if (doc && doc.revision !== undefined) this._revision = doc.revision;
    this._undo = [];
    this._redo = [];
    this.emit('doc', { ops: [], inverse: [], touched: [], source: source || 'load' });
    return this._doc;
  }
  _step(from, to, source) {
    if (this._readOnly) throw new ReadOnlyError();
    const entry = from.pop();
    if (!entry) return null;
    const ops = source === 'undo' ? entry.inverse : entry.ops;
    let r;
    try {
      r = applyOps(this._doc, ops);
    } catch (err) {
      this.emit('error', { error: err, source: source });
      return null;
    }
    this._setDoc(r.doc);
    if (source === 'undo') to.push({ label: entry.label, ops: entry.ops, inverse: r.inverse });
    else to.push({ label: entry.label, ops: entry.ops, inverse: r.inverse });
    this.emit('doc', { ops: ops, inverse: r.inverse, touched: r.touched, source: source, label: entry.label });
    return this._doc;
  }
  undo() { return this._step(this._undo, this._redo, 'undo'); }
  redo() { return this._step(this._redo, this._undo, 'redo'); }
  select(sel) {
    this._selection = sel || null;
    this.emit('selection', this._selection);
  }
  highlight(h) {
    this._highlight = h || null;
    this.emit('highlight', this._highlight);
  }
  setFilter(partial) {
    this._filter = Object.assign({}, this._filter, partial || {});
    this.emit('filter', this._filter);
  }
  setRoom(id) {
    this._room = id;
    this.emit('room', id);
  }
  setOverlay(o) {
    this._overlay = o || null;
    this.emit('overlay', this._overlay);
  }
  setReadOnly(b) {
    this._readOnly = !!b;
    this.emit('mode', { readOnly: this._readOnly });
  }
  setRevision(n) {
    this._revision = n;
    if (this._doc) this._doc = Object.assign({}, this._doc, { revision: n });
    this.emit('revision', n);
  }
  setVocab(v) {
    this._vocab = v || null;
  }
}

export function createStore(opts) {
  return new Store(opts || {});
}
