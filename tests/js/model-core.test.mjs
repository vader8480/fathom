// T2: js/model-core.js (W5) against SPEC §6.2, §4.4.3, §4.4.4, §4.9, §5.11.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  loadModule, loadFixtureDoc, loadVocab, sharedFixture, readJson, fixturePath,
  clone, norm, m, need, ids, toSet, canonDoc, device, cable, rng,
} from './fixtures/helpers.mjs';

const { mod: mc, skip: absent, error } = await loadModule('js/model-core.js', 'W5');
const pv = await loadModule('js/patchview-core.js', 'W3');
const S = '§6.2';
const skip = absent || (error ? 'model-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);

if (error) test('model-core.js imports in Node (§6.1 pure module)', () => { throw error; });

const vocab = loadVocab();
const fixture = loadFixtureDoc();
const fx = () => clone(fixture);

function apply(doc, ops) {
  const r = need(mc, 'applyOps', 'FR-PORT-03', '§4.9')(doc, ops);
  assert.ok(r && r.doc, m('§4.9', S, 'applyOps must return {doc, inverse, touched}'));
  return r.doc;
}

function asOps(x) {
  return Array.isArray(x) ? x : x && Array.isArray(x.ops) ? x.ops : x;
}

// ------------------------------------------------------------------ identifiers

T('COLLECTIONS and ROOTS constants', () => {
  assert.deepEqual(need(mc, 'COLLECTIONS', '§4.1', S),
    ['venues', 'rooms', 'systems', 'locations', 'racks', 'networks', 'devices', 'cables', 'bundles', 'floorplans', 'attachments', 'templates', 'imports', 'pages'],
    m('§4.1', S, 'COLLECTIONS order'));
  assert.deepEqual(need(mc, 'ROOTS', '§4.1', S), ['meta', 'settings', 'media']);
});

T('slug matches Python fathom.model.slug', () => {
  const slug = need(mc, 'slug', '§4.2', S);
  for (const v of readJson(fixturePath('slug-vectors.json'))) {
    assert.equal(slug(v.input), v.expected, m('§4.2', S, `slug(${JSON.stringify(v.input)})`));
  }
});

T('newId / portRef / parsePortRef', () => {
  const newId = need(mc, 'newId', '§4.2', S);
  const a = newId('c', new Set());
  assert.match(a, /^c-[a-z0-9]{8}$/, m('§4.2', S, 'newId(prefix) = prefix-8 random [a-z0-9]'));
  assert.equal(newId('c', [], 'Main Speakers'), 'main-speakers', m('§4.2', S, 'newId with base = slug(base)'));
  assert.equal(newId('c', new Set(['main-speakers']), 'Main Speakers'), 'main-speakers-2', m('§4.2', S, 'dedupe -2 (Set)'));
  assert.equal(newId('c', ['main-speakers', 'main-speakers-2'], 'Main Speakers'), 'main-speakers-3', m('§4.2', S, 'dedupe -3 (Array)'));
  assert.equal(newId('c', { 'main-speakers': {} }, 'Main Speakers'), 'main-speakers-2', m('§4.2', S, 'dedupe (Object)'));
  const portRef = need(mc, 'portRef', '§4.2', S);
  const parsePortRef = need(mc, 'parsePortRef', '§4.2', S);
  assert.equal(portRef('atem-mini', 'hdmi-in-1'), 'atem-mini:hdmi-in-1');
  assert.equal(portRef('atem-mini', null), 'atem-mini');
  assert.equal(portRef('atem-mini'), 'atem-mini');
  assert.deepEqual(norm(parsePortRef('atem-mini:hdmi-in-1')), { device: 'atem-mini', port: 'hdmi-in-1' });
  assert.deepEqual(norm(parsePortRef('atem-mini')), { device: 'atem-mini', port: null });
});

// ---------------------------------------------------------------- index & lookup

T('indexDoc on fixture', () => {
  const ix = need(mc, 'indexDoc', '§6.2', S)(fx());
  assert.equal(ix.byId.devices['atem-mini'].name, 'ATEM Mini', m('§6.2', S, 'byId.devices'));
  assert.equal(ix.byId.cables['c-0011'].medium, 'analog', m('§6.2', S, 'byId.cables'));
  assert.equal(ix.ports['atem-mini']['hdmi-in-1'].label, 'SB-Video-1', m('§6.2', S, 'ports[dev][port]'));
  assert.deepEqual(ids(ix.cablesByDevice['atem-mini']).sort(), ['c-0011', 'c-0012', 'c-0013', 'c-0015'], m('§6.2', S, 'cablesByDevice'));
  assert.deepEqual(ids(ix.cablesByPort['atem-mini:hdmi-in-1']), ['c-0012'], m('§6.2', S, 'cablesByPort'));
  assert.deepEqual(ids(ix.devicesByRoom['']), ['spare-ulxd4d'], m('FR-ROOM-02', S, 'devicesByRoom[""]'));
  assert.equal(ix.devicesByRoom.main.length, 11, m('FR-ROOM-02', S, 'devicesByRoom.main'));
});

T('devicePorts / portLabel / deviceTitle / disciplineOf / mediumInfo / carries', () => {
  const d = fx();
  assert.deepEqual(need(mc, 'devicePorts', S, S)({ id: 'x' }), [], m('§6.2', S, 'devicePorts always an array'));
  const portLabel = need(mc, 'portLabel', S, S);
  assert.equal(portLabel({ id: 'p', name: 'Input 1', label: 'Kick' }), 'Kick');
  assert.equal(portLabel({ id: 'p', name: 'Input 1' }), 'Input 1');
  assert.equal(portLabel({ id: 'p' }), 'p');
  const deviceTitle = need(mc, 'deviceTitle', S, S);
  assert.equal(deviceTitle(device(d, 'wireless-mics')), 'Wireless Mics ×2', m('§6.2', S, "name + ' ×count'"));
  assert.equal(deviceTitle(device(d, 'atem-mini')), 'ATEM Mini');
  const disciplineOf = need(mc, 'disciplineOf', '§4.4.2', S);
  assert.equal(disciplineOf(device(d, 'restream'), vocab), 'network', m('§4.4.2', S, 'kind stream -> network'));
  assert.equal(disciplineOf(device(d, 'atem-mini'), vocab), 'video');
  assert.equal(disciplineOf({ id: 'q', kind: 'mic', discipline: 'video' }, vocab), 'video', m('§4.4.2', S, 'device.discipline override'));
  assert.equal(disciplineOf({ id: 'q', kind: 'laser' }, vocab), 'other', m('§4.4.2', S, 'unknown kind -> other'));
  const mediumInfo = need(mc, 'mediumInfo', S, S);
  assert.equal(mediumInfo('hdmi', vocab).color, '#f59e0b');
  assert.deepEqual(mediumInfo('laser', vocab), vocab.media.other, m('FR-VOC-07', S, 'unknown medium -> other'));
  assert.deepEqual([...need(mc, 'carries', S, S)('hdmi', vocab)].sort(), ['audio', 'video']);
});

// ------------------------------------------------------------- port expansion

T('expandPortGroups vectors', (t) => {
  const expand = need(mc, 'expandPortGroups', 'FR-PORT-03', '§4.4.3');
  const shared = sharedFixture('port-expansion.json');
  assert.ok(shared, 'no port-expansion vectors found');
  t.diagnostic('vectors: ' + shared.source);
  assert.ok(shared.data.length >= 8, m('FR-PORT-03', '§4.4.3', 'at least 8 vectors'));
  for (const v of shared.data) {
    const groups = Array.isArray(v.input) ? v.input : v.input && v.input.groups ? v.input.groups : [v.input];
    let out = norm(expand(clone(groups), { v1: !!v.v1 }));
    if (v.fields) out = out.map((p) => Object.fromEntries(v.fields.filter((f) => f in p).map((f) => [f, p[f]])));
    assert.deepEqual(out, v.expected, m('FR-PORT-03', '§4.4.3', `vector ${v.name || JSON.stringify(groups).slice(0, 60)}`));
  }
});

T('expandPortGroups vectors (T2 set)', () => {
  const expand = need(mc, 'expandPortGroups', 'FR-PORT-03', '§4.4.3');
  for (const v of readJson(fixturePath('port-expansion.json'))) {
    let out = norm(expand(clone(v.input), { v1: !!v.v1 }));
    if (v.fields) out = out.map((p) => Object.fromEntries(v.fields.filter((f) => f in p).map((f) => [f, p[f]])));
    assert.deepEqual(out, v.expected, m('FR-PORT-03', '§4.4.3', `T2 vector ${v.name}`));
  }
});

// ----------------------------------------------------------------------- ops

T('mergePatch RFC 7396 vectors', () => {
  const mergePatch = need(mc, 'mergePatch', '§4.9', S);
  const cases = [
    [{ a: 'b' }, { a: 'c' }, { a: 'c' }],
    [{ a: 'b' }, { b: 'c' }, { a: 'b', b: 'c' }],
    [{ a: 'b' }, { a: null }, {}],
    [{ a: 'b', b: 'c' }, { a: null }, { b: 'c' }],
    [{ a: ['b'] }, { a: 'c' }, { a: 'c' }],
    [{ a: 'c' }, { a: ['b'] }, { a: ['b'] }],
    [{ a: { b: 'c' } }, { a: { b: 'd', c: null } }, { a: { b: 'd' } }],
    [{ a: [{ b: 'c' }] }, { a: [1] }, { a: [1] }],
    [['a', 'b'], ['c', 'd'], ['c', 'd']],
    [{ a: 'b' }, ['c'], ['c']],
    [{ a: 'foo' }, null, null],
    [{ a: 'foo' }, 'bar', 'bar'],
    [{ e: null }, { a: 1 }, { e: null, a: 1 }],
    [[1, 2], { a: 'b', c: null }, { a: 'b' }],
    [{}, { a: { bb: { ccc: null } } }, { a: { bb: {} } }],
  ];
  for (const [target, patch, expected] of cases) {
    const before = clone(target);
    const out = mergePatch(target, clone(patch));
    assert.deepEqual(out, expected, m('§4.9', S, `mergePatch(${JSON.stringify(before)}, ${JSON.stringify(patch)})`));
    assert.deepEqual(target, before, m('§4.9', S, 'mergePatch must not mutate its target'));
  }
});

T('applyOps shared vectors', (t) => {
  const applyOps = need(mc, 'applyOps', '§4.9', S);
  const shared = sharedFixture('ops-vectors.json');
  assert.ok(shared, 'no ops vectors found');
  t.diagnostic('vectors: ' + shared.source);
  assert.ok(shared.data.length >= 10, m('§4.9', S, 'at least 10 vectors'));
  for (const v of shared.data) {
    const label = v.name || JSON.stringify(v.ops).slice(0, 80);
    const doc = clone(v.doc);
    const errCode = v.error || v.expected_error;
    if (errCode) {
      assert.throws(() => applyOps(doc, clone(v.ops)), () => true, m('§4.9', S, `${label}: must throw ${errCode}`));
      continue;
    }
    const r = applyOps(doc, clone(v.ops));
    assert.deepEqual(norm(r.doc), norm(v.expected), m('§4.9', S, `${label}: resulting doc`));
    assert.deepEqual([...r.touched].sort(), [...v.touched].sort(), m('§4.9', S, `${label}: touched refs`));
    assert.deepEqual(doc, v.doc, m('§4.9', S, `${label}: input doc must not be mutated (pure)`));
    // inverse restores (collection order may differ after undoing a delete: compare canonically)
    const back = applyOps(r.doc, r.inverse).doc;
    assert.deepEqual(canonDoc(back), canonDoc(v.doc), m('§4.9', S, `${label}: applying inverse restores the doc`));
  }
});

T('applyOps vectors (T2 set)', () => {
  const applyOps = need(mc, 'applyOps', '§4.9', S);
  for (const v of readJson(fixturePath('ops-vectors.json'))) {
    if (v.error) {
      assert.throws(() => applyOps(clone(v.doc), clone(v.ops)), () => true, m('§4.9', S, `T2 vector ${v.name}: must throw ${v.error}`));
      continue;
    }
    const r = applyOps(clone(v.doc), clone(v.ops));
    assert.deepEqual(norm(r.doc), norm(v.expected), m('§4.9', S, `T2 vector ${v.name}: resulting doc`));
    assert.deepEqual([...r.touched].sort(), [...v.touched].sort(), m('§4.9', S, `T2 vector ${v.name}: touched`));
    assert.deepEqual(canonDoc(applyOps(r.doc, r.inverse).doc), canonDoc(v.doc), m('§4.9', S, `T2 vector ${v.name}: inverse`));
  }
});

T('invertOps restores the original doc', () => {
  const applyOps = need(mc, 'applyOps', '§4.9', S);
  const invertOps = need(mc, 'invertOps', '§4.9', S);
  const shared = sharedFixture('ops-vectors.json');
  for (const v of shared.data) {
    if (v.error || v.expected_error) continue;
    const inv = invertOps(clone(v.doc), clone(v.ops));
    assert.ok(Array.isArray(inv), m('§4.9', S, 'invertOps returns an ops array'));
    const fwd = applyOps(clone(v.doc), clone(v.ops)).doc;
    const back = applyOps(fwd, inv).doc;
    assert.deepEqual(canonDoc(back), canonDoc(v.doc), m('§4.9', S, `invertOps: ${v.name || ''}`));
  }
  // root inverse uses replace:true
  const d = fx();
  const inv = invertOps(d, [{ op: 'root', key: 'settings', value: { units: 'metric' } }]);
  const rootInv = inv.find((o) => o.op === 'root');
  assert.ok(rootInv && rootInv.replace === true, m('§4.9', S, 'root inverse = {op:"root", replace:true}'));
  assert.deepEqual(rootInv.value, d.settings);
});

T('diffDocs round-trip', () => {
  const diffDocs = need(mc, 'diffDocs', '§4.9', S);
  const a = fx();
  const b = clone(a);
  device(b, 'atem-mini').name = 'Switcher';
  b.cables = b.cables.filter((c) => c.id !== 'c-0010');
  b.devices.push({ id: 'new-dev', name: 'New', kind: 'other', ports: [] });
  b.settings.units = 'metric';
  const ops = diffDocs(a, b);
  const byRef = Object.fromEntries(ops.map((o) => [o.op === 'root' ? o.key : `${o.coll}/${o.id}`, o]));
  assert.equal(byRef['cables/c-0010'] && byRef['cables/c-0010'].op, 'del', m('§4.9', S, 'del for ids missing in b'));
  assert.equal(byRef['devices/atem-mini'] && byRef['devices/atem-mini'].op, 'put', m('§4.9', S, 'put for changed entities'));
  assert.equal(byRef['devices/new-dev'] && byRef['devices/new-dev'].op, 'put', m('§4.9', S, 'put for new entities'));
  assert.ok(byRef.settings && byRef.settings.op === 'root' && byRef.settings.replace === true, m('§4.9', S, 'root replace:true for changed roots'));
  assert.equal(ops.length, 4, m('§4.9', S, 'unchanged entities produce no ops'));
  assert.deepEqual(canonDoc(apply(a, ops)), canonDoc(b), m('§4.9', S, 'applyOps(a, diffDocs(a,b)) == b'));
  assert.deepEqual(diffDocs(a, clone(a)), [], m('§4.9', S, 'diff of equal docs is empty'));
});

// ------------------------------------------------------------ connection rules

function ep(device, port) {
  return port === undefined ? { device } : { device, port };
}

T('canConnect', () => {
  const canConnect = need(mc, 'canConnect', 'FR-PORT-04', '§4.4.4');
  const d = fx();
  const chk = (from, to, level, code, why) => {
    const r = canConnect(d, from, to, vocab);
    assert.equal(r.level, level, m('FR-PORT-04', '§4.4.4', `${why}: level`));
    if (code) assert.equal(r.code, code, m('FR-PORT-04', '§4.4.4', `${why}: code`));
    assert.equal(r.ok, level !== 'error', m('FR-PORT-04', '§4.4.4', `${why}: ok`));
    return r;
  };
  chk(ep('audio-rack-1', 'analog-out-3'), ep('sub-x2', 'analog-in-2'), 'ok', null, 'out -> in');
  chk(ep('audio-rack-1', 'analog-out-3'), ep('audio-rack-1', 'dsnake'), 'warn', 'medium_mismatch', 'out -> io allowed (analog -> snake: carries intersect)');
  chk(ep('sound-board', 'slink'), ep('atem-mini', 'hdmi-in-2'), 'warn', null, 'io -> in (medium differs, still allowed)');
  chk(ep('audio-rack-1', 'analog-in-5'), ep('sub-x2', 'analog-in-2'), 'error', 'bad_direction', 'in -> in refused');
  chk(ep('audio-rack-1', 'analog-out-3'), ep('main-speakers', 'thru-1'), 'error', 'bad_direction', 'out -> out refused');
  chk(ep('sound-board', 'slink'), ep('sound-board', 'slink'), 'error', 'self_loop', 'same device, same port');
  chk(ep('atem-mini', 'hdmi-out-1'), ep('video-converter', 'sdi-in-1'), 'warn', 'medium_mismatch', 'HDMI -> SDI (carries intersect)');
  chk(ep('audio-rack-1', 'analog-out-3'), ep('sub-x2', 'analog-in-1'), 'warn', 'port_overuse', 'in port already has 1 cable (channels 1)');
  chk(ep('stage-box-1'), ep('atem-mini', 'hdmi-in-2'), 'ok', null, 'device-level endpoint -> in port');
  const d2 = fx();
  d2.devices.push({ id: 'dmx-node', name: 'DMX Node', kind: 'dmx_node', ports: [{ id: 'dmx-out-1', name: 'DMX Out 1', dir: 'out', medium: 'dmx' }] });
  const r = canConnect(d2, ep('dmx-node', 'dmx-out-1'), ep('sub-x2', 'analog-in-2'), vocab);
  assert.equal(r.level, 'warn', m('FR-PORT-04', '§4.4.4', 'disjoint media: warn'));
  assert.equal(r.code, 'medium_incompatible', m('FR-PORT-04', '§4.4.4', 'disjoint carries -> medium_incompatible'));
});

T('connectOps', () => {
  const connectOps = need(mc, 'connectOps', 'FR-PV-04', S);
  const d = fx();
  const from = ep('audio-rack-1', 'analog-out-3');
  const to = ep('sub-x2', 'analog-in-2');
  const ops = asOps(connectOps(d, from, to, {}, vocab));
  assert.equal(ops.length, 1, m('FR-PV-04', S, 'exactly one op'));
  const op = ops[0];
  assert.equal(op.op, 'put', m('FR-PV-04', S, 'one put cable op'));
  assert.equal(op.coll, 'cables');
  assert.match(op.id, /^c-[a-z0-9]{8}$/, m('FR-PV-04', '§4.2', 'new cable id c- + 8 random [a-z0-9]'));
  assert.equal(op.value.id, op.id, m('FR-PV-04', '§4.9', 'value.id must equal id'));
  assert.deepEqual(norm(op.value.from), from, m('FR-PV-04', S, 'from endpoint'));
  assert.deepEqual(norm(op.value.to), to, m('FR-PV-04', S, 'to endpoint'));
  assert.equal(op.value.medium, 'analog', m('FR-PV-04', '§4.3.10', 'medium defaults from the from-port'));
  assert.deepEqual(d, fixture, m('FR-PV-04', S, 'connectOps must not mutate the doc'));
  const ops2 = asOps(connectOps(d, ep('stage-box-1'), ep('atem-mini', 'hdmi-in-2'), { id: 'c-test' }, vocab));
  assert.equal(ops2[0].id, 'c-test', m('FR-PV-04', S, 'opts.id honoured'));
  assert.equal(ops2[0].value.medium, 'hdmi', m('FR-PV-04', '§4.3.10', 'device-level from: medium from the to-port'));
  const d3 = apply(d, ops2);
  assert.equal(cable(d3, 'c-test').to.port, 'hdmi-in-2');
});

T('disconnectOps', () => {
  const ops = asOps(need(mc, 'disconnectOps', 'FR-PV-05', S)(fx(), 'c-0011'));
  assert.deepEqual(norm(ops), [{ op: 'del', coll: 'cables', id: 'c-0011' }], m('FR-PV-05', S, 'one del op'));
});

T('repatchOps', () => {
  const repatchOps = need(mc, 'repatchOps', 'FR-PV-05', S);
  const d = fx();
  const before = clone(cable(d, 'c-0011'));
  const d2 = apply(d, asOps(repatchOps(d, 'c-0011', 'to', ep('atem-mini', 'hdmi-in-2'))));
  const after = cable(d2, 'c-0011');
  assert.deepEqual(norm(after.to), ep('atem-mini', 'hdmi-in-2'), m('FR-PV-05', S, 'dragged end moved'));
  assert.deepEqual(after.from, before.from, m('FR-PV-05', S, 're-patch changes only the dragged end'));
  assert.equal(after.type, before.type, m('FR-PV-05', S, 'other cable fields kept'));
  assert.equal(after.length_m, before.length_m);
  assert.equal(d2.cables.length, d.cables.length);
  const d3 = apply(d, asOps(repatchOps(d, 'c-0011', 'from', ep('audio-rack-1', 'analog-out-3'))));
  assert.deepEqual(norm(cable(d3, 'c-0011').from), ep('audio-rack-1', 'analog-out-3'));
  assert.deepEqual(cable(d3, 'c-0011').to, before.to, m('FR-PV-05', S, 'from-end repatch keeps to'));
});

T('deleteDeviceOps', () => {
  const deleteDeviceOps = need(mc, 'deleteDeviceOps', 'FR-PV-11', S);
  const d = fx();
  d.floorplans.push({ id: 'fp-main', name: 'Main', room: 'main', source: { attachment: 'att-1', kind: 'png' }, image: { attachment: 'att-1', kind: 'png', width: 100, height: 100 },
    markers: [{ device: 'atem-mini', x: 0.5, y: 0.5 }, { device: 'sound-board', x: 0.2, y: 0.2 }] });
  d.rooms[0].flow.extra_cards = [{ id: 'atem-mini-ref', device: 'atem-mini' }, { id: 'sb-ref', device: 'sound-board' }];
  const d2 = apply(d, asOps(deleteDeviceOps(d, 'atem-mini')));
  assert.equal(device(d2, 'atem-mini'), undefined, m('FR-PV-11', S, 'device removed'));
  const gone = ['c-0011', 'c-0012', 'c-0013', 'c-0015'];
  assert.deepEqual(d2.cables.filter((c) => gone.includes(c.id)), [], m('FR-PV-11', S, 'its cables removed'));
  assert.equal(d2.cables.length, 11, m('FR-PV-11', S, 'other cables kept'));
  assert.deepEqual(norm(d2.floorplans[0].markers), [{ device: 'sound-board', x: 0.2, y: 0.2 }], m('FR-PV-11', S, 'its floor-plan markers removed, others kept'));
  assert.deepEqual(ids(d2.rooms[0].flow.extra_cards), ['sb-ref'], m('FR-PV-11', S, 'its extra map cards removed, others kept'));
});

T('duplicateDeviceOps', () => {
  const r = need(mc, 'duplicateDeviceOps', 'FR-PV-11', S)(fx(), 'atem-mini', {});
  assert.ok(r && Array.isArray(r.ops) && typeof r.id === 'string', m('FR-PV-11', S, 'returns {ops, id}'));
  assert.notEqual(r.id, 'atem-mini');
  const d2 = apply(fx(), r.ops);
  const dup = device(d2, r.id);
  assert.ok(dup, m('FR-PV-11', S, 'duplicate exists'));
  assert.deepEqual(dup.ports, device(fixture, 'atem-mini').ports, m('FR-PV-11', S, 'copies ports'));
  assert.equal(d2.cables.length, 15, m('FR-PV-11', S, 'does not copy cables'));
  assert.deepEqual(norm({ x: dup.patch.x, y: dup.patch.y }), { x: 724, y: 324 }, m('FR-PV-11', S, 'patch offset +24,+24'));
  assert.equal(new Set(d2.devices.map((x) => x.id)).size, d2.devices.length, 'ids stay unique');
});

T('renameOps', () => {
  const renameOps = need(mc, 'renameOps', 'FR-PV-06', S);
  const d = fx();
  let d2 = apply(d, asOps(renameOps(d, { coll: 'devices', id: 'atem-mini' }, 'Switcher')));
  assert.equal(device(d2, 'atem-mini').name, 'Switcher', m('FR-PV-06', S, 'device rename sets name'));
  d2 = apply(d, asOps(renameOps(d, { coll: 'devices', id: 'atem-mini', port: 'hdmi-in-2' }, 'Cam 2')));
  const p = device(d2, 'atem-mini').ports.find((x) => x.id === 'hdmi-in-2');
  assert.equal(p.label, 'Cam 2', m('FR-PV-06', S, 'port rename sets label'));
  assert.equal(p.name, 'Input 2', m('FR-PV-06', S, 'port name unchanged'));
  d2 = apply(d, asOps(renameOps(d, { coll: 'devices', id: 'atem-mini', port: 'hdmi-in-1' }, '')));
  const p2 = device(d2, 'atem-mini').ports.find((x) => x.id === 'hdmi-in-1');
  assert.ok(!p2.label, m('FR-PV-06', S, 'empty label clears to name'));
  assert.equal(need(mc, 'portLabel', S, S)(p2), 'Input 1');
});

T('addDeviceFromTemplateOps', () => {
  const add = need(mc, 'addDeviceFromTemplateOps', 'FR-PV-11', S);
  const tpl = {
    id: 'blackmagic-atem-mini-pro', manufacturer: 'Blackmagic Design', model: 'ATEM Mini Pro', name: 'ATEM Mini Pro', kind: 'video_switcher', brand: 'blackmagic',
    ports: [
      { group: 'HDMI In', dir: 'in', medium: 'hdmi', connector: 'HDMI-A', count: 4 },
      { group: 'Mic In', dir: 'in', medium: 'analog', connector: 'TRS 3.5mm', count: 2 },
      { group: 'HDMI Out', dir: 'out', medium: 'hdmi', connector: 'HDMI-A' },
      { group: 'USB', dir: 'out', medium: 'usb', connector: 'USB-C' },
    ],
  };
  const d = fx();
  const r = add(d, clone(tpl), { room: 'main', name: 'ATEM 2', x: 96, y: 200 });
  assert.ok(r && Array.isArray(r.ops) && r.id, m('FR-PV-11', S, 'returns {ops, id}'));
  const d2 = apply(d, r.ops);
  const dev = device(d2, r.id);
  assert.ok(dev, m('FR-PV-11', S, 'device added'));
  assert.deepEqual(dev.ports.map((p) => p.id), ['hdmi-in-1', 'hdmi-in-2', 'hdmi-in-3', 'hdmi-in-4', 'mic-in-1', 'mic-in-2', 'hdmi-out', 'usb'],
    m('FR-PV-11', '§4.4.3', "card gets the template's expanded ports"));
  assert.equal(dev.template, tpl.id, m('FR-PV-11', '§4.5', 'template id recorded'));
  assert.equal(dev.kind, 'video_switcher');
  assert.equal(dev.manufacturer, 'Blackmagic Design');
  assert.equal(dev.model, 'ATEM Mini Pro');
  assert.equal(dev.room, 'main', m('FR-PV-11', S, 'opts.room'));
  assert.equal(dev.name, 'ATEM 2', m('FR-PV-11', S, 'opts.name'));
  assert.deepEqual(norm({ x: dev.patch && dev.patch.x, y: dev.patch && dev.patch.y }), { x: 96, y: 200 }, m('FR-PV-11', S, 'placed at opts.x, opts.y'));
  assert.ok(!device(d, r.id), 'input doc untouched');
});

T('setPortsOps', () => {
  const ports = [{ id: 'in-a', name: 'In A', dir: 'in', medium: 'analog' }];
  const d2 = apply(fx(), asOps(need(mc, 'setPortsOps', 'FR-PORT-06', S)(fx(), 'sub-x2', ports)));
  assert.deepEqual(norm(device(d2, 'sub-x2').ports), ports, m('FR-PORT-06', S, 'ports replaced'));
});

// --------------------------------------------------------------- filtering

T('filterDevices shared inventory', () => {
  const filterDevices = need(mc, 'filterDevices', 'FR-ROOM-02', S);
  assert.deepEqual(ids(filterDevices(fx(), { room: '' }, vocab)), ['spare-ulxd4d'], m('FR-ROOM-02', S, 'room "" = shared inventory'));
});

T('filterDevices room / system / status / state / query', () => {
  const f = need(mc, 'filterDevices', 'FR-ROOM-08', S);
  assert.equal(f(fx(), { room: '*' }, vocab).length, 12, m('FR-ROOM-03', S, "room '*' = all rooms"));
  assert.equal(f(fx(), { room: 'main' }, vocab).length, 11, m('FR-ROOM-03', S, 'room main'));
  assert.deepEqual(ids(f(fx(), { room: '*', system: 'main-video' }, vocab)).sort(), ['atem-mini', 'restream', 'samsung-tv-1', 'video-converter'],
    m('FR-ROOM-08', S, 'system main-video = exactly 4 devices'));
  assert.deepEqual(ids(f(fx(), { room: '*', statuses: ['spare'] }, vocab)), ['spare-ulxd4d'], m('FR-PLN-01', S, 'statuses filter'));
  const d = fx();
  device(d, 'restream').status = 'planned';
  device(d, 'sub-x2').status = 'retired';
  const asBuilt = ids(f(d, { room: '*', state: 'as_built' }, vocab));
  assert.ok(!asBuilt.includes('restream'), m('FR-PLN-01', '§4.4.6', 'as_built excludes planned'));
  assert.ok(!asBuilt.includes('spare-ulxd4d'), m('FR-PLN-01', '§4.4.6', 'as_built excludes spares'));
  const planned = ids(f(d, { room: '*', state: 'planned' }, vocab));
  assert.ok(planned.includes('restream') && !planned.includes('sub-x2'), m('FR-PLN-01', '§4.4.6', 'planned = planned + installed'));
  const all = ids(f(d, { room: '*', state: 'all' }, vocab));
  assert.ok(all.includes('spare-ulxd4d') && !all.includes('sub-x2'), m('FR-PLN-01', '§4.4.6', 'all = everything except retired'));
  assert.deepEqual(ids(f(fx(), { room: '*', query: 'atem' }, vocab)), ['atem-mini'], m('FR-PV-10', S, 'text query'));
});

T('external ghost devices', (t) => {
  const d = fx();
  d.rooms.push({ id: 'chapel', venue: 'hillside', name: 'Chapel' });
  const d2 = apply(d, [{ op: 'merge', coll: 'devices', id: 'atem-mini', value: { room: 'chapel' } }]);
  const inMain = ids(need(mc, 'filterDevices', 'FR-ROOM-05', S)(d2, { room: 'main' }, vocab));
  assert.ok(!inMain.includes('atem-mini'), m('FR-ROOM-05', S, 'moved device leaves the room filter'));
  assert.equal(d2.cables.length, 15, m('FR-ROOM-05', S, 'moving keeps its cables'));
  if (!pv.mod) { t.diagnostic('patchview-core.js absent (W3): ghost card part skipped'); return; }
  const scene = need(pv.mod, 'buildScene', 'FR-ROOM-05', '§6.5')(d2, null, vocab, { room: 'main' }, {});
  const ghost = scene.cards.find((c) => c.id === 'atem-mini');
  assert.ok(ghost, m('FR-ROOM-05', '§6.5', 'main room shows a ghost card for atem-mini'));
  assert.equal(ghost.external, true, m('FR-ROOM-05', '§6.5', 'ghost card is external'));
  const w = scene.wires.map((x) => x.cable && x.cable.id ? x.cable.id : x.id);
  for (const c of ['c-0011', 'c-0012', 'c-0013', 'c-0015']) assert.ok(w.includes(c), m('FR-ROOM-05', '§6.5', `ghost keeps cable ${c}`));
});

// -------------------------------------------------------------------- search

function hitKeysOk(h) {
  for (const k of ['kind', 'id', 'device', 'port', 'title', 'subtitle', 'room', 'score', 'match']) {
    assert.ok(k in h, m('FR-SRCH-03', '§5.11', `hit missing key ${k}`));
  }
}

T('searchLocal', () => {
  const searchLocal = need(mc, 'searchLocal', 'FR-SRCH-03', S);
  const d = fx();
  const ip = searchLocal(d, '10.20.0.40', 20);
  const iface = ip.find((h) => h.kind === 'interface');
  assert.ok(iface, m('FR-SRCH-01', '§5.11', '10.20.0.40 finds an interface'));
  assert.equal(iface.id, 'atem-mini/primary', m('FR-SRCH-01', '§5.11', 'interface id = <device>/<interface>'));
  assert.equal(iface.device, 'atem-mini');
  hitKeysOk(iface);
  const port = searchLocal(d, 'SB-Video-1', 20).find((h) => h.kind === 'port');
  assert.ok(port, m('FR-SRCH-01', S, 'port label search'));
  assert.ok(['atem-mini:hdmi-in-1', 'stage-box-1:hdmi-out-1'].includes(port.id), m('FR-SRCH-01', '§5.11', 'port id = <device>:<port>'));
  const cab = searchLocal(d, 'A-003', 20)[0];
  assert.ok(cab && cab.kind === 'cable' && cab.id === 'c-0005', m('FR-SRCH-01', S, 'cable tag search'));
  assert.ok(searchLocal(d, 'a', 3).length <= 3, m('FR-SRCH-03', S, 'limit respected'));
});

T('searchLocal ranking', () => {
  const searchLocal = need(mc, 'searchLocal', 'FR-SRCH-04', S);
  const d = fx();
  const atem = searchLocal(d, 'atem', 20);
  assert.equal(atem[0].kind, 'device', m('FR-SRCH-04', S, '"atem" ranks a device first'));
  assert.equal(atem[0].id, 'atem-mini', m('FR-SRCH-04', S, '"atem" ranks ATEM Mini first'));
  hitKeysOk(atem[0]);
  for (let i = 1; i < atem.length; i++) assert.ok(atem[i - 1].score >= atem[i].score, m('FR-SRCH-04', S, 'sorted by score'));
  const exact = searchLocal(d, 'ATEM Mini', 20)[0];
  assert.equal(exact.id, 'atem-mini');
  assert.equal(exact.score, 100, m('FR-SRCH-04', S, 'exact = 100'));
  const prefix = searchLocal(d, 'Restr', 20).find((h) => h.kind === 'device');
  assert.ok(prefix && prefix.id === 'restream' && prefix.score === 80, m('FR-SRCH-04', S, `prefix = 80, got ${JSON.stringify(prefix)}`));
  const fuzzy = searchLocal(d, 'restreem', 20).find((h) => h.id === 'restream');
  assert.ok(fuzzy && fuzzy.score === 25, m('FR-SRCH-04', S, `fuzzy (edit distance 1, token >= 4) = 25, got ${JSON.stringify(fuzzy)}`));
});

// ------------------------------------------------------------------ validation

T('validateLocal fixture is clean', () => {
  const v = need(mc, 'validateLocal', '§4.7', S)(fx(), vocab);
  assert.deepEqual(v, [], m('Appendix B', S, 'validateLocal(fixture) must be []'));
});

T('validateLocal problems', () => {
  const validateLocal = need(mc, 'validateLocal', '§4.7', S);
  const codes = (d) => validateLocal(d, vocab).map((p) => `${p.level}:${p.code}`);
  let d = fx();
  d.cables.push({ id: 'c-x1', from: { device: 'ghost', port: 'p' }, to: { device: 'sub-x2', port: 'analog-in-2' }, medium: 'analog' });
  assert.ok(codes(d).includes('error:dangling_ref'), m('§4.7', S, 'dangling cable device -> error dangling_ref'));
  d = fx();
  d.cables.push({ id: 'c-x2', from: { device: 'sub-x2', port: 'analog-in-2' }, to: { device: 'audio-rack-1', port: 'analog-in-5' }, medium: 'analog' });
  assert.ok(codes(d).includes('warning:bad_direction'), m('§4.7', S, 'cable from an in port -> warning bad_direction'));
  d = fx();
  d.cables.push({ id: 'c-x3', from: { device: 'audio-rack-1', port: 'analog-out-3' }, to: { device: 'sub-x2', port: 'analog-in-1' }, medium: 'analog' });
  assert.ok(codes(d).includes('warning:port_overuse'), m('FR-PORT-04', '§4.7', 'second cable into a 1-channel in port -> port_overuse'));
  d = fx();
  d.cables.push({ id: 'c-x4', from: { device: 'atem-mini', port: 'hdmi-out-1' }, to: { device: 'video-converter', port: 'sdi-in-1' }, medium: 'hdmi' });
  assert.ok(codes(d).includes('warning:medium_mismatch'), m('§4.7', S, 'hdmi -> sdi -> medium_mismatch'));
  const p = validateLocal(d, vocab)[0];
  for (const k of ['level', 'code', 'ref', 'message']) assert.ok(k in p, m('§4.7', S, `Problem has ${k}`));
});

// ------------------------------------------------------------------- units

T('formatLength', () => {
  const formatLength = need(mc, 'formatLength', '§4.1', S);
  assert.equal(formatLength(5, 'metric'), '5 m', m('§4.1', S, 'formatLength(5, metric)'));
  assert.equal(formatLength(5, 'imperial'), '16.4 ft', m('§4.1', S, 'formatLength(5, imperial)'));
});

// ------------------------------------------------------------------ viewport

T('viewport math', () => {
  const vp = need(mc, 'viewport', 'FR-PV-07', S);
  const close = (a, b, why) => assert.ok(Math.abs(a - b) < 1e-6, m('FR-PV-07', S, `${why}: ${a} vs ${b}`));
  const v0 = { x: 30, y: -12, k: 1.5 };
  const w = vp.screenToWorld(v0, { x: 100, y: 50 });
  const s = vp.worldToScreen(v0, w);
  close(s.x, 100, 'screen<->world x'); close(s.y, 50, 'screen<->world y');
  const z = vp.zoomAt(v0, { x: 200, y: 120 }, 2, 0.15, 3);
  close(z.k, 3, 'zoomAt factor applied (1.5*2 = 3)');
  const w1 = vp.screenToWorld(v0, { x: 200, y: 120 });
  const w2 = vp.screenToWorld(z, { x: 200, y: 120 });
  close(w1.x, w2.x, 'zoomAt keeps pt fixed (x)'); close(w1.y, w2.y, 'zoomAt keeps pt fixed (y)');
  close(vp.zoomAt(v0, { x: 0, y: 0 }, 10, 0.15, 3).k, 3, 'zoomAt clamps to max');
  close(vp.clampK(5, 0.15, 3), 3, 'clampK max'); close(vp.clampK(0.01, 0.15, 3), 0.15, 'clampK min'); close(vp.clampK(1, 0.15, 3), 1, 'clampK inside');
  const f = vp.fit({ x: 0, y: 0, w: 1000, h: 500 }, { w: 520, h: 520 }, 10);
  const c = vp.worldToScreen(f, { x: 500, y: 250 });
  close(c.x, 260, 'fit centres bounds (x)'); close(c.y, 260, 'fit centres bounds (y)');
  const tl = vp.worldToScreen(f, { x: 0, y: 0 });
  const br = vp.worldToScreen(f, { x: 1000, y: 500 });
  assert.ok(tl.x >= 10 - 1e-6 && br.x <= 510 + 1e-6, m('FR-PV-07', S, 'fit keeps bounds inside size minus margin'));
});

// --------------------------------------------------------------------- store

function mkStore(opts) {
  const createStore = need(mc, 'createStore', 'FR-PV-08', S);
  return createStore(Object.assign({ doc: fx(), vocab, readOnly: false, overlay: null, room: 'main' }, opts || {}));
}

function listen(store, type) {
  const got = [];
  store.addEventListener(type, (e) => got.push(e.detail));
  return got;
}

T('store commit / undo / redo basics', () => {
  const st = mkStore();
  assert.ok(st instanceof EventTarget, m('FR-PV-08', S, 'Store extends EventTarget'));
  assert.equal(st.canUndo, false);
  const docEv = listen(st, 'doc');
  const ops = [{ op: 'merge', coll: 'devices', id: 'atem-mini', value: { name: 'Switcher' } }];
  const ret = st.commit(ops, 'Rename');
  assert.equal(device(st.doc, 'atem-mini').name, 'Switcher', m('FR-PV-08', S, 'commit applies ops'));
  assert.equal(device(ret, 'atem-mini').name, 'Switcher', m('FR-PV-08', S, 'commit returns the new doc'));
  assert.equal(docEv.length, 1, m('FR-PV-08', S, 'commit emits doc'));
  assert.equal(docEv[0].source, 'local', m('FR-PV-08', S, "doc event source 'local'"));
  assert.equal(docEv[0].label, 'Rename');
  assert.deepEqual(norm(docEv[0].ops), ops);
  assert.ok(Array.isArray(docEv[0].inverse), m('FR-PV-08', S, 'doc event carries inverse'));
  assert.equal(st.canUndo, true); assert.equal(st.undoLabel, 'Rename');
  st.undo();
  assert.equal(device(st.doc, 'atem-mini').name, 'ATEM Mini', m('FR-PV-08', S, 'undo restores'));
  assert.equal(docEv[1].source, 'undo', m('FR-PV-08', S, "undo emits doc with source 'undo'"));
  assert.ok(docEv[1].ops.length > 0, m('FR-PV-08', S, 'undo ops are emitted (sent to the server)'));
  assert.equal(st.canRedo, true); assert.equal(st.redoLabel, 'Rename');
  st.redo();
  assert.equal(device(st.doc, 'atem-mini').name, 'Switcher', m('FR-PV-08', S, 'redo re-applies'));
  assert.equal(docEv[2].source, 'redo');
  st.undo();
  st.commit([{ op: 'merge', coll: 'devices', id: 'sub-x2', value: { name: 'Subs' } }], 'Other');
  assert.equal(st.canRedo, false, m('FR-PV-08', S, 'commit clears redo'));
});

T('store undo/redo 20 steps', () => {
  const st = mkStore();
  const start = clone(st.doc);
  const r = rng(42);
  const devIds = start.devices.filter((d) => d.ports.length).map((d) => d.id);
  for (let i = 0; i < 20; i++) {
    const id = devIds[Math.floor(r() * devIds.length)];
    const kind = i % 4;
    let ops;
    if (kind === 0) ops = [{ op: 'merge', coll: 'devices', id, value: { patch: { x: Math.round(r() * 1000), y: Math.round(r() * 1000) } } }];
    else if (kind === 1) ops = [{ op: 'merge', coll: 'devices', id, value: { name: 'Dev ' + i } }];
    else if (kind === 2) ops = [{ op: 'put', coll: 'cables', id: 'c-t2-' + i, value: { id: 'c-t2-' + i, from: { device: id }, to: { device: 'restream' }, medium: 'other' } }];
    else ops = [{ op: 'root', key: 'settings', value: { units: i % 8 === 3 ? 'metric' : 'imperial', currency: 'C' + i } }];
    st.commit(ops, 'edit ' + i);
  }
  const end = clone(st.doc);
  for (let i = 0; i < 20; i++) st.undo();
  assert.deepEqual(st.doc, start, m('FR-PV-08', S, '20 edits then 20 undos deep-equals the start'));
  assert.equal(st.canUndo, false);
  for (let i = 0; i < 20; i++) st.redo();
  assert.deepEqual(st.doc, end, m('FR-PV-08', S, '20 redos deep-equals the end'));
});

T('store undo of a delete restores the entity', (t) => {
  const st = mkStore();
  const start = clone(st.doc);
  st.commit([{ op: 'del', coll: 'cables', id: 'c-0005' }], 'Delete');
  st.undo();
  assert.deepEqual(canonDoc(st.doc), canonDoc(start), m('FR-PV-08', S, 'undo of a delete restores the cable'));
  const strict = JSON.stringify(st.doc.cables.map((c) => c.id)) === JSON.stringify(start.cables.map((c) => c.id));
  t.diagnostic('collection order after undo-of-delete preserved: ' + strict + ' (§4.9 put appends; see T2 notes)');
});

T('store undo cap 200', () => {
  const st = mkStore();
  for (let i = 0; i < 205; i++) st.commit([{ op: 'merge', coll: 'devices', id: 'atem-mini', value: { name: 'n' + i } }], 'e' + i);
  let n = 0;
  while (st.canUndo && n < 300) { st.undo(); n++; }
  assert.equal(n, 200, m('FR-PV-08', S, 'undo stack capped at 200'));
});

T('store applyRemote and replaceDoc', () => {
  const st = mkStore();
  const docEv = listen(st, 'doc');
  st.commit([{ op: 'merge', coll: 'devices', id: 'atem-mini', value: { name: 'Mine' } }], 'Mine');
  st.applyRemote([{ op: 'merge', coll: 'devices', id: 'sub-x2', value: { name: 'Theirs' } }], 'remote');
  assert.equal(docEv[1].source, 'remote', m('§6.2', S, 'applyRemote emits doc with its source'));
  assert.equal(st.undoLabel, 'Mine', m('§6.2', S, 'applyRemote does not touch undo'));
  st.undo();
  assert.equal(device(st.doc, 'atem-mini').name, 'ATEM Mini');
  assert.equal(device(st.doc, 'sub-x2').name, 'Theirs', m('§6.2', S, 'undo leaves remote changes'));
  st.replaceDoc(fx(), 7, 'load');
  assert.equal(st.canUndo, false, m('§6.2', S, 'replaceDoc clears undo'));
  assert.equal(st.canRedo, false);
  assert.equal(docEv[docEv.length - 1].source, 'load');
});

T('store read-only', () => {
  const st = mkStore({ readOnly: true });
  const before = clone(st.doc);
  assert.throws(() => st.commit([{ op: 'merge', coll: 'devices', id: 'atem-mini', value: { name: 'x' } }], 'x'),
    () => true, m('FR-PV-13', S, 'commit in read-only mode throws ReadOnlyError'));
  assert.deepEqual(st.doc, before, m('FR-PV-13', S, 'no change in read-only mode'));
  const st2 = mkStore();
  const mode = listen(st2, 'mode');
  st2.setReadOnly(true);
  assert.equal(st2.readOnly, true);
  assert.equal(mode.length, 1, m('FR-PV-13', S, 'setReadOnly emits mode'));
  assert.throws(() => st2.commit([{ op: 'merge', coll: 'devices', id: 'atem-mini', value: { name: 'x' } }], 'x'));
});

T('store events: selection, highlight, filter, room, overlay, revision', () => {
  const st = mkStore();
  const ev = {};
  for (const k of ['selection', 'highlight', 'filter', 'room', 'overlay', 'revision']) ev[k] = listen(st, k);
  st.select({ type: 'device', id: 'atem-mini' });
  assert.equal(st.selection.id, 'atem-mini'); assert.equal(ev.selection.length, 1, m('§6.2', S, 'select emits selection'));
  st.highlight({ devices: ['atem-mini'], ports: [], cables: ['c-0011'], source: 'test' });
  assert.equal(ev.highlight.length, 1, m('FR-PV-14', S, 'highlight emits highlight'));
  st.setFilter({ query: 'atem' });
  assert.equal(st.filter.query, 'atem'); assert.equal(ev.filter.length, 1);
  st.setRoom('chapel');
  assert.equal(st.room, 'chapel'); assert.equal(ev.room.length, 1);
  st.setOverlay({ devices: [] });
  assert.equal(ev.overlay.length, 1);
  st.setRevision(9);
  assert.equal(st.revision, 9); assert.equal(ev.revision.length, 1);
  assert.ok(st.index && st.index.byId.devices['atem-mini'], m('§6.2', S, 'store.index = indexDoc(doc)'));
  st.commit([{ op: 'put', coll: 'devices', id: 'zz', value: { id: 'zz', name: 'ZZ', kind: 'other', ports: [] } }], 'add');
  assert.ok(st.index.byId.devices.zz, m('§6.2', S, 'index invalidated on change'));
});
