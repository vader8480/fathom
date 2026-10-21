// T2: js/patchview-core.js (W3) against SPEC §6.5, §6.9.1–6.9.4, FR-PV-*, FR-TRC-05.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  loadModule, loadFixtureDoc, loadVocab, readJson, fixturePath, clone, norm, m, need, device, toSet,
} from './fixtures/helpers.mjs';

const { mod: pv, skip: absent, error } = await loadModule('js/patchview-core.js', 'W3');
const mcL = await loadModule('js/model-core.js', 'W5');
const genL = await loadModule('dev/fixture-gen.js', 'W3');
const S = '§6.5';
const skip = absent || (error ? 'patchview-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);

if (error) test('patchview-core.js imports in Node (§6.1 pure module)', () => { throw error; });

const vocab = loadVocab();
const fixture = loadFixtureDoc();
const fx = () => clone(fixture);
const MAIN = { room: 'main' };

function scene(doc, filter, overlay, opts) {
  return need(pv, 'buildScene', 'FR-PV-01', S)(doc, overlay || null, vocab, Object.assign({}, MAIN, filter || {}), opts || {});
}
function wireCableId(w) {
  return w.cable && typeof w.cable === 'object' ? w.cable.id : w.cable || w.id;
}
function cardOf(sc, id) {
  return sc.cards.find((c) => c.id === id);
}
function ref(x) {
  if (typeof x === 'string') return x;
  return x.port ? `${x.device}:${x.port}` : x.device;
}
function overlap(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}
function nums(path) {
  return (String(path).match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/gi) || []).map(Number);
}

// Call traceLocal with the documented argument shapes (start {device, port} or "dev:port").
function trace(doc, overlay, start, opts) {
  const traceLocal = need(pv, 'traceLocal', 'FR-TRC-05', '§6.9');
  // The §6.5 signature has no vocab parameter; carries() needs one, so it travels in opts.
  opts = Object.assign({ vocab }, opts || {});
  let r;
  try {
    r = traceLocal(doc, overlay, start, opts);
  } catch (e) {
    r = traceLocal(doc, overlay, ref(start), opts);
  }
  assert.ok(r && r.cables && r.ports && r.devices, m('FR-TRC-05', '§6.5', 'traceLocal returns {ports, cables, devices}'));
  return { ports: toSet(r.ports), cables: toSet(r.cables), devices: toSet(r.devices) };
}

// ---------------------------------------------------------------- geometry

T('GEOM constants', () => {
  const G = need(pv, 'GEOM', 'FR-PV-01', S);
  assert.deepEqual(
    { cardW: G.cardW, headerH: G.headerH, rowH: G.rowH, sectionH: G.sectionH, ioSectionH: G.ioSectionH, pad: G.pad, dotR: G.dotR, grid: G.grid, maxRows: G.maxRows },
    { cardW: 248, headerH: 56, rowH: 22, sectionH: 18, ioSectionH: 18, pad: 8, dotR: 5, grid: 8, maxRows: 12 },
    m('FR-PV-01', S, 'GEOM values'));
});

