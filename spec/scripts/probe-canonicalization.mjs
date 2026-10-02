// Resolves §13 round 2, question 1: how does Presto render `null` in the canonical string?
//
// Takes a signed body captured from the gateway and the Presto certificate, builds one
// candidate canonical string per competing rule, and reports which one the signature verifies
// against. Whichever wins becomes the [C] rule in §3.4 and a vector in spec/vectors/canonical.json.
//
//   node scripts/probe-null-canonicalization.mjs <body.json> <presto-cert.pem|der>

import { readFileSync } from 'node:fs';
import { createVerify, createPublicKey, X509Certificate } from 'node:crypto';

const [bodyPath, certPath] = process.argv.slice(2);
if (!bodyPath || !certPath) {
  console.error('usage: node scripts/probe-null-canonicalization.mjs <body.json> <presto-cert.pem|der>');
  process.exit(2);
}

const body = JSON.parse(readFileSync(bodyPath, 'utf8'));
const { signature } = body;
if (typeof signature !== 'string') throw new Error(`${bodyPath} has no "signature"`);
if (!Object.values(body).includes(null)) {
  console.warn('warning: this body contains no null, so every candidate will agree');
}

const raw = readFileSync(certPath);
const publicKey = (() => {
  const text = raw.toString('latin1');
  if (text.includes('-----BEGIN CERTIFICATE-----')) return new X509Certificate(text).publicKey;
  if (text.includes('-----BEGIN PUBLIC KEY-----')) return createPublicKey(text);
  return new X509Certificate(raw).publicKey;
})();

// §3.4: every key except `signature`, sorted by UTF-16 code unit, values rendered and joined with ':'.
const byCodeUnit = (a, b) => (a < b ? -1 : 1);
const render = (value, nullAs) => {
  if (value === null) return nullAs;
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return String(value);
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) throw new Error(`non-integer number: ${value}`);
    return String(value);
  }
  throw new Error(`unrenderable value: ${JSON.stringify(value)}`);
};

const canonical = (nullAs, { omitNulls = false } = {}) =>
  Object.keys(body)
    .filter((k) => k !== 'signature')
    .filter((k) => !(omitNulls && body[k] === null))
    .sort(byCodeUnit)
    .map((k) => render(body[k], nullAs))
    .join(':');

const candidates = [
  ['null renders as the empty string', canonical('')],
  ['the null key is omitted entirely', canonical('', { omitNulls: true })],
  ['null renders as the literal "null"', canonical('null')],
  ['null renders as "NULL"', canonical('NULL')],
];

const verifies = (text) =>
  createVerify('RSA-SHA256').update(text, 'utf8').end().verify(publicKey, signature, 'base64');

let winner = null;
for (const [label, text] of candidates) {
  const ok = verifies(text);
  if (ok && !winner) winner = label;
  console.log(`${ok ? 'MATCH ' : '      '} ${label}\n        ${text}\n`);
}

if (winner) {
  console.log(`Presto's rule: ${winner}`);
} else {
  console.log(
    'No candidate matched. Either the certificate is wrong, or some other rule in §3.4 is off —\n' +
      'check key sorting and the rendering of booleans and integers against a body with no nulls first.',
  );
  process.exit(1);
}
