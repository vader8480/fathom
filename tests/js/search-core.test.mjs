// Unit tests for js/search-core.js beyond tests/js/search-contract.test.mjs:
// category stamping, route hygiene of targets, ctx.recent-shaped recents,
// edge cases and campus-demo vectors (docs/ui-audit.md B.2 SEARCH).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { loadModule, loadFixtureDoc, readJson, clone, ROOT } from './fixtures/helpers.mjs';

const { mod: sc, skip } = await loadModule('js/search-core.js', 'SEARCH');
const { mod: rc } = await loadModule('js/router-core.js', 'ROUTER');
const T = (name, fn) => test(name, { skip }, fn);

const fixture = loadFixtureDoc();
const campus = readJson(path.join(ROOT, 'fathom', 'samples', 'campus-demo', 'project.json'));
const ROUTE = { project: 'demo', room: 'chapel', view: 'patch', id: '', tab: '', sub: '', extra: [], query: { sel: 'device:x', filter: 'audio' } };
const key = (h) => h.kind + ':' + h.id;
const hit = (kind, id, extra) => Object.assign({ kind, id, device: null, port: null, title: id, subtitle: '', room: null, score: 60, match: 'name' }, extra);

T('kindsFor returns a copy; unknown and all mean no filter', () => {
  const k = sc.kindsFor('networks');
  k.push('cable');
  assert.deepEqual(sc.kindsFor('networks'), ['network', 'interface']);
  assert.equal(sc.kindsFor('all'), null);
  assert.equal(sc.kindsFor('nope'), null);
  assert.equal(sc.kindsFor(undefined), null);
});

T('categorize honours a stamped category and falls back for unknown kinds', () => {
  assert.equal(sc.categorize(hit('device', 'a', { category: 'inventory' })), 'inventory');
  assert.equal(sc.categorize(hit('device', 'a', { match: 'serial', category: 'devices' })), 'devices');
  assert.equal(sc.categorize(hit('device', 'a', { category: 'all' })), 'devices', 'all is not a category of its own');
  assert.equal(sc.categorize(hit('device', 'a', { category: 'bogus' })), 'devices');
  assert.equal(sc.categorize(hit('widget', 'a')), 'all');
  assert.equal(sc.categorize(null), 'all');
});

T('groupHits stamps category on copies and never mutates its input', () => {
  const hits = [hit('device', 'a', { match: 'serial' }), hit('device', 'b'), hit('cable', 'c')];
  const before = clone(hits);
  const groups = sc.groupHits(hits, 'all');
  assert.deepEqual(groups.map((g) => [g.key, g.label, typeof g.glyph, g.hits.map((x) => x.category)]),
    [['devices', 'Devices', 'string', ['devices']], ['inventory', 'Inventory', 'string', ['inventory']], ['cables', 'Cables', 'string', ['cables']]]);
  assert.deepEqual(hits, before);
});

T('groupHits(single) keeps only that category kinds; unknown category groups like all', () => {
  const hits = [hit('device', 'a'), hit('cable', 'c'), hit('interface', 'a/i', { device: 'a' }), hit('network', 'n')];
  assert.deepEqual(sc.groupHits(hits, 'cables').map((g) => g.hits.map(key)), [['cable:c']]);
  assert.deepEqual(sc.groupHits(hits, 'networks').map((g) => g.hits.map(key)), [['interface:a/i', 'network:n']]);
  assert.deepEqual(sc.groupHits(hits, 'rooms'), []);
  assert.deepEqual(sc.groupHits(hits, 'nope').map((g) => g.key), sc.groupHits(hits, 'all').map((g) => g.key));
  assert.deepEqual(sc.groupHits(null, 'all'), []);
});

T('a device listed under Devices opens its page, under Inventory the inventory drawer', () => {
  const serial = hit('device', 'sound-board', { device: 'sound-board', match: 'serial' });
  const named = hit('device', 'atem-mini', { device: 'atem-mini', match: 'name' });
  const asDevice = sc.groupHits([serial], 'devices')[0].hits[0];
  assert.equal(sc.targetFor(asDevice, ROUTE, fixture).view, 'devices');
  const asInv = sc.groupHits([named], 'inventory')[0].hits[0];
  assert.deepEqual(sc.targetFor(asInv, ROUTE, fixture).query, { sel: 'device:atem-mini', sec: 'inventory' });
});

