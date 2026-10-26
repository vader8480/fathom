// DRAWER: js/drawer-core.js (and the Node-safe import of js/drawer.js) against
// docs/ui-audit.md D1, D3, D4 and B.2 DRAWER.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { loadModule, need, JS } from './fixtures/helpers.mjs';

const { mod, skip: absent, error } = await loadModule('js/drawer-core.js', 'DRAWER');
const S = 'docs/ui-audit.md B.2 DRAWER';
const skip = absent || (error ? 'drawer-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);
const fn = (name) => need(mod, name, 'DRAWER', S);

if (error) test('drawer-core.js imports in Node (D12 pure module)', () => { throw error; });

const SEL = 'device:foh-cl5';

T('drawerMode: every breakpoint edge maps through layoutFor (D3)', () => {
  const drawerMode = fn('drawerMode');
  const cases = [[-1, 'full'], [0, 'full'], [320, 'full'], [699, 'full'], [699.5, 'full'],
    [700, 'sheet'], [744, 'sheet'], [1024, 'sheet'], [1099, 'sheet'], [1099.9, 'sheet'],
    [1100, 'docked'], [1440, 'docked'], [3840, 'docked']];
  for (const [w, want] of cases) assert.equal(drawerMode(w), want, `drawerMode(${w})`);
  assert.equal(drawerMode('820'), 'sheet', 'numeric strings are accepted');
});

T('isModal: sheet and full are modal, docked is not', () => {
  const isModal = fn('isModal');
  assert.equal(isModal('docked'), false);
  assert.equal(isModal('sheet'), true);
  assert.equal(isModal('full'), true);
  assert.equal(isModal(''), false);
});

T('parseDrawer: tolerant of missing and empty values', () => {
  const parseDrawer = fn('parseDrawer');
  assert.deepEqual(parseDrawer(undefined), { sel: null, section: null, open: false });
  assert.deepEqual(parseDrawer(null), { sel: null, section: null, open: false });
  assert.deepEqual(parseDrawer({ sel: '', sec: '' }), { sel: null, section: null, open: false });
  assert.deepEqual(parseDrawer({ sel: SEL, drawer: '' }), { sel: SEL, section: null, open: true });
  assert.deepEqual(parseDrawer({ sel: SEL, drawer: 'false' }), { sel: SEL, section: null, open: true },
    "only the literal '0' closes");
  assert.deepEqual(parseDrawer({ sec: 'net' }), { sel: null, section: 'net', open: false },
    'sec is reported but nothing opens without sel');
});

T('drawerParams: sec and drawer are dropped without a selection', () => {
  const drawerParams = fn('drawerParams');
  assert.deepEqual(drawerParams({ sel: null, section: 'net', open: false }), { sel: null, sec: null, drawer: null });
  assert.deepEqual(drawerParams({ sel: '', section: 'net', open: true }), { sel: null, sec: null, drawer: null });
  assert.deepEqual(drawerParams(undefined), { sel: null, sec: null, drawer: null });
  assert.deepEqual(drawerParams({ sel: SEL, section: '', open: false }), { sel: SEL, sec: null, drawer: '0' });
});

T('parseDrawer and drawerParams round trip in both directions', () => {
  const parseDrawer = fn('parseDrawer');
  const drawerParams = fn('drawerParams');
  for (const sel of [null, SEL, 'port:foh-cl5:omni-in-1', 'channel:foh-cl5:ch-1']) {
    for (const section of [null, 'inventory', 'procedures']) {
      for (const open of [true, false]) {
        const s = { sel, section: sel ? section : null, open: !!sel && open };
        assert.deepEqual(parseDrawer(drawerParams(s)), s, `state ${JSON.stringify(s)}`);
      }
    }
  }
  for (const q of [{ sel: SEL, sec: 'net', drawer: '0' }, { sel: SEL }, {}]) {
    const p = drawerParams(parseDrawer(q));
    assert.deepEqual(p, { sel: q.sel || null, sec: q.sec || null, drawer: q.drawer || null }, `query ${JSON.stringify(q)}`);
  }
});

T('drawerHistory: open from closed pushes; switch and close replace; no change is null (D1)', () => {
  const drawerHistory = fn('drawerHistory');
  const closed = { sel: null, section: null, open: false };
  const open = { sel: SEL, section: null, open: true };
  const selected = { sel: SEL, section: null, open: false };
  assert.equal(drawerHistory(closed, open), 'push', 'nothing -> open');
  assert.equal(drawerHistory(selected, open), 'push', 'drawer=0 -> open (Details)');
  assert.equal(drawerHistory(open, { sel: 'cable:c-0001', open: true }), 'replace', 'switch subject while open');
  assert.equal(drawerHistory(open, { sel: SEL, section: 'net', open: true }), 'replace', 'switch section while open');
  assert.equal(drawerHistory(open, closed), 'replace', 'close');
  assert.equal(drawerHistory(closed, selected), 'replace', 'canvas selection below lg');
  assert.equal(drawerHistory(open, { sel: SEL, open: true }), null, 'same state');
  assert.equal(drawerHistory(closed, { sel: null, section: 'net', open: true }), null, 'no selection is no change');
});

T('topLayer: LAYERS order, unknown keys ignored, missing flags are closed', () => {
  const topLayer = fn('topLayer');
  assert.deepEqual(Array.from(fn('LAYERS')), ['palette', 'dialog', 'trace', 'assistant', 'explorer', 'drawer']);
  assert.equal(topLayer(undefined), null);
  assert.equal(topLayer({}), null);
  assert.equal(topLayer({ highlight: true }), null, 'highlight sits below the drawer and is the shell\'s');
  assert.equal(topLayer({ drawer: true, highlight: true }), 'drawer');
  assert.equal(topLayer({ drawer: true, explorer: 1 }), 'explorer', 'truthy values count');
  assert.equal(topLayer({ drawer: true, trace: true, dialog: true }), 'dialog');
  assert.equal(topLayer({ palette: true, dialog: true, drawer: true }), 'palette');
});

T('isCanvas: patch, plan, map and the racks elevation', () => {
  const isCanvas = fn('isCanvas');
  assert.equal(isCanvas('patch', {}), true);
  assert.equal(isCanvas('plan', { id: 'fp-main-stage' }), true);
  assert.equal(isCanvas('map'), true, 'route is optional');
  assert.equal(isCanvas('racks', { view: 'racks' }), true, 'racks landing shows all elevations');
  assert.equal(isCanvas('racks', { id: 'rk-foh', tab: 'elevation' }), true);
  assert.equal(isCanvas('racks', { id: 'rk-foh', tab: 'elevation', sub: 'front' }), true);
  assert.equal(isCanvas('racks', { id: 'rk-foh' }), false, 'rack page overview');
  assert.equal(isCanvas('racks', { id: 'rk-foh', tab: 'cables' }), false);
  assert.equal(isCanvas('', { view: 'patch' }), true, 'falls back to route.view');
  for (const v of ['home', 'table', 'inventory', 'schedules', 'devices', 'rooms', 'sop', 'settings']) {
    assert.equal(isCanvas(v, { view: v }), false, v);
  }
});

T('selectionOpensDrawer: patch, inventory and racks at sm, md, lg with and without intent (D4)', () => {
  const selectionOpensDrawer = fn('selectionOpensDrawer');
  const rows = [
    // view, route, {layout: [no intent, intent]}
    ['patch', { view: 'patch' }, { sm: [false, true], md: [false, true], lg: [true, true] }],
    ['inventory', { view: 'inventory' }, { sm: [true, true], md: [true, true], lg: [true, true] }],
    ['racks', { view: 'racks' }, { sm: [false, true], md: [false, true], lg: [true, true] }],
    ['racks', { view: 'racks', id: 'rk-foh', tab: 'elevation', sub: 'rear' }, { sm: [false, true], md: [false, true], lg: [true, true] }],
    ['racks', { view: 'racks', id: 'rk-foh', tab: 'devices' }, { sm: [true, true], md: [true, true], lg: [true, true] }],
  ];
  for (const [view, route, want] of rows) {
    for (const layout of ['sm', 'md', 'lg']) {
      assert.equal(selectionOpensDrawer(view, route, layout), want[layout][0], `${view} ${JSON.stringify(route)} ${layout}`);
      assert.equal(selectionOpensDrawer(view, route, layout, false), want[layout][0], `${view} ${layout} intent=false`);
      assert.equal(selectionOpensDrawer(view, route, layout, true), want[layout][1], `${view} ${layout} intent=true`);
    }
  }
  assert.equal(selectionOpensDrawer('patch', { view: 'patch' }, 'md', 1), false, 'only intent === true counts');
});

T('trapIndex: Tab wraps at the ends, enters from outside, falls back to the host', () => {
  const trapIndex = fn('trapIndex');
  assert.equal(trapIndex(0, -1, false), -1, 'nothing focusable: keep the host');
  assert.equal(trapIndex(0, -1, true), -1);
  assert.equal(trapIndex(3, -1, false), 0, 'from the host or outside, Tab goes to the first');
  assert.equal(trapIndex(3, -1, true), 2, 'Shift+Tab goes to the last');
  assert.equal(trapIndex(3, 2, false), 0, 'wraps forward');
  assert.equal(trapIndex(3, 0, true), 2, 'wraps backward');
  assert.equal(trapIndex(3, 1, false), null, 'middle: the browser moves');
  assert.equal(trapIndex(3, 1, true), null);
  assert.equal(trapIndex(1, 0, false), 0);
  assert.equal(trapIndex(1, 0, true), 0);
  assert.equal(trapIndex(2, 5, false), 0, 'stale index counts as outside');
});

T('drawer-core.js is pure: no DOM, storage or timers (D12)', () => {
  const src = readFileSync(path.join(JS, 'drawer-core.js'), 'utf8').replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const word of ['window', 'document', 'localStorage', 'sessionStorage', 'setTimeout', 'setInterval', 'fetch', 'navigator', 'location']) {
    assert.ok(!new RegExp('\\b' + word + '\\b').test(src), `drawer-core.js mentions ${word}`);
  }
  const imports = src.match(/from\s+'[^']+'/g) || [];
  assert.deepEqual(imports, ["from './router-core.js'"], 'only router-core is imported');
});

