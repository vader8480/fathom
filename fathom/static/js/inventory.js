// Inventory view: device table with configurable columns, sort, filters,
// quick filters, bulk status/room/location, CSV, and a per-device inventory
// form (serial, asset tag, location / rack / RU, IP, firmware, dates, vendor,
// cost, status, photos, notes). mount(el, ctx) (§6.4, §6.7).
import {fits, rackUnits} from './rack-core.js';

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

function list(v) { return Array.isArray(v) ? v : []; }

function byId(arr) {
  const m = {};
  list(arr).forEach(function (e) { if (e && e.id != null) m[e.id] = e; });
  return m;
}

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

function h(tag, attrs, children) {
  const n = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v == null || v === false) return;
      if (k === 'text') n.textContent = v;
      else if (k === 'class') n.className = v;
      else if (k === 'style') n.setAttribute('style', v);
      else n.setAttribute(k, v === true ? '' : v);
    });
  }
  (children || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
  return n;
}

export function mount(el, ctx) {
  const store = ctx.store;
  const vocab = ctx.vocab || store.vocab || {};
  const S = {room: 'current', status: '', location: '', kind: '', system: '', text: '', qWarranty: false, qSerial: false, group: false,
    visible: DEFAULT_VISIBLE.slice(), sort: {key: 'name', dir: 1}, selected: {}, editing: null, csvUrl: ''};
  const listeners = [];
  function on(target, type, fn, opts) {
    target.addEventListener(type, fn, opts);
    listeners.push([target, type, fn, opts]);
  }

  el.innerHTML = '';
  const root = h('div', {class: 'inv-root'});
  const roomSel = h('select', {id: 'inv-room', 'aria-label': 'Room filter'});
  const statusSel = h('select', {id: 'inv-status', 'aria-label': 'Status filter'});
  const locSel = h('select', {id: 'inv-location', 'aria-label': 'Location filter'});
  const kindSel = h('select', {id: 'inv-kind', 'aria-label': 'Kind filter'});
  const sysSel = h('select', {id: 'inv-system', 'aria-label': 'System filter'});
  const textIn = h('input', {id: 'inv-filter', type: 'search', placeholder: 'Search devices', 'aria-label': 'Search devices'});
  const qWarranty = h('button', {id: 'inv-q-warranty', type: 'button', class: 'inv-btn', 'aria-pressed': 'false', text: 'Warranty < 90 days'});
  const qSerial = h('button', {id: 'inv-q-serial', type: 'button', class: 'inv-btn', 'aria-pressed': 'false', text: 'Missing serial'});
  const groupCb = h('input', {id: 'inv-group', type: 'checkbox'});
  const colsBox = h('details', {id: 'inv-columns', class: 'inv-columns'});
  const csv = h('a', {id: 'inv-csv', class: 'inv-btn', role: 'button', text: 'CSV'});
  const filters = h('div', {class: 'inv-toolbar'}, [roomSel, statusSel, locSel, kindSel, sysSel, textIn, qWarranty, qSerial,
    h('span', {class: 'inv-check'}, [groupCb, h('label', {for: 'inv-group', text: 'Group by location'})]), colsBox, csv]);
  const selCount = h('span', {class: 'inv-selcount', role: 'status'});
  const bulkStatus = h('select', {id: 'inv-bulk-status', 'aria-label': 'Set status of selected devices'});
  const bulkRoom = h('select', {id: 'inv-bulk-room', 'aria-label': 'Move selected devices to room'});
  const bulkLoc = h('select', {id: 'inv-bulk-location', 'aria-label': 'Set location of selected devices'});
  const markInstalled = h('button', {id: 'inv-mark-installed', type: 'button', class: 'inv-btn', text: 'Mark installed'});
  const clearSel = h('button', {type: 'button', class: 'inv-btn', text: 'Clear selection'});
  const bulk = h('div', {class: 'inv-bulk', role: 'group', 'aria-label': 'Bulk actions'}, [selCount, bulkStatus, bulkRoom, bulkLoc, markInstalled, clearSel]);
  const tableWrap = h('div', {class: 'inv-scroll'});
  const formHost = h('div', {class: 'inv-formhost'});
  root.appendChild(filters);
  root.appendChild(bulk);
  root.appendChild(tableWrap);
  root.appendChild(formHost);
  el.appendChild(root);

  function doc() { return store.doc; }
  function readOnly() { return !!store.readOnly; }
  function room() {
    if (S.room === '*') return '*';
    return store.room && store.room !== '*' ? store.room : '*';
  }
  function commit(ops, label) {
    if (!ops.length) return;
    if (readOnly()) { ctx.toast('Read-only: changes are not allowed here.', 'warn'); return; }
    ctx.commit(ops, label);
  }

  function fillSelect(sel, items, current, placeholder) {
    sel.innerHTML = '';
    if (placeholder != null) sel.appendChild(h('option', {value: '', text: placeholder}));
    items.forEach(function (it) { sel.appendChild(h('option', {value: it[0], text: it[1], selected: it[0] === current})); });
  }

  function renderFilters() {
    const d = doc();
    const curRoom = store.room && store.room !== '*' ? (byId(d.rooms)[store.room] || {}).name || store.room : '';
    fillSelect(roomSel, [['current', curRoom ? 'Room: ' + curRoom : 'Current room'], ['*', 'All rooms'], ['__shared', 'Shared inventory']], S.room, null);
    fillSelect(statusSel, STATUSES.map(function (s) { return [s, s]; }), S.status, 'Any status');
    fillSelect(locSel, list(d.locations).map(function (l) { return [l.id, l.name]; }).concat([['__none', 'No location']]), S.location, 'Any location');
    const kinds = {};
    list(d.devices).forEach(function (x) { kinds[x.kind] = true; });
    fillSelect(kindSel, Object.keys(kinds).sort().map(function (k) { return [k, (vocab.kinds && vocab.kinds[k] && vocab.kinds[k].label) || k]; }), S.kind, 'Any kind');
    fillSelect(sysSel, list(d.systems).map(function (s) { return [s.id, s.name]; }), S.system, 'Any system');
    qWarranty.setAttribute('aria-pressed', S.qWarranty ? 'true' : 'false');
    qSerial.setAttribute('aria-pressed', S.qSerial ? 'true' : 'false');
    groupCb.checked = S.group;
    colsBox.innerHTML = '';
    colsBox.appendChild(h('summary', {text: 'Columns'}));
    const box = h('div', {class: 'inv-colslist', role: 'group', 'aria-label': 'Visible columns'});
    INV_COLUMNS.forEach(function (c) {
      const id = 'inv-col-' + c[0];
      box.appendChild(h('div', {class: 'inv-check'}, [h('input', {type: 'checkbox', id: id, 'data-col': c[0], checked: S.visible.indexOf(c[0]) >= 0, disabled: c[0] === 'name'}),
        h('label', {for: id, text: c[1]})]));
    });
    colsBox.appendChild(box);
    const ro = readOnly();
    fillSelect(bulkStatus, STATUSES.map(function (s) { return [s, s]; }), '', 'Set status\u2026');
    fillSelect(bulkRoom, [['__shared', 'Shared inventory']].concat(list(d.rooms).map(function (r) { return [r.id, r.name]; })), '', 'Move to room\u2026');
    fillSelect(bulkLoc, [['__none', 'No location']].concat(list(d.locations).map(function (l) { return [l.id, l.name]; })), '', 'Set location\u2026');
    [bulkStatus, bulkRoom, bulkLoc, markInstalled].forEach(function (b) { b.disabled = ro; });
  }

  function filtered() {
    const today = Date.now();
    const t = S.text.trim().toLowerCase();
    const r = room();
    return inventoryRows(doc(), vocab).filter(function (row) {
      if (S.room === '__shared') { if (row.room_id !== '') return false; }
      else if (r !== '*' && row.room_id !== r) return false;
      if (S.status && row.status !== S.status) return false;
      if (S.location === '__none' ? row.location_id : (S.location && row.location_id !== S.location)) return false;
      if (S.kind && row.kind !== S.kind) return false;
      if (S.system && row.system_id !== S.system) return false;
      if (S.qSerial && row.serial) return false;
      if (S.qWarranty) {
        const dd = daysUntil(row.warranty_until, today);
        if (dd == null || dd >= 90) return false;
      }
      if (t) {
        const hay = [row.name, row.id, row.manufacturer, row.model, row.serial, row.asset_tag, row.vendor, row.ips, row.notes, row.location].join(' ').toLowerCase();
        if (hay.indexOf(t) < 0) return false;
      }
      return true;
    }).sort(function (a, b) {
      const k = S.sort.key;
      const x = a[k];
      const y = b[k];
      const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), undefined, {numeric: true});
      return c * S.sort.dir;
    });
  }

  function render() {
    renderFilters();
    const rows = filtered();
    const visibleIds = {};
    rows.forEach(function (r) { visibleIds[r.id] = true; });
    Object.keys(S.selected).forEach(function (id) { if (!visibleIds[id]) delete S.selected[id]; });
    const nSel = Object.keys(S.selected).length;
    selCount.textContent = nSel ? nSel + ' selected' : rows.length + ' device' + (rows.length === 1 ? '' : 's');
    bulk.classList.toggle('inv-has-sel', nSel > 0);
    [bulkStatus, bulkRoom, bulkLoc, markInstalled, clearSel].forEach(function (b) { b.hidden = !nSel; });
    const columns = INV_COLUMNS.filter(function (c) { return S.visible.indexOf(c[0]) >= 0; });
    const table = h('table', {id: 'inv-table', class: 'inv-table'});
    table.appendChild(h('caption', {class: 'inv-sr', text: 'Inventory'}));
    const allCb = h('input', {type: 'checkbox', id: 'inv-select-all', 'aria-label': 'Select all shown devices', checked: rows.length > 0 && nSel === rows.length});
    const trh = h('tr', null, [h('th', {scope: 'col', class: 'inv-cbcol'}, [allCb])]);
    columns.forEach(function (c) {
      const sorted = S.sort.key === c[0];
      trh.appendChild(h('th', {scope: 'col', 'aria-sort': sorted ? (S.sort.dir > 0 ? 'ascending' : 'descending') : 'none'}, [
        h('button', {type: 'button', class: 'inv-sort', 'data-sort': c[0], text: c[1] + (sorted ? (S.sort.dir > 0 ? ' \u25b2' : ' \u25bc') : '')}),
      ]));
    });
    trh.appendChild(h('th', {scope: 'col', class: 'inv-actcol', text: 'Edit'}));
    table.appendChild(h('thead', null, [trh]));
    const today = Date.now();
    function rowEl(r) {
      const cells = [h('td', {class: 'inv-cbcol'}, [h('input', {type: 'checkbox', 'data-select': r.id, 'aria-label': 'Select ' + r.name, checked: !!S.selected[r.id]})])];
      columns.forEach(function (c) {
        const v = r[c[0]];
        if (c[0] === 'status') {
          cells.push(h('td', null, [h('span', {class: 'inv-status inv-' + v, text: v})]));
        } else if (c[0] === 'name') {
          const color = (vocab.disciplines && vocab.disciplines[r.discipline] && vocab.disciplines[r.discipline].color) || '#9aa3b5';
          cells.push(h('th', {scope: 'row', class: 'inv-name'}, [h('span', {class: 'inv-dot', style: 'background:' + color, 'aria-hidden': 'true'}), r.name]));
        } else if (c[0] === 'warranty_until' && v) {
          const dd = daysUntil(v, today);
          cells.push(h('td', {class: dd != null && dd < 90 ? 'inv-warn' : null, text: v + (dd != null && dd < 0 ? ' (expired)' : '')}));
        } else if (c[0] === 'cost' && v !== '') {
          cells.push(h('td', {class: 'inv-num', text: Number(v).toFixed(2)}));
        } else {
          cells.push(h('td', {text: v == null ? '' : String(v)}));
        }
      });
      cells.push(h('td', {class: 'inv-actcol'}, [h('button', {type: 'button', class: 'inv-btn', 'data-edit': r.id, 'aria-label': 'Edit inventory for ' + r.name, text: readOnly() ? 'View' : 'Edit'})]));
      return h('tr', {'data-device': r.id, class: (S.selected[r.id] ? 'inv-selected' : '') + (r.status === 'planned' ? ' inv-planned' : '')}, cells);
    }
    if (S.group) {
      const groups = {};
      const order = [];
      rows.forEach(function (r) {
        const k = r.location || 'No location';
        if (!groups[k]) { groups[k] = []; order.push(k); }
        groups[k].push(r);
      });
      order.sort(function (a, b) { return a === 'No location' ? 1 : b === 'No location' ? -1 : a.localeCompare(b); });
      order.forEach(function (k) {
        const tb = h('tbody', {class: 'inv-group'});
        tb.appendChild(h('tr', {class: 'inv-grouphead'}, [h('th', {scope: 'rowgroup', colspan: String(columns.length + 2), text: k + ' (' + groups[k].length + ')'})]));
        groups[k].forEach(function (r) { tb.appendChild(rowEl(r)); });
        table.appendChild(tb);
      });
    } else {
      const tb = h('tbody');
      rows.forEach(function (r) { tb.appendChild(rowEl(r)); });
      table.appendChild(tb);
    }
    if (!rows.length) table.appendChild(h('tbody', null, [h('tr', null, [h('td', {colspan: String(columns.length + 2), class: 'inv-hint', text: 'No devices match these filters.'})])]));
    tableWrap.innerHTML = '';
    tableWrap.appendChild(table);
    renderCsv(rows);
  }

  function renderCsv(rows) {
    if (S.csvUrl && typeof URL !== 'undefined' && URL.revokeObjectURL) { URL.revokeObjectURL(S.csvUrl); S.csvUrl = ''; }
    csv.setAttribute('download', (ctx.project || 'project') + '-inventory.csv');
    if (ctx.api && ctx.api.scheduleUrl) {
      const r = S.room === '__shared' ? '' : room();
      csv.setAttribute('href', ctx.api.scheduleUrl(ctx.project, 'inventory', {room: r, format: 'csv'}));
      return;
    }
    if (typeof Blob === 'undefined') return;
    S.csvUrl = URL.createObjectURL(new Blob([csvString(CSV_KEYS, rows)], {type: 'text/csv;charset=utf-8'}));
    csv.setAttribute('href', S.csvUrl);
  }

  // --------------------------------------------------------------- bulk
  function selectedIds() { return Object.keys(S.selected); }

  function bulkApply(field, value) {
    const ids = selectedIds();
    if (!ids.length || value === '') return;
    const d = doc();
    const devs = byId(d.devices);
    let ops = [];
    let label = '';
    if (field === 'status') {
      ops = ids.filter(function (id) { return devs[id] && (devs[id].status || 'installed') !== value; })
        .map(function (id) { return {op: 'merge', coll: 'devices', id: id, value: {status: value === 'installed' ? null : value}}; });
      label = 'Set ' + ops.length + ' device' + (ops.length === 1 ? '' : 's') + ' to ' + value;
    } else if (field === 'room') {
      const r = value === '__shared' ? '' : value;
      ops = ids.filter(function (id) { return devs[id] && (devs[id].room || '') !== r; })
        .map(function (id) { return {op: 'merge', coll: 'devices', id: id, value: {room: r}}; });
      const rn = r ? (byId(d.rooms)[r] || {}).name || r : 'shared inventory';
      label = 'Moved ' + ops.length + ' device' + (ops.length === 1 ? '' : 's') + ' to ' + rn;
    } else if (field === 'location') {
      const l = value === '__none' ? null : value;
      ops = ids.filter(function (id) { return devs[id] && (devs[id].location || null) !== l; })
        .map(function (id) { return {op: 'merge', coll: 'devices', id: id, value: {location: l}}; });
      label = 'Set location of ' + ops.length + ' device' + (ops.length === 1 ? '' : 's');
    }
    if (!ops.length) { ctx.toast('Nothing to change.', 'info'); return; }
    commit(ops, label);
  }

  function markAllInstalled() {
    const devs = byId(doc().devices);
    const ids = selectedIds().filter(function (id) { return devs[id] && devs[id].status === 'planned'; });
    if (!ids.length) { ctx.toast('No planned devices selected.', 'info'); return; }
    commit(ids.map(function (id) { return {op: 'merge', coll: 'devices', id: id, value: {status: 'installed'}}; }),
      'Marked ' + ids.length + ' device' + (ids.length === 1 ? '' : 's') + ' installed');
  }

  // --------------------------------------------------------------- form
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
      render();
      if (opener && opener.isConnected) opener.focus();
      else {
        const b = tableWrap.querySelector('[data-edit="' + String(id).replace(/["\\]/g, '\\$&') + '"]');
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

  // ------------------------------------------------------------- events
  on(roomSel, 'change', function () { S.room = roomSel.value; render(); });
  on(statusSel, 'change', function () { S.status = statusSel.value; render(); });
  on(locSel, 'change', function () { S.location = locSel.value; render(); });
  on(kindSel, 'change', function () { S.kind = kindSel.value; render(); });
  on(sysSel, 'change', function () { S.system = sysSel.value; render(); });
  on(textIn, 'input', function () { S.text = textIn.value; render(); });
  on(qWarranty, 'click', function () { S.qWarranty = !S.qWarranty; render(); qWarranty.focus(); });
  on(qSerial, 'click', function () { S.qSerial = !S.qSerial; render(); qSerial.focus(); });
  on(groupCb, 'change', function () { S.group = groupCb.checked; render(); groupCb.focus(); });
  on(colsBox, 'change', function (e) {
    const cb = e.target.closest('[data-col]');
    if (!cb) return;
    const k = cb.getAttribute('data-col');
    S.visible = INV_COLUMNS.map(function (c) { return c[0]; }).filter(function (c) {
      return c === k ? cb.checked : S.visible.indexOf(c) >= 0;
    });
    const open = colsBox.open;
    render();
    colsBox.open = open;
    const again = colsBox.querySelector('[data-col="' + k + '"]');
    if (again) again.focus();
  });
  on(bulkStatus, 'change', function () { bulkApply('status', bulkStatus.value); });
  on(bulkRoom, 'change', function () { bulkApply('room', bulkRoom.value); });
  on(bulkLoc, 'change', function () { bulkApply('location', bulkLoc.value); });
  on(markInstalled, 'click', markAllInstalled);
  on(clearSel, 'click', function () { S.selected = {}; render(); });
  on(tableWrap, 'click', function (e) {
    const s = e.target.closest('[data-sort]');
    if (s) {
      const k = s.getAttribute('data-sort');
      S.sort = S.sort.key === k ? {key: k, dir: -S.sort.dir} : {key: k, dir: 1};
      render();
      const again = tableWrap.querySelector('[data-sort="' + k + '"]');
      if (again) again.focus();
      return;
    }
    const ed = e.target.closest('[data-edit]');
    if (ed) { openForm(ed.getAttribute('data-edit'), ed); return; }
    const tr = e.target.closest('tr[data-device]');
    if (tr && !e.target.closest('input,button,a')) ctx.select({type: 'device', id: tr.getAttribute('data-device')});
  });
  on(tableWrap, 'change', function (e) {
    const cb = e.target;
    if (cb.id === 'inv-select-all') {
      S.selected = {};
      if (cb.checked) filtered().forEach(function (r) { S.selected[r.id] = true; });
      render();
      const a = tableWrap.querySelector('#inv-select-all');
      if (a) a.focus();
      return;
    }
    const id = cb.getAttribute && cb.getAttribute('data-select');
    if (!id) return;
    if (cb.checked) S.selected[id] = true; else delete S.selected[id];
    render();
    const again = tableWrap.querySelector('[data-select="' + String(id).replace(/["\\]/g, '\\$&') + '"]');
    if (again) again.focus();
  });
  on(store, 'doc', function () { if (!S.editing) render(); });
  on(store, 'room', render);
  on(store, 'mode', render);

  render();

  return {
    destroy: function () {
      listeners.forEach(function (l) { l[0].removeEventListener(l[1], l[2], l[3]); });
      if (S.csvUrl && URL.revokeObjectURL) URL.revokeObjectURL(S.csvUrl);
      el.innerHTML = '';
    },
    focus: function (sel) {
      const id = sel && (sel.device || sel.id);
      if (!id) return;
      const row = tableWrap.querySelector('tr[data-device="' + String(id).replace(/["\\]/g, '\\$&') + '"]');
      if (row && row.scrollIntoView) row.scrollIntoView({block: 'center'});
    },
    getState: function () { return {room: S.room, visible: S.visible.slice(), sort: S.sort, group: S.group}; },
    setState: function (s) {
      if (!s) return;
      if (s.room) S.room = s.room;
      if (s.visible) S.visible = s.visible;
      if (s.sort) S.sort = s.sort;
      S.group = !!s.group;
      render();
    },
    _state: S,
    _openForm: openForm,
  };
}