T('cardLayout sides and rows', () => {
  const cardLayout = need(pv, 'cardLayout', 'FR-PV-01', S);
  const G = pv.GEOM;
  const dev = device(fixture, 'atem-mini');
  const all = new Set(dev.ports.map((p) => p.id));
  const L = cardLayout(dev, { connected: all, labels: {}, showUnconnected: true, expanded: false, maxRows: 12 });
  assert.equal(L.w, G.cardW, m('FR-PV-01', S, 'card width = GEOM.cardW'));
  const side = Object.fromEntries(L.rows.map((r) => [r.port.id, r.side]));
  assert.equal(side['hdmi-in-1'], 'left', m('FR-PV-01', S, 'inputs on the left'));
  assert.equal(side['hdmi-out-1'], 'right', m('FR-PV-01', S, 'outputs on the right'));
  assert.equal(L.rows.length, 5, m('FR-PV-01', S, 'one row per port'));
  assert.ok(L.h >= G.headerH + 3 * G.rowH, m('FR-PV-01', S, 'height covers header + rows'));
  for (const r of L.rows) assert.ok(r.y >= G.headerH - 1 && r.y < L.h, m('FR-PV-01', S, `row ${r.port.id} y inside the card body`));
  const lefts = L.rows.filter((r) => r.side === 'left').map((r) => r.y);
  assert.deepEqual(lefts, [...lefts].sort((a, b) => a - b), m('FR-PV-01', S, 'rows in port order top-down'));
  const io = cardLayout(device(fixture, 'sound-board'), { connected: new Set(['slink']), labels: {}, showUnconnected: true });
  assert.equal(io.rows[0].side, 'both', m('FR-PV-01', S, "io ports: side 'both'"));
  const lab = Object.fromEntries(L.rows.map((r) => [r.port.id, r.label]));
  assert.equal(lab['hdmi-in-1'], 'SB-Video-1', m('FR-PV-01', S, 'row label = port label'));
  const rr = L.rows.find((r) => r.port.id === 'hdmi-in-2');
  assert.equal(rr.index, 2, m('FR-PV-01', S, 'row index'));
});

T('cardLayout overlay labels', () => {
  const cardLayout = need(pv, 'cardLayout', 'FR-PORT-07', S);
  const dev = device(fixture, 'video-converter');
  const L = cardLayout(dev, { connected: new Set(), labels: { 'sdi-out-2': 'From import', 'hdmi-in-1': 'Ignored' }, showUnconnected: true });
  const r2 = L.rows.find((r) => r.port.id === 'sdi-out-2');
  assert.equal(r2.label, 'From import', m('FR-PORT-07', S, 'overlay label shown when doc label empty'));
  assert.equal(r2.overlayLabel, true, m('FR-PORT-07', S, 'overlayLabel flag'));
  const r1 = L.rows.find((r) => r.port.id === 'hdmi-in-1');
  assert.equal(r1.label, 'Program In', m('FR-PORT-07', S, 'doc label wins over overlay'));
  assert.equal(r1.overlayLabel, false);
});

T('cardLayout collapses columns over 12 ports', () => {
  const cardLayout = need(pv, 'cardLayout', 'FR-PV-10', S);
  const ports = [];
  for (let i = 1; i <= 20; i++) ports.push({ id: 'in-' + i, name: 'In ' + i, dir: 'in', medium: 'analog', group: 'In' });
  ports.push({ id: 'out-1', name: 'Out 1', dir: 'out', medium: 'analog', group: 'Out' });
  ports[4].label = 'Labelled';
  const dev = { id: 'big', name: 'Big', kind: 'console', ports };
  const L = cardLayout(dev, { connected: new Set(['in-1', 'in-2', 'out-1']), labels: {}, showUnconnected: true, expanded: false, maxRows: 12 });
  const left = L.rows.filter((r) => r.side === 'left').map((r) => r.port.id);
  assert.deepEqual(left, ['in-1', 'in-2', 'in-5'], m('FR-PV-10', S, '> 12 ports collapse to connected/labelled ports'));
  assert.equal(L.hidden.left, 17, m('FR-PV-10', S, 'hidden.left = "+N more"'));
  const X = cardLayout(dev, { connected: new Set(['in-1']), labels: {}, showUnconnected: true, expanded: true, maxRows: 12 });
  assert.equal(X.rows.filter((r) => r.side === 'left').length, 20, m('FR-PV-10', S, 'expanded shows every port'));
  const small = cardLayout(device(fixture, 'audio-rack-1'), { connected: new Set(['analog-in-1']), labels: {}, showUnconnected: false });
  assert.ok(small.rows.every((r) => r.port.id === 'analog-in-1'), m('FR-PV-10', S, 'showUnconnected:false hides unconnected ports'));
});

// --------------------------------------------------------------------- scene

