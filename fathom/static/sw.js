/* Fathom service worker (ES2018). Scope = the app root; URLs are relative to it.
 * Precache the app shell, network-first for viewer pages and project docs,
 * stale-while-revalidate for /static/, network only for everything else.
 * Rack images (static/rack-images/) are never precached; they are kept in their
 * own runtime cache, which outlives VERSION bumps. */
'use strict';

const VERSION = '0.5.1';
const SHELL_CACHE = 'fathom-shell-' + VERSION;
const PAGES_CACHE = 'fathom-pages-' + VERSION;
const IMAGES_CACHE = 'fathom-images-1';
const NETWORK_TIMEOUT_MS = 3000;

const PRECACHE = [
  './', 'static/app.html', 'static/login.html', 'static/css/app.css', 'static/css/patchview.css', 'static/css/plan.css',
  'static/js/app.js', 'static/js/api.js', 'static/js/model-core.js', 'static/js/inspector.js', 'static/js/assistant-ui.js',
  'static/js/patchtable.js', 'static/js/patchtable-core.js', 'static/js/patchview.js', 'static/js/patchview-core.js',
  'static/js/floorplan.js', 'static/js/floorplan-core.js', 'static/js/rack.js', 'static/js/rack-core.js',
  'static/js/schedules.js', 'static/js/inventory.js', 'static/js/views-admin.js', 'static/js/presets-core.js', 'static/js/suggest-ui.js',
  'static/js/views-sop.js', 'static/css/sop.css', 'static/js/console-core.js', 'static/js/trace-ui.js', 'static/css/trace.css',
  'static/icons/icon-192.png', 'manifest.webmanifest',
  // UI uplift (docs/ui-audit.md B.2 SHELL item 8); install tolerates files that are not there yet (page-rack.js).
  'static/js/router-core.js', 'static/js/dom.js', 'static/js/explorer.js', 'static/js/explorer-core.js',
  'static/js/entity-header.js', 'static/js/entity-core.js', 'static/js/datatable.js', 'static/js/datatable-core.js',
  'static/js/drawer.js', 'static/js/drawer-core.js', 'static/js/search.js', 'static/js/search-core.js',
  'static/js/home.js', 'static/js/home-core.js', 'static/js/feedback.js', 'static/js/feedback-core.js',
  'static/js/wizard.js', 'static/js/wizard-core.js', 'static/js/page-device.js', 'static/js/page-room.js',
  'static/js/page-rack.js', 'static/js/views-discovery.js', 'static/js/merge-ui.js',
  'static/js/tour.js', 'static/css/tour.css', 'static/js/improve-ui.js', 'static/js/scenes.js', 'static/css/scenes.css',
  'static/css/explorer.css', 'static/css/entity-header.css', 'static/css/datatable.css', 'static/css/drawer.css',
  'static/css/search.css', 'static/css/home.css', 'static/css/feedback.css', 'static/css/wizard.css',
  'static/css/page-device.css', 'static/css/page-room.css', 'static/css/rack.css', 'static/css/inventory.css',
  'static/css/schedules.css', 'static/css/admin.css', 'static/css/discovery.css', 'static/css/inspector.css',
  'static/css/patchtable.css',
  // Rackula features; install tolerates files that are not there yet (rack-toolbar.css, page-rack.css).
  'static/js/rack-elevation.js', 'static/js/rack-display.js', 'static/js/rack-display-core.js',
  'static/js/rack-palette.js', 'static/js/rack-palette-core.js', 'static/js/rack-export.js', 'static/js/rack-export-core.js',
  'static/css/rack-toolbar.css', 'static/css/rack-palette.css', 'static/css/rack-export.css', 'static/css/page-rack.css',
  'static/js/speech.js', 'static/js/assistant-core.js', 'static/css/assistant.css'
];

const SCOPE = new URL(self.registration ? self.registration.scope : self.location.href);
const ROOT = SCOPE.pathname.endsWith('/') ? SCOPE.pathname : SCOPE.pathname + '/';

function rel(url) {
  // path relative to the app root, or null when outside it
  if (url.origin !== self.location.origin) return null;
  if (url.pathname.indexOf(ROOT) !== 0) return null;
  return url.pathname.slice(ROOT.length);
}

