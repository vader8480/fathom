// T-EXPLORER: contract test for js/explorer-core.js, written from docs/ui-audit.md alone
// (B.2 EXPLORER "Core", B.1 D3 breakpoints, B.1 D8 storage key fathom.ui.explorer.<key>).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, m, need } from './fixtures/helpers.mjs';

const { mod: ex, skip: absent, error } = await loadModule('js/explorer-core.js', 'EXPLORER');
const skip = absent || (error ? 'explorer-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);
const S = 'B.2 EXPLORER';
const D3 = 'B.1 D3';
const D8 = 'B.1 D8';
const C = (text) => m('EXPLORER', S, text);

if (error) test('explorer-core.js imports in Node (pure module)', () => { throw error; });

// In-memory Web Storage stand-in.
function memStorage(seed) {
  const data = new Map(Object.entries(seed || {}));
  return {
    data,
    getItem(k) { return data.has(k) ? data.get(k) : null; },
    setItem(k, v) { data.set(k, String(v)); },
    removeItem(k) { data.delete(k); },
  };
}
const throwing = {
  getItem() { throw new Error('SecurityError: storage disabled'); },
  setItem() { throw new Error('QuotaExceededError'); },
  removeItem() { throw new Error('SecurityError: storage disabled'); },
};

// The contract does not say whether activeChipKeys is an Array or a Set; this value works as both.
function chipKeys() {
  const a = Array.prototype.slice.call(arguments);
  Object.defineProperty(a, 'has', { value: (k) => a.indexOf(k) !== -1 });
  Object.defineProperty(a, 'size', { get: () => a.length });
  return a;
}

const ITEMS = [
  { id: 'foh-cl5', label: 'FOH CL5', sub: 'Yamaha CL5', disc: 'audio', group: 'Main Auditorium' },
  { id: 'proj-1', label: 'Projector 1', sub: 'Epson Pro L1505', disc: 'video', group: 'Main Auditorium' },
  { id: 'ulxd-4', label: 'Wireless Rx', sub: 'Shure ULXD4Q', disc: 'audio', group: 'FOH Rack' },
  { id: 'grandma', label: 'grandMA3 light', sub: 'MA Lighting', disc: 'lighting', group: 'Booth' },
  { id: 'cam-2', label: 'PTZ Camera', disc: 'video', group: 'Booth' },
  { id: 'dante-sw', label: 'Dante switch', sub: 'Netgear M4250', disc: 'network' },
];
const CHIPS = [
  { key: 'audio', label: 'Audio', test: (i) => i.disc === 'audio' },
  { key: 'video', label: 'Video', test: (i) => i.disc === 'video' },
  { key: 'lighting', label: 'Lighting', test: (i) => i.disc === 'lighting' },
];
const ids = (list) => list.map((i) => i.id);
const filterIds = (q, keys) => ids(need(ex, 'filterItems', 'EXPLORER', S)(ITEMS, q, keys, CHIPS));

// clampWidth

T('clampWidth keeps integers inside 240..480', () => {
  const clampWidth = need(ex, 'clampWidth', 'EXPLORER', S);
  for (const w of [240, 241, 300, 333, 400, 479, 480]) assert.equal(clampWidth(w), w, C(`clampWidth(${w})`));
});

T('clampWidth clamps to 240 and 480', () => {
  const clampWidth = need(ex, 'clampWidth', 'EXPLORER', S);
  for (const w of [239, 100, 0, -5]) assert.equal(clampWidth(w), 240, C(`clampWidth(${w}) is 240`));
  for (const w of [481, 1000, 1e6]) assert.equal(clampWidth(w), 480, C(`clampWidth(${w}) is 480`));
});

T('clampWidth defaults to 300 for undefined, NaN and non-numbers', () => {
  const clampWidth = need(ex, 'clampWidth', 'EXPLORER', S);
  assert.equal(clampWidth(), 300, C('clampWidth() is 300'));
  for (const w of [undefined, NaN, null, 'abc', '400', {}, [], true]) {
    assert.equal(clampWidth(w), 300, C(`clampWidth(${JSON.stringify(w) || String(w)}) is 300`));
  }
});

// loadExplorer / saveExplorer

T('loadExplorer defaults to {w: 300, c: false} on empty storage', () => {
  const loadExplorer = need(ex, 'loadExplorer', 'EXPLORER', S);
  const st = loadExplorer(memStorage(), 'devices');
  assert.deepEqual({ w: st.w, c: st.c }, { w: 300, c: false }, C('default state'));
});

T('loadExplorer returns a fresh default each call', () => {
  const loadExplorer = need(ex, 'loadExplorer', 'EXPLORER', S);
  const store = memStorage();
  const a = loadExplorer(store, 'devices');
  a.w = 460; a.c = true;
  const b = loadExplorer(store, 'devices');
  assert.deepEqual({ w: b.w, c: b.c }, { w: 300, c: false }, C('mutating a loaded state does not change the default'));
});

T('saveExplorer writes exactly fathom.ui.explorer.<key> as JSON {w, c}', () => {
  const saveExplorer = need(ex, 'saveExplorer', 'EXPLORER', D8);
  const store = memStorage();
  saveExplorer(store, 'devices', { w: 400, c: true });
  assert.deepEqual([...store.data.keys()], ['fathom.ui.explorer.devices'], m('EXPLORER', D8, 'one key, exact name'));
  const raw = JSON.parse(store.data.get('fathom.ui.explorer.devices'));
  assert.deepEqual({ w: raw.w, c: raw.c }, { w: 400, c: true }, m('EXPLORER', D8, 'stored shape {w, c}'));
});

T('saveExplorer stores widths inside 240..480', () => {
  const saveExplorer = need(ex, 'saveExplorer', 'EXPLORER', D8);
  const store = memStorage();
  saveExplorer(store, 'wide', { w: 999, c: false });
  saveExplorer(store, 'narrow', { w: 10, c: false });
  assert.equal(JSON.parse(store.getItem('fathom.ui.explorer.wide')).w, 480, m('EXPLORER', D8, 'w stored clamped to 480'));
  assert.equal(JSON.parse(store.getItem('fathom.ui.explorer.narrow')).w, 240, m('EXPLORER', D8, 'w stored clamped to 240'));
});

T('loadExplorer reads exactly fathom.ui.explorer.<key>', () => {
  const loadExplorer = need(ex, 'loadExplorer', 'EXPLORER', D8);
  const store = memStorage({
    'fathom.ui.explorer.devices': JSON.stringify({ w: 420, c: true }),
    'fathom.explorer.rooms': JSON.stringify({ w: 260, c: true }),
    'rooms': JSON.stringify({ w: 260, c: true }),
  });
  const d = loadExplorer(store, 'devices');
  assert.deepEqual({ w: d.w, c: d.c }, { w: 420, c: true }, m('EXPLORER', D8, 'reads the documented key'));
  const r = loadExplorer(store, 'rooms');
  assert.deepEqual({ w: r.w, c: r.c }, { w: 300, c: false }, m('EXPLORER', D8, 'ignores other key spellings'));
});

T('load and save round trip, keys independent', () => {
  const loadExplorer = need(ex, 'loadExplorer', 'EXPLORER', S);
  const saveExplorer = need(ex, 'saveExplorer', 'EXPLORER', S);
  const store = memStorage();
  saveExplorer(store, 'devices', { w: 400, c: false });
  saveExplorer(store, 'rooms', { w: 256, c: true });
  const d = loadExplorer(store, 'devices');
  const r = loadExplorer(store, 'rooms');
  assert.deepEqual({ w: d.w, c: d.c }, { w: 400, c: false }, C('devices round trip'));
  assert.deepEqual({ w: r.w, c: r.c }, { w: 256, c: true }, C('rooms round trip'));
  saveExplorer(store, 'devices', { w: 480, c: true });
  const d2 = loadExplorer(store, 'devices');
  assert.deepEqual({ w: d2.w, c: d2.c }, { w: 480, c: true }, C('overwrite round trip'));
  const r2 = loadExplorer(store, 'rooms');
  assert.deepEqual({ w: r2.w, c: r2.c }, { w: 256, c: true }, C('other key untouched'));
});

T('loadExplorer tolerates corrupt JSON and non-object values', () => {
  const loadExplorer = need(ex, 'loadExplorer', 'EXPLORER', D8);
  for (const raw of ['{not json', '', 'undefined', 'null', '42', '"str"', '[]', '[400, true]']) {
    const st = loadExplorer(memStorage({ 'fathom.ui.explorer.devices': raw }), 'devices');
    assert.deepEqual({ w: st.w, c: st.c }, { w: 300, c: false }, m('EXPLORER', D8, `stored ${JSON.stringify(raw)} falls back to default`));
  }
});

T('loadExplorer tolerates wrong field types', () => {
  const loadExplorer = need(ex, 'loadExplorer', 'EXPLORER', D8);
  const load = (v) => {
    const st = loadExplorer(memStorage({ 'fathom.ui.explorer.k': JSON.stringify(v) }), 'k');
    return { w: st.w, c: st.c };
  };
  assert.deepEqual(load({ w: 'abc', c: true }), { w: 300, c: true }, m('EXPLORER', D8, 'w: "abc" falls back to 300'));
  assert.deepEqual(load({ w: 400, c: 'yes' }), { w: 400, c: false }, m('EXPLORER', D8, 'c: "yes" is not collapsed'));
  assert.deepEqual(load({ w: 'abc', c: 'yes' }), { w: 300, c: false }, m('EXPLORER', D8, 'both wrong'));
  assert.deepEqual(load({ w: null, c: 1 }), { w: 300, c: false }, m('EXPLORER', D8, 'w: null, c: 1'));
  assert.deepEqual(load({}), { w: 300, c: false }, m('EXPLORER', D8, 'empty object'));
  assert.deepEqual(load({ c: true }), { w: 300, c: true }, m('EXPLORER', D8, 'missing w'));
  assert.deepEqual(load({ w: 350 }), { w: 350, c: false }, m('EXPLORER', D8, 'missing c'));
});

T('loadExplorer clamps out-of-range stored widths', () => {
  const loadExplorer = need(ex, 'loadExplorer', 'EXPLORER', D8);
  const load = (w) => loadExplorer(memStorage({ 'fathom.ui.explorer.k': JSON.stringify({ w: w, c: false }) }), 'k').w;
  assert.equal(load(1000), 480, m('EXPLORER', D8, 'w 1000 loads as 480'));
  assert.equal(load(481), 480, m('EXPLORER', D8, 'w 481 loads as 480'));
  assert.equal(load(239), 240, m('EXPLORER', D8, 'w 239 loads as 240'));
  assert.equal(load(-20), 240, m('EXPLORER', D8, 'w -20 loads as 240'));
});

T('load and save tolerate missing storage (null)', () => {
  const loadExplorer = need(ex, 'loadExplorer', 'EXPLORER', D8);
  const saveExplorer = need(ex, 'saveExplorer', 'EXPLORER', D8);
  let st;
  assert.doesNotThrow(() => { st = loadExplorer(null, 'devices'); }, m('EXPLORER', D8, 'load with null storage'));
  assert.deepEqual({ w: st.w, c: st.c }, { w: 300, c: false }, m('EXPLORER', D8, 'null storage gives default'));
  assert.doesNotThrow(() => saveExplorer(null, 'devices', { w: 400, c: true }), m('EXPLORER', D8, 'save with null storage'));
});

T('load and save tolerate throwing getItem/setItem (Safari private mode)', () => {
  const loadExplorer = need(ex, 'loadExplorer', 'EXPLORER', D8);
  const saveExplorer = need(ex, 'saveExplorer', 'EXPLORER', D8);
  let st;
  assert.doesNotThrow(() => { st = loadExplorer(throwing, 'devices'); }, m('EXPLORER', D8, 'load with throwing getItem'));
  assert.deepEqual({ w: st.w, c: st.c }, { w: 300, c: false }, m('EXPLORER', D8, 'throwing storage gives default'));
  assert.doesNotThrow(() => saveExplorer(throwing, 'devices', { w: 400, c: true }), m('EXPLORER', D8, 'save with throwing setItem'));
});

// filterItems

T('filterItems: empty query and empty chip set keep every item in order', () => {
  assert.deepEqual(filterIds('', chipKeys()), ids(ITEMS), C('no filtering'));
});

T('filterItems: default match is label + sub, case-insensitive substring', () => {
  assert.deepEqual(filterIds('cl5', chipKeys()), ['foh-cl5'], C('label/sub "cl5"'));
  assert.deepEqual(filterIds('SHURE', chipKeys()), ['ulxd-4'], C('sub match, upper-case query'));
  assert.deepEqual(filterIds('ire', chipKeys()), ['ulxd-4'], C('mid-word substring of label "Wireless"'));
  assert.deepEqual(filterIds('grandma3', chipKeys()), ['grandma'], C('mixed-case label, lower-case query'));
  assert.deepEqual(filterIds('ptz', chipKeys()), ['cam-2'], C('item without sub still matches on label'));
  assert.deepEqual(filterIds('epson pro', chipKeys()), ['proj-1'], C('query with a space is one substring'));
  assert.deepEqual(filterIds('lighting', chipKeys()), ['grandma'], C('only label/sub, not the disc field'));
  assert.deepEqual(filterIds('zzz-no-match', chipKeys()), [], C('no match gives empty list'));
});

T('filterItems: chips are OR within the active set', () => {
  assert.deepEqual(filterIds('', chipKeys('audio')), ['foh-cl5', 'ulxd-4'], C('audio only'));
  assert.deepEqual(filterIds('', chipKeys('audio', 'video')), ['foh-cl5', 'proj-1', 'ulxd-4', 'cam-2'], C('audio OR video, original order'));
  assert.deepEqual(filterIds('', chipKeys('video', 'audio')), ['foh-cl5', 'proj-1', 'ulxd-4', 'cam-2'], C('chip order does not matter'));
  assert.deepEqual(filterIds('', chipKeys('audio', 'video', 'lighting')), ['foh-cl5', 'proj-1', 'ulxd-4', 'grandma', 'cam-2'], C('all chips'));
});

T('filterItems: chips AND query', () => {
  assert.deepEqual(filterIds('foh', chipKeys('audio')), ['foh-cl5'], C('audio AND "foh"'));
  assert.deepEqual(filterIds('shure', chipKeys('audio', 'video')), ['ulxd-4'], C('(audio OR video) AND "shure"'));
  assert.deepEqual(filterIds('shure', chipKeys('video')), [], C('video AND "shure" is empty'));
  assert.deepEqual(filterIds('dante', chipKeys('audio', 'video', 'lighting')), [], C('query match excluded by chips'));
  assert.deepEqual(filterIds('dante', chipKeys()), ['dante-sw'], C('same query, no chips'));
});

T('filterItems: an item passes if ANY active chip test is true', () => {
  const filterItems = need(ex, 'filterItems', 'EXPLORER', S);
  const chips = [
    { key: 'wireless', label: 'Wireless', test: (i) => /wireless/i.test(i.label) },
    { key: 'audio', label: 'Audio', test: (i) => i.disc === 'audio' },
  ];
  const out = filterItems(ITEMS, '', chipKeys('wireless', 'audio'), chips);
  assert.deepEqual(ids(out), ['foh-cl5', 'ulxd-4'], C('item matching two chips appears once'));
});

T('filterItems returns the item objects and does not mutate input', () => {
  const filterItems = need(ex, 'filterItems', 'EXPLORER', S);
  const items = ITEMS.map((i) => Object.assign({}, i));
  const before = JSON.stringify(items);
  const out = filterItems(items, 'cl5', chipKeys(), CHIPS);
  assert.equal(out.length, 1, C('one match'));
  assert.equal(out[0], items[0], C('same object as the input item'));
  assert.equal(JSON.stringify(items), before, C('input items unchanged'));
  assert.equal(items.length, ITEMS.length, C('input array length unchanged'));
});

// groupItems

T('groupItems groups in first-seen order, keeping item order', () => {
  const groupItems = need(ex, 'groupItems', 'EXPLORER', S);
  const items = [
    { id: 'a', label: 'A', group: 'Booth' },
    { id: 'b', label: 'B', group: 'Stage' },
    { id: 'c', label: 'C', group: 'Booth' },
    { id: 'd', label: 'D', group: 'Attic' },
    { id: 'e', label: 'E', group: 'Stage' },
  ];
  const out = groupItems(items);
  assert.ok(Array.isArray(out), C('returns an array'));
  assert.deepEqual(out.map((g) => g.group), ['Booth', 'Stage', 'Attic'], C('first-seen order, not alphabetical'));
  assert.deepEqual(out.map((g) => ids(g.items)), [['a', 'c'], ['b', 'e'], ['d']], C('items keep input order'));
});

T('groupItems: items without a group share one group labelled "" or null', () => {
  const groupItems = need(ex, 'groupItems', 'EXPLORER', S);
  const items = [
    { id: 'a', label: 'A', group: 'Booth' },
    { id: 'b', label: 'B' },
    { id: 'c', label: 'C', group: 'Stage' },
    { id: 'd', label: 'D', group: '' },
    { id: 'e', label: 'E', group: null },
    { id: 'f', label: 'F', group: 'Booth' },
  ];
  const out = groupItems(items);
  const named = out.filter((g) => g.group !== '' && g.group !== null);
  const blank = out.filter((g) => g.group === '' || g.group === null);
  assert.deepEqual(named.map((g) => g.group), ['Booth', 'Stage'], C('named groups in first-seen order'));
  assert.deepEqual(named.map((g) => ids(g.items)), [['a', 'f'], ['c']], C('named group members'));
  assert.equal(blank.length, 1, C('exactly one ungrouped group'));
  assert.deepEqual(ids(blank[0].items), ['b', 'd', 'e'], C('missing, "" and null group land together in input order'));
  assert.equal(out.length, 3, C('no other groups'));

  const only = groupItems([{ id: 'x', label: 'X' }, { id: 'y', label: 'Y' }]);
  assert.equal(only.length, 1, C('all ungrouped: one group'));
  assert.equal(only[0].group, blank[0].group, C('ungrouped label is consistent across calls'));
  assert.deepEqual(ids(only[0].items), ['x', 'y'], C('all ungrouped items kept'));
});

T('groupItems of an empty list is empty', () => {
  const groupItems = need(ex, 'groupItems', 'EXPLORER', S);
  assert.deepEqual(groupItems([]), [], C('no groups'));
});

// nextIndex

T('nextIndex: ArrowDown / ArrowUp step by one', () => {
  const nextIndex = need(ex, 'nextIndex', 'EXPLORER', S);
  assert.equal(nextIndex(5, 0, 'ArrowDown'), 1, C('down from 0'));
  assert.equal(nextIndex(5, 2, 'ArrowDown'), 3, C('down from 2'));
  assert.equal(nextIndex(5, 3, 'ArrowUp'), 2, C('up from 3'));
  assert.equal(nextIndex(5, 4, 'ArrowUp'), 3, C('up from last'));
});

T('nextIndex wraps at both ends', () => {
  const nextIndex = need(ex, 'nextIndex', 'EXPLORER', S);
  assert.equal(nextIndex(5, 4, 'ArrowDown'), 0, C('down from last wraps to 0'));
  assert.equal(nextIndex(5, 0, 'ArrowUp'), 4, C('up from 0 wraps to last'));
  assert.equal(nextIndex(1, 0, 'ArrowDown'), 0, C('single item, down'));
  assert.equal(nextIndex(1, 0, 'ArrowUp'), 0, C('single item, up'));
});

T('nextIndex: Home and End', () => {
  const nextIndex = need(ex, 'nextIndex', 'EXPLORER', S);
  assert.equal(nextIndex(5, 3, 'Home'), 0, C('Home'));
  assert.equal(nextIndex(5, 1, 'End'), 4, C('End'));
  assert.equal(nextIndex(5, 0, 'Home'), 0, C('Home at 0'));
  assert.equal(nextIndex(5, 4, 'End'), 4, C('End at last'));
  assert.equal(nextIndex(5, -1, 'Home'), 0, C('Home with nothing active'));
  assert.equal(nextIndex(5, -1, 'End'), 4, C('End with nothing active'));
});

T('nextIndex: empty list gives -1, nothing active + ArrowDown gives 0', () => {
  const nextIndex = need(ex, 'nextIndex', 'EXPLORER', S);
  for (const key of ['ArrowDown', 'ArrowUp', 'Home', 'End']) {
    assert.equal(nextIndex(0, -1, key), -1, C(`count 0, ${key}`));
    assert.equal(nextIndex(0, 0, key), -1, C(`count 0, current 0, ${key}`));
  }
  assert.equal(nextIndex(5, -1, 'ArrowDown'), 0, C('current -1 + ArrowDown is 0'));
});

// explorerMode

T('explorerMode: drawer below 700, side at 700 and above (D3)', () => {
  const explorerMode = need(ex, 'explorerMode', 'EXPLORER', D3);
  for (const w of [0, 320, 390, 699, 699.5]) assert.equal(explorerMode(w), 'drawer', m('EXPLORER', D3, `width ${w} is drawer`));
  for (const w of [700, 744, 820, 1099, 1100, 1280, 2560]) assert.equal(explorerMode(w), 'side', m('EXPLORER', D3, `width ${w} is side`));
});
