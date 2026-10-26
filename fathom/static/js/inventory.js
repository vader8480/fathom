// Inventory view: the device list as a shared DataTable (docs/ui-audit.md B.3 INV) with
// configurable columns, sort, column filters, quick filters, group by location, bulk
// status/room/location, CSV of the filtered rows, the server export, bulk add, and a
// per-device inventory form (serial, asset tag, location / rack / RU, IP, firmware,
// dates, vendor, cost, status, photos, notes). A row opens the device drawer at the
// inventory section. mount(el, ctx) (§6.4, §6.7).
import {fits, rackUnits} from './rack-core.js';
import {openDuplicatesDialog, openMergeDialog} from './merge-ui.js';
import {h, on} from './dom.js';
import {createTable} from './datatable.js';
import {confirmScope, emptyState} from './feedback.js';
import {bulkAdd} from './wizard.js';

const STATUSES = ['installed', 'planned', 'spare', 'retired'];

export const INV_COLUMNS = [
  ['name', 'Name'], ['room', 'Room'], ['location', 'Location'], ['system', 'System'], ['kind', 'Kind'], ['discipline', 'Discipline'],
  ['manufacturer', 'Manufacturer'], ['model', 'Model'], ['status', 'Status'], ['serial', 'Serial'], ['asset_tag', 'Asset tag'],
  ['firmware', 'Firmware'], ['purchase_date', 'Purchased'], ['warranty_until', 'Warranty until'], ['vendor', 'Vendor'],
  ['cost', 'Cost'], ['currency', 'Currency'], ['po', 'PO'], ['rack', 'Rack'], ['ru', 'RU'], ['ips', 'IPs'], ['notes', 'Notes'], ['id', 'Id'],
];
const DEFAULT_VISIBLE = ['name', 'room', 'location', 'kind', 'model', 'status', 'serial', 'asset_tag', 'warranty_until', 'cost', 'rack', 'ru', 'ips'];
const CSV_KEYS = ['id', 'name', 'room', 'location', 'kind', 'discipline', 'manufacturer', 'model', 'status', 'serial', 'asset_tag', 'firmware',
  'purchase_date', 'warranty_until', 'vendor', 'cost', 'currency', 'po', 'rack', 'ru', 'ips', 'notes'];
const MOBILE_COLUMNS = ['name', 'status', 'room'];
const FILTER_IDS = {room: 'inv-room', status: 'inv-status', location: 'inv-location', kind: 'inv-kind', system: 'inv-system'};
const QUICK = ['warranty', 'serial'];
const NO_LOCATION = 'No location';
const DEVICE_NOUN = {one: 'device', many: 'devices'};

function list(v) { return Array.isArray(v) ? v : []; }

function byId(arr) {
  const m = {};
  list(arr).forEach(function (e) { if (e && e.id != null) m[e.id] = e; });
  return m;
}

function plural(n, noun) { return n + ' ' + (n === 1 ? noun.one : noun.many); }

function disciplineOf(dev, vocab) {
  if (dev.discipline) return dev.discipline;
  const k = vocab && vocab.kinds && vocab.kinds[dev.kind];
  return (k && k.discipline) || 'other';
}

function daysUntil(dateStr, today) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr || '');
  if (!m) return null;
  const t = Date.UTC(+m[1], +m[2] - 1, +m[3]);
  return Math.round((t - today) / 86400000);
}

// One flattened row per device (also the local CSV, FR-INV-04).
export function inventoryRows(doc, vocab) {
  const rooms = byId(doc.rooms);
  const locs = byId(doc.locations);
  const racks = byId(doc.racks);
  const systems = byId(doc.systems);
  const cur = (doc.settings && doc.settings.currency) || 'USD';
  return list(doc.devices).filter(function (d) { return !d.auto; }).map(function (d) {
    const inv = d.inventory || {};
    const rk = d.rack && d.rack.id ? racks[d.rack.id] : null;
    return {
      id: d.id, name: d.name, room: d.room ? (rooms[d.room] ? rooms[d.room].name : d.room) : 'Shared', room_id: d.room || '',
      location: d.location ? (locs[d.location] ? locs[d.location].name : d.location) : '', location_id: d.location || '',
      system: d.system ? (systems[d.system] ? systems[d.system].name : d.system) : '', system_id: d.system || '',
      kind: d.kind, discipline: disciplineOf(d, vocab), manufacturer: d.manufacturer || '', model: d.model || '',
      status: d.status || 'installed', serial: inv.serial || '', asset_tag: inv.asset_tag || '', firmware: inv.firmware || '',
      purchase_date: inv.purchase_date || '', warranty_until: inv.warranty_until || '', vendor: inv.vendor || '',
      cost: inv.cost == null ? '' : inv.cost, currency: inv.cost == null ? '' : (inv.currency || cur), po: inv.po || '',
      rack: d.rack && d.rack.id ? (rk ? rk.name : d.rack.id) : '', rack_id: d.rack && d.rack.id ? d.rack.id : '', ru: d.rack && d.rack.u ? d.rack.u : '',
      ips: list(d.interfaces).map(function (i) { return i.ip; }).filter(Boolean).join(';'), notes: inv.notes || '',
    };
  });
}

