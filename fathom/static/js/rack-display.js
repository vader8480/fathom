// Rack display (DOM side): template summaries for the rack views, fetched from the library in
// batches and cached per project and id (docs/SPEC.md §6.13.11). Pure parts: rack-display-core.js.

export const CHUNK = 100;

// `<project>\u0000<id>` → {value: summary|null} once settled, or {pending: Promise} in flight.
const cache = new Map();

function key(project, id) {
  return project + '\u0000' + id;
}

export function clearTemplateInfoCache() {
  cache.clear();
}

function projectTemplates(ctx) {
  const doc = ctx && ctx.store && ctx.store.doc;
  const out = {};
  const list = doc && Array.isArray(doc.templates) ? doc.templates : [];
  for (let i = 0; i < list.length; i++) {
    const t = list[i];
    if (t && typeof t.id === 'string' && t.id && !Object.prototype.hasOwnProperty.call(out, t.id)) out[t.id] = t;
  }
  return out;
}

function uniqueIds(ids) {
  const seen = {};
  const out = [];
  (Array.isArray(ids) ? ids : []).forEach(function (id) {
    if (typeof id === 'string' && id && !seen[id]) { seen[id] = true; out.push(id); }
  });
  return out;
}

// One library request for `chunk`; settles every id in it. A failed request leaves the ids
// uncached so a later call retries them.
function fetchChunk(ctx, project, chunk) {
  let p;
  try {
    p = Promise.resolve(ctx.api.library({ids: chunk.join(','), project: project}));
  } catch (e) {
    p = Promise.reject(e);
  }
  const done = p.then(function (res) {
    const list = Array.isArray(res) ? res : (res && Array.isArray(res.templates) ? res.templates : []);
    const found = {};
    list.forEach(function (t) { if (t && typeof t.id === 'string') found[t.id] = t; });
    chunk.forEach(function (id) {
      cache.set(key(project, id), {value: Object.prototype.hasOwnProperty.call(found, id) ? found[id] : null});
    });
  }, function () {
    chunk.forEach(function (id) {
      const k = key(project, id);
      const e = cache.get(k);
      if (e && e.pending === done) cache.delete(k);
    });
  });
  chunk.forEach(function (id) { cache.set(key(project, id), {pending: done}); });
  return done;
}

// Promise of {id: summary} for the ids that resolve. Project templates (`ctx.store.doc.templates`)
// come from the store without a request; the rest from the cache or `ctx.api.library`, only the
// missing ids, in chunks of CHUNK. Unknown ids are cached as misses and left out. Never rejects.
export function loadTemplateInfo(ctx, ids) {
  const want = uniqueIds(ids);
  const local = projectTemplates(ctx);
  const project = (ctx && ctx.project) || '';
  const hasApi = !!(ctx && ctx.api && typeof ctx.api.library === 'function');
  const missing = [];
  const waits = [];
  want.forEach(function (id) {
    if (Object.prototype.hasOwnProperty.call(local, id)) return;
    const e = cache.get(key(project, id));
    if (e && e.pending) { if (waits.indexOf(e.pending) < 0) waits.push(e.pending); }
    else if (!e && hasApi) missing.push(id);
  });
  for (let i = 0; i < missing.length; i += CHUNK) waits.push(fetchChunk(ctx, project, missing.slice(i, i + CHUNK)));
  return Promise.all(waits).then(function () {
    const out = {};
    want.forEach(function (id) {
      if (Object.prototype.hasOwnProperty.call(local, id)) { out[id] = local[id]; return; }
      const e = cache.get(key(project, id));
      if (e && e.value) out[id] = e.value;
    });
    return out;
  }, function () { return {}; });
}

// The settled summary for `id` without a request: a project template, else the cached library
// summary; null for a known miss, undefined when not loaded yet.
export function peekTemplateInfo(ctx, id) {
  const local = projectTemplates(ctx);
  if (Object.prototype.hasOwnProperty.call(local, id)) return local[id];
  const e = cache.get(key((ctx && ctx.project) || '', id));
  if (!e || e.pending) return undefined;
  return e.value;
}
