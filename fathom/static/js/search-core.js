// Pure search core (docs/ui-audit.md B.2 SEARCH): categories, grouping,
// offline augmentation (networks, status), role filtering, hit -> route
// targets, recents and keyboard index math. No DOM, window, storage, fetch
// or timers, so it imports in Node.

import { searchLocal, scoreText } from './model-core.js';

export const CATEGORIES = [
  { key: 'all', label: 'All', glyph: '\u2315', kinds: null },
  { key: 'devices', label: 'Devices', glyph: '\u25EB', kinds: ['device'] },
  { key: 'inventory', label: 'Inventory', glyph: '\u2116', kinds: ['device'] },
  { key: 'rooms', label: 'Rooms', glyph: '\u25A3', kinds: ['room'] },
  { key: 'racks', label: 'Racks', glyph: '\u2261', kinds: ['rack'] },
  { key: 'ports', label: 'Ports', glyph: '\u25CB', kinds: ['port'] },
  { key: 'cables', label: 'Cables', glyph: '\u223F', kinds: ['cable'] },
  { key: 'networks', label: 'Networks', glyph: '\u2194\uFE0E', kinds: ['network', 'interface'] },
  { key: 'plans', label: 'Plans', glyph: '\u25A6', kinds: ['floorplan'] },
  { key: 'procedures', label: 'Procedures', glyph: '\u2611', kinds: ['page'] },
  { key: 'files', label: 'Files', glyph: '\u2398', kinds: ['attachment'] },
];

// fathom/search.py KIND_ORDER (ties after score).
export const KIND_ORDER = ['device', 'port', 'cable', 'interface', 'network', 'room', 'rack', 'floorplan', 'attachment', 'page'];

const CAT_OF_KIND = {
  device: 'devices', room: 'rooms', rack: 'racks', port: 'ports', cable: 'cables', interface: 'networks',
  network: 'networks', floorplan: 'plans', page: 'procedures', attachment: 'files',
};

const RECENT_TYPES = ['device', 'room', 'rack', 'page'];
const ALL_CAP = 6;
const ONE_CAP = 50;
const SHORT_CODE_RE = /^[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}$/;

// ------------------------------------------------------------ short codes (FR-INV-13)

// Device short codes are assigned server-side (8 chars of 23456789ABCDEFGHJKLMNPQRSTUVWXYZ)
// and shown as XXXX-XXXX; the client only formats, parses and matches them.
export function formatShortCode(code) {
  const s = str(code).replace(/[^A-Za-z0-9]/g, '').toUpperCase();
  return s.length === 8 ? s.slice(0, 4) + '-' + s.slice(4) : s;
}

// The 8-char upper-case code of `text` (with or without the dash), or ''.
export function parseShortCode(text) {
  const s = str(text).trim();
  return SHORT_CODE_RE.test(s) ? s.replace('-', '').toUpperCase() : '';
}

export function isShortCodeQuery(text) {
  return SHORT_CODE_RE.test(str(text).trim());
}

function roomLabel(doc, rid) {
  const rm = byId(doc && doc.rooms, rid);
  return rm ? (str(rm.name) || str(rid)) : str(rid);
}

// The device hit for a code match (§5.11 shape, score 100): title = device name,
// subtitle "Code XXXX-XXXX · <room>". `res` is a GET /api/v2/codes/<code> body
// ({device, name, room, kind}) or a device record from the doc.
export function codeHit(doc, res, code) {
  if (!res) return null;
  const id = str(res.device || res.id);
  if (!id) return null;
  const dev = byId(doc && doc.devices, id);
  const room = str(res.room || (dev && dev.room));
  return {
    kind: 'device', id: id, device: id, port: null, title: str(res.name || (dev && dev.name)) || id,
    subtitle: join(['Code ' + formatShortCode(code || res.short_code || (dev && dev.short_code)), room ? roomLabel(doc, room) : '']),
    room: room, score: 100, match: 'code', status: dev ? str(dev.status) : str(res.status),
  };
}

