// Rack library palette (docs/SPEC.md §6.13.11): a searchable, categorised list of rack-mountable
// templates with favourites and recents. The host owns placement: Add / Enter call onPick(entry,
// template) with the full template, a pointer drag on a row calls onDragStart(entry, event). A palette
// list (D9 picker exemption), not a datatable. Prefs live in localStorage `fathom.ui.rack.palette`.
//
//   mountRackPalette(el, ctx, {onPick, onDragStart, presets, storage}) -> {root, destroy, focus, refresh}

import { h, on } from './dom.js';
import * as core from './rack-palette-core.js';
import { skeleton, emptyState, inlineError } from './feedback.js';

const PAGE = 200;
const DRAG_PX = 5;
const TOUCH_SLOP_PX = 8;
const LONG_PRESS_MS = 350;
const STAR_ON = '\u2605';
const STAR_OFF = '\u2606';

let seq = 0;

function closest(node, sel, stop) {
  for (let n = node; n && n !== stop && n.nodeType === 1; n = n.parentElement) if (n.matches(sel)) return n;
  return null;
}

function defaultStorage() {
  try { return typeof window !== 'undefined' ? window.localStorage : null; } catch (e) { return null; }
}

function loadPrefs(storage) {
  try { return core.readPrefs(storage ? storage.getItem(core.STORAGE_KEY) : null); } catch (e) { return core.readPrefs(null); }
}

function savePrefs(storage, prefs) {
  try { if (storage) storage.setItem(core.STORAGE_KEY, JSON.stringify(prefs)); } catch (e) { /* full or blocked storage */ }
}

function imageBase(ctx) {
  const b = (ctx.api && ctx.api.base) || ctx.appRoot || '/';
  return b.charAt(b.length - 1) === '/' ? b : b + '/';
}

function minimalTemplate(e) {
  return { id: e.id, manufacturer: e.manufacturer, model: e.model, name: e.name, kind: e.kind, ru: e.ru, ports: [] };
}

