// ENTITY unit tests for js/entity-core.js beyond tests/js/entity-contract.test.mjs (docs/ui-audit.md B.2 ENTITY).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadFixtureDoc, loadVocab, clone, device } from './fixtures/helpers.mjs';

const { mod, skip, error } = await loadModule('js/entity-core.js', 'ENTITY');
const T = (name, fn) => test(name, { skip: skip || false }, fn);
if (error) test('entity-core.js imports', () => { throw error; });

const fixture = loadFixtureDoc();
const vocab = loadVocab();
const fx = () => clone(fixture);
const byKey = (list, key) => list.find((x) => x.key === key);
const href = (view, id) => '#/campus/main/' + view + '/' + id;

T('entity-header.js imports in Node (no DOM at import)', async () => {
  const eh = await loadModule('js/entity-header.js', 'ENTITY');
  assert.equal(eh.error, null, String(eh.error));
  assert.equal(typeof eh.mod.mountEntityHeader, 'function');
});

T('deviceFacts: keys, labels and hrefs from opts.href', () => {
  const doc = fx();
  const facts = mod.deviceFacts(doc, vocab, device(doc, 'shure-wireless'), null, { href });
  assert.deepEqual(facts.map((f) => f.key), ['kind', 'status', 'room', 'rack', 'network', 'ports']);
  assert.equal(byKey(facts, 'kind').value, 'Audio \u00b7 Wireless receivers');
  assert.equal(byKey(facts, 'status').value, 'Installed');
  assert.equal(byKey(facts, 'room').href, '#/campus/main/rooms/main');
  assert.equal(byKey(facts, 'rack').href, '#/campus/main/racks/rk-foh');
  assert.equal(byKey(facts, 'network').href, undefined);
  for (const f of mod.deviceFacts(doc, vocab, device(doc, 'shure-wireless'), null)) assert.equal('href' in f, false, 'no opts → no href');
});

T('deviceFacts: kind without vocab, unknown room id, dante name only, no ports', () => {
  const doc = fx();
  const d = { id: 'x', name: 'X', kind: 'mystery', discipline: 'lighting', room: 'gone', dante_name: 'X-DANTE', ports: [] };
  doc.devices.push(d);
  const facts = mod.deviceFacts(doc, null, d, null);
  assert.equal(byKey(facts, 'kind').value, 'Lighting \u00b7 mystery');
  assert.equal(byKey(facts, 'room').value, 'gone', 'unknown room falls back to its id');
  assert.equal(byKey(facts, 'network').value, 'X-DANTE');
  assert.equal(byKey(facts, 'ports'), undefined, 'zero ports is omitted');
  assert.equal(byKey(facts, 'status'), undefined);
  assert.deepEqual(mod.deviceFacts(doc, vocab, null, null), []);
});

T('rackPosition: multi-U, rear face, top-down numbering, missing rack', () => {
  const doc = fx();
  const d = device(doc, 'sound-board');
  d.rack = { id: 'rk-foh', u: 3, height: 2, face: 'rear' };
  assert.equal(mod.rackPosition(doc, d), 'FOH rack \u00b7 U3\u20134 rear');
  doc.racks[0].numbering = 'top_down';
  d.rack = { id: 'rk-foh', u: 3, height: 2 };
  assert.equal(mod.rackPosition(doc, d), 'FOH rack \u00b7 U9\u201310', '12U top-down: U3–4 print as 10 and 9, low to high');
  d.rack = { id: 'rk-gone' };
  assert.equal(mod.rackPosition(doc, d), 'rk-gone');
  delete d.rack;
  assert.equal(mod.rackPosition(doc, d), '');
});

T('statusPill levels and tabLabel', () => {
  assert.deepEqual(mod.statusPill('installed'), { label: 'Installed', level: 'ok' });
  assert.deepEqual(mod.statusPill('planned'), { label: 'Planned', level: 'warn' });
  assert.deepEqual(mod.statusPill('spare'), { label: 'Spare', level: 'muted' });
  assert.deepEqual(mod.statusPill('Retired'), { label: 'Retired', level: 'muted' });
  assert.deepEqual(mod.statusPill('weird'), { label: 'Weird', level: 'muted' });
  assert.equal(mod.statusPill(''), null);
  assert.equal(mod.statusPill(undefined), null);
  assert.equal(mod.tabLabel('dmx'), 'DMX');
  assert.equal(mod.tabLabel('elevation'), 'Elevation');
  assert.equal(mod.tabLabel('custom'), 'Custom');
});

