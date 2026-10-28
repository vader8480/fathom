// Rack page `racks/<id>[/<tab>[/front|rear|both]]` (docs/ui-audit.md B.3 RK): the
// racks explorer, the entity header (D5) and one tab panel: overview cards
// (space, load and power against the rack's limits), the one-rack elevation,
// the devices table, the accessories table or the cables table. rack.js
// mounts it when the route has an id and passes createElevation in, so the
// two modules do not import each other. Header ⋯: export, the public viewer
// page, its QR code, duplicate and delete.
import { h, on } from './dom.js';
import { mountExplorer } from './explorer.js';
import { mountEntityHeader } from './entity-header.js';
import { createTable, openTableDialog } from './datatable.js';
import { confirmScope, emptyState } from './feedback.js';
import { rackFacts, rackTabs, resolveTab, summaryCards, tabLabel, statusPill } from './entity-core.js';
import {
  ITEM_TYPES, findRack, rackUnits, rackDevices, rackItems, shelfCells, rackTotals, collisions, outOfRange, ruLabel,
  deleteRackOps, addItemOps, moveItemOps, updateItemOps, delItemOps, duplicateRackOps,
} from './rack-core.js';
import { DISPLAY_MODES, ANNOTATION_FIELDS, STORAGE } from './rack-display-core.js';
import { loadTemplateInfo } from './rack-display.js';
import { openRackExport } from './rack-export.js';
import { portLabel, deviceTitle } from './model-core.js';

const GLYPH = '\u2261';
const DOT = ' \u00b7 ';
const FACES = ['front', 'rear', 'both'];
const FACE_LABELS = { front: 'Front', rear: 'Rear', both: 'Both' };
const DISPLAY_LABELS = { label: 'Labels', image: 'Images', both: 'Both' };

function list(v) { return Array.isArray(v) ? v : []; }

function byId(arr, id) {
  const a = list(arr);
  for (let i = 0; i < a.length; i++) if (a[i] && a[i].id === id) return a[i];
  return null;
}

function cap(s) {
  const t = String(s || '');
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : '';
}

function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

function sortRacks(racks) {
  return racks.slice().sort(function (a, b) {
    return (a.order == null ? 1e9 : a.order) - (b.order == null ? 1e9 : b.order) || String(a.name || a.id).localeCompare(String(b.name || b.id));
  });
}

function typeLabel(type) {
  const t = ITEM_TYPES.filter(function (x) { return x.type === type; })[0];
  return t ? t.label : cap(type);
}

// The lower and upper printed labels of a span (labels follow numbering and start_u).
function spanLabels(rack, u, height) {
  const a = Number(ruLabel(rack, u));
  const b = Number(ruLabel(rack, u + height - 1));
  return a < b ? [a, b] : [b, a];
}

// U label for a placement: "U10", "U3–4" (labels follow the rack's numbering).
function uText(rack, p) {
  if (!(p.u >= 1)) return '';
  const s = spanLabels(rack, p.u, p.height);
  return 'U' + (p.height <= 1 ? s[0] : s[0] + '\u2013' + s[1]);
}

// The physical u whose span starts at printed label `n` (the "3" of "U3–4"), or 0.
function uFromLabel(rack, n, height) {
  for (let u = 1; u + height - 1 <= rackUnits(rack); u++) if (spanLabels(rack, u, height)[0] === n) return u;
  return 0;
}

function readPref(key, ok, dflt) {
  let v = null;
  try { v = window.localStorage.getItem(key); } catch (e) { v = null; }
  if (typeof v === 'string' && v.charAt(0) === '"') {
    try { v = JSON.parse(v); } catch (e) { v = null; }
  }
  return typeof v === 'string' && ok(v) ? v : dflt;
}

function writePref(key, v) {
  try { window.localStorage.setItem(key, v); } catch (e) { /* storage off */ }
}

function deviceRows(doc, rack) {
  return rackDevices(doc, rack.id).map(function (p) {
    const d = byId(doc.devices, p.device) || { id: p.device };
    const pill = statusPill(d.status);
    return {
      id: p.device,
      top: p.u >= 1 ? p.u + p.height - 1 : 0,
      u: uText(rack, p),
      name: deviceTitle(d) || p.device,
      model: ((d.manufacturer || '') + ' ' + (d.model || '')).trim(),
      status: pill ? pill.label : '',
      face: cap(p.face) + (p.side !== 'full' ? ' ' + p.side : ''),
      depth: p.depth === 'half' ? 'Half' : 'Full',
      height: p.height,
    };
  }).sort(function (a, b) { return b.top - a.top || a.name.localeCompare(b.name); });
}

function itemRows(doc, rack) {
  return rackItems(doc, rack.id).map(function (it) {
    const used = it.type === 'shelf' ? shelfCells(doc, rack.id, it.id).filter(function (c) { return c.device; }).length : 0;
    return {
      id: it.id,
      item: it,
      top: it.u >= 1 ? it.u + it.height - 1 : 0,
      u: uText(rack, it),
      start: it.u >= 1 ? spanLabels(rack, it.u, it.height)[0] : '',
      type: typeLabel(it.type),
      label: it.label,
      face: cap(it.face),
      depth: it.depth === 'half' ? 'Half' : 'Full',
      slots: it.slots,
      used: used,
      weight: it.weight_kg,
    };
  }).sort(function (a, b) { return b.top - a.top || a.label.localeCompare(b.label); });
}

