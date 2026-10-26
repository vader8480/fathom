// Pure DataTable core (docs/ui-audit.md B.2 TABLE, D1 query keys, D8 storage).
// No DOM, window, timers or storage globals: storage is injected, so the module
// imports in Node. The DOM half lives in datatable.js.
//
// State shape (D8 plus the URL-only fields q and page):
//   {q, sort: {col, dir: 1 | -1} | null, filters: {col: [value]}, page (1-based),
//    pageSize, hidden: [col], density: 'normal' | 'compact', extra: {}}
// Filter values are display strings; '' is written as EMPTY ('(empty)').

export const PAGE_SIZES = [25, 50, 100, 200];
export const DEFAULT_PAGE_SIZE = 50;
export const STATE_VERSION = 1;
export const EMPTY = '(empty)';
export const DENSITIES = ['normal', 'compact'];

const STORAGE_PREFIX = 'fathom.ui.table.';

function own(o, k) {
  return !!o && Object.prototype.hasOwnProperty.call(o, k);
}

function isObj(o) {
  return !!o && typeof o === 'object' && !Array.isArray(o);
}

function identityValue(key) {
  return function (row) { return row == null ? undefined : row[key]; };
}

// Display text of a value: null/undefined -> '', arrays joined with ', '.
export function textOf(v) {
  if (v === null || v === undefined) return '';
  if (Array.isArray(v)) return v.map(textOf).filter(function (s) { return s !== ''; }).join(', ');
  return String(v);
}

// Filter values of one cell: arrays give one value per element; '' -> EMPTY.
function filterValuesOf(v) {
  if (Array.isArray(v)) {
    const out = [];
    v.forEach(function (x) { const s = textOf(x); if (s !== '' && out.indexOf(s) < 0) out.push(s); });
    return out.length ? out : [EMPTY];
  }
  const s = textOf(v);
  return [s === '' ? EMPTY : s];
}

// ------------------------------------------------------------ columns

export function normalizeColumns(cols) {
  return (Array.isArray(cols) ? cols : []).filter(function (c) { return c && c.key !== undefined && c.key !== null; }).map(function (c) {
    const key = String(c.key);
    const out = Object.assign({}, c);
    out.key = key;
    out.header = c.header === undefined || c.header === null ? key : String(c.header);
    out.value = typeof c.value === 'function' ? c.value : identityValue(key);
    out.cell = typeof c.cell === 'function' ? c.cell : null;
    out.csv = typeof c.csv === 'function' || c.csv === false ? c.csv : null;
    out.sortable = c.sortable !== false;
    out.filterable = c.filterable === true;
    out.searchable = c.searchable !== false;
    out.hideOnMobile = c.hideOnMobile === true;
    out.hidden = c.hidden === true;
    out.align = c.align === 'right' || c.align === 'center' ? c.align : 'left';
    out.width = c.width === undefined ? null : c.width;
    out.sticky = c.sticky === true;
    return out;
  });
}

function columnMap(columns) {
  const m = {};
  (columns || []).forEach(function (c) { if (c && c.key !== undefined) m[c.key] = c; });
  return m;
}

// ------------------------------------------------------------ natural compare

const NUM_RE = /^\s*[-+]?(\d+\.?\d*|\.\d+)\s*$/;
const CHUNK_RE = /(\d+)|(\D+)/g;

function prepare(v) {
  if (Array.isArray(v)) v = textOf(v);
  if (v === null || v === undefined || v === '') return { e: true, n: null, s: '', l: '', c: null };
  if (typeof v === 'number') {
    if (isFinite(v)) return { e: false, n: v, s: String(v), l: String(v), c: null };
    v = String(v);
  }
  const s = typeof v === 'string' ? v : String(v);
  if (s.trim() === '') return { e: true, n: null, s: s, l: '', c: null };
  return { e: false, n: NUM_RE.test(s) ? parseFloat(s) : null, s: s, l: s.toLowerCase(), c: null };
}

function chunksOf(p) {
  if (p.c) return p.c;
  const out = [];
  let m;
  CHUNK_RE.lastIndex = 0;
  while ((m = CHUNK_RE.exec(p.l)) !== null) out.push(m[1] !== undefined ? { d: true, v: m[1].replace(/^0+(?=\d)/, '') } : { d: false, v: m[2] });
  p.c = out;
  return out;
}

