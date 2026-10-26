// FEEDBACK unit tests (docs/ui-audit.md B.2 FEEDBACK, D8): what feedback-contract.test.mjs does not
// cover, plus the storage-backed createNotices and confirmScope from feedback.js (both DOM-free).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule } from './fixtures/helpers.mjs';

const core = await loadModule('js/feedback-core.js', 'FEEDBACK');
const ui = await loadModule('js/feedback.js', 'FEEDBACK');
if (core.error) throw core.error;
if (ui.error) throw ui.error;
const C = core.mod;
const F = ui.mod;

const SEC = 1000;
const MIN = 60 * SEC;
const NOW = Date.UTC(2026, 9, 26, 17, 0, 0);

function memStorage(init) {
  const m = new Map(Object.entries(init || {}));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: (k) => { m.delete(k); },
    map: m,
  };
}
const throwing = {
  getItem() { throw new Error('SecurityError'); },
  setItem() { throw new Error('QuotaExceededError'); },
};

test('relTime boundaries and bad input', () => {
  assert.equal(C.relTime(NOW - 44.999 * SEC, NOW), 'just now');
  assert.equal(C.relTime(NOW - 45 * SEC, NOW), '1 min ago');
  assert.equal(C.relTime(NOW - 59 * SEC, NOW), '1 min ago');
  assert.equal(C.relTime(NOW - (60 * MIN - 1), NOW), '59 min ago');
  assert.equal(C.relTime(NOW - (24 * 60 * MIN - 1), NOW), '23 h ago');
  assert.equal(C.relTime(NOW - 400 * 24 * 60 * MIN, NOW), '400 d ago');
  assert.equal(C.relTime(null, NOW), '');
  assert.equal(C.relTime(NaN, NOW), '');
  assert.equal(C.relTime(NOW, undefined), '');
});

test('freshness: exactly 15 min is fresh; revisions compare as strings; reason precedence', () => {
  assert.equal(C.freshness(NOW - 15 * MIN, NOW, 1, 1).stale, false);
  assert.equal(C.freshness(NOW - 15 * MIN - 1, NOW, 1, 1).reason, 'age');
  assert.equal(C.freshness(NOW, NOW, 7, '7').stale, false, 'numeric and string revision are the same');
  assert.equal(C.freshness(NOW, NOW, 7, null).stale, false, 'unknown current revision cannot make it stale');
  assert.equal(C.freshness(NOW, NOW, '', 3).stale, false, 'empty revision counts as unknown');
  assert.equal(C.freshness(NOW - 30 * MIN, NOW, 1, 2).reason, 'revision', 'revision wins over age');
  const fresh = C.freshness(NOW - 4 * MIN, NOW, 1, 1);
  assert.equal(fresh.text, 'Updated 4 min ago');
  assert.equal(fresh.reason, null);
  assert.equal(C.freshness(NOW - 4 * MIN, NOW, 1, 2).text, 'Stale \u00b7 updated 4 min ago');
  const never = C.freshness(null, NOW, 1, 2);
  assert.deepEqual(never, { stale: true, text: 'Stale \u00b7 never updated', reason: 'revision' });
  assert.equal(C.freshness(undefined, NOW).text, 'Never updated');
});

test('freshText labels (age mode)', () => {
  assert.equal(C.freshText(NOW - 2 * 60 * MIN, NOW, false, 'Run'), 'Run 2 h ago');
  assert.equal(C.freshText(NOW - 2 * 60 * MIN, NOW, true, 'Run'), 'Stale \u00b7 run 2 h ago');
  assert.equal(C.freshText(NOW - 5 * SEC, NOW, false), 'Updated just now');
});

test('scopeText: no count, string noun, zero and missing pieces', () => {
  assert.equal(C.scopeText({ verb: 'Delete', noun: 'FOH rack' }), 'Delete FOH rack?');
  assert.equal(C.scopeText({ verb: 'Restore', noun: 'revision 12' }), 'Restore revision 12?');
  assert.equal(C.scopeText({ verb: 'Remove', count: 0, noun: { one: 'patch', many: 'patches' } }), 'Remove 0 patches?');
  assert.equal(C.scopeText({ verb: 'Assign tags to', count: 42, noun: { one: 'untagged cable', many: 'untagged cables' }, scope: 'Main Auditorium' }),
    'Assign tags to 42 untagged cables in Main Auditorium?');
  assert.equal(C.scopeText({ verb: 'Delete', count: 2, noun: { one: 'share link' } }), 'Delete 2 share link?', 'falls back to one when many is missing');
  assert.equal(C.scopeText({ verb: 'Delete', count: 1, noun: { many: 'backups' } }), 'Delete 1 backups?');
  assert.equal(C.scopeText({}), '?');
  assert.equal(C.scopeText(), '?');
});

