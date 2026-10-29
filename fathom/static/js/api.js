// Fathom API client (§5) and the change queue (§6.3): batches ops, posts
// them with base_revision, handles rebases, conflicts and offline queueing.

import { touchedRefs } from './model-core.js';
import { formatShortCode, parseShortCode } from './search-core.js';

export class ApiError extends Error {
  constructor(message, status, code, details) {
    super(message || ('HTTP ' + status));
    this.name = 'ApiError';
    this.status = status || 0;
    this.code = code || '';
    this.details = details || {};
  }
}

// A `/changes` batch refused because the project is locked (settings.locked, §3.28 FR-UX-17):
// the server answers 423 with code "locked".
export function isLockedError(e) {
  return !!e && (e.code === 'locked' || e.status === 423);
}

function qs(params) {
  if (!params) return '';
  const parts = [];
  Object.keys(params).forEach(function (k) {
    const v = params[k];
    if (v === undefined || v === null || v === '') return;
    const vals = Array.isArray(v) ? [v.join(',')] : [v];
    vals.forEach(function (x) { parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(String(x))); });
  });
  return parts.length ? '?' + parts.join('&') : '';
}

function enc(s) {
  return encodeURIComponent(String(s));
}

export function createApi(opts) {
  opts = opts || {};
  const base = opts.base || '';
  const fetchImpl = opts.fetchImpl || (typeof fetch !== 'undefined' ? fetch.bind(typeof window !== 'undefined' ? window : globalThis) : null);

  function url(path, params) {
    return base + path + qs(params);
  }

  function request(method, path, body, extra) {
    extra = extra || {};
    const headers = { 'X-Fathom': '1', 'Accept': 'application/json' };
    let payload;
    if (body instanceof (typeof FormData !== 'undefined' ? FormData : function () {})) {
      payload = body;
    } else if (body instanceof (typeof Blob !== 'undefined' ? Blob : function () {})) {
      headers['Content-Type'] = body.type || 'application/octet-stream';
      payload = body;
    } else if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    if (extra.headers) Object.keys(extra.headers).forEach(function (k) { headers[k] = extra.headers[k]; });
    if (!fetchImpl) return Promise.reject(new ApiError('No fetch available', 0, 'offline'));
    return fetchImpl(url(path, extra.params), { method: method, headers: headers, body: payload, credentials: 'same-origin' }).then(function (res) {
      if (res.status === 204) return { data: null, res: res };
      const ct = (res.headers && res.headers.get && res.headers.get('Content-Type')) || '';
      const isJson = ct.indexOf('json') >= 0;
      const p = isJson ? res.json().catch(function () { return null; }) : res.text();
      return p.then(function (data) {
        if (!res.ok) {
          const d = isJson && data ? data : {};
          throw new ApiError(d.error || (typeof data === 'string' && data ? data.slice(0, 200) : 'HTTP ' + res.status), res.status, d.code || '', d.details || (typeof d.detail === 'string' && d.detail ? { detail: d.detail } : {}));
        }
        return { data: data, res: res };
      });
    }, function (err) {
      throw new ApiError((err && err.message) || 'Network error', 0, 'offline');
    });
  }
  function get(path, params) { return request('GET', path, undefined, { params: params }).then(function (r) { return r.data; }); }
  function send(method, path, body, params) { return request(method, path, body, { params: params }).then(function (r) { return r.data; }); }
  function proj(name) { return 'api/v2/projects/' + enc(name); }

  return {
    base: base,
    url: url,
    request: request,
    meta: function () { return get('api/v2/meta'); },
    session: function () { return get('api/v2/session'); },
    login: function (username, password) { return send('POST', 'api/v2/session', { username: username, password: password }); },
    logout: function () { return send('DELETE', 'api/v2/session'); },
    listProjects: function () { return get('api/v2/projects'); },
    createProject: function (o) { return send('POST', 'api/v2/projects', { name: o.name, template: o.template || 'blank', org: o.org || '' }); },
    // Moves the project to the trash (restorable from Settings › Trash); {purge: true} deletes it for good.
    deleteProject: function (name, o) { o = o || {}; return send('DELETE', proj(name), undefined, { confirm: name, purge: o.purge ? 1 : '' }); },
    listTrash: function () { return get('api/v2/trash'); },
    restoreTrash: function (name) { return send('POST', 'api/v2/trash/' + enc(name) + '/restore', {}); },
    purgeTrash: function (name) { return send('DELETE', 'api/v2/trash/' + enc(name)); },
    lookupCode: function (code) { return get('api/v2/codes/' + enc(parseShortCode(code) || String(code || '').trim())); },
    // Absolute link for a device short code (the QR / label target): <origin>/c/XXXX-XXXX.
    codeLink: function (code) {
      const path = base + 'c/' + formatShortCode(code);
      if (typeof location === 'undefined' || !location.href) return path.charAt(0) === '/' ? path : '/' + path;
      try { return new URL(path, location.href).href; } catch (e) { return path; }
    },
    labelPresets: function () { return get('api/v2/labels/presets'); },
    deviceLabelsUrl: function (name, params) { return url(proj(name) + '/labels/devices', params); },
    getProject: function (name) {
      return request('GET', proj(name)).then(function (r) {
        const d = r.data || {};
        const h = r.res && r.res.headers;
        return {
          name: d.name || name, doc: d.doc, revision: d.revision, problems: d.problems || [], role: d.role || 'admin',
          migrated_from: d.migrated_from || null,
          etag: (h && h.get && h.get('ETag')) || ('"r' + d.revision + '"'),
          offline: !!(h && h.get && h.get('X-Fathom-Offline')),
        };
      });
    },
    putProject: function (name, doc, baseRevision, summary) {
      return request('PUT', proj(name), { doc: doc, base_revision: baseRevision, summary: summary || '' }, { headers: { 'If-Match': '"r' + baseRevision + '"' } }).then(function (r) { return r.data; });
    },
    postChanges: function (name, baseRevision, ops, summary) { return send('POST', proj(name) + '/changes', { base_revision: baseRevision, ops: ops, summary: summary || '' }); },
    overlay: function (name) { return get(proj(name) + '/overlay'); },
    duplicates: function (name, o) { o = o || {}; return get(proj(name) + '/devices/duplicates', { device: o.device, min: o.min, limit: o.limit }); },
    mergePreview: function (name, survivor, duplicates, choices) { return send('POST', proj(name) + '/devices/merge/preview', { survivor: survivor, duplicates: duplicates, choices: choices || {} }); },
    mergeDevices: function (name, survivor, duplicates, choices, baseRevision) {
      return send('POST', proj(name) + '/devices/merge', { survivor: survivor, duplicates: duplicates, choices: choices || {}, base_revision: baseRevision });
    },
    channels: function (name, device) { return get(proj(name) + '/devices/' + enc(device) + '/channels'); },
    applyChannels: function (name, device) { return send('POST', proj(name) + '/devices/' + enc(device) + '/channels/apply', {}); },
    offlineManifest: function (name) { return get(proj(name) + '/offline-manifest'); },
    history: function (name, o) { o = o || {}; return get(proj(name) + '/history', { limit: o.limit, before: o.before }); },
    historyDoc: function (name, rev) { return get(proj(name) + '/history/' + enc(rev)); },
    historyDiff: function (name, rev, against) { return get(proj(name) + '/history/' + enc(rev) + '/diff', { against: against }); },
    restore: function (name, rev, baseRevision) { return send('POST', proj(name) + '/history/' + enc(rev) + '/restore', { base_revision: baseRevision }); },
    upload: function (name, target, files, params) {
      const fd = new FormData();
      Array.prototype.forEach.call(files || [], function (f) { fd.append('file', f, f.name); });
      return send('POST', proj(name) + '/' + target, fd, params);
    },
    importPreview: function (name, files, params) {
      const fd = new FormData();
      Array.prototype.forEach.call(files || [], function (f) { fd.append('file', f, f.name); });
      return send('POST', proj(name) + '/imports/preview', fd, params);
    },
    deleteImport: function (name, id, deleteFiles) { return send('DELETE', proj(name) + '/imports/' + enc(id), undefined, { delete_files: deleteFiles ? 1 : '' }); },
    importTemplateUrl: function (name, kind, table) { return url(proj(name) + '/imports/templates/' + enc(kind) + '/' + enc(table) + '.csv'); },
    inspectImport: function (name, id) { return get(proj(name) + '/imports/' + enc(id) + '/inspect'); },
    discoveryRuns: function (name) { return get(proj(name) + '/discovery/runs'); },
    startDiscovery: function (name, o) { return send('POST', proj(name) + '/discovery/runs', o || {}); },
    discoveryRun: function (name, id) { return get(proj(name) + '/discovery/runs/' + enc(id)); },
    cancelDiscovery: function (name, id) { return send('DELETE', proj(name) + '/discovery/runs/' + enc(id)); },
    discoveryFindings: function (name, id) { return get(proj(name) + '/discovery/runs/' + enc(id) + '/findings'); },
    discoveryDiff: function (name, id, against) { return get(proj(name) + '/discovery/runs/' + enc(id) + '/diff', against ? { against: against } : undefined); },
    discoveryPromote: function (name, id, body) { return send('POST', proj(name) + '/discovery/runs/' + enc(id) + '/findings/promote', body || {}); },
    discoverySettings: function (name) { return get(proj(name) + '/discovery/settings'); },
    saveDiscoverySettings: function (name, body) { return send('PUT', proj(name) + '/discovery/settings', body || {}); },
    discoveryTest: function (name, probe, settings) { return send('POST', proj(name) + '/discovery/test', { probe: probe, settings: settings || {} }); },
    schedule: function (name, kind, params) { return get(proj(name) + '/schedules/' + enc(kind), params); },
    scheduleUrl: function (name, kind, params) { return url(proj(name) + '/schedules/' + enc(kind), params); },
    tagPreview: function (name, scope, pattern) { return get(proj(name) + '/cables/tag-preview', { scope: scope, pattern: pattern }); },
    trace: function (name, params) { return get(proj(name) + '/trace', params); },
    search: function (name, q, o) { o = o || {}; return get(proj(name) + '/search', { q: q, limit: o.limit, kinds: o.kinds }); },
    // Assistant (§5.10, P4B): payload {question, room, use_llm, history[{role, text, attachments?}],
    // attachments?, manual_text?} is sent as given; the answer may carry llm, used_tools, proposal.
    ask: function (name, payload) { return send('POST', proj(name) + '/assistant', payload); },
    // Applies a proposal the assistant returned: body {proposal | id, base_revision} -> {revision, applied, summary}; 423 when locked.
    applyProposal: function (name, body) { return send('POST', proj(name) + '/assistant/apply', body || {}); },
    // Language-model settings (P4A, admin): providers catalogue, saved settings, model list and a connection test.
    llmProviders: function () { return get('api/v2/llm/providers'); },
    llmSettings: function () { return get('api/v2/llm/settings'); },
    saveLlmSettings: function (body) { return send('PUT', 'api/v2/llm/settings', body || {}); },
    llmModels: function (body) { return send('POST', 'api/v2/llm/models', body || {}); },
    llmTest: function (body) { return send('POST', 'api/v2/llm/test', body || {}); },
    qrUrl: function (name, device) { return url(proj(name) + '/qr/' + enc(device) + '.svg'); },
    rackSvgUrl: function (name, rack, face) { return url(proj(name) + '/racks/' + enc(rack) + '.svg', { face: face }); },
    floorplanImageUrl: function (name, fp, hide) { return url(proj(name) + '/floorplans/' + enc(fp) + '/image', { hide: hide }); },
    fileUrl: function (name, att) { return url(proj(name) + '/files/' + enc(att.id) + '/' + enc(att.name || 'file')); },
    deleteFile: function (name, attId) { return send('DELETE', proj(name) + '/files/' + enc(attId)); },
    builds: function (name) { return get(proj(name) + '/builds'); },
    build: function (name, o) { return send('POST', proj(name) + '/builds', o || {}); },
    deleteBuild: function (name, run) { return send('DELETE', proj(name) + '/builds/' + enc(run)); },
    library: function (params) { return get('api/v2/library', params); },
    presets: function () { return get('api/v2/presets'); },
    suggestModels: function (q) { return get('api/v2/library/suggest', q || {}); },
    template: function (id, project) { return get('api/v2/library/' + enc(id), { project: project }); },
    saveTemplate: function (t, override) { return send('POST', 'api/v2/library', t, { override: override ? 1 : '' }); },
    deleteTemplate: function (id) { return send('DELETE', 'api/v2/library/' + enc(id)); },
    users: function () { return get('api/v2/users'); },
    createUser: function (u) { return send('POST', 'api/v2/users', u); },
    updateUser: function (username, patch) { return send('PATCH', 'api/v2/users/' + enc(username), patch); },
    deleteUser: function (username) { return send('DELETE', 'api/v2/users/' + enc(username)); },
    changePassword: function (old, nw) { return send('POST', 'api/v2/users/me/password', { old: old, new: nw }); },
    backups: function () { return get('api/v2/backups'); },
    createBackup: function (o) { return send('POST', 'api/v2/backups', o || {}); },
    uploadBackup: function (file) { return send('POST', 'api/v2/backups/upload', new Blob([file], { type: 'application/zip' })); },
    backupUrl: function (name) { return url('api/v2/backups/' + enc(name)); },
    deleteBackup: function (name) { return send('DELETE', 'api/v2/backups/' + enc(name)); },
    restoreBackup: function (name) { return send('POST', 'api/v2/backups/' + enc(name) + '/restore', { confirm: name }); },
    pages: function (name, params) { return get(proj(name) + '/pages', params); },
    getPage: function (name, slug) { return get(proj(name) + '/pages/' + enc(slug)); },
    putPage: function (name, slug, page, baseRevision) { return send('PUT', proj(name) + '/pages/' + enc(slug), Object.assign({}, page, baseRevision ? { base_revision: baseRevision } : {})); },
    deletePage: function (name, slug) { return send('DELETE', proj(name) + '/pages/' + enc(slug)); },
    movePage: function (name, slug, o) { return send('POST', proj(name) + '/pages/' + enc(slug) + '/move', o || {}); },
    previewPage: function (name, body) { return send('POST', proj(name) + '/pages/preview', { body: body }); },
    pageVersions: function (name, slug) { return get(proj(name) + '/pages/' + enc(slug) + '/versions'); },
    pageVersion: function (name, slug, rev) { return get(proj(name) + '/pages/' + enc(slug) + '/versions/' + enc(rev)); },
    restorePage: function (name, slug, rev, baseRevision) { return send('POST', proj(name) + '/pages/' + enc(slug) + '/restore/' + enc(rev), { base_revision: baseRevision }); },
    pageQrUrl: function (name, slug, o) { o = o || {}; return url(proj(name) + '/qr/page/' + enc(slug) + '.svg', { share: o.share, scale: o.scale, ecl: o.ecl }); },
    pagesQrSheetUrl: function (name, o) { o = o || {}; return url(proj(name) + '/qr/pages.html', { room: o.room, share: o.share }); },
    publicPageUrl: function (name, slug, shareToken) { return url((shareToken ? 's/' + enc(shareToken) : 'p/' + enc(name)) + '/sop/' + enc(slug)); },
    completePage: function (name, slug) { return send('POST', proj(name) + '/pages/' + enc(slug) + '/complete', {}); },
    sopBundleUrl: function (name) { return url(proj(name) + '/sop/bundle.zip'); },
    problems: function (name, params) { return get(proj(name) + '/problems', params); },
    // body: a plain object (JSON) or a FormData with text/device/page/name/device_status and an optional photo
    reportProblem: function (name, body) { return send('POST', proj(name) + '/problems', body); },
    // "Suggest an improvement" (FR-UX-18): a problem report with kind "suggestion"; body {text, name?, url?, device?, page?}
    reportSuggestion: function (name, body) { return send('POST', proj(name) + '/problems', Object.assign({}, body || {}, { kind: 'suggestion' })); },
    patchProblem: function (name, id, patch) { return send('PATCH', proj(name) + '/problems/' + enc(id), patch); },
    // Scenes (FR-SCN, §5.6 "Scenes"): `sid` may be the literal 'base' where the server allows it.
    scenes: function (name) { return get(proj(name) + '/scenes'); },
    createScene: function (name, body) { return send('POST', proj(name) + '/scenes', body || {}); },
    patchScene: function (name, sid, body) { return send('PATCH', proj(name) + '/scenes/' + enc(sid), body || {}); },
    deleteScene: function (name, sid) { return send('DELETE', proj(name) + '/scenes/' + enc(sid)); },
    activateScene: function (name, sid) { return send('POST', proj(name) + '/scenes/' + enc(sid || 'base') + '/activate', {}); },
    saveScene: function (name, sid) { return send('POST', proj(name) + '/scenes/' + enc(sid) + '/save', {}); },
    sceneDiff: function (name, sid, against) { return get(proj(name) + '/scenes/' + enc(sid) + '/diff', { against: against || 'base' }); },
    sceneDoc: function (name, sid) { return get(proj(name) + '/scenes/' + enc(sid || 'base') + '/doc'); },
    shares: function (name) { return get(proj(name) + '/shares'); },
    createShare: function (name, o) { return send('POST', proj(name) + '/shares', o || {}); },
    deleteShare: function (name, token) { return send('DELETE', proj(name) + '/shares/' + enc(token)); },
  };
}

