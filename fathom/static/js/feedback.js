// Loading, empty, error, confirm, freshness and review states plus the notification bell
// (docs/ui-audit.md B.2 FEEDBACK). Nothing touches the DOM at import time; createNotices only
// needs the injected storage, so it also runs in Node.

import { h, on } from './dom.js';
import {
  freshness, freshText, relTime, scopeText, addNotice, markRead, markAllRead as markAllReadList,
  unreadCount, noticesKey, parseNotices, bellLabel, countText, errorInfo, skeletonSpec,
} from './feedback-core.js';

const REFRESH_MS = 30 * 1000;
const LEVEL_CLASS = { info: 'info', ok: 'ok', success: 'ok', warn: 'warn', warning: 'warn', err: 'err', error: 'err' };
const LEVEL_GLYPH = { info: '\u2139\uFE0E', ok: '\u2713', warn: '\u26A0\uFE0E', err: '\u2715' };

function levelOf(level) { return LEVEL_CLASS[level] || 'info'; }

function announce(text) {
  const live = typeof document !== 'undefined' && document.getElementById('fathom-live');
  if (!live || !text) return;
  live.textContent = '';
  setTimeout(function () { live.textContent = text; }, 30);
}

function thenable(v) { return !!v && typeof v.then === 'function'; }

// Runs fn; while a returned promise is pending the button is disabled and shows busyText.
function runBusy(btn, fn, busyText) {
  if (btn.disabled) return;
  let r;
  try { r = fn(); } catch (e) { console.error(e); return; }
  if (!thenable(r)) return;
  const label = btn.textContent;
  btn.disabled = true;
  btn.setAttribute('aria-busy', 'true');
  btn.textContent = busyText;
  function done() {
    btn.disabled = false;
    btn.removeAttribute('aria-busy');
    btn.textContent = label;
  }
  r.then(done, function (e) { done(); console.error(e); });
}

// ------------------------------------------------------------ skeleton

function bar(width, cls) {
  return h('span', { class: 'fb-skel-bar' + (cls ? ' ' + cls : ''), style: { width: width + '%' } });
}

function cardsBlock(cards) {
  return h('div', { class: 'fb-skel-cards' }, cards.map(function (c) {
    return h('div', { class: 'fb-skel-card' }, [bar(c.title, 'fb-skel-title')].concat(c.lines.map(function (w) { return bar(w); })));
  }));
}

export function skeleton(kind, n) {
  const s = skeletonSpec(kind, n);
  let body;
  if (s.kind === 'table') {
    const cols = s.cols.map(function (w) { return w + 'fr'; }).join(' ');
    const row = function (widths, head) {
      return h('div', { class: 'fb-skel-row' + (head ? ' fb-skel-head' : ''), style: { gridTemplateColumns: cols } }, widths.map(function (w) {
        return h('span', { class: 'fb-skel-cell' }, bar(head ? 50 : w));
      }));
    };
    body = h('div', { class: 'fb-skel-table' }, [row(s.cols, true)].concat(s.rows.map(function (r) { return row(r, false); })));
  } else if (s.kind === 'list') {
    body = h('div', { class: 'fb-skel-list' }, s.items.map(function (it) {
      return h('div', { class: 'fb-skel-item' }, [h('span', { class: 'fb-skel-dot' }), h('span', { class: 'fb-skel-lines' }, [bar(it.main), bar(it.sub, 'fb-skel-sub')])]);
    }));
  } else if (s.kind === 'page') {
    const tabs = [];
    for (let i = 0; i < s.tabs; i++) tabs.push(h('span', { class: 'fb-skel-tab' }));
    body = h('div', { class: 'fb-skel-page' }, [
      h('div', { class: 'fb-skel-header' }, [bar(38, 'fb-skel-h1'), h('div', { class: 'fb-skel-facts' }, [bar(14), bar(18), bar(11), bar(16)])]),
      h('div', { class: 'fb-skel-tabs' }, tabs),
      cardsBlock(s.cards),
    ]);
  } else {
    body = cardsBlock(s.cards);
  }
  return h('div', { class: 'fb-skeleton fb-skeleton-' + s.kind, 'data-kind': s.kind, 'aria-busy': 'true' }, [
    h('span', { class: 'fb-sr' }, 'Loading\u2026'),
    h('div', { class: 'fb-skel', 'aria-hidden': 'true' }, body),
  ]);
}

// ------------------------------------------------------------ empty and error

