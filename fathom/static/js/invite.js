// Invite page (/invite/<token>, FR-USER-11): asks the API whether the link is still open, lets the
// invitee pick a username and password, and lands them in the app with a session cookie. Plain
// ES2018, no imports beyond ./dom.js (the page must not pull the whole shell).
import { h, on } from './dom.js';

function $(id) { return document.getElementById(id); }

// App root from this script's URL (…/static/js/invite.js → …/), so the page works under a sub-path too.
function appRoot() {
  const s = document.querySelector('script[src*="js/invite.js"]');
  if (s && s.src) return s.src.replace(/static\/js\/invite\.js.*$/, '');
  return new URL('../', location.href).href;
}

function token() {
  const m = /\/invite\/(inv-[A-Za-z0-9_-]+)/.exec(location.pathname);
  return m ? m[1] : '';
}

function api(method, path, body) {
  const opts = { method: method, credentials: 'same-origin', headers: { Accept: 'application/json', 'X-Fathom': '1' } };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  return fetch(appRoot() + path, opts).then(function (res) {
    return res.text().then(function (text) {
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
      if (res.ok) return data || {};
      const err = new Error((data && data.error) || ('HTTP ' + res.status));
      err.status = res.status;
      err.code = data && data.code;
      throw err;
    });
  });
}

function setState(state) { $('invite').setAttribute('data-state', state); }

function roleLabel(role) {
  return role === 'admin' ? 'an administrator' : role === 'viewer' ? 'a viewer' : 'an editor';
}

function showInvalid() {
  setState('invalid');
  $('invite-intro').textContent = 'This invite link is no longer valid.';
  const err = $('invite-error');
  err.textContent = '';
  err.appendChild(h('span', {}, ['Ask the person who invited you for a new link, or ']));
  err.appendChild(h('a', { href: appRoot() + 'login' }, 'sign in'));
  err.appendChild(h('span', {}, [' if you already have an account.']));
}

function boot() {
  const form = $('invite-form');
  const err = $('invite-error');
  const tok = token();
  if (!tok) { showInvalid(); return; }
  api('GET', 'api/v2/invites/' + encodeURIComponent(tok) + '/check').then(function (inv) {
    setState('open');
    $('invite-intro').textContent = "You're invited to Fathom as " + roleLabel(inv.role) + '. Pick a username and a password to get started.';
    $('invite-user').focus();
  }, function (ex) {
    if (ex.status === 404) { showInvalid(); return; }
    setState('open');
    $('invite-intro').textContent = "You're invited to Fathom.";
    err.textContent = ex.status === 429 ? 'Too many attempts. Wait a few minutes and try again.' : 'Could not reach the server; try again in a moment.';
  });
  on(form, 'submit', function (e) {
    e.preventDefault();
    err.textContent = '';
    const user = $('invite-user').value.trim();
    const pass = $('invite-pass').value;
    if (pass !== $('invite-pass2').value) {
      err.textContent = 'The two passwords do not match.';
      $('invite-pass2').select();
      return;
    }
    const btn = $('invite-submit');
    btn.disabled = true;
    api('POST', 'api/v2/invites/' + encodeURIComponent(tok) + '/accept', { username: user, password: pass }).then(function () {
      location.href = appRoot();
    }, function (ex) {
      btn.disabled = false;
      if (ex.status === 404) { showInvalid(); return; }
      err.textContent = ex.status === 429 ? 'Too many attempts. Wait a few minutes and try again.'
        : ex.code === 'exists' ? 'That username is taken; pick another one.'
          : ex.message || 'Something went wrong.';
      if (ex.code === 'exists') $('invite-user').select();
    });
  });
}

if (document.getElementById('invite-form')) boot();
