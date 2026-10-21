// T2: js/patchtable-core.js (W5) against SPEC §6.6, §5.8.2, FR-PT-*.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { loadModule, loadFixtureDoc, loadVocab, sharedFixture, clone, norm, m, need, device, cable, ROOT } from './fixtures/helpers.mjs';

const { mod: pt, skip: absent, error } = await loadModule('js/patchtable-core.js', 'W5');
const mcL = await loadModule('js/model-core.js', 'W5');
const S = '§6.6';
const skip = absent || (error ? 'patchtable-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);

if (error) test('patchtable-core.js imports in Node (§6.1 pure module)', () => { throw error; });

const vocab = loadVocab();
const fixture = loadFixtureDoc();
const fx = () => clone(fixture);

function build(doc, filter, overlay) {
  return need(pt, 'buildPatchTable', 'FR-PT-01', S)(doc, overlay || null, vocab, filter);
}

// Independent reading of the §6.6 rules (doc cables only, no overlay rows).
function oracle(doc, room) {
  const byId = Object.fromEntries(doc.devices.map((d) => [d.id, d]));
  const portOf = (dv, p) => ((byId[dv] || {}).ports || []).find((x) => x.id === p);
  const lbl = (p) => (p ? p.label || null : null);
  const kindDisc = (d) => d.discipline || (vocab.kinds[d.kind] || {}).discipline || 'other';
  const out = [];
  for (const d of doc.devices) {
    if (room !== '*' && (d.room || '') !== room) continue;
    const model = [d.manufacturer || '', d.model || ''].join(' ').trim() || d.sub || '';
    const sections = [];
    let cur = null;
    for (const p of d.ports || []) {
      // ungrouped ports are keyed by their fallback title (W5 and W6 agree; see T2 notes)
      const short = (vocab.media[p.medium] || vocab.media.other).short;
      const g = p.group || `\u0000${short} ${p.dir === 'in' ? 'In' : p.dir === 'out' ? 'Out' : 'I/O'}`;
      if (!cur || cur._g !== g) {
        cur = { _g: g, _dirs: new Set(), title: g.replace('\u0000', ''), dir: p.dir, medium: p.medium, rows: [] };
        sections.push(cur);
      }
      cur._dirs.add(p.dir);
      const cabs = doc.cables.filter((c) => (c.from.device === d.id && c.from.port === p.id) || (c.to.device === d.id && c.to.port === p.id));
      const base = { port: p.id, port_name: p.name, label: lbl(p) };
      if (!cabs.length) {
        cur.rows.push(Object.assign(base, { peer_device: null, peer_name: null, peer_port: null, peer_port_name: null, peer_label: null, cable: null, tag: null, medium: p.medium, source: null }));
      }
      for (const c of cabs) {
        const peer = c.from.device === d.id && c.from.port === p.id ? c.to : c.from;
        const pp = peer.port ? portOf(peer.device, peer.port) : null;
        cur.rows.push(Object.assign({}, base, {
          peer_device: peer.device, peer_name: (byId[peer.device] || {}).name || peer.device, peer_port: peer.port || null,
          peer_port_name: pp ? pp.name : null, peer_label: lbl(pp), cable: c.id, tag: c.tag || null, medium: c.medium, source: 'cable',
        }));
      }
    }
    for (const s of sections) {
      if (s._dirs.size > 1) s.dir = 'io';
      if (!s.title) {
        const short = (vocab.media[s.medium] || vocab.media.other).short;
        s.title = `${short} ${s.dir === 'in' ? 'In' : s.dir === 'out' ? 'Out' : 'I/O'}`;
      }
      delete s._g; delete s._dirs;
    }
    out.push({ device: d.id, name: d.name, model, room: d.room || '', discipline: kindDisc(d), kind: d.kind, sections });
  }
  return out;
}

T('fixture blocks equal golden', (t) => {
  const golden = sharedFixture('patchtable-sunday.json');
  const got = norm(build(fx(), { room: '*' }));
  if (golden && golden.source.startsWith('T1')) {
    t.diagnostic('golden: ' + golden.source);
    assert.equal(got.length, golden.data.length, m('FR-PT-01', S, 'block count vs golden'));
    golden.data.forEach((b, i) => assert.deepEqual(got[i], b, m('FR-PT-01', S, `block ${b.device} vs golden ${golden.source}`)));
  } else {
    t.diagnostic('T1 golden absent: comparing with the T2 §6.6 oracle only');
  }
  const exp = oracle(fx(), '*');
  exp.forEach((b, i) => assert.deepEqual(got[i], b, m('FR-PT-01', S, `block ${b.device} vs T2 §6.6 oracle`)));
});

T('PatchBlock example row (§6.6)', () => {
  const blocks = build(fx(), { room: '*' });
  const ar = blocks.find((b) => b.device === 'audio-rack-1');
  assert.equal(ar.name, 'Audio Rack 1');
  assert.equal(ar.model, 'Allen & Heath AR84', m('FR-PT-01', S, 'model = manufacturer + model'));
  assert.equal(ar.discipline, 'audio'); assert.equal(ar.kind, 'stage_io'); assert.equal(ar.room, 'main');
  const sec = ar.sections[0];
  assert.deepEqual({ title: sec.title, dir: sec.dir, medium: sec.medium }, { title: 'Analog In', dir: 'in', medium: 'analog' });
  assert.deepEqual(norm(sec.rows[0]), {
    port: 'analog-in-1', port_name: 'Input 1', label: 'SB1-Out 1', peer_device: 'stage-box-1', peer_name: 'Stage Box 1', peer_port: 'analog-out-1',
    peer_port_name: 'Output 1', peer_label: 'SB1-Out 1', cable: 'c-0005', tag: 'A-003', medium: 'analog', source: 'cable',
  }, m('FR-PT-01', S, 'audio-rack-1 Analog In row 1 equals the §6.6 example'));
  const unp = sec.rows.find((r) => r.port === 'analog-in-5');
  for (const k of ['peer_device', 'peer_name', 'peer_port', 'peer_port_name', 'peer_label', 'cable', 'tag', 'source']) {
    assert.equal(unp[k], null, m('FR-PT-02', S, `unpatched port: ${k} = null`));
  }
  const rs = blocks.find((b) => b.device === 'restream');
  assert.equal(rs.model, 'Video Stream', m('FR-PT-01', S, 'model falls back to sub'));
  assert.deepEqual(blocks.map((b) => b.device), fixture.devices.map((d) => d.id), m('FR-PT-01', S, 'blocks in devices order'));
});

T('sections: fallback title, mixed dir, extra rows, device-level section', () => {
  const d = fx();
  device(d, 'restream').ports.push({ id: 'x1', name: 'X1', dir: 'in', medium: 'hdmi' }, { id: 'x2', name: 'X2', dir: 'out', medium: 'hdmi' });
  device(d, 'sub-x2').ports.push({ id: 'aux', name: 'Aux', dir: 'out', medium: 'dmx' });
  d.cables.push({ id: 'c-extra', from: { device: 'audio-rack-1', port: 'analog-out-3' }, to: { device: 'sub-x2', port: 'analog-in-2' }, medium: 'analog' });
  d.cables.push({ id: 'c-dl', from: { device: 'restream' }, to: { device: 'samsung-tv-1', port: 'hdmi-in-1' }, medium: 'hdmi' });
  const blocks = build(d, { room: '*' });
  const rs = blocks.find((b) => b.device === 'restream');
  const nogIn = rs.sections.find((s) => s.rows.some((r) => r.port === 'x1'));
  const nogOut = rs.sections.find((s) => s.rows.some((r) => r.port === 'x2'));
  assert.deepEqual([nogIn.title, nogIn.dir, nogOut.title, nogOut.dir], ['HDMI In', 'in', 'HDMI Out', 'out'], m('FR-PT-01', S, 'ungrouped ports titled "<MEDIA.short> <In|Out>"'));
  const d3 = fx();
  device(d3, 'restream').ports.push({ id: 'y1', name: 'Y1', dir: 'in', medium: 'analog', group: 'Mixed' }, { id: 'y2', name: 'Y2', dir: 'out', medium: 'analog', group: 'Mixed' });
  const mixed = build(d3, { room: '*' }).find((b) => b.device === 'restream').sections.find((s) => s.title === 'Mixed');
  assert.ok(mixed && mixed.dir === 'io' && mixed.rows.length === 2, m('FR-PT-01', S, 'group with mixed dirs -> one section, dir io'));
  const sx = blocks.find((b) => b.device === 'sub-x2');
  assert.ok(sx.sections.some((s) => s.title === 'DMX Out'), m('FR-PT-01', S, 'ungrouped out section titled "DMX Out"'));
  const out3 = blocks.find((b) => b.device === 'audio-rack-1').sections.flatMap((s) => s.rows).filter((r) => r.port === 'analog-out-3');
  assert.deepEqual(out3.map((r) => r.cable), ['c-0010', 'c-extra'], m('FR-PT-01', S, 'one extra row per additional cable on the same port'));
  const last = rs.sections[rs.sections.length - 1];
  assert.equal(last.title, 'Device', m('FR-PORT-02', S, 'device-level endpoints in a final "Device" section'));
  assert.equal(last.rows[0].port, null, m('FR-PORT-02', S, 'device-level row port = null'));
  assert.equal(last.rows[0].cable, 'c-dl');
  assert.equal(last.dir, 'out', m('FR-PORT-02', S, 'Device section dir from cable direction'));
  const tv = blocks.find((b) => b.device === 'samsung-tv-1').sections.flatMap((s) => s.rows).find((r) => r.port === 'hdmi-in-1');
  assert.equal(tv.peer_device, 'restream'); assert.equal(tv.peer_port, null, m('FR-PORT-02', S, 'device-level peer port = null'));
});

T('filters', () => {
  const atem = build(fx(), { room: '*', query: 'atem', text: 'atem' });
  assert.deepEqual(atem.map((b) => b.device), ['atem-mini'], m('FR-PT-06', S, 'filter "atem" shows exactly one block'));
  assert.equal(build(fx(), { room: 'main' }).length, 11, m('FR-PT-06', S, 'room filter'));
  assert.deepEqual(build(fx(), { room: '' }).map((b) => b.device), ['spare-ulxd4d'], m('FR-PT-06', S, 'room "" = shared inventory'));
  assert.equal(build(fx(), { room: '*' }).length, 12, m('FR-PT-06', S, "room '*' = all"));
});

T('overlay rows only with includeOverlay', () => {
  const ov = { routes: [{ kind: 'dante', from: { device: 'sound-board', port: 'slink', channel: '1 · Kick' }, to: { device: 'audio-rack-1', port: 'dsnake', channel: '1' }, label: 'Kick', medium: 'snake' }] };
  const off = build(fx(), { room: '*' }, ov).flatMap((b) => b.sections.flatMap((s) => s.rows));
  assert.ok(off.every((r) => r.source === 'cable' || r.source === null), m('FR-PT-07', S, 'no overlay rows unless filter.includeOverlay'));
  const on = build(fx(), { room: '*', includeOverlay: true }, ov).flatMap((b) => b.sections.flatMap((s) => s.rows));
  assert.ok(on.some((r) => r.source === 'dante'), m('FR-PT-07', S, 'overlay rows marked source "dante" with includeOverlay'));
});

// ------------------------------------------------------------------------ CSV

const HEADER = 'Room,Device,Section,Dir,Port,Label,Peer device,Peer port,Cable,Medium,Source';

function parseCsv(text) {
  const rows = []; let row = []; let f = ''; let q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { f += '"'; i++; } else if (c === '"') q = false; else f += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(f); f = ''; }
    else if (c === '\r' && text[i + 1] === '\n') { row.push(f); rows.push(row); row = []; f = ''; i++; }
    else f += c;
  }
  if (f || row.length) { row.push(f); rows.push(row); }
  return rows;
}

