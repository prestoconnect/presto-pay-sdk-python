# Security policy

This SDK signs and verifies payment requests with a merchant private key. If you find a vulnerability, report
it privately rather than opening a public issue. That covers signature verification, key handling, webhook
verification, or anything else.

## Reporting

Report privately through
[GitHub Security Advisories](https://github.com/prestoconnect/presto-pay-sdk-python/security/advisories/new).
Include:

- the affected version(s) and Python version;
- steps to reproduce, or a minimal example;
- what you expected to happen instead.

## Scope

In scope: this library's own code (`src/`). The keys under `spec/keys/` and `tests/fixtures/` are throwaway test
material that signs nothing but test vectors. Real merchant or Presto staging credentials must never be
committed.

## Supported versions

Before 1.0, only the latest published version is supported. From 1.0, this section will list which major
versions still receive security fixes.