T('targets reset id/tab/sub and the query, so nothing leaks from the current route', () => {
  const from = { project: 'demo', room: 'main', view: 'devices', id: 'sound-board', tab: 'ports', sub: 'x', extra: [], query: { sel: 'port:sound-board:in-1', sec: 'ports' } };
  const dev = sc.targetFor(hit('device', 'atem-mini', { device: 'atem-mini' }), from, fixture);
  const r = rc.mergeRoute(from, dev);
  assert.deepEqual([r.view, r.id, r.tab, r.sub, r.query], ['devices', 'atem-mini', '', '', {}]);
  assert.equal(rc.buildRoute(r), '#/demo/main/devices/atem-mini');
  const cab = rc.mergeRoute(ROUTE, sc.targetFor(hit('cable', 'c-0005'), ROUTE, fixture));
  assert.equal(rc.buildRoute(cab), '#/demo/chapel/schedules/cables?sel=cable:c-0005');
  const page = rc.mergeRoute(ROUTE, sc.targetFor(hit('page', 'power-up'), ROUTE, fixture));
  assert.equal(rc.buildRoute(page), '#/demo/chapel/sop?page=power-up');
});

T('targetFor edge cases', () => {
  assert.equal(sc.targetFor(null, ROUTE, fixture), null);
  assert.equal(sc.targetFor(hit('widget', 'x'), ROUTE, fixture), null);
  const iface = sc.targetFor(hit('interface', 'odd-id', { device: 'atem-mini' }), ROUTE, fixture);
  assert.equal(iface.query.hl, 'odd-id', 'an interface id without the device prefix is used as is');
  const ghost = sc.targetFor(hit('device', 'ghost', { device: 'ghost', room: 'main' }), ROUTE, fixture);
  assert.equal(ghost.room, 'chapel', 'device not in the doc keeps route.room');
  const noRoute = sc.targetFor(hit('device', 'spare-ulxd4d', { device: 'spare-ulxd4d' }), null, null);
  assert.equal(noRoute.room, '');
});

T('augmentLocal network hits: subtitle, status, kind order after interface', () => {
  const d = clone(fixture);
  d.networks.push({ id: 'flag', name: 'Flag net', vlan: true, subnet: '' });
  const [lan] = sc.augmentLocal(d, 'av-lan', 10).filter((x) => x.kind === 'network');
  assert.equal(lan.subtitle, 'VLAN 20 \u00b7 10.20.0.0/24');
  assert.deepEqual([lan.device, lan.port, lan.room, lan.status, lan.match], [null, null, '', '', 'id']);
  const flag = sc.augmentLocal(d, 'Flag net', 10).find((x) => x.id === 'flag');
  assert.equal(flag.subtitle, '', 'boolean vlan and empty subnet are not shown');
  for (const x of sc.augmentLocal(d, 'a', 200)) assert.equal(typeof x.status, 'string', key(x));
  const tie = sc.augmentLocal({ devices: [{ id: 'd', name: 'D', interfaces: [{ id: 'i', hostname: 'core' }] }], networks: [{ id: 'n', name: 'core' }] }, 'core', 10);
  assert.deepEqual(tie.map(key), ['interface:d/i', 'network:n']);
  assert.deepEqual(sc.augmentLocal(null, 'x', 10), []);
  assert.ok(sc.augmentLocal(d, 'a').length <= 20, 'default limit 20');
});

T('mergeHits dedupes inside a and skips holes', () => {
  const a = [hit('room', 'main'), hit('room', 'main', { score: 1 }), null];
  assert.deepEqual(sc.mergeHits(a, [hit('room', 'main'), hit('rack', 'r')]).map(key), ['room:main', 'rack:r']);
  assert.equal(sc.mergeHits(a, null)[0].score, 60, 'first occurrence wins');
  assert.deepEqual(sc.mergeHits(undefined, undefined), []);
});

T('roleFilter tolerates bad input and returns a new array', () => {
  assert.deepEqual(sc.roleFilter(null, 'viewer'), []);
  const hits = [hit('page', 'p', { status: 'published' })];
  assert.notEqual(sc.roleFilter(hits, 'admin'), hits);
});

T('recentHits works with a ctx.recent that only has list(type)', () => {
  const recent = { push() {}, list: (t) => ({ device: ['atem-mini', 'ghost'], rack: ['rk-foh'] }[t] || []) };
  assert.deepEqual(sc.recentHits(fixture, recent).map(key), ['device:atem-mini', 'rack:rk-foh']);
  const broken = { list() { throw new Error('storage'); } };
  assert.deepEqual(sc.recentHits(fixture, broken), []);
  assert.deepEqual(sc.recentHits(null, recent), []);
  assert.deepEqual(sc.recentHits(fixture, null), []);
});