T('buildScene on fixture', () => {
  const sc = scene(fx());
  assert.equal(sc.cards.length, 11, m('FR-PV-01', S, 'main room = 11 cards (spare is shared inventory)'));
  assert.equal(sc.wires.length, 15, m('FR-PV-02', S, 'one wire per cable (15)'));
  assert.equal(new Set(sc.wires.map(wireCableId)).size, 15, m('FR-PV-02', S, 'wires map 1:1 to cables'));
  const atem = cardOf(sc, 'atem-mini');
  assert.deepEqual({ x: atem.x, y: atem.y }, { x: 700, y: 300 }, m('FR-PV-03', S, 'card position = device.patch'));
  assert.ok(atem.w > 0 && atem.h > 0 && atem.layout && atem.layout.rows, m('FR-PV-01', S, 'card carries w, h, layout'));
  const w = sc.wires.find((x) => wireCableId(x) === 'c-0014');
  assert.equal(w.color, vocab.media.sdi.color, m('FR-PV-02', S, 'wire color from medium'));
  assert.equal(w.medium, 'sdi');
  const aes = scene(Object.assign(fx(), { cables: [{ id: 'c-a', from: { device: 'atem-mini', port: 'hdmi-out-1' }, to: { device: 'video-converter', port: 'hdmi-in-1' }, medium: 'aes3' }] }));
  assert.equal(aes.wires[0].dash, vocab.media.aes3.dash, m('FR-PV-02', S, 'wire dash from medium'));
  const b = sc.bounds;
  for (const c of sc.cards) {
    assert.ok(c.x >= b.x - 1e-6 && c.y >= b.y - 1e-6 && c.x + c.w <= b.x + b.w + 1e-6 && c.y + c.h <= b.y + b.h + 1e-6, m('FR-PV-01', S, `bounds contain card ${c.id}`));
  }
  assert.ok(sc.cards.every((c) => !c.external), m('FR-ROOM-05', S, 'no ghosts when every peer is in the room'));
});

T('buildScene layout determinism', () => {
  assert.deepEqual(norm(scene(fx())), norm(scene(fx())), m('FR-PV-12', S, 'buildScene is deterministic'));
  const d = fx();
  for (const x of d.devices) delete x.patch;
  assert.deepEqual(norm(scene(d)), norm(scene(clone(d))), m('FR-PV-12', S, 'deterministic without saved positions'));
});

T('buildScene filters', () => {
  const vid = scene(fx(), { disciplines: ['video'] });
  const shown = new Set(vid.cards.filter((c) => !c.external).map((c) => c.id));
  for (const id of ['atem-mini', 'video-converter', 'samsung-tv-1', 'stage-box-1']) assert.ok(shown.has(id), m('FR-PV-10', S, `video chip shows ${id} (video or mixed)`));
  for (const id of ['wireless-mics', 'shure-wireless', 'sound-board', 'main-speakers', 'sub-x2']) assert.ok(!shown.has(id), m('FR-PV-10', S, `video chip hides audio-only ${id}`));
  const aud = new Set(scene(fx(), { disciplines: ['audio'] }).cards.map((c) => c.id));
  assert.ok(aud.has('atem-mini'), m('FR-PV-10', S, 'audio chip still shows mixed ATEM'));
  assert.ok(!aud.has('samsung-tv-1') || cardOf(scene(fx(), { disciplines: ['audio'] }), 'samsung-tv-1').external, m('FR-PV-10', S, 'audio chip hides video-only display'));
  const q = scene(fx(), { query: 'atem' });
  assert.equal(q.cards.length, 11, m('FR-PV-10', S, 'text filter dims, does not hide'));
  assert.equal(cardOf(q, 'atem-mini').dim, false, m('FR-PV-10', S, 'match not dimmed'));
  assert.equal(cardOf(q, 'sub-x2').dim, true, m('FR-PV-10', S, 'non-match dimmed'));
  const d = fx();
  device(d, 'restream').status = 'planned';
  const st = scene(d, { statuses: ['installed'] });
  assert.ok(!st.cards.some((c) => c.id === 'restream' && !c.external), m('FR-PV-10', S, 'status chips filter'));
});

