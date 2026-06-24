---
schema_version: "striatum.synthesis.v1"
artifact_kind: "synthesis"
---

# FINAL_REPORT — RFC 0002: Zero-touch node lifecycle (build)

author: author-claude-opus-4.8-002

The build is **complete and green**. The independent verifier returned
`accept_with_findings` (`striatum/campaign/rfc-0002/build/review/VERIFICATION_REVIEW.md`,
`reviewer-openai-codex-gpt-5.5-001`), reviewing branch `striatum/rfc-0002-build-2` at
`ce891b1`. Its single finding is a **methodology note**, not a code defect: this run's Git
delta from `origin/master` is artifact/workflow-only, because the RFC-0002 implementation
source already integrated into `master` via the prior run
(`run_c0712bbd…`, merge `af991b8`); the verifier therefore verified the committed branch
source directly and confirmed every gate bullet and BC1–BC8 discharged under both the
hermetic and the PG-gated suites. **No source change was required by the finding.** I
re-confirmed the integrated tree is green and produced this report.

The two corrections that justified a second build attempt — **MUST-FIX 1** (the write-time
single-writer fence) and **MUST-FIX 2** (BC8 option (a)) — are both present and proven in
this tree (see §3 / §4).

---

## 1. Final files changed (and the migration)

Source delta of the RFC-0002 build vs. the pre-RFC-0002 baseline (`33657c2`, parent of the
first slice commit) → integrated `HEAD` (`ce891b1`):

| File | Δ | What it carries |
|------|----|-----------------|
| **`migrations/009_zero_touch_lifecycle.sql`** | **NEW (+56)** | The migration — **number `009`**, the lowest unused file (`001`–`008` exist). Purely additive: `gpu_slots` += `status`/`probe_streak`/`gpu_uuid`/`boot_epoch`; `fleet_nodes` += `driven_by`/`lease_until`; new single-row table `fleet_meta(holder, lease_until)`; backfill `UPDATE gpu_slots SET status='routable'`; new view `routable_slots` **alongside** `live_slots`; reverse block included. |
| `heartbeat.py` | +117 | Shared `UPSERT`: quarantine→graduate `status`/`probe_streak` CASE, `boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)`, `gpu_uuid` COALESCE, strict-`>` ratchet `WHERE`. `GRADUATION_STREAK = 3`. `next_boot_epoch()` (strictly-monotonic-per-write). Non-gating server-side per-node `NODE_LEASE_CAS`. Push path stamps `boot_epoch`; pull leaves it NULL. |
| `heartbeat_all.py` | +131 | `FETCH` server-side lease predicate (`driven_by IS NULL OR now() >= lease_until`); `fleet_meta` puller-lease CAS + `PULLER_LEASE_TTL = 15` (`< 45 s`), `NODE_LEASE_TTL = 30`; **stale-only PRUNE** (`… AND heartbeat_ts <= now() - interval '45 seconds'`); **MUST-FIX 1 — `pull_write()` / `PULL_WRITE_GUARD` write-time fence** (`SELECT 1 … FOR UPDATE` re-checks a fresh push-lease in the same txn as the UPSERT; puller yields → 0 rows). |
| `pick_slot.py` | +1 | `PICK` += `AND status = 'routable'` (Slice 4). |
| `di_fleet.py` | +5 | `LEASE_CLAIM_SQL` += `AND status = 'routable'` (Slice 4; renew/release unchanged). |
| `tests/test_graduation.py` | NEW (+273) | Hermetic state-machine + SQL-substring tests (graduation ladder, strict-`>` ratchet, uuid re-quarantine, DB-clock `heartbeat_ts`). |
| `tests/test_lifecycle_pg.py` | NEW (+360) | PG-guarded lifecycle tests incl. `test_pull_yields_when_push_acquires_after_fetch` (MUST-FIX 1) and all `binding: true` discharge tests. |
| `tests/test_driver_lease.py` | NEW (+98) | Hermetic FETCH-predicate / no-client-clock tests. |
| `tests/test_puller_lease.py` | NEW (+77) | Hermetic CAS + deadman-failover. |
| `tests/test_load_aware_liveness.py` | +39 | BC8 option (a): de-list when marker owns the card + `test_pull_only_node_has_no_db_path`. |
| `tests/test_leases_pg.py`, `tests/test_epoch_pg.py`, `tests/lease_fakes.py` | +5 / +39 / +10 | Fixture/guard alignment with the `009` columns. |
| `bin/di-fleet` | **unchanged** | Thin `exec python3 di_fleet.py` wrapper (committed plan §5 — not edited). |

