// Rackula DSP: js/rack-display-core.js and js/rack-display.js loadTemplateInfo against
// docs/SPEC.md §4.4.7 (category colours, annotations) and §6.13.11 (display modules).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadVocab, clone } from './fixtures/helpers.mjs';

const core = await loadModule('js/rack-display-core.js', 'DSP');
const dom = await loadModule('js/rack-display.js', 'DSP');
for (const [name, r] of [['rack-display-core.js', core], ['rack-display.js', dom]]) {
  if (r.error) test(`${name} imports in Node`, () => { throw r.error; });
}
const skipCore = core.skip || (core.error ? 'rack-display-core.js failed to import' : false);
const skipDom = dom.skip || (dom.error ? 'rack-display.js failed to import' : false);
const T = (name, fn) => test(name, { skip: skipCore }, fn);
const TD = (name, fn) => test(name, { skip: skipDom }, fn);
const D = core.mod || {};
const vocab = loadVocab();

const CATS = {
  server: '#4A7A8A', network: '#7968A6', firewall: '#C0392B', storage: '#3D7A4A', power: '#A84A4A',
  kvm: '#926A40', 'av-media': '#A85A7A', cooling: '#75753F', chassis: '#5A6A8A', shelf: '#6272A4',
  blank: '#44475A', 'cable-management': '#6272A4', 'patch-panel': '#6272A4', other: '#6272A4',
};

function dev(extra) {
  return Object.assign({id: 'd1', name: 'Amp 1', kind: 'amp', ports: [], rack: {id: 'r1', u: 3, face: 'front'}}, extra || {});
}

// ------------------------------------------------------------------ constants

T('DISPLAY_MODES, ANNOTATION_FIELDS, STORAGE', () => {
  assert.deepEqual(D.DISPLAY_MODES, ['label', 'image', 'both']);
  assert.deepEqual(D.ANNOTATION_FIELDS, [
    {key: '', label: 'None'}, {key: 'name', label: 'Name'}, {key: 'model', label: 'Model'},
    {key: 'ip', label: 'IP address'}, {key: 'serial', label: 'Serial'}, {key: 'asset_tag', label: 'Asset tag'},
    {key: 'code', label: 'Code'}, {key: 'power', label: 'Power'}, {key: 'weight', label: 'Weight'},
    {key: 'status', label: 'Status'},
  ]);
  assert.deepEqual(D.STORAGE, {display: 'fathom.ui.rack.display', annotate: 'fathom.ui.rack.annotate', face: 'fathom.ui.rack.face'});
  for (const k of Object.values(D.STORAGE)) assert.ok(k.startsWith('fathom.ui.'), k);
});

T('CATEGORY_COLORS is exactly the contract B table', () => {
  assert.deepEqual(D.CATEGORY_COLORS, CATS);
});

// ------------------------------------------------------------------ blockColor

T('blockColor: a valid rack.color override wins', () => {
  assert.equal(D.blockColor(dev({rack: {id: 'r1', u: 1, color: '#123abc'}}), vocab, {rack_category: 'server'}), '#123abc');
  assert.equal(D.blockColor(dev({rack: {id: 'r1', u: 1, color: '#ABCDEF'}}), vocab, null), '#ABCDEF');
});

T('blockColor: an invalid colour override is ignored', () => {
  for (const bad of ['red', '#12345', '#1234567', '123456', '#ggg000', '#abc', '', null, 42, 'url(x)']) {
    assert.equal(D.blockColor(dev({rack: {id: 'r1', u: 1, color: bad}}), vocab, {rack_category: 'power'}), CATS.power, String(bad));
  }
});

T('blockColor: category colour from the template summary, also via a {templateId: summary} map', () => {
  for (const [cat, col] of Object.entries(CATS)) assert.equal(D.blockColor(dev(), vocab, {id: 't', rack_category: cat}), col, cat);
  const d = dev({template: 'apc-x'});
  assert.equal(D.blockColor(d, vocab, {'apc-x': {id: 'apc-x', rack_category: 'power'}, other: {id: 'other', rack_category: 'server'}}), CATS.power);
  assert.equal(D.blockColor(d, vocab, {other: {id: 'other', rack_category: 'server'}}), vocab.disciplines.audio.color, 'map without the device');
});

