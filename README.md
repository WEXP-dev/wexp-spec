# WEXP Specifications

WEXP (Witnessed Execution) is an IETF-oriented specification effort for
classifying the evidentiary strength of claims about software and AI execution,
subject to explicit evidence and observation boundaries.

Logs, traces, approvals, tool-call records, and attestations provide different
kinds of evidence. WEXP distinguishes where an action was observed, how authentic
the resulting record is, and what execution-related claim the available
evidence can support. It grades evidentiary strength; it does not certify an
action's correctness, safety, or alignment.

This repository contains intentionally published WEXP specification states. The
specifications are authoritative; test vectors, implementations, runners, and
CI do not define or override them. Pre-publication development is maintained
separately and does not constitute a published specification state.

## Published specification

The currently published specification is
[`draft-sergeev-wexp-core-00`](https://datatracker.ietf.org/doc/draft-sergeev-wexp-core/00/).
It is an Internet-Draft, not an Internet Standard.

This repository includes copies of the official IETF archive files:

- [XML](drafts/core/00/draft-sergeev-wexp-core-00.xml)
- [Plain text](drafts/core/00/draft-sergeev-wexp-core-00.txt)
- [HTML](drafts/core/00/draft-sergeev-wexp-core-00.html)
- [Integrity and provenance manifest](manifests/core-00.json)

Core `-00` was published in the official IETF archive before this repository
was created, then imported here. The import and current integrity checks do not
claim that it was published through WEXP. This repository's Git root does not
replace or redefine the original IETF publication event.

## WEXP repositories

- [Specifications — `wexp-spec`](https://github.com/WEXP-dev/wexp-spec) —
  published WEXP specifications and their provenance.
- [Test vectors — `wexp-vectors`](https://github.com/WEXP-dev/wexp-vectors) —
  schemas and validation tools for implementation-independent WEXP test vectors.
- [Reference implementation — `wexp-ref`](https://github.com/WEXP-dev/wexp-ref)
  — the reference implementation and generic execution tools.

## Integrity and provenance

[`manifests/core-00.json`](manifests/core-00.json) records artifact identities,
public source URLs, and current SHA-256 digests. The repository verifier and CI
check declared hashes and XML syntax. A passing check does not establish WEXP
semantic correctness, protocol conformance, or IETF acceptance.

[`provenance/PUBLIC-GENESIS.json`](provenance/PUBLIC-GENESIS.json) inventories
the files in this repository's first authorized public commit. Later commits do
not amend that genesis inventory, and its timestamp does not claim that the
included files were originally created or published at the Git root.

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
