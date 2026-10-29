// js/rack-palette-core.js (docs/SPEC.md §6.13.11): entries, ranking, categories, prefs and
// deviceFromTemplate. The expected device in DEVICE_FROM_PYTHON was produced once by
// fathom.library.instantiate (port groups expanded by fathom.library.expand_port_groups).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as pal from '../../fathom/static/js/rack-palette-core.js';

const VOCAB = {
  kinds: {
    stage_io: { label: 'Stage I/O', discipline: 'audio' },
    power: { label: 'Power · UPS · PDU', discipline: 'power' },
    switch: { label: 'Network switches', discipline: 'network' },
    computer: { label: 'Computers', discipline: 'audio' },
    video_switcher: { label: 'Video switchers', discipline: 'video' },
    patch_panel: { label: 'Patch panels · wall plates', discipline: 'other' },
    dmx_node: { label: 'DMX nodes · splitters', discipline: 'lighting' },
  },
};

const LIBRARY = {
  templates: [
    { id: 'apc-smt1500rmi2uc', manufacturer: 'APC', model: 'SMT1500RMI2UC', name: 'SMT1500RMI2UC', kind: 'power', ru: 2, source: 'catalog', rack_category: 'power', image_front: 'apc/apc-smt1500rmi2uc.front.webp', part_number: 'SMT1500RMI2UC', weight_kg: 26.4 },
    { id: 'generic-ups', manufacturer: 'Generic', model: 'UPS', name: 'UPS', kind: 'power', ru: 2, source: 'preset' },
    { id: 'ups-room', manufacturer: 'House', model: 'UPS', name: 'UPS', kind: 'power', ru: 1, source: 'project' },
    { id: 'netgear-gs724t', manufacturer: 'Netgear', model: 'GS724T', name: 'GS724T', kind: 'switch', ru: 1, source: 'catalog', rack_category: 'network' },
    { id: 'dell-r640', manufacturer: 'Dell', model: 'PowerEdge R640', name: 'PowerEdge R640', kind: 'computer', ru: 1, source: 'catalog', rack_category: 'server' },
    { id: 'bmd-atem-2me', manufacturer: 'Blackmagic Design', model: 'ATEM 2 M/E Constellation', name: 'ATEM 2 M/E Constellation', kind: 'video_switcher', ru: 2, source: 'builtin' },
    { id: 'yamaha-rio3224-d2', manufacturer: 'Yamaha', model: 'Rio3224-D2', name: 'Rio3224-D2', kind: 'stage_io', ru: 5, source: 'builtin' },
    { id: 'shure-ad4q', manufacturer: 'Shure', model: 'AD4Q', name: 'AD4Q', kind: 'wireless_rx', ru: null, source: 'builtin' },
    { id: 'acme-patch-24', manufacturer: 'Acme', model: 'Patch 24', name: 'Patch 24', kind: 'patch_panel', ru: 1, source: 'custom' },
    { id: 'enttec-storm', manufacturer: 'ENTTEC', model: 'Storm 24', name: 'Storm 24', kind: 'dmx_node', ru: 1, source: 'extension' },
    { id: 'apc-smt1500rmi2uc', manufacturer: 'dup', model: 'dup', kind: 'power', ru: 2, source: 'builtin' },
  ],
};

const PRESETS = {
  groups: ['Power'],
  presets: [
    { id: 'generic-ups', label: 'UPS', group: 'Power', kind: 'power', ru: 2, routing: 'passthrough', ports: [{ group: 'Outlet', dir: 'out', medium: 'power', count: 6 }] },
    { id: 'generic-pdu', label: 'PDU', group: 'Power', kind: 'power', ru: 1, ports: [{ group: 'Outlet', dir: 'out', medium: 'power', count: 8 }] },
    { id: 'generic-wall-plate', label: 'Wall plate', group: 'Audio', kind: 'patch_panel', ports: [] },
  ],
};

const entries = pal.normalizeEntries(LIBRARY, PRESETS);
const ids = (list) => list.map((e) => e.id);