export function mountRackPalette(el, ctx, opts) {
  ctx = ctx || {};
  opts = opts || {};
  const uid = 'rpal-' + (++seq);
  const storage = opts.storage || defaultStorage();
  const base = imageBase(ctx);
  const broken = {};
  const offs = [];
  const st = { entries: [], loading: true, error: null, q: '', cat: 'all', limit: PAGE, prefs: loadPrefs(storage), busy: {} };
  let rowsByKey = {};
  let drag = null;
  let destroyed = false;
  let loadSeq = 0;

  const search = h('input', {
    type: 'search', class: 'rpal-search', id: uid + '-q', placeholder: 'Search rack gear', 'aria-label': 'Search the rack library',
    autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', enterkeyhint: 'search',
  });
  const chips = h('div', { class: 'rpal-chips', role: 'group', 'aria-label': 'Category' });
  const body = h('div', { class: 'rpal-body', id: uid + '-body' });
  const status = h('div', { class: 'rpal-status sr-only', role: 'status', 'aria-live': 'polite' });
  const root = h('div', { class: 'rpal-root', 'data-rpal': '' }, [
    h('div', { class: 'rpal-head' }, [search, chips]), body, status,
  ]);
  el.appendChild(root);

  function vocab() {
    return ctx.vocab || (ctx.store && ctx.store.vocab) || null;
  }

  function announce(text) {
    status.textContent = text;
  }

  // ---------------------------------------------------------------- rendering

  function thumb(e) {
    const swatch = h('span', { class: 'rpal-swatch', style: { '--rpal-c': core.categoryColor(e.category) }, title: core.categoryLabel(e.category) });
    if (!e.image_front || broken[e.image_front]) return h('span', { class: 'rpal-thumb', 'aria-hidden': 'true' }, swatch);
    const img = h('img', {
      class: 'rpal-img', src: base + 'static/rack-images/' + e.image_front, alt: '', loading: 'lazy', decoding: 'async', draggable: 'false',
      onerror: function () {
        broken[e.image_front] = true;
        if (img.parentNode) img.parentNode.replaceChild(swatch, img);
      },
    });
    return h('span', { class: 'rpal-thumb', 'aria-hidden': 'true' }, img);
  }

  function row(e, sec) {
    const fav = core.isFav(st.prefs, e.id, e.aliases);
    const sub = [e.manufacturer, e.model && e.model !== e.name ? e.model : ''].filter(Boolean).join(' \u00b7 ');
    const key = sec + ':' + e.id;
    const li = h('li', {
      class: 'rpal-row', 'data-id': e.id, 'data-sec': sec, 'data-source': e.source, 'data-category': e.category, tabindex: '-1',
      'aria-label': e.name + (sub ? ', ' + sub : '') + ', ' + e.ru + 'U',
    }, [
      thumb(e),
      h('span', { class: 'rpal-text' }, [
        h('span', { class: 'rpal-name' }, e.name),
        sub ? h('span', { class: 'rpal-sub' }, sub) : null,
      ]),
      h('span', { class: 'rpal-ru', title: e.ru + ' rack units' }, e.ru + 'U'),
      h('button', {
        type: 'button', class: 'rpal-star' + (fav ? ' rpal-on' : ''), 'aria-pressed': fav ? 'true' : 'false', tabindex: '-1',
        'aria-label': 'Favourite ' + e.name, title: fav ? 'Remove from favourites (f)' : 'Add to favourites (f)',
      }, fav ? STAR_ON : STAR_OFF),
      h('button', { type: 'button', class: 'rpal-add', tabindex: '-1', 'aria-label': 'Add ' + e.name, disabled: st.busy[e.id] ? true : null }, st.busy[e.id] ? 'Adding\u2026' : 'Add'),
    ]);
    rowsByKey[key] = e;
    return li;
  }

  function section(key, title, list, count) {
    return h('section', { class: 'rpal-sec', 'data-sec': key, 'aria-label': title }, [
      h('h3', { class: 'rpal-sec-title' }, [title, count !== undefined ? h('span', { class: 'rpal-count' }, String(count)) : null]),
      h('ul', { class: 'rpal-list', role: 'list' }, list.map(function (e) { return row(e, key); })),
    ]);
  }

  function inCat(e) {
    return st.cat === 'all' || e.category === st.cat;
  }

  function renderChips() {
    const groups = core.groupByCategory(st.entries);
    if (st.cat !== 'all' && !groups.some(function (g) { return g.key === st.cat; })) st.cat = 'all';
    const chip = function (key, label, n, color) {
      return h('button', { type: 'button', class: 'rpal-chip', 'data-cat': key, 'aria-pressed': st.cat === key ? 'true' : 'false' }, [
        color ? h('i', { class: 'rpal-dot', style: { '--rpal-c': color }, 'aria-hidden': 'true' }) : null,
        label, h('span', { class: 'rpal-chip-n' }, String(n)),
      ]);
    };
    chips.textContent = '';
    if (!st.entries.length) return;
    chips.appendChild(chip('all', 'All', st.entries.length, ''));
    groups.forEach(function (g) { chips.appendChild(chip(g.key, g.label, g.entries.length, g.color)); });
  }

  function focusKey() {
    const a = document.activeElement;
    if (!a || !body.contains(a)) return null;
    const r = closest(a, '.rpal-row', body);
    if (!r) return null;
    const part = a === r ? 'row' : (a.classList.contains('rpal-star') ? 'star' : (a.classList.contains('rpal-add') ? 'add' : 'row'));
    return { sec: r.getAttribute('data-sec'), id: r.getAttribute('data-id'), part: part };
  }

  function rowEl(sec, id) {
    const all = body.querySelectorAll('.rpal-row');
    for (let i = 0; i < all.length; i++) if (all[i].getAttribute('data-sec') === sec && all[i].getAttribute('data-id') === id) return all[i];
    return null;
  }

  function restoreFocus(f) {
    if (!f) return;
    const r = rowEl(f.sec, f.id) || body.querySelector('.rpal-row[data-id="' + cssEsc(f.id) + '"]');
    if (!r) return;
    const t = f.part === 'star' ? r.querySelector('.rpal-star') : (f.part === 'add' ? r.querySelector('.rpal-add') : r);
    setActive(r);
    (t || r).focus({ preventScroll: false });
  }

  function cssEsc(s) {
    return String(s).replace(/["\\]/g, '\\$&');
  }

  function setActive(r) {
    const all = body.querySelectorAll('.rpal-row');
    for (let i = 0; i < all.length; i++) {
      const on = all[i] === r;
      all[i].setAttribute('tabindex', on ? '0' : '-1');
      all[i].classList.toggle('rpal-active', on);
      const btns = all[i].querySelectorAll('button');
      for (let j = 0; j < btns.length; j++) btns[j].setAttribute('tabindex', on ? '0' : '-1');
    }
  }

  function render() {
    if (destroyed) return;
    const f = focusKey();
    rowsByKey = {};
    body.textContent = '';
    renderChips();
    if (st.loading) {
      body.appendChild(skeleton('list', 6));
      return;
    }
    if (st.error) {
      body.appendChild(inlineError(st.error, refresh));
      return;
    }
    if (!st.entries.length) {
      body.appendChild(emptyState({ title: 'No rack gear in the library', text: 'Templates with a rack height (RU) are listed here.' }));
      announce('No rack gear');
      return;
    }
    if (!st.q) {
      const favs = core.entriesFor(st.entries, st.prefs.favs).filter(inCat);
      const recents = core.entriesFor(st.entries, st.prefs.recents).filter(inCat);
      if (favs.length) body.appendChild(section('favs', 'Favourites', favs));
      if (recents.length) body.appendChild(section('recent', 'Recent', recents));
    }
    const results = core.searchEntries(st.entries, st.q, { category: st.cat, vocab: vocab() });
    const catLabel = st.cat === 'all' ? '' : core.categoryLabel(st.cat);
    if (!results.length) {
      body.appendChild(emptyState({
        title: 'No matches for \u201c' + st.q + '\u201d' + (catLabel ? ' in ' + catLabel : '') + '.',
        text: 'Try a maker, model or part number.',
        action: catLabel ? { label: 'Search all categories', run: function () { st.cat = 'all'; render(); search.focus(); } } : null,
      }));
      announce('No matches');
      restoreFocus(f);
      return;
    }
    const title = st.q ? 'Results' : (catLabel || 'All gear');
    body.appendChild(section('results', title, results.slice(0, st.limit), results.length));
    if (results.length > st.limit) {
      const more = Math.min(PAGE, results.length - st.limit);
      body.appendChild(h('button', { type: 'button', class: 'rpal-more ghost' }, 'Show ' + more + ' more (' + (results.length - st.limit) + ' hidden)'));
    }
    const first = body.querySelector('.rpal-row');
    if (first) setActive(first);
    announce(results.length + (results.length === 1 ? ' item' : ' items'));
    restoreFocus(f);
  }

  // ---------------------------------------------------------------- actions

  function entryOf(r) {
    return r ? rowsByKey[r.getAttribute('data-sec') + ':' + r.getAttribute('data-id')] || null : null;
  }

  function toggleFav(e) {
    st.prefs = core.toggleFav(st.prefs, e.id, e.aliases);
    savePrefs(storage, st.prefs);
    const fav = core.isFav(st.prefs, e.id, e.aliases);
    render();
    announce((fav ? 'Added to' : 'Removed from') + ' favourites: ' + e.name);
  }

  function resolveTemplate(e) {
    if (e.template && Array.isArray(e.template.ports)) return Promise.resolve(e.template);
    if (ctx.api && typeof ctx.api.template === 'function') {
      return Promise.resolve(ctx.api.template(e.id, ctx.project)).then(function (t) {
        if (!t || typeof t !== 'object') throw new Error('Template ' + e.id + ' not found');
        e.template = t;
        return t;
      });
    }
    return Promise.resolve(minimalTemplate(e));
  }

  function pick(e) {
    if (!e || st.busy[e.id]) return Promise.resolve(null);
    st.busy[e.id] = true;
    render();
    return resolveTemplate(e).then(function (t) {
      delete st.busy[e.id];
      st.prefs = core.pushRecent(st.prefs, e.id, e.aliases);
      savePrefs(storage, st.prefs);
      render();
      announce('Added ' + e.name);
      if (typeof opts.onPick === 'function') opts.onPick(e, t);
      return t;
    }, function (err) {
      delete st.busy[e.id];
      render();
      const msg = 'Could not load ' + e.name + ': ' + ((err && err.message) || err);
      if (typeof ctx.toast === 'function') ctx.toast(msg, 'err');
      announce(msg);
      return null;
    });
  }

  function rows() {
    return Array.prototype.slice.call(body.querySelectorAll('.rpal-row'));
  }

  function moveTo(i) {
    const list = rows();
    if (i < 0) { search.focus(); return; }
    const r = list[i];
    if (!r) return;
    setActive(r);
    r.focus();
    if (r.scrollIntoView) r.scrollIntoView({ block: 'nearest' });
  }

  // ---------------------------------------------------------------- events

  offs.push(on(search, 'input', function () {
    st.q = search.value;
    st.limit = PAGE;
    body.scrollTop = 0;
    render();
  }));
  offs.push(on(search, 'keydown', function (ev) {
    if (ev.key === 'ArrowDown') { ev.preventDefault(); moveTo(0); }
    else if (ev.key === 'Escape' && search.value) { ev.preventDefault(); ev.stopPropagation(); search.value = ''; st.q = ''; render(); }
  }));
  offs.push(on(chips, 'click', function (ev) {
    const c = closest(ev.target, '.rpal-chip', chips);
    if (!c) return;
    st.cat = c.getAttribute('data-cat') || 'all';
    st.limit = PAGE;
    body.scrollTop = 0;
    render();
  }));
  offs.push(on(body, 'click', function (ev) {
    if (closest(ev.target, '.rpal-more', body)) { st.limit += PAGE; render(); return; }
    const r = closest(ev.target, '.rpal-row', body);
    const e = entryOf(r);
    if (!e) return;
    if (closest(ev.target, '.rpal-star', r)) { setActive(r); toggleFav(e); return; }
    if (closest(ev.target, '.rpal-add', r)) { setActive(r); pick(e); return; }
    setActive(r);
    r.focus();
  }));
  offs.push(on(body, 'keydown', function (ev) {
    const r = closest(ev.target, '.rpal-row', body);
    if (!r || ev.altKey || ev.ctrlKey || ev.metaKey) return;
    const list = rows();
    const i = list.indexOf(r);
    if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'PageDown', 'PageUp'].indexOf(ev.key) >= 0) {
      ev.preventDefault();
      moveTo(core.nextRow(list.length, i, ev.key));
      return;
    }
    if (ev.target !== r) return;
    const e = entryOf(r);
    if (!e) return;
    if (ev.key === 'Enter') { ev.preventDefault(); pick(e); }
    else if (ev.key === 'f' || ev.key === 'F') { ev.preventDefault(); toggleFav(e); }
  }));
  offs.push(on(body, 'contextmenu', function (ev) {
    if (drag && drag.started) ev.preventDefault();
  }));

  // Pointer drag: mouse/pen start after DRAG_PX of movement; touch needs a long press so a swipe scrolls.
  function endDrag() {
    if (!drag) return;
    if (drag.timer) clearTimeout(drag.timer);
    if (drag.row) drag.row.classList.remove('rpal-dragging');
    drag = null;
  }
  function startDrag(ev) {
    if (!drag || drag.started) return;
    if (drag.timer) clearTimeout(drag.timer);
    drag.timer = 0;
    drag.started = true;
    drag.row.classList.add('rpal-dragging');
    opts.onDragStart(drag.entry, ev);
  }
  offs.push(on(body, 'pointerdown', function (ev) {
    if (typeof opts.onDragStart !== 'function' || ev.isPrimary === false) return;
    if (ev.pointerType === 'mouse' && ev.button !== 0) return;
    const r = closest(ev.target, '.rpal-row', body);
    if (!r || closest(ev.target, 'button', r)) return;
    const e = entryOf(r);
    if (!e) return;
    endDrag();
    drag = { entry: e, row: r, id: ev.pointerId, x: ev.clientX, y: ev.clientY, touch: ev.pointerType === 'touch', started: false, timer: 0 };
    if (drag.touch) drag.timer = setTimeout(function () { startDrag(ev); }, LONG_PRESS_MS);
  }));
  offs.push(on(document, 'pointermove', function (ev) {
    if (!drag || drag.started || ev.pointerId !== drag.id) return;
    const d = Math.max(Math.abs(ev.clientX - drag.x), Math.abs(ev.clientY - drag.y));
    if (drag.touch) { if (d > TOUCH_SLOP_PX) endDrag(); }
    else if (d > DRAG_PX) startDrag(ev);
  }));
  offs.push(on(document, 'pointerup', function (ev) { if (drag && ev.pointerId === drag.id) endDrag(); }));
  offs.push(on(document, 'pointercancel', function (ev) { if (drag && ev.pointerId === drag.id) endDrag(); }));
  offs.push(on(body, 'touchmove', function (ev) { if (drag && drag.started) ev.preventDefault(); }, { passive: false }));

  // ---------------------------------------------------------------- data

  function refresh() {
    const my = ++loadSeq;
    st.loading = true;
    st.error = null;
    render();
    const lib = ctx.api && typeof ctx.api.library === 'function'
      ? Promise.resolve().then(function () { return ctx.api.library({ source: 'all', rack: 1, project: ctx.project }); })
      : Promise.resolve(null);
    return lib.then(function (res) {
      if (destroyed || my !== loadSeq) return;
      st.entries = core.normalizeEntries(res, opts.presets || null);
      st.loading = false;
      render();
    }, function (err) {
      if (destroyed || my !== loadSeq) return;
      st.loading = false;
      st.error = err || new Error('Could not load the library');
      render();
    });
  }

  refresh();

  return {
    root: root,
    focus: function () { search.focus(); },
    refresh: refresh,
    destroy: function () {
      destroyed = true;
      endDrag();
      offs.forEach(function (off) { off(); });
      if (root.parentNode) root.parentNode.removeChild(root);
    },
  };
}

