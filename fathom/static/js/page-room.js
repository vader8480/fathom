// Room landing and room page (docs/ui-audit.md B.3 PROOM, A.3, D4, D5).
//
//   rooms                 DataTable of rooms; a row navigates to rooms/<id> (the shell sets the room
//                         segment and the store room to <id>).
//   rooms/<id>[/<tab>]    explorer of rooms + sticky entity header (roomFacts, floor plan thumbnail,
//                         room links) + URL tabs: overview (summary cards with drill-downs), devices,
//                         cables, racks (rows open the drawer), plans, procedures (rows navigate).
//
// Read-mostly (D5): editing stays in the drawer and in Settings ▸ Rooms.

import { h } from './dom.js';
import { mountExplorer } from './explorer.js';
import { mountEntityHeader } from './entity-header.js';
import { createTable, openTableDialog } from './datatable.js';
import { inlineError } from './feedback.js';
import { roomFacts, roomTabs, resolveTab, summaryCards, tabLabel, statusPill, primaryAddress, rackPosition, rackFacts } from './entity-core.js';
import { indexDoc, devicePorts, portLabel, portRef, deviceTitle, formatLength, mediumInfo } from './model-core.js';

const GLYPH = '\u25A3';
const DOT = ' \u00b7 ';
const TABLE_KEYS = ['q', 'sort', 'pg', 'hl'];
const NOUNS = {
  room: { one: 'room', many: 'rooms' }, device: { one: 'device', many: 'devices' }, cable: { one: 'cable', many: 'cables' },
  rack: { one: 'rack', many: 'racks' }, floorplan: { one: 'plan', many: 'plans' }, page: { one: 'procedure', many: 'procedures' },
  problem: { one: 'problem', many: 'problems' },
};
const TAB_KIND = { devices: 'device', cables: 'cable', racks: 'rack', plans: 'floorplan', procedures: 'page' };

function list(v) {
  return Array.isArray(v) ? v : [];
}

function str(v) {
  return v === undefined || v === null ? '' : String(v);
}

function cap(s) {
  const t = str(s).trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : '';
}

function byId(coll) {
  const m = {};
  list(coll).forEach(function (x) { if (x && x.id !== undefined) m[x.id] = x; });
  return m;
}

function plural(n, noun) {
  return n + ' ' + (n === 1 ? noun.one : noun.many);
}

function sortedRooms(doc) {
  return list(doc.rooms).filter(function (r) { return r && r.id; }).slice().sort(function (a, b) {
    return (a.order || 0) - (b.order || 0) || str(a.name || a.id).localeCompare(str(b.name || b.id));
  });
}

function firstPlan(doc, roomId) {
  return list(doc.floorplans).filter(function (f) { return f && f.room === roomId; }).slice().sort(function (a, b) {
    return (a.order || 0) - (b.order || 0);
  })[0] || null;
}

function isQueryTableKey(k) {
  return TABLE_KEYS.indexOf(k) >= 0 || k.indexOf('f.') === 0;
}

