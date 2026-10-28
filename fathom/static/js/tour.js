// First-run tour (FR-UX-16): pure-DOM coachmarks. A positioned highlight box
// with a huge box-shadow dims the page and leaves a cut-out around the target;
// a card with title, text, step counter, Back / Next / Done and Skip tour sits
// next to it (a bottom sheet at sm). Esc closes, focus stays in the card, the
// layout follows resize and scroll. A step whose target is missing or hidden is
// skipped. The shell (app.js) decides when to run it and stores the result under
// fathom.ui.tour (§6.14).
//
//   const t = startTour([{target: '#app-search', title, text}, {target: null, …}], {onClose});
//   t.next(); t.back(); t.close('skip'); t.done.then(function (r) { /* {done, reason, step} */ });

import { h, on } from './dom.js';

export const TOUR_KEY = 'fathom.ui.tour';
const PAD = 6;
const GAP = 12;
const EDGE = 8;
const FOCUSABLE = 'button:not([disabled]),[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

function rendered(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  if (!(r.width > 0 && r.height > 0)) return false;
  const cs = window.getComputedStyle(el);
  return cs.visibility !== 'hidden' && cs.display !== 'none';
}

// First rendered element of a selector list, or null.
export function findTarget(selector, root) {
  if (!selector) return null;
  let all;
  try { all = (root || document).querySelectorAll(selector); } catch (e) { return null; }
  for (let i = 0; i < all.length; i++) if (rendered(all[i])) return all[i];
  return null;
}

// A step is shown when it has no target (centered card) or its target is rendered.
export function stepVisible(step, root) {
  if (!step) return false;
  if (!step.target) return true;
  return !!findTarget(step.target, root);
}

// Where the card goes for a target rect `t` and card size (w, h) inside a viewport (W, H):
// below when it fits, else above, else beside; clamped to the viewport edges. Pure.
export function placeCard(t, w, h, W, H) {
  if (!t) return { top: Math.max(EDGE, Math.round((H - h) / 2)), left: Math.max(EDGE, Math.round((W - w) / 2)), side: 'center' };
  const clampX = function (x) { return Math.max(EDGE, Math.min(W - w - EDGE, x)); };
  const clampY = function (y) { return Math.max(EDGE, Math.min(H - h - EDGE, y)); };
  if (t.bottom + GAP + h <= H - EDGE) return { top: Math.round(t.bottom + GAP), left: clampX(Math.round(t.left)), side: 'below' };
  if (t.top - GAP - h >= EDGE) return { top: Math.round(t.top - GAP - h), left: clampX(Math.round(t.left)), side: 'above' };
  if (t.right + GAP + w <= W - EDGE) return { top: clampY(Math.round(t.top)), left: Math.round(t.right + GAP), side: 'right' };
  if (t.left - GAP - w >= EDGE) return { top: clampY(Math.round(t.top)), left: Math.round(t.left - GAP - w), side: 'left' };
  return { top: clampY(Math.round(t.bottom + GAP)), left: clampX(Math.round(t.left)), side: 'over' };
}