T('blockColor: unknown category falls back to the discipline colour', () => {
  assert.equal(D.blockColor(dev(), vocab, {rack_category: 'spaceship'}), vocab.disciplines.audio.color);
  assert.equal(D.blockColor(dev(), vocab, {rack_category: 'constructor'}), vocab.disciplines.audio.color, 'no prototype keys');
});

T('blockColor: discipline from device.discipline, else the kind', () => {
  assert.equal(D.blockColor(dev(), vocab, null), vocab.disciplines.audio.color);
  assert.equal(D.blockColor(dev({discipline: 'video'}), vocab, null), vocab.disciplines.video.color);
  assert.equal(D.blockColor(dev({kind: 'switch'}), vocab, {}), vocab.disciplines.network.color);
});

T('blockColor: final fallback #9aa3b5', () => {
  assert.equal(D.blockColor(dev({kind: 'nope'}), {}, null), '#9aa3b5');
  assert.equal(D.blockColor(dev({kind: 'nope'}), null, undefined), '#9aa3b5');
  assert.equal(D.blockColor(dev({discipline: 'mystery'}), {kinds: {}, disciplines: {}}, null), '#9aa3b5');
  assert.equal(D.blockColor({}, vocab, null), vocab.disciplines.other.color);
  assert.equal(D.blockColor(null, null, null), '#9aa3b5');
});

// ------------------------------------------------------------------ deviceImage

T('deviceImage: template images per face, with base', () => {
  const info = {id: 'apc', image_front: 'apc/x.front.webp', image_rear: 'apc/x.rear.webp'};
  assert.equal(D.deviceImage(dev(), info, 'front', {}), 'static/rack-images/apc/x.front.webp');
  assert.equal(D.deviceImage(dev(), info, 'rear', {base: '/fathom/'}), '/fathom/static/rack-images/apc/x.rear.webp');
  assert.equal(D.deviceImage(dev(), info, 'front'), 'static/rack-images/apc/x.front.webp', 'opts optional');
  assert.equal(D.deviceImage(dev(), {id: 'a', image_front: '/apc/y.webp'}, 'front', {base: '/'}), '/static/rack-images/apc/y.webp');
});

T('deviceImage: rear without an image is empty, never the front image', () => {
  const info = {id: 'apc', image_front: 'apc/x.front.webp'};
  assert.equal(D.deviceImage(dev(), info, 'rear', {base: '/'}), '');
  const d = dev({rack: {id: 'r1', u: 1, image_front: 'att-1'}});
  assert.equal(D.deviceImage(d, info, 'rear', {attachmentUrl: (a) => '/files/' + a}), '');
});

T('deviceImage: attachment override per face via opts.attachmentUrl', () => {
  const info = {id: 'apc', image_front: 'apc/x.front.webp', image_rear: 'apc/x.rear.webp'};
  const d = dev({rack: {id: 'r1', u: 1, image_front: 'att-7'}});
  const opts = {base: '/', attachmentUrl: (a) => '/api/files/' + a};
  assert.equal(D.deviceImage(d, info, 'front', opts), '/api/files/att-7');
  assert.equal(D.deviceImage(d, info, 'rear', opts), '/static/rack-images/apc/x.rear.webp');
  assert.equal(D.deviceImage(d, info, 'front', {base: '/'}), '/static/rack-images/apc/x.front.webp', 'no attachmentUrl → template');
  assert.equal(D.deviceImage(d, null, 'front', opts), '/api/files/att-7', 'no template');
});

T('deviceImage: no info, unknown face or a map without the device', () => {
  assert.equal(D.deviceImage(dev(), null, 'front', {}), '');
  assert.equal(D.deviceImage(dev(), {id: 'x', image_front: 'a.webp'}, 'both', {}), '');
  assert.equal(D.deviceImage(dev(), {id: 'x', image_front: 'a.webp'}, undefined, {}), '');
  assert.equal(D.deviceImage(dev({template: 't'}), {t: {id: 't', image_front: 'a.webp'}}, 'front', {}), 'static/rack-images/a.webp');
  assert.equal(D.deviceImage(dev({template: 'q'}), {t: {id: 't', image_front: 'a.webp'}}, 'front', {}), '');
  assert.equal(D.deviceImage(dev(), {id: 'x', image_front: 7}, 'front', {}), '');
});

