// XPT: js/rack-export-core.js (rack export SVG, filenames, remembered choices).
// The items / shelf / rows cases use rack-core's own itemBlocks,
// shelfChildBlocks and racksByRow when it exports them, else stand-ins passed
// through opts.core with the contract shapes (docs/notes/rackula.md D, RJS).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadFixtureDoc, loadVocab, clone } from './fixtures/helpers.mjs';

const { mod: X, error } = await loadModule('js/rack-export-core.js', 'XPT');
const { mod: RC } = await loadModule('js/rack-core.js', 'W4');
if (error) throw error;

const vocab = loadVocab();

// Minimal XML well-formedness: one root, balanced and properly nested tags,
// quoted unique attributes, no raw '<' or stray '&' in text.
function wellFormed(xml) {
  let s = xml.replace(/^<\?xml[^?]*\?>\s*/, '');
  const stack = [];
  let roots = 0;
  let i = 0;
  while (i < s.length) {
    const lt = s.indexOf('<', i);
    const chunk = lt < 0 ? s.slice(i) : s.slice(i, lt);
    if (/&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)/.test(chunk)) throw new Error('stray & in text near ' + JSON.stringify(chunk.slice(0, 40)));
    if (!stack.length && chunk.trim()) throw new Error('text outside the root');
    if (lt < 0) break;
    const gt = s.indexOf('>', lt);
    if (gt < 0) throw new Error('unterminated tag');
    const tag = s.slice(lt + 1, gt);
    if (tag[0] === '/') {
      const name = tag.slice(1).trim();
      const open = stack.pop();
      if (open !== name) throw new Error('</' + name + '> closes <' + open + '>');
    } else {
      const self = tag.endsWith('/');
      const body = self ? tag.slice(0, -1) : tag;
      const m = /^([A-Za-z_][\w:.-]*)([\s\S]*)$/.exec(body);
      if (!m) throw new Error('bad tag <' + tag.slice(0, 30) + '>');
      const rest = m[2].replace(/\s+([A-Za-z_][\w:.-]*)="([^"<]*)"/g, (all, k, v) => {
        if (/&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)/.test(v)) throw new Error('stray & in attribute ' + k);
        return ' ' + k + '=';
      });
      const keys = (m[2].match(/\s([A-Za-z_][\w:.-]*)="/g) || []).map((k) => k.trim());
      if (new Set(keys).size !== keys.length) throw new Error('duplicate attribute in <' + m[1] + '>');
      if (rest.replace(/\s+[A-Za-z_][\w:.-]*=/g, '').trim()) throw new Error('bad attributes in <' + m[1] + '>: ' + rest.slice(0, 40));
      if (!stack.length) roots++;
      if (!self) stack.push(m[1]);
    }
    i = gt + 1;
  }
  if (stack.length) throw new Error('unclosed <' + stack.join('> <') + '>');
  if (roots !== 1) throw new Error(roots + ' root elements');
  return true;
}

function count(svg, re) {
  return (svg.match(re) || []).length;
}

function doc2() {
  return {
    meta: {title: 'Grace & Truth'},
    racks: [
      {id: 'rk-a', name: 'Audio rack', units: 12, order: 1},
      {id: 'rk-b', name: 'Video <rack>', units: 8, order: 2, width_in: 10},
    ],
    devices: [
      {id: 'mix', name: 'Mixer "A" & <B>', kind: 'console', manufacturer: 'Allen & Heath', model: 'SQ-5', rack: {id: 'rk-a', u: 10, height: 2, face: 'front'}},
      {id: 'amp', name: 'Amp', kind: 'amp', rack: {id: 'rk-a', u: 1, height: 2, face: 'rear', depth: 'half'}},
      {id: 'sw', name: 'Switch', kind: 'switch', rack: {id: 'rk-b', u: 8, height: 1, face: 'front', side: 'left'}},
      {id: 'loose', name: 'Loose', kind: 'mic'},
    ],
  };
}

