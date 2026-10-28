// XPT dev harness: openRackExport on the inline doc of dev/rack-export.html
// with a stub ctx (store.doc, vocab from /api/v2/meta, a stub library API that
// answers {templates} and resolves attachments to a static image).
// window.__rx = {ctx, open(opts), results, last}. Query: ?smoke=1 sets
// data-smoke; ?api=0 drops ctx.api; ?open=1 opens the dialog on load.
window.__fathomErrors = window.__fathomErrors || [];
(function () {
  const errs = window.__fathomErrors;
  window.addEventListener('error', function (e) { errs.push(String((e && e.message) || e)); });
  window.addEventListener('unhandledrejection', function (e) { errs.push('unhandled: ' + String(e && e.reason && (e.reason.stack || e.reason.message) || e.reason)); });
})();

const params = new URLSearchParams(location.search);

async function main() {
  const rx = await import('../js/rack-export.js');
  const dom = await import('../js/dom.js');
  const doc = JSON.parse(document.getElementById('rx-h-doc').textContent);
  const meta = await fetch('/api/v2/meta', {headers: {Accept: 'application/json'}}).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
  const root = new URL('../../', location.href).href;
  const calls = [];
  const api = params.get('api') === '0' ? null : {
    base: root,
    library: function (q) {
      calls.push(q);
      const ids = String(q.ids || '').split(',');
      const all = [{id: 'demo-sw8', name: '8-port switch', kind: 'switch', ru: 1, rack_category: 'network', image_front: 'missing/demo-sw8.front.webp'}];
      return Promise.resolve({templates: all.filter(function (t) { return ids.indexOf(t.id) >= 0; })});
    },
    fileUrl: function (project, att) { return root + 'static/icons/' + encodeURIComponent(att.name); },
  };
  const ctx = {
    store: {doc: doc, vocab: meta && meta.vocab, readOnly: true},
    vocab: (meta && meta.vocab) || {},
    project: 'harness-demo',
    api: api,
    appRoot: root,
    ensureCss: function () { return Promise.resolve(); },
    toast: function (m, level) { log('toast ' + (level || 'info') + ': ' + m); },
  };
  const logEl = document.getElementById('rx-h-log');
  function log(text) { logEl.insertBefore(dom.h('li', null, text), logEl.firstChild); }
  const state = {ctx: ctx, results: [], calls: calls, last: null};
  window.__rx = state;
  state.open = function (o) {
    const p = rx.openRackExport(ctx, o || {racks: ['rk-audio', 'rk-video'], face: undefined});
    state.last = p;
    return p.then(function (res) { state.results.push(res); log('closed: ' + JSON.stringify(res)); return res; });
  };
  document.getElementById('rx-h-open').addEventListener('click', function () { state.open({racks: ['rk-audio', 'rk-video']}); });
  document.getElementById('rx-h-open-one').addEventListener('click', function () { state.open({racks: ['rk-audio'], face: 'rear'}); });
  if (params.get('open') === '1') state.open();
  if (params.has('smoke')) {
    setTimeout(function () {
      document.documentElement.setAttribute('data-smoke', JSON.stringify({ready: true, errors: window.__fathomErrors, stats: null}));
    }, 200);
  }
}

main().catch(function (err) {
  window.__fathomErrors.push('harness: ' + String(err && (err.stack || err.message) || err));
  if (params.has('smoke')) document.documentElement.setAttribute('data-smoke', JSON.stringify({ready: false, errors: window.__fathomErrors, stats: null}));
});
