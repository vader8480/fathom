// Entity page core (docs/ui-audit.md A.3, D5, B.2 ENTITY): header facts, URL
// tabs and overview summary cards for device, room and rack pages. Pure: no
// DOM, window, storage or timers, so it imports in Node. Facts are
// [{key, label, value, href?}]; empties are omitted. Every function takes an
// optional trailing `opts` with `href(view, id)` (e.g. a ctx.routeHref wrapper)
// that, when given, fills the `href` of facts that name another entity.

import { indexDoc, devicePorts, portRef } from './model-core.js';
import { rackDevices, rackItems, rackTotals, rackUnits, ruLabel } from './rack-core.js';

const DOT = ' \u00b7 ';

export const TAB_LABELS = {
  overview: 'Overview', ports: 'Ports', cables: 'Cables', network: 'Network', dmx: 'DMX',
  channels: 'Channels', inventory: 'Inventory', procedures: 'Procedures', files: 'Files',
  devices: 'Devices', racks: 'Racks', plans: 'Plans', elevation: 'Elevation',
};

const DEVICE_TABS = ['overview', 'ports', 'cables', 'network', 'inventory', 'procedures', 'files'];
const ROOM_TABS = ['overview', 'devices', 'cables', 'racks', 'plans', 'procedures'];
const RACK_TABS = ['overview', 'elevation', 'devices', 'cables'];

const STATUS_LEVEL = { installed: 'ok', planned: 'warn', spare: 'muted', retired: 'muted' };

function list(v) {
  return Array.isArray(v) ? v : [];
}

function str(v) {
  return v === undefined || v === null ? '' : String(v).trim();
}

function has(v) {
  return v !== undefined && v !== null && String(v).trim() !== '';
}

function find(coll, id) {
  if (!has(id)) return null;
  for (let i = 0; i < coll.length; i++) if (coll[i] && coll[i].id === id) return coll[i];
  return null;
}

function cap(s) {
  const t = str(s);
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : '';
}

function plural(n, one, many) {
  return n + ' ' + (n === 1 ? one : many);
}

function linker(opts) {
  const fn = opts && typeof opts.href === 'function' ? opts.href : null;
  return function (view, id) {
    if (!fn || !has(id)) return undefined;
    const href = fn(view, id);
    return typeof href === 'string' && href ? href : undefined;
  };
}

function fact(out, key, label, value, href) {
  if (!has(value)) return;
  const f = { key: key, label: label, value: String(value) };
  if (href) f.href = href;
  out.push(f);
}

function nameOf(entity, id) {
  return entity ? str(entity.name) || str(entity.id) : str(id);
}

// Cables with at least one end on one of `ids`, each once, in doc order.
function cablesTouching(doc, ids) {
  const set = {};
  ids.forEach(function (id) { set[id] = true; });
  return list(doc && doc.cables).filter(function (c) {
    return c && ((c.from && set[c.from.device]) || (c.to && set[c.to.device]));
  });
}

function patchedCount(idx, device) {
  return devicePorts(device).filter(function (p) {
    return p && list(idx.cablesByPort[portRef(device.id, p.id)]).length > 0;
  }).length;
}

export function tabLabel(key) {
  return TAB_LABELS[key] || cap(key);
}

// Header status pill for a device status: {label, level} (level ok | warn | err | muted), or null.
export function statusPill(status) {
  const s = str(status).toLowerCase();
  if (!s) return null;
  return { label: cap(s), level: STATUS_LEVEL[s] || 'muted' };
}

// Primary network address: the ip of the role-primary interface, else the
// first interface with an ip; plus dante_name ("10.20.0.10 · FOH-CL5").
export function primaryAddress(device) {
  const ifs = list(device && device.interfaces).filter(function (i) { return i && has(i.ip); });
  const primary = ifs.filter(function (i) { return i.role === 'primary'; })[0] || ifs[0];
  const parts = [];
  if (primary) parts.push(str(primary.ip));
  if (device && has(device.dante_name)) parts.push(str(device.dante_name));
  return parts.join(DOT);
}