test('addNotice: defaults, bad input, dedupe edge at 60 s, ids unique at the same time', () => {
  const a = C.addNotice(null, { text: 'Hi' }, NOW);
  assert.equal(a.length, 1);
  assert.equal(a[0].level, 'info');
  assert.equal(a[0].href, '');
  const b = C.addNotice(a, { text: 'Hi' }, NOW + 60 * SEC);
  assert.equal(b.length, 1, 'exactly 60 s later is still within the window');
  let same = [];
  for (let i = 0; i < 5; i++) same = C.addNotice(same, { text: 'n' + i }, NOW);
  assert.equal(new Set(same.map((e) => e.id)).size, 5, 'ids unique even with one clock value');
  assert.equal(C.addNotice([], { text: 'x' }, 'soon')[0].t, 0, 'a non-number now becomes 0');
});

test('markRead, markAllRead and unreadCount are immutable', () => {
  let list = [];
  list = C.addNotice(list, { text: 'a' }, NOW);
  list = C.addNotice(list, { text: 'b' }, NOW + MIN);
  const snapshot = JSON.stringify(list);
  const one = C.markRead(list, list[1].id);
  assert.equal(JSON.stringify(list), snapshot);
  assert.deepEqual(one.map((e) => e.read), [false, true]);
  assert.equal(C.unreadCount(one), 1);
  assert.equal(C.unreadCount(C.markAllRead(list)), 0);
  assert.equal(C.unreadCount(null), 0);
  assert.deepEqual(C.markRead(list, 'nope').map((e) => e.read), [false, false]);
});

test('parseNotices tolerates corrupt values; noticesKey per D8', () => {
  assert.deepEqual(C.parseNotices('{oops'), []);
  assert.deepEqual(C.parseNotices('{"a":1}'), []);
  assert.deepEqual(C.parseNotices(null), []);
  const good = { id: 'n1', level: 'warn', text: 'ok', href: '#x', t: 5, read: 1 };
  const out = C.parseNotices(JSON.stringify([good, { id: 'n2', text: 3, t: 1 }, null, 'x', { text: 'no id', t: 1 }]));
  assert.deepEqual(out, [Object.assign({}, good, { read: true })]);
  const many = [];
  for (let i = 0; i < 80; i++) many.push({ id: 'n' + i, text: 't' + i, t: i });
  assert.equal(C.parseNotices(JSON.stringify(many)).length, 50);
  assert.equal(C.noticesKey('campus'), 'fathom.ui.notices.campus');
});

test('bellLabel and countText', () => {
  assert.equal(C.bellLabel(2), 'Notifications, 2 unread');
  assert.equal(C.bellLabel(0), 'Notifications');
  assert.equal(C.countText(0), '');
  assert.equal(C.countText(7), '7');
  assert.equal(C.countText(120), '99+');
});

test('errorInfo classifies ApiError, offline, Error, string and nothing', () => {
  const api = (message, status, code) => Object.assign(new Error(message), { name: 'ApiError', status, code });
  assert.deepEqual(C.errorInfo(api('boom', 500, '')), { kind: 'server', title: 'Couldn\u2019t load', message: 'boom' });
  assert.equal(C.errorInfo(api('', 404, '')).message, 'HTTP 404');
  assert.equal(C.errorInfo(api('Network error', 0, 'offline')).kind, 'offline');
  assert.match(C.errorInfo(api('Network error', 0, 'offline')).message, /server can.t be reached/);
  assert.equal(C.errorInfo(api('No fetch available', 0, 'offline')).message, 'No fetch available');
  assert.equal(C.errorInfo(new Error('bad'), false).kind, 'offline', 'browser offline wins');
  assert.deepEqual(C.errorInfo(new Error('bad')), { kind: 'error', title: 'Something went wrong', message: 'bad' });
  assert.equal(C.errorInfo('plain text').message, 'plain text');
  assert.equal(C.errorInfo(null).kind, 'error');
  assert.ok(C.errorInfo(undefined).message.length > 0);
});

test('skeletonSpec shapes per kind', () => {
  const t = C.skeletonSpec('table');
  assert.equal(t.kind, 'table');
  assert.equal(t.rows.length, 8, 'table default is 8 rows (TABLE setLoading)');
  assert.ok(t.rows.every((r) => r.length === t.cols.length));
  assert.equal(C.skeletonSpec('table', 3).rows.length, 3);
  assert.equal(C.skeletonSpec('cards').cards.length, 4);
  const p = C.skeletonSpec('page');
  assert.equal(p.tabs, 5);
  assert.equal(p.cards.length, 3);
  assert.equal(C.skeletonSpec('list', 2).items.length, 2);
  assert.equal(C.skeletonSpec('bogus').kind, 'list', 'unknown kind falls back to list');
  assert.equal(C.skeletonSpec('list', 999).items.length, 50, 'count is capped');
  assert.equal(C.skeletonSpec('list', -1).items.length, 6);
  assert.deepEqual(C.SKELETON_KINDS, ['table', 'cards', 'page', 'list']);
});