function localCodeHits(doc, q) {
  const code = parseShortCode(q);
  if (!code) return [];
  const out = [];
  (Array.isArray(doc.devices) ? doc.devices : []).forEach(function (d) {
    if (d && d.id && parseShortCode(d.short_code) === code) out.push(codeHit(doc, d, code));
  });
  return out;
}

function own(o, k) {
  return !!o && Object.prototype.hasOwnProperty.call(o, k);
}

function str(v) {
  return v === undefined || v === null ? '' : String(v);
}

function category(key) {
  for (let i = 0; i < CATEGORIES.length; i++) if (CATEGORIES[i].key === key) return CATEGORIES[i];
  return null;
}

function byId(list, id) {
  const arr = Array.isArray(list) ? list : [];
  for (let i = 0; i < arr.length; i++) if (arr[i] && arr[i].id === id) return arr[i];
  return null;
}

function join(parts) {
  return parts.filter(function (p) { return p !== undefined && p !== null && p !== ''; }).join(' \u00b7 ');
}

function hitKey(h) {
  return str(h && h.kind) + ':' + str(h && h.id);
}

// Copy of the category's kinds; null for `all` (no filter) and unknown keys.
export function kindsFor(key) {
  const c = category(key);
  return c && c.kinds ? c.kinds.slice() : null;
}

// Category key of a hit. groupHits stamps `category` on the hits it returns,
// which wins, so a device listed under Inventory also targets the inventory
// drawer.
export function categorize(hit) {
  if (!hit) return 'all';
  if (hit.category && hit.category !== 'all' && category(hit.category)) return hit.category;
  if (hit.kind === 'device' && (hit.match === 'serial' || hit.match === 'asset_tag')) return 'inventory';
  return own(CAT_OF_KIND, hit.kind) ? CAT_OF_KIND[hit.kind] : 'all';
}

// Ordered groups [{key, label, glyph, hits}] with empty groups dropped. In
// `all`, one group per category in CATEGORIES order, at most 6 hits each; in a
// single category, one group of that category's kinds, at most 50 hits.
// Returned hits are shallow copies carrying `category` = their group key.
export function groupHits(hits, cat) {
  const list = Array.isArray(hits) ? hits : [];
  const tag = function (h, key) { return Object.assign({}, h, { category: key }); };
  const single = cat && cat !== 'all' ? category(cat) : null;
  if (single) {
    const kinds = single.kinds;
    const out = list.filter(function (h) { return h && kinds.indexOf(h.kind) >= 0; }).slice(0, ONE_CAP)
      .map(function (h) { return tag(h, single.key); });
    return out.length ? [{ key: single.key, label: single.label, glyph: single.glyph, hits: out }] : [];
  }
  const buckets = {};
  list.forEach(function (h) {
    if (!h) return;
    const key = categorize(Object.assign({}, h, { category: null }));
    if (key === 'all') return;
    if (!buckets[key]) buckets[key] = [];
    if (buckets[key].length < ALL_CAP) buckets[key].push(tag(h, key));
  });
  const groups = [];
  CATEGORIES.forEach(function (c) {
    if (c.key !== 'all' && buckets[c.key] && buckets[c.key].length) groups.push({ key: c.key, label: c.label, glyph: c.glyph, hits: buckets[c.key] });
  });
  return groups;
}

function compareHits(a, b) {
  if (b.score !== a.score) return b.score - a.score;
  const ka = KIND_ORDER.indexOf(a.kind);
  const kb = KIND_ORDER.indexOf(b.kind);
  if (ka !== kb) return (ka < 0 ? 99 : ka) - (kb < 0 ? 99 : kb);
  const ta = str(a.title).toLowerCase();
  const tb = str(b.title).toLowerCase();
  return ta < tb ? -1 : ta > tb ? 1 : 0;
}