T('filter by system', () => {
  const sc = scene(fx(), { system: 'main-video' });
  const own = sc.cards.filter((c) => !c.external).map((c) => c.id).sort();
  assert.deepEqual(own, ['atem-mini', 'restream', 'samsung-tv-1', 'video-converter'], m('FR-ROOM-08', S, 'system main-video shows exactly its 4 devices'));
});

T('buildScene room: all rooms, external ghosts, overlay auto devices', () => {
  const d = fx();
  d.rooms.push({ id: 'chapel', venue: 'hillside', name: 'Chapel' });
  device(d, 'atem-mini').room = 'chapel';
  const sc = scene(d);
  const g = cardOf(sc, 'atem-mini');
  assert.ok(g && g.external === true, m('FR-ROOM-05', S, 'cross-room device appears as an external ghost'));
  const gw = sc.wires.filter((w) => ['c-0011', 'c-0012', 'c-0013', 'c-0015'].includes(wireCableId(w)));
  assert.equal(gw.length, 4, m('FR-ROOM-05', S, 'ghost keeps its 4 cables'));
  assert.ok(sc.cards.filter((c) => c.external).every((c) => c.id === 'atem-mini'), m('FR-ROOM-05', S, 'only peers of room devices become ghosts'));
  const all = scene(fx(), { room: '*' });
  assert.equal(all.cards.length, 12, m('FR-PV-10', S, "room '*' shows all rooms"));
  const ov = { devices: [{ id: 'dante-am2-7', name: 'AM2-7', kind: 'iem', room: 'main', auto: true, source: 'dante', ports: [{ id: 'dante', name: 'Dante', dir: 'io', medium: 'dante', channels: 2 }] }] };
  const so = scene(fx(), {}, ov);
  const a = cardOf(so, 'dante-am2-7');
  assert.ok(a && a.auto === true, m('FR-PV-01', S, 'overlay auto devices appear as auto cards'));
});

T('portAnchor and wirePath', () => {
  const sc = scene(fx());
  const portAnchor = need(pv, 'portAnchor', 'FR-PV-02', S);
  const wirePath = need(pv, 'wirePath', 'FR-PV-02', S);
  const G = pv.GEOM;
  const c = cardOf(sc, 'audio-rack-1');
  const l = portAnchor(c, 'analog-in-1', 'left');
  const r = portAnchor(c, 'analog-out-1', 'right');
  assert.ok(Math.abs(l.x - c.x) <= G.dotR + 1, m('FR-PV-01', S, 'input dot on the left edge'));
  assert.ok(Math.abs(r.x - (c.x + c.w)) <= G.dotR + 1, m('FR-PV-01', S, 'output dot on the right edge'));
  assert.ok(l.y > c.y + G.headerH - 1 && l.y < c.y + c.h, m('FR-PV-01', S, 'port anchor y within body'));
  const r1 = portAnchor(c, 'analog-out-1', 'right');
  const r2 = portAnchor(c, 'analog-out-2', 'right');
  assert.ok(r2.y > r1.y, m('FR-PV-01', S, 'later ports lower'));
  const h = portAnchor(c, null, 'right');
  assert.ok(h.y >= c.y && h.y <= c.y + G.headerH, m('FR-PORT-02', S, 'device-level anchor on the card header'));
  const cases = [
    [{ x: 0, y: 0 }, { x: 200, y: 100 }, [0, 0, 100, 0, 100, 100, 200, 100]],
    [{ x: 0, y: 0 }, { x: 50, y: 10 }, [0, 0, 40, 0, 10, 10, 50, 10]],
    [{ x: 10, y: 20 }, { x: -90, y: 20 }, [10, 20, 60, 20, -140, 20, -90, 20]],
  ];
  for (const [a, b, exp] of cases) {
    const p = wirePath(a, b);
    assert.match(String(p).trim(), /^M\s*\S+[\s,]+\S+\s*C/, m('FR-PV-02', S, 'path = "M ax ay C ..."'));
    const got = nums(p);
    assert.equal(got.length, 8, m('FR-PV-02', S, `wirePath numbers: ${p}`));
    got.forEach((v, i) => assert.ok(Math.abs(v - exp[i]) < 0.01, m('FR-PV-02', S, `wirePath(${JSON.stringify(a)}, ${JSON.stringify(b)}) = ${p}, expected ${exp.join(' ')}`)));
  }
});