function endText(doc, end) {
  if (!end || !end.device) return '';
  const d = byId(doc.devices, end.device);
  const port = d ? list(d.ports).filter(function (p) { return p && p.id === end.port; })[0] : null;
  return (d ? deviceTitle(d) : end.device) + (end.port ? DOT + (port ? portLabel(port) : end.port) : '');
}

function cableRows(doc, deviceIds) {
  const set = {};
  deviceIds.forEach(function (id) { set[id] = true; });
  return list(doc.cables).filter(function (c) {
    return c && ((c.from && set[c.from.device]) || (c.to && set[c.to.device]));
  }).map(function (c) {
    return {
      id: c.id,
      tag: c.tag || c.id || '',
      from: endText(doc, c.from),
      to: endText(doc, c.to),
      medium: c.medium || '',
      length: typeof c.length_m === 'number' ? c.length_m : null,
      status: cap(c.status),
    };
  });
}

const DEVICE_COLUMNS = [
  { key: 'u', header: 'U', value: function (r) { return r.top; }, cell: function (r) { return r.u; }, csv: function (r) { return r.u; }, width: '84px' },
  { key: 'name', header: 'Device', sticky: true },
  { key: 'model', header: 'Model', hideOnMobile: true },
  { key: 'status', header: 'Status', filterable: true },
  { key: 'face', header: 'Face', filterable: true, hideOnMobile: true },
  { key: 'depth', header: 'Depth', filterable: true, hideOnMobile: true },
];

const CABLE_COLUMNS = [
  { key: 'tag', header: 'Tag', sticky: true },
  { key: 'from', header: 'From' },
  { key: 'to', header: 'To' },
  { key: 'medium', header: 'Medium', filterable: true, hideOnMobile: true },
  { key: 'length', header: 'Length', align: 'right', hideOnMobile: true,
    cell: function (r) { return r.length === null ? '' : r.length + ' m'; } },
  { key: 'status', header: 'Status', filterable: true, hideOnMobile: true },
];

const PROBLEM_COLUMNS = [
  { key: 'text', header: 'Problem' },
  { key: 'device', header: 'Device' },
  { key: 'created', header: 'Reported', hideOnMobile: true },
];

