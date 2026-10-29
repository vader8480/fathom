// Rack library palette, pure core (docs/SPEC.md §6.13.11): library entries, ranked search,
// categories, favourites/recents prefs and the device a template instantiates into. No DOM, window,
// storage, fetch or timers, so it imports in Node.

import { newId, expandPortGroups, scoreText, deepClone } from './model-core.js';
import { CATEGORY_COLORS } from './rack-display-core.js';

export { CATEGORY_COLORS };

export const STORAGE_KEY = 'fathom.ui.rack.palette';
export const PREFS_VERSION = 1;
export const MAX_RECENTS = 12;
export const MAX_FAVS = 200;

// Rackula categories in display order (contract B `rack_category`).
export const CATEGORY_ORDER = ['server', 'network', 'firewall', 'patch-panel', 'power', 'storage', 'kvm', 'av-media',
  'cooling', 'shelf', 'blank', 'cable-management', 'chassis', 'other'];

export const CATEGORY_LABELS = {
  server: 'Server', network: 'Network', firewall: 'Firewall', 'patch-panel': 'Patch panel', power: 'Power',
  storage: 'Storage', kvm: 'KVM', 'av-media': 'AV / Media', cooling: 'Cooling', shelf: 'Shelf', blank: 'Blank',
  'cable-management': 'Cable management', chassis: 'Chassis', other: 'Other',
};

// Tie-break order after the score.
export const SOURCE_ORDER = ['project', 'custom', 'builtin', 'extension', 'preset', 'catalog'];

// Fathom kinds (vocab.KINDS) whose discipline is audio or video, for templates without `rack_category`.
const AV_KINDS = ['source', 'stage_io', 'console', 'iem', 'pa', 'video', 'mic', 'wireless_rx', 'processor', 'amp', 'speaker',
  'recorder', 'intercom', 'camera', 'video_source', 'video_switcher', 'video_router', 'converter', 'encoder', 'display',
  'projector'];
const KIND_CATEGORY = { switch: 'network', network: 'network', power: 'power', patch_panel: 'patch-panel', computer: 'server' };

const HAS = Object.prototype.hasOwnProperty;

function str(v) {
  return v === undefined || v === null ? '' : String(v);
}

function ruOf(v) {
  const n = parseInt(v, 10);
  return n >= 1 ? n : 0;
}

// Category key of a template or entry: its `rack_category` when known, else derived from `kind`
// (switch/network → network, power → power, patch_panel → patch-panel, computer → server,
// audio/video kinds → av-media, anything else → other).
export function categoryOf(t) {
  const x = t || {};
  const rc = str(x.rack_category);
  if (rc && HAS.call(CATEGORY_LABELS, rc)) return rc;
  const kind = str(x.kind);
  if (HAS.call(KIND_CATEGORY, kind)) return KIND_CATEGORY[kind];
  if (AV_KINDS.indexOf(kind) >= 0) return 'av-media';
  return 'other';
}

export function categoryLabel(key) {
  return HAS.call(CATEGORY_LABELS, key) ? CATEGORY_LABELS[key] : CATEGORY_LABELS.other;
}

export function categoryColor(key) {
  return HAS.call(CATEGORY_COLORS, key) ? CATEGORY_COLORS[key] : CATEGORY_COLORS.other;
}

export function kindLabel(kind, vocab) {
  const k = str(kind);
  const v = vocab && vocab.kinds && HAS.call(vocab.kinds, k) ? vocab.kinds[k] : null;
  if (v && v.label) return String(v.label);
  return k.replace(/_/g, ' ');
}

// A /api/v2/presets entry in the §4.5 template shape (fathom.presets.as_template).
export function presetAsTemplate(p) {
  const x = p || {};
  const label = str(x.label || x.name || x.model || x.id);
  const t = { id: str(x.id), manufacturer: str(x.manufacturer) || 'Generic', model: str(x.model) || label, name: label, kind: str(x.kind) || 'other' };
  ['discipline', 'brand', 'ru', 'width', 'power_w', 'weight_kg', 'dante', 'routing', 'dmx_footprint', 'rack_category',
    'image_front', 'image_rear', 'full_depth', 'part_number'].forEach(function (k) {
    if (x[k] !== undefined && x[k] !== null) t[k] = deepClone(x[k]);
  });
  t.ports = deepClone(Array.isArray(x.ports) ? x.ports : []);
  t.source = 'preset';
  return t;
}

