# Contributing

This repository holds published specification states. Pre-publication
development is maintained separately. Artifacts enter this repository only
after machine checks and explicit human authorization.

Corrections to repository metadata, integrity tooling, or an inaccurately
imported artifact may be proposed through a focused pull request. Do not change
the normative meaning or bytes of a published draft as an editorial shortcut.
Any byte-level artifact change needs explicit provenance and review.

Contributions that are or become IETF Contributions remain subject to the
applicable IETF contribution rules, including BCP 78 / RFC 5378 and the
applicable IETF Trust Legal Provisions. A pull request does not replace the
applicable IETF submission process or place Internet-Draft text solely under a
repository software license.

External developers should be able to implement and test WEXP using
`wexp-spec` plus `wexp-vectors` without depending on `wexp-ref`. The reference
implementation is optional and is not a conformance oracle.

Before proposing a change:

1. Run `python3 scripts/verify_publication.py`.
2. Explain whether the change affects artifact bytes, metadata, or tooling.
3. Preserve the distinction between current repository integrity and original
   publication provenance.
4. Do not claim IETF acceptance, interoperability, independent verification,
   or complete protocol correctness unless the claimed event or result was
   actually observed.
