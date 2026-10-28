// T2: js/api.js (W5) against SPEC §6.3, FR-MOB-08, FR-SEC-03 (fake fetch + fake storage, no network).
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, loadFixtureDoc, loadVocab, m, need } from './fixtures/helpers.mjs';

const { mod: api, skip: absent, error } = await loadModule('js/api.js', 'W5');
const mcL = await loadModule('js/model-core.js', 'W5');
const S = '§6.3';
const skip = absent || (error ? 'api.js failed to import (see failing test)' : (mcL.mod ? false : 'W5 model-core.js not present'));
const T = (name, fn) => test(name, { skip }, fn);

if (error) test('api.js imports in Node', () => { throw error; });

const vocab = loadVocab();

function jsonResponse(status, body, headers) {
  return new Response(JSON.stringify(body), { status, headers: Object.assign({ 'Content-Type': 'application/json' }, headers || {}) });
}

function fakeFetch(handler) {
  const calls = [];
  const fn = async (url, init) => {
    const h = new Headers((init && init.headers) || {});
    const call = { url: String(url), method: ((init && init.method) || 'GET').toUpperCase(), headers: h, body: init && init.body };
    calls.push(call);
    return handler(call, calls.length);
  };
  fn.calls = calls;
  return fn;
}

function fakeStorage() {
  const data = new Map();
  return {
    data,
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  };
}

async function settle(n = 20) {
  for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r));
}

T('requests send X-Fathom and Accept headers; errors become ApiError', async () => {
  const createApi = need(api, 'createApi', 'FR-SEC-03', S);
  const f = fakeFetch((call) => {
    if (/projects\/missing$/.test(call.url)) return jsonResponse(404, { error: 'not found', code: 'not_found', details: { x: 1 } });
    return jsonResponse(200, { name: 'sunday-demo', revision: 1, doc: loadFixtureDoc(), problems: [], role: 'admin' }, { ETag: '"r1"' });
  });
  const a = createApi({ base: '', fetchImpl: f });
  const got = await a.getProject('sunday-demo');
  assert.equal(got.revision, 1, m('§6.3', S, 'getProject -> {doc, revision, ...}'));
  assert.ok(got.doc && got.doc.devices, m('§6.3', S, 'getProject returns the doc'));
  const c = f.calls[0];
  assert.match(c.url, /api\/v2\/projects\/sunday-demo$/, m('§6.3', '§5.6', 'GET api/v2/projects/<n>'));
  assert.equal(c.headers.get('X-Fathom'), '1', m('FR-SEC-03', S, 'every request sends X-Fathom: 1'));
  assert.match(c.headers.get('Accept') || '', /application\/json/, m('§6.3', S, 'Accept: application/json'));
  const ApiError = need(api, 'ApiError', '§6.3', S);
  await assert.rejects(a.getProject('missing'), (e) => {
    assert.ok(e instanceof ApiError, m('§6.3', S, 'non-2xx -> ApiError'));
    assert.equal(e.status, 404); assert.equal(e.code, 'not_found', m('§6.3', S, 'ApiError.code from the error body'));
    return true;
  });
  await a.postChanges('sunday-demo', 1, [{ op: 'del', coll: 'cables', id: 'c-0001' }], 'x').catch(() => {});
  const post = f.calls[f.calls.length - 1];
  assert.equal(post.method, 'POST');
  assert.match(post.url, /api\/v2\/projects\/sunday-demo\/changes$/, m('§6.3', '§5.6', 'postChanges URL'));
  assert.match(post.headers.get('Content-Type') || '', /application\/json/, m('FR-SEC-03', S, 'JSON bodies with Content-Type application/json'));
  assert.equal(post.headers.get('X-Fathom'), '1', m('FR-SEC-03', S, 'mutating request sends X-Fathom: 1'));
  const body = JSON.parse(post.body);
  assert.equal(body.base_revision, 1, m('§5.4', S, 'changes body carries base_revision'));
  assert.equal(body.ops.length, 1);
});

