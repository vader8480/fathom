// T-TABLE: contract test for js/datatable-core.js (TABLE), written from docs/ui-audit.md alone:
// B.2 TABLE (API, Behaviour, Core, Tests → Core), D1 (q, sort, f.<col>, pg) and D8 (storage key/shape).
//
// Where the contract leaves a shape open, this file uses the D8 field names for the state object:
//   {q, sort: {col, dir: 1 | -1} | null, filters: {col: [values]}, page, pageSize, hidden: [col],
//    density, extra}
// with `page` 1-based (like `pg`), filter value '(empty)' standing for '' (as distinctValues reports it),
// and core functions taking columns that went through normalizeColumns.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, m, need, rng } from './fixtures/helpers.mjs';

const { mod: dt, skip: absent, error } = await loadModule('js/datatable-core.js', 'TABLE');
const sched = await loadModule('js/schedules.js', 'SCH');
const SEC = 'B.2 TABLE Core';
const skip = absent || (error ? 'datatable-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);
const fn = (name) => need(dt, name, 'TABLE', SEC);

if (error) test('datatable-core.js imports in Node (D12 pure module)', () => { throw error; });

// ---- fixtures -------------------------------------------------------------------------------

const NAMES = ['FOH CL5', 'Stage Box', 'Amp Rack', 'Dante Switch', 'Wireless Rx', 'Drum Sub'];
const STATUSES = ['ok', 'spare', 'repair', '', 'ok', 'retired'];
const N = 240;

// 240 rows in a deterministic shuffled order; tags are unpadded (A-1 … A-240) so a plain string sort
// would put A-10 before A-2.
function makeRows() {
  const out = [];
  for (let i = 0; i < N; i++) {
    const n = i + 1;
    out.push({
      id: 'r-' + String(n).padStart(3, '0'),
      n,
      name: NAMES[i % NAMES.length] + ' ' + n,
      tag: 'A-' + n,
      status: STATUSES[(i * 7 + Math.floor(i / 3)) % STATUSES.length],
      length: ((i * 37) % 97) + 1,
      notes: n === 77 ? 'zebracrossing' : 'note ' + (n % 5),
      secret: n === 99 ? 'needle' : '',
    });
  }
  const r = rng(42);
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(r() * (i + 1));
    const t = out[i]; out[i] = out[j]; out[j] = t;
  }
  return out;
}

const RAW_COLS = [
  { key: 'name', header: 'Name', value: (r) => r.name, filterable: true },
  { key: 'tag', header: 'Tag', value: (r) => r.tag },
  { key: 'status', header: 'Status', value: (r) => r.status, filterable: true },
  { key: 'length', header: 'Length', value: (r) => r.length, align: 'right' },
  { key: 'notes', header: 'Notes', value: (r) => r.notes },
  { key: 'secret', header: 'Secret', value: (r) => r.secret, searchable: false },
];

const cols = () => fn('normalizeColumns')(RAW_COLS.map((c) => Object.assign({}, c)));

function st(partial) {
  return Object.assign({ q: '', sort: null, filters: {}, page: 1, pageSize: 50, hidden: [], density: 'normal', extra: {} }, partial || {});
}

function apply(rows, partial, columns) {
  return fn('applyState')(rows, columns || cols(), st(partial));
}

const ids = (list) => Array.from(list || []).map((r) => (typeof r === 'string' ? r : r.id));
const sorted = (a) => a.slice().sort();
const statusVal = (v) => (v === '' ? '(empty)' : v);

function memStorage(init) {
  const map = new Map(Object.entries(init || {}));
  return {
    map,
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)); },
    removeItem: (k) => { map.delete(k); },
    key: (i) => Array.from(map.keys())[i] || null,
    get length() { return map.size; },
  };
}

const throwingStorage = {
  getItem() { throw new Error('SecurityError: private mode'); },
  setItem() { throw new Error('QuotaExceededError'); },
  removeItem() { throw new Error('SecurityError: private mode'); },
  key() { return null; },
  length: 0,
};