export function mountRackPage(el, ctx, opts) {
  const o = opts || {};
  const store = ctx.store;
  const createElevation = o.createElevation;
  let route = o.route || {};
  let id = '';
  let tab = '';
  let face = 'front';
  let display = readPref(STORAGE.display, function (v) { return DISPLAY_MODES.indexOf(v) >= 0; }, 'label');
  let annotate = readPref(STORAGE.annotate, function (v) { return ANNOTATION_FIELDS.some(function (f) { return f.key === v; }); }, '');
  let info = {};
  let infoKey = '';
  let eh = null;
  let elev = null;
  let table = null;
  let printer = null;
  let bar = null;
  let redirectTimer = 0;
  let destroyed = false;
  let docSig = '';
  let exRoom = null;
  const offs = [];

  if (typeof ctx.ensureCss === 'function') ctx.ensureCss('page-rack.css');

  const root = h('div', { class: 'rp-root' });
  el.appendChild(root);
  const ex = mountExplorer(root, {
    key: 'racks', title: 'Racks', glyph: GLYPH, items: [], selected: null, mobileLabel: 'Racks',
    listId: 'rp-racks', contentLabel: 'Rack',
    footer: function (shown, total) { return shown === total ? plural(total, 'rack', 'racks') : shown + ' of ' + total + ' racks'; },
  });
  const body = h('div', { class: 'rp-body' });
  const printHost = h('div', { class: 'rp-print', 'aria-hidden': 'true' });
  ex.content.appendChild(body);
  root.appendChild(printHost);

  function doc() { return store.doc || {}; }
  function readOnly() { return !!store.readOnly; }
  function rack() { return findRack(doc(), id); }
  function toast(msg, level) { if (typeof ctx.toast === 'function') ctx.toast(msg, level); }
  function commit(ops, label) {
    if (!ops || !ops.length || readOnly()) return false;
    ctx.commit(ops, label);
    return true;
  }
  function liveRoute() {
    let r = null;
    try { r = ctx.route; } catch (e) { r = null; }
    return r || route;
  }
  function href(partial) {
    if (typeof ctx.routeHref !== 'function') return null;
    const v = ctx.routeHref(partial);
    return v && v !== '#' ? v : null;
  }
  function subOf(k, f) { return k === 'elevation' && f && f !== 'front' ? f : ''; }
  function tabHref(k, sub) {
    return href({ view: 'racks', id: id, tab: k, sub: subOf(k, sub), query: {} });
  }
  function go(k, sub) {
    if (typeof ctx.navigateRoute === 'function') ctx.navigateRoute({ view: 'racks', id: id, tab: k, sub: subOf(k, sub), query: {} });
  }
  function openDrawer(sel) {
    if (typeof ctx.openDrawer === 'function') ctx.openDrawer(sel);
    else if (typeof ctx.openInspector === 'function') ctx.openInspector(sel);
    else ctx.select(sel);
  }
  function scroller() { return ex.content.parentNode; }
  function appRoot() { return typeof ctx.appRoot === 'string' ? ctx.appRoot : ''; }
  function projectPath() { return 'p/' + encodeURIComponent(ctx.project || '') + '/rk/' + encodeURIComponent(id); }
  function viewerHref() { return appRoot() + projectPath(); }
  function qrSrc() {
    return appRoot() + 'api/v2/projects/' + encodeURIComponent(ctx.project || '') + '/qr/rack/' + encodeURIComponent(id) + '.svg';
  }
  function tabs() { return rackTabs(doc(), rack()); }

  // ------------------------------------------------------------ template info

  // Weight and power of catalog/library templates; the cards and badges re-render when they arrive.
  function loadInfo() {
    const d = doc();
    const seen = {};
    const ids = [];
    rackDevices(d, id).forEach(function (p) {
      const dev = byId(d.devices, p.device);
      const t = dev && dev.template;
      if (typeof t === 'string' && t && !seen[t]) { seen[t] = true; ids.push(t); }
    });
    const key = id + '|' + ids.sort().join(',');
    if (key === infoKey) return;
    infoKey = key;
    if (!ids.length) { info = {}; return; }
    loadTemplateInfo(ctx, ids).then(function (res) {
      if (destroyed || key !== infoKey) return;
      info = res || {};
      const rk = rack();
      if (!rk || !eh) return;
      eh.update(headerOpts(rk));
      if (tab === 'overview') renderPanel();
    });
  }

  // ------------------------------------------------------------ explorer

  function renderExplorer() {
    const d = doc();
    const rooms = {};
    list(d.rooms).forEach(function (r) { if (r) rooms[r.id] = r.name || r.id; });
    exRoom = store.room;
    const allRooms = store.room === '*';
    const racks = sortRacks(list(d.racks).filter(function (r) { return r && r.id; }));
    const sub = tab === 'elevation' ? face : '';
    function itemHref(r) {
      const p = { view: 'racks', id: r.id, tab: tab || 'overview', sub: subOf(tab, sub), query: {} };
      if (!allRooms && r.room) p.room = r.room;
      return href(p);
    }
    ex.setItems(racks.map(function (r) {
      return {
        id: r.id, label: r.name || r.id, glyph: GLYPH, href: itemHref(r),
        group: r.room ? rooms[r.room] || r.room : 'No room',
        sub: rackUnits(r) + 'U' + DOT + plural(rackDevices(d, r.id).length, 'device', 'devices'),
      };
    }));
    ex.setSelected(id);
  }

  // ------------------------------------------------------------ header

  function headerOpts(rk) {
    const d = doc();
    const ro = readOnly();
    const devIds = rackDevices(d, rk.id).map(function (p) { return p.device; });
    const nCables = cableRows(d, devIds).length;
    const nItems = rackItems(d, rk.id).length;
    const coll = collisions(d, rk.id);
    const oor = outOfRange(d, rk.id);
    const tot = rackTotals(d, rk.id, info);
    const room = byId(d.rooms, rk.room);
    const loc = byId(d.locations, rk.location);
    const badges = [];
    if (coll.length) {
      badges.push({ label: plural(coll.length, 'collision', 'collisions'), level: 'err', title: 'Devices overlap. Open the elevation.',
        onClick: function () { go('elevation', coll[0].face); } });
    }
    if (oor.length) {
      badges.push({ label: plural(oor.length, 'device', 'devices') + ' outside the rack', level: 'warn', title: 'Open the elevation.',
        onClick: function () { go('elevation', face); } });
    }
    if (tot && tot.max_load_kg !== null && tot.weight_kg > tot.max_load_kg) {
      badges.push({ key: 'overweight', label: 'Over max load', level: 'warn', title: tot.weight_kg + ' kg of ' + tot.max_load_kg + ' kg max.' });
    }
    if (tot && tot.power_limit_w !== null && tot.power_w > tot.power_limit_w) {
      badges.push({ key: 'over-power', label: 'Over power limit', level: 'warn', title: tot.power_w + ' W of ' + tot.power_limit_w + ' W limit.' });
    }
    const overflow = [
      { key: 'export', label: 'Export\u2026', run: function () { openRackExport(ctx, { racks: [rk.id], face: face }); } },
      { key: 'viewer', label: 'Open viewer page', href: viewerHref(), target: '_blank' },
      { key: 'qr', label: 'QR code\u2026', run: openQr },
    ];
    if (!ro) {
      overflow.push({ key: 'duplicate', label: 'Duplicate rack\u2026', run: duplicateRack });
      overflow.push({ key: 'delete', label: 'Delete rack', danger: true, run: deleteRack });
    }
    return {
      kind: 'rack', id: rk.id, glyph: GLYPH, title: rk.name || rk.id,
      subtitle: [room ? room.name || room.id : '', loc ? loc.name || loc.id : ''].filter(Boolean).join(DOT),
      facts: rackFacts(d, rk, { info: info, href: function (view, ref) { return href({ view: view, id: ref, tab: '', sub: '', room: view === 'rooms' ? ref : undefined, query: {} }); } }),
      badges: badges,
      actions: [
        { key: 'edit', label: ro ? 'Details' : 'Edit', primary: true, run: function () { openDrawer({ type: 'rack', id: rk.id }); } },
        { key: 'print', label: 'Print', run: printRack },
      ],
      overflow: overflow,
      tabs: tabs().map(function (k) {
        const count = k === 'devices' ? devIds.length : k === 'cables' ? nCables : k === 'accessories' ? nItems : null;
        return { key: k, label: tabLabel(k), count: count, href: tabHref(k, k === 'elevation' ? face : '') };
      }),
      activeTab: tab,
    };
  }

  function deleteRack() {
    const rk = rack();
    if (!rk || readOnly()) return;
    const n = rackDevices(doc(), rk.id).length;
    confirmScope(ctx, {
      verb: 'Delete', noun: rk.name || rk.id, danger: true, ok: 'Delete rack',
      detail: n ? plural(n, 'device becomes', 'devices become') + ' unracked.' : 'The rack is empty.',
    }).then(function (ok) {
      if (!ok || destroyed) return;
      const name = rk.name || rk.id;
      ctx.commit(deleteRackOps(doc(), rk.id), 'Deleted rack ' + name);
      if (typeof ctx.navigateRoute === 'function') ctx.navigateRoute({ view: 'racks', id: '', tab: '', sub: '', query: {} });
    });
  }

  // Copies the rack and its accessories; the dialog offers to copy its devices too.
  function duplicateRack() {
    const rk = rack();
    if (!rk || readOnly()) return;
    const name = rk.name || rk.id;
    const n = rackDevices(doc(), rk.id).length;
    function run(withDevices) {
      if (destroyed || !rack()) return;
      const res = duplicateRackOps(doc(), rk.id, { devices: withDevices });
      if (!commit(res.ops, 'Duplicated rack ' + name)) return;
      if (typeof ctx.navigateRoute === 'function') ctx.navigateRoute({ view: 'racks', id: res.id, tab: 'overview', sub: '', query: {} });
    }
    if (typeof ctx.openDialog !== 'function') { run(false); return; }
    const box = n ? h('input', { type: 'checkbox', id: 'rp-dup-devices', class: 'rp-dup-devices' }) : null;
    const content = h('div', { class: 'rp-dup' }, [
      h('p', { text: 'Creates \u201c' + name + ' (copy)\u201d with the same size, settings and accessories.' }),
      box ? h('label', { class: 'rp-check', for: 'rp-dup-devices' }, [box, h('span', {
        text: 'Also copy its ' + plural(n, 'device', 'devices') + ' (serials, asset tags and IP addresses are left blank)',
      })]) : null,
    ]);
    ctx.openDialog({
      title: 'Duplicate ' + name, body: content,
      buttons: [{ label: 'Cancel', value: null }, { label: 'Duplicate', primary: true, value: function () { return { devices: !!(box && box.checked) }; } }],
    }).then(function (v) { if (v) run(v.devices); });
  }

  // The QR code of the public rack page (/p/<n>/rk/<rack>); 409 no_public_url explains itself.
  function openQr() {
    const rk = rack();
    if (!rk) return;
    const src = qrSrc();
    if (typeof ctx.openDialog !== 'function') { window.open(src, '_blank', 'noopener'); return; }
    const name = rk.name || rk.id;
    const img = h('img', { class: 'rp-qr-img', alt: 'QR code for the ' + name + ' viewer page', width: '240', height: '240', hidden: true });
    const msg = h('p', { class: 'rp-qr-msg', role: 'status' }, 'Loading the QR code\u2026');
    const printBtn = h('button', { type: 'button', class: 'rp-qr-print', disabled: true, text: 'Print' });
    const content = h('div', { class: 'rp-qr' }, [
      h('div', { class: 'rp-qr-frame' }, [img, msg]),
      h('p', { class: 'rp-qr-name', text: name }),
      h('p', { class: 'rp-qr-url' }, [h('a', { href: viewerHref(), target: '_blank', rel: 'noopener', text: viewerHref() })]),
      h('div', { class: 'rp-qr-tools' }, [printBtn]),
    ]);
    function show() {
      img.hidden = false;
      img.setAttribute('src', src);
    }
    function fail(text) {
      img.hidden = true;
      img.removeAttribute('src');
      msg.hidden = false;
      msg.className = 'rp-qr-msg rp-qr-err';
      msg.textContent = text;
      printBtn.disabled = true;
    }
    img.addEventListener('load', function () { msg.hidden = true; printBtn.disabled = false; });
    img.addEventListener('error', function () { if (!img.hidden) fail('The QR code could not be loaded.'); });
    printBtn.addEventListener('click', function () {
      const html = document.documentElement;
      html.classList.add('rp-qr-printing');
      const done = function () { html.classList.remove('rp-qr-printing'); window.removeEventListener('afterprint', done); };
      window.addEventListener('afterprint', done);
      try { window.print(); } finally { setTimeout(done, 0); }
    });
    ctx.openDialog({ title: 'QR code' + DOT + name, body: content, buttons: [{ label: 'Close', value: null }] });
    if (typeof fetch !== 'function') { show(); return; }
    fetch(src, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (r.ok) { show(); return; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (j && j.code === 'no_public_url') fail('No public URL is set for this server, so the QR code has nothing to point at. An admin can set the Public URL in Settings \u2192 Project, or FATHOM_PUBLIC_URL on the server.');
        else fail((j && j.error) || 'The QR code could not be made (HTTP ' + r.status + ').');
      });
    }, function () { show(); });
  }

  // Both faces of this rack only, in a container that is hidden on screen.
  function printRack() {
    if (!rack() || printer) return;
    root.classList.add('rp-printing');
    printer = createElevation(printHost, ctx, { rack: id, face: 'front' });
    printer.print(function () {
      if (printer) printer.destroy();
      printer = null;
      printHost.innerHTML = '';
      root.classList.remove('rp-printing');
    });
  }

  // ------------------------------------------------------------ panels

  function clearPanel() {
    if (table) table.destroy();
    if (elev) elev.destroy();
    while (offs.length) offs.pop()();
    table = null;
    elev = null;
    bar = null;
    body.innerHTML = '';
  }

  function tableUrl() {
    if (typeof ctx.setParams !== 'function') return null;
    return {
      get: function () { return liveRoute().query || {}; },
      set: function (patch) { ctx.setParams(patch); },
    };
  }

  function drillColumns(kind) {
    if (kind === 'device') return DEVICE_COLUMNS.filter(function (c) { return c.key !== 'depth'; });
    if (kind === 'cable') return CABLE_COLUMNS;
    return PROBLEM_COLUMNS;
  }

  function drillRows(kind, ids) {
    const d = doc();
    const rk = rack();
    const want = {};
    ids.forEach(function (x) { want[x] = true; });
    if (kind === 'device') return deviceRows(d, rk).filter(function (r) { return want[r.id]; });
    if (kind === 'cable') return cableRows(d, rackDevices(d, rk.id).map(function (p) { return p.device; })).filter(function (r) { return want[r.id]; });
    return list(d.problems).filter(function (p) { return p && want[p.id]; }).map(function (p) {
      const dev = byId(d.devices, p.device);
      return { id: p.id, text: p.text || '', device: dev ? deviceTitle(dev) : p.device || '', deviceId: p.device || '', created: p.created || '' };
    });
  }

  function drill(c) {
    const kind = c.drill.kind;
    openTableDialog(ctx, {
      title: c.drill.title, key: 'rack-' + kind + 's', columns: drillColumns(kind), rows: drillRows(kind, c.drill.ids),
      csvName: id + '-' + kind + 's.csv',
      onRow: function (row) {
        if (kind === 'problem') { if (row.deviceId) openDrawer({ type: 'device', id: row.deviceId }); return; }
        openDrawer({ type: kind, id: row.id });
      },
    });
  }

  function cardEl(c) {
    const parts = [
      h('span', { class: 'rp-card-label', text: c.label }),
      h('span', { class: 'rp-card-value' }, [h('span', { class: 'rp-card-n', text: String(c.count) }), c.sub ? h('span', { class: 'rp-card-sub', text: ' ' + c.sub }) : null]),
      c.level === 'warn' && c.title ? h('span', { class: 'rp-card-warn', text: c.title }) : null,
    ];
    const attrs = { class: 'rp-card' + (c.level === 'warn' ? ' rp-card--warn' : ''), 'data-card': c.key, 'data-level': c.level || null };
    if (c.drill && c.count > 0) {
      const b = h('button', Object.assign(attrs, { type: 'button', title: 'Show ' + c.drill.title }), parts);
      b.addEventListener('click', function () { drill(c); });
      return b;
    }
    const link = c.tab ? tabHref(c.tab, '') : null;
    if (link) return h('a', Object.assign(attrs, { href: link }), parts);
    return h('div', attrs, parts);
  }

  function renderOverview(rk) {
    const cards = summaryCards('rack', doc(), rk, { info: info, tabs: tabs() });
    body.appendChild(h('div', { class: 'rp-panel rp-overview', 'data-tab': 'overview' }, [
      h('div', { class: 'rp-cards' }, cards.map(cardEl)),
      rk.notes ? h('section', { class: 'rp-notes' }, [h('h2', { class: 'rp-h', text: 'Notes' }), h('p', { text: rk.notes })]) : null,
    ]));
  }

  // ------------------------------------------------------------ elevation

  function faceLink(f) {
    return h('a', {
      class: 'rp-face', 'data-face': f, href: tabHref('elevation', f), 'aria-current': f === face ? 'true' : null, text: FACE_LABELS[f],
    });
  }

  function syncBar() {
    if (!bar) return;
    Array.prototype.forEach.call(bar.querySelectorAll('.rp-face'), function (a) {
      if (a.getAttribute('data-face') === face) a.setAttribute('aria-current', 'true');
      else a.removeAttribute('aria-current');
    });
    Array.prototype.forEach.call(bar.querySelectorAll('.rp-display-opt'), function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-display') === display ? 'true' : 'false');
    });
    const sel = bar.querySelector('.rp-annotate');
    if (sel && sel.value !== annotate) sel.value = annotate;
  }

  function setDisplay(v) {
    if (DISPLAY_MODES.indexOf(v) < 0 || v === display) return;
    display = v;
    writePref(STORAGE.display, v);
    if (elev) elev.setOptions({ display: v });
    syncBar();
  }

  function setAnnotate(v) {
    if (v === annotate) return;
    annotate = v;
    writePref(STORAGE.annotate, v);
    if (elev) elev.setOptions({ annotate: v });
    syncBar();
  }

  function renderElevation(rk) {
    const faces = h('nav', { class: 'rp-faces', 'aria-label': 'Rack face' }, FACES.map(faceLink));
    const modes = h('div', { class: 'rp-seg rp-display', role: 'group', 'aria-label': 'Show devices as' }, DISPLAY_MODES.map(function (m) {
      return h('button', { type: 'button', class: 'rp-display-opt', 'data-display': m, 'aria-pressed': m === display ? 'true' : 'false', text: DISPLAY_LABELS[m] || cap(m) });
    }));
    const ann = h('select', { id: 'rp-annotate', class: 'rp-annotate', 'aria-label': 'Annotation column' }, ANNOTATION_FIELDS.map(function (f) {
      return h('option', { value: f.key, text: f.key ? f.label : 'No annotation' });
    }));
    ann.value = annotate;
    const add = readOnly() || typeof ctx.pickDevice !== 'function' ? null
      : h('button', { type: 'button', class: 'rk-btn rp-add', text: 'Add device\u2026' });
    const host = h('div', { class: 'rp-elev', 'data-face': face });
    bar = h('div', { class: 'rp-bar' }, [faces, modes, h('label', { class: 'rp-ann' }, [h('span', { class: 'rp-ann-label', text: 'Annotate' }), ann]), add]);
    body.appendChild(h('div', { class: 'rp-panel rp-elevation', 'data-tab': 'elevation' }, [bar, host]));
    offs.push(on(modes, 'click', function (e) {
      const b = e.target.closest('.rp-display-opt');
      if (b) setDisplay(b.getAttribute('data-display'));
    }));
    offs.push(on(ann, 'change', function () { setAnnotate(ann.value); }));
    elev = createElevation(host, ctx, { rack: rk.id, face: face === 'rear' ? 'rear' : 'front' });
    if (typeof elev.setOptions === 'function') elev.setOptions({ face: face, display: display, annotate: annotate });
    if (add) offs.push(on(add, 'click', function () { if (elev) elev.addDevice(); }));
  }

  // ------------------------------------------------------------ tables

  function itemInput(row, field) {
    const cacheKey = '_' + field;
    if (row[cacheKey]) return row[cacheKey];
    const it = row.item;
    const isU = field === 'u';
    const input = h('input', {
      type: isU ? 'number' : 'text', class: 'rp-acc-' + field, inputmode: isU ? 'numeric' : null, min: isU ? '0' : null,
      value: isU ? String(row.start) : it.label, 'aria-label': (isU ? 'Lowest U of ' : 'Label of ') + it.label,
      'data-item': it.id,
    });
    input.addEventListener('change', function () {
      const rk = rack();
      if (!rk) return;
      if (isU) {
        const n = parseInt(input.value, 10);
        const u = isNaN(n) ? 0 : uFromLabel(rk, n, it.height);
        const ops = u ? moveItemOps(doc(), rk.id, it.id, u) : [];
        if (!ops.length) {
          toast(it.label + ' does not fit at U' + input.value + '.', 'warn');
          input.value = String(row.start);
          return;
        }
        commit(ops, 'Moved ' + it.label + ' to U' + n);
      } else {
        const v = input.value.trim();
        commit(updateItemOps(doc(), rk.id, it.id, { label: v || null }), 'Renamed ' + it.label + (v ? ' to ' + v : ''));
      }
    });
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); input.blur(); } });
    row[cacheKey] = input;
    return input;
  }

  function deleteItem(row) {
    const rk = rack();
    if (!rk || readOnly()) return;
    const it = row.item;
    const ops = delItemOps(doc(), rk.id, it.id);
    if (!row.used) { commit(ops, 'Deleted ' + it.label); return; }
    confirmScope(ctx, {
      verb: 'Delete', noun: it.label, danger: true, ok: 'Delete shelf',
      detail: plural(row.used, 'device on it becomes', 'devices on it become') + ' unracked.',
    }).then(function (ok) { if (ok && !destroyed) commit(delItemOps(doc(), rk.id, it.id), 'Deleted ' + it.label); });
  }

  function itemColumns() {
    const ro = readOnly();
    const cols = [
      { key: 'u', header: 'U', value: function (r) { return r.top; }, csv: function (r) { return r.u; }, width: '96px',
        cell: ro ? function (r) { return r.u; } : function (r) { return itemInput(r, 'u'); } },
      { key: 'type', header: 'Type', filterable: true, hideOnMobile: true },
      { key: 'label', header: 'Label', sticky: true, cell: ro ? null : function (r) { return itemInput(r, 'label'); } },
      { key: 'face', header: 'Face', filterable: true, hideOnMobile: true },
      { key: 'depth', header: 'Depth', filterable: true, hideOnMobile: true },
      { key: 'slots', header: 'Slots', align: 'right', hideOnMobile: true,
        cell: function (r) { return r.slots === null ? '' : r.used + ' / ' + r.slots + ' used'; },
        csv: function (r) { return r.slots === null ? '' : r.slots; } },
      { key: 'weight', header: 'Weight', align: 'right', hideOnMobile: true,
        cell: function (r) { return r.weight === null ? '' : r.weight + ' kg'; }, csv: function (r) { return r.weight === null ? '' : r.weight; } },
    ];
    if (!ro) {
      cols.push({ key: 'actions', header: '', sortable: false, csv: false, width: '56px', value: function () { return ''; },
        cell: function (r) {
          if (r._del) return r._del;
          r._del = h('button', { type: 'button', class: 'rp-acc-del', 'data-item': r.id, 'aria-label': 'Delete ' + r.label, title: 'Delete', text: '\u00d7' });
          r._del.addEventListener('click', function () { deleteItem(r); });
          return r._del;
        } });
    }
    return cols;
  }

  function addItem(type) {
    const rk = rack();
    if (!rk || readOnly()) return;
    const res = addItemOps(doc(), rk.id, { type: type });
    if (!res.ops.length) { toast('There is no free space for a ' + typeLabel(type).toLowerCase() + ' in ' + (rk.name || rk.id) + '.', 'warn'); return; }
    if (commit(res.ops, 'Added ' + typeLabel(type).toLowerCase() + ' to ' + (rk.name || rk.id)) && table) table.setHighlight(res.id);
  }

  function renderAccessories(rk) {
    const ro = readOnly();
    const host = h('div', { class: 'rp-panel rp-table rp-accessories', 'data-tab': 'accessories' });
    if (!ro) {
      const type = h('select', { id: 'rp-acc-type', class: 'rp-acc-type', 'aria-label': 'Accessory type' }, ITEM_TYPES.map(function (t) {
        return h('option', { value: t.type, text: t.label + (t.height > 1 ? ' (' + t.height + 'U)' : '') });
      }));
      const add = h('button', { type: 'button', class: 'rk-btn rp-acc-add', text: 'Add accessory' });
      host.appendChild(h('div', { class: 'rp-bar rp-acc-bar' }, [type, add]));
      offs.push(on(add, 'click', function () { addItem(type.value); }));
    }
    const tableHost = h('div', { class: 'rp-acc-table' });
    host.appendChild(tableHost);
    body.appendChild(host);
    table = createTable(tableHost, {
      key: 'rack-accessories',
      scope: ctx.project || '',
      caption: 'Accessories in ' + (rk.name || rk.id),
      columns: itemColumns(),
      rows: itemRows(doc(), rk),
      url: tableUrl(),
      sticky: true,
      selectable: false,
      noun: { one: 'accessory', many: 'accessories' },
      empty: ro ? 'No accessories in this rack.' : 'No accessories yet. Add blanks, vents, shelves or cable managers above.',
      csvName: rk.id + '-accessories.csv',
      rowAttrs: function (r) { return { 'data-type': r.item.type }; },
    });
  }

  function renderTable(rk, kind) {
    const d = doc();
    const isDev = kind === 'devices';
    const devIds = rackDevices(d, rk.id).map(function (p) { return p.device; });
    const host = h('div', { class: 'rp-panel rp-table', 'data-tab': kind });
    body.appendChild(host);
    const sel = store.selection;
    table = createTable(host, {
      key: isDev ? 'rack-devices' : 'rack-cables',
      scope: ctx.project || '',
      caption: (isDev ? 'Devices in ' : 'Cables touching ') + (rk.name || rk.id),
      columns: isDev ? DEVICE_COLUMNS : CABLE_COLUMNS,
      rows: isDev ? deviceRows(d, rk) : cableRows(d, devIds),
      url: tableUrl(),
      sticky: true,
      noun: isDev ? { one: 'device', many: 'devices' } : { one: 'cable', many: 'cables' },
      empty: isDev ? 'No devices in this rack yet.' : 'No cables touch the devices in this rack.',
      csvName: rk.id + '-' + kind + '.csv',
      highlight: sel && sel.type === (isDev ? 'device' : 'cable') ? sel.id : null,
      onRow: function (row) { openDrawer({ type: isDev ? 'device' : 'cable', id: row.id }); },
    });
  }

  function refreshTable() {
    if (!table) return;
    const rk = rack();
    if (!rk) return;
    const d = doc();
    if (tab === 'accessories') table.setRows(itemRows(d, rk));
    else table.setRows(tab === 'devices' ? deviceRows(d, rk) : cableRows(d, rackDevices(d, rk.id).map(function (p) { return p.device; })));
  }

  function renderPanel() {
    clearPanel();
    const rk = rack();
    if (!rk) return;
    if (tab === 'elevation') renderElevation(rk);
    else if (tab === 'accessories') renderAccessories(rk);
    else if (tab === 'devices' || tab === 'cables') renderTable(rk, tab);
    else renderOverview(rk);
  }

  function renderMissing() {
    clearPanel();
    if (eh) { eh.destroy(); eh = null; }
    const back = href({ view: 'racks', id: '', tab: '', sub: '', query: {} });
    body.appendChild(h('div', { class: 'rp-panel rp-missing', 'data-tab': '' }, emptyState({
      title: 'Rack \u201c' + id + '\u201d not found',
      text: 'It may have been deleted or renamed. Pick another rack from the list.',
      action: back ? { label: 'All racks', href: back } : null,
    })));
    if (ctx.setTitle) ctx.setTitle('Rack not found');
  }

  function renderAll() {
    const rk = rack();
    docSig = sigOf();
    renderExplorer();
    if (!rk) { renderMissing(); return; }
    loadInfo();
    if (eh) eh.update(headerOpts(rk));
    else eh = mountEntityHeader(ex.content, headerOpts(rk));
    renderPanel();
    if (ctx.setTitle) ctx.setTitle(rk.name || rk.id);
  }

  function sigOf() {
    return String(store.readOnly) + '|' + (rack() ? 1 : 0);
  }

  // ------------------------------------------------------------ routing

  function canonical(r) {
    const res = resolveTab(rackTabs(doc(), findRack(doc(), r.id || '') || {}), r.tab);
    const sub = r.sub || '';
    let redirect = res.redirect;
    let f = 'front';
    if (res.tab === 'elevation') {
      if (sub && FACES.indexOf(sub) < 0) redirect = true;
      f = sub === 'rear' || sub === 'both' ? sub : 'front';
    } else if (sub) {
      redirect = true;
    }
    return { tab: res.tab, face: f, redirect: redirect };
  }

  // Unknown or missing tabs and stray subs are replaced (D5); the write is
  // deferred because the shell is still mounting this view.
  function scheduleRedirect(c) {
    clearTimeout(redirectTimer);
    if (typeof ctx.navigateRoute !== 'function') return;
    redirectTimer = setTimeout(function () {
      if (destroyed) return;
      const cur = liveRoute();
      if (cur.view !== 'racks' || cur.id !== id) return;
      ctx.navigateRoute({ tab: c.tab, sub: subOf(c.tab, c.face) }, { replace: true });
    }, 0);
  }

  function apply(r, first) {
    const prevId = id;
    const prevTab = tab;
    const prevFace = face;
    route = r || route;
    id = route.id || '';
    const c = canonical(route);
    tab = c.tab;
    face = c.face;
    if (c.redirect && findRack(doc(), id)) scheduleRedirect(c);
    if (first || id !== prevId) {
      if (scroller()) scroller().scrollTop = 0;
      renderAll();
      if (rack() && ctx.recent && typeof ctx.recent.push === 'function') ctx.recent.push('rack', id);
      return;
    }
    if (!rack()) return;
    if (tab !== prevTab) {
      if (scroller()) scroller().scrollTop = 0;
      eh.update(headerOpts(rack()));
      renderPanel();
      renderExplorer();
      return;
    }
    if (face !== prevFace) {
      if (elev) {
        if (typeof elev.setOptions === 'function') elev.setOptions({ face: face });
        else elev.setFace(face);
        const host = body.querySelector('.rp-elev');
        if (host) host.setAttribute('data-face', face);
      }
      syncBar();
      eh.update(headerOpts(rack()));
      renderExplorer();
      return;
    }
    if (store.room !== exRoom) renderExplorer();
    if (table) table.readUrl();
  }

  function onDoc() {
    if (destroyed) return;
    if (sigOf() !== docSig) { renderAll(); return; }
    renderExplorer();
    const rk = rack();
    if (!rk) return;
    loadInfo();
    eh.update(headerOpts(rk));
    if (tab === 'overview') renderPanel();
    else refreshTable();
  }

  function onSelection(e) {
    if (!table || tab === 'accessories') return;
    const sel = e.detail;
    table.setHighlight(sel && sel.type === (tab === 'devices' ? 'device' : 'cable') ? sel.id : null);
  }

  store.addEventListener('doc', onDoc);
  store.addEventListener('mode', onDoc);
  store.addEventListener('selection', onSelection);

  apply(route, true);

  return {
    route: function (r) { if (!destroyed) apply(r, false); },
    focus: function (sel) {
      if (elev && sel) elev.focus(sel);
    },
    destroy: function () {
      if (destroyed) return;
      destroyed = true;
      clearTimeout(redirectTimer);
      store.removeEventListener('doc', onDoc);
      store.removeEventListener('mode', onDoc);
      store.removeEventListener('selection', onSelection);
      clearPanel();
      if (printer) printer.destroy();
      if (eh) eh.destroy();
      ex.destroy();
      if (root.parentNode) root.parentNode.removeChild(root);
    },
    get _state() { return elev ? elev._state : {}; },
  };
}