T('ChangeQueue persists and flushes', async () => {
  const { ChangeQueue, createApi } = api;
  assert.ok(ChangeQueue && createApi, m('FR-MOB-08', S, 'ChangeQueue and createApi exported'));
  mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  try {
    const storage = fakeStorage();
    const key = 'fathom.pending.sunday-demo';
    let online = false;
    const posts = [];
    const f = fakeFetch((call) => {
      if (!online) return Promise.reject(new TypeError('Failed to fetch'));
      if (call.url.endsWith('/changes')) {
        const body = JSON.parse(call.body);
        posts.push(body);
        return jsonResponse(200, { revision: body.base_revision + 1, rebased: false, problems: [], touched: [] });
      }
      return jsonResponse(200, {});
    });
    const a = createApi({ base: '', fetchImpl: f });
    const store1 = mcL.mod.createStore({ doc: loadFixtureDoc(), vocab, readOnly: false, overlay: null, room: 'main' });
    store1.setRevision(1);
    const states = [];
    const q1 = new ChangeQueue({ api: a, project: 'sunday-demo', store: store1, debounceMs: 600, maxBatch: 200, storage });
    q1.addEventListener('state', (e) => states.push(e.detail && e.detail.state));
    const e1 = [{ op: 'merge', coll: 'devices', id: 'atem-mini', value: { name: 'Edit 1' } }];
    const e2 = [{ op: 'merge', coll: 'devices', id: 'sub-x2', value: { name: 'Edit 2' } }];
    store1.commit(e1, 'Edit 1'); q1.enqueue(e1, 'Edit 1');
    store1.commit(e2, 'Edit 2'); q1.enqueue(e2, 'Edit 2');
    assert.ok(q1.pending > 0, m('FR-MOB-08', S, 'pending count after 2 edits'));
    await q1.flush().catch(() => {});
    await settle();
    assert.ok(states.includes('offline'), m('FR-MOB-08', S, `network error emits state 'offline' (got ${JSON.stringify(states)})`));
    const saved = storage.getItem(key);
    assert.ok(saved, m('FR-MOB-08', S, `unsent ops persisted to storage["${key}"]`));
    const savedOps = JSON.stringify(JSON.parse(saved));
    assert.ok(savedOps.includes('Edit 1') && savedOps.includes('Edit 2'), m('FR-MOB-08', S, 'both edits persisted'));

    // "reload": a new queue restores from storage and flushes once online
    online = true;
    const store2 = mcL.mod.createStore({ doc: loadFixtureDoc(), vocab, readOnly: false, overlay: null, room: 'main' });
    store2.setRevision(1);
    const q2 = new ChangeQueue({ api: a, project: 'sunday-demo', store: store2, debounceMs: 600, maxBatch: 200, storage });
    if (q2.pending === 0 && typeof q2.takeRestored === 'function') {
      // W5 restores in two steps (constructor loads, shell re-applies via takeRestored); not in the §6.3 contract (T2 notes).
      const restored = q2.takeRestored();
      store2.applyRemote(restored, 'pending');
    }
    assert.ok(q2.pending > 0, m('FR-MOB-08', S, 'pending ops restored on startup'));
    await q2.flush();
    await settle();
    assert.equal(posts.length, 1, m('FR-MOB-08', S, `2 queued edits flush as exactly one request (one new revision), got ${posts.length}`));
    assert.equal(posts[0].ops.length, 2, m('FR-MOB-08', S, 'the request carries both edits in order'));
    assert.equal(posts[0].ops[0].id, 'atem-mini'); assert.equal(posts[0].ops[1].id, 'sub-x2');
    assert.equal(posts[0].base_revision, 1, m('FR-MOB-08', S, 'sent with the last known revision'));
    assert.equal(q2.pending, 0, m('FR-MOB-08', S, 'nothing pending after flush'));
    const left = storage.getItem(key);
    assert.ok(!left || JSON.parse(left).length === 0 || (JSON.parse(left).ops || []).length === 0, m('FR-MOB-08', S, 'storage cleared after a successful flush'));
    assert.equal(store2.revision, 2, m('§6.3', S, 'store revision updated on success'));
  } finally {
    mock.timers.reset();
  }
});

