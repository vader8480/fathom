// WIZARD unit tests for js/wizard-core.js beyond tests/js/wizard-contract.test.mjs:
// parsing details, header handling, mapping, lookups, batch validation, id
// generation, repatch ops, text helpers and remembered form values.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadFixtureDoc, loadVocab, clone } from './fixtures/helpers.mjs';

const { mod: W, error } = await loadModule('js/wizard-core.js', 'WIZARD');
const { mod: mc } = await loadModule('js/model-core.js', 'W5');
if (error) throw error;

const vocab = loadVocab();
const fixture = loadFixtureDoc();
const fx = () => clone(fixture);
const apply = (doc, ops) => mc.applyOps(doc, ops).doc;
const errors = (doc) => mc.validateLocal(doc, vocab).filter((p) => p.level === 'error').map((p) => p.code + ' ' + p.ref).sort();

function memStorage(seed) {
  const m = Object.assign({}, seed || {});
  return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, removeItem: (k) => { delete m[k]; }, _m: m };
}

// ------------------------------------------------------------ parsing

test('splitRecords keeps newlines inside quoted fields', () => {
  const r = W.splitRecords('Name,Note\n"Mixer","line 1\nline 2"\nBox,x', ',');
  assert.deepEqual(r, [['Name', 'Note'], ['Mixer', 'line 1\nline 2'], ['Box', 'x']]);
});

test('splitRecords trims unquoted fields, keeps quoted spacing and drops delimiter-only lines', () => {
  assert.deepEqual(W.splitRecords('  a  ,  " b "  \n,,\n \t \n', ','), [['a', ' b ']]);
  assert.deepEqual(W.splitRecords('x;y\n;\n', ';'), [['x', 'y']]);
});

test('detectDelimiter prefers the delimiter giving consistent columns', () => {
  assert.equal(W.detectDelimiter('a\tb, c\nd\te, f'), '\t');
  assert.equal(W.detectDelimiter('a;b,c\nd;e,f'), ';');
  assert.equal(W.detectDelimiter('a,b\nc,d'), ',');
  assert.equal(W.detectDelimiter('just names\nanother'), ',', 'single column falls back to comma');
});

test('parsePasted with header false names the columns and keeps the first row', () => {
  const r = W.parsePasted('Mic 1,main\nMic 2,main', { header: false });
  assert.deepEqual(r.header, ['Column 1', 'Column 2']);
  assert.equal(r.rows.length, 2);
});

test('parsePasted extends the header for rows longer than it', () => {
  const r = W.parsePasted('Name\tRoom\nA\tmain\tSN-1');
  assert.deepEqual(r.header, ['Name', 'Room', 'Column 3']);
  assert.deepEqual(r.rows[0], ['A', 'main', 'SN-1']);
});

test('parsePasted of empty text gives no header and no rows', () => {
  assert.deepEqual(W.parsePasted('  \n\n').rows, []);
  assert.deepEqual(W.parsePasted('').header, []);
});

test('parsePasted honours a forced delimiter', () => {
  const r = W.parsePasted('a;b,c\n1;2,3', { delimiter: ',' });
  assert.equal(r.delimiter, ',');
  assert.deepEqual(r.header, ['a;b', 'c']);
});

// ------------------------------------------------------------ mapping

test('guessMapping maps a field once (first column wins) and accepts field objects', () => {
  const r = W.guessMapping(['Name', 'Device', 'Make'], W.DEVICE_FIELDS);
  assert.deepEqual(r, ['name', null, 'manufacturer']);
});

test('guessMapping prefers exact keys over synonyms', () => {
  assert.deepEqual(W.guessMapping(['Type', 'Kind'], W.DEVICE_FIELDS), [null, 'kind'], 'exact Kind beats the Type synonym');
  assert.deepEqual(W.guessMapping(['Type'], W.DEVICE_FIELDS), ['kind'], 'Type is a device synonym for kind');
  assert.deepEqual(W.guessMapping(['Type'], W.CABLE_FIELDS), ['type']);
  assert.deepEqual(W.guessMapping(['Asset tag', 'Length (m)', 'From port'], W.DEVICE_FIELDS.concat(W.CABLE_FIELDS)), ['asset_tag', 'length_m', 'from_port']);
});

