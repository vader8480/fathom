// T-FEEDBACK contract test: js/feedback-core.js against docs/ui-audit.md B.2 FEEDBACK (Core) and B.1 D8.
// Written from the contract alone; the unit's own tests live in feedback-core.test.mjs.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, clone, m, need } from './fixtures/helpers.mjs';

const { mod, skip: absent, error } = await loadModule('js/feedback-core.js', 'FEEDBACK');
const S = 'B.2 FEEDBACK';
const skip = absent || (error ? 'feedback-core.js failed to import (see failing test)' : false);
const T = (name, fn) => test(name, { skip }, fn);

if (error) test('feedback-core.js imports in Node (pure core module)', () => { throw error; });

const SEC = 1000;
const MIN = 60 * SEC;
const H = 60 * MIN;
const D = 24 * H;
const NOW = Date.UTC(2026, 9, 26, 17, 0, 0);
const REL = /just now|\d+ (min|h|d) ago/;
const STALE_REASONS = ['revision', 'age'];

function assertShape(r, what) {
  assert.ok(r && typeof r === 'object', m('freshness', S, `${what}: returns an object`));
  assert.equal(typeof r.stale, 'boolean', m('freshness', S, `${what}: stale is a boolean`));
  assert.equal(typeof r.text, 'string', m('freshness', S, `${what}: text is a string`));
  assert.ok('reason' in r, m('freshness', S, `${what}: has a reason key`));
}

function assertFresh(r, what) {
  assertShape(r, what);
  assert.equal(r.stale, false, m('freshness', S, `${what}: not stale`));
  assert.ok(!STALE_REASONS.includes(r.reason), m('freshness', S, `${what}: no stale reason when fresh (got ${r.reason})`));
}

// ---- freshness ----

T('freshness: same revision, young age is fresh', () => {
  const freshness = need(mod, 'freshness', 'freshness', S);
  assertFresh(freshness(NOW - 4 * MIN, NOW, 7, 7), '4 min, rev 7/7');
  assertFresh(freshness(NOW, NOW, 'r1', 'r1'), '0 s, rev r1/r1');
  assertFresh(freshness(NOW - 14 * MIN, NOW, 7, 7), '14 min, rev 7/7');
});

T('freshness: text carries a relative time', () => {
  const freshness = need(mod, 'freshness', 'freshness', S);
  const a = freshness(NOW - 4 * MIN, NOW, 7, 7);
  assert.ok(a.text.includes('4 min ago'), m('freshness', S, `4 min old text mentions "4 min ago" (got "${a.text}")`));
  const b = freshness(NOW - 5 * SEC, NOW, 7, 7);
  assert.ok(b.text.includes('just now'), m('freshness', S, `5 s old text mentions "just now" (got "${b.text}")`));
  const c = freshness(NOW - 4 * MIN, NOW, 7, 8);
  assert.ok(c.text.includes('4 min ago'), m('freshness', S, `stale-by-revision text still gives the age (got "${c.text}")`));
  const d = freshness(NOW - 20 * MIN, NOW, 7, 7);
  assert.match(d.text, REL, m('freshness', S, `stale-by-age text has a relative time (got "${d.text}")`));
});

T('freshness: revision differs → stale, reason revision', () => {
  const freshness = need(mod, 'freshness', 'freshness', S);
  for (const [a, b] of [[7, 8], ['r1', 'r2'], [0, 1]]) {
    const r = freshness(NOW - 1 * MIN, NOW, a, b);
    assertShape(r, `rev ${a}/${b}`);
    assert.equal(r.stale, true, m('freshness', S, `rev ${a} vs ${b} is stale`));
    assert.equal(r.reason, 'revision', m('freshness', S, `rev ${a} vs ${b} reason is revision`));
  }
});

T('freshness: age over 15 min with same revision → stale, reason age', () => {
  const freshness = need(mod, 'freshness', 'freshness', S);
  for (const age of [16 * MIN, 2 * H, 3 * D]) {
    const r = freshness(NOW - age, NOW, 7, 7);
    assertShape(r, `age ${age / MIN} min`);
    assert.equal(r.stale, true, m('freshness', S, `${age / MIN} min old is stale`));
    assert.equal(r.reason, 'age', m('freshness', S, `${age / MIN} min old reason is age`));
  }
});

T('freshness: both revision and age stale → stale with one of the two reasons', () => {
  const freshness = need(mod, 'freshness', 'freshness', S);
  const r = freshness(NOW - 30 * MIN, NOW, 7, 8);
  assertShape(r, '30 min, rev 7/8');
  assert.equal(r.stale, true, m('freshness', S, 'old and revision-changed is stale'));
  assert.ok(STALE_REASONS.includes(r.reason), m('freshness', S, `reason is revision or age (got ${r.reason})`));
});

T('freshness: no revisions given → age decides', () => {
  const freshness = need(mod, 'freshness', 'freshness', S);
  assertFresh(freshness(NOW - 2 * MIN, NOW), '2 min, no revs');
  const r = freshness(NOW - 20 * MIN, NOW);
  assert.equal(r.stale, true, m('freshness', S, '20 min, no revs is stale'));
  assert.equal(r.reason, 'age', m('freshness', S, '20 min, no revs reason is age'));
});

