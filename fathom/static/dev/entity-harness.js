// Harness for dev/entity.html: mounts entity-header.js with entity-core.js facts,
// tabs and summary cards on fixture-v2.json. Hash: #/<device|room|rack>/<id>[/<tab>]
// (tabs are real links; an unknown tab is replaced with overview, an unknown id
// shows the D5 inline error). ?smoke=1 writes data-smoke; ?rows=N sets the filler
// length of non-overview tabs (default 80). window.__eh exposes the handle and log.
import { h } from '../js/dom.js';
import { mountEntityHeader } from '../js/entity-header.js';
import { deviceFacts, roomFacts, rackFacts, deviceTabs, roomTabs, rackTabs, resolveTab, summaryCards, statusPill, tabLabel } from '../js/entity-core.js';
import { deviceTitle } from '../js/model-core.js';

window.__fathomErrors = window.__fathomErrors || [];
(function () {
  const errs = window.__fathomErrors;
  window.addEventListener('error', function (e) { errs.push(String((e && e.message) || e)); });
  window.addEventListener('unhandledrejection', function (e) { errs.push('unhandled: ' + String(e && e.reason && (e.reason.stack || e.reason.message) || e.reason)); });
})();

const params = new URLSearchParams(location.search);
const ROWS = Math.max(0, parseInt(params.get('rows') || '80', 10) || 0);
const GLYPH = { device: '\u25CF', room: '\u25A3', rack: '\u25A4' };
const KIND = { device: 'Device', room: 'Room', rack: 'Rack' };
const COLL = { device: 'devices', room: 'rooms', rack: 'racks' };
const VIEW = { devices: 'device', rooms: 'room', racks: 'rack' };

const S = { doc: null, vocab: null, ctxInfo: null, handle: null, kind: '', id: '', tab: '' };
const log = [];
window.__eh = { log: log, handle: null, state: S };

function note(text) {
  log.push(text);
  const ul = document.getElementById('h-log');
  ul.insertBefore(h('li', null, text), ul.firstChild);
}

