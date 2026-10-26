// Harness for js/explorer.js (docs/ui-audit.md B.2 EXPLORER, D10): mounts a
// device explorer on fixture-v2.json. Items link to #device=<id>; the hash
// drives setSelected, so the default onSelect path is exercised.
// ?smoke=1 writes data-smoke; ?many=N adds N synthetic items; ?empty=1 mounts
// no items; ?key=<k> picks the storage key (default harness-devices).
import { mountExplorer } from '../js/explorer.js';
import { h } from '../js/dom.js';

window.__fathomErrors = window.__fathomErrors || [];
const errors = window.__fathomErrors;
window.addEventListener('error', function (e) { errors.push(String((e && e.message) || e)); });
window.addEventListener('unhandledrejection', function (e) { errors.push('unhandled: ' + String(e && e.reason && (e.reason.stack || e.reason))); });

const params = new URLSearchParams(location.search);
const KIND_DISC = { mic: 'audio', wireless_rx: 'audio', stage_io: 'audio', console: 'audio', speaker: 'audio',
  video_switcher: 'video', converter: 'video', display: 'video', stream: 'network' };
const DISC = [
  { key: 'audio', label: 'Audio', glyph: 'A' }, { key: 'video', label: 'Video', glyph: 'V' },
  { key: 'lighting', label: 'Lighting', glyph: 'L' }, { key: 'network', label: 'Network', glyph: 'N' },
  { key: 'other', label: 'Other', glyph: 'X' },
];
const TABS = [
  { key: 'overview', label: 'Overview', glyph: '\u25A4' }, { key: 'ports', label: 'Ports', glyph: '\u25CE' },
  { key: 'cables', label: 'Cables', glyph: '\u2194' }, { key: 'network', label: 'Network', glyph: '\u26AD' },
];

const logEl = h('ul', { id: 'ex-harness-log' });
function log(msg) {
  logEl.insertBefore(h('li', { text: msg }), logEl.firstChild);
  while (logEl.childNodes.length > 30) logEl.removeChild(logEl.lastChild);
}

function discLabel(k) {
  const d = DISC.filter(function (x) { return x.key === k; })[0];
  return d ? d.label : 'Other';
}

function toItems(doc, vocab) {
  const kinds = (vocab && vocab.kinds) || {};
  const rooms = {};
  (doc.rooms || []).forEach(function (r) { rooms[r.id] = r.name; });
  return (doc.devices || []).map(function (d) {
    const disc = (kinds[d.kind] && kinds[d.kind].discipline) || KIND_DISC[d.kind] || 'other';
    const model = [d.manufacturer, d.model].filter(Boolean).join(' ');
    return {
      id: d.id, label: d.name || d.id, sub: model || d.kind, disc: disc, group: discLabel(disc),
      glyph: (DISC.filter(function (x) { return x.key === disc; })[0] || DISC[4]).glyph,
      badge: (d.ports || []).length || null, href: '#device=' + encodeURIComponent(d.id), room: rooms[d.room] || '',
    };
  });
}

function synthetic(n) {
  const out = [];
  for (let i = 1; i <= n; i++) {
    const disc = DISC[i % 4].key;
    out.push({ id: 'syn-' + i, label: 'Synthetic ' + i, sub: 'Model ' + (100 + i), disc: disc, group: discLabel(disc),
      glyph: DISC[i % 4].glyph, href: '#device=syn-' + i });
  }
  return out;
}

function selectedFromHash() {
  const m = /^#device=(.*)$/.exec(location.hash);
  return m ? decodeURIComponent(m[1]) : null;
}

function getJson(url) {
  return fetch(url, { credentials: 'same-origin' }).then(function (r) {
    if (!r.ok) throw new Error(url + ': HTTP ' + r.status);
    return r.json();
  });
}

function main() {
  const vocabP = getJson('../../api/v2/meta').then(function (m) { return m.vocab || null; }).catch(function () { return null; });
  return Promise.all([getJson('fixture-v2.json'), vocabP]).then(function (r) {
    const doc = r[0];
    const room = ((doc.rooms || [])[0] || {}).name || '';
    let items = params.get('empty') === '1' ? [] : toItems(doc, r[1]);
    const many = Number(params.get('many')) || 0;
    if (many > 0) items = items.concat(synthetic(Math.min(many, 2000)));
    const host = document.getElementById('ex-host');
    const selected = selectedFromHash();
    const ex = mountExplorer(host, {
      key: params.get('key') || 'harness-devices',
      title: 'Devices', glyph: '\u25EB',
      items: items,
      chips: DISC.slice(0, 4).map(function (c) {
        return { key: c.key, label: c.label, test: function (it) { return it.disc === c.key; } };
      }),
      toolbar: [{ key: 'nodes', label: 'Nodes', title: 'Toggle nodes (harness)', pressed: false,
        run: function (e, b) { b.setAttribute('aria-pressed', String(b.getAttribute('aria-pressed') !== 'true')); log('toolbar: nodes'); } }],
      footer: function (shown, total) {
        return (shown === total ? total + ' devices' : shown + ' of ' + total + ' devices') + (room ? ' \u00B7 ' + room : '');
      },
      rail: TABS.map(function (t, i) { return { key: t.key, label: t.label, glyph: t.glyph, href: '#tab=' + t.key, active: i === 0 }; }),
      selected: selected,
      mobileLabel: 'Devices',
    });
    const pageBox = h('div', { class: 'h-page' });
    ex.content.appendChild(pageBox);
    function renderPage() {
      const id = selectedFromHash();
      const it = items.filter(function (x) { return x.id === id; })[0];
      pageBox.textContent = '';
      pageBox.appendChild(h('h1', { id: 'ex-harness-title', text: it ? it.label : 'No device selected' }));
      pageBox.appendChild(h('p', { class: 'muted', text: it ? it.sub : 'Pick a device in the explorer.' }));
      if (it) {
        pageBox.appendChild(h('dl', null, [
          h('dt', { text: 'Id' }), h('dd', { class: 'mono', text: it.id }),
          h('dt', { text: 'Discipline' }), h('dd', { text: discLabel(it.disc) }),
          h('dt', { text: 'Ports' }), h('dd', { text: String(it.badge || 0) }),
          h('dt', { text: 'Room' }), h('dd', { text: it.room || '\u2014' }),
        ]));
      }
      pageBox.appendChild(logEl);
    }
    window.addEventListener('hashchange', function () {
      const id = selectedFromHash();
      log('hashchange: ' + location.hash);
      ex.setSelected(id);
      renderPage();
    });
    renderPage();
    window.__ex = { handle: ex, items: items, log: log };
    if (params.has('smoke')) {
      setTimeout(function () {
        document.documentElement.setAttribute('data-smoke', JSON.stringify({ ready: true, errors: errors, stats: { items: items.length } }));
      }, 300);
    }
  });
}

main().catch(function (err) {
  errors.push('harness: ' + String(err && (err.stack || err.message) || err));
  if (params.has('smoke')) document.documentElement.setAttribute('data-smoke', JSON.stringify({ ready: false, errors: errors, stats: null }));
});