// Tolerant accessors for partial state objects (missing field = default).
const sortOf = (s) => (s && s.sort) || null;
const filtersOf = (s) => {
  const f = (s && s.filters) || {};
  const out = {};
  for (const k of Object.keys(f)) if (f[k] && f[k].length) out[k] = f[k].slice();
  return out;
};
const qOf = (s) => (s && s.q) || '';
const pageOf = (s) => (s && s.page) || 1;

function toPlain(p) {
  if (!p) return {};
  if (typeof p.entries === 'function' && !Array.isArray(p) && Object.getPrototypeOf(p) !== Object.prototype) {
    return Object.fromEntries(p.entries());
  }
  return Object.assign({}, p);
}

// ---- exports --------------------------------------------------------------------------------

T('exports every core function named in B.2 TABLE', () => {
  for (const name of ['normalizeColumns', 'applyState', 'distinctValues', 'matchesQuery', 'compareValues', 'toCsv',
    'stateToParams', 'paramsToState', 'loadState', 'saveState', 'selectAllFiltered']) {
    assert.equal(typeof fn(name), 'function', m('TABLE', SEC, name + ' must be a function'));
  }
  need(dt, 'PAGE_SIZES', 'TABLE', SEC);
});

T('PAGE_SIZES is [25, 50, 100, 200]', () => {
  assert.deepEqual(Array.from(fn('PAGE_SIZES')), [25, 50, 100, 200]);
});

// ---- normalizeColumns -----------------------------------------------------------------------

T('normalizeColumns fills the API defaults and keeps explicit options', () => {
  const out = fn('normalizeColumns')([
    { key: 'name', header: 'Name' },
    { key: 'len', header: 'Len', value: (r) => r.len * 2, sortable: false, filterable: true, searchable: false,
      hideOnMobile: true, hidden: true, align: 'right', width: 80, sticky: true },
  ]);
  assert.equal(out.length, 2);
  const [a, b] = out;
  assert.equal(a.key, 'name');
  assert.equal(a.header, 'Name');
  assert.equal(a.sortable, true);
  assert.equal(a.filterable, false);
  assert.equal(a.searchable, true);
  assert.equal(a.hideOnMobile, false);
  assert.equal(a.hidden, false);
  assert.equal(a.align, 'left');
  assert.equal(a.sticky, false);
  assert.equal(typeof a.value, 'function', 'value defaults to a function');
  assert.equal(a.value({ name: 'FOH CL5' }), 'FOH CL5', 'default value reads row[key]');
  assert.equal(b.sortable, false);
  assert.equal(b.filterable, true);
  assert.equal(b.searchable, false);
  assert.equal(b.hideOnMobile, true);
  assert.equal(b.hidden, true);
  assert.equal(b.align, 'right');
  assert.equal(b.width, 80);
  assert.equal(b.sticky, true);
  assert.equal(b.value({ len: 4 }), 8);
});

// ---- compareValues --------------------------------------------------------------------------

T('compareValues sorts naturally: tags, numbers and embedded digits', () => {
  const cmp = fn('compareValues');
  assert.ok(cmp('A-002', 'A-010') < 0, 'A-002 < A-010');
  assert.ok(cmp('A-010', 'A-002') > 0, 'A-010 > A-002');
  assert.ok(cmp('A-2', 'A-10') < 0, 'A-2 < A-10 (natural, not lexical)');
  assert.ok(cmp('item 9', 'item 10') < 0, 'item 9 < item 10');
  assert.ok(cmp(2, 10) < 0, '2 < 10 numerically');
  assert.ok(cmp(10, 9) > 0, '10 > 9 numerically');
  assert.ok(cmp('2', '10') < 0, '"2" < "10" naturally');
  assert.ok(cmp(1.5, 1.25) > 0, '1.5 > 1.25');
  assert.equal(cmp('A-007', 'A-007'), 0);
  assert.equal(cmp(3, 3), 0);
});

