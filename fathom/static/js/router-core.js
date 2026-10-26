// Pure routing core (docs/ui-audit.md D1, D2, D3): URL grammar, sections,
// role filtering, nav memory and breakpoints. No DOM, window, timers or
// storage globals; storage is injected, so the module imports in Node.
//
//   #/<project>/<room>/<view>[/<seg4>[/<seg5>[/<seg6>]]][?<query>]

export const BP = { md: 700, lg: 1100 };

export function layoutFor(width) {
  const w = Number(width);
  if (w < BP.md) return 'sm';
  if (w < BP.lg) return 'md';
  return 'lg';
}

export const DEFAULT_VIEW = 'home';

export const VIEW_SHAPES = {
  devices: ['id', 'tab', 'sub'],
  rooms: ['id', 'tab'],
  racks: ['id', 'tab', 'sub'],
  plan: ['id'],
  schedules: ['tab'],
  imports: ['tab'],
  settings: ['tab'],
  discovery: ['tab', 'sub'],
  history: ['id'],
};

export const SECTIONS = [
  { key: 'home', label: 'Home', glyph: '\u2302', views: ['home'], nav: 'sm' },
  { key: 'patch', label: 'Patch', glyph: '\u2B95', views: ['patch', 'table', 'map'], nav: 'all' },
  { key: 'rooms', label: 'Rooms', glyph: '\u25A3', views: ['rooms', 'plan', 'racks'], nav: 'all' },
  { key: 'devices', label: 'Devices', glyph: '\u25EB', views: ['devices', 'inventory'], nav: 'all' },
  { key: 'schedules', label: 'Schedules', glyph: '\u2630', views: ['schedules', 'builds'], nav: 'all' },
  { key: 'sop', label: 'SOPs', glyph: '\u2611', views: ['sop'], nav: 'all' },
  { key: 'data', label: 'Data', glyph: '\u21C5', views: ['imports', 'discovery', 'history', 'json'], nav: 'all' },
  { key: 'settings', label: 'Settings', glyph: '\u2699\uFE0E', views: ['settings'], nav: 'all' },
];

export const VIEW_ROLES = {};
SECTIONS.forEach(function (s) { s.views.forEach(function (v) { VIEW_ROLES[v] = 'viewer'; }); });

export const TAB_ROLES = { settings: { users: 'admin', backups: 'admin', sharing: 'editor' } };

const RANK = { viewer: 0, editor: 1, admin: 2 };
const NAV_KEY = 'fathom.ui.nav';
const ROUTE_FIELDS = ['id', 'tab', 'sub'];

function own(o, k) {
  return !!o && Object.prototype.hasOwnProperty.call(o, k);
}

function rank(role) {
  return own(RANK, role) ? RANK[role] : 0;
}

function str(v) {
  return v === undefined || v === null ? '' : String(v);
}

function isObj(o) {
  return !!o && typeof o === 'object' && !Array.isArray(o);
}

// ------------------------------------------------------------ roles and sections

export function canSee(view, role, tab) {
  let need = rank(own(VIEW_ROLES, view) ? VIEW_ROLES[view] : 'viewer');
  if (tab && own(TAB_ROLES, view) && own(TAB_ROLES[view], tab)) need = Math.max(need, rank(TAB_ROLES[view][tab]));
  return rank(role) >= need;
}

export function sectionOf(view) {
  const v = view || DEFAULT_VIEW;
  for (let i = 0; i < SECTIONS.length; i++) {
    if (SECTIONS[i].views.indexOf(v) >= 0) return SECTIONS[i].key;
  }
  return 'data';
}

export function sectionsFor(role) {
  const out = [];
  SECTIONS.forEach(function (s) {
    const views = s.views.filter(function (v) { return canSee(v, role); });
    if (views.length) out.push({ key: s.key, label: s.label, glyph: s.glyph, views: views, nav: s.nav });
  });
  return out;
}

// Route to the first permitted view of section `key`, same project and room;
// null when the section is unknown or has no permitted view.
export function sectionRoot(key, route, role) {
  const secs = sectionsFor(role);
  for (let i = 0; i < secs.length; i++) {
    if (secs[i].key === key) {
      const r = route || {};
      return { project: str(r.project), room: str(r.room), view: secs[i].views[0], query: {} };
    }
  }
  return null;
}

// ------------------------------------------------------------ parse / build

function decodeSeg(p) {
  try { return decodeURIComponent(p); } catch (e) { return p; }
}

function encQuery(v) {
  return encodeURIComponent(v).replace(/%3A/g, ':').replace(/%2C/g, ',').replace(/%7C/g, '|').replace(/%2F/g, '/');
}