// ------------------------------------------------------------ dev harness (fathom/static/dev/rack-palette.html)

// Boots the harness page from its JSON data block: a stub ctx whose api serves the inline library and
// templates. Query: ?api=0 (no api: presets only), ?api=real (the server's library through api.js;
// &project=<name> for project templates), ?fail=1 (the first library call fails), ?many=N (N extra
// synthetic entries), ?smoke=1 (data-smoke on <html>). window.__rpal exposes the handle and the
// recorded picks, drags and calls.
export function bootHarness() {
  if (new URLSearchParams(location.search).get('api') === 'real') {
    return import('./api.js').then(function (m) {
      const real = m.createApi({ base: '/' });
      return fetch('/api/v2/meta', { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; })
        .then(function (meta) { return bootStub(real, (meta && meta.vocab) || null); });
    });
  }
  return bootStub(null, null);
}

function bootStub(realApi, realVocab) {
  const errs = window.__fathomErrors = window.__fathomErrors || [];
  window.addEventListener('error', function (e) { errs.push(String((e && e.message) || e)); });
  window.addEventListener('unhandledrejection', function (e) { errs.push('unhandled: ' + String(e && e.reason && (e.reason.message || e.reason))); });
  const params = new URLSearchParams(location.search);
  const dataEl = document.getElementById('rpal-h-data');
  const data = JSON.parse((dataEl && dataEl.textContent) || '{}');
  const templates = data.library && Array.isArray(data.library.templates) ? data.library.templates.slice() : [];
  const many = Math.min(2000, parseInt(params.get('many') || '0', 10) || 0);
  for (let i = 1; i <= many; i++) {
    templates.push({ id: 'synthetic-' + i, manufacturer: 'Synth', model: 'Unit ' + i, name: 'Synthetic unit ' + i, kind: i % 2 ? 'switch' : 'computer', ru: 1 + (i % 3), source: 'catalog' });
  }
  const rec = window.__rpal = { picks: [], drags: [], libraryCalls: [], templateCalls: [], doc: { devices: [] }, handle: null };
  let fails = params.get('fail') === '1' ? 1 : 0;
  const api = params.get('api') === '0' ? null : {
    base: '/',
    library: function (p) {
      rec.libraryCalls.push(p);
      if (fails > 0) { fails--; return Promise.reject(new Error('Library unavailable (harness ?fail=1)')); }
      if (realApi) return realApi.library(p);
      return Promise.resolve({ templates: templates });
    },
    template: function (id, project) {
      rec.templateCalls.push([id, project]);
      if (realApi) return realApi.template(id, project);
      const t = data.templates && data.templates[id];
      if (t) return Promise.resolve(JSON.parse(JSON.stringify(t)));
      const s = templates.filter(function (x) { return x.id === id; })[0];
      return s ? Promise.resolve(Object.assign({ ports: [] }, s)) : Promise.reject(new Error('template not found'));
    },
  };
  const log = document.getElementById('rpal-h-log');
  function note(text) {
    if (!log) return;
    log.insertBefore(h('li', null, text), log.firstChild);
  }
  const project = realApi ? (params.get('project') || '') : 'harness';
  const ctx = { api: api, project: project, vocab: realVocab || data.vocab || null, toast: function (m) { note('toast: ' + m); } };
  const host = document.getElementById('rpal-h-palette');
  rec.handle = mountRackPalette(host, ctx, {
    presets: data.presets || null,
    onPick: function (entry, template) {
      const r = core.deviceFromTemplate(rec.doc, template, { room: 'main', vocab: ctx.vocab });
      rec.doc.devices.push(r.ops[0].value);
      rec.picks.push({ id: entry.id, template: template.id, ports: (template.ports || []).length, device: r.id, devicePorts: r.ops[0].value.ports.length });
      note('Picked ' + entry.name + ' \u2192 device ' + r.id + ' (' + r.ops[0].value.ports.length + ' ports)');
    },
    onDragStart: function (entry, ev) {
      rec.drags.push({ id: entry.id, type: ev.type, pointerType: ev.pointerType });
      note('Drag ' + entry.name + ' (' + ev.pointerType + ')');
    },
  });
  if (params.get('smoke') === '1') {
    const t0 = Date.now();
    (function wait() {
      const ready = host.querySelector('.rpal-row, .fb-error, .fb-empty');
      if (!ready && Date.now() - t0 < 10000) { setTimeout(wait, 50); return; }
      setTimeout(function () {
        document.documentElement.setAttribute('data-smoke', JSON.stringify({ ready: !!ready, errors: errs }));
      }, 300);
    })();
  }
}

if (typeof document !== 'undefined' && document.body && document.body.hasAttribute('data-rpal-harness')) bootHarness();