T('recentHits orders across types by time, resolves page ids to slugs and dedupes', () => {
  const d = clone(fixture);
  d.pages = [{ id: 'pg-1', slug: 'power-up', title: 'Power up', status: 'draft', kind: 'sop' }];
  const out = sc.recentHits(d, {
    device: [{ id: 'atem-mini', t: 10 }, { id: 'atem-mini', t: 5 }],
    room: [{ id: 'main', t: 30 }],
    page: [{ id: 'pg-1', t: 20 }],
  });
  assert.deepEqual(out.map(key), ['room:main', 'page:power-up', 'device:atem-mini']);
  const page = out[1];
  assert.deepEqual([page.status, page.subtitle], ['draft', 'sop']);
  assert.deepEqual(sc.roleFilter(out, 'viewer').map(key), ['room:main', 'device:atem-mini'], 'draft recents are hidden from viewers');
  const dev = out[2];
  assert.deepEqual([dev.device, dev.room, dev.status], ['atem-mini', 'main', 'installed']);
});

T('recentType: only devices, rooms, racks and pages are remembered', () => {
  assert.deepEqual(['device', 'room', 'rack', 'page', 'port', 'cable', 'network', 'section'].map((k) => sc.recentType(hit(k, 'x'))),
    ['device', 'room', 'rack', 'page', '', '', '', '']);
  assert.equal(sc.recentType(null), '');
});

T('moveActive: out-of-range index, larger and zero deltas', () => {
  assert.equal(sc.moveActive(3, 7, 1), 0);
  assert.equal(sc.moveActive(3, 7, -1), 2);
  assert.equal(sc.moveActive(4, 1, 0), 1);
  assert.equal(sc.moveActive(4, 1, 5), 2);
  assert.equal(sc.moveActive(4, 1, -6), 3);
  assert.equal(sc.moveActive(undefined, 0, 1), -1);
});

T('noMatchText names the category except for all', () => {
  assert.equal(sc.noMatchText(' x ', 'cables'), 'No matches for \u201cx\u201d in Cables.');
  assert.equal(sc.noMatchText('x', 'all'), 'No matches for \u201cx\u201d.');
  assert.equal(sc.noMatchText('x'), 'No matches for \u201cx\u201d.');
});

T('campus-demo vectors: foh, chapel, A-001, RC-0001, IP and VLAN', () => {
  const top = (q) => sc.augmentLocal(campus, q, 40)[0];
  const route = { project: 'campus-demo', room: 'main', view: 'home', id: '', tab: '', sub: '', extra: [], query: {} };
  const foh = top('foh');
  assert.equal(key(foh), 'device:foh-cl5');
  assert.equal(rc.buildRoute(rc.mergeRoute(route, sc.targetFor(foh, route, campus))), '#/campus-demo/main/devices/foh-cl5');
  const chapel = top('chapel');
  assert.equal(key(chapel), 'room:chapel');
  assert.equal(rc.buildRoute(rc.mergeRoute(route, sc.targetFor(chapel, route, campus))), '#/campus-demo/chapel/rooms/chapel');
  assert.equal(key(top('A-001')), 'cable:c-0009');
  const groups = sc.groupHits(sc.augmentLocal(campus, 'RC-0001', 40), 'all');
  const inv = groups.find((g) => g.key === 'inventory');
  assert.ok(inv && inv.hits[0].id === 'foh-cl5', 'RC-0001 lands in the Inventory group');
  assert.equal(rc.buildRoute(rc.mergeRoute(route, sc.targetFor(inv.hits[0], route, campus))),
    '#/campus-demo/main/inventory?sel=device:foh-cl5&sec=inventory');
  const ip = top('10.20.0.10');
  assert.equal(rc.buildRoute(rc.mergeRoute(route, sc.targetFor(ip, route, campus))), '#/campus-demo/main/devices/foh-cl5/network?hl=primary');
  const vlan = top('20');
  assert.equal(key(vlan), 'network:av-dante');
  assert.equal(rc.buildRoute(rc.mergeRoute(route, sc.targetFor(vlan, route, campus))), '#/campus-demo/main/settings/networks?hl=av-dante');
  assert.equal(key(top('atem')), 'device:switcher', 'campus-demo ranks the switcher (code ATEM) first');
});
