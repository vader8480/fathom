// Discovery view (network discovery: passive probes plus opt-in read-only active ones).
// Route discovery/<tab>?run=<id> (docs/ui-audit.md D1, B.3 DISC): the tab is one of the
// findings tabs or `runs`; with no tab the latest run's `new` tab shows (replace).
// Run panel at the top (start, live progress + log via 1 s polling, cancel; editors only),
// sources collapsed into details.disc-sources (per-probe mode / maturity / settings / Test;
// active cards are off by default and say what they send), then the findings tabs (new
// devices, matches, connections, networks, unresolved) as DataTables with promote / merge /
// ignore in each row. The Changes tab diffs the shown run against an earlier completed run
// (new / missing / moved devices, changed addresses, new / lost links). Nothing runs unless
// the Run button is pressed.
// Each new / matched host carries the server's library model suggestions
// (findings[].model_suggestions); the chosen template travels with promote /
// merge as body.templates so the device is set up like Add gear would.

import { h } from './dom.js';
import { createTable } from './datatable.js';
import { skeleton, emptyState, inlineError, confirmScope, staleBadge, reviewBadge } from './feedback.js';
import { suggestionControl, defaultChoice } from './suggest-ui.js';

export const TABS = ['new', 'matches', 'connections', 'networks', 'unresolved', 'changes', 'runs'];
const DEFAULT_TAB = 'new';

function msg(e) { return (e && e.message) || String(e); }
function fmtTime(s) {
  if (!s) return '';
  const d = new Date(typeof s === 'number' ? s * 1000 : s);
  return isNaN(d.getTime()) ? String(s) : d.toLocaleString();
}
function epochMs(s) {
  if (!s) return null;
  const t = typeof s === 'number' ? s * 1000 : Date.parse(s);
  return isNaN(t) ? null : t;
}
function pct(v) { return Math.round((Number(v) || 0) * 100) + '%'; }
function cap(s) { s = String(s || ''); return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }
function conf(level, value) {
  return h('span', { class: 'chip disc-conf disc-conf-' + (level || 'low'), title: 'confidence ' + pct(value) }, [h('i'), cap(level || 'low') + ' \u00b7 ' + pct(value)]);
}
function sourcesChips(list) {
  return h('span', { class: 'disc-srcs' }, (list || []).map(function (s) { return h('span', { class: 'chip disc-src' }, s); }));
}
function dash() { return h('span', { class: 'muted' }, '\u2014'); }
function addrs(e) {
  const parts = [];
  (e.ips || []).forEach(function (ip) { parts.push(h('div', { class: 'mono' }, ip)); });
  const macs = e.macs || [];
  macs.slice(0, 3).forEach(function (m) { parts.push(h('div', { class: 'mono muted' }, m)); });
  if (macs.length > 3) parts.push(h('div', { class: 'muted small' }, '+' + (macs.length - 3) + ' more MAC addresses'));
  if (e.hostname && e.hostname !== e.label) parts.push(h('div', { class: 'muted' }, e.hostname));
  return h('div', { class: 'disc-addrs' }, parts);
}
function addrText(e) { return (e.ips || []).concat(e.macs || []).concat(e.hostname && e.hostname !== e.label ? [e.hostname] : []).join(' '); }
function detailsBlock(obj) {
  const pre = h('div', { class: 'adm-pre hidden' });
  const btn = h('button', { type: 'button', class: 'small ghost', 'aria-expanded': 'false', onclick: function () {
    const open = pre.classList.toggle('hidden');
    btn.setAttribute('aria-expanded', open ? 'false' : 'true');
    if (!open && !pre.textContent) pre.textContent = JSON.stringify(obj, null, 2);
  } }, 'Evidence');
  return [btn, pre];
}
function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