test('looksLikeHeader is true only when a column maps', () => {
  assert.equal(W.looksLikeHeader(['Name', 'x'], W.DEVICE_FIELDS), true);
  assert.equal(W.looksLikeHeader(['Mic 1', 'main'], W.DEVICE_FIELDS), false);
});

test('mappingErrors reports required fields and doubly mapped columns', () => {
  const e = W.mappingErrors(['room', 'room'], W.DEVICE_FIELDS, ['Room', 'Space']);
  assert.match(e.mapping, /Name/);
  assert.match(e['col-1'], /Room is already mapped to “Room”/);
  assert.deepEqual(W.mappingErrors(['name', null], W.DEVICE_FIELDS, ['Name', 'x']), {});
  const c = W.mappingErrors(['from'], W.CABLE_FIELDS, ['From']);
  assert.match(c.mapping, /To/);
});

test('rowObject builds a field object; the first non-empty duplicate wins', () => {
  assert.deepEqual(W.rowObject([' A ', '', 'B'], ['name', 'room', null]), { name: 'A', room: '' });
  assert.deepEqual(W.rowObject(['', 'x'], ['name', 'name']), { name: 'x' });
  assert.deepEqual(W.rowObject(['only'], ['name', 'room']), { name: 'only', room: '' });
});

test('applyRemembered overrides guesses and clears the displaced column', () => {
  const header = ['Device', 'Label'];
  const guess = W.guessMapping(header, W.DEVICE_FIELDS);
  assert.deepEqual(guess, ['name', null]);
  const out = W.applyRemembered(header, guess, { label: 'name', device: null }, W.DEVICE_FIELDS);
  assert.deepEqual(out, [null, 'name']);
  assert.deepEqual(W.applyRemembered(header, guess, { device: 'bogus' }, W.DEVICE_FIELDS), guess, 'unknown fields ignored');
  assert.deepEqual(W.rememberMapping(['Device', 'Column 2'], ['name', 'room']), { device: 'name' });
});

// ------------------------------------------------------------ lookups

test('resolveRoom matches id, then name or code case-insensitively', () => {
  const doc = fx();
  assert.equal(W.resolveRoom(doc, 'main'), 'main');
  assert.equal(W.resolveRoom(doc, 'main auditorium'), 'main');
  assert.equal(W.resolveRoom(doc, 'nowhere'), null);
  assert.equal(W.resolveRoom(doc, ''), '');
});

test('resolveStatus and resolveKind accept case and labels', () => {
  assert.equal(W.resolveStatus('Planned'), 'planned');
  assert.equal(W.resolveStatus('broken'), null);
  assert.equal(W.resolveKind('Loudspeakers', vocab), 'speaker');
  assert.equal(W.resolveKind('Wireless RX', vocab), 'wireless_rx');
  assert.equal(W.resolveKind('flux capacitor', vocab), null);
  assert.equal(W.resolveKind('flux capacitor', null), 'flux capacitor', 'no vocab: kept');
});

test('resolveEndpoint matches devices and ports by id, name or label', () => {
  const doc = fx();
  assert.deepEqual(W.resolveEndpoint(doc, 'audio-rack-1:analog-in-5'), { device: 'audio-rack-1', port: 'analog-in-5' });
  assert.deepEqual(W.resolveEndpoint(doc, 'Audio Rack 1:Input 5'), { device: 'audio-rack-1', port: 'analog-in-5' });
  assert.deepEqual(W.resolveEndpoint(doc, 'atem mini', 'Program Out'), { device: 'atem-mini', port: 'hdmi-out-1' });
  assert.deepEqual(W.resolveEndpoint(doc, 'ATEM Mini'), { device: 'atem-mini', port: null }, 'device-level endpoint');
  assert.match(W.resolveEndpoint(doc, 'Stage Box 1:Input 1').error, /More than one port/);
  assert.match(W.resolveEndpoint(doc, 'Nope:1').error, /Unknown device/);
  assert.equal(W.resolveEndpoint(doc, '').error, 'required');
});

