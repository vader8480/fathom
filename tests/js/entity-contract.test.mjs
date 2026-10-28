// T-ENTITY: js/entity-core.js (ENTITY) against docs/ui-audit.md A.3, B.1 D5 and B.2 ENTITY (Core).
// Facts and cards are matched by `key` or, failing that, by label, so either naming passes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { JS, loadModule, loadFixtureDoc, loadVocab, clone, need, device } from './fixtures/helpers.mjs';

const { mod, skip: absent, error } = await loadModule('js/entity-core.js', 'ENTITY');
const { indexDoc } = await import(pathToFileURL(path.join(JS, 'model-core.js')).href);
const S = 'B.2 ENTITY';
const skip = absent || (error ? 'entity-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);
const msg = (sec, text) => `ui-audit ${sec}: ${text}`;

if (error) test('entity-core.js imports in Node (D12 pure module)', () => { throw error; });

const fixture = loadFixtureDoc();
const vocab = loadVocab();
const fx = () => clone(fixture);
const BASE_TABS = ['overview', 'ports', 'cables', 'network', 'inventory', 'procedures', 'files'];

const FACT = {
  kind: /^kind|type/i,
  status: /status/i,
  room: /^room/i,
  rack: /rack/i,
  network: /network|ip|dante/i,
  ports: /^ports?/i,
  venue: /venue/i,
  code: /code/i,
  devices: /device/i,
  racks: /racks?$/i,
  plans: /plan/i,
  cables: /cable/i,
  height: /height|size/i,
  used: /used/i,
  free: /free/i,
  location: /location/i,
  procedures: /procedure|sop/i,
  problems: /problem/i,
  files: /file|attachment/i,
};

function find(list, key) {
  const byKey = (list || []).find((x) => x && x.key === key);
  if (byKey) return byKey;
  const re = FACT[key];
  return re ? (list || []).find((x) => x && typeof x.label === 'string' && re.test(x.label)) : undefined;
}
const keyOf = (list, item) => (list || []).indexOf(item);
const text = (f) => (f === undefined || f === null ? '' : String(f.value));
const firstInt = (v) => {
  const mm = String(v).match(/\d+/);
  return mm ? parseInt(mm[0], 10) : NaN;
};
const tabKeys = (tabs) => (tabs || []).map((t) => (typeof t === 'string' ? t : t && t.key));

function wellFormedFacts(facts, sec) {
  assert.ok(Array.isArray(facts), msg(sec, 'facts are an array'));
  for (const f of facts) {
    assert.equal(typeof f.label, 'string', msg(sec, 'every fact has a string label'));
    assert.ok(f.label.length > 0, msg(sec, 'labels are not empty'));
    assert.ok(f.value !== undefined && f.value !== null && String(f.value).trim() !== '', msg(sec, `fact "${f.label}" has a value (empties are omitted)`));
    if (f.href !== undefined && f.href !== null) assert.equal(typeof f.href, 'string', msg(sec, 'href is a string when present'));
  }
}

function assertOrder(facts, keys, sec) {
  const found = keys.map((k) => find(facts, k)).filter(Boolean);
  const idx = found.map((f) => keyOf(facts, f));
  const sorted = idx.slice().sort((a, b) => a - b);
  assert.deepEqual(idx, sorted, msg(sec, `facts follow the order ${keys.join(', ')}`));
}

function cablesTouching(doc, devIds) {
  const set = new Set(devIds);
  return (doc.cables || []).filter((c) => set.has((c.from || {}).device) || set.has((c.to || {}).device));
}

function patchedPorts(doc, dev) {
  const used = new Set();
  for (const c of doc.cables || []) {
    for (const e of [c.from || {}, c.to || {}]) if (e.device === dev.id && e.port) used.add(e.port);
  }
  return (dev.ports || []).filter((p) => used.has(p.id)).length;
}

function withDevice(doc, id, patch) {
  const d = device(doc, id);
  Object.assign(d, patch);
  return d;
}

T('exports the B.2 ENTITY core API', () => {
  for (const name of ['deviceFacts', 'roomFacts', 'rackFacts', 'deviceTabs', 'roomTabs', 'rackTabs', 'resolveTab', 'summaryCards']) {
    assert.equal(typeof need(mod, name, 'ENTITY', S), 'function', msg(S, `${name} is a function`));
  }
});

T('deviceFacts: atem-mini values in contract order', () => {
  const deviceFacts = need(mod, 'deviceFacts', 'ENTITY', S);
  const doc = fx();
  const dev = device(doc, 'atem-mini');
  const facts = deviceFacts(doc, vocab, dev, null);
  wellFormedFacts(facts, S);

  const kind = find(facts, 'kind');
  assert.ok(kind, msg(S, 'kind fact present'));
  assert.match(text(kind), /video/i, msg(S, 'kind fact carries the discipline label (Video)'));
  assert.match(text(kind), /switcher/i, msg(S, 'kind fact carries the kind (video_switcher)'));

  const status = find(facts, 'status');
  assert.ok(status, msg(S, 'status fact present'));
  assert.match(text(status), /^installed$/i, msg(S, 'status = device.status'));

  const room = find(facts, 'room');
  assert.ok(room, msg(S, 'room fact present'));
  assert.equal(text(room), 'Main Auditorium', msg(S, 'room fact shows the room name'));

  assert.equal(find(facts, 'rack'), undefined, msg(S, 'atem-mini is not racked: rack · U omitted'));

  const net = find(facts, 'network');
  assert.ok(net, msg(S, 'network fact present'));
  assert.equal(text(net), '10.20.0.40', msg(S, 'no primary-role interface: first interface with an ip; no dante_name'));

  const ports = find(facts, 'ports');
  assert.ok(ports, msg(S, 'ports fact present'));
  assert.equal(dev.ports.length, 5);
  assert.equal(patchedPorts(doc, dev), 4);
  assert.equal(text(ports), '5 (4 patched)', msg(S, 'ports "n (m patched)" from cables touching its ports'));

  const order = ['kind', 'status', 'room', 'network', 'ports'].map((k) => keyOf(facts, find(facts, k)));
  assert.deepEqual(order, order.slice().sort((a, b) => a - b), msg(S, 'order kind, status, room, rack · U, network, ports'));
});

T('deviceFacts: rack · U for a racked device (shure-wireless in FOH rack at U10)', () => {
  const deviceFacts = need(mod, 'deviceFacts', 'ENTITY', S);
  const doc = fx();
  const facts = deviceFacts(doc, vocab, device(doc, 'shure-wireless'), null);
  wellFormedFacts(facts, S);
  const rack = find(facts, 'rack');
  assert.ok(rack, msg(S, 'rack fact present when device.rack is set'));
  assert.match(text(rack), /FOH rack/, msg(S, 'rack fact names the rack'));
  assert.match(text(rack), /U\s*10\b/, msg(S, 'rack fact shows the U position'));
  assert.equal(text(find(facts, 'ports')), '4 (4 patched)', msg(S, 'all four ports carry cables'));
  assert.equal(text(find(facts, 'network')), '10.20.0.31');
  assertOrder(facts, ['kind', 'status', 'room', 'rack', 'network', 'ports'], S);
});

T('deviceFacts: network prefers role primary, else first with an ip, plus dante_name', () => {
  const deviceFacts = need(mod, 'deviceFacts', 'ENTITY', S);
  let doc = fx();
  let dev = withDevice(doc, 'atem-mini', {
    interfaces: [
      { id: 'ctl', role: 'control', ip: '10.20.0.41' },
      { id: 'primary', role: 'primary', ip: '10.20.0.42' },
    ],
  });
  assert.equal(text(find(deviceFacts(doc, vocab, dev, null), 'network')), '10.20.0.42', msg(S, 'role primary wins over list order'));

  doc = fx();
  dev = withDevice(doc, 'atem-mini', {
    interfaces: [
      { id: 'mgmt', role: 'management' },
      { id: 'media', role: 'media', ip: '10.20.0.43' },
    ],
  });
  assert.equal(text(find(deviceFacts(doc, vocab, dev, null), 'network')), '10.20.0.43', msg(S, 'first interface that has an ip'));

  doc = fx();
  dev = withDevice(doc, 'atem-mini', { dante_name: 'ATEM-MINI' });
  assert.equal(text(find(deviceFacts(doc, vocab, dev, null), 'network')), '10.20.0.40 \u00b7 ATEM-MINI', msg(S, 'ip · dante_name (e.g. 10.20.0.10 · FOH-CL5)'));
});

T('deviceFacts: facts with no value are omitted', () => {
  const deviceFacts = need(mod, 'deviceFacts', 'ENTITY', S);
  const doc = fx();
  const dev = device(doc, 'atem-mini');
  delete dev.interfaces;
  delete dev.rack;
  delete dev.dante_name;
  const facts = deviceFacts(doc, vocab, dev, {});
  wellFormedFacts(facts, S);
  assert.equal(find(facts, 'rack'), undefined, msg(S, 'no rack → no rack · U fact'));
  assert.equal(find(facts, 'network'), undefined, msg(S, 'no interfaces and no dante_name → no network fact'));
  assert.ok(find(facts, 'kind') && find(facts, 'room') && find(facts, 'ports'), msg(S, 'facts with values stay'));

  const bare = { id: 'bare', name: 'Bare', kind: 'video_switcher', ports: [], interfaces: [{ id: 'primary', role: 'primary' }] };
  doc.devices.push(bare);
  const bf = deviceFacts(doc, vocab, bare, null);
  wellFormedFacts(bf, S);
  assert.equal(find(bf, 'network'), undefined, msg(S, 'interface without ip → no network fact'));
  assert.equal(find(bf, 'room'), undefined, msg(S, 'no room → no room fact'));
  assert.equal(find(bf, 'rack'), undefined);
});

T('deviceTabs: base list without dmx or channels', () => {
  const deviceTabs = need(mod, 'deviceTabs', 'ENTITY', S);
  const doc = fx();
  assert.deepEqual(tabKeys(deviceTabs(doc, device(doc, 'atem-mini'))), BASE_TABS, msg(S, 'atem-mini has no DMX or console channels'));
  const fresh = withDevice(doc, 'sound-board', { dmx: { footprint: 16 }, channels: [] });
  assert.deepEqual(tabKeys(deviceTabs(doc, fresh)), BASE_TABS, msg(S, 'footprint alone is not an address or universe; empty channels → no tab'));
});

T('deviceTabs: dmx after network, channels only for console channels', () => {
  const deviceTabs = need(mod, 'deviceTabs', 'ENTITY', S);
  const withTabs = (extra) => BASE_TABS.slice(0, 4).concat(extra, BASE_TABS.slice(4));
  let doc = fx();
  let dev = withDevice(doc, 'atem-mini', { dmx: { universe: 1, address: 101, footprint: 16 } });
  assert.deepEqual(tabKeys(deviceTabs(doc, dev)), withTabs(['dmx']), msg(S, 'dmx inserted after network'));

  doc = fx();
  dev = withDevice(doc, 'atem-mini', { dmx: { universe: 2 } });
  assert.deepEqual(tabKeys(deviceTabs(doc, dev)), withTabs(['dmx']), msg(S, 'universe alone gives a dmx tab'));

  doc = fx();
  dev = withDevice(doc, 'atem-mini', { dmx: { address: 1 } });
  assert.deepEqual(tabKeys(deviceTabs(doc, dev)), withTabs(['dmx']), msg(S, 'address alone gives a dmx tab'));

  doc = fx();
  dev = withDevice(doc, 'sound-board', { channels: [{ id: 'in-1', kind: 'input', index: 1, name: 'Kick' }] });
  assert.deepEqual(tabKeys(deviceTabs(doc, dev)), withTabs(['channels']), msg(S, 'console channels → channels tab'));

  doc = fx();
  dev = withDevice(doc, 'sound-board', {
    dmx: { universe: 1, address: 1 },
    channels: [{ id: 'in-1', kind: 'input', index: 1 }],
  });
  assert.deepEqual(tabKeys(deviceTabs(doc, dev)), withTabs(['dmx', 'channels']), msg(S, 'both: network, dmx, channels, inventory'));
});

T('roomTabs and rackTabs', () => {
  const roomTabs = need(mod, 'roomTabs', 'ENTITY', S);
  const rackTabs = need(mod, 'rackTabs', 'ENTITY', S);
  assert.deepEqual(tabKeys(roomTabs()), ['overview', 'devices', 'cables', 'racks', 'plans', 'procedures'], msg('A.3', 'room tabs'));
  assert.deepEqual(tabKeys(rackTabs()), ['overview', 'elevation', 'devices', 'cables'], msg('A.3', 'rack tabs'));
});

T('resolveTab: known tab kept, unknown or empty → overview + redirect (D5)', () => {
  const resolveTab = need(mod, 'resolveTab', 'ENTITY', S);
  const deviceTabs = need(mod, 'deviceTabs', 'ENTITY', S);
  const doc = fx();
  const tabs = deviceTabs(doc, device(doc, 'atem-mini'));
  for (const k of BASE_TABS) assert.deepEqual(resolveTab(tabs, k), { tab: k, redirect: false }, msg('D5', `known tab ${k}`));
  assert.deepEqual(resolveTab(tabs, 'bogus'), { tab: 'overview', redirect: true }, msg('D5', 'unknown tab'));
  assert.deepEqual(resolveTab(tabs, 'dmx'), { tab: 'overview', redirect: true }, msg('D5', 'dmx is unknown for a device without DMX'));
  assert.deepEqual(resolveTab(tabs, ''), { tab: 'overview', redirect: true }, msg('D5', 'empty tab'));
  assert.equal(resolveTab(tabs, undefined).tab, 'overview', msg('D5', 'no tab segment → overview'));
  assert.deepEqual(resolveTab(BASE_TABS.slice(), 'files'), { tab: 'files', redirect: false }, msg(S, 'plain string arrays accepted'));
});

T('roomFacts: main room venue, code and counts', () => {
  const roomFacts = need(mod, 'roomFacts', 'ENTITY', S);
  const doc = fx();
  const room = doc.rooms.find((r) => r.id === 'main');
  const facts = roomFacts(doc, room);
  assert.ok(Array.isArray(facts));
  for (const f of facts) assert.equal(typeof f.label, 'string');

  const devs = indexDoc(doc).devicesByRoom.main;
  assert.equal(devs.length, 11);
  assert.equal(text(find(facts, 'venue')), 'Hillside Church', msg(S, 'venue name'));
  assert.equal(text(find(facts, 'code')), 'MAIN', msg(S, 'room code'));
  assert.equal(firstInt(text(find(facts, 'devices'))), devs.length, msg(S, 'devices count = devicesByRoom'));
  const racks = facts.find((f) => f.key === 'racks') || facts.find((f) => /^racks?$/i.test(f.label));
  assert.ok(racks, msg(S, 'racks fact present'));
  assert.equal(firstInt(text(racks)), 1, msg(S, 'one rack in main'));
  const cables = find(facts, 'cables');
  assert.ok(cables, msg(S, 'cables fact present'));
  assert.equal(firstInt(text(cables)), cablesTouching(doc, devs.map((d) => d.id)).length, msg(S, 'cables touching room devices'));
  const plans = find(facts, 'plans');
  if (plans) assert.equal(firstInt(text(plans)), 0, msg(S, 'no floor plans in the fixture'));
  assertOrder(facts, ['venue', 'code', 'devices', 'plans', 'cables'], S);
  assert.ok(keyOf(facts, find(facts, 'devices')) < keyOf(facts, racks), msg(S, 'devices before racks'));
});

T('rackFacts: rk-foh room, height, used and free U, devices, location', () => {
  const rackFacts = need(mod, 'rackFacts', 'ENTITY', S);
  let doc = fx();
  const rack = doc.racks.find((r) => r.id === 'rk-foh');
  let facts = rackFacts(doc, rack);
  wellFormedFacts(facts, S);
  assert.equal(text(find(facts, 'room')), 'Main Auditorium', msg(S, 'rack room name'));
  assert.equal(firstInt(text(find(facts, 'height'))), 12, msg(S, 'height U = rack.units'));
  assert.equal(firstInt(text(find(facts, 'used'))), 1, msg(S, 'shure-wireless: 1U (half width still uses the U)'));
  assert.equal(firstInt(text(find(facts, 'free'))), 11, msg(S, 'free = 12 − 1'));
  const devs = facts.find((f) => f.key === 'devices') || facts.find((f) => /^devices?$/i.test(f.label));
  assert.ok(devs, msg(S, 'devices fact present'));
  assert.equal(firstInt(text(devs)), 1, msg(S, 'one device in rk-foh'));
  assert.equal(text(find(facts, 'location')), 'FOH booth', msg(S, 'location name'));
  assertOrder(facts, ['room', 'height', 'used', 'free'], S);
  assert.ok(keyOf(facts, find(facts, 'free')) < keyOf(facts, devs), msg(S, 'free U before devices'));
  assert.ok(keyOf(facts, devs) < keyOf(facts, find(facts, 'location')), msg(S, 'devices before location'));

  doc = fx();
  device(doc, 'sound-board').rack = { id: 'rk-foh', u: 3, height: 2, face: 'front', side: 'full' };
  facts = rackFacts(doc, doc.racks[0]);
  assert.equal(firstInt(text(find(facts, 'used'))), 3, msg(S, '1U + 2U placed'));
  assert.equal(firstInt(text(find(facts, 'free'))), 9, msg(S, '12 − 3'));
  const devs2 = facts.find((f) => f.key === 'devices') || facts.find((f) => /^devices?$/i.test(f.label));
  assert.equal(firstInt(text(devs2)), 2, msg(S, 'two racked devices'));
});

function cardWellFormed(cards, sec) {
  assert.ok(Array.isArray(cards), msg(sec, 'cards are an array'));
  for (const c of cards) {
    assert.equal(typeof c.label, 'string', msg(sec, 'card label'));
    assert.equal(typeof c.count, 'number', msg(sec, `card "${c.label}" count is a number`));
    assert.ok(c.count >= 0);
    if (c.drill) {
      assert.ok(Array.isArray(c.drill.ids), msg(sec, `card "${c.label}" drill.ids is an array`));
      assert.equal(c.drill.ids.length, c.count, msg(sec, `card "${c.label}" drill.ids has count entries`));
      assert.equal(typeof c.drill.title, 'string', msg(sec, 'drill title'));
    }
  }
}

T('summaryCards device: counts match the doc; empty ctxInfo gives 0 problems and procedures', () => {
  const summaryCards = need(mod, 'summaryCards', 'ENTITY', S);
  const deviceTabs = need(mod, 'deviceTabs', 'ENTITY', S);
  const doc = fx();
  const dev = device(doc, 'atem-mini');
  const cards = summaryCards('device', doc, dev, { problems: [], pages: [] });
  cardWellFormed(cards, S);
  const tabs = tabKeys(deviceTabs(doc, dev));
  for (const c of cards) if (c.tab) assert.ok(tabs.includes(c.tab), msg(S, `card tab ${c.tab} is a device tab`));

  const ports = find(cards, 'ports');
  assert.ok(ports && ports.drill, msg('A.3', 'Ports card with a drill-down'));
  assert.equal(ports.count, dev.ports.length, msg(S, 'Ports count = device ports'));
  assert.equal(ports.tab, 'ports');

  const cables = find(cards, 'cables');
  assert.ok(cables && cables.drill, msg('A.3', 'Cables card with a drill-down'));
  const expected = indexDoc(doc).cablesByDevice['atem-mini'].map((c) => c.id).sort();
  assert.deepEqual(expected, ['c-0011', 'c-0012', 'c-0013', 'c-0015']);
  assert.equal(cables.count, expected.length, msg(S, 'Cables count = cables touching the device'));
  assert.deepEqual(cables.drill.ids.slice().sort(), expected, msg(S, 'Cables drill ids are the cable ids'));
  assert.equal(cables.tab, 'cables');

  const problems = find(cards, 'problems');
  assert.ok(problems, msg('A.3', 'Problems card'));
  assert.equal(problems.count, 0);
  const procs = find(cards, 'procedures');
  assert.ok(procs, msg('A.3', 'Procedures card'));
  assert.equal(procs.count, 0);
  const files = find(cards, 'files');
  if (files) assert.equal(files.count, 0, msg(S, 'no attachments in the fixture'));
});

T('summaryCards device: ctxInfo problems and pages are counted', () => {
  const summaryCards = need(mod, 'summaryCards', 'ENTITY', S);
  const doc = fx();
  const dev = device(doc, 'atem-mini');
  const ctxInfo = {
    problems: [{ id: 'pr-00000001', text: 'No HDMI out', status: 'open', device: 'atem-mini', room: 'main' }],
    pages: [{ id: 'pg-00000001', slug: 'atem-start', title: 'Start the ATEM', devices: ['atem-mini'] }],
  };
  const cards = summaryCards('device', doc, dev, ctxInfo);
  cardWellFormed(cards, S);
  assert.equal(find(cards, 'problems').count, 1, msg(S, 'one open problem'));
  assert.equal(find(cards, 'procedures').count, 1, msg(S, 'one procedure'));
});

T('summaryCards room: devices count matches devicesByRoom', () => {
  const summaryCards = need(mod, 'summaryCards', 'ENTITY', S);
  const doc = fx();
  const room = doc.rooms.find((r) => r.id === 'main');
  const cards = summaryCards('room', doc, room, { problems: [], pages: [] });
  cardWellFormed(cards, S);
  const devs = indexDoc(doc).devicesByRoom.main.map((d) => d.id).sort();
  const dc = cards.find((c) => c.key === 'devices') || cards.find((c) => /^devices?$/i.test(c.label));
  assert.ok(dc, msg(S, 'room Devices card'));
  assert.equal(dc.count, devs.length, msg(S, 'Devices count = devicesByRoom.main'));
  if (dc.drill) assert.deepEqual(dc.drill.ids.slice().sort(), devs, msg(S, 'drill ids are the room device ids'));
  const cables = find(cards, 'cables');
  if (cables) assert.equal(cables.count, cablesTouching(doc, devs).length, msg(S, 'room Cables count'));
  const racks = cards.find((c) => c.key === 'racks') || cards.find((c) => /^racks?$/i.test(c.label));
  if (racks) assert.equal(racks.count, 1, msg(S, 'room Racks count'));
  const roomTabs = tabKeys(need(mod, 'roomTabs', 'ENTITY', S)());
  for (const c of cards) if (c.tab) assert.ok(roomTabs.includes(c.tab), msg(S, `card tab ${c.tab} is a room tab`));
});

T('summaryCards rack: Devices and Cables cards match the rack', () => {
  const summaryCards = need(mod, 'summaryCards', 'ENTITY', S);
  const doc = fx();
  const rack = doc.racks.find((r) => r.id === 'rk-foh');
  const cards = summaryCards('rack', doc, rack, { problems: [], pages: [] });
  cardWellFormed(cards, S);
  const dc = cards.find((c) => c.key === 'devices') || cards.find((c) => /^devices?$/i.test(c.label));
  assert.ok(dc, msg('B.3 RK', 'rack Devices card'));
  assert.equal(dc.count, 1);
  if (dc.drill) assert.deepEqual(dc.drill.ids, ['shure-wireless']);
  const cc = find(cards, 'cables');
  assert.ok(cc, msg('B.3 RK', 'rack Cables card'));
  assert.equal(cc.count, cablesTouching(doc, ['shure-wireless']).length, msg('B.3 RK', 'cables touching rack devices'));
  const rackTabs = tabKeys(need(mod, 'rackTabs', 'ENTITY', S)());
  for (const c of cards) if (c.tab) assert.ok(rackTabs.includes(c.tab), msg(S, `card tab ${c.tab} is a rack tab`));
});

T('core is pure: deterministic and does not mutate the doc', () => {
  const doc = fx();
  const before = JSON.stringify(doc);
  const dev = device(doc, 'atem-mini');
  const room = doc.rooms[0];
  const rack = doc.racks[0];
  const ctxInfo = { problems: [], pages: [] };
  const run = () => [
    mod.deviceFacts(doc, vocab, dev, null),
    mod.roomFacts(doc, room),
    mod.rackFacts(doc, rack),
    mod.deviceTabs(doc, dev),
    mod.summaryCards('device', doc, dev, ctxInfo),
    mod.summaryCards('room', doc, room, ctxInfo),
    mod.summaryCards('rack', doc, rack, ctxInfo),
  ];
  const a = JSON.stringify(run());
  const b = JSON.stringify(run());
  assert.equal(a, b, msg(S, 'same input → same output'));
  assert.equal(JSON.stringify(doc), before, msg(S, 'doc unchanged'));
});
