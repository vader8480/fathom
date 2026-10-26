// TABLE: unit tests for js/datatable-core.js beyond tests/js/datatable-contract.test.mjs
// (index caching, grouping, merge rules, URL patches, array values, edge cases).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadFixtureDoc, rng } from './fixtures/helpers.mjs';

const { mod: dt, skip, error } = await loadModule('js/datatable-core.js', 'TABLE');
if (error) test('datatable-core.js imports in Node', () => { throw error; });
const T = (name, fn) => test(name, { skip: skip || !!error }, fn);

const COLS = () => dt.normalizeColumns([
  { key: 'name', header: 'Name', filterable: true },
  { key: 'tag', header: 'Tag' },
  { key: 'status', header: 'Status', filterable: true },
  { key: 'len', header: 'Length', align: 'right' },
  { key: 'tags', header: 'Tags', filterable: true },
  { key: 'act', header: '', sortable: false, searchable: false, csv: false },
]);
const ROWS = [
  { id: 'a', name: 'FOH CL5', tag: 'A-10', status: 'ok', len: 12, tags: ['audio', 'foh'] },
  { id: 'b', name: 'Stage Box', tag: 'A-2', status: '', len: 3.5, tags: [] },
  { id: 'c', name: 'amp rack', tag: 'A-002', status: 'spare', len: null, tags: ['audio'] },
  { id: 'd', name: 'Dante Switch', tag: 'B-1', status: 'ok', len: 40, tags: ['network'] },
];
const st = (p) => Object.assign(dt.defaultState(COLS()), p || {});
const ids = (res) => res.rows.map((r) => r.id);

T('compareValues: empties first, numeric strings numeric, case-insensitive, leading zeros stable', () => {
  const c = dt.compareValues;
  assert.ok(c('', 'a') < 0 && c(null, 0) < 0 && c(undefined, '') === 0);
  assert.ok(c('9.5', '10') < 0, 'numeric strings compare as numbers');
  assert.ok(c('alpha', 'Beta') < 0 && c('Beta', 'alpha') > 0);
  assert.ok(c('A-2', 'A-002') !== 0, 'distinct strings never tie');
  assert.equal(Math.sign(c('A-2', 'A-002')), -Math.sign(c('A-002', 'A-2')));
  assert.ok(c('10.20.0.9', '10.20.0.10') < 0, 'IP-like strings sort per octet');
  assert.ok(c(['b', 'a'], 'b, a') === 0, 'arrays compare by their joined text');
});

T('compareValues gives a total order a shuffled list sorts into deterministically', () => {
  const vals = ['A-10', 'a-2', 'A-2', 'A-002', 'B', 'b', '', '7', '07', '70', 'item 9', 'item 10', '10.0.0.2', '10.0.0.10'];
  const r = rng(3);
  const once = vals.slice().sort(dt.compareValues);
  for (let k = 0; k < 20; k++) {
    const sh = vals.slice().sort(() => r() - 0.5);
    assert.deepEqual(sh.sort(dt.compareValues), once);
  }
  assert.equal(once[0], '');
});

T('applyState puts empty values last in both directions', () => {
  const asc = dt.applyState(ROWS, COLS(), st({ sort: { col: 'len', dir: 1 } }));
  assert.deepEqual(ids(asc), ['b', 'a', 'd', 'c']);
  const desc = dt.applyState(ROWS, COLS(), st({ sort: { col: 'len', dir: -1 } }));
  assert.deepEqual(ids(desc), ['d', 'a', 'b', 'c']);
});

T('applyState ignores sort on a non-sortable column', () => {
  assert.deepEqual(ids(dt.applyState(ROWS, COLS(), st({ sort: { col: 'act', dir: 1 } }))), ['a', 'b', 'c', 'd']);
});

T('array values: each element is a filter value; [] counts as (empty); search uses the joined text', () => {
  const c = COLS();
  const tags = c.find((x) => x.key === 'tags');
  assert.deepEqual(dt.distinctValues(ROWS, tags), ['audio', 'foh', 'network', '(empty)']);
  assert.deepEqual(ids(dt.applyState(ROWS, c, st({ filters: { tags: ['audio'] } }))), ['a', 'c']);
  assert.deepEqual(ids(dt.applyState(ROWS, c, st({ filters: { tags: ['(empty)'] } }))), ['b']);
  assert.deepEqual(ids(dt.applyState(ROWS, c, st({ q: 'network' }))), ['d']);
});

T('a cached index gives the same results as a fresh one and is reused only for the same rows', () => {
  const c = COLS();
  const index = dt.createIndex(ROWS, c);
  const states = [st({ q: 'a' }), st({ q: 'a-', sort: { col: 'tag', dir: 1 } }), st({ filters: { status: ['ok'] }, sort: { col: 'name', dir: -1 } })];
  for (const s of states) {
    assert.deepEqual(ids(dt.applyState(ROWS, c, s, { index })), ids(dt.applyState(ROWS, c, s)));
  }
  const other = ROWS.slice(0, 2);
  assert.deepEqual(ids(dt.applyState(other, c, st(), { index })), ['a', 'b'], 'index for other rows is ignored');
});