function networkHits(doc, q) {
  const out = [];
  (Array.isArray(doc.networks) ? doc.networks : []).forEach(function (n) {
    if (!n || !n.id) return;
    const vlan = n.vlan === undefined || n.vlan === null || typeof n.vlan === 'boolean' ? '' : String(n.vlan).trim();
    const fields = [['name', n.name], ['id', n.id], ['vlan', vlan], ['subnet', n.subnet], ['protocol', n.protocol]];
    let best = 0;
    let match = '';
    fields.forEach(function (f) {
      const s = scoreText(f[1], q);
      if (s > best) { best = s; match = f[0]; }
    });
    if (!best) return;
    out.push({
      kind: 'network', id: String(n.id), device: null, port: null, title: str(n.name) || String(n.id),
      subtitle: join([vlan ? 'VLAN ' + vlan : '', n.subnet]), room: '', score: best, match: match, status: '',
    });
  });
  return out;
}

// Offline search: model-core searchLocal plus network hits (fields as
// fathom/search.py) and `status` on every hit (device.status for devices). An
// exact short-code query (XXXX-XXXX) leads with the device carrying that code.
export function augmentLocal(doc, q, limit) {
  const query = str(q).trim();
  if (!doc || !query) return [];
  const lim = limit > 0 ? limit : 20;
  const devices = {};
  (Array.isArray(doc.devices) ? doc.devices : []).forEach(function (d) { if (d && d.id) devices[d.id] = d; });
  const hits = searchLocal(doc, query, Infinity).map(function (h) {
    const d = h.kind === 'device' ? devices[h.id] : null;
    return Object.assign({}, h, { status: d ? str(d.status) : str(h.status) });
  }).concat(networkHits(doc, query));
  hits.sort(compareHits);
  return mergeHits(localCodeHits(doc, query), hits).slice(0, lim);
}

// a, then the hits of b whose kind:id is not already present.
export function mergeHits(a, b) {
  const seen = {};
  const out = [];
  [a, b].forEach(function (list) {
    (Array.isArray(list) ? list : []).forEach(function (h) {
      const k = hitKey(h);
      if (!h || own(seen, k)) return;
      seen[k] = true;
      out.push(h);
    });
  });
  return out;
}

export function roleFilter(hits, role) {
  const list = Array.isArray(hits) ? hits.slice() : [];
  if (role !== 'viewer') return list;
  return list.filter(function (h) { return !(h && h.kind === 'page' && h.status === 'draft'); });
}

// The partial route a hit opens (for ctx.navigateRoute), or null when the hit
// has no destination (an attachment without a device). id/tab/sub and query
// are always given so nothing from the current route leaks into the target.
export function targetFor(hit, route, doc) {
  if (!hit) return null;
  const r = route || {};
  const d = doc || {};
  const t = function (view, fields, query) {
    return Object.assign({ view: view, id: '', tab: '', sub: '', query: query || {} }, fields);
  };
  const dev = str(hit.device) || (hit.kind === 'device' ? str(hit.id) : '');
  switch (categorize(hit)) {
    case 'inventory':
      return t('inventory', {}, { sel: 'device:' + dev, sec: 'inventory' });
    case 'devices': {
      const rec = byId(d.devices, dev);
      return t('devices', { id: dev, room: (rec && rec.room) || str(r.room) });
    }
    default:
  }
  switch (hit.kind) {
    case 'port':
      return t('devices', { id: dev, tab: 'ports' }, { sel: 'port:' + dev + ':' + str(hit.port) });
    case 'cable':
      return t('schedules', { tab: 'cables' }, { sel: 'cable:' + str(hit.id) });
    case 'interface': {
      const id = str(hit.id);
      const iface = dev && id.indexOf(dev + '/') === 0 ? id.slice(dev.length + 1) : id.slice(id.lastIndexOf('/') + 1);
      return t('devices', { id: dev, tab: 'network' }, { hl: iface });
    }
    case 'network':
      return t('settings', { tab: 'networks' }, { hl: str(hit.id) });
    case 'room':
      return t('rooms', { id: str(hit.id), room: str(hit.id) });
    case 'rack':
      return t('racks', { id: str(hit.id) });
    case 'floorplan':
      return t('plan', { id: str(hit.id) });
    case 'attachment':
      return dev ? t('devices', { id: dev, tab: 'files' }, { hl: str(hit.id) }) : null;
    case 'page':
      return t('sop', {}, { page: str(hit.id) });
    default:
      return null;
  }
}