test('normalizeEntries: rack-mountable only, first id wins, presets fill gaps and carry their template', () => {
  assert.deepEqual(ids(entries), ['apc-smt1500rmi2uc', 'generic-ups', 'ups-room', 'netgear-gs724t', 'dell-r640', 'bmd-atem-2me',
    'yamaha-rio3224-d2', 'acme-patch-24', 'enttec-storm', 'generic-pdu']);
  const apc = entries[0];
  assert.deepEqual(Object.assign({}, apc), {
    id: 'apc-smt1500rmi2uc', name: 'SMT1500RMI2UC', manufacturer: 'APC', model: 'SMT1500RMI2UC', part_number: 'SMT1500RMI2UC',
    ru: 2, kind: 'power', rack_category: 'power', image_front: 'apc/apc-smt1500rmi2uc.front.webp', source: 'catalog',
    template: null, category: 'power', weight_kg: 26.4,
  });
  const ups = entries[1];
  assert.equal(ups.source, 'preset');
  assert.equal(ups.template.id, 'generic-ups');
  assert.equal(ups.template.ports[0].count, 6);
  const pdu = entries.find((e) => e.id === 'generic-pdu');
  assert.equal(pdu.source, 'preset');
  assert.equal(pdu.manufacturer, 'Generic');
  assert.equal(pdu.name, 'PDU');
  assert.equal(pdu.template.model, 'PDU');
  assert.deepEqual(ids(pal.normalizeEntries(null, PRESETS.presets)), ['generic-ups', 'generic-pdu'], 'presets alone (no API)');
  assert.deepEqual(pal.normalizeEntries(null, null), []);
  assert.deepEqual(ids(pal.normalizeEntries(LIBRARY.templates.slice(0, 1))), ['apc-smt1500rmi2uc'], 'a bare list works');
});

test('categoryOf: rack_category wins, else derived from the kind', () => {
  const cat = (kind, rc) => pal.categoryOf({ kind: kind, rack_category: rc });
  assert.equal(cat('power', 'kvm'), 'kvm');
  assert.equal(cat('power', 'bogus'), 'power');
  assert.equal(cat('switch'), 'network');
  assert.equal(cat('network'), 'network');
  assert.equal(cat('patch_panel'), 'patch-panel');
  assert.equal(cat('computer'), 'server');
  for (const k of ['stage_io', 'console', 'amp', 'wireless_rx', 'video_switcher', 'camera', 'encoder', 'display']) assert.equal(cat(k), 'av-media', k);
  assert.equal(cat('dmx_node'), 'other');
  assert.equal(cat(''), 'other');
  assert.equal(pal.CATEGORY_LABELS['av-media'], 'AV / Media');
  assert.equal(pal.CATEGORY_COLORS.server, '#4A7A8A');
  assert.deepEqual(Object.keys(pal.CATEGORY_LABELS).sort(), pal.CATEGORY_ORDER.slice().sort());
  assert.deepEqual(Object.keys(pal.CATEGORY_COLORS).sort(), pal.CATEGORY_ORDER.slice().sort());
});

