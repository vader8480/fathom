// Dev harness for datatable.js (docs/ui-audit.md B.2 TABLE, D10).
// ?rows=N synthetic rows (default 240) · ?cards=1 card layout at sm · ?readonly=1
// no selection · ?appdialog=1 drill-down through app.js openDialog · ?smoke=1
// writes data-smoke. The main table binds its state to the hash query (D1 keys).
import { h } from '../js/dom.js';
import { parseRoute, buildRoute, withQuery } from '../js/router-core.js';
import { createTable, openTableDialog } from '../js/datatable.js';

const errors = [];
window.__fathomErrors = errors;
window.addEventListener('error', function (e) { errors.push(String((e && e.message) || e)); });
window.addEventListener('unhandledrejection', function (e) { errors.push('unhandled: ' + String(e && e.reason && (e.reason.stack || e.reason.message) || e.reason)); });

const params = new URLSearchParams(location.search);
const N = Math.max(0, Math.min(200000, parseInt(params.get('rows') || '240', 10) || 0));
const readOnly = params.has('readonly');
const events = [];
const log = document.getElementById('h-log');

function note(text) {
  events.push(text);
  if (log) {
    log.insertBefore(h('li', { text: text }), log.firstChild);
    while (log.childNodes.length > 60) log.removeChild(log.lastChild);
  }
}