// ---------------------------------------------------------------- hit testing

T('hitTest', () => {
  const hitTest = need(pv, 'hitTest', 'FR-PV-04', S);
  const portAnchor = pv.portAnchor;
  const G = pv.GEOM;
  const sc = scene(fx());
  const opts = { k: 1, zoom: 1 };
  const far = hitTest(sc, { x: sc.bounds.x - 500, y: sc.bounds.y - 500 }, opts);
  assert.equal(far.type, 'background', m('FR-PV-04', S, 'empty canvas = background'));
  const c = cardOf(sc, 'audio-rack-1');
  const hdr = hitTest(sc, { x: c.x + c.w / 2, y: c.y + G.headerH / 2 }, opts);
  assert.ok(['header', 'card'].includes(hdr.type), m('FR-PV-06', S, 'card header hit'));
  assert.equal(hdr.card && (hdr.card.id || hdr.card), 'audio-rack-1');
  const a = portAnchor(c, 'analog-in-5', 'left');
  const pt = hitTest(sc, a, opts);
  assert.equal(pt.type, 'port', m('FR-PV-04', S, 'port dot hit'));
  assert.equal(pt.port && (pt.port.id || pt.port), 'analog-in-5');
  // midpoint of the long c-0011 wire (audio-rack-1 -> atem-mini), away from cards
  const w = sc.wires.find((x) => wireCableId(x) === 'c-0011');
  const from = portAnchor(cardOf(sc, 'audio-rack-1'), 'analog-out-4', 'right');
  const to = portAnchor(cardOf(sc, 'atem-mini'), 'analog-in-1', 'left');
  const n = nums(pv.wirePath(from, to));
  const bez = (t, i) => (1 - t) ** 3 * n[i] + 3 * (1 - t) ** 2 * t * n[i + 2] + 3 * (1 - t) * t * t * n[i + 4] + t ** 3 * n[i + 6];
  const mid = { x: bez(0.5, 0), y: bez(0.5, 1) };
  const inCard = sc.cards.some((cc) => mid.x >= cc.x && mid.x <= cc.x + cc.w && mid.y >= cc.y && mid.y <= cc.y + cc.h);
  if (!inCard) {
    const wh = hitTest(sc, mid, opts);
    assert.equal(wh.type, 'wire', m('FR-PV-05', S, 'wire midpoint hit'));
    assert.equal(wireCableId(wh.wire || {}) || wh.wire, wireCableId(w));
  }
});

T('compatibleTargets', () => {
  const compatibleTargets = need(pv, 'compatibleTargets', 'FR-PV-04', S);
  const d = fx();
  const sc = scene(d);
  const set = toSet(compatibleTargets(d, sc, { device: 'audio-rack-1', port: 'analog-out-3' }, vocab));
  assert.ok(set.has('sub-x2:analog-in-2'), m('FR-PV-04', S, 'free analog input is compatible'));
  for (const r of set) {
    const [dv, p] = r.split(':');
    const port = (device(d, dv) || { ports: [] }).ports.find((x) => x.id === p);
    assert.ok(!port || port.dir !== 'out', m('FR-PV-04', '§4.4.4', `out port ${r} must not be a target`));
  }
  assert.ok(!set.has('audio-rack-1:analog-out-3'), m('FR-PV-04', '§4.4.4', 'source port itself excluded'));
});