// "FOH rack · U10" (or "U3–4" for a 2U device, " rear" for the rear face).
export function rackPosition(doc, device) {
  const r = device && device.rack;
  if (!r || !has(r.id)) return '';
  const rack = find(list(doc && doc.racks), r.id);
  const u = parseInt(r.u, 10);
  let pos = '';
  if (u >= 1) {
    const hgt = parseInt(r.height, 10) >= 1 ? parseInt(r.height, 10) : 1;
    const a = ruLabel(rack, u);
    const b = ruLabel(rack, u + hgt - 1);
    pos = 'U' + (hgt > 1 ? (Number(a) < Number(b) ? a + '\u2013' + b : b + '\u2013' + a) : a);
    if (r.face === 'rear') pos += ' rear';
  }
  return nameOf(rack, r.id) + (pos ? DOT + pos : '');
}

export function deviceFacts(doc, vocab, device, overlay, opts) {
  const out = [];
  if (!device) return out;
  const link = linker(opts);
  const kinds = (vocab && vocab.kinds) || {};
  const discs = (vocab && vocab.disciplines) || {};
  const k = kinds[device.kind] || null;
  const disc = str(device.discipline) || (k && str(k.discipline)) || '';
  const discLabel = disc ? (discs[disc] && str(discs[disc].label)) || cap(disc) : '';
  const kindLabel = (k && str(k.label)) || str(device.kind);
  fact(out, 'kind', 'Kind', [discLabel, kindLabel].filter(Boolean).join(DOT));
  const pill = statusPill(device.status);
  fact(out, 'status', 'Status', pill ? pill.label : '');
  if (has(device.room)) {
    const room = find(list(doc && doc.rooms), device.room);
    fact(out, 'room', 'Room', nameOf(room, device.room), link('rooms', device.room));
  }
  fact(out, 'rack', 'Rack \u00b7 U', rackPosition(doc, device), device.rack ? link('racks', device.rack.id) : undefined);
  fact(out, 'network', 'Network', primaryAddress(device));
  const ports = devicePorts(device);
  if (ports.length) fact(out, 'ports', 'Ports', ports.length + ' (' + patchedCount(indexDoc(doc), device) + ' patched)');
  return out;
}

export function roomFacts(doc, room, opts) {
  const out = [];
  if (!room) return out;
  const link = linker(opts);
  const idx = indexDoc(doc);
  if (has(room.venue)) fact(out, 'venue', 'Venue', nameOf(find(list(doc && doc.venues), room.venue), room.venue));
  fact(out, 'code', 'Code', str(room.code));
  const devs = list(idx.devicesByRoom[room.id]);
  fact(out, 'devices', 'Devices', String(devs.length), link('devices', room.id));
  fact(out, 'racks', 'Racks', String(list(doc && doc.racks).filter(function (r) { return r && r.room === room.id; }).length));
  fact(out, 'plans', 'Plans', String(list(doc && doc.floorplans).filter(function (f) { return f && f.room === room.id; }).length));
  fact(out, 'cables', 'Cables', String(cablesTouching(doc, devs.map(function (d) { return d.id; })).length));
  return out;
}

const FORM_FACTOR_LABELS = {
  cabinet: 'Cabinet', open_frame: 'Open frame', two_post: '2-post', four_post: '4-post',
  wall_mount: 'Wall mount', road_case: 'Road case',
};

const RACK_WIDTHS = [10, 19, 21, 23];

// rackTotals for a rack object that may not be in doc.racks (then devices only,
// counted by rack id, items from the object).
function totalsOf(doc, rack, info) {
  const t = rackTotals(doc, rack.id, info);
  if (t) return t;
  const units = rackUnits(rack);
  const used = {};
  rackDevices(doc, rack.id).forEach(function (p) {
    if (p.shelf || !(p.u >= 1)) return;
    for (let u = p.u; u < p.u + p.height; u++) if (u <= units) used[u] = true;
  });
  const n = Object.keys(used).length;
  return { units: units, used_u: n, free_u: units - n, weight_kg: 0, max_load_kg: null, power_w: 0, power_limit_w: null,
    devices: rackDevices(doc, rack.id).length, items: list(rack.items).length };
}

function rackWidthIn(rack) {
  const w = parseInt(rack && rack.width_in, 10);
  return RACK_WIDTHS.indexOf(w) >= 0 ? w : 19;
}

