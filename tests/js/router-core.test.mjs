// ROUTER: js/router-core.js and js/dom.js against docs/ui-audit.md D1, D2, D3 and B.2 ROUTER.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, need } from './fixtures/helpers.mjs';

const { mod: rc, skip: absent, error } = await loadModule('js/router-core.js', 'ROUTER');
const dm = await loadModule('js/dom.js', 'ROUTER');
const S = 'docs/ui-audit.md';
const skip = absent || (error ? 'router-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);
const fn = (name) => need(rc, name, 'ROUTER', S);

if (error) test('router-core.js imports in Node (D12 pure module)', () => { throw error; });

function memStore(init) {
  const data = Object.assign({}, init || {});
  return {
    data,
    getItem: (k) => (Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
    removeItem: (k) => { delete data[k]; },
  };
}
const throwing = {
  getItem() { throw new Error('SecurityError'); },
  setItem() { throw new Error('QuotaExceededError'); },
  removeItem() { throw new Error('SecurityError'); },
};

// Output of app.js buildHash (DEFAULT_VIEW 'patch') at the time router-core.js was written.
const LEGACY = [
  [['campus', 'main', 'patch', undefined], '#/campus/main/patch'],
  [['campus', '*', 'table', null], '#/campus/*/table'],
  [['campus', 'main', 'patch', { sel: 'device:foh-cl5' }], '#/campus/main/patch?sel=device:foh-cl5'],
  [['campus', 'main', 'plan', { sel: 'marker:fp-main-floor:foh-cl5' }], '#/campus/main/plan?sel=marker:fp-main-floor:foh-cl5'],
  [['sunday-demo', 'main', 'patch', { sel: 'device:atem-mini', filter: 'audio,video' }], '#/sunday-demo/main/patch?sel=device:atem-mini&filter=audio%2Cvideo'],
  [['campus', 'main', 'sop', { page: 'power-up', edit: '1', empty: '', nul: null, undef: undefined }], '#/campus/main/sop?page=power-up&edit=1'],
  [['my show', 'room/1', 'patch', { sel: 'port:rio-sl:analog-in-9' }], '#/my%20show/room%2F1/patch?sel=port:rio-sl:analog-in-9'],
  [['', '', 'inventory', {}], '#///inventory'],
  [['campus', 'chapel', 'sop', { page: 'a b&c=d', from: '#/x/y?z=1' }], '#/campus/chapel/sop?page=a%20b%26c%3Dd&from=%23%2Fx%2Fy%3Fz%3D1'],
  [['campus', 'main', 'schedules', { n: 0, flag: false, q: 'drum|~' }], '#/campus/main/schedules?n=0&flag=false&q=drum%7C~'],
];

T('1. round trips: buildRoute(parseRoute(x)) === x (D1 vector table)', () => {
  const parseRoute = fn('parseRoute');
  const buildRoute = fn('buildRoute');
  const vectors = [
    '#/campus/main/patch',
    '#/campus/*/table',
    '#/campus/main/patch?sel=device:foh-cl5',
    '#/campus/main/patch?sel=port:rio-sl:analog-in-9',
    '#/campus/main/plan?sel=marker:fp-main-floor:foh-cl5',
    '#/campus/main/sop?page=power-up&edit=1',
    '#/sunday-demo/main/patch?sel=device:atem-mini&filter=audio,video',
    '#/campus/main/devices/foh-cl5/ports?sel=port:foh-cl5:omni-in-1&sec=ports',
    '#/campus/main/schedules/cables?q=drum&sort=-length&f.state=planned|~&pg=2',
    '#/my%20show/main/patch',
    // D1 path-shape examples
    '#/campus/main/inventory?sel=device:foh-cl5&sec=inventory',
    '#/campus/chapel/rooms/chapel/devices',
    '#/campus/main/racks/rk-foh/elevation/rear',
    '#/campus/main/plan/fp-main-stage?sel=marker:fp-main-stage:foh-cl5&drawer=0',
    '#/campus/main/imports?hl=imp-0003',
    '#/campus/main/settings/networks?hl=av-dante',
    '#/campus/main/discovery/unresolved?run=run-20261026-101500-0001',
    '#/campus/main/history/42',
    '#/campus/main/devices//ports',
    '#/campus/main/patch?zz=1&aa=2&unknown.key=x',
  ];
  for (const h of vectors) assert.equal(buildRoute(parseRoute(h)), h, h);

  const r = parseRoute('#/campus/main/devices/foh-cl5/ports?sel=port:foh-cl5:omni-in-1&sec=ports');
  assert.deepEqual(r, {
    project: 'campus', room: 'main', view: 'devices', id: 'foh-cl5', tab: 'ports', sub: '', extra: [],
    query: { sel: 'port:foh-cl5:omni-in-1', sec: 'ports' },
  });
  assert.equal(parseRoute('#/my%20show/main/patch').project, 'my show');
  assert.deepEqual(parseRoute('#/c/m/schedules/cables?f.state=planned|~').query, { 'f.state': 'planned|~' });
  assert.deepEqual(parseRoute('#/c/m/patch?a=1&a=2&b=3').query, { a: '1', b: '3' }, 'first value wins');
  assert.deepEqual(Object.keys(parseRoute('#/c/m/patch?zz=1&aa=2').query), ['zz', 'aa'], 'insertion order');

  // query encoding (D1): %3A %2C %7C %2F kept literal, everything else encoded; empty values dropped
  assert.equal(buildRoute({ project: 'p', room: 'r', view: 'patch', query: { a: 'x:y,z|w/v', b: 'a b&c', c: '', d: null, e: undefined, f: 0 } }),
    '#/p/r/patch?a=x:y,z|w/v&b=a%20b%26c&f=0');
  assert.equal(buildRoute({ project: 'a/b', room: '*', view: 'patch' }), '#/a%2Fb/*/patch');
  assert.equal(buildRoute({ project: 'p', room: 'r', view: 'devices', id: 'x', tab: '', sub: '' }), '#/p/r/devices/x', 'trailing empty segments dropped');
  assert.equal(buildRoute({ project: 'p', room: 'r', view: 'home', query: {} }), '#/p/r/home');
  assert.equal(buildRoute({ project: 'p', room: 'r', view: '' }), '#/p/r');
});

T('1b. every legacy buildHash output parses to the same route after buildRoute', () => {
  const parseRoute = fn('parseRoute');
  const buildRoute = fn('buildRoute');
  for (const [, h] of LEGACY) {
    const r = parseRoute(h);
    assert.deepEqual(parseRoute(buildRoute(r)), r, h);
  }
  assert.equal(buildRoute(parseRoute('#/sunday-demo/main/patch?filter=audio%2Cvideo')), '#/sunday-demo/main/patch?filter=audio,video');
});

T('2. legacyHash equals the old buildHash for 10 vectors', () => {
  const legacyHash = fn('legacyHash');
  for (const [args, want] of LEGACY) assert.equal(legacyHash(...args), want, JSON.stringify(args));
  assert.equal(legacyHash('campus', 'main', ''), '#/campus/main/' + rc.DEFAULT_VIEW, 'empty view writes DEFAULT_VIEW');
});

T('3. empty views: parseRoute gives view "" and DEFAULT_VIEW is home', () => {
  const parseRoute = fn('parseRoute');
  assert.equal(rc.DEFAULT_VIEW, 'home');
  for (const h of ['', '#', '#/', '#/campus', '#/campus/main', '#/campus/main/', '#/campus/main/?sel=device:x']) {
    assert.equal(parseRoute(h).view, '', JSON.stringify(h));
  }
  assert.deepEqual(parseRoute(''), { project: '', room: '', view: '', id: '', tab: '', sub: '', extra: [], query: {} });
  assert.equal(parseRoute('#/campus').project, 'campus');
  assert.equal(parseRoute('#/campus/main/').room, 'main');
  assert.equal(parseRoute(null).view, '');
  assert.equal(parseRoute('#/campus/main/?sel=device:x').query.sel, 'device:x');
});

T('4. VIEW_SHAPES and extra segments', () => {
  const parseRoute = fn('parseRoute');
  const buildRoute = fn('buildRoute');
  assert.deepEqual(rc.VIEW_SHAPES, {
    devices: ['id', 'tab', 'sub'], rooms: ['id', 'tab'], racks: ['id', 'tab', 'sub'], plan: ['id'], schedules: ['tab'],
    imports: ['tab'], settings: ['tab'], discovery: ['tab', 'sub'], history: ['id'],
  });
  const r = parseRoute('#/p/r/devices/x/ports/extra/more');
  assert.equal(r.id, 'x');
  assert.equal(r.tab, 'ports');
  assert.equal(r.sub, 'extra');
  assert.deepEqual(r.extra, ['more']);
  assert.equal(buildRoute(r), '#/p/r/devices/x/ports/extra/more');

  const u = parseRoute('#/p/r/nosuchview/a/b');
  assert.equal(u.view, 'nosuchview');
  assert.deepEqual([u.id, u.tab, u.sub], ['', '', '']);
  assert.deepEqual(u.extra, ['a', 'b']);
  assert.equal(buildRoute(u), '#/p/r/nosuchview/a/b');

  const pa = parseRoute('#/p/r/patch/zzz');
  assert.deepEqual([pa.id, pa.extra], ['', ['zzz']], 'views without a shape keep segments in extra');
  const s = parseRoute('#/p/r/schedules/cables');
  assert.deepEqual([s.id, s.tab], ['', 'cables']);
  assert.equal(parseRoute('#/p/r/plan/fp%20a').id, 'fp a');
  assert.equal(parseRoute('#/p/r/rooms/chapel/devices/x').extra[0], 'x');
  assert.equal(parseRoute('#/p/r/history/42/').id, '42');
  assert.equal(parseRoute('#/p/r/devices/%E0%A4%A').id, '%E0%A4%A', 'malformed escapes are kept raw');
});

T('4b. withQuery, mergeRoute, sameRoute', () => {
  const parseRoute = fn('parseRoute');
  const buildRoute = fn('buildRoute');
  const withQuery = fn('withQuery');
  const mergeRoute = fn('mergeRoute');
  const sameRoute = fn('sameRoute');
  const r = parseRoute('#/c/m/devices/foh/ports?sel=port:foh:1&q=x');
  const w = withQuery(r, { q: null, sec: 'ports', pg: 2, sel: '' });
  assert.equal(buildRoute(w), '#/c/m/devices/foh/ports?sec=ports&pg=2');
  assert.equal(buildRoute(r), '#/c/m/devices/foh/ports?sel=port:foh:1&q=x', 'withQuery does not mutate');
  assert.equal(buildRoute(withQuery(r, { q: undefined })), '#/c/m/devices/foh/ports?sel=port:foh:1');

  assert.equal(buildRoute(mergeRoute(r, { tab: 'cables' })), '#/c/m/devices/foh/cables?sel=port:foh:1&q=x');
  assert.equal(buildRoute(mergeRoute(r, { view: 'patch' })), '#/c/m/patch?sel=port:foh:1&q=x', 'view change clears id/tab/sub');
  assert.equal(buildRoute(mergeRoute(r, { view: 'racks', id: 'rk-foh', tab: 'elevation', query: {} })), '#/c/m/racks/rk-foh/elevation');
  assert.equal(buildRoute(mergeRoute(r, { view: 'devices' })), buildRoute(r), 'same view keeps id/tab');
  assert.equal(buildRoute(mergeRoute(r, { room: '*', query: { sel: 'device:foh' } })), '#/c/*/devices/foh/ports?sel=device:foh');
  assert.equal(buildRoute(mergeRoute(r, { project: 'other' })), '#/other/m/devices/foh/ports?sel=port:foh:1&q=x');
  assert.equal(buildRoute(mergeRoute(parseRoute('#/p/r/devices/x/a/b/c'), { id: 'y' })), '#/p/r/devices/y/a/b', 'new id drops extra');
  assert.equal(buildRoute(mergeRoute(null, { project: 'p', room: 'r', view: 'sop' })), '#/p/r/sop');

  assert.equal(sameRoute('#/c/m/patch?sel=device:a', '#/c/m/patch?sel=device:a'), true);
  assert.equal(sameRoute('#/c/m/patch?a=1&b=2', '#/c/m/patch?b=2&a=1'), true, 'query order is irrelevant');
  assert.equal(sameRoute('#/c/m/patch?sel=device:a', '#/c/m/patch?sel=device:b'), false);
  assert.equal(sameRoute('#/c/m/patch?sel=device:a', '#/c/m/patch?sel=device:b', ['sel']), true);
  assert.equal(sameRoute('#/c/m/patch', '#/c/m/patch?drawer=0'), false);
  assert.equal(sameRoute('#/c/m/patch', '#/c/m/patch?drawer=0', ['drawer']), true);
  assert.equal(sameRoute('#/c/m/devices/a', '#/c/m/devices/b'), false);
  assert.equal(sameRoute('#/c/m/devices/a/ports', parseRoute('#/c/m/devices/a/ports')), true);
  assert.equal(sameRoute('#/c/m', '#/c/m/home'), true, 'empty view is DEFAULT_VIEW');
  assert.equal(sameRoute('#/c/m/x/1', '#/c/m/x/2'), false, 'extra is compared');
});

T('5. selToString / selFromString keep the app.js vectors', () => {
  const selToString = fn('selToString');
  const selFromString = fn('selFromString');
  const V = [
    ['device:x', { type: 'device', id: 'x', device: 'x' }, 'device:x'],
    ['device:x:port', { type: 'port', id: 'x', device: 'x', port: 'port' }, 'port:x:port'],
    ['port:d:p', { type: 'port', id: 'd', device: 'd', port: 'p' }, 'port:d:p'],
    ['port:d', { type: 'port', id: 'd', device: 'd', port: null }, 'port:d:null'],
    ['cable:c1', { type: 'cable', id: 'c1' }, 'cable:c1'],
    ['rack:rk', { type: 'rack', id: 'rk' }, 'rack:rk'],
    ['floorplan:fp', { type: 'floorplan', id: 'fp' }, 'floorplan:fp'],
    ['marker:fp:d', { type: 'marker', id: 'd', floorplan: 'fp', device: 'd' }, 'marker:fp:d'],
    ['channel:d:3', { type: 'channel', id: 'd', device: 'd', channel: '3' }, 'channel:d:3'],
    ['channel:d', { type: 'device', id: 'd', device: 'd' }, 'device:d'],
    ['bundle:b', { type: 'bundle', id: 'b' }, 'bundle:b'],
    ['room:chapel', { type: 'room', id: 'chapel' }, 'room:chapel'],
    ['cable:c:extra', { type: 'cable', id: 'c', port: 'extra', device: 'c' }, 'cable:c'],
    ['device', null, ''],
    ['', null, ''],
  ];
  for (const [s, sel, back] of V) {
    assert.deepEqual(selFromString(s), sel, s);
    assert.equal(selToString(selFromString(s)), back, s);
  }
  assert.equal(selFromString(null), null);
  assert.equal(selToString(null), '');
  assert.equal(selToString({ type: 'port', device: 'rio-sl', port: 'analog-in-9' }), 'port:rio-sl:analog-in-9');
  assert.equal(selToString({ type: 'marker', id: 'foh-cl5', floorplan: 'fp-main-floor' }), 'marker:fp-main-floor:foh-cl5');
});

T('6. SECTIONS, roles: sectionsFor / canSee / sectionOf / sectionRoot', () => {
  const sectionsFor = fn('sectionsFor');
  const canSee = fn('canSee');
  const sectionOf = fn('sectionOf');
  const sectionRoot = fn('sectionRoot');
  assert.deepEqual(rc.SECTIONS.map((s) => s.key), ['home', 'patch', 'rooms', 'devices', 'schedules', 'sop', 'data', 'settings']);
  assert.deepEqual(rc.SECTIONS.map((s) => s.views[0]), ['home', 'patch', 'rooms', 'devices', 'schedules', 'sop', 'imports', 'settings']);
  assert.deepEqual(rc.SECTIONS.map((s) => s.nav), ['sm', 'all', 'all', 'all', 'all', 'all', 'all', 'all']);
  assert.deepEqual(rc.SECTIONS.find((s) => s.key === 'data').views, ['imports', 'discovery', 'history', 'json']);
  assert.equal(rc.SECTIONS.find((s) => s.key === 'settings').glyph, '\u2699\uFE0E');
  assert.equal(rc.SECTIONS.find((s) => s.key === 'home').glyph, '\u2302');
  for (const s of rc.SECTIONS) assert.deepEqual(Object.keys(s), ['key', 'label', 'glyph', 'views', 'nav'], s.key);
  for (const s of rc.SECTIONS) for (const v of s.views) assert.equal(rc.VIEW_ROLES[v], 'viewer', v);
  assert.deepEqual(rc.TAB_ROLES, { settings: { users: 'admin', backups: 'admin', sharing: 'editor' } });

  for (const role of ['viewer', 'editor', 'admin']) assert.equal(sectionsFor(role).length, 8, role);
  assert.deepEqual(sectionsFor('viewer').map((s) => s.views), rc.SECTIONS.map((s) => s.views));
  assert.notEqual(sectionsFor('viewer')[0], rc.SECTIONS[0], 'sectionsFor returns copies');
  assert.equal(canSee('settings', 'viewer', 'users'), false);
  assert.equal(canSee('settings', 'viewer', 'backups'), false);
  assert.equal(canSee('settings', 'viewer', 'sharing'), false);
  assert.equal(canSee('settings', 'editor', 'sharing'), true);
  assert.equal(canSee('settings', 'editor', 'users'), false);
  assert.equal(canSee('settings', 'admin', 'users'), true);
  assert.equal(canSee('settings', 'viewer'), true);
  assert.equal(canSee('settings', 'viewer', 'networks'), true);
  assert.equal(canSee('patch', 'viewer'), true);
  assert.equal(canSee('patch', undefined), true);

  assert.equal(sectionOf('table'), 'patch');
  assert.equal(sectionOf('inventory'), 'devices');
  assert.equal(sectionOf('builds'), 'schedules');
  assert.equal(sectionOf('json'), 'data');
  assert.equal(sectionOf('nosuchview'), 'data');
  assert.equal(sectionOf(''), 'home');

  const cur = { project: 'campus', room: 'chapel', view: 'devices', id: 'x', tab: 'ports', sub: '', extra: [], query: { sel: 'device:x' } };
  assert.deepEqual(sectionRoot('rooms', cur, 'viewer'), { project: 'campus', room: 'chapel', view: 'rooms', query: {} });
  assert.deepEqual(sectionRoot('data', cur, 'admin'), { project: 'campus', room: 'chapel', view: 'imports', query: {} });
  assert.equal(sectionRoot('nosuch', cur, 'admin'), null);
});

T('7. navMemory: remembered hash, active root, per project, corrupt storage', () => {
  const navMemory = fn('navMemory');
  const parseRoute = fn('parseRoute');
  const st = memStore();
  const nav = navMemory(st);
  nav.remember('campus', '#/campus/main/schedules/cables?q=drum');
  nav.remember('campus', '#/campus/main/patch?sel=device:foh-cl5');
  nav.remember('campus', '#/campus/main/table');
  assert.deepEqual(JSON.parse(st.data['fathom.ui.nav']), {
    campus: { schedules: '#/campus/main/schedules/cables?q=drum', patch: '#/campus/main/table' },
  });
  const here = parseRoute('#/campus/main/table');
  assert.equal(nav.target('campus', 'schedules', here, 'admin'), '#/campus/main/schedules/cables?q=drum', 'other section: remembered');
  assert.equal(nav.target('campus', 'patch', here, 'admin'), '#/campus/main/patch', 'active section: root');
  assert.equal(nav.target('campus', 'rooms', here, 'admin'), '#/campus/main/rooms', 'never visited: root');
  assert.equal(nav.target('campus', 'nosuch', here, 'admin'), '');
  assert.equal(nav.target('campus', 'patch', parseRoute('#/campus/*/schedules'), 'admin'), '#/campus/main/table', 'remembered hash keeps its room');
  assert.equal(nav.target('campus', 'rooms', parseRoute('#/campus/*/patch'), 'admin'), '#/campus/*/rooms', 'root uses the current room');
  assert.equal(nav.target('campus', 'home', parseRoute('#/campus/main'), 'admin'), '#/campus/main/home', 'empty view is home');

  nav.remember('other', '#/other/main/settings/users');
  assert.equal(nav.target('other', 'schedules', parseRoute('#/other/main/patch'), 'admin'), '#/other/main/schedules', 'per project');
  assert.equal(nav.target('other', 'settings', parseRoute('#/other/main/patch'), 'admin'), '#/other/main/settings/users');
  assert.equal(nav.target('other', 'settings', parseRoute('#/other/main/patch'), 'viewer'), '#/other/main/settings', 'tab not permitted: root');
  assert.equal(navMemory(st).target('campus', 'schedules', here, 'admin'), '#/campus/main/schedules/cables?q=drum', 'state lives in storage');

  nav.clear();
  assert.equal(st.data['fathom.ui.nav'], undefined);
  assert.equal(nav.target('campus', 'schedules', here, 'admin'), '#/campus/main/schedules');

  for (const bad of ['{not json', '[]', '"str"', 'null', '{"campus": 5}', '{"campus": {"schedules": 7}}']) {
    const s2 = memStore({ 'fathom.ui.nav': bad });
    const n2 = navMemory(s2);
    assert.equal(n2.target('campus', 'schedules', here, 'admin'), '#/campus/main/schedules', bad);
    n2.remember('campus', '#/campus/main/schedules/racks');
    assert.equal(n2.target('campus', 'schedules', here, 'admin'), '#/campus/main/schedules/racks', bad);
  }
  for (const s of [throwing, null, undefined]) {
    const n3 = navMemory(s);
    assert.doesNotThrow(() => n3.remember('campus', '#/campus/main/schedules'));
    assert.equal(n3.target('campus', 'schedules', here, 'admin'), '#/campus/main/schedules');
    assert.doesNotThrow(() => n3.clear());
  }
});

T('8. BP and layoutFor thresholds (D3)', () => {
  const layoutFor = fn('layoutFor');
  assert.deepEqual(rc.BP, { md: 700, lg: 1100 });
  assert.equal(layoutFor(390), 'sm');
  assert.equal(layoutFor(699), 'sm');
  assert.equal(layoutFor(700), 'md');
  assert.equal(layoutFor(744), 'md');
  assert.equal(layoutFor(1099), 'md');
  assert.equal(layoutFor(1100), 'lg');
  assert.equal(layoutFor(1280), 'lg');
});

test('dom.js imports in Node and exports h, esc, on', { skip: dm.skip }, () => {
  if (dm.error) throw dm.error;
  for (const k of ['h', 'esc', 'on']) assert.equal(typeof dm.mod[k], 'function', k);
  assert.equal(dm.mod.esc('<a href="x">\'&</a>'), '&lt;a href=&quot;x&quot;&gt;&#39;&amp;&lt;/a&gt;');
  assert.equal(dm.mod.esc(null), '');
  const calls = [];
  const target = {
    addEventListener: (t, f, o) => calls.push(['add', t, f, o]),
    removeEventListener: (t, f, o) => calls.push(['remove', t, f, o]),
  };
  const f = () => {};
  const off = dm.mod.on(target, 'click', f, { passive: true });
  assert.equal(typeof off, 'function');
  off();
  off();
  assert.deepEqual(calls, [['add', 'click', f, { passive: true }], ['remove', 'click', f, { passive: true }]]);
});
