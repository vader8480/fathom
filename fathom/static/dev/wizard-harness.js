// WIZARD dev harness (docs/ui-audit.md D10): openWizard and bulkAdd on the
// sunday-demo fixture with a fake ctx from app.js makeCtx. ctx.commit records
// {label, ops} in window.__wz.commits and applies them to the in-memory store.
// Query: ?smoke=1 sets data-smoke; ?open=devices|cables|generic opens a wizard;
// &sample=1 fills the paste step; &step=map|preview|review|result walks to it;
// ?readonly=1 makes the store read-only; window.__wz.failNext = true makes the
// next commit fail (returns null, as makeCtx's commit does on an error).
window.__fathomErrors = window.__fathomErrors || [];
(function () {
  const errs = window.__fathomErrors;
  window.addEventListener('error', function (e) { errs.push(String((e && e.message) || e)); });
  window.addEventListener('unhandledrejection', function (e) { errs.push('unhandled: ' + String(e && e.reason && (e.reason.stack || e.reason.message) || e.reason)); });
})();

const params = new URLSearchParams(location.search);

export const SAMPLES = {
  devices: [
    'Name\tRoom\tStatus\tKind\tManufacturer\tModel\tSerial no.',
    'Lectern Mic\tMain Auditorium\tplanned\tMicrophones\tShure\tMX418\tSN-1001',
    'Choir Mic L\tmain\tinstalled\tmic\tAudio-Technica\tPRO45\tSN-1002',
    'Choir Mic R\tmain\tinstalled\tmic\tAudio-Technica\tPRO45\tSN-1003',
    'Confidence Monitor\t\tspare\tdisplay\tLG\t43UN\t',
    'Lobby Speaker\tLobby\tplanned\tspeaker\tJBL\tControl 26\t',
    '\tmain\tplanned\tmic\tShure\tSM58\t',
    'Stage Box 2\tmain\tbroken\tstage_io\tYamaha\tRio1608\tSN-1004',
  ].join('\n'),
  cables: [
    'From\tTo\tTag\tType\tLength',
    'Main Speakers - L/R:Thru 1\tAudio Rack 1:Input 5\tA-101\tXLR3\t25',
    'main-speakers:thru-2\taudio-rack-1:analog-in-6\tA-102\tXLR3\t25',
    'Video Converter:HDMI Out\tSamsung TV - 1:HDMI 1\tV-101\tHDMI\t50',
    'Nowhere:Out 1\taudio-rack-1:analog-in-6\tA-103\tXLR3\t10',
  ].join('\n'),
};

function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