test('resolveEndpoint copes with a colon inside a device name', () => {
  const doc = fx();
  doc.devices.push({ id: 'amp-a', name: 'Amp: A', kind: 'amp', ports: [{ id: 'in-1', name: 'In 1', dir: 'in', medium: 'analog' }] });
  assert.deepEqual(W.resolveEndpoint(doc, 'Amp: A:In 1'), { device: 'amp-a', port: 'in-1' });
});

// ------------------------------------------------------------ validators

test('validateDeviceRow rejects malformed ids and checks the default room', () => {
  const doc = fx();
  assert.ok(W.validateDeviceRow(doc, { id: 'has space', name: 'X' }).id);
  assert.ok(W.validateDeviceRow(doc, { name: 'X' }, { room: 'gone' }).room);
  assert.deepEqual(W.validateDeviceRow(doc, { name: 'X', room: 'Main Auditorium' }), {});
  assert.ok(W.validateDeviceRow(doc, { name: 'X', kind: 'flux' }, { vocab }).kind);
  assert.deepEqual(W.validateDeviceRow(doc, { name: 'X', kind: 'Displays' }, { vocab }), {});
});

test('validateDeviceRow treats extra-card ids as taken', () => {
  const doc = fx();
  doc.rooms[0].flow = { extra_cards: [{ id: 'xcard', device: 'atem-mini' }] };
  assert.ok(W.validateDeviceRow(doc, { id: 'xcard', name: 'X' }).id);
});

test('deviceRowWarnings notes an existing name without blocking', () => {
  assert.ok(W.deviceRowWarnings(fx(), { name: 'atem mini' }).name);
  assert.deepEqual(W.deviceRowWarnings(fx(), { name: 'Brand new' }), {});
});

test('validateRows flags duplicate ids inside the batch', () => {
  const r = W.validateRows(fx(), 'devices', [{ id: 'new-a', name: 'A' }, { id: 'new-a', name: 'B' }, { name: '' }]);
  assert.deepEqual(r[0].errors, {});
  assert.match(r[1].errors.id, /another pasted row/);
  assert.ok(r[2].errors.name);
});

test('validateCableRow accepts separate port columns and checks length, medium and status', () => {
  const doc = fx();
  assert.deepEqual(W.validateCableRow(doc, { from: 'main-speakers', from_port: 'thru-1', to: 'audio-rack-1', to_port: 'Input 5' }), {});
  assert.ok(W.validateCableRow(doc, { from: 'main-speakers:thru-1', to: 'audio-rack-1:analog-in-5', length_m: 'long' }).length_m);
  assert.ok(W.validateCableRow(doc, { from: 'main-speakers:thru-1', to: 'audio-rack-1:analog-in-5', medium: 'smoke' }, { vocab }).medium);
  assert.ok(W.validateCableRow(doc, { from: 'main-speakers:thru-1', to: 'audio-rack-1:analog-in-5', status: 'gone' }).status);
});

test('validateCableRow mentions the cable tag of an occupied port; repatch accepts truthy text', () => {
  const doc = fx();
  const e = W.validateCableRow(doc, { from: 'main-speakers:thru-1', to: 'audio-rack-1:analog-in-3' });
  assert.match(e.to, /already patched \(cable A-001\)/);
  assert.deepEqual(W.validateCableRow(doc, { from: 'main-speakers:thru-1', to: 'audio-rack-1:analog-in-3', repatch: 'yes' }), {});
  assert.deepEqual(W.validateCableRow(doc, { from: 'main-speakers:thru-1', to: 'audio-rack-1:analog-in-3' }, { repatch: true }), {});
});

