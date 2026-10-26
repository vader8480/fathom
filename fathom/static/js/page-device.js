// Device landing and device page (docs/ui-audit.md B.3 PDEV, D1, D4, D5).
//
//   #/<p>/<room>/devices                      landing: DataTable `devices` (URL state), rows navigate
//   #/<p>/<room>/devices/<id>/<tab>[/<sub>]   page: explorer + sticky entity header + URL tabs
//
// The page is read-mostly: every tab is a DataTable or a summary, and editing
// happens in the drawer (ctx.openDrawer). `sub` (or `?hl=`) names a row of the
// active tab to highlight, e.g. devices/foh-cl5/ports/omni-in-3.

import { h, on } from './dom.js';
import {
  deviceTitle, devicePorts, portRef, mediumInfo, disciplineOf, formatLength,
  duplicateDeviceOps, deleteDeviceOps, addDeviceFromTemplateOps,
} from './model-core.js';
import { mountExplorer } from './explorer.js';
import { mountEntityHeader } from './entity-header.js';
import { deviceFacts, deviceTabs, resolveTab, summaryCards, statusPill, rackPosition, tabLabel } from './entity-core.js';
import { createTable, openTableDialog } from './datatable.js';
import { inlineError, reviewBadge, confirmScope, skeleton, emptyState } from './feedback.js';
import { bulkAdd } from './wizard.js';
import { fetchDuplicates, openMergeDialog } from './merge-ui.js';
import { openTraceDrawer } from './trace-ui.js';
import { pagesForDevice } from './views-sop.js';
import { channelLabel, groupOf, GROUPS, sortChannels } from './console-core.js';

const DOT = ' \u00b7 ';
const GLYPH = '\u25EB';
const TABLE_KEYS = ['q', 'sort', 'pg', 'hl'];
// Tabs every device has; the collapsed explorer rail links to these (DMX and Channels vary per device).
const RAIL_TABS = [
  { key: 'overview', glyph: 'O' }, { key: 'ports', glyph: 'P' }, { key: 'cables', glyph: 'C' },
  { key: 'network', glyph: 'N' }, { key: 'inventory', glyph: 'I' }, { key: 'procedures', glyph: '\u2611' },
  { key: 'files', glyph: 'F' },
];

function str(v) {
  return v === undefined || v === null ? '' : String(v);
}

function plural(n, one, many) {
  return n + ' ' + (n === 1 ? one : many);
}

function find(list, id) {
  if (!id) return null;
  for (let i = 0; i < (list || []).length; i++) if (list[i] && list[i].id === id) return list[i];
  return null;
}

function fmtSize(n) {
  const v = Number(n);
  if (!isFinite(v) || v <= 0) return '';
  if (v < 1024) return v + ' B';
  if (v < 1024 * 1024) return Math.round(v / 102.4) / 10 + ' KB';
  return Math.round(v / 104857.6) / 10 + ' MB';
}

function fmtDate(s) {
  if (!s) return '';
  const d = new Date(s);
  if (isNaN(d.getTime())) return String(s);
  return d.toISOString().slice(0, 10);
}

