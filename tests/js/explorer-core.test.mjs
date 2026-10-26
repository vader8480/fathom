// EXPLORER: unit tests for js/explorer-core.js beyond tests/js/explorer-contract.test.mjs
// (docs/ui-audit.md B.2 EXPLORER, D3, D8): helpers the DOM module relies on, edge cases and purity.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { loadModule, m, JS } from './fixtures/helpers.mjs';

const { mod: ex, skip, error } = await loadModule('js/explorer-core.js', 'EXPLORER');
const T = (name, fn) => test(name, { skip: skip || (error ? 'import failed' : false) }, fn);
const C = (text) => m('EXPLORER', 'B.2 EXPLORER', text);

if (error) test('explorer-core.js imports', () => { throw error; });

function memStorage(seed) {
  const data = new Map(Object.entries(seed || {}));
  return {
    data,
    getItem(k) { return data.has(k) ? data.get(k) : null; },
    setItem(k, v) { data.set(k, String(v)); },
  };
}

T('module is pure: no DOM, storage, network or timer globals', () => {
  const src = readFileSync(path.join(JS, 'explorer-core.js'), 'utf8').replace(/\/\/.*$/gm, '');
  for (const word of ['window', 'document', 'localStorage', 'sessionStorage', 'fetch(', 'setTimeout', 'setInterval', 'location']) {
    assert.equal(src.indexOf(word), -1, C(`no ${word}`));
  }
});

T('constants match the plan', () => {
  assert.equal(ex.MIN_WIDTH, 240);
  assert.equal(ex.MAX_WIDTH, 480);
  assert.equal(ex.DEFAULT_WIDTH, 300);
  assert.equal(ex.RAIL_WIDTH, 56, C('56px rail'));
  assert.equal(ex.KEY_STEP, 16, C('←/→ move 16px'));
  assert.equal(ex.storageKey('devices'), 'fathom.ui.explorer.devices');
  assert.equal(ex.storageKey('plan-unplaced'), 'fathom.ui.explorer.plan-unplaced');
});

T('clampWidth rounds fractions and rejects infinities', () => {
  assert.equal(ex.clampWidth(300.4), 300);
  assert.equal(ex.clampWidth(300.6), 301);
  assert.equal(ex.clampWidth(Infinity), 300);
  assert.equal(ex.clampWidth(-Infinity), 300);
});

T('saveExplorer coerces c to a boolean and reports success', () => {
  const s = memStorage();
  assert.equal(ex.saveExplorer(s, 'k', { w: 350, c: 'yes' }), true);
  assert.deepEqual(JSON.parse(s.getItem('fathom.ui.explorer.k')), { w: 350, c: false });
  assert.equal(ex.saveExplorer(s, 'k', null), true, C('missing state saves the default'));
  assert.deepEqual(JSON.parse(s.getItem('fathom.ui.explorer.k')), { w: 300, c: false });
  assert.equal(ex.saveExplorer(null, 'k', { w: 300 }), false);
  assert.equal(ex.saveExplorer({ setItem() { throw new Error('quota'); } }, 'k', { w: 300 }), false);
});

T('loadExplorer ignores a non-string storage value', () => {
  const st = ex.loadExplorer({ getItem() { return 42; } }, 'k');
  assert.deepEqual(st, { w: 300, c: false });
});

T('resizeKey: arrows step 16px, Home/End jump to bounds, other keys are null', () => {
  assert.equal(ex.resizeKey(300, 'ArrowRight'), 316);
  assert.equal(ex.resizeKey(300, 'ArrowLeft'), 284);
  assert.equal(ex.resizeKey(472, 'ArrowRight'), 480, C('clamped high'));
  assert.equal(ex.resizeKey(250, 'ArrowLeft'), 240, C('clamped low'));
  assert.equal(ex.resizeKey(300, 'Home'), 240);
  assert.equal(ex.resizeKey(300, 'End'), 480);
  assert.equal(ex.resizeKey(300, 'Enter'), null);
  assert.equal(ex.resizeKey(undefined, 'ArrowRight'), 316, C('bad width starts from the default'));
});

T('dragWidth follows the pointer and clamps', () => {
  assert.equal(ex.dragWidth(300, 500, 600), 400);
  assert.equal(ex.dragWidth(300, 500, 420), 240);
  assert.equal(ex.dragWidth(300, 500, 2000), 480);
  assert.equal(ex.dragWidth(300, 10, 10.6), 301);
});

