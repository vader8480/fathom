// Harness for js/feedback.js (docs/ui-audit.md B.2 FEEDBACK, D10): every state side by side.
// ?smoke=1 writes data-smoke once rendered. window.__fb exposes the live objects for tests:
// api (the feedback.js module), notices, bell, badges, counts, clock offset (ms added to Date.now()
// for the badges and notices).
import { h } from '../js/dom.js';
import * as feedback from '../js/feedback.js';

const { skeleton, emptyState, inlineError, confirmScope, staleBadge, reviewBadge, createNotices, mountBell } = feedback;

window.__fathomErrors = window.__fathomErrors || [];
(function () {
  const errs = window.__fathomErrors;
  window.addEventListener('error', function (e) { errs.push(String((e && e.message) || e)); });
  window.addEventListener('unhandledrejection', function (e) { errs.push('unhandled: ' + String(e && e.reason && (e.reason.stack || e.reason.message) || e.reason)); });
  const ce = console.error;
  console.error = function () { errs.push(Array.prototype.map.call(arguments, String).join(' ')); return ce.apply(console, arguments); };
})();

const params = new URLSearchParams(location.search);
const MIN = 60 * 1000;
const fb = window.__fb = { api: feedback, counts: { retry: 0, emptyAction: 0, emptySecondary: 0, refresh: 0, review: 0 }, offset: 0, badges: {}, confirms: [] };
function now() { return Date.now() + fb.offset; }
function later(ms, v) { return new Promise(function (res) { setTimeout(function () { res(v); }, ms); }); }

function apiError(message, status, code) {
  const e = new Error(message);
  e.name = 'ApiError';
  e.status = status;
  e.code = code || '';
  return e;
}

function card(title, demos) {
  return h('section', { class: 'h-card' }, [h('h2', null, title)].concat(demos));
}
function demo(id, note, content) {
  return h('div', { class: 'h-demo', id: id }, [note ? h('p', { class: 'h-note' }, note) : null].concat(content));
}

// A local confirm dialog in case app.js cannot load; same contract as app.js confirmDialog.
function localConfirm(message, opts) {
  return new Promise(function (resolve) {
    const back = h('div', { class: 'app-dialog-backdrop' });
    function done(v) { back.remove(); resolve(v); }
    back.appendChild(h('div', { class: 'app-dialog', role: 'dialog', 'aria-modal': 'true' }, [
      h('header', null, h('h2', null, opts && opts.danger ? 'Are you sure?' : 'Confirm')),
      h('div', { class: 'body' }, h('p', { style: { margin: '0', whiteSpace: 'pre-wrap' } }, message)),
      h('footer', null, [
        h('button', { type: 'button', onclick: function () { done(false); } }, 'Cancel'),
        h('button', { type: 'button', class: opts && opts.danger ? 'danger' : 'primary', onclick: function () { done(true); } }, (opts && opts.ok) || 'OK'),
      ]),
    ]));
    document.body.appendChild(back);
  });
}

function ctxConfirm() {
  return import('../js/app.js').then(function (m) { return m.confirmDialog || localConfirm; }, function () { return localConfirm; });
}