// Stand-ins matching the contract shapes, used only when rack-core lacks them.
const ITEM_TYPES = [
  {type: 'blank', label: 'Blank panel', height: 1, face: 'front', depth: 'half', color: '#44475a'},
  {type: 'vent', label: 'Vent panel', height: 1, face: 'front', depth: 'half', color: '#44475a'},
  {type: 'shelf', label: 'Shelf', height: 1, face: 'front', depth: 'full', color: '#6272a4', slots: 2},
  {type: 'drawer', label: 'Drawer', height: 2, face: 'front', depth: 'full', color: '#6272a4'},
];
function fakeItemBlocks(doc, rackId, face) {
  const rack = doc.racks.find((r) => r.id === rackId);
  return (rack.items || []).filter((it) => it.face === face || (it.depth || 'full') === 'full').map((it) => {
    const h = it.height || 1;
    return {id: 'item:' + it.id, item: it.id, type: it.type, u: it.u, height: h, face: it.face || 'front', depth: it.depth || 'full',
      label: it.label || '', color: it.color || '', slots: it.slots || 2, x: 0, y: (rack.units - (it.u + h - 1)) * 22, w: 320, h: h * 22, behind: (it.face || 'front') !== face};
  });
}
function fakeShelfChildBlocks(doc, rackId, face) {
  const rack = doc.racks.find((r) => r.id === rackId);
  const out = [];
  (rack.items || []).filter((it) => it.type === 'shelf' && (it.face === face || it.depth === 'full')).forEach((it) => {
    doc.devices.filter((d) => d.rack && d.rack.id === rackId && d.rack.shelf === it.id).forEach((d) => {
      const slots = it.slots || 2;
      out.push({device: d.id, item: it.id, slot: d.rack.slot, x: d.rack.slot * 320 / slots, y: (rack.units - it.u) * 22, w: 320 / slots, h: 22});
    });
  });
  return out;
}
function fakeFaceBlocks(doc, rackId, face) {
  return RC.faceBlocks(doc, rackId, face).filter((b) => !(doc.devices.find((d) => d.id === b.device).rack.shelf));
}
const fakeCore = {};
if (typeof RC.itemBlocks !== 'function') Object.assign(fakeCore, {itemBlocks: fakeItemBlocks, faceBlocks: fakeFaceBlocks, ITEM_TYPES});
if (typeof RC.shelfChildBlocks !== 'function') fakeCore.shelfChildBlocks = fakeShelfChildBlocks;

function itemsDoc() {
  const d = doc2();
  d.racks[0].items = [
    {id: 'ri-1', type: 'shelf', u: 5, face: 'front', depth: 'full', slots: 2},
    {id: 'ri-2', type: 'blank', u: 3, face: 'front', depth: 'half', label: 'Blank & <spare>'},
    {id: 'ri-3', type: 'drawer', u: 6, height: 2, face: 'front', depth: 'full'},
  ];
  d.devices.push({id: 'mini', name: 'Mac mini', kind: 'computer', rack: {id: 'rk-a', u: 5, height: 1, face: 'front', side: 'full', shelf: 'ri-1', slot: 1}});
  d.devices.push({id: 'hub', name: 'USB hub', kind: 'other', rack: {id: 'rk-a', u: 5, height: 1, face: 'front', side: 'full', shelf: 'ri-1', slot: 0}});
  return d;
}

// ------------------------------------------------------------ well-formedness and escaping

test('buildRackSvg is a well-formed standalone SVG with xmlns, width, height and viewBox', () => {
  const svg = X.buildRackSvg(doc2(), ['rk-a', 'rk-b'], {face: 'front', vocab, title: 'Grace & Truth', date: '2026-10-28'});
  assert.ok(wellFormed(svg));
  assert.match(svg, /^<\?xml version="1.0" encoding="UTF-8"\?>\n<svg xmlns="http:\/\/www.w3.org\/2000\/svg"/);
  const size = X.svgSize(svg);
  assert.ok(size.width >= X.GEOM.minW && size.height > 200, JSON.stringify(size));
  assert.match(svg, new RegExp('viewBox="0 0 ' + size.width + ' ' + size.height + '"'));
});

test('the checker itself rejects broken XML', () => {
  assert.throws(() => wellFormed('<svg><g></svg>'));
  assert.throws(() => wellFormed('<svg><text>a < b</text></svg>'));
  assert.throws(() => wellFormed('<svg><text>a & b</text></svg>'));
  assert.throws(() => wellFormed('<svg a="1" a="2"/>'));
  assert.throws(() => wellFormed('<svg/><svg/>'));
});

