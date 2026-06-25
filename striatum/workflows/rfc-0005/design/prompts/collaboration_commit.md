# Task — Commit the gated build plan

Publish the committed build plan ONLY after the adjudicator ledger records a
clearing verdict (`accept` or `accept_with_findings`). If the ledger verdict is
`reject`, do not publish a plan — state that the gate refused and why.

## Deliverable — the committed build plan (at the declared artifact path)

The committed plan is the holder's build plan **amended with every binding
constraint** the adjudicator recorded. It is the exact contract the build run will
execute, so it must be self-contained:

- The ordered, independently-committable slices and their blast radius.
- The migration 006 schema + apply order.
- The falsifiable-gate → test map, with each binding constraint folded in (e.g. "a
  real two-transaction concurrency test is REQUIRED, not an assertion").
- The live-infra safety boundary and the `di --json` boundary.
- The exact operator deployment steps the RFC requires (so the build's final report
  can restate them).

## Acceptance link

Reference the clearing ledger and preserve every accepted constraint. Do NOT weaken
or drop a constraint the adjudicator recorded.

## Output contract

Write ONLY the declared publication artifact.
