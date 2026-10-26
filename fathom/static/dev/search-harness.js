// Harness for js/search.js (dev/search.html). Supplies the ctx members the
// palette uses (docs/ui-audit.md B.2 SHELL item 4) and records navigations in
// window.__sr.
//   ?project=<name>  project served by this server (default campus-demo)
//   ?fixture=1       fixture-v2.json doc with api null (offline search)
//   ?role=viewer     ctx.role (drafts are hidden from viewers)
//   ?recent=device:atem-mini,room:main   seed ctx.recent
//   ?q=<text>&cat=<category>             open the palette on load
//   ?smoke=1         writes data-smoke on <html> once ready
import { createApi } from '../js/api.js';
import { layoutFor, sectionsFor, parseRoute, buildRoute, mergeRoute } from '../js/router-core.js';
import { openSearch } from '../js/search.js';

window.__fathomErrors = window.__fathomErrors || [];
(function () {
  const errs = window.__fathomErrors;
  window.addEventListener('error', function (e) { errs.push(String((e && e.message) || e)); });
  window.addEventListener('unhandledrejection', function (e) { errs.push('unhandled: ' + String((e && e.reason && (e.reason.stack || e.reason.message)) || (e && e.reason))); });
})();

const params = new URLSearchParams(location.search);
const fixture = params.has('fixture');
const project = fixture ? 'sunday-demo' : (params.get('project') || 'campus-demo');
const role = params.get('role') || 'admin';
const appRoot = location.pathname.replace(/static\/dev\/[^/]*$/, '');

function log(text) {
  const ul = document.getElementById('h-log');
  const li = document.createElement('li');
  li.textContent = text;
  ul.insertBefore(li, ul.firstChild);
}

// D8 fathom.ui.recent.<project>: {type: [{id, t}]}, newest first, max 8, deduped.
function makeRecent(name) {
  const key = 'fathom.ui.recent.' + name;
  function read() {
    try {
      const o = JSON.parse(localStorage.getItem(key) || '{}');
      return o && typeof o === 'object' && !Array.isArray(o) ? o : {};
    } catch (e) {
      return {};
    }
  }
  return {
    push: function (type, id) {
      const all = read();
      const list = (Array.isArray(all[type]) ? all[type] : []).filter(function (e) { return e && e.id !== id; });
      list.unshift({ id: id, t: Date.now() });
      all[type] = list.slice(0, 8);
      try { localStorage.setItem(key, JSON.stringify(all)); } catch (e) { /* private mode */ }
      window.__sr.recents.push(type + ':' + id);
      log('recent.push ' + type + ' ' + id);
    },
    list: function (type) {
      const all = read();
      return (Array.isArray(all[type]) ? all[type] : []).map(function (e) { return e.id; });
    },
  };
}

function loadDoc(api) {
  if (fixture) {
    return fetch('fixture-v2.json').then(function (r) {
      if (!r.ok) throw new Error('fixture-v2.json: HTTP ' + r.status);
      return r.json();
    });
  }
  return api.getProject(project).then(function (p) { return p.doc; });
}

function main() {
  const api = fixture ? null : createApi({ base: appRoot });
  let route = parseRoute(location.hash || ('#/' + project + '/main/patch'));
  if (!route.project) route = parseRoute('#/' + project + '/main/patch');
  window.__sr = { navigations: [], recents: [], ctx: null };
  return loadDoc(api).then(function (doc) {
    const recent = makeRecent(project);
    (params.get('recent') || '').split(',').filter(Boolean).reverse().forEach(function (s) {
      const i = s.indexOf(':');
      if (i > 0) recent.push(s.slice(0, i), s.slice(i + 1));
    });
    window.__sr.recents = [];
    const ctx = {
      store: { doc: doc, readOnly: role === 'viewer' },
      api: api,
      project: project,
      role: role,
      get route() { return JSON.parse(JSON.stringify(route)); },
      navigateRoute: function (partial, o) {
        route = mergeRoute(route, partial);
        const hash = buildRoute(route);
        window.__sr.navigations.push({ partial: partial, hash: hash, replace: !!(o && o.replace) });
        document.getElementById('h-route').textContent = hash;
        log('navigateRoute ' + hash);
        return hash;
      },
      routeHref: function (partial) { return buildRoute(mergeRoute(route, partial)); },
      recent: recent,
      projects: [{ name: project, title: project }],
      sections: sectionsFor(role),
      layout: function () { return layoutFor(window.innerWidth); },
      toast: function (msg) { log('toast ' + msg); },
    };
    window.__sr.ctx = ctx;
    document.getElementById('h-route').textContent = buildRoute(route);
    document.getElementById('h-status').textContent = (fixture ? 'fixture sunday-demo, offline' : project + ', online') + ' \u00b7 role ' + role + ' \u00b7 ' + (doc.devices || []).length + ' devices';
    const open = function () { openSearch(ctx); };
    document.getElementById('app-search').addEventListener('click', open);
    document.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && String(e.key).toLowerCase() === 'k') { e.preventDefault(); open(); }
    });
    if (params.has('q') || params.has('cat')) openSearch(ctx, { query: params.get('q') || '', category: params.get('cat') || 'all' });
  });
}

function ready(ok) {
  if (!params.has('smoke')) return;
  setTimeout(function () {
    document.documentElement.setAttribute('data-smoke', JSON.stringify({ ready: ok, errors: window.__fathomErrors }));
  }, 300);
}

main().then(function () { ready(true); }, function (err) {
  window.__fathomErrors.push('harness: ' + String((err && (err.stack || err.message)) || err));
  document.getElementById('h-status').textContent = 'Failed: ' + String((err && err.message) || err);
  ready(false);
});