test('searchEntries: exact > prefix > token > substring > fuzzy, ties by source then name', () => {
  const s = (q, o) => ids(pal.searchEntries(entries, q, Object.assign({ vocab: VOCAB }, o)));
  // exact name "UPS" (100): project before preset; then token matches on the kind label "Power · UPS · PDU" (60).
  assert.deepEqual(s('ups'), ['ups-room', 'generic-ups', 'generic-pdu', 'apc-smt1500rmi2uc']);
  // prefix of a field (80) before token (60) before substring (40).
  const ranked = pal.searchEntries(entries, 'r6', { vocab: VOCAB });
  assert.equal(ranked[0].id, 'dell-r640');
  assert.deepEqual(s('poweredge'), ['dell-r640'], 'prefix of the name');
  assert.deepEqual(s('r640'), ['dell-r640'], 'token of the model');
  assert.deepEqual(s('724'), ['netgear-gs724t'], 'substring');
  assert.deepEqual(s('netgeer'), ['netgear-gs724t'], 'fuzzy edit distance 1 on a token of >= 4 chars');
  assert.deepEqual(s('dell server'), ['dell-r640'], 'tokens across fields');
  assert.deepEqual(s('smt1500rmi2uc'), ['apc-smt1500rmi2uc'], 'part number / model');
  assert.deepEqual(s('apc smt1500rmi2uc'), ['apc-smt1500rmi2uc'], 'maker + model');
  // kind and category labels
  assert.deepEqual(s('switches'), ['netgear-gs724t', 'bmd-atem-2me'], 'token of a kind label (60), then fuzzy "switchers" (25)');
  assert.deepEqual(s('av / media'), ['bmd-atem-2me', 'yamaha-rio3224-d2']);
  // Exact (100) beats prefix (80): "patch 24" is exact for acme-patch-24.
  assert.equal(s('patch 24')[0], 'acme-patch-24');
  // Scores
  assert.equal(pal.scoreEntry(entries[2], 'ups', VOCAB).score, 100);
  assert.equal(pal.scoreEntry(entries.find((e) => e.id === 'dell-r640'), 'power', VOCAB).score, 80);
  assert.equal(pal.scoreEntry(entries.find((e) => e.id === 'dell-r640'), 'r640', VOCAB).score, 60);
  assert.equal(pal.scoreEntry(entries.find((e) => e.id === 'netgear-gs724t'), '724', VOCAB).score, 40);
  assert.equal(pal.scoreEntry(entries.find((e) => e.id === 'netgear-gs724t'), 'netgeer', VOCAB).score, 25);
  assert.equal(pal.scoreEntry(entries.find((e) => e.id === 'netgear-gs724t'), 'zzz', VOCAB).score, 0);
  // Empty query: every entry, by source order then name.
  assert.deepEqual(s(''), ['ups-room', 'acme-patch-24', 'bmd-atem-2me', 'yamaha-rio3224-d2', 'enttec-storm', 'generic-pdu',
    'generic-ups', 'netgear-gs724t', 'dell-r640', 'apc-smt1500rmi2uc']);
  assert.deepEqual(pal.searchEntries(null, 'x'), []);
});

test('searchEntries: power query ranks prefix matches by source, then name', () => {
  // "power" is a prefix of the kind label "Power · UPS · PDU" (80) and of "PowerEdge R640" (80).
  const out = ids(pal.searchEntries(entries, 'power', { vocab: VOCAB }));
  assert.equal(out[0], 'ups-room', 'project first');
  assert.deepEqual(out.slice(-3), ['generic-ups', 'apc-smt1500rmi2uc', 'dell-r640'], 'preset before catalog, catalog by name');
});

test('searchEntries: category filter', () => {
  assert.deepEqual(ids(pal.searchEntries(entries, '', { category: 'power' })), ['ups-room', 'generic-pdu', 'generic-ups', 'apc-smt1500rmi2uc']);
  assert.deepEqual(ids(pal.searchEntries(entries, 'ups', { category: 'power', vocab: VOCAB })), ['ups-room', 'generic-ups', 'generic-pdu', 'apc-smt1500rmi2uc']);
  assert.deepEqual(ids(pal.searchEntries(entries, 'ups', { category: 'server', vocab: VOCAB })), []);
  assert.deepEqual(ids(pal.searchEntries(entries, 'ups', { category: 'power' })), ['ups-room', 'generic-ups'], 'without vocab the kind label is the raw kind');
  assert.deepEqual(ids(pal.searchEntries(entries, 'ups', { category: 'network' })), []);
  assert.equal(pal.searchEntries(entries, '', { category: 'all' }).length, entries.length);
});

