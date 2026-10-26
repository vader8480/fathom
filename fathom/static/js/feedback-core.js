// Pure logic behind feedback.js (docs/ui-audit.md B.2 FEEDBACK, D8): freshness, relative time,
// scope wording, the notice list and error classification. No DOM, storage or clock access:
// every time is passed in, so the module imports in Node.

export const STALE_AFTER_MS = 15 * 60 * 1000;
export const NOTICE_DEDUPE_MS = 60 * 1000;
export const MAX_NOTICES = 50;
export const NOTICES_PREFIX = 'fathom.ui.notices.';

const SEC = 1000;
const MIN = 60 * SEC;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

function isNum(v) { return typeof v === 'number' && isFinite(v); }
function given(v) { return v !== undefined && v !== null && v !== ''; }

export function relTime(ms, now) {
  if (!isNum(ms) || !isNum(now)) return '';
  const d = now - ms;
  if (d < 45 * SEC) return 'just now';
  if (d < HOUR) return Math.max(1, Math.floor(d / MIN)) + ' min ago';
  if (d < DAY) return Math.floor(d / HOUR) + ' h ago';
  return Math.floor(d / DAY) + ' d ago';
}

// "Updated 4 min ago" / "Stale · updated 4 min ago"; label replaces "updated" (e.g. "Run").
export function freshText(fetchedAt, now, stale, label) {
  const word = label || 'updated';
  const ago = isNum(fetchedAt) ? relTime(fetchedAt, now) : '';
  const tail = ago ? word + ' ' + ago : 'never ' + word;
  if (stale) return 'Stale \u00b7 ' + tail.charAt(0).toLowerCase() + tail.slice(1);
  return tail.charAt(0).toUpperCase() + tail.slice(1);
}

// Stale when both revisions are known and differ, or when fetchedAt is more than 15 min before now.
// A missing fetchedAt has no age, so only the revision can make it stale.
export function freshness(fetchedAt, now, fetchedRev, currentRev) {
  const revStale = given(fetchedRev) && given(currentRev) && String(fetchedRev) !== String(currentRev);
  const ageStale = isNum(fetchedAt) && isNum(now) && now - fetchedAt > STALE_AFTER_MS;
  const stale = revStale || ageStale;
  return {
    stale: stale,
    text: freshText(isNum(fetchedAt) ? fetchedAt : null, now, stale),
    reason: revStale ? 'revision' : (ageStale ? 'age' : null),
  };
}

function nounFor(noun, count) {
  if (typeof noun === 'string') return noun;
  if (!noun) return '';
  return count === 1 ? (noun.one || noun.many || '') : (noun.many || noun.one || '');
}

// "Delete 12 cables in Main Auditorium?"; without a count: "Delete FOH rack?" (noun used as is).
export function scopeText(o) {
  o = o || {};
  const hasCount = isNum(o.count);
  const parts = [o.verb || ''];
  if (hasCount) parts.push(String(o.count));
  parts.push(nounFor(o.noun, hasCount ? o.count : 1));
  let s = parts.filter(function (p) { return p !== ''; }).join(' ');
  if (o.scope) s += ' in ' + o.scope;
  return s + '?';
}

function noticeId(list, now) {
  const base = 'n' + Math.max(0, Math.floor(now)).toString(36);
  const ids = {};
  list.forEach(function (e) { ids[String(e.id)] = true; });
  let id = base;
  for (let k = 1; ids[id]; k++) id = base + '-' + k;
  return id;
}

// New list, newest first. The same text within 60 s of an existing notice is dropped; max 50.
export function addNotice(list, n, now) {
  const cur = Array.isArray(list) ? list.slice() : [];
  const t = isNum(now) ? now : 0;
  const text = String((n && n.text) || '');
  const dup = cur.some(function (e) { return e && e.text === text && Math.abs(t - e.t) <= NOTICE_DEDUPE_MS; });
  if (dup) return cur;
  const entry = {
    id: noticeId(cur, t),
    level: (n && n.level) || 'info',
    text: text,
    href: (n && n.href) || '',
    t: t,
    read: false,
  };
  return [entry].concat(cur).slice(0, MAX_NOTICES);
}

