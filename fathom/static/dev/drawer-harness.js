// DRAWER harness for dev/drawer.html (docs/ui-audit.md B.2 DRAWER, D10).
// Mounts createDrawer on a shell-shaped #app-inspector with fake inspector
// content. Drawer state lives in the hash as the app's query keys
// (#sel=…&sec=…&drawer=0) and is written with the D1 history rule, so reload
// and Back behave as in the app. ?smoke=1 writes data-smoke.
/* eslint-disable */
window.__fathomErrors = window.__fathomErrors || [];
(function () {
  const errs = window.__fathomErrors;
  window.addEventListener('error', function (e) { errs.push(String((e && e.message) || e)); });
  window.addEventListener('unhandledrejection', function (e) { errs.push('unhandled: ' + String(e && e.reason && (e.reason.stack || e.reason.message) || e.reason)); });
})();

import { h } from '../js/dom.js';
import { layoutFor } from '../js/router-core.js';
import { createDrawer } from '../js/drawer.js';
import { parseDrawer, drawerParams, drawerHistory, selectionOpensDrawer } from '../js/drawer-core.js';

const ITEMS = {
  'device:foh-cl5': { title: 'FOH CL5', kind: 'Device', sections: ['identity', 'net', 'inventory', 'procedures'] },
  'port:foh-cl5:omni-in-1': { title: 'FOH CL5 \u00b7 OMNI IN 1', kind: 'Port', sections: ['identity', 'cables'] },
  'cable:c-0001': { title: 'Cable A-001', kind: 'Cable', sections: ['identity', 'ends'] },
  'rack:rk-foh': { title: 'FOH rack', kind: 'Rack', sections: ['identity', 'devices'] },
};
const SECTION_LABELS = { identity: 'Identity', net: 'Network', inventory: 'Inventory', procedures: 'Procedures',
  cables: 'Cables', ends: 'Ends', devices: 'Devices' };

const host = document.getElementById('app-inspector');
const logEl = document.getElementById('dr-h-log');
const statusEl = document.getElementById('dr-h-status');
const selbar = document.getElementById('dr-h-selbar');
const log = window.__drLog = [];

function note(text) {
  log.push(text);
  logEl.insertBefore(h('li', null, text), logEl.firstChild);
  while (logEl.children.length > 12) logEl.removeChild(logEl.lastChild);
}