test('groupByCategory: category order, empty groups dropped', () => {
  const g = pal.groupByCategory(entries);
  assert.deepEqual(g.map((x) => x.key), ['server', 'network', 'patch-panel', 'power', 'av-media', 'other']);
  assert.equal(g[0].label, 'Server');
  assert.equal(g[0].color, '#4A7A8A');
  assert.deepEqual(ids(g.find((x) => x.key === 'power').entries), ['apc-smt1500rmi2uc', 'generic-ups', 'ups-room', 'generic-pdu']);
  assert.deepEqual(pal.groupByCategory(null), []);
});

test('prefs: readPrefs tolerates junk; toggleFav / pushRecent are pure', () => {
  const empty = { v: 1, favs: [], recents: [] };
  for (const raw of [null, undefined, '', 'not json', '[]', 42, [], { v: 2, favs: ['a'] }]) assert.deepEqual(pal.readPrefs(raw), empty, String(raw));
  assert.deepEqual(pal.readPrefs('{"v":1,"favs":["a","a",3,"b"],"recents":["x"]}'), { v: 1, favs: ['a', 'b'], recents: ['x'] });
  assert.deepEqual(pal.readPrefs({ favs: ['a'] }), { v: 1, favs: ['a'], recents: [] });
  const p0 = { v: 1, favs: ['a'], recents: [] };
  const p1 = pal.toggleFav(p0, 'b');
  assert.deepEqual(p1.favs, ['a', 'b']);
  assert.deepEqual(p0.favs, ['a'], 'input untouched');
  assert.notEqual(p1, p0);
  assert.deepEqual(pal.toggleFav(p1, 'a').favs, ['b']);
  assert.equal(pal.isFav(p1, 'b'), true);
  assert.equal(pal.isFav(p1, 'z'), false);
  let p = pal.readPrefs(null);
  for (let i = 1; i <= 14; i++) p = pal.pushRecent(p, 'd' + i);
  assert.equal(p.recents.length, pal.MAX_RECENTS);
  assert.equal(p.recents[0], 'd14');
  assert.equal(p.recents[11], 'd3');
  const before = p.recents.slice();
  const q = pal.pushRecent(p, 'd10');
  assert.deepEqual(q.recents.slice(0, 2), ['d10', 'd14']);
  assert.equal(q.recents.length, 12);
  assert.deepEqual(p.recents, before, 'input untouched');
  assert.deepEqual(pal.readPrefs(JSON.parse(JSON.stringify(q))), q, 'round-trips through JSON');
  assert.equal(pal.STORAGE_KEY, 'fathom.ui.rack.palette');
  assert.deepEqual(ids(pal.entriesFor(entries, ['dell-r640', 'gone', 'generic-ups'])), ['dell-r640', 'generic-ups']);
});

const TEMPLATE = {
  id: 'acme-stagebox-16', manufacturer: 'Acme', model: 'SB-16', name: 'Stagebox 16', kind: 'stage_io', brand: 'acme', ru: 3,
  dante: true, routing: 'indexed', dmx_footprint: null,
  ports: [
    { group: 'Mic In', dir: 'in', medium: 'analog', connector: 'XLR3F', count: 4, labels: ['Kick', '', 'Snare'] },
    { group: 'Line Out', dir: 'out', medium: 'analog', connector: 'XLR3M', count: 2, start: 5 },
    { group: 'AES', dir: 'out', medium: 'aes3', names: ['1/2', '3/4'], channels: 2 },
    { group: 'Dante', dir: 'io', medium: 'dante', connector: 'etherCON', names: ['Primary', 'Secondary'], channels: 32 },
    { group: 'Power', dir: 'in', medium: 'power', connector: 'IEC C14', label: 'Mains' },
    { group: 'Power', dir: 'in', medium: 'power' },
    { group: 'Word Clock', dir: 'io', medium: 'other', names: ['In', 'Out'], dirs: { In: 'in', Out: 'out' } },
  ],
};