T('csv structure', () => {
  const patchTableCsv = need(pt, 'patchTableCsv', 'FR-PT-05', S);
  const blocks = build(fx(), { room: '*' });
  const csv = patchTableCsv(blocks);
  assert.equal(csv.split('\r\n')[0], HEADER, m('FR-PT-05', '§5.8.2', 'header = patch column labels'));
  assert.ok(csv.endsWith('\r\n'), m('FR-PT-05', S, 'rows end with \\r\\n (csv module default)'));
  assert.ok(!/[^\r]\n/.test(csv), m('FR-PT-05', S, 'only \\r\\n line endings'));
  const rows = parseCsv(csv);
  const nRows = blocks.reduce((n, b) => n + b.sections.reduce((k, s) => k + s.rows.length, 0), 0);
  assert.equal(rows.length, nRows + 1, m('FR-PT-05', S, 'one CSV line per row (blocks -> sections -> rows)'));
  const r = rows.find((x) => x[4] === 'SB1-Out 1' && x[1] === 'Audio Rack 1');
  assert.ok(r, m('FR-PT-05', S, 'port column = port label or name; device column = device name'));
  assert.deepEqual(r.slice(1), ['Audio Rack 1', 'Analog In', 'in', 'SB1-Out 1', 'SB1-Out 1', 'Stage Box 1', 'SB1-Out 1', 'A-003', 'analog', 'cable'], m('FR-PT-05', S, 'CSV row for audio-rack-1 analog-in-1'));
  const unp = rows.find((x) => x[1] === 'Audio Rack 1' && x[4] === 'Input 5');
  assert.deepEqual(unp.slice(6), ['', '', '', 'analog', ''], m('FR-PT-05', S, 'unpatched: empty peer/cable/source'));
});

