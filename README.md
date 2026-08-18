# WEXP Specifications

WEXP (Witnessed Execution Protocol) is an IETF-oriented specification effort
for evaluating support for claims about software and AI execution within
explicit evidence and observation boundaries.

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

The current specification state is `draft-sergeev-wexp-core-01`. It is an
Internet-Draft, not an Internet Standard.

- [XML](drafts/core/01/draft-sergeev-wexp-core-01.xml) — the authoritative artifact
- [Plain text](drafts/core/01/draft-sergeev-wexp-core-01.txt)
- [HTML](drafts/core/01/draft-sergeev-wexp-core-01.html)
- [Integrity and provenance manifest](manifests/core-01.json)

These are frozen bytes, published unchanged. Revision `01` is posted at the IETF
as [`draft-sergeev-wexp-core-01`](https://datatracker.ietf.org/doc/draft-sergeev-wexp-core/01/)
(2026-08-17). The XML the IETF serves is byte-identical to the XML here, and so
is the plain text; the IETF renders its own HTML, which differs as expected.
Being posted is not IETF adoption, working-group acceptance, or standardization.

### Previous revision

[`draft-sergeev-wexp-core-00`](https://datatracker.ietf.org/doc/draft-sergeev-wexp-core/00/)
remains available:

- [XML](drafts/core/00/draft-sergeev-wexp-core-00.xml)
- [Plain text](drafts/core/00/draft-sergeev-wexp-core-00.txt)
- [HTML](drafts/core/00/draft-sergeev-wexp-core-00.html)
- [Integrity and provenance manifest](manifests/core-00.json)

Core `-00` was published in the official IETF archive before this repository
was created, then imported here. The import and current integrity checks do not
claim that it was published through WEXP. This repository's Git root does not
replace or redefine the original IETF publication event.

## Known issues and representation

[`known-issues/CORE-01-KNOWN-ISSUES-001.md`](known-issues/CORE-01-KNOWN-ISSUES-001.md)
is a **project-maintained** known-issues record for the posted revision `-01`.
Core-01 is an Internet-Draft, not an RFC: this is not an RFC Editor erratum and
does not modify the published draft. It records KI-001, a confirmed inconsistency
between §12 and the normative fixture C14, with the project's selected
interpretation, and KI-002, an adjacent question that remains open.

[`representation/CORE-01-REPRESENTATION-CONTRACT-001.md`](representation/CORE-01-REPRESENTATION-CONTRACT-001.md)
states how the public corpus and tooling serialize Core's logical values. It is
carrier detail and does not amend Core semantics.

## Reporting a vulnerability

See [`SECURITY.md`](SECURITY.md). Security vulnerabilities in WEXP Core should be
reported through GitHub Private Vulnerability Reporting for this repository.

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
