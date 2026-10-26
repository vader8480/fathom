// Entity page header (docs/ui-audit.md D5, B.2 ENTITY): sticky title row with
// status, badges, facts, actions + ⋯ overflow menu, optional thumbnail and URL
// tabs. Compact (.eh--compact) once the sentinel above it leaves the scroller,
// and always at sm. The layout comes from router-core's layoutFor (D3).
// The header and its sentinel are prepended to `el`; the page content must
// follow inside `el` too, since `position: sticky` only sticks within its parent.
//
//   const eh = mountEntityHeader(el, {kind, id, glyph, title, subtitle, status, facts, badges,
//     actions, overflow, tabs, activeTab, thumb, onTab});
//   eh.update(partial); eh.setTab(key); eh.destroy();

import { h, on } from './dom.js';
import { layoutFor } from './router-core.js';

const LEVELS = { ok: 1, warn: 1, err: 1, muted: 1 };
const MORE = '\u22EF';
let seq = 0;

function arr(v) {
  return Array.isArray(v) ? v.filter(Boolean) : [];
}

function txt(v) {
  return v === undefined || v === null ? '' : String(v);
}

function level(v) {
  return LEVELS[v] ? v : 'muted';
}

function normalize(o) {
  const n = Object.assign({ kind: '', id: '', glyph: '', title: '', subtitle: '', status: null, facts: [], badges: [],
    actions: [], overflow: [], tabs: [], activeTab: '', thumb: null, onTab: null }, o || {});
  ['facts', 'badges', 'actions', 'overflow', 'tabs'].forEach(function (k) { n[k] = arr(n[k]); });
  n.tabs = n.tabs.map(function (t) { return typeof t === 'string' ? { key: t, label: t } : t; });
  if (typeof n.status === 'string') n.status = n.status ? { label: n.status, level: 'muted' } : null;
  return n;
}

function currentLayout() {
  return layoutFor(typeof window !== 'undefined' ? window.innerWidth : 1280);
}

function scrollParent(el) {
  for (let p = el; p && p.nodeType === 1 && p !== document.body && p !== document.documentElement; p = p.parentElement) {
    if (/(auto|scroll|overlay)/.test(getComputedStyle(p).overflowY)) return p;
  }
  return null;
}

function modified(e) {
  return e.button > 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey;
}