function render(confirmFn) {
  const main = document.getElementById('fb-h-main');
  const ctx = {
    confirm: function (message, opts) { fb.confirms.push({ message: message, opts: opts }); return confirmFn(message, opts); },
    subscribe: function (type, fn) {
      if (type !== 'route') return function () {};
      window.addEventListener('hashchange', fn);
      return function () { window.removeEventListener('hashchange', fn); };
    },
  };

  // skeletons
  main.appendChild(card('Skeletons', ['table', 'cards', 'page', 'list'].map(function (k) {
    return demo('fb-h-skel-' + k, "skeleton('" + k + "')", skeleton(k, k === 'table' ? 5 : k === 'list' ? 4 : k === 'cards' ? 3 : undefined));
  })));

  // empty
  main.appendChild(card('Empty state', [
    demo('fb-h-empty', 'with action and secondary', emptyState({
      title: 'No devices in Main Auditorium yet.',
      text: 'Add gear in Patch, or bulk add from a spreadsheet.',
      action: { label: 'Add gear', run: function () { fb.counts.emptyAction++; } },
      secondary: { label: 'Bulk add', run: function () { fb.counts.emptySecondary++; } },
    })),
    demo('fb-h-empty-plain', 'no action (viewer)', emptyState({ title: 'No revisions yet.', text: 'Every save creates one.', action: null })),
  ]));

  // errors
  const retryOut = h('span', { class: 'h-out', id: 'fb-h-retry-count' }, 'retries: 0');
  function retry() {
    fb.counts.retry++;
    retryOut.textContent = 'retries: ' + fb.counts.retry;
    return later(300);
  }
  main.appendChild(card('Errors', [
    demo('fb-h-error', 'ApiError 500 with retry', [inlineError(apiError('Overlay could not be built: bad sheet "Rack 3"', 500, 'server_error'), retry), retryOut]),
    demo('fb-h-error-compact', 'compact, beside a failing thing', inlineError(apiError('Schedule failed to load', 502), retry, { compact: true })),
    demo('fb-h-offline', 'offline (ApiError status 0)', inlineError(apiError('Network error', 0, 'offline'), retry)),
    demo('fb-h-error-plain', 'plain Error, no retry', inlineError(new Error('Floor plan image could not be decoded'), null)),
  ]));

  // freshness
  const b = fb.badges;
  b.rev = staleBadge({ fetchedAt: now() - 4 * MIN, fetchedRev: 7, currentRev: 8, now: now, onRefresh: function () {
    fb.counts.refresh++;
    return later(300).then(function () { b.rev.update({ fetchedAt: now(), fetchedRev: 8 }); });
  } });
  b.fresh = staleBadge({ fetchedAt: now() - 2 * MIN, fetchedRev: 7, currentRev: 7, now: now, onRefresh: function () { fb.counts.refresh++; } });
  b.age = staleBadge({ fetchedAt: now() - 20 * MIN, now: now, onRefresh: function () { fb.counts.refresh++; } });
  b.run = staleBadge({ fetchedAt: now() - 5 * MIN, label: 'Run', always: true, now: now });
  const bump = h('button', { type: 'button', id: 'fb-h-bump', onclick: function () { b.fresh.update({ currentRev: 9 }); } }, 'Change doc revision');
  main.appendChild(card('Freshness', [
    demo('fb-h-stale-rev', 'revision differs (7 vs 8); Refresh catches up', b.rev),
    demo('fb-h-stale-fresh', 'fresh: hidden until the revision changes', h('div', { class: 'h-row' }, [b.fresh, bump])),
    demo('fb-h-stale-age', 'same revision, 20 min old', b.age),
    demo('fb-h-stale-run', "age mode, always shown (label 'Run')", b.run),
  ]));

  // review
  main.appendChild(card('Review badges', [
    demo('fb-h-review', 'count 3', reviewBadge({ count: 3, onClick: function () { fb.counts.review++; } })),
    demo('fb-h-review-label', "count 2, label 'model suggestions'", reviewBadge({ count: 2, label: 'model suggestions', onClick: function () { fb.counts.review++; } })),
    demo('fb-h-review-zero', 'count 0: not rendered', reviewBadge({ count: 0 }) || h('span', { class: 'h-out' }, '(nothing)')),
  ]));

  // confirm
  const confirmOut = h('span', { class: 'h-out', id: 'fb-h-confirm-result' }, '\u2014');
  function ask(o) {
    return function () {
      confirmScope(ctx, o).then(function (v) { fb.lastConfirm = v; confirmOut.textContent = String(v); });
    };
  }
  main.appendChild(card('Confirm scope', [demo('fb-h-confirm-demo', 'confirmScope via ctx.confirm', h('div', { class: 'h-row' }, [
    h('button', { type: 'button', id: 'fb-h-confirm', class: 'danger', onclick: ask({ verb: 'Delete', count: 12, noun: { one: 'cable', many: 'cables' }, scope: 'Main Auditorium', danger: true }) }, 'Delete 12 cables'),
    h('button', { type: 'button', id: 'fb-h-confirm-one', onclick: ask({ verb: 'Restore', noun: 'revision 12', detail: 'This creates revision 43.' }) }, 'Restore revision 12'),
    confirmOut,
  ]))]));

  // notices
  let storage = null;
  try { storage = window.sessionStorage; } catch (e) { storage = null; }
  const notices = fb.notices = createNotices(storage, 'harness', { now: now });
  notices.clear();
  if (!params.has('empty')) {
    fb.offset = -2 * 60 * MIN;
    notices.add({ level: 'ok', text: 'Conflict resolved', href: '#conflict' });
    notices.markAllRead();
    fb.offset = -6 * MIN;
    notices.add({ level: 'warn', text: 'Import finished with 2 errors', href: '#imports' });
    fb.offset = -30 * 1000;
    notices.add({ level: 'ok', text: 'Saved 3 queued changes', href: '#saved' });
    fb.offset = 0;
  }
  fb.bell = mountBell(document.getElementById('fb-h-bell'), document.getElementById('fb-h-bell-count'), notices, ctx);
  let seq = 0;
  function add(level, text) { return function () { notices.add({ level: level, text: text || (level + ' notice ' + (++seq)), href: '#n' + seq }); }; }
  main.appendChild(card('Notices and bell', [demo('fb-h-notices', 'the bell is in the header; Arrow keys, Home, End and Esc work inside it', h('div', { class: 'h-row' }, [
    h('button', { type: 'button', id: 'fb-h-add-info', onclick: add('info') }, 'Add info'),
    h('button', { type: 'button', id: 'fb-h-add-warn', onclick: add('warn') }, 'Add warning'),
    h('button', { type: 'button', id: 'fb-h-add-err', onclick: add('err') }, 'Add error'),
    h('button', { type: 'button', id: 'fb-h-add-dup', onclick: add('ok', 'Saved 3 queued changes') }, 'Repeat last save (deduped)'),
    h('button', { type: 'button', id: 'fb-h-clear', onclick: function () { notices.clear(); } }, 'Clear'),
  ]))]));
}

function ready() {
  if (params.get('smoke') === '1') {
    setTimeout(function () {
      document.documentElement.setAttribute('data-smoke', JSON.stringify({ ready: true, errors: window.__fathomErrors, stats: null }));
    }, 100);
  }
}

ctxConfirm().then(function (fn) {
  try { render(fn); } catch (e) { console.error(e); }
  ready();
});