T('compareValues is a consistent comparator (antisymmetric on a mixed list)', () => {
  const cmp = fn('compareValues');
  const vals = ['A-1', 'A-10', 'A-2', 'B-1', 'a-3', 'item 10', 'item 9', 'Zed', 'alpha', '7', '70', '8'];
  for (const a of vals) for (const b of vals) {
    assert.equal(Math.sign(cmp(a, b)) || 0, -Math.sign(cmp(b, a)) || 0, `sign(cmp(${a},${b})) = -sign(cmp(${b},${a}))`);
  }
});

// ---- applyState: sort -----------------------------------------------------------------------

T('applyState sorts a tag column naturally (A-1, A-2 … A-240) without mutating the input', () => {
  const rows = makeRows();
  const before = ids(rows);
  const res = apply(rows, { sort: { col: 'tag', dir: 1 }, pageSize: 200 });
  assert.equal(res.total, N);
  assert.equal(res.filtered, N);
  assert.equal(res.rows.length, N);
  assert.deepEqual(res.rows.map((r) => r.tag), Array.from({ length: N }, (_, i) => 'A-' + (i + 1)));
  assert.deepEqual(ids(rows), before, 'input array order unchanged');
  const desc = apply(rows, { sort: { col: 'tag', dir: -1 }, pageSize: 200 });
  assert.deepEqual(desc.rows.map((r) => r.tag), Array.from({ length: N }, (_, i) => 'A-' + (N - i)));
});

T('applyState sorts numbers numerically and is stable on ties', () => {
  const rows = makeRows();
  const res = apply(rows, { sort: { col: 'length', dir: 1 } });
  const lens = res.rows.map((r) => r.length);
  for (let i = 1; i < lens.length; i++) assert.ok(lens[i - 1] <= lens[i], `length ascending at ${i}: ${lens[i - 1]} <= ${lens[i]}`);
  const pos = new Map(rows.map((r, i) => [r.id, i]));
  for (let i = 1; i < res.rows.length; i++) {
    const a = res.rows[i - 1]; const b = res.rows[i];
    if (a.length === b.length) assert.ok(pos.get(a.id) < pos.get(b.id), `ties on length ${a.length} keep input order`);
  }
  const d = apply(rows, { sort: { col: 'length', dir: -1 } }).rows.map((r) => r.length);
  for (let i = 1; i < d.length; i++) assert.ok(d[i - 1] >= d[i], 'length descending');
});

T('applyState with sort null keeps input order', () => {
  const rows = makeRows();
  assert.deepEqual(ids(apply(rows, { sort: null, pageSize: 200 }).rows), ids(rows).slice(0, N));
});

// ---- applyState: filters --------------------------------------------------------------------

T('filter on "(empty)" selects rows whose value is the empty string', () => {
  const rows = makeRows();
  const res = apply(rows, { filters: { status: ['(empty)'] }, pageSize: 200 });
  const want = rows.filter((r) => r.status === '');
  assert.ok(want.length > 0);
  assert.equal(res.filtered, want.length);
  assert.deepEqual(sorted(ids(res.rows)), sorted(ids(want)));
});

T('filters are OR within a column and AND across columns', () => {
  const rows = makeRows();
  const or = apply(rows, { filters: { status: ['spare', '(empty)'] }, pageSize: 200 });
  assert.deepEqual(sorted(ids(or.rows)), sorted(ids(rows.filter((r) => r.status === 'spare' || r.status === ''))));
  const and = apply(rows, { filters: { status: ['spare', '(empty)'], name: ['Stage Box 2', 'Stage Box 8', 'FOH CL5 1'] }, pageSize: 200 });
  const want = rows.filter((r) => (r.status === 'spare' || r.status === '') && ['Stage Box 2', 'Stage Box 8', 'FOH CL5 1'].includes(r.name));
  assert.deepEqual(sorted(ids(and.rows)), sorted(ids(want)));
  assert.equal(and.total, N);
});

