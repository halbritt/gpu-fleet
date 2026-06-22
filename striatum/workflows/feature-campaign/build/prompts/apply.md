# Task — Apply accepted review findings and finalize

Read the verifier's finding. If it recorded `accept_with_findings` or
`needs_revision`, address each finding in the code and re-run
`python3 -m pytest tests/ -q` until green. If it recorded `accept`, confirm the tree
is still green and proceed to the report.

## Deliverable — the final report (at the declared artifact path)

List:

- Final files changed and the migration (`migrations/0NN_*.sql`, the number used).
- The falsifiable-gate → test map with the FINAL verbatim pytest result line.
- Every binding constraint from the committed plan, marked discharged.
- The EXACT operator deployment steps (the build did NOT perform these):
  1. `python3 -m pytest tests/ -q` is green on the integrated tree.
  2. Apply the new migration to the live `gpu_fleet` DB using **stop → migrate →
     start** for the `gpu-fleet-heartbeat` service if the change alters
     `probe_model`/sentinels; otherwise migrate-before-restart is sufficient.
  3. Re-deploy `cp bin/di-fleet ~/.local/bin/` if `bin/di-fleet` changed.
  4. `systemctl --user restart gpu-fleet-heartbeat`.

## Output contract

Stay inside the declared write scope. Do NOT run any deployment step yourself.
