// Global search palette (docs/ui-audit.md B.2 SEARCH): a dropdown anchored
// under #app-search at md/lg and a full-screen sheet at sm. Online it asks the
// server; offline or on error it searches the loaded doc (search-core).
//
// ctx members used: store.doc, api.search, project, role, route, navigateRoute,
// recent, sections, layout. All are optional.

import { h, on } from './dom.js';
import { layoutFor, buildRoute, mergeRoute } from './router-core.js';
import {
  CATEGORIES, kindsFor, categorize, groupHits, augmentLocal, mergeHits, roleFilter,
  targetFor, recentHits, recentType, moveActive, noMatchText,
} from './search-core.js';

const DEBOUNCE_MS = 150;
const LIMIT = 40;
const RECENT_MAX = 8;
const EMPTY_ROUTE = { project: '', room: '', view: '', id: '', tab: '', sub: '', extra: [], query: {} };

let S = null;

function glyphOf(key) {
  for (let i = 0; i < CATEGORIES.length; i++) if (CATEGORIES[i].key === key) return CATEGORIES[i].glyph;
  return CATEGORIES[0].glyph;
}

function visible(el) {
  return !!el && el.getClientRects().length > 0;
}

function routeOf(ctx) {
  let r = null;
  try { r = ctx.route; } catch (e) { r = null; }
  return r && typeof r === 'object' ? r : EMPTY_ROUTE;
}

function docOf(ctx) {
  return ctx.store && ctx.store.doc ? ctx.store.doc : null;
}

function layoutOf(ctx) {
  if (typeof ctx.layout === 'function') {
    const l = ctx.layout();
    if (l === 'sm' || l === 'md' || l === 'lg') return l;
  }
  return layoutFor(window.innerWidth);
}

function offline(ctx) {
  return !ctx.api || typeof ctx.api.search !== 'function' || !ctx.project || navigator.onLine === false;
}

// Older servers send no `status`; fill device status from the doc.
function withStatus(hits, doc) {
  const devs = {};
  ((doc && doc.devices) || []).forEach(function (d) { if (d && d.id) devs[d.id] = d; });
  return hits.map(function (x) {
    if (x && typeof x.status === 'string') return x;
    const d = x && x.kind === 'device' ? devs[x.id] : null;
    return Object.assign({}, x, { status: d && d.status ? String(d.status) : '' });
  });
}

export function closeSearch() {
  if (S) S.close(true);
}

export function openSearch(ctx, opts) {
  ctx = ctx || {};
  opts = opts || {};
  if (S) {
    if (opts.category) S.setCategory(opts.category);
    if (typeof opts.query === 'string') S.setQuery(opts.query);
    S.input.focus();
    S.input.select();
    return S.api;
  }
  S = create(ctx, opts);
  return S.api;
}