T('groupBy orders rows group by group (natural, empty group last) and keeps the sort inside groups', () => {
  const rows = [
    { id: '1', name: 'x', room: 'Lobby', n: 3 }, { id: '2', name: 'y', room: '', n: 1 },
    { id: '3', name: 'z', room: 'Chapel', n: 2 }, { id: '4', name: 'w', room: 'Lobby', n: 1 },
  ];
  const c = dt.normalizeColumns([{ key: 'name' }, { key: 'n' }]);
  const res = dt.applyState(rows, c, dt.defaultState(c, {}), { groupBy: (r) => r.room });
  assert.deepEqual(res.rows.map((r) => r.id), ['3', '1', '4', '2']);
  const sorted = dt.applyState(rows, c, Object.assign(dt.defaultState(c), { sort: { col: 'n', dir: 1 } }), { groupBy: (r) => r.room });
  assert.deepEqual(sorted.rows.map((r) => r.id), ['3', '4', '1', '2']);
  const custom = dt.applyState(rows, c, dt.defaultState(c), { groupBy: (r) => r.room, groupOrder: (a, b) => (a < b ? 1 : a > b ? -1 : 0) });
  assert.deepEqual(custom.rows.map((r) => r.id), ['1', '4', '3', '2']);
});

T('applyState reports start and pageSize, and defaults a bad pageSize to 50', () => {
  const rows = Array.from({ length: 120 }, (_, i) => ({ id: String(i), name: 'n' + i }));
  const c = dt.normalizeColumns([{ key: 'name' }]);
  const res = dt.applyState(rows, c, { page: 2, pageSize: 0 });
  assert.equal(res.pageSize, 50);
  assert.equal(res.start, 50);
  assert.equal(res.pages, 3);
  const empty = dt.applyState([], c, { page: 4, pageSize: 25 });
  assert.equal(empty.page, 1);
  assert.equal(empty.pages, 1);
  assert.deepEqual(empty.pageRows, []);
});

T('defaultState takes default-hidden columns and valid options only', () => {
  const c = dt.normalizeColumns([{ key: 'a' }, { key: 'b', hidden: true }]);
  const s = dt.defaultState(c, { pageSize: 100, density: 'compact' });
  assert.deepEqual(s.hidden, ['b']);
  assert.equal(s.pageSize, 100);
  assert.equal(s.density, 'compact');
  const bad = dt.defaultState(c, { pageSize: 30, density: 'tiny' });
  assert.equal(bad.pageSize, 50);
  assert.equal(bad.density, 'normal');
});

T('mergeState: q/sort/filter changes return to page 1; explicit page wins; extra merges key-wise', () => {
  const c = COLS();
  const s = st({ page: 4, extra: { mode: 'rows', keep: 1 } });
  assert.equal(dt.mergeState(s, { q: 'x' }, c).page, 1);
  assert.equal(dt.mergeState(s, { q: '' }, c).page, 4, 'unchanged q keeps the page');
  assert.equal(dt.mergeState(s, { sort: { col: 'tag', dir: -1 } }, c).page, 1);
  assert.equal(dt.mergeState(s, { filters: { status: ['ok'] } }, c).page, 1);
  assert.equal(dt.mergeState(s, { q: 'x', page: 3 }, c).page, 3);
  assert.equal(dt.mergeState(s, { hidden: ['tag'] }, c).page, 4);
  assert.deepEqual(dt.mergeState(s, { extra: { mode: 'blocks', keep: null } }, c).extra, { mode: 'blocks' });
  assert.equal(dt.mergeState(s, { sort: { col: 'gone', dir: 1 } }, c).sort, null);
  assert.deepEqual(dt.mergeState(s, { hidden: ['gone', 'tag', 'tag'] }, c).hidden, ['tag']);
  assert.deepEqual(dt.mergeState(s, { filters: { status: [], gone: ['x'] } }, c).filters, {});
  assert.equal(s.page, 4, 'input state not mutated');
});

T('mergeState keeps the first visible row on screen when the page size changes', () => {
  const s = st({ page: 3, pageSize: 25 });
  assert.equal(dt.mergeState(s, { pageSize: 50 }).page, 2, 'row 51 is on page 2 of 50');
  assert.equal(dt.mergeState(s, { pageSize: 200 }).page, 1);
  assert.equal(dt.mergeState(s, { pageSize: 33 }).pageSize, 25, 'sizes outside PAGE_SIZES are refused');
});

T('urlPatch writes changed D1 keys and nulls stale table keys only', () => {
  const query = { q: 'old', sort: 'tag', 'f.status': 'ok', pg: '3', sel: 'device:x', page: 'power-up' };
  const p = dt.urlPatch(query, st({ q: 'new', sort: { col: 'tag', dir: 1 }, page: 1 }));
  assert.deepEqual(p, { q: 'new', 'f.status': null, pg: null });
  assert.deepEqual(dt.urlPatch({ q: 'x' }, st({ q: 'x' })), {}, 'no change, empty patch');
  assert.ok(dt.isTableParam('f.room') && dt.isTableParam('pg') && !dt.isTableParam('page') && !dt.isTableParam('sel'));
});