// fathom.library.instantiate(TEMPLATE, device_id='stagebox-16-2', room='main')
const DEVICE_FROM_PYTHON = {"id": "stagebox-16-2", "name": "Stagebox 16", "kind": "stage_io", "manufacturer": "Acme", "model": "SB-16", "brand": "acme", "template": "acme-stagebox-16", "room": "main", "dante": true, "routing": {"mode": "indexed"}, "ports": [{"id": "mic-in-1", "name": "Mic In 1", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Mic In", "index": 1, "origin": "template", "label": "Kick"}, {"id": "mic-in-2", "name": "Mic In 2", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Mic In", "index": 2, "origin": "template"}, {"id": "mic-in-3", "name": "Mic In 3", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Mic In", "index": 3, "origin": "template", "label": "Snare"}, {"id": "mic-in-4", "name": "Mic In 4", "dir": "in", "medium": "analog", "connector": "XLR3F", "group": "Mic In", "index": 4, "origin": "template"}, {"id": "line-out-5", "name": "Line Out 5", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Line Out", "index": 5, "origin": "template"}, {"id": "line-out-6", "name": "Line Out 6", "dir": "out", "medium": "analog", "connector": "XLR3M", "group": "Line Out", "index": 6, "origin": "template"}, {"id": "aes-1-2", "name": "AES 1/2", "dir": "out", "medium": "aes3", "group": "AES", "index": 1, "channels": 2, "origin": "template"}, {"id": "aes-3-4", "name": "AES 3/4", "dir": "out", "medium": "aes3", "group": "AES", "index": 2, "channels": 2, "origin": "template"}, {"id": "dante-primary", "name": "Dante Primary", "dir": "io", "medium": "dante", "connector": "etherCON", "group": "Dante", "index": 1, "channels": 32, "origin": "template"}, {"id": "dante-secondary", "name": "Dante Secondary", "dir": "io", "medium": "dante", "connector": "etherCON", "group": "Dante", "index": 2, "channels": 32, "origin": "template"}, {"id": "power", "name": "Power", "dir": "in", "medium": "power", "connector": "IEC C14", "group": "Power", "index": 1, "origin": "template", "label": "Mains"}, {"id": "power-b", "name": "Power", "dir": "in", "medium": "power", "group": "Power", "index": 1, "origin": "template"}, {"id": "word-clock-in", "name": "Word Clock In", "dir": "in", "medium": "other", "group": "Word Clock", "index": 1, "origin": "template"}, {"id": "word-clock-out", "name": "Word Clock Out", "dir": "out", "medium": "other", "group": "Word Clock", "index": 2, "origin": "template"}]};

test('deviceFromTemplate: mirrors fathom.library.instantiate (ids deduped, ports expanded, template kept, no rack)', () => {
  const doc = { devices: [{ id: 'stagebox-16' }, { id: 'other' }] };
  const before = JSON.stringify(TEMPLATE);
  const r = pal.deviceFromTemplate(doc, TEMPLATE, { room: 'main', vocab: VOCAB });
  assert.equal(r.id, 'stagebox-16-2');
  assert.deepEqual(r.ops, [{ op: 'put', coll: 'devices', id: 'stagebox-16-2', value: DEVICE_FROM_PYTHON }]);
  assert.equal('rack' in r.ops[0].value, false);
  assert.equal(JSON.stringify(TEMPLATE), before, 'template untouched');
  const r3 = pal.deviceFromTemplate({ devices: [{ id: 'stagebox-16' }, { id: 'stagebox-16-2' }] }, TEMPLATE, {});
  assert.equal(r3.id, 'stagebox-16-3');
  assert.equal(r3.ops[0].value.room, '');
  const named = pal.deviceFromTemplate({ devices: [] }, TEMPLATE, { name: '  Stage Left Box ', room: 'sanctuary' });
  assert.equal(named.id, 'stage-left-box');
  assert.equal(named.ops[0].value.name, 'Stage Left Box');
  assert.equal(named.ops[0].value.room, 'sanctuary');
  assert.equal(named.ops[0].value.template, 'acme-stagebox-16');
});