function actionNode(a, cls) {
  if (!a) return null;
  if (typeof Node !== 'undefined' && a instanceof Node) return a;
  if (typeof a === 'string') return h('p', { class: cls + ' fb-empty-note' }, a);
  if (a.href) return h('a', { class: 'fb-btn ' + cls, href: a.href }, a.label || '');
  if (typeof a.run === 'function') {
    return h('button', { type: 'button', class: cls, onclick: function (e) { a.run(e); } }, a.label || '');
  }
  return null;
}

export function emptyState(o) {
  o = o || {};
  const action = actionNode(o.action, 'primary fb-empty-action');
  const secondary = actionNode(o.secondary, 'ghost fb-empty-secondary');
  return h('div', { class: 'fb-empty' }, [
    o.title ? h('h3', { class: 'fb-empty-title' }, o.title) : null,
    o.text ? h('p', { class: 'fb-empty-text' }, o.text) : null,
    action || secondary ? h('div', { class: 'fb-empty-actions' }, [action, secondary]) : null,
  ]);
}

export function inlineError(err, retry, opts) {
  const compact = !!(opts && opts.compact);
  const online = typeof navigator !== 'undefined' && navigator.onLine === false ? false : undefined;
  const info = errorInfo(err, online);
  const btn = typeof retry === 'function'
    ? h('button', { type: 'button', class: 'fb-retry', onclick: function () { runBusy(btn, retry, 'Retrying\u2026'); } }, 'Retry')
    : null;
  return h('div', { class: 'fb-error fb-error-' + info.kind + (compact ? ' fb-compact' : ''), role: 'alert', 'data-kind': info.kind }, [
    h('span', { class: 'fb-error-glyph', 'aria-hidden': 'true' }, '\u26A0\uFE0E'),
    h('div', { class: 'fb-error-body' }, [
      compact ? null : h('strong', { class: 'fb-error-title' }, info.title),
      h('span', { class: 'fb-error-msg' }, info.message),
    ]),
    btn,
  ]);
}

export { inlineError as errorState };

// ------------------------------------------------------------ confirm

export function confirmScope(ctx, o) {
  o = o || {};
  const text = scopeText(o);
  const message = o.detail ? text + '\n' + o.detail : text;
  const hasCount = typeof o.count === 'number' && isFinite(o.count);
  const noun = o.noun && typeof o.noun === 'object' ? (o.count === 1 ? o.noun.one : o.noun.many) : '';
  const ok = o.ok || (hasCount && noun ? o.verb + ' ' + o.count + ' ' + noun : o.verb) || undefined;
  let p;
  try {
    if (ctx && typeof ctx.confirm === 'function') p = ctx.confirm(message, { danger: !!o.danger, ok: ok, title: o.title });
    else p = typeof window !== 'undefined' && typeof window.confirm === 'function' ? window.confirm(message) : false;
  } catch (e) {
    console.error(e);
    p = false;
  }
  return Promise.resolve(p).then(function (v) { return v === true; }, function () { return false; });
}

// ------------------------------------------------------------ freshness and review

function val(v) { return typeof v === 'function' ? v() : v; }

const REASON_TITLE = {
  revision: 'The project changed since this data was loaded.',
  age: 'Loaded more than 15 minutes ago.',
};

// Extra options beyond the contract: label (replaces "updated", e.g. "Run"), always (show while
// fresh too), now (clock). fetchedAt, fetchedRev and currentRev may be getters.
export function staleBadge(o) {
  const st = Object.assign({}, o || {});
  const clock = typeof st.now === 'function' ? st.now : function () { return Date.now(); };
  const text = h('span', { class: 'fb-stale-text' });
  const btn = typeof st.onRefresh === 'function'
    ? h('button', { type: 'button', class: 'fb-stale-refresh', onclick: function () {
      runBusy(btn, function () { return st.onRefresh(); }, 'Refreshing\u2026');
    } }, 'Refresh')
    : null;
  const el = h('span', { class: 'fb-stale', hidden: true }, [h('span', { class: 'fb-stale-dot', 'aria-hidden': 'true' }), text, btn]);
  let wasStale = null;
  let timer = null;

  function evaluate() {
    const at = val(st.fetchedAt);
    const now = clock();
    const f = freshness(typeof at === 'number' ? at : null, now, val(st.fetchedRev), val(st.currentRev));
    const label = st.label ? freshText(typeof at === 'number' ? at : null, now, f.stale, st.label) : f.text;
    text.textContent = label;
    el.hidden = !(f.stale || st.always);
    el.classList.toggle('fb-is-stale', f.stale);
    el.setAttribute('data-reason', f.reason || '');
    if (f.reason) el.title = REASON_TITLE[f.reason]; else el.removeAttribute('title');
    if (wasStale === false && f.stale) announce(label);
    wasStale = f.stale;
    return f;
  }
  function stop() { if (timer) clearInterval(timer); timer = null; }
  function start() {
    if (timer) return;
    timer = setInterval(function () {
      if (!el.isConnected) { stop(); return; }
      evaluate();
    }, REFRESH_MS);
  }
  el.update = function (patch) {
    Object.assign(st, patch || {});
    const f = evaluate();
    start();
    return f;
  };
  el.refresh = evaluate;
  el.destroy = stop;
  evaluate();
  start();
  return el;
}