async function main() {
  const app = await import('../js/app.js');
  const dom = await import('../js/dom.js');
  const mc = await import('../js/model-core.js');
  const wz = await import('../js/wizard.js');
  const core = await import('../js/wizard-core.js');
  const [doc, meta] = await Promise.all([
    fetch('fixture-v2.json').then(function (r) { if (!r.ok) throw new Error('fixture: HTTP ' + r.status); return r.json(); }),
    fetch('/api/v2/meta', { headers: { Accept: 'application/json' } }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
  ]);
  const vocab = (meta && meta.vocab) || null;
  const store = mc.createStore({ doc: doc, vocab: vocab, readOnly: params.get('readonly') === '1', room: params.has('room') ? params.get('room') : 'main' });
  const logEl = document.getElementById('wz-h-log');
  const status = document.getElementById('wz-h-status');
  const state = { store: store, commits: [], results: [], core: core, wizard: wz, samples: SAMPLES, ctx: null, last: null };
  window.__wz = state;
  function log(text) {
    logEl.insertBefore(dom.h('li', null, text), logEl.firstChild);
  }
  const ctx = app.makeCtx(store, {
    api: null,
    project: 'sunday-demo',
    ensureCss: function () { return Promise.resolve(); },
    commit: function (ops, label) {
      if (store.readOnly) return null;
      if (state.failNext) { state.failNext = false; return null; }
      state.commits.push({ label: label, ops: JSON.parse(JSON.stringify(ops)) });
      const d = store.commit(ops, label);
      log(label + ' \u00b7 ' + ops.length + ' ops: ' + ops.map(function (o) { return o.op + ' ' + o.coll + '/' + o.id; }).join(', '));
      return d;
    },
  });
  state.ctx = ctx;
  store.addEventListener('doc', function (e) { status.textContent = (e.detail.source || '') + ': ' + (e.detail.label || '') + ' \u00b7 ' + store.doc.devices.length + ' devices, ' + store.doc.cables.length + ' cables'; });

  function track(p) {
    state.last = p;
    return p.then(function (res) { state.results.push(res); log('wizard closed: ' + JSON.stringify(res)); return res; });
  }
  state.open = function (kind) {
    if (kind === 'generic') return track(wz.openWizard(ctx, genericSpec()));
    return track(wz.bulkAdd(ctx, { kind: kind, room: store.room }));
  };
  document.getElementById('wz-h-devices').addEventListener('click', function () { state.open('devices'); });
  document.getElementById('wz-h-cables').addEventListener('click', function () { state.open('cables'); });
  document.getElementById('wz-h-generic').addEventListener('click', function () { state.open('generic'); });
  document.getElementById('wz-h-undo').addEventListener('click', function () { if (store.canUndo) store.undo(); });

  // A minimal two-step wizard (name + choice) exercising openWizard alone.
  function genericSpec() {
    return {
      title: 'New share link',
      data: { label: '', scope: 'project', days: '7' },
      steps: [{
        key: 'name', label: 'Name',
        render: function (body, d) {
          const input = dom.h('input', { name: 'label', id: 'wz-g-label', autocomplete: 'off' });
          input.value = d.label;
          input.addEventListener('input', function () { d.label = input.value; });
          body.appendChild(dom.h('div', { class: 'wz-field' }, [dom.h('label', { for: 'wz-g-label', class: 'wz-label' }, 'Link name'), input]));
        },
        validate: function (d) { return d.label.trim() ? {} : { label: 'Give the link a name' }; },
      }, {
        key: 'expiry', label: 'Expiry',
        render: function (body, d) {
          const days = dom.h('input', { name: 'days', id: 'wz-g-days', inputmode: 'numeric' });
          days.value = d.days;
          days.addEventListener('input', function () { d.days = days.value; });
          body.appendChild(dom.h('div', { class: 'wz-field' }, [dom.h('label', { for: 'wz-g-days', class: 'wz-label' }, 'Expires after (days)'), days]));
        },
        validate: function (d) { return /^\d+$/.test(d.days) && Number(d.days) > 0 ? {} : { days: 'Enter a whole number of days' }; },
      }],
      review: function (d) { return dom.h('p', null, 'Create “' + d.label + '” for ' + d.days + ' days.'); },
      submit: function (d) { state.commits.push({ label: 'share ' + d.label, ops: [] }); return Promise.resolve({ token: 'abc123', label: d.label }); },
      result: function (r) { return { text: 'Link “' + r.label + '” created.', href: '#/sunday-demo/main/settings/sharing?hl=' + r.token, hrefLabel: 'Open sharing settings' }; },
    };
  }

  // Scripted walk for screenshots: fill the paste step and press Next up to `step`.
  state.walk = async function (kind, step) {
    state.open(kind);
    await wait(80);
    const ta = document.querySelector('.wz textarea[name=text]');
    if (ta && SAMPLES[kind]) {
      ta.value = SAMPLES[kind];
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    }
    const order = ['paste', 'map', 'preview', 'review', 'result'];
    for (let i = 0; i < order.indexOf(step || 'paste'); i++) {
      const next = document.querySelector('.wz .wz-next');
      if (!next || next.disabled) break;
      next.click();
      await wait(150);
    }
  };

  if (params.get('open')) {
    if (params.get('sample') === '1' || params.get('step')) await state.walk(params.get('open'), params.get('step') || 'paste');
    else state.open(params.get('open'));
  }
  await wait(50);
  if (params.has('smoke')) {
    setTimeout(function () {
      document.documentElement.setAttribute('data-smoke', JSON.stringify({ ready: true, errors: window.__fathomErrors, stats: null }));
    }, 300);
  }
}

main().catch(function (err) {
  window.__fathomErrors.push('harness: ' + String(err && (err.stack || err.message) || err));
  if (params.has('smoke')) document.documentElement.setAttribute('data-smoke', JSON.stringify({ ready: false, errors: window.__fathomErrors, stats: null }));
});