T('freshness: null fetchedAt keeps the shape', () => {
  const freshness = need(mod, 'freshness', 'freshness', S);
  const r = freshness(null, NOW, 7, 7);
  assertShape(r, 'null fetchedAt');
  if (r.stale) {
    assert.ok(typeof r.reason === 'string' && r.reason.length > 0,
      m('freshness', S, `null fetchedAt reported stale must name a reason (got ${r.reason})`));
  } else {
    assert.ok(!STALE_REASONS.includes(r.reason), m('freshness', S, 'null fetchedAt not stale → no stale reason'));
  }
});

T('freshness: uses the passed now, not the wall clock', () => {
  const freshness = need(mod, 'freshness', 'freshness', S);
  const past = Date.UTC(2001, 0, 1);
  assertFresh(freshness(past - 1 * MIN, past, 1, 1), 'fixed past now');
  const r = freshness(past - 20 * MIN, past, 1, 1);
  assert.equal(r.reason, 'age', m('freshness', S, 'uses the passed now, not Date.now()'));
});

// ---- relTime ----

T('relTime: under 45 s is "just now"', () => {
  const relTime = need(mod, 'relTime', 'relTime', S);
  for (const s of [0, 1, 30, 44]) {
    assert.equal(relTime(NOW - s * SEC, NOW), 'just now', m('relTime', S, `${s} s ago`));
  }
});

T('relTime: minutes', () => {
  const relTime = need(mod, 'relTime', 'relTime', S);
  assert.equal(relTime(NOW - 1 * MIN, NOW), '1 min ago', m('relTime', S, '60 s'));
  assert.equal(relTime(NOW - 4 * MIN, NOW), '4 min ago', m('relTime', S, '4 min'));
  assert.equal(relTime(NOW - 59 * MIN, NOW), '59 min ago', m('relTime', S, '59 min'));
});

T('relTime: hours', () => {
  const relTime = need(mod, 'relTime', 'relTime', S);
  assert.equal(relTime(NOW - 60 * MIN, NOW), '1 h ago', m('relTime', S, '60 min'));
  assert.equal(relTime(NOW - 5 * H, NOW), '5 h ago', m('relTime', S, '5 h'));
  assert.equal(relTime(NOW - 23 * H, NOW), '23 h ago', m('relTime', S, '23 h'));
});

T('relTime: days', () => {
  const relTime = need(mod, 'relTime', 'relTime', S);
  assert.equal(relTime(NOW - 24 * H, NOW), '1 d ago', m('relTime', S, '24 h'));
  assert.equal(relTime(NOW - 3 * D, NOW), '3 d ago', m('relTime', S, '3 d'));
});

T('relTime: future timestamps are "just now"', () => {
  const relTime = need(mod, 'relTime', 'relTime', S);
  for (const ahead of [1 * SEC, 5 * MIN, 2 * D]) {
    assert.equal(relTime(NOW + ahead, NOW), 'just now', m('relTime', S, `${ahead / SEC} s in the future`));
  }
});

// ---- scopeText ----

const CABLE = { one: 'cable', many: 'cables' };

T('scopeText: plural with scope', () => {
  const scopeText = need(mod, 'scopeText', 'scopeText', S);
  assert.equal(scopeText({ verb: 'Delete', count: 12, noun: CABLE, scope: 'Main Auditorium' }),
    'Delete 12 cables in Main Auditorium?', m('scopeText', S, 'contract example'));
});

T('scopeText: singular with scope', () => {
  const scopeText = need(mod, 'scopeText', 'scopeText', S);
  assert.equal(scopeText({ verb: 'Delete', count: 1, noun: CABLE, scope: 'Main Auditorium' }),
    'Delete 1 cable in Main Auditorium?', m('scopeText', S, 'count 1 uses noun.one'));
});

T('scopeText: without scope', () => {
  const scopeText = need(mod, 'scopeText', 'scopeText', S);
  assert.equal(scopeText({ verb: 'Delete', count: 12, noun: CABLE }), 'Delete 12 cables?',
    m('scopeText', S, 'scope omitted'));
  assert.equal(scopeText({ verb: 'Delete', count: 12, noun: CABLE, scope: '' }), 'Delete 12 cables?',
    m('scopeText', S, 'empty scope behaves as omitted'));
  assert.equal(scopeText({ verb: 'Move', count: 1, noun: { one: 'device', many: 'devices' } }), 'Move 1 device?',
    m('scopeText', S, 'singular, no scope, other verb'));
});

// ---- addNotice ----

const N = (text, extra) => Object.assign({ level: 'info', text, href: '#/p/campus/devices' }, extra || {});