// ------------------------------------------------------------------ annotationValue

const DOC = {
  templates: [{id: 'tpl-amp', name: 'Amp', ru: 2, weight_kg: 12.5, power_w: 450, source: 'project'}],
  devices: [],
};

T('annotationValue: name, model, serial, asset_tag, code', () => {
  const d = dev({name: 'Amp 1', manufacturer: 'Powersoft', model: 'X8', code: 'AMP1', inventory: {serial: 'SN-1', asset_tag: 'A-9'}});
  assert.equal(D.annotationValue(DOC, d, 'name'), 'Amp 1');
  assert.equal(D.annotationValue(DOC, d, 'model'), 'Powersoft X8');
  assert.equal(D.annotationValue(DOC, d, 'serial'), 'SN-1');
  assert.equal(D.annotationValue(DOC, d, 'asset_tag'), 'A-9');
  assert.equal(D.annotationValue(DOC, d, 'code'), 'AMP1');
});

T('annotationValue: model is trimmed with one side missing', () => {
  assert.equal(D.annotationValue(DOC, dev({manufacturer: 'Shure'}), 'model'), 'Shure');
  assert.equal(D.annotationValue(DOC, dev({model: 'ULXD4Q'}), 'model'), 'ULXD4Q');
  assert.equal(D.annotationValue(DOC, dev({manufacturer: '', model: ''}), 'model'), '');
  assert.equal(D.annotationValue(DOC, dev(), 'model'), '');
});

T('annotationValue: missing fields give empty strings', () => {
  const d = {id: 'x', kind: 'other'};
  for (const f of ['name', 'model', 'ip', 'serial', 'asset_tag', 'code', 'power', 'weight']) assert.equal(D.annotationValue({}, d, f), '', f);
  assert.equal(D.annotationValue({}, dev({inventory: null}), 'serial'), '');
  assert.equal(D.annotationValue({}, dev({inventory: 'bad'}), 'asset_tag'), '');
});

T('annotationValue: unknown or empty field and no device', () => {
  assert.equal(D.annotationValue(DOC, dev(), ''), '');
  assert.equal(D.annotationValue(DOC, dev(), 'nope'), '');
  assert.equal(D.annotationValue(DOC, dev(), undefined), '');
  assert.equal(D.annotationValue(DOC, null, 'name'), '');
});

T('annotationValue: ip prefers the primary role, else the first non-empty ip', () => {
  const ifs = (list) => dev({interfaces: list});
  assert.equal(D.annotationValue(DOC, ifs([{id: 'a', role: 'control', ip: '10.0.0.5'}, {id: 'b', role: 'primary', ip: '10.0.0.9'}]), 'ip'), '10.0.0.9');
  assert.equal(D.annotationValue(DOC, ifs([{id: 'p', role: 'primary', ip: ''}, {id: 'c', role: 'control', ip: '10.0.0.7'}]), 'ip'), '10.0.0.7', 'primary without ip skipped');
  assert.equal(D.annotationValue(DOC, ifs([{id: 'a', role: 'media'}, {id: 'b', role: 'secondary', ip: '192.168.1.2'}, {id: 'c', ip: '192.168.1.3'}]), 'ip'), '192.168.1.2');
  assert.equal(D.annotationValue(DOC, ifs([{id: 'a', ip: '10.1.1.1'}, {id: 'b', role: 'primary', ip: '10.1.1.2'}]), 'ip'), '10.1.1.2', 'role must be "primary"');
  assert.equal(D.annotationValue(DOC, ifs([{id: 'a', role: 'primary', ip: '10.0.0.1'}, {id: 'b', role: 'primary', ip: '10.0.0.2'}]), 'ip'), '10.0.0.1');
});

T('annotationValue: ip with missing or odd interfaces', () => {
  assert.equal(D.annotationValue(DOC, dev(), 'ip'), '');
  assert.equal(D.annotationValue(DOC, dev({interfaces: []}), 'ip'), '');
  assert.equal(D.annotationValue(DOC, dev({interfaces: null}), 'ip'), '');
  assert.equal(D.annotationValue(DOC, dev({interfaces: {ip: '1.2.3.4'}}), 'ip'), '');
  assert.equal(D.annotationValue(DOC, dev({interfaces: [null, 'x', {id: 'a', ip: '  '}, {id: 'b', ip: '10.9.9.9'}]}), 'ip'), '10.9.9.9');
});