function create(ctx, opts) {
  const opener = document.activeElement;
  const offs = [];
  let items = [];
  let active = -1;
  let timer = null;
  let seq = 0;
  let closed = false;
  let busy = false;
  let pendingGo = false;

  const back = h('button', { type: 'button', class: 'sr-back', 'aria-label': 'Close search', onclick: function () { st.close(true); } }, '\u2039');
  const input = h('input', {
    id: 'app-palette-input', class: 'sr-input', type: 'search', role: 'combobox', autocomplete: 'off', autocapitalize: 'off',
    spellcheck: 'false', enterkeyhint: 'go', 'aria-label': 'Search', 'aria-autocomplete': 'list', 'aria-expanded': 'false',
    'aria-controls': 'app-palette-list', placeholder: 'Search devices, cables, rooms\u2026',
  });
  const select = h('select', { id: 'app-search-cat', class: 'sr-cat', 'aria-label': 'Category' },
    CATEGORIES.map(function (c) { return h('option', { value: c.key }, c.label); }));
  const list = h('ul', { id: 'app-palette-list', class: 'sr-list', role: 'listbox', 'aria-label': 'Search results' });
  const empty = h('div', { class: 'sr-empty', hidden: true });
  const foot = h('div', { class: 'sr-foot' });
  const live = h('span', { class: 'sr-only', 'aria-live': 'polite' });
  const root = h('div', { id: 'app-palette', class: 'sr-root', role: 'dialog', 'aria-label': 'Search' }, [
    h('div', { class: 'sr-bar' }, [back, h('span', { class: 'sr-icon', 'aria-hidden': 'true' }, '\u2315'), input, select]),
    list, empty, foot, live,
  ]);

  function place() {
    const lay = layoutOf(ctx);
    root.setAttribute('data-layout', lay);
    if (lay === 'sm') {
      root.setAttribute('aria-modal', 'true');
      root.style.top = root.style.left = root.style.width = root.style.maxHeight = '';
      return;
    }
    root.removeAttribute('aria-modal');
    const W = window.innerWidth;
    const H = window.innerHeight;
    const w = Math.min(640, Math.round(W * 0.9));
    const anchor = document.getElementById('app-search');
    const r = visible(anchor) ? anchor.getBoundingClientRect() : null;
    let top = Math.round(H * 0.1);
    let left = (W - w) / 2;
    if (r && r.width > 0) { top = Math.round(r.bottom + 4); left = r.left + r.width / 2 - w / 2; }
    left = Math.max(8, Math.min(W - w - 8, left));
    root.style.top = top + 'px';
    root.style.left = Math.round(left) + 'px';
    root.style.width = w + 'px';
    root.style.maxHeight = Math.max(160, H - top - 12) + 'px';
  }

  function setActive(i, scroll) {
    if (active >= 0 && items[active]) items[active].li.setAttribute('aria-selected', 'false');
    active = i >= 0 && i < items.length ? i : -1;
    if (active < 0) { input.removeAttribute('aria-activedescendant'); return; }
    const li = items[active].li;
    li.setAttribute('aria-selected', 'true');
    input.setAttribute('aria-activedescendant', li.id);
    if (scroll && li.scrollIntoView) li.scrollIntoView({ block: 'nearest' });
  }

  function option(hit, cat, glyph) {
    const n = items.length;
    const status = hit.status ? String(hit.status) : '';
    const li = h('li', {
      class: 'sr-hit', role: 'option', id: 'sr-hit-' + n, 'aria-selected': 'false',
      'data-hit-kind': hit.kind, 'data-hit-id': hit.id, 'data-hit-cat': cat,
      onclick: function () { go(n); },
      onpointermove: function () { if (active !== n) setActive(n, false); },
    }, [
      h('span', { class: 'sr-glyph', 'aria-hidden': 'true' }, glyph),
      h('span', { class: 'sr-text' }, [h('span', { class: 'sr-title' }, String(hit.title || hit.id)), h('span', { class: 'sr-sub' }, String(hit.subtitle || ''))]),
      h('span', { class: 'sr-status', 'data-status': status }, status),
    ]);
    items.push({ hit: hit, li: li });
    return li;
  }

  // groups: [{key, label, hits, glyph?}]; a hit's glyph is its category's.
  function render(groups, initial) {
    list.innerHTML = '';
    items = [];
    active = -1;
    groups.forEach(function (g, gi) {
      if (!g.hits.length) return;
      list.appendChild(h('li', { class: 'sr-group', role: 'presentation', id: 'sr-group-' + gi }, g.label));
      g.hits.forEach(function (hit) {
        const cat = hit.kind === 'section' ? 'section' : categorize(hit);
        list.appendChild(option(hit, cat, hit.glyph || glyphOf(cat)));
      });
    });
    input.setAttribute('aria-expanded', items.length ? 'true' : 'false');
    setActive(initial, false);
    list.scrollTop = 0;
  }

  function idle() {
    const cat = select.value;
    const kinds = kindsFor(cat);
    const doc = docOf(ctx);
    const recent = roleFilter(recentHits(doc, ctx.recent), ctx.role).filter(function (x) {
      return !kinds || kinds.indexOf(x.kind) >= 0;
    }).slice(0, RECENT_MAX).map(function (x) { return Object.assign({}, x, { category: cat === 'all' ? categorize(x) : cat }); });
    const groups = [{ key: 'recent', label: 'Recent', hits: recent }];
    if (cat === 'all') {
      const secs = Array.isArray(ctx.sections) ? ctx.sections : [];
      groups.push({ key: 'goto', label: 'Go to', hits: secs.filter(function (s) { return s && s.views && s.views.length; }).map(function (s) {
        return { kind: 'section', id: s.key, title: s.label, subtitle: '', status: '', glyph: s.glyph, view: s.views[0] };
      }) });
    }
    empty.hidden = true;
    empty.innerHTML = '';
    render(groups, -1);
    hint(false);
    live.textContent = '';
  }

  function hint(local) {
    foot.textContent = (local ? 'Offline search \u00b7 ' : '') + '\u2191\u2193 to move \u00b7 Enter to open \u00b7 Esc to close';
    foot.setAttribute('data-offline', local ? '1' : '0');
  }

  function show(hits, q, cat, local) {
    const groups = groupHits(hits, cat);
    render(groups, groups.length ? 0 : -1);
    hint(local);
    empty.innerHTML = '';
    empty.hidden = items.length > 0;
    if (!items.length) {
      empty.appendChild(h('p', null, noMatchText(q, cat)));
      if (cat !== 'all') {
        empty.appendChild(h('button', { type: 'button', class: 'sr-all', onclick: function () { st.setCategory('all'); input.focus(); run(); } }, 'Search all categories'));
      }
    }
    live.textContent = items.length ? items.length + (items.length === 1 ? ' result' : ' results') : noMatchText(q, cat);
    if (pendingGo) {
      pendingGo = false;
      if (active >= 0) go(active);
    }
  }

  function localHits(doc, q, cat) {
    const kinds = kindsFor(cat);
    return augmentLocal(doc, q, kinds ? Infinity : LIMIT).filter(function (x) { return !kinds || kinds.indexOf(x.kind) >= 0; }).slice(0, LIMIT);
  }

  function run() {
    if (timer) { clearTimeout(timer); timer = null; }
    const q = input.value.trim();
    const cat = select.value;
    const my = ++seq;
    const done = function () {
      busy = false;
      root.removeAttribute('aria-busy');
    };
    if (!q) { done(); pendingGo = false; idle(); return; }
    const doc = docOf(ctx);
    const local = function () {
      if (closed || my !== seq) return;
      done();
      show(roleFilter(localHits(doc, q, cat), ctx.role), q, cat, true);
    };
    if (offline(ctx)) { local(); return; }
    busy = true;
    root.setAttribute('aria-busy', 'true');
    ctx.api.search(ctx.project, q, { limit: LIMIT, kinds: kindsFor(cat) }).then(function (r) {
      if (closed || my !== seq) return;
      done();
      let hits = withStatus((r && Array.isArray(r.hits)) ? r.hits : [], doc);
      if (cat === 'all' || cat === 'networks') {
        hits = mergeHits(hits, localHits(doc, q, 'networks').filter(function (x) { return x.kind === 'network'; }));
      }
      show(roleFilter(hits, ctx.role), q, cat, false);
    }, local);
  }

  function navigate(target) {
    if (typeof ctx.navigateRoute === 'function') ctx.navigateRoute(target);
    else location.hash = buildRoute(mergeRoute(routeOf(ctx), target));
  }

  function go(i) {
    const it = items[i];
    if (!it) return;
    const hit = it.hit;
    let target;
    if (hit.kind === 'section') target = { view: hit.view, id: '', tab: '', sub: '', query: {} };
    else target = targetFor(hit, routeOf(ctx), docOf(ctx));
    const type = recentType(hit);
    if (type && ctx.recent && typeof ctx.recent.push === 'function') ctx.recent.push(type, hit.id);
    st.close(false);
    if (target) navigate(target);
  }

  function focusables() {
    return Array.prototype.filter.call(root.querySelectorAll('button, input, select'), function (el) { return !el.disabled && visible(el); });
  }

  function onKey(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      st.close(true);
      return;
    }
    if (e.key === 'Tab') {
      const f = focusables();
      if (!f.length) return;
      const at = f.indexOf(document.activeElement);
      e.preventDefault();
      f[at < 0 ? 0 : (at + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
      return;
    }
    if (e.target !== input || e.altKey || e.metaKey || e.ctrlKey) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      setActive(moveActive(items.length, active, e.key === 'ArrowDown' ? 1 : -1), true);
    } else if (e.key === 'Enter' && !e.isComposing) {
      e.preventDefault();
      if (timer || busy) {
        pendingGo = true;
        if (timer) run();
        return;
      }
      if (active >= 0) go(active);
    }
  }

  function onOutside(e) {
    if (root.contains(e.target)) return;
    const anchor = document.getElementById('app-search');
    if (anchor && anchor.contains(e.target)) return;
    st.close(false);
  }

  const st = {
    input: input,
    root: root,
    setQuery: function (q) { input.value = q; run(); },
    setCategory: function (key) {
      let ok = false;
      CATEGORIES.forEach(function (c) { if (c.key === key) ok = true; });
      select.value = ok ? key : 'all';
    },
    close: function (restore) {
      if (closed) return;
      closed = true;
      if (timer) clearTimeout(timer);
      offs.forEach(function (off) { off(); });
      root.remove();
      if (S === st) S = null;
      if (!restore) return;
      const anchor = document.getElementById('app-search');
      const to = visible(anchor) ? anchor : opener;
      if (to && typeof to.focus === 'function' && document.contains(to)) to.focus();
    },
    api: null,
  };
  st.api = { root: root, input: input, close: function () { st.close(true); } };

  st.setCategory(opts.category || 'all');
  if (typeof opts.query === 'string') input.value = opts.query;
  offs.push(on(input, 'input', function () {
    pendingGo = false;
    if (timer) clearTimeout(timer);
    timer = setTimeout(run, DEBOUNCE_MS);
  }));
  offs.push(on(select, 'change', run));
  offs.push(on(document, 'keydown', onKey, true));
  offs.push(on(document, 'pointerdown', onOutside, true));
  offs.push(on(window, 'resize', place));
  document.body.appendChild(root);
  place();
  run();
  input.focus();
  return st;
}
