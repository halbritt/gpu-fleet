# HANDOFF — peecee → Qwen3-VL swap, compiled through striatum-next

2026-07-08 ~04:50 UTC. Delete this file when the pass closes.

## Mission

Advance `gpu-fleet` toward **`peecee-serves-qwen3-vl@1`** (instance catalog:
`~/git/striatum-instance/striatum-next/catalog/target-states/`). The Principal's
verbatim command is pinned as the L0 on `gpu-fleet/intents/peecee-qwen3-vl-swap`.
**Principal authority for this compilation is delegated to the session agent**
(in-conversation, 2026-07-07): resolve escalations and accept/reject gates
individually on merits — never scripted, never blanket (standing rule 2026-07-06).

## Invocation

```bash
cd ~/git/gpu-fleet && S="$HOME/git/striatum-next/bin/striatum \
  --catalog $HOME/git/striatum-next/catalog --backends $HOME/git/striatum-next/backends"
$S status            # or --json
$S accept <identity> / $S reject <identity> --reason ... / $S resolve <seq> ...
systemctl --user start striatum-wake-019f3d37.service   # trigger a drive (NEVER run `drive` in-session — see traps)
```

Timer `striatum-wake-019f3d37.timer` fires ~15 min; the graph self-advances.
Read artifact bodies: `python3 <scratchpad>/read-artifact.py <identity-substring>`
(pattern: ledger `artifact_admitted` → object at
`~/.local/share/striatum/graphs/019f3d37-*/objects/sha256/xx/yy/<hash>.zst`,
**skip 16-byte `SOB1zstd` header** before `zstd -dc`).

## State at handoff (updated 2026-07-08 ~16:35 UTC)

- RQ-1 captured: satisfied. RQ-3: canceled (issued without `--note`).
- **RQ-109 `peecee-serves-qwen3-vl`: satisfied [Asserted] — HOLLOW.** Floor
  artifact; the real close is still owed (see "Remaining"). Do not cite it as done.
- **Campaign now under RQ-365** (RQ-2 → canceled 277, RQ-278 → canceled 364; each
  cancel+re-request recovered a lane killed by the in-session-dispatch trap below —
  accepted heads carry across requests).
- **Accepted heads:** proposal v196 (gate 211) · design v251 (codex review zero
  findings, gates 264/267) · implementation-plan v285 (codex review zero findings,
  gates 297/345). Plan lowers design C1–C11 into 3 packets: `migration-011`
  (`migrations/011_peecee_qwen3_vl.sql`), `readme-currency` (README peecee
  example), `changeset-gate` (mutation-free audit).
- **In flight:** work-graph v352 failed `work-graph-legality`
  (`changeset-gate` packet has empty `write_scope`; gate refuses `no_write_scope`).
  Packetization-revision run 367 (dispatch `590d7042…`) live on claude-code since
  16:30Z, dispatched from the wake unit (delegated cgroup — safe). Next: legality
  gate re-check, then build packets, then acceptance of the change-set.

## Adjudication card (measured 2026-07-07 on peecee, live host settings)

Fit rule (proposal v196, binding): serve **32B iff 100% GPU-resident at the
32768-token floor** (floor = the slot's current declared context; fixed, not
tunable); else 8B. Selection order is lexicographic; context may not be shrunk
to make 32B fit.

| model | num_ctx | ollama ps | footprint | speed |
|---|---|---|---|---|
| qwen3-vl:8b | 32768 | **100% GPU** | 8.0 GB | 131 tok/s |
| qwen3-vl:32b | 8192 | 100% GPU | 21 GB | 39 tok/s |
| qwen3-vl:32b | 16384 | 100% GPU, 318 MiB free | 22 GB | 40 tok/s |
| qwen3-vl:32b | 32768 | **7%/93% CPU/GPU — FAILS** | 25 GB | 25 tok/s |

⇒ **Contract selects `qwen3-vl:8b` at max_context 32768.** Both models are
pulled on peecee; `qwen3.6:27b` restored resident (keep_alive -1) — live service
untouched. Lanes cannot reach peecee (`network: vendor-endpoint-only`), so these
numbers enter the graph via gate reasons: if the design/build fabricates or
omits measurements, **reject with this table in `--reason`** — the bounded
revision cycle carries it in. Also honor review finding on v196: liveness
threshold needs strict `>` at `A_marker + margin` (don't let `min_load_vram_mib`
re-admit marker co-residency under the 8B's small footprint — see proposal
`#el:liveness-threshold`).

## Remaining after integration (world side, then close)

1. Apply the new migration (011+) to the live db: `psql -d gpu_fleet -f migrations/011_*.sql`.
2. Verify heartbeat re-lists: `routable_slots` shows peecee slot 0 `qwen3-vl:8b`.
3. Decode-probe through `http://peecee:11434/v1`; `ssh peecee "ollama ps"` = 100% GPU.
4. Update `~/git/peecee/README.md` (intended-resident-model paragraph) — commit/push.
5. Close the pass with REAL evidence pinned:
   `$S request gpu-fleet/passes/peecee-qwen3-vl-close --target observed --note "<commit sha, ollama ps, routable_slots row, probe result>"`
   (this — not RQ-109 — is the satisfaction that counts).

## Traps learned (details: memory `striatum-fleet-driving`, `~/git/proximal/systemd-user/`)

- **ROOT CAUSE FOUND (2026-07-08): every in-session Principal verb that unblocks
  work dispatches lanes into the caller's cgroup.** `accept` runs an inline drive;
  from an SSH/Claude session the supervisor lands in the undelegated
  `session-N.scope` and `createLaneCgroup` gets EPERM — lanes die at birth with
  empty transcripts (runs 214/270/357; principal-trigger sessions 217/273/360).
  This subsumes the old "never `striatum drive` in-session" trap. **Wrap every
  in-session verb:** `systemd-run --user --scope -p Delegate=yes --quiet -- $S
  accept … --reason "…"` (verified), or just wake the unit and adjudicate on the
  next pass. Registered upstream: `dispatches-inherit-a-delegated-subtree@1`
  (striatum-next `1e74a43`); the zombie-run half is
  `failed-submissions-close-their-run@1` (`8d08441`). Supervisor binaries in
  `~/.local/bin/striatum-backend-*` must be rebuilt after striatum-next pulls
  (they lagged edda5bf's crash-reason persistence by 9 minutes, hiding this for
  18 hours). `accept` takes `--reason`, not `--note`.
- Product-state requests produce their conjuncts **under the requesting
  request**: only request them at close, with facts in `--note` (RQ-3/RQ-109
  lessons).
- Host fixes in force (recorded in `halbritt/proximal` `systemd-user/`): user-manager
  PATH (stale root claude 1.0.60 shadowed 2.1.202) and `KillMode=process`
  drop-ins on all five `striatum-wake-*` units (oneshot was reaping lanes).
- Upstream findings registered as target states in the product catalog (commit
  `c119a0a`, bracket RQ-9343/9367 on the self graph):
  `lanes-outlive-their-dispatcher@1`, `probes-attest-the-lane@1`. Candidate
  third finding: run 214's drained-but-never-closed failed submission.
- striatum-next escalation **9330** (graduated-acceptance, bounds_exhausted) is
  NOT in this delegation — the Principal's, likely healable post-fixes.
