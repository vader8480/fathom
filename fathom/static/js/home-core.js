// Pure core of the home view (docs/ui-audit.md B.2 HOME, D2, D8): section
// cards, room cards, the recents strip and project cards. No DOM, window,
// timers or storage; recents are passed in, so the module imports in Node.

export const SECTION_COPY = {
  patch: 'Wire devices port to port and trace signal paths.',
  rooms: 'Floor plans, racks and room overviews.',
  devices: 'Every device, its ports, network and inventory record.',
  schedules: 'Cable, IP, DMX and parts lists, and printable builds.',
  sop: 'Step-by-step procedures for volunteers.',
  data: 'Imports, network discovery, history and raw JSON.',
  settings: 'Project, rooms, systems, networks, users and sharing.',
};

export const RECENT_TYPES = ['device', 'room', 'rack', 'page'];
export const RECENT_MAX = 8;

export const RECENT_LABELS = { device: 'Device', room: 'Room', rack: 'Rack', page: 'SOP' };

export function recentKey(project) {
  return 'fathom.ui.recent.' + String(project || '');
}

function arr(x) {
  return Array.isArray(x) ? x : [];
}

function str(v) {
  return v === undefined || v === null ? '' : String(v);
}

function num(v) {
  return typeof v === 'number' && isFinite(v) ? v : null;
}

function plural(n, one, many) {
  return n + ' ' + (n === 1 ? one : many);
}

export function countsText(devices, cables) {
  return plural(devices, 'device', 'devices') + ' \u00b7 ' + plural(cables, 'cable', 'cables');
}

export function projectTitle(doc, name) {
  const meta = (doc && doc.meta) || {};
  return str(meta.title) || str(name) || 'Untitled project';
}

// ------------------------------------------------------------ sections

// One card per section except home, in the order given (already role-filtered
// by the shell); a section without a permitted view gets no card.
export function sectionCards(sections) {
  const out = [];
  arr(sections).forEach(function (s) {
    if (!s || s.key === 'home') return;
    const views = arr(s.views);
    if (!views.length) return;
    out.push({
      key: str(s.key),
      label: str(s.label),
      glyph: str(s.glyph),
      view: str(views[0]),
      text: Object.prototype.hasOwnProperty.call(SECTION_COPY, s.key) ? SECTION_COPY[s.key] : '',
    });
  });
  return out;
}

// ------------------------------------------------------------ recents

// Entries of one recents type as [{id, t}], newest first, deduped, ignoring
// malformed items.
function entriesOf(list) {
  const seen = {};
  const out = [];
  arr(list).forEach(function (e, i) {
    const id = typeof e === 'string' ? e : str(e && e.id);
    if (!id || seen[id]) return;
    seen[id] = true;
    const t = typeof e === 'string' ? null : num(e.t);
    out.push({ id: id, t: t === null ? -(i + 1) : t });
  });
  return out;
}

// Recents in the D8 shape from the shell's `ctx.recent.list(type)` results
// (`lists[type]`: ids or {id, t}) and the stored D8 object (`stored`). A type
// missing from `lists` is taken from `stored`. Bare ids take their `t` from
// `stored`; ids it does not know rank by position below every timed entry.
export function recentInput(lists, stored) {
  const st = stored && typeof stored === 'object' ? stored : {};
  const out = {};
  RECENT_TYPES.forEach(function (type) {
    const times = {};
    entriesOf(st[type]).forEach(function (e) { times[e.id] = e.t; });
    if (lists && Array.isArray(lists[type])) {
      out[type] = arr(lists[type]).map(function (e, i) {
        const id = typeof e === 'string' ? e : str(e && e.id);
        const own = typeof e === 'string' ? null : num(e && e.t);
        const t = own !== null ? own : (Object.prototype.hasOwnProperty.call(times, id) && times[id] >= 0 ? times[id] : -(i + 1));
        return { id: id, t: t };
      }).filter(function (e) { return !!e.id; });
    } else {
      out[type] = entriesOf(st[type]);
    }
  });
  return out;
}

function byId(list) {
  const m = {};
  arr(list).forEach(function (x) { if (x && x.id !== undefined && x.id !== null) m[String(x.id)] = x; });
  return m;
}

function pageIndex(pages) {
  const m = {};
  arr(pages).forEach(function (p) {
    if (!p) return;
    if (p.id) m[String(p.id)] = p;
    if (p.slug && !m[String(p.slug)]) m[String(p.slug)] = p;
  });
  return m;
}

function resolveRecent(doc, type, id) {
  const d = doc || {};
  if (type === 'device') {
    const dev = byId(d.devices)[id];
    if (!dev) return null;
    const r = { view: 'devices', id: id, query: {} };
    if (dev.room) r.room = String(dev.room);
    return { title: str(dev.name) || id, route: r };
  }
  if (type === 'room') {
    const room = byId(d.rooms)[id];
    if (!room) return null;
    return { title: str(room.name) || id, route: { room: id, view: 'rooms', id: id, query: {} } };
  }
  if (type === 'rack') {
    const rack = byId(d.racks)[id];
    if (!rack) return null;
    const r = { view: 'racks', id: id, query: {} };
    if (rack.room) r.room = String(rack.room);
    return { title: str(rack.name) || id, route: r };
  }
  if (type === 'page') {
    const page = pageIndex(d.pages)[id];
    if (!page) return null;
    return { title: str(page.title) || str(page.slug) || id, route: { view: 'sop', query: { page: str(page.slug) || id } } };
  }
  return null;
}

