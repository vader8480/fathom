// T2 gate G6 (SPEC §8.1, §2.3 item 9): fathom/static/**/*.js must be ES2018 syntax that runs in Safari 15+.
// Tokenises each file (strings, template literals, regex literals and comments are skipped) and
// rejects: ?.  ??  ||=  &&=  ??=  class fields  #private  static {  numeric separators  top-level await
// import.meta  plus other post-ES2018 syntax (optional catch binding, BigInt literals, export * as ns,
// hashbang) and regex features Safari 15 cannot parse (lookbehind, /d and /v flags). Also `node --check`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { STATIC, ROOT } from './fixtures/helpers.mjs';

const RULES = {
  'optional-chaining': '?. optional chaining (ES2020)',
  'nullish': '?? nullish coalescing (ES2020)',
  'logical-assign': '||= / &&= / ??= logical assignment (ES2021)',
  'class-field': 'class field declaration (ES2022)',
  'private': '#private name (ES2022)',
  'static-block': 'static { } class static block (ES2022)',
  'numeric-separator': 'numeric separator 1_000 (ES2021)',
  'bigint': 'BigInt literal (ES2020)',
  'top-level-await': 'top-level await outside functions (ES2022)',
  'import-meta': 'import.meta (ES2020)',
  'optional-catch': 'catch without binding (ES2019)',
  'export-star-as': 'export * as ns (ES2020)',
  'hashbang': '#! hashbang (ES2023)',
  'regex-lookbehind': 'regex lookbehind (?<= / (?<! (Safari < 16.4 cannot parse)',
  'regex-flag': 'regex flag d or v (ES2022+)',
};

const KW_EXPR = new Set(['return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete', 'void', 'throw', 'case', 'do', 'else', 'yield', 'await', 'extends']);
const PUNCS = ['>>>=', '...', '===', '!==', '**=', '<<=', '>>=', '>>>', '&&=', '||=', '??=', '=>', '==', '!=', '<=', '>=', '&&', '||', '??', '++', '--',
  '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<', '>>', '**'];
const ID_START = /[A-Za-z_$\u00c0-\uffff]/;
const ID_PART = /[\w$\u00c0-\uffff]/;