function cmpStr(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

function comparePrepared(a, b) {
  if (a.e || b.e) return a.e === b.e ? 0 : (a.e ? -1 : 1);
  if (a.n !== null && b.n !== null && a.n !== b.n) return a.n < b.n ? -1 : 1;
  if (a.n === null || b.n === null) {
    const ca = chunksOf(a);
    const cb = chunksOf(b);
    const n = Math.min(ca.length, cb.length);
    for (let i = 0; i < n; i++) {
      const x = ca[i];
      const y = cb[i];
      if (x.d && y.d) {
        if (x.v.length !== y.v.length) return x.v.length < y.v.length ? -1 : 1;
        const c = cmpStr(x.v, y.v);
        if (c) return c;
      } else if (x.d !== y.d) {
        return x.d ? -1 : 1;
      } else {
        const c = cmpStr(x.v, y.v);
        if (c) return c;
      }
    }
    if (ca.length !== cb.length) return ca.length < cb.length ? -1 : 1;
  }
  return cmpStr(a.l, b.l) || cmpStr(a.s, b.s);
}

// Natural, case-insensitive comparator: numbers numerically, 'A-2' < 'A-10',
// empty values first. Total order: only identical values compare equal.
export function compareValues(a, b) {
  return comparePrepared(prepare(a), prepare(b));
}

// ------------------------------------------------------------ index (per rows + columns)

// Lazily cached per-column texts, sort keys and filter values for one rows array.
// datatable.js keeps one per setRows so a keystroke costs a scan of cached strings.
export function createIndex(rows, columns) {
  const list = Array.isArray(rows) ? rows : [];
  const cols = columnMap(columns);
  const texts = {};
  const preps = {};
  const fvals = {};
  const hays = {};
  function values(key, map) {
    const c = cols[key];
    const out = new Array(list.length);
    for (let i = 0; i < list.length; i++) out[i] = map(c ? c.value(list[i]) : undefined);
    return out;
  }
  return {
    rows: list,
    columns: columns,
    text: function (key) {
      if (!own(texts, key)) texts[key] = values(key, function (v) { return textOf(v).toLowerCase(); });
      return texts[key];
    },
    prep: function (key) {
      if (!own(preps, key)) preps[key] = values(key, prepare);
      return preps[key];
    },
    filterValues: function (key) {
      if (!own(fvals, key)) fvals[key] = values(key, filterValuesOf);
      return fvals[key];
    },
    hay: function (keys) {
      const id = keys.join('\u0000');
      if (!own(hays, id)) {
        const parts = keys.map(this.text, this);
        const out = new Array(list.length);
        for (let i = 0; i < list.length; i++) {
          let s = '';
          for (let j = 0; j < parts.length; j++) s += (j ? '\u0001' : '') + parts[j][i];
          out[i] = s;
        }
        hays[id] = out;
      }
      return hays[id];
    },
  };
}

// ------------------------------------------------------------ state

function tokens(q) {
  const s = String(q == null ? '' : q).trim().toLowerCase();
  return s ? s.split(/\s+/) : [];
}

function hiddenSet(columns, state) {
  const set = {};
  if (state && Array.isArray(state.hidden)) state.hidden.forEach(function (k) { set[k] = true; });
  else (columns || []).forEach(function (c) { if (c.hidden) set[c.key] = true; });
  return set;
}

function searchKeys(columns, hidden) {
  return (columns || []).filter(function (c) { return c.searchable !== false && !hidden[c.key]; }).map(function (c) { return c.key; });
}

export function cleanFilters(filters, columns) {
  const out = {};
  if (!isObj(filters)) return out;
  const known = columns ? columnMap(columns) : null;
  Object.keys(filters).forEach(function (k) {
    if (k === '__proto__' || (known && !own(known, k))) return;
    const vals = Array.isArray(filters[k]) ? filters[k] : [];
    const clean = [];
    vals.forEach(function (v) { const s = textOf(v); if (clean.indexOf(s) < 0) clean.push(s); });
    if (clean.length) out[k] = clean;
  });
  return out;
}

function cleanSort(sort, columns) {
  if (!isObj(sort) || typeof sort.col !== 'string' || !sort.col) return null;
  const dir = sort.dir === -1 || sort.dir === '-1' ? -1 : sort.dir === 1 || sort.dir === '1' ? 1 : 0;
  if (!dir) return null;
  if (columns) {
    const c = columnMap(columns)[sort.col];
    if (!c || c.sortable === false) return null;
  }
  return { col: sort.col, dir: dir };
}

function cleanPageSize(n, fallback) {
  const v = Number(n);
  return PAGE_SIZES.indexOf(v) >= 0 ? v : fallback;
}

export function defaultState(columns, opts) {
  const o = opts || {};
  return {
    q: '',
    sort: null,
    filters: {},
    page: 1,
    pageSize: cleanPageSize(o.pageSize, DEFAULT_PAGE_SIZE),
    hidden: (columns || []).filter(function (c) { return c.hidden; }).map(function (c) { return c.key; }),
    density: DENSITIES.indexOf(o.density) >= 0 ? o.density : 'normal',
    extra: {},
  };
}

function copyState(s) {
  return {
    q: s.q,
    sort: s.sort ? { col: s.sort.col, dir: s.sort.dir } : null,
    filters: cleanFilters(s.filters),
    page: s.page,
    pageSize: s.pageSize,
    hidden: (s.hidden || []).slice(),
    density: s.density,
    extra: Object.assign({}, s.extra || {}),
  };
}

function sameJson(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

// New state with `partial` applied. Changing q, sort or filters returns to page 1
// unless partial.page is given; a page-size change keeps the first visible row on
// screen. filters and hidden are replaced; extra is merged key-wise (null deletes).
export function mergeState(state, partial, columns) {
  const out = copyState(state);
  const p = partial || {};
  let reset = false;
  if (own(p, 'q')) {
    const q = String(p.q == null ? '' : p.q);
    if (q !== out.q) reset = true;
    out.q = q;
  }
  if (own(p, 'sort')) {
    const s = cleanSort(p.sort, columns);
    if (!sameJson(s, out.sort)) reset = true;
    out.sort = s;
  }
  if (own(p, 'filters')) {
    const f = cleanFilters(p.filters, columns);
    if (!sameJson(f, out.filters)) reset = true;
    out.filters = f;
  }
  if (own(p, 'pageSize')) {
    const n = cleanPageSize(p.pageSize, out.pageSize);
    if (n !== out.pageSize) {
      const first = (Math.max(1, out.page) - 1) * out.pageSize;
      out.page = Math.floor(first / n) + 1;
      out.pageSize = n;
    }
  }
  if (own(p, 'hidden')) {
    const known = columns ? columnMap(columns) : null;
    out.hidden = (Array.isArray(p.hidden) ? p.hidden : []).map(String).filter(function (k, i, a) {
      return a.indexOf(k) === i && (!known || own(known, k));
    });
  }
  if (own(p, 'density') && DENSITIES.indexOf(p.density) >= 0) out.density = p.density;
  if (own(p, 'extra') && isObj(p.extra)) {
    Object.keys(p.extra).forEach(function (k) {
      if (p.extra[k] === null || p.extra[k] === undefined) delete out.extra[k];
      else if (k !== '__proto__') out.extra[k] = p.extra[k];
    });
  }
  if (own(p, 'page')) {
    const pg = parseInt(p.page, 10);
    out.page = pg >= 1 ? pg : 1;
  } else if (reset) {
    out.page = 1;
  }
  return out;
}

// ------------------------------------------------------------ apply

export function matchesQuery(row, columns, q, hidden) {
  const toks = tokens(q);
  if (!toks.length) return true;
  const hid = hidden ? hiddenSet(columns, { hidden: hidden }) : hiddenSet(columns, null);
  const texts = (columns || []).filter(function (c) { return c.searchable !== false && !hid[c.key]; }).map(function (c) {
    return textOf(c.value(row)).toLowerCase();
  });
  return toks.every(function (t) { return texts.some(function (s) { return s.indexOf(t) >= 0; }); });
}

function groupOrderDefault(a, b) {
  if (a === '' || b === '') return a === b ? 0 : (a === '' ? 1 : -1);
  return compareValues(a, b);
}

function filteredIndices(index, columns, state) {
  const n = index.rows.length;
  const cols = columnMap(columns);
  const filters = cleanFilters(state && state.filters);
  const active = Object.keys(filters).filter(function (k) { return own(cols, k); }).map(function (k) {
    const set = {};
    filters[k].forEach(function (v) { set[v] = true; });
    return { vals: index.filterValues(k), set: set };
  });
  const toks = tokens(state && state.q);
  const hay = toks.length ? index.hay(searchKeys(columns, hiddenSet(columns, state))) : null;
  const out = [];
  for (let i = 0; i < n; i++) {
    let ok = true;
    for (let a = 0; ok && a < active.length; a++) {
      const vs = active[a].vals[i];
      let hit = false;
      for (let j = 0; j < vs.length; j++) if (active[a].set[vs[j]] === true) { hit = true; break; }
      ok = hit;
    }
    if (ok && hay) {
      const s = hay[i];
      for (let t = 0; t < toks.length; t++) if (s.indexOf(toks[t]) < 0) { ok = false; break; }
    }
    if (ok) out.push(i);
  }
  return out;
}

// -> {rows, total, filtered, pageRows, page, pages, pageSize, start}. `rows` is the
// filtered and sorted set (all pages). opts: {index (createIndex of these rows),
// groupBy (row -> label; rows are ordered group by group), groupOrder (a, b)}.
export function applyState(rows, columns, state, opts) {
  const o = opts || {};
  const list = Array.isArray(rows) ? rows : [];
  const index = o.index && o.index.rows === list ? o.index : createIndex(list, columns);
  const s = state || {};
  let idx = filteredIndices(index, columns, s);
  const sort = cleanSort(s.sort, columns);
  if (sort) {
    const keys = index.prep(sort.col);
    const dir = sort.dir;
    idx.sort(function (a, b) {
      const x = keys[a];
      const y = keys[b];
      if (x.e !== y.e) return x.e ? 1 : -1;
      return (comparePrepared(x, y) * dir) || (a - b);
    });
  }
  let sorted = idx.map(function (i) { return list[i]; });
  if (typeof o.groupBy === 'function') {
    const order = [];
    const groups = {};
    sorted.forEach(function (r) {
      const g = textOf(o.groupBy(r));
      if (!own(groups, g)) { groups[g] = []; order.push(g); }
      groups[g].push(r);
    });
    order.sort(typeof o.groupOrder === 'function' ? o.groupOrder : groupOrderDefault);
    sorted = [];
    order.forEach(function (g) { Array.prototype.push.apply(sorted, groups[g]); });
  }
  const size = Number(s.pageSize) > 0 ? Math.floor(Number(s.pageSize)) : DEFAULT_PAGE_SIZE;
  const pages = Math.max(1, Math.ceil(sorted.length / size));
  let page = parseInt(s.page, 10);
  if (!(page >= 1)) page = 1;
  if (page > pages) page = pages;
  const start = (page - 1) * size;
  return {
    rows: sorted,
    total: list.length,
    filtered: sorted.length,
    pageRows: sorted.slice(start, start + size),
    page: page,
    pages: pages,
    pageSize: size,
    start: start,
  };
}

// Sorted distinct filter values of `column` over `rows`; '' is reported once as
// EMPTY, after the other values.
export function distinctValues(rows, column, index) {
  const vals = index && column ? index.filterValues(column.key) : (Array.isArray(rows) ? rows : []).map(function (r) {
    return filterValuesOf(column ? column.value(r) : undefined);
  });
  const seen = {};
  const out = [];
  let empty = false;
  vals.forEach(function (vs) {
    vs.forEach(function (v) {
      if (v === EMPTY) { empty = true; return; }
      if (!own(seen, v)) { seen[v] = true; out.push(v); }
    });
  });
  out.sort(compareValues);
  if (empty) out.push(EMPTY);
  return out;
}

// Ids of every row in the filtered set (all pages). rowId defaults to row.id;
// canSelect, when given, drops rows that may not be selected.
export function selectAllFiltered(rows, columns, state, rowId, canSelect) {
  const idOf = typeof rowId === 'function' ? rowId : function (r) { return r.id; };
  const index = createIndex(rows, columns);
  return filteredIndices(index, columns, state || {}).map(function (i) { return index.rows[i]; })
    .filter(function (r) { return typeof canSelect !== 'function' || canSelect(r); })
    .map(function (r) { return String(idOf(r)); });
}

// ------------------------------------------------------------ CSV

function csvCell(v) {
  const s = textOf(v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

// RFC 4180 with CRLF after every line and no BOM; byte-compatible with
// schedules.js csvString. column.csv === false leaves a column out.
export function toCsv(columns, rows) {
  const cols = (columns || []).filter(function (c) { return c.csv !== false; });
  const out = [cols.map(function (c) { return csvCell(c.header); }).join(',')];
  (rows || []).forEach(function (r) {
    out.push(cols.map(function (c) { return csvCell(typeof c.csv === 'function' ? c.csv(r) : c.value(r)); }).join(','));
  });
  return out.join('\r\n') + '\r\n';
}

// ------------------------------------------------------------ URL params (D1)

export function isTableParam(key) {
  return key === 'q' || key === 'sort' || key === 'pg' || String(key).indexOf('f.') === 0;
}

function escapeFilterValue(v) {
  if (v === EMPTY) return '~';
  return String(v).replace(/[\\|~]/g, function (c) { return '\\' + c; });
}

function parseFilterParam(s) {
  const out = [];
  let cur = '';
  let raw = '';
  const str = String(s);
  function push() {
    if (raw === '~') out.push(EMPTY);
    else if (raw !== '') out.push(cur);
    cur = '';
    raw = '';
  }
  for (let i = 0; i < str.length; i++) {
    const ch = str[i];
    if (ch === '\\' && i + 1 < str.length) {
      cur += str[i + 1];
      raw += ch + str[i + 1];
      i++;
    } else if (ch === '|') {
      push();
    } else {
      cur += ch;
      raw += ch;
    }
  }
  push();
  return out.filter(function (v, i, a) { return a.indexOf(v) === i; });
}

// Table state -> D1 query keys (strings). Default values are left out.
export function stateToParams(state) {
  const s = state || {};
  const out = {};
  const q = String(s.q == null ? '' : s.q);
  if (q.trim() !== '') out.q = q;
  const sort = cleanSort(s.sort);
  if (sort) out.sort = (sort.dir < 0 ? '-' : '') + sort.col;
  const f = cleanFilters(s.filters);
  Object.keys(f).forEach(function (k) { out['f.' + k] = f[k].map(escapeFilterValue).join('|'); });
  const pg = parseInt(s.page, 10);
  if (pg > 1) out.pg = String(pg);
  return out;
}

// D1 query -> {q, sort, filters, page}; unknown columns and keys are ignored.
export function paramsToState(query, columns) {
  const q = isObj(query) ? query : {};
  const cols = columnMap(columns);
  const out = { q: '', sort: null, filters: {}, page: 1 };
  if (typeof q.q === 'string') out.q = q.q;
  if (typeof q.sort === 'string' && q.sort) {
    const desc = q.sort.charAt(0) === '-';
    out.sort = cleanSort({ col: desc ? q.sort.slice(1) : q.sort, dir: desc ? -1 : 1 }, columns);
  }
  Object.keys(q).forEach(function (k) {
    if (k.indexOf('f.') !== 0) return;
    const col = k.slice(2);
    if (!own(cols, col) || col === '__proto__') return;
    const vals = parseFilterParam(q[k]);
    if (vals.length) out.filters[col] = vals;
  });
  const pg = parseInt(q.pg, 10);
  out.page = pg >= 1 ? pg : 1;
  return out;
}

// Patch for a {get, set} URL binding: the D1 keys of `state` that differ from
// `query`, plus null for table keys in `query` that the state no longer has.
export function urlPatch(query, state) {
  const cur = isObj(query) ? query : {};
  const next = stateToParams(state);
  const patch = {};
  Object.keys(next).forEach(function (k) { if (cur[k] !== next[k]) patch[k] = next[k]; });
  Object.keys(cur).forEach(function (k) { if (isTableParam(k) && !own(next, k) && cur[k] !== '' && cur[k] != null) patch[k] = null; });
  return patch;
}

// ------------------------------------------------------------ storage (D8)

export function storageKey(scope, key) {
  return STORAGE_PREFIX + (scope ? scope + '.' : '') + key;
}

// Stored state over defaultState(columns, defaults); q and page are URL-only and
// come back as '' and 1. Missing, corrupt or other-version data gives defaults;
// columns that no longer exist are dropped.
export function loadState(storage, scope, key, columns, defaults) {
  const base = defaultState(columns, defaults);
  let raw = null;
  try { raw = storage ? storage.getItem(storageKey(scope, key)) : null; } catch (e) { raw = null; }
  if (!raw) return base;
  let j = null;
  try { j = JSON.parse(raw); } catch (e) { return base; }
  if (!isObj(j) || j.v !== STATE_VERSION) return base;
  const known = columns ? columnMap(columns) : null;
  const out = base;
  out.sort = cleanSort(j.sort, columns);
  out.filters = cleanFilters(j.filters, columns);
  out.pageSize = cleanPageSize(j.pageSize, base.pageSize);
  if (Array.isArray(j.hidden)) {
    out.hidden = j.hidden.filter(function (k, i, a) { return typeof k === 'string' && a.indexOf(k) === i && (!known || own(known, k)); });
  }
  if (DENSITIES.indexOf(j.density) >= 0) out.density = j.density;
  if (isObj(j.extra)) out.extra = Object.assign({}, j.extra);
  return out;
}

export function saveState(storage, scope, key, state) {
  const s = state || {};
  const rec = {
    v: STATE_VERSION,
    sort: cleanSort(s.sort),
    filters: cleanFilters(s.filters),
    pageSize: Number(s.pageSize) || DEFAULT_PAGE_SIZE,
    hidden: Array.isArray(s.hidden) ? s.hidden.slice() : [],
    density: DENSITIES.indexOf(s.density) >= 0 ? s.density : 'normal',
    extra: isObj(s.extra) ? s.extra : {},
  };
  try {
    if (storage) storage.setItem(storageKey(scope, key), JSON.stringify(rec));
    return true;
  } catch (e) {
    return false;
  }
}