function abs(path) {
  return new URL(path, SCOPE).toString();
}

self.addEventListener('install', function (event) {
  event.waitUntil(caches.open(SHELL_CACHE).then(function (cache) {
    return Promise.all(PRECACHE.map(function (p) {
      return cache.addAll([abs(p)]).catch(function () { return null; });
    }));
  }));
});

self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.map(function (k) {
      if (k.indexOf('fathom-') === 0 && k !== SHELL_CACHE && k !== PAGES_CACHE && k !== IMAGES_CACHE) return caches.delete(k);
      return null;
    }));
  }).then(function () { return self.clients.claim(); }));
});

function neverCache(path) {
  return path === 'api/v2/session' || path === 'login' || /^builds\/.*\.zip$/.test(path);
}

function timeout(ms) {
  return new Promise(function (_, reject) { setTimeout(function () { reject(new Error('timeout')); }, ms); });
}

function markOffline(resp) {
  if (!resp) return resp;
  const headers = new Headers(resp.headers);
  headers.set('X-Fathom-Offline', '1');
  return resp.blob().then(function (body) {
    return new Response(body, { status: resp.status, statusText: resp.statusText, headers: headers });
  });
}

function networkFirst(request, cacheName, timeoutMs, offlineHeader) {
  const net = fetch(request).then(function (resp) {
    if (resp && resp.ok && resp.type !== 'opaqueredirect') {
      const copy = resp.clone();
      caches.open(cacheName).then(function (c) { return c.put(request, copy); }).catch(function () {});
    }
    return resp;
  });
  const race = timeoutMs ? Promise.race([net, timeout(timeoutMs)]) : net;
  return race.catch(function () {
    return caches.match(request, { ignoreVary: true }).then(function (hit) {
      if (hit) return offlineHeader ? markOffline(hit) : hit;
      return net;
    });
  });
}

function staleWhileRevalidate(event, cacheName) {
  const request = event.request;
  return caches.open(cacheName).then(function (cache) {
    return cache.match(request).then(function (hit) {
      const update = fetch(request).then(function (resp) {
        if (resp && resp.ok) cache.put(request, resp.clone()).catch(function () {});
        return resp;
      });
      if (hit) {
        event.waitUntil(update.catch(function () {}));
        return hit;
      }
      return update;
    });
  });
}

self.addEventListener('fetch', function (event) {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  const path = rel(url);
  if (path === null || neverCache(path)) return;
  if (request.mode === 'navigate' && (/^p\//.test(path) || /^s\//.test(path))) {
    event.respondWith(networkFirst(request, PAGES_CACHE, NETWORK_TIMEOUT_MS, false));
    return;
  }
  if (/^api\/v2\/projects\/[^/]+$/.test(path) || path === 'api/v2/meta') {
    event.respondWith(networkFirst(request, PAGES_CACHE, 0, true));
    return;
  }
  if (/^static\/rack-images\//.test(path)) {
    event.respondWith(staleWhileRevalidate(event, IMAGES_CACHE));
    return;
  }
  if (/^static\//.test(path)) {
    event.respondWith(staleWhileRevalidate(event, SHELL_CACHE));
    return;
  }
  if (path === '' || path === 'manifest.webmanifest') {
    event.respondWith(networkFirst(request, SHELL_CACHE, NETWORK_TIMEOUT_MS, false));
  }
});

self.addEventListener('message', function (event) {
  const data = event.data || {};
  if (data.type === 'fathom:skip-waiting') {
    self.skipWaiting();
    return;
  }
  if (data.type !== 'fathom:prefetch' || !Array.isArray(data.urls)) return;
  const failed = [];
  let ok = 0;
  const work = caches.open(PAGES_CACHE).then(function (cache) {
    return Promise.all(data.urls.map(function (u) {
      const target = abs(String(u));
      return fetch(target, { credentials: 'same-origin' }).then(function (resp) {
        if (!resp.ok) throw new Error(String(resp.status));
        ok += 1;
        return cache.put(target, resp);
      }).catch(function () { failed.push(u); });
    }));
  }).then(function () {
    if (event.source && event.source.postMessage) {
      event.source.postMessage({ type: 'fathom:prefetched', ok: ok, failed: failed });
    }
  });
  if (event.waitUntil) event.waitUntil(work);
});