// ------------------------------------------------------------ change queue

const BACKOFF = [1000, 2000, 5000, 10000, 30000];

function makeEvent(type, detail) {
  const e = new Event(type);
  try { e.detail = detail; } catch (err) { Object.defineProperty(e, 'detail', { value: detail }); }
  return e;
}

function summarize(labels) {
  const uniq = [];
  labels.forEach(function (l) { if (l && uniq.indexOf(l) < 0) uniq.push(l); });
  if (!uniq.length) return '';
  if (uniq.length === 1) return uniq[0];
  return uniq.slice(0, 3).join('; ') + (uniq.length > 3 ? ' (+' + (uniq.length - 3) + ')' : '');
}

export class ChangeQueue extends EventTarget {
  constructor(o) {
    super();
    o = o || {};
    this.api = o.api;
    this.project = o.project;
    this.store = o.store;
    this.debounceMs = o.debounceMs === undefined ? 600 : o.debounceMs;
    this.maxBatch = o.maxBatch || 200;
    this.storage = o.storage === undefined ? null : o.storage;
    this.autosave = o.autosave === undefined ? true : !!o.autosave;
    this._items = [];
    this._timer = null;
    this._retry = 0;
    this._inflight = null;
    this._paused = false;
    this._conflict = null;
    this._state = 'idle';
    this._error = '';
    this._restored = this._load();
  }
  get key() { return 'fathom.pending.' + this.project; }
  get pending() {
    let n = 0;
    this._items.forEach(function (it) { n += it.ops.length; });
    return n;
  }
  get state() { return this._state; }
  get conflict() { return this._conflict; }
  // Ops restored from storage at construction; the shell re-applies them on the fresh doc.
  takeRestored() {
    const r = this._restored || [];
    this._restored = null;
    if (r.length) {
      this._items = r.slice();
      this._persist();
    }
    let ops = [];
    r.forEach(function (it) { ops = ops.concat(it.ops); });
    return ops;
  }
  _load() {
    if (!this.storage) return [];
    try {
      const raw = this.storage.getItem(this.key);
      if (!raw) return [];
      const v = JSON.parse(raw);
      const items = Array.isArray(v) ? v : (v && Array.isArray(v.items) ? v.items : (v && Array.isArray(v.ops) ? [{ ops: v.ops, label: v.label || 'Offline edits' }] : []));
      return items.filter(function (it) { return it && Array.isArray(it.ops) && it.ops.length; });
    } catch (err) {
      return [];
    }
  }
  _persist() {
    if (!this.storage) return;
    try {
      if (this._items.length) this.storage.setItem(this.key, JSON.stringify({ project: this.project, items: this._items }));
      else this.storage.removeItem(this.key);
    } catch (err) { /* storage full or disabled */ }
  }
  _emit(state, extra) {
    this._state = state;
    const detail = Object.assign({ state: state, pending: this.pending, revision: this.store ? this.store.revision : null, error: this._error || undefined, conflicts: this._conflict ? this._conflict.conflicts : undefined }, extra || {});
    this.dispatchEvent(makeEvent('state', detail));
    if (this.store && this.store.emit) this.store.emit('saving', detail);
  }
  setAutosave(b) {
    this.autosave = !!b;
    if (this.autosave && this._items.length) this._schedule(this.debounceMs);
  }
  enqueue(ops, label) {
    if (!ops || !ops.length) return;
    this._items.push({ ops: ops, label: label || '' });
    this._persist();
    if (this._paused) { this._emit(this._conflict ? 'conflict' : this._state); return; }
    this._emit(this._state === 'offline' ? 'offline' : 'pending');
    if (this.autosave) this._schedule(this.debounceMs);
  }
  _schedule(ms) {
    const self = this;
    if (this._timer) clearTimeout(this._timer);
    this._timer = setTimeout(function () { self._timer = null; self.flush(); }, ms);
  }
  _takeBatch() {
    const ops = [];
    const labels = [];
    let n = 0;
    while (n < this._items.length) {
      const it = this._items[n];
      if (ops.length && ops.length + it.ops.length > this.maxBatch) break;
      for (const op of it.ops) ops.push(op);
      labels.push(it.label);
      n++;
    }
    return { ops: ops, labels: labels, count: n };
  }
  flush() {
    const self = this;
    if (this._timer) { clearTimeout(this._timer); this._timer = null; }
    if (this._inflight) return this._inflight.then(function () { return self._items.length && !self._paused ? self.flush() : null; });
    if (this._paused || !this._items.length) {
      if (!this._items.length && !this._paused && this._state !== 'saved') this._emit('saved');
      return Promise.resolve(null);
    }
    const batch = this._takeBatch();
    const base = this.store ? this.store.revision : 0;
    this._emit('saving');
    this._inflight = this.api.postChanges(this.project, base, batch.ops, summarize(batch.labels)).then(function (res) {
      self._inflight = null;
      self._retry = 0;
      self._error = '';
      self._items.splice(0, batch.count);
      self._persist();
      if (self.store) self.store.setRevision(res.revision);
      if (res.problems && res.problems.length) self.dispatchEvent(makeEvent('problems', res.problems));
      if (res.rebased) {
        self.dispatchEvent(makeEvent('rebased', res));
        return self.resync().then(function () { return self._items.length ? self.flush() : (self._emit('saved'), null); });
      }
      if (self._items.length) return self.flush();
      self._emit('saved');
      return res;
    }, function (err) {
      self._inflight = null;
      if (err && err.status === 409 && err.code !== 'v2_required') {
        self._paused = true;
        self._conflict = { conflicts: (err.details && err.details.conflicts) || [], by: (err.details && err.details.by) || [], revision: err.details && err.details.revision, message: err.message };
        self._error = err.message;
        self._emit('conflict');
        return null;
      }
      if (!err || err.status === 0 || err.status >= 500 || err.status === 429) {
        const delay = BACKOFF[Math.min(self._retry, BACKOFF.length - 1)];
        self._retry++;
        self._error = (err && err.message) || 'offline';
        self._emit(err && err.status ? 'error' : 'offline', { retryIn: delay });
        self._schedule(delay);
        return null;
      }
      // Someone locked editing (423): every queued op would be refused too, so the whole queue is
      // dropped at once instead of one batch per retry; the shell shows the lock banner after resync.
      if (isLockedError(err)) {
        let all = [];
        self._items.forEach(function (it) { all = all.concat(it.ops); });
        self._items = [];
        self._persist();
        self._error = err.message;
        self._emit('error', { dropped: all.length, locked: true });
        self.dispatchEvent(makeEvent('dropped', { error: err, ops: all, locked: true }));
        return self.resync().catch(function () { return null; });
      }
      // validation / permission errors: drop this batch so the queue does not wedge
      self._items.splice(0, batch.count);
      self._persist();
      self._error = err.message;
      self._emit('error', { problems: err.details && err.details.problems, dropped: batch.ops.length });
      self.dispatchEvent(makeEvent('dropped', { error: err, ops: batch.ops }));
      return self.resync().catch(function () { return null; });
    });
    return this._inflight;
  }
  // Reload the doc from the server and re-apply the still-pending local ops on it.
  resync() {
    const self = this;
    if (!this.api || !this.store) return Promise.resolve(null);
    return this.api.getProject(this.project).then(function (p) {
      self.store.replaceDoc(p.doc, p.revision, 'load');
      let ops = [];
      self._items.forEach(function (it) { ops = ops.concat(it.ops); });
      if (ops.length) {
        try { self.store.applyRemote(ops, 'pending'); } catch (err) { self._items = []; self._persist(); }
      }
      return p;
    });
  }
  resolveConflict(mode) {
    const self = this;
    const conflict = this._conflict || { conflicts: [] };
    this._paused = false;
    this._conflict = null;
    this._error = '';
    if (mode === 'keep') {
      return this.api.getProject(this.project).then(function (p) {
        const pend = [];
        self._items.forEach(function (it) { pend.push(it); });
        self.store.replaceDoc(p.doc, p.revision, 'load');
        let ops = [];
        pend.forEach(function (it) { ops = ops.concat(it.ops); });
        try { if (ops.length) self.store.applyRemote(ops, 'pending'); } catch (err) { /* keep anyway, server decides */ }
        return self.flush();
      });
    }
    const bad = {};
    (conflict.conflicts || []).forEach(function (r) { bad[r] = true; });
    this._items = this._items.map(function (it) {
      return { label: it.label, ops: it.ops.filter(function (op) { return !bad[touchedRefs([op])[0]]; }) };
    }).filter(function (it) { return it.ops.length; });
    this._persist();
    return this.resync().then(function () { return self._items.length ? self.flush() : (self._emit('saved'), null); });
  }
}