T('annotationValue: power and weight from the device, without a trailing .0', () => {
  assert.equal(D.annotationValue(DOC, dev({power_w: 250}), 'power'), '250 W');
  assert.equal(D.annotationValue(DOC, dev({power_w: 250.0}), 'power'), '250 W');
  assert.equal(D.annotationValue(DOC, dev({power_w: 12.5}), 'power'), '12.5 W');
  assert.equal(D.annotationValue(DOC, dev({weight_kg: 3}), 'weight'), '3 kg');
  assert.equal(D.annotationValue(DOC, dev({weight_kg: 3.25}), 'weight'), '3.25 kg');
  assert.equal(D.annotationValue(DOC, dev({weight_kg: '4.0'}), 'weight'), '4 kg', 'numeric strings');
});

T('annotationValue: power and weight fall back to info, then doc.templates', () => {
  const d = dev({template: 'tpl-amp'});
  assert.equal(D.annotationValue(DOC, d, 'power'), '450 W');
  assert.equal(D.annotationValue(DOC, d, 'weight'), '12.5 kg');
  assert.equal(D.annotationValue(DOC, d, 'power', {id: 'tpl-amp', power_w: 600}), '600 W', 'info summary first');
  assert.equal(D.annotationValue(DOC, d, 'weight', {'tpl-amp': {id: 'tpl-amp', weight_kg: 20}}), '20 kg', 'info map');
  assert.equal(D.annotationValue(DOC, d, 'weight', {other: {id: 'other', weight_kg: 99}}), '12.5 kg', 'map without the device');
  assert.equal(D.annotationValue(DOC, d, 'power', {id: 'tpl-amp', name: 'Amp'}), '450 W', 'info without the value');
  assert.equal(D.annotationValue(DOC, dev({template: 'tpl-amp', power_w: 100}), 'power', {id: 'tpl-amp', power_w: 600}), '100 W', 'device first');
  assert.equal(D.annotationValue({}, dev({template: 'tpl-amp'}), 'power'), '', 'no templates');
});

T('annotationValue: zero, negative and non-numeric power/weight give empty', () => {
  assert.equal(D.annotationValue(DOC, dev({power_w: 0}), 'power'), '');
  assert.equal(D.annotationValue(DOC, dev({weight_kg: -2}), 'weight'), '');
  assert.equal(D.annotationValue(DOC, dev({weight_kg: 'heavy'}), 'weight'), '');
  assert.equal(D.annotationValue(DOC, dev({template: 'tpl-amp', power_w: 0}), 'power'), '', 'device 0 overrides the template');
  assert.equal(D.annotationValue(DOC, dev({template: 'tpl-amp', power_w: null}), 'power'), '450 W', 'null is unset');
  assert.equal(D.annotationValue(DOC, dev({template: 'tpl-amp', weight_kg: ''}), 'weight'), '12.5 kg', 'empty string is unset');
});

T('annotationValue: status defaults to installed', () => {
  assert.equal(D.annotationValue(DOC, dev(), 'status'), 'installed');
  assert.equal(D.annotationValue(DOC, dev({status: ''}), 'status'), 'installed');
  assert.equal(D.annotationValue(DOC, dev({status: 'planned'}), 'status'), 'planned');
});

T('annotationValue: every ANNOTATION_FIELDS key returns a string', () => {
  const d = dev({template: 'tpl-amp', interfaces: [{id: 'p', ip: '10.0.0.1'}], inventory: {serial: 1234}});
  for (const f of D.ANNOTATION_FIELDS) assert.equal(typeof D.annotationValue(DOC, d, f.key), 'string', f.key);
  assert.equal(D.annotationValue(DOC, d, 'serial'), '1234');
});

T('annotationValue does not mutate its inputs', () => {
  const doc = clone(DOC);
  const d = dev({template: 'tpl-amp', interfaces: [{id: 'a', ip: '10.0.0.1'}]});
  const before = clone(d);
  for (const f of D.ANNOTATION_FIELDS) D.annotationValue(doc, d, f.key, {id: 'tpl-amp'});
  assert.deepEqual(d, before);
  assert.deepEqual(doc, DOC);
});

