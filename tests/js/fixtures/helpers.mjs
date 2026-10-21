// Shared helpers for the T2 frontend tests (not a test file itself).
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(here, '..', '..', '..');
export const STATIC = path.join(ROOT, 'fathom', 'static');
export const JS = path.join(STATIC, 'js');

export function readJson(p) {
  return JSON.parse(readFileSync(p, 'utf8'));
}

export function fixturePath(name) {
  return path.join(here, name);
}

export function loadFixtureDoc() {
  return readJson(path.join(STATIC, 'dev', 'fixture-v2.json'));
}

export function loadVocab() {
  return readJson(fixturePath('vocab.json'));
}

// Prefer T1's shared file (tests/fixtures/<name>) and fall back to ours.
export function sharedFixture(name) {
  const t1 = path.join(ROOT, 'tests', 'fixtures', name);
  if (existsSync(t1)) return { source: 'T1 tests/fixtures/' + name, data: readJson(t1), path: t1 };
  const own = fixturePath(name);
  if (existsSync(own)) return { source: 'T2 tests/js/fixtures/' + name, data: readJson(own), path: own };
  return null;
}

// Load a module under fathom/static. Returns {mod, skip, error}:
//  - skip: string reason when the file is absent (tests must skip, naming the unit)
//  - error: import failure (tests must fail)
export async function loadModule(rel, unit) {
  const p = path.join(STATIC, rel);
  if (!existsSync(p)) return { mod: null, skip: `${unit} module ${rel} not present`, error: null };
  try {
    return { mod: await import(pathToFileURL(p).href), skip: false, error: null };
  } catch (e) {
    return { mod: null, skip: false, error: e };
  }
}

export function clone(x) {
  return x === undefined ? undefined : JSON.parse(JSON.stringify(x));
}

// JSON-normalized value (drops undefined, converts Sets to sorted arrays).
export function norm(x) {
  return JSON.parse(JSON.stringify(x, (k, v) => (v instanceof Set ? [...v].sort() : v)));
}

export function m(fr, sec, text) {
  return `${fr} (${sec}): ${text}`;
}

// Fails with an FR-tagged message when a contract export is missing.
export function need(mod, name, fr, sec) {
  if (!mod || typeof mod[name] === 'undefined') {
    throw new Error(m(fr, sec, `export \`${name}\` missing from module`));
  }
  return mod[name];
}

export function ids(list) {
  return (list || []).map((x) => (typeof x === 'string' ? x : x && (x.id || (x.device && x.device.id) || x.device)));
}

export function toSet(x) {
  if (x instanceof Set) return x;
  if (Array.isArray(x)) return new Set(x);
  if (x && typeof x === 'object') return new Set(Object.keys(x));
  return new Set();
}

// Canonical form that ignores collection order (entities sorted by id).
export function canonDoc(doc) {
  const d = clone(doc);
  for (const k of Object.keys(d || {})) {
    if (Array.isArray(d[k]) && d[k].every((e) => e && typeof e === 'object' && 'id' in e)) {
      d[k].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    }
  }
  return d;
}

export function device(doc, id) {
  return (doc.devices || []).find((d) => d.id === id);
}

export function cable(doc, id) {
  return (doc.cables || []).find((c) => c.id === id);
}

// Tiny deterministic PRNG (mulberry32).
export function rng(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