export function reviewBadge(o) {
  o = o || {};
  const count = Number(o.count) || 0;
  if (count <= 0) return null;
  const label = count + ' ' + (o.label || 'to review');
  return h('button', {
    type: 'button', class: 'fb-review', 'aria-label': label, title: o.title,
    onclick: typeof o.onClick === 'function' ? function (e) { o.onClick(e); } : null,
  }, [h('span', { class: 'fb-review-glyph', 'aria-hidden': 'true' }, '\u26A0\uFE0E'), h('span', { class: 'fb-review-label' }, label)]);
}

// ------------------------------------------------------------ notices and bell

// Notices live in storage (sessionStorage) under fathom.ui.notices.<project>; a missing or throwing
// storage falls back to memory. opts.now injects the clock. Beyond the contract: markRead(id), clear().
export function createNotices(storage, project, opts) {
  const key = noticesKey(project);
  const clock = opts && typeof opts.now === 'function' ? opts.now : function () { return Date.now(); };
  const subs = [];
  let mem = [];

  function read() {
    try {
      if (storage) {
        const raw = storage.getItem(key);
        if (raw !== null && raw !== undefined) { mem = parseNotices(raw); return mem; }
      }
    } catch (e) { /* private mode: keep memory */ }
    return mem;
  }
  function write(list) {
    mem = list;
    try { if (storage) storage.setItem(key, JSON.stringify(list)); } catch (e) { /* quota or private mode */ }
  }
  function copy(list) { return list.map(function (e) { return Object.assign({}, e); }); }
  function emit() {
    const list = copy(mem);
    const n = unreadCount(mem);
    subs.slice().forEach(function (fn) {
      try { fn(list, n); } catch (e) { console.error(e); }
    });
  }

  mem = read();
  return {
    key: key,
    add: function (n) {
      const before = read();
      const after = addNotice(before, n, clock());
      if (after.length && before.length && after[0].id === before[0].id && after.length === before.length) {
        const text = String((n && n.text) || '');
        const same = before.filter(function (e) { return e.text === text; })[0];
        return same ? Object.assign({}, same) : null;
      }
      write(after);
      emit();
      return Object.assign({}, after[0]);
    },
    list: function () { return copy(read()); },
    unread: function () { return unreadCount(read()); },
    markRead: function (id) { write(markRead(read(), id)); emit(); },
    markAllRead: function () { write(markAllReadList(read())); emit(); },
    clear: function () { write([]); emit(); },
    subscribe: function (fn) {
      subs.push(fn);
      return function () {
        const i = subs.indexOf(fn);
        if (i >= 0) subs.splice(i, 1);
      };
    },
  };
}

let bellSeq = 0;