test('drawer.js imports in Node without touching the DOM and exports the contract', { skip }, async () => {
  const dr = await loadModule('js/drawer.js', 'DRAWER');
  if (dr.error) throw dr.error;
  assert.equal(typeof need(dr.mod, 'createDrawer', 'DRAWER', S), 'function');
  assert.equal(typeof need(dr.mod, 'domLayers', 'DRAWER', S), 'function');
  const src = readFileSync(path.join(JS, 'drawer.js'), 'utf8');
  assert.ok(!/from\s+'\.\/app\.js'/.test(src), 'D12: DOM helpers come from dom.js, not app.js');
  assert.ok(/from\s+'\.\/dom\.js'/.test(src), 'imports dom.js');
});

test('drawer.css uses only the D3 breakpoints and dr- classes', () => {
  const css = readFileSync(path.join(JS, '..', 'css', 'drawer.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const m of css.match(/\(\s*(?:max|min)-width\s*:\s*\d+px\s*\)/g) || []) {
    assert.ok(/(max-width:\s*699px|min-width:\s*700px|max-width:\s*1099px|min-width:\s*1100px)/.test(m), `breakpoint ${m}`);
  }
  const classes = new Set((css.match(/\.[a-z][\w-]*/g) || []).map((c) => c.slice(1)));
  for (const c of classes) assert.ok(c.indexOf('dr-') === 0, `class .${c} lacks the dr- prefix (D11)`);
  assert.ok(/prefers-reduced-motion:\s*reduce/.test(css), 'reduced motion disables the slide');
});