T('moveOps snaps', () => {
  const moveOps = need(pv, 'moveOps', 'FR-PV-03', S);
  const ops = moveOps(fx(), { 'atem-mini': { x: 703, y: 297 }, 'sub-x2': { x: 1043, y: 229 } });
  assert.equal(ops.length, 2, m('FR-PV-03', S, 'one merge op per moved device'));
  const by = Object.fromEntries(ops.map((o) => [o.id, o]));
  assert.equal(by['atem-mini'].op, 'merge'); assert.equal(by['atem-mini'].coll, 'devices');
  assert.deepEqual(norm({ x: by['atem-mini'].value.patch.x, y: by['atem-mini'].value.patch.y }), { x: 704, y: 296 }, m('FR-PV-03', S, 'snapped to the 8 px grid'));
  assert.deepEqual(norm({ x: by['sub-x2'].value.patch.x, y: by['sub-x2'].value.patch.y }), { x: 1040, y: 232 });
  const snap = need(pv, 'snap', 'FR-PV-03', S);
  assert.equal(snap(13, 8), 16); assert.equal(snap(11, 8), 8); assert.equal(snap(-5, 8), -8); assert.equal(snap(40, 8), 40);
});

// ---------------------------------------------------------------- autoLayout

function rects(doc, pos) {
  const cardLayout = pv.cardLayout;
  const conn = {};
  for (const c of doc.cables) {
    for (const e of [c.from, c.to]) if (e.port) (conn[e.device] = conn[e.device] || new Set()).add(e.port);
  }
  return Object.entries(pos).map(([id, p]) => {
    const L = cardLayout(device(doc, id), { connected: conn[id] || new Set(), labels: {}, showUnconnected: true, expanded: false, maxRows: 12 });
    return { id, x: p.x, y: p.y, w: L.w, h: L.h };
  });
}

T('autoLayout layered left to right', () => {
  const autoLayout = need(pv, 'autoLayout', 'FR-PV-12', S);
  const d = fx();
  const idsMain = d.devices.filter((x) => x.room === 'main').map((x) => x.id);
  const pos = autoLayout(d, idsMain, vocab, { x: 0, y: 0 });
  assert.deepEqual(Object.keys(pos).sort(), [...idsMain].sort(), m('FR-PV-12', S, 'a position for every requested device'));
  assert.deepEqual(norm(autoLayout(d, idsMain, vocab, { x: 0, y: 0 })), norm(pos), m('FR-PV-12', S, 'deterministic'));
  const chain = ['wireless-mics', 'shure-wireless', 'audio-rack-1', 'main-speakers'];
  for (let i = 1; i < chain.length; i++) {
    assert.ok(pos[chain[i - 1]].x < pos[chain[i]].x, m('FR-PV-12', S, `${chain[i - 1]} left of ${chain[i]} (cable direction)`));
  }
  assert.ok(pos['atem-mini'].x < pos['restream'].x && pos['video-converter'].x < pos['samsung-tv-1'].x, m('FR-PV-12', S, 'video chain left to right'));
  const R = rects(d, pos);
  for (let i = 0; i < R.length; i++) for (let j = i + 1; j < R.length; j++) {
    assert.ok(!overlap(R[i], R[j]), m('FR-PV-12', S, `cards ${R[i].id} and ${R[j].id} overlap`));
  }
});

T('autoLayout no overlap on migrated RRC', () => {
  const autoLayout = need(pv, 'autoLayout', 'FR-PV-12', S);
  const rrc = readJson(fixturePath('rrc-v2.json'));
  const all = rrc.devices.map((x) => x.id);
  const pos = autoLayout(rrc, all, vocab, { x: 0, y: 0 });
  const R = rects(rrc, pos);
  assert.equal(R.length, all.length, m('FR-PV-12', S, 'every RRC device positioned'));
  const bad = [];
  for (let i = 0; i < R.length; i++) for (let j = i + 1; j < R.length; j++) if (overlap(R[i], R[j])) bad.push(R[i].id + '/' + R[j].id);
  assert.deepEqual(bad, [], m('FR-PV-12', S, 'autoLayout positions for migrated RRC overlap the rendered cards (default heights ignore connected ports)'));
});

