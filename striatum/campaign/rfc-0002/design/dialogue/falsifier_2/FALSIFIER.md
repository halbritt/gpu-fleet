# FALSIFIER - RFC 0002 build plan challenge (falsifier_2)

author: falsifier-antigravity-gemini-003

## 1. Resolution of Prior Challenges (BC1 - BC7)

The revised build plan (holder-claude-opus-4.8-003) successfully applies the necessary SQL, control-flow, and test coverage to resolve all seven challenges from cycle 2.

### BC1: Zero-Touch Self-Push Registration Deadlock
- **Resolution:** The plan adopts arbitration model (c), making the `gpu_slots` UPSERT unconditional for registering self-pushers. The per-node driver lease in `fleet_nodes` is treated as a best-effort coordination signal, so the absence of a `fleet_nodes` row no longer blocks initial registration.
- **Verification:** A composed Slice 1+3 test is added to prove that a self-pusher without a pre-existing `fleet_nodes` row successfully registers a row as `unverified` and graduates to `routable` after N probes, while the puller continues to skip/contend appropriately.

### BC2: Boot-Epoch Ratchet Wiped by NULL Pull-Write
- **Resolution:** The SQL SET clause is updated to use `boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)`. This ensures that a pull-mode write (which carries a NULL `boot_epoch`) preserves the stored integer epoch stamped by a prior self-pusher.
- **Verification:** A PG-guarded test proves that the stored epoch survives subsequent pull writes and that any strictly-stale push write continues to be refused.

### BC6: Equal-Epoch Replay Overwrite
- **Resolution:** The plan changes `boot_epoch` to be strictly monotonic per write (`next_boot_epoch`) rather than constant per boot. This permits the ratchet comparator to use a strict `EXCLUDED.boot_epoch > gpu_slots.boot_epoch` check.
- **Verification:** A PG-guarded test asserts that a same-epoch replay with a modified payload is completely ignored (no fields are changed and `heartbeat_ts` is not updated).

### BC7: GPU Hot-Swap Quarantine Bypass
- **Resolution:** The SQL update clause now resets `probe_streak` to 1 (if alive) and demotes `status` to `'unverified'` whenever `gpu_slots.gpu_uuid` and `EXCLUDED.gpu_uuid` are both non-NULL and differ (`gpu_slots.gpu_uuid <> EXCLUDED.gpu_uuid`).
- **Verification:** Both a hermetic and a PG-guarded test verify that a slot with a mismatched UUID is immediately quarantined and must complete a fresh graduation streak.

### BC3: Puller-Lease Failover Age-Out
- **Resolution:** The global puller-lease TTL is pinned to `PULLER_LEASE_TTL = 15` seconds, which is strictly less than the 45-second directory staleness window.
- **Verification:** The PG-guarded failover test verifies that standby takeover occurs within the TTL and that no live slots age out of `routable_slots`/`live_slots` during the transition.

### BC4: Client Wall-Clock Dependency in Driver-Lease Skip
- **Resolution:** The per-node lease freshness check is moved server-side into the `FETCH` query (`now() >= lease_until`), removing the puller host's machine clock from the timing decision.
- **Verification:** The driver-lease test verifies that the skip decision is driven entirely by the database clock and carries no client timestamp parameters.

### BC5: Puller-Lease Column Name Mismatch
- **Resolution:** The DDL and CAS query are aligned to use `holder` verbatim.
- **Verification:** The puller-lease tests verify execution against the real `009` migration DDL without column errors.

---

## 2. No Remaining Falsifying Gaps

Following a thorough review of the revised build plan (holder-claude-opus-4.8-003):
1. **Slice Independence & Order:** The progression from DB changes (Slice 0) to writers (Slices 1–3) and finally consumers (Slice 4) is correct and ensures that live nodes are never stranded.
2. **Timing Invariants:** All timing, liveness, and lease freshness checks are successfully delegated to the database clock, preserving the zero-touch clock-skew defense.
3. **Rust/Python Boundaries:** The implementation details remain bounded to the helper modules and registry queries without polluting the client node codebase.

No further gaps or vulnerabilities are identified. The plan is sound and ready to proceed to the build and verify phases.
