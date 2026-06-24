# RFC 0002 build — prior verifier finding + must-fix (READ THIS FIRST)

A prior build attempt (canceled) was correctly rejected by the independent verifier on
the **single-writer gate (BC1 / C9)**. Implement the committed plan's slices, and make
sure these two things are right — they are why the prior attempt failed.

## MUST-FIX 1 — write-time driver-lease fence (the blocking finding)

The prior build arbitrated the per-node driver-lease only at **pull FETCH time**
(`heartbeat_all.FETCH` filtered out already-leased nodes), but **not at WRITE time**, so
a stale pull write could still land after a self-pusher won the lease:

1. Puller `FETCH` snapshots node `quad` (no lease yet) and enters the probe phase.
2. A self-pusher acquires a fresh per-node lease and writes the row.
3. The puller's later `conn.execute(UPSERT, row)` **still overwrites** the measured
   fields — because the `UPSERT` admits pull rows with `EXCLUDED.boot_epoch IS NULL` and
   the boot-epoch ratchet does not fence a NULL-boot_epoch pull write. The verifier
   reproduced exactly this (`fetched=['quad']` → fresh lease `push/quad` → stale
   `m-PULL` write still landed). That refutes the RFC's "exactly one driver-lease holder,
   the other writer skipped" gate and the committed plan's required **C9** condition
   ("refuted by a test showing two concurrent committed writers for one (node, slot)").

**Required fix:** make the driver-lease re-checked **at write time, in the same
statement/transaction as the UPSERT**, so a pull write is refused for a `(node, slot)`
whose per-node driver-lease is currently held fresh by a *different* writer. Two viable
shapes (pick one, keep it server-side / DB-clock):
- Add a guard to the pull-write path keyed to `driven_by` / `lease_until`
  (`WHERE` / `CASE` on the UPSERT) that no-ops the pull write when another holder's lease
  is fresh; or
- Extend the boot-epoch ratchet so a NULL-`boot_epoch` (pull) write is fenced against a
  row whose driver-lease is fresh and held by a self-pusher.

**Required test:** drive the production `FETCH → pusher NODE_LEASE_CAS → UPSERT`
interleaving (fetch-before-push-before-write) and assert the stale pull write does **not**
land — exactly one committed writer per `(node, slot)`. Hermetic where possible; a
guarded ephemeral-Postgres companion for the real SQL is fine (mirror
`tests/test_leases_pg.py`'s `GPU_FLEET_TEST_DB` guard).

## MUST-FIX 2 — BC8: take the inert option (a)

Do **NOT** retire peecee's SSH `nvidia-smi` leg in v1. Live `ollama_ondemand_liveness`
fails closed if `gpu_stats` errors, so removing the SSH leg would make peecee report
`alive=False` and drop out of `routable_slots`. Keep peecee's existing SSH-via-pull
liveness, delete any operator SSH-retirement step, and narrow the "zero-SSH pull-only"
wording to "no fleet code/creds on the node." Do **NOT** modify `probe_node` /
`gpu_stats` / `ollama_ondemand_liveness`; option (b) (a real HTTP-only peecee liveness
path) is out of scope for this build. Keep the build inert wrt the live probe path.

## Preserve everything else

The prior attempt was otherwise sound (it passed the full PG-gated suite, 95 tests). The
committed plan's rollout safety is correct and MUST be kept: migration 009 backfills
existing `gpu_slots` rows to `status='routable'`, adds `routable_slots` **alongside**
`live_slots`, and **no consumer gates on `status` until the final slice** — behavior
equals today's during rollout. Only MUST-FIX 1 (write-time single-writer fence + its
test) and MUST-FIX 2 (BC8 option a) need correcting versus the prior attempt.
