# IETF publication pipeline

This directory holds the machine-checkable part of the boundary between
"a revision exists in this repository" and "a revision was submitted to the
IETF Datatracker".

```text
human publication authorization
        -> exact Publication Candidate
        -> exact public spec commit
        -> signed publication tag
        -> WEXP publication guard
        -> draft build, render and lint
        -> Datatracker submission API
        -> human confirmation email
        -> post-publication verification
```

Automation is transport, not publication authority. Nothing here shortens,
replaces, or bypasses IETF confirmation, author, rights, or Note Well
processes. The manual Datatracker submission tool remains the fallback.

## What may trigger a submission

Only an exact, annotated, signed publication tag whose name is exactly the
Internet-Draft revision identity, for example `draft-sergeev-wexp-core-01`.

No merge to `main`, no pull request, and no ordinary branch push can submit an
Internet-Draft. The prepare and submit workflows are separate files with
separate triggers, and the submit workflow additionally requires a repository
variable that is deliberately not set.

## Two phases

**Phase A — PREPARE** (`scripts/prepare_publication.py`) is safe to run
repeatedly and never submits. It copies the exact authorized XML, renders text
and HTML, lints, diffs against the previous published revision, runs the
publication guard, builds the submission request, and writes a bundle with
`SHA256SUMS` and `BUNDLE-MANIFEST.json`. It terminates with exactly
`READY FOR IETF SUBMISSION` or `NOT READY — <reason>`, and always prints
`SUBMISSION NOT PERFORMED`.

**Phase B — SUBMIT** consumes that exact bundle by digest. It must not rebuild
a different draft. It is currently hard-disabled.

## Publication guard

`scripts/publication_guard.py` performs fourteen fail-closed checks. Missing
evidence is a failure, never a pass.

| ID | Check |
|---|---|
| G01 | triggering ref is an allowed, exact publication tag |
| G02 | the tag resolves to the exact expected commit |
| G03 | the commit is on or derived from authorized public spec state |
| G04 | the tag is annotated and its signature verifies |
| G05 | the exact draft name and revision match the tag |
| G06 | the XML source identity is known and hashes as declared |
| G07 | XML `docName`, `ipr` and series metadata match the intended revision |
| G08 | the publication authorization record is present and exact |
| G09 | the Publication Candidate identity is present and exact |
| G10 | no dirty or generated divergence exists |
| G11 | the draft build and lint pass |
| G12 | no unpublished or private reference enters the artifacts |
| G13 | no secret or private material enters the artifacts |
| G14 | candidate-approved XML and submission XML are the same bytes |

## Authorization records

`authorizations/<draft-name>-<revision>.json` binds one exact revision. Two
record kinds exist:

- `publication_authorization` — a human authorized this exact revision. It
  carries the Publication Candidate identity, the authorized XML digest, the
  authorizing identity and date, and the submission parameters.
- `historical_import_non_authorization` — an artifact this pipeline must never
  submit. `submission.enabled` must be `false`. `draft-sergeev-wexp-core-00`
  uses this kind because Core-00 was published before this repository existed.

The Publication Candidate is referenced by `candidate_id`, an exact 40-hex
source commit, and exact SHA-256 digests. It is deliberately *not* referenced
by a repository URL: pre-publication material is maintained outside this
repository, and naming its location here would disclose unpublished work. A
public reader can therefore verify that a candidate identity was bound, and
that the submitted bytes match the authorized digest, but cannot independently
resolve the candidate. That limitation is explicit and is not claimed away.

G12 works from an allowlist of the three public WEXP repositories rather than a
list of private ones. A denylist would have to name the private repositories in
a public file — the disclosure the check exists to prevent — and would miss any
repository created later. It also rejects absolute developer or CI checkout
paths, and rejects Publication Candidate identifiers inside artifacts while
permitting them in the authorization record, which is where they belong.

## Authentication, secrets, and the human confirmation boundary

The Datatracker Internet-Draft submission interface
(`https://datatracker.ietf.org/api/submission`, observed 2026-08-14 against
Datatracker 12.71.0) takes **no API key and no bearer token**. It accepts
`multipart/form-data` with `user` (the submitter's Datatracker account email
address), `xml` (a single RFCXML file; XML-only, no text or combined uploads),
and optional `replaces`.

Consequences, stated plainly:

- **No Datatracker credential is stored in this repository, in GitHub Actions
  secrets, or in any workflow.** There is nothing to rotate and nothing a
  compromised workflow could exfiltrate for this endpoint. The submitter email
  address is already published inside the draft itself.
- A successful POST only *queues* a submission. Datatracker then emails the
  authors — for `-00`, the authors listed in the document; for `-01` and later,
  the authors of the **previous** revision — and a human must open that message
  and click the confirmation link.
- **Submission is therefore never fully unattended.** Any claim that this
  pipeline publishes an Internet-Draft without a human in the loop would be
  false. The pipeline automates preparation and transport up to the point where
  the IETF requires a person.
- Because no credential gates the endpoint, the meaningful protection is the
  guard plus the trigger design, not secret custody. That is why every guard
  check fails closed and why the submit workflow is disabled by default.

Should a future IETF interface introduce a credential, it will be configured as
a GitHub Actions secret scoped to a protected environment on the submit
workflow only, never referenced from a `pull_request`-triggered workflow, and
never echoed: the request preview redacts the submitter address and the client
never logs field values.

## Non-claims

- A prepared bundle is not an IETF submission, publication, or acceptance.
- A passing guard does not establish WEXP semantic correctness, conformance,
  or interoperability.
- Rendered text and HTML are regenerated representations, not the submitted
  bytes. Post-publication verification reports the archived XML relationship as
  `BYTE_IDENTICAL` only when the digests actually match.
