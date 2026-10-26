// Contract tests: js/drawer-core.js (DRAWER) against docs/ui-audit.md B.1 D1, D3, D4 and B.2 DRAWER.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, m, need } from './fixtures/helpers.mjs';

const { mod, skip: absent, error } = await loadModule('js/drawer-core.js', 'DRAWER');
const skip = absent || (error ? 'drawer-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);

if (error) test('drawer-core.js imports in Node (D12 pure module)', () => { throw error; });

const nil = (v) => v === null || v === undefined;
const SEL = 'device:foh-cl5';

// parseDrawer may report absent values as null or undefined; compare in a normalized form.
function normState(s) {
  return { sel: nil(s.sel) ? null : s.sel, section: nil(s.section) ? null : s.section, open: s.open };
}

T('drawerMode thresholds (D3: sm < 700, md 700-1099, lg >= 1100)', () => {
  const drawerMode = need(mod, 'drawerMode', 'D3', 'B.2 DRAWER');
  const cases = [
    [0, 'full'], [390, 'full'], [699, 'full'],
    [700, 'sheet'], [820, 'sheet'], [1099, 'sheet'],
    [1100, 'docked'], [1280, 'docked'], [2560, 'docked'],
  ];
  for (const [w, want] of cases) {
    assert.equal(drawerMode(w), want, m('D3', 'B.2 DRAWER', `drawerMode(${w})`));
  }
});

T('parseDrawer: no sel means closed', () => {
  const parseDrawer = need(mod, 'parseDrawer', 'D1', 'B.2 DRAWER');
  for (const q of [{}, { drawer: '0' }, { q: 'x' }]) {
    const r = parseDrawer(q);
    assert.ok(nil(r.sel), m('D1', 'B.2 DRAWER', `sel absent for ${JSON.stringify(q)}`));
    assert.equal(r.open, false, m('D4', 'B.2 DRAWER', `open = !!sel && drawer !== '0' for ${JSON.stringify(q)}`));
  }
  assert.ok(nil(parseDrawer({}).section), m('D1', 'B.2 DRAWER', 'section absent without sec'));
});

T('parseDrawer: sel opens unless drawer=0; sec maps to section', () => {
  const parseDrawer = need(mod, 'parseDrawer', 'D1', 'B.2 DRAWER');
  assert.deepEqual(normState(parseDrawer({ sel: SEL })), { sel: SEL, section: null, open: true },
    m('D4', 'B.2 DRAWER', 'sel without drawer=0 opens the drawer'));
  assert.deepEqual(normState(parseDrawer({ sel: SEL, drawer: '0' })), { sel: SEL, section: null, open: false },
    m('D4', 'B.2 DRAWER', 'drawer=0 keeps the selection with the drawer closed'));
  assert.deepEqual(normState(parseDrawer({ sel: SEL, sec: 'net' })), { sel: SEL, section: 'net', open: true },
    m('D1', 'B.2 DRAWER', 'sec is the drawer section'));
  assert.deepEqual(normState(parseDrawer({ sel: SEL, sec: 'inventory', drawer: '0' })),
    { sel: SEL, section: 'inventory', open: false }, m('D1', 'B.2 DRAWER', 'sec survives drawer=0'));
  assert.deepEqual(normState(parseDrawer({ sel: 'port:foh-cl5:omni-in-1', drawer: '1', filter: 'audio' })),
    { sel: 'port:foh-cl5:omni-in-1', section: null, open: true },
    m('D1', 'B.2 DRAWER', "only drawer === '0' closes; unrelated keys are ignored"));
});

T('drawerParams: query patch {sel, sec, drawer} with null deleting keys', () => {
  const drawerParams = need(mod, 'drawerParams', 'D1', 'B.2 DRAWER');
  const cases = [
    [{ sel: SEL, section: null, open: true }, { sel: SEL, sec: null, drawer: null }],
    [{ sel: SEL, section: 'net', open: true }, { sel: SEL, sec: 'net', drawer: null }],
    [{ sel: SEL, section: null, open: false }, { sel: SEL, sec: null, drawer: '0' }],
    [{ sel: SEL, section: 'procedures', open: false }, { sel: SEL, sec: 'procedures', drawer: '0' }],
    [{ sel: null, section: null, open: false }, { sel: null, sec: null, drawer: null }],
    [{ sel: null, section: null, open: true }, { sel: null, sec: null, drawer: null }],
  ];
  for (const [state, want] of cases) {
    assert.deepEqual(drawerParams(state), want, m('D1', 'B.2 DRAWER', `drawerParams(${JSON.stringify(state)})`));
  }
  assert.deepEqual(drawerParams({ sel: SEL, open: true }), { sel: SEL, sec: null, drawer: null },
    m('D1', 'B.2 DRAWER', 'missing section deletes a stale sec'));
});

T('parseDrawer(drawerParams(x)) round trip over the truth table', () => {
  const parseDrawer = need(mod, 'parseDrawer', 'D1', 'B.2 DRAWER');
  const drawerParams = need(mod, 'drawerParams', 'D1', 'B.2 DRAWER');
  const states = [{ sel: null, section: null, open: false }];
  for (const sel of [SEL, 'marker:fp-main-stage:foh-cl5', 'cable:c-0001']) {
    for (const section of [null, 'net', 'inventory']) {
      for (const open of [true, false]) states.push({ sel, section, open });
    }
  }
  for (const s of states) {
    const q = drawerParams(s);
    assert.deepEqual(normState(parseDrawer(q)), s, m('D1', 'B.2 DRAWER', `round trip ${JSON.stringify(s)} via ${JSON.stringify(q)}`));
  }
});

T('drawerParams(parseDrawer(q)) reproduces the drawer keys of q', () => {
  const parseDrawer = need(mod, 'parseDrawer', 'D1', 'B.2 DRAWER');
  const drawerParams = need(mod, 'drawerParams', 'D1', 'B.2 DRAWER');
  const queries = [
    {},
    { sel: SEL },
    { sel: SEL, drawer: '0' },
    { sel: SEL, sec: 'net' },
    { sel: SEL, sec: 'net', drawer: '0' },
  ];
  for (const q of queries) {
    const want = { sel: q.sel || null, sec: q.sec || null, drawer: q.drawer || null };
    assert.deepEqual(drawerParams(parseDrawer(q)), want, m('D1', 'B.2 DRAWER', `round trip ${JSON.stringify(q)}`));
  }
});

T('topLayer follows the D4 Esc order', () => {
  const topLayer = need(mod, 'topLayer', 'D4', 'B.2 DRAWER');
  const ORDER = ['palette', 'dialog', 'trace', 'assistant', 'explorer', 'drawer'];
  const flags = (on) => {
    const f = {};
    for (const k of ORDER) f[k] = on.indexOf(k) >= 0;
    return f;
  };
  assert.ok(nil(topLayer(flags([]))), m('D4', 'B.2 DRAWER', 'no layer open returns null/undefined'));
  for (const k of ORDER) {
    assert.equal(topLayer(flags([k])), k, m('D4', 'B.2 DRAWER', `only ${k} open`));
  }
  // Every subset: the answer is the first open key in ORDER.
  for (let mask = 1; mask < 1 << ORDER.length; mask++) {
    const on = ORDER.filter((_, i) => mask & (1 << i));
    assert.equal(topLayer(flags(on)), on[0], m('D4', 'B.2 DRAWER', `open: ${on.join(', ')}`));
  }
});

T('CANVAS_VIEWS is patch, plan, map', () => {
  const CANVAS_VIEWS = need(mod, 'CANVAS_VIEWS', 'D4', 'B.2 DRAWER');
  assert.deepEqual(Array.from(CANVAS_VIEWS), ['patch', 'plan', 'map'], m('D4', 'B.2 DRAWER', 'CANVAS_VIEWS'));
});

T('selectionOpensDrawer truth table (D3 canvas selection row, D4)', () => {
  const selectionOpensDrawer = need(mod, 'selectionOpensDrawer', 'D4', 'B.2 DRAWER');
  const canvas = [
    ['patch', { view: 'patch' }],
    ['plan', { view: 'plan', id: 'fp-main-stage' }],
    ['plan', { view: 'plan' }],
    ['map', { view: 'map' }],
    ['racks', { view: 'racks' }],
    ['racks', { view: 'racks', id: 'rk-foh', tab: 'elevation' }],
    ['racks', { view: 'racks', id: 'rk-foh', tab: 'elevation', sub: 'rear' }],
  ];
  const lists = [
    ['inventory', { view: 'inventory' }],
    ['schedules', { view: 'schedules', tab: 'cables' }],
    ['devices', { view: 'devices' }],
    ['devices', { view: 'devices', id: 'foh-cl5', tab: 'ports' }],
    ['table', { view: 'table' }],
    ['racks', { view: 'racks', id: 'rk-foh', tab: 'devices' }],
  ];
  const label = (view, route, layout, intent) =>
    m('D4', 'B.2 DRAWER', `selectionOpensDrawer(${view}, ${JSON.stringify(route)}, ${layout}, ${intent})`);
  for (const layout of ['sm', 'md', 'lg']) {
    for (const intent of [undefined, false, true]) {
      for (const [view, route] of canvas) {
        const want = layout === 'lg' || intent === true;
        assert.equal(selectionOpensDrawer(view, route, layout, intent), want, label(view, route, layout, intent));
      }
      for (const [view, route] of lists) {
        assert.equal(selectionOpensDrawer(view, route, layout, intent), true, label(view, route, layout, intent));
      }
    }
  }
});