T('paramsToState: trailing backslash, empty parts, duplicates and bad pg are tolerated', () => {
  const c = COLS();
  const s = dt.paramsToState({ 'f.status': 'a\\', 'f.name': '||x|x|', pg: 'abc', sort: '-' }, c);
  assert.deepEqual(s.filters, { status: ['a\\'], name: ['x'] });
  assert.equal(s.page, 1);
  assert.equal(s.sort, null);
  assert.equal(dt.paramsToState({ sort: 'act' }, c).sort, null, 'non-sortable column dropped');
  assert.deepEqual(dt.paramsToState(null, c), { q: '', sort: null, filters: {}, page: 1 });
});

T('toCsv leaves csv:false columns out and joins array values', () => {
  const c = COLS();
  const out = dt.toCsv(c, [ROWS[0]]);
  assert.equal(out, 'Name,Tag,Status,Length,Tags\r\nFOH CL5,A-10,ok,12,"audio, foh"\r\n');
});

T('selectAllFiltered honours rowId and canSelect', () => {
  const c = COLS();
  const got = dt.selectAllFiltered(ROWS, c, st({ filters: { tags: ['audio'] } }), (r) => 'x-' + r.id, (r) => r.id !== 'c');
  assert.deepEqual(got, ['x-a']);
});

T('storageKey and loadState defaults option; extra survives as a copy', () => {
  assert.equal(dt.storageKey('campus', 'inventory'), 'fathom.ui.table.campus.inventory');
  assert.equal(dt.storageKey('', 'templates'), 'fathom.ui.table.templates');
  const map = new Map();
  const storage = { getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: (k, v) => map.set(k, v) };
  assert.equal(dt.loadState(storage, 's', 'k', COLS(), { pageSize: 25 }).pageSize, 25);
  const extra = { mode: 'rows' };
  dt.saveState(storage, 's', 'k', st({ extra, density: 'bogus', pageSize: 100 }));
  const back = dt.loadState(storage, 's', 'k', COLS(), { pageSize: 25 });
  assert.equal(back.pageSize, 100);
  assert.equal(back.density, 'normal');
  assert.deepEqual(back.extra, extra);
  assert.notEqual(back.extra, extra);
  assert.equal(back.q, '');
  assert.equal(back.page, 1);
  map.set(dt.storageKey('s', 'k'), JSON.stringify({ v: 1, sort: { col: 'tag', dir: 2 }, hidden: 'tag', filters: { status: 'ok' } }));
  const bad = dt.loadState(storage, 's', 'k', COLS());
  assert.equal(bad.sort, null);
  assert.deepEqual(bad.hidden, []);
  assert.deepEqual(bad.filters, {});
});

T('fixture-v2 devices: filter, search and sort agree with a plain implementation', () => {
  const doc = loadFixtureDoc();
  const c = dt.normalizeColumns([
    { key: 'name' }, { key: 'kind', filterable: true }, { key: 'model' }, { key: 'status', filterable: true },
    { key: 'ports', value: (d) => (d.ports || []).length },
  ]);
  const res = dt.applyState(doc.devices, c, Object.assign(dt.defaultState(c), { sort: { col: 'ports', dir: -1 }, q: 's' }));
  const want = doc.devices.filter((d) => [d.name, d.kind, d.model, d.status, String((d.ports || []).length)]
    .some((v) => String(v == null ? '' : v).toLowerCase().indexOf('s') >= 0));
  assert.equal(res.filtered, want.length);
  for (let i = 1; i < res.rows.length; i++) assert.ok((res.rows[i - 1].ports || []).length >= (res.rows[i].ports || []).length);
  const kinds = dt.distinctValues(doc.devices, c[1]);
  assert.deepEqual(kinds, Array.from(new Set(doc.devices.map((d) => d.kind || '(empty)'))).sort(dt.compareValues));
});

T('20k rows: a cached search keystroke and a sort stay well inside a frame budget', () => {
  const r = rng(11);
  const rows = Array.from({ length: 20000 }, (_, i) => ({ id: 'r' + i, name: 'Device ' + Math.floor(r() * 5000), tag: 'A-' + i, len: Math.floor(r() * 100), status: ['ok', 'spare', ''][i % 3] }));
  const c = dt.normalizeColumns([{ key: 'name' }, { key: 'tag' }, { key: 'len' }, { key: 'status', filterable: true }]);
  const index = dt.createIndex(rows, c);
  const s0 = dt.defaultState(c);
  dt.applyState(rows, c, Object.assign({}, s0, { q: 'x', sort: { col: 'len', dir: 1 } }), { index });
  const t0 = performance.now();
  for (const q of ['d', 'de', 'dev', 'devi', 'devic', 'device 4']) dt.applyState(rows, c, Object.assign({}, s0, { q, sort: { col: 'len', dir: 1 } }), { index });
  const per = (performance.now() - t0) / 6;
  assert.ok(per < 150, 'cached keystroke took ' + per.toFixed(1) + ' ms');
});