test('names, models, rack names and the title are escaped (< & " >)', () => {
  const svg = X.buildRackSvg(doc2(), ['rk-a', 'rk-b'], {face: 'both', annotate: 'model', vocab, title: 'Grace & "Truth" <x>', date: 'd'});
  assert.ok(wellFormed(svg));
  assert.ok(svg.indexOf('Mixer &quot;A&quot; &amp; &lt;B&gt;') > 0, 'device name escaped');
  assert.ok(svg.indexOf('Allen &amp; Heath SQ-5') > 0, 'model escaped');
  assert.ok(svg.indexOf('Video &lt;rack&gt;') > 0, 'rack name escaped');
  assert.ok(svg.indexOf('Grace &amp; &quot;Truth&quot; &lt;x&gt;') > 0, 'title escaped');
  assert.equal(svg.indexOf('<B>'), -1);
  assert.equal(svg.indexOf('<rack>'), -1);
});

test('control characters XML cannot carry are dropped', () => {
  const d = doc2();
  d.devices[0].name = 'Bell\u0007 mixer\u0000';
  const svg = X.buildRackSvg(d, ['rk-a'], {vocab});
  assert.ok(wellFormed(svg));
  assert.ok(svg.indexOf('Bell mixer') > 0);
  assert.equal(/[\u0000-\u0008]/.test(svg), false);
  assert.equal(X.xmlEsc('a\'b'), 'a&#39;b');
});

// ------------------------------------------------------------ faces and layout

