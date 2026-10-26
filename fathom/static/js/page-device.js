// Device landing and device page: wave-1 stub (docs/ui-audit.md B.2 SHELL item 2).
// PDEV replaces it in wave 2. Renders a heading and a plain link list; editing
// stays in the drawer.

import { h } from './dom.js';
import { deviceTitle } from './model-core.js';

function hrefFor(ctx, partial) {
  return typeof ctx.routeHref === 'function' ? ctx.routeHref(partial) : '#';
}

function byName(a, b) {
  return deviceTitle(a).localeCompare(deviceTitle(b));
}

export function mount(el, ctx) {
  ctx = ctx || {};
  const doc = (ctx.store && ctx.store.doc) || {};
  const route = ctx.route || {};
  const devices = (doc.devices || []).filter(function (d) { return d && d.id && !d.auto; });
  const root = h('div', { class: 'adm pd-stub' });
  el.appendChild(root);
  if (route.id) {
    const d = devices.filter(function (x) { return x.id === route.id; })[0];
    root.appendChild(h('p', null, h('a', { href: hrefFor(ctx, { view: 'devices', id: '', query: {} }) }, '\u2190 All devices')));
    if (!d) {
      root.appendChild(h('h2', null, 'Device \u201c' + route.id + '\u201d not found'));
      return { destroy: function () {} };
    }
    root.appendChild(h('h2', null, deviceTitle(d)));
    root.appendChild(h('p', { class: 'muted' }, ((d.manufacturer || '') + ' ' + (d.model || '')).trim() || d.kind || ''));
    root.appendChild(h('ul', null, [
      h('li', null, h('a', { href: hrefFor(ctx, { view: 'patch', room: d.room || route.room, query: { sel: 'device:' + d.id, drawer: '0' } }) }, 'Show in patch view')),
      h('li', null, h('button', { type: 'button', class: 'small', onclick: function () { if (ctx.openDrawer) ctx.openDrawer({ type: 'device', id: d.id, device: d.id }); } }, 'Details')),
    ]));
    if (ctx.setTitle) ctx.setTitle(deviceTitle(d));
    return { destroy: function () {} };
  }
  root.appendChild(h('h2', null, 'Devices'));
  root.appendChild(h('p', { class: 'muted' }, devices.length + ' device' + (devices.length === 1 ? '' : 's')));
  root.appendChild(h('ul', { class: 'pd-list' }, devices.slice().sort(byName).map(function (d) {
    return h('li', null, h('a', { href: hrefFor(ctx, { view: 'devices', id: d.id }), 'data-device': d.id }, deviceTitle(d)));
  })));
  return { destroy: function () {} };
}
