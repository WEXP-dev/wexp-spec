# WEXP Specifications

This repository is the public publication boundary for explicitly published
states of the Witnessed Execution Protocol (WEXP) specifications. The
specifications are authoritative; implementations and test runners do not
override them.

This repository contains only explicitly published WEXP specification states.
Pre-publication development is maintained separately and does not constitute a
published specification state.

## State model

These states are deliberately distinct:

```text
development state
    != published repository state
    != IETF submission
    != remote IETF acceptance
```

GitHub Actions can check repository integrity and reproducibility declarations.
They do not establish WEXP semantic correctness, independent conformance, or
IETF acceptance.

## Published artifacts

`drafts/core/00/` contains the three official IETF archive artifacts for
`draft-sergeev-wexp-core-00`. Their current repository hashes and historical
import facts are recorded in `manifests/core-00.json`.

Core `-00` predates this repository pipeline. Its import must not be interpreted
as evidence that it was published through WEXP, or that an original WEXP
publication record exists.

## Specification and software version namespaces

Published specification identities use their document and revision namespace.

Reference implementation and vector versions use separate SemVer namespaces:

- `ref-v0.x.y`
- `vectors-v0.x.y`

IETF document revision identifiers and SemVer versions must not be mixed.
Historical tags or releases must not be manufactured solely to create a cleaner
repository history.

## Licensing / IETF legal status

Internet-Drafts and other IETF Contributions retain their applicable IETF legal
status; this repository does not apply a blanket software license to them.
Embedded notices remain authoritative for each artifact. See
[`LICENSES/IETF-TRUST.md`](LICENSES/IETF-TRUST.md),
[RFC 5378 / BCP 78](https://www.rfc-editor.org/rfc/rfc5378.html), and the
[IETF Trust Legal Provisions](https://trustee.ietf.org/documents/trust-legal-provisions/).