function entryFrom(s, source, template) {
  const name = str(s.name) || str(s.model) || str(s.id);
  const e = {
    id: str(s.id), name: name, manufacturer: str(s.manufacturer), model: str(s.model), part_number: str(s.part_number),
    ru: ruOf(s.ru), kind: str(s.kind) || 'other', rack_category: str(s.rack_category), image_front: str(s.image_front),
    source: source, template: template || null,
  };
  e.category = categoryOf(e);
  if (s.image_rear) e.image_rear = str(s.image_rear);
  if (typeof s.full_depth === 'boolean') e.full_depth = s.full_depth;
  ['weight_kg', 'power_w'].forEach(function (k) { if (typeof s[k] === 'number') e[k] = s[k]; });
  if (s.discipline) e.discipline = str(s.discipline);
  return e;
}

function twinKey(e) {
  return str(e.manufacturer).trim().toLowerCase() + '\u0000' + str(e.model).trim().toLowerCase();
}

function keeperRank(e) {
  return e.image_front ? 0 : (e.image_rear ? 1 : 2);
}

// Collapses catalog entries that share a case-insensitive manufacturer + model (the catalog keeps some
// devices under two slugs so Rackula layouts resolve): the one with a front image wins, then one
// with a rear image, then the shorter id (then the smaller id). The kept entry lists the dropped ids
// in `aliases` and stays where the first twin was. Other sources are never collapsed.
// Returns {entries, dropped: {droppedId: keptId}}.
export function dedupeCatalog(entries) {
  const list = Array.isArray(entries) ? entries : [];
  const groups = {};
  list.forEach(function (e) {
    if (!e || e.source !== 'catalog' || !(str(e.manufacturer) || str(e.model))) return;
    const k = twinKey(e);
    (groups[k] = groups[k] || []).push(e);
  });
  const dropped = {};
  const keep = {};
  Object.keys(groups).forEach(function (k) {
    const g = groups[k];
    if (g.length < 2) return;
    const best = g.slice().sort(function (a, b) {
      return (keeperRank(a) - keeperRank(b)) || (a.id.length - b.id.length) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
    })[0];
    const kept = Object.assign({}, best, { aliases: (best.aliases || []).slice() });
    g.forEach(function (e) {
      if (e === best) return;
      dropped[e.id] = best.id;
      kept.aliases.push(e.id);
    });
    keep[k] = kept;
  });
  const out = [];
  const placed = {};
  list.forEach(function (e) {
    if (!e) return;
    const k = e.source === 'catalog' ? twinKey(e) : '';
    if (k && HAS.call(keep, k)) {
      if (!placed[k]) { placed[k] = true; out.push(keep[k]); }
      return;
    }
    out.push(e);
  });
  return { entries: out, dropped: dropped };
}

// Palette entries from GET /api/v2/library?source=all&rack=1 (`{templates: [summary]}`, or the list)
// plus GET /api/v2/presets (`{presets}` or the list) as a fallback for ids the library lacks. Only
// rack-mountable templates (`ru` ≥ 1) are kept; the first entry per id wins; catalog twins collapse
// (dedupeCatalog). `template` is the full template when the data carries ports (presets), else null
// (fetch it with ctx.api.template).
export function normalizeEntries(libraryResponse, presets) {
  const lib = libraryResponse && Array.isArray(libraryResponse.templates) ? libraryResponse.templates
    : (Array.isArray(libraryResponse) ? libraryResponse : []);
  const pre = presets && Array.isArray(presets.presets) ? presets.presets : (Array.isArray(presets) ? presets : []);
  const presetById = {};
  pre.forEach(function (p) { if (p && p.id && !HAS.call(presetById, p.id)) presetById[p.id] = presetAsTemplate(p); });
  const out = [];
  const seen = {};
  lib.forEach(function (s) {
    if (!s || !s.id || HAS.call(seen, s.id) || !ruOf(s.ru)) return;
    const source = str(s.source) || 'builtin';
    const full = Array.isArray(s.ports) ? s : (source === 'preset' && HAS.call(presetById, s.id) ? presetById[s.id] : null);
    seen[s.id] = true;
    out.push(entryFrom(s, source, full));
  });
  Object.keys(presetById).forEach(function (id) {
    const t = presetById[id];
    if (HAS.call(seen, id) || !ruOf(t.ru)) return;
    seen[id] = true;
    out.push(entryFrom(t, 'preset', t));
  });
  return dedupeCatalog(out).entries;
}

function sourceRank(s) {
  const i = SOURCE_ORDER.indexOf(s);
  return i < 0 ? SOURCE_ORDER.length : i;
}