export function markRead(list, id) {
  return (Array.isArray(list) ? list : []).map(function (e) {
    return id === undefined || String(e.id) === String(id) ? Object.assign({}, e, { read: true }) : e;
  });
}

export function markAllRead(list) { return markRead(list); }

export function unreadCount(list) {
  return (Array.isArray(list) ? list : []).filter(function (e) { return !e.read; }).length;
}

export function noticesKey(project) {
  return NOTICES_PREFIX + (project || '');
}

// Tolerant reader for the sessionStorage value: corrupt JSON or bad entries give [].
export function parseNotices(raw) {
  let v;
  try { v = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (e) { return []; }
  if (!Array.isArray(v)) return [];
  return v.filter(function (e) {
    return e && typeof e === 'object' && given(e.id) && typeof e.text === 'string' && isNum(e.t);
  }).map(function (e) {
    return { id: e.id, level: e.level || 'info', text: e.text, href: e.href || '', t: e.t, read: !!e.read };
  }).slice(0, MAX_NOTICES);
}

export function bellLabel(unread) {
  return unread > 0 ? 'Notifications, ' + unread + ' unread' : 'Notifications';
}

export function countText(unread) {
  if (!(unread > 0)) return '';
  return unread > 99 ? '99+' : String(unread);
}

// {kind: 'offline' | 'server' | 'error', title, message} for an ApiError, Error, string or nothing.
export function errorInfo(err, online) {
  const status = err && isNum(err.status) ? err.status : null;
  const code = (err && err.code) || '';
  let message = '';
  if (typeof err === 'string') message = err;
  else if (err && err.message) message = String(err.message);
  if (online === false || code === 'offline' || (err && err.name === 'ApiError' && status === 0)) {
    return { kind: 'offline', title: 'You\u2019re offline', message: message && message !== 'Network error' ? message : 'The server can\u2019t be reached. Check the connection, then retry.' };
  }
  if (status && status >= 400) {
    return { kind: 'server', title: 'Couldn\u2019t load', message: message || 'HTTP ' + status };
  }
  return { kind: 'error', title: 'Something went wrong', message: message || 'An unexpected error occurred.' };
}

// Placeholder geometry per kind; widths are percentages. n is rows, cards or items.
export const SKELETON_KINDS = ['table', 'cards', 'page', 'list'];
const COL_W = [28, 18, 22, 14, 12];
const LINE_W = [62, 48, 74, 55, 68, 40];

export function skeletonSpec(kind, n) {
  const k = SKELETON_KINDS.indexOf(kind) >= 0 ? kind : 'list';
  const count = isNum(n) && n > 0 ? Math.min(50, Math.floor(n)) : { table: 8, cards: 4, page: 3, list: 6 }[k];
  const out = { kind: k, count: count };
  if (k === 'table') {
    out.cols = COL_W.slice();
    out.rows = [];
    for (let i = 0; i < count; i++) out.rows.push(COL_W.map(function (w, j) { return Math.max(30, 100 - ((i * 7 + j * 13) % 45)); }));
  } else if (k === 'list') {
    out.items = [];
    for (let i = 0; i < count; i++) out.items.push({ main: LINE_W[i % LINE_W.length], sub: Math.round(LINE_W[(i + 3) % LINE_W.length] * 0.6) });
  } else {
    out.cards = [];
    for (let i = 0; i < count; i++) out.cards.push({ title: 40 + ((i * 17) % 30), lines: [LINE_W[i % LINE_W.length], LINE_W[(i + 2) % LINE_W.length]] });
    if (k === 'page') out.tabs = 5;
  }
  return out;
}