function parse() {
  const parts = location.hash.replace(/^#\/?/, '').split('?')[0].split('/').map(decodeURIComponent);
  return { kind: parts[0] || '', id: parts[1] || '', tab: parts[2] || '' };
}

function href(kind, id, tab) {
  return '#/' + kind + '/' + encodeURIComponent(id) + (tab ? '/' + tab : '');
}

function link(view, id) {
  return VIEW[view] ? href(VIEW[view], id) : undefined;
}

function find(kind, id) {
  return (S.doc[COLL[kind]] || []).filter(function (e) { return e.id === id; })[0] || null;
}

function act(key) {
  return function () { note('action:' + key); };
}

function optionsFor(kind, e, tab) {
  const cards = summaryCards(kind, S.doc, e, S.ctxInfo);
  const counts = {};
  cards.forEach(function (c) { if (c.tab && c.drill && counts[c.tab] === undefined) counts[c.tab] = c.count; });
  const keys = kind === 'device' ? deviceTabs(S.doc, e) : kind === 'room' ? roomTabs() : rackTabs();
  const o = {
    kind: kind, id: e.id, glyph: GLYPH[kind], title: kind === 'device' ? deviceTitle(e) : (e.name || e.id), activeTab: tab,
    tabs: keys.map(function (k) { return { key: k, label: tabLabel(k), count: counts[k] === undefined ? null : counts[k], href: href(kind, e.id, k) }; }),
    onTab: function (key) { note('tab:' + key); },
  };
  if (kind === 'device') {
    const problems = cards.filter(function (c) { return c.key === 'problems'; })[0];
    o.subtitle = [e.manufacturer, e.model].filter(Boolean).join(' ');
    o.status = statusPill(e.status);
    o.facts = deviceFacts(S.doc, S.vocab, e, null, { href: link });
    o.badges = problems && problems.count ? [{ label: problems.count + ' open', level: 'err', title: 'Open problem reports', onClick: act('badge:problems') }] : [];
    o.actions = [{ key: 'edit', label: 'Edit', primary: true, run: act('edit') }, { key: 'patch', label: 'Show in patch', run: act('patch') },
      { key: 'trace', label: 'Trace', run: act('trace') }, { key: 'public', label: 'Public page', href: '../../p/sunday-demo/d/' + encodeURIComponent(e.id), target: '_blank' }];
    o.overflow = [{ key: 'duplicate', label: 'Duplicate', run: act('duplicate') }, { key: 'merge', label: 'Merge into\u2026', run: act('merge') },
      { key: 'qr', label: 'QR code', run: act('qr') }, { key: 'delete', label: 'Delete device', danger: true, run: act('delete') }];
  } else if (kind === 'room') {
    o.subtitle = e.kind ? e.kind.charAt(0).toUpperCase() + e.kind.slice(1) : '';
    o.facts = roomFacts(S.doc, e, { href: link });
    o.thumb = { src: 'plans/main-floor.svg', alt: 'Floor plan of ' + (e.name || e.id), href: '#/room/' + encodeURIComponent(e.id) + '/plans' };
    o.actions = [{ key: 'edit', label: 'Edit', primary: true, run: act('edit') }, { key: 'patch', label: 'Patch', run: act('patch') },
      { key: 'plan', label: 'Plan', run: act('plan') }, { key: 'racks', label: 'Racks', run: act('racks') }, { key: 'sop', label: 'SOPs', run: act('sop') }];
  } else {
    o.facts = rackFacts(S.doc, e, { href: link });
    o.actions = [{ key: 'edit', label: 'Edit', primary: true, run: act('edit') }, { key: 'print', label: 'Print', run: act('print') }];
    o.overflow = [{ key: 'delete', label: 'Delete rack', danger: true, run: act('delete') }];
  }
  return o;
}

function renderPanel(kind, e, tab) {
  const panel = document.getElementById('h-panel');
  panel.textContent = '';
  panel.setAttribute('data-tab', tab);
  if (tab === 'overview') {
    panel.appendChild(h('div', { class: 'h-cards' }, summaryCards(kind, S.doc, e, S.ctxInfo).map(function (c) {
      return h('button', { type: 'button', class: 'h-card', 'data-card': c.key, onclick: function () {
        if (c.drill && c.count) note('drill:' + c.drill.title + ' [' + c.drill.ids.join(', ') + ']');
        else if (c.tab) location.hash = href(kind, e.id, c.tab);
      } }, [h('strong', null, String(c.count)), h('span', null, c.label + (c.sub ? ' \u00b7 ' + c.sub : ''))]);
    })));
  }
  const rows = [];
  for (let i = 1; i <= ROWS; i++) rows.push(h('li', null, tabLabel(tab) + ' row ' + i));
  panel.appendChild(h('ul', { class: 'h-rows', 'aria-label': tabLabel(tab) }, rows));
}

function landing() {
  const host = document.getElementById('h-panel');
  const groups = ['device', 'room', 'rack'].map(function (kind) {
    return h('section', null, [h('h2', null, KIND[kind] + 's'), h('div', null, (S.doc[COLL[kind]] || []).map(function (e) {
      return h('a', { href: href(kind, e.id) }, e.name || e.id);
    }))]);
  });
  host.appendChild(h('div', { class: 'h-landing' }, groups));
}

function route() {
  const r = parse();
  const page = document.getElementById('h-page');
  const panel = document.getElementById('h-panel');
  const sameEntity = S.handle && r.kind === S.kind && r.id === S.id;
  if (!sameEntity) {
    if (S.handle) S.handle.destroy();
    S.handle = window.__eh.handle = null;
    panel.textContent = '';
    panel.removeAttribute('data-tab');
  }
  if (!COLL[r.kind]) {
    S.kind = S.id = '';
    landing();
    return;
  }
  const e = find(r.kind, r.id);
  if (!e) {
    S.kind = S.id = '';
    panel.appendChild(h('div', { class: 'h-error', role: 'alert' }, [
      h('h2', null, KIND[r.kind] + ' \u201c' + r.id + '\u201d not found'),
      h('a', { href: '#/' }, 'All ' + KIND[r.kind].toLowerCase() + 's'),
    ]));
    return;
  }
  const keys = r.kind === 'device' ? deviceTabs(S.doc, e) : r.kind === 'room' ? roomTabs() : rackTabs();
  const res = resolveTab(keys, r.tab);
  if (res.redirect) {
    history.replaceState(null, '', href(r.kind, e.id, res.tab));
    if (r.tab) note('redirect:' + r.tab + '->' + res.tab);
  }
  S.kind = r.kind;
  S.id = e.id;
  S.tab = res.tab;
  if (sameEntity) S.handle.setTab(res.tab);
  else S.handle = window.__eh.handle = mountEntityHeader(page, optionsFor(r.kind, e, res.tab));
  renderPanel(r.kind, e, res.tab);
  document.title = (e.name || e.id) + ' \u00b7 ' + tabLabel(res.tab) + ' \u00b7 Entity harness';
}

async function main() {
  const res = await fetch('fixture-v2.json');
  if (!res.ok) throw new Error('fixture-v2.json: HTTP ' + res.status);
  S.doc = await res.json();
  try {
    const meta = await fetch('../../api/v2/meta');
    S.vocab = meta.ok ? (await meta.json()).vocab : null;
  } catch (err) {
    S.vocab = null;
  }
  S.vocab = S.vocab || { kinds: {}, disciplines: {} };
  S.ctxInfo = {
    problems: [{ id: 'pr-harness1', text: 'No HDMI out on program', status: 'open', device: 'atem-mini', room: 'main' }],
    pages: [{ id: 'pg-harness1', slug: 'atem-start', title: 'Start the ATEM', devices: ['atem-mini'] }],
  };
  if (!location.hash || location.hash === '#') history.replaceState(null, '', href('device', 'atem-mini'));
  window.addEventListener('hashchange', route);
  route();
  if (params.has('smoke')) {
    setTimeout(function () {
      document.documentElement.setAttribute('data-smoke', JSON.stringify({ ready: true, errors: window.__fathomErrors, stats: null }));
    }, 300);
  }
}

main().catch(function (err) {
  window.__fathomErrors.push('harness: ' + String(err && (err.stack || err.message) || err));
  if (params.has('smoke')) document.documentElement.setAttribute('data-smoke', JSON.stringify({ ready: false, errors: window.__fathomErrors, stats: null }));
});