T('resolveTab: objects, no overview, empty list', () => {
  assert.deepEqual(mod.resolveTab([{ key: 'overview' }, { key: 'ports' }], 'ports'), { tab: 'ports', redirect: false });
  assert.deepEqual(mod.resolveTab(['front', 'rear'], 'side'), { tab: 'front', redirect: true }, 'no overview → first tab');
  assert.deepEqual(mod.resolveTab([], 'x'), { tab: 'overview', redirect: true });
  assert.deepEqual(mod.resolveTab(null, null), { tab: 'overview', redirect: true });
});

T('tab lists are fresh copies', () => {
  const a = mod.roomTabs();
  a.push('junk');
  assert.equal(mod.roomTabs().includes('junk'), false);
  const doc = fx();
  const t = mod.deviceTabs(doc, device(doc, 'atem-mini'));
  t.length = 0;
  assert.equal(mod.deviceTabs(doc, device(doc, 'atem-mini')).length, 7);
});

T('roomFacts: hrefs, missing venue, plans per room', () => {
  const doc = fx();
  doc.floorplans = [{ id: 'fp-a', room: 'main' }, { id: 'fp-b', room: 'other' }];
  const room = doc.rooms[0];
  let facts = mod.roomFacts(doc, room, { href });
  assert.deepEqual(facts.map((f) => f.key), ['venue', 'code', 'devices', 'racks', 'plans', 'cables']);
  assert.equal(byKey(facts, 'plans').value, '1');
  assert.equal(byKey(facts, 'devices').href, '#/campus/main/devices/main');
  delete room.venue;
  delete room.code;
  facts = mod.roomFacts(doc, room);
  assert.deepEqual(facts.map((f) => f.key), ['devices', 'racks', 'plans', 'cables']);
  assert.deepEqual(mod.roomFacts(doc, null), []);
});

T('rackFacts: side-by-side half-width share a U, out-of-range and auto devices', () => {
  const doc = fx();
  device(doc, 'spare-ulxd4d').rack = { id: 'rk-foh', u: 10, height: 1, side: 'right' };
  device(doc, 'sound-board').rack = { id: 'rk-foh', u: 12, height: 3 };
  device(doc, 'atem-mini').rack = { id: 'rk-foh', u: 5 };
  device(doc, 'atem-mini').auto = true;
  const facts = mod.rackFacts(doc, doc.racks[0], { href });
  assert.equal(byKey(facts, 'used').value, '2 U', 'U10 (two halves) + U12 (U13–14 are outside the 12U rack)');
  assert.equal(byKey(facts, 'free').value, '10 U');
  assert.equal(byKey(facts, 'devices').value, '3', 'auto devices are not listed');
  assert.equal(byKey(facts, 'room').href, '#/campus/main/rooms/main');
  assert.equal(byKey(facts, 'location').href, undefined);
});

T('summaryCards device: ports drill ids are port refs; files from attachments', () => {
  const doc = fx();
  doc.attachments = [{ id: 'att-1', name: 'manual.pdf', device: 'atem-mini' }, { id: 'att-2', name: 'x.pdf', device: 'other' }];
  const dev = device(doc, 'atem-mini');
  const cards = mod.summaryCards('device', doc, dev, {});
  assert.deepEqual(cards.map((c) => c.key), ['ports', 'cables', 'network', 'procedures', 'problems', 'files']);
  const ports = byKey(cards, 'ports');
  assert.deepEqual(ports.drill.ids, dev.ports.map((p) => 'atem-mini:' + p.id));
  assert.equal(ports.sub, '4 patched');
  assert.equal(byKey(cards, 'cables').drill.title, '4 cables \u00b7 ATEM Mini');
  assert.equal(byKey(cards, 'network').sub, '10.20.0.40');
  assert.equal(byKey(cards, 'network').drill, null);
  assert.deepEqual(byKey(cards, 'files').drill.ids, ['att-1']);
  assert.equal(byKey(cards, 'problems').tab, null, 'no problems tab on device pages');
});