test('feedback.js imports in Node and exports the B.2 API', () => {
  for (const k of ['skeleton', 'emptyState', 'inlineError', 'confirmScope', 'staleBadge', 'reviewBadge', 'createNotices', 'mountBell']) {
    assert.equal(typeof F[k], 'function', k);
  }
  assert.equal(F.errorState, F.inlineError);
  assert.equal(F.reviewBadge({ count: 0 }), null, 'count 0 is not rendered');
  assert.equal(F.reviewBadge({}), null);
});

test('createNotices: persists under the D8 key, dedupes, and survives a reload', () => {
  let t = NOW;
  const s = memStorage();
  const n = F.createNotices(s, 'campus', { now: () => t });
  assert.deepEqual(n.list(), []);
  const e = n.add({ level: 'warn', text: 'Import finished with 2 errors', href: '#/campus/main/imports' });
  assert.equal(e.text, 'Import finished with 2 errors');
  assert.equal(n.unread(), 1);
  t += 30 * SEC;
  const again = n.add({ level: 'warn', text: 'Import finished with 2 errors' });
  assert.equal(again.id, e.id, 'deduped add returns the existing notice');
  assert.equal(n.list().length, 1);
  const raw = JSON.parse(s.getItem('fathom.ui.notices.campus'));
  assert.deepEqual(Object.keys(raw[0]).sort(), ['href', 'id', 'level', 'read', 't', 'text']);
  const reloaded = F.createNotices(s, 'campus');
  assert.equal(reloaded.unread(), 1, 'a second instance reads the same storage');
  assert.equal(F.createNotices(s, 'other').list().length, 0, 'per project');
  n.list()[0].text = 'mutated';
  assert.equal(n.list()[0].text, 'Import finished with 2 errors', 'list() returns copies');
});

test('createNotices: subscribe, markRead, markAllRead, clear', () => {
  let t = NOW;
  const n = F.createNotices(memStorage(), 'p', { now: () => t });
  const seen = [];
  const off = n.subscribe((list, unread) => seen.push([list.length, unread]));
  n.add({ text: 'a' });
  t += MIN * 2;
  const b = n.add({ text: 'b' });
  n.add({ text: 'b' });
  n.markRead(b.id);
  n.markAllRead();
  assert.deepEqual(seen, [[1, 1], [2, 2], [2, 1], [2, 0]], 'a deduped add does not notify');
  off();
  n.clear();
  assert.equal(seen.length, 4, 'unsubscribed');
  assert.deepEqual(n.list(), []);
  const bad = n.subscribe(() => { throw new Error('listener'); });
  const orig = console.error;
  console.error = () => {};
  try { n.add({ text: 'still works' }); } finally { console.error = orig; }
  bad();
  assert.equal(n.list().length, 1, 'a throwing subscriber does not break add');
});

test('createNotices: throwing, missing or corrupt storage falls back to memory', () => {
  for (const s of [throwing, null, memStorage({ 'fathom.ui.notices.p': '{corrupt' })]) {
    const n = F.createNotices(s, 'p', { now: () => NOW });
    assert.deepEqual(n.list(), []);
    n.add({ text: 'x' });
    assert.equal(n.unread(), 1);
    n.markAllRead();
    assert.equal(n.unread(), 0);
  }
});

test('confirmScope words the question through ctx.confirm and returns a boolean', async () => {
  const calls = [];
  const ctx = { confirm: (msg, opts) => { calls.push([msg, opts]); return Promise.resolve(true); } };
  const ok = await F.confirmScope(ctx, { verb: 'Delete', count: 12, noun: { one: 'cable', many: 'cables' }, scope: 'Main Auditorium', danger: true });
  assert.equal(ok, true);
  assert.equal(calls[0][0], 'Delete 12 cables in Main Auditorium?');
  assert.equal(calls[0][1].danger, true);
  assert.equal(calls[0][1].ok, 'Delete 12 cables');
  await F.confirmScope(ctx, { verb: 'Delete', noun: 'FOH rack', detail: '6 devices become unracked.' });
  assert.equal(calls[1][0], 'Delete FOH rack?\n6 devices become unracked.');
  assert.equal(calls[1][1].ok, 'Delete');
  assert.equal(calls[1][1].danger, false);
  assert.equal(await F.confirmScope({ confirm: () => Promise.resolve(null) }, { verb: 'X' }), false, 'dismissed is false');
  assert.equal(await F.confirmScope({ confirm: () => 'yes' }, { verb: 'X' }), false, 'only true confirms');
  assert.equal(await F.confirmScope({ confirm: () => Promise.reject(new Error('gone')) }, { verb: 'X' }), false);
  assert.equal(await F.confirmScope({ confirm: () => true }, { verb: 'X' }), true, 'a sync confirm works');
  assert.equal(await F.confirmScope(null, { verb: 'X' }), false, 'no ctx and no window.confirm');
});
