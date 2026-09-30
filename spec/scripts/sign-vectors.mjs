// Regenerates vectors/signatures.json by signing each canonical string with keys/test-merchant-key.pem.
//
// PKCS#1 v1.5 is deterministic, so the output is stable and a diff means an input changed.
// Equivalent to, and checked against, the OpenSSL command line:
//
//   printf '%s' "<canonical>" | openssl dgst -sha256 -sign keys/test-merchant-key.pem | openssl base64 -A
//
//   node scripts/sign-vectors.mjs [--check]

import { readFileSync, writeFileSync } from 'node:fs';
import { createSign } from 'node:crypto';

const CASES = [
  {
    name: 'presto-worked-example',
    note: 'The canonical string from canonical.json, signed with the throwaway key rather than the merchant one.',
    canonical:
      '1200:MYR:Order #12345:PW2401XH9KCX:https://merchant.example.com/webhook/notify:PM240110XDSFC:https://merchant.example.com/redirect/TXN10001:20250423104500.000:TXN10001:WebPay',
  },
  {
    name: 'null-bearing-init-response',
    note: 'Leading separator from a null-valued first key.',
    canonical:
      ':200:MYR::::PP260924K4H3DSF:20260924133756.056:PendingAuthorise:https://hpp-staging.prestouniverse.com/PM181019QGJWH4K/PP260924K4H3DSF:PM181019QGJWH4K:true:20260924133756.056:PM202609244E33DA4FCCC7445B99821588791F2418:',
  },
  {
    name: 'business-error',
    canonical: '1201:Invalid input.:false:20260924124938.038',
  },
  {
    name: 'empty-canonical-string',
    note: 'A body whose only key is `signature`. Signing zero bytes must still work.',
    canonical: '',
  },
  {
    name: 'single-separator',
    note: 'Two empty values and nothing else.',
    canonical: ':',
  },
  {
    name: 'non-ascii-utf8',
    note: 'Signed over UTF-8 bytes, so a UTF-16 or Latin-1 encoding of the same string gives a different signature.',
    canonical: 'café:naïve:日本語:emoji 🧾:1',
  },
  {
    name: 'colon-heavy',
    canonical: 'https://x.example/a:b:c:d:1',
  },
];

const key = readFileSync(new URL('../keys/test-merchant-key.pem', import.meta.url));
const sign = (canonical) =>
  createSign('RSA-SHA256').update(canonical, 'utf8').end().sign(key, 'base64');

const generated = {
  $comment:
    'Canonical string -> Base64 RSASSA-PKCS1-v1_5/SHA-256 signature under keys/test-merchant-key.pem, ' +
    'verifiable with keys/test-merchant-public.pem or keys/test-merchant-cert.pem. ' +
    'Regenerate with scripts/sign-vectors.mjs; PKCS#1 v1.5 is deterministic, so the output is stable.',
  key: 'keys/test-merchant-key.pem',
  algorithm: 'RSASSA-PKCS1-v1_5 / SHA-256 / Base64 with padding',
  cases: CASES.map((c) => ({ ...c, signature: sign(c.canonical) })),
};

const target = new URL('../vectors/signatures.json', import.meta.url);
const text = JSON.stringify(generated, null, 2) + '\n';

if (process.argv.includes('--check')) {
  const current = readFileSync(target, 'utf8');
  if (current !== text) {
    console.error('vectors/signatures.json is stale; run: node scripts/sign-vectors.mjs');
    process.exit(1);
  }
  console.log(`vectors/signatures.json is up to date (${CASES.length} cases)`);
} else {
  writeFileSync(target, text);
  console.log(`wrote vectors/signatures.json (${CASES.length} cases)`);
}
