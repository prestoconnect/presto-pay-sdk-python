// Checks the vectors against themselves, with no SDK involved.
//
//   1. Every canonical.json case: build the canonical string from the body per wire-contract.md §4
//      and compare, or confirm the case is rejected for the stated reason.
//   2. Every captured case carrying a signature: verify it against the certificate in `verifyWith`.
//      This is what keeps the null rule honest — it is proven, not asserted.
//   3. Every signatures.json case: verify against the throwaway public key.
//   4. Every timestamps.json case: format and parse in both directions.
//
// This file is a second implementation of the contract, deliberately naive and deliberately not the SDK,
// so an SDK bug cannot agree with it by construction.
//
//   node scripts/verify-vectors.mjs

import { readFileSync } from 'node:fs';
import { createVerify, createPublicKey, X509Certificate } from 'node:crypto';

const root = new URL('..', import.meta.url);
const read = (p) => readFileSync(new URL(p, root));
const readJson = (p) => JSON.parse(read(p).toString('utf8'));

let failures = 0;
const check = (ok, label, detail) => {
  if (!ok) {
    failures += 1;
    console.error(`  FAIL ${label}${detail ? `\n       ${detail}` : ''}`);
  }
  return ok;
};

const MAX_SAFE = 9007199254740991n;

// wire-contract.md §4, written out longhand.
function canonicalize(text) {
  const body = JSON.parse(text, (_key, value) => {
    if (typeof value === 'number' && !Number.isSafeInteger(value)) {
      throw new RangeError('non-integer number or integer outside ±(2^53 − 1)');
    }
    return value;
  });
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    throw new TypeError('not a JSON object');
  }
  // JSON.parse has already rounded oversized integers, so re-check the raw token text.
  for (const token of text.match(/-?\d{16,}/g) ?? []) {
    const n = BigInt(token);
    if (n > MAX_SAFE || n < -MAX_SAFE) throw new RangeError('integer outside ±(2^53 − 1)');
  }
  return Object.keys(body)
    .filter((k) => k !== 'signature')
    .sort()
    .map((k) => {
      const v = body[k];
      if (v === null) return '';
      if (typeof v === 'string') return v;
      if (typeof v === 'boolean') return String(v);
      if (typeof v === 'number') return String(v);
      throw new TypeError(Array.isArray(v) ? 'array value' : 'object value');
    })
    .join(':');
}

function publicKeyFrom(path) {
  const raw = read(path);
  const text = raw.toString('latin1');
  if (text.includes('-----BEGIN CERTIFICATE-----')) return new X509Certificate(text).publicKey;
  if (text.includes('-----BEGIN PUBLIC KEY-----')) return createPublicKey(text);
  return new X509Certificate(raw).publicKey;
}

const verifies = (canonical, signature, key) =>
  createVerify('RSA-SHA256').update(canonical, 'utf8').end().verify(key, signature, 'base64');

console.log('canonical.json');
const canonical = readJson('vectors/canonical.json');
let signed = 0;
for (const c of canonical.cases) {
  const text = 'bodyRaw' in c ? c.bodyRaw : JSON.stringify(c.body);
  let produced;
  let error;
  try {
    produced = canonicalize(text);
  } catch (e) {
    error = e;
  }

  if ('reject' in c) {
    check(error !== undefined, c.name, `expected rejection (${c.reject}), got "${produced}"`);
    continue;
  }
  if (error) {
    check(false, c.name, `unexpected rejection: ${error.message}`);
    continue;
  }
  if (!check(produced === c.canonical, c.name, `expected ${JSON.stringify(c.canonical)}\n       produced ${JSON.stringify(produced)}`)) {
    continue;
  }
  if (c.signature) {
    const ok = verifies(c.canonical, c.signature, publicKeyFrom(c.verifyWith));
    check(ok, `${c.name} (signature)`, 'signature does not verify over the canonical string');
    if (ok) signed += 1;
  }
}
console.log(`  ${canonical.cases.length} cases, ${signed} verified against a real gateway signature`);

console.log('signatures.json');
const signatures = readJson('vectors/signatures.json');
const testKey = publicKeyFrom('keys/test-merchant-public.pem');
for (const c of signatures.cases) {
  check(verifies(c.canonical, c.signature, testKey), c.name, 'does not verify under the test key');
}
console.log(`  ${signatures.cases.length} cases`);

console.log('timestamps.json');
const TZ = 8 * 3600 * 1000;
const pad = (n, w) => String(n).padStart(w, '0');
const format = (ms) => {
  const d = new Date(ms + TZ);
  return (
    `${pad(d.getUTCFullYear(), 4)}${pad(d.getUTCMonth() + 1, 2)}${pad(d.getUTCDate(), 2)}` +
    `${pad(d.getUTCHours(), 2)}${pad(d.getUTCMinutes(), 2)}${pad(d.getUTCSeconds(), 2)}` +
    `.${pad(d.getUTCMilliseconds(), 3)}`
  );
};
const parse = (ts) => {
  if (!/^\d{14}\.\d{3}$/.test(ts)) throw new RangeError('wrong length or non-digit character');
  const n = (a, b) => Number(ts.slice(a, b));
  const [y, mo, d, h, mi, s, ms] = [n(0, 4), n(4, 6), n(6, 8), n(8, 10), n(10, 12), n(12, 14), n(15, 18)];
  const at = Date.UTC(y, mo - 1, d, h, mi, s, ms) - TZ;
  const back = new Date(at + TZ);
  if (
    back.getUTCFullYear() !== y || back.getUTCMonth() + 1 !== mo || back.getUTCDate() !== d ||
    back.getUTCHours() !== h || back.getUTCMinutes() !== mi || back.getUTCSeconds() !== s
  ) {
    throw new RangeError('not a calendar date');
  }
  return at;
};

const timestamps = readJson('vectors/timestamps.json');
for (const c of timestamps.format) {
  check(format(c.epochMillis) === c.ts, `${c.name} (format)`, `expected ${c.ts}, produced ${format(c.epochMillis)}`);
  let parsed;
  try {
    parsed = parse(c.ts);
  } catch (e) {
    check(false, `${c.name} (parse)`, e.message);
    continue;
  }
  check(parsed === c.epochMillis, `${c.name} (parse)`, `expected ${c.epochMillis}, produced ${parsed}`);
  check(new Date(c.epochMillis).toISOString() === c.utc, `${c.name} (utc)`, `expected ${c.utc}`);
}
for (const c of timestamps.parse) {
  let ok = false;
  try {
    parse(c.ts);
  } catch {
    ok = true;
  }
  check(ok, `${c.name}`, `expected rejection (${c.reject})`);
}
console.log(`  ${timestamps.format.length} format cases, ${timestamps.parse.length} parse rejections`);

if (failures) {
  console.error(`\n${failures} failure(s)`);
  process.exit(1);
}
console.log('\nall vectors consistent');