export function startTour(steps, opts) {
  opts = opts || {};
  steps = (steps || []).filter(function (s) { return s && (s.title || s.text); });
  const root = opts.root || document.body;
  const opener = document.activeElement;
  let cur = -1;
  let closed = false;
  let resolveDone = null;
  const done = new Promise(function (res) { resolveDone = res; });
  const offs = [];
  const ids = 'tour-' + Math.random().toString(36).slice(2, 8);

  const backdrop = h('div', { class: 'tour-backdrop', 'data-tour': 'backdrop' });
  const hl = h('div', { class: 'tour-hl', 'aria-hidden': 'true' });
  const title = h('h2', { class: 'tour-title', id: ids + '-title' });
  const text = h('p', { class: 'tour-text', id: ids + '-text' });
  const count = h('span', { class: 'tour-count muted' });
  const skip = h('button', { type: 'button', class: 'ghost tour-skip', onclick: function () { close('skip'); } }, 'Skip tour');
  const back = h('button', { type: 'button', class: 'tour-back', onclick: function () { api.back(); } }, 'Back');
  const next = h('button', { type: 'button', class: 'primary tour-next', onclick: function () { api.next(); } }, 'Next');
  const card = h('div', {
    class: 'tour-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': ids + '-title', 'aria-describedby': ids + '-text',
    'data-tour': 'card', tabindex: '-1',
  }, [
    h('div', { class: 'tour-head' }, [count, h('button', { type: 'button', class: 'icon ghost tour-close', 'aria-label': 'Close tour', onclick: function () { close('close'); } }, '\u00d7')]),
    title, text,
    h('div', { class: 'tour-foot' }, [skip, h('span', { class: 'grow' }), back, next]),
  ]);

  function visibleIndexes() {
    const out = [];
    steps.forEach(function (s, i) { if (stepVisible(s, document)) out.push(i); });
    return out;
  }

  function sheet() { return window.innerWidth < 700; }

  function layout() {
    if (closed || cur < 0) return;
    const step = steps[cur];
    const el = step.target ? findTarget(step.target, document) : null;
    const W = window.innerWidth;
    const H = window.innerHeight;
    if (el) {
      const r = el.getBoundingClientRect();
      const t = { top: r.top - PAD, left: r.left - PAD, right: r.right + PAD, bottom: r.bottom + PAD };
      hl.hidden = false;
      hl.style.top = Math.round(t.top) + 'px';
      hl.style.left = Math.round(t.left) + 'px';
      hl.style.width = Math.round(t.right - t.left) + 'px';
      hl.style.height = Math.round(t.bottom - t.top) + 'px';
      card.setAttribute('data-target', step.target);
      if (!sheet()) {
        card.classList.remove('tour-card--sheet');
        const p = placeCard(t, card.offsetWidth, card.offsetHeight, W, H);
        card.style.top = p.top + 'px';
        card.style.left = p.left + 'px';
        card.setAttribute('data-side', p.side);
      }
    } else {
      // no target: a zero-size box in the middle, so the shadow dims everything
      hl.hidden = false;
      hl.style.top = Math.round(H / 2) + 'px';
      hl.style.left = Math.round(W / 2) + 'px';
      hl.style.width = '0px';
      hl.style.height = '0px';
      card.removeAttribute('data-target');
      if (!sheet()) {
        card.classList.remove('tour-card--sheet');
        const p = placeCard(null, card.offsetWidth, card.offsetHeight, W, H);
        card.style.top = p.top + 'px';
        card.style.left = p.left + 'px';
        card.setAttribute('data-side', p.side);
      }
    }
    if (sheet()) {
      // The sheet docks away from the target: at the top when the target sits in
      // the lower half (the tab bar), else at the bottom.
      const mid = el ? (el.getBoundingClientRect().top + el.getBoundingClientRect().bottom) / 2 : 0;
      const atTop = !!el && mid > H / 2;
      card.classList.add('tour-card--sheet');
      card.classList.toggle('tour-card--sheet-top', atTop);
      card.style.top = '';
      card.style.left = '';
      card.setAttribute('data-side', atTop ? 'sheet-top' : 'sheet');
    } else {
      card.classList.remove('tour-card--sheet-top');
    }
  }

  function show(i) {
    const vis = visibleIndexes();
    if (!vis.length) { close('empty'); return; }
    if (vis.indexOf(i) < 0) {
      // the requested step vanished: the next visible one, else the previous
      const after = vis.filter(function (v) { return v > i; });
      i = after.length ? after[0] : vis[vis.length - 1];
    }
    cur = i;
    const step = steps[i];
    const pos = vis.indexOf(i);
    const el = step.target ? findTarget(step.target, document) : null;
    if (el && typeof el.scrollIntoView === 'function') { try { el.scrollIntoView({ block: 'nearest', inline: 'nearest' }); } catch (e) { /* ignore */ } }
    title.textContent = step.title || '';
    text.textContent = step.text || '';
    count.textContent = (pos + 1) + ' of ' + vis.length;
    card.setAttribute('data-step', String(i));
    back.disabled = pos === 0;
    const last = pos === vis.length - 1;
    next.textContent = last ? 'Done' : 'Next';
    next.setAttribute('data-last', last ? '1' : '0');
    layout();
    if (typeof opts.onStep === 'function') { try { opts.onStep(i, step); } catch (e) { /* ignore */ } }
    setTimeout(function () { if (!closed) next.focus(); }, 0);
  }

  function close(reason) {
    if (closed) return;
    closed = true;
    offs.forEach(function (f) { try { f(); } catch (e) { /* ignore */ } });
    backdrop.remove();
    hl.remove();
    card.remove();
    document.documentElement.classList.remove('tour-on');
    const result = { done: reason === 'done', reason: reason || 'close', step: cur };
    if (typeof opts.onClose === 'function') { try { opts.onClose(result); } catch (e) { /* ignore */ } }
    if (opener && opener.focus && document.contains(opener)) { try { opener.focus(); } catch (e) { /* gone */ } }
    resolveDone(result);
  }

  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close('esc'); return; }
    if (e.key === 'Tab') {
      const f = Array.prototype.filter.call(card.querySelectorAll(FOCUSABLE), function (x) { return rendered(x); });
      if (!f.length) { e.preventDefault(); card.focus(); return; }
      const first = f[0];
      const last = f[f.length - 1];
      const inside = card.contains(document.activeElement);
      if (!inside) { e.preventDefault(); (e.shiftKey ? last : first).focus(); return; }
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      return;
    }
    if (e.key === 'ArrowRight') { e.preventDefault(); api.next(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); api.back(); }
  }

  const api = {
    done: done,
    index: function () { return cur; },
    isOpen: function () { return !closed; },
    next: function () {
      if (closed) return;
      const vis = visibleIndexes();
      const after = vis.filter(function (v) { return v > cur; });
      if (after.length) show(after[0]); else close('done');
    },
    back: function () {
      if (closed) return;
      const vis = visibleIndexes();
      const before = vis.filter(function (v) { return v < cur; });
      if (before.length) show(before[before.length - 1]);
    },
    goTo: function (i) { if (!closed) show(i); },
    close: close,
    relayout: layout,
  };

  const vis0 = visibleIndexes();
  if (!vis0.length) {
    closed = true;
    const r = { done: false, reason: 'empty', step: -1 };
    if (typeof opts.onClose === 'function') opts.onClose(r);
    resolveDone(r);
    return api;
  }
  root.appendChild(backdrop);
  root.appendChild(hl);
  root.appendChild(card);
  document.documentElement.classList.add('tour-on');
  offs.push(on(document, 'keydown', onKey, true));
  offs.push(on(window, 'resize', layout));
  offs.push(on(window, 'scroll', layout, true));
  offs.push(on(document, 'focusin', function (e) {
    if (closed || card.contains(e.target)) return;
    setTimeout(function () { if (!closed && !card.contains(document.activeElement)) next.focus(); }, 0);
  }));
  show(vis0[0]);
  return api;
}