T('state naming unknown columns (stale storage) does not throw or drop rows', () => {
  const rows = makeRows();
  const res = apply(rows, { sort: { col: 'gone', dir: 1 }, filters: { gone: ['x'] }, hidden: ['gone'] });
  assert.equal(res.total, N);
  assert.equal(res.filtered, N);
});

// ---- search ---------------------------------------------------------------------------------

T('matchesQuery: case-insensitive, AND across tokens, any searchable column per token', () => {
  const mq = fn('matchesQuery');
  const c = cols();
  const row = { name: 'FOH CL5 7', tag: 'A-7', status: 'ok', length: 12, notes: 'Drum riser', secret: 'needle' };
  assert.equal(mq(row, c, ''), true, 'empty query matches');
  assert.equal(mq(row, c, 'foh'), true);
  assert.equal(mq(row, c, 'cl5 drum'), true, 'tokens may match different columns');
  assert.equal(mq(row, c, '  DRUM   foh '), true, 'case and extra whitespace ignored');
  assert.equal(mq(row, c, 'foh guitar'), false, 'every token must match');
  assert.equal(mq(row, c, 'needle'), false, 'searchable:false columns are not searched');
});

T('matchesQuery skips hidden columns', () => {
  const mq = fn('matchesQuery');
  const c = fn('normalizeColumns')(RAW_COLS.map((x) => Object.assign({}, x, x.key === 'notes' ? { hidden: true } : {})));
  const row = { name: 'Amp Rack 3', tag: 'A-3', status: 'ok', length: 1, notes: 'zebracrossing', secret: '' };
  assert.equal(mq(row, c, 'zebra'), false);
  assert.equal(mq(row, c, 'amp'), true);
});

T('applyState search spans visible searchable columns only', () => {
  const rows = makeRows();
  const one = apply(rows, { q: 'stage A-14' });
  assert.deepEqual(ids(one.rows).sort(), ids(rows.filter((r) => /stage/i.test(r.name) && /a-14/i.test(r.tag))).sort());
  assert.ok(one.filtered >= 1);
  assert.equal(apply(rows, { q: 'ZEBRA' }).filtered, 1, 'notes searched when visible');
  assert.equal(apply(rows, { q: 'zebra', hidden: ['notes'] }).filtered, 0, 'notes not searched when hidden');
  assert.equal(apply(rows, { q: 'needle' }).filtered, 0, 'searchable:false column not searched');
  const none = apply(rows, { q: 'nothing-matches-this' });
  assert.equal(none.filtered, 0);
  assert.deepEqual(Array.from(none.pageRows), []);
});

// ---- distinctValues -------------------------------------------------------------------------

function valuesOf(list) {
  return Array.from(list).map((v) => (v && typeof v === 'object' ? (v.value !== undefined ? v.value : v.label) : v));
}

T('distinctValues: unique, naturally sorted, "" reported once as "(empty)"', () => {
  const c = cols();
  const vals = valuesOf(fn('distinctValues')(makeRows(), c.find((x) => x.key === 'status')));
  assert.equal(vals.filter((v) => v === '(empty)').length, 1, '(empty) appears exactly once');
  assert.ok(!vals.includes(''), 'the empty string itself is not listed');
  assert.equal(new Set(vals).size, vals.length, 'no duplicates');
  assert.deepEqual(sorted(vals), sorted(['ok', 'spare', 'repair', 'retired', '(empty)']));
  const nonEmpty = vals.filter((v) => v !== '(empty)');
  assert.deepEqual(nonEmpty, ['ok', 'repair', 'retired', 'spare']);
  const tags = valuesOf(fn('distinctValues')([{ tag: 'A-10' }, { tag: 'A-2' }, { tag: 'A-2' }, { tag: 'A-1' }], c.find((x) => x.key === 'tag')));
  assert.deepEqual(tags, ['A-1', 'A-2', 'A-10']);
});

// ---- pagination -----------------------------------------------------------------------------