Total: **13 files, +1188 / −23**.

---

## 2. FINAL verbatim pytest result

Hermetic default suite, run on the integrated tree at `ce891b1` in this build's worktree:

```text
$ python3 -m pytest tests/ -q
........................................................................ [ 90%]
........                                                                 [100%]
80 passed, 3 skipped in 1.24s
```

PG-gated full suite (verifier, throwaway Postgres 17 under `/tmp`, unix-socket only,
`GPU_FLEET_TEST_DB` = ephemeral `gpu_fleet_test`):

```text
$ GPU_FLEET_TEST_DB="dbname=gpu_fleet_test host=$PGDATA user=postgres" python3 -m pytest tests/ -q
........................................................................ [ 72%]
...........................                                              [100%]
99 passed in 4.06s
```

The 3 hermetic skips are the PG-guarded modules (`importorskip("psycopg")` +
`GPU_FLEET_TEST_DB` unset); they run and pass under the PG-gated invocation.

## 3. Falsifiable-gate → test map (RFC 0002)

| RFC gate bullet | Proving test(s) | Kind |
|---|---|---|
| **No SPOF** — kill the puller-lease holder ⇒ another drives within ≤ TTL, no age-out | `test_puller_lease.py::test_cas_grants_one_then_deadman_failover` · `test_lifecycle_pg.py::test_puller_failover_no_ageout` | hermetic + PG |
| **Zero-touch register** — self-report w/o `fleet_nodes`, appears `unverified`, graduates after N | `test_graduation.py::test_streak_promotes_after_N_and_demotes_on_break` · `test_lifecycle_pg.py::test_self_push_no_fleet_node_registers_and_graduates` (BC1, composed Slice-1+3) | hermetic + PG |
| **Anti-lie** — big-declared / small-measured never graduates; routes only measured | `test_graduation.py::test_failing_or_cold_probe_never_increments_streak` · `test_pick_slot.py` status-gate · `test_lifecycle_pg.py` big-declared-small-measured | hermetic + PG |
| **Single writer** — push vs pull ⇒ exactly one committed writer per `(node, slot)` | `test_driver_lease.py::test_fetch_predicate_skips_fresh_lease` (FETCH-time) · **`test_lifecycle_pg.py::test_pull_yields_when_push_acquires_after_fetch`** (MUST-FIX 1 write-time fence: fetch→push-CAS→write interleaving, stale pull write lands 0 rows) | hermetic + PG |
| **Identity survives churn** — rebooted node re-presents `gpu_uuid`, skips re-quarantine | `test_graduation.py::test_matching_uuid_carries_routable_forward` · `test_lifecycle_pg.py::test_reboot_same_uuid_skips_requarantine` · `…::test_hot_swap_demotes_to_unverified` | hermetic + PG |
| **peecee** runs zero fleet code/creds, still pull-monitored, de-lists when marker owns card | `test_load_aware_liveness.py` (de-list under existing SSH-via-pull liveness — option (a)) · `…::test_pull_only_node_has_no_db_path` | hermetic |
| **No node wall-clock** for `heartbeat_ts`/liveness | `test_graduation.py::test_upsert_stamps_heartbeat_ts_from_db_clock` · `test_lease_no_consumer_clock.py` · `test_driver_lease.py::test_fetch_freshness_uses_db_now_no_client_clock` | hermetic |

## 4. Binding constraints — all discharged

Confirmed present in this tree and confirmed by the verifier (review §"Binding Constraints").