// ctx.recent type for a hit chosen from search, or '' when it is not
// remembered (only devices, rooms, racks and pages are).
export function recentType(hit) {
  return hit && RECENT_TYPES.indexOf(hit.kind) >= 0 ? hit.kind : '';
}

function recentEntries(recent, type) {
  if (!recent) return [];
  const raw = Array.isArray(recent[type]) ? recent[type] : null;
  if (raw) {
    return raw.map(function (e) {
      return e && typeof e === 'object' ? { id: str(e.id), t: Number(e.t) || 0 } : { id: str(e), t: 0 };
    });
  }
  if (typeof recent.list === 'function') {
    let ids = [];
    try { ids = recent.list(type) || []; } catch (e) { ids = []; }
    return (Array.isArray(ids) ? ids : []).map(function (id) { return { id: str(id), t: 0 }; });
  }
  return [];
}

function recentHit(doc, type, id) {
  const rooms = Array.isArray(doc.rooms) ? doc.rooms : [];
  const roomName = function (rid) { const rm = byId(rooms, rid); return rm ? str(rm.name) || rid : (rid ? rid : 'Shared inventory'); };
  const base = { kind: type, id: id, device: null, port: null, title: id, subtitle: '', room: null, score: 0, match: 'recent', status: '' };
  if (type === 'device') {
    const d = byId(doc.devices, id);
    if (!d) return null;
    const model = (str(d.manufacturer) + ' ' + str(d.model)).trim() || str(d.sub);
    return Object.assign(base, { device: id, title: str(d.name) || id, subtitle: join([model, roomName(str(d.room))]), room: str(d.room), status: str(d.status) });
  }
  if (type === 'room') {
    const rm = byId(rooms, id);
    return rm ? Object.assign(base, { title: str(rm.name) || id, subtitle: str(rm.code), room: id }) : null;
  }
  if (type === 'rack') {
    const k = byId(doc.racks, id);
    return k ? Object.assign(base, { title: str(k.name) || id, subtitle: join([k.units ? k.units + 'U' : '', roomName(str(k.room))]), room: str(k.room) }) : null;
  }
  if (type === 'page') {
    const pages = Array.isArray(doc.pages) ? doc.pages : [];
    let p = null;
    for (let i = 0; i < pages.length && !p; i++) if (pages[i] && (pages[i].slug === id || pages[i].id === id)) p = pages[i];
    if (!p || !p.slug) return null;
    return Object.assign(base, { id: str(p.slug), title: str(p.title) || str(p.slug), subtitle: str(p.kind || 'sop').replace(/_/g, ' '), status: str(p.status) });
  }
  return null;
}

// Hits for the remembered devices, rooms, racks and pages (D8 shape
// {type: [{id, t}]} or a ctx.recent with list(type) -> ids), newest first;
// ids no longer in the doc are dropped.
export function recentHits(doc, recent) {
  if (!doc || !recent) return [];
  const rows = [];
  const seen = {};
  RECENT_TYPES.forEach(function (type, ti) {
    recentEntries(recent, type).forEach(function (e, i) {
      const h = e.id ? recentHit(doc, type, e.id) : null;
      if (!h || own(seen, hitKey(h))) return;
      seen[hitKey(h)] = true;
      rows.push({ h: h, t: e.t, ti: ti, i: i });
    });
  });
  rows.sort(function (a, b) { return b.t - a.t || a.ti - b.ti || a.i - b.i; });
  return rows.map(function (r) { return r.h; });
}

// Next active option index for ↑/↓ with wrap-around; -1 when there are none.
export function moveActive(count, index, delta) {
  const n = Number(count) || 0;
  if (n <= 0) return -1;
  const i = Number(index);
  if (!(i >= 0) || i >= n) return delta < 0 ? n - 1 : 0;
  return (((i + (Math.trunc(Number(delta)) || 0)) % n) + n) % n;
}

// The no-results line: "No matches for “x” in Cables." (category `all`: no "in …").
export function noMatchText(q, cat) {
  const c = cat && cat !== 'all' ? category(cat) : null;
  return 'No matches for \u201c' + str(q).trim() + '\u201d' + (c ? ' in ' + c.label : '') + '.';
}