T('formatNumber and templateInfo helpers', () => {
  assert.equal(D.formatNumber(12), '12');
  assert.equal(D.formatNumber(12.0), '12');
  assert.equal(D.formatNumber(0.5), '0.5');
  const d = dev({template: 'tpl-amp'});
  assert.equal(D.templateInfo(DOC, d, null).id, 'tpl-amp');
  assert.equal(D.templateInfo(DOC, d, {id: 'other'}).id, 'other');
  assert.equal(D.templateInfo(DOC, dev(), null), null);
});

// ------------------------------------------------------------------ airflowGlyph

T('airflowGlyph: front-to-rear and rear-to-front are in/out per face', () => {
  const fIn = D.airflowGlyph('front-to-rear', 'front');
  const rOut = D.airflowGlyph('front-to-rear', 'rear');
  assert.ok(fIn.glyph && /intake/i.test(fIn.title), JSON.stringify(fIn));
  assert.ok(rOut.glyph && /exhaust/i.test(rOut.title), JSON.stringify(rOut));
  assert.notEqual(fIn.glyph, rOut.glyph);
  assert.deepEqual(D.airflowGlyph('rear-to-front', 'rear').glyph, fIn.glyph);
  assert.deepEqual(D.airflowGlyph('rear-to-front', 'front').glyph, rOut.glyph);
  assert.deepEqual(D.airflowGlyph('front-to-rear', undefined), fIn, 'face defaults to front');
});

T('airflowGlyph: sideways arrows, mirrored on the rear', () => {
  assert.equal(D.airflowGlyph('left-to-right', 'front').glyph, '\u2192');
  assert.equal(D.airflowGlyph('left-to-right', 'rear').glyph, '\u2190');
  assert.equal(D.airflowGlyph('right-to-left', 'front').glyph, '\u2190');
  assert.equal(D.airflowGlyph('right-to-left', 'rear').glyph, '\u2192');
  assert.ok(/exhaust/i.test(D.airflowGlyph('side-to-rear', 'rear').title));
  assert.ok(/side/i.test(D.airflowGlyph('side-to-rear', 'front').title));
  assert.ok(D.airflowGlyph('mixed', 'front').glyph);
});

T('airflowGlyph: null for passive, empty and unknown; titles are text', () => {
  for (const a of ['passive', '', null, undefined, 'sideways', 'FRONT-TO-REAR']) assert.equal(D.airflowGlyph(a, 'front'), null, String(a));
  for (const a of ['front-to-rear', 'rear-to-front', 'left-to-right', 'right-to-left', 'side-to-rear', 'mixed']) {
    for (const f of ['front', 'rear']) {
      const g = D.airflowGlyph(a, f);
      assert.deepEqual(Object.keys(g).sort(), ['glyph', 'title']);
      assert.ok(typeof g.glyph === 'string' && g.glyph.length >= 1 && /^[^<>&]+$/.test(g.title), a + ' ' + f);
    }
  }
});

// ------------------------------------------------------------------ textColorOn

function lum(hex) {
  const n = parseInt(hex.slice(1), 16);
  const c = (v) => { const s = v / 255; return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); };
  return 0.2126 * c((n >> 16) & 255) + 0.7152 * c((n >> 8) & 255) + 0.0722 * c(n & 255);
}

T('textColorOn: every CATEGORY_COLOR picks the higher-contrast text, at least 4.5:1', () => {
  for (const [cat, hex] of Object.entries(CATS)) {
    const L = lum(hex);
    const black = (L + 0.05) / 0.05;
    const white = 1.05 / (L + 0.05);
    const got = D.textColorOn(hex);
    assert.equal(got, black > white ? '#000' : '#fff', cat);
    assert.ok(Math.max(black, white) >= 4.5, `${cat} ${hex} contrast ${Math.max(black, white).toFixed(2)}`);
  }
});

T('textColorOn: light and dark extremes, shorthand, invalid', () => {
  assert.equal(D.textColorOn('#ffffff'), '#000');
  assert.equal(D.textColorOn('#000000'), '#fff');
  assert.equal(D.textColorOn('#fbbf24'), '#000', 'lighting amber');
  assert.equal(D.textColorOn('#9aa3b5'), '#000', 'fallback grey');
  assert.equal(D.textColorOn('#fff'), '#000');
  assert.equal(D.textColorOn('#123'), '#fff');
  assert.equal(D.textColorOn('nope'), '#fff');
  assert.equal(D.textColorOn(undefined), '#fff');
  assert.equal(D.luminance('#ffffff'), 1);
  assert.equal(D.luminance('x'), null);
  assert.equal(D.contrastRatio(1, 0), 21);
});

