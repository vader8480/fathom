// Discovery view (network discovery, Phase 1: passive, ad hoc).
// Sources panel (per-probe mode / maturity / settings / Test), Run panel
// (start, live progress + log via 1 s polling, cancel) and Findings panel
// (new devices, matches, connections, networks, unresolved) with promote /
// merge / ignore. Nothing runs unless the Run button is pressed.

function h(tag, attrs, children) {
  const el = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k.indexOf('on') === 0 && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, String(v));
    });
  }
  (Array.isArray(children) ? children : (children == null ? [] : [children])).forEach(function (c) {
    if (c === null || c === undefined || c === false) return;
    el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  });
  return el;
}

function msg(e) { return (e && e.message) || String(e); }
function fmtTime(s) {
  if (!s) return '';
  const d = new Date(typeof s === 'number' ? s * 1000 : s);
  return isNaN(d.getTime()) ? String(s) : d.toLocaleString();
}
function pct(v) { return Math.round((Number(v) || 0) * 100) + '%'; }
function cap(s) { s = String(s || ''); return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }
function conf(level, value) {
  return h('span', { class: 'chip disc-conf disc-conf-' + (level || 'low'), title: 'confidence ' + pct(value) }, [h('i'), cap(level || 'low') + ' \u00b7 ' + pct(value)]);
}
function sourcesChips(list) {
  return h('span', { class: 'disc-srcs' }, (list || []).map(function (s) { return h('span', { class: 'chip disc-src' }, s); }));
}
function td(label, children, cls) { return h('td', { 'data-label': label, class: cls || null }, children); }
function thead(cols) { return h('thead', null, h('tr', null, cols.map(function (c) { return h('th', { scope: 'col' }, c); }))); }
function addrs(e) {
  const parts = [];
  (e.ips || []).forEach(function (ip) { parts.push(h('div', { class: 'mono' }, ip)); });
  (e.macs || []).forEach(function (m) { parts.push(h('div', { class: 'mono muted' }, m)); });
  if (e.hostname && e.hostname !== e.label) parts.push(h('div', { class: 'muted' }, e.hostname));
  return parts;
}
function detailsBlock(obj) {
  const pre = h('div', { class: 'adm-pre hidden' });
  const btn = h('button', { type: 'button', class: 'small ghost', 'aria-expanded': 'false', onclick: function () {
    const open = pre.classList.toggle('hidden');
    btn.setAttribute('aria-expanded', open ? 'false' : 'true');
    if (!open && !pre.textContent) pre.textContent = JSON.stringify(obj, null, 2);
  } }, 'Evidence');
  return [btn, pre];
}