| BC | Sev | Status | Evidence in the integrated tree |
|----|-----|--------|---------------------------------|
| **BC1** zero-touch self-push deadlock | high | **discharged** | Per-node lease CAS is **non-gating**; the UPSERT runs unconditionally (model c). `test_self_push_no_fleet_node_registers_and_graduates`. |
| **BC2** NULL pull-write erases ratchet | high | **discharged** | `boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)` (`heartbeat.py:84`). `test_boot_epoch_survives_null_pull_write`. |
| **BC6** equal-epoch replay overwrites | high | **discharged** | `next_boot_epoch()` strictly monotonic + strict `EXCLUDED.boot_epoch > gpu_slots.boot_epoch` (`heartbeat.py:110`, **never `>=`**). `test_equal_epoch_replay_is_noop` + `test_ratchet_predicate_is_strict_gt`. |
| **BC7** gpu_uuid hot-swap bypasses quarantine | high | **discharged** | `probe_streak`/`status` CASE resets to 1 / `unverified` on a non-NULL uuid mismatch. `test_uuid_mismatch_resets_streak_and_demotes` + `test_hot_swap_demotes_to_unverified`. |
| **BC3** puller-lease TTL vs 45 s | medium | **discharged** | `PULLER_LEASE_TTL = 15` (`< 45`). `test_puller_failover_no_ageout`. |
| **BC4** client wall-clock in skip | medium | **discharged** | FETCH **and** the write-time guard test freshness server-side (`now()`/`now() < lease_until`), no client timestamp. `test_fetch_freshness_uses_db_now_no_client_clock`. |
| **BC5** `fleet_meta` column name | low | **discharged** | DDL, CAS, and tests all name `holder`; PG tests run the real CAS on real `009`. |
| **BC8** peecee pull-only vs SSH-retirement | medium | **discharged (option a)** | **MUST-FIX 2:** peecee keeps its cross-host SSH `nvidia-smi` `gpu_cmd`; no edit to `probe_node`/`gpu_stats`/`ollama_ondemand_liveness`; **no SSH-retirement step ships**; no false "HTTP-only liveness" claim. `test_load_aware_liveness.py` + `test_pull_only_node_has_no_db_path`. |

`final_review_required` constraints (BC1, BC2, BC6, BC7, BC8): all green; the ratchet `WHERE`
remains strict `>`. Settled RFC design not re-opened.

---

## 5. EXACT operator deployment steps

> The build did **NOT** perform any of these. The build is inert wrt live infra: it touched
> only `migrations/009`, the source files above, and the **hermetic** test run. It did not
> connect to the live `gpu_fleet` DB, restart `gpu-fleet-heartbeat`, SSH to peecee, or touch
> a GPU. Apply order: **DB → writer → consumers**.

1. **Confirm green on the integrated tree:**
   ```bash
   python3 -m pytest tests/ -q          # expect: 80 passed, 3 skipped
   ```

2. **Apply migration `009` to the live `gpu_fleet` DB.**
   This change does **not** alter `probe_model`/sentinels (BC8 option (a) keeps peecee's
   existing probe path; `009` is purely additive `ADD COLUMN IF NOT EXISTS` / `CREATE …
   IF NOT EXISTS` + one backfill + one new view) — so **migrate-before-restart is
   sufficient**; a `stop → migrate → start` of `gpu-fleet-heartbeat` is **not** required
   (and the migration is safe even with the heartbeat running):
   ```bash
   psql "$GPU_FLEET_DSN" -f migrations/009_zero_touch_lifecycle.sql
   ```
   (Re-apply is idempotent. The backfill sets every existing slot `status='routable'`, so
   the later consumer gate strands nothing.)

3. **Re-deploy the consumer code on consumer hosts.** `bin/di-fleet` itself is **unchanged**
   (thin wrapper), so `cp bin/di-fleet ~/.local/bin/` is a no-op for this build — but update
   the gpu-fleet **checkout** on consumer hosts so the new `di_fleet.py` and `pick_slot.py`
   (the `status='routable'` gate) take effect:
   ```bash
   git -C ~/git/gpu-fleet pull        # or redeploy the checkout the consumers import
   cp bin/di-fleet ~/.local/bin/      # only if bin/di-fleet changes in a future build
   ```

4. **Restart the heartbeat writer:**
   ```bash
   systemctl --user restart gpu-fleet-heartbeat
   ```

After step 4 the writer populates `status`/`boot_epoch`, honors the per-node lease
server-side, and protects self-push rows via the stale-only PRUNE; new nodes appear
`unverified` and graduate after 3 alive probes. The SPOF kill (a **second** puller) and any
**push** sidecar on the trusted quad-server are separate, optional operator steps; **peecee
stays pull-only** (no fleet code/creds), monitored as today.