T('summaryCards: resolved problems and archived pages do not count; body refs do', () => {
  const doc = fx();
  const dev = device(doc, 'atem-mini');
  const ctxInfo = {
    problems: [
      { id: 'pr-1', text: 'a', status: 'open', device: 'atem-mini' },
      { id: 'pr-2', text: 'b', status: 'resolved', device: 'atem-mini' },
      { id: 'pr-3', text: 'c', device: 'atem-mini' },
      { id: 'pr-4', text: 'd', status: 'open', room: 'main' },
    ],
    pages: [
      { id: 'pg-1', slug: 'one', devices: ['atem-mini'] },
      { id: 'pg-2', slug: 'two', status: 'archived', devices: ['atem-mini'] },
      { id: 'pg-3', slug: 'three', body: 'See [[device:atem-mini|the ATEM]] and [[room:main]].' },
      { id: 'pg-4', slug: 'four', rooms: ['main'] },
    ],
  };
  const d = mod.summaryCards('device', doc, dev, ctxInfo);
  assert.deepEqual(byKey(d, 'problems').drill.ids, ['pr-1', 'pr-3'], 'status defaults to open');
  assert.deepEqual(byKey(d, 'procedures').drill.ids, ['one', 'three']);
  const r = mod.summaryCards('room', doc, doc.rooms[0], ctxInfo);
  assert.deepEqual(byKey(r, 'problems').drill.ids, ['pr-1', 'pr-3', 'pr-4'], 'room problems: by room or by a device in the room');
  assert.deepEqual(byKey(r, 'procedures').drill.ids, ['three', 'four']);
  const k = mod.summaryCards('rack', doc, doc.racks[0], ctxInfo);
  assert.equal(byKey(k, 'problems').count, 0, 'atem-mini is not in rk-foh');
});

T('summaryCards: ctxInfo falls back to doc.pages and doc.problems', () => {
  const doc = fx();
  doc.pages = [{ id: 'pg-1', slug: 'one', devices: ['atem-mini'] }];
  doc.problems = [{ id: 'pr-1', text: 'a', status: 'open', device: 'atem-mini' }];
  const cards = mod.summaryCards('device', doc, device(doc, 'atem-mini'), null);
  assert.equal(byKey(cards, 'procedures').count, 1);
  assert.equal(byKey(cards, 'problems').count, 1);
  const empty = mod.summaryCards('device', doc, device(doc, 'atem-mini'), { problems: [], pages: [] });
  assert.equal(byKey(empty, 'procedures').count, 0, 'given lists win over the doc');
});

T('summaryCards rack: height, used and free cards go to the elevation tab', () => {
  const doc = fx();
  const cards = mod.summaryCards('rack', doc, doc.racks[0], {});
  assert.deepEqual(cards.map((c) => [c.key, c.count, c.tab]), [
    ['height', 12, 'elevation'], ['used', 1, 'elevation'], ['free', 11, 'elevation'],
    ['devices', 1, 'devices'], ['cables', 4, 'cables'], ['problems', 0, null],
  ]);
  assert.deepEqual(mod.summaryCards('rack', doc, null, {}), []);
  assert.deepEqual(mod.summaryCards('cable', doc, { id: 'c-0001' }, {}), [], 'unknown kind → no cards');
});

T('summaryCards room: plans and racks drill ids', () => {
  const doc = fx();
  doc.floorplans = [{ id: 'fp-a', room: 'main' }];
  const cards = mod.summaryCards('room', doc, doc.rooms[0], {});
  assert.deepEqual(cards.map((c) => c.key), ['devices', 'cables', 'racks', 'plans', 'procedures', 'problems']);
  assert.deepEqual(byKey(cards, 'racks').drill.ids, ['rk-foh']);
  assert.deepEqual(byKey(cards, 'plans').drill, { title: 'Floor plans \u00b7 Main Auditorium', kind: 'floorplan', ids: ['fp-a'] });
});
