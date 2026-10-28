// Web Speech API wrapper for the assistant's voice input (§6.8, P4C). Thin on purpose: the
// browser does the recognition, this module hides the vendor prefix, keeps one active session
// and turns the event soup into {interim, final} callbacks. Safari and Chrome expose
// `webkitSpeechRecognition`; Firefox has nothing, so `available()` is false there and callers
// hide the microphone button.

let current = null;

function ctor() {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

export function available() {
  return !!ctor();
}

export function listening() {
  return !!current;
}

// Starts a session; returns the recogniser (or null when unavailable or when start() throws).
// o.onResult({interim, final, isFinal}) fires on every result event (final is the text of the
// results marked final in that event); o.onEnd() once the session stops (silence, stop(), or
// an error); o.onError(code) with the browser's error code ('not-allowed', 'no-speech',
// 'network', 'audio-capture', 'aborted', or 'unavailable' when the API is missing).
export function start(o) {
  o = o || {};
  const C = ctor();
  if (!C) { if (o.onError) o.onError('unavailable'); return null; }
  stop();
  let r;
  try { r = new C(); } catch (e) { if (o.onError) o.onError('unavailable'); return null; }
  const lang = o.lang || (typeof navigator !== 'undefined' && navigator.language) || 'en-US';
  try { r.lang = lang; } catch (e) { /* read-only in a stub */ }
  r.interimResults = o.interim !== false;
  r.continuous = !!o.continuous;
  r.maxAlternatives = 1;
  let ended = false;
  function end() {
    if (ended) return;
    ended = true;
    if (current === r) current = null;
    if (o.onEnd) o.onEnd();
  }
  r.onresult = function (e) {
    let interim = '';
    let fin = '';
    const results = (e && e.results) || [];
    const from = e && typeof e.resultIndex === 'number' ? e.resultIndex : 0;
    for (let i = from; i < results.length; i++) {
      const res = results[i];
      const alt = res && res[0];
      const t = alt && alt.transcript ? String(alt.transcript) : '';
      if (res && res.isFinal) fin += t;
      else interim += t;
    }
    if (o.onResult) o.onResult({ interim: interim, final: fin, isFinal: !!fin });
  };
  r.onerror = function (e) {
    if (o.onError) o.onError((e && e.error) || 'error');
  };
  r.onend = end;
  try {
    r.start();
  } catch (e) {
    if (o.onError) o.onError('unavailable');
    end();
    return null;
  }
  current = r;
  return r;
}

export function stop() {
  const r = current;
  current = null;
  if (!r) return;
  try { r.stop(); } catch (e) { /* already stopped */ }
}

// Human wording for the error codes the browsers send.
export function errorText(code) {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
      return 'Microphone access was denied. Allow it in the browser and try again.';
    case 'no-speech':
      return 'No speech was heard.';
    case 'audio-capture':
      return 'No microphone was found.';
    case 'network':
      return 'Speech recognition needs the network.';
    case 'aborted':
      return '';
    case 'unavailable':
      return 'Voice input is not available in this browser.';
    default:
      return 'Voice input failed' + (code ? ' (' + code + ')' : '') + '.';
  }
}