// Up to RECENT_MAX known recents across types, newest first:
// [{type, id, title, label, t, route}], where `route` is a partial route for
// ctx.routeHref. Unknown ids are dropped before the cap.
export function recentStrip(doc, recent) {
  const rc = recent && typeof recent === 'object' ? recent : {};
  const all = [];
  RECENT_TYPES.forEach(function (type, ti) {
    entriesOf(rc[type]).forEach(function (e, i) {
      const hit = resolveRecent(doc, type, e.id);
      if (hit) all.push({ type: type, id: e.id, title: hit.title, label: RECENT_LABELS[type], t: e.t, route: hit.route, _o: i * RECENT_TYPES.length + ti });
    });
  });
  all.sort(function (a, b) { return b.t - a.t || a._o - b._o; });
  return all.slice(0, RECENT_MAX).map(function (x) {
    return { type: x.type, id: x.id, title: x.title, label: x.label, t: x.t, route: x.route };
  });
}

// ------------------------------------------------------------ rooms

function isArchived(p) {
  return !!p && p.status === 'archived';
}

// One card per room: [{id, name, code, counts, devices, cables, links}].
// Links (in this order): Patch, Plan (floor plans), Racks (racks), SOPs
// (non-archived pages listing the room), room page. Rooms in `recent.room`
// come first, newest first; the rest keep doc order.
export function roomCards(doc, recent, pages) {
  const d = doc || {};
  const rooms = arr(d.rooms).filter(function (r) { return r && r.id; });
  const devRoom = {};
  const devCount = {};
  arr(d.devices).forEach(function (x) {
    if (!x || !x.id) return;
    const r = str(x.room);
    devRoom[x.id] = r;
    if (r) devCount[r] = (devCount[r] || 0) + 1;
  });
  const cabCount = {};
  arr(d.cables).forEach(function (c) {
    if (!c) return;
    const a = devRoom[str(c.from && c.from.device)] || '';
    const b = devRoom[str(c.to && c.to.device)] || '';
    if (a) cabCount[a] = (cabCount[a] || 0) + 1;
    if (b && b !== a) cabCount[b] = (cabCount[b] || 0) + 1;
  });
  const has = function (list) {
    const m = {};
    arr(list).forEach(function (x) { if (x && x.room) m[String(x.room)] = (m[String(x.room)] || 0) + 1; });
    return m;
  };
  const plans = has(d.floorplans);
  const racks = has(d.racks);
  const sops = {};
  arr(pages).forEach(function (p) {
    if (!p || isArchived(p)) return;
    const seen = {};
    arr(p.rooms).forEach(function (r) {
      const k = str(r);
      if (!k || seen[k]) return;
      seen[k] = true;
      sops[k] = (sops[k] || 0) + 1;
    });
  });

  const cards = rooms.map(function (r) {
    const id = String(r.id);
    const nd = devCount[id] || 0;
    const nc = cabCount[id] || 0;
    const links = [{ key: 'patch', label: 'Patch', view: 'patch' }];
    if (plans[id]) links.push({ key: 'plan', label: 'Plan', view: 'plan' });
    if (racks[id]) links.push({ key: 'racks', label: 'Racks', view: 'racks' });
    if (sops[id]) links.push({ key: 'sop', label: 'SOPs', view: 'sop' });
    links.push({ key: 'room', label: 'Room page', view: 'rooms', id: id });
    return { id: id, name: str(r.name) || id, code: str(r.code), counts: countsText(nd, nc), devices: nd, cables: nc, links: links };
  });

  const index = {};
  cards.forEach(function (c, i) { index[c.id] = i; });
  const rc = recent && typeof recent === 'object' ? recent : {};
  const first = entriesOf(rc.room).map(function (e, i) { return { id: e.id, t: e.t, i: i }; })
    .filter(function (e) { return Object.prototype.hasOwnProperty.call(index, e.id); })
    .sort(function (a, b) { return b.t - a.t || a.i - b.i; });
  const out = [];
  const used = {};
  first.forEach(function (e) { used[e.id] = true; out.push(cards[index[e.id]]); });
  cards.forEach(function (c) { if (!used[c.id]) out.push(c); });
  return out;
}

// ------------------------------------------------------------ projects

// One card per listed project: [{name, title, org, counts, current}];
// `current` is true only on the card named `current`.
export function projectCards(projects, current) {
  const cur = str(current);
  return arr(projects).filter(function (p) { return p && p.name; }).map(function (p) {
    const name = String(p.name);
    const parts = [];
    if (num(p.rooms) !== null) parts.push(plural(p.rooms, 'room', 'rooms'));
    if (num(p.devices) !== null) parts.push(plural(p.devices, 'device', 'devices'));
    return {
      name: name,
      title: str(p.title) || name,
      org: str(p.org),
      counts: parts.join(' \u00b7 '),
      current: !!cur && name === cur,
    };
  });
}