test('validateRows flags a port claimed by two pasted rows and repeated tags', () => {
  const rows = [
    { from: 'main-speakers:thru-1', to: 'audio-rack-1:analog-in-5', tag: 'T-1' },
    { from: 'main-speakers:thru-2', to: 'audio-rack-1:analog-in-5', tag: 'T-1' },
    { from: 'main-speakers:thru-2', to: 'audio-rack-1:analog-in-6', tag: 'A-001' },
  ];
  const r = W.validateRows(fx(), 'cables', rows, { vocab });
  assert.deepEqual(r[0].errors, {});
  assert.match(r[1].errors.to, /used by row 1/);
  assert.match(r[1].warnings.tag, /repeats row 1/);
  assert.deepEqual(r[2].errors, {}, 'row 2 failed, so thru-2 is still free for row 3');
  assert.match(r[2].warnings.tag, /already used/);
});

test('cableRowWarnings reports a medium mismatch', () => {
  const w = W.cableRowWarnings(fx(), { from: 'atem-mini:hdmi-out-1', to: 'samsung-tv-1:sdi-in-1' }, { vocab });
  assert.match(w.to, /HDMI/);
});

// ------------------------------------------------------------ ops

test('bulkDeviceOps makes slug ids unique against the doc and the batch', () => {
  const doc = fx();
  const ops = W.bulkDeviceOps(doc, [{ name: 'ATEM Mini' }, { name: 'ATEM Mini' }, { name: 'Lectern' }, { name: '  ' }], { room: 'main' });
  assert.deepEqual(ops.map((o) => o.id), ['atem-mini-2', 'atem-mini-3', 'lectern'], 'blank names skipped');
  const after = apply(doc, ops);
  assert.deepEqual(errors(after), errors(doc));
});

test('bulkDeviceOps resolves row room, kind, status and stores asset tag and note', () => {
  const doc = fx();
  doc.rooms.push({ id: 'annex', venue: doc.rooms[0].venue, name: 'Annex' });
  const [op] = W.bulkDeviceOps(doc, [{ name: 'Sub', room: 'Annex', kind: 'Loudspeakers', status: 'Spare', asset_tag: 'AT-9', note: 'n', manufacturer: 'd&b', model: 'B6' }], { room: 'main', vocab });
  assert.deepEqual(op.value, { id: 'sub', name: 'Sub', kind: 'speaker', room: 'annex', manufacturer: 'd&b', model: 'B6', status: 'spare', note: 'n', inventory: { asset_tag: 'AT-9' }, ports: [] });
});

test('bulkDeviceOps without a room leaves the device roomless and replaces an invalid row id', () => {
  const [op] = W.bulkDeviceOps(fx(), [{ id: 'bad id', name: 'Thing' }], {});
  assert.equal(op.id, 'thing');
  assert.equal('room' in op.value, false);
  const [shared] = W.bulkDeviceOps(fx(), [{ name: 'Spare' }], { room: '' });
  assert.equal(shared.value.room, '', 'empty room = shared inventory');
});

test('bulkCableOps carries tag, type, length in settings units, colour, label and status', () => {
  const doc = fx();
  const ops = W.bulkCableOps(doc, [{ from: 'Main Speakers - L/R:Thru 1', to: 'audio-rack-1:analog-in-5', tag: 'X-1', type: 'XLR3', length_m: '10', color: 'red', label: 'Thru', status: 'planned' }], { vocab });
  assert.equal(ops.length, 1);
  const c = ops[0].value;
  assert.deepEqual([c.from, c.to, c.medium, c.tag, c.type, c.color, c.label, c.status], [{ device: 'main-speakers', port: 'thru-1' }, { device: 'audio-rack-1', port: 'analog-in-5' }, 'analog', 'X-1', 'XLR3', 'red', 'Thru', 'planned']);
  assert.equal(c.length_m, 3.048, 'fixture units are imperial: 10 ft');
  assert.ok(!doc.cables.some((x) => x.id === c.id));
});