T('isHexColor', () => {
  assert.equal(D.isHexColor('#a1B2c3'), true);
  for (const b of ['#abc', 'abcdef', '#abcdeg', '', null]) assert.equal(D.isHexColor(b), false, String(b));
});

T('rack-display-core.js is pure (no DOM, storage, network or timers)', async () => {
  const { readFileSync } = await import('node:fs');
  const { JS } = await import('./fixtures/helpers.mjs');
  const src = readFileSync(JS + '/rack-display-core.js', 'utf8').replace(/\/\/.*$/gm, '');
  for (const word of ['window', 'document', 'fetch', 'localStorage', 'sessionStorage', 'setTimeout', 'setInterval']) {
    assert.ok(!new RegExp('\\b' + word + '\\b').test(src), word);
  }
});

// ------------------------------------------------------------------ loadTemplateInfo

function stubCtx(lib, extra) {
  const calls = [];
  const api = {
    library(params) {
      calls.push(params);
      const ids = String(params.ids || '').split(',').filter(Boolean);
      return Promise.resolve(lib(ids, params));
    },
  };
  return Object.assign({project: 'campus', api, calls, store: {doc: {templates: []}}}, extra || {});
}
const known = (ids) => ({templates: ids.filter((i) => !i.startsWith('missing')).map((i) => ({id: i, name: i.toUpperCase(), ru: 1}))});
const L = () => dom.mod;

TD('loadTemplateInfo: one request for the missing ids, then served from the cache', async () => {
  L().clearTemplateInfoCache();
  const ctx = stubCtx(known);
  const a = await L().loadTemplateInfo(ctx, ['t1', 't2', 't1', '', null]);
  assert.deepEqual(Object.keys(a).sort(), ['t1', 't2']);
  assert.equal(a.t1.name, 'T1');
  assert.deepEqual(ctx.calls, [{ids: 't1,t2', project: 'campus'}]);
  const b = await L().loadTemplateInfo(ctx, ['t2', 't3']);
  assert.deepEqual(Object.keys(b).sort(), ['t2', 't3']);
  assert.deepEqual(ctx.calls[1], {ids: 't3', project: 'campus'}, 'only the missing id');
  await L().loadTemplateInfo(ctx, ['t1', 't2', 't3']);
  assert.equal(ctx.calls.length, 2, 'all cached');
});

TD('loadTemplateInfo: unknown ids are cached as misses and left out', async () => {
  L().clearTemplateInfoCache();
  const ctx = stubCtx(known);
  const a = await L().loadTemplateInfo(ctx, ['t1', 'missing-1']);
  assert.deepEqual(Object.keys(a), ['t1']);
  const b = await L().loadTemplateInfo(ctx, ['missing-1']);
  assert.deepEqual(b, {});
  assert.equal(ctx.calls.length, 1, 'negative result cached');
  assert.equal(L().peekTemplateInfo(ctx, 'missing-1'), null);
  assert.equal(L().peekTemplateInfo(ctx, 't1').id, 't1');
  assert.equal(L().peekTemplateInfo(ctx, 'never'), undefined);
});

TD('loadTemplateInfo: chunks of at most 100 ids', async () => {
  L().clearTemplateInfoCache();
  const ctx = stubCtx(known);
  const ids = Array.from({length: 250}, (_, i) => 'tp-' + i);
  const out = await L().loadTemplateInfo(ctx, ids);
  assert.equal(Object.keys(out).length, 250);
  assert.deepEqual(ctx.calls.map((c) => c.ids.split(',').length), [100, 100, 50]);
  assert.deepEqual(ctx.calls.flatMap((c) => c.ids.split(',')), ids);
});

TD('loadTemplateInfo: the cache is per project', async () => {
  L().clearTemplateInfoCache();
  const ctx = stubCtx(known);
  await L().loadTemplateInfo(ctx, ['t1']);
  const other = stubCtx(known, {project: 'other'});
  await L().loadTemplateInfo(other, ['t1']);
  assert.deepEqual(other.calls, [{ids: 't1', project: 'other'}]);
});