T('buildScene auto-positions migrated RRC without overlap', () => {
  const rrc = readJson(fixturePath('rrc-v2.json'));
  const sc = scene(rrc, { room: '*' });
  const S2 = sc.cards.filter((c) => !c.external);
  assert.equal(S2.length, rrc.devices.length, m('FR-PV-12', S, 'a card for every RRC device'));
  const bad2 = [];
  for (let i = 0; i < S2.length; i++) for (let j = i + 1; j < S2.length; j++) if (overlap(S2[i], S2[j])) bad2.push(S2[i].id + '/' + S2[j].id);
  assert.deepEqual(bad2, [], m('FR-PV-12', S, 'migrated RRC shows zero overlapping cards'));
  const d = rrc.devices.find((x) => x.id === sc.cards[0].id);
  assert.ok(!d.patch, m('FR-PV-12', S, 'auto positions are not persisted in the doc'));
});

// -------------------------------------------------------------------- tracing

T('traceLocal downstream audio', () => {
  const r = trace(fx(), null, { device: 'audio-rack-1', port: 'analog-out-4' }, { direction: 'down', discipline: 'audio' });
  assert.deepEqual([...r.cables].sort(), ['c-0011', 'c-0013', 'c-0014', 'c-0015'], m('FR-TRC-05', '§6.9.3', 'downstream audio from audio-rack-1:analog-out-4 = exactly c-0011, c-0013, c-0014, c-0015'));
  for (const p of ['atem-mini:analog-in-1', 'restream:usb-in-1', 'samsung-tv-1:sdi-in-1']) assert.ok(r.ports.has(p), m('FR-TRC-05', '§6.9.1', `reaches ${p}`));
  for (const dv of ['atem-mini', 'video-converter', 'samsung-tv-1', 'restream']) assert.ok(r.devices.has(dv), m('FR-TRC-05', '§6.9', `devices include ${dv}`));
  assert.ok(!r.devices.has('main-speakers'), m('FR-TRC-05', '§6.9', 'does not reach main speakers'));
});

T('traceLocal passthrough routing', () => {
  const r = trace(fx(), null, { device: 'stage-box-1', port: 'hdmi-out-1' }, { direction: 'up' });
  assert.ok(r.ports.has('stage-box-1:hdmi-in-1'), m('FR-PORT-05', '§4.4.5', 'upstream from hdmi-out-1 reaches hdmi-in-1'));
  for (const p of ['analog-in-1', 'analog-in-2', 'return-in-1']) assert.ok(!r.ports.has('stage-box-1:' + p), m('FR-PORT-05', '§4.4.5', `passthrough must not reach ${p}`));
  assert.equal(r.cables.size, 0, m('FR-PORT-05', '§4.4.5', 'hdmi-in-1 is unpatched: no cables'));
});

T('traceLocal discipline filter video', () => {
  const r = trace(fx(), null, { device: 'samsung-tv-1', port: 'sdi-in-1' }, { direction: 'up', discipline: 'video' });
  assert.ok(r.ports.has('atem-mini:hdmi-in-1'), m('FR-TRC-02', '§6.9.2', 'video trace reaches atem-mini:hdmi-in-1'));
  assert.ok(!r.ports.has('atem-mini:analog-in-1'), m('FR-TRC-02', '§6.9.2', 'video trace must not reach atem-mini:analog-in-1'));
  assert.ok(r.cables.has('c-0012') && r.cables.has('c-0013') && r.cables.has('c-0014'), m('FR-TRC-02', '§6.9.3', 'cables on the video path'));
  assert.ok(!r.cables.has('c-0011'), m('FR-TRC-02', '§6.9.2', 'analog cable excluded'));
});