test('deviceFromTemplate: discipline only when it differs from the kind, dmx footprint, routing object, presets', () => {
  const t = { id: 'x-node', manufacturer: 'X', model: 'Node', kind: 'stage_io', discipline: 'audio', dmx_footprint: 4, routing: { mode: 'explicit', map: [['a', 'b']] }, ports: [] };
  const v = pal.deviceFromTemplate(null, t, { vocab: VOCAB }).ops[0].value;
  assert.equal('discipline' in v, false);
  assert.deepEqual(v.dmx, { footprint: 4 });
  assert.deepEqual(v.routing, { mode: 'explicit', map: [['a', 'b']] });
  assert.notEqual(v.routing, t.routing, 'routing is copied');
  assert.equal(v.name, 'Node');
  assert.equal(v.id, 'node');
  assert.equal(pal.deviceFromTemplate(null, Object.assign({}, t, { discipline: 'lighting' }), { vocab: VOCAB }).ops[0].value.discipline, 'lighting');
  const ups = entries.find((e) => e.id === 'generic-ups');
  const u = pal.deviceFromTemplate({ devices: [{ id: 'ups' }] }, ups.template, { room: 'main' });
  assert.equal(u.id, 'ups-2');
  assert.equal(u.ops[0].value.template, 'generic-ups');
  assert.equal(u.ops[0].value.manufacturer, 'Generic');
  assert.deepEqual(u.ops[0].value.routing, { mode: 'passthrough' });
  assert.deepEqual(u.ops[0].value.ports.map((p) => p.id), ['outlet-1', 'outlet-2', 'outlet-3', 'outlet-4', 'outlet-5', 'outlet-6']);
});

test('nextRow: arrows, Home/End, paging, back to the search box', () => {
  assert.equal(pal.nextRow(5, -1, 'ArrowDown'), 0);
  assert.equal(pal.nextRow(5, 0, 'ArrowDown'), 1);
  assert.equal(pal.nextRow(5, 4, 'ArrowDown'), 4);
  assert.equal(pal.nextRow(5, 0, 'ArrowUp'), -1);
  assert.equal(pal.nextRow(5, 3, 'ArrowUp'), 2);
  assert.equal(pal.nextRow(5, 2, 'Home'), 0);
  assert.equal(pal.nextRow(5, 2, 'End'), 4);
  assert.equal(pal.nextRow(30, 2, 'PageDown'), 12);
  assert.equal(pal.nextRow(30, 5, 'PageUp'), 0);
  assert.equal(pal.nextRow(0, 0, 'ArrowDown'), -1);
  assert.equal(pal.nextRow(5, 2, 'x'), 2);
});