T('filterItems accepts a Set of keys and ignores unknown chip keys', () => {
  const items = [{ id: 'a', label: 'A', k: 1 }, { id: 'b', label: 'B', k: 2 }];
  const chips = [{ key: 'one', test: (i) => i.k === 1 }];
  assert.deepEqual(ex.filterItems(items, '', new Set(['one']), chips).map((i) => i.id), ['a']);
  assert.deepEqual(ex.filterItems(items, '', ['nope'], chips).map((i) => i.id), ['a', 'b'], C('unknown key is no filter'));
  assert.deepEqual(ex.filterItems(items, '', null, null).map((i) => i.id), ['a', 'b']);
  assert.deepEqual(ex.filterItems(null, 'x', [], []), []);
});

T('filterItems trims the query and supports a custom match', () => {
  const items = [{ id: 'a', label: 'FOH CL5', ip: '10.0.0.5' }, { id: 'b', label: 'Rio', ip: '10.0.0.6' }];
  assert.deepEqual(ex.filterItems(items, '  cl5 ', [], []).map((i) => i.id), ['a']);
  const byIp = (it, q) => it.ip.indexOf(q) === 0;
  assert.deepEqual(ex.filterItems(items, '10.0.0.6', [], [], byIp).map((i) => i.id), ['b'], C('match replaces label + sub'));
  let calls = 0;
  ex.filterItems(items, '   ', [], [], () => { calls++; return false; });
  assert.equal(calls, 0, C('blank query never calls match'));
});

T('defaultMatch does not match across the label/sub boundary', () => {
  const it = { label: 'FOH CL5', sub: 'Yamaha' };
  assert.equal(ex.defaultMatch(it, 'cl5'), true);
  assert.equal(ex.defaultMatch(it, 'yama'), true);
  assert.equal(ex.defaultMatch(it, 'cl5 yamaha'), false);
  assert.equal(ex.defaultMatch({ label: 42 }, '4'), true, C('non-string labels'));
});

T('groupItems keeps a group named "0" apart from the ungrouped one', () => {
  const out = ex.groupItems([{ id: 'a', group: 0 }, { id: 'b' }, { id: 'c', group: '0' }]);
  assert.deepEqual(out.map((g) => g.group), ['0', '']);
  assert.deepEqual(out[0].items.map((i) => i.id), ['a', 'c']);
});

T('flattenGroups gives display (keyboard) order', () => {
  const groups = ex.groupItems([{ id: 'a', group: 'X' }, { id: 'b', group: 'Y' }, { id: 'c', group: 'X' }]);
  assert.deepEqual(ex.flattenGroups(groups).map((i) => i.id), ['a', 'c', 'b']);
  assert.deepEqual(ex.flattenGroups(null), []);
});

T('nextIndex: other keys keep the current index; out-of-range current restarts', () => {
  assert.equal(ex.nextIndex(5, 2, 'Enter'), 2);
  assert.equal(ex.nextIndex(5, -1, 'x'), -1);
  assert.equal(ex.nextIndex(3, 7, 'Enter'), 2, C('clamped to the last item'));
  assert.equal(ex.nextIndex(3, 7, 'ArrowDown'), 0);
  assert.equal(ex.nextIndex(3, 7, 'ArrowUp'), 2);
  assert.equal(ex.nextIndex(-2, 0, 'ArrowDown'), -1);
  assert.equal(ex.nextIndex(4, NaN, 'ArrowDown'), 0);
});

T('footerText uses the footer callback, else a count', () => {
  assert.equal(ex.footerText(3, 3), '3 items');
  assert.equal(ex.footerText(1, 1), '1 item');
  assert.equal(ex.footerText(2, 5), '2 of 5');
  assert.equal(ex.footerText(2, 5, (s, t) => s + '/' + t + ' devices'), '2/5 devices');
  assert.equal(ex.footerText(2, 5, () => null), '');
});

T('openLabel is "☰ <label> (<total>)"', () => {
  assert.equal(ex.openLabel('Devices', 40), '\u2630 Devices (40)');
  assert.equal(ex.openLabel('Unplaced', undefined), '\u2630 Unplaced (0)');
});