function formFactorLabel(rack) {
  const f = str(rack && rack.form_factor);
  return FORM_FACTOR_LABELS[f] || FORM_FACTOR_LABELS.cabinet;
}

// Load and power against the rack's limits: {weight: {value, limit, over}, power: {…}}.
function rackLimits(totals) {
  function one(v, lim) { return { value: v, limit: lim, over: lim !== null && v > lim }; }
  const t = totals || {};
  return {
    weight: one(t.weight_kg || 0, typeof t.max_load_kg === 'number' ? t.max_load_kg : null),
    power: one(t.power_w || 0, typeof t.power_limit_w === 'number' ? t.power_limit_w : null),
  };
}

// The rack page passes opts.info / ctxInfo.info (template summaries
// {id: {weight_kg, power_w}} for rackTotals, {} while loading); its presence
// selects the page's fuller facts and cards over the A.3 set.
function pageInfo(o) {
  return o && o.info && typeof o.info === 'object' ? o.info : null;
}

// A.3: room, height, used, free, devices, location. With opts.info: width and
// form factor after height, row last.
export function rackFacts(doc, rack, opts) {
  const out = [];
  if (!rack) return out;
  const link = linker(opts);
  const info = pageInfo(opts);
  const t = totalsOf(doc, rack, info);
  if (has(rack.room)) fact(out, 'room', 'Room', nameOf(find(list(doc && doc.rooms), rack.room), rack.room), link('rooms', rack.room));
  fact(out, 'height', 'Height', t.units + ' U');
  if (info) {
    fact(out, 'width', 'Width', rackWidthIn(rack) + '\u2033');
    fact(out, 'form', 'Form factor', formFactorLabel(rack));
  }
  fact(out, 'used', 'Used', t.used_u + ' U');
  fact(out, 'free', 'Free', Math.max(0, t.free_u) + ' U');
  fact(out, 'devices', 'Devices', String(t.devices));
  if (has(rack.location)) fact(out, 'location', 'Location', nameOf(find(list(doc && doc.locations), rack.location), rack.location));
  if (info) fact(out, 'row', 'Row', str(rack.row));
  return out;
}

function hasDmx(device) {
  const d = device && device.dmx;
  return !!d && (has(d.address) || has(d.universe));
}

export function deviceTabs(doc, device) {
  const tabs = DEVICE_TABS.slice();
  const extra = [];
  if (hasDmx(device)) extra.push('dmx');
  if (device && list(device.channels).length) extra.push('channels');
  tabs.splice.apply(tabs, [tabs.indexOf('network') + 1, 0].concat(extra));
  return tabs;
}

export function roomTabs() {
  return ROOM_TABS.slice();
}

// Without a rack: the A.3 tab set. A rack page passes its rack and also gets
// `accessories` after `devices` (shown even when the rack has none, to add one).
export function rackTabs(doc, rack) {
  const tabs = RACK_TABS.slice();
  if (rack) tabs.splice(tabs.indexOf('devices') + 1, 0, 'accessories');
  return tabs;
}

// tabs: keys or {key} objects. Unknown, empty or missing → the default tab
// (overview) with redirect: true, so the caller replaces the URL (D5).
export function resolveTab(tabs, requested) {
  const keys = list(tabs).map(function (t) { return typeof t === 'string' ? t : t && t.key; }).filter(Boolean);
  const want = str(requested);
  if (want && keys.indexOf(want) >= 0) return { tab: want, redirect: false };
  return { tab: keys.indexOf('overview') >= 0 || !keys.length ? 'overview' : keys[0], redirect: true };
}

function pagesOf(doc, ctxInfo) {
  const pages = ctxInfo && Array.isArray(ctxInfo.pages) ? ctxInfo.pages : list(doc && doc.pages);
  return pages.filter(function (p) { return p && p.status !== 'archived'; });
}

// Problem reports ({id, text, status, device, room, page}: doc.problems, GET
// /problems). Validation results ({level, code, ref, path, message}, what the
// shell's ctx.problems() holds) are not reports and never count.
function isReport(p) {
  return !!p && typeof p === 'object' && has(p.id) && !(has(p.code) && has(p.level));
}