function readQuery() {
  const q = {};
  new URLSearchParams(location.hash.replace(/^#\??/, '')).forEach(function (v, k) { if (!(k in q)) q[k] = v; });
  return q;
}

function hashFor(state) {
  const p = drawerParams(state);
  const parts = [];
  ['sel', 'sec', 'drawer'].forEach(function (k) {
    if (p[k] !== null) parts.push(k + '=' + encodeURIComponent(p[k]).replace(/%3A/gi, ':'));
  });
  return parts.length ? '#' + parts.join('&') : location.pathname + location.search;
}

let state = parseDrawer(readQuery());
let rendered = '';

const drawer = createDrawer(host, {
  label: 'Details',
  onClose: function (reason) { note('onClose: ' + reason); setState({ sel: null, section: null, open: false }); },
});

function openDialog(opener) {
  // Mirrors app.js dialog(): capture-phase Esc on document, so it sits above the drawer.
  let back = null;
  function close() {
    document.removeEventListener('keydown', onKey, true);
    if (back) back.remove();
    note('dialog closed');
    if (opener && opener.isConnected) opener.focus();
  }
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
  }
  const input = h('input', { type: 'text', id: 'dr-h-dialog-input', 'aria-label': 'Dialog field' });
  const box = h('div', { class: 'app-dialog', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Harness dialog' }, [
    h('header', null, [h('h2', null, 'Dialog above the drawer'), h('button', { type: 'button', class: 'icon ghost', 'aria-label': 'Close', onclick: close }, '\u00d7')]),
    h('div', { class: 'body' }, [input]),
  ]);
  back = h('div', { class: 'app-dialog-backdrop', id: 'dr-h-dialog' }, box);
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(back);
  input.focus();
  note('dialog opened');
}

function renderContent() {
  const item = ITEMS[state.sel] || { title: state.sel || '', kind: 'Item', sections: ['identity'] };
  if (rendered !== state.sel) {
    rendered = state.sel;
    host.innerHTML = '';
    const sections = item.sections.map(function (key) {
      return h('details', { 'data-section': key }, [
        h('summary', null, SECTION_LABELS[key] || key),
        h('p', null, item.kind + ' ' + (SECTION_LABELS[key] || key).toLowerCase() + ' fields.'),
        h('div', { class: 'row' }, [h('button', { type: 'button', class: 'small' }, 'Edit ' + key)]),
      ]);
    });
    host.appendChild(h('div', { class: 'dr-h-ins' }, [
      h('header', null, [
        h('h2', null, item.title),
        h('button', { type: 'button', class: 'dr-h-dialog-btn', onclick: function (e) { openDialog(e.currentTarget); } }, 'Dialog'),
        h('button', { type: 'button', class: 'icon ghost dr-h-close', 'aria-label': 'Close details',
          onclick: function () { note('close button'); drawer.close(); setState({ sel: null, section: null, open: false }); } }, '\u00d7'),
      ]),
      h('div', { class: 'body' }, [
        h('label', null, ['Name', h('input', { type: 'text', id: 'dr-h-name', value: item.title })]),
      ].concat(sections)),
    ]));
  }
  Array.prototype.forEach.call(host.querySelectorAll('details[data-section]'), function (d) {
    if (state.section && d.getAttribute('data-section') === state.section) {
      d.open = true;
      d.scrollIntoView({ block: 'nearest' });
    }
  });
}

function sync(openOpts) {
  if (state.sel) renderContent();
  else { host.innerHTML = ''; rendered = ''; }
  if (state.open) drawer.open(openOpts);
  else drawer.close();
  selbar.hidden = !(state.sel && !state.open);
  document.getElementById('dr-h-selbar-title').textContent = state.sel ? (ITEMS[state.sel] ? ITEMS[state.sel].title : state.sel) : '';
  status();
}

function status() {
  statusEl.textContent = layoutFor(window.innerWidth) + ' \u00b7 ' + drawer.mode() + ' \u00b7 ' + (drawer.isOpen() ? 'open' : 'closed');
}

function setState(next, openOpts) {
  const how = drawerHistory(state, next);
  state = { sel: next.sel || null, section: next.section || null, open: !!next.open && !!next.sel };
  if (how === 'push') history.pushState(null, '', hashFor(state));
  else if (how === 'replace') history.replaceState(null, '', hashFor(state));
  if (how) note((how === 'push' ? 'push ' : 'replace ') + (location.hash || '(no hash)'));
  sync(openOpts);
}

function openDrawer(sel, section) {
  setState({ sel: sel, section: section || null, open: true });
}

function canvasSelect(sel) {
  const open = selectionOpensDrawer('patch', { view: 'patch' }, layoutFor(window.innerWidth), false);
  setState({ sel: sel, section: null, open: open }, { focus: false });
}

function row(label, key, onclick, attrs) {
  return h('li', null, h('button', Object.assign({ type: 'button', onclick: onclick }, attrs || {}), [h('span', null, label), h('span', { class: 'k' }, key)]));
}

const rows = document.getElementById('dr-h-rows');
Object.keys(ITEMS).forEach(function (sel) {
  rows.appendChild(row(ITEMS[sel].title, sel, function () { openDrawer(sel); }, { 'data-open': sel }));
});
rows.appendChild(row('FOH CL5 at the inventory section', 'sec=inventory', function () { openDrawer('device:foh-cl5', 'inventory'); },
  { 'data-open': 'device:foh-cl5', 'data-sec': 'inventory' }));
const canvas = document.getElementById('dr-h-canvas');
canvas.appendChild(row('Select FOH CL5 on the patch canvas', 'patch', function () { canvasSelect('device:foh-cl5'); }, { 'data-canvas': 'device:foh-cl5' }));

document.getElementById('dr-h-selbar-open').addEventListener('click', function () { openDrawer(state.sel, state.section); });
document.getElementById('dr-h-selbar-close').addEventListener('click', function () { setState({ sel: null, section: null, open: false }); });
window.addEventListener('popstate', function () { state = parseDrawer(readQuery()); note('popstate ' + (location.hash || '(no hash)')); sync(); });
window.addEventListener('resize', function () { drawer.relayout(); status(); });

window.__drawer = drawer;
window.__drh = { openDrawer: openDrawer, canvasSelect: canvasSelect, state: function () { return state; } };

sync();
if (new URLSearchParams(location.search).has('smoke')) {
  setTimeout(function () {
    document.documentElement.setAttribute('data-smoke', JSON.stringify({ ready: true, errors: window.__fathomErrors }));
  }, 0);
}