T('traceLocal bidirectional, device-level and overlay edges', () => {
  const up = trace(fx(), null, { device: 'sound-board', port: 'slink' }, { direction: 'down' });
  assert.ok(up.cables.has('c-0008') && up.ports.has('audio-rack-1:dsnake'), m('FR-TRC-01', '§6.9.3', 'bidirectional snake traversed'));
  const back = trace(fx(), null, { device: 'audio-rack-1', port: 'dsnake' }, { direction: 'down' });
  assert.ok(back.ports.has('sound-board:slink'), m('FR-TRC-01', '§6.9.3', 'bidirectional cable both ways'));
  const d = fx();
  d.cables.push({ id: 'c-dev', from: { device: 'stage-box-1' }, to: { device: 'atem-mini', port: 'hdmi-in-2' }, medium: 'hdmi' });
  const dl = trace(d, null, { device: 'atem-mini', port: 'hdmi-in-2' }, { direction: 'up' });
  assert.ok(dl.cables.has('c-dev') && dl.devices.has('stage-box-1'), m('FR-TRC-01', '§6.9.1', 'device-level endpoint via virtual dev:* node'));
  const ov = { routes: [{ kind: 'dante', from: { device: 'sound-board', port: 'slink' }, to: { device: 'samsung-tv-1', port: 'hdmi-in-1' }, medium: 'dante' }] };
  const ro = trace(fx(), ov, { device: 'samsung-tv-1', port: 'hdmi-in-1' }, { direction: 'up' });
  assert.ok(ro.ports.has('sound-board:slink'), m('FR-TRC-05', '§6.9.3', 'overlay route edges included when an overlay is given'));
  const no = trace(fx(), null, { device: 'samsung-tv-1', port: 'hdmi-in-1' }, { direction: 'up' });
  assert.ok(!no.ports.has('sound-board:slink'), m('FR-TRC-05', '§6.9.3', 'no route edges without overlay'));
});

// ------------------------------------------------------------- fixture-gen.js

test('makeFixture validates (fixture-gen.js)', { skip: genL.skip || (mcL.mod ? false : 'W5 model-core.js not present') }, () => {
  if (genL.error) throw genL.error;
  const makeFixture = need(genL.mod, 'makeFixture', 'FR-PV-15', '§6.12');
  const a = makeFixture({ devices: 150, cables: 600, seed: 1 });
  assert.equal(a.fathom, 2, m('FR-PV-15', '§6.12', 'v2 doc'));
  assert.equal(a.devices.length, 150, m('FR-PV-15', '§6.12', '150 devices'));
  assert.equal(a.cables.length, 600, m('FR-PV-15', '§6.12', '600 cables'));
  assert.ok(a.devices.every((d) => d.room === 'main'), m('FR-PV-15', '§6.12', 'single room main'));
  assert.ok(a.devices.every((d) => d.ports.length >= 4 && d.ports.length <= 24), m('FR-PV-15', '§6.12', '4-24 ports per device'));
  const errs = need(mcL.mod, 'validateLocal', '§4.7', '§6.2')(a, vocab).filter((p) => p.level === 'error');
  assert.deepEqual(errs, [], m('FR-PV-15', '§6.12', 'makeFixture doc has 0 validateLocal errors'));
  const canConnect = mcL.mod.canConnect;
  const bad = a.cables.filter((c) => canConnect && canConnect(a, c.from, c.to, vocab).level === 'error').map((c) => c.id);
  assert.deepEqual(bad.slice(0, 5), [], m('FR-PV-15', '§6.12', 'cables only between compatible ports'));
  assert.deepEqual(makeFixture({ devices: 150, cables: 600, seed: 1 }), a, m('FR-PV-15', '§6.12', 'deterministic for a seed'));
  if (!skip) {
    const t0 = Date.now();
    const sc = pv.buildScene(a, null, vocab, { room: 'main' }, {});
    assert.equal(sc.cards.length, 150);
    assert.equal(sc.wires.length, 600);
    assert.ok(Date.now() - t0 < 1500, m('FR-PV-15', '§8.2', 'buildScene for 150/600 under 1500 ms in Node'));
  }
});