// ctxInfo.problems wins when it is a report list (an empty list included); a
// list holding only validation results falls back to doc.problems.
function problemsOf(doc, ctxInfo) {
  const given = ctxInfo && Array.isArray(ctxInfo.problems) ? ctxInfo.problems : null;
  const probs = given && (!given.length || given.some(isReport)) ? given : list(doc && doc.problems);
  return probs.filter(function (p) { return isReport(p) && (p.status || 'open') === 'open'; });
}

function bodyRefs(body, type) {
  const out = [];
  const re = /\[\[(device|room):([^\]|]+)(?:\|[^\]]*)?\]\]/g;
  let m;
  while ((m = re.exec(String(body || '')))) if (m[1] === type) out.push(m[2].trim());
  return out;
}

// Pages that apply to an entity explicitly (devices/rooms) or through [[device:id]] body refs.
function pagesFor(pages, type, id) {
  const field = type + 's';
  return pages.filter(function (p) {
    return list(p[field]).indexOf(id) >= 0 || bodyRefs(p.body, type).indexOf(id) >= 0;
  });
}

function ids(items, fn) {
  return items.map(fn || function (x) { return x.id; });
}

function card(key, label, items, opts) {
  const o = opts || {};
  const c = { key: key, label: label, count: items.length, sub: o.sub || '', tab: o.tab || null };
  c.drill = o.kind ? { title: o.title || label, kind: o.kind, ids: ids(items, o.id) } : null;
  return c;
}

function countCard(key, label, count, tab, sub) {
  return { key: key, label: label, count: count, sub: sub || '', tab: tab || null, drill: null };
}

function deviceCards(doc, device, ctxInfo) {
  const idx = indexDoc(doc);
  const name = nameOf(device, device.id);
  const ports = devicePorts(device).filter(function (p) { return p && has(p.id); });
  const patched = patchedCount(idx, device);
  const cables = list(idx.cablesByDevice[device.id]);
  const ifaces = list(device.interfaces).filter(Boolean);
  const files = list(doc && doc.attachments).filter(function (a) { return a && a.device === device.id; });
  const problems = problemsOf(doc, ctxInfo).filter(function (p) { return p.device === device.id; });
  const pages = pagesFor(pagesOf(doc, ctxInfo), 'device', device.id);
  return [
    card('ports', 'Ports', ports, { tab: 'ports', kind: 'port', title: 'Ports' + DOT + name, sub: ports.length ? patched + ' patched' : '',
      id: function (p) { return portRef(device.id, p.id); } }),
    card('cables', 'Cables', cables, { tab: 'cables', kind: 'cable', title: plural(cables.length, 'cable', 'cables') + DOT + name }),
    card('network', 'Network', ifaces, { tab: 'network', sub: primaryAddress(device) }),
    card('procedures', 'Procedures', pages, { tab: 'procedures', kind: 'page', title: 'Procedures' + DOT + name,
      id: function (p) { return p.slug || p.id; } }),
    card('problems', 'Problems', problems, { kind: 'problem', title: 'Open problems' + DOT + name, sub: problems.length ? 'open' : '' }),
    card('files', 'Files', files, { tab: 'files', kind: 'file', title: 'Files' + DOT + name }),
  ];
}

function roomCards(doc, room, ctxInfo) {
  const idx = indexDoc(doc);
  const name = nameOf(room, room.id);
  const devs = list(idx.devicesByRoom[room.id]);
  const devIds = ids(devs);
  const cables = cablesTouching(doc, devIds);
  const racks = list(doc && doc.racks).filter(function (r) { return r && r.room === room.id; });
  const plans = list(doc && doc.floorplans).filter(function (f) { return f && f.room === room.id; });
  const pages = pagesFor(pagesOf(doc, ctxInfo), 'room', room.id);
  const problems = problemsOf(doc, ctxInfo).filter(function (p) { return p.room === room.id || (has(p.device) && devIds.indexOf(p.device) >= 0); });
  return [
    card('devices', 'Devices', devs, { tab: 'devices', kind: 'device', title: plural(devs.length, 'device', 'devices') + DOT + name }),
    card('cables', 'Cables', cables, { tab: 'cables', kind: 'cable', title: plural(cables.length, 'cable', 'cables') + DOT + name }),
    card('racks', 'Racks', racks, { tab: 'racks', kind: 'rack', title: 'Racks' + DOT + name }),
    card('plans', 'Plans', plans, { tab: 'plans', kind: 'floorplan', title: 'Floor plans' + DOT + name }),
    card('procedures', 'Procedures', pages, { tab: 'procedures', kind: 'page', title: 'Procedures' + DOT + name,
      id: function (p) { return p.slug || p.id; } }),
    card('problems', 'Problems', problems, { kind: 'problem', title: 'Open problems' + DOT + name, sub: problems.length ? 'open' : '' }),
  ];
}