export function mount(el, ctx) {
  const root = h('div', { class: 'adm disc' });
  el.appendChild(root);
  if (!ctx.api) {
    root.appendChild(h('div', { class: 'app-error-card' }, [h('h3', null, 'Needs the server'), h('div', null, 'Discovery talks to the Fathom server.')]));
    return { destroy: function () { el.innerHTML = ''; } };
  }
  const store = ctx.store;
  const ro = function () { return !!store.readOnly; };
  const S = { sources: [], settings: null, limits: { min_window: 10, max_window: 300 }, runs: [], active: '', run: null, findings: null, runId: '', tab: 'new',
    selected: {}, timer: null, caps: null, destroyed: false, loadingFindings: false };

  root.appendChild(h('h2', null, 'Discovery'));
  root.appendChild(h('p', { class: 'muted disc-intro' }, [
    'Passive network discovery: reads the UniFi controller you point it at and listens to what devices already announce (mDNS / Dante, LLDP / CDP) plus this host\u2019s ARP table. ',
    h('strong', null, 'Nothing runs unless you start it here'), ' \u2014 there is no scheduler and no background listener \u2014 and nothing is ever sent to an AV device or written to any device.',
  ]));

  // ------------------------------------------------------------ sources
  root.appendChild(h('h3', null, 'Sources'));
  const srcWrap = h('div', { class: 'adm-cards disc-sources' });
  root.appendChild(srcWrap);

  function fieldInput(src, f, cur) {
    const key = f.key;
    if (f.type === 'check') {
      const cb = h('input', { type: 'checkbox', id: 'disc-' + src.id + '-' + key, checked: !!cur[key] });
      return { el: h('div', { class: 'field check' }, [h('label', { for: cb.id }, f.label), cb]), read: function () { return cb.checked; }, input: cb };
    }
    const secret = !!f.secret;
    const isSet = !!cur[key + '_set'];
    const inp = h('input', { type: secret ? 'password' : 'text', id: 'disc-' + src.id + '-' + key, value: secret ? '' : (cur[key] || ''),
      placeholder: secret ? (isSet ? (cur[key + '_from_env'] ? 'set via environment \u2014 type to override' : 'set \u2014 leave blank to keep') : (f.placeholder || '')) : (cur[key + '_env'] ? 'env: ' + cur[key + '_env'] : (f.placeholder || '')),
      autocomplete: secret ? 'new-password' : 'off', spellcheck: 'false', autocapitalize: 'none' });
    const row = h('div', { class: 'field' }, [h('label', { for: inp.id }, f.label), inp]);
    if (f.help) row.appendChild(h('div', { class: 'muted disc-help' }, f.help));
    let clear = null;
    if (secret && isSet) {
      clear = h('button', { type: 'button', class: 'small ghost', title: 'Forget the stored ' + f.label.toLowerCase() }, 'Clear');
      clear.addEventListener('click', function () { clear.dataset.clear = '1'; inp.value = ''; inp.placeholder = 'will be cleared on save'; });
      row.appendChild(h('div', { class: 'disc-clear' }, clear));
    }
    return { el: row, input: inp, read: function () {
      if (secret) { if (clear && clear.dataset.clear === '1') return ''; return inp.value ? inp.value : null; }
      return inp.value.trim();
    } };
  }

  function lastRunFor(pid) {
    const r = S.run && S.run.summaries ? S.run.summaries[pid] : null;
    if (!r) return null;
    const bits = [];
    if (r.hosts !== undefined) bits.push(r.hosts + ' hosts');
    if (r.links) bits.push(r.links + ' links');
    if (r.networks) bits.push(r.networks + ' networks');
    return h('div', { class: 'muted disc-last' }, 'Last run: ' + (r.status || '') + (bits.length ? ' \u00b7 ' + bits.join(', ') : '') + (S.run.finished ? ' \u00b7 ' + fmtTime(S.run.finished) : ''));
  }

  function sourceCard(src) {
    const cur = src.settings || {};
    const enabled = h('input', { type: 'checkbox', id: 'disc-' + src.id + '-enabled', checked: cur.enabled !== false, disabled: ro() ? true : null });
    const fields = (src.fields || []).map(function (f) { return fieldInput(src, f, cur); });
    const out = h('div', { class: 'disc-test-out', 'aria-live': 'polite' });
    function collect() {
      const probe = { enabled: enabled.checked };
      (src.fields || []).forEach(function (f, i) {
        const v = fields[i].read();
        if (v !== null) probe[f.key] = v;
      });
      return probe;
    }
    const save = h('button', { type: 'button', class: 'small primary', disabled: ro() ? true : null, onclick: function () {
      save.disabled = true;
      const probes = {};
      probes[src.id] = collect();
      ctx.api.saveDiscoverySettings(ctx.project, { probes: probes }).then(function (r) {
        save.disabled = false;
        ctx.toast('Saved ' + src.label + ' settings', 'ok');
        S.settings = r.settings;
        return ctx.reload().then(loadAll);
      }, function (e) { save.disabled = false; ctx.toast(msg(e), 'err'); });
    } }, 'Save');
    const test = h('button', { type: 'button', class: 'small', disabled: ro() ? true : null, onclick: function () {
      test.disabled = true;
      out.innerHTML = '';
      out.appendChild(h('span', { class: 'muted' }, 'Testing\u2026'));
      const probe = collect();
      delete probe.enabled;
      ctx.api.discoveryTest(ctx.project, src.id, probe).then(function (r) {
        test.disabled = false;
        out.innerHTML = '';
        const res = r.result || {};
        out.appendChild(h('div', { class: res.ok ? 'disc-ok' : 'imp-warn' }, (res.ok ? '\u2713 ' : '\u26a0 ') + (res.message || (res.ok ? 'OK' : 'Failed'))));
      }, function (e) { test.disabled = false; out.innerHTML = ''; out.appendChild(h('div', { class: 'imp-warn' }, msg(e))); });
    } }, 'Test');
    const chips = h('div', { class: 'row disc-chips' }, [
      h('span', { class: 'chip disc-mode disc-mode-' + (src.mode || 'passive'), title: src.mode === 'active' ? 'Sends probe packets to devices' : 'Reads a controller or listens only' }, [h('i'), cap(src.mode || 'passive')]),
      h('span', { class: 'chip disc-maturity disc-maturity-' + (src.maturity || 'experimental') }, cap(src.maturity || 'experimental')),
      src.available ? null : h('span', { class: 'chip imp-chip-err' }, 'unavailable'),
    ]);
    return h('div', { class: 'adm-card disc-card', 'data-probe': src.id }, [
      h('div', { class: 'disc-card-head' }, [h('h4', null, src.label), h('label', { class: 'disc-enabled', for: enabled.id }, [enabled, ' enabled'])]),
      chips,
      h('div', { class: 'help' }, src.help || ''),
      src.sends ? h('div', { class: 'muted disc-sends' }, [h('strong', null, 'On the wire: '), src.sends]) : null,
      src.available ? null : h('div', { class: 'imp-warn' }, src.unavailable_reason || 'Not available on this server.'),
      h('div', { class: 'disc-fields' }, fields.map(function (f) { return f.el; })),
      h('div', { class: 'row', style: { marginTop: '6px' } }, [save, test]),
      out,
      lastRunFor(src.id),
    ]);
  }

  function drawSources() {
    srcWrap.innerHTML = '';
    if (!S.sources.length) { srcWrap.appendChild(h('div', { class: 'muted' }, 'The server did not list any discovery sources.')); return; }
    S.sources.forEach(function (s) { srcWrap.appendChild(sourceCard(s)); });
    if (S.caps && !S.caps.zeroconf) {
      srcWrap.appendChild(h('div', { class: 'adm-card disc-card disc-install' }, [
        h('h4', null, 'Optional extra not installed'),
        h('div', { class: 'help' }, 'mDNS / Dante listening needs the zeroconf package. Install the discovery extra on the server and restart it:'),
        h('div', { class: 'adm-pre' }, S.caps.install_hint || "pip install 'fathom-audio[discovery]'"),
        h('div', { class: 'muted', style: { fontSize: '12px' } }, 'The Docker image already includes it. UniFi and ARP work without it.'),
      ]));
    }
  }

  // ------------------------------------------------------------ run
  root.appendChild(h('h3', null, 'Run'));
  const windowInp = h('input', { type: 'number', min: 10, max: 300, step: 5, value: 60, inputmode: 'numeric', 'aria-label': 'Listen window in seconds', style: { width: '80px' } });
  const runBtn = h('button', { type: 'button', class: 'primary' }, 'Run discovery');
  const cancelBtn = h('button', { type: 'button', class: 'danger hidden' }, 'Cancel');
  const status = h('div', { class: 'disc-status', 'aria-live': 'polite' });
  const bar = h('div', { class: 'disc-bar' }, h('div', { class: 'disc-bar-fill' }));
  const log = h('div', { class: 'adm-pre disc-log hidden', 'aria-live': 'polite' });
  const runsWrap = h('div', { class: 'disc-runs' });
  runBtn.addEventListener('click', function () {
    if (ro()) return;
    runBtn.disabled = true;
    const w = Math.max(S.limits.min_window, Math.min(S.limits.max_window, parseInt(windowInp.value, 10) || 60));
    windowInp.value = w;
    ctx.api.startDiscovery(ctx.project, { window: w }).then(function (r) {
      S.run = r.run;
      S.runId = r.run.id;
      S.active = r.run.id;
      S.findings = null;
      S.selected = {};
      drawRun();
      drawFindings();
      poll();
    }, function (e) {
      runBtn.disabled = false;
      if (e && e.status === 409) {
        const rid = e.details && e.details.run;
        ctx.toast('A discovery run is already in progress' + (rid ? ' (' + rid + ')' : ''), 'warn');
        if (rid) { S.active = rid; S.runId = rid; poll(); }
      } else ctx.toast(msg(e), 'err');
    });
  });
  cancelBtn.addEventListener('click', function () {
    if (!S.runId) return;
    cancelBtn.disabled = true;
    ctx.api.cancelDiscovery(ctx.project, S.runId).then(function (r) { S.run = r.run; cancelBtn.disabled = false; drawRun(); poll(); }, function (e) { cancelBtn.disabled = false; ctx.toast(msg(e), 'err'); });
  });
  root.appendChild(h('div', { class: 'adm-card disc-run' }, [
    h('div', { class: 'row disc-run-row' }, [
      h('label', { class: 'disc-window' }, ['Listen window', windowInp, h('span', { class: 'muted' }, 's')]),
      runBtn, cancelBtn,
    ]),
    h('div', { class: 'muted disc-note' }, 'One run per project at a time. The enabled passive sources collect for the window (mDNS and LLDP listen for the whole window; UniFi and ARP are read once), then results are correlated against this project. Nothing keeps running afterwards.'),
    status, bar, log, runsWrap,
  ]));

  function drawRun() {
    const r = S.run;
    const active = !!(r && r.active);
    runBtn.disabled = ro() || active || (!!S.active && S.active !== (r && r.id));
    cancelBtn.classList.toggle('hidden', !active || ro());
    bar.classList.toggle('hidden', !r);
    if (!r) { status.textContent = S.active ? 'A run (' + S.active + ') is in progress in another session.' : 'No run yet.'; log.classList.add('hidden'); return; }
    const fill = bar.firstChild;
    fill.style.width = pct(r.progress);
    fill.className = 'disc-bar-fill disc-bar-' + (r.status || 'queued');
    const parts = [h('span', { class: 'chip disc-status-' + r.status }, [h('i'), cap(r.status)]), h('span', { class: 'mono muted' }, r.id)];
    if (active) parts.push(h('span', null, (r.stage || 'running') + (r.remaining !== undefined ? ' \u00b7 ' + Math.round(r.remaining) + ' s max left' : '')));
    else {
      if (r.finished) parts.push(h('span', { class: 'muted' }, fmtTime(r.finished) + (r.elapsed ? ' \u00b7 ' + Math.round(r.elapsed) + ' s' : '')));
      if (r.error) parts.push(h('span', { class: 'imp-warn' }, r.error));
      if (r.by) parts.push(h('span', { class: 'muted' }, 'by ' + r.by));
    }
    status.innerHTML = '';
    status.appendChild(h('div', { class: 'row' }, parts));
    const lines = r.log || [];
    log.classList.toggle('hidden', !lines.length);
    log.textContent = lines.map(function (x) { return (x.level === 'warn' || x.level === 'error' ? '! ' : '  ') + x.msg; }).join('\n');
    log.scrollTop = log.scrollHeight;
  }

  function drawRuns() {
    runsWrap.innerHTML = '';
    if (!S.runs.length) return;
    const sel = h('select', { 'aria-label': 'Previous runs' }, S.runs.map(function (r) {
      const c = r.counts || {};
      return h('option', { value: r.id, selected: r.id === S.runId ? true : null }, fmtTime(r.started || r.finished) + ' \u00b7 ' + (r.status || '') + (c.entities !== undefined ? ' \u00b7 ' + c.entities + ' hosts, ' + (c.connections || 0) + ' links' : ''));
    }));
    sel.addEventListener('change', function () { showRun(sel.value); });
    runsWrap.appendChild(h('div', { class: 'row', style: { marginTop: '8px' } }, [h('span', { class: 'muted' }, 'Show run'), sel]));
  }

  function stopPoll() { if (S.timer) { clearTimeout(S.timer); S.timer = null; } }
  function poll() {
    stopPoll();
    if (S.destroyed || !S.runId) return;
    ctx.api.discoveryRun(ctx.project, S.runId).then(function (r) {
      if (S.destroyed) return;
      S.run = r.run;
      drawRun();
      if (r.run.active) { S.timer = setTimeout(poll, 1000); return; }
      S.active = '';
      runBtn.disabled = ro();
      return ctx.api.discoveryRuns(ctx.project).then(function (rr) {
        if (S.destroyed) return;
        S.runs = rr.runs || [];
        S.sources = rr.sources || S.sources;
        drawRuns();
        drawSources();
        return loadFindings().then(function () { return ctx.reload(); });
      });
    }).catch(function (e) { if (!S.destroyed) { status.textContent = msg(e); runBtn.disabled = ro(); } });
  }

  function showRun(rid) {
    S.runId = rid;
    S.findings = null;
    S.selected = {};
    ctx.api.discoveryRun(ctx.project, rid).then(function (r) {
      S.run = r.run;
      drawRun();
      drawRuns();
      if (r.run.active) poll(); else loadFindings();
    }, function (e) { ctx.toast(msg(e), 'err'); });
  }

  // ------------------------------------------------------------ findings
  root.appendChild(h('h3', null, 'Findings'));
  const findWrap = h('div', { class: 'disc-findings' });
  root.appendChild(findWrap);

  function loadFindings() {
    if (!S.runId || !S.run || S.run.active) { drawFindings(); return Promise.resolve(); }
    S.loadingFindings = true;
    drawFindings();
    return ctx.api.discoveryFindings(ctx.project, S.runId).then(function (f) {
      S.loadingFindings = false;
      S.findings = f;
      drawFindings();
    }, function (e) { S.loadingFindings = false; findWrap.innerHTML = ''; findWrap.appendChild(h('div', { class: 'imp-warn' }, msg(e))); });
  }

  function promote(body, label) {
    if (ro()) { ctx.toast('Read-only', 'warn'); return Promise.resolve(); }
    const flush = ctx.flush ? ctx.flush() : Promise.resolve();
    return flush.then(function () { return ctx.api.discoveryPromote(ctx.project, S.runId, body); }).then(function (r) {
      const s = r.summary || {};
      const bits = [];
      if (s.devices) bits.push(s.devices + (s.devices === 1 ? ' device' : ' devices'));
      if (s.merged) bits.push(s.merged + ' merged');
      if (s.cables) bits.push(s.cables + (s.cables === 1 ? ' cable' : ' cables'));
      if (s.networks) bits.push(s.networks + (s.networks === 1 ? ' network' : ' networks'));
      if (s.ignored) bits.push(s.ignored + ' ignored');
      ctx.toast((label || 'Done') + (bits.length ? ': ' + bits.join(', ') : ''), 'ok');
      S.selected = {};
      return ctx.reload().then(function () { return ctx.api.overlay(ctx.project).then(function (o) { store.setOverlay(o); }, function () {}); }).then(loadFindings);
    }, function (e) { ctx.toast(msg(e), 'err'); });
  }

  function roomSelect() {
    const def = (S.findings && S.findings.room) || (store.doc.settings && store.doc.settings.default_room) || '';
    return h('select', { 'aria-label': 'Room for new devices' }, (store.doc.rooms || []).map(function (r) { return h('option', { value: r.id, selected: r.id === def ? true : null }, r.name || r.id); }));
  }

  function selBox(key) {
    const cb = h('input', { type: 'checkbox', 'aria-label': 'Select', checked: !!S.selected[key] });
    cb.addEventListener('change', function () { if (cb.checked) S.selected[key] = true; else delete S.selected[key]; updateBulk(); });
    return cb;
  }
  let bulkBar = null;
  function updateBulk() {
    if (!bulkBar) return;
    const n = Object.keys(S.selected).length;
    bulkBar.classList.toggle('hidden', !n);
    const lab = bulkBar.querySelector('.disc-bulk-n');
    if (lab) lab.textContent = n + ' selected';
  }

  function entityRow(e, cols, actions) {
    const key = 'e:' + e.id;
    const tr = h('tr', { class: 'disc-row disc-' + e.status }, [
      h('td', { class: 'disc-sel' }, actions ? selBox(key) : null),
      td('Device', [h('div', { class: 'disc-name' }, e.label), h('div', { class: 'muted' }, [e.manufacturer, e.model].filter(Boolean).join(' ') || (e.kind_hint ? e.kind_hint : ''))]),
      td('Kind', e.kind || ''),
    ].concat(cols).concat([
      td('Addresses', addrs(e)),
      td('Sources', sourcesChips(e.sources)),
      td('Confidence', [conf(e.level, e.confidence), e.reasons && e.reasons.length ? h('div', { class: 'muted disc-reasons' }, e.reasons.join(' \u00b7 ')) : null]),
      td('', actions || detailsBlock(e.observations), 'disc-actions'),
    ]));
    return tr;
  }

  function newDevicesTab(f) {
    const list = f.entities.filter(function (e) { return e.status === 'new'; });
    const room = roomSelect();
    const tb = h('tbody');
    list.forEach(function (e) {
      const acts = ro() ? detailsBlock(e.observations) : [
        h('button', { type: 'button', class: 'small primary', onclick: function () { promote({ entities: [e.id], room: room.value }, 'Promoted ' + e.label); } }, 'Promote'),
        h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ ignore: { entities: [e.id] } }, 'Ignored ' + e.label); } }, 'Ignore'),
      ].concat(detailsBlock(e.observations));
      tb.appendChild(entityRow(e, [], acts));
    });
    if (!list.length) return h('div', { class: 'muted' }, 'No new devices: every host seen matches a device already in the project (or was ignored).');
    bulkBar = h('div', { class: 'row disc-bulk hidden' }, [
      h('span', { class: 'disc-bulk-n' }, '0 selected'),
      h('button', { type: 'button', class: 'small primary', disabled: ro() ? true : null, onclick: function () {
        const ids = Object.keys(S.selected).filter(function (k) { return k.indexOf('e:') === 0; }).map(function (k) { return k.slice(2); });
        promote({ entities: ids, room: room.value }, 'Promoted ' + ids.length + ' devices');
      } }, 'Promote selected'),
      h('button', { type: 'button', class: 'small', disabled: ro() ? true : null, onclick: function () {
        const ids = Object.keys(S.selected).filter(function (k) { return k.indexOf('e:') === 0; }).map(function (k) { return k.slice(2); });
        promote({ ignore: { entities: ids } }, 'Ignored ' + ids.length + ' hosts');
      } }, 'Ignore selected'),
    ]);
    const all = h('input', { type: 'checkbox', 'aria-label': 'Select all' });
    all.addEventListener('change', function () {
      S.selected = {};
      if (all.checked) list.forEach(function (e) { S.selected['e:' + e.id] = true; });
      tb.querySelectorAll('.disc-sel input').forEach(function (cb) { cb.checked = all.checked; });
      updateBulk();
    });
    return h('div', null, [
      h('div', { class: 'row disc-toolbar' }, [h('label', { class: 'disc-room' }, ['Room for new devices ', room]), bulkBar]),
      h('table', { class: 'adm-table disc-table' }, [
        h('thead', null, h('tr', null, [h('th', { class: 'disc-sel' }, all)].concat(['Device', 'Kind', 'Addresses', 'Sources', 'Confidence', ''].map(function (c) { return h('th', { scope: 'col' }, c); })))),
        tb,
      ]),
    ]);
  }

  function matchesTab(f) {
    const list = f.entities.filter(function (e) { return e.status === 'match' || e.status === 'possible'; });
    if (!list.length) return h('div', { class: 'muted' }, 'No host matched a device already in the project.');
    const tb = h('tbody');
    list.forEach(function (e) {
      const m = e.match || {};
      const target = h('select', { 'aria-label': 'Merge into' }, [h('option', { value: m.device }, (m.name || m.device) + ' (' + pct(m.score) + ')')]
        .concat((m.others || []).map(function (o) { return h('option', { value: o.device }, (o.name || o.device) + ' (' + pct(o.score) + ')'); }))
        .concat((store.doc.devices || []).filter(function (d) { return d.id !== m.device && !(m.others || []).some(function (o) { return o.device === d.id; }); }).map(function (d) { return h('option', { value: d.id }, d.name || d.id); })));
      const newIfs = (e.interfaces || []).filter(function (i) { return !i.known; });
      const acts = ro() ? detailsBlock(e.observations) : [
        h('button', { type: 'button', class: 'small primary', onclick: function () {
          const merge = {};
          merge[e.id] = target.value;
          promote({ merge: merge }, 'Merged ' + e.label + ' into ' + target.options[target.selectedIndex].textContent);
        } }, 'Merge into'),
        e.proposed ? h('button', { type: 'button', class: 'small', title: 'Create a separate new device instead', onclick: function () { promote({ entities: [e.id] }, 'Promoted ' + e.label); } }, 'New device') : null,
        h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ ignore: { entities: [e.id] } }, 'Ignored ' + e.label); } }, 'Ignore'),
      ].concat(detailsBlock(e.observations));
      tb.appendChild(entityRow(e, [
        td('Matches', [
          h('div', { class: 'row' }, [h('span', { class: 'chip ' + (e.status === 'match' ? 'on' : '') }, e.status === 'match' ? 'Match' : 'Possible'), target]),
          h('div', { class: 'muted disc-reasons' }, (m.reasons || []).join(' \u00b7 ') + (newIfs.length ? ' \u00b7 adds ' + newIfs.length + (newIfs.length === 1 ? ' interface' : ' interfaces') : ' \u00b7 refreshes switch / port')),
        ]),
      ], acts));
    });
    return h('table', { class: 'adm-table disc-table' }, [
      h('thead', null, h('tr', null, [h('th', { class: 'disc-sel' })].concat(['Discovered', 'Kind', 'Matches', 'Addresses', 'Sources', 'Confidence', ''].map(function (c) { return h('th', { scope: 'col' }, c); })))),
      tb,
    ]);
  }

  function connectionsTab(f) {
    const rows = f.rows || [];
    if (!rows.length) return h('div', { class: 'muted' }, 'No switch-port connections were reported. LLDP on the switches and a UniFi controller give the best results.');
    const byId = {};
    (f.connections || []).forEach(function (c) { byId[c.id] = c; });
    const tb = h('tbody');
    const proposable = rows.filter(function (r) { return r.proposed && r.status === 'new'; });
    rows.forEach(function (r) {
      const c = byId[r.id] || {};
      const key = 'c:' + r.id;
      const can = r.proposed && r.status === 'new' && !ro();
      const flag = r.flag ? h('span', { class: 'chip disc-flag disc-flag-' + r.flag, title: { uplink: 'Switch-to-switch link', unmanaged: 'Several hosts share this port: an unmanaged switch, hub or AP hangs off it', via: 'Reached through an uplink; no direct cable', host: 'The port this Fathom server is plugged into' }[r.flag] || r.flag }, r.flag) : null;
      const stat = r.status === 'exists' ? h('span', { class: 'chip' }, 'in schedule') : (r.status === 'ignored' ? h('span', { class: 'chip' }, 'ignored') : null);
      const acts = [];
      if (can) acts.push(h('button', { type: 'button', class: 'small primary', onclick: function () { promote({ connections: [r.id] }, 'Added cable'); } }, 'Add cable'));
      if (!ro() && r.status !== 'ignored') acts.push(h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ ignore: { connections: [r.id] } }, 'Ignored connection'); } }, 'Ignore'));
      if (!ro() && r.status === 'ignored') acts.push(h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ unignore: { connections: [r.id] } }, 'Restored connection'); } }, 'Unignore'));
      tb.appendChild(h('tr', { class: 'disc-row' + (r.flag ? ' disc-flagged' : '') }, [
        h('td', { class: 'disc-sel' }, can ? selBox(key) : null),
        td('Tag', h('span', { class: 'muted' }, r.tag || '\u2014')),
        td('From room', r.from_room || ''), td('From device', r.from_device || ''), td('From port', r.from_port || ''),
        td('To room', r.to_room || ''), td('To device', r.to_device || ''), td('To port', r.to_port || h('span', { class: 'muted' }, '\u2014')),
        td('Medium', r.medium || ''), td('Type', r.type || ''), td('Length', h('span', { class: 'muted' }, '\u2014')),
        td('Confidence', [conf(r.level, r.confidence), h('div', { class: 'muted disc-reasons' }, (r.signal || '').split('/').join(' + '))]),
        td('Flags', [flag, stat, c.peers_on_port > 1 ? h('span', { class: 'muted' }, c.peers_on_port + ' on port') : null]),
        td('', acts.concat(detailsBlock(c.evidence || c)), 'disc-actions'),
      ]));
    });
    bulkBar = h('div', { class: 'row disc-bulk hidden' }, [
      h('span', { class: 'disc-bulk-n' }, '0 selected'),
      h('button', { type: 'button', class: 'small primary', disabled: ro() ? true : null, onclick: function () {
        const ids = Object.keys(S.selected).filter(function (k) { return k.indexOf('c:') === 0; }).map(function (k) { return k.slice(2); });
        promote({ connections: ids }, 'Added ' + ids.length + ' cables');
      } }, 'Add selected as cables'),
    ]);
    const all = h('input', { type: 'checkbox', 'aria-label': 'Select all proposed' });
    all.addEventListener('change', function () {
      S.selected = {};
      if (all.checked) proposable.forEach(function (r) { S.selected['c:' + r.id] = true; });
      tb.querySelectorAll('.disc-sel input').forEach(function (cb) { cb.checked = all.checked; });
      updateBulk();
    });
    return h('div', null, [
      h('div', { class: 'row disc-toolbar' }, [
        h('span', { class: 'muted' }, 'Generated connections, in cable-schedule columns. Only unflagged links at medium confidence or better can become cables; both ends must be in the project (promote or merge them first).'),
        bulkBar,
      ]),
      h('div', { class: 'disc-scroll' }, h('table', { class: 'adm-table disc-table disc-conn' }, [
        h('thead', null, h('tr', null, [h('th', { class: 'disc-sel' }, all)].concat(['Tag', 'From room', 'From device', 'From port', 'To room', 'To device', 'To port', 'Medium', 'Type', 'Length', 'Confidence', 'Flags', ''].map(function (c) { return h('th', { scope: 'col' }, c); })))),
        tb,
      ])),
    ]);
  }

  function networksTab(f) {
    const nets = f.networks || [];
    if (!nets.length) return h('div', { class: 'muted' }, 'No VLANs or subnets were reported (a UniFi controller provides them).');
    const tb = h('tbody');
    nets.forEach(function (n) {
      const acts = [];
      if (!ro() && n.status === 'new') {
        acts.push(h('button', { type: 'button', class: 'small primary', onclick: function () { promote({ networks: [n.id] }, 'Added network ' + n.name); } }, 'Add network'));
        acts.push(h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ ignore: { networks: [n.id] } }, 'Ignored ' + n.name); } }, 'Ignore'));
      }
      tb.appendChild(h('tr', { class: 'disc-row' }, [
        td('Network', [h('div', { class: 'disc-name' }, n.name || ('VLAN ' + n.vlan)), n.purpose ? h('div', { class: 'muted' }, n.purpose) : null]),
        td('VLAN', n.vlan === null || n.vlan === undefined ? h('span', { class: 'muted' }, '\u2014') : h('span', { class: 'mono' }, String(n.vlan))),
        td('Subnet', h('span', { class: 'mono' }, n.subnet || '')), td('Gateway', h('span', { class: 'mono' }, n.gateway || '')), td('DHCP', h('span', { class: 'mono' }, n.dhcp_range || '')),
        td('Hosts', n.hosts ? String(n.hosts) : ''),
        td('Sources', sourcesChips(n.sources)),
        td('Project', n.match ? h('span', { class: 'chip on', title: n.match.reason }, ['= ', n.match.name || n.match.network, n.match.differs && n.match.differs.length ? ' (differs: ' + n.match.differs.join(', ') + ')' : '']) : h('span', { class: 'chip' }, n.status === 'ignored' ? 'ignored' : 'new')),
        td('', acts.concat(detailsBlock(n.evidence)), 'disc-actions'),
      ]));
    });
    return h('table', { class: 'adm-table disc-table' }, [thead(['Network', 'VLAN', 'Subnet', 'Gateway', 'DHCP', 'Hosts', 'Sources', 'Project', '']), tb]);
  }

  function unresolvedTab(f) {
    const list = f.entities.filter(function (e) { return e.status === 'unresolved' || e.status === 'ignored'; });
    if (!list.length) return h('div', { class: 'muted' }, 'Nothing unresolved or ignored.');
    const tb = h('tbody');
    list.forEach(function (e) {
      const acts = ro() ? detailsBlock(e.observations) : (e.status === 'ignored'
        ? [h('button', { type: 'button', class: 'small', onclick: function () { promote({ unignore: { entities: [e.id] } }, 'Restored ' + e.label); } }, 'Unignore')]
        : [h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ ignore: { entities: [e.id] } }, 'Ignored ' + e.label); } }, 'Ignore')]).concat(detailsBlock(e.observations));
      tb.appendChild(entityRow(e, [td('Why', h('span', { class: 'muted' }, e.status === 'ignored' ? 'Ignored by you' : 'No MAC address and no name: cannot be told apart between runs'))], acts));
    });
    return h('table', { class: 'adm-table disc-table' }, [
      h('thead', null, h('tr', null, [h('th', { class: 'disc-sel' })].concat(['Host', 'Kind', 'Why', 'Addresses', 'Sources', 'Confidence', ''].map(function (c) { return h('th', { scope: 'col' }, c); })))),
      tb,
    ]);
  }

  function drawFindings() {
    findWrap.innerHTML = '';
    bulkBar = null;
    if (S.run && S.run.active) { findWrap.appendChild(h('div', { class: 'muted' }, 'Findings appear when the run finishes.')); return; }
    if (S.loadingFindings) { findWrap.appendChild(h('div', { class: 'muted' }, 'Loading findings\u2026')); return; }
    const f = S.findings;
    if (!f) { findWrap.appendChild(h('div', { class: 'muted' }, S.runs.length ? 'Pick a run above to see its findings.' : 'Run discovery to see what is on the network.')); return; }
    const c = f.counts || {};
    const tabs = [
      ['new', 'New devices', c.new || 0], ['match', 'Matches existing', (c.matched || 0) + (c.possible || 0)], ['conn', 'Connections', c.connections || 0],
      ['net', 'Networks / VLANs', c.networks || 0], ['unres', 'Unresolved', (c.unresolved || 0) + (c.ignored || 0)],
    ];
    const bar = h('div', { class: 'adm-tabs disc-tabs', role: 'tablist' }, tabs.map(function (t) {
      return h('button', { type: 'button', role: 'tab', class: 'small', 'aria-selected': S.tab === t[0] ? 'true' : 'false', 'data-tab': t[0], onclick: function () { S.tab = t[0]; S.selected = {}; drawFindings(); } }, t[1] + ' (' + t[2] + ')');
    }));
    findWrap.appendChild(h('div', { class: 'row disc-summary' }, [
      h('span', { class: 'chip' }, (c.entities || 0) + ' hosts seen'), h('span', { class: 'chip' }, (c.cables || 0) + ' cables proposed'),
      h('span', { class: 'muted' }, 'computed against revision ' + (f.revision || 0) + (f.computed ? ' at ' + fmtTime(f.computed) : '')),
    ]));
    findWrap.appendChild(bar);
    const body = h('div', { class: 'disc-tab-body', role: 'tabpanel' });
    findWrap.appendChild(body);
    body.appendChild({ new: newDevicesTab, match: matchesTab, conn: connectionsTab, net: networksTab, unres: unresolvedTab }[S.tab](f));
    (f.notes || []).slice(0, 12).forEach(function (n) { findWrap.appendChild(h('div', { class: 'muted', style: { fontSize: '12px' } }, n)); });
  }

  // ------------------------------------------------------------ boot
  function loadAll() {
    return Promise.all([ctx.api.discoveryRuns(ctx.project), ctx.api.discoverySettings(ctx.project)]).then(function (rs) {
      if (S.destroyed) return;
      const runs = rs[0], st = rs[1];
      S.runs = runs.runs || [];
      S.sources = st.sources || runs.sources || [];
      S.settings = st.settings || null;
      S.limits = st.limits || S.limits;
      S.caps = runs.capabilities || null;
      S.active = runs.active || '';
      if (S.settings && S.settings.window) windowInp.value = S.settings.window;
      windowInp.min = S.limits.min_window;
      windowInp.max = S.limits.max_window;
      drawSources();
      drawRuns();
      if (S.active) { S.runId = S.active; poll(); return; }
      if (!S.runId && S.runs.length) { showRun(S.runs[0].id); return; }
      drawRun();
      drawFindings();
    }, function (e) {
      if (S.destroyed) return;
      srcWrap.innerHTML = '';
      srcWrap.appendChild(h('div', { class: 'imp-warn' }, msg(e)));
      drawRun();
      drawFindings();
    });
  }
  drawRun();
  drawFindings();
  loadAll();

  return { destroy: function () { S.destroyed = true; stopPoll(); el.innerHTML = ''; } };
}