export function mountEntityHeader(host, options) {
  const uid = 'eh-' + (++seq);
  let o = normalize(options);
  let layout = currentLayout();
  let stuck = false;
  let factsOpen = false;
  let destroyed = false;
  let io = null;
  let scroller = null;
  let actionsEl = null;
  let moreBtn = null;
  let menu = null;
  let menuOffs = [];
  const offs = [];

  const sentinel = h('div', { class: 'eh-sentinel', 'aria-hidden': 'true' });
  const header = h('header', { class: 'eh' });
  host.insertBefore(sentinel, host.firstChild);
  host.insertBefore(header, sentinel.nextSibling);

  function compact() {
    return layout === 'sm' || stuck;
  }

  function applyMode() {
    header.setAttribute('data-layout', layout);
    header.classList.toggle('eh--compact', compact());
    header.classList.toggle('eh--stuck', stuck);
  }

  // ------------------------------------------------------------ parts

  function badge(b) {
    const pill = h('span', { class: 'eh-badge-pill' }, txt(b.label));
    const cls = 'eh-badge eh-' + level(b.level);
    if (typeof b.onClick !== 'function') return h('span', { class: cls, title: b.title || null }, pill);
    return h('button', { type: 'button', class: cls, title: b.title || null, onclick: function (e) { b.onClick(b, e); } }, pill);
  }

  function factValue(f) {
    const v = txt(f.value);
    return f.href ? h('a', { href: f.href }, v) : v;
  }

  function factList() {
    return h('dl', { class: 'eh-facts' }, o.facts.map(function (f) {
      return h('div', { class: 'eh-fact', 'data-fact': f.key || null }, [h('dt', null, txt(f.label)), h('dd', null, factValue(f))]);
    }));
  }

  function factsBlock() {
    if (!o.facts.length) return null;
    if (layout !== 'sm') return factList();
    const d = h('details', { class: 'eh-facts-more', open: factsOpen }, [
      h('summary', null, ['Details', h('span', { class: 'eh-count' }, String(o.facts.length))]),
      factList(),
    ]);
    d.addEventListener('toggle', function () { factsOpen = d.open; });
    return d;
  }

  function thumbBlock() {
    const t = o.thumb;
    if (!t || !t.src) return null;
    const img = h('img', { src: t.src, alt: txt(t.alt), loading: 'lazy', decoding: 'async' });
    return t.href ? h('a', { class: 'eh-thumb', href: t.href }, img) : h('div', { class: 'eh-thumb' }, img);
  }

  function tabEl(t) {
    const sel = t.key === o.activeTab;
    const count = t.count === undefined || t.count === null || t.count === '' ? null : h('span', { class: 'eh-count' }, String(t.count));
    const a = h('a', { class: 'eh-tab', role: 'tab', 'aria-selected': sel ? 'true' : 'false', tabindex: sel ? '0' : '-1',
      'data-tab': t.key, href: t.href || null }, [h('span', { class: 'eh-tab-label' }, txt(t.label || t.key)), count]);
    a.addEventListener('click', function (e) {
      if (modified(e)) return;
      if (typeof o.onTab === 'function') o.onTab(t.key, e);
      if (!t.href) e.preventDefault();
      if (!e.defaultPrevented || !t.href) setTab(t.key);
    });
    return a;
  }

  function tabsBlock() {
    if (!o.tabs.length) return null;
    const nav = h('nav', { class: 'eh-tabs', role: 'tablist', 'aria-label': (o.title ? o.title + ' ' : '') + 'sections' }, o.tabs.map(tabEl));
    nav.addEventListener('keydown', function (e) {
      const tabs = Array.prototype.slice.call(nav.querySelectorAll('.eh-tab'));
      const i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      let j = -1;
      if (e.key === 'ArrowRight') j = (i + 1) % tabs.length;
      else if (e.key === 'ArrowLeft') j = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === 'Home') j = 0;
      else if (e.key === 'End') j = tabs.length - 1;
      if (j < 0) return;
      e.preventDefault();
      tabs.forEach(function (t, k) { t.setAttribute('tabindex', k === j ? '0' : '-1'); });
      tabs[j].focus();
      revealTab(tabs[j]);
    });
    return nav;
  }

  function revealTab(tab) {
    const nav = tab && tab.parentNode;
    if (!nav || nav.scrollWidth <= nav.clientWidth) return;
    const left = tab.offsetLeft;
    const right = left + tab.offsetWidth;
    if (left < nav.scrollLeft) nav.scrollLeft = Math.max(0, left - 8);
    else if (right > nav.scrollLeft + nav.clientWidth) nav.scrollLeft = right - nav.clientWidth + 8;
  }

  // ------------------------------------------------------------ actions and menu

  function runItem(item, e) {
    if (item.disabled) return;
    if (typeof item.run === 'function') item.run(item, e);
  }

  function actionEl(a) {
    const cls = 'eh-action' + (a.primary ? ' eh-primary primary' : '') + (a.danger ? ' danger' : '');
    if (a.href) return h('a', { class: cls, href: a.href, target: a.target || null, rel: a.target ? 'noopener' : null, 'data-action': a.key || null, title: a.title || null }, txt(a.label));
    return h('button', { type: 'button', class: cls, 'data-action': a.key || null, title: a.title || null, disabled: !!a.disabled,
      onclick: function (e) { runItem(a, e); } }, txt(a.label));
  }

  function menuItemEl(item) {
    if (item.separator) return h('li', { class: 'eh-sep', role: 'separator' });
    const cls = 'eh-menu-item' + (item.danger ? ' danger' : '');
    const attrs = { class: cls, role: 'menuitem', tabindex: '-1', 'data-action': item.key || null, title: item.title || null };
    let el;
    if (item.href) {
      el = h('a', Object.assign(attrs, { href: item.href, target: item.target || null, rel: item.target ? 'noopener' : null }), txt(item.label));
      el.addEventListener('click', function () { closeMenu(false); });
    } else {
      el = h('button', Object.assign(attrs, { type: 'button', disabled: !!item.disabled }), txt(item.label));
      el.addEventListener('click', function (e) { closeMenu(true); runItem(item, e); });
    }
    return h('li', { role: 'none' }, el);
  }

  function menuItems() {
    const moved = o.actions.filter(function (a) { return layout === 'sm' || (stuck && !a.primary); });
    const items = moved.slice();
    if (moved.length && o.overflow.length) items.push({ separator: true });
    return items.concat(o.overflow);
  }

  function menuButtons() {
    return menu ? Array.prototype.slice.call(menu.querySelectorAll('.eh-menu-item:not([disabled])')) : [];
  }

  function focusItem(i) {
    const items = menuButtons();
    if (!items.length) return;
    items[(i + items.length) % items.length].focus();
  }

  function openMenu(index) {
    if (!menu || !menu.hidden) {
      if (menu) focusItem(index);
      return;
    }
    menu.hidden = false;
    moreBtn.setAttribute('aria-expanded', 'true');
    header.classList.add('eh--menu');
    menuOffs.push(on(document, 'pointerdown', function (e) {
      if (!menu.contains(e.target) && e.target !== moreBtn && !moreBtn.contains(e.target)) closeMenu(false);
    }, true));
    focusItem(index);
  }

  function closeMenu(returnFocus) {
    menuOffs.forEach(function (off) { off(); });
    menuOffs = [];
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    moreBtn.setAttribute('aria-expanded', 'false');
    header.classList.remove('eh--menu');
    if (returnFocus) moreBtn.focus();
  }

  function renderActions() {
    if (!actionsEl) return;
    closeMenu(false);
    actionsEl.textContent = '';
    moreBtn = null;
    menu = null;
    o.actions.forEach(function (a) {
      if (layout === 'sm' || (stuck && !a.primary)) return;
      actionsEl.appendChild(actionEl(a));
    });
    const items = menuItems();
    if (!items.length) return;
    menu = h('ul', { class: 'eh-menu', role: 'menu', id: uid + '-menu', 'aria-label': 'More actions', hidden: true }, items.map(menuItemEl));
    moreBtn = h('button', { type: 'button', class: 'eh-more', 'aria-haspopup': 'menu', 'aria-expanded': 'false', 'aria-controls': uid + '-menu',
      'aria-label': 'More actions', title: 'More actions' }, MORE);
    moreBtn.addEventListener('click', function () {
      if (menu.hidden) openMenu(0); else closeMenu(true);
    });
    moreBtn.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); openMenu(0); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); openMenu(-1); }
      else if (e.key === 'Escape' && !menu.hidden) { e.preventDefault(); e.stopPropagation(); closeMenu(true); }
    });
    menu.addEventListener('keydown', function (e) {
      const items2 = menuButtons();
      const i = items2.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); focusItem(i + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); focusItem(i - 1); }
      else if (e.key === 'Home') { e.preventDefault(); focusItem(0); }
      else if (e.key === 'End') { e.preventDefault(); focusItem(-1); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu(true); }
      else if (e.key === 'Tab') closeMenu(false);
    });
    actionsEl.appendChild(h('div', { class: 'eh-more-wrap' }, [moreBtn, menu]));
  }

  // ------------------------------------------------------------ render

  function render() {
    if (destroyed) return;
    closeMenu(false);
    header.textContent = '';
    header.setAttribute('data-entity', o.kind || '');
    header.setAttribute('data-id', o.id || '');
    applyMode();
    const st = o.status && o.status.label ? h('span', { class: 'eh-status eh-' + level(o.status.level) }, txt(o.status.label)) : null;
    const main = h('div', { class: 'eh-main' }, [
      o.glyph ? h('span', { class: 'eh-glyph', 'aria-hidden': 'true' }, txt(o.glyph)) : null,
      h('div', { class: 'eh-titles' }, [
        h('h1', { class: 'eh-title', title: txt(o.title) }, txt(o.title)),
        o.subtitle ? h('span', { class: 'eh-subtitle' }, txt(o.subtitle)) : null,
      ]),
      st,
      o.badges.length ? h('span', { class: 'eh-badges' }, o.badges.map(badge)) : null,
    ]);
    actionsEl = h('div', { class: 'eh-actions' });
    header.appendChild(h('div', { class: 'eh-bar' }, [main, actionsEl]));
    const facts = factsBlock();
    const thumb = thumbBlock();
    if (facts || thumb) header.appendChild(h('div', { class: 'eh-body' }, [facts, thumb]));
    const tabs = tabsBlock();
    if (tabs) header.appendChild(tabs);
    renderActions();
    revealActive();
  }

  function revealActive() {
    const tab = header.querySelector('.eh-tab[aria-selected="true"]');
    if (tab) revealTab(tab);
  }

  function setStuck(v) {
    if (v === stuck || destroyed) return;
    stuck = v;
    applyMode();
    renderActions();
  }

  function checkStuck() {
    const top = scroller ? scroller.getBoundingClientRect().top : 0;
    setStuck(sentinel.getBoundingClientRect().bottom <= top);
  }

  function observe() {
    if (destroyed || io) return;
    scroller = scrollParent(host);
    if (typeof IntersectionObserver === 'function') {
      io = new IntersectionObserver(function (entries) {
        const e = entries[entries.length - 1];
        const top = e.rootBounds ? e.rootBounds.top : 0;
        setStuck(!e.isIntersecting && e.boundingClientRect.top < top);
      }, { root: scroller, threshold: 0 });
      io.observe(sentinel);
    } else {
      io = { disconnect: on(scroller || window, 'scroll', checkStuck, { passive: true }) };
      checkStuck();
    }
  }

  function onResize() {
    const next = currentLayout();
    if (next === layout) return;
    layout = next;
    render();
  }

  render();
  offs.push(on(window, 'resize', onResize));
  if (host.isConnected) observe();
  else {
    const t = setTimeout(observe, 0);
    offs.push(function () { clearTimeout(t); });
  }

  function setTab(key) {
    o.activeTab = key;
    Array.prototype.forEach.call(header.querySelectorAll('.eh-tab'), function (t) {
      const sel = t.getAttribute('data-tab') === key;
      t.setAttribute('aria-selected', sel ? 'true' : 'false');
      t.setAttribute('tabindex', sel ? '0' : '-1');
    });
    revealActive();
  }

  return {
    el: header,
    update: function (partial) {
      o = normalize(Object.assign({}, o, partial || {}));
      render();
    },
    setTab: setTab,
    isCompact: compact,
    destroy: function () {
      if (destroyed) return;
      closeMenu(false);
      destroyed = true;
      if (io) io.disconnect();
      offs.forEach(function (off) { off(); });
      if (header.parentNode) header.parentNode.removeChild(header);
      if (sentinel.parentNode) sentinel.parentNode.removeChild(sentinel);
    },
  };
}
