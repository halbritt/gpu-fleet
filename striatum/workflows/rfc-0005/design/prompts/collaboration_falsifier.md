# Task — Falsify the build plan

Read the published build plan and the RFC in context_docs. Write the strongest
justified falsifying challenge against the **PLAN** (not against the RFC's settled
design). Attack from the posture named in your work-packet objective. High-value
attack surfaces:

- A falsifiable-gate item with **no test**, or a test that would not actually prove
  it (e.g. claiming exclusivity without a genuine two-transaction concurrency test;
  claiming "no reaper" while a test secretly runs one; claiming a zombie is fenced
  without observing the renew return zero rows).
- A migration that is **not** backward-compatible, has the wrong apply order, or
  breaks the hermetic `python3 -m pytest tests/ -q` default.
- A slice whose blast radius is wrong, that is **not** independently committable, or
  that would silently touch live infra (the `gpu_fleet` DB, the
  `gpu-fleet-heartbeat` service, peecee's GPU) or violate the `di --json` shell-out
  boundary.
- An RFC open question the plan left unanswered, or a plan claim whose **refuting
  observation is actually achievable**.

## Refutation test

Name the claim challenged, the concrete evidence or counterexample, the strongest
rebuttal you can justify from the artifacts, and any unanswered gap.

## Output contract

Write ONLY your declared challenge artifact. Do not invent missing upstream content
and do not decide gate acceptance.