export function tokenize(src) {
  const toks = [];
  const findings = [];
  const n = src.length;
  let i = 0;
  let line = 1;
  const tpl = [];
  let depth = 0;
  const parens = [];
  let lastParenOpener = null;
  const add = (t, v, l) => toks.push({ t, v, line: l });
  const find = (rule, l) => findings.push({ rule, line: l });
  const last = () => toks[toks.length - 1];
  const regexOk = () => {
    const p = last();
    if (!p) return true;
    if (p.t === 'num' || p.t === 'str' || p.t === 'tpl' || p.t === 'regex') return false;
    if (p.t === 'id') return KW_EXPR.has(p.v);
    if (p.v === ')') return ['if', 'while', 'for', 'with'].includes(lastParenOpener);
    return p.v !== ']';
  };
  const readTemplate = (startLine) => {
    // i points just after ` or after the } closing a ${ }
    while (i < n) {
      const c = src[i];
      if (c === '\\') { if (src[i + 1] === '\n') line++; i += 2; continue; }
      if (c === '`') { i++; add('tpl', '`', startLine); return; }
      if (c === '$' && src[i + 1] === '{') { i += 2; add('tpl', '${', startLine); tpl.push(depth); depth++; return; }
      if (c === '\n') line++;
      i++;
    }
  };
  if (src.startsWith('#!')) { find('hashbang', 1); while (i < n && src[i] !== '\n') i++; }
  while (i < n) {
    const c = src[i];
    const d = src[i + 1];
    if (c === '\n') { line++; i++; continue; }
    if (c === ' ' || c === '\t' || c === '\r' || c === '\f' || c === '\v' || c === '\ufeff' || c === '\u00a0' || c === '\u2028' || c === '\u2029') { i++; continue; }
    if (c === '/' && d === '/') { while (i < n && src[i] !== '\n') i++; continue; }
    if (c === '/' && d === '*') {
      const end = src.indexOf('*/', i + 2);
      const stop = end < 0 ? n : end + 2;
      for (let k = i; k < stop; k++) if (src[k] === '\n') line++;
      i = stop; continue;
    }
    if (c === '"' || c === "'") {
      const l0 = line; i++;
      while (i < n && src[i] !== c) {
        if (src[i] === '\\') { if (src[i + 1] === '\n') line++; i += 2; continue; }
        if (src[i] === '\n') { line++; break; }
        i++;
      }
      i++; add('str', c, l0); continue;
    }
    if (c === '`') { i++; readTemplate(line); continue; }
    if (c === '}' && tpl.length && depth - 1 === tpl[tpl.length - 1]) {
      tpl.pop(); depth--; i++; readTemplate(line); continue;
    }
    if (/[0-9]/.test(c) || (c === '.' && /[0-9]/.test(d || ''))) {
      const mm = /^(?:0[xXoObB][0-9a-fA-F_]+n?|(?:[0-9][0-9_]*\.?[0-9_]*|\.[0-9][0-9_]*)(?:[eE][+-]?[0-9_]+)?n?)/.exec(src.slice(i, i + 64));
      const v = mm ? mm[0] : c;
      if (v.includes('_')) find('numeric-separator', line);
      if (/n$/.test(v)) find('bigint', line);
      add('num', v, line); i += v.length; continue;
    }
    if (c === '#' && ID_START.test(d || '')) { find('private', line); i++; continue; }
    if (ID_START.test(c) || c === '\\') {
      let j = i + 1;
      while (j < n && (ID_PART.test(src[j]) || src[j] === '\\')) j++;
      add('id', src.slice(i, j), line); i = j; continue;
    }
    if (c === '/' && regexOk()) {
      let j = i + 1; let cls = false; let ok = false;
      while (j < n) {
        const ch = src[j];
        if (ch === '\n') break;
        if (ch === '\\') { j += 2; continue; }
        if (cls) { if (ch === ']') cls = false; } else if (ch === '[') cls = true; else if (ch === '/') { ok = true; break; }
        j++;
      }
      if (ok) {
        const body = src.slice(i + 1, j);
        let k = j + 1;
        while (k < n && /[a-z]/i.test(src[k])) k++;
        const flags = src.slice(j + 1, k);
        if (/\(\?<[=!]/.test(body)) find('regex-lookbehind', line);
        if (/[dv]/.test(flags)) find('regex-flag', line);
        add('regex', body, line); i = k; continue;
      }
    }
    if (c === '?' && d === '.' && !/[0-9]/.test(src[i + 2] || '')) { add('punc', '?.', line); i += 2; continue; }
    let p = null;
    for (const cand of PUNCS) if (src.startsWith(cand, i)) { p = cand; break; }
    if (!p) p = c;
    if (p === '{') depth++;
    if (p === '}') depth--;
    if (p === '(') { const q = last(); parens.push(q && q.t === 'id' ? q.v : null); }
    if (p === ')') lastParenOpener = parens.pop();
    add('punc', p, line); i += p.length;
  }
  return { toks, findings };
}

function matchMap(toks) {
  const map = new Map();
  const st = [];
  const pairs = { ')': '(', ']': '[', '}': '{' };
  toks.forEach((t, i) => {
    if (t.t !== 'punc') return;
    if (t.v === '(' || t.v === '[' || t.v === '{') st.push(i);
    else if (pairs[t.v]) {
      for (let k = st.length - 1; k >= 0; k--) {
        if (toks[st[k]].v === pairs[t.v]) { map.set(st[k], i); st.length = k; break; }
      }
    }
  });
  return map;
}

const isP = (t, v) => t && t.t === 'punc' && t.v === v;
const isId = (t, v) => t && t.t === 'id' && (v === undefined || t.v === v);

export function scan(src) {
  const { toks, findings } = tokenize(src);
  const mm = matchMap(toks);
  const find = (rule, t) => findings.push({ rule, line: t ? t.line : 0 });
  for (let i = 0; i < toks.length; i++) {
    const t = toks[i];
    const prev = toks[i - 1];
    if (t.t === 'punc') {
      if (t.v === '?.') find('optional-chaining', t);
      else if (t.v === '??') find('nullish', t);
      else if (t.v === '||=' || t.v === '&&=' || t.v === '??=') find('logical-assign', t);
    }
    if (isId(t, 'import') && isP(toks[i + 1], '.') && isId(toks[i + 2], 'meta') && !isP(prev, '.')) find('import-meta', t);
    if (isId(t, 'catch') && isP(toks[i + 1], '{') && !isP(prev, '.')) find('optional-catch', t);
    if (isId(t, 'export') && isP(toks[i + 1], '*') && isId(toks[i + 2], 'as')) find('export-star-as', t);
    const nx = toks[i + 1];
    const realClass = isP(nx, '{') || (isId(nx) && !isP(toks[i + 2], ':') && !isP(toks[i + 2], ','));
    if (isId(t, 'class') && !isP(prev, '.') && realClass) {
      let j = i + 1; let pd = 0;
      while (j < toks.length) {
        const u = toks[j];
        if (isP(u, '(') || isP(u, '[')) pd++;
        else if (isP(u, ')') || isP(u, ']')) pd--;
        else if (isP(u, '{') && pd === 0) break;
        j++;
      }
      const close = mm.get(j);
      if (close !== undefined) scanClassBody(toks, j + 1, close, mm, find);
    }
  }
  // top-level await
  const KW_BLOCK = new Set(['if', 'for', 'while', 'switch', 'catch', 'with']);
  const parenOpenPrev = [];
  let lastClosedOpener = null;
  const braces = [];
  let fnDepth = 0;
  let nest = 0;
  const arrows = [];
  for (let i = 0; i < toks.length; i++) {
    const t = toks[i];
    const prev = toks[i - 1];
    if (t.t === 'punc') {
      if (t.v === '(') { parenOpenPrev.push(prev ? prev.v : null); nest++; }
      else if (t.v === ')') { lastClosedOpener = parenOpenPrev.pop(); nest--; }
      else if (t.v === '[') nest++;
      else if (t.v === ']') nest--;
      else if (t.v === '{') {
        const fn = isP(prev, '=>') || (isP(prev, ')') && !KW_BLOCK.has(lastClosedOpener));
        braces.push(fn); if (fn) fnDepth++; nest++;
      } else if (t.v === '}') { if (braces.pop()) fnDepth--; nest--; }
      if (t.v === '=>' && !isP(toks[i + 1], '{')) arrows.push(nest);
      while (arrows.length && (nest < arrows[arrows.length - 1] || ((t.v === ',' || t.v === ';') && nest === arrows[arrows.length - 1]))) arrows.pop();
    }
    if (isId(t, 'await') && fnDepth === 0 && !arrows.length && !isP(prev, '.')) find('top-level-await', t);
  }
  return findings;
}

function scanClassBody(toks, start, end, mm, find) {
  let j = start;
  while (j < end) {
    if (isP(toks[j], ';')) { j++; continue; }
    if (isId(toks[j], 'static') && isP(toks[j + 1], '{')) {
      find('static-block', toks[j]);
      j = (mm.get(j + 1) || j + 1) + 1; continue;
    }
    while (j < end && (isId(toks[j], 'static') || isId(toks[j], 'async') || isId(toks[j], 'get') || isId(toks[j], 'set') || isP(toks[j], '*')) &&
      !(isP(toks[j + 1], '(') || isP(toks[j + 1], '=') || isP(toks[j + 1], ';') || isP(toks[j + 1], '}'))) j++;
    const keyTok = toks[j];
    if (isP(keyTok, '[')) j = (mm.get(j) || j) + 1;
    else j++;
    const after = toks[j];
    if (isP(after, '(')) {
      j = (mm.get(j) || j) + 1;
      if (isP(toks[j], '{')) j = (mm.get(j) || j) + 1;
      continue;
    }
    find('class-field', keyTok);
    // skip the initializer up to the next ';' or newline-separated member at this level
    while (j < end && !isP(toks[j], ';')) {
      if (isP(toks[j], '(') || isP(toks[j], '[') || isP(toks[j], '{')) j = (mm.get(j) || j) + 1; else j++;
      if (toks[j] && toks[j - 1] && toks[j].line > toks[j - 1].line && !isP(toks[j - 1], '=') && toks[j].t === 'id') break;
    }
  }
}

// ---------------------------------------------------------------- self tests

const CASES = [
  ['a?.b', ['optional-chaining']],
  ['f?.(x)', ['optional-chaining']],
  ['x ? .5 : 1', []],
  ['a ?? b', ['nullish']],
  ['a ||= b; c &&= d; e ??= f', ['logical-assign', 'logical-assign', 'logical-assign']],
  ['const s = "a?.b ?? c ||= 1_000";', []],
  ["const s = 'it\\'s ?? fine';", []],
  ['const t = `x${a ? b : c}?.y ?? z`;', []],
  ['const t = `${`${a?.b}`}`;', ['optional-chaining']],
  ['const t = `${ {a: 1}.a } ${"}"} ?? `;', []],
  ['// a?.b ?? c\n/* x ||= y */ const q = 1;', []],
  ['const r = /a?.b??/g; const r2 = [/x?./];', []],
  ['const x = a / b / c?.d;', ['optional-chaining']],
  ['if (a) /re?./.test(s);', []],
  ['return /(?<=a)b/.test(s);', ['regex-lookbehind']],
  ['const r = /(?<name>a)/s;', []],
  ['const r = /a/d;', ['regex-flag']],
  ['class A { x = 1; m() {} }', ['class-field']],
  ['class A { static y; }', ['class-field']],
  ['class A { z\n m() {} }', ['class-field']],
  ['class A { #p; }', ['private', 'class-field']],
  ['class A { static { init(); } }', ['static-block']],
  ['class A extends B { constructor(o) { super(); this.x = 1; } get v() { return 1; } set v(x) {} static m() {} async n() { await 1; } *g() {} [k]() {} static async s() {} }', []],
  ['const C = class extends mix({a: 1}) { m() { return {x: 1}; } };', []],
  ["h('div', { class: 'a', role: 'b' }); const o = {class: x, y: 1}; el.class = 2; f({ class: c });", []],
  ['while (x) /a?./.exec(s);', []],
  ['const z = (a + b) / 2 / c;', []],
  ['const n = 1_000;', ['numeric-separator']],
  ['const n = 0x1F + 1e3 + .5 + 0.25;', []],
  ['const big = 10n;', ['bigint']],
  ['await x;', ['top-level-await']],
  ['if (a) { await x; }', ['top-level-await']],
  ['async function f() { await x; for await (const y of z) {} }', []],
  ['const f = async () => await x, g = 1;', []],
  ['const f = async (a) => { return await a; };', []],
  ['const o = { async m() { await 1; } };', []],
  ['obj.await = 1; x.import.meta = 2;', []],
  ['const u = import.meta.url;', ['import-meta']],
  ['const m = await import("./x.js");', ['top-level-await']],
  ['import("./x.js").then(function (m) { return m; });', []],
  ['try { a(); } catch { b(); }', ['optional-catch']],
  ['try { a(); } catch (e) { b(); } finally {}', []],
  ['export * as ns from "./x.js";', ['export-star-as']],
  ['export * from "./x.js"; export { a as b };', []],
  ['#!/usr/bin/env node\nconst a = 1;', ['hashbang']],
  ['const o = { a: 1 }; const q = o.a / 2 / 3;', []],
];

test('syntax lint self-test (tokeniser ignores strings, templates, regexes, comments)', () => {
  for (const [src, want] of CASES) {
    const got = scan(src).map((f) => f.rule).sort();
    assert.deepEqual(got, [...want].sort(), `lint self-test for ${JSON.stringify(src)}`);
  }
});

// ------------------------------------------------------------------ the gate

function listJs(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((f) => f.endsWith('.js')).sort().map((f) => path.join(dir, f));
}

const files = [...listJs(path.join(STATIC, 'js')), path.join(STATIC, 'sw.js'), ...listJs(path.join(STATIC, 'dev'))];

for (const f of files) {
  const rel = path.relative(ROOT, f);
  const present = existsSync(f);
  const why = rel.endsWith('sw.js') ? 'W1 fathom/static/sw.js not present' : `${rel} not present`;
  test(`ES2018 syntax: ${rel}`, { skip: present ? false : why }, () => {
    const src = readFileSync(f, 'utf8');
    const out = scan(src).map((x) => `${rel}:${x.line} ${RULES[x.rule]}`);
    assert.deepEqual(out, [], `G6 / §2.3 item 9: ES2019+ syntax in ${rel}:\n  ${out.join('\n  ')}`);
  });
  test(`node --check: ${rel}`, { skip: present ? false : why }, () => {
    const r = spawnSync(process.execPath, ['--check', f], { encoding: 'utf8' });
    assert.equal(r.status, 0, `G6: node --check ${rel} failed:\n${r.stderr}`);
  });
}