export function mount(el, ctxIn) {
  const ctx = ctxIn || {};
  const store = ctx.store;
  const S = {
    route: ctx.route || { id: '', tab: '', sub: '', query: {}, room: '' },
    mode: '', id: '', tab: '', device: null,
    root: null, table: null, ex: null, eh: null, body: null,
    dups: {}, dupsFor: {}, timer: 0, destroyed: false, pending: 0,
    skel: null, boot: 0, focusSel: null,
  };
  const offs = [];

  // ------------------------------------------------------------ ctx helpers

  function doc() { return (store && store.doc) || {}; }
  function vocab() { return ctx.vocab || (store && store.vocab) || {}; }
  function ro() { return !store || !!store.readOnly; }
  function index() { return store && store.index ? store.index : { cablesByDevice: {}, cablesByPort: {}, ports: {} }; }
  function room() { return (store && store.room) || S.route.room || ''; }
  function href(partial) { return typeof ctx.routeHref === 'function' ? ctx.routeHref(partial) : '#'; }
  function go(partial, opts) { if (typeof ctx.navigateRoute === 'function') ctx.navigateRoute(partial, opts); }
  function drawer(sel, section) {
    if (typeof ctx.openDrawer === 'function') ctx.openDrawer(sel, section ? { section: section } : undefined);
  }
  function toast(msg, level) { if (typeof ctx.toast === 'function') ctx.toast(msg, level); }
  function commit(ops, label) { return typeof ctx.commit === 'function' ? ctx.commit(ops, label) : null; }
  // Problem reports live in the document; ctx.problems() holds validation warnings, which name no device.
  function problems() {
    const p = doc().problems;
    return Array.isArray(p) ? p : [];
  }
  function docReady() { return !!(store && store.doc); }
  function later(fn) {
    Promise.resolve().then(function () { if (!S.destroyed) fn(); });
  }
  function tableUrl() {
    return {
      get: function () { return (ctx.route && ctx.route.query) || {}; },
      set: function (patch) { if (typeof ctx.setParams === 'function') ctx.setParams(patch); },
    };
  }
  // The drawer keys survive a tab switch; the previous tab's table keys do not.
  function keptQuery() {
    const q = (ctx.route && ctx.route.query) || {};
    const out = {};
    Object.keys(q).forEach(function (k) {
      if (TABLE_KEYS.indexOf(k) < 0 && k.indexOf('f.') !== 0) out[k] = q[k];
    });
    return out;
  }

  function roomName(id) {
    if (id === '*') return 'All rooms';
    if (!id) return 'Shared inventory';
    const r = find(doc().rooms, id);
    return r ? (r.name || r.id) : id;
  }
  function kindLabel(d) {
    const k = (vocab().kinds || {})[d.kind];
    return (k && k.label) || str(d.kind);
  }
  function discOf(d) {
    const key = disciplineOf(d, vocab());
    const discs = vocab().disciplines || {};
    return { key: key, label: (discs[key] && discs[key].label) || key };
  }
  function model(d) {
    return ((d.manufacturer || '') + ' ' + (d.model || '')).trim();
  }
  function primaryIp(d) {
    const ifs = (d.interfaces || []).filter(function (i) { return i && i.ip; });
    const p = ifs.filter(function (i) { return i.role === 'primary'; })[0] || ifs[0];
    return p ? String(p.ip) : '';
  }
  function patchedCount(d) {
    const byPort = index().cablesByPort || {};
    return devicePorts(d).filter(function (p) { return (byPort[portRef(d.id, p.id)] || []).length > 0; }).length;
  }
  function openProblems(id) {
    return problems().filter(function (p) { return p && p.device === id && (p.status || 'open') === 'open'; });
  }
  function deviceRoomFor(target) {
    const r = room();
    return target && target.room && r !== '*' ? target.room : r;
  }
  function pageHref(target, tab, sub) {
    return href({ view: 'devices', id: target.id, tab: tab || '', sub: sub || '', room: deviceRoomFor(target), query: {} });
  }
  // DataTable `empty` callback: our copy when the table has no rows at all, the table's own
  // "No rows match" + Clear filters when filters hide every row.
  function emptyTable(build) {
    return function (state, info) {
      if (info && info.total) {
        return h('div', { class: 'pd-filtered' }, [
          h('p', { class: 'dt-empty-text' }, 'No rows match these filters.'),
          h('button', { type: 'button', class: 'dt-clear', onclick: function () { if (S.table) S.table.setState({ q: '', filters: {} }); } }, 'Clear filters'),
        ]);
      }
      const node = build();
      node.classList.add('pd-empty');
      return node;
    };
  }
  function patchHref(d) {
    const lg = typeof ctx.layout !== 'function' || ctx.layout() === 'lg';
    return href({ view: 'patch', id: '', tab: '', sub: '', room: d.room || room(), query: { sel: 'device:' + d.id, drawer: lg ? null : '0' } });
  }
  function scoped() {
    const r = room();
    return (doc().devices || []).filter(function (d) {
      return d && d.id && !d.auto && (r === '*' || (d.room || '') === r);
    });
  }

  // ------------------------------------------------------------ store events

  function schedule() {
    if (S.timer) return;
    S.timer = setTimeout(function () { S.timer = 0; refresh(); }, 40);
  }
  if (store && typeof store.addEventListener === 'function') {
    offs.push(on(store, 'doc', schedule));
    offs.push(on(store, 'overlay', schedule));
  }

  function refresh() {
    if (S.destroyed) return;
    if (S.skel) { boot(); return; }
    if (S.mode === 'landing') {
      if (S.table) S.table.setRows(landingRows());
      if (S.landSub) S.landSub.textContent = landingSub();
      return;
    }
    if (S.mode !== 'page') return;
    const d = find(doc().devices, S.id);
    if (!d) { showDevice(S.route); return; }
    S.device = d;
    if (S.ex) S.ex.setItems(explorerItems());
    if (S.eh) S.eh.update(headerOpts(d));
    const tabs = deviceTabs(doc(), d);
    if (tabs.indexOf(S.tab) < 0) { showDevice(S.route); return; }
    if (S.tabRows && S.table) S.table.setRows(S.tabRows());
    else renderTab();
  }

  // ------------------------------------------------------------ landing

  function landingRows() {
    const r = room();
    return scoped().map(function (d) {
      const ports = devicePorts(d).length;
      const probs = openProblems(d.id).length;
      const dups = S.dups[d.id] || 0;
      return {
        id: d.id, d: d, title: deviceTitle(d), kind: kindLabel(d), model: model(d), room: roomName(d.room || ''),
        rack: rackPosition(doc(), d), status: (statusPill(d.status || 'installed') || {}).label || '', ip: primaryIp(d),
        ports: ports ? ports + ' / ' + patchedCount(d) + ' patched' : '', problems: probs, dups: dups,
        review: probs + dups, href: href({ view: 'devices', id: d.id, room: r, query: {} }),
      };
    });
  }

  function reviewCell(row) {
    if (!row.review) return null;
    const bits = [];
    if (row.problems) bits.push(plural(row.problems, 'open problem', 'open problems'));
    if (row.dups) bits.push(plural(row.dups, 'possible duplicate', 'possible duplicates'));
    return reviewBadge({
      count: row.review, title: bits.join(DOT),
      onClick: function () { drawer({ type: 'device', id: row.id, device: row.id }, row.problems ? 'problems' : 'dups'); },
    });
  }

  function landingColumns() {
    return [
      { key: 'name', header: 'Name', value: function (r) { return r.title; }, sticky: true,
        cell: function (r) { return h('a', { class: 'pd-link', href: r.href, 'data-device': r.id }, r.title); } },
      { key: 'kind', header: 'Kind', value: function (r) { return r.kind; }, filterable: true },
      { key: 'model', header: 'Model', value: function (r) { return r.model; }, hideOnMobile: true },
      { key: 'room', header: 'Room', value: function (r) { return r.room; }, filterable: true },
      { key: 'rack', header: 'Rack \u00b7 U', value: function (r) { return r.rack; }, hideOnMobile: true },
      { key: 'status', header: 'Status', value: function (r) { return r.status; }, filterable: true },
      { key: 'ip', header: 'IP', value: function (r) { return r.ip; }, hideOnMobile: true },
      { key: 'ports', header: 'Ports', value: function (r) { return r.ports; }, hideOnMobile: true },
      { key: 'review', header: 'Review', value: function (r) { return r.review || ''; }, cell: reviewCell,
        csv: function (r) { return r.review ? String(r.review) : ''; }, searchable: false },
    ];
  }

  function addDevice() {
    if (typeof ctx.pickTemplate !== 'function') return;
    Promise.resolve(ctx.pickTemplate({})).then(function (t) {
      if (!t || S.destroyed) return;
      const r = room();
      const target = r === '*' ? ((doc().settings && doc().settings.default_room) || '') : r;
      const res = addDeviceFromTemplateOps(doc(), t, { room: target, vocab: vocab() });
      if (!commit(res.ops, 'Add ' + (t.name || t.model || t.id))) return;
      if (res.id) go({ view: 'devices', id: res.id, query: {} });
    }).catch(function (e) { toast((e && e.message) || 'Could not add the device', 'err'); });
  }

  function loadDuplicates(onDone) {
    if (!ctx.api || !ctx.project) return;
    fetchDuplicates(ctx, { limit: 100 }).then(function (list) {
      if (S.destroyed) return;
      const counts = {};
      (list || []).forEach(function (s) {
        (s.devices || []).forEach(function (x) { if (x && x.id) counts[x.id] = (counts[x.id] || 0) + 1; });
      });
      S.dups = counts;
      onDone();
    }, function () { /* duplicates are advisory */ });
  }

  function landingSub() {
    return roomName(room()) + DOT + plural(scoped().length, 'device', 'devices');
  }

  function renderLanding() {
    teardown();
    S.mode = 'landing';
    const r = room();
    const actions = [];
    if (!ro()) {
      actions.push(h('button', { type: 'button', class: 'primary pd-add', 'data-action': 'add', onclick: addDevice }, 'Add device'));
      actions.push(h('button', { type: 'button', class: 'pd-bulk', 'data-action': 'bulk',
        onclick: function () { bulkAdd(ctx, { kind: 'devices', room: r === '*' ? '' : r }); } }, 'Bulk add'));
    }
    const root = h('div', { class: 'pd-root pd-is-landing' }, [
      h('div', { class: 'pd-landing' }, [
        h('header', { class: 'pd-head' }, [
          h('h1', { class: 'pd-title' }, [h('span', { class: 'pd-glyph', 'aria-hidden': 'true' }, GLYPH), 'Devices']),
          h('p', { class: 'pd-sub' }, landingSub()),
        ]),
      ]),
    ]);
    el.appendChild(root);
    S.root = root;
    S.landSub = root.querySelector('.pd-sub');
    S.table = createTable(root.firstChild, {
      key: 'devices', scope: ctx.project || '', caption: 'Devices' + DOT + roomName(r),
      columns: landingColumns(), rows: landingRows(),
      onRow: function (row) { go({ view: 'devices', id: row.id, query: {} }); },
      url: tableUrl(), highlight: S.route.query.hl || null, actions: actions,
      noun: { one: 'device', many: 'devices' }, csvName: 'devices-' + (r === '*' ? 'all' : r) + '.csv',
      empty: emptyTable(function () {
        const editor = !ro();
        return emptyState({
          title: r === '*' ? 'No devices in this project yet.' : 'No devices in ' + roomName(r) + ' yet.',
          text: editor ? 'Add one from a template, or bulk add them from a spreadsheet.' : 'Devices appear here once an editor documents them.',
          action: editor ? { label: 'Add device', run: addDevice } : null,
          secondary: editor ? { label: 'Bulk add', run: function () { bulkAdd(ctx, { kind: 'devices', room: r === '*' ? '' : r }); } } : null,
        });
      }),
    });
    if (typeof ctx.setTitle === 'function') ctx.setTitle('Devices');
    loadDuplicates(function () { if (S.mode === 'landing' && S.table) S.table.setRows(landingRows()); });
  }

  // ------------------------------------------------------------ page: explorer + header

  function explorerItems() {
    const discs = Object.keys(vocab().disciplines || {});
    const tab = S.tab && S.tab !== 'overview' ? S.tab : '';
    return scoped().map(function (d) {
      const disc = discOf(d);
      const probs = openProblems(d.id).length;
      return {
        id: d.id, label: deviceTitle(d), sub: model(d) || kindLabel(d), group: disc.label, disc: disc.key,
        badge: probs ? '\u26A0\uFE0E ' + probs : null, href: pageHref(d, tab), order: discs.indexOf(disc.key),
      };
    }).sort(function (a, b) {
      const oa = a.order < 0 ? 999 : a.order;
      const ob = b.order < 0 ? 999 : b.order;
      return oa - ob || a.label.localeCompare(b.label);
    });
  }

  function disciplineChips() {
    const discs = vocab().disciplines || {};
    const seen = {};
    scoped().forEach(function (d) { seen[disciplineOf(d, vocab())] = true; });
    return Object.keys(discs).filter(function (k) { return seen[k]; }).map(function (k) {
      return { key: k, label: discs[k].label || k, test: function (item) { return item.disc === k; } };
    });
  }

  function railItems(d) {
    return RAIL_TABS.map(function (t) {
      return { key: t.key, label: tabLabel(t.key), glyph: t.glyph, href: d ? pageHref(d, t.key) : null, active: t.key === S.tab };
    });
  }

  // The explorer renders its rail once; keep its links on the current device and tab.
  function syncRail() {
    if (!S.ex) return;
    const d = S.device;
    Array.prototype.forEach.call(S.ex.root.querySelectorAll('.ex-rail-item[data-key]'), function (a) {
      const key = a.getAttribute('data-key');
      if (d) a.setAttribute('href', pageHref(d, key)); else a.removeAttribute('href');
      if (key === S.tab) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
  }

  function mountPage() {
    teardown();
    S.mode = 'page';
    const r = room();
    const root = h('div', { class: 'pd-root pd-is-page' });
    el.appendChild(root);
    S.root = root;
    S.ex = mountExplorer(root, {
      key: 'devices', title: 'Devices', glyph: GLYPH, items: [], chips: disciplineChips(),
      selected: S.route.id || null, mobileLabel: 'Devices', rail: railItems(null), contentLabel: 'Device',
      footer: function (shown, total) {
        return (shown === total ? plural(total, 'device', 'devices') : shown + ' of ' + plural(total, 'device', 'devices')) + DOT + roomName(r);
      },
    });
    S.body = h('div', { class: 'pd-body' });
    S.ex.content.appendChild(S.body);
  }

  function counts(d) {
    const idx = index();
    return {
      ports: devicePorts(d).length,
      cables: (idx.cablesByDevice[d.id] || []).length,
      network: (d.interfaces || []).filter(Boolean).length,
      channels: (d.channels || []).filter(function (c) { return c && c.id; }).length,
      procedures: procedures(d).length,
      files: files(d).length,
    };
  }

  function headerOpts(d) {
    const tabs = deviceTabs(doc(), d);
    const n = counts(d);
    const probs = openProblems(d.id).length;
    const dups = S.dupsFor[d.id] || 0;
    const badges = [];
    if (probs) badges.push({ label: plural(probs, 'open problem', 'open problems'), level: 'warn', title: 'Show the problem reports',
      onClick: function () { drawer({ type: 'device', id: d.id, device: d.id }, 'problems'); } });
    if (dups) badges.push({ label: plural(dups, 'possible duplicate', 'possible duplicates'), level: 'warn', title: 'Review likely duplicates',
      onClick: function () { drawer({ type: 'device', id: d.id, device: d.id }, 'dups'); } });
    const pub = (ctx.appRoot || '') + 'p/' + encodeURIComponent(ctx.project || '') + '/d/' + encodeURIComponent(d.id);
    const actions = [
      { key: 'edit', label: ro() ? 'Details' : 'Edit', primary: true, run: function () { drawer({ type: 'device', id: d.id, device: d.id }); } },
      { key: 'patch', label: 'Show in patch view', run: function () {
        if (typeof ctx.navigate === 'function') ctx.navigate('patch', { sel: 'device:' + d.id, room: d.room || undefined });
      } },
      ctx.api ? { key: 'trace', label: 'Trace', run: function () { trace(d); } } : null,
      { key: 'public', label: 'Public page', href: pub, target: '_blank' },
    ];
    const overflow = [];
    if (!ro()) overflow.push({ key: 'duplicate', label: 'Duplicate', run: function () { duplicate(d); } });
    if (!ro() && ctx.api) overflow.push({ key: 'merge', label: 'Merge\u2026', run: function () { merge(d); } });
    if (ctx.api && typeof ctx.api.qrUrl === 'function') overflow.push({ key: 'qr', label: 'QR code', href: ctx.api.qrUrl(ctx.project, d.id), target: '_blank' });
    if (!ro()) {
      if (overflow.length) overflow.push({ separator: true });
      overflow.push({ key: 'delete', label: 'Delete', danger: true, run: function () { remove(d); } });
    }
    return {
      kind: 'device', id: d.id, glyph: GLYPH, title: deviceTitle(d), subtitle: model(d) || kindLabel(d),
      status: statusPill(d.status || 'installed'),
      facts: deviceFacts(doc(), vocab(), d, store ? store.overlay : null, { href: function (view, id) {
        if (view === 'rooms') return href({ view: 'rooms', id: id, room: id, query: {} });
        return href({ view: view, id: id, query: {} });
      } }),
      badges: badges, actions: actions, overflow: overflow,
      tabs: tabs.map(function (k) {
        return { key: k, label: tabLabel(k), count: n[k] === undefined ? null : n[k], href: pageHref(d, k) };
      }),
      activeTab: S.tab,
      onTab: function (key, e) {
        e.preventDefault();
        go({ tab: key, sub: '', query: keptQuery() });
      },
    };
  }

  function trace(d) {
    openTraceDrawer({
      from: d.id, title: deviceTitle(d), sub: 'all ports', direction: 'down', dca: true,
      fetchPaths: function (params) { return ctx.api.trace(ctx.project, params); },
      actions: [{ label: 'Open in patch view', onclick: function (st) {
        st.close();
        if (typeof ctx.navigate === 'function') ctx.navigate('patch', { sel: 'device:' + d.id });
      } }],
      onHop: function (hop) {
        if (!hop || !hop.device) return;
        if (hop.kind === 'channel' || hop.kind === 'dca') drawer({ type: 'channel', id: hop.device, device: hop.device, channel: hop.channel });
        else if (hop.port) drawer({ type: 'port', id: hop.device, device: hop.device, port: hop.port });
        else drawer({ type: 'device', id: hop.device, device: hop.device });
      },
    });
  }

  function duplicate(d) {
    const res = duplicateDeviceOps(doc(), d.id);
    if (!commit(res.ops, 'Duplicate ' + deviceTitle(d))) return;
    if (res.id) go({ view: 'devices', id: res.id, query: {} });
  }

  function merge(d) {
    if (typeof ctx.pickDevice !== 'function') return;
    Promise.resolve(ctx.pickDevice({ title: 'Merge ' + deviceTitle(d) + ' with which device?', exclude: [d.id] })).then(function (other) {
      if (!other || other === d.id || S.destroyed) return;
      openMergeDialog(ctx, [d.id, other], { survivor: d.id });
    });
  }

  function remove(d) {
    const n = (index().cablesByDevice[d.id] || []).length;
    confirmScope(ctx, {
      verb: 'Delete', noun: deviceTitle(d), scope: d.room ? roomName(d.room) : '', danger: true,
      detail: n ? plural(n, 'connected cable is', 'connected cables are') + ' deleted too.' : '',
    }).then(function (yes) {
      if (!yes || S.destroyed) return;
      if (!commit(deleteDeviceOps(doc(), d.id), 'Delete ' + deviceTitle(d))) return;
      if (typeof ctx.closeDrawer === 'function' && store && store.selection) ctx.closeDrawer();
      go({ view: 'devices', id: '', tab: '', sub: '', query: {} });
    });
  }

  function loadDeviceDuplicates(d) {
    if (!ctx.api || !ctx.project) return;
    const id = d.id;
    fetchDuplicates(ctx, { device: id }).then(function (list) {
      const n = (list || []).length;
      if (S.destroyed || (S.dupsFor[id] || 0) === n) return;
      S.dupsFor[id] = n;
      if (S.mode === 'page' && S.id === id && S.eh && S.device) S.eh.update(headerOpts(S.device));
    }, function () { /* advisory */ });
  }

  function notFound(id) {
    if (S.eh) { S.eh.destroy(); S.eh = null; }
    destroyTable();
    S.device = null;
    S.body.textContent = '';
    const err = inlineError(new Error('Device \u201c' + id + '\u201d not found'), null, { compact: true });
    err.classList.add('pd-notfound');
    S.body.appendChild(err);
    S.body.appendChild(h('p', null, h('a', { class: 'pd-back', href: href({ view: 'devices', id: '', tab: '', sub: '', query: {} }) }, '\u2190 All devices')));
    if (typeof ctx.setTitle === 'function') ctx.setTitle('Device not found');
    syncRail();
  }

  function showDevice(r) {
    if (S.mode !== 'page') mountPage();
    const d = find(doc().devices, r.id);
    S.id = r.id;
    S.ex.setItems(explorerItems());
    S.ex.setSelected(r.id);
    if (!d) { S.tab = ''; notFound(r.id); return; }
    const res = resolveTab(deviceTabs(doc(), d), r.tab);
    S.device = d;
    S.tab = res.tab;
    S.ex.setItems(explorerItems());
    if (S.eh) S.eh.update(headerOpts(d));
    else S.eh = mountEntityHeader(S.ex.content, headerOpts(d));
    syncRail();
    renderTab();
    if (ctx.recent && typeof ctx.recent.push === 'function') ctx.recent.push('device', d.id);
    if (typeof ctx.setTitle === 'function') ctx.setTitle(deviceTitle(d));
    loadDeviceDuplicates(d);
    if (res.redirect) later(function () { if (S.id === d.id) go({ tab: res.tab, sub: '' }, { replace: true }); });
  }

  function showTab(r) {
    const d = S.device;
    const res = resolveTab(deviceTabs(doc(), d), r.tab);
    S.tab = res.tab;
    if (S.eh) S.eh.setTab(res.tab);
    S.ex.setItems(explorerItems());
    syncRail();
    renderTab();
    if (res.redirect) later(function () { if (S.id === d.id) go({ tab: res.tab, sub: '' }, { replace: true }); });
  }

  // ------------------------------------------------------------ tabs

  function destroyTable() {
    if (S.table) { S.table.destroy(); S.table = null; }
    S.tabRows = null;
  }

  function highlightId() {
    return str(S.route.query.hl) || str(S.route.sub) || null;
  }

  function tabTable(host, key, spec) {
    S.tabRows = spec.rows;
    S.table = createTable(host, Object.assign({
      key: key, scope: ctx.project || '', url: tableUrl(), highlight: highlightId(), pageSize: 50,
      rows: spec.rows(),
    }, spec.opts));
    return S.table;
  }

  function renderTab() {
    destroyTable();
    const d = S.device;
    const body = S.body;
    body.textContent = '';
    body.setAttribute('data-tab', S.tab);
    const name = deviceTitle(d);
    const fn = TABS[S.tab] || TABS.overview;
    fn(body, d, name);
  }

  function portRows(d, onlyRefs) {
    const idx = index();
    const docNow = doc();
    const want = onlyRefs ? {} : null;
    if (want) onlyRefs.forEach(function (r) { want[r] = true; });
    return devicePorts(d).filter(function (p) { return p && p.id && (!want || want[portRef(d.id, p.id)]); }).map(function (p) {
      const cables = idx.cablesByPort[portRef(d.id, p.id)] || [];
      const c = cables[0] || null;
      let far = null;
      if (c) {
        const end = c.from && c.from.device === d.id && c.from.port === p.id ? c.to : c.from;
        const fd = end ? find(docNow.devices, end.device) : null;
        const fp = fd ? devicePorts(fd).filter(function (x) { return x.id === end.port; })[0] : null;
        far = end ? { device: fd, id: end.device, port: end.port, text: (fd ? deviceTitle(fd) : end.device) + DOT + (fp ? (fp.name || fp.label || fp.id) : end.port) } : null;
      }
      return {
        id: p.id, ref: portRef(d.id, p.id), port: p.name || p.id, label: p.label || '', dir: p.dir || '',
        signal: p.medium ? mediumInfo(p.medium, vocab()).label : '', connector: p.connector || '', far: far,
        cable: c, tag: c ? (c.tag || '') : '', extra: cables.length > 1 ? cables.length - 1 : 0,
      };
    });
  }

  function farCell(row) {
    if (!row.far) return null;
    const target = row.far.device;
    const kids = [target ? h('a', { class: 'pd-link', href: pageHref(target, 'ports', row.far.port) }, row.far.text) : row.far.text];
    if (row.extra) kids.push(h('span', { class: 'pd-more' }, ' +' + row.extra));
    return h('span', null, kids);
  }

  function portColumns() {
    return [
      { key: 'port', header: 'Port', value: function (r) { return r.port; }, sticky: true },
      { key: 'label', header: 'Label', value: function (r) { return r.label; } },
      { key: 'dir', header: 'Dir', value: function (r) { return r.dir; }, filterable: true },
      { key: 'signal', header: 'Signal', value: function (r) { return r.signal; }, filterable: true, hideOnMobile: true },
      { key: 'connector', header: 'Connector', value: function (r) { return r.connector; }, filterable: true, hideOnMobile: true },
      { key: 'far', header: 'Connected to', value: function (r) { return r.far ? r.far.text : ''; }, cell: farCell },
      { key: 'tag', header: 'Cable tag', value: function (r) { return r.tag; } },
    ];
  }

  function openPort(d, row) { drawer({ type: 'port', id: d.id, device: d.id, port: row.id }); }

  function cableRows(d, onlyIds) {
    const idx = index();
    const units = (doc().settings && doc().settings.units) || 'metric';
    const want = onlyIds ? {} : null;
    if (want) onlyIds.forEach(function (id) { want[id] = true; });
    const list = want ? (doc().cables || []).filter(function (c) { return c && want[c.id]; }) : (idx.cablesByDevice[d.id] || []);
    return list.map(function (c) {
      const mine = c.from && c.from.device === d.id ? c.from : c.to;
      const other = mine === c.from ? c.to : c.from;
      const md = mine ? find(doc().devices, mine.device) : null;
      const od = other ? find(doc().devices, other.device) : null;
      const portName = function (dev, end) {
        const p = dev && end ? devicePorts(dev).filter(function (x) { return x.id === end.port; })[0] : null;
        return p ? (p.name || p.label || p.id) : (end ? str(end.port) : '');
      };
      return {
        id: c.id, c: c, tag: c.tag || '', here: portName(md, mine),
        other: other ? (od ? deviceTitle(od) : str(other.device)) + DOT + portName(od, other) : '',
        otherDev: od, otherPort: other ? other.port : '',
        signal: c.medium ? mediumInfo(c.medium, vocab()).label : '', type: c.type || '',
        length: formatLength(c.length_m, units), status: c.status || '',
      };
    });
  }

  function cableColumns() {
    return [
      { key: 'tag', header: 'Tag', value: function (r) { return r.tag; }, sticky: true },
      { key: 'here', header: 'This end', value: function (r) { return r.here; } },
      { key: 'other', header: 'Other end', value: function (r) { return r.other; }, cell: function (r) {
        return r.otherDev ? h('a', { class: 'pd-link', href: pageHref(r.otherDev, 'ports', r.otherPort) }, r.other) : r.other;
      } },
      { key: 'signal', header: 'Signal', value: function (r) { return r.signal; }, filterable: true, hideOnMobile: true },
      { key: 'type', header: 'Type', value: function (r) { return r.type; }, hideOnMobile: true },
      { key: 'length', header: 'Length', value: function (r) { return r.length; }, align: 'right', hideOnMobile: true },
      { key: 'status', header: 'State', value: function (r) { return r.status; }, filterable: true, hideOnMobile: true },
    ];
  }

  function procedures(d) {
    return pagesForDevice(doc(), d.id).filter(function (p) { return p && p.status !== 'archived'; });
  }
  function procRows(d) {
    return procedures(d).map(function (p) {
      return { id: p.slug || p.id, slug: p.slug || p.id, title: p.title || p.slug || p.id, kind: p.kind || 'sop',
        status: p.status || 'published', due: p.review_due || '' };
    });
  }
  function procColumns() {
    return [
      { key: 'title', header: 'Title', value: function (r) { return r.title; }, sticky: true, cell: function (r) {
        return h('a', { class: 'pd-link', href: href({ view: 'sop', id: '', tab: '', sub: '', query: { page: r.slug } }) }, r.title);
      } },
      { key: 'kind', header: 'Kind', value: function (r) { return r.kind; }, filterable: true },
      { key: 'status', header: 'Status', value: function (r) { return r.status; }, filterable: true },
      { key: 'due', header: 'Review due', value: function (r) { return r.due; }, hideOnMobile: true },
    ];
  }
  function openProc(row) { go({ view: 'sop', query: { page: row.slug } }); }

  function files(d) {
    return (doc().attachments || []).filter(function (a) { return a && a.device === d.id; });
  }
  function fileUrl(a) {
    return ctx.api && typeof ctx.api.fileUrl === 'function' ? ctx.api.fileUrl(ctx.project, a) : '';
  }
  function fileRows(d, onlyIds) {
    const want = onlyIds ? {} : null;
    if (want) onlyIds.forEach(function (id) { want[id] = true; });
    return files(d).filter(function (a) { return !want || want[a.id]; }).map(function (a) {
      return { id: a.id, a: a, name: a.name || a.id, kind: a.kind || a.mime || '', size: fmtSize(a.size), uploaded: fmtDate(a.uploaded), url: fileUrl(a) };
    });
  }
  function fileColumns() {
    return [
      { key: 'name', header: 'Name', value: function (r) { return r.name; }, sticky: true, cell: function (r) {
        return r.url ? h('a', { class: 'pd-link', href: r.url, target: '_blank', rel: 'noopener' }, r.name) : r.name;
      } },
      { key: 'kind', header: 'Kind', value: function (r) { return r.kind; }, filterable: true },
      { key: 'size', header: 'Size', value: function (r) { return r.size; }, align: 'right', hideOnMobile: true },
      { key: 'uploaded', header: 'Uploaded', value: function (r) { return r.uploaded; }, hideOnMobile: true },
    ];
  }
  function openFile(row) { if (row.url) window.open(row.url, '_blank', 'noopener'); }

  function problemRows(ids) {
    const want = {};
    (ids || []).forEach(function (id) { want[id] = true; });
    return problems().filter(function (p) { return p && want[p.id]; }).map(function (p) {
      return { id: p.id, text: p.title || p.text || p.summary || p.id, created: fmtDate(p.created), by: p.by || p.reporter || '' };
    });
  }

  const DRILL = {
    port: function (d, ids) {
      return { columns: portColumns(), rows: portRows(d, ids), onRow: function (row) { openPort(d, row); } };
    },
    cable: function (d, ids) {
      return { columns: cableColumns(), rows: cableRows(d, ids), onRow: function (row) { drawer({ type: 'cable', id: row.id }); } };
    },
    page: function (d) {
      return { columns: procColumns(), rows: procRows(d), onRow: openProc };
    },
    file: function (d, ids) {
      return { columns: fileColumns(), rows: fileRows(d, ids), onRow: openFile };
    },
    problem: function (d, ids) {
      return {
        columns: [
          { key: 'text', header: 'Report', value: function (r) { return r.text; } },
          { key: 'created', header: 'Reported', value: function (r) { return r.created; } },
          { key: 'by', header: 'By', value: function (r) { return r.by; }, hideOnMobile: true },
        ],
        rows: problemRows(ids),
        onRow: function () { drawer({ type: 'device', id: d.id, device: d.id }, 'problems'); },
      };
    },
  };

  function drill(d, card) {
    const fn = card.drill && DRILL[card.drill.kind];
    if (!fn) return;
    const spec = fn(d, card.drill.ids);
    openTableDialog(ctx, { title: card.drill.title, key: 'device.drill.' + card.drill.kind, columns: spec.columns, rows: spec.rows, onRow: spec.onRow });
  }

  function cardEl(d, card) {
    const canDrill = !!(card.drill && DRILL[card.drill.kind] && card.count > 0);
    const noun = card.label.toLowerCase();
    const countText = String(card.count);
    const count = canDrill
      ? h('button', { type: 'button', class: 'pd-count', 'data-drill': card.drill.kind, 'aria-label': 'List ' + card.count + ' ' + noun,
        onclick: function () { drill(d, card); } }, countText)
      : h('span', { class: 'pd-count' }, countText);
    return h('section', { class: 'pd-card', 'data-card': card.key }, [
      h('h3', { class: 'pd-card-title' }, card.label),
      count,
      card.sub ? h('p', { class: 'pd-card-sub' }, card.sub) : null,
      card.tab ? h('a', { class: 'pd-card-link', href: pageHref(d, card.tab), 'data-tab': card.tab,
        onclick: function (e) {
          if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
          e.preventDefault();
          go({ tab: card.tab, sub: '', query: keptQuery() });
        } }, 'Open ' + tabLabel(card.tab) + ' \u203A') : null,
    ]);
  }

  function editButton(d, label, section) {
    return h('button', { type: 'button', class: 'pd-edit', 'data-section': section,
      onclick: function () { drawer({ type: 'device', id: d.id, device: d.id }, section); } }, ro() ? 'Details' : label);
  }

  // o: {title, editor, viewer, write: action for editors only, nav: action for everyone}.
  function tabEmpty(o) {
    const editor = !ro();
    return emptyState({
      title: o.title,
      text: editor ? o.editor : o.viewer,
      action: (editor && o.write) || o.nav || null,
      secondary: editor && o.write ? o.nav || null : null,
    });
  }
  function drawerAction(d, label, section) {
    return { label: label, run: function () { drawer({ type: 'device', id: d.id, device: d.id }, section); } };
  }
  const TAB_EMPTY = {
    ports: function (d, name) {
      return tabEmpty({ title: name + ' has no ports yet.', editor: 'Add its inputs and outputs in the inspector\u2019s Ports section.',
        viewer: 'Nobody has recorded its inputs and outputs yet.', write: drawerAction(d, 'Add ports', 'ports') });
    },
    cables: function (d, name) {
      return tabEmpty({ title: 'No cables connected to ' + name + '.', editor: 'Drag between its ports in the patch view to connect it.',
        viewer: 'Nothing is patched to it yet.', nav: { label: 'Open in patch view', href: patchHref(d) } });
    },
    network: function (d, name) {
      return tabEmpty({ title: 'No interfaces on ' + name + '.', editor: 'Add one in the inspector\u2019s Network section.',
        viewer: 'No IP address, MAC or hostname has been recorded.', write: drawerAction(d, 'Add interface', 'net') });
    },
    channels: function (d, name) {
      return tabEmpty({ title: 'No console channels on ' + name + '.', editor: 'Add channels in the inspector\u2019s Console channels section.',
        viewer: 'No channels have been recorded.', write: drawerAction(d, 'Add channels', 'console') });
    },
    inventory: function (d, name) {
      return tabEmpty({ title: 'No inventory details for ' + name + '.', editor: 'Record the serial, asset tag and warranty in the inspector\u2019s Inventory section.',
        viewer: 'No serial, asset tag or warranty has been recorded.', write: drawerAction(d, 'Add inventory details', 'inventory') });
    },
    procedures: function (d, name) {
      return tabEmpty({ title: 'No procedures mention ' + name + ' yet.',
        editor: 'Write an SOP page for it, or link it from a page with [[device:' + d.id + ']].',
        viewer: 'Procedures that list this device appear here.',
        write: { label: 'New procedure', href: href({ view: 'sop', id: '', tab: '', sub: '', query: { 'new': '1', device: d.id } }) } });
    },
    files: function (d, name) {
      return tabEmpty({ title: 'No photos or documents for ' + name + '.', editor: 'Upload them in the inspector\u2019s Photos & documents section.',
        viewer: 'Photos and manuals attached to it appear here.', write: drawerAction(d, 'Upload files', 'files') });
    },
  };
  function emptyFor(key, d, name) {
    return emptyTable(function () { return TAB_EMPTY[key](S.device || d, name); });
  }

  function factsList(items) {
    return h('dl', { class: 'pd-facts' }, items.map(function (f) {
      return h('div', { class: 'pd-fact', 'data-fact': f.key }, [h('dt', null, f.label), h('dd', null, f.value || '\u2014')]);
    }));
  }

  const TABS = {
    overview: function (body, d) {
      const cards = summaryCards('device', doc(), d, { problems: problems() });
      body.appendChild(h('div', { class: 'pd-cards' }, cards.map(function (c) { return cardEl(d, c); })));
      body.appendChild(h('section', { class: 'pd-notes' }, [
        h('h3', { class: 'pd-card-title' }, 'Notes'),
        d.note ? h('p', { class: 'pd-note' }, String(d.note)) : h('p', { class: 'pd-muted' }, 'No notes yet.'),
        editButton(d, d.note ? 'Edit notes' : 'Add a note', 'notes'),
      ]));
      S.tabRows = null;
    },
    ports: function (body, d, name) {
      tabTable(body, 'device.ports', { rows: function () { return portRows(S.device); }, opts: {
        caption: 'Ports' + DOT + name, columns: portColumns(), noun: { one: 'port', many: 'ports' },
        onRow: function (row) { openPort(S.device, row); }, csvName: d.id + '-ports.csv',
        empty: emptyFor('ports', d, name),
      } });
    },
    cables: function (body, d, name) {
      tabTable(body, 'device.cables', { rows: function () { return cableRows(S.device); }, opts: {
        caption: 'Cables' + DOT + name, columns: cableColumns(), noun: { one: 'cable', many: 'cables' },
        onRow: function (row) { drawer({ type: 'cable', id: row.id }); }, csvName: d.id + '-cables.csv',
        empty: emptyFor('cables', d, name),
      } });
    },
    network: function (body, d, name) {
      tabTable(body, 'device.net', { rows: function () {
        const nets = doc().networks || [];
        return (S.device.interfaces || []).filter(Boolean).map(function (i, k) {
          const net = find(nets, i.network);
          const sw = i.switch ? find(doc().devices, i.switch) : null;
          return {
            id: i.id || 'if-' + (k + 1), ip: i.ip || '', mac: i.mac || '', host: i.hostname || '', role: i.role || '',
            network: net ? (net.name || net.id) : str(i.network),
            sw: [i.switch ? (sw ? deviceTitle(sw) : i.switch) : '', i.switch_port || ''].filter(Boolean).join(DOT),
          };
        });
      }, opts: {
        caption: 'Network' + DOT + name, noun: { one: 'interface', many: 'interfaces' }, csvName: d.id + '-network.csv',
        columns: [
          { key: 'ip', header: 'IP', value: function (r) { return r.ip; }, sticky: true },
          { key: 'mac', header: 'MAC', value: function (r) { return r.mac; } },
          { key: 'host', header: 'Hostname', value: function (r) { return r.host; } },
          { key: 'role', header: 'Role', value: function (r) { return r.role; }, filterable: true },
          { key: 'network', header: 'Network', value: function (r) { return r.network; }, filterable: true },
          { key: 'sw', header: 'Switch port', value: function (r) { return r.sw; }, hideOnMobile: true },
        ],
        onRow: function () { drawer({ type: 'device', id: S.device.id, device: S.device.id }, 'net'); },
        empty: emptyFor('network', d, name),
      } });
    },
    dmx: function (body, d, name) {
      tabTable(body, 'device.dmx', { rows: function () {
        const x = S.device.dmx || {};
        return [{ id: 'dmx', universe: str(x.universe), address: str(x.address), footprint: str(x.footprint), mode: str(x.mode),
          protocol: str(x.protocol), channel: str(x.channel) }];
      }, opts: {
        caption: 'DMX' + DOT + name, csvName: d.id + '-dmx.csv', search: false, pageSizes: [25],
        columns: [
          { key: 'universe', header: 'Universe', value: function (r) { return r.universe; }, sticky: true },
          { key: 'address', header: 'Address', value: function (r) { return r.address; } },
          { key: 'footprint', header: 'Footprint', value: function (r) { return r.footprint; } },
          { key: 'mode', header: 'Mode', value: function (r) { return r.mode; } },
          { key: 'protocol', header: 'Protocol', value: function (r) { return r.protocol; }, hideOnMobile: true },
          { key: 'channel', header: 'Console channel', value: function (r) { return r.channel; }, hideOnMobile: true },
        ],
        onRow: function () { drawer({ type: 'device', id: S.device.id, device: S.device.id }, 'dmx'); },
      } });
    },
    channels: function (body, d, name) {
      const groupLabel = {};
      GROUPS.forEach(function (g) { groupLabel[g.id] = g.label; });
      tabTable(body, 'device.channels', { rows: function () {
        return sortChannels((S.device.channels || []).filter(function (c) { return c && c.id; })).map(function (c) {
          return { id: c.id, label: channelLabel(c), name: c.name || '', group: groupLabel[groupOf(c)] || '', kind: c.kind || '' };
        });
      }, opts: {
        caption: 'Channels' + DOT + name, noun: { one: 'channel', many: 'channels' }, csvName: d.id + '-channels.csv',
        columns: [
          { key: 'label', header: 'Channel', value: function (r) { return r.label; }, sticky: true },
          { key: 'name', header: 'Name', value: function (r) { return r.name; } },
          { key: 'group', header: 'Group', value: function (r) { return r.group; }, filterable: true },
          { key: 'kind', header: 'Kind', value: function (r) { return r.kind; }, filterable: true, hideOnMobile: true },
        ],
        onRow: function (row) { drawer({ type: 'channel', id: S.device.id, device: S.device.id, channel: row.id }); },
        empty: emptyFor('channels', d, name),
      } });
    },
    inventory: function (body, d, name) {
      const inv = d.inventory || {};
      const loc = find(doc().locations, d.location);
      const pill = statusPill(d.status || 'installed');
      S.tabRows = null;
      if (!['serial', 'asset_tag', 'purchase_date', 'warranty_until'].some(function (k) { return str(inv[k]).trim(); }) && !d.location) {
        const box = TAB_EMPTY.inventory(d, name);
        box.classList.add('pd-empty');
        body.appendChild(h('section', { class: 'pd-panel pd-inventory pd-inventory-empty' }, box));
        return;
      }
      body.appendChild(h('section', { class: 'pd-panel pd-inventory' }, [
        factsList([
          { key: 'serial', label: 'Serial', value: str(inv.serial) },
          { key: 'asset_tag', label: 'Asset tag', value: str(inv.asset_tag) },
          { key: 'purchase_date', label: 'Purchased', value: str(inv.purchase_date) },
          { key: 'warranty_until', label: 'Warranty until', value: str(inv.warranty_until) },
          { key: 'location', label: 'Location', value: loc ? (loc.name || loc.id) : str(d.location) },
          { key: 'status', label: 'Status', value: pill ? pill.label : '' },
        ]),
        editButton(d, 'Edit inventory', 'inventory'),
      ]));
      S.tabRows = null;
    },
    procedures: function (body, d, name) {
      tabTable(body, 'device.procedures', { rows: function () { return procRows(S.device); }, opts: {
        caption: 'Procedures' + DOT + name, columns: procColumns(), noun: { one: 'procedure', many: 'procedures' },
        onRow: openProc, csvName: d.id + '-procedures.csv',
        empty: emptyFor('procedures', d, name),
      } });
    },
    files: function (body, d, name) {
      tabTable(body, 'device.files', { rows: function () { return fileRows(S.device); }, opts: {
        caption: 'Files' + DOT + name, columns: fileColumns(), noun: { one: 'file', many: 'files' },
        onRow: openFile, csvName: d.id + '-files.csv',
        empty: emptyFor('files', d, name),
      } });
    },
  };

  // ------------------------------------------------------------ lifecycle

  function teardown() {
    destroyTable();
    if (S.eh) { S.eh.destroy(); S.eh = null; }
    if (S.ex) { S.ex.destroy(); S.ex = null; }
    if (S.root && S.root.parentNode) S.root.parentNode.removeChild(S.root);
    S.root = null;
    S.body = null;
    S.landSub = null;
    S.device = null;
    S.mode = '';
  }

  function apply(r, prev) {
    S.route = r;
    if (!r.id) {
      if (S.mode !== 'landing' || !prev || prev.room !== r.room) { renderLanding(); return; }
      if (S.table) {
        S.table.readUrl();
        if (str(r.query.hl) !== str(prev.query.hl)) S.table.setHighlight(r.query.hl || null);
      }
      return;
    }
    if (S.mode !== 'page' || !prev || prev.id !== r.id || prev.room !== r.room || !S.device) { showDevice(r); return; }
    if (r.tab !== prev.tab) {
      if (r.tab && r.tab === S.tab) return;
      showTab(r);
      return;
    }
    if (S.table) {
      if (r.sub !== prev.sub || str(r.query.hl) !== str(prev.query.hl)) S.table.setHighlight(highlightId());
      S.table.readUrl();
    }
  }

  // First render: a page-shaped skeleton until the doc is ready, replaced by the content on a later
  // task so mount() returns (and the shell paints its frame) before the tables are built.
  function boot() {
    if (S.boot) { clearTimeout(S.boot); S.boot = 0; }
    if (S.destroyed || !S.skel || !docReady()) return;
    const sk = S.skel;
    S.skel = null;
    apply(S.route, null);
    if (sk.parentNode) sk.parentNode.removeChild(sk);
    if (S.focusSel) { const sel = S.focusSel; S.focusSel = null; focusSel(sel); }
  }

  function focusSel(sel) {
    if (S.destroyed || S.mode !== 'page' || !S.table || !sel || sel.device !== S.id) return;
    if (sel.type === 'port' && S.tab === 'ports') S.table.setHighlight(sel.port);
    else if (sel.type === 'channel' && S.tab === 'channels') S.table.setHighlight(sel.channel);
  }

  S.skel = skeleton(S.route.id ? 'page' : 'table');
  S.skel.classList.add('pd-skeleton');
  el.appendChild(S.skel);
  S.boot = setTimeout(boot, 0);

  return {
    route: function (r) {
      if (S.destroyed || !r) return;
      if (S.skel) { S.route = r; return; }
      apply(r, S.route);
    },
    focus: function (sel) {
      if (S.skel) { S.focusSel = sel; return; }
      focusSel(sel);
    },
    destroy: function () {
      if (S.destroyed) return;
      if (S.boot) { clearTimeout(S.boot); S.boot = 0; }
      if (S.skel && S.skel.parentNode) S.skel.parentNode.removeChild(S.skel);
      S.skel = null;
      teardown();
      S.destroyed = true;
      if (S.timer) clearTimeout(S.timer);
      offs.forEach(function (off) { try { off(); } catch (e) { /* already gone */ } });
    },
  };
}