function cmpText(a, b) {
  const x = str(a).toLowerCase();
  const y = str(b).toLowerCase();
  return x < y ? -1 : x > y ? 1 : 0;
}

export function compareEntries(a, b) {
  return (sourceRank(a.source) - sourceRank(b.source)) || cmpText(a.name, b.name) || cmpText(a.id, b.id);
}

// [field, text] pairs searched for an entry; `all` (every field joined) only counts up to the
// token level, so "dell server" matches across fields without outranking a field match.
export function entryFields(e, vocab) {
  const cat = e.category || categoryOf(e);
  return [
    ['name', e.name], ['manufacturer', e.manufacturer], ['model', e.model], ['part_number', e.part_number],
    ['kind', kindLabel(e.kind, vocab)], ['category', categoryLabel(cat)],
    ['maker_model', (str(e.manufacturer) + ' ' + str(e.model)).trim()],
  ];
}

// Score (0 when no match) and the field that matched, on the FR-SRCH-04 scale.
export function scoreEntry(e, q, vocab) {
  let best = 0;
  let match = '';
  entryFields(e, vocab).forEach(function (f) {
    const s = scoreText(f[1], q);
    if (s > best) { best = s; match = f[0]; }
  });
  const all = entryFields(e, vocab).map(function (f) { return str(f[1]); }).join(' ');
  const s = Math.min(60, scoreText(all, q));
  if (s > best) { best = s; match = 'all'; }
  return { score: best, match: match };
}

// Entries matching `q`, best first: exact 100 > prefix 80 > token 60 > substring 40 > fuzzy 25
// (model-core.scoreText), ties by SOURCE_ORDER then name. An empty query keeps every entry in tie
// order. opts: {category: key ('' or 'all' = every category), vocab}.
export function searchEntries(entries, q, opts) {
  const o = opts || {};
  const cat = o.category && o.category !== 'all' ? o.category : '';
  const query = str(q).trim();
  const rows = [];
  (Array.isArray(entries) ? entries : []).forEach(function (e) {
    if (!e) return;
    if (cat && (e.category || categoryOf(e)) !== cat) return;
    const s = query ? scoreEntry(e, query, o.vocab).score : 1;
    if (s > 0) rows.push({ e: e, s: s });
  });
  rows.sort(function (a, b) { return (b.s - a.s) || compareEntries(a.e, b.e); });
  return rows.map(function (r) { return r.e; });
}

// [{key, label, color, entries}] in CATEGORY_ORDER, empty categories dropped; entries keep their order.
export function groupByCategory(entries) {
  const by = {};
  (Array.isArray(entries) ? entries : []).forEach(function (e) {
    if (!e) return;
    const k = e.category || categoryOf(e);
    (by[k] = by[k] || []).push(e);
  });
  return CATEGORY_ORDER.filter(function (k) { return by[k]; }).map(function (k) {
    return { key: k, label: CATEGORY_LABELS[k], color: CATEGORY_COLORS[k], entries: by[k] };
  });
}

// ------------------------------------------------------------ prefs

function idList(v, cap) {
  const out = [];
  (Array.isArray(v) ? v : []).forEach(function (id) {
    if (typeof id !== 'string' || !id || out.indexOf(id) >= 0 || out.length >= cap) return;
    out.push(id);
  });
  return out;
}

// Prefs from the parsed value of localStorage `fathom.ui.rack.palette` (a JSON string is parsed too);
// anything missing or corrupt gives the defaults.
export function readPrefs(raw) {
  let v = raw;
  if (typeof v === 'string') {
    try { v = JSON.parse(v); } catch (e) { v = null; }
  }
  if (!v || typeof v !== 'object' || Array.isArray(v) || (v.v !== undefined && v.v !== PREFS_VERSION)) {
    return { v: PREFS_VERSION, favs: [], recents: [] };
  }
  return { v: PREFS_VERSION, favs: idList(v.favs, MAX_FAVS), recents: idList(v.recents, MAX_RECENTS) };
}

function idsOf(id, aliases) {
  return [String(id)].concat(Array.isArray(aliases) ? aliases.map(String) : []);
}

// `aliases` (optional): the dropped twin ids of a deduped catalog entry, which count as the same entry.
export function isFav(prefs, id, aliases) {
  const favs = readPrefs(prefs).favs;
  return idsOf(id, aliases).some(function (x) { return favs.indexOf(x) >= 0; });
}