T('pagination: 240 rows at 25 per page = 10 pages; slices and last page', () => {
  const rows = makeRows();
  const p1 = apply(rows, { sort: { col: 'tag', dir: 1 }, pageSize: 25, page: 1 });
  assert.equal(p1.pages, 10);
  assert.equal(p1.page, 1);
  assert.deepEqual(p1.pageRows.map((r) => r.tag), Array.from({ length: 25 }, (_, i) => 'A-' + (i + 1)));
  const p3 = apply(rows, { sort: { col: 'tag', dir: 1 }, pageSize: 50, page: 3 });
  assert.equal(p3.pages, 5);
  assert.equal(p3.page, 3);
  assert.deepEqual(p3.pageRows.map((r) => r.tag), Array.from({ length: 50 }, (_, i) => 'A-' + (101 + i)));
  const last = apply(rows, { sort: { col: 'tag', dir: 1 }, pageSize: 100, page: 3 });
  assert.equal(last.pages, 3);
  assert.equal(last.pageRows.length, 40);
  assert.equal(last.pageRows[0].tag, 'A-201');
});

T('pagination: page beyond the end clamps to the last page when filters shrink rows', () => {
  const rows = makeRows();
  const all = apply(rows, { sort: { col: 'tag', dir: 1 }, pageSize: 25, page: 8 });
  assert.equal(all.page, 8);
  const spare = rows.filter((r) => r.status === 'spare').length;
  assert.ok(spare > 25 && spare <= 50, 'fixture: spare rows span two pages of 25');
  const res = apply(rows, { sort: { col: 'tag', dir: 1 }, pageSize: 25, page: 8, filters: { status: ['spare'] } });
  assert.equal(res.filtered, spare);
  assert.equal(res.pages, 2);
  assert.equal(res.page, 2, 'page clamps to the last page');
  assert.deepEqual(ids(res.pageRows), ids(res.rows.slice(25)));
  const low = apply(rows, { pageSize: 25, page: 0 });
  assert.equal(low.page, 1, 'page below 1 clamps to 1');
});

// ---- select all -----------------------------------------------------------------------------

T('selectAllFiltered returns every filtered id across all pages, and nothing else', () => {
  const rows = makeRows();
  const state = st({ filters: { status: ['ok', '(empty)'] }, q: '', pageSize: 25, page: 1 });
  const got = Array.from(fn('selectAllFiltered')(rows, cols(), state));
  const want = ids(rows.filter((r) => r.status === 'ok' || r.status === ''));
  assert.ok(want.length > 25, 'fixture spans several pages');
  assert.deepEqual(sorted(got), sorted(want));
  const q = Array.from(fn('selectAllFiltered')(rows, cols(), st({ q: 'drum', filters: { status: ['ok'] }, pageSize: 25 })));
  assert.deepEqual(sorted(q), sorted(ids(rows.filter((r) => /drum/i.test(r.name) && r.status === 'ok'))));
});

// ---- CSV ------------------------------------------------------------------------------------

// Five vectors; `expect` strings are what schedules.js csvString produces for the same header labels and
// cell values (quote only on `"`, `,`, CR or LF; double inner quotes; CRLF after every line; no BOM).
const CSV_VECTORS = [
  {
    name: 'plain values',
    columns: [{ key: 'name', header: 'Name' }, { key: 'tag', header: 'Tag' }],
    rows: [{ name: 'FOH CL5', tag: 'A-001' }, { name: 'Stage Box', tag: 'A-002' }],
    expect: 'Name,Tag\r\nFOH CL5,A-001\r\nStage Box,A-002\r\n',
  },
  {
    name: 'comma in a value and in a header',
    columns: [{ key: 'loc', header: 'Room, rack' }, { key: 'n', header: 'N' }],
    rows: [{ loc: 'Main, FOH', n: 'x' }],
    expect: '"Room, rack",N\r\n"Main, FOH",x\r\n',
  },
  {
    name: 'double quotes are doubled',
    columns: [{ key: 'model', header: 'Model' }],
    rows: [{ model: '19" rack' }, { model: '"quoted"' }],
    expect: 'Model\r\n"19"" rack"\r\n"""quoted"""\r\n',
  },
  {
    name: 'LF, CRLF and CR inside values',
    columns: [{ key: 'notes', header: 'Notes' }, { key: 'k', header: 'K' }],
    rows: [{ notes: 'line 1\nline 2', k: 'a' }, { notes: 'x\r\ny', k: 'b' }, { notes: 'cr\ronly', k: 'c' }],
    expect: 'Notes,K\r\n"line 1\nline 2",a\r\n"x\r\ny",b\r\n"cr\ronly",c\r\n',
  },
  {
    name: 'null, undefined, numbers, spaces and semicolons',
    columns: [{ key: 'a', header: 'A' }, { key: 'b', header: 'B' }, { key: 'c', header: 'C' }, { key: 'd', header: 'D' }],
    rows: [{ a: null, b: undefined, c: 0, d: ' pad ' }, { a: 12.5, b: 'x;y', c: -3, d: '' }],
    expect: 'A,B,C,D\r\n,,0, pad \r\n12.5,x;y,-3,\r\n',
  },
];