function csvString(keys, rows) {
  function q(v) {
    const s = v == null ? '' : String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  return [keys.join(',')].concat(rows.map(function (r) { return keys.map(function (k) { return q(r[k]); }).join(','); })).join('\r\n') + '\r\n';
}

function parseQuick(v) {
  const out = [];
  String(v || '').split('|').forEach(function (k) { if (QUICK.indexOf(k) >= 0 && out.indexOf(k) < 0) out.push(k); });
  return out;
}

function quickString(arr) {
  return QUICK.filter(function (k) { return arr.indexOf(k) >= 0; }).join('|');
}

function cssEsc(s) { return String(s).replace(/["\\]/g, '\\$&'); }

export function invColumns(vocab) {
  const today = Date.now();
  const cols = INV_COLUMNS.map(function (c) {
    const key = c[0];
    const col = {key: key, header: c[1], hidden: DEFAULT_VISIBLE.indexOf(key) < 0, hideOnMobile: MOBILE_COLUMNS.indexOf(key) < 0};
    if (FILTER_IDS[key]) col.filterable = true;
    if (key === 'name') {
      col.sticky = true;
      col.cell = function (r) {
        const d = vocab && vocab.disciplines && vocab.disciplines[r.discipline];
        return h('span', {class: 'inv-name'}, [
          h('span', {class: 'inv-dot', style: {background: (d && d.color) || '#9aa3b5'}, 'aria-hidden': 'true'}), r.name || r.id,
        ]);
      };
    } else if (key === 'status') {
      col.cell = function (r) { return h('span', {class: 'inv-status inv-' + r.status, text: r.status}); };
    } else if (key === 'warranty_until') {
      col.cell = function (r) {
        if (!r.warranty_until) return '';
        const dd = daysUntil(r.warranty_until, today);
        return h('span', {class: dd != null && dd < 90 ? 'inv-warn' : null, text: r.warranty_until + (dd != null && dd < 0 ? ' (expired)' : '')});
      };
    } else if (key === 'cost') {
      col.align = 'right';
      col.cell = function (r) { return r.cost === '' ? '' : Number(r.cost).toFixed(2); };
    } else if (key === 'ru') {
      col.align = 'right';
    }
    return col;
  });
  return cols;
}

export function mount(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || store.vocab || {};
  const S = {scope: 'current', group: false, quick: [], csvAllUrl: '', editing: null, destroyed: false};
  const offs = [];
  let table = null;
  let tableOpts = null;
  let builtReadOnly = null;

  function readOnly() { return !!store.readOnly || ctx.role === 'viewer'; }
  function doc() { return store.doc; }
  function route() { return ctx.route && typeof ctx.route === 'object' ? ctx.route : null; }
  function routed() { const r = route(); return !!r && r.view === 'inventory' && typeof ctx.setParams === 'function'; }
  function query() { const r = route(); return (r && r.query) || {}; }
  function room() {
    if (S.scope === '*') return '*';
    return store.room && store.room !== '*' ? store.room : '*';
  }
  function roomName(id) {
    const r = byId(doc().rooms)[id];
    return r ? r.name : (id || 'shared inventory');
  }
  function scopeName() {
    if (S.scope === '__shared') return 'shared inventory';
    const r = room();
    return r === '*' ? '' : roomName(r);
  }
  function commit(ops, label) {
    if (!ops.length) return;
    if (readOnly()) { ctx.toast('Read-only: changes are not allowed here.', 'warn'); return; }
    ctx.commit(ops, label);
  }

  // ------------------------------------------------------------ chrome

  el.innerHTML = '';
  const root = h('div', {class: 'inv-root'});
  const tableHost = h('div', {class: 'inv-tablehost'});
  const formHost = h('div', {class: 'inv-formhost'});
  root.appendChild(tableHost);
  root.appendChild(formHost);
  el.appendChild(root);

  const scopeSel = h('select', {id: 'inv-scope', class: 'inv-scope', 'aria-label': 'Rooms shown'});
  const qWarranty = h('button', {id: 'inv-q-warranty', type: 'button', class: 'inv-btn inv-chip', 'data-quick': 'warranty', 'aria-pressed': 'false', text: 'Warranty < 90 days'});
  const qSerial = h('button', {id: 'inv-q-serial', type: 'button', class: 'inv-btn inv-chip', 'data-quick': 'serial', 'aria-pressed': 'false', text: 'Missing serial'});
  const groupCb = h('input', {id: 'inv-group', type: 'checkbox'});
  const groupBox = h('span', {class: 'inv-check inv-chip'}, [groupCb, h('label', {for: 'inv-group', text: 'Group by location'})]);
  const bulkAddBtn = h('button', {id: 'inv-bulk-add', type: 'button', class: 'inv-btn inv-primary', text: 'Bulk add\u2026', title: 'Add many devices from pasted spreadsheet rows'});
  const dupsBtn = ctx.api ? h('button', {id: 'inv-dups', type: 'button', class: 'inv-btn', text: 'Duplicates', title: 'Find devices that are probably the same unit'}) : null;
  const csvAll = h('a', {id: 'inv-csv-all', class: 'inv-menu-item', role: 'menuitem', href: '#', text: 'Export all (import format)'});
  const more = h('details', {class: 'inv-more'}, [
    h('summary', {class: 'inv-btn inv-more-btn', 'aria-label': 'More inventory actions', title: 'More'}, [h('span', {'aria-hidden': 'true', text: '\u22EF'})]),
    h('div', {class: 'inv-menu', role: 'menu'}, [csvAll]),
  ]);
  const quickBar = h('div', {class: 'inv-quick', role: 'group', 'aria-label': 'Quick filters'}, [scopeSel, qWarranty, qSerial, groupBox]);

  const bulkStatus = h('select', {id: 'inv-bulk-status', 'aria-label': 'Set status of selected devices'});
  const bulkRoom = h('select', {id: 'inv-bulk-room', 'aria-label': 'Move selected devices to room'});
  const bulkLoc = h('select', {id: 'inv-bulk-location', 'aria-label': 'Set location of selected devices'});
  const markInstalled = h('button', {id: 'inv-mark-installed', type: 'button', class: 'inv-btn', text: 'Mark installed'});
  const mergeSel = h('button', {id: 'inv-merge', type: 'button', class: 'inv-btn', text: 'Merge\u2026', title: 'Merge the selected devices into one', hidden: true});

  function fillSelect(sel, items, current, placeholder) {
    sel.innerHTML = '';
    if (placeholder != null) sel.appendChild(h('option', {value: '', text: placeholder}));
    items.forEach(function (it) { sel.appendChild(h('option', {value: it[0], text: it[1], selected: it[0] === current})); });
    sel.value = current == null ? '' : current;
  }

  function renderControls() {
    const d = doc();
    const curRoom = store.room && store.room !== '*' ? (byId(d.rooms)[store.room] || {}).name || store.room : '';
    fillSelect(scopeSel, [['current', curRoom ? 'Room: ' + curRoom : 'Current room'], ['*', 'All rooms'], ['__shared', 'Shared inventory']], S.scope, null);
    qWarranty.setAttribute('aria-pressed', S.quick.indexOf('warranty') >= 0 ? 'true' : 'false');
    qSerial.setAttribute('aria-pressed', S.quick.indexOf('serial') >= 0 ? 'true' : 'false');
    groupCb.checked = S.group;
    fillSelect(bulkStatus, STATUSES.map(function (s) { return [s, s]; }), '', 'Set status\u2026');
    fillSelect(bulkRoom, [['__shared', 'Shared inventory']].concat(list(d.rooms).map(function (r) { return [r.id, r.name]; })), '', 'Move to room\u2026');
    fillSelect(bulkLoc, [['__none', NO_LOCATION]].concat(list(d.locations).map(function (l) { return [l.id, l.name]; })), '', 'Set location\u2026');
    bulkAddBtn.hidden = readOnly();
    renderCsvAll();
  }

  // ------------------------------------------------------------ rows

  function scopedRows() {
    const r = room();
    return inventoryRows(doc(), vocab).filter(function (row) {
      if (S.scope === '__shared') return row.room_id === '';
      return r === '*' || row.room_id === r;
    }).sort(function (a, b) { return String(a.name).localeCompare(String(b.name), undefined, {numeric: true}); });
  }

  function rows() {
    const today = Date.now();
    return scopedRows().filter(function (row) {
      if (S.quick.indexOf('serial') >= 0 && row.serial) return false;
      if (S.quick.indexOf('warranty') >= 0) {
        const dd = daysUntil(row.warranty_until, today);
        if (dd == null || dd >= 90) return false;
      }
      return true;
    });
  }

  function refreshRows() {
    renderControls();
    if (table) table.setRows(rows());
  }

  function renderCsvAll() {
    if (S.csvAllUrl && typeof URL !== 'undefined' && URL.revokeObjectURL) { URL.revokeObjectURL(S.csvAllUrl); S.csvAllUrl = ''; }
    csvAll.setAttribute('download', (ctx.project || 'project') + '-inventory-all.csv');
    if (ctx.api && ctx.api.scheduleUrl) {
      const r = S.scope === '__shared' ? '' : room();
      csvAll.setAttribute('href', ctx.api.scheduleUrl(ctx.project, 'inventory', {room: r, format: 'csv'}));
      return;
    }
    if (typeof Blob === 'undefined' || typeof URL === 'undefined' || !URL.createObjectURL) return;
    S.csvAllUrl = URL.createObjectURL(new Blob([csvString(CSV_KEYS, scopedRows())], {type: 'text/csv;charset=utf-8'}));
    csvAll.setAttribute('href', S.csvAllUrl);
  }

  function groupLabel(r) { return r.location || NO_LOCATION; }
  function groupOrder(a, b) {
    if (a === NO_LOCATION || b === NO_LOCATION) return a === b ? 0 : (a === NO_LOCATION ? 1 : -1);
    return a.localeCompare(b, undefined, {numeric: true});
  }

  function emptyNode(state, info) {
    if (info && info.total > 0) {
      return h('div', {class: 'inv-empty'}, [
        h('p', {class: 'dt-empty-text', text: 'No devices match these filters.'}),
        h('button', {type: 'button', class: 'dt-clear', onclick: function () { clearFilters(); }}, 'Clear filters'),
      ]);
    }
    const where = scopeName();
    const quick = S.quick.length > 0;
    return emptyState({
      title: quick ? 'No devices match the quick filters.' : (where ? 'No devices in ' + where + '.' : 'No devices yet.'),
      text: quick ? '' : 'Add gear in Patch' + (readOnly() ? '.' : ' or bulk add from a spreadsheet.'),
      action: quick ? {label: 'Clear filters', run: clearFilters} : (readOnly() ? null : {label: 'Bulk add\u2026', run: startBulkAdd}),
    });
  }

  function clearFilters() {
    if (S.quick.length) setQuick([]);
    if (table) table.setState({q: '', filters: {}});
    const s = table && table.root.querySelector('.dt-search');
    if (s) { s.value = ''; s.focus(); }
  }

  // ------------------------------------------------------------ table

  function urlBinding() {
    if (!routed()) return null;
    return {
      get: function () { return query(); },
      set: function (patch) { ctx.setParams(patch, {replace: true}); },
    };
  }

  function build() {
    if (table) table.destroy();
    const ro = readOnly();
    builtReadOnly = ro;
    const q = query();
    tableOpts = {
      key: 'inventory',
      scope: ctx.project || '',
      caption: 'Inventory',
      columns: invColumns(vocab).concat([editCol]),
      rows: [],
      rowAttrs: function (r) { return {'data-device': r.id}; },
      rowClass: function (r) { return r.status === 'planned' ? 'inv-planned' : ''; },
      groupBy: null,
      groupOrder: groupOrder,
      selectable: !ro,
      noun: DEVICE_NOUN,
      bulkActions: ro ? [] : [bulkStatus, bulkRoom, bulkLoc, markInstalled, mergeSel],
      actions: [quickBar, bulkAddBtn, dupsBtn, more].filter(Boolean),
      ids: {table: 'inv-table', columns: 'inv-columns', csv: 'inv-csv', search: 'inv-filter', selectAll: 'inv-select-all', filters: FILTER_IDS},
      url: urlBinding(),
      csvName: (ctx.project || 'project') + '-inventory.csv',
      searchPlaceholder: 'Search devices',
      highlight: q.hl || null,
      empty: emptyNode,
      onRow: function (row) { openRow(row.id); },
    };
    table = createTable(tableHost, tableOpts);
    table.root.addEventListener('dt:select', onSelect);
    const extra = table.getState().extra || {};
    if (extra.scope === '*' || extra.scope === '__shared' || extra.scope === 'current') S.scope = extra.scope;
    S.group = !!extra.group;
    tableOpts.groupBy = S.group ? groupLabel : null;
    refreshRows();
    onSelect();
  }

  function setExtra() {
    tableOpts.groupBy = S.group ? groupLabel : null;
    table.setState({extra: {scope: S.scope, group: S.group}});
    table.refresh();
  }

  function setQuick(next) {
    S.quick = next;
    if (routed()) ctx.setParams({quick: quickString(next) || null}, {replace: true});
    refreshRows();
  }

  function onSelect() {
    const n = table ? table.getSelection().length : 0;
    mergeSel.hidden = n < 2 || readOnly() || !ctx.api;
  }

  function openRow(id) {
    const sel = {type: 'device', id: id};
    if (typeof ctx.openDrawer === 'function') ctx.openDrawer(sel, {section: 'inventory'});
    else if (typeof ctx.openInspector === 'function') ctx.openInspector(sel);
    else ctx.select(sel);
    openSection('inventory');
  }

  // Opens the drawer's inventory <details> and scrolls it into view once the inspector
  // has rendered it, for inspectors without focusSection.
  function openSection(sec) {
    let tries = 0;
    (function tick() {
      if (S.destroyed) return;
      const d = document.querySelector('#app-inspector details[data-section="' + sec + '"]');
      if (d) {
        if (!d.open) d.open = true;
        if (d.scrollIntoView) d.scrollIntoView({block: 'start'});
        return;
      }
      tries += 1;
      if (tries < 40) setTimeout(tick, 100);
    })();
  }

  // ------------------------------------------------------------ bulk

  function selectedIds() { return table ? table.getSelection() : []; }

  function bulkApply(field, value) {
    const ids = selectedIds();
    if (!ids.length || value === '') return Promise.resolve(false);
    const d = doc();
    const devs = byId(d.devices);
    let ops = [];
    let label = '';
    let verb = '';
    let detail = '';
    if (field === 'status') {
      ops = ids.filter(function (id) { return devs[id] && (devs[id].status || 'installed') !== value; })
        .map(function (id) { return {op: 'merge', coll: 'devices', id: id, value: {status: value === 'installed' ? null : value}}; });
      label = 'Set ' + plural(ops.length, DEVICE_NOUN) + ' to ' + value;
      verb = 'Set status of';
      detail = 'New status: ' + value + '.';
    } else if (field === 'room') {
      const r = value === '__shared' ? '' : value;
      ops = ids.filter(function (id) { return devs[id] && (devs[id].room || '') !== r; })
        .map(function (id) { return {op: 'merge', coll: 'devices', id: id, value: {room: r}}; });
      const rn = r ? roomName(r) : 'shared inventory';
      label = 'Moved ' + plural(ops.length, DEVICE_NOUN) + ' to ' + rn;
      verb = 'Move';
      detail = 'They move to ' + rn + '.';
    } else if (field === 'location') {
      const l = value === '__none' ? null : value;
      ops = ids.filter(function (id) { return devs[id] && (devs[id].location || null) !== l; })
        .map(function (id) { return {op: 'merge', coll: 'devices', id: id, value: {location: l}}; });
      label = 'Set location of ' + plural(ops.length, DEVICE_NOUN);
      verb = 'Set location of';
      detail = 'New location: ' + (l ? (byId(d.locations)[l] || {}).name || l : NO_LOCATION) + '.';
    }
    if (!ops.length) { ctx.toast('Nothing to change.', 'info'); return Promise.resolve(false); }
    return confirmBulk(ids.length, verb, ops.length, detail).then(function (ok) {
      if (ok) commit(ops, label);
      return ok;
    });
  }

  function confirmBulk(selected, verb, count, detail) {
    if (selected <= 1) return Promise.resolve(true);
    return confirmScope(ctx, {verb: verb, count: count, noun: DEVICE_NOUN, scope: scopeName(), detail: detail});
  }

  function markAllInstalled() {
    const devs = byId(doc().devices);
    const sel = selectedIds();
    const ids = sel.filter(function (id) { return devs[id] && devs[id].status === 'planned'; });
    if (!ids.length) { ctx.toast('No planned devices selected.', 'info'); return; }
    confirmBulk(sel.length, 'Mark installed:', ids.length, 'Only planned devices change.').then(function (ok) {
      if (!ok) return;
      commit(ids.map(function (id) { return {op: 'merge', coll: 'devices', id: id, value: {status: 'installed'}}; }),
        'Marked ' + plural(ids.length, DEVICE_NOUN) + ' installed');
    });
  }

  function startBulkAdd() {
    if (readOnly()) return;
    bulkAdd(ctx, {kind: 'devices', room: S.scope === '__shared' ? '' : store.room});
  }

  // ------------------------------------------------------------ form
  function openForm(id, opener) {
    const d = doc();
    const dev = byId(d.devices)[id];
    if (!dev) return;
    S.editing = id;
    const ro = readOnly();
    const inv = dev.inventory || {};
    const iface = list(dev.interfaces).filter(function (i) { return i.id === 'primary'; })[0] || list(dev.interfaces)[0] || null;
    const form = h('form', {class: 'inv-form', 'aria-labelledby': 'inv-form-title'});
    function field(key, label, input, help) {
      input.id = 'inv-f-' + key;
      input.setAttribute('data-field', key);
      if (ro) input.disabled = true;
      return h('div', {class: 'inv-field'}, [h('label', {for: input.id, text: label}), input, help ? h('span', {class: 'inv-hint', id: input.id + '-help', text: help}) : null]);
    }
    function text(v, attrs) { return h('input', Object.assign({type: 'text', value: v == null ? '' : String(v)}, attrs || {})); }
    function sel(items, cur) { return h('select', null, items.map(function (it) { return h('option', {value: it[0], text: it[1], selected: it[0] === (cur == null ? '' : cur)}); })); }
    const roomItems = [['', 'Shared inventory']].concat(list(d.rooms).map(function (r) { return [r.id, r.name]; }));
    const locItems = [['', '\u2014']].concat(list(d.locations).map(function (l) { return [l.id, l.name]; }));
    const rackItems = [['', 'Not racked']].concat(list(d.racks).map(function (r) { return [r.id, r.name + ' (' + rackUnits(r) + 'U)']; }));
    const r = dev.rack || {};
    form.appendChild(h('h3', {id: 'inv-form-title', text: (ro ? '' : 'Edit ') + dev.name}));
    form.appendChild(h('p', {class: 'inv-hint', text: ((dev.manufacturer || '') + ' ' + (dev.model || '')).trim() || dev.kind}));
    const grid = h('div', {class: 'inv-grid'});
    grid.appendChild(field('status', 'Status', sel(STATUSES.map(function (s) { return [s, s]; }), dev.status || 'installed')));
    grid.appendChild(field('room', 'Room', sel(roomItems, dev.room || '')));
    grid.appendChild(field('location', 'Location', sel(locItems, dev.location || '')));
    grid.appendChild(field('serial', 'Serial', text(inv.serial)));
    grid.appendChild(field('asset_tag', 'Asset tag', text(inv.asset_tag)));
    grid.appendChild(field('firmware', 'Firmware', text(inv.firmware)));
    grid.appendChild(field('purchase_date', 'Purchase date', h('input', {type: 'date', value: inv.purchase_date || ''})));
    grid.appendChild(field('warranty_until', 'Warranty until', h('input', {type: 'date', value: inv.warranty_until || ''})));
    grid.appendChild(field('vendor', 'Vendor', text(inv.vendor)));
    grid.appendChild(field('cost', 'Cost', text(inv.cost, {inputmode: 'decimal'})));
    grid.appendChild(field('currency', 'Currency', text(inv.currency || '', {placeholder: (d.settings && d.settings.currency) || 'USD', maxlength: '3'})));
    grid.appendChild(field('po', 'PO', text(inv.po)));
    grid.appendChild(field('rack', 'Rack', sel(rackItems, r.id || '')));
    grid.appendChild(field('ru', 'RU (lowest)', text(r.u || '', {inputmode: 'numeric'})));
    grid.appendChild(field('face', 'Face', sel([['front', 'front'], ['rear', 'rear']], r.face || 'front')));
    grid.appendChild(field('ip', 'IP (' + (iface ? iface.id : 'primary') + ')', text(iface ? iface.ip : '', {inputmode: 'decimal'})));
    form.appendChild(grid);
    form.appendChild(field('notes', 'Notes', h('textarea', {rows: '3'}, [inv.notes || ''])));
    const err = h('p', {class: 'inv-error', id: 'inv-form-error', role: 'alert'});
    form.appendChild(err);
    // photos / documents
    const atts = list(d.attachments).filter(function (a) { return a.device === id; });
    const photos = h('div', {class: 'inv-photos'});
    photos.appendChild(h('h4', {text: 'Photos & documents'}));
    const ul = h('ul', {class: 'inv-attlist'});
    atts.forEach(function (a) {
      const url = ctx.api && ctx.api.fileUrl ? ctx.api.fileUrl(ctx.project, a) : a.file;
      ul.appendChild(h('li', null, [h('a', {href: url, target: '_blank', rel: 'noopener', text: a.name}), h('span', {class: 'inv-hint', text: ' ' + (a.kind || '')})]));
    });
    if (!atts.length) ul.appendChild(h('li', {class: 'inv-hint', text: 'None yet.'}));
    photos.appendChild(ul);
    if (!ro) {
      if (ctx.api && ctx.api.upload) {
        photos.appendChild(h('div', {class: 'inv-uploadrow'}, [
          h('input', {type: 'file', id: 'inv-f-photo', class: 'inv-file', accept: 'image/*,application/pdf', multiple: true, 'data-upload': 'file'}),
          h('label', {for: 'inv-f-photo', class: 'inv-btn', text: 'Add photo or PDF\u2026'}),
          h('input', {type: 'file', id: 'inv-f-camera', class: 'inv-file', accept: 'image/*', capture: 'environment', 'data-upload': 'camera'}),
          h('label', {for: 'inv-f-camera', class: 'inv-btn', text: 'Take photo'}),
        ]));
      } else {
        photos.appendChild(h('p', {class: 'inv-hint', text: 'Uploading photos needs the server.'}));
      }
    }
    form.appendChild(photos);
    form.appendChild(h('div', {class: 'inv-formrow'}, [
      ro ? null : h('button', {type: 'submit', class: 'inv-btn inv-primary', text: 'Save'}),
      h('button', {type: 'button', class: 'inv-btn', 'data-act': 'close', text: ro ? 'Close' : 'Cancel'}),
    ]));

    formHost.innerHTML = '';
    let dlg = null;
    const useDialog = typeof HTMLDialogElement !== 'undefined' && typeof document.createElement('dialog').showModal === 'function';
    if (useDialog) {
      dlg = h('dialog', {class: 'inv-dialog', 'aria-labelledby': 'inv-form-title'}, [form]);
      formHost.appendChild(dlg);
      dlg.addEventListener('close', function () { finish(); });
      dlg.addEventListener('cancel', function () { /* Esc closes */ });
      dlg.showModal();
    } else {
      formHost.appendChild(h('div', {class: 'inv-panel', role: 'dialog', 'aria-labelledby': 'inv-form-title'}, [form]));
      form.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    }
    const first = form.querySelector('select,input,textarea');
    if (first) first.focus();

    function finish() {
      formHost.innerHTML = '';
      S.editing = null;
      if (opener && opener.isConnected) opener.focus();
      else {
        const b = tableHost.querySelector('.inv-edit[data-device="' + cssEsc(id) + '"]');
        if (b) b.focus();
      }
    }
    function close() { if (dlg && dlg.open) dlg.close(); else finish(); }

    form.addEventListener('click', function (e) { if (e.target.closest('[data-act="close"]')) close(); });
    form.addEventListener('change', function (e) {
      const up = e.target.closest('[data-upload]');
      if (!up || !up.files || !up.files.length) return;
      const files = Array.prototype.slice.call(up.files);
      up.value = '';
      err.textContent = 'Uploading\u2026';
      Promise.resolve(ctx.api.upload(ctx.project, 'files', files, {device: id, kind: 'photo'})).then(function (res) {
        const added = list(res && res.attachments);
        if (added.length && store.applyRemote) {
          store.applyRemote(added.filter(function (a) { return !byId(doc().attachments)[a.id]; }).map(function (a) {
            return {op: 'put', coll: 'attachments', id: a.id, value: a};
          }), 'remote');
        }
        if (res && res.revision && store.setRevision && !(store.revision >= res.revision)) store.setRevision(res.revision);
        err.textContent = '';
        ctx.toast('Uploaded ' + added.length + ' file' + (added.length === 1 ? '' : 's'), 'ok');
        close();
        openForm(id, opener);
      }, function (er) { err.textContent = (er && er.message) || 'Upload failed.'; });
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      const v = function (k) { const n = form.querySelector('[data-field="' + k + '"]'); return n ? String(n.value).trim() : ''; };
      const fresh = byId(doc().devices)[id];
      if (!fresh) { close(); return; }
      const value = {};
      const invPatch = {};
      let changed = false;
      ['serial', 'asset_tag', 'firmware', 'purchase_date', 'warranty_until', 'vendor', 'po', 'notes', 'currency'].forEach(function (k) {
        const nv = k === 'currency' ? v(k).toUpperCase() : v(k);
        const ov = (fresh.inventory || {})[k] || '';
        if (nv !== ov) { invPatch[k] = nv === '' ? null : nv; changed = true; }
      });
      const costTxt = v('cost').replace(',', '.');
      const oldCost = fresh.inventory && fresh.inventory.cost != null ? fresh.inventory.cost : null;
      if (costTxt === '') { if (oldCost != null) { invPatch.cost = null; changed = true; } }
      else {
        const c = parseFloat(costTxt);
        if (!(c >= 0)) { err.textContent = 'Cost must be a number.'; form.querySelector('[data-field="cost"]').setAttribute('aria-describedby', 'inv-form-error'); return; }
        if (c !== oldCost) { invPatch.cost = c; changed = true; }
      }
      if (Object.keys(invPatch).length) value.inventory = invPatch;
      const st = v('status');
      if (st !== (fresh.status || 'installed')) { value.status = st; changed = true; }
      if (v('room') !== (fresh.room || '')) { value.room = v('room'); changed = true; }
      if (v('location') !== (fresh.location || '')) { value.location = v('location') || null; changed = true; }
      const rk = v('rack');
      const fr = fresh.rack || {};
      if (!rk) { if (fr.id) { value.rack = null; changed = true; } }
      else {
        const u = parseInt(v('ru'), 10);
        if (!(u >= 1)) { err.textContent = 'Enter the lowest RU (1 = bottom) for the rack position.'; form.querySelector('[data-field="ru"]').setAttribute('aria-describedby', 'inv-form-error'); return; }
        const face = v('face') || 'front';
        if (rk !== fr.id || u !== fr.u || face !== (fr.face || 'front')) {
          const f = fits(doc(), rk, id, u, {face: face});
          if (!f.ok && f.reason === 'out_of_range') { err.textContent = 'That RU is outside the rack.'; return; }
          if (!f.ok) ctx.toast('Rack position overlaps ' + f.conflicts.join(', ') + ' (collision warning).', 'warn');
          value.rack = {id: rk, u: u, face: face};
          if (!fr.height) value.rack.height = 1;
          changed = true;
        }
      }
      const ip = v('ip');
      const oldIp = iface ? (iface.ip || '') : '';
      if (ip !== oldIp) {
        if (ip && !/^(\d{1,3}\.){3}\d{1,3}$|:/.test(ip)) { err.textContent = 'IP does not look like an IPv4 or IPv6 address.'; return; }
        const ifs = list(fresh.interfaces).map(function (i) { return Object.assign({}, i); });
        const it = iface ? ifs.filter(function (i) { return i.id === iface.id; })[0] : null;
        if (it) { if (ip) it.ip = ip; else delete it.ip; }
        else if (ip) ifs.push({id: 'primary', role: 'primary', ip: ip});
        value.interfaces = ifs;
        changed = true;
      }
      if (changed) commit([{op: 'merge', coll: 'devices', id: id, value: value}], 'Edited inventory of ' + fresh.name);
      close();
    });
  }

  // Row action column: appended after the data columns so it stays last and visible at sm.
  const editCol = {
    key: 'edit', header: 'Edit', sortable: false, searchable: false, csv: false, filterable: false,
    value: function () { return ''; },
    cell: function (r) {
      return h('button', {type: 'button', class: 'inv-btn inv-edit', 'data-device': r.id, 'aria-label': (readOnly() ? 'View' : 'Edit') + ' inventory for ' + r.name, text: readOnly() ? 'View' : 'Edit'});
    },
  };
  // ------------------------------------------------------------ events
  offs.push(on(scopeSel, 'change', function () { S.scope = scopeSel.value || 'current'; setExtra(); refreshRows(); scopeSel.focus(); }));
  offs.push(on(qWarranty, 'click', function () { toggleQuick('warranty'); qWarranty.focus(); }));
  offs.push(on(qSerial, 'click', function () { toggleQuick('serial'); qSerial.focus(); }));
  offs.push(on(groupCb, 'change', function () { S.group = groupCb.checked; setExtra(); groupCb.focus(); }));
  offs.push(on(bulkAddBtn, 'click', startBulkAdd));
  if (dupsBtn) offs.push(on(dupsBtn, 'click', function () { openDuplicatesDialog(ctx); }));
  offs.push(on(csvAll, 'click', function () { more.open = false; }));
  offs.push(on(more, 'keydown', function (e) {
    if (e.key === 'Escape' && more.open) { e.preventDefault(); e.stopPropagation(); more.open = false; more.querySelector('summary').focus(); }
  }));
  offs.push(on(document, 'pointerdown', function (e) { if (more.open && !more.contains(e.target)) more.open = false; }, true));
  [[bulkStatus, 'status'], [bulkRoom, 'room'], [bulkLoc, 'location']].forEach(function (b) {
    offs.push(on(b[0], 'change', function () {
      const v = b[0].value;
      bulkApply(b[1], v).then(function () { b[0].value = ''; });
    }));
  });
  offs.push(on(markInstalled, 'click', markAllInstalled));
  offs.push(on(mergeSel, 'click', function () {
    const ids = selectedIds();
    if (ids.length > 21) { ctx.toast('Merge at most 21 devices at a time.', 'warn'); return; }
    openMergeDialog(ctx, ids).then(function (done) { if (done && table) table.clearSelection(); });
  }));
  offs.push(on(tableHost, 'click', function (e) {
    const ed = e.target.closest('.inv-edit[data-device]');
    if (ed) openForm(ed.getAttribute('data-device'), ed);
  }));

  function toggleQuick(k) {
    const next = S.quick.slice();
    const i = next.indexOf(k);
    if (i >= 0) next.splice(i, 1); else next.push(k);
    setQuick(next);
  }

  function onDoc() { refreshRows(); }
  function onMode() { if (readOnly() !== builtReadOnly) build(); else refreshRows(); }
  store.addEventListener('doc', onDoc);
  store.addEventListener('room', onDoc);
  store.addEventListener('mode', onMode);
  offs.push(function () {
    store.removeEventListener('doc', onDoc);
    store.removeEventListener('room', onDoc);
    store.removeEventListener('mode', onMode);
  });

  S.quick = parseQuick(query().quick);
  build();
  const q0 = query();
  if (q0.sec === 'inventory' && /^device:/.test(q0.sel || '')) openSection('inventory');

  return {
    destroy: function () {
      S.destroyed = true;
      offs.forEach(function (f) { f(); });
      if (table) { table.root.removeEventListener('dt:select', onSelect); table.destroy(); table = null; }
      if (S.csvAllUrl && typeof URL !== 'undefined' && URL.revokeObjectURL) URL.revokeObjectURL(S.csvAllUrl);
      el.innerHTML = '';
    },
    route: function (r) {
      if (!table || !r || r.view !== 'inventory') return;
      const qq = r.query || {};
      table.readUrl();
      const nq = parseQuick(qq.quick);
      if (quickString(nq) !== quickString(S.quick)) { S.quick = nq; refreshRows(); }
      table.setHighlight(qq.hl || null);
    },
    focus: function (sel) {
      const id = sel && (sel.device || sel.id);
      if (!id || !table) return;
      const row = tableHost.querySelector('tr[data-device="' + cssEsc(id) + '"]');
      if (row && row.scrollIntoView) row.scrollIntoView({block: 'center'});
    },
    getState: function () { return {room: S.scope, group: S.group}; },
    setState: function (s) {
      if (!s || !table) return;
      if (s.room === 'current' || s.room === '*' || s.room === '__shared') S.scope = s.room;
      S.group = !!s.group;
      setExtra();
      refreshRows();
    },
    _state: S,
    _table: function () { return table; },
    _openForm: openForm,
  };
}
