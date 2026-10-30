# Relationship-group overflow preflight

Follow-up to PR #400, reviewed head `686ce68e`. Fix: `e6668b65`.
All sanitized relationship groups are checked for integer overflow before the
first group is written. The existing `head` selection and `dry` behaviour remain.

The new unit regression fails on the reviewed implementation in all six cases:
one earlier query was already sent. The corrected tests cover missing and null
`code`, upper and lower integer bounds, valid groups, `head` and `dry`.
Live tests verify that rejection leaves no relationship on either engine.

Final counts, source hashes, server settings and immutable image identities are
in [summary.json](summary.json). Raw before/after logs are retained unchanged.
To reproduce the red check, copy the updated parameter-test file to a checkout
of `686ce68e` without changing its connector, then run that file with
`-k overflowing_edge_group`. The final suites run against the fix checkout.
Every test interpreter checks the imported connector path and SHA-256 first.

No benchmark was rerun and no performance conclusion was changed. PR #401 stays
in draft. Detailed evidence is separate from the upstream documentation.