T('toCsv matches schedules.js csvString byte for byte on 5 vectors (RFC 4180, CRLF, no BOM)', () => {
  const toCsv = fn('toCsv');
  const csvString = sched.mod && sched.mod.csvString;
  for (const v of CSV_VECTORS) {
    if (csvString) {
      const ref = csvString(v.columns.map((c) => ({ key: c.key, label: c.header })), v.rows);
      assert.equal(ref, v.expect, `fixture check: csvString agrees with the literal for "${v.name}"`);
    }
    const out = toCsv(fn('normalizeColumns')(v.columns.map((c) => Object.assign({}, c))), v.rows);
    assert.equal(out, v.expect, v.name);
    assert.notEqual(out.charCodeAt(0), 0xfeff, 'no BOM');
  }
});

T('toCsv uses column.csv over column.value, and value over row[key]', () => {
  const columns = fn('normalizeColumns')([
    { key: 'len', header: 'Length', value: (r) => r.len, csv: (r) => r.len + ' m' },
    { key: 'name', header: 'Name', value: (r) => r.name.toUpperCase() },
  ]);
  assert.equal(fn('toCsv')(columns, [{ len: 3, name: 'foh, left' }]), 'Length,Name\r\n3 m,"FOH, LEFT"\r\n');
  assert.equal(fn('toCsv')(columns, []), 'Length,Name\r\n', 'no rows: header line only');
});

// ---- URL params (D1) ------------------------------------------------------------------------

T('stateToParams writes q, sort (col / -col), f.<col> and 1-based pg as strings', () => {
  const p = toPlain(fn('stateToParams')(st({
    q: 'drum', sort: { col: 'length', dir: -1 }, filters: { status: ['spare', '(empty)'] }, page: 3, pageSize: 25,
    hidden: ['notes'], density: 'compact',
  })));
  assert.equal(p.q, 'drum');
  assert.equal(p.sort, '-length');
  assert.equal(p['f.status'], 'spare|~');
  assert.equal(p.pg, '3');
  for (const k of Object.keys(p)) {
    assert.ok(k === 'q' || k === 'sort' || k === 'pg' || k.indexOf('f.') === 0, `only D1 table keys are written (got ${k})`);
  }
  const asc = toPlain(fn('stateToParams')(st({ sort: { col: 'tag', dir: 1 } })));
  assert.equal(asc.sort, 'tag');
  const blank = toPlain(fn('stateToParams')(st({})));
  for (const k of ['q', 'sort']) assert.ok(blank[k] === undefined || blank[k] === '' || blank[k] === null, `${k} empty for default state`);
  assert.ok(!Object.keys(blank).some((k) => k.indexOf('f.') === 0 && blank[k]), 'no f.* for no filters');
});

