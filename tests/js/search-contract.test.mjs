// T-SEARCH: contract test for js/search-core.js, written from docs/ui-audit.md alone
// (B.2 SEARCH "Core", B.1 D1/D2/D8, B.4 network kind and `status`) and SPEC §5.11 / FR-SRCH-04.
// The implementing unit owns tests/js/search-core.test.mjs; this file never reads the implementation.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadFixtureDoc, clone, norm, m, need } from './fixtures/helpers.mjs';

const { mod, skip: absent, error } = await loadModule('js/search-core.js', 'SEARCH');
const mc = await loadModule('js/model-core.js', 'W5');
const S = 'ui-audit B.2 SEARCH';
const skip = absent || (error ? 'search-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);

if (error) test('search-core.js imports in Node (D12 pure module)', () => { throw error; });

const fixture = loadFixtureDoc();

// Fixture doc plus a second network (campus-demo `av-dante`), a floor plan, an attachment and SOP pages,
// so every hit kind can be built from real records.
function fx() {
  const d = clone(fixture);
  d.networks = (d.networks || []).concat([
    { id: 'av-dante', name: 'Dante primary', vlan: 31, subnet: '10.31.0.0/24', protocol: 'dante' },
  ]);
  d.floorplans = [{ id: 'fp-main-stage', name: 'Main stage', room: 'main' }];
  d.attachments = [
    { id: 'att-atem-manual', name: 'ATEM manual.pdf', kind: 'manual', device: 'atem-mini' },
    { id: 'att-site-map', name: 'Site map.pdf', kind: 'drawing' },
  ];
  d.pages = [
    { id: 'pg-0000aaaa', slug: 'power-up', title: 'Power up', status: 'published', body: '' },
    { id: 'pg-0000bbbb', slug: 'stream-check', title: 'Stream check', status: 'draft', body: '' },
  ];
  return d;
}

const HIT_KEYS = ['kind', 'id', 'device', 'port', 'title', 'subtitle', 'room', 'score', 'match'];
function hitKeysOk(h, why) {
  for (const k of HIT_KEYS) assert.ok(h && k in h, m('FR-SRCH-03', '§5.11', `${why}: hit missing key ${k} in ${JSON.stringify(h)}`));
}

const key = (h) => h.kind + ':' + h.id;
const keys = (list) => (list || []).map(key);

function hit(kind, id, extra) {
  return Object.assign({ kind: kind, id: id, device: null, port: null, title: id, subtitle: '', room: null, score: 60, match: 'name' }, extra);
}

function local(doc, q, limit) {
  return need(mc.mod, 'searchLocal', 'FR-SRCH-03', '§6.2')(doc, q, limit || 20);
}

// Group shape is not fixed by the contract: an array (or ordered object) of groups, each naming its
// category as `key` or `category` and holding `hits` or `items`. Empty groups are ignored.
function groupsOf(out) {
  let list = out;
  if (list && !Array.isArray(list) && typeof list === 'object') {
    list = Object.keys(list).map((k) => (Array.isArray(list[k]) ? { key: k, hits: list[k] } : Object.assign({ key: k }, list[k])));
  }
  assert.ok(Array.isArray(list), m('FR-SRCH', S, `groupHits must return an ordered list of groups, got ${JSON.stringify(out)}`));
  return list.map((g) => {
    const c = g.key !== undefined ? g.key : g.category;
    const k = c && typeof c === 'object' ? c.key : c;
    const items = g.hits || g.items || [];
    return { key: k, hits: items };
  }).filter((g) => g.hits.length > 0);
}

// Partial routes compare after dropping absent values (undefined, null, '', empty query): mergeRoute
// clears id/tab/sub on a view change and buildRoute drops empty values, so they mean the same thing.
function partial(r) {
  const out = {};
  for (const k of Object.keys(r || {})) {
    const v = r[k];
    if (v === undefined || v === null || v === '') continue;
    if (k === 'query') {
      const q = {};
      for (const qk of Object.keys(v)) if (v[qk] !== undefined && v[qk] !== null && v[qk] !== '') q[qk] = v[qk];
      if (Object.keys(q).length) out.query = q;
      continue;
    }
    out[k] = v;
  }
  return norm(out);
}

const ROUTE = { project: 'demo', room: 'chapel', view: 'patch', id: '', tab: '', sub: '', extra: [], query: {} };

const ORDER = ['all', 'devices', 'inventory', 'rooms', 'racks', 'ports', 'cables', 'networks', 'plans', 'procedures', 'files'];
const KIND_OF = {
  devices: ['device'], inventory: ['device'], rooms: ['room'], racks: ['rack'], ports: ['port'], cables: ['cable'],
  networks: ['network', 'interface'], plans: ['floorplan'], procedures: ['page'], files: ['attachment'],
};
const ALL_KINDS = ['device', 'port', 'cable', 'interface', 'network', 'room', 'rack', 'floorplan', 'attachment', 'page'];

// ------------------------------------------------------------------ CATEGORIES / kindsFor

T('CATEGORIES: keys in contract order, each {key, label, glyph, kinds}', () => {
  const cats = need(mod, 'CATEGORIES', 'FR-SRCH', S);
  assert.ok(Array.isArray(cats), m('FR-SRCH', S, 'CATEGORIES is an array'));
  assert.deepEqual(cats.map((c) => c.key), ORDER, m('FR-SRCH', S, 'CATEGORIES key order'));
  for (const c of cats) {
    assert.equal(typeof c.label, 'string', m('FR-SRCH', S, `${c.key}.label is a string`));
    assert.ok(c.label.length > 0, m('FR-SRCH', S, `${c.key}.label non-empty`));
    assert.equal(typeof c.glyph, 'string', m('FR-SRCH', S, `${c.key}.glyph is a string`));
    assert.ok(c.glyph.length > 0, m('FR-SRCH', S, `${c.key}.glyph non-empty`));
    assert.ok('kinds' in c, m('FR-SRCH', S, `${c.key} has kinds`));
    if (c.key !== 'all') assert.deepEqual(c.kinds, KIND_OF[c.key], m('FR-SRCH', S, `${c.key}.kinds`));
  }
  const byKey = {};
  for (const c of cats) byKey[c.key] = c;
  assert.deepEqual(byKey.inventory.kinds, ['device'], m('FR-SRCH', S, "inventory.kinds = ['device']"));
  assert.deepEqual(byKey.networks.kinds, ['network', 'interface'], m('FR-SRCH', S, "networks.kinds = ['network', 'interface']"));
  assert.equal(byKey.cables.label, 'Cables', m('FR-SRCH', S, 'cables label (No matches … in Cables.)'));
});

T('kindsFor(category) returns the category kinds; all means every kind or no filter', () => {
  const kindsFor = need(mod, 'kindsFor', 'FR-SRCH', S);
  for (const k of ORDER.slice(1)) assert.deepEqual(kindsFor(k), KIND_OF[k], m('FR-SRCH', S, `kindsFor(${k})`));
  const all = kindsFor('all');
  const noFilter = all === null || all === undefined || (Array.isArray(all) && all.length === 0);
  const every = Array.isArray(all) && ALL_KINDS.every((x) => all.indexOf(x) >= 0);
  assert.ok(noFilter || every, m('FR-SRCH', S, `kindsFor('all') is empty/null (no filter) or lists every kind, got ${JSON.stringify(all)}`));
});

// ------------------------------------------------------------------ categorize

T('categorize: serial / asset_tag device match is inventory, others by kind', () => {
  const categorize = need(mod, 'categorize', 'FR-SRCH', S);
  const d = fx();
  const serial = local(d, 'SQ5-004211').find((h) => h.kind === 'device');
  assert.ok(serial && serial.id === 'sound-board' && serial.match === 'serial', 'fixture: serial search hits sound-board');
  assert.equal(categorize(serial), 'inventory', m('FR-SRCH', S, 'serial match -> inventory'));
  const tag = local(d, 'HC-0012').find((h) => h.kind === 'device');
  assert.ok(tag && tag.match === 'asset_tag', 'fixture: asset tag search hits sound-board');
  assert.equal(categorize(tag), 'inventory', m('FR-SRCH', S, 'asset_tag match -> inventory'));
  const atem = local(d, 'atem')[0];
  assert.equal(atem.id, 'atem-mini');
  assert.equal(categorize(atem), 'devices', m('FR-SRCH', S, 'name match -> devices'));
  assert.equal(categorize(hit('device', 'sound-board', { device: 'sound-board', match: 'model' })), 'devices');
  const expect = {
    room: 'rooms', rack: 'racks', port: 'ports', cable: 'cables', interface: 'networks', network: 'networks',
    floorplan: 'plans', page: 'procedures', attachment: 'files',
  };
  for (const kind of Object.keys(expect)) {
    assert.equal(categorize(hit(kind, 'x-1')), expect[kind], m('FR-SRCH', S, `categorize(${kind})`));
  }
  assert.equal(categorize(hit('port', 'atem-mini:hdmi-in-1', { match: 'serial' })), 'ports', m('FR-SRCH', S, 'serial match only re-categorises devices'));
});

// ------------------------------------------------------------------ groupHits

function mixedHits() {
  const out = [];
  for (let i = 0; i < 9; i++) {
    out.push(hit('cable', 'c-' + i));
    out.push(hit('device', 'dev-' + i, { device: 'dev-' + i, match: i % 2 ? 'name' : 'model' }));
    if (i < 7) out.push(hit('port', 'dev-' + i + ':in-1', { device: 'dev-' + i, port: 'in-1' }));
  }
  out.push(hit('device', 'inv-1', { device: 'inv-1', match: 'serial' }));
  out.push(hit('network', 'av-lan'));
  out.push(hit('room', 'main'));
  out.push(hit('page', 'power-up'));
  out.push(hit('interface', 'dev-1/primary', { device: 'dev-1' }));
  out.push(hit('attachment', 'att-1'));
  out.push(hit('device', 'inv-2', { device: 'inv-2', match: 'asset_tag' }));
  out.push(hit('floorplan', 'fp-1'));
  out.push(hit('rack', 'rk-1'));
  out.push(hit('room', 'chapel'));
  out.push(hit('network', 'av-dante'));
  return out;
}

T('groupHits(all): CATEGORIES order, max 6 per group, rank order kept inside a group', () => {
  const groupHits = need(mod, 'groupHits', 'FR-SRCH', S);
  const hits = mixedHits();
  const groups = groupsOf(groupHits(hits, 'all'));
  assert.deepEqual(groups.map((g) => g.key),
    ['devices', 'inventory', 'rooms', 'racks', 'ports', 'cables', 'networks', 'plans', 'procedures', 'files'],
    m('FR-SRCH', S, 'group order follows CATEGORIES (all itself is not a group)'));
  const byKey = {};
  for (const g of groups) byKey[g.key] = keys(g.hits);
  const firstOf = (pred, n) => keys(hits.filter(pred).slice(0, n));
  const isDev = (h) => h.kind === 'device' && h.match !== 'serial' && h.match !== 'asset_tag';
  assert.deepEqual(byKey.devices, firstOf(isDev, 6), m('FR-SRCH', S, 'devices: first 6 in input order'));
  assert.deepEqual(byKey.cables, firstOf((h) => h.kind === 'cable', 6), m('FR-SRCH', S, 'cables capped at 6'));
  assert.deepEqual(byKey.ports, firstOf((h) => h.kind === 'port', 6), m('FR-SRCH', S, 'ports capped at 6'));
  assert.deepEqual(byKey.inventory, ['device:inv-1', 'device:inv-2'], m('FR-SRCH', S, 'serial/asset_tag devices grouped as inventory'));
  assert.deepEqual(byKey.networks, ['network:av-lan', 'interface:dev-1/primary', 'network:av-dante'], m('FR-SRCH', S, 'networks group holds network and interface hits'));
  assert.deepEqual(byKey.rooms, ['room:main', 'room:chapel']);
  assert.deepEqual(byKey.racks, ['rack:rk-1']);
  assert.deepEqual(byKey.plans, ['floorplan:fp-1']);
  assert.deepEqual(byKey.procedures, ['page:power-up']);
  assert.deepEqual(byKey.files, ['attachment:att-1']);
  for (const g of groups) assert.ok(g.hits.length <= 6, m('FR-SRCH', S, `${g.key} has at most 6 hits in all`));
});

T('groupHits(single category): one group, capped at 50', () => {
  const groupHits = need(mod, 'groupHits', 'FR-SRCH', S);
  const cables = [];
  for (let i = 0; i < 60; i++) cables.push(hit('cable', 'c-' + String(i).padStart(4, '0'), { score: 100 - i }));
  const g = groupsOf(groupHits(cables, 'cables'));
  assert.deepEqual(g.map((x) => x.key), ['cables'], m('FR-SRCH', S, 'single category -> one group'));
  assert.deepEqual(keys(g[0].hits), keys(cables.slice(0, 50)), m('FR-SRCH', S, 'single category capped at 50, rank order kept'));
  const devices = [];
  for (let i = 0; i < 55; i++) devices.push(hit('device', 'd-' + i, { device: 'd-' + i }));
  const gd = groupsOf(groupHits(devices, 'devices'));
  assert.deepEqual(gd.map((x) => x.key), ['devices']);
  assert.equal(gd[0].hits.length, 50, m('FR-SRCH', S, 'devices capped at 50'));
  const few = groupsOf(groupHits(cables.slice(0, 7), 'cables'));
  assert.equal(few[0].hits.length, 7, m('FR-SRCH', S, 'the 6 cap applies only to all'));
});

T('groupHits(inventory): every device hit is shown as an inventory item', () => {
  const groupHits = need(mod, 'groupHits', 'FR-SRCH', S);
  const devs = [
    hit('device', 'atem-mini', { device: 'atem-mini', match: 'name' }),
    hit('device', 'sound-board', { device: 'sound-board', match: 'serial' }),
    hit('device', 'restream', { device: 'restream', match: 'model' }),
    hit('device', 'spare-ulxd4d', { device: 'spare-ulxd4d', match: 'asset_tag' }),
  ];
  const g = groupsOf(groupHits(devs, 'inventory'));
  assert.deepEqual(g.map((x) => x.key), ['inventory'], m('FR-SRCH', S, 'inventory category -> one inventory group'));
  assert.deepEqual(keys(g[0].hits), keys(devs), m('FR-SRCH', S, 'all device hits, input order'));
  assert.deepEqual(groupsOf(groupHits([], 'all')), [], m('FR-SRCH', S, 'no hits -> no non-empty groups'));
});

// ------------------------------------------------------------------ augmentLocal

T('augmentLocal finds a network by name and by VLAN, keeping the §5.11 hit shape', () => {
  const augmentLocal = need(mod, 'augmentLocal', 'FR-SRCH', S);
  const d = fx();
  const byName = augmentLocal(d, 'AV LAN', 40);
  const lan = byName.find((h) => h.kind === 'network' && h.id === 'av-lan');
  assert.ok(lan, m('FR-SRCH', S, `"AV LAN" finds network av-lan, got ${JSON.stringify(keys(byName))}`));
  hitKeysOk(lan, 'network hit');
  assert.equal(lan.title, 'AV LAN', m('FR-SRCH', 'B.4', 'network title = name'));
  assert.equal(typeof lan.subtitle, 'string');
  assert.equal(lan.score, 100, m('FR-SRCH-04', S, 'exact name = 100'));
  assert.equal(lan.match, 'name', m('FR-SRCH', '§5.11', 'match names the field'));
  assert.ok(!byName.some((h) => h.kind === 'network' && h.id === 'av-dante'), m('FR-SRCH', S, '"AV LAN" does not hit av-dante'));

  const dante = augmentLocal(d, 'Dante primary', 40).find((h) => h.kind === 'network');
  assert.ok(dante && dante.id === 'av-dante' && dante.title === 'Dante primary', m('FR-SRCH', S, 'second network by name'));

  const byVlan = augmentLocal(d, '31', 40).find((h) => h.kind === 'network' && h.id === 'av-dante');
  assert.ok(byVlan, m('FR-SRCH', S, 'VLAN 31 finds av-dante'));
  assert.equal(byVlan.match, 'vlan', m('FR-SRCH', '§5.11', 'VLAN match field'));
  assert.equal(byVlan.score, 100, m('FR-SRCH-04', S, 'exact VLAN = 100'));
  const lan20 = augmentLocal(d, '20', 40).find((h) => h.kind === 'network' && h.id === 'av-lan');
  assert.ok(lan20, m('FR-SRCH', S, 'VLAN 20 finds av-lan'));
});

T('augmentLocal adds device status, keeps searchLocal results, ranking and limit', () => {
  const augmentLocal = need(mod, 'augmentLocal', 'FR-SRCH', S);
  const d = fx();
  delete d.devices.find((x) => x.id === 'restream').status;
  const before = clone(d);
  const atem = augmentLocal(d, 'atem', 40);
  assert.equal(atem[0].kind, 'device', m('FR-SRCH-04', S, '"atem" ranks a device first'));
  assert.equal(atem[0].id, 'atem-mini', m('FR-SRCH-04', S, '"atem" ranks ATEM Mini first'));
  assert.equal(atem[0].status, 'installed', m('FR-SRCH', S, 'device hit carries device.status'));
  for (const h of atem) hitKeysOk(h, 'augmentLocal hit');
  for (let i = 1; i < atem.length; i++) assert.ok(atem[i - 1].score >= atem[i].score, m('FR-SRCH-04', S, 'sorted by score'));
  const spare = augmentLocal(d, 'ULXD4D', 40).find((h) => h.kind === 'device' && h.id === 'spare-ulxd4d');
  assert.ok(spare, 'fixture: ULXD4D finds the spare');
  assert.equal(spare.status, 'spare', m('FR-SRCH', S, 'status = device.status'));
  const rs = augmentLocal(d, 'restream', 40).find((h) => h.kind === 'device' && h.id === 'restream');
  assert.ok(rs, 'fixture: restream device');
  assert.equal(rs.status || '', '', m('FR-SRCH', 'B.4', 'unset status -> empty'));
  const inv = augmentLocal(d, 'SQ5-004211', 40)[0];
  assert.ok(inv && inv.kind === 'device' && inv.id === 'sound-board' && inv.match === 'serial', m('FR-SRCH', S, 'serial match survives'));
  const cab = augmentLocal(d, 'A-003', 40)[0];
  assert.ok(cab && cab.kind === 'cable' && cab.id === 'c-0005', m('FR-SRCH', S, 'cable tag search as searchLocal'));
  const ip = augmentLocal(d, '10.20.0.40', 40).find((h) => h.kind === 'interface');
  assert.ok(ip && ip.id === 'atem-mini/primary', m('FR-SRCH', S, 'IP search as searchLocal'));
  assert.ok(augmentLocal(d, 'a', 3).length <= 3, m('FR-SRCH-03', S, 'limit respected'));
  assert.ok(augmentLocal(d, '20', 2).length <= 2, m('FR-SRCH-03', S, 'limit respected with network hits'));
  assert.deepEqual(d, before, m('FR-SRCH', 'D12', 'augmentLocal does not mutate the doc'));
  const bare = fx();
  delete bare.networks;
  assert.equal(augmentLocal(bare, 'atem', 40)[0].id, 'atem-mini', m('FR-SRCH', S, 'doc without networks'));
  assert.deepEqual(augmentLocal(d, '', 40), [], m('FR-SRCH', S, 'empty query -> []'));
});

// ------------------------------------------------------------------ mergeHits / roleFilter

T('mergeHits dedupes by kind:id', () => {
  const mergeHits = need(mod, 'mergeHits', 'FR-SRCH', S);
  const a = [
    hit('device', 'atem-mini', { score: 100 }),
    hit('cable', 'c-0005', { score: 80 }),
    hit('room', 'main', { score: 60 }),
  ];
  const b = [
    hit('network', 'av-lan', { score: 90 }),
    hit('device', 'atem-mini', { score: 100, status: 'installed' }),
    hit('device', 'main', { score: 40 }),
  ];
  const out = mergeHits(a, b);
  const k = keys(out);
  assert.equal(k.length, new Set(k).size, m('FR-SRCH', S, `no duplicate kind:id, got ${JSON.stringify(k)}`));
  assert.deepEqual(k.slice().sort(), ['cable:c-0005', 'device:atem-mini', 'device:main', 'network:av-lan', 'room:main'],
    m('FR-SRCH', S, 'every distinct kind:id kept (same id, different kind is distinct)'));
  const posA = keys(a).map((x) => k.indexOf(x));
  for (let i = 1; i < posA.length; i++) assert.ok(posA[i - 1] < posA[i], m('FR-SRCH', S, 'relative order of a is kept'));
  assert.deepEqual(keys(mergeHits([], b)), keys(b), m('FR-SRCH', S, 'merge into empty'));
  assert.deepEqual(keys(mergeHits(a, [])), keys(a), m('FR-SRCH', S, 'merge empty'));
});

T('roleFilter drops draft page hits for viewers only', () => {
  const roleFilter = need(mod, 'roleFilter', 'FR-SRCH', S);
  const hits = [
    hit('page', 'power-up', { status: 'published' }),
    hit('page', 'stream-check', { status: 'draft' }),
    hit('device', 'odd', { device: 'odd', status: 'draft' }),
    hit('cable', 'c-0005', { status: '' }),
  ];
  const snapshot = clone(hits);
  assert.deepEqual(keys(roleFilter(hits, 'viewer')), ['page:power-up', 'device:odd', 'cable:c-0005'],
    m('FR-SRCH', S, 'viewer: draft pages dropped, non-page hits kept'));
  assert.deepEqual(keys(roleFilter(hits, 'editor')), keys(hits), m('FR-SRCH', S, 'editor keeps drafts'));
  assert.deepEqual(keys(roleFilter(hits, 'admin')), keys(hits), m('FR-SRCH', S, 'admin keeps drafts'));
  assert.deepEqual(hits, snapshot, m('FR-SRCH', S, 'input not mutated'));
});

// ------------------------------------------------------------------ targetFor

T('targetFor: device, inventory and port', () => {
  const targetFor = need(mod, 'targetFor', 'FR-SRCH', S);
  const d = fx();
  const atem = local(d, 'atem')[0];
  assert.deepEqual(partial(targetFor(atem, ROUTE, d)), { view: 'devices', id: 'atem-mini', room: 'main' },
    m('FR-SRCH', S, 'device -> devices page in the device room'));
  const spare = local(d, 'ULXD4D').find((h) => h.kind === 'device');
  assert.deepEqual(partial(targetFor(spare, ROUTE, d)), { view: 'devices', id: 'spare-ulxd4d', room: 'chapel' },
    m('FR-SRCH', S, 'device without a room keeps route.room'));
  const inv = local(d, 'SQ5-004211').find((h) => h.kind === 'device');
  assert.deepEqual(partial(targetFor(inv, ROUTE, d)), { view: 'inventory', query: { sel: 'device:sound-board', sec: 'inventory' } },
    m('FR-SRCH', S, 'inventory (serial) -> inventory drawer'));
  const tag = local(d, 'HC-0012').find((h) => h.kind === 'device');
  assert.deepEqual(partial(targetFor(tag, ROUTE, d)), { view: 'inventory', query: { sel: 'device:sound-board', sec: 'inventory' } },
    m('FR-SRCH', S, 'inventory (asset tag) -> inventory drawer'));
  const port = local(d, 'SB-Video-1').find((h) => h.kind === 'port');
  assert.ok(port, 'fixture: port label search');
  assert.deepEqual(partial(targetFor(port, ROUTE, d)),
    { view: 'devices', id: port.device, tab: 'ports', query: { sel: 'port:' + port.device + ':' + port.port } },
    m('FR-SRCH', S, 'port -> device ports tab with port selection'));
});

T('targetFor: cable, interface, network', () => {
  const targetFor = need(mod, 'targetFor', 'FR-SRCH', S);
  const d = fx();
  const cab = local(d, 'A-003')[0];
  assert.deepEqual(partial(targetFor(cab, ROUTE, d)), { view: 'schedules', tab: 'cables', query: { sel: 'cable:c-0005' } },
    m('FR-SRCH', S, 'cable -> schedules/cables with selection'));
  const iface = local(d, '10.20.0.40').find((h) => h.kind === 'interface');
  assert.equal(iface.id, 'atem-mini/primary');
  assert.deepEqual(partial(targetFor(iface, ROUTE, d)), { view: 'devices', id: 'atem-mini', tab: 'network', query: { hl: 'primary' } },
    m('FR-SRCH', S, 'interface -> device network tab, hl = the interface id'));
  const net = hit('network', 'av-lan', { title: 'AV LAN', subtitle: 'VLAN 20 · 10.20.0.0/24' });
  assert.deepEqual(partial(targetFor(net, ROUTE, d)), { view: 'settings', tab: 'networks', query: { hl: 'av-lan' } },
    m('FR-SRCH', S, 'network -> settings/networks highlight'));
});

T('targetFor: room, rack, floorplan, attachment, page', () => {
  const targetFor = need(mod, 'targetFor', 'FR-SRCH', S);
  const d = fx();
  const room = local(d, 'Main Auditorium').find((h) => h.kind === 'room');
  assert.deepEqual(partial(targetFor(room, ROUTE, d)), { view: 'rooms', id: 'main', room: 'main' }, m('FR-SRCH', S, 'room -> room page'));
  const rack = local(d, 'FOH rack').find((h) => h.kind === 'rack');
  assert.deepEqual(partial(targetFor(rack, ROUTE, d)), { view: 'racks', id: 'rk-foh' }, m('FR-SRCH', S, 'rack -> rack page'));
  const fp = local(d, 'Main stage').find((h) => h.kind === 'floorplan');
  assert.ok(fp, 'fixture clone: floor plan hit');
  assert.deepEqual(partial(targetFor(fp, ROUTE, d)), { view: 'plan', id: 'fp-main-stage' }, m('FR-SRCH', S, 'floorplan -> plan canvas'));
  const att = local(d, 'ATEM manual').find((h) => h.kind === 'attachment');
  assert.ok(att && att.device === 'atem-mini', 'fixture clone: attachment hit with device');
  assert.deepEqual(partial(targetFor(att, ROUTE, d)), { view: 'devices', id: 'atem-mini', tab: 'files', query: { hl: 'att-atem-manual' } },
    m('FR-SRCH', S, 'attachment with a device -> device files tab'));
  const loose = local(d, 'Site map').find((h) => h.kind === 'attachment');
  assert.ok(loose && !loose.device, 'fixture clone: attachment without device');
  const r = targetFor(loose, ROUTE, d);
  assert.ok(r === null || r === undefined || Object.keys(partial(r)).length === 0,
    m('FR-SRCH', S, `attachment without a device keeps today's pick() behaviour (no navigation), got ${JSON.stringify(r)}`));
  const page = hit('page', 'power-up', { title: 'Power up', status: 'published' });
  assert.deepEqual(partial(targetFor(page, ROUTE, d)), { view: 'sop', query: { page: 'power-up' } }, m('FR-SRCH', S, 'page -> sop?page='));
});

// ------------------------------------------------------------------ recentHits / moveActive

// D8 storage shape {type: [{id, t}]}, newest first; also answers ctx.recent.list(type) -> ids (non-enumerable).
function recentOf(byType) {
  const r = {};
  for (const k of Object.keys(byType)) r[k] = byType[k].map((id, i) => ({ id: id, t: 1000 - i }));
  Object.defineProperty(r, 'list', { enumerable: false, value: (type) => (byType[type] || []).slice() });
  return r;
}

T('recentHits resolves ids to hits and drops unknown ids', () => {
  const recentHits = need(mod, 'recentHits', 'FR-SRCH', S);
  const d = fx();
  const recent = recentOf({
    device: ['restream', 'ghost-device', 'atem-mini'],
    room: ['main', 'nowhere'],
    rack: ['rk-foh'],
    page: ['power-up', 'no-such-page'],
  });
  const out = recentHits(d, recent);
  assert.ok(Array.isArray(out), m('FR-SRCH', S, 'recentHits returns a list of hits'));
  const k = keys(out);
  assert.deepEqual(k.slice().sort(), ['device:atem-mini', 'device:restream', 'page:power-up', 'rack:rk-foh', 'room:main'],
    m('FR-SRCH', S, `known ids resolved, unknown dropped, got ${JSON.stringify(k)}`));
  assert.ok(k.indexOf('device:restream') < k.indexOf('device:atem-mini'), m('FR-SRCH', 'D8', 'newest first within a type'));
  const byKey = {};
  for (const h of out) byKey[key(h)] = h;
  assert.equal(byKey['device:atem-mini'].title, 'ATEM Mini', m('FR-SRCH', '§5.11', 'device title = name'));
  assert.equal(byKey['room:main'].title, 'Main Auditorium', m('FR-SRCH', '§5.11', 'room title = name'));
  assert.equal(byKey['rack:rk-foh'].title, 'FOH rack', m('FR-SRCH', '§5.11', 'rack title = name'));
  assert.equal(byKey['page:power-up'].title, 'Power up', m('FR-SRCH', '§5.11', 'page hit id = slug, title = page title'));
  assert.deepEqual(recentHits(d, recentOf({})), [], m('FR-SRCH', S, 'no recents -> []'));
});

T('moveActive wraps both ways and handles count 0', () => {
  const moveActive = need(mod, 'moveActive', 'FR-SRCH', S);
  assert.equal(moveActive(5, 2, 1), 3, m('FR-SRCH', S, 'down'));
  assert.equal(moveActive(5, 2, -1), 1, m('FR-SRCH', S, 'up'));
  assert.equal(moveActive(5, 4, 1), 0, m('FR-SRCH', S, 'down from last wraps to first'));
  assert.equal(moveActive(5, 0, -1), 4, m('FR-SRCH', S, 'up from first wraps to last'));
  assert.equal(moveActive(5, -1, 1), 0, m('FR-SRCH', S, 'down from nothing active -> first'));
  assert.equal(moveActive(1, 0, 1), 0, m('FR-SRCH', S, 'single option, down'));
  assert.equal(moveActive(1, 0, -1), 0, m('FR-SRCH', S, 'single option, up'));
  let i = 0;
  for (const dlt of [1, 1, -1]) i = moveActive(3, i, dlt);
  assert.equal(i, 1, m('FR-SRCH', S, '↓ ↓ ↑ from 0 of 3 -> 1'));
  assert.equal(moveActive(0, 0, 1), -1, m('FR-SRCH', S, 'count 0 -> -1 (no active option)'));
  assert.equal(moveActive(0, -1, -1), -1, m('FR-SRCH', S, 'count 0 -> -1 (no active option)'));
});