export function mount(el, ctx) {
  ctx = ctx || {};
  const store = ctx.store || null;
  const root = h('div', { class: 'pr-root' });
  el.appendChild(root);

  const S = {
    route: ctx.route || { id: '', tab: '', query: {} },
    mode: '',          // 'landing' | 'page'
    roomId: '',
    tab: '',
    room: null,
    ex: null,
    eh: null,
    body: null,
    table: null,
    timer: 0,
    redirect: 0,
    destroyed: false,
  };

  function doc() {
    return (store && store.doc) || {};
  }

  function vocab() {
    return ctx.vocab || (store && store.vocab) || {};
  }

  function readOnly() {
    return !!(store && store.readOnly) || ctx.role === 'viewer';
  }

  function href(partial) {
    return typeof ctx.routeHref === 'function' ? ctx.routeHref(partial) : '#';
  }

  function go(partial, opts) {
    if (typeof ctx.navigateRoute === 'function') ctx.navigateRoute(partial, opts);
  }

  function inspect(sel, section) {
    if (typeof ctx.openDrawer === 'function') ctx.openDrawer(sel, section ? { section: section } : undefined);
    else if (typeof ctx.select === 'function') ctx.select(sel);
  }

  function setTitle(text) {
    if (typeof ctx.setTitle === 'function') ctx.setTitle(text);
  }

  function roomHref(id, tab) {
    return href({ view: 'rooms', id: id, room: id, tab: tab || 'overview', sub: '' });
  }

  // Query kept across a tab switch: the selection (drawer) stays, the previous tab's table state goes.
  function tabQuery() {
    const q = Object.assign({}, (S.route && S.route.query) || {});
    Object.keys(q).forEach(function (k) { if (isQueryTableKey(k)) delete q[k]; });
    return q;
  }

  function goTab(tab) {
    if (tab === S.tab) return;
    go({ tab: tab, query: tabQuery() });
  }

  function tableUrl() {
    return {
      get: function () { return (S.route && S.route.query) || {}; },
      set: function (patch) { if (typeof ctx.setParams === 'function') ctx.setParams(patch, { replace: true }); },
    };
  }

  // ---------------------------------------------------------- record lookups

  function rowsFor(kind, ids) {
    const d = doc();
    if (kind === 'page') {
      const pages = {};
      list(d.pages).forEach(function (p) { if (p) pages[p.slug || p.id] = p; });
      return ids.map(function (id) { return pages[id]; }).filter(Boolean);
    }
    const coll = { device: 'devices', cable: 'cables', rack: 'racks', floorplan: 'floorplans', problem: 'problems' }[kind];
    const m = byId(d[coll]);
    return ids.map(function (id) { return m[id]; }).filter(Boolean);
  }

  function rowIdFor(kind) {
    if (kind === 'page') return function (p) { return p.slug || p.id; };
    return function (x) { return x.id; };
  }

  // ---------------------------------------------------------- columns per record kind

  function deviceName(d, id) {
    return d ? deviceTitle(d) : str(id);
  }

  function endText(idx, devs, end) {
    if (!end || !end.device) return '';
    const dev = devs[end.device];
    const p = end.port && idx.ports[end.device] ? idx.ports[end.device][end.port] : null;
    return deviceName(dev, end.device) + (end.port ? DOT + (p ? portLabel(p) : end.port) : '');
  }

  function columnsFor(kind) {
    const d = doc();
    const v = vocab();
    if (kind === 'device') {
      const idx = indexDoc(d);
      return [
        { key: 'name', header: 'Name', value: function (x) { return deviceTitle(x); } },
        { key: 'kind', header: 'Kind', filterable: true, value: function (x) { const k = (v.kinds || {})[x.kind]; return (k && k.label) || str(x.kind); } },
        { key: 'model', header: 'Model', hideOnMobile: true, value: function (x) { return [x.manufacturer, x.model].filter(Boolean).join(' '); } },
        { key: 'rack', header: 'Rack \u00b7 U', hideOnMobile: true, value: function (x) { return rackPosition(d, x); } },
        { key: 'status', header: 'Status', filterable: true, value: function (x) { const p = statusPill(x.status); return p ? p.label : ''; } },
        { key: 'ip', header: 'IP', hideOnMobile: true, value: function (x) { return primaryAddress(x); } },
        { key: 'ports', header: 'Ports', hideOnMobile: true, align: 'right', value: function (x) {
          const ports = devicePorts(x);
          if (!ports.length) return '';
          const patched = ports.filter(function (p) { return list(idx.cablesByPort[portRef(x.id, p.id)]).length > 0; }).length;
          return ports.length + ' / ' + patched + ' patched';
        } },
      ];
    }
    if (kind === 'cable') {
      const idx = indexDoc(d);
      const devs = idx.byId.devices;
      const units = (d.settings && d.settings.units) || 'metric';
      return [
        { key: 'tag', header: 'Tag', value: function (c) { return c.tag || c.id; } },
        { key: 'from', header: 'From', value: function (c) { return endText(idx, devs, c.from); } },
        { key: 'to', header: 'To', value: function (c) { return endText(idx, devs, c.to); } },
        { key: 'medium', header: 'Medium', filterable: true, value: function (c) { return c.medium ? mediumInfo(c.medium, v).label || c.medium : ''; } },
        { key: 'type', header: 'Type', hideOnMobile: true, value: function (c) { return str(c.type); } },
        { key: 'length', header: 'Length', hideOnMobile: true, align: 'right', value: function (c) { return formatLength(c.length_m, units); } },
      ];
    }
    if (kind === 'rack') {
      const locs = byId(d.locations);
      const fact = function (r, key) {
        const f = rackFacts(d, r).filter(function (x) { return x.key === key; })[0];
        return f ? f.value : '';
      };
      return [
        { key: 'name', header: 'Name', value: function (r) { return r.name || r.id; } },
        { key: 'location', header: 'Location', hideOnMobile: true, value: function (r) { const l = locs[r.location]; return l ? l.name || l.id : str(r.location); } },
        { key: 'height', header: 'Height', align: 'right', value: function (r) { return fact(r, 'height'); } },
        { key: 'used', header: 'Used', align: 'right', hideOnMobile: true, value: function (r) { return fact(r, 'used'); } },
        { key: 'free', header: 'Free', align: 'right', hideOnMobile: true, value: function (r) { return fact(r, 'free'); } },
        { key: 'devices', header: 'Devices', align: 'right', value: function (r) { return fact(r, 'devices'); } },
      ];
    }
    if (kind === 'floorplan') {
      return [
        { key: 'name', header: 'Name', value: function (f) { return f.name || f.id; } },
        { key: 'source', header: 'Source', hideOnMobile: true, filterable: true, value: function (f) { return str(f.source && f.source.kind).toUpperCase(); } },
        { key: 'markers', header: 'Devices placed', align: 'right', value: function (f) { return String(list(f.markers).length); } },
        { key: 'scale', header: 'Scale', hideOnMobile: true, value: function (f) { return f.calibration ? 'Calibrated' : ''; } },
      ];
    }
    if (kind === 'page') {
      return [
        { key: 'title', header: 'Title', value: function (p) { return p.title || p.slug || p.id; } },
        { key: 'kind', header: 'Kind', hideOnMobile: true, filterable: true, value: function (p) { return cap(p.kind); } },
        { key: 'status', header: 'Status', filterable: true, value: function (p) { return cap(p.status); } },
        { key: 'updated', header: 'Updated', hideOnMobile: true, value: function (p) { return str(p.updated).slice(0, 10); } },
      ];
    }
    if (kind === 'problem') {
      const devs = byId(d.devices);
      return [
        { key: 'text', header: 'Problem', value: function (p) { return p.text || p.message || p.id; } },
        { key: 'device', header: 'Device', value: function (p) { return p.device ? deviceName(devs[p.device], p.device) : ''; } },
        { key: 'created', header: 'Reported', hideOnMobile: true, value: function (p) { return str(p.created).slice(0, 10); } },
      ];
    }
    return [];
  }

  // Rows inside a page open the drawer (D4); plans and procedures change context, so they navigate.
  function onRowFor(kind) {
    if (kind === 'device') return function (x) { inspect({ type: 'device', id: x.id, device: x.id }); };
    if (kind === 'cable') return function (c) { inspect({ type: 'cable', id: c.id }); };
    if (kind === 'rack') return function (r) { inspect({ type: 'rack', id: r.id }); };
    if (kind === 'floorplan') return function (f) { go({ view: 'plan', id: f.id, room: f.room || S.roomId }); };
    if (kind === 'page') return function (p) { go({ view: 'sop', query: { page: p.slug || p.id } }); };
    if (kind === 'problem') return function () { go({ view: 'sop', query: { problems: '1' } }); };
    return null;
  }

  function emptyFor(kind, name) {
    return {
      device: 'No devices in ' + name + ' yet. Add gear in Patch.',
      cable: 'No cables connected to devices in ' + name + ' yet.',
      rack: 'No racks in ' + name + '. Add one in Racks.',
      floorplan: 'No floor plan for ' + name + '. Upload one in Plan.',
      page: 'No procedures apply to ' + name + ' yet.',
    }[kind] || 'Nothing here yet.';
  }

  function openDrill(card) {
    if (!card || !card.drill) return null;
    const kind = card.drill.kind;
    return openTableDialog(ctx, {
      title: card.drill.title,
      key: 'room.drill.' + kind,
      columns: columnsFor(kind),
      rows: rowsFor(kind, card.drill.ids),
      rowId: rowIdFor(kind),
      onRow: onRowFor(kind),
      empty: 'Nothing to show.',
    });
  }

  // ---------------------------------------------------------- lifecycle helpers

  function clear() {
    if (S.redirect) { clearTimeout(S.redirect); S.redirect = 0; }
    if (S.table) { S.table.destroy(); S.table = null; }
    if (S.eh) { S.eh.destroy(); S.eh = null; }
    if (S.ex) { S.ex.destroy(); S.ex = null; }
    S.body = null;
    S.room = null;
    S.tab = '';
    root.textContent = '';
    root.className = 'pr-root';
  }

  // ---------------------------------------------------------- landing

  function landingRows() {
    const d = doc();
    const venues = byId(d.venues);
    return sortedRooms(d).map(function (r) {
      const counts = {};
      summaryCards('room', d, r).forEach(function (c) { counts[c.key] = c.count; });
      const v = venues[r.venue];
      return {
        id: r.id, name: r.name || r.id, code: str(r.code), venue: v ? v.name || v.id : str(r.venue),
        devices: counts.devices || 0, cables: counts.cables || 0, racks: counts.racks || 0,
        plans: counts.plans || 0, procedures: counts.procedures || 0,
      };
    });
  }

  function renderLanding() {
    clear();
    S.mode = 'landing';
    S.roomId = '';
    root.classList.add('pr-is-landing');
    const d = doc();
    const venueCount = list(d.venues).length;
    const rows = landingRows();
    const lede = h('p', { class: 'pr-lede' }, plural(rows.length, NOUNS.room) + (venueCount === 1 ? DOT + (list(d.venues)[0].name || '') : ''));
    const host = h('div', { class: 'pr-landing-table' });
    root.appendChild(h('div', { class: 'pr-landing' }, [
      h('div', { class: 'pr-landing-head' }, [h('h1', { class: 'pr-title' }, [h('span', { class: 'pr-glyph', 'aria-hidden': 'true' }, GLYPH), 'Rooms']), lede]),
      host,
    ]));
    const num = function (key, header, hide) {
      return { key: key, header: header, align: 'right', hideOnMobile: !!hide, value: function (r) { return r[key]; } };
    };
    S.table = createTable(host, {
      key: 'rooms',
      scope: ctx.project || '',
      caption: 'Rooms',
      noun: NOUNS.room,
      columns: [
        { key: 'name', header: 'Name', value: function (r) { return r.name; },
          cell: function (r) { return h('a', { class: 'pr-room-link', href: roomHref(r.id), 'data-room': r.id }, r.name); } },
        { key: 'code', header: 'Code', hideOnMobile: true, value: function (r) { return r.code; } },
        { key: 'venue', header: 'Venue', hideOnMobile: true, hidden: venueCount < 2, filterable: venueCount > 1, value: function (r) { return r.venue; } },
        num('devices', 'Devices'), num('cables', 'Cables'), num('racks', 'Racks', true), num('plans', 'Plans', true),
        num('procedures', 'Procedures', true),
      ],
      rows: rows,
      onRow: function (r) { go({ view: 'rooms', id: r.id, room: r.id, tab: 'overview' }); },
      url: tableUrl(),
      highlight: (S.route.query || {}).hl || null,
      csvName: (ctx.project ? ctx.project + '-' : '') + 'rooms.csv',
      empty: 'No rooms yet. Add a room in Settings \u25B8 Rooms, or import a spreadsheet in Data \u25B8 Imports.',
    });
    setTitle('Rooms');
  }

  // ---------------------------------------------------------- page

  function explorerItems() {
    const d = doc();
    const venues = byId(d.venues);
    const grouped = list(d.venues).length > 0;
    const idx = indexDoc(d);
    return sortedRooms(d).map(function (r) {
      const v = venues[r.venue];
      return {
        id: r.id, label: r.name || r.id, sub: str(r.code), glyph: GLYPH,
        badge: list(idx.devicesByRoom[r.id]).length,
        group: grouped ? (v ? v.name || v.id : '') : '',
        href: roomHref(r.id, S.tab || 'overview'),
      };
    });
  }

  function tabHref(tab) {
    return href({ tab: tab, query: tabQuery() });
  }

  function railItems() {
    return roomTabs().map(function (t) {
      return { key: t, label: tabLabel(t), href: tabHref(t), active: t === S.tab };
    });
  }

  // explorer.js renders the rail once and has no setter; keep its links in step with the tab.
  function syncRail() {
    if (!S.ex) return;
    Array.prototype.forEach.call(S.ex.root.querySelectorAll('.ex-rail-item[data-key]'), function (a) {
      const k = a.getAttribute('data-key');
      a.setAttribute('href', tabHref(k));
      if (k === S.tab) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
  }

  function cardsFor(room) {
    return summaryCards('room', doc(), room);
  }

  function factHref(view, id) {
    if (view === 'devices' && id === S.roomId) return tabHref('devices');
    return href({ view: view, id: id, tab: '', sub: '' });
  }

  function headerOptions(room, cards) {
    const d = doc();
    const counts = {};
    cards.forEach(function (c) { counts[c.key] = c; });
    const id = room.id;
    const plan = firstPlan(d, id);
    const api = ctx.api;
    const thumb = plan && api && typeof api.floorplanImageUrl === 'function'
      ? { src: api.floorplanImageUrl(ctx.project, plan.id), alt: 'Floor plan: ' + (plan.name || plan.id), href: href({ view: 'plan', id: plan.id, room: id }) }
      : null;
    const problems = counts.problems && counts.problems.count ? counts.problems : null;
    const actions = [
      { key: 'patch', label: 'Patch', primary: true, href: href({ view: 'patch', room: id }) },
      { key: 'plan', label: 'Plan', href: href({ view: 'plan', room: id, id: '' }) },
      { key: 'racks', label: 'Racks', href: href({ view: 'racks', room: id, id: '' }) },
      { key: 'sop', label: 'SOPs', href: href({ view: 'sop', room: id }) },
    ];
    if (!readOnly()) actions.push({ key: 'edit', label: 'Edit', title: 'Edit this room in Settings', href: href({ view: 'settings', tab: 'rooms', id: '', query: { hl: id } }) });
    const overflow = [];
    if (ctx.project) {
      overflow.push({ key: 'public', label: 'Public page', target: '_blank',
        href: str(ctx.appRoot || '/') + 'p/' + encodeURIComponent(ctx.project) + '/r/' + encodeURIComponent(id) });
    }
    const title = room.name || id;
    const kindLabel = cap(room.kind);
    return {
      kind: 'room', id: id, glyph: GLYPH, title: title, subtitle: kindLabel.toLowerCase() === title.toLowerCase() ? '' : kindLabel,
      facts: roomFacts(d, room, { href: factHref }),
      badges: problems ? [{ key: 'problems', label: plural(problems.count, { one: 'open problem', many: 'open problems' }), level: 'warn',
        title: 'Open problem reports in ' + (room.name || id), onClick: function () { openDrill(problems); } }] : [],
      actions: actions,
      overflow: overflow,
      tabs: roomTabs().map(function (t) {
        const c = counts[t];
        return { key: t, label: tabLabel(t), count: c && t !== 'overview' ? c.count : null, href: tabHref(t) };
      }),
      activeTab: S.tab,
      thumb: thumb,
      onTab: function (key, e) {
        if (e && (e.button > 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)) return;
        if (e) e.preventDefault();
        goTab(key);
      },
    };
  }

  function notFound(id) {
    const box = h('div', { class: 'pr-notfound' }, [
      inlineError({ status: 404, message: 'Room \u201c' + id + '\u201d not found' }, null),
      h('p', null, h('a', { class: 'pr-back', href: href({ view: 'rooms', id: '', tab: '', query: {} }) }, '\u2190 All rooms')),
    ]);
    S.ex.content.appendChild(box);
    setTitle('Room not found');
  }

  function renderPage() {
    clear();
    S.mode = 'page';
    root.classList.add('pr-is-page');
    const id = S.route.id;
    S.roomId = id;
    const room = sortedRooms(doc()).filter(function (r) { return r.id === id; })[0] || null;
    const res = resolveTab(roomTabs(), S.route.tab);
    S.tab = res.tab;
    S.ex = mountExplorer(root, {
      key: 'rooms', title: 'Rooms', glyph: GLYPH, items: explorerItems(), selected: room ? id : null,
      footer: function (shown, total) { return (shown === total ? '' : shown + ' of ') + plural(total, NOUNS.room); },
      rail: railItems(), mobileLabel: 'Rooms', contentLabel: room ? room.name || id : 'Room',
    });
    if (!room) {
      notFound(id);
      return;
    }
    S.room = room;
    if (ctx.recent && typeof ctx.recent.push === 'function') ctx.recent.push('room', id);
    setTitle(room.name || id);
    S.eh = mountEntityHeader(S.ex.content, headerOptions(room, cardsFor(room)));
    S.body = h('div', { class: 'pr-body' });
    S.ex.content.appendChild(S.body);
    showTab(S.tab);
    if (res.redirect) scheduleRedirect(res.tab);
  }

  // D5: a missing or unknown tab segment is replaced with the default tab. Deferred so the shell has
  // registered this handle before the replace comes back through route().
  function scheduleRedirect(tab) {
    if (S.redirect) clearTimeout(S.redirect);
    S.redirect = setTimeout(function () {
      S.redirect = 0;
      if (S.destroyed || S.mode !== 'page') return;
      go({ tab: tab }, { replace: true });
    }, 0);
  }

  function overviewPanel(panel, room) {
    const cards = cardsFor(room);
    const grid = h('div', { class: 'pr-cards' });
    cards.forEach(function (c) {
      const noun = NOUNS[c.drill ? c.drill.kind : ''] || { one: c.label.toLowerCase(), many: c.label.toLowerCase() };
      const canDrill = !!c.drill && c.count > 0;
      const main = h('button', {
        type: 'button', class: 'pr-card-main', disabled: !canDrill,
        'aria-label': canDrill ? 'Show ' + plural(c.count, noun) : c.label + ': none',
        onclick: function () { openDrill(c); },
      }, [
        h('span', { class: 'pr-card-label' }, c.label),
        h('span', { class: 'pr-card-n' }, String(c.count)),
        c.sub ? h('span', { class: 'pr-card-sub' }, c.sub) : null,
      ]);
      const link = c.tab ? h('a', {
        class: 'pr-card-tab', href: tabHref(c.tab), 'aria-label': 'Open the ' + tabLabel(c.tab) + ' tab',
        onclick: function (e) {
          if (e.button > 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
          e.preventDefault();
          goTab(c.tab);
        },
      }, tabLabel(c.tab) + ' \u203A') : null;
      grid.appendChild(h('div', { class: 'pr-card' + (c.count ? '' : ' pr-card-zero'), 'data-card': c.key }, [main, link]));
    });
    panel.appendChild(grid);
    if (str(room.notes).trim()) {
      panel.appendChild(h('section', { class: 'pr-notes' }, [h('h2', { class: 'pr-h2' }, 'Notes'), h('p', { class: 'pr-notes-text' }, str(room.notes))]));
    }
  }

  function tablePanel(panel, tab, room) {
    const kind = TAB_KIND[tab];
    const card = cardsFor(room).filter(function (c) { return c.key === tab; })[0];
    const ids = card && card.drill ? card.drill.ids : [];
    S.table = createTable(panel, {
      key: 'room.' + tab,
      scope: ctx.project || '',
      caption: tabLabel(tab) + DOT + (room.name || room.id),
      noun: NOUNS[kind],
      columns: columnsFor(kind),
      rows: rowsFor(kind, ids),
      rowId: rowIdFor(kind),
      onRow: onRowFor(kind),
      url: tableUrl(),
      highlight: (S.route.query || {}).hl || null,
      sticky: false,
      csvName: (ctx.project ? ctx.project + '-' : '') + room.id + '-' + tab + '.csv',
      empty: emptyFor(kind, room.name || room.id),
    });
  }

  function showTab(tab) {
    if (S.table) { S.table.destroy(); S.table = null; }
    S.tab = tab;
    S.body.textContent = '';
    const panel = h('div', { class: 'pr-panel', role: 'tabpanel', 'data-tab': tab, 'aria-label': tabLabel(tab) });
    S.body.appendChild(panel);
    if (tab === 'overview') overviewPanel(panel, S.room);
    else tablePanel(panel, tab, S.room);
    if (S.eh) S.eh.setTab(tab);
    if (S.ex) S.ex.setItems(explorerItems());
    syncRail();
  }

  // ---------------------------------------------------------- doc changes

  function refresh() {
    S.timer = 0;
    if (S.destroyed) return;
    if (S.mode === 'landing') {
      if (S.table) S.table.setRows(landingRows());
      return;
    }
    if (S.mode !== 'page') return;
    const room = sortedRooms(doc()).filter(function (r) { return r.id === S.roomId; })[0] || null;
    if (!room || !S.room) { renderPage(); return; }
    S.room = room;
    S.ex.setItems(explorerItems());
    const cards = cardsFor(room);
    S.eh.update(headerOptions(room, cards));
    if (S.tab === 'overview') {
      showTab('overview');
      return;
    }
    const kind = TAB_KIND[S.tab];
    const card = cards.filter(function (c) { return c.key === S.tab; })[0];
    if (S.table) S.table.setRows(rowsFor(kind, card && card.drill ? card.drill.ids : []));
  }

  function onDoc() {
    if (S.timer) clearTimeout(S.timer);
    S.timer = setTimeout(refresh, 30);
  }

  // ---------------------------------------------------------- routing

  function render() {
    if (S.route.id) renderPage(); else renderLanding();
  }

  function route(r) {
    if (S.destroyed || !r) return;
    const prev = S.route;
    S.route = r;
    if (!r.id) {
      if (S.mode !== 'landing') { renderLanding(); return; }
      if (S.table) S.table.readUrl();
      if ((r.query || {}).hl !== (prev.query || {}).hl && S.table) S.table.setHighlight(r.query.hl || null);
      return;
    }
    if (S.mode !== 'page' || r.id !== S.roomId) { renderPage(); return; }
    if (!S.room) return;
    const res = resolveTab(roomTabs(), r.tab);
    if (res.tab !== S.tab) showTab(res.tab);
    else {
      if (S.table) S.table.readUrl();
      if ((r.query || {}).hl !== (prev.query || {}).hl && S.table) S.table.setHighlight(r.query.hl || null);
      syncRail();
    }
    if (res.redirect) scheduleRedirect(res.tab);
  }

  render();
  if (store && typeof store.addEventListener === 'function') store.addEventListener('doc', onDoc);

  return {
    route: route,
    destroy: function () {
      if (S.destroyed) return;
      if (S.timer) clearTimeout(S.timer);
      if (store && typeof store.removeEventListener === 'function') store.removeEventListener('doc', onDoc);
      clear();
      S.destroyed = true;
      if (root.parentNode) root.parentNode.removeChild(root);
    },
  };
}
