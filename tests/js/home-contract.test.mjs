// T-HOME contract test: js/home-core.js against docs/ui-audit.md B.2 HOME (Core), D2 (SECTIONS) and
// D8 (`fathom.ui.recent.<project>`). Written from the document alone; the unit's own tests live in
// tests/js/home-core.test.mjs.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadFixtureDoc, clone, need } from './fixtures/helpers.mjs';

const { mod, skip: absent, error } = await loadModule('js/home-core.js', 'HOME');
const skip = absent || (error ? 'home-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);
const FR = 'HOME';
const S = 'ui-audit B.2 HOME';

if (error) test('home-core.js imports in Node (pure module)', () => { throw error; });

// D2 SECTIONS table, in table order.
const SECTIONS = [
  { key: 'home', label: 'Home', glyph: '\u2302', views: ['home'] },
  { key: 'patch', label: 'Patch', glyph: '\u2B95', views: ['patch', 'table', 'map'] },
  { key: 'rooms', label: 'Rooms', glyph: '\u25A3', views: ['rooms', 'plan', 'racks'] },
  { key: 'devices', label: 'Devices', glyph: '\u25EB', views: ['devices', 'inventory'] },
  { key: 'schedules', label: 'Schedules', glyph: '\u2630', views: ['schedules', 'builds'] },
  { key: 'sop', label: 'SOPs', glyph: '\u2611', views: ['sop'] },
  { key: 'data', label: 'Data', glyph: '\u21C5', views: ['imports', 'discovery', 'history', 'json'] },
  { key: 'settings', label: 'Settings', glyph: '\u2699\uFE0E', views: ['settings'] },
];

// B.2 HOME item 3.
const COPY = {
  patch: 'Wire devices port to port and trace signal paths.',
  rooms: 'Floor plans, racks and room overviews.',
  devices: 'Every device, its ports, network and inventory record.',
  schedules: 'Cable, IP, DMX and parts lists, and printable builds.',
  sop: 'Step-by-step procedures for volunteers.',
  data: 'Imports, network discovery, history and raw JSON.',
  settings: 'Project, rooms, systems, networks, users and sharing.',
};

// Fixture: room `main` has 11 devices (spare-ulxd4d is shared inventory, room ""), 15 cables between
// them, the rack rk-foh and no floor plans. Added: `overflow` (2 devices, 3 cables between them, one
// floor plan, no racks) and `youth` (empty). Doc order main, overflow, youth is also name order.
const fixture = loadFixtureDoc();
function port(id, dir) {
  return { id, name: id, dir, medium: 'analog', connector: 'xlr' };
}
function buildDoc() {
  const d = clone(fixture);
  d.rooms.push({ id: 'overflow', venue: 'hillside', name: 'Overflow Room', code: 'OVF', kind: 'room' });
  d.rooms.push({ id: 'youth', venue: 'hillside', name: 'Youth Room', code: 'YTH', kind: 'room' });
  d.devices.push({
    id: 'ov-mixer', name: 'Overflow Mixer', kind: 'console', room: 'overflow', status: 'installed',
    ports: [port('in-1', 'in'), port('in-2', 'in'), port('out-1', 'out')],
  });
  d.devices.push({
    id: 'ov-speaker', name: 'Overflow Speaker', kind: 'speaker', room: 'overflow', status: 'installed',
    ports: [port('in-1', 'in'), port('out-1', 'out'), port('out-2', 'out')],
  });
  d.cables.push({ id: 'c-0101', from: { device: 'ov-mixer', port: 'out-1' }, to: { device: 'ov-speaker', port: 'in-1' }, medium: 'analog' });
  d.cables.push({ id: 'c-0102', from: { device: 'ov-speaker', port: 'out-1' }, to: { device: 'ov-mixer', port: 'in-1' }, medium: 'analog' });
  d.cables.push({ id: 'c-0103', from: { device: 'ov-speaker', port: 'out-2' }, to: { device: 'ov-mixer', port: 'in-2' }, medium: 'analog' });
  d.floorplans.push({
    id: 'fp-overflow', name: 'Overflow floor', room: 'overflow',
    source: { attachment: 'att-fp1', kind: 'png', page: 1 },
    image: { attachment: 'att-fp1', kind: 'png', width: 1000, height: 600 },
    markers: [],
  });
  return d;
}

const PAGE = {
  id: 'pg-1a2b3c4d', slug: 'power-up', title: 'Power up the overflow room', kind: 'sop',
  status: 'published', rooms: ['overflow'], devices: [], tags: [],
};
const PAGES = [
  PAGE,
  { id: 'pg-5e6f7a8b', slug: 'mic-check', title: 'Mic check', kind: 'checklist', status: 'published', rooms: [], devices: ['wireless-mics'], tags: [] },
];
const docWithPages = () => Object.assign(buildDoc(), { pages: clone(PAGES) });

const LINK_ORDER = ['patch', 'plan', 'racks', 'sop', 'rooms'];
const byView = (card, view) => (card.links || []).filter((l) => l.view === view);
const roomPageLink = (card) => (card.links || []).find((l) => l.view === 'rooms' && l.id === card.id);
const cardOf = (cards, id) => {
  const c = cards.find((x) => x.id === id);
  assert.ok(c, `${FR} (${S}): room card for ${id}`);
  return c;
};

// ---------------------------------------------------------------- sectionCards

T('sectionCards: one card per section except home, in section order', () => {
  const sectionCards = need(mod, 'sectionCards', FR, S);
  const input = clone(SECTIONS);
  const cards = sectionCards(input);
  assert.ok(Array.isArray(cards));
  assert.deepEqual(cards.map((c) => c.key), SECTIONS.filter((s) => s.key !== 'home').map((s) => s.key));
  assert.deepEqual(input, SECTIONS, 'input sections are not mutated');
});

T('sectionCards: label, glyph, first view and one-line copy', () => {
  const sectionCards = need(mod, 'sectionCards', FR, S);
  const cards = sectionCards(clone(SECTIONS));
  for (const s of SECTIONS.filter((x) => x.key !== 'home')) {
    const c = cards.find((x) => x.key === s.key);
    assert.ok(c, `card for ${s.key}`);
    assert.equal(c.label, s.label, `${s.key} label`);
    assert.equal(c.glyph, s.glyph, `${s.key} glyph`);
    assert.equal(c.view, s.views[0], `${s.key} view = first view of the section`);
    assert.equal(typeof c.text, 'string');
  }
  assert.equal(cards.find((c) => c.key === 'patch').text, 'Wire devices port to port and trace signal paths.');
  assert.equal(cards.find((c) => c.key === 'devices').text, 'Every device, its ports, network and inventory record.');
  for (const [key, text] of Object.entries(COPY)) {
    assert.equal(cards.find((c) => c.key === key).text, text, `${key} copy`);
  }
});

T('sectionCards: follows the (role-filtered) sections it is given', () => {
  const sectionCards = need(mod, 'sectionCards', FR, S);
  const subset = clone(SECTIONS).filter((s) => s.key !== 'settings' && s.key !== 'data');
  assert.deepEqual(sectionCards(subset).map((c) => c.key), ['patch', 'rooms', 'devices', 'schedules', 'sop']);
  assert.deepEqual(sectionCards([clone(SECTIONS[0])]), []);
});

// ---------------------------------------------------------------- roomCards

T('roomCards: one card per room with id, name and counts', () => {
  const roomCards = need(mod, 'roomCards', FR, S);
  const cards = roomCards(buildDoc(), {}, []);
  assert.ok(Array.isArray(cards));
  assert.deepEqual(cards.map((c) => c.id).sort(), ['main', 'overflow', 'youth']);
  assert.equal(cardOf(cards, 'main').name, 'Main Auditorium');
  assert.equal(cardOf(cards, 'overflow').name, 'Overflow Room');
  const ov = cardOf(cards, 'overflow').counts;
  assert.equal(typeof ov, 'string', 'counts is display text');
  assert.match(ov, /\b2 devices\b[\s\S]*\b3 cables\b/, `overflow counts "${ov}" ~ "2 devices · 3 cables"`);
  const mn = cardOf(cards, 'main').counts;
  assert.match(mn, /\b11 devices\b[\s\S]*\b15 cables\b/, `main counts "${mn}" ~ "11 devices · 15 cables" (shared inventory excluded)`);
});

T('roomCards: Patch and room page links are always present', () => {
  const roomCards = need(mod, 'roomCards', FR, S);
  for (const c of roomCards(buildDoc(), {}, [])) {
    assert.ok(Array.isArray(c.links), `${c.id} links`);
    const patch = byView(c, 'patch');
    assert.equal(patch.length, 1, `${c.id}: one Patch link`);
    assert.equal(patch[0].label, 'Patch');
    assert.ok(roomPageLink(c), `${c.id}: room page link {view: 'rooms', id: '${c.id}'}`);
    for (const l of c.links) {
      assert.equal(typeof l.key, 'string', `${c.id}: link key`);
      assert.ok(l.key, `${c.id}: link key non-empty`);
      assert.equal(typeof l.label, 'string', `${c.id}: link label`);
      assert.equal(typeof l.view, 'string', `${c.id}: link view`);
    }
    const keys = c.links.map((l) => l.key);
    assert.equal(new Set(keys).size, keys.length, `${c.id}: link keys unique`);
  }
});

T('roomCards: Racks link only for a room with racks', () => {
  const roomCards = need(mod, 'roomCards', FR, S);
  const cards = roomCards(buildDoc(), {}, []);
  const racks = byView(cardOf(cards, 'main'), 'racks');
  assert.equal(racks.length, 1, 'main has rk-foh → Racks link');
  assert.equal(racks[0].label, 'Racks');
  assert.equal(byView(cardOf(cards, 'overflow'), 'racks').length, 0, 'overflow has no racks');
  assert.equal(byView(cardOf(cards, 'youth'), 'racks').length, 0, 'youth has no racks');
  const d = buildDoc();
  d.racks.push({ id: 'rk-ovf', name: 'Overflow rack', room: 'overflow', units: 8, numbering: 'bottom_up', faces: ['front'] });
  assert.equal(byView(cardOf(roomCards(d, {}, []), 'overflow'), 'racks').length, 1, 'adding a rack adds the link');
});

T('roomCards: Plan link only for a room with floor plans', () => {
  const roomCards = need(mod, 'roomCards', FR, S);
  const cards = roomCards(buildDoc(), {}, []);
  const plan = byView(cardOf(cards, 'overflow'), 'plan');
  assert.equal(plan.length, 1, 'overflow has fp-overflow → Plan link');
  assert.equal(plan[0].label, 'Plan');
  assert.equal(byView(cardOf(cards, 'main'), 'plan').length, 0, 'main has no floor plans');
  assert.equal(byView(cardOf(cards, 'youth'), 'plan').length, 0, 'youth has no floor plans');
});

T('roomCards: SOPs link only when pages apply to the room', () => {
  const roomCards = need(mod, 'roomCards', FR, S);
  const cards = roomCards(buildDoc(), {}, clone(PAGES));
  const sop = byView(cardOf(cards, 'overflow'), 'sop');
  assert.equal(sop.length, 1, 'power-up applies to overflow → SOPs link');
  assert.equal(sop[0].label, 'SOPs');
  assert.equal(byView(cardOf(cards, 'main'), 'sop').length, 0, 'no page lists main in rooms');
  assert.equal(byView(cardOf(cards, 'youth'), 'sop').length, 0, 'no page lists youth in rooms');
  for (const c of roomCards(buildDoc(), {}, [])) {
    assert.equal(byView(c, 'sop').length, 0, `${c.id}: no pages → no SOPs link`);
  }
});

T('roomCards: an empty room has only Patch and room page links', () => {
  const roomCards = need(mod, 'roomCards', FR, S);
  const youth = cardOf(roomCards(buildDoc(), {}, clone(PAGES)), 'youth');
  assert.deepEqual(youth.links.map((l) => l.view).sort(), ['patch', 'rooms']);
});

T('roomCards: link chips follow the contract order Patch, Plan, Racks, SOPs, room page', () => {
  const roomCards = need(mod, 'roomCards', FR, S);
  const d = buildDoc();
  d.racks.push({ id: 'rk-ovf', name: 'Overflow rack', room: 'overflow', units: 8, numbering: 'bottom_up', faces: ['front'] });
  const ov = cardOf(roomCards(d, {}, clone(PAGES)), 'overflow');
  assert.deepEqual(ov.links.map((l) => l.view), LINK_ORDER);
});

T('roomCards: rooms in recents come first, newest first; the rest keep doc order', () => {
  const roomCards = need(mod, 'roomCards', FR, S);
  assert.deepEqual(roomCards(buildDoc(), {}, []).map((c) => c.id), ['main', 'overflow', 'youth']);
  const recent = { device: [], room: [{ id: 'youth', t: 300 }, { id: 'ghost-room', t: 250 }, { id: 'overflow', t: 200 }], rack: [], page: [] };
  assert.deepEqual(roomCards(buildDoc(), recent, []).map((c) => c.id), ['youth', 'overflow', 'main'], 'unknown recent ids add no card');
  const one = { room: [{ id: 'overflow', t: 10 }] };
  assert.deepEqual(roomCards(buildDoc(), one, []).map((c) => c.id), ['overflow', 'main', 'youth']);
});

// ---------------------------------------------------------------- recentStrip

T('recentStrip: empty or missing recents give an empty strip', () => {
  const recentStrip = need(mod, 'recentStrip', FR, S);
  assert.deepEqual(recentStrip(docWithPages(), { device: [], room: [], rack: [], page: [] }), []);
  assert.deepEqual(recentStrip(docWithPages(), {}), []);
});

T('recentStrip: merged across types by t descending, with type, id and title', () => {
  const recentStrip = need(mod, 'recentStrip', FR, S);
  const recent = {
    device: [{ id: 'atem-mini', t: 600 }, { id: 'sound-board', t: 300 }],
    room: [{ id: 'overflow', t: 500 }],
    rack: [{ id: 'rk-foh', t: 400 }],
    page: [{ id: 'power-up', t: 200 }],
  };
  const strip = recentStrip(docWithPages(), recent);
  assert.deepEqual(strip.map((r) => [r.type, r.id]), [
    ['device', 'atem-mini'], ['room', 'overflow'], ['rack', 'rk-foh'], ['device', 'sound-board'], ['page', 'power-up'],
  ]);
  const title = (type, id) => strip.find((r) => r.type === type && r.id === id).title;
  assert.equal(title('device', 'atem-mini'), fixture.devices.find((x) => x.id === 'atem-mini').name);
  assert.equal(title('room', 'overflow'), 'Overflow Room');
  assert.equal(title('rack', 'rk-foh'), 'FOH rack');
  assert.equal(title('page', 'power-up'), PAGE.title);
  for (const r of strip) if (r.href !== undefined) assert.equal(typeof r.href, 'string', 'href is a string when present');
});

T('recentStrip: unknown ids are dropped, per type', () => {
  const recentStrip = need(mod, 'recentStrip', FR, S);
  const recent = {
    device: [{ id: 'ghost-dev', t: 90 }, { id: 'main', t: 80 }, { id: 'restream', t: 10 }],
    room: [{ id: 'atem-mini', t: 70 }, { id: 'main', t: 20 }],
    rack: [{ id: 'rk-missing', t: 60 }],
    page: [{ id: 'gone-page', t: 50 }, { id: 'power-up', t: 30 }],
  };
  assert.deepEqual(recentStrip(docWithPages(), recent).map((r) => [r.type, r.id]), [
    ['page', 'power-up'], ['room', 'main'], ['device', 'restream'],
  ]);
});

T('recentStrip: at most 8 entries, the newest known ones', () => {
  const recentStrip = need(mod, 'recentStrip', FR, S);
  const recent = {
    device: [
      { id: 'atem-mini', t: 1000 }, { id: 'ghost-dev', t: 950 }, { id: 'sound-board', t: 500 }, { id: 'shure-wireless', t: 300 },
      { id: 'stage-box-1', t: 200 }, { id: 'ov-mixer', t: 150 }, { id: 'restream', t: 100 },
    ],
    room: [{ id: 'overflow', t: 900 }, { id: 'main', t: 400 }, { id: 'nowhere', t: 350 }],
    rack: [{ id: 'rk-missing', t: 990 }, { id: 'rk-foh', t: 800 }],
    page: [{ id: 'power-up', t: 700 }, { id: 'gone-page', t: 650 }],
  };
  const strip = recentStrip(docWithPages(), recent);
  assert.deepEqual(strip.map((r) => [r.type, r.id]), [
    ['device', 'atem-mini'], ['room', 'overflow'], ['rack', 'rk-foh'], ['page', 'power-up'],
    ['device', 'sound-board'], ['room', 'main'], ['device', 'shure-wireless'], ['device', 'stage-box-1'],
  ], 'unknown ids do not take a slot; capped at 8');
});

// ---------------------------------------------------------------- projectCards

const PROJECTS = [
  { name: 'campus', org: 'Hillside Church', title: 'Campus', schema: 2, revision: 12, rooms: 3, devices: 40, cables: 70 },
  { name: 'sunday-demo', org: 'Hillside Church', title: 'Signal flow, mic to stream', schema: 2, revision: 1, rooms: 1, devices: 12, cables: 15 },
  { name: 'annex', org: '', title: 'Annex', schema: 2, revision: 3, rooms: 1, devices: 4, cables: 2 },
];

T('projectCards: one card per project, current flagged on the matching name', () => {
  const projectCards = need(mod, 'projectCards', FR, S);
  const cards = projectCards(clone(PROJECTS), 'sunday-demo');
  assert.ok(Array.isArray(cards));
  assert.equal(cards.length, PROJECTS.length);
  for (const p of PROJECTS) {
    const mine = cards.filter((c) => c.name === p.name);
    assert.equal(mine.length, 1, `one card named ${p.name}`);
    if (p.name === 'sunday-demo') assert.equal(mine[0].current, true, 'current project card');
    else assert.ok(!mine[0].current, `${p.name} is not current`);
  }
});

T('projectCards: no current flag when the current name is not listed', () => {
  const projectCards = need(mod, 'projectCards', FR, S);
  const cards = projectCards(clone(PROJECTS), 'elsewhere');
  assert.equal(cards.length, PROJECTS.length);
  assert.ok(cards.every((c) => !c.current));
  assert.deepEqual(projectCards([], 'campus'), []);
});