test('bulkCableOps with repatch deletes the cables on the reused ports first', () => {
  const doc = fx();
  const rows = [{ from: 'main-speakers:thru-1', to: 'audio-rack-1:analog-in-3', repatch: 'x' }];
  assert.equal(W.validateRows(doc, 'cables', rows)[0].errors.to, undefined);
  const ops = W.bulkCableOps(doc, rows);
  assert.deepEqual(W.replacedCables(ops), ['c-0003']);
  assert.deepEqual(ops.map((o) => o.op), ['del', 'put']);
  const after = apply(doc, ops);
  const idx = mc.indexDoc(after);
  assert.equal(idx.cablesByPort['audio-rack-1:analog-in-3'].length, 1);
  assert.equal(idx.cablesByPort['audio-rack-1:analog-in-3'][0].from.device, 'main-speakers');
  assert.equal(after.cables.length, doc.cables.length);
});

test('bulkCableOps skips unresolvable rows and gives unique ids', () => {
  const ops = W.bulkCableOps(fx(), [
    { from: 'nope:1', to: 'audio-rack-1:analog-in-5' },
    { from: 'main-speakers:thru-1', to: 'audio-rack-1:analog-in-5' },
    { from: 'main-speakers:thru-2', to: 'audio-rack-1:analog-in-6' },
  ]);
  assert.equal(ops.length, 2);
  assert.notEqual(ops[0].id, ops[1].id);
});

// ------------------------------------------------------------ steps and text

test('canAdvance treats falsy messages as no error and strings in a list as errors', () => {
  assert.equal(W.canAdvance('map', { name: '' }), true);
  assert.equal(W.canAdvance('map', ['bad']), false);
  assert.equal(W.canAdvance('map', [{}, null]), true);
});

test('reviewText, commitLabel and plural word counts', () => {
  assert.equal(W.reviewText('devices', 18, 'Main Auditorium'), 'Add 18 devices to Main Auditorium');
  assert.equal(W.reviewText('devices', 1, ''), 'Add 1 device to shared inventory');
  assert.equal(W.reviewText('cables', 2, 'Chapel'), 'Add 2 cables in Chapel');
  assert.equal(W.reviewText('cables', 1), 'Add 1 cable');
  assert.equal(W.commitLabel('devices', 18), 'Bulk add 18 devices');
  assert.equal(W.commitLabel('cables', 1), 'Bulk add 1 cable');
});

test('resultRoute targets the device page, the devices landing or the cables schedule', () => {
  assert.deepEqual(W.resultRoute('devices', ['a']), { view: 'devices', id: 'a', query: {} });
  assert.deepEqual(W.resultRoute('devices', ['a', 'b']), { view: 'devices', query: { hl: 'a', 'f.id': 'a|b' } });
  assert.deepEqual(W.resultRoute('cables', ['c-1', 'c-2']), { view: 'schedules', tab: 'cables', query: { hl: 'c-1', 'f.id': 'c-1|c-2' } });
  const many = Array.from({ length: 51 }, (_, i) => 'd' + i);
  assert.deepEqual(W.resultRoute('devices', many).query, { hl: 'd0' }, 'no filter list past 50 rows');
});

// ------------------------------------------------------------ remembered form values

test('saveForm and loadForm round-trip under fathom.ui.form.<key>', () => {
  const s = memStorage();
  assert.equal(W.saveForm(s, 'bulk-devices', { room: 'main' }), true);
  assert.ok(s._m['fathom.ui.form.bulk-devices']);
  assert.deepEqual(W.loadForm(s, 'bulk-devices'), { room: 'main' });
});

test('loadForm tolerates missing, corrupt and non-object values and throwing storage', () => {
  assert.equal(W.loadForm(memStorage(), 'x'), null);
  assert.equal(W.loadForm(memStorage({ 'fathom.ui.form.x': '{nope' }), 'x'), null);
  assert.equal(W.loadForm(memStorage({ 'fathom.ui.form.x': '[1]' }), 'x'), null);
  const bad = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  assert.equal(W.loadForm(bad, 'x'), null);
  assert.equal(W.saveForm(bad, 'x', {}), false);
  assert.equal(W.loadForm(null, 'x'), null);
});
