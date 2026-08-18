# Core-01 representation contract 001

Core defines **logical** appraisal values. §6.1 states that Core values are
logical, not carrier encodings. This document states how the public Core-01
vector corpus and the public reference tooling serialize those logical values,
so that an independent implementation can reproduce results byte-for-byte.

**Nothing here is normative Core semantics.** Core does not say how a logical
value is carried. Where this document and Core disagree about meaning, Core
wins; this document only fixes a carrier where Core deliberately leaves one open.

An independent implementation, written from the published specification alone,
reproduced all sixteen published appraisals except for one component whose
carrier encoding is not stated anywhere public. That is the gap this record
closes.

## R-001 — the logical value `unavailable`

§8.4 gives the logical value of every input-derived component in a fixed
rejection as `unavailable`. Core does not bind that logical value to a carrier
encoding.

    logical value:   unavailable
    harness carrier: JSON null

The public vector corpus and `wexp-ref` both use JSON `null`. An implementation
emitting the string `"unavailable"` is not semantically wrong; it will simply not
match the published projections byte-for-byte.

## R-002 — the top-level `representation` member

Public vector inputs carry a top-level `representation` member. Core does not
state whether this belongs to the Core AppraisalInput or to the harness
envelope.

    disposition: harness envelope, not Core AppraisalInput

It identifies the test representation the input is written in. A Core appraiser
does not derive semantics from it, and an input that omits it is not thereby
invalid Core input — it is simply not in the harness's expected shape.

## R-003 — `evaluation_context` sub-members

Public fixtures carry `evaluation_context` with an `id` and omit other members.
Core does not enumerate which sub-members are required, optional, or omissible.

    disposition: `id` is required by the harness schema; other sub-members are
    omitted rather than null when not applicable.

## R-004 — omitted, null, and unavailable are three different things

    omitted      the member is absent from the input
    null         the member is present and carries the logical value unavailable
    unavailable  the logical Core value, carried as null per R-001

An implementation that treats an omitted member as null, or null as an empty
value, will diverge from the published projections.

## R-005 — non-Core tokens and `profile_identifiers`

Recorded in [`CORE-01-KNOWN-ISSUES-001.md`](../known-issues/CORE-01-KNOWN-ISSUES-001.md) as KI-002. §6 requires
a non-Core token to resolve through an immutable registry revision identified by
an applied profile identifier; the published vector inputs carry no
`profile_identifiers` member, and the public set supplies the token through its
profile registry instead. KI-002 is unresolved; until a subsequent Core revision states the resolution rule, an implementation reproducing the public corpus should read non-Core tokens
from the candidate profile's registry.

## Boundary

This document defines the public representation/harness contract for the
applicable WEXP Core-01 tooling and vector surface. **It does not amend Core-01
normative semantics.** Where this contract and published Core-01 semantics
conflict, Core-01 remains the normative authority, subject to the explicitly
recorded project-maintained known issues.

## Scope

This contract describes the public Core-01 corpus and `wexp-ref` as published. It
does not change any expected semantic result, any published vector, or the
identity of any published artifact.
