// Explorer (docs/ui-audit.md B.2 EXPLORER): a filterable, grouped list beside
// a page. Resizable 240–480px and collapsible to a 56px rail at md/lg (both
// persisted in localStorage fathom.ui.explorer.<key>); a slide-in drawer with a
// backdrop and focus trap at sm. The page goes into `handle.content`.
//
// Options beyond the B.2 block (all optional):
//   renderItem(item, base) -> Node   content of each li.ex-item instead of the
//                                    default link `base` (which it may decorate and
//                                    return); null/undefined keeps `base`. The li
//                                    (role=option, data-id, aria-selected) stays
//                                    the explorer's. Controls inside a row that must
//                                    not pick the item carry [data-ex-ignore]. To
//                                    put controls beside it, return a div.ex-item-row
//                                    holding `base` (a.ex-item-link) and the controls.
//   itemAttrs(item) -> {}            extra li attributes (class is added; role, id,
//                                    data-id, data-index, aria-selected are kept)
//   headSlot: Node                   shown between the head and the list (hints,
//                                    a legend); hidden in the collapsed rail
//   emptyText: string | (query, total) -> string
//                                    a string replaces "Nothing here yet" (no items);
//                                    a function decides both empty and no-match text
//   listId, contentLabel, storage, toolbar[{key, label, glyph, title, pressed, run}]
// Handle extras: setRail(rail) takes [{key, label, glyph, href, active}] or groups
// [{items: [...]}] (a separator between groups); setChips(chips) keeps the
// pressed chips that still exist; setHeadSlot(node); update(partial) applies
// items, selected, chips, rail, headSlot, toolbar, footer, emptyText, match,
// renderItem, itemAttrs and mobileLabel without a remount (key, title and glyph
// are fixed at mount).

import { h, on } from './dom.js';
import {
  RAIL_WIDTH, loadExplorer, saveExplorer, clampWidth, filterItems, groupItems, flattenGroups,
  nextIndex, resizeKey, dragWidth, explorerMode, footerText, openLabel,
} from './explorer-core.js';

let seq = 0;

const RESERVED_ATTRS = { role: 1, id: 1, 'data-id': 1, 'data-index': 1, 'aria-selected': 1 };

const FOCUSABLE = 'a[href]:not([tabindex="-1"]),button:not([disabled]):not([tabindex="-1"]),input:not([disabled]),' +
  'select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

function defaultStorage() {
  try {
    return window.localStorage;
  } catch (e) {
    return null;
  }
}

function str(v) {
  return v === undefined || v === null ? '' : String(v);
}

function visible(el) {
  return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
}

function focusEl(el) {
  if (!el || typeof el.focus !== 'function') return;
  try {
    el.focus({ preventScroll: true });
  } catch (e) {
    el.focus();
  }
}

function followHref(href) {
  if (!href) return;
  if (href.charAt(0) === '#') location.hash = href;
  else location.href = href;
}

function toolbarButton(t) {
  if (t && t.nodeType === 1) return t;
  const b = h('button', {
    type: 'button', class: 'ex-tool' + (t.class ? ' ' + t.class : ''), 'data-key': t.key || null,
    title: t.title || t.label || null, 'aria-label': t.glyph && t.label ? t.label : null,
    'aria-pressed': typeof t.pressed === 'boolean' ? String(t.pressed) : null,
  }, t.glyph ? [h('span', { 'aria-hidden': 'true', text: t.glyph })] : (t.label || ''));
  const run = t.run || t.onClick;
  if (typeof run === 'function') b.addEventListener('click', function (e) { run(e, b); });
  return b;
}

