// HOME: js/home-core.js against docs/ui-audit.md B.2 HOME, D2 and D8 (what home-contract.test.mjs does
// not cover: routes, robustness, archived pages, cross-room cables, recents input from the shell).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadFixtureDoc, clone, need } from './fixtures/helpers.mjs';

const { mod, skip: absent, error } = await loadModule('js/home-core.js', 'HOME');
const rc = await loadModule('js/router-core.js', 'ROUTER');
const skip = absent || (error ? 'home-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);
const fn = (name) => need(mod, name, 'HOME', 'docs/ui-audit.md B.2 HOME');

if (error) test('home-core.js imports in Node (D12 pure module)', () => { throw error; });

const fixture = loadFixtureDoc();

function twoRooms() {
  const d = clone(fixture);
  d.rooms.push({ id: 'lobby', venue: 'hillside', name: 'Lobby', code: 'LOB', kind: 'room' });
  d.devices.push({ id: 'lobby-tv', name: 'Lobby TV', kind: 'display', room: 'lobby', status: 'installed', ports: [] });
  d.cables.push({ id: 'c-x1', from: { device: 'video-converter', port: 'out-9' }, to: { device: 'lobby-tv', port: 'in-1' }, medium: 'sdi' });
  return d;
}

T('recentKey and countsText', () => {
  assert.equal(fn('recentKey')('campus-demo'), 'fathom.ui.recent.campus-demo');
  const countsText = fn('countsText');
  assert.equal(countsText(1, 1), '1 device \u00b7 1 cable');
  assert.equal(countsText(0, 2), '0 devices \u00b7 2 cables');
});

T('projectTitle: doc meta title, else project name', () => {
  const projectTitle = fn('projectTitle');
  assert.equal(projectTitle(fixture, 'sunday-demo'), 'Signal flow, mic to stream');
  assert.equal(projectTitle({ meta: {} }, 'annex'), 'annex');
  assert.equal(projectTitle(null, ''), 'Untitled project');
});

T('sectionCards: works with router-core sectionsFor for every role; skips empty sections', () => {
  const sectionCards = fn('sectionCards');
  for (const role of ['viewer', 'editor', 'admin']) {
    const secs = rc.mod.sectionsFor(role);
    const cards = sectionCards(secs);
    assert.deepEqual(cards.map((c) => c.key), secs.filter((s) => s.key !== 'home').map((s) => s.key));
    for (const c of cards) assert.ok(c.text.length > 10, `${c.key} has copy`);
  }
  assert.deepEqual(sectionCards([{ key: 'data', label: 'Data', glyph: 'x', views: [] }]), []);
  assert.deepEqual(sectionCards(null), []);
  assert.deepEqual(sectionCards([null, { key: 'home', views: ['home'] }]), []);
});

T('roomCards: a cable between two rooms counts in both; shared inventory is in no room', () => {
  const roomCards = fn('roomCards');
  const cards = roomCards(twoRooms(), {}, []);
  const main = cards.find((c) => c.id === 'main');
  const lobby = cards.find((c) => c.id === 'lobby');
  assert.equal(main.devices, 11);
  assert.equal(main.cables, 16);
  assert.equal(lobby.devices, 1);
  assert.equal(lobby.cables, 1);
  assert.equal(lobby.counts, '1 device \u00b7 1 cable');
  assert.equal(main.code, 'MAIN');
});

T('roomCards: archived pages and duplicate room ids do not make or double a SOPs link', () => {
  const roomCards = fn('roomCards');
  const pages = [
    { id: 'pg-1', slug: 'old', title: 'Old', status: 'archived', rooms: ['main'] },
    { id: 'pg-2', slug: 'dup', title: 'Dup', status: 'draft', rooms: ['lobby', 'lobby'] },
  ];
  const cards = roomCards(twoRooms(), {}, pages);
  assert.equal(cards.find((c) => c.id === 'main').links.filter((l) => l.view === 'sop').length, 0);
  assert.equal(cards.find((c) => c.id === 'lobby').links.filter((l) => l.view === 'sop').length, 1);
});

T('roomCards: room page link carries the room id; the rest have no id', () => {
  const roomCards = fn('roomCards');
  const main = roomCards(clone(fixture), {}, [])[0];
  assert.deepEqual(main.links.map((l) => [l.key, l.view, l.id]), [
    ['patch', 'patch', undefined], ['racks', 'racks', undefined], ['room', 'rooms', 'main'],
  ]);
});

T('roomCards: tolerates a missing doc, malformed recents, and does not mutate its input', () => {
  const roomCards = fn('roomCards');
  assert.deepEqual(roomCards(null, null, null), []);
  assert.deepEqual(roomCards({ rooms: [null, { name: 'no id' }] }, {}, []), []);
  const d = twoRooms();
  const before = JSON.stringify(d);
  const order = roomCards(d, { room: [null, 'lobby', { t: 5 }, { id: 'lobby', t: 1 }] }, []).map((c) => c.id);
  assert.deepEqual(order, ['lobby', 'main']);
  assert.equal(JSON.stringify(d), before);
  assert.deepEqual(roomCards(d, { room: 'main' }, []).map((c) => c.id), ['main', 'lobby']);
});

T('recentStrip: each entry has a route the shell can turn into an href', () => {
  const recentStrip = fn('recentStrip');
  const d = Object.assign(twoRooms(), { pages: [{ id: 'pg-1', slug: 'power-up', title: 'Power up', rooms: [] }] });
  const strip = recentStrip(d, {
    device: [{ id: 'lobby-tv', t: 9 }, { id: 'spare-ulxd4d', t: 3 }],
    room: [{ id: 'lobby', t: 8 }],
    rack: [{ id: 'rk-foh', t: 7 }],
    page: [{ id: 'pg-1', t: 6 }],
  });
  const route = (type, id) => strip.find((r) => r.type === type && r.id === id).route;
  assert.deepEqual(route('device', 'lobby-tv'), { view: 'devices', id: 'lobby-tv', query: {}, room: 'lobby' });
  assert.deepEqual(route('device', 'spare-ulxd4d'), { view: 'devices', id: 'spare-ulxd4d', query: {} }, 'shared inventory keeps the current room');
  assert.deepEqual(route('room', 'lobby'), { room: 'lobby', view: 'rooms', id: 'lobby', query: {} });
  assert.deepEqual(route('rack', 'rk-foh'), { view: 'racks', id: 'rk-foh', query: {}, room: 'main' });
  assert.deepEqual(route('page', 'pg-1'), { view: 'sop', query: { page: 'power-up' } }, 'pages open by slug, found by id or slug');
  assert.deepEqual(strip.map((r) => r.label), ['Device', 'Room', 'Rack', 'SOP', 'Device']);
  const build = rc.mod.buildRoute;
  const merge = rc.mod.mergeRoute;
  const cur = rc.mod.parseRoute('#/sunday-demo/main/home');
  assert.equal(build(merge(cur, route('page', 'pg-1'))), '#/sunday-demo/main/sop?page=power-up');
  assert.equal(build(merge(cur, route('device', 'lobby-tv'))), '#/sunday-demo/lobby/devices/lobby-tv');
});

T('recentStrip: duplicates, malformed entries and a missing doc are tolerated', () => {
  const recentStrip = fn('recentStrip');
  assert.deepEqual(recentStrip(null, { device: [{ id: 'x', t: 1 }] }), []);
  assert.deepEqual(recentStrip(clone(fixture), null), []);
  const strip = recentStrip(clone(fixture), {
    device: [{ id: 'atem-mini', t: 5 }, { id: 'atem-mini', t: 4 }, null, { t: 3 }, 'restream'],
    room: 'main',
    rack: { id: 'rk-foh' },
  });
  assert.deepEqual(strip.map((r) => [r.type, r.id]), [['device', 'atem-mini'], ['device', 'restream']]);
});

T('recentInput: shell id lists take times from storage; unknown times rank below', () => {
  const recentInput = fn('recentInput');
  const stored = { device: [{ id: 'a', t: 50 }, { id: 'b', t: 10 }], room: [{ id: 'r1', t: 40 }], rack: 'junk' };
  const out = recentInput({ device: ['b', 'c', 'a'], room: ['r1'], rack: [], page: [{ id: 'p1', t: 30 }] }, stored);
  assert.deepEqual(out.device, [{ id: 'b', t: 10 }, { id: 'c', t: -2 }, { id: 'a', t: 50 }]);
  assert.deepEqual(out.room, [{ id: 'r1', t: 40 }]);
  assert.deepEqual(out.rack, []);
  assert.deepEqual(out.page, [{ id: 'p1', t: 30 }]);
  const fromStore = recentInput(null, stored);
  assert.deepEqual(fromStore.device, [{ id: 'a', t: 50 }, { id: 'b', t: 10 }]);
  assert.deepEqual(fromStore.rack, []);
  assert.deepEqual(recentInput(null, 'corrupt'), { device: [], room: [], rack: [], page: [] });
});

T('recentInput feeds recentStrip: cross-type order follows the stored times', () => {
  const recentInput = fn('recentInput');
  const recentStrip = fn('recentStrip');
  const stored = { device: [{ id: 'atem-mini', t: 100 }, { id: 'restream', t: 10 }], room: [{ id: 'main', t: 50 }] };
  const input = recentInput({ device: ['atem-mini', 'restream'], room: ['main'], rack: [], page: [] }, stored);
  assert.deepEqual(recentStrip(clone(fixture), input).map((r) => r.id), ['atem-mini', 'main', 'restream']);
});

T('projectCards: title falls back to name, counts from listing numbers, nameless entries dropped', () => {
  const projectCards = fn('projectCards');
  const cards = projectCards([
    { name: 'campus', title: 'Campus', org: 'Hillside', rooms: 3, devices: 40, cables: 70 },
    { name: 'annex', rooms: 1, devices: 1 },
    { title: 'No name' },
    null,
  ], 'annex');
  assert.deepEqual(cards, [
    { name: 'campus', title: 'Campus', org: 'Hillside', counts: '3 rooms \u00b7 40 devices', current: false },
    { name: 'annex', title: 'annex', org: '', counts: '1 room \u00b7 1 device', current: true },
  ]);
  assert.deepEqual(projectCards(null, 'x'), []);
  assert.equal(projectCards([{ name: 'a' }], '')[0].current, false);
});

T('home-core.js is pure: no DOM, window, storage, fetch or timers', async () => {
  const { readFileSync } = await import('node:fs');
  const { JS } = await import('./fixtures/helpers.mjs');
  const src = readFileSync(JS + '/home-core.js', 'utf8').replace(/\/\/.*$/gm, '');
  for (const word of ['document', 'window', 'localStorage', 'sessionStorage', 'fetch(', 'setTimeout', 'setInterval', 'Date.now']) {
    assert.ok(src.indexOf(word) < 0, `home-core.js mentions ${word}`);
  }
});