T('stateToParams escapes |, ~ and \\ with a backslash; "(empty)" alone is ~', () => {
  const enc = (vals) => toPlain(fn('stateToParams')(st({ filters: { status: vals } })))['f.status'];
  assert.equal(enc(['a|b']), 'a\\|b');
  assert.equal(enc(['~']), '\\~');
  assert.equal(enc(['c\\d']), 'c\\\\d');
  assert.equal(enc(['(empty)']), '~');
  assert.equal(enc(['x', '(empty)']), 'x|~');
});

T('paramsToState parses -col, f.<col> escapes, ~ and pg; ignores unknown columns and keys', () => {
  const s = fn('paramsToState')({
    q: 'foh', sort: '-length', 'f.status': 'ok|~|a\\|b|\\~|c\\\\d', pg: '4', 'f.gone': 'x', sel: 'device:foh-cl5', hl: 'r-001',
  }, cols());
  assert.equal(qOf(s), 'foh');
  assert.deepEqual(sortOf(s), { col: 'length', dir: -1 });
  assert.deepEqual(filtersOf(s), { status: ['ok', '(empty)', 'a|b', '~', 'c\\d'] });
  assert.equal(pageOf(s), 4);
  assert.deepEqual(sortOf(fn('paramsToState')({ sort: 'tag' }, cols())), { col: 'tag', dir: 1 });
  assert.equal(sortOf(fn('paramsToState')({ sort: '-gone' }, cols())), null, 'sort on an unknown column is dropped');
  const empty = fn('paramsToState')({}, cols());
  assert.equal(qOf(empty), '');
  assert.equal(sortOf(empty), null);
  assert.deepEqual(filtersOf(empty), {});
  assert.equal(pageOf(empty), 1);
});

T('params round trip with |, ~, \\ and "(empty)" in filter values', () => {
  const c = cols();
  const cases = [
    st({ q: 'stage box', sort: { col: 'tag', dir: 1 }, filters: { status: ['ok'] }, page: 2 }),
    st({ sort: { col: 'length', dir: -1 }, filters: { status: ['a|b', '~', 'c\\d', '(empty)', 'pipe|tilde~back\\slash', '\\|~'] }, page: 7 }),
    st({ filters: { status: ['(empty)'], name: ['FOH CL5 1', 'x|y'] } }),
    st({ q: 'A-1|2 ~x' }),
  ];
  for (const s of cases) {
    const back = fn('paramsToState')(toPlain(fn('stateToParams')(s)), c);
    assert.equal(qOf(back), s.q, 'q');
    assert.deepEqual(sortOf(back), s.sort, 'sort');
    assert.deepEqual(filtersOf(back), filtersOf(s), 'filters');
    assert.equal(pageOf(back), s.page, 'pg');
  }
});

// ---- storage (D8) ---------------------------------------------------------------------------

T('saveState writes fathom.ui.table.<scope>.<key> as versioned JSON in the D8 shape', () => {
  const storage = memStorage();
  const state = st({ sort: { col: 'tag', dir: -1 }, filters: { status: ['spare', '(empty)'] }, pageSize: 100,
    hidden: ['notes'], density: 'compact', extra: { group: 'room' } });
  fn('saveState')(storage, 'campus', 'inventory', state);
  const raw = storage.getItem('fathom.ui.table.campus.inventory');
  assert.ok(raw, 'stored under fathom.ui.table.campus.inventory');
  const j = JSON.parse(raw);
  assert.equal(j.v, 1);
  assert.deepEqual(j.sort, { col: 'tag', dir: -1 });
  assert.deepEqual(j.filters, { status: ['spare', '(empty)'] });
  assert.equal(j.pageSize, 100);
  assert.deepEqual(j.hidden, ['notes']);
  assert.equal(j.density, 'compact');
  assert.deepEqual(j.extra, { group: 'room' });
  assert.equal(storage.length, 1, 'one key written');
});

T('empty scope drops the scope and its dot: fathom.ui.table.<key>', () => {
  const storage = memStorage();
  fn('saveState')(storage, '', 'templates', st({ pageSize: 25 }));
  assert.ok(storage.getItem('fathom.ui.table.templates'), 'stored under fathom.ui.table.templates');
  assert.equal(storage.getItem('fathom.ui.table..templates'), null);
  const s = fn('loadState')(storage, '', 'templates');
  assert.equal(s.pageSize, 25);
});