function num1(n) {
  return String(Math.round(n * 10) / 10);
}

// A load card (weight, power): value against the rack's limit, level 'warn' when over.
function limitCard(key, label, l, unit, limitWord) {
  const c = countCard(key, label, l.value, null, l.limit === null ? unit : unit + ' of ' + num1(l.limit) + ' ' + limitWord);
  c.limit = l.limit;
  c.level = l.over ? 'warn' : '';
  c.title = l.over ? num1(l.value - l.limit) + ' ' + unit + ' over the ' + limitWord : '';
  return c;
}

function rackCards(doc, rack, ctxInfo) {
  const name = nameOf(rack, rack.id);
  const info = pageInfo(ctxInfo);
  const t = totalsOf(doc, rack, info);
  const tabs = ctxInfo && Array.isArray(ctxInfo.tabs) ? ctxInfo.tabs : rackTabs();
  const devIds = ids(rackDevices(doc, rack.id), function (p) { return p.device; });
  const devs = devIds.map(function (id) { return { id: id }; });
  const cables = cablesTouching(doc, devIds);
  const problems = problemsOf(doc, ctxInfo).filter(function (p) { return has(p.device) && devIds.indexOf(p.device) >= 0; });
  const devCard = card('devices', 'Devices', devs, { tab: 'devices', kind: 'device', title: plural(devs.length, 'device', 'devices') + DOT + name });
  const tail = [
    card('cables', 'Cables', cables, { tab: 'cables', kind: 'cable', title: plural(cables.length, 'cable', 'cables') + DOT + name }),
    card('problems', 'Problems', problems, { kind: 'problem', title: 'Open problems' + DOT + name, sub: problems.length ? 'open' : '' }),
  ];
  if (!info) {
    return [
      countCard('height', 'Height', t.units, 'elevation', 'U'),
      countCard('used', 'Used', t.used_u, 'elevation', 'U'),
      countCard('free', 'Free', Math.max(0, t.free_u), 'elevation', 'U'),
      devCard,
    ].concat(tail);
  }
  const lim = rackLimits(t);
  return [
    countCard('used', 'Used', t.used_u, 'elevation', 'of ' + t.units + ' U'),
    countCard('free', 'Free', Math.max(0, t.free_u), 'elevation', 'U'),
    limitCard('weight', 'Weight', lim.weight, 'kg', 'max'),
    limitCard('power', 'Power', lim.power, 'W', 'limit'),
    devCard,
    countCard('accessories', 'Accessories', rackItems(doc, rack.id).length, tabs.indexOf('accessories') >= 0 ? 'accessories' : null),
  ].concat(tail);
}

// Overview cards: [{key, label, count, sub, tab, drill: {title, kind, ids} | null}].
// ctxInfo = {problems, pages}: problem reports (not ctx.problems(), which holds
// validation results; see problemsOf) and the SOP pages. Each falls back to the
// doc collection (doc.problems, doc.pages) when absent. Only open problem reports
// and non-archived pages count.
// Racks: height, used, free, devices, cables, problems (A.3). With ctxInfo.info
// (template summaries, see pageInfo): used, free, weight, power, devices,
// accessories, cables, problems; weight and power add {limit, level:
// 'warn'|'', title}, and ctxInfo.tabs (default rackTabs()) gates the
// accessories card's tab.
export function summaryCards(kind, doc, entity, ctxInfo) {
  if (!entity) return [];
  if (kind === 'device') return deviceCards(doc, entity, ctxInfo);
  if (kind === 'room') return roomCards(doc, entity, ctxInfo);
  if (kind === 'rack') return rackCards(doc, entity, ctxInfo);
  return [];
}