// Returns {open(which), close(focusButton), toggle(), render(), isOpen(), destroy(), pop, menu}.
export function mountBell(button, countEl, notices, ctx) {
  const id = 'fb-notices-' + (++bellSeq);
  const menu = h('ul', { class: 'fb-notices', role: 'menu', id: id, 'aria-label': 'Notifications' });
  const pop = h('div', { class: 'fb-bell-pop', hidden: true }, [h('div', { class: 'fb-bell-head', 'aria-hidden': 'true' }, 'Notifications'), menu]);
  document.body.appendChild(pop);
  button.classList.add('fb-bell');
  button.setAttribute('aria-haspopup', 'menu');
  button.setAttribute('aria-expanded', 'false');
  button.setAttribute('aria-controls', id);
  if (countEl) countEl.classList.add('fb-bell-count');
  let isOpen = false;
  let offDoc = [];

  function items() { return Array.prototype.slice.call(menu.querySelectorAll('[role=menuitem]')); }
  function focusAt(i) {
    const its = items();
    if (!its.length) return;
    const k = ((i % its.length) + its.length) % its.length;
    its[k].focus();
  }

  function renderMenu() {
    const active = document.activeElement;
    const keep = active && menu.contains(active) ? items().indexOf(active) : -1;
    const list = notices.list();
    const now = Date.now();
    menu.textContent = '';
    if (!list.length) {
      menu.appendChild(h('li', { role: 'none', class: 'fb-notices-empty' },
        h('span', { role: 'menuitem', tabindex: '-1', 'aria-disabled': 'true' }, 'No notifications')));
    }
    list.forEach(function (n) {
      const lv = levelOf(n.level);
      const inner = [
        h('span', { class: 'fb-notice-glyph', 'aria-hidden': 'true' }, LEVEL_GLYPH[lv]),
        h('span', { class: 'fb-notice-text' }, n.text),
        h('span', { class: 'fb-notice-time' }, relTime(n.t, now)),
        n.read ? null : h('span', { class: 'fb-sr' }, ', unread'),
      ];
      const pick = function () { close(!n.href); notices.markRead(n.id); };
      const item = n.href
        ? h('a', { role: 'menuitem', tabindex: '-1', href: n.href, onclick: pick }, inner)
        : h('button', { role: 'menuitem', tabindex: '-1', type: 'button', onclick: pick }, inner);
      menu.appendChild(h('li', { role: 'none', class: 'fb-notice fb-' + lv + (n.read ? '' : ' fb-unread'), 'data-id': n.id }, item));
    });
    const unread = unreadCount(list);
    menu.appendChild(h('li', { role: 'none', class: 'fb-notices-foot' }, h('button', {
      role: 'menuitem', tabindex: '-1', type: 'button', class: 'fb-markall', 'aria-disabled': unread ? null : 'true',
      onclick: function () { if (unread) notices.markAllRead(); },
    }, 'Mark all read')));
    if (keep >= 0) focusAt(Math.min(keep, items().length - 1));
  }

  function position() {
    const r = button.getBoundingClientRect();
    const vw = document.documentElement.clientWidth || window.innerWidth;
    const width = Math.min(360, vw - 16);
    const left = Math.max(8, Math.min(vw - width - 8, r.right - width));
    const top = Math.round(r.bottom + 6);
    pop.style.left = Math.round(left) + 'px';
    pop.style.top = top + 'px';
    pop.style.width = Math.round(width) + 'px';
    pop.style.maxHeight = Math.max(160, window.innerHeight - top - 12) + 'px';
  }

  function render() {
    const n = notices.unread();
    if (countEl) {
      countEl.textContent = countText(n);
      countEl.hidden = n === 0;
    }
    button.setAttribute('aria-label', bellLabel(n));
    button.classList.toggle('fb-has-unread', n > 0);
    if (isOpen) renderMenu();
  }

  function open(which) {
    if (!isOpen) {
      isOpen = true;
      pop.hidden = false;
      button.setAttribute('aria-expanded', 'true');
      renderMenu();
      position();
      offDoc = [
        on(document, 'pointerdown', function (e) {
          if (!pop.contains(e.target) && !button.contains(e.target)) close(false);
        }, true),
        on(window, 'resize', position),
        on(window, 'scroll', position, true),
      ];
    }
    if (which === 'last') focusAt(-1);
    else if (which !== 'none') focusAt(0);
  }

  function close(focusButton) {
    if (!isOpen) return;
    isOpen = false;
    pop.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    offDoc.forEach(function (off) { off(); });
    offDoc = [];
    if (focusButton) button.focus();
  }

  function toggle() { if (isOpen) close(true); else open('first'); }

  const offs = [
    on(button, 'click', function (e) { e.preventDefault(); toggle(); }),
    on(button, 'keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); open('first'); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); open('last'); }
      else if (e.key === 'Escape' && isOpen) { e.preventDefault(); e.stopPropagation(); close(true); }
    }),
    on(menu, 'keydown', function (e) {
      const its = items();
      const i = its.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); focusAt(i + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); focusAt(i < 0 ? -1 : i - 1); }
      else if (e.key === 'Home') { e.preventDefault(); focusAt(0); }
      else if (e.key === 'End') { e.preventDefault(); focusAt(-1); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); }
      else if (e.key === 'Tab') close(false);
      else if ((e.key === ' ' || e.key === 'Spacebar') && document.activeElement && document.activeElement.tagName === 'A') {
        e.preventDefault();
        document.activeElement.click();
      }
    }),
    notices.subscribe(render),
  ];
  if (ctx && typeof ctx.subscribe === 'function') {
    const offRoute = ctx.subscribe('route', function () { close(false); });
    if (typeof offRoute === 'function') offs.push(offRoute);
  }
  render();

  return {
    open: open,
    close: close,
    toggle: toggle,
    render: render,
    isOpen: function () { return isOpen; },
    destroy: function () {
      close(false);
      offs.forEach(function (off) { off(); });
      pop.remove();
    },
    pop: pop,
    menu: menu,
  };
}