test('dedupeCatalog: catalog twins (same maker + model, any case) collapse to one row', () => {
  const lib = { templates: [
    { id: 'dell-poweredge-r640', manufacturer: 'Dell', model: 'PowerEdge R640', kind: 'computer', ru: 1, source: 'catalog', rack_category: 'server' },
    { id: 'poweredge-r640', manufacturer: 'dell', model: 'poweredge r640', kind: 'computer', ru: 1, source: 'catalog', rack_category: 'server', image_front: 'dell/r640.front.webp' },
    { id: 'ubiquiti-usw-24', manufacturer: 'Ubiquiti', model: 'USW-24', kind: 'switch', ru: 1, source: 'catalog', image_rear: 'ubiquiti/usw-24.rear.webp' },
    { id: 'usw-24', manufacturer: 'Ubiquiti', model: 'USW-24', kind: 'switch', ru: 1, source: 'catalog' },
    { id: 'apc-ap7900b', manufacturer: 'APC', model: 'AP7900B', kind: 'power', ru: 1, source: 'catalog' },
    { id: 'ap7900b', manufacturer: 'APC', model: 'AP7900B', kind: 'power', ru: 1, source: 'catalog' },
    { id: 'my-ap7900b', manufacturer: 'APC', model: 'AP7900B', kind: 'power', ru: 1, source: 'custom' },
    { id: 'house-ap7900b', manufacturer: 'APC', model: 'AP7900B', kind: 'power', ru: 1, source: 'project' },
    { id: 'house-ap7900b-2', manufacturer: 'APC', model: 'AP7900B', kind: 'power', ru: 1, source: 'project' },
    { id: 'netgear-gs724t', manufacturer: 'Netgear', model: 'GS724T', kind: 'switch', ru: 1, source: 'catalog' },
  ] };
  const list = pal.normalizeEntries(lib, null);
  assert.deepEqual(ids(list), ['poweredge-r640', 'ubiquiti-usw-24', 'ap7900b', 'my-ap7900b', 'house-ap7900b', 'house-ap7900b-2', 'netgear-gs724t'],
    'front image wins, then rear image, then the shorter id; kept at the first twin\'s place; other sources untouched');
  assert.deepEqual(list[0].aliases, ['dell-poweredge-r640']);
  assert.deepEqual(list[1].aliases, ['usw-24']);
  assert.deepEqual(list[2].aliases, ['apc-ap7900b']);
  assert.equal('aliases' in list[3], false);
  assert.equal('aliases' in list[6], false, 'singletons unchanged');
  const raw = lib.templates.map((s) => Object.assign({}, s));
  const r = pal.dedupeCatalog(raw);
  assert.deepEqual(r.dropped, { 'dell-poweredge-r640': 'poweredge-r640', 'usw-24': 'ubiquiti-usw-24', 'apc-ap7900b': 'ap7900b' });
  assert.equal(r.entries.length, raw.length - 3);
  assert.equal('aliases' in raw[1], false, 'input untouched');
  assert.deepEqual(pal.dedupeCatalog(null), { entries: [], dropped: {} });
  // Same id length and no images: the smaller id wins.
  const tie = pal.dedupeCatalog([
    { id: 'b-x', manufacturer: 'M', model: 'X', source: 'catalog' }, { id: 'a-x', manufacturer: 'M', model: 'X', source: 'catalog' }]);
  assert.deepEqual(ids(tie.entries), ['a-x']);
});

test('dedupeCatalog: favourites and recents on a dropped id resolve to the kept twin', () => {
  const list = pal.normalizeEntries({ templates: [
    { id: 'dell-poweredge-r640', manufacturer: 'Dell', model: 'PowerEdge R640', kind: 'computer', ru: 1, source: 'catalog' },
    { id: 'poweredge-r640', manufacturer: 'Dell', model: 'PowerEdge R640', kind: 'computer', ru: 1, source: 'catalog', image_front: 'dell/r640.front.webp' },
    { id: 'netgear-gs724t', manufacturer: 'Netgear', model: 'GS724T', kind: 'switch', ru: 1, source: 'catalog' },
  ] }, null);
  const kept = list[0];
  assert.deepEqual(ids(pal.entriesFor(list, ['dell-poweredge-r640', 'netgear-gs724t'])), ['poweredge-r640', 'netgear-gs724t']);
  assert.deepEqual(ids(pal.entriesFor(list, ['dell-poweredge-r640', 'poweredge-r640'])), ['poweredge-r640'], 'listed once');
  const old = { v: 1, favs: ['dell-poweredge-r640'], recents: ['dell-poweredge-r640', 'netgear-gs724t'] };
  assert.equal(pal.isFav(old, kept.id, kept.aliases), true);
  assert.equal(pal.isFav(old, kept.id), false, 'without aliases only the id counts');
  assert.deepEqual(pal.toggleFav(old, kept.id, kept.aliases).favs, [], 'un-starring drops the alias too');
  assert.deepEqual(pal.toggleFav({ v: 1, favs: [], recents: [] }, kept.id, kept.aliases).favs, ['poweredge-r640']);
  assert.deepEqual(pal.pushRecent(old, kept.id, kept.aliases).recents, ['poweredge-r640', 'netgear-gs724t']);
});

test('CATEGORY_COLORS is rack-display-core\'s table', async () => {
  const dc = await import('../../fathom/static/js/rack-display-core.js');
  assert.equal(pal.CATEGORY_COLORS, dc.CATEGORY_COLORS);
});