T('csv RFC 4180 quoting', () => {
  const patchTableCsv = need(pt, 'patchTableCsv', 'FR-PT-05', S);
  const d = fx();
  device(d, 'sub-x2').ports[1].label = 'Sub, "B"';
  device(d, 'sub-x2').name = 'Sub\nx2';
  const csv = patchTableCsv(build(d, { room: '*' }));
  assert.ok(csv.includes('"Sub, ""B"""'), m('FR-PT-05', S, 'comma and quote fields quoted, quotes doubled'));
  assert.ok(csv.includes('"Sub\nx2"'), m('FR-PT-05', S, 'field with a newline quoted'));
  assert.ok(!csv.includes('"Audio Rack 1"'), m('FR-PT-05', S, 'plain fields not quoted (minimal quoting like Python csv)'));
});

T('csv equals server', (t) => {
  const p = path.join(ROOT, 'tests', 'fixtures', 'patchtable-sunday.csv');
  if (!existsSync(p)) { t.skip('T1 tests/fixtures/patchtable-sunday.csv not present'); return; }
  const want = readFileSync(p, 'utf8');
  const got = need(pt, 'patchTableCsv', 'FR-PT-05', S)(build(fx(), { room: '*' }));
  assert.equal(got, want, m('FR-PT-05', S, 'client CSV byte-identical to server CSV'));
});

