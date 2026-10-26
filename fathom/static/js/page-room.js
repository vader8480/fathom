// Room landing and room page: wave-1 stub (docs/ui-audit.md B.2 SHELL item 2).
// PROOM replaces it in wave 2. Renders a heading and a plain link list.

import { h } from './dom.js';

function hrefFor(ctx, partial) {
  return typeof ctx.routeHref === 'function' ? ctx.routeHref(partial) : '#';
}

export function mount(el, ctx) {
  ctx = ctx || {};
  const doc = (ctx.store && ctx.store.doc) || {};
  const route = ctx.route || {};
  const rooms = (doc.rooms || []).filter(function (r) { return r && r.id; }).slice().sort(function (a, b) { return (a.order || 0) - (b.order || 0); });
  const root = h('div', { class: 'adm pr-stub' });
  el.appendChild(root);
  if (route.id) {
    const r = rooms.filter(function (x) { return x.id === route.id; })[0];
    root.appendChild(h('p', null, h('a', { href: hrefFor(ctx, { view: 'rooms', id: '', query: {} }) }, '\u2190 All rooms')));
    if (!r) {
      root.appendChild(h('h2', null, 'Room \u201c' + route.id + '\u201d not found'));
      return { destroy: function () {} };
    }
    const n = (doc.devices || []).filter(function (d) { return d && !d.auto && d.room === r.id; }).length;
    root.appendChild(h('h2', null, r.name || r.id));
    root.appendChild(h('p', { class: 'muted' }, n + ' device' + (n === 1 ? '' : 's')));
    root.appendChild(h('ul', null, [['patch', 'Patch'], ['plan', 'Floor plans'], ['racks', 'Racks'], ['sop', 'SOPs']].map(function (v) {
      return h('li', null, h('a', { href: hrefFor(ctx, { view: v[0], room: r.id }) }, v[1]));
    })));
    if (ctx.setTitle) ctx.setTitle(r.name || r.id);
    return { destroy: function () {} };
  }
  root.appendChild(h('h2', null, 'Rooms'));
  root.appendChild(h('ul', { class: 'pr-list' }, rooms.map(function (r) {
    return h('li', null, h('a', { href: hrefFor(ctx, { view: 'rooms', id: r.id, room: r.id }), 'data-room': r.id }, r.name || r.id));
  })));
  return { destroy: function () {} };
}