T('loadState round-trips saveState and keeps scopes apart', () => {
  const storage = memStorage();
  const state = st({ sort: { col: 'length', dir: 1 }, filters: { status: ['ok'] }, pageSize: 200, hidden: ['secret'], density: 'compact', extra: { mode: 'rows' } });
  fn('saveState')(storage, 'campus', 'inventory', state);
  const s = fn('loadState')(storage, 'campus', 'inventory', cols());
  assert.deepEqual(sortOf(s), state.sort);
  assert.deepEqual(filtersOf(s), state.filters);
  assert.equal(s.pageSize, 200);
  assert.deepEqual(s.hidden, ['secret']);
  assert.equal(s.density, 'compact');
  assert.deepEqual(s.extra, { mode: 'rows' });
  const other = fn('loadState')(storage, 'sunday-demo', 'inventory', cols()) || {};
  assert.equal(sortOf(other), null, 'another project sees defaults');
  assert.deepEqual(filtersOf(other), {});
});

T('loadState falls back to defaults on missing, corrupt or wrong-version data', () => {
  const key = 'fathom.ui.table.campus.inventory';
  const defaults = (s) => {
    assert.equal(sortOf(s), null);
    assert.deepEqual(filtersOf(s), {});
    assert.ok(!s || !s.hidden || s.hidden.length === 0, 'no hidden columns');
    assert.ok(!s || s.pageSize === undefined || s.pageSize !== 200, 'stored pageSize not applied');
  };
  defaults(fn('loadState')(memStorage(), 'campus', 'inventory', cols()));
  for (const raw of ['{not json', 'null', '"str"', '[]', '42', '']) {
    defaults(fn('loadState')(memStorage({ [key]: raw }), 'campus', 'inventory', cols()));
  }
  const v2 = JSON.stringify({ v: 2, sort: { col: 'tag', dir: 1 }, filters: { status: ['ok'] }, pageSize: 200, hidden: ['notes'] });
  defaults(fn('loadState')(memStorage({ [key]: v2 }), 'campus', 'inventory', cols()));
  const nov = JSON.stringify({ sort: { col: 'tag', dir: 1 }, filters: { status: ['ok'] }, pageSize: 200, hidden: ['notes'] });
  defaults(fn('loadState')(memStorage({ [key]: nov }), 'campus', 'inventory', cols()));
});

T('loadState ignores unknown columns in stored state', () => {
  const key = 'fathom.ui.table.campus.inventory';
  const raw = JSON.stringify({ v: 1, sort: { col: 'gone', dir: 1 }, filters: { gone: ['x'], status: ['spare'] },
    pageSize: 25, hidden: ['gone', 'notes'], density: 'normal', extra: {} });
  const s = fn('loadState')(memStorage({ [key]: raw }), 'campus', 'inventory', cols());
  assert.equal(s.pageSize, 25, 'known fields survive');
  assert.ok((s.hidden || []).includes('notes'), 'known hidden column kept');
  assert.equal(filtersOf(s).status && filtersOf(s).status[0], 'spare', 'known filter kept');
  const res = fn('applyState')(makeRows(), cols(), st(Object.assign({}, s, { q: '', page: 1 })));
  const spare = makeRows().filter((r) => r.status === 'spare').length;
  assert.equal(res.filtered, spare, 'stale filter on an unknown column does not drop rows');
});

T('loadState and saveState tolerate a throwing storage (Safari private mode)', () => {
  let s;
  assert.doesNotThrow(() => { s = fn('loadState')(throwingStorage, 'campus', 'inventory', cols()); });
  assert.equal(sortOf(s), null);
  assert.deepEqual(filtersOf(s), {});
  assert.doesNotThrow(() => fn('saveState')(throwingStorage, 'campus', 'inventory', st({ pageSize: 25 })));
});