function rng(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const DEVICES = ['FOH CL5', 'Stage Box A', 'Stage Box B', 'Amp Rack L', 'Amp Rack R', 'Dante Switch', 'Wireless Rx', 'Monitor Desk', 'Playback Mac', 'Drum Sub'];
const MEDIA = ['analog', 'dante', 'speaker', 'aes3', 'video', 'dmx'];
const STATES = ['installed', 'planned', 'spare', '', 'installed', 'retired'];
const ROOMS = ['Main Auditorium', 'Chapel', 'Lobby'];

export function syntheticRows(n) {
  const r = rng(7);
  const out = [];
  for (let i = 0; i < n; i++) {
    const k = i + 1;
    const from = DEVICES[Math.floor(r() * DEVICES.length)];
    let to = DEVICES[Math.floor(r() * DEVICES.length)];
    if (to === from) to = DEVICES[(DEVICES.indexOf(from) + 3) % DEVICES.length];
    out.push({
      id: 'c-' + String(k).padStart(5, '0'),
      tag: 'A-' + k,
      from: from + ' \u00B7 ' + (1 + Math.floor(r() * 48)),
      to: to + ' \u00B7 ' + (1 + Math.floor(r() * 48)),
      medium: MEDIA[Math.floor(r() * MEDIA.length)],
      state: STATES[(i * 7 + Math.floor(i / 3)) % STATES.length],
      length: Math.round((1 + r() * 79) * 2) / 2,
      room: ROOMS[i % ROOMS.length],
      notes: k % 17 === 0 ? 'Drum riser, gaffer "taped"' : k % 5 === 0 ? 'Spare pair, label pending' : '',
    });
  }
  return out;
}

let rows = syntheticRows(N);

const MAIN_COLUMNS = [
  { key: 'tag', header: 'Tag', sticky: true, width: 90 },
  { key: 'from', header: 'From' },
  { key: 'to', header: 'To' },
  { key: 'medium', header: 'Medium', filterable: true, hideOnMobile: true },
  { key: 'state', header: 'State', filterable: true, cell: function (row) {
    return row.state ? h('span', { class: 'pill', text: row.state }) : h('span', { class: 'muted', text: '\u2014' });
  } },
  { key: 'length', header: 'Length', align: 'right', cell: function (row) { return row.length + ' m'; }, csv: function (row) { return String(row.length); } },
  { key: 'room', header: 'Room', filterable: true, hideOnMobile: true },
  { key: 'notes', header: 'Notes', hideOnMobile: true },
];

function hashRoute() {
  const r = parseRoute(location.hash);
  if (!r.view) { r.project = 'dev'; r.room = 'main'; r.view = 'datatable'; }
  return r;
}

const urlBinding = {
  get: function () { return hashRoute().query; },
  set: function (patch) {
    const next = buildRoute(withQuery(hashRoute(), patch));
    history.replaceState(history.state, '', location.pathname + location.search + next);
    note('url ' + JSON.stringify(patch));
  },
};

function setState(field, value) {
  const ids = main.getSelection();
  const set = {};
  ids.forEach(function (id) { set[id] = true; });
  rows = rows.map(function (r) { return set[r.id] ? Object.assign({}, r, { [field]: value }) : r; });
  main.setRows(rows);
  main.clearSelection();
  note('bulk ' + field + '=' + value + ' on ' + ids.length);
}

let dialogCtx = { project: 'dev' };

function fixtureCableRows(doc) {
  const devs = {};
  (doc.devices || []).forEach(function (d) { devs[d.id] = d; });
  return (doc.cables || []).map(function (c) {
    const a = devs[c.from && c.from.device] || {};
    const b = devs[c.to && c.to.device] || {};
    return { id: c.id, tag: c.tag || '', from: (a.name || c.from.device) + ' \u00B7 ' + c.from.port, to: (b.name || c.to.device) + ' \u00B7 ' + c.to.port, medium: c.medium || '' };
  });
}

let fixtureDoc = { devices: [], cables: [] };

function openDrill() {
  const cables = fixtureCableRows(fixtureDoc);
  return openTableDialog(dialogCtx, {
    title: cables.length + ' cables',
    key: 'harness.drill',
    columns: [
      { key: 'id', header: 'Cable' },
      { key: 'from', header: 'From' },
      { key: 'to', header: 'To' },
      { key: 'medium', header: 'Medium', filterable: true },
    ],
    rows: cables,
    onRow: function (row) { note('drill row ' + row.id); },
  }).then(function (picked) { note('drill closed ' + (picked ? picked.id : 'null')); return picked; });
}

const drillBtn = h('button', { type: 'button', id: 'h-drill', onclick: openDrill }, 'Drill-down\u2026');
const loadBtn = h('button', { type: 'button', id: 'h-loading', onclick: function () {
  main.setLoading(true);
  setTimeout(function () { main.setRows(rows); }, 800);
} }, 'Reload');

const t0 = performance.now();
const main = createTable(document.getElementById('h-main-table'), {
  key: 'harness.main',
  scope: params.get('scope') || 'dev',
  caption: 'Synthetic cables',
  columns: MAIN_COLUMNS,
  rows: rows,
  selectable: !readOnly,
  bulkActions: readOnly ? [] : [
    { label: 'Mark planned', run: function () { setState('state', 'planned'); }, noun: { one: 'cable', many: 'cables' } },
    { label: 'Clear state', danger: true, run: function () { setState('state', ''); } },
  ],
  actions: [drillBtn, loadBtn],
  ids: { root: 'h-main', table: 'h-table', search: 'h-search', csv: 'h-csv', columns: 'h-columns', selectAll: 'h-select-all', filters: { state: 'h-state', medium: 'h-medium' } },
  url: urlBinding,
  csvName: 'synthetic-cables.csv',
  cards: params.has('cards'),
  empty: 'No cables yet.',
  onRow: function (row) { note('onRow ' + row.id); },
});
const firstRenderMs = performance.now() - t0;

['dt:state', 'dt:select', 'dt:row'].forEach(function (type) {
  main.root.addEventListener(type, function (e) {
    const d = e.detail || {};
    note(type + ' ' + (type === 'dt:row' ? d.id : type === 'dt:select' ? d.ids.length + ' ids' : JSON.stringify({ q: d.q, sort: d.sort, filters: d.filters, page: d.page })));
  });
});

let ports = null;

function portRows(doc) {
  const out = [];
  (doc.devices || []).forEach(function (d) {
    (d.ports || []).forEach(function (p) {
      out.push({ id: d.id + ':' + p.id, device: d.name || d.id, port: p.name || p.id, label: p.label || '', dir: p.dir || '', medium: p.medium || '', group: p.group || '' });
    });
  });
  return out;
}

function mountPorts(doc) {
  ports = createTable(document.getElementById('h-ports-table'), {
    key: 'harness.ports',
    scope: 'dev',
    caption: 'Fixture ports',
    columns: [
      { key: 'port', header: 'Port' },
      { key: 'label', header: 'Label' },
      { key: 'dir', header: 'Dir', filterable: true },
      { key: 'medium', header: 'Medium', filterable: true },
      { key: 'group', header: 'Group', hideOnMobile: true },
      { key: 'device', header: 'Device', hidden: true },
    ],
    rows: [],
    groupBy: function (r) { return r.device; },
    pageSize: 25,
    density: 'compact',
    empty: 'No ports in the fixture.',
    onRow: function (row) { note('port ' + row.id); },
  });
  ports.setLoading(true);
  ports.setRows(portRows(doc));
}

function smoke() {
  if (!params.has('smoke')) return;
  document.documentElement.setAttribute('data-smoke', JSON.stringify({
    ready: true, errors: errors,
    stats: { rows: rows.length, firstRenderMs: Math.round(firstRenderMs), domRows: document.querySelectorAll('#h-main tbody tr.dt-row').length },
  }));
}

window.__dt = {
  main: main,
  get ports() { return ports; },
  events: events,
  syntheticRows: syntheticRows,
  rows: function () { return rows; },
  openDrill: openDrill,
  firstRenderMs: firstRenderMs,
  time: function (fn) { const s = performance.now(); fn(); return performance.now() - s; },
};

const dialogReady = params.has('appdialog')
  ? import('../js/app.js').then(function (m) { dialogCtx = { project: 'dev', openDialog: m.openDialog }; }, function (e) { note('app.js import failed: ' + e); })
  : Promise.resolve();

const fixtureReady = fetch('fixture-v2.json').then(function (r) {
  if (!r.ok) throw new Error('fixture-v2.json HTTP ' + r.status);
  return r.json();
}).then(function (doc) {
  fixtureDoc = doc;
  mountPorts(doc);
}).catch(function (e) {
  errors.push(String(e));
  mountPorts({ devices: [] });
  if (ports) ports.setError(e, function () { location.reload(); });
});

Promise.all([dialogReady, fixtureReady]).then(function () { setTimeout(smoke, 50); });
