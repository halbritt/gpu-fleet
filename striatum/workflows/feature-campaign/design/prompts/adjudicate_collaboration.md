# Task — Adjudicate the build-plan challenges

Read only the curated dialogue trajectory (the build plan and the falsifier
challenges) for the RFC in context_docs. Publish the **collaboration ledger** and a
verdict — one of `accept`, `accept_with_findings`, `needs_revision`, `reject`. A
clearing verdict (the one that lets the commit phase publish) is `accept` or
`accept_with_findings`; never write `clear` or any other value.

## Verdict basis

- Did any challenge **land** materially — i.e. expose a falsifiable-gate item with
  no real test, a non-backward-compatible migration, a live-infra leak, a broken
  `di --json` boundary, or a slice that is not independently committable?
- Did the plan answer it directly, or only deflect?
- Which surviving objections become **binding constraints** the build MUST
  discharge? State each as a concrete, checkable requirement (these carry into the
  committed plan and the build's verify gate).
- `needs_revision` only for substance the holder can repair in one cycle. `reject`
  only for an undischargeable defect (e.g. the design as specified cannot satisfy
  its own falsifiable gate). An honest `reject` with a truthful ledger is a
  successful gate outcome, not a failure.

## Output contract

Use the declared collaboration_ledger schema and verdict vocabulary. Do not read raw
provider logs or private diagnostics as evidence.
