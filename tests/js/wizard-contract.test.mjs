// T-WIZARD: js/wizard-core.js against docs/ui-audit.md B.2 WIZARD (Core) and SPEC §4.3.8, §4.3.10, §4.9.
// Written from the contract before the implementation; every test skips while the module is absent.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadFixtureDoc, loadVocab, clone, m, need } from './fixtures/helpers.mjs';

const { mod, skip: absent, error } = await loadModule('js/wizard-core.js', 'WIZARD');
const { mod: mc, error: mcError } = await loadModule('js/model-core.js', 'W5');
const S = 'B.2 WIZARD';
const skip = absent || (error ? 'wizard-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);

if (error) test('wizard-core.js imports in Node (pure core module)', () => { throw error; });

const vocab = loadVocab();
const fixture = loadFixtureDoc();
const fx = () => clone(fixture);

const fn = (name) => need(mod, name, 'WIZARD', S);
const core = (name) => {
  if (mcError) throw mcError;
  return need(mc, name, '§4.9', '§6.2');
};

function asOps(x) {
  return Array.isArray(x) ? x : x && Array.isArray(x.ops) ? x.ops : x;
}

function apply(doc, ops) {
  const r = core('applyOps')(doc, ops);
  assert.ok(r && r.doc, m('§4.9', S, 'applyOps must accept the generated ops'));
  return r.doc;
}

function errorKeys(doc) {
  return core('validateLocal')(doc, vocab)
    .filter((p) => p.level === 'error')
    .map((p) => p.code + ' ' + p.ref + ' ' + p.path)
    .sort();
}

function problemKeys(doc) {
  return core('validateLocal')(doc, vocab).map((p) => p.level + ' ' + p.code + ' ' + p.ref).sort();
}

function assertErrorsObject(e, what) {
  assert.ok(e && typeof e === 'object' && !Array.isArray(e), m('WIZARD', S, what + ' must return an errors object {field: message}'));
}

function assertValid(e, what) {
  assertErrorsObject(e, what);
  assert.deepEqual(Object.keys(e), [], m('WIZARD', S, what + ' must return {} for a valid row, got ' + JSON.stringify(e)));
}

function assertFieldError(e, field, what) {
  assertErrorsObject(e, what);
  assert.ok(e[field], m('WIZARD', S, what + ' must report an error on `' + field + '`, got ' + JSON.stringify(e)));
  assert.equal(typeof e[field], 'string', m('WIZARD', S, what + ': error messages are strings'));
}

function assertInvalid(e, what) {
  assertErrorsObject(e, what);
  assert.ok(Object.keys(e).length > 0, m('WIZARD', S, what + ' must be rejected'));
}

// guessMapping may return an array aligned with the header (preferred) or an object keyed by header text.
function mappedAt(result, header, i) {
  if (Array.isArray(result)) return result[i] === undefined ? null : result[i];
  assert.ok(result && typeof result === 'object', m('WIZARD', S, 'guessMapping must return an array or object'));
  const v = result[header[i]];
  return v === undefined ? null : v;
}

// ------------------------------------------------------------------ fixture port discovery

function portState(doc) {
  const idx = core('indexDoc')(doc);
  const ports = [];
  for (const d of doc.devices || []) {
    for (const p of d.ports || []) {
      const ref = d.id + ':' + p.id;
      ports.push({ device: d.id, port: p.id, dir: p.dir, medium: p.medium, used: !!(idx.cablesByPort[ref] || []).length });
    }
  }
  return ports;
}

const isSource = (p) => p.dir === 'out' || p.dir === 'io';
const isSink = (p) => p.dir === 'in' || p.dir === 'io';
const key = (p) => p.device + ':' + p.port;

// Disjoint pairs of free ports (source -> sink, same medium, different devices) that canConnect rates 'ok'.
function freePairs(doc, n) {
  const ports = portState(doc).filter((p) => !p.used);
  const taken = new Set();
  const out = [];
  for (const a of ports) {
    if (out.length >= n) break;
    if (!isSource(a) || taken.has(key(a))) continue;
    for (const b of ports) {
      if (!isSink(b) || taken.has(key(b)) || b.device === a.device || b.medium !== a.medium || key(a) === key(b)) continue;
      const r = core('canConnect')(doc, { device: a.device, port: a.port }, { device: b.device, port: b.port }, vocab);
      if (r.level !== 'ok') continue;
      taken.add(key(a));
      taken.add(key(b));
      out.push({ from: { device: a.device, port: a.port }, to: { device: b.device, port: b.port }, medium: a.medium });
      break;
    }
  }
  assert.equal(out.length, n, 'fixture must offer ' + n + ' disjoint free compatible port pairs');
  return out;
}

// An occupied input with a free same-medium output on another device (canConnect: warn, not error).
function occupiedSinkCase(doc) {
  const ports = portState(doc);
  for (const b of ports) {
    if (!b.used || b.dir !== 'in') continue;
    for (const a of ports) {
      if (a.used || a.dir !== 'out' || a.device === b.device || a.medium !== b.medium) continue;
      const r = core('canConnect')(doc, { device: a.device, port: a.port }, { device: b.device, port: b.port }, vocab);
      if (r.level === 'error') continue;
      return { from: { device: a.device, port: a.port }, to: { device: b.device, port: b.port } };
    }
  }
  throw new Error('fixture must have an occupied input with a free same-medium output elsewhere');
}

// An occupied output with a free same-medium input on another device.
function occupiedSourceCase(doc) {
  const ports = portState(doc);
  for (const a of ports) {
    if (!a.used || a.dir !== 'out') continue;
    for (const b of ports) {
      if (b.used || b.dir !== 'in' || b.device === a.device || b.medium !== a.medium) continue;
      return { from: { device: a.device, port: a.port }, to: { device: b.device, port: b.port } };
    }
  }
  throw new Error('fixture must have an occupied output with a free same-medium input elsewhere');
}

// Two free inputs on different devices: canConnect says bad_direction (level 'error').
function inputToInputCase(doc) {
  const ins = portState(doc).filter((p) => !p.used && p.dir === 'in');
  for (const a of ins) {
    for (const b of ins) {
      if (a.device === b.device) continue;
      const r = core('canConnect')(doc, { device: a.device, port: a.port }, { device: b.device, port: b.port }, vocab);
      if (r.level === 'error') return { from: { device: a.device, port: a.port }, to: { device: b.device, port: b.port } };
    }
  }
  throw new Error('fixture must have two free inputs on different devices');
}

const asRef = (e) => e.device + ':' + e.port;

// ------------------------------------------------------------------ exports

T('wizard-core exports the Core API', () => {
  for (const name of ['parsePasted', 'guessMapping', 'validateDeviceRow', 'validateCableRow', 'bulkDeviceOps', 'bulkCableOps', 'canAdvance']) {
    assert.equal(typeof fn(name), 'function', m('WIZARD', S, '`' + name + '` must be a function'));
  }
});

// ------------------------------------------------------------------ parsePasted

T('parsePasted detects tab-separated input', () => {
  const r = fn('parsePasted')('Name\tRoom\tSerial\nFOH Mixer\tmain\tSQ5-1\nStage Box\tmain\tDX-2');
  assert.equal(r.delimiter, '\t', m('WIZARD', S, 'tab delimiter'));
  assert.deepEqual(r.header, ['Name', 'Room', 'Serial']);
  assert.deepEqual(r.rows, [['FOH Mixer', 'main', 'SQ5-1'], ['Stage Box', 'main', 'DX-2']]);
});

T('parsePasted detects comma-separated input', () => {
  const r = fn('parsePasted')('Name,Room,Status\nFOH Mixer,main,installed\nStage Box,main,planned');
  assert.equal(r.delimiter, ',', m('WIZARD', S, 'comma delimiter'));
  assert.deepEqual(r.header, ['Name', 'Room', 'Status']);
  assert.deepEqual(r.rows, [['FOH Mixer', 'main', 'installed'], ['Stage Box', 'main', 'planned']]);
});

T('parsePasted detects semicolon-separated input even when fields contain commas', () => {
  const r = fn('parsePasted')('Name;Room\nSpeaker, L;main\nSpeaker, R;main');
  assert.equal(r.delimiter, ';', m('WIZARD', S, 'semicolon delimiter'));
  assert.deepEqual(r.header, ['Name', 'Room']);
  assert.deepEqual(r.rows, [['Speaker, L', 'main'], ['Speaker, R', 'main']]);
});

T('parsePasted keeps quoted commas inside one field', () => {
  const r = fn('parsePasted')('Name,Room,Model\n"Mixer, FOH",main,SQ5\nStage Box,main,"DX168, rev B"');
  assert.equal(r.delimiter, ',');
  assert.deepEqual(r.rows, [['Mixer, FOH', 'main', 'SQ5'], ['Stage Box', 'main', 'DX168, rev B']]);
});

T('parsePasted unescapes doubled quotes inside a quoted field', () => {
  const r = fn('parsePasted')('Name,Room\n"55"" Display",main');
  assert.deepEqual(r.rows, [['55" Display', 'main']]);
});

T('parsePasted handles CRLF and a trailing newline', () => {
  const r = fn('parsePasted')('Name,Room\r\nFOH Mixer,main\r\nStage Box,main\r\n');
  assert.deepEqual(r.header, ['Name', 'Room']);
  assert.deepEqual(r.rows, [['FOH Mixer', 'main'], ['Stage Box', 'main']], m('WIZARD', S, 'no \\r left in fields; no empty trailing row'));
});

T('parsePasted skips empty lines', () => {
  const r = fn('parsePasted')('\nName\tRoom\n\nFOH Mixer\tmain\n\n\nStage Box\tmain\n\n');
  assert.equal(r.delimiter, '\t');
  assert.deepEqual(r.header, ['Name', 'Room'], m('WIZARD', S, 'first non-empty row is the header'));
  assert.deepEqual(r.rows, [['FOH Mixer', 'main'], ['Stage Box', 'main']]);
});

// ------------------------------------------------------------------ guessMapping

const DEVICE_FIELDS = ['id', 'name', 'room', 'status', 'kind', 'manufacturer', 'model', 'serial'];

T('guessMapping maps headers to field keys case-insensitively with synonyms', () => {
  const header = ['Device', 'Room', 'Serial no.', 'Colour of the sky'];
  const r = fn('guessMapping')(header, DEVICE_FIELDS);
  assert.deepEqual(header.map((_, i) => mappedAt(r, header, i)), ['name', 'room', 'serial', null]);
});

T('guessMapping matches exact keys regardless of case and surrounding spaces', () => {
  const header = ['NAME', ' room ', 'SERIAL', 'Status', 'Model'];
  const r = fn('guessMapping')(header, DEVICE_FIELDS);
  assert.deepEqual(header.map((_, i) => mappedAt(r, header, i)), ['name', 'room', 'serial', 'status', 'model']);
});

T('guessMapping knows Name and Serial number as synonyms', () => {
  const header = ['Serial number', 'Name'];
  const r = fn('guessMapping')(header, DEVICE_FIELDS);
  assert.deepEqual(header.map((_, i) => mappedAt(r, header, i)), ['serial', 'name']);
});

T('guessMapping only proposes keys from the given fields', () => {
  const header = ['Name', 'Serial'];
  const r = fn('guessMapping')(header, ['name', 'room']);
  assert.deepEqual(header.map((_, i) => mappedAt(r, header, i)), ['name', null]);
});

T('guessMapping maps cable From/To headers', () => {
  const header = ['From', 'To', 'Something else'];
  const r = fn('guessMapping')(header, ['from', 'to', 'tag', 'medium']);
  assert.deepEqual(header.map((_, i) => mappedAt(r, header, i)), ['from', 'to', null]);
});

// ------------------------------------------------------------------ validateDeviceRow

T('validateDeviceRow accepts a minimal and a full valid row', () => {
  const v = fn('validateDeviceRow');
  const doc = fx();
  assertValid(v(doc, { name: 'Lectern Mic' }), 'name only');
  assertValid(v(doc, { id: 'lectern-mic', name: 'Lectern Mic', room: 'main', status: 'planned', serial: 'SN-001' }), 'full row');
  for (const s of core('STATUSES')) assertValid(v(doc, { name: 'X', status: s }), 'status ' + s);
  assert.deepEqual(doc, fixture, m('WIZARD', S, 'validateDeviceRow must not mutate the doc'));
});

T('validateDeviceRow requires a name', () => {
  const v = fn('validateDeviceRow');
  assertFieldError(v(fx(), { room: 'main' }), 'name', 'missing name');
  assertFieldError(v(fx(), { name: '', room: 'main' }), 'name', 'empty name');
  assertFieldError(v(fx(), { name: '   ', room: 'main' }), 'name', 'blank name');
});

T('validateDeviceRow rejects an unknown room', () => {
  assertFieldError(fn('validateDeviceRow')(fx(), { name: 'X', room: 'no-such-room' }), 'room', 'unknown room');
});

T('validateDeviceRow rejects a status outside the vocab statuses', () => {
  assertFieldError(fn('validateDeviceRow')(fx(), { name: 'X', status: 'broken' }), 'status', 'unknown status');
});

T('validateDeviceRow rejects a duplicate id', () => {
  const existing = fixture.devices[0].id;
  assertFieldError(fn('validateDeviceRow')(fx(), { id: existing, name: 'X' }), 'id', 'duplicate id ' + existing);
});

// ------------------------------------------------------------------ validateCableRow

T('validateCableRow accepts free compatible ports as dev:port refs and as {device, port}', () => {
  const v = fn('validateCableRow');
  const doc = fx();
  const [p] = freePairs(doc, 1);
  assertValid(v(doc, { from: asRef(p.from), to: asRef(p.to) }), 'string refs');
  assertValid(v(doc, { from: clone(p.from), to: clone(p.to) }), 'object refs');
  assert.deepEqual(doc, fixture, m('WIZARD', S, 'validateCableRow must not mutate the doc'));
});

T('validateCableRow rejects an unknown device on either end', () => {
  const v = fn('validateCableRow');
  const [p] = freePairs(fx(), 1);
  assertFieldError(v(fx(), { from: 'no-such-device:out-1', to: asRef(p.to) }), 'from', 'unknown from device');
  assertFieldError(v(fx(), { from: asRef(p.from), to: { device: 'no-such-device', port: 'in-1' } }), 'to', 'unknown to device');
});

T('validateCableRow rejects an unknown port on either end', () => {
  const v = fn('validateCableRow');
  const [p] = freePairs(fx(), 1);
  assertFieldError(v(fx(), { from: p.from.device + ':no-such-port', to: asRef(p.to) }), 'from', 'unknown from port');
  assertFieldError(v(fx(), { from: asRef(p.from), to: { device: p.to.device, port: 'no-such-port' } }), 'to', 'unknown to port');
});

T('validateCableRow rejects an occupied port unless repatch', () => {
  const v = fn('validateCableRow');
  const sink = occupiedSinkCase(fx());
  assertFieldError(v(fx(), { from: asRef(sink.from), to: asRef(sink.to) }), 'to', 'occupied input ' + asRef(sink.to));
  assertValid(v(fx(), { from: asRef(sink.from), to: asRef(sink.to), repatch: true }), 'occupied input with repatch');
  const src = occupiedSourceCase(fx());
  assertFieldError(v(fx(), { from: clone(src.from), to: clone(src.to) }), 'from', 'occupied output ' + asRef(src.from));
});

T('validateCableRow rejects what canConnect rates level error', () => {
  const v = fn('validateCableRow');
  const bad = inputToInputCase(fx());
  assertInvalid(v(fx(), { from: asRef(bad.from), to: asRef(bad.to) }), 'input -> input (bad_direction)');
  const [p] = freePairs(fx(), 1);
  assertInvalid(v(fx(), { from: asRef(p.from), to: asRef(p.from) }), 'self loop');
});

T('validateCableRow requires both endpoints', () => {
  const v = fn('validateCableRow');
  const [p] = freePairs(fx(), 1);
  assertFieldError(v(fx(), { to: asRef(p.to) }), 'from', 'missing from');
  assertFieldError(v(fx(), { from: asRef(p.from), to: '' }), 'to', 'empty to');
});

// ------------------------------------------------------------------ bulkDeviceOps

T('bulkDeviceOps adds N devices to the given room with unique ids and no new errors', () => {
  const base = apply(fx(), [{ op: 'put', coll: 'rooms', id: 'annex', value: { id: 'annex', venue: 'hillside', name: 'Annex' } }]);
  const before = clone(base);
  const existingIds = new Set(base.devices.map((d) => d.id));
  const rows = [
    { name: 'Lectern Mic' },
    { name: 'Lectern Mic' },
    { name: fixture.devices[0].name },
    { name: 'Confidence Monitor', status: 'planned' },
  ];
  const ops = asOps(fn('bulkDeviceOps')(base, rows, { room: 'annex' }));
  assert.ok(Array.isArray(ops), m('WIZARD', S, 'bulkDeviceOps must return ops'));
  assert.deepEqual(base, before, m('WIZARD', S, 'bulkDeviceOps must not mutate the doc'));
  for (const op of ops) {
    assert.equal(op.op, 'put', m('§4.9', S, 'device add ops are puts (shaped like duplicateDeviceOps)'));
    assert.equal(op.coll, 'devices', m('§4.9', S, 'bulkDeviceOps touches devices only'));
  }
  const after = apply(base, ops);
  assert.equal(after.devices.length, base.devices.length + rows.length, m('WIZARD', S, 'N more devices'));
  const added = after.devices.filter((d) => !existingIds.has(d.id));
  assert.equal(added.length, rows.length, m('WIZARD', S, 'each row gets a new, unused id'));
  assert.equal(new Set(added.map((d) => d.id)).size, rows.length, m('WIZARD', S, 'ids unique within the batch'));
  for (const d of added) assert.equal(d.room, 'annex', m('WIZARD', S, d.id + ' must be in the given room'));
  assert.deepEqual(added.map((d) => d.name).sort(), rows.map((r) => r.name).sort(), m('WIZARD', S, 'names preserved'));
  assert.equal(added.find((d) => d.name === 'Confidence Monitor').status, 'planned', m('WIZARD', S, 'status carried over'));
  assert.equal((core('indexDoc')(after).devicesByRoom.annex || []).length, rows.length);
  assert.deepEqual(errorKeys(after), errorKeys(base), m('WIZARD', S, 'validateLocal reports no new errors'));
});

T('bulkDeviceOps keeps an explicit row id and stores serial under inventory.serial', () => {
  const doc = fx();
  const ops = asOps(fn('bulkDeviceOps')(doc, [{ id: 'lectern-mic', name: 'Lectern Mic', serial: 'SN-001' }], { room: 'main' }));
  const after = apply(doc, ops);
  const d = after.devices.find((x) => x.id === 'lectern-mic');
  assert.ok(d, m('WIZARD', S, 'a valid row id is used as the device id'));
  assert.equal(d.room, 'main');
  assert.equal(d.inventory && d.inventory.serial, 'SN-001', m('§4.3.8', S, 'serial lives in device.inventory.serial'));
  assert.deepEqual(errorKeys(after), errorKeys(doc));
});

T('bulkDeviceOps returns no ops for no rows', () => {
  assert.deepEqual(asOps(fn('bulkDeviceOps')(fx(), [], { room: 'main' })), []);
});

// ------------------------------------------------------------------ bulkCableOps

T('bulkCableOps adds cables between free compatible ports', () => {
  const doc = fx();
  const pairs = freePairs(doc, 2);
  const rows = [
    { from: asRef(pairs[0].from), to: asRef(pairs[0].to) },
    { from: clone(pairs[1].from), to: clone(pairs[1].to) },
  ];
  const existing = new Set(doc.cables.map((c) => c.id));
  const ops = asOps(fn('bulkCableOps')(doc, rows));
  assert.ok(Array.isArray(ops), m('WIZARD', S, 'bulkCableOps must return ops'));
  assert.deepEqual(doc, fixture, m('WIZARD', S, 'bulkCableOps must not mutate the doc'));
  for (const op of ops) {
    assert.equal(op.op, 'put', m('§4.9', S, 'cable add ops are puts (connectOps)'));
    assert.equal(op.coll, 'cables', m('§4.9', S, 'bulkCableOps touches cables only'));
  }
  const after = apply(doc, ops);
  assert.equal(after.cables.length, doc.cables.length + rows.length, m('WIZARD', S, 'N more cables'));
  const added = after.cables.filter((c) => !existing.has(c.id));
  assert.equal(added.length, rows.length, m('WIZARD', S, 'each cable gets a new, unused id'));
  for (const p of pairs) {
    const c = added.find((x) => x.from && x.to && x.from.device === p.from.device && x.from.port === p.from.port);
    assert.ok(c, m('WIZARD', S, 'cable from ' + asRef(p.from)));
    assert.deepEqual({ device: c.to.device, port: c.to.port }, p.to, m('WIZARD', S, 'cable to ' + asRef(p.to)));
    assert.equal(c.medium, p.medium, m('§4.3.10', S, 'medium taken from the ports'));
  }
  const idx = core('indexDoc')(after);
  for (const p of pairs) {
    assert.equal((idx.cablesByPort[asRef(p.from)] || []).length, 1);
    assert.equal((idx.cablesByPort[asRef(p.to)] || []).length, 1);
  }
  assert.deepEqual(problemKeys(after), problemKeys(doc), m('WIZARD', S, 'validateLocal reports no new problems'));
});

T('bulkCableOps returns no ops for no rows', () => {
  assert.deepEqual(asOps(fn('bulkCableOps')(fx(), [])), []);
});

// ------------------------------------------------------------------ canAdvance

T('canAdvance is false with errors and true without', () => {
  const ca = fn('canAdvance');
  for (const step of ['paste', 'map', 'preview', 0, 2]) {
    assert.equal(ca(step, {}), true, m('WIZARD', S, 'no errors -> can advance (' + step + ')'));
    assert.equal(ca(step, { name: 'Name is required' }), false, m('WIZARD', S, 'errors -> cannot advance (' + step + ')'));
    assert.equal(ca(step, null), true, m('WIZARD', S, 'null errors -> can advance'));
    assert.equal(ca(step, undefined), true, m('WIZARD', S, 'undefined errors -> can advance'));
    assert.equal(ca(step, []), true, m('WIZARD', S, 'empty error list -> can advance'));
    assert.equal(ca(step, [{ name: 'Name is required' }]), false, m('WIZARD', S, 'error list -> cannot advance'));
  }
});