function cleanQuery(q) {
  const out = {};
  if (!isObj(q)) return out;
  Object.keys(q).forEach(function (k) {
    const v = q[k];
    if (k === '__proto__' || v === undefined || v === null || v === '') return;
    out[k] = String(v);
  });
  return out;
}

function copyRoute(r) {
  r = r || {};
  return {
    project: str(r.project), room: str(r.room), view: str(r.view),
    id: str(r.id), tab: str(r.tab), sub: str(r.sub),
    extra: Array.isArray(r.extra) ? r.extra.map(str) : [],
    query: cleanQuery(r.query),
  };
}

function toRoute(x) {
  return typeof x === 'string' ? parseRoute(x) : copyRoute(x);
}

export function parseRoute(hash) {
  let s = str(hash).replace(/^#?\/?/, '');
  let qs = '';
  const qi = s.indexOf('?');
  if (qi >= 0) { qs = s.slice(qi + 1); s = s.slice(0, qi); }
  const parts = s === '' ? [] : s.split('/').map(decodeSeg);
  const view = parts[2] || '';
  const rest = parts.slice(3);
  while (rest.length && rest[rest.length - 1] === '') rest.pop();
  const shape = own(VIEW_SHAPES, view) ? VIEW_SHAPES[view] : [];
  const route = { project: parts[0] || '', room: parts[1] || '', view: view, id: '', tab: '', sub: '', extra: [], query: {} };
  shape.forEach(function (k, i) { if (i < rest.length) route[k] = rest[i]; });
  route.extra = rest.slice(shape.length);
  if (qs) {
    new URLSearchParams(qs).forEach(function (v, k) {
      if (k !== '__proto__' && !own(route.query, k)) route.query[k] = v;
    });
  }
  return route;
}

export function buildRoute(route) {
  const r = route || {};
  const view = str(r.view);
  const segs = [encodeURIComponent(str(r.project)), encodeURIComponent(str(r.room)).replace(/%2A/g, '*'), encodeURIComponent(view)];
  (own(VIEW_SHAPES, view) ? VIEW_SHAPES[view] : []).forEach(function (k) { segs.push(encodeURIComponent(str(r[k]))); });
  if (Array.isArray(r.extra)) r.extra.forEach(function (x) { segs.push(encodeURIComponent(str(x))); });
  while (segs.length && segs[segs.length - 1] === '') segs.pop();
  let s = '#/' + segs.join('/');
  const q = [];
  if (isObj(r.query)) {
    Object.keys(r.query).forEach(function (k) {
      const v = r.query[k];
      if (v === undefined || v === null || v === '') return;
      q.push(encodeURIComponent(k) + '=' + encQuery(String(v)));
    });
  }
  if (q.length) s += '?' + q.join('&');
  return s;
}

// New route with `patch` merged into its query; null, undefined or '' deletes a key.
export function withQuery(route, patch) {
  const out = copyRoute(route);
  if (isObj(patch)) {
    Object.keys(patch).forEach(function (k) {
      const v = patch[k];
      if (v === undefined || v === null || v === '') delete out.query[k];
      else if (k !== '__proto__') out.query[k] = String(v);
    });
  }
  return out;
}

// Fields present in `partial` (null/undefined = absent) replace the route's.
// Changing the view clears id, tab, sub and extra unless given; `query`, when
// given, replaces the whole query (use withQuery to merge).
export function mergeRoute(route, partial) {
  const out = copyRoute(route);
  const p = partial || {};
  if (p.project != null) out.project = String(p.project);
  if (p.room != null) out.room = String(p.room);
  if (p.view != null && String(p.view) !== out.view) {
    out.view = String(p.view);
    out.id = ''; out.tab = ''; out.sub = ''; out.extra = [];
  }
  ROUTE_FIELDS.forEach(function (k) {
    if (p[k] != null) { out[k] = String(p[k]); out.extra = []; }
  });
  if (Array.isArray(p.extra)) out.extra = p.extra.map(str);
  if (p.query != null) out.query = cleanQuery(p.query);
  return out;
}

// Routes or hashes are equal; an empty view equals DEFAULT_VIEW and query
// keys listed in ignoreKeys are not compared.
export function sameRoute(a, b, ignoreKeys) {
  const x = toRoute(a);
  const y = toRoute(b);
  const fields = ['project', 'room', 'id', 'tab', 'sub'];
  for (let i = 0; i < fields.length; i++) if (x[fields[i]] !== y[fields[i]]) return false;
  if ((x.view || DEFAULT_VIEW) !== (y.view || DEFAULT_VIEW)) return false;
  if (x.extra.length !== y.extra.length) return false;
  for (let i = 0; i < x.extra.length; i++) if (x.extra[i] !== y.extra[i]) return false;
  const ignore = Array.isArray(ignoreKeys) ? ignoreKeys : [];
  const keep = function (k) { return ignore.indexOf(k) < 0; };
  const kx = Object.keys(x.query).filter(keep);
  const ky = Object.keys(y.query).filter(keep);
  if (kx.length !== ky.length) return false;
  for (let i = 0; i < kx.length; i++) {
    if (!own(y.query, kx[i]) || y.query[kx[i]] !== x.query[kx[i]]) return false;
  }
  return true;
}

// ------------------------------------------------------------ selection strings (from app.js)

export function selToString(sel) {
  if (!sel) return '';
  if (sel.type === 'port') return 'port:' + (sel.device || sel.id) + ':' + sel.port;
  if (sel.type === 'marker') return 'marker:' + (sel.floorplan || '') + ':' + (sel.device || sel.id);
  if (sel.type === 'channel') return 'channel:' + (sel.device || sel.id) + ':' + sel.channel;
  return sel.type + ':' + sel.id;
}

export function selFromString(s) {
  if (!s) return null;
  const parts = String(s).split(':');
  const type = parts[0];
  if (type === 'port') return { type: 'port', id: parts[1], device: parts[1], port: parts[2] || null };
  if (type === 'channel') return parts[2] ? { type: 'channel', id: parts[1], device: parts[1], channel: parts[2] } : { type: 'device', id: parts[1], device: parts[1] };
  if (type === 'marker') return { type: 'marker', id: parts[2], floorplan: parts[1], device: parts[2] };
  if (!parts[1]) return null;
  const sel = { type: type, id: parts[1] };
  if (type === 'device') sel.device = parts[1];
  if (parts[2]) { sel.port = parts[2]; sel.device = parts[1]; sel.type = type === 'device' ? 'port' : type; }
  return sel;
}

// ------------------------------------------------------------ nav memory

// sessionStorage-like `storage` (getItem/setItem/removeItem); every access
// tolerates a missing or throwing store and corrupt JSON.
export function navMemory(storage) {
  function read() {
    try {
      const raw = storage ? storage.getItem(NAV_KEY) : null;
      const o = raw ? JSON.parse(raw) : null;
      return isObj(o) ? o : {};
    } catch (e) {
      return {};
    }
  }
  function write(o) {
    try { if (storage) storage.setItem(NAV_KEY, JSON.stringify(o)); } catch (e) { /* full or unavailable */ }
  }
  function asHash(hash) {
    const s = str(hash);
    if (s.charAt(0) === '#') return s;
    return s.charAt(0) === '/' ? '#' + s : '#/' + s;
  }
  return {
    remember: function (project, hash) {
      const h = asHash(hash);
      const r = parseRoute(h);
      const p = str(project) || r.project;
      if (!p || p === '__proto__') return;
      const all = read();
      const mem = isObj(all[p]) ? all[p] : {};
      mem[sectionOf(r.view)] = h;
      all[p] = mem;
      write(all);
    },
    // Hash for a click on section `key` while `route` is current: the active
    // section goes to its root, another section to its remembered hash (when
    // still permitted) or its root; '' when the section is not permitted.
    target: function (project, key, route, role) {
      const cur = toRoute(route);
      const p = str(project) || cur.project;
      const root = sectionRoot(key, { project: p, room: cur.room }, role);
      if (!root) return '';
      const rootHash = buildRoute(root);
      if (sectionOf(cur.view) === key) return rootHash;
      const mem = read()[p];
      const h = isObj(mem) && typeof mem[key] === 'string' ? mem[key] : '';
      if (h) {
        const r = parseRoute(h);
        if (r.project === p && sectionOf(r.view) === key && canSee(r.view || DEFAULT_VIEW, role, r.tab)) return h;
      }
      return rootHash;
    },
    clear: function () {
      try { if (storage) storage.removeItem(NAV_KEY); } catch (e) { /* unavailable */ }
    },
  };
}

// ------------------------------------------------------------ legacy

// app.js buildHash's algorithm. Output is identical for every non-empty view;
// an empty view writes DEFAULT_VIEW, which is now 'home' (D1) instead of 'patch'.
export function legacyHash(project, room, view, params) {
  let s = '#/' + encodeURIComponent(project || '') + '/' + encodeURIComponent(room || '').replace(/%2A/g, '*') + '/' + (view || DEFAULT_VIEW);
  const q = [];
  if (params) Object.keys(params).forEach(function (k) { if (params[k] !== undefined && params[k] !== null && params[k] !== '') q.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]).replace(/%3A/g, ':')); });
  if (q.length) s += '?' + q.join('&');
  return s;
}