// Effective "enabled" of a source card: active probes only when explicitly switched on.
export function sourceEnabled(src) {
  const cur = (src && src.settings) || {};
  if (src && src.mode === 'active') return cur.enabled === true;
  return cur.enabled !== false;
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
  const route0 = ctx.route || { tab: '', query: {} };
  const S = { sources: [], settings: null, limits: { min_window: 10, max_window: 300 }, runs: [], active: '', run: null, findings: null, runId: '',
    tab: TABS.indexOf(route0.tab) >= 0 ? route0.tab : DEFAULT_TAB, timer: null, caps: null, destroyed: false, loadingFindings: false, findingsError: null,
    diff: null, diffAgainst: '', loadingDiff: false, loaded: false, memo: {}, models: {}, targets: {}, tables: [], primary: null, room: '' };

  // ------------------------------------------------------------ header: title, run age, review badge
  const ageSlot = h('span', { class: 'disc-age', hidden: true });
  const age = staleBadge({ fetchedAt: null, label: 'Run', always: true });
  ageSlot.appendChild(age);
  const reviewSlot = h('span', { class: 'disc-review' });
  root.appendChild(h('div', { class: 'disc-head' }, [h('h2', null, 'Discovery'), h('span', { class: 'disc-badges' }, [ageSlot, reviewSlot])]));

  function drawBadges() {
    const r = S.run;
    const at = r && !r.active ? epochMs(r.finished || r.started) : null;
    ageSlot.hidden = at === null;
    age.update({ fetchedAt: at });
    reviewSlot.innerHTML = '';
    const c = S.findings && S.findings.run === S.runId ? (S.findings.counts || {}) : null;
    const n = c ? (c.unresolved || 0) : 0;
    const b = reviewBadge({ count: n, label: 'unresolved', title: 'Hosts that cannot be told apart between runs', onClick: function () { goTab('unresolved'); } });
    if (b) reviewSlot.appendChild(b);
  }

  // ------------------------------------------------------------ URL (D1)
  function primaryUrl() {
    return {
      get: function () { const r = ctx.route; return (r && r.query) || {}; },
      set: function (patch) { if (ctx.setParams) ctx.setParams(patch); },
    };
  }
  function canonical(replace) {
    const r = ctx.route || { tab: '', query: {} };
    const q = Object.assign({}, r.query || {});
    if (S.runId) q.run = S.runId;
    if (r.tab !== S.tab || (S.runId && (r.query || {}).run !== S.runId)) {
      if (ctx.navigateRoute) ctx.navigateRoute({ tab: S.tab, query: q }, { replace: replace !== false });
    }
  }
  // Tab and run changes push a new URL first (the shell calls route() synchronously, which redraws),
  // so the new primary table reads that URL's q/sort/pg rather than the previous tab's.
  function goTab(tab) {
    if (TABS.indexOf(tab) < 0) tab = DEFAULT_TAB;
    if (tab === S.tab) return;
    if (ctx.navigateRoute) ctx.navigateRoute({ tab: tab, query: S.runId ? { run: S.runId } : {} });
    if (S.tab !== tab) { S.tab = tab; drawFindings(); }
  }
  function goRun(rid) {
    if (!rid || rid === S.runId) return;
    if (ctx.navigateRoute) ctx.navigateRoute({ tab: S.tab, query: { run: rid } });
    if (S.runId !== rid) showRun(rid);
  }

  // ------------------------------------------------------------ run
  const windowInp = h('input', { type: 'number', min: 10, max: 300, step: 5, value: 60, inputmode: 'numeric', 'aria-label': 'Listen window in seconds', style: { width: '80px' } });
  const runBtn = h('button', { type: 'button', class: 'primary disc-run-btn' }, 'Run discovery');
  const cancelBtn = h('button', { type: 'button', class: 'danger hidden disc-cancel' }, 'Cancel');
  const status = h('div', { class: 'disc-status', 'aria-live': 'polite' });
  const bar = h('div', { class: 'disc-bar' }, h('div', { class: 'disc-bar-fill' }));
  const log = h('div', { class: 'adm-pre disc-log', 'aria-live': 'polite' });
  const logSum = h('summary', null, 'Run log');
  const logWrap = h('details', { class: 'disc-log-wrap hidden' }, [logSum, log]);
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
      S.findingsError = null;
      S.diff = null;
      S.diffAgainst = '';
      logWrap.open = true;
      if (ctx.setParams) ctx.setParams({ run: S.runId });
      drawRun();
      drawFindings();
      poll();
    }, function (e) {
      runBtn.disabled = false;
      if (e && e.status === 409) {
        const rid = e.details && e.details.run;
        ctx.toast('A discovery run is already in progress' + (rid ? ' (' + rid + ')' : ''), 'warn');
        if (rid) { S.active = rid; S.runId = rid; if (ctx.setParams) ctx.setParams({ run: rid }); poll(); }
      } else ctx.toast(msg(e), 'err');
    });
  });
  cancelBtn.addEventListener('click', function () {
    if (!S.runId) return;
    cancelBtn.disabled = true;
    ctx.api.cancelDiscovery(ctx.project, S.runId).then(function (r) { S.run = r.run; cancelBtn.disabled = false; drawRun(); poll(); }, function (e) { cancelBtn.disabled = false; ctx.toast(msg(e), 'err'); });
  });
  const runNote = 'One run per project at a time. The enabled sources collect for the window (mDNS and LLDP listen for the whole window; UniFi, ARP and the active sources are read once, one host at a time), then results are correlated against this project. Nothing keeps running afterwards.';
  root.appendChild(h('div', { class: 'adm-card disc-run' }, [
    ro() ? null : h('div', { class: 'row disc-run-row' }, [
      h('label', { class: 'disc-window' }, ['Listen window', windowInp, h('span', { class: 'muted' }, 's')]),
      runBtn, cancelBtn,
    ]),
    status, bar, logWrap, runsWrap,
  ]));

  function drawRun() {
    const r = S.run;
    const active = !!(r && r.active);
    runBtn.disabled = ro() || active || (!!S.active && S.active !== (r && r.id));
    cancelBtn.classList.toggle('hidden', !active || ro());
    bar.classList.toggle('hidden', !r);
    drawBadges();
    if (!r) {
      status.textContent = S.active ? 'A run (' + S.active + ') is in progress in another session.' : (S.loaded ? 'No run yet.' : 'Loading runs\u2026');
      logWrap.classList.add('hidden');
      return;
    }
    const fill = bar.firstChild;
    fill.style.width = pct(r.progress);
    fill.className = 'disc-bar-fill disc-bar-' + (r.status || 'queued');
    const parts = [h('span', { class: 'chip disc-status-' + r.status }, [h('i'), cap(r.status)]), h('span', { class: 'mono muted disc-run-id' }, r.id)];
    if (r.mode === 'active') {
      const t = r.targets || {};
      const hosts = Object.keys(t).map(function (k) { return k + ': ' + (t[k] || []).join(', '); }).join('; ');
      parts.push(h('span', { class: 'chip disc-mode disc-mode-active', title: 'Read-only queries were sent to ' + (hosts || 'the listed hosts') }, [h('i'), 'Active']));
    }
    if (active) parts.push(h('span', null, (r.stage || 'running') + (r.remaining !== undefined ? ' \u00b7 ' + Math.round(r.remaining) + ' s max left' : '')));
    else {
      if (r.finished) parts.push(h('span', { class: 'muted' }, fmtTime(r.finished) + (r.elapsed ? ' \u00b7 ' + Math.round(r.elapsed) + ' s' : '')));
      if (r.error) parts.push(h('span', { class: 'imp-warn' }, r.error));
      if (r.by) parts.push(h('span', { class: 'muted' }, 'by ' + r.by));
    }
    status.innerHTML = '';
    status.appendChild(h('div', { class: 'row' }, parts));
    const lines = r.log || [];
    logWrap.classList.toggle('hidden', !lines.length);
    if (active) logWrap.open = true;
    logSum.textContent = 'Run log \u00b7 ' + plural(lines.length, 'line', 'lines');
    log.textContent = lines.map(function (x) { return (x.level === 'warn' || x.level === 'error' ? '! ' : '  ') + x.msg; }).join('\n');
    log.scrollTop = log.scrollHeight;
  }

  function runOption(r) {
    const c = r.counts || {};
    const dc = r.diff && r.diff.against && r.diff.counts ? r.diff.counts.changes : null;
    return fmtTime(r.started || r.finished) + ' \u00b7 ' + (r.status || '') + (r.mode === 'active' ? ' \u00b7 active' : '') + (c.entities !== undefined ? ' \u00b7 ' + c.entities + ' hosts, ' + (c.connections || 0) + ' links' : '') + (dc !== null && dc !== undefined ? ' \u00b7 ' + dc + (dc === 1 ? ' change' : ' changes') : '');
  }
  function drawRuns() {
    runsWrap.innerHTML = '';
    if (!S.runs.length) return;
    const sel = h('select', { 'aria-label': 'Previous runs', class: 'disc-run-pick' }, S.runs.map(function (r) {
      return h('option', { value: r.id, selected: r.id === S.runId ? true : null }, runOption(r));
    }));
    sel.addEventListener('change', function () { goRun(sel.value); });
    runsWrap.appendChild(h('div', { class: 'row disc-run-pick-row' }, [h('span', { class: 'muted' }, 'Show run'), sel]));
  }

  function stopPoll() { if (S.timer) { clearTimeout(S.timer); S.timer = null; } }
  function poll() {
    stopPoll();
    if (S.destroyed || !S.runId) return;
    const rid = S.runId;
    ctx.api.discoveryRun(ctx.project, rid).then(function (r) {
      if (S.destroyed || rid !== S.runId) return;
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
    S.findingsError = null;
    S.diff = null;
    S.diffAgainst = '';
    S.run = null;
    stopPoll();
    drawRuns();
    drawFindings();
    return ctx.api.discoveryRun(ctx.project, rid).then(function (r) {
      if (S.destroyed || rid !== S.runId) return;
      S.run = r.run;
      logWrap.open = !!r.run.active;
      drawRun();
      if (r.run.active) { drawFindings(); poll(); } else loadFindings();
    }, function (e) {
      if (S.destroyed || rid !== S.runId) return;
      S.findingsError = e;
      drawRun();
      drawFindings();
    });
  }

  // ------------------------------------------------------------ sources (collapsed summary)
  const srcSummary = h('span', { class: 'disc-sources-text' }, 'Sources');
  const srcEdit = h('span', { class: 'disc-sources-edit' }, ro() ? 'Details' : 'Edit');
  const srcWrap = h('div', { class: 'adm-cards disc-source-cards' });
  const sources = h('details', { class: 'disc-sources' }, [
    h('summary', null, [h('span', { class: 'disc-sources-glyph', 'aria-hidden': 'true' }, '\u25B8'), srcSummary, h('span', { class: 'muted' }, '\u00b7'), srcEdit]),
    h('div', { class: 'disc-sources-body' }, [
      h('p', { class: 'muted disc-intro' }, [
        'Passive sources read the UniFi controller you point them at and listen to what devices already announce (mDNS / Dante, LLDP / CDP) plus this host\u2019s ARP table. ',
        'Active sources (SNMP on your switches, Yamaha SCP, Videohub, Q-SYS, Dante Domain Manager) are ', h('strong', null, 'off until you enable them'), ', contact only the hosts you list, and send documented read-only queries. ',
        'Dante Controller has no API: without a DDM, Dante routing comes from the preset-XML import. ',
        h('strong', null, 'Nothing runs unless you start it here'), ' \u2014 there is no scheduler and no background listener \u2014 and nothing is ever written to any device.',
      ]),
      h('p', { class: 'muted disc-note' }, runNote),
      srcWrap,
    ]),
  ]);
  root.appendChild(sources);
  let sourcesOpened = false;

  function fieldInput(src, f, cur) {
    const key = f.key;
    const dis = ro() ? true : null;
    if (f.type === 'check') {
      const cb = h('input', { type: 'checkbox', id: 'disc-' + src.id + '-' + key, checked: !!cur[key], disabled: dis });
      return { el: h('div', { class: 'field check' }, [h('label', { for: cb.id }, f.label), cb]), read: function () { return cb.checked; }, input: cb };
    }
    if (f.type === 'select') {
      const sel = h('select', { id: 'disc-' + src.id + '-' + key, disabled: dis }, (f.options || []).map(function (o) { return h('option', { value: o, selected: String(cur[key] || f.default || '') === o ? true : null }, o); }));
      const row = h('div', { class: 'field' }, [h('label', { for: sel.id }, f.label), sel]);
      if (f.help) row.appendChild(h('div', { class: 'muted disc-help' }, f.help));
      return { el: row, read: function () { return sel.value; }, input: sel };
    }
    if (f.type === 'list') {
      const lines = String(cur[key] || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      const ta = h('textarea', { id: 'disc-' + src.id + '-' + key, rows: Math.max(2, Math.min(6, lines.length + 1)), spellcheck: 'false', autocapitalize: 'none', disabled: dis,
        placeholder: cur[key + '_env'] ? 'env: ' + cur[key + '_env'] : (f.placeholder || '') });
      ta.value = lines.join('\n');
      const row = h('div', { class: 'field disc-list' }, [h('label', { for: ta.id }, f.label), ta]);
      row.appendChild(h('div', { class: 'muted disc-help' }, (f.help ? f.help + ' ' : '') + 'Only these hosts are contacted.'));
      return { el: row, input: ta, read: function () { return ta.value.split(/[\n,;]+/).map(function (s) { return s.trim(); }).filter(Boolean); } };
    }
    const secret = !!f.secret;
    const isSet = !!cur[key + '_set'];
    const inp = h('input', { type: secret ? 'password' : 'text', id: 'disc-' + src.id + '-' + key, disabled: dis,
      placeholder: secret ? (isSet ? (cur[key + '_from_env'] ? 'set via environment \u2014 type to override' : 'set \u2014 leave blank to keep') : (f.placeholder || '')) : (cur[key + '_env'] ? 'env: ' + cur[key + '_env'] : (f.placeholder || '')),
      autocomplete: secret ? 'new-password' : 'off', spellcheck: 'false', autocapitalize: 'none' });
    inp.value = secret ? '' : (cur[key] || '');
    const row = h('div', { class: 'field' }, [h('label', { for: inp.id }, f.label), inp]);
    if (f.help) row.appendChild(h('div', { class: 'muted disc-help' }, f.help));
    let clear = null;
    if (secret && isSet && !ro()) {
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
    const save = h('button', { type: 'button', class: 'small primary', onclick: function () {
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
    const test = h('button', { type: 'button', class: 'small', onclick: function () {
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
    const active = src.mode === 'active';
    const maturityTitle = { experimental: 'Experimental: parser and protocol handling are new; expect gaps', tested: 'Tested: verified against recorded device captures and in use',
      mature: 'Mature: stable protocol, long in use' }[src.maturity || 'experimental'];
    const chips = h('div', { class: 'row disc-chips' }, [
      h('span', { class: 'chip disc-mode disc-mode-' + (src.mode || 'passive'), title: active ? 'Sends read-only queries to the hosts listed below (opt-in, off by default)' : 'Reads a controller or listens only; sends nothing to AV devices' }, [h('i'), cap(src.mode || 'passive')]),
      h('span', { class: 'chip disc-maturity disc-maturity-' + (src.maturity || 'experimental'), title: maturityTitle }, cap(src.maturity || 'experimental')),
      active && cur.enabled !== true ? h('span', { class: 'chip disc-optin', title: 'Active sources never run until enabled here' }, 'Off by default') : null,
      src.available ? null : h('span', { class: 'chip imp-chip-err' }, 'unavailable'),
    ]);
    return h('div', { class: 'adm-card disc-card' + (active ? ' disc-card-active' : ''), 'data-probe': src.id, 'data-mode': src.mode || 'passive' }, [
      h('div', { class: 'disc-card-head' }, [h('h4', null, src.label), h('label', { class: 'disc-enabled', for: enabled.id }, [enabled, ' enabled'])]),
      chips,
      h('div', { class: 'help' }, src.help || ''),
      src.sends ? h('div', { class: 'muted disc-sends' + (active ? ' disc-sends-active' : '') }, [h('strong', null, active ? 'What this sends to the device: ' : 'On the wire: '), src.sends]) : null,
      src.available ? null : h('div', { class: 'imp-warn' }, src.unavailable_reason || 'Not available on this server.'),
      h('div', { class: 'disc-fields' }, fields.map(function (f) { return f.el; })),
      ro() ? null : h('div', { class: 'row disc-card-acts' }, [save, test]),
      out,
      lastRunFor(src.id),
    ]);
  }

  function drawSources() {
    srcWrap.innerHTML = '';
    const on = S.sources.filter(function (s) { return sourceEnabled(s) && s.available !== false; });
    if (!S.sources.length) srcSummary.textContent = S.loaded ? 'No discovery sources' : 'Sources';
    else srcSummary.textContent = plural(on.length, 'source', 'sources') + ' configured' + (on.length ? ': ' + on.map(function (s) { return s.label; }).join(', ') : '');
    sources.setAttribute('data-configured', String(on.length));
    if (S.loaded && !sourcesOpened) {
      sourcesOpened = true;
      if (!on.length) sources.open = true;
    }
    if (!S.sources.length) { srcWrap.appendChild(h('div', { class: 'muted' }, 'The server did not list any discovery sources.')); return; }
    S.sources.forEach(function (s) { srcWrap.appendChild(sourceCard(s)); });
    if (S.caps && !S.caps.zeroconf) {
      srcWrap.appendChild(h('div', { class: 'adm-card disc-card disc-install' }, [
        h('h4', null, 'Optional extra not installed'),
        h('div', { class: 'help' }, 'mDNS / Dante listening needs the zeroconf package. Install the discovery extra on the server and restart it:'),
        h('div', { class: 'adm-pre' }, S.caps.install_hint || "pip install 'fathom-audio[discovery]'"),
        h('div', { class: 'muted', style: { fontSize: '12px' } }, 'Into the venv the service runs from (`.venv/bin/pip install "fathom-audio[discovery]"`), then restart fathom.service. UniFi, LLDP and ARP work without it.'),
      ]));
    }
  }

  // ------------------------------------------------------------ findings
  root.appendChild(h('h3', null, 'Findings'));
  const findWrap = h('div', { class: 'disc-findings' });
  root.appendChild(findWrap);

  function loadFindings() {
    if (!S.runId || !S.run || S.run.active) { drawFindings(); return Promise.resolve(); }
    const rid = S.runId;
    S.loadingFindings = true;
    S.findingsError = null;
    S.diff = null; // the diff is computed against the live document too
    drawFindings();
    return ctx.api.discoveryFindings(ctx.project, rid).then(function (f) {
      if (S.destroyed || rid !== S.runId) return;
      S.loadingFindings = false;
      S.findings = f;
      S.memo = {};
      S.models = {};
      S.targets = {};
      drawFindings();
    }, function (e) {
      if (S.destroyed || rid !== S.runId) return;
      S.loadingFindings = false;
      S.findingsError = e;
      drawFindings();
    });
  }

  // Per-row controls survive DataTable re-renders (sort, page, search) within one findings load.
  function memo(key, make) {
    if (!Object.prototype.hasOwnProperty.call(S.memo, key)) S.memo[key] = make();
    return S.memo[key];
  }

  // Model suggestion controls per entity; their choice rides along with promote / merge.
  function modelControl(e) {
    const list = e.model_suggestions || [];
    if (!list.length || e.status === 'unresolved' || e.status === 'ignored') return null;
    return memo('model:' + e.id, function () {
      const c = suggestionControl(list, { label: e.label, readOnly: ro(), pickTemplate: ctx.pickTemplate ? function () { return ctx.pickTemplate({}); } : null });
      S.models[e.id] = c;
      return c.el;
    });
  }
  function entityById(id) {
    const list = (S.findings && S.findings.entities) || [];
    for (let i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  // Rows never rendered (other pages) have no control yet: they take the default suggestion, as the
  // control would have preselected it.
  function templatesFor(ids) {
    const out = {};
    (ids || []).forEach(function (id) {
      const c = S.models[id];
      let v = '';
      if (c) v = c.value();
      else {
        const e = entityById(id);
        if (e && e.status !== 'unresolved' && e.status !== 'ignored') v = defaultChoice(e.model_suggestions || []);
      }
      if (v) out[id] = v;
    });
    return Object.keys(out).length ? out : undefined;
  }

  function promote(body, label) {
    if (ro()) { ctx.toast('Read-only', 'warn'); return Promise.resolve(); }
    if (!body.templates) {
      const ids = (body.entities || []).concat(Object.keys(body.merge || {}));
      const t = templatesFor(ids);
      if (t) body.templates = t;
    }
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
      return ctx.reload().then(function () { return ctx.api.overlay(ctx.project).then(function (o) { store.setOverlay(o); }, function () {}); }).then(loadFindings);
    }, function (e) { ctx.toast(msg(e), 'err'); });
  }
  // More than one finding at once asks first (B.5 confirmScope).
  function promoteMany(n, verb, noun, body, label) {
    if (n <= 1) return promote(body, label);
    return confirmScope(ctx, { verb: verb, count: n, noun: noun, scope: '' }).then(function (ok) { if (ok) return promote(body, label); });
  }

  function roomSelect() {
    const def = S.room || (S.findings && S.findings.room) || (store.doc.settings && store.doc.settings.default_room) || '';
    const sel = h('select', { 'aria-label': 'Room for new devices', class: 'disc-room-pick' }, (store.doc.rooms || []).map(function (r) { return h('option', { value: r.id, selected: r.id === def ? true : null }, r.name || r.id); }));
    sel.addEventListener('change', function () { S.room = sel.value; });
    S.room = sel.value;
    return sel;
  }

  function matchedDevice(e) {
    const id = e && e.match && e.match.device;
    if (!id) return '';
    return (store.doc.devices || []).some(function (d) { return d.id === id; }) ? id : '';
  }
  function openMatched(e) {
    const id = matchedDevice(e);
    if (!id) return;
    if (ctx.openDrawer) ctx.openDrawer({ type: 'device', id: id });
  }

  function actions(key, make) {
    return memo('acts:' + key, function () { return h('div', { class: 'disc-actions' }, make()); });
  }

  // Shared entity columns; `extra` slots in after Kind.
  function deviceCol(header) {
    return { key: 'label', header: header, sticky: true, value: function (e) { return e.label; },
      cell: function (e) {
        return h('div', { class: 'disc-dev' }, [
          h('div', { class: 'disc-name' }, [e.label, matchedDevice(e) ? h('span', { class: 'disc-open', 'aria-hidden': 'true' }, ' \u203A') : null]),
          h('div', { class: 'muted' }, [e.manufacturer, e.model].filter(Boolean).join(' ') || (e.kind_hint ? e.kind_hint : '')),
        ]);
      } };
  }
  function entityColumns(header, extra, acts) {
    return [deviceCol(header), { key: 'kind', header: 'Kind', filterable: true, value: function (e) { return e.kind || ''; } }]
      .concat(extra || [])
      .concat([
        { key: 'addresses', header: 'Addresses', value: addrText, cell: addrs, sortable: false },
        { key: 'sources', header: 'Sources', filterable: true, hideOnMobile: true, value: function (e) { return e.sources || []; }, cell: function (e) { return sourcesChips(e.sources); } },
        { key: 'confidence', header: 'Confidence', align: 'left', value: function (e) { return Number(e.confidence) || 0; }, csv: function (e) { return pct(e.confidence); },
          cell: function (e) { return h('div', null, [conf(e.level, e.confidence), e.reasons && e.reasons.length ? h('div', { class: 'muted disc-reasons' }, e.reasons.join(' \u00b7 ')) : null]); } },
        { key: 'actions', header: 'Actions', sortable: false, searchable: false, csv: false, value: function () { return ''; }, cell: acts },
      ]);
  }
  function modelCol() {
    return { key: 'model', header: 'Suggested model', sortable: false, searchable: false, csv: false, value: function () { return ''; },
      cell: function (e) { return modelControl(e); } };
  }

  function table(host, key, opts) {
    const o = Object.assign({ key: 'discovery.' + key, scope: ctx.project, cards: true, pageSize: 50, csvName: 'discovery-' + key + '-' + (S.runId || 'run') + '.csv' }, opts);
    if (o.primary) { o.url = primaryUrl(); delete o.primary; }
    const t = createTable(host, o);
    S.tables.push(t);
    if (o.url) S.primary = t;
    return t;
  }
  function empty(text) { return emptyState({ text: text }); }

  function newDevicesTab(host, f) {
    const list = f.entities.filter(function (e) { return e.status === 'new'; });
    if (!list.length) { host.appendChild(empty('No new devices: every host seen matches a device already in the project (or was ignored).')); return; }
    const room = ro() ? null : roomSelect();
    const ids = function (rows) { return rows.map(function (e) { return e.id; }); };
    table(host, 'new', {
      primary: true, caption: 'New devices', rows: list, noun: { one: 'host', many: 'hosts' },
      columns: entityColumns('Device', [modelCol()], function (e) {
        return actions('e:' + e.id, function () {
          return (ro() ? [] : [
            h('button', { type: 'button', class: 'small primary', onclick: function () { promote({ entities: [e.id], room: S.room }, 'Promoted ' + e.label); } }, 'Promote'),
            h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ ignore: { entities: [e.id] } }, 'Ignored ' + e.label); } }, 'Ignore'),
          ]).concat(detailsBlock(e.observations));
        });
      }),
      rowAttrs: function (e) { return { 'data-entity': e.id }; },
      rowClass: function (e) { return 'disc-row disc-' + e.status; },
      selectable: !ro(),
      bulkActions: ro() ? [] : [
        { label: 'Promote selected', run: function (rows) { const x = ids(rows); return promoteMany(x.length, 'Promote', { one: 'host', many: 'hosts' }, { entities: x, room: S.room }, 'Promoted ' + plural(x.length, 'device', 'devices')); } },
        { label: 'Ignore selected', run: function (rows) { const x = ids(rows); return promoteMany(x.length, 'Ignore', { one: 'host', many: 'hosts' }, { ignore: { entities: x } }, 'Ignored ' + plural(x.length, 'host', 'hosts')); } },
      ],
      actions: room ? [h('label', { class: 'disc-room' }, ['Room for new devices ', room])] : [],
    });
  }

  function mergeTarget(e) {
    return memo('target:' + e.id, function () {
      const m = e.match || {};
      const others = m.others || [];
      const sel = h('select', { 'aria-label': 'Merge ' + e.label + ' into', class: 'disc-target', disabled: ro() ? true : null }, [h('option', { value: m.device }, (m.name || m.device) + ' (' + pct(m.score) + ')')]
        .concat(others.map(function (o) { return h('option', { value: o.device }, (o.name || o.device) + ' (' + pct(o.score) + ')'); }))
        .concat((store.doc.devices || []).filter(function (d) { return d.id !== m.device && !others.some(function (o) { return o.device === d.id; }); }).map(function (d) { return h('option', { value: d.id }, d.name || d.id); })));
      S.targets[e.id] = sel;
      return sel;
    });
  }

  function matchesTab(host, f) {
    const list = f.entities.filter(function (e) { return e.status === 'match' || e.status === 'possible'; });
    if (!list.length) { host.appendChild(empty('No host matched a device already in the project.')); return; }
    const matchCol = { key: 'match', header: 'Matches', filterable: true,
      value: function (e) { return e.status === 'match' ? 'Match' : 'Possible'; },
      cell: function (e) {
        const m = e.match || {};
        const newIfs = (e.interfaces || []).filter(function (i) { return !i.known; });
        return h('div', null, [
          h('div', { class: 'row' }, [h('span', { class: 'chip ' + (e.status === 'match' ? 'on' : '') }, e.status === 'match' ? 'Match' : 'Possible'), mergeTarget(e)]),
          h('div', { class: 'muted disc-reasons' }, (m.reasons || []).join(' \u00b7 ') + (newIfs.length ? ' \u00b7 adds ' + newIfs.length + (newIfs.length === 1 ? ' interface' : ' interfaces') : ' \u00b7 refreshes switch / port')),
        ]);
      } };
    table(host, 'matches', {
      primary: true, caption: 'Matches existing', rows: list, noun: { one: 'host', many: 'hosts' },
      columns: entityColumns('Discovered', [matchCol, modelCol()], function (e) {
        return actions('m:' + e.id, function () {
          return (ro() ? [] : [
            h('button', { type: 'button', class: 'small primary', onclick: function () {
              const target = S.targets[e.id];
              const merge = {};
              merge[e.id] = target ? target.value : (e.match || {}).device;
              const name = target ? target.options[target.selectedIndex].textContent : ((e.match || {}).name || merge[e.id]);
              promote({ merge: merge }, 'Merged ' + e.label + ' into ' + name);
            } }, 'Merge into'),
            e.proposed ? h('button', { type: 'button', class: 'small', title: 'Create a separate new device instead', onclick: function () { promote({ entities: [e.id] }, 'Promoted ' + e.label); } }, 'New device') : null,
            h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ ignore: { entities: [e.id] } }, 'Ignored ' + e.label); } }, 'Ignore'),
          ]).concat(detailsBlock(e.observations));
        });
      }),
      rowAttrs: function (e) { return { 'data-entity': e.id, title: matchedDevice(e) ? 'Open ' + ((e.match || {}).name || '') : null }; },
      rowClass: function (e) { return 'disc-row disc-' + e.status + (matchedDevice(e) ? ' disc-linked' : ''); },
      onRow: openMatched,
    });
  }

  const FLAG_TITLE = { uplink: 'Switch-to-switch link', unmanaged: 'Several hosts share this port: an unmanaged switch, hub or AP hangs off it', via: 'Reached through an uplink; no direct cable', host: 'The port this Fathom server is plugged into' };
  function connectionsTab(host, f) {
    const rows = f.rows || [];
    if (!rows.length) { host.appendChild(empty('No switch-port connections were reported. LLDP on the switches and a UniFi controller give the best results.')); return; }
    const byId = {};
    (f.connections || []).forEach(function (c) { byId[c.id] = c; });
    const canAdd = function (r) { return !!r.proposed && r.status === 'new'; };
    const txt = function (k) { return function (r) { return r[k] || ''; }; };
    host.appendChild(h('p', { class: 'muted disc-hint' }, 'Generated connections, in cable-schedule columns. Only unflagged links at medium confidence or better can become cables; both ends must be in the project (promote or merge them first).'));
    table(host, 'connections', {
      primary: true, caption: 'Connections', rows: rows, noun: { one: 'connection', many: 'connections' },
      columns: [
        { key: 'tag', header: 'Tag', hideOnMobile: true, value: txt('tag'), cell: function (r) { return h('span', { class: 'muted' }, r.tag || '\u2014'); } },
        { key: 'from_room', header: 'From room', filterable: true, hideOnMobile: true, value: txt('from_room') },
        { key: 'from_device', header: 'From device', filterable: true, value: txt('from_device') },
        { key: 'from_port', header: 'From port', value: txt('from_port') },
        { key: 'to_room', header: 'To room', filterable: true, hideOnMobile: true, value: txt('to_room') },
        { key: 'to_device', header: 'To device', filterable: true, value: txt('to_device') },
        { key: 'to_port', header: 'To port', value: txt('to_port'), cell: function (r) { return r.to_port || dash(); } },
        { key: 'medium', header: 'Medium', filterable: true, value: txt('medium') },
        { key: 'type', header: 'Type', hideOnMobile: true, value: txt('type') },
        { key: 'length', header: 'Length', hideOnMobile: true, sortable: false, value: txt('length'), cell: function (r) { return r.length || dash(); } },
        { key: 'confidence', header: 'Confidence', value: function (r) { return Number(r.confidence) || 0; }, csv: function (r) { return pct(r.confidence); },
          cell: function (r) { return h('div', null, [conf(r.level, r.confidence), h('div', { class: 'muted disc-reasons' }, (r.signal || '').split('/').join(' + '))]); } },
        { key: 'flags', header: 'Flags', filterable: true,
          value: function (r) { const v = []; if (r.flag) v.push(r.flag); if (r.status === 'exists') v.push('in schedule'); if (r.status === 'ignored') v.push('ignored'); return v; },
          cell: function (r) {
            const c = byId[r.id] || {};
            return h('div', { class: 'row' }, [
              r.flag ? h('span', { class: 'chip disc-flag disc-flag-' + r.flag, title: FLAG_TITLE[r.flag] || r.flag }, r.flag) : null,
              r.status === 'exists' ? h('span', { class: 'chip' }, 'in schedule') : (r.status === 'ignored' ? h('span', { class: 'chip' }, 'ignored') : null),
              c.peers_on_port > 1 ? h('span', { class: 'muted' }, c.peers_on_port + ' on port') : null,
            ]);
          } },
        { key: 'actions', header: 'Actions', sortable: false, searchable: false, csv: false, value: function () { return ''; },
          cell: function (r) {
            return actions('c:' + r.id, function () {
              const c = byId[r.id] || {};
              const acts = [];
              if (canAdd(r) && !ro()) acts.push(h('button', { type: 'button', class: 'small primary', onclick: function () { promote({ connections: [r.id] }, 'Added cable'); } }, 'Add cable'));
              if (!ro() && r.status !== 'ignored') acts.push(h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ ignore: { connections: [r.id] } }, 'Ignored connection'); } }, 'Ignore'));
              if (!ro() && r.status === 'ignored') acts.push(h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ unignore: { connections: [r.id] } }, 'Restored connection'); } }, 'Unignore'));
              return acts.concat(detailsBlock(c.evidence || c));
            });
          } },
      ],
      rowClass: function (r) { return 'disc-row' + (r.flag ? ' disc-flagged' : ''); },
      selectable: ro() ? false : canAdd,
      bulkActions: ro() ? [] : [
        { label: 'Add selected as cables', run: function (sel) { const x = sel.map(function (r) { return r.id; }); return promoteMany(x.length, 'Add', { one: 'cable', many: 'cables' }, { connections: x }, 'Added ' + plural(x.length, 'cable', 'cables')); } },
      ],
    });
  }

  function networksTab(host, f) {
    const nets = f.networks || [];
    if (!nets.length) { host.appendChild(empty('No VLANs or subnets were reported (a UniFi controller provides them).')); return; }
    const mono = function (k) { return { key: k, header: { subnet: 'Subnet', gateway: 'Gateway', dhcp_range: 'DHCP' }[k], value: function (n) { return n[k] || ''; }, cell: function (n) { return h('span', { class: 'mono' }, n[k] || ''); } }; };
    table(host, 'networks', {
      primary: true, caption: 'Networks / VLANs', rows: nets, noun: { one: 'network', many: 'networks' },
      columns: [
        { key: 'name', header: 'Network', sticky: true, value: function (n) { return n.name || ('VLAN ' + n.vlan); },
          cell: function (n) { return h('div', null, [h('div', { class: 'disc-name' }, n.name || ('VLAN ' + n.vlan)), n.purpose ? h('div', { class: 'muted' }, n.purpose) : null]); } },
        { key: 'vlan', header: 'VLAN', value: function (n) { return n.vlan === null || n.vlan === undefined ? '' : n.vlan; },
          cell: function (n) { return n.vlan === null || n.vlan === undefined ? dash() : h('span', { class: 'mono' }, String(n.vlan)); } },
        mono('subnet'), Object.assign(mono('gateway'), { hideOnMobile: true }), Object.assign(mono('dhcp_range'), { hideOnMobile: true }),
        { key: 'hosts', header: 'Hosts', align: 'right', value: function (n) { return n.hosts || ''; } },
        { key: 'sources', header: 'Sources', filterable: true, hideOnMobile: true, value: function (n) { return n.sources || []; }, cell: function (n) { return sourcesChips(n.sources); } },
        { key: 'project', header: 'Project', filterable: true,
          value: function (n) { return n.match ? 'in project' : (n.status === 'ignored' ? 'ignored' : 'new'); },
          csv: function (n) { return n.match ? (n.match.name || n.match.network) : (n.status === 'ignored' ? 'ignored' : 'new'); },
          cell: function (n) { return n.match ? h('span', { class: 'chip on', title: n.match.reason }, ['= ', n.match.name || n.match.network, n.match.differs && n.match.differs.length ? ' (differs: ' + n.match.differs.join(', ') + ')' : '']) : h('span', { class: 'chip' }, n.status === 'ignored' ? 'ignored' : 'new'); } },
        { key: 'actions', header: 'Actions', sortable: false, searchable: false, csv: false, value: function () { return ''; },
          cell: function (n) {
            return actions('n:' + n.id, function () {
              const acts = [];
              if (!ro() && n.status === 'new') {
                acts.push(h('button', { type: 'button', class: 'small primary', onclick: function () { promote({ networks: [n.id] }, 'Added network ' + n.name); } }, 'Add network'));
                acts.push(h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ ignore: { networks: [n.id] } }, 'Ignored ' + n.name); } }, 'Ignore'));
              }
              return acts.concat(detailsBlock(n.evidence));
            });
          } },
      ],
      rowClass: function () { return 'disc-row'; },
    });
  }

  function unresolvedTab(host, f) {
    const list = f.entities.filter(function (e) { return e.status === 'unresolved' || e.status === 'ignored'; });
    if (!list.length) { host.appendChild(empty('Nothing unresolved or ignored.')); return; }
    const why = { key: 'why', header: 'Why', filterable: true, value: function (e) { return e.status === 'ignored' ? 'Ignored by you' : 'No MAC address and no name'; },
      cell: function (e) { return h('span', { class: 'muted' }, e.status === 'ignored' ? 'Ignored by you' : 'No MAC address and no name: cannot be told apart between runs'); } };
    table(host, 'unresolved', {
      primary: true, caption: 'Unresolved', rows: list, noun: { one: 'host', many: 'hosts' },
      columns: entityColumns('Host', [why], function (e) {
        return actions('u:' + e.id, function () {
          return (ro() ? [] : (e.status === 'ignored'
            ? [h('button', { type: 'button', class: 'small', onclick: function () { promote({ unignore: { entities: [e.id] } }, 'Restored ' + e.label); } }, 'Unignore')]
            : [h('button', { type: 'button', class: 'small ghost', onclick: function () { promote({ ignore: { entities: [e.id] } }, 'Ignored ' + e.label); } }, 'Ignore')])).concat(detailsBlock(e.observations));
        });
      }),
      rowAttrs: function (e) { return { 'data-entity': e.id }; },
      rowClass: function (e) { return 'disc-row disc-' + e.status + (matchedDevice(e) ? ' disc-linked' : ''); },
      onRow: openMatched,
    });
  }

  // ------------------------------------------------------------ changes (run-to-run diff)
  function loadDiff(against) {
    if (!S.runId) return Promise.resolve();
    const rid = S.runId;
    S.loadingDiff = true;
    S.diffAgainst = against || '';
    drawFindings();
    return ctx.api.discoveryDiff(ctx.project, rid, against).then(function (d) {
      if (S.destroyed || rid !== S.runId) return;
      S.loadingDiff = false;
      S.diff = d;
      drawFindings();
    }, function (e) {
      if (S.destroyed || rid !== S.runId) return;
      S.loadingDiff = false;
      S.diff = { error: e, candidates: [] };
      drawFindings();
    });
  }
  function runLabel(id) {
    const r = S.runs.filter(function (x) { return x.id === id; })[0];
    return r ? fmtTime(r.started || r.finished) + ' \u00b7 ' + id : id;
  }
  function whereText(loc) { return loc ? (loc.switch || loc.switch_mac || '?') + ' \u00b7 ' + (loc.port || '') : ''; }
  function whereCell(loc) {
    if (!loc) return dash();
    return h('div', null, [h('div', null, whereText(loc)), loc.evidence === 'uplink' ? h('div', { class: 'muted disc-reasons' }, 'reported by the controller') : null]);
  }
  function diffDeviceTable(host, key, list, whereLabel) {
    table(host, 'changes-' + key, {
      caption: whereLabel === 'Was on' ? 'Missing devices' : 'New devices', rows: list, pageSize: 25, noun: { one: 'device', many: 'devices' },
      rowId: function (e) { return e.id || e.label; },
      columns: [
        deviceCol('Device'),
        { key: 'kind', header: 'Kind', filterable: true, value: function (e) { return e.kind || ''; } },
        { key: 'addresses', header: 'Addresses', sortable: false, value: addrText, cell: addrs },
        { key: 'where', header: whereLabel, value: function (e) { return whereText(e.location); }, cell: function (e) { return whereCell(e.location); } },
        { key: 'sources', header: 'Sources', hideOnMobile: true, filterable: true, value: function (e) { return e.sources || []; }, cell: function (e) { return sourcesChips(e.sources); } },
        { key: 'confidence', header: 'Confidence', value: function (e) { return Number(e.confidence) || 0; }, csv: function (e) { return pct(e.confidence); }, cell: function (e) { return conf(e.level, e.confidence); } },
        { key: 'project', header: 'Project', filterable: true, value: function (e) { return e.status === 'match' ? 'in project' : (e.status || ''); },
          cell: function (e) { return e.status === 'match' ? h('span', { class: 'chip on' }, 'in project') : h('span', { class: 'chip' }, e.status || ''); } },
      ],
      rowClass: function (e) { return 'disc-row' + (matchedDevice(e) ? ' disc-linked' : ''); },
      onRow: openMatched,
    });
  }
  function diffLinkTable(host, key, list) {
    table(host, 'changes-' + key, {
      caption: key === 'lost-links' ? 'Lost links' : 'New links', rows: list, pageSize: 25, noun: { one: 'link', many: 'links' },
      rowId: function (l) { return (l.switch || l.switch_mac || '') + '|' + (l.port || '') + '|' + (l.peer || l.peer_mac || ''); },
      columns: [
        { key: 'switch', header: 'Switch', sticky: true, filterable: true, value: function (l) { return l.switch || l.switch_mac || ''; } },
        { key: 'port', header: 'Port', value: function (l) { return l.port || ''; } },
        { key: 'peer', header: 'Device', value: function (l) { return l.peer || l.peer_mac || ''; },
          cell: function (l) { return h('div', null, [h('div', null, l.peer || l.peer_mac || ''), l.peer_mac ? h('div', { class: 'mono muted' }, l.peer_mac) : null]); } },
        { key: 'peer_port', header: 'Device port', value: function (l) { return l.peer_port || ''; }, cell: function (l) { return l.peer_port || dash(); } },
        { key: 'medium', header: 'Medium', filterable: true, value: function (l) { return l.medium || ''; } },
        { key: 'confidence', header: 'Confidence', value: function (l) { return Number(l.confidence) || 0; }, csv: function (l) { return pct(l.confidence); },
          cell: function (l) { return h('div', null, [conf(l.level, l.confidence), h('div', { class: 'muted disc-reasons' }, (l.methods || []).join(' + '))]); } },
        { key: 'flags', header: 'Flags', filterable: true, value: function (l) { const v = []; if (l.flag) v.push(l.flag); if (l.status === 'exists') v.push('in schedule'); return v; },
          cell: function (l) { return h('div', { class: 'row' }, [l.flag ? h('span', { class: 'chip disc-flag disc-flag-' + l.flag }, l.flag) : null, l.status === 'exists' ? h('span', { class: 'chip' }, 'in schedule') : null]); } },
      ],
      rowClass: function (l) { return 'disc-row' + (l.flag ? ' disc-flagged' : ''); },
    });
  }
  function diffMovedTable(host, list) {
    table(host, 'changes-moved', {
      caption: 'Moved', rows: list, pageSize: 25, noun: { one: 'device', many: 'devices' },
      rowId: function (m) { return m.id || m.label; },
      columns: [
        { key: 'label', header: 'Device', sticky: true, value: function (m) { return m.label; },
          cell: function (m) { return h('div', null, [h('div', { class: 'disc-name' }, m.label), (m.macs || []).length ? h('div', { class: 'mono muted' }, m.macs[0]) : null]); } },
        { key: 'kind', header: 'Kind', filterable: true, value: function (m) { return m.kind || ''; } },
        { key: 'from', header: 'Was on', value: function (m) { return whereText(m.from); }, cell: function (m) { return whereCell(m.from); } },
        { key: 'to', header: 'Now on', value: function (m) { return whereText(m.to); }, cell: function (m) { return whereCell(m.to); } },
      ],
      rowClass: function () { return 'disc-row'; },
    });
  }
  function diffChangedTable(host, list) {
    const fmt = function (v) { return Array.isArray(v) ? v.join(', ') : (v === null || v === undefined ? '\u2014' : String(v)); };
    table(host, 'changes-changed', {
      caption: 'Changed', rows: list, pageSize: 25, noun: { one: 'change', many: 'changes' },
      rowId: function (c) { return (c.id || c.label) + '|' + c.field; },
      columns: [
        { key: 'label', header: 'Device', sticky: true, value: function (c) { return c.label; }, cell: function (c) { return h('div', { class: 'disc-name' }, c.label); } },
        { key: 'field', header: 'Field', filterable: true, value: function (c) { return cap(c.field_label || c.field); } },
        { key: 'before', header: 'Before', value: function (c) { return fmt(c.before); }, cell: function (c) { return h('span', { class: 'mono' }, fmt(c.before)); } },
        { key: 'after', header: 'After', value: function (c) { return fmt(c.after); }, cell: function (c) { return h('span', { class: 'mono' }, fmt(c.after)); } },
      ],
      rowClass: function () { return 'disc-row'; },
    });
  }
  function diffTab(host) {
    if (!S.diff && !S.loadingDiff) { loadDiff(S.diffAgainst); }
    if (S.loadingDiff || !S.diff) { host.appendChild(skeleton('table')); return; }
    const r = S.diff;
    const wrap = h('div', { class: 'disc-diff' });
    host.appendChild(wrap);
    const cands = r.candidates || [];
    const sel = h('select', { 'aria-label': 'Compare with run', disabled: cands.length ? null : true }, cands.length
      ? cands.map(function (c) {
        const cc = c.counts || {};
        return h('option', { value: c.id, selected: c.id === r.against ? true : null }, fmtTime(c.started || c.finished) + (c.mode === 'active' ? ' \u00b7 active' : '') + (cc.entities !== undefined ? ' \u00b7 ' + cc.entities + ' hosts, ' + (cc.connections || 0) + ' links' : ''));
      })
      : [h('option', { value: '' }, 'no earlier completed run')]);
    sel.addEventListener('change', function () { loadDiff(sel.value); });
    wrap.appendChild(h('div', { class: 'row disc-toolbar' }, [
      h('label', { class: 'row disc-against' }, ['Compared with', sel]),
      r.against && r.diff && r.diff.computed ? h('span', { class: 'muted' }, 'both runs correlated against the current project' + (r.persisted ? ' \u00b7 stored with the run' : '')) : null,
    ]));
    if (r.error) { wrap.appendChild(inlineError(r.error, function () { return loadDiff(S.diffAgainst); })); return; }
    if (!r.against) {
      wrap.appendChild(empty('This is the first completed run of the project; start another run later and it will be compared with this one here.'));
      return;
    }
    const d = r.diff || {};
    const c = d.counts || {};
    wrap.appendChild(h('div', { class: 'row disc-summary' }, [
      h('span', { class: 'chip ' + (c.new_devices ? 'on' : '') }, '+' + (c.new_devices || 0) + ' devices'),
      h('span', { class: 'chip ' + (c.missing_devices ? 'warn' : '') }, '\u2212' + (c.missing_devices || 0) + ' devices'),
      h('span', { class: 'chip ' + (c.moved ? 'on' : '') }, (c.moved || 0) + ' moved'),
      h('span', { class: 'chip ' + (c.changed ? 'on' : '') }, (c.changed || 0) + ' changed'),
      h('span', { class: 'chip ' + (c.new_links ? 'on' : '') }, '+' + (c.new_links || 0) + ' links'),
      h('span', { class: 'chip ' + (c.lost_links ? 'warn' : '') }, '\u2212' + (c.lost_links || 0) + ' links'),
      h('span', { class: 'muted' }, (c.paired || 0) + ' devices seen in both runs, ' + (c.unchanged || 0) + ' unchanged'),
    ]));
    if (!c.changes) {
      wrap.appendChild(empty('No changes since ' + runLabel(r.against) + '.'));
      return;
    }
    const section = function (title, n, hint, fill) {
      if (!n) return;
      wrap.appendChild(h('h4', { class: 'disc-diff-h' }, [title, ' ', h('span', { class: 'chip' }, String(n))]));
      if (hint) wrap.appendChild(h('div', { class: 'muted disc-diff-hint' }, hint));
      const box = h('div', { class: 'disc-diff-table' });
      wrap.appendChild(box);
      fill(box);
    };
    section('New devices', c.new_devices, 'Seen in this run but not in the earlier one. Promote them from the New devices tab.', function (b) { diffDeviceTable(b, 'new', d.new_devices || [], 'Where'); });
    section('Missing devices', c.missing_devices, 'Seen in the earlier run but not in this one: unplugged, powered down, or outside this run\u2019s sources.', function (b) { diffDeviceTable(b, 'missing', d.missing_devices || [], 'Was on'); });
    section('Moved', c.moved, 'Same device (by MAC, serial or name), different switch port.', function (b) { diffMovedTable(b, d.moved || []); });
    section('Changed', c.changed, 'IP, VLAN, hostname or Dante name differs from the earlier run.', function (b) { diffChangedTable(b, d.changed || []); });
    section('New links', c.new_links, 'Switch-port connections that were not reported in the earlier run.', function (b) { diffLinkTable(b, 'new-links', d.new_links || []); });
    section('Lost links', c.lost_links, 'Switch-port connections the earlier run reported and this one did not.', function (b) { diffLinkTable(b, 'lost-links', d.lost_links || []); });
  }

  // ------------------------------------------------------------ runs tab
  function runsTab(host) {
    if (!S.runs.length) { host.appendChild(empty(S.loaded ? (ro() ? 'Discovery has not been run for this project.' : 'No runs yet. Run discovery to see what is on the network.') : 'Loading runs\u2026')); return; }
    const t = table(host, 'runs', {
      // Not `highlight`: that scrolls the row into view after render and moves the tab strip away on sm.
      primary: true, caption: 'Discovery runs', rows: S.runs, noun: { one: 'run', many: 'runs' },
      columns: [
        { key: 'started', header: 'Started', sticky: true, value: function (r) { return Number(r.started || r.finished) || 0; }, csv: function (r) { return fmtTime(r.started || r.finished); },
          cell: function (r) { return h('div', { class: 'disc-name' }, [fmtTime(r.started || r.finished), r.id === S.runId ? h('span', { class: 'chip on disc-shown' }, 'shown') : null]); } },
        { key: 'status', header: 'Status', filterable: true, value: function (r) { return r.status || ''; },
          cell: function (r) { return h('span', { class: 'chip disc-status-' + r.status }, [h('i'), cap(r.status)]); } },
        { key: 'mode', header: 'Mode', filterable: true, value: function (r) { return r.mode || 'passive'; } },
        { key: 'hosts', header: 'Hosts', align: 'right', value: function (r) { const c = r.counts || {}; return c.entities === undefined ? '' : c.entities; } },
        { key: 'links', header: 'Links', align: 'right', value: function (r) { const c = r.counts || {}; return c.entities === undefined ? '' : (c.connections || 0); } },
        { key: 'changes', header: 'Changes', align: 'right', value: function (r) { return r.diff && r.diff.against && r.diff.counts ? r.diff.counts.changes : ''; } },
        { key: 'elapsed', header: 'Duration', align: 'right', hideOnMobile: true, value: function (r) { return r.elapsed ? Math.round(r.elapsed) : ''; }, cell: function (r) { return r.elapsed ? Math.round(r.elapsed) + ' s' : ''; } },
        { key: 'by', header: 'By', filterable: true, hideOnMobile: true, value: function (r) { return r.by || ''; } },
        { key: 'id', header: 'Run id', hideOnMobile: true, value: function (r) { return r.id; }, cell: function (r) { return h('span', { class: 'mono muted' }, r.id); } },
      ],
      rowAttrs: function (r) { return { 'data-run': r.id, title: r.id === S.runId ? null : 'Show this run' }; },
      rowClass: function (r) { return 'disc-row disc-linked' + (r.id === S.runId ? ' disc-run-shown' : ''); },
      onRow: function (r) { goRun(r.id); },
    });
    return t;
  }

  // ------------------------------------------------------------ tabs and findings body
  function destroyTables() {
    S.tables.forEach(function (t) { try { t.destroy(); } catch (e) { console.warn(e); } });
    S.tables = [];
    S.primary = null;
  }

  function tabStrip(f) {
    const c = (f && f.counts) || {};
    const dc = S.diff && S.diff.diff && S.diff.diff.counts ? S.diff.diff.counts.changes : (S.run && S.run.diff && S.run.diff.against && S.run.diff.counts ? S.run.diff.counts.changes : null);
    const n = function (v) { return f ? v : null; };
    const tabs = [
      ['new', 'New devices', n(c.new || 0)], ['matches', 'Matches existing', n((c.matched || 0) + (c.possible || 0))], ['connections', 'Connections', n(c.connections || 0)],
      ['networks', 'Networks / VLANs', n(c.networks || 0)], ['unresolved', 'Unresolved', n((c.unresolved || 0) + (c.ignored || 0))], ['changes', 'Changes', f ? dc : null],
      ['runs', 'Runs', S.runs.length],
    ];
    const strip = h('div', { class: 'adm-tabs disc-tabs', role: 'tablist', 'aria-label': 'Findings' }, tabs.map(function (t) {
      const on = S.tab === t[0];
      return h('button', { type: 'button', role: 'tab', class: 'small disc-tab', id: 'disc-tab-' + t[0], 'data-disc-tab': t[0], 'aria-selected': on ? 'true' : 'false',
        'aria-controls': 'disc-tabpanel', tabindex: on ? '0' : '-1', onclick: function () { goTab(t[0]); } },
      t[1] + (t[2] === null || t[2] === undefined ? '' : ' (' + t[2] + ')'));
    }));
    strip.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' && e.key !== 'Home' && e.key !== 'End') return;
      const all = Array.prototype.slice.call(strip.querySelectorAll('[role=tab]'));
      let i = all.indexOf(document.activeElement);
      if (i < 0) return;
      e.preventDefault();
      if (e.key === 'Home') i = 0;
      else if (e.key === 'End') i = all.length - 1;
      else i = (i + (e.key === 'ArrowRight' ? 1 : -1) + all.length) % all.length;
      all[i].focus();
    });
    return strip;
  }
  function revealTab(strip) {
    const b = strip.querySelector('[aria-selected=true]');
    if (!b || strip.scrollWidth <= strip.clientWidth) return;
    strip.scrollLeft = Math.max(0, b.offsetLeft - (strip.clientWidth - b.offsetWidth) / 2);
  }

  function drawFindings() {
    const hadFocus = findWrap.contains(document.activeElement) && document.activeElement.getAttribute('data-disc-tab');
    destroyTables();
    findWrap.innerHTML = '';
    drawBadges();
    if (!S.loaded) { findWrap.appendChild(skeleton('table')); return; }
    if (!S.runs.length && !S.run) {
      findWrap.appendChild(emptyState({ title: 'No runs yet', text: ro() ? 'Discovery has not been run for this project.' : 'Run discovery to see what is on the network.' }));
      return;
    }
    const f = S.findings && S.findings.run === S.runId ? S.findings : null;
    if (f) {
      const c = f.counts || {};
      findWrap.appendChild(h('div', { class: 'row disc-summary' }, [
        h('span', { class: 'chip' }, (c.entities || 0) + ' hosts seen'), h('span', { class: 'chip' }, (c.cables || 0) + ' cables proposed'),
        h('span', { class: 'muted' }, 'computed against revision ' + (f.revision || 0) + (f.computed ? ' at ' + fmtTime(f.computed) : '')),
      ]));
    }
    const strip = tabStrip(f);
    findWrap.appendChild(strip);
    const body = h('div', { class: 'disc-tab-body', role: 'tabpanel', id: 'disc-tabpanel', 'aria-labelledby': 'disc-tab-' + S.tab, 'data-disc-tab': S.tab });
    findWrap.appendChild(body);
    if (S.tab === 'runs') runsTab(body);
    else if (S.run && S.run.active) body.appendChild(h('div', { class: 'muted' }, 'Findings appear when the run finishes.'));
    else if (S.findingsError) body.appendChild(inlineError(S.findingsError, function () { return S.run ? loadFindings() : showRun(S.runId); }));
    else if (S.loadingFindings || (S.runId && !f)) body.appendChild(skeleton('table'));
    else if (!f) body.appendChild(h('div', { class: 'muted' }, 'Pick a run above to see its findings.'));
    else if (S.tab === 'changes') diffTab(body);
    else ({ new: newDevicesTab, matches: matchesTab, connections: connectionsTab, networks: networksTab, unresolved: unresolvedTab })[S.tab](body, f);
    if (f) (f.notes || []).slice(0, 12).forEach(function (n) { findWrap.appendChild(h('div', { class: 'muted disc-notes' }, n)); });
    revealTab(strip);
    if (hadFocus) { const b = strip.querySelector('[aria-selected=true]'); if (b) b.focus(); }
  }

  // ------------------------------------------------------------ boot
  function loadAll() {
    return Promise.all([ctx.api.discoveryRuns(ctx.project), ctx.api.discoverySettings(ctx.project)]).then(function (rs) {
      if (S.destroyed) return;
      const first = !S.loaded;
      const runs = rs[0], st = rs[1];
      S.loaded = true;
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
      if (!first && S.runId) { drawRuns(); drawFindings(); return; }
      const want = ((ctx.route || {}).query || {}).run || '';
      const rid = want || S.active || (S.runs.length ? S.runs[0].id : '');
      S.runId = rid;
      canonical(true);
      if (!rid) { drawRuns(); drawRun(); drawFindings(); return; }
      if (rid === S.active) { drawRuns(); drawRun(); drawFindings(); poll(); return; }
      showRun(rid);
    }, function (e) {
      if (S.destroyed) return;
      S.loaded = true;
      canonical(true);
      srcWrap.innerHTML = '';
      srcWrap.appendChild(inlineError(e, loadAll));
      findWrap.innerHTML = '';
      findWrap.appendChild(inlineError(e, loadAll));
      drawRun();
    });
  }
  drawRun();
  drawFindings();
  loadAll();

  return {
    route: function (r) {
      if (S.destroyed || !S.loaded) return;
      const tab = TABS.indexOf(r.tab) >= 0 ? r.tab : DEFAULT_TAB;
      const want = (r.query || {}).run || '';
      let redraw = false;
      if (want && want !== S.runId) { S.tab = tab; showRun(want); redraw = true; }
      else if (tab !== S.tab) { S.tab = tab; drawFindings(); redraw = true; }
      if (!redraw && S.primary) S.primary.readUrl();
      if (tab !== r.tab || (!want && S.runId)) canonical(true);
    },
    destroy: function () {
      S.destroyed = true;
      stopPoll();
      destroyTables();
      if (age.destroy) age.destroy();
      el.innerHTML = '';
    },
  };
}
