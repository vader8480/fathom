// T-ROUTER: contract test for js/router-core.js and js/dom.js (ROUTER), written from docs/ui-audit.md
// B.1 D1 (URL grammar), D2 (sections, roles, nav memory), D3 (breakpoints), D8 (storage keys) and
// B.2 ROUTER. legacyHash and selToString/selFromString vectors are hand-derived from today's
// app.js buildHash / selToString / selFromString.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, m, need } from './fixtures/helpers.mjs';

const { mod, skip: absent, error } = await loadModule('js/router-core.js', 'ROUTER');
const dom = await loadModule('js/dom.js', 'ROUTER');
const skip = absent || (error ? 'router-core.js failed to import (see failing test)' : false);
const domSkip = dom.skip || (dom.error ? 'dom.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);
const TD = (name, fn) => test(name, { skip: domSkip }, fn);

if (error) test('router-core.js imports in Node (D12 pure module)', () => { throw error; });
if (dom.error) test('dom.js imports in Node (D12, no top-level DOM access)', () => { throw dom.error; });

const D1 = 'D1';
const D2 = 'D2';
const R = 'B.2 ROUTER';
const U = 'UI-ROUTER';
const fn = (name, sec) => need(mod, name, U, sec || R);

// id/tab/sub may be '', null or undefined when absent; the contract does not pin which.
const blank = (v) => v === '' || v === null || v === undefined;
const plain = (o) => Object.assign({}, o);

function checkRoute(r, exp, label) {
  assert.ok(r && typeof r === 'object', m(U, D1, `${label}: parseRoute returns an object`));
  for (const k of ['project', 'room', 'view']) {
    assert.equal(r[k], exp[k] || '', m(U, D1, `${label}: ${k}`));
  }
  for (const k of ['id', 'tab', 'sub']) {
    if (exp[k]) assert.equal(r[k], exp[k], m(U, D1, `${label}: ${k}`));
    else assert.ok(blank(r[k]), m(U, D1, `${label}: ${k} empty, got ${JSON.stringify(r[k])}`));
  }
  assert.deepEqual(r.extra, exp.extra || [], m(U, D1, `${label}: extra`));
  assert.ok(r.query && typeof r.query === 'object' && !Array.isArray(r.query), m(U, D1, `${label}: query is a plain object`));
  assert.deepEqual(plain(r.query), exp.query || {}, m(U, D1, `${label}: query`));
  assert.deepEqual(Object.keys(r.query), Object.keys(exp.query || {}), m(U, D1, `${label}: query key order`));
}

// B.2 ROUTER test group 1: the ten round-trip vectors.
const ROUND_TRIPS = [
  ['#/campus/main/patch', { project: 'campus', room: 'main', view: 'patch' }],
  ['#/campus/*/table', { project: 'campus', room: '*', view: 'table' }],
  ['#/campus/main/patch?sel=device:foh-cl5', { project: 'campus', room: 'main', view: 'patch', query: { sel: 'device:foh-cl5' } }],
  ['#/campus/main/patch?sel=port:rio-sl:analog-in-9', { project: 'campus', room: 'main', view: 'patch', query: { sel: 'port:rio-sl:analog-in-9' } }],
  ['#/campus/main/plan?sel=marker:fp-main-floor:foh-cl5', { project: 'campus', room: 'main', view: 'plan', query: { sel: 'marker:fp-main-floor:foh-cl5' } }],
  ['#/campus/main/sop?page=power-up&edit=1', { project: 'campus', room: 'main', view: 'sop', query: { page: 'power-up', edit: '1' } }],
  ['#/sunday-demo/main/patch?sel=device:atem-mini&filter=audio,video',
    { project: 'sunday-demo', room: 'main', view: 'patch', query: { sel: 'device:atem-mini', filter: 'audio,video' } }],
  ['#/campus/main/devices/foh-cl5/ports?sel=port:foh-cl5:omni-in-1&sec=ports',
    { project: 'campus', room: 'main', view: 'devices', id: 'foh-cl5', tab: 'ports', query: { sel: 'port:foh-cl5:omni-in-1', sec: 'ports' } }],
  ['#/campus/main/schedules/cables?q=drum&sort=-length&f.state=planned|~&pg=2',
    { project: 'campus', room: 'main', view: 'schedules', tab: 'cables', query: { q: 'drum', sort: '-length', 'f.state': 'planned|~', pg: '2' } }],
  ['#/my%20show/main/patch', { project: 'my show', room: 'main', view: 'patch' }],
];

// D1 shapes table examples.
const SHAPE_EXAMPLES = [
  ['#/campus/main/inventory?sel=device:foh-cl5&sec=inventory', { project: 'campus', room: 'main', view: 'inventory', query: { sel: 'device:foh-cl5', sec: 'inventory' } }],
  ['#/campus/chapel/rooms/chapel/devices', { project: 'campus', room: 'chapel', view: 'rooms', id: 'chapel', tab: 'devices' }],
  ['#/campus/main/racks/rk-foh/elevation/rear', { project: 'campus', room: 'main', view: 'racks', id: 'rk-foh', tab: 'elevation', sub: 'rear' }],
  ['#/campus/main/plan/fp-main-stage?sel=marker:fp-main-stage:foh-cl5&drawer=0',
    { project: 'campus', room: 'main', view: 'plan', id: 'fp-main-stage', query: { sel: 'marker:fp-main-stage:foh-cl5', drawer: '0' } }],
  ['#/campus/main/imports?hl=imp-0003', { project: 'campus', room: 'main', view: 'imports', query: { hl: 'imp-0003' } }],
  ['#/campus/main/settings/networks?hl=av-dante', { project: 'campus', room: 'main', view: 'settings', tab: 'networks', query: { hl: 'av-dante' } }],
  ['#/campus/main/discovery/unresolved?run=run-20261026-101500-0001',
    { project: 'campus', room: 'main', view: 'discovery', tab: 'unresolved', query: { run: 'run-20261026-101500-0001' } }],
  ['#/campus/main/history/42', { project: 'campus', room: 'main', view: 'history', id: '42' }],
  ['#/campus/main/schedules/cables?q=drum&sort=-length&pg=2', { project: 'campus', room: 'main', view: 'schedules', tab: 'cables', query: { q: 'drum', sort: '-length', pg: '2' } }],
  ['#/campus/main/patch?zz=1&smoke=1', { project: 'campus', room: 'main', view: 'patch', query: { zz: '1', smoke: '1' } }],
];

// Hand-derived from app.js buildHash: encodeURIComponent on project/room (room keeps '*'), view as is,
// params dropped when undefined/null/'', values encodeURIComponent with only %3A -> ':'.
const LEGACY = [
  [['campus', 'main', 'patch'], '#/campus/main/patch'],
  [['campus', '*', 'table'], '#/campus/*/table'],
  [['campus', 'main', 'patch', { sel: 'device:foh-cl5' }], '#/campus/main/patch?sel=device:foh-cl5'],
  [['campus', 'main', 'patch', { sel: 'port:rio-sl:analog-in-9' }], '#/campus/main/patch?sel=port:rio-sl:analog-in-9'],
  [['campus', 'main', 'plan', { sel: 'marker:fp-main-floor:foh-cl5' }], '#/campus/main/plan?sel=marker:fp-main-floor:foh-cl5'],
  [['campus', 'main', 'sop', { page: 'power-up', edit: '1' }], '#/campus/main/sop?page=power-up&edit=1'],
  [['sunday-demo', 'main', 'patch', { sel: 'device:atem-mini', filter: 'audio,video' }], '#/sunday-demo/main/patch?sel=device:atem-mini&filter=audio%2Cvideo'],
  [['my show', 'main', 'patch'], '#/my%20show/main/patch'],
  [['campus', '', 'patch', { sel: '', filter: null, q: undefined }], '#/campus//patch'],
  [['campus', 'main', 'map', { sel: 'device:a b', q: 'x/y&z' }], '#/campus/main/map?sel=device:a%20b&q=x%2Fy%26z'],
  [['campus', 'main', 'schedules', { q: 'drum', sort: '-length', 'f.state': 'planned|~', pg: 2 }], '#/campus/main/schedules?q=drum&sort=-length&f.state=planned%7C~&pg=2'],
  [['a:b', 'main hall', 'inventory', {}], '#/a%3Ab/main%20hall/inventory'],
];

const SECTION_TABLE = [
  { key: 'home', label: 'Home', glyph: '\u2302', views: ['home'], nav: 'sm' },
  { key: 'patch', label: 'Patch', glyph: '\u2B95', views: ['patch', 'table', 'map'], nav: 'all' },
  { key: 'rooms', label: 'Rooms', glyph: '\u25A3', views: ['rooms', 'plan', 'racks'], nav: 'all' },
  { key: 'devices', label: 'Devices', glyph: '\u25EB', views: ['devices', 'inventory'], nav: 'all' },
  { key: 'schedules', label: 'Schedules', glyph: '\u2630', views: ['schedules', 'builds'], nav: 'all' },
  { key: 'sop', label: 'SOPs', glyph: '\u2611', views: ['sop'], nav: 'all' },
  { key: 'data', label: 'Data', glyph: '\u21C5', views: ['imports', 'discovery', 'history', 'json'], nav: 'all' },
  { key: 'settings', label: 'Settings', glyph: '\u2699', views: ['settings'], nav: 'all' },
];
const ALL_VIEWS = [].concat(...SECTION_TABLE.map((s) => s.views));

function fakeStorage(init) {
  const data = new Map(Object.entries(init || {}));
  return {
    data,
    getItem(k) { return data.has(k) ? data.get(k) : null; },
    setItem(k, v) { data.set(k, String(v)); },
    removeItem(k) { data.delete(k); },
    clear() { data.clear(); },
    key(i) { const ks = Array.from(data.keys()); return i < ks.length ? ks[i] : null; },
    get length() { return data.size; },
  };
}

function throwingStorage() {
  const boom = () => { throw new Error('SecurityError: storage disabled'); };
  return { getItem: boom, setItem: boom, removeItem: boom, clear: boom, key: boom, get length() { return boom(); } };
}

// ------------------------------------------------------------ D3 breakpoints

T('BP and layoutFor (D3; test group 8)', () => {
  assert.deepEqual(plain(fn('BP', 'D3')), { md: 700, lg: 1100 }, m(U, 'D3', 'BP = {md: 700, lg: 1100}'));
  const layoutFor = fn('layoutFor', 'D3');
  const cases = [[0, 'sm'], [390, 'sm'], [699, 'sm'], [700, 'md'], [744, 'md'], [820, 'md'], [1099, 'md'], [1100, 'lg'], [1280, 'lg']];
  for (const [w, exp] of cases) assert.equal(layoutFor(w), exp, m(U, 'D3', `layoutFor(${w})`));
});

// ------------------------------------------------------------ D1 grammar

T('DEFAULT_VIEW is home and VIEW_SHAPES matches the D1 table', () => {
  assert.equal(fn('DEFAULT_VIEW', D1), 'home', m(U, D1, 'empty view means home'));
  const shapes = fn('VIEW_SHAPES', D1);
  const exp = {
    devices: ['id', 'tab', 'sub'], rooms: ['id', 'tab'], racks: ['id', 'tab', 'sub'], plan: ['id'], schedules: ['tab'],
    imports: ['tab'], settings: ['tab'], discovery: ['tab', 'sub'], history: ['id'],
  };
  for (const v of Object.keys(exp)) assert.deepEqual(shapes[v], exp[v], m(U, D1, `VIEW_SHAPES.${v}`));
  for (const v of ['home', 'patch', 'table', 'map', 'inventory', 'builds', 'sop', 'json']) {
    assert.ok(shapes[v] === undefined || (Array.isArray(shapes[v]) && shapes[v].length === 0), m(U, D1, `${v} takes no segments`));
  }
  for (const v of Object.keys(shapes)) {
    assert.ok(v in exp || (Array.isArray(shapes[v]) && shapes[v].length === 0), m(U, D1, `unexpected shape for ${v}`));
  }
});

T('parseRoute: the ten round-trip vectors field by field (test group 1)', () => {
  const parseRoute = fn('parseRoute', D1);
  for (const [h, exp] of ROUND_TRIPS) checkRoute(parseRoute(h), exp, h);
});

T('Round trips: buildRoute(parseRoute(x)) === x (test group 1)', () => {
  const parseRoute = fn('parseRoute', D1);
  const buildRoute = fn('buildRoute', D1);
  for (const [h] of ROUND_TRIPS.concat(SHAPE_EXAMPLES)) assert.equal(buildRoute(parseRoute(h)), h, m(U, D1, `round trip ${h}`));
});

T('parseRoute: D1 shape-table examples', () => {
  const parseRoute = fn('parseRoute', D1);
  for (const [h, exp] of SHAPE_EXAMPLES) checkRoute(parseRoute(h), exp, h);
});

T('parseRoute: empty views (test group 3)', () => {
  const parseRoute = fn('parseRoute', D1);
  checkRoute(parseRoute(''), { project: '', room: '', view: '' }, "''");
  checkRoute(parseRoute('#/campus'), { project: 'campus', room: '', view: '' }, '#/campus');
  checkRoute(parseRoute('#/campus/main/'), { project: 'campus', room: 'main', view: '' }, '#/campus/main/');
});

T('parseRoute: shapes and extra segments (test group 4)', () => {
  const parseRoute = fn('parseRoute', D1);
  checkRoute(parseRoute('#/p/r/devices/x/ports/extra/more'), { project: 'p', room: 'r', view: 'devices', id: 'x', tab: 'ports', sub: 'extra', extra: ['more'] }, 'devices overflow');
  checkRoute(parseRoute('#/p/r/widgets/a/b'), { project: 'p', room: 'r', view: 'widgets', extra: ['a', 'b'] }, 'unknown view');
  checkRoute(parseRoute('#/p/r/patch/a'), { project: 'p', room: 'r', view: 'patch', extra: ['a'] }, 'shapeless view');
  checkRoute(parseRoute('#/p/r/schedules/cables/x'), { project: 'p', room: 'r', view: 'schedules', tab: 'cables', extra: ['x'] }, 'schedules overflow');
  checkRoute(parseRoute('#/p/r/plan/fp-1/x/y'), { project: 'p', room: 'r', view: 'plan', id: 'fp-1', extra: ['x', 'y'] }, 'plan overflow');
  checkRoute(parseRoute('#/p/r/history/42'), { project: 'p', room: 'r', view: 'history', id: '42' }, 'history id');
});

T('parseRoute: query decoding, first value wins, unknown keys kept', () => {
  const parseRoute = fn('parseRoute', D1);
  const r = parseRoute('#/campus/main/patch?a=1&q=a%20b%26c&a=2&zz=%3A');
  assert.deepEqual(plain(r.query), { a: '1', q: 'a b&c', zz: ':' }, m(U, D1, 'decoded strings, first value winning'));
  assert.equal(parseRoute('#/campus/main/map?pg=2').query.pg, '2', m(U, D1, 'query values are strings'));
});

T('buildRoute: encoding rules and dropped values', () => {
  const buildRoute = fn('buildRoute', D1);
  const base = { project: 'campus', room: 'main', view: 'patch', extra: [], query: {} };
  assert.equal(buildRoute(base), '#/campus/main/patch');
  assert.equal(buildRoute(Object.assign({}, base, { project: 'my show', room: '*' })), '#/my%20show/*/patch', m(U, D1, 'segments encoded, * kept in room'));
  assert.equal(buildRoute(Object.assign({}, base, { query: { sel: 'device:a/b', filter: 'a,b', 'f.x': 'a|b', q: 'a b&c=d' } })),
    '#/campus/main/patch?sel=device:a/b&filter=a,b&f.x=a|b&q=a%20b%26c%3Dd', m(U, D1, 'query values keep : , | / unescaped'));
  assert.equal(buildRoute(Object.assign({}, base, { query: { a: '', b: null, c: undefined, d: '1' } })), '#/campus/main/patch?d=1', m(U, D1, 'empty, null, undefined dropped'));
  assert.equal(buildRoute(Object.assign({}, base, { query: { a: '', b: null } })), '#/campus/main/patch', m(U, D1, 'no ? when every value is dropped'));
  assert.equal(buildRoute(Object.assign({}, base, { query: { z: '1', a: '2', m: '3' } })), '#/campus/main/patch?z=1&a=2&m=3', m(U, D1, 'insertion order'));
  assert.equal(buildRoute(Object.assign({}, base, { view: 'schedules', tab: 'cables', query: { pg: 2 } })), '#/campus/main/schedules/cables?pg=2');
  assert.equal(buildRoute(Object.assign({}, base, { view: 'devices', id: 'x', tab: '', sub: '' })), '#/campus/main/devices/x', m(U, D1, 'trailing empty segments dropped'));
  assert.equal(buildRoute(Object.assign({}, base, { view: 'racks', id: 'rk-foh', tab: 'elevation', sub: 'rear' })), '#/campus/main/racks/rk-foh/elevation/rear');
  assert.equal(buildRoute(Object.assign({}, base, { view: 'devices', id: 'a b/c' })), '#/campus/main/devices/a%20b%2Fc', m(U, D1, 'id encoded with encodeURIComponent'));
});

T('withQuery: null or empty deletes, order preserved, input untouched', () => {
  const parseRoute = fn('parseRoute', D1);
  const buildRoute = fn('buildRoute', D1);
  const withQuery = fn('withQuery', R);
  const h = '#/campus/main/devices/foh-cl5/ports?a=1&b=2&c=3';
  const r = parseRoute(h);
  const r2 = withQuery(r, { b: 'x', d: '4', a: null, c: '' });
  assert.notEqual(r2, r, m(U, R, 'returns a new route'));
  assert.equal(buildRoute(r2), '#/campus/main/devices/foh-cl5/ports?b=x&d=4', m(U, R, 'b updated in place, d appended, a and c deleted'));
  assert.equal(r2.view, 'devices');
  assert.equal(r2.id, 'foh-cl5');
  assert.equal(r2.tab, 'ports');
  assert.equal(buildRoute(r), h, m(U, R, 'input route not mutated'));
  assert.deepEqual(plain(r.query), { a: '1', b: '2', c: '3' });
  assert.equal(buildRoute(withQuery(parseRoute('#/campus/main/patch'), { sel: 'device:x' })), '#/campus/main/patch?sel=device:x');
});

T('mergeRoute: changing view clears id/tab/sub unless given', () => {
  const parseRoute = fn('parseRoute', D1);
  const buildRoute = fn('buildRoute', D1);
  const mergeRoute = fn('mergeRoute', R);
  const h = '#/campus/main/devices/foh-cl5/ports?sel=device:foh-cl5';
  const r = parseRoute(h);

  const a = mergeRoute(r, { view: 'rooms' });
  assert.equal(a.view, 'rooms');
  assert.equal(a.project, 'campus');
  assert.equal(a.room, 'main');
  for (const k of ['id', 'tab', 'sub']) assert.ok(blank(a[k]), m(U, R, `view change clears ${k}`));

  const b = mergeRoute(r, { view: 'racks', id: 'rk-foh' });
  assert.equal(b.view, 'racks');
  assert.equal(b.id, 'rk-foh', m(U, R, 'given id kept'));
  assert.ok(blank(b.tab) && blank(b.sub), m(U, R, 'tab/sub cleared'));

  const c = mergeRoute(r, { tab: 'cables' });
  assert.equal(c.view, 'devices');
  assert.equal(c.id, 'foh-cl5', m(U, R, 'same view keeps id'));
  assert.equal(c.tab, 'cables');

  const d = mergeRoute(r, { view: 'devices' });
  assert.equal(d.id, 'foh-cl5', m(U, R, 'same view is not a view change'));
  assert.equal(d.tab, 'ports');

  const e = mergeRoute(r, { room: 'chapel' });
  assert.equal(e.room, 'chapel');
  assert.equal(e.view, 'devices');
  assert.equal(e.id, 'foh-cl5');

  assert.equal(buildRoute(r), h, m(U, R, 'input route not mutated'));
});

T('sameRoute with and without ignoreKeys', () => {
  const parseRoute = fn('parseRoute', D1);
  const sameRoute = fn('sameRoute', R);
  const a = parseRoute('#/campus/main/patch?sel=device:a&filter=audio');
  const b = parseRoute('#/campus/main/patch?sel=device:b&filter=audio');
  const c = parseRoute('#/campus/main/patch?sel=device:b&filter=video');
  assert.equal(sameRoute(a, parseRoute('#/campus/main/patch?sel=device:a&filter=audio')), true);
  assert.equal(sameRoute(a, b), false, m(U, R, 'sel differs'));
  assert.equal(sameRoute(a, b, ['sel']), true, m(U, R, 'sel ignored'));
  assert.equal(sameRoute(a, c, ['sel']), false, m(U, R, 'filter still compared'));
  assert.equal(sameRoute(parseRoute('#/campus/main/patch'), parseRoute('#/campus/main/table')), false, m(U, R, 'view differs'));
  assert.equal(sameRoute(parseRoute('#/campus/main/devices/a'), parseRoute('#/campus/main/devices/b')), false, m(U, R, 'id differs'));
  assert.equal(sameRoute(parseRoute('#/campus/main/devices/a/ports'), parseRoute('#/campus/main/devices/a/cables')), false, m(U, R, 'tab differs'));
  assert.equal(sameRoute(parseRoute('#/campus/main/patch'), parseRoute('#/other/main/patch')), false, m(U, R, 'project differs'));
  assert.equal(sameRoute(parseRoute('#/campus/main/patch'), parseRoute('#/campus/*/patch')), false, m(U, R, 'room differs'));
});

T('legacyHash equals the old buildHash (test group 2)', () => {
  const legacyHash = fn('legacyHash', R);
  for (const [args, exp] of LEGACY) assert.equal(legacyHash.apply(null, args), exp, m(U, R, `legacyHash(${JSON.stringify(args)})`));
});

T('legacyHash output parses and rebuilds to the same route', () => {
  const legacyHash = fn('legacyHash', R);
  const parseRoute = fn('parseRoute', D1);
  const buildRoute = fn('buildRoute', D1);
  for (const [args] of LEGACY) {
    const h = legacyHash.apply(null, args);
    const r = parseRoute(h);
    const r2 = parseRoute(buildRoute(r));
    for (const k of ['project', 'room', 'view', 'id', 'tab', 'sub']) assert.equal(r2[k], r[k], m(U, D1, `${h}: ${k}`));
    assert.deepEqual(plain(r2.query), plain(r.query), m(U, D1, `${h}: query`));
  }
  assert.equal(parseRoute(LEGACY[6][1]).query.filter, 'audio,video');
  assert.equal(parseRoute(LEGACY[9][1]).query.q, 'x/y&z');
  assert.equal(parseRoute(LEGACY[11][1]).project, 'a:b');
  assert.equal(parseRoute(LEGACY[11][1]).room, 'main hall');
});

// ------------------------------------------------------------ selection strings

T('selToString keeps the app.js vectors (test group 5)', () => {
  const selToString = fn('selToString', D1);
  const cases = [
    [null, ''],
    [undefined, ''],
    [{ type: 'device', id: 'foh-cl5' }, 'device:foh-cl5'],
    [{ type: 'port', device: 'rio-sl', port: 'analog-in-9' }, 'port:rio-sl:analog-in-9'],
    [{ type: 'port', id: 'rio-sl', port: 'analog-in-9' }, 'port:rio-sl:analog-in-9'],
    [{ type: 'cable', id: 'c-1' }, 'cable:c-1'],
    [{ type: 'rack', id: 'rk-foh' }, 'rack:rk-foh'],
    [{ type: 'floorplan', id: 'fp-main' }, 'floorplan:fp-main'],
    [{ type: 'marker', floorplan: 'fp', device: 'dev' }, 'marker:fp:dev'],
    [{ type: 'marker', id: 'dev' }, 'marker::dev'],
    [{ type: 'channel', device: 'dev', channel: 'ch' }, 'channel:dev:ch'],
    [{ type: 'channel', id: 'dev', channel: 'ch' }, 'channel:dev:ch'],
    [{ type: 'bundle', id: 'b-1' }, 'bundle:b-1'],
    [{ type: 'room', id: 'chapel' }, 'room:chapel'],
  ];
  for (const [sel, exp] of cases) assert.equal(selToString(sel), exp, m(U, D1, `selToString(${JSON.stringify(sel)})`));
});

T('selFromString keeps the app.js vectors (test group 5)', () => {
  const selFromString = fn('selFromString', D1);
  const cases = [
    ['', null],
    [null, null],
    [undefined, null],
    ['device', null],
    ['cable:', null],
    ['device:foh-cl5', { type: 'device', id: 'foh-cl5', device: 'foh-cl5' }],
    ['port:rio-sl:analog-in-9', { type: 'port', id: 'rio-sl', device: 'rio-sl', port: 'analog-in-9' }],
    ['port:rio-sl', { type: 'port', id: 'rio-sl', device: 'rio-sl', port: null }],
    ['cable:c-1', { type: 'cable', id: 'c-1' }],
    ['rack:rk-foh', { type: 'rack', id: 'rk-foh' }],
    ['floorplan:fp-main', { type: 'floorplan', id: 'fp-main' }],
    ['marker:fp-main-floor:foh-cl5', { type: 'marker', id: 'foh-cl5', floorplan: 'fp-main-floor', device: 'foh-cl5' }],
    ['channel:dev:ch', { type: 'channel', id: 'dev', device: 'dev', channel: 'ch' }],
    ['channel:dev', { type: 'device', id: 'dev', device: 'dev' }],
    ['device:x:port', { type: 'port', id: 'x', device: 'x', port: 'port' }],
    ['cable:c-1:p', { type: 'cable', id: 'c-1', device: 'c-1', port: 'p' }],
    ['bundle:b-1', { type: 'bundle', id: 'b-1' }],
    ['room:chapel', { type: 'room', id: 'chapel' }],
  ];
  for (const [s, exp] of cases) assert.deepEqual(selFromString(s), exp, m(U, D1, `selFromString(${JSON.stringify(s)})`));
});

T('selToString(selFromString(s)) === s for canonical strings', () => {
  const selToString = fn('selToString', D1);
  const selFromString = fn('selFromString', D1);
  for (const s of ['device:foh-cl5', 'port:rio-sl:analog-in-9', 'cable:c-1', 'rack:rk-foh', 'floorplan:fp-main',
    'marker:fp-main-floor:foh-cl5', 'channel:dev:ch', 'bundle:b-1', 'room:chapel']) {
    assert.equal(selToString(selFromString(s)), s, m(U, D1, `sel round trip ${s}`));
  }
});

// ------------------------------------------------------------ D2 sections and roles

T('SECTIONS matches the D2 table in order', () => {
  const SECTIONS = fn('SECTIONS', D2);
  assert.ok(Array.isArray(SECTIONS), m(U, D2, 'SECTIONS is an array'));
  assert.deepEqual(SECTIONS.map((s) => s.key), SECTION_TABLE.map((s) => s.key), m(U, D2, 'section keys and order'));
  SECTION_TABLE.forEach((exp, i) => {
    const s = SECTIONS[i];
    assert.equal(s.label, exp.label, m(U, D2, `${exp.key} label`));
    assert.deepEqual(s.views, exp.views, m(U, D2, `${exp.key} views (first = root)`));
    assert.equal(s.nav, exp.nav, m(U, D2, `${exp.key} nav`));
    assert.ok(typeof s.glyph === 'string' && s.glyph.length > 0, m(U, D2, `${exp.key} glyph non-empty`));
    assert.equal(s.glyph.replace(/\uFE0E/g, ''), exp.glyph, m(U, D2, `${exp.key} glyph (ignoring \\uFE0E)`));
  });
});

T('VIEW_ROLES, TAB_ROLES and canSee', () => {
  const VIEW_ROLES = fn('VIEW_ROLES', D2);
  for (const v of ALL_VIEWS) assert.equal(VIEW_ROLES[v], 'viewer', m(U, D2, `VIEW_ROLES.${v}`));
  const TAB_ROLES = fn('TAB_ROLES', D2);
  assert.deepEqual(plain(TAB_ROLES.settings), { users: 'admin', backups: 'admin', sharing: 'editor' }, m(U, D2, 'TAB_ROLES.settings'));
  const canSee = fn('canSee', D2);
  const cases = [
    ['settings', 'viewer', 'users', false], ['settings', 'editor', 'users', false], ['settings', 'admin', 'users', true],
    ['settings', 'viewer', 'backups', false], ['settings', 'editor', 'backups', false], ['settings', 'admin', 'backups', true],
    ['settings', 'viewer', 'sharing', false], ['settings', 'editor', 'sharing', true], ['settings', 'admin', 'sharing', true],
    ['settings', 'viewer', 'networks', true], ['settings', 'viewer', undefined, true],
    ['no-such-view', 'viewer', undefined, true], ['no-such-view', 'admin', 'x', true],
  ];
  for (const [v, role, tab, exp] of cases) assert.equal(canSee(v, role, tab), exp, m(U, D2, `canSee(${v}, ${role}, ${tab})`));
  for (const v of ALL_VIEWS) {
    for (const role of ['viewer', 'editor', 'admin']) assert.equal(canSee(v, role), true, m(U, D2, `canSee(${v}, ${role})`));
  }
});

T('sectionOf maps views to sections; unknown -> data', () => {
  const sectionOf = fn('sectionOf', D2);
  for (const s of SECTION_TABLE) for (const v of s.views) assert.equal(sectionOf(v), s.key, m(U, D2, `sectionOf(${v})`));
  assert.equal(sectionOf('table'), 'patch');
  assert.equal(sectionOf('inventory'), 'devices');
  assert.equal(sectionOf('json'), 'data');
  assert.equal(sectionOf('no-such-view'), 'data', m(U, D2, 'unknown views -> data'));
});

T('sectionsFor keeps all 8 sections for every role (test group 6)', () => {
  const sectionsFor = fn('sectionsFor', D2);
  for (const role of ['viewer', 'editor', 'admin']) {
    const list = sectionsFor(role);
    assert.equal(list.length, 8, m(U, D2, `${role}: no section hidden`));
    assert.deepEqual(list.map((s) => s.key), SECTION_TABLE.map((s) => s.key), m(U, D2, `${role}: keys`));
    list.forEach((s, i) => assert.deepEqual(s.views, SECTION_TABLE[i].views, m(U, D2, `${role}: ${s.key} views`)));
  }
  const canSee = fn('canSee', D2);
  assert.equal(canSee('settings', 'viewer', 'users'), false, m(U, D2, 'test group 6'));
  assert.equal(canSee('settings', 'editor', 'sharing'), true, m(U, D2, 'test group 6'));
});

T('sectionRoot: first permitted view, same project and room, nothing else', () => {
  const parseRoute = fn('parseRoute', D1);
  const sectionRoot = fn('sectionRoot', D2);
  const cur = parseRoute('#/campus/main/devices/foh-cl5/ports?sel=port:foh-cl5:a&sec=ports');
  const cases = [['home', 'home'], ['patch', 'patch'], ['rooms', 'rooms'], ['devices', 'devices'], ['schedules', 'schedules'], ['sop', 'sop'], ['data', 'imports'], ['settings', 'settings']];
  for (const [key, view] of cases) {
    const r = sectionRoot(key, cur, 'viewer');
    assert.equal(r.project, 'campus', m(U, D2, `${key} root project`));
    assert.equal(r.room, 'main', m(U, D2, `${key} root room`));
    assert.equal(r.view, view, m(U, D2, `${key} root view`));
    for (const k of ['id', 'tab', 'sub']) assert.ok(blank(r[k]), m(U, D2, `${key} root has no ${k}`));
    assert.ok(r.extra === undefined || (Array.isArray(r.extra) && r.extra.length === 0), m(U, D2, `${key} root has no extra`));
    assert.deepEqual(plain(r.query), {}, m(U, D2, `${key} root query empty`));
  }
  const all = sectionRoot('rooms', parseRoute('#/campus/*/patch?sel=device:x'), 'admin');
  assert.equal(all.room, '*', m(U, D2, 'root keeps the * room'));
  assert.equal(all.view, 'rooms');
});

// ------------------------------------------------------------ D2/D8 nav memory

const HASH_DEV = '#/campus/main/devices/foh-cl5/ports?sel=port:foh-cl5:omni-in-1';

T('navMemory: remembered hash for another section (test group 7)', () => {
  const navMemory = fn('navMemory', D2);
  const parseRoute = fn('parseRoute', D1);
  const store = fakeStorage();
  const nm = navMemory(store);
  for (const k of ['remember', 'target', 'clear']) assert.equal(typeof nm[k], 'function', m(U, D2, `navMemory().${k}`));
  nm.remember('campus', HASH_DEV);
  const cur = parseRoute('#/campus/main/patch?sel=device:x');
  assert.equal(nm.target('campus', 'devices', cur, 'admin'), HASH_DEV, m(U, D2, 'other section -> remembered hash'));
  assert.equal(nm.target('campus', 'schedules', cur, 'admin'), '#/campus/main/schedules', m(U, D2, 'nothing remembered -> root'));
  assert.equal(nm.target('campus', 'data', cur, 'viewer'), '#/campus/main/imports', m(U, D2, 'root is the first view'));
  nm.remember('campus', '#/campus/main/inventory?q=cl5');
  assert.equal(nm.target('campus', 'devices', cur, 'admin'), '#/campus/main/inventory?q=cl5', m(U, D2, 'sub-view counts for its section; latest wins'));
  assert.equal(navMemory(store).target('campus', 'devices', cur, 'admin'), '#/campus/main/inventory?q=cl5', m(U, D2, 'persists in storage'));
});

T('navMemory: active section returns its root (test group 7)', () => {
  const navMemory = fn('navMemory', D2);
  const parseRoute = fn('parseRoute', D1);
  const nm = navMemory(fakeStorage());
  nm.remember('campus', HASH_DEV);
  nm.remember('campus', '#/campus/main/table?q=x');
  assert.equal(nm.target('campus', 'devices', parseRoute(HASH_DEV), 'admin'), '#/campus/main/devices', m(U, D2, 'active section -> root'));
  assert.equal(nm.target('campus', 'patch', parseRoute('#/campus/main/map?sel=device:x'), 'admin'), '#/campus/main/patch', m(U, D2, 'active section -> root even when remembered'));
  assert.equal(nm.target('campus', 'rooms', parseRoute('#/campus/*/rooms/chapel'), 'admin'), '#/campus/*/rooms', m(U, D2, 'root keeps the room'));
});

T('navMemory: per project, storage key and shape (D8)', () => {
  const navMemory = fn('navMemory', D2);
  const parseRoute = fn('parseRoute', D1);
  const store = fakeStorage();
  const nm = navMemory(store);
  nm.remember('campus', HASH_DEV);
  assert.equal(nm.target('other', 'devices', parseRoute('#/other/main/patch'), 'admin'), '#/other/main/devices', m(U, D2, 'memory is per project'));
  const raw = store.getItem('fathom.ui.nav');
  assert.ok(typeof raw === 'string', m(U, 'D8', 'written to fathom.ui.nav'));
  const data = JSON.parse(raw);
  assert.equal(data.campus.devices, HASH_DEV, m(U, 'D8', '{"<project>": {"<section>": "<hash>"}}'));
  nm.remember('other', '#/other/main/sop?page=x');
  const data2 = JSON.parse(store.getItem('fathom.ui.nav'));
  assert.equal(data2.campus.devices, HASH_DEV);
  assert.equal(data2.other.sop, '#/other/main/sop?page=x');
});

T('navMemory: clear()', () => {
  const navMemory = fn('navMemory', D2);
  const parseRoute = fn('parseRoute', D1);
  const store = fakeStorage();
  const nm = navMemory(store);
  nm.remember('campus', HASH_DEV);
  nm.clear();
  const cur = parseRoute('#/campus/main/patch');
  assert.equal(nm.target('campus', 'devices', cur, 'admin'), '#/campus/main/devices', m(U, D2, 'cleared -> root'));
  assert.equal(navMemory(store).target('campus', 'devices', cur, 'admin'), '#/campus/main/devices', m(U, D2, 'cleared in storage too'));
});

T('navMemory: survives corrupt JSON and throwing storage (test group 7, D8)', () => {
  const navMemory = fn('navMemory', D2);
  const parseRoute = fn('parseRoute', D1);
  const cur = parseRoute('#/campus/main/patch');
  for (const bad of ['{not json', 'null', '[1,2]', '"x"', '42', '{"campus": 5}', '{"campus": "x"}']) {
    const store = fakeStorage({ 'fathom.ui.nav': bad });
    const nm = navMemory(store);
    assert.equal(nm.target('campus', 'devices', cur, 'admin'), '#/campus/main/devices', m(U, 'D8', `corrupt ${bad} -> root`));
    nm.remember('campus', HASH_DEV);
    assert.equal(nm.target('campus', 'devices', cur, 'admin'), HASH_DEV, m(U, 'D8', `corrupt ${bad} is overwritten`));
  }
  const nm = navMemory(throwingStorage());
  assert.doesNotThrow(() => nm.remember('campus', HASH_DEV), m(U, 'D8', 'remember tolerates throwing storage'));
  assert.equal(nm.target('campus', 'schedules', cur, 'admin'), '#/campus/main/schedules', m(U, 'D8', 'target tolerates throwing storage'));
  assert.equal(nm.target('campus', 'patch', cur, 'admin'), '#/campus/main/patch');
  assert.doesNotThrow(() => nm.clear(), m(U, 'D8', 'clear tolerates throwing storage'));
});

// ------------------------------------------------------------ dom.js (D12)

TD('dom.js exports h, esc, on', () => {
  for (const name of ['h', 'esc', 'on']) assert.equal(typeof need(dom.mod, name, U, 'D12'), 'function', m(U, 'D12', `${name} is a function`));
});

TD('dom.js esc is the app.js esc', () => {
  const esc = need(dom.mod, 'esc', U, 'D12');
  assert.equal(esc('<a href="x">\'&'), '&lt;a href=&quot;x&quot;&gt;&#39;&amp;');
  assert.equal(esc(null), '');
  assert.equal(esc(undefined), '');
  assert.equal(esc(0), '0');
});

TD('dom.js on(target, type, fn, opts) returns off()', () => {
  const on = need(dom.mod, 'on', U, 'D12');
  const calls = [];
  const target = {
    addEventListener(t, f, o) { calls.push(['add', t, f, o]); },
    removeEventListener(t, f, o) { calls.push(['remove', t, f, o]); },
  };
  const seen = [];
  const handler = (e) => seen.push(e);
  const off = on(target, 'click', handler, { passive: true });
  assert.equal(typeof off, 'function', m(U, 'D12', 'on returns off()'));
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'add');
  assert.equal(calls[0][1], 'click');
  const ev = { type: 'click' };
  calls[0][2].call(target, ev);
  assert.deepEqual(seen, [ev], m(U, 'D12', 'registered listener calls fn'));
  off();
  const rm = calls.filter((c) => c[0] === 'remove');
  assert.equal(rm.length, 1, m(U, 'D12', 'off removes the listener'));
  assert.equal(rm[0][1], 'click');
  assert.equal(rm[0][2], calls[0][2], m(U, 'D12', 'off removes the same listener it added'));
});
