# WEXP Specifications

WEXP (Witnessed Execution Protocol) is an IETF-oriented specification effort
for classifying the evidentiary strength of claims about actions performed by
software and AI systems within explicit evidence and observation boundaries.

Logs, traces, approvals, tool-call records, and attestations can establish
different facts. WEXP distinguishes where an action was observed, how authentic
the resulting record is, and what execution-related claim the available
evidence can support. It grades evidentiary strength; it does not certify an
action's correctness, safety, or alignment.

This repository contains intentionally published WEXP specification states. The
specifications are authoritative; test vectors, implementations, runners, and
CI do not define or override them. Pre-publication development is maintained
separately and does not constitute a published specification state.

## Published specification state

The current published specification state is
[`draft-sergeev-wexp-core-00`](https://datatracker.ietf.org/doc/draft-sergeev-wexp-core/00/).
It is an Internet-Draft, not an Internet Standard.

Repository copies of the official IETF archive artifacts are available as:

- [XML](drafts/core/00/draft-sergeev-wexp-core-00.xml)
- [Plain text](drafts/core/00/draft-sergeev-wexp-core-00.txt)
- [HTML](drafts/core/00/draft-sergeev-wexp-core-00.html)
- [Integrity and provenance manifest](manifests/core-00.json)

Core `-00` predates this repository pipeline and was imported later from the
official IETF archive. Its import and current integrity checks do not claim that
it was published through WEXP. The repository's Git root does not replace or
redefine the original IETF publication event.

## WEXP repositories

- [Specifications — `wexp-spec`](https://github.com/WEXP-dev/wexp-spec) —
  published WEXP specification states.
- [Test vectors — `wexp-vectors`](https://github.com/WEXP-dev/wexp-vectors) —
  implementation-independent test-vector infrastructure.
- [Reference implementation — `wexp-ref`](https://github.com/WEXP-dev/wexp-ref)
  — conservative implementation and generic tooling bounded by published WEXP
  specifications.

## Integrity and provenance

[`manifests/core-00.json`](manifests/core-00.json) records artifact identities,
public source URLs, and current SHA-256 digests. The repository verifier and CI
check declared hashes and XML syntax. A passing check does not establish WEXP
semantic correctness, protocol conformance, or IETF acceptance.

[`provenance/PUBLIC-GENESIS.json`](provenance/PUBLIC-GENESIS.json) records the
first intentionally authorized public repository state. Later commits do not
amend that genesis inventory, and its timestamp does not claim that the
included artifacts were originally created or published at the Git root.

## Licensing / IETF legal status

Internet-Drafts and other IETF Contributions retain their applicable IETF legal
status; this repository does not apply a blanket software license to them.
Embedded notices remain authoritative for each artifact. See
[`LICENSES/IETF-TRUST.md`](LICENSES/IETF-TRUST.md),
[RFC 5378 / BCP 78](https://www.rfc-editor.org/rfc/rfc5378.html), and the
[IETF Trust Legal Provisions](https://trustee.ietf.org/documents/trust-legal-provisions/).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for repository contribution guidance.
A pull request does not replace the applicable IETF submission process.