TD('loadTemplateInfo: project templates come from the store without a request', async () => {
  L().clearTemplateInfoCache();
  const ctx = stubCtx(known, {store: {doc: {templates: [{id: 'p1', name: 'Local', ru: 2, source: 'project'}, {id: 't1', name: 'Shadow'}]}}});
  const out = await L().loadTemplateInfo(ctx, ['p1', 't1', 't2']);
  assert.equal(out.p1.name, 'Local');
  assert.equal(out.t1.name, 'Shadow', 'project tier wins');
  assert.equal(out.t2.name, 'T2');
  assert.deepEqual(ctx.calls, [{ids: 't2', project: 'campus'}]);
  const only = await L().loadTemplateInfo(ctx, ['p1']);
  assert.deepEqual(Object.keys(only), ['p1']);
  assert.equal(ctx.calls.length, 1);
});

TD('loadTemplateInfo: resolves {} without ctx.api, and without a ctx', async () => {
  L().clearTemplateInfoCache();
  assert.deepEqual(await L().loadTemplateInfo({project: 'campus', api: null}, ['t1']), {});
  assert.deepEqual(await L().loadTemplateInfo(null, ['t1']), {});
  assert.deepEqual(await L().loadTemplateInfo({project: 'campus', api: {}}, ['t1']), {});
  assert.deepEqual(await L().loadTemplateInfo(stubCtx(known), []), {});
  const harness = await L().loadTemplateInfo({api: null, store: {doc: {templates: [{id: 'p1', ru: 1}]}}}, ['p1', 't1']);
  assert.deepEqual(Object.keys(harness), ['p1'], 'harness still sees project templates');
});

TD('loadTemplateInfo: a failed request resolves without those ids and is retried later', async () => {
  L().clearTemplateInfoCache();
  let fail = true;
  const ctx = stubCtx((ids) => { if (fail) throw new Error('offline'); return known(ids); });
  assert.deepEqual(await L().loadTemplateInfo(ctx, ['t1']), {});
  fail = false;
  const out = await L().loadTemplateInfo(ctx, ['t1']);
  assert.equal(out.t1.id, 't1');
  assert.equal(ctx.calls.length, 2);
  const rejecting = {project: 'campus', api: {library() { return Promise.reject(new Error('500')); }}};
  assert.deepEqual(await L().loadTemplateInfo(rejecting, ['zz']), {});
  const throwing = {project: 'campus', api: {library() { throw new Error('sync'); }}};
  assert.deepEqual(await L().loadTemplateInfo(throwing, ['zz']), {});
  const odd = {project: 'campus', api: {library() { return Promise.resolve(null); }}};
  assert.deepEqual(await L().loadTemplateInfo(odd, ['yy']), {});
});

TD('loadTemplateInfo: concurrent calls share one in-flight request', async () => {
  L().clearTemplateInfoCache();
  let release;
  const gate = new Promise((r) => { release = r; });
  const ctx = stubCtx((ids) => gate.then(() => known(ids)));
  const p1 = L().loadTemplateInfo(ctx, ['t1', 't2']);
  const p2 = L().loadTemplateInfo(ctx, ['t2', 't3']);
  assert.equal(L().peekTemplateInfo(ctx, 't2'), undefined, 'pending is not settled');
  release();
  const [a, b] = await Promise.all([p1, p2]);
  assert.deepEqual(Object.keys(a).sort(), ['t1', 't2']);
  assert.deepEqual(Object.keys(b).sort(), ['t2', 't3']);
  assert.deepEqual(ctx.calls.map((c) => c.ids), ['t1,t2', 't3']);
});

TD('loadTemplateInfo: accepts a bare array response', async () => {
  L().clearTemplateInfoCache();
  const ctx = stubCtx((ids) => ids.map((i) => ({id: i})));
  assert.deepEqual(Object.keys(await L().loadTemplateInfo(ctx, ['a1', 'b1'])), ['a1', 'b1']);
});

TD('rack-display.js loads in Node without touching document or window', () => {
  assert.equal(typeof globalThis.document, 'undefined');
  assert.equal(typeof globalThis.window, 'undefined');
  assert.equal(typeof L().loadTemplateInfo, 'function');
});
