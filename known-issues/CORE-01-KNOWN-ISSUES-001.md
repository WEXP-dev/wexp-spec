# Core-01 known issues 001 — `draft-sergeev-wexp-core-01`

**This is a project-maintained known-issues record for an Internet-Draft.**
Core-01 is an Internet-Draft, not an RFC. This document is **not** an RFC Editor
erratum, not an IETF-issued errata record, not a modification of the published
Internet-Draft, and not a new revision. It asserts nothing about RFC status.

Applies to the posted revision:

    draft-sergeev-wexp-core-01
    103095 bytes
    84c0a16467585c29925339a10dd287c2e67bfe21ed592826254bf424dc24f56d

**The published bytes are not modified.** This record states known issues in that
revision and the disposition intended for the next Core revision. Where an issue
concerns two normative passages that disagree, this record says which reading is
intended, so that implementers do not have to guess.

## KI-001 — §12 cross-field contract conflicts with the §13 fixture C14

**Status:** CONFIRMED — normative inconsistency in revision 01.
Normative clarification belongs in a subsequent Core revision.

§12 states, of the evaluation-scope cross-field contract:

> A scope value of `evaluated` with a governed `not-evaluated` status … violates
> the cross-field contract and produces `E_PROFILE_MAPPING_INVALID`.

`counter-entry status for counter-evidence` is one of the governed statuses that
sentence ranges over, and §6.2 evaluates the cross-field check before appraisal.

§13 fixture C14 is itself normative. It supplies:

    evaluation_scope["counter-evidence"] = "evaluated"
    a counter-entry with status "not-evaluated"

and requires appraisal to proceed and produce `downgrade` with the §8.6 gap
`E_COUNTER_EVIDENCE_NOT_EVALUATED`. It does **not** expect
`E_PROFILE_MAPPING_INVALID`.

Read strictly, §12 rejects at ingress what §13 requires to be appraised. Both are
normative, so the published text does not resolve which applies.

### Intended disposition

The C14 semantics are intended and are preserved:

    applicable counter-evidence with status not-evaluated
    → appraisal proceeds
    → the applicable §8.6 gap is reported

The counter-entry status must not be governed in a way that converts an
applicable `not-evaluated` counter-evidence entry into an ingress cross-field
rejection before §8 appraisal. The other directions of the §12 check — the
syntactic authenticity and composition cases — are unaffected.

### For implementers of revision 01

This is a project-maintained disposition of a known issue in revision 01, not a
change to the normative published bytes. Follow C14. An implementation that rejects that input at ingress is consistent
with one reading of §12 but produces a result the normative fixtures contradict.

## KI-002 — non-Core token in §13 fixture C15 without a profile identifier

**Status:** OPEN / UNDER REVIEW.

KI-002 is **not** classified as a confirmed Core defect. It is adjacent to
KI-001 but its normative disposition has not been ratified, and the KI-001
correction is deliberately not extended to it.

Fixture C15 uses the token `P_COUNTER_FAIL`, which is not a Core token. §6
requires a non-Core token to resolve uniquely through an immutable registry
revision identified by an applied profile identifier. The published vector inputs
carry no `profile_identifiers` member.

The public vector set supplies the token through its profile registry, so the
fixture is evaluable in practice. What the published text does not currently do
is state how a Core-conformant appraiser is expected to resolve a non-Core token
when the input carries no applied profile identifier.

This is recorded as a drafting gap, not as a decision. It is deliberately **not**
folded into the KI-001 correction.

## What this record does not do

It does not modify revision 01, publish a new revision, change any expected
vector result, or alter the published vector set. It has no effect on the
identity of any published artifact.