T('ChangeQueue conflict pauses', async () => {
  const { ChangeQueue, createApi } = api;
  mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  try {
    const f = fakeFetch((call) => jsonResponse(409, { error: 'Someone else changed 1 item', code: 'conflict', details: { revision: 5, conflicts: ['devices/atem-mini'], by: ['sam'] } }));
    const store = mcL.mod.createStore({ doc: loadFixtureDoc(), vocab, readOnly: false, overlay: null, room: 'main' });
    store.setRevision(1);
    const ev = [];
    const q = new ChangeQueue({ api: createApi({ fetchImpl: f }), project: 'sunday-demo', store, storage: null });
    q.addEventListener('state', (e) => ev.push(e.detail));
    const ops = [{ op: 'merge', coll: 'devices', id: 'atem-mini', value: { name: 'x' } }];
    store.commit(ops, 'x'); q.enqueue(ops, 'x');
    await q.flush().catch(() => {});
    await settle();
    const c = ev.find((d) => d && d.state === 'conflict');
    assert.ok(c, m('FR-HIST-06', S, '409 emits state conflict'));
    assert.deepEqual(c.conflicts, ['devices/atem-mini'], m('FR-HIST-06', S, 'conflict carries details.conflicts'));
    const n = f.calls.length;
    await q.flush().catch(() => {});
    await settle();
    assert.equal(f.calls.length, n, m('FR-HIST-06', S, 'queue pauses until resolveConflict'));
    assert.equal(typeof q.resolveConflict, 'function', m('FR-HIST-06', S, "resolveConflict('reload'|'keep') exists"));
  } finally {
    mock.timers.reset();
  }
});

T('importTemplateUrl builds the import template download path', () => {
  const a = api.createApi({ base: '/', fetchImpl: fakeFetch(() => jsonResponse(200, {})) });
  assert.equal(a.importTemplateUrl('my show', 'csv', 'devices'), '/api/v2/projects/my%20show/imports/templates/csv/devices.csv');
});

// ---- P1C: trash, short codes and label sheets (SPEC §6.3)

T('trash and project delete URLs', async () => {
  const f = fakeFetch(() => jsonResponse(200, { items: [], retention_days: 30 }));
  const a = api.createApi({ base: '/', fetchImpl: f });
  await a.listTrash();
  assert.equal(f.calls[0].method, 'GET'); assert.equal(f.calls[0].url, '/api/v2/trash');
  await a.restoreTrash('my show');
  assert.equal(f.calls[1].method, 'POST'); assert.equal(f.calls[1].url, '/api/v2/trash/my%20show/restore');
  assert.equal(f.calls[1].headers.get('X-Fathom'), '1');
  await a.purgeTrash('my show');
  assert.equal(f.calls[2].method, 'DELETE'); assert.equal(f.calls[2].url, '/api/v2/trash/my%20show');
  await a.deleteProject('my show');
  assert.equal(f.calls[3].method, 'DELETE');
  assert.equal(f.calls[3].url, '/api/v2/projects/my%20show?confirm=my%20show', 'without purge the project moves to the trash');
  await a.deleteProject('my show', { purge: true });
  assert.equal(f.calls[4].url, '/api/v2/projects/my%20show?confirm=my%20show&purge=1');
  await a.deleteProject('my show', { purge: false });
  assert.equal(f.calls[5].url, '/api/v2/projects/my%20show?confirm=my%20show');
});

T('lookupCode normalises the code; codeLink and label URLs are pure', async () => {
  const f = fakeFetch(() => jsonResponse(200, { project: 'campus-demo', device: 'foh-cl5', name: 'FOH CL5', room: 'main', kind: 'console' }));
  const a = api.createApi({ base: '/', fetchImpl: f });
  const r = await a.lookupCode('abcd-2345');
  assert.equal(r.device, 'foh-cl5');
  assert.equal(f.calls[0].method, 'GET');
  assert.equal(f.calls[0].url, '/api/v2/codes/ABCD2345', 'dash stripped, upper-cased');
  await a.lookupCode('ABCD2345');
  assert.equal(f.calls[1].url, '/api/v2/codes/ABCD2345');
  await a.lookupCode('not a code');
  assert.equal(f.calls[2].url, '/api/v2/codes/not%20a%20code', 'anything else is passed through for the server to reject');
  assert.equal(a.codeLink('ABCD2345'), '/c/ABCD-2345', 'no location in Node: a root-relative link');
  assert.equal(api.createApi({ base: '', fetchImpl: f }).codeLink('abcd-2345'), '/c/ABCD-2345');
  assert.equal(a.deviceLabelsUrl('my show', { preset: 'avery-5160', room: 'main', ids: ['a', 'b'] }),
    '/api/v2/projects/my%20show/labels/devices?preset=avery-5160&room=main&ids=a%2Cb');
  assert.equal(a.deviceLabelsUrl('my show'), '/api/v2/projects/my%20show/labels/devices');
  assert.equal(f.calls.length, 3, 'deviceLabelsUrl and codeLink do not fetch');
  await a.labelPresets();
  assert.equal(f.calls[3].url, '/api/v2/labels/presets');
});

// ---- P2B: suggestions and lock errors (SPEC §3.28 FR-UX-17/18, §6.3)