export function mountExplorer(el, opts) {
  const o = Object.assign({
    key: 'explorer', title: 'Items', glyph: '', items: [], chips: [], match: null, toolbar: [], footer: null,
    rail: [], selected: null, onSelect: null, mobileLabel: '', listId: '',
  }, opts || {});
  const uid = 'ex' + (++seq);
  const storage = Object.prototype.hasOwnProperty.call(o, 'storage') ? o.storage : defaultStorage();
  const state = loadExplorer(storage, o.key);
  let chips = Array.isArray(o.chips) ? o.chips : [];
  let activeChips = [];
  const offs = [];
  let items = Array.isArray(o.items) ? o.items.slice() : [];
  let selected = o.selected === undefined || o.selected === null ? null : String(o.selected);
  let query = '';
  let shown = [];
  let active = -1;
  let mode = explorerMode(window.innerWidth);
  let drawerOpen = false;
  let opener = null;
  let drag = null;
  let destroyed = false;

  const title = str(o.title);
  const search = h('input', {
    class: 'ex-search', type: 'search', placeholder: 'Filter ' + title.toLowerCase() + '\u2026',
    'aria-label': 'Filter ' + title, autocomplete: 'off', spellcheck: 'false', 'aria-controls': uid + '-list',
  });
  const chipBox = h('div', { class: 'ex-chips', role: 'group', 'aria-label': title + ' filters' });
  function buildChips() {
    chipBox.textContent = '';
    chipBox.hidden = !chips.length;
    chips.forEach(function (c) {
      chipBox.appendChild(h('button', {
        type: 'button', class: 'ex-chip', 'data-chip': c.key, 'aria-pressed': 'false',
      }, [h('span', { class: 'ex-chip-pill' }, [h('span', { class: 'ex-chip-label', text: str(c.label) }), h('span', { class: 'ex-chip-n' })])]));
    });
  }
  buildChips();
  const toolbar = h('div', { class: 'ex-toolbar' });
  function buildToolbar() {
    toolbar.textContent = '';
    const tools = (Array.isArray(o.toolbar) ? o.toolbar : []).map(toolbarButton);
    tools.forEach(function (t) { toolbar.appendChild(t); });
    toolbar.hidden = !tools.length;
  }
  buildToolbar();
  const closeBtn = h('button', { type: 'button', class: 'ex-close', 'aria-label': 'Close ' + title, title: 'Close' }, '\u00D7');
  const head = h('div', { class: 'ex-head' }, [
    h('div', { class: 'ex-titlebar' }, [
      h('h2', { class: 'ex-title' }, [o.glyph ? h('span', { class: 'ex-glyph', 'aria-hidden': 'true', text: o.glyph }) : null,
        h('span', { class: 'ex-title-text', text: title })]),
      closeBtn,
    ]),
    search, chipBox, toolbar,
  ]);
  const slot = h('div', { class: 'ex-slot' });
  const list = h('ul', { class: 'ex-list', id: o.listId || uid + '-list', role: 'listbox', 'aria-label': title, tabindex: '0' });
  const empty = h('p', { class: 'ex-empty', role: 'status', hidden: true });
  const rail = h('nav', { class: 'ex-rail', 'aria-label': title });
  const count = h('span', { class: 'ex-count', 'aria-live': 'polite' });
  const collapseBtn = h('button', { type: 'button', class: 'ex-collapse', 'aria-controls': uid + '-side' });
  const foot = h('div', { class: 'ex-foot' }, [count, collapseBtn]);
  const side = h('aside', { class: 'ex-side', id: uid + '-side', 'aria-label': title }, [head, slot, list, empty, rail, foot]);

  function setSlot(node) {
    slot.textContent = '';
    if (node && node.nodeType) slot.appendChild(node);
    slot.hidden = !slot.firstChild;
  }
  setSlot(o.headSlot);
  const resizer = h('div', {
    class: 'ex-resizer', role: 'separator', 'aria-orientation': 'vertical', 'aria-valuemin': '240',
    'aria-valuemax': '480', 'aria-valuenow': String(state.w), tabindex: '0', 'aria-label': 'Resize ' + title,
    'aria-controls': uid + '-side', title: 'Drag to resize \u00B7 double-click to reset',
  });
  const openBtn = h('button', {
    type: 'button', class: 'ex-open', 'aria-controls': uid + '-side', 'aria-expanded': 'false', 'aria-haspopup': 'dialog',
  });
  const page = h('div', { class: 'ex-page' });
  const content = h('section', { class: 'ex-content', 'aria-label': o.contentLabel || null }, [openBtn, page]);
  const backdrop = h('div', { class: 'ex-backdrop', hidden: true });
  const root = h('div', { class: 'ex-root', 'data-explorer': o.key }, [side, resizer, content, backdrop]);

  function save() {
    saveExplorer(storage, o.key, state);
  }

  function applyWidth() {
    root.style.setProperty('--ex-w', state.w + 'px');
    resizer.setAttribute('aria-valuenow', String(state.w));
  }

  function applyCollapsed() {
    root.classList.toggle('ex-collapsed', state.c);
    collapseBtn.setAttribute('aria-expanded', String(!state.c));
    collapseBtn.setAttribute('aria-label', (state.c ? 'Expand ' : 'Collapse ') + title);
    collapseBtn.title = state.c ? 'Expand' : 'Collapse';
    collapseBtn.textContent = state.c ? '\u00BB' : '\u00AB';
  }

  function applyMode() {
    root.setAttribute('data-mode', mode);
    if (mode === 'drawer' && drawerOpen) {
      side.setAttribute('role', 'dialog');
      side.setAttribute('aria-modal', 'true');
    } else {
      side.removeAttribute('role');
      side.removeAttribute('aria-modal');
    }
  }

  function renderRail() {
    rail.textContent = '';
    if (o.glyph) rail.appendChild(h('span', { class: 'ex-rail-glyph', 'aria-hidden': 'true', title: title, text: o.glyph }));
    const flat = [];
    (Array.isArray(o.rail) ? o.rail : []).forEach(function (r) {
      if (!r) return;
      if (!Array.isArray(r.items)) { flat.push(r); return; }
      if (flat.length && r.items.length) flat.push(null);
      r.items.forEach(function (x) { if (x) flat.push(x); });
    });
    flat.forEach(function (r) {
      if (r === null) { rail.appendChild(h('span', { class: 'ex-rail-sep', role: 'separator' })); return; }
      rail.appendChild(h('a', {
        class: 'ex-rail-item', href: r.href || null, 'data-key': r.key || null, title: r.label || null,
        'aria-label': r.label || null, 'aria-current': r.active ? 'page' : null,
      }, h('span', { 'aria-hidden': 'true', text: str(r.glyph || (r.label ? r.label.charAt(0) : '\u2022')) })));
    });
  }

  function chipCounts() {
    Array.prototype.forEach.call(chipBox.children, function (b) {
      const key = b.getAttribute('data-chip');
      const c = chips.filter(function (x) { return x.key === key; })[0];
      const n = c && typeof c.test === 'function' ? items.filter(function (it) { return !!c.test(it); }).length : 0;
      b.querySelector('.ex-chip-n').textContent = String(n);
      b.setAttribute('aria-pressed', String(activeChips.indexOf(key) !== -1));
    });
  }

  function itemEl(item, i) {
    const id = str(item.id);
    const depth = Math.max(0, Math.min(8, Number(item.depth) || 0));
    const a = h('a', { class: 'ex-item-link', href: item.href || null, tabindex: '-1', draggable: 'false',
      style: depth ? { paddingLeft: (12 + depth * 14) + 'px' } : null }, [
      item.glyph ? h('span', { class: 'ex-item-glyph', 'aria-hidden': 'true', text: str(item.glyph) }) : null,
      h('span', { class: 'ex-item-text' }, [
        h('span', { class: 'ex-item-label', text: str(item.label || id) }),
        item.sub ? h('span', { class: 'ex-item-sub', text: str(item.sub) }) : null,
      ]),
      item.badge !== undefined && item.badge !== null && item.badge !== '' ? h('span', { class: 'ex-badge', text: str(item.badge) }) : null,
    ]);
    let content = a;
    if (typeof o.renderItem === 'function') {
      const r = o.renderItem(item, a);
      if (r && r.nodeType) content = r;
    }
    const li = h('li', {
      class: 'ex-item', role: 'option', id: uid + '-o' + i, 'data-id': id, 'data-index': String(i),
      'aria-selected': String(selected !== null && id === selected),
    }, content);
    if (typeof o.itemAttrs === 'function') applyAttrs(li, o.itemAttrs(item));
    return li;
  }

  function applyAttrs(li, attrs) {
    if (!attrs || typeof attrs !== 'object') return;
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (RESERVED_ATTRS[k] || v === undefined || v === null || v === false) return;
      if (k === 'class') String(v).split(/\s+/).forEach(function (c) { if (c) li.classList.add(c); });
      else if (k === 'style' && typeof v === 'object') Object.keys(v).forEach(function (p) { li.style.setProperty(p.indexOf('-') >= 0 ? p : p.replace(/[A-Z]/g, function (c) { return '-' + c.toLowerCase(); }), String(v[p])); });
      else li.setAttribute(k, v === true ? '' : String(v));
    });
  }

  function emptyMessage() {
    if (typeof o.emptyText === 'function') {
      const t = o.emptyText(query, items.length);
      if (t !== undefined && t !== null) return str(t);
    }
    if (!items.length) return typeof o.emptyText === 'string' && o.emptyText ? o.emptyText : 'Nothing here yet';
    return 'No matches' + (query ? ' for \u201C' + query + '\u201D' : '');
  }

  function renderList() {
    const groups = groupItems(filterItems(items, query, activeChips, chips, o.match));
    const named = groups.some(function (g) { return g.group !== ''; });
    shown = flattenGroups(groups);
    const keep = list.scrollTop;
    list.textContent = '';
    let i = 0;
    groups.forEach(function (g) {
      if (named) {
        list.appendChild(h('li', { class: 'ex-group', role: 'presentation' }, [
          h('span', { class: 'ex-group-label', text: g.group || 'Other' }),
          h('span', { class: 'ex-group-n', text: String(g.items.length) }),
        ]));
      }
      g.items.forEach(function (it) { list.appendChild(itemEl(it, i++)); });
    });
    list.scrollTop = keep;
    if (active >= shown.length) active = shown.length - 1;
    markActive(false);
    empty.hidden = shown.length > 0;
    empty.textContent = emptyMessage();
    count.textContent = footerText(shown.length, items.length, o.footer);
    openBtn.textContent = openLabel(o.mobileLabel || title, items.length);
    chipCounts();
  }

  function liAt(i) {
    return i >= 0 ? list.querySelector('#' + uid + '-o' + i) : null;
  }

  function ensureVisible(li) {
    if (!li || !list.clientHeight) return;
    const hdr = list.querySelector('.ex-group');
    const pad = hdr ? hdr.offsetHeight : 0;
    const top = li.offsetTop;
    const bottom = top + li.offsetHeight;
    if (top - pad < list.scrollTop) list.scrollTop = Math.max(0, top - pad);
    else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight;
  }

  function markActive(scroll) {
    const prev = list.querySelector('.ex-active');
    if (prev) prev.classList.remove('ex-active');
    const li = liAt(active);
    if (li) {
      li.classList.add('ex-active');
      list.setAttribute('aria-activedescendant', li.id);
      if (scroll) ensureVisible(li);
    } else {
      list.removeAttribute('aria-activedescendant');
    }
  }

  function selectedIndex() {
    if (selected === null) return -1;
    for (let i = 0; i < shown.length; i++) if (str(shown[i].id) === selected) return i;
    return -1;
  }

  function activate(i, ev) {
    const item = shown[i];
    if (!item) return;
    active = i;
    markActive(true);
    if (mode === 'drawer' && drawerOpen) close();
    if (typeof o.onSelect === 'function') o.onSelect(item, ev);
    else followHref(item.href);
  }

  function setQuery(v) {
    query = v;
    active = -1;
    renderList();
  }

  // ---- drawer (sm)

  function open() {
    if (destroyed || mode !== 'drawer' || drawerOpen) return;
    drawerOpen = true;
    const ae = document.activeElement;
    opener = ae && ae !== document.body && !side.contains(ae) ? ae : openBtn;
    root.classList.add('ex-is-open');
    backdrop.hidden = false;
    openBtn.setAttribute('aria-expanded', 'true');
    applyMode();
    focusEl(search);
    const li = liAt(selectedIndex());
    if (li) ensureVisible(li);
  }

  function close(opts) {
    if (!drawerOpen) return;
    drawerOpen = false;
    const hadFocus = side.contains(document.activeElement);
    root.classList.remove('ex-is-open');
    backdrop.hidden = true;
    openBtn.setAttribute('aria-expanded', 'false');
    applyMode();
    if (hadFocus && !(opts && opts.focus === false)) {
      const back = opener && document.contains(opener) && visible(opener) ? opener : openBtn;
      focusEl(back);
    }
    opener = null;
  }

  function trapTab(e) {
    const els = Array.prototype.filter.call(side.querySelectorAll(FOCUSABLE), visible);
    if (!els.length) return;
    const first = els[0];
    const last = els[els.length - 1];
    const ae = document.activeElement;
    if (e.shiftKey && (ae === first || !side.contains(ae))) {
      e.preventDefault();
      focusEl(last);
    } else if (!e.shiftKey && (ae === last || !side.contains(ae))) {
      e.preventDefault();
      focusEl(first);
    }
  }

  function relayout() {
    const next = explorerMode(window.innerWidth);
    if (next === mode) return;
    if (drawerOpen) close({ focus: false });
    mode = next;
    applyMode();
  }

  // ---- events

  offs.push(on(search, 'input', function () { setQuery(search.value); }));
  offs.push(on(search, 'keydown', function (e) {
    if (e.key === 'ArrowDown' && shown.length) {
      e.preventDefault();
      active = nextIndex(shown.length, -1, 'ArrowDown');
      focusEl(list);
      markActive(true);
    } else if (e.key === 'Enter' && shown.length === 1) {
      e.preventDefault();
      activate(0, e);
    } else if (e.key === 'Escape' && search.value) {
      e.preventDefault();
      e.stopPropagation();
      search.value = '';
      setQuery('');
    }
  }));

  offs.push(on(chipBox, 'click', function (e) {
    const b = e.target.closest('.ex-chip');
    if (!b) return;
    const key = b.getAttribute('data-chip');
    const at = activeChips.indexOf(key);
    if (at === -1) activeChips.push(key);
    else activeChips.splice(at, 1);
    active = -1;
    renderList();
  }));

  offs.push(on(list, 'keydown', function (e) {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      active = nextIndex(shown.length, active, e.key);
      markActive(true);
    } else if (e.key === 'Enter' || e.key === ' ') {
      if (active < 0) return;
      e.preventDefault();
      activate(active, e);
    } else if (e.key.length === 1 && e.key !== ' ') {
      e.preventDefault();
      focusEl(search);
      search.value += e.key;
      setQuery(search.value);
    }
  }));
  offs.push(on(list, 'focus', function () {
    if (active < 0 && shown.length) active = Math.max(0, selectedIndex());
    markActive(true);
  }));
  offs.push(on(list, 'click', function (e) {
    const li = e.target.closest('.ex-item');
    if (!li || !list.contains(li)) return;
    if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const skip = e.target.closest('[data-ex-ignore]');
    if (skip && li.contains(skip)) return;
    e.preventDefault();
    focusEl(list);
    activate(Number(li.getAttribute('data-index')), e);
  }));

  offs.push(on(collapseBtn, 'click', function () { handle.setCollapsed(!state.c); }));
  offs.push(on(openBtn, 'click', function () { open(); }));
  offs.push(on(closeBtn, 'click', function () { close(); }));
  offs.push(on(backdrop, 'click', function () { close(); }));
  offs.push(on(side, 'keydown', function (e) {
    if (!drawerOpen) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === 'Tab') {
      trapTab(e);
    }
  }));

  offs.push(on(resizer, 'pointerdown', function (e) {
    if (e.button !== 0 || state.c) return;
    e.preventDefault();
    drag = { id: e.pointerId, x: e.clientX, w: state.w };
    try { resizer.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointers */ }
    root.classList.add('ex-resizing');
  }));
  offs.push(on(resizer, 'pointermove', function (e) {
    if (!drag || e.pointerId !== drag.id) return;
    state.w = dragWidth(drag.w, drag.x, e.clientX);
    applyWidth();
  }));
  function endDrag(e) {
    if (!drag || (e && e.pointerId !== drag.id)) return;
    drag = null;
    root.classList.remove('ex-resizing');
    save();
  }
  offs.push(on(resizer, 'pointerup', endDrag));
  offs.push(on(resizer, 'pointercancel', endDrag));
  offs.push(on(resizer, 'lostpointercapture', endDrag));
  offs.push(on(resizer, 'keydown', function (e) {
    const w = resizeKey(state.w, e.key);
    if (w === null) return;
    e.preventDefault();
    handle.setWidth(w);
  }));
  offs.push(on(resizer, 'dblclick', function () { handle.setWidth(clampWidth()); }));
  offs.push(on(window, 'resize', relayout));

  const handle = {
    root: root,
    side: side,
    list: list,
    content: page,
    search: search,
    setItems: function (next) {
      items = Array.isArray(next) ? next.slice() : [];
      renderList();
    },
    setRail: function (next) {
      o.rail = Array.isArray(next) ? next : [];
      renderRail();
    },
    setChips: function (next) {
      chips = Array.isArray(next) ? next.filter(Boolean) : [];
      activeChips = activeChips.filter(function (k) { return chips.some(function (c) { return c.key === k; }); });
      buildChips();
      active = -1;
      renderList();
    },
    setHeadSlot: setSlot,
    update: function (partial) {
      const p = partial || {};
      const has = function (k) { return Object.prototype.hasOwnProperty.call(p, k); };
      ['footer', 'emptyText', 'match', 'renderItem', 'itemAttrs', 'mobileLabel'].forEach(function (k) { if (has(k)) o[k] = p[k]; });
      if (has('toolbar')) { o.toolbar = p.toolbar; buildToolbar(); }
      if (has('headSlot')) setSlot(p.headSlot);
      if (has('rail')) handle.setRail(p.rail);
      if (has('chips')) handle.setChips(p.chips);
      if (has('items')) items = Array.isArray(p.items) ? p.items.slice() : [];
      renderList();
      if (has('selected')) handle.setSelected(p.selected);
    },
    setSelected: function (id) {
      const next = id === undefined || id === null ? null : String(id);
      const changed = next !== selected;
      selected = next;
      Array.prototype.forEach.call(list.querySelectorAll('.ex-item'), function (li) {
        li.setAttribute('aria-selected', String(selected !== null && li.getAttribute('data-id') === selected));
      });
      const at = selectedIndex();
      if (at >= 0) ensureVisible(liAt(at));
      if (changed) close();
    },
    open: open,
    close: close,
    isOpen: function () { return drawerOpen; },
    mode: function () { return mode; },
    isCollapsed: function () { return state.c; },
    width: function () { return state.w; },
    setCollapsed: function (c) {
      state.c = !!c;
      applyCollapsed();
      save();
    },
    setWidth: function (px) {
      state.w = clampWidth(px);
      applyWidth();
      save();
    },
    relayout: relayout,
    destroy: function () {
      if (destroyed) return;
      close({ focus: false });
      destroyed = true;
      offs.forEach(function (off) { off(); });
      if (root.parentNode) root.parentNode.removeChild(root);
    },
  };

  applyWidth();
  applyCollapsed();
  applyMode();
  renderRail();
  renderList();
  el.appendChild(root);
  const at = selectedIndex();
  if (at >= 0) ensureVisible(liAt(at));
  root.style.setProperty('--ex-rail', RAIL_WIDTH + 'px');
  return handle;
}