T('addNotice: entry shape', () => {
  const addNotice = need(mod, 'addNotice', 'addNotice', S);
  const out = addNotice([], N('Saved 3 devices', { level: 'warn', href: '#/p/campus/rooms' }), NOW);
  assert.ok(Array.isArray(out), m('addNotice', S, 'returns an array'));
  assert.equal(out.length, 1);
  const e = out[0];
  for (const k of ['id', 'level', 'text', 'href', 't', 'read']) {
    assert.ok(k in e, m('addNotice', 'D8', `entry has ${k}`));
  }
  assert.ok(e.id !== undefined && e.id !== null && e.id !== '', m('addNotice', 'D8', 'id is set'));
  assert.equal(e.level, 'warn', m('addNotice', 'D8', 'level kept'));
  assert.equal(e.text, 'Saved 3 devices', m('addNotice', 'D8', 'text kept'));
  assert.equal(e.href, '#/p/campus/rooms', m('addNotice', 'D8', 'href kept'));
  assert.equal(e.t, NOW, m('addNotice', 'D8', 't is the passed now'));
  assert.equal(e.read, false, m('addNotice', 'D8', 'new notice is unread'));
  assert.deepEqual(JSON.parse(JSON.stringify(out)), out, m('addNotice', 'D8', 'list is JSON-serialisable (sessionStorage)'));
});

T('addNotice: returns a new list and does not mutate the input', () => {
  const addNotice = need(mod, 'addNotice', 'addNotice', S);
  const one = addNotice([], N('A'), NOW);
  const before = clone(one);
  const two = addNotice(one, N('B'), NOW + 5 * MIN);
  assert.notEqual(two, one, m('addNotice', S, 'new array returned'));
  assert.deepEqual(one, before, m('addNotice', S, 'input list unchanged'));
  assert.equal(two.length, 2);
  const deduped = addNotice(two, N('B'), NOW + 5 * MIN + 10 * SEC);
  assert.notEqual(deduped, two, m('addNotice', S, 'new array returned on dedupe too'));
  assert.equal(two.length, 2, m('addNotice', S, 'input untouched by dedupe'));
});

T('addNotice: newest first, unique ids', () => {
  const addNotice = need(mod, 'addNotice', 'addNotice', S);
  let list = [];
  list = addNotice(list, N('first'), NOW);
  list = addNotice(list, N('second'), NOW + 2 * MIN);
  list = addNotice(list, N('third'), NOW + 4 * MIN);
  assert.deepEqual(list.map((e) => e.text), ['third', 'second', 'first'], m('addNotice', S, 'newest first'));
  assert.deepEqual(list.map((e) => e.t), [NOW + 4 * MIN, NOW + 2 * MIN, NOW], m('addNotice', S, 't per entry'));
  assert.equal(new Set(list.map((e) => String(e.id))).size, 3, m('addNotice', S, 'ids are unique'));
});

T('addNotice: same text within 60 s is deduped', () => {
  const addNotice = need(mod, 'addNotice', 'addNotice', S);
  const base = addNotice(addNotice([], N('older'), NOW - 10 * MIN), N('Import finished'), NOW);
  for (const dt of [0, 30 * SEC, 59 * SEC]) {
    const out = addNotice(base, N('Import finished'), NOW + dt);
    assert.equal(out.length, base.length, m('addNotice', S, `same text after ${dt / SEC} s is deduped`));
    assert.equal(out.filter((e) => e.text === 'Import finished').length, 1, m('addNotice', S, 'one copy kept'));
    assert.equal(out[0].text, 'Import finished', m('addNotice', S, 'deduped notice stays first'));
  }
});

T('addNotice: same text after 61 s is not deduped', () => {
  const addNotice = need(mod, 'addNotice', 'addNotice', S);
  const base = addNotice([], N('Import finished'), NOW);
  const out = addNotice(base, N('Import finished'), NOW + 61 * SEC);
  assert.equal(out.length, 2, m('addNotice', S, 'repeat after 61 s is a new notice'));
  assert.equal(out[0].t, NOW + 61 * SEC, m('addNotice', S, 'new one is first'));
});

T('addNotice: different text within 60 s is kept', () => {
  const addNotice = need(mod, 'addNotice', 'addNotice', S);
  const out = addNotice(addNotice([], N('A'), NOW), N('B'), NOW + 1 * SEC);
  assert.equal(out.length, 2, m('addNotice', S, 'dedupe is by text only'));
});

T('addNotice: caps at 50, dropping the oldest', () => {
  const addNotice = need(mod, 'addNotice', 'addNotice', S);
  let list = [];
  for (let i = 0; i < 55; i++) list = addNotice(list, N('notice ' + i), NOW + i * 2 * MIN);
  assert.equal(list.length, 50, m('addNotice', 'D8', 'max 50'));
  assert.equal(list[0].text, 'notice 54', m('addNotice', S, 'newest kept first'));
  assert.equal(list[49].text, 'notice 5', m('addNotice', S, 'oldest five dropped'));
  assert.ok(!list.some((e) => e.text === 'notice 4'), m('addNotice', S, 'notice 4 dropped'));
  assert.equal(new Set(list.map((e) => String(e.id))).size, 50, m('addNotice', S, 'ids unique across 50'));
});