// New prefs with `id` added to (end) or removed from the favourites; removing also drops its aliases.
export function toggleFav(prefs, id, aliases) {
  const p = readPrefs(prefs);
  if (!id) return p;
  const all = idsOf(id, aliases);
  const favs = isFav(p, id, aliases)
    ? p.favs.filter(function (x) { return all.indexOf(x) < 0; })
    : p.favs.concat([String(id)]).slice(0, MAX_FAVS);
  return { v: PREFS_VERSION, favs: favs, recents: p.recents };
}

// New prefs with `id` first in the recents (moved if present, its aliases removed), at most MAX_RECENTS.
export function pushRecent(prefs, id, aliases) {
  const p = readPrefs(prefs);
  if (!id) return p;
  const all = idsOf(id, aliases);
  const recents = [String(id)].concat(p.recents.filter(function (x) { return all.indexOf(x) < 0; })).slice(0, MAX_RECENTS);
  return { v: PREFS_VERSION, favs: p.favs, recents: recents };
}

// Entries for a list of ids (favourites, recents) in that order. An id dropped by dedupeCatalog
// resolves to its kept twin (via `aliases`); unknown ids are skipped and each entry appears once.
export function entriesFor(entries, ids) {
  const by = {};
  (Array.isArray(entries) ? entries : []).forEach(function (e) {
    if (!e) return;
    if (!HAS.call(by, e.id)) by[e.id] = e;
    (Array.isArray(e.aliases) ? e.aliases : []).forEach(function (a) { if (!HAS.call(by, a)) by[a] = e; });
  });
  const out = [];
  (Array.isArray(ids) ? ids : []).forEach(function (id) {
    if (HAS.call(by, id) && out.indexOf(by[id]) < 0) out.push(by[id]);
  });
  return out;
}

// ------------------------------------------------------------ instantiate

// The device a template instantiates into, mirroring fathom.library.instantiate: id = slug of the
// name deduped against doc.devices (`-2`, `-3`, …), name, kind, discipline (only when it differs from
// the kind's; with no `opts.vocab` it is kept when set), manufacturer, model, brand, template: <id>,
// room, dante, dmx footprint, routing and the §4.4.3 expanded ports. Never sets `rack`: the host
// places it. opts: {room, name, vocab}.
export function deviceFromTemplate(doc, template, opts) {
  const o = opts || {};
  const t = template || {};
  const name = str(o.name).trim() || str(t.name) || str(t.model) || str(t.label) || str(t.id) || 'Device';
  const id = newId(null, (doc && doc.devices) || [], name);
  const dev = { id: id, name: name, kind: str(t.kind) || 'other' };
  if (t.discipline) {
    const kinds = o.vocab && o.vocab.kinds;
    const kd = kinds && HAS.call(kinds, dev.kind) ? kinds[dev.kind].discipline : undefined;
    if (!kinds || t.discipline !== kd) dev.discipline = t.discipline;
  }
  ['manufacturer', 'model', 'brand'].forEach(function (k) { if (t[k]) dev[k] = t[k]; });
  if (t.id) dev.template = t.id;
  dev.room = str(o.room);
  if (t.dante) dev.dante = true;
  if (t.dmx_footprint) dev.dmx = { footprint: t.dmx_footprint };
  if (typeof t.routing === 'string' && t.routing) dev.routing = { mode: t.routing };
  else if (t.routing && typeof t.routing === 'object' && t.routing.mode) dev.routing = deepClone(t.routing);
  dev.ports = expandPortGroups(Array.isArray(t.ports) ? t.ports : []);
  return { ops: [{ op: 'put', coll: 'devices', id: id, value: dev }], id: id };
}

// ------------------------------------------------------------ keyboard

// Next row index for ArrowUp/ArrowDown/Home/End/PageUp/PageDown; -1 from the first row on ArrowUp
// (back to the search box). Unknown keys return `current`.
export function nextRow(count, current, key) {
  const n = Number(count) || 0;
  if (n <= 0) return -1;
  const i = Number(current);
  const at = i >= 0 && i < n ? i : -1;
  switch (key) {
    case 'ArrowDown': return at < 0 ? 0 : Math.min(n - 1, at + 1);
    case 'ArrowUp': return at <= 0 ? -1 : at - 1;
    case 'Home': return 0;
    case 'End': return n - 1;
    case 'PageDown': return Math.min(n - 1, (at < 0 ? 0 : at) + 10);
    case 'PageUp': return Math.max(0, at - 10);
    default: return at;
  }
}
