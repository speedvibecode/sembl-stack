# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via
[GitHub Security Advisories](https://github.com/speedvibecode/sembl-stack/security/advisories/new)
(preferred) or by email to totlasiddharth@gmail.com. Do not open a public issue for
security reports.

You can expect an acknowledgement within a few days. Please include a reproduction
if you can.

## Scope notes

sembl-stack is a **local-first CLI**: it runs on the operator's machine, with the
operator's own credentials, against repositories the operator already controls. There
is no hosted service and no server-side data. The security surfaces we care most
about:

- **Credential handling** — profiles store only pointers (`env:VAR` / `keyring`),
  never key material; executor output is secret-scrubbed; third-party process output
  is persisted as fingerprints (byte count + SHA-256), never content.
- **Untrusted diff/content handling** — reviewer prompts treat the diff as data, not
  instructions; run artifacts are local and gitignored.
- **Release integrity** — PyPI publishing uses Trusted Publishing (OIDC, no stored
  tokens) with a version-lockstep guard.

Reports in any of these areas are especially appreciated.
