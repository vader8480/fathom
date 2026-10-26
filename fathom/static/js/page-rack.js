// Rack page `racks/<id>[/<tab>[/front|rear]]` (docs/ui-audit.md B.3 RK): the
// racks explorer, the entity header (D5) and one tab panel: overview cards,
// the one-rack elevation, the devices table or the cables table. rack.js
// mounts it when the route has an id and passes createElevation in, so the
// two modules do not import each other.
import { h } from './dom.js';
import { mountExplorer } from './explorer.js';
import { mountEntityHeader } from './entity-header.js';
import { createTable, openTableDialog } from './datatable.js';
import { confirmScope, emptyState } from './feedback.js';
import { rackFacts, rackTabs, resolveTab, summaryCards, tabLabel, statusPill } from './entity-core.js';
import { findRack, rackUnits, rackDevices, collisions, outOfRange, ruLabel, deleteRackOps } from './rack-core.js';
import { portLabel, deviceTitle } from './model-core.js';

const GLYPH = '\u2261';
const DOT = ' \u00b7 ';
const DASH = '\u2014';

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

// U label for a placement: "U10", "U3–4" (labels follow the rack's numbering).
function uText(rack, p) {
  if (!(p.u >= 1)) return '';
  const a = ruLabel(rack, p.u);
  const b = ruLabel(rack, p.u + p.height - 1);
  if (p.height <= 1) return 'U' + a;
  return 'U' + (Number(a) < Number(b) ? a + '\u2013' + b : b + '\u2013' + a);
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
  let eh = null;
  let elev = null;
  let table = null;
  let printer = null;
  let faceSeg = null;
  let redirectTimer = 0;
  let destroyed = false;
  let docSig = '';
  let exRoom = null;

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
  function tabHref(k, sub) {
    return href({ view: 'racks', id: id, tab: k, sub: k === 'elevation' && sub === 'rear' ? 'rear' : '', query: {} });
  }
  function go(k, sub) {
    if (typeof ctx.navigateRoute === 'function') ctx.navigateRoute({ view: 'racks', id: id, tab: k, sub: k === 'elevation' && sub === 'rear' ? 'rear' : '', query: {} });
  }
  function openDrawer(sel) {
    if (typeof ctx.openDrawer === 'function') ctx.openDrawer(sel);
    else if (typeof ctx.openInspector === 'function') ctx.openInspector(sel);
    else ctx.select(sel);
  }
  function scroller() { return ex.content.parentNode; }

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
      const p = { view: 'racks', id: r.id, tab: tab || 'overview', sub: sub === 'rear' ? 'rear' : '', query: {} };
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
    const devIds = rackDevices(d, rk.id).map(function (p) { return p.device; });
    const nCables = cableRows(d, devIds).length;
    const coll = collisions(d, rk.id);
    const oor = outOfRange(d, rk.id);
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
    return {
      kind: 'rack', id: rk.id, glyph: GLYPH, title: rk.name || rk.id,
      subtitle: [room ? room.name || room.id : '', loc ? loc.name || loc.id : ''].filter(Boolean).join(DOT),
      facts: rackFacts(d, rk, { href: function (view, ref) { return href({ view: view, id: ref, tab: '', sub: '', room: view === 'rooms' ? ref : undefined, query: {} }); } }),
      badges: badges,
      actions: [
        { key: 'edit', label: readOnly() ? 'Details' : 'Edit', primary: true, run: function () { openDrawer({ type: 'rack', id: rk.id }); } },
        { key: 'print', label: 'Print', run: printRack },
      ],
      overflow: readOnly() ? [] : [{ key: 'delete', label: 'Delete rack', danger: true, run: deleteRack }],
      tabs: rackTabs().map(function (k) {
        return { key: k, label: tabLabel(k), count: k === 'devices' ? devIds.length : k === 'cables' ? nCables : null, href: tabHref(k, k === 'elevation' ? face : '') };
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
    table = null;
    elev = null;
    faceSeg = null;
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
    ];
    const attrs = { class: 'rp-card', 'data-card': c.key };
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
    const cards = summaryCards('rack', doc(), rk);
    body.appendChild(h('div', { class: 'rp-panel rp-overview', 'data-tab': 'overview' }, [
      h('div', { class: 'rp-cards' }, cards.map(cardEl)),
      rk.notes ? h('section', { class: 'rp-notes' }, [h('h2', { class: 'rp-h', text: 'Notes' }), h('p', { text: rk.notes })]) : null,
    ]));
  }

  function faceLink(f) {
    return h('a', {
      class: 'rp-face', 'data-face': f, href: tabHref('elevation', f), 'aria-current': f === face ? 'true' : null,
      text: f === 'front' ? 'Front' : 'Rear',
    });
  }

  function renderElevation(rk) {
    faceSeg = h('nav', { class: 'rp-faces', 'aria-label': 'Rack face' }, [faceLink('front'), faceLink('rear')]);
    const add = readOnly() || typeof ctx.pickDevice !== 'function' ? null
      : h('button', { type: 'button', class: 'rk-btn rp-add', text: 'Add device\u2026' });
    const host = h('div', { class: 'rp-elev' });
    body.appendChild(h('div', { class: 'rp-panel rp-elevation', 'data-tab': 'elevation' }, [
      h('div', { class: 'rp-bar' }, [faceSeg, add]),
      host,
    ]));
    elev = createElevation(host, ctx, { rack: rk.id, face: face });
    if (add) add.addEventListener('click', function () { if (elev) elev.addDevice(); });
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
    table.setRows(tab === 'devices' ? deviceRows(d, rk) : cableRows(d, rackDevices(d, rk.id).map(function (p) { return p.device; })));
  }

  function renderPanel() {
    clearPanel();
    const rk = rack();
    if (!rk) return;
    if (tab === 'elevation') renderElevation(rk);
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
    const res = resolveTab(rackTabs(), r.tab);
    const sub = r.sub || '';
    let redirect = res.redirect;
    let f = 'front';
    if (res.tab === 'elevation') {
      if (sub && sub !== 'front' && sub !== 'rear') redirect = true;
      f = sub === 'rear' ? 'rear' : 'front';
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
      ctx.navigateRoute({ tab: c.tab, sub: c.tab === 'elevation' && c.face === 'rear' ? 'rear' : '' }, { replace: true });
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
      if (elev) elev.setFace(face);
      if (faceSeg) {
        Array.prototype.forEach.call(faceSeg.querySelectorAll('.rp-face'), function (a) {
          if (a.getAttribute('data-face') === face) a.setAttribute('aria-current', 'true');
          else a.removeAttribute('aria-current');
        });
      }
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
    eh.update(headerOpts(rk));
    if (tab === 'overview') renderPanel();
    else refreshTable();
  }

  function onSelection(e) {
    if (!table) return;
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