test('face both draws front and rear for every rack, left to right', () => {
  const svg = X.buildRackSvg(doc2(), ['rk-a', 'rk-b'], {face: 'both', vocab});
  assert.equal(count(svg, /<g class="rx-face" data-face="front">/g), 2);
  assert.equal(count(svg, /<g class="rx-face" data-face="rear">/g), 2);
  assert.equal(count(svg, /<g class="rx-rack" data-rack="/g), 2);
  assert.ok(svg.indexOf('data-rack="rk-a"') < svg.indexOf('data-rack="rk-b"'));
  const one = X.svgSize(X.buildRackSvg(doc2(), ['rk-a'], {face: 'front', vocab}));
  const both = X.svgSize(X.buildRackSvg(doc2(), ['rk-a'], {face: 'both', vocab}));
  assert.ok(both.width > one.width + 300, 'two faces side by side');
});

test('single faces: the rear-mounted half-depth amp shows only on the rear; full depth shows behind', () => {
  const front = X.buildRackSvg(doc2(), ['rk-a'], {face: 'front', vocab});
  const rear = X.buildRackSvg(doc2(), ['rk-a'], {face: 'rear', vocab});
  assert.equal(count(front, /data-face="rear"/g), 0);
  assert.ok(front.indexOf('data-device="amp"') < 0);
  assert.ok(rear.indexOf('data-device="amp"') > 0);
  assert.match(rear, /data-device="mix" data-behind="1"/, 'the full-depth mixer is seen from behind on the rear');
  assert.match(front, /data-device="mix">/);
});

test('U labels follow ruLabel (top_down numbering) and the rack width', () => {
  const d = doc2();
  d.racks[0].numbering = 'top_down';
  const svg = X.buildRackSvg(d, ['rk-a'], {face: 'front', vocab});
  const labels = [];
  svg.replace(/<text[^>]*class="rx-ru"[^>]*>(-?\d+)<\/text>/g, (a, x) => { labels.push(x); return a; });
  assert.equal(labels.length, 12);
  assert.deepEqual(labels.slice(0, 3), [1, 2, 3].map((u) => RC.ruLabel(d.racks[0], u)), 'u 1..3 from the bottom');
  assert.deepEqual(labels.slice(0, 3), ['12', '11', '10']);
  const narrow = X.svgSize(X.buildRackSvg(doc2(), ['rk-b'], {face: 'front', vocab}));
  const wide = X.svgSize(X.buildRackSvg(doc2(), ['rk-a'], {face: 'front', vocab}));
  assert.ok(narrow.width <= wide.width);
});

test('unknown rack ids are skipped; none left still gives a valid SVG', () => {
  const svg = X.buildRackSvg(doc2(), ['nope'], {vocab});
  assert.ok(wellFormed(svg));
  assert.match(svg, /No racks selected/);
});

test('rows: racks sharing a row are grouped with a caption (racksByRow)', () => {
  const d = doc2();
  d.racks[0].row = 'A';
  d.racks[1].row = 'A';
  d.racks.push({id: 'rk-c', name: 'Lighting', units: 6, order: 0});
  const core = typeof RC.racksByRow === 'function' ? {} : {racksByRow: function (racks) {
    const sorted = racks.slice().sort((a, b) => (a.order === undefined ? 1e9 : a.order) - (b.order === undefined ? 1e9 : b.order));
    const out = [];
    sorted.forEach((r) => {
      const g = r.row ? out.find((x) => x.row === r.row) : null;
      if (g) g.racks.push(r); else out.push({row: r.row || '', racks: [r]});
    });
    return out;
  }};
  const svg = X.buildRackSvg(d, ['rk-a', 'rk-b', 'rk-c'], {vocab, core});
  assert.ok(wellFormed(svg));
  assert.equal(count(svg, /<g class="rx-row" data-row="A">/g), 1);
  assert.ok(svg.indexOf('data-rack="rk-c"') < svg.indexOf('data-rack="rk-a"'), 'ordered by racksByRow');
});

// ------------------------------------------------------------ legend, annotations, colours

test('legend lists the disciplines used and can be turned off', () => {
  const on = X.buildRackSvg(doc2(), ['rk-a', 'rk-b'], {face: 'both', vocab});
  assert.match(on, /<g class="rx-legend">/);
  const keys = X.legendEntries(doc2(), ['rk-a', 'rk-b'], {face: 'both', vocab}).map((e) => e.key);
  assert.deepEqual(keys.slice().sort(), ['disc:audio', 'disc:network']);
  assert.match(on, /data-key="disc:audio"/);
  const off = X.buildRackSvg(doc2(), ['rk-a', 'rk-b'], {face: 'both', vocab, legend: false});
  assert.equal(off.indexOf('rx-legend'), -1);
  assert.ok(X.svgSize(off).height < X.svgSize(on).height);
});

test('block colour: opts.blockColor wins and its categories enter the legend; rack.color stays out', () => {
  const d = doc2();
  d.devices[2].template = 'netgear-gs108';
  d.devices[1].rack.color = '#123456';
  const info = {'netgear-gs108': {rack_category: 'network'}};
  const blockColor = (dev, vc, inf) => (dev.rack.color ? dev.rack.color : inf && inf.rack_category === 'network' ? '#7968A6' : vc.disciplines[vc.kinds[dev.kind].discipline].color);
  const svg = X.buildRackSvg(d, ['rk-a', 'rk-b'], {face: 'both', vocab, info, blockColor});
  assert.ok(svg.indexOf('fill="#7968A6"') > 0);
  assert.ok(svg.indexOf('fill="#123456"') > 0);
  const keys = X.legendEntries(d, ['rk-a', 'rk-b'], {face: 'both', vocab, info, blockColor}).map((e) => e.key);
  assert.deepEqual(keys, ['cat:network', 'disc:audio']);
  const fallback = X.buildRackSvg(d, ['rk-b'], {face: 'front', vocab, info});
  assert.ok(fallback.indexOf('fill="' + vocab.disciplines.network.color + '"') > 0, 'discipline colour without blockColor');
});

test('annotation column: off by default, names via the fallback, values via opts.annotationValue', () => {
  const plain = X.buildRackSvg(doc2(), ['rk-a'], {face: 'front', vocab});
  assert.equal(plain.indexOf('rx-annotations'), -1);
  const named = X.buildRackSvg(doc2(), ['rk-a'], {face: 'front', vocab, annotate: 'name'});
  assert.match(named, /<g class="rx-annotations" data-field="name">/);
  assert.ok(/class="rx-ann"[^>]*>Mixer &quot;A&quot;/.test(named));
  assert.ok(X.svgSize(named).width > X.svgSize(plain).width);
  const custom = X.buildRackSvg(doc2(), ['rk-a'], {face: 'front', vocab, annotate: 'ip', annotationValue: (doc, dev, field) => (field === 'ip' ? '10.0.0.' + dev.id.length : ''),
    fields: [{key: '', label: 'None'}, {key: 'ip', label: 'IP address'}]});
  assert.match(custom, /class="rx-ann"[^>]*>10\.0\.0\.3</);
  assert.match(custom, />IP address</);
  assert.equal(X.buildRackSvg(doc2(), ['rk-a'], {annotate: 'serial', vocab}).indexOf('class="rx-ann"'), -1, 'unknown fields give empty values');
});

// ------------------------------------------------------------ items and shelves

test('items are drawn by type, with escaped labels, when rack-core provides itemBlocks', () => {
  const d = itemsDoc();
  const svg = X.buildRackSvg(d, ['rk-a'], {face: 'front', vocab, core: fakeCore});
  assert.ok(wellFormed(svg));
  assert.match(svg, /<g class="rx-item" data-item="ri-1" data-type="shelf">/);
  assert.match(svg, /<g class="rx-item" data-item="ri-2" data-type="blank">/);
  assert.match(svg, /<g class="rx-item" data-item="ri-3" data-type="drawer">/);
  assert.ok(svg.indexOf('Blank &amp; &lt;spare&gt;') > 0);
  const keys = X.legendEntries(d, ['rk-a'], {face: 'front', vocab, core: fakeCore}).map((e) => e.key);
  assert.ok(keys.indexOf('item:shelf') >= 0 && keys.indexOf('item:blank') >= 0);
  const rear = X.buildRackSvg(d, ['rk-a'], {face: 'rear', vocab, core: fakeCore});
  assert.equal(rear.indexOf('data-item="ri-2"'), -1, 'the half-depth front blank is not on the rear');
  assert.ok(rear.indexOf('data-item="ri-1"') > 0, 'the full-depth shelf is');
});

test('shelf children are drawn inside their cells, once, and annotated on one line', () => {
  const d = itemsDoc();
  const svg = X.buildRackSvg(d, ['rk-a'], {face: 'front', vocab, core: fakeCore, annotate: 'name'});
  assert.ok(wellFormed(svg));
  assert.equal(count(svg, /data-device="mini"/g), 1);
  assert.equal(count(svg, /data-device="hub"/g), 1);
  const x = (id) => Number(new RegExp('data-device="' + id + '"[^]*?<rect x="([\\d.]+)"').exec(svg)[1]);
  assert.ok(x('mini') > x('hub') + 100, 'slot 1 is right of slot 0');
  assert.match(svg, /class="rx-ann"[^>]*>(USB hub, Mac mini|Mac mini, USB hub)</);
});

test('without itemBlocks in the core nothing item-shaped is drawn', () => {
  const core = {itemBlocks: null, shelfChildBlocks: null};
  const svg = X.buildRackSvg(itemsDoc(), ['rk-a'], {face: 'front', vocab, core});
  assert.ok(wellFormed(svg));
  assert.equal(svg.indexOf('rx-item'), -1);
});

// ------------------------------------------------------------ images

test('images: per-face data URLs on matching blocks; a bare string is front only with both faces', () => {
  const png = 'data:image/png;base64,iVBORw0KGgo=';
  const svg = X.buildRackSvg(doc2(), ['rk-a'], {face: 'both', vocab, images: {mix: {front: png, rear: png + 'R'}, amp: png}});
  assert.ok(wellFormed(svg));
  assert.equal(count(svg, /<image /g), 2, 'mixer front + mixer rear (behind); amp string is front-only');
  assert.match(svg, /href="data:image\/png;base64,iVBORw0KGgo="/);
  assert.match(svg, /xlink:href="data:image\/png;base64,iVBORw0KGgo=R"/);
  const rearOnly = X.buildRackSvg(doc2(), ['rk-a'], {face: 'rear', vocab, images: {amp: png}});
  assert.equal(count(rearOnly, /<image /g), 1, 'a string applies to the single exported face');
});

test('imageRequests: attachments first, template paths per face, never the front on the rear', () => {
  const d = doc2();
  d.devices[0].template = 't-mix';
  d.devices[1].template = 't-amp';
  d.devices[1].rack.image_rear = 'att-0123456789ab';
  const info = {'t-mix': {image_front: 'yamaha/mix.front.webp'}, 't-amp': {image_front: 'x/amp.front.webp', image_rear: 'x/amp.rear.webp'}};
  assert.deepEqual(X.imageRequests(d, ['rk-a'], 'both', info), [
    {device: 'mix', face: 'front', path: 'yamaha/mix.front.webp'},
    {device: 'amp', face: 'front', path: 'x/amp.front.webp'},
    {device: 'amp', face: 'rear', att: 'att-0123456789ab'},
  ]);
  assert.deepEqual(X.imageRequests(d, ['rk-a'], 'rear', info), [{device: 'amp', face: 'rear', att: 'att-0123456789ab'}]);
  assert.deepEqual(X.imageRequests(d, ['rk-a'], 'front', {'t-mix': {image_front: 'https://evil.example/x.png'}}), []);
  assert.deepEqual(X.imageRequests(d, ['rk-a'], 'front', {'t-mix': {image_front: 'a/../../api/x.png'}}), []);
  assert.deepEqual(X.templateIds(d, ['rk-a', 'rk-b']), ['t-mix', 't-amp']);
});

// ------------------------------------------------------------ choices, filenames, sizes

test('readPrefs tolerates junk and keeps valid choices', () => {
  assert.deepEqual(X.readPrefs(null), X.DEFAULT_PREFS);
  assert.deepEqual(X.readPrefs('{oops'), X.DEFAULT_PREFS);
  assert.deepEqual(X.readPrefs('[1]'), X.DEFAULT_PREFS);
  assert.deepEqual(X.readPrefs(JSON.stringify({v: 1, face: 'both', format: 'png', legend: false, annotate: 'asset_tag'})),
    {v: 1, face: 'both', format: 'png', legend: false, annotate: 'asset_tag'});
  assert.deepEqual(X.readPrefs({face: 'side', format: 'gif', legend: 'yes', annotate: '<x>'}), X.DEFAULT_PREFS);
  assert.equal(X.STORAGE_KEY, 'fathom.ui.rack.export');
});

test('exportFilename: <project>-<rack|racks>-<face>.<ext>, sanitised', () => {
  assert.equal(X.exportFilename('sunday-demo', ['rk-foh'], 'front', 'svg'), 'sunday-demo-rk-foh-front.svg');
  assert.equal(X.exportFilename('sunday-demo', ['rk-a', 'rk-b'], 'both', 'png'), 'sunday-demo-racks-both.png');
  assert.equal(X.exportFilename('My Church/../x', ['rk a'], 'weird', 'pdf'), 'My-Church-x-rk-a-front.pdf');
  assert.equal(X.exportFilename('', [], 'rear'), 'fathom-racks-rear.svg');
});

test('normalizeFields accepts {key, label} and bare keys with None first', () => {
  assert.deepEqual(X.normalizeFields([{key: 'name', label: 'Name'}, 'asset_tag', {key: '', label: 'None'}]),
    [{key: '', label: 'None'}, {key: 'name', label: 'Name'}, {key: 'asset_tag', label: 'Asset tag'}]);
  assert.deepEqual(X.normalizeFields(null), X.BASIC_FIELDS);
});

test('pngScale keeps 2x unless the canvas would be too large; svgSize reads the root size', () => {
  assert.equal(X.pngScale(1200, 800, 2), 2);
  const s = X.pngScale(9000, 3000, 2);
  assert.ok(s < 2 && 9000 * s * 3000 * s <= 16777216, String(s));
  assert.deepEqual(X.svgSize('<svg xmlns="x" width="10" height="20.5">'), {width: 10, height: 20.5});
  assert.deepEqual(X.svgSize('nope'), {width: 0, height: 0});
});

test('helpers: textColorOn, fitText, facesOf', () => {
  assert.equal(X.textColorOn('#ffffff'), '#000');
  assert.equal(X.textColorOn('#44475a'), '#fff');
  assert.equal(X.fitText('abcdefghijklmnop', 40, 10), 'abcde\u2026');
  assert.equal(X.fitText('abc', 400, 10), 'abc');
  assert.deepEqual(X.facesOf('both'), ['front', 'rear']);
  assert.deepEqual(X.facesOf('x'), ['front']);
});

test('the fixture rack exports cleanly at every face', () => {
  const fx = clone(loadFixtureDoc());
  ['front', 'rear', 'both'].forEach((face) => {
    const svg = X.buildRackSvg(fx, fx.racks.map((r) => r.id), {face, vocab, annotate: 'model', title: 'Sunday', date: '2026-10-28'});
    assert.ok(wellFormed(svg), face);
    assert.match(svg, /Sunday · 2026-10-28/);
  });
});