T('reportSuggestion posts kind=suggestion; isLockedError recognises 423 and code locked', async () => {
  const f = fakeFetch(() => jsonResponse(201, { id: 'p1', forwarded: false }));
  const a = api.createApi({ base: '/', fetchImpl: f });
  const r = await a.reportSuggestion('my show', { text: 'Bigger buttons', name: 'sam', url: 'http://x/#/my%20show', kind: 'bug' });
  assert.equal(r.id, 'p1');
  assert.equal(f.calls[0].method, 'POST');
  assert.equal(f.calls[0].url, '/api/v2/projects/my%20show/problems');
  assert.equal(f.calls[0].headers.get('X-Fathom'), '1');
  const body = JSON.parse(f.calls[0].body);
  assert.equal(body.kind, 'suggestion', 'kind is always suggestion, whatever the caller passed');
  assert.equal(body.text, 'Bigger buttons');
  assert.equal(body.name, 'sam');
  assert.equal(body.url, 'http://x/#/my%20show');
  await a.reportSuggestion('my show');
  assert.deepEqual(JSON.parse(f.calls[1].body), { kind: 'suggestion' }, 'no body still posts the kind');
  const isLockedError = need(api, 'isLockedError', 'FR-UX-17', S);
  assert.equal(isLockedError({ status: 423 }), true);
  assert.equal(isLockedError({ code: 'locked' }), true);
  assert.equal(isLockedError({ status: 409, code: 'conflict' }), false);
  assert.equal(isLockedError(null), false);
  assert.equal(isLockedError(undefined), false);
  assert.equal(isLockedError(new Error('x')), false);
});

T('ChangeQueue drops every queued op on 423 locked and reloads the doc', async () => {
  const { ChangeQueue, createApi } = api;
  mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  try {
    const storage = fakeStorage();
    const serverDoc = loadFixtureDoc();
    serverDoc.settings = Object.assign({}, serverDoc.settings, { locked: true, locked_by: 'sam' });
    const f = fakeFetch((call) => {
      if (call.method === 'POST') return jsonResponse(423, { error: 'Editing is locked by sam', code: 'locked' });
      return jsonResponse(200, { name: 'sunday-demo', revision: 7, doc: serverDoc, problems: [], role: 'admin' });
    });
    const store = mcL.mod.createStore({ doc: loadFixtureDoc(), vocab, readOnly: false, overlay: null, room: 'main' });
    store.setRevision(1);
    const dropped = [];
    const states = [];
    const q = new ChangeQueue({ api: createApi({ fetchImpl: f }), project: 'sunday-demo', store, storage, debounceMs: 600, maxBatch: 1 });
    q.addEventListener('dropped', (e) => dropped.push(e.detail));
    q.addEventListener('state', (e) => states.push(e.detail));
    const op1 = [{ op: 'merge', coll: 'devices', id: 'atem-mini', value: { name: 'x' } }];
    const op2 = [{ op: 'merge', coll: 'devices', id: 'atem-mini', value: { name: 'y' } }];
    store.commit(op1, 'x'); q.enqueue(op1, 'x');
    store.commit(op2, 'y'); q.enqueue(op2, 'y');
    const posts = () => f.calls.filter((c) => c.method === 'POST').length;
    await q.flush().catch(() => {});
    await settle();
    assert.equal(posts(), 1, 'the first 423 stops the flush; nothing is retried');
    assert.equal(dropped.length, 1, 'one dropped event for the whole queue');
    assert.equal(dropped[0].locked, true, 'dropped.detail.locked marks the lock case');
    assert.equal(dropped[0].ops.length, 2, 'every queued op is dropped, not just the failing batch');
    assert.equal(api.isLockedError(dropped[0].error), true);
    assert.ok(states.some((d) => d && d.state === 'error' && d.locked === true && d.dropped === 2), 'state error carries dropped count and locked flag');
    assert.equal(store.doc.settings.locked, true, 'the doc is reloaded from the server');
    assert.equal(store.revision, 7);
    assert.equal(store.doc.devices.find((d) => d.id === 'atem-mini').name, serverDoc.devices.find((d) => d.id === 'atem-mini').name, 'pending local edits are gone after the reload');
    const pend = storage.getItem('fathom.pending.sunday-demo');
    assert.ok(!pend || JSON.parse(pend).length === 0, 'persisted queue is cleared');
    await q.flush().catch(() => {});
    await settle();
    assert.equal(posts(), 1, 'an empty queue does not post again');
  } finally {
    mock.timers.reset();
  }
});