T('patchCellOps', () => {
  const patchCellOps = need(pt, 'patchCellOps', 'FR-PT-03', S);
  const applyOps = need(mcL.mod, 'applyOps', '§4.9', '§6.2');
  const d = fx();
  const row = { device: 'audio-rack-1', port: 'analog-in-1', cable: 'c-0005' };
  const asOps = (x) => (Array.isArray(x) ? x : x.ops);
  let d2 = applyOps(d, asOps(patchCellOps(d, row, 'label', 'Keys'))).doc;
  assert.equal(device(d2, 'audio-rack-1').ports[0].label, 'Keys', m('FR-PT-03', S, "field 'label' -> renameOps"));
  d2 = applyOps(d, asOps(patchCellOps(d, row, 'clear'))).doc;
  assert.equal(cable(d2, 'c-0005'), undefined, m('FR-PT-03', S, "field 'clear' -> disconnect"));
  const free = { device: 'main-speakers', port: 'analog-in-2', cable: null };
  d2 = applyOps(d, asOps(patchCellOps(d, free, 'peer', { device: 'audio-rack-1', port: 'analog-out-2' }))).doc;
  const nc = d2.cables.find((c) => c.to.device === 'main-speakers' && c.to.port === 'analog-in-2');
  assert.ok(nc && nc.from.device === 'audio-rack-1' && nc.from.port === 'analog-out-2', m('FR-PT-02', S, "field 'peer' on an unpatched port -> connectOps (Patch main-speakers Input 2 from audio-rack-1 Output 2)"));
  d2 = applyOps(d, asOps(patchCellOps(d, row, 'peer', { device: 'stage-box-1', port: 'analog-out-2' }))).doc;
  const rp = cable(d2, 'c-0005') || d2.cables.find((c) => c.to.device === 'audio-rack-1' && c.to.port === 'analog-in-1');
  assert.ok(rp && rp.from.port === 'analog-out-2', m('FR-PT-03', S, "field 'peer' on a patched port -> repatch"));
});
