# BUILD_PLAN — RFC 0005: Exporter-fed capacity signal (probe-anchored)

author: holder-claude-opus-4.8-003

Translates the settled design in `docs/rfc/0005-exporter-capacity-signal.md` into an
ordered, falsifiable build plan a separate build run executes. The RFC is settled
(`/adhd`-prepared, scored, traps recorded); this plan does **not** re-open its design
or resurrect a rejected alternative — it realizes it against the live code as it
stands after RFC 0001/0002/0003 landed: migration `009` applied; the lease lifecycle
inlined in `di_fleet.py`; the heartbeat UPSERT already preserves-and-conditionally-bumps
`epoch` (`heartbeat.py:77-81`); `pick_slot.py` selects `FROM gpu_slots` and gates on raw
`vram_free_mib` (`pick_slot.py:29,36`) under `FOR UPDATE SKIP LOCKED` (`pick_slot.py:41`);
and `di_fleet`'s claim gates on `vram_free_mib >= %(model_mib)s` (`di_fleet.py:109`) where
`model_mib` is a defaulted kwarg production never populates.

## Revision note — cycle 3

This revision stands on two layers of prior falsification and discharges **both**:

1. **The adjudicator's cycle-2 collaboration ledger** (`dialogue/adjudicator/COLLABORATION_LEDGER_cycle_2.md`,
   `needs_revision`) recorded one **blocking** constraint (**BC1**) plus four accompanying
   repairs (**BC2–BC5**). All five are discharged below, each folded into the relevant
   slice **and** the falsifiable-gate→test map, **preserving intact everything the ledger
   recorded as surviving falsification** (the spine in the table's last block).
2. **The latest (attempt-2) falsifier challenges against the revised plan**
   (`dialogue/falsifier_1/FALSIFIER.md`, codex-002; `dialogue/falsifier_2/FALSIFIER.md`,
   gemini-002) landed **three new, code-grounded defects** the cycle-2 plan had not yet
   closed. They are folded in here as **F-CARD**, **F-KEYS**, **F-LOCK** (and a baseline
   robustness reinforcement, **F-BASE**), because the next falsifier round will resurrect
   them if unaddressed. None re-opens the RFC's settled design.

| Constraint | Severity / kind | Where discharged |
|---|---|---|
| **BC1** — reader-side headroom has no production path; `kv_bytes` undefined; `di --json` boundary unreconciled (UNREBUTTED blocker) | high / gate | **Slice 0** (`model_capacity` policy table + `capacity_policy.default_request_context_tokens`) + **Slice 3** (request-capacity contract: `max_context` sourced at the di-fleet argv layer; per-slot footprint/KV from `model_capacity` joined on `served_model`; `kv_bytes` realized as a **defined inline SQL expression**; threaded through `route_slots`→`pick`, first-claim, **and** failover-claim) + **§3 gate row 8** (e2e `di_fleet` 32k-vs-4k test). C7 restated for production threading. |
| **BC2** — freshness decay compared node-clock `fast_source_ts` vs DB-clock `heartbeat_ts` (cross-clock) | high / gate | **Slice 0** (`capacity_slots` view + the inline PICK/claim freshness test compute staleness from **same-clock summands**: a node-clock age + a DB-clock `now()-updated_ts`) + **§3 gate row 1** (skew-resistance test **and** frozen-source decay test). OQ-C restated naming each clock. |
| **BC3** — `live_slowdown_factor = probe_ms / cold_probe_ms` crashes on `None`/`0` (incl. every ollama-ondemand tick) | medium / policy | **Slice 1** (`None`/`0` guard moved **into the `CAPACITY_UPSERT` SQL** as `CASE`/`NULLIF`, never a Python division; ollama-ondemand no-baseline rule) + **§3 gate row 6** (failed-probe + cold-ollama-ondemand tests). |
| **BC4** — the puller (`heartbeat_all.py`) never writes the companion, so pull-mode slots (incl. peecee) are blind | medium / policy | **Slice 2** (companion telemetry computed in `probe_node`, written by `pull_write` under the same savepoint guard) + **§3 gate row 4** (puller integration test). |
| **BC5** — slices claimed "independently committable … either deploy order" but Slice 2 has a hard 010 precondition | low / policy | **§1** (committable-vs-deployable disambiguation) + **§2** (DB→writer→reader is the operative invariant). |
| **F-CARD** *(new — codex-002)* — `capacity_policy` has no singleton/cardinality contract, so a re-apply or a second tuning row can **multiply** every slot row through the policy join and break `pick`'s one-row-per-slot contract even when the companion is empty | high / gate | **Slice 0** (`capacity_policy` is a true **singleton**: `id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1)`, seeded `ON CONFLICT (id) DO NOTHING`; `model_capacity` keyed by `model PRIMARY KEY`; the view and PICK reference policy via a **guaranteed-singleton** scalar/`CROSS JOIN`) + **§3 gate row 9** (re-apply idempotence + one-row-per-slot + `pick(k=2)` PK-uniqueness test). |
| **F-KEYS** *(new — gemini-002 #1)* — adding `mig_mode`/`ecc_mode` to the **shared** `UPSERT` `KeyError`s every writer, because `heartbeat_once`, `probe_node`, **and** `_failed_row` each build their own row dict | high / gate | **Slice 2** (extend `GPU_QUERY` + `gpu_stats` to emit `mig_mode`/`ecc_mode`; **all three** row-builders carry the keys — push/pull from `stats`, `_failed_row` as `None`) + **§3 gate row 2** (row-dict-key + puller-no-KeyError tests). |
| **F-LOCK** *(new — gemini-002 #2)* — `FOR UPDATE` cannot lock rows through a join **view** (`capacity_slots`) | high / gate | **Slice 3** (PICK keeps `FROM gpu_slots` as the **base** relation with **inline** LEFT JOINs to companion/policy and `FOR UPDATE OF gpu_slots SKIP LOCKED`; the `capacity_slots` view is read-only/diagnostic, never locked) + **§3 gate row 5b** (lock-clause inspection + real-`pick` claim test). |
| **F-BASE** *(reinforcement — gemini-002 #4)* — a baseline captured while the card is hot, or a `0` baseline, would mis-scale or crash `live_slowdown_factor` | medium / policy | **Slice 1** (the cold baseline is **sticky in the DB** via `COALESCE(gpu_slots_capacity.cold_probe_ms, EXCLUDED.cold_probe_ms)` — read from the persisted companion row, so a heartbeat-process restart **never** recaptures a hot baseline; `0`/`None` guarded by `NULLIF`/`CASE`) + **§3 gate row 6**. |

**Preserved without change (the sound spine — the ledger's "What survived"):** **C-EPOCH**
(fast capacity bands never bump `epoch`, gate only NEW picks/claims; only slow capability
bands `mig_mode`/`ecc_mode` bump `epoch` and fence held leases — resolving the self-abort
loop); **C3** companion-table fault isolation (LEFT JOIN + a separate savepoint-guarded
write); **C4** `effective_free = LEAST(probe_floor, exporter_free)` probe-anchoring; **OQ-P**
phantom shrinks `effective_free` rather than minting a self-lease; **C5** fleet-floor
dead-man guard; **C1/C2** additive/reversible Migration `010` at the lowest-unused number;
**OQ-B** ollama-ondemand residency-only floor never force-loads; and the live-infra safety
boundary. The **DB→writer→reader** slice discipline is retained and tightened.

## The one fact that drives the whole build

Capacity must get **richer without coupling the router to the exporter and without
storming `epoch`.** The mechanism the RFC mandates is a **`gpu_slots_capacity`
companion table** that the heartbeat (the writer that already touches the row) populates
and that `pick` **LEFT JOINs** — so a malformed/crashed exporter degrades the fleet to
liveness-only routing instead of poisoning the `gpu_slots` liveness UPSERT. Every
routing-relevant number is **probe-anchored** (the decode-probe that already runs is the
meter; the exporter only enriches), carries **provenance + a freshness half-life**, and
is **hysteresis-banded** so stale/noisy telemetry self-erases and never bumps `epoch`.

Turning this on is therefore an **additive companion-table migration**, then **two
writer slices** (cheapest-first: `live_slowdown_factor`, then the probe-floor +
per-PID + exporter enrichment behind per-backend adapters), then **one reader slice**
that swaps the flat VRAM predicate for a probe-anchored, **request-aware headroom**
predicate while still emitting the legacy keys (the RFC-0001 BC2 discipline). Until the
reader switches — and until the `model_capacity` policy rows are seeded — **fleet
behavior equals today's.**

### The load-bearing interpretation decision (falsifiers: attack this first) — C-EPOCH

The RFC's gate says *"Raw VRAM/util churn within a band produces an identical UPSERT and
does not bump epoch; only a band-crossing does"* and the design says *"extends the
RFC-0003 `IS DISTINCT FROM` exclusion … Only a genuine band-crossing — or a
topology/MIG/ECC change — is routing-relevant."* Realizing this against the live
`epoch`-as-lease-fence (RFC 0003: a bumped `epoch` makes a held lease's **renew** return
zero rows → the job aborts + re-picks, `di_fleet.py:138-147`) forces a decision the RFC
leaves implicit, because a naïve reading **self-aborts running jobs**: a job that claims a
slot and loads its model physically lowers free VRAM, so its **own** allocation would
cross the headroom band down, bump `epoch`, and fence its **own** renew — a guaranteed
abort loop. This plan resolves it as (UNCHALLENGED across both cycles — keep intact):

- **Fast capacity bands** (probe-floor headroom, util, `live_slowdown_factor`/contention,
  phantom) live **only** in the companion table and **never bump `gpu_slots.epoch`.**
  They gate **NEW** picks/claims (the `headroom >= 0` predicate + `ORDER BY`); a held
  lease is **never** fenced by a fast-band move — mirroring the RFC-0002 invariant
  already in the code: *"a slot already leased while routable stays renewable through a
  transient demote within its TTL; demotion gates only NEW claims"* (`di_fleet.py:113-116`).
  Within-band churn writes an **identical** companion row (a no-op); a band-crossing
  rewrites the companion row (so `pick` sees the new band) **without** touching `epoch`.
- **Slow capability bands** (`mig_mode`, `ecc_mode`) genuinely invalidate a holder's
  routing assumption (the card's compute partitioning changed), so they **do** bump
  `epoch` and fence held leases — extending RFC-0003's existing
  `{served_model, nvlink_domain, max_context}` diff set (`heartbeat.py:77-81`), exactly the
  same `IS DISTINCT FROM` pattern, on the **same** `gpu_slots` row. These come from the
  node's **own local `nvidia-smi`** (measured, trusted — already shelled at
  `heartbeat.py:149-170`), **not** from the Prometheus exporter, so coupling them to
  `epoch` does not couple `epoch` to the untrusted exporter and does not violate the
  fault-isolation rationale.

This is the safer reading of "routing-relevant" and is **within** the settled design (it
honors both "never bump epoch on churn" and "a capability change is routing-relevant");
it is recorded as **Open-question answer OQ-E** and **claim C-EPOCH** below. The
gate-bullet-2 test proves both halves.

---

## 1. Scope & slices (ordered)

Commit/deploy order mirrors the RFC's **DB → writer → reader**. **BC5 disambiguation:**
each slice is **independently *committable*** — green on its own under `python3 -m pytest
tests/ -q`, which (for the PG-guarded tests) applies **all** relevant migrations
(`001…010`) to its throwaway fixtures before running code, so a slice's tests never meet
an out-of-order schema. The slices are **NOT freely deploy-ordered**: Slice 2 has a
**HARD deploy-order precondition on Migration 010** (it adds `mig_mode`/`ecc_mode` to the
**non-savepoint-guarded** liveness UPSERT and the epoch `CASE`, so deploying Slice 2
against an un-migrated schema fails the liveness UPSERT and ages slots out). The operative
deploy invariant is **DB (010) before writers, writers before reader** (§2). Within the
writers, **A-before-or-after-B is free** (Slice 1's and Slice 2's companion fields are
disjoint and neither is read until Slice 3) — that, and **only** that, is what "either
order" means here. No runtime column-existence probing is added (YAGNI for a DB-first,
in-order operator deploy).

### Slice 0 — DB: migration `010` (additive companion table + policy-as-data)
- **Files:** `migrations/010_exporter_capacity_signal.sql` (new). Edits no prior,
  already-applied migration.
- **Change:**
  - `CREATE TABLE IF NOT EXISTS gpu_slots_capacity` — companion keyed by the same PK
    `(node, endpoint_url, slot_id)` as `gpu_slots`, **all columns nullable/defaulted**:
    `cold_probe_ms INT` (the idle/registration baseline), `live_slowdown_factor NUMERIC`,
    `probe_floor_mib INT` (probe-measured allocatable floor), `exporter_free_mib INT`,
    `effective_free_mib INT` (stored `LEAST(probe_floor_mib, exporter_free_mib)` — the
    lower, probe-anchored number, **C4**), `util_band SMALLINT`, `power_w INT`,
    `temp_c INT`, `phantom_mib INT DEFAULT 0`, `phantom_pids INT DEFAULT 0`,
    `capacity_source TEXT DEFAULT 'absent' CHECK (capacity_source IN
    ('measured','stale','exporter_down','absent'))`, **`fast_source_age_s NUMERIC`**
    (BC2 — the node-computed age of the fast-field source measurement at write time),
    **`slow_source_age_s NUMERIC`** (likewise for the slow capability fields),
    `updated_ts TIMESTAMPTZ NOT NULL DEFAULT now()` (the DB write clock).
  - `ALTER TABLE gpu_slots ADD COLUMN IF NOT EXISTS mig_mode TEXT, ADD COLUMN IF NOT
    EXISTS ecc_mode TEXT;` — the **slow capability** columns the epoch diff extends to
    (written from local `nvidia-smi`, not the exporter). Nullable → epoch behaves as
    today until the writer slice names them.
  - **`CREATE TABLE IF NOT EXISTS capacity_policy` as a TRUE SINGLETON (F-CARD).**
    `id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1)`, plus band edges, `m`/`n` confirmations,
    `fast_half_life_s`, `slow_half_life_s`, the decay multiplier `k`, and
    `default_request_context_tokens` (BC1 — the request `max_context` fallback when a
    consumer passes no flag), **as data, not code** (tuning is a row edit, never a
    redeploy). Seeded with the single `id = 1` row `ON CONFLICT (id) DO NOTHING`. The
    `CHECK (id = 1)` + PK makes a second row **impossible**, so a re-applied migration (or
    a fat-fingered tuning insert) can never create a second policy row — the
    `ON CONFLICT (id) DO NOTHING` now has a real unique constraint to conflict on
    (codex-002's exact objection). Tuning is an `UPDATE` of the `id = 1` row.
  - **`CREATE TABLE IF NOT EXISTS model_capacity` (BC1)** — the **request-capacity
    policy**: `model TEXT PRIMARY KEY`, `footprint_mib INT NOT NULL DEFAULT 0`,
    `kv_mib_per_1k_tokens NUMERIC NOT NULL DEFAULT 0`. The registry-side source of model
    footprint and per-token KV cost, **as data**, seeded for the fleet's models by the
    operator (who measures footprints offline; the **build never measures real GPUs**).
    `model PRIMARY KEY` means a LEFT JOIN on a slot's `served_model` returns **at most one
    row per slot** (F-CARD: no fan-out). A model with **no row** LEFT-JOINs to NULL →
    `COALESCE(...,0)` → footprint 0, KV 0 → the headroom predicate reduces to today's (the
    BC anchor). Seeded `ON CONFLICT (model) DO NOTHING`.
  - `CREATE VIEW capacity_slots` — `gpu_slots` LEFT JOIN `gpu_slots_capacity` (PK) LEFT
    JOIN `model_capacity` (on `served_model`), `CROSS JOIN (SELECT … FROM capacity_policy
    WHERE id = 1)` — the **singleton** policy, so the view is provably **one row per
    `(node, endpoint_url, slot_id)`** (F-CARD). It exposes the **freshness-decayed**
    `capacity_source` and a decayed `effective_free_mib`. **BC2 — single-clock decay:** the
    view computes `fast_staleness_s = COALESCE(fast_source_age_s, 0) + GREATEST(0,
    EXTRACT(EPOCH FROM (now() - updated_ts)))` and decays the fast fields to
    `capacity_source = 'stale'` (and `effective_free_mib → NULL`) when
    `fast_staleness_s > k * fast_half_life_s` (slow fields likewise with
    `slow_source_age_s` / `slow_half_life_s`). Both summands are **same-clock
    differences** — `fast_source_age_s` is a node-clock difference sampled entirely on the
    writing node; `now() - updated_ts` is a DB-clock difference — so an absolute node↔DB
    NTP skew is **never** load-bearing (it cancels in each difference), yet a frozen source
    (its measurement time stops advancing → `fast_source_age_s` grows each tick, or the row
    stops being written → `now() - updated_ts` grows) still decays. This view is **for
    diagnostics/read-only consumers**; the locking `pick`/claim paths replicate the same
    join + decay **inline over the base tables** (Slice 3, F-LOCK), never `FOR UPDATE`
    through the view. `live_slots`/`routable_slots` are **not** dropped (expand/contract; a
    later contract migration retires them, as `007` did for `free_slots`).
- **Blast radius:** three new tables (`gpu_slots_capacity`, `capacity_policy`,
  `model_capacity`), one new view, two new nullable columns on `gpu_slots`. Renames/drops
  nothing. `IF NOT EXISTS` everywhere → idempotent re-apply (mirrors `009`), and with the
  `capacity_policy` PK the seed is idempotent on re-apply (F-CARD).
- **Backward compatible:** the running heartbeat UPSERT names **none** of the new
  columns/tables, so it is unaffected the instant the DDL commits. No consumer reads the
  companion/policy until Slice 3, so until then **behavior == today**. No backfill is
  required (an absent companion row == `capacity_source='absent'` == "fall back to today's
  `vram_free_mib`"; an absent `model_capacity` row == footprint/KV 0 == today's
  predicate). Safe with `gpu-fleet-heartbeat` running; stop→migrate→start is optional and
  equally safe.
- **Reversibility (before Slice 3 deploys):** `DROP VIEW IF EXISTS capacity_slots; DROP
  TABLE IF EXISTS model_capacity; DROP TABLE IF EXISTS capacity_policy; DROP TABLE IF
  EXISTS gpu_slots_capacity; ALTER TABLE gpu_slots DROP COLUMN IF EXISTS ecc_mode, DROP
  COLUMN IF EXISTS mig_mode;` — committed as a comment block, mirroring `008`/`009`.

### Slice 1 — Writer A: `live_slowdown_factor` + cold baseline (cheapest, zero new side effect)
- **Files:** `heartbeat.py` (a **new** `CAPACITY_UPSERT` constant + baseline capture in
  `heartbeat_once`), `tests/test_capacity_signal.py` (new, hermetic), `tests/test_capacity_pg.py`
  (new, guarded).
- **Change:** each tick writes the companion row via a **separate** `CAPACITY_UPSERT`
  statement, after the liveness UPSERT, under a savepoint (below). This ships **first**
  because it uses data already in hand (`probe_ms` exists; the baseline is captured once)
  with **zero new side effects** — no scratch allocation, no exporter read, no per-PID read
  (RFC §Principle 1, §Open-question "probe-floor aggressiveness").
- **F-BASE — the cold baseline is sticky IN THE DB, not in process state.** The
  `CAPACITY_UPSERT` persists `cold_probe_ms` via
  `cold_probe_ms = COALESCE(gpu_slots_capacity.cold_probe_ms, EXCLUDED.cold_probe_ms)` —
  i.e. **once a baseline row exists it is read back from the persisted companion row and
  kept**, so the FIRST passing probe (captured at registration, when the slot is freshly
  declared and idle) is the sticky baseline and a **heartbeat-process restart never
  recaptures a hot baseline** (the DB already holds the cold one; the COALESCE keeps it).
  This is exactly gemini-002 #4's "must query the existing baseline from the DB, don't
  recapture while hot" — discharged **in SQL**, with no extra Python `SELECT` round-trip.
- **BC3 — `live_slowdown_factor` is computed *in SQL*, never by a Python division.** The
  `CAPACITY_UPSERT` sets
  `live_slowdown_factor = CASE WHEN EXCLUDED.probe_ms IS NULL
       OR COALESCE(gpu_slots_capacity.cold_probe_ms, EXCLUDED.cold_probe_ms) IS NULL
       THEN NULL
       ELSE EXCLUDED.probe_ms::numeric / NULLIF(COALESCE(gpu_slots_capacity.cold_probe_ms,
       EXCLUDED.cold_probe_ms), 0) END`.
  So a **`None`/missing `probe_ms`** (a failed/timed-out `decode_probe` → `(False, None,
  err)`, `heartbeat.py:185-186`; and — by this plan's own residency-only design — an
  **ollama-ondemand** slot, which returns `(True, None, note)` on every tick because it
  skips the decode probe to avoid forcing a load, `heartbeat.py:269-271`) yields
  `live_slowdown_factor = NULL`, **never a `TypeError`**; a zero/`None` baseline yields
  `NULL` via `NULLIF(...,0)`, **never a `ZeroDivisionError`** (F-BASE's `0` case). The
  Python side passes `probe_ms` (possibly `None`) as a bound parameter and performs no
  arithmetic. **ollama-ondemand no-baseline rule (defined explicitly):** an ollama-ondemand
  slot never establishes a `cold_probe_ms` (it never decode-probes), so
  `live_slowdown_factor` stays `NULL` and `capacity_source` reflects the residency-only
  measurement (`measured` when residency/exporter data is present, never `absent` solely
  because slowdown is `NULL`); the slot still receives a **well-formed** companion row.
- **Fault isolation (load-bearing, C3):** the companion write runs **after** the liveness
  UPSERT in the **same** transaction, wrapped in a **savepoint** — `SAVEPOINT cap; <CAPACITY_UPSERT>;
  RELEASE SAVEPOINT cap` with `ROLLBACK TO SAVEPOINT cap` on any error (psycopg
  `conn.transaction()` nested block, or explicit `SAVEPOINT`). A savepoint, **not** the
  full `conn.rollback()` that `NODE_LEASE_CAS` uses (`heartbeat.py:356-361`): the CAS runs
  *before* the liveness UPSERT, so a full rollback there loses nothing; the capacity write
  runs *after* the liveness UPSERT, so it must roll back **only itself** and leave the
  liveness UPSERT intact. It mirrors the *swallow-and-continue intent* of `NODE_LEASE_CAS`
  with the mechanism the after-position requires. A malformed/failed companion write
  **must never** sink or roll back liveness; capacity is best-effort enrichment.
- **Blast radius:** one new SQL constant + the savepoint wrapper in `heartbeat_once`
  (`heartbeat.py:374-375`, between the liveness UPSERT and the commit); `gpu_slots` UPSERT
  untouched. **Backward compatible:** nothing reads the companion until Slice 3.

### Slice 2 — Writer B: probe-floor + exporter enrichment + per-PID phantom + MIG/ECC + puller wiring
- **Files:** `heartbeat.py` (probe-floor adapter, exporter read, per-PID attribution,
  `effective_free_mib = LEAST(floor, exporter)`, MIG/ECC into the **`gpu_slots`** UPSERT +
  the epoch `CASE`, **plus the `GPU_QUERY`/`gpu_stats` extension for F-KEYS**),
  `heartbeat_all.py` (**BC4** — the puller computes companion telemetry in `probe_node`
  and writes it in `pull_write`; it already `from heartbeat import UPSERT`
  (`heartbeat_all.py:24-30`), so the epoch-`CASE` edit covers both writers in one place),
  `tests/test_capacity_signal.py`, `tests/test_capacity_pg.py`.
- **Change A — probe-floor behind a per-backend adapter (observer-effect guard, OQ-B).** A
  decode/scratch-allocation floor is **gated per-backend**: the peecee `ollama-ondemand`
  slot uses a **residency-only** floor (it reuses `ollama_resident`,
  `heartbeat.py:191-209` — a pure read that never forces a load), **never** the aggressive
  scratch-allocation floor. Honors the RFC-0002/load-aware invariant verbatim; proven by
  gate test K.
- **Change B — exporter enrichment.** A node reads its **own local** exporter
  (`localhost`) during its heartbeat (no cross-host scrape). peecee (pull-only) has its
  exporter read by the **puller-lease holder over the existing pull channel** (attributed
  `proxied_by`), never a new SSH fanout, never fleet code/creds on the node.
  `effective_free_mib = LEAST(probe_floor_mib, exporter_free_mib)` — trust the **lower**
  (**C4**).
- **Change C — per-PID phantom (OQ-P).** The heartbeat reads per-PID VRAM-used, sums the
  PIDs the fleet **recognizes** (its own lease-bound inference servers), and treats all
  **unrecognized-PID VRAM as a phantom occupant** (`phantom_mib`/`phantom_pids`) that
  **shrinks `effective_free_mib`** so a card hosting an unknown VRAM hog drops out of
  `pick`. **Only the node that physically owns the card writes its phantom.** (Minting a
  synthetic `lease_holder='phantom:<card>'` self-lease — the RFC's alternative mechanism —
  is **deferred**: it would require the heartbeat to write the `gpu_slots` lease columns it
  never touches today and race real claims; shrinking `effective_free` achieves the same
  "pick routes around it" with far smaller blast radius. OQ-P.)
- **Change D — MIG/ECC slow-band into `epoch`, with EVERY writer's row dict carrying the
  keys (F-KEYS — the gemini-002 #1 KeyError).** Adding `%(mig_mode)s`/`%(ecc_mode)s` to the
  **shared** `UPSERT` (`heartbeat.py:46-111`) means **every** dict passed to
  `conn.execute(UPSERT, row)` must contain those keys, or psycopg raises `KeyError` and
  crashes the writer loop. There are **three** row-builders, and **all three** are updated:
  1. extend `GPU_QUERY` (`heartbeat.py:31`) with `mig.mode.current,ecc.mode.current` and
     parse them in `gpu_stats` (`heartbeat.py:149-170`) into `stats["mig_mode"]` /
     `stats["ecc_mode"]` (tolerating an older `nvidia-smi` that omits them → `None`, exactly
     as `gpu_uuid` is already tolerated at `heartbeat.py:161-163`);
  2. `heartbeat_once`'s row dict (`heartbeat.py:362-373`) adds
     `"mig_mode": stats.get("mig_mode"), "ecc_mode": stats.get("ecc_mode")`;
  3. `heartbeat_all.probe_node`'s row dict (`heartbeat_all.py:117-130`) adds the same from
     its `stats`; and `heartbeat_all._failed_row` (`heartbeat_all.py:133-147`) adds
     `"mig_mode": None, "ecc_mode": None` (a crashed probe knows no capability → NULL,
     which `IS DISTINCT FROM` a prior NULL is false → no spurious epoch bump).

  Then **extend the epoch `CASE`** (`heartbeat.py:77-81`) with `OR gpu_slots.mig_mode IS
  DISTINCT FROM EXCLUDED.mig_mode OR gpu_slots.ecc_mode IS DISTINCT FROM EXCLUDED.ecc_mode`.
  Fast capacity fields are **not** in this diff (**C-EPOCH**). These slow fields stamp
  `slow_source_age_s` in the companion.
- **Change E — BC4: wire the companion write into the PULLER.** `heartbeat_all.probe_node`
  (the DB-free I/O phase) is extended to compute the same capacity telemetry it can reach
  for a pulled node (proxied exporter read over the existing pull channel; the
  residency-only floor; `live_slowdown_factor` inputs) into the row dict.
  `heartbeat_all.pull_write` (`heartbeat_all.py:207-221`) then executes the **same
  `CAPACITY_UPSERT`** (imported alongside `UPSERT`) under the **same savepoint guard**, in
  the existing single-writer transaction, **after** the liveness UPSERT
  (`heartbeat_all.py:219`) and **before** the `commit()` (`heartbeat_all.py:220`) — so a
  companion failure `ROLLBACK TO`s to the savepoint without aborting the liveness write the
  puller already performed (and without tripping the `tick` exception path at
  `heartbeat_all.py:241-243`). This closes the gap where every pull-mode slot —
  **including peecee, the host whose `marker` co-tenant motivates Principle 3** — silently
  `COALESCE`-fell back to legacy `vram_free`. **"Only the card-owning node writes its
  phantom"** is honored: a proxied/pulled node's per-PID phantom is attributed via the
  existing proxy/deferral (peecee's per-PID arrives over the pull channel, attributed
  `proxied_by`); the puller does not invent a phantom for a node it cannot per-PID-measure.
  Proven by gate test M.
- **Blast radius:** `heartbeat.py` `GPU_QUERY`/`gpu_stats` + capacity adapters + the one
  shared `UPSERT` constant (covers `heartbeat_all` transitively) + the puller proxy + the
  puller companion wiring; all three row-builders. **Backward compatible:** MIG/ECC
  additions bump epoch only on a real capability change (NULL until a node reports them,
  and a NULL-vs-NULL `IS DISTINCT FROM` is false); the companion enrichment is read by
  nobody until Slice 3. **Deploy precondition (BC5):** Slice 2 requires Migration 010
  already applied (mig/ecc ride the unguarded liveness UPSERT).

### Slice 3 — Reader: request-aware probe-anchored headroom (BC1 — the gate-clearing slice)
- **Files:** `pick_slot.py`, `di_fleet.py` (`route_slots`, `LEASE_CLAIM_SQL`, `claim`,
  `failover_transfer`, `run_leased_shard`, `run_failover_shard`, `_split_argv`, `main`),
  `tests/test_pick_slot.py`, `tests/test_di_fleet.py`, `tests/test_capacity_pg.py`.

**The request-capacity contract (discharges BC1 in production, not just in SQL).** The
RFC's reader invariant is `headroom_mib = effective_free − (model_footprint +
kv_bytes(max_context))` — *"a 32k-context request and a 4k-context request correctly see
different slots as routable."* Where each input comes from, **without crossing the
`di --json` boundary or probing live hardware**:

- **`model_footprint` and per-token KV cost are PER-SLOT, registry-sourced.** They are NOT
  a single request scalar (di-fleet fans across heterogeneous slots, each serving its own
  model). The SQL **LEFT JOINs `model_capacity` on the slot's `served_model`** and reads
  `footprint_mib` + `kv_mib_per_1k_tokens` from that policy row (seeded as data by the
  operator). No engine import, no GPU probe — the values are **data the operator measured
  offline**, exactly like `min_load_vram_mib` already is for `ollama-ondemand`
  (`heartbeat.py:212-220`).
- **`max_context` is the ONLY request-side input, a scalar, sourced at the di-fleet
  layer.** `_split_argv` (`di_fleet.py:847`) is extended to **consume a di-fleet-owned
  `--max-context N`** (like the existing di-fleet-only `-k`/`--slots`, `di_fleet.py:864-865`)
  and to **peek** `--model VALUE` (leaving it in `passthrough` so the child still receives
  it). When `--max-context` is absent, di-fleet falls back to
  `capacity_policy.default_request_context_tokens` (a single registry read of the singleton
  row; itself defaulting such that an un-seeded fleet yields `0` KV). **This is argv +
  registry SQL only** — the boundary is preserved verbatim.
- **`kv_bytes(max_context)` is DEFINED, not a dangling symbol.** It is realized as an
  **inline SQL expression over the joined `model_capacity` row and the `%(max_context)s`
  bound parameter**: `CEIL(COALESCE(mc.kv_mib_per_1k_tokens,0) * %(max_context)s::numeric /
  1000.0)::int`. **Owning slice: Slice 3** (it is created and tested here; the
  `model_capacity` table it reads is created in Slice 0). It is **not** a Python helper and
  **not** an undefined `kv_bytes()` function — the SQL references only columns/params that
  exist (gemini-002 #5 / codex's "second strike"). (A named SQL function
  `kv_budget_mib(numeric,int)` is an optional later readability refactor; the build ships
  the inline expression so Migration 010 needs no function object.)

- **Change A — `pick` (`pick_slot.py`), locking the BASE table, never a view (F-LOCK).**
  `PICK` keeps **`FROM gpu_slots`** as its base relation (`pick_slot.py:29`) and adds
  **inline** `LEFT JOIN gpu_slots_capacity c USING (node, endpoint_url, slot_id)`,
  `LEFT JOIN model_capacity mc ON mc.model = gpu_slots.served_model`, and
  `CROSS JOIN (SELECT … FROM capacity_policy WHERE id = 1) cp` (the F-CARD singleton). The
  lock clause becomes **`FOR UPDATE OF gpu_slots SKIP LOCKED`** — naming the base table so
  Postgres locks exactly the `gpu_slots` row and does **not** attempt to lock the read-only
  companion/policy/model joins (which would otherwise error `cannot lock rows in view` /
  fail on a non-lockable join, gemini-002 #2). The query is **never** run against the
  `capacity_slots` view with `FOR UPDATE`; the view is read-only/diagnostic. Because
  `model_capacity` is PK-keyed on `model` and `capacity_policy` is the singleton, the join
  is provably **one row per `(node, endpoint_url, slot_id)`** — `pick(k=2)` on a one-slot
  fleet returns that slot **once**, never duplicated (F-CARD). The VRAM predicate becomes
  the **request-aware, freshness-decayed headroom** form (decay computed inline with the
  BC2 same-clock summands so a stale companion `COALESCE`-falls-through to
  `gpu_slots.vram_free_mib`):
  `COALESCE(<fresh effective_free or NULL>, gpu_slots.vram_free_mib)
   >= COALESCE(%(min_vram)s::int,0) + COALESCE(mc.footprint_mib,0)
    + CEIL(COALESCE(mc.kv_mib_per_1k_tokens,0) * COALESCE(%(max_context)s,0)::numeric / 1000.0)::int`.
  With `max_context=NULL` and no `model_capacity` row this is **byte-equivalent** to
  today's `vram_free_mib >= COALESCE(min_vram,0)`. The `ORDER BY` trusts
  `capacity_source='measured'` first (weighting `stale` at a decaying discount, not a hard
  cliff), and a **fleet-floor / dead-man guard** (C5) ensures `pick` **never returns
  empty** when every fast field is stale — it falls back to last-known-good band with a
  `degraded` flag. New output keys (`effective_free_mib`, `capacity_source`, `degraded`)
  are **additive**; legacy `vram_free_mib`/`free_slots`/`capacity` keys stay
  (`pick_slot.py:71-74`) so un-upgraded readers never KeyError. `pick()` gains a
  `max_context` kwarg (defaulted `None`, BC).
- **Change B — `di_fleet` claim + failover threaded with the SAME `max_context`.**
  `LEASE_CLAIM_SQL`'s `AND vram_free_mib >= %(model_mib)s` (`di_fleet.py:109`) becomes the
  **same request-aware headroom predicate**, using **correlated scalar subqueries** on the
  companion and `model_capacity` (an `UPDATE … WHERE` can't add a `FROM`, so the subqueries
  correlate on the row's PK / `served_model`):
  `COALESCE((SELECT effective_free_mib FROM gpu_slots_capacity c WHERE (c.node,c.endpoint_url,c.slot_id)
   = (gpu_slots.node,gpu_slots.endpoint_url,gpu_slots.slot_id) AND <fresh>), gpu_slots.vram_free_mib)
   >= COALESCE(%(model_mib)s,0)
    + COALESCE((SELECT footprint_mib FROM model_capacity WHERE model = gpu_slots.served_model),0)
    + CEIL(COALESCE((SELECT kv_mib_per_1k_tokens FROM model_capacity WHERE model = gpu_slots.served_model),0)
      * COALESCE(%(max_context)s,0)::numeric / 1000.0)::int`.
  `model_mib` is **kept** as an additive floor term (defaulted `0`) so the existing
  `claim(model_mib=…)` signature is untouched and byte-equivalent when unset. `claim()` and
  `failover_transfer()` gain a `max_context` kwarg (defaulted `None`, BC) carried into the
  SQL params; `run_leased_shard` and `run_failover_shard` gain and forward it.
- **Change C — production threading (the bit cycle 1 was missing; the BC1 blocker).**
  `route_slots(k, db=…, latency_class=None, pick_fn=None, max_context=None)`
  (`di_fleet.py:238`) forwards `max_context` to `pick(...)` (`di_fleet.py:267`). `main()`
  (`di_fleet.py:898`) computes the request capacity **once**: `_split_argv` parses
  `--max-context` (and peeks `--model`); `main` resolves `max_context` (flag else a single
  `capacity_policy` singleton read) and then threads it through **all three** claim paths:
  (i) `slots = route_slots(k, db=db, max_context=max_context)` (`di_fleet.py:905`);
  (ii) the `leased_shard` closure (`di_fleet.py:929-931`) calls
       `run_leased_shard(..., max_context=max_context)`;
  (iii) the `leased_failover` closure (`di_fleet.py:933-938`) calls
        `run_failover_shard(..., max_context=max_context)`.
  So **route_slots/pick, the first-attempt claim, AND the failover claim all receive the
  same non-default `max_context`** — a defaulted kwarg production never populates is **not**
  what ships (codex-002 / gemini-002 #5 "always default to 0/None" objection). (Per-slot
  footprint/KV are sourced in SQL, so no per-slot value is threaded through Python; the one
  threaded scalar is `max_context`.) `_split_argv`'s return tuple grows from 5 to 6 (the new
  `max_context`); `main`'s unpacking at `di_fleet.py:900` is updated in lockstep.
- **Restated C7 (production threading, not only the COALESCE fall-through):** backward
  compatibility holds on **two** axes — (1) an **un-seeded** registry (`model_capacity`
  empty, `max_context` unset) makes the predicate byte-equivalent to today's; (2) a slot
  with **no/stale companion row** `COALESCE`-falls-through to `vram_free_mib`. Legacy keys
  stay in `pick` output. The feature is **live in production** the moment the operator
  seeds `model_capacity` and a consumer passes (or defaults) `max_context` — proven by the
  e2e gate test, not merely asserted.
- **Blast radius:** two SQL predicates (PICK + LEASE_CLAIM_SQL) + the
  `route_slots`/`main`/`_split_argv`/`claim`/`failover_transfer`/`run_*_shard` threading +
  their tests. **No code crosses the `di --json` boundary** (argv parse + registry SQL
  only; the Node engine is never imported; no GPU is read).

---

## 2. Migration plan

- **Number: `010`** — `migrations/` holds `001`–`009` (`009_zero_touch_lifecycle.sql` is
  the last). `010` is the lowest unused **file** number (verified: no `010*` present;
  cycle-1 **C1/C2** cleared this). The RFC body's *"Migration 010 (or 011 if the
  `free_slots` contract migration lands first)"* resolves to **`010`**: the
  `free_slots`→`capacity` **contract** migration is **not built** (`pick_slot.py:71-74`
  still aliases `free_slots`), so it has not consumed `010`. The build edits no existing
  migration. (The packet objective's "migration 006" phrasing is generic; the live
  `migrations/` directory is authoritative and the lowest unused there is `010`.)
- **Exact schema changes:** as enumerated in Slice 0 — `gpu_slots_capacity`,
  `capacity_policy` (singleton), `model_capacity`, the `capacity_slots` view, and two
  nullable `gpu_slots` columns (`mig_mode`, `ecc_mode`). **All companion/policy fields are
  nullable/defaulted or seeded `ON CONFLICT DO NOTHING` against a real key**, so the schema
  existing changes nothing until the heartbeat populates the companion AND the reader
  switches AND the operator seeds `model_capacity`.
- **Apply order (operator, AFTER integration): DB → writer → reader — the operative
  deploy invariant (BC5).**
  1. **DB:** apply `010` (additive ⇒ safe even with `gpu-fleet-heartbeat` running).
  2. **Writers:** redeploy `heartbeat.py`/`heartbeat_all.py` (Slice 1 then Slice 2). Slice 2
     **requires** step 1 first (mig/ecc ride the unguarded liveness UPSERT, and the row
     dicts now carry the keys — F-KEYS). They begin populating the companion (push **and**
     pull paths, BC4) + writing MIG/ECC; still no routing change.
  3. **Reader:** redeploy `pick_slot.py`/`di_fleet.py` (Slice 3) — the headroom predicate
     goes live, degrading to today's number wherever the companion is empty/stale or
     `model_capacity` is unseeded.
  4. **(optional) Seed `model_capacity`** rows to turn on request-aware footprint/KV. Until
     then the reader is byte-equivalent to today's flat-VRAM routing.
- **Backward-compatibility invariant:** until the reader (Slice 3) is deployed, fleet
  behavior equals today's; and even after, a slot with no/stale companion row or an
  unseeded model routes on the legacy `vram_free_mib` exactly as today.

---

## 3. Test plan — mapped to the RFC's Falsifiable gate

The default `python3 -m pytest tests/ -q` (a hermetic suite — currently **99 test
functions**, of which `test_epoch_pg.py`/`test_leases_pg.py`/`test_lifecycle_pg.py`
**skip** when `GPU_FLEET_TEST_DB` is unset; the prompt's "26" is stale) MUST stay green and
hermetic. Hermetic tests **inject fakes** (a per-PID source, a fake exporter, a fake
probe-floor, a recording `pick_fn`/`lease_ops`) — **no real `nvidia-smi`/HTTP in units** —
mirroring `tests/test_probe_all.py` and `tests/test_load_aware_liveness.py`. Every DB-backed
test goes in **`tests/test_capacity_pg.py`, guarded exactly like `tests/test_epoch_pg.py`**:
`pytest.importorskip("psycopg")`, skip unless `GPU_FLEET_TEST_DB` names an **ephemeral**
cluster, and **refuse** a bare `gpu_fleet` (`test_epoch_pg.py:26-37`). The PG fixture applies
the **real** migrations (`001,002,007,008,009,010`, mirroring `test_epoch_pg.py:49-50`) to
the throwaway cluster — so the suite also proves `010` applies cleanly on the real schema.

| # | RFC gate bullet (+ constraint) | Test(s) | Kind |
|---|---|---|---|
| 1 | A frozen/stale exporter (its source measurement time stops advancing) decays its capacity fields to `stale` and drops them out of `pick`'s `ORDER BY` within `k × half_life`, **with no writer touching the row** — **and (BC2) a node↔DB clock skew does NOT spuriously decay a fresh slot** | **A1 (frozen, hermetic).** `test_capacity_signal.py::test_decay_marks_stale_by_single_clock` — a pure decay helper mirroring `fast_source_age_s + (now−updated_ts)`: a large age (or old `updated_ts`) → `'stale'`. **A2 (skew, hermetic).** `::test_skew_does_not_decay_fresh_slot` — small real `fast_source_age_s` but an `updated_ts`/source clock offset by several × `half_life` (simulated NTP skew) → still `'measured'` (the absolute offset cancels). **A3 (frozen, PG).** `test_capacity_pg.py::test_frozen_source_decays_out_of_pick` — INSERT a companion row, advance nothing; `now()-updated_ts` crosses `k×half_life` → decays to `stale`, falls out of the measured ORDER BY. **A4 (skew, PG).** `::test_db_skew_keeps_fresh_slot_measured` — fresh `fast_source_age_s` with a wildly offset stored timestamp stays `measured`. | A1,A2: **hermetic**; A3,A4: **PG-guarded** |
| 2 | Raw VRAM/util churn **within a band** produces an **identical** UPSERT and does **not** bump `epoch`; only a band-crossing does — **and (F-KEYS) the shared UPSERT never KeyErrors a writer** | **C.** `test_capacity_signal.py::test_capacity_upsert_stores_only_banded_values` — SQL-shape inspection: `CAPACITY_UPSERT` stores banded values; the `gpu_slots` epoch `CASE` references `mig_mode/ecc_mode` (+ the existing trio) but **not** `effective_free_mib`/`util_band` (à la `test_heartbeat_epoch.py`). **C-KEYS (F-KEYS, hermetic).** `::test_all_upsert_row_builders_have_mig_ecc_keys` — assert the dicts returned by `heartbeat.heartbeat_once` (via a fake conn/stats), `heartbeat_all.probe_node`, and `heartbeat_all._failed_row` ALL contain `mig_mode`/`ecc_mode`, so `conn.execute(UPSERT, row)` cannot `KeyError`. **D.** `test_capacity_pg.py::test_within_band_churn_noop_and_no_epoch_bump` — two ticks whose raw VRAM differs but lands in the same band → byte-identical companion row, `epoch` unchanged, a held lease's `renew` still True (no self-abort). **E.** `::test_mig_ecc_crossing_bumps_epoch_and_fences` — a MIG/ECC change bumps `epoch` and fences a held lease's renew. | C,C-KEYS: **hermetic**; D,E: **PG-guarded** |
| 3 | A slot whose exporter free-VRAM **exceeds** the probe-measured floor routes on the **lower** (probe) number | **F.** `test_capacity_signal.py::test_effective_free_is_least_of_floor_and_exporter` — a **fake exporter over-reporting** free VRAM (22000) with a probe floor of 8000 → `effective_free_mib == 8000`. **G.** `test_capacity_pg.py::test_pick_routes_on_probe_floor_not_exporter` — end-to-end: the over-reporting slot is gated by the floor in `pick`/claim. | F: **hermetic**; G: **PG-guarded** |
| 4 | An unrecognized PID holding VRAM shrinks `effective_free` (mints a phantom) so `pick` routes **around** the card, and it **clears** when the PID exits — **and (BC4) the puller populates the companion for pull-mode slots** | **H.** `test_capacity_signal.py::test_unrecognized_pid_becomes_phantom_and_clears` — a **fake per-PID source**: recognized PIDs summed; an unknown PID → `phantom_mib>0` → `effective_free` shrinks below footprint; remove it → restored. **I.** `test_capacity_pg.py::test_phantom_drops_slot_from_pick`. **M.** `::test_puller_writes_companion_row` — run `heartbeat_all.tick`/`pull_write` (fake `probe_node` yielding capacity telemetry) for a pulled node → `gpu_slots_capacity` has a row for that node, written under the savepoint guard. **M2 (hermetic).** `test_capacity_signal.py::test_pull_write_invokes_capacity_upsert` — a `RecordingConn` shows `pull_write` issues `CAPACITY_UPSERT` after the liveness UPSERT and inside the savepoint. | H,M2: **hermetic**; I,M: **PG-guarded** |
| 5 | `pick` **never returns empty** when all fast fields are stale — it degrades to last-known-good with a `degraded` flag | **J.** `test_pick_slot.py::test_pick_degrades_not_empty_when_all_stale` — a `RecordingConn` returns only stale-capacity rows → `pick()` returns them with `degraded=True`, **not** `[]`. | **hermetic** |
| 5b | **(F-LOCK) `pick` locks the BASE table, never a join view, and never duplicates a slot** | **P1 (hermetic).** `test_pick_slot.py::test_pick_locks_base_table_not_view` — assert the `PICK` SQL string selects `FROM gpu_slots` and ends `FOR UPDATE OF gpu_slots SKIP LOCKED` (not a bare `FOR UPDATE`, and not `FROM capacity_slots`). **P2 (PG).** `test_capacity_pg.py::test_pick_k2_one_slot_returns_unique_pk` — seed ONE routable slot + no companion row; `pick(k=2)` returns exactly **one** row whose PK is unique (the policy/model joins cannot multiply it), and a real second-claim of that PK is a fenced no-op. | P1: **hermetic**; P2: **PG-guarded** |
| 6 | The peecee `ollama-ondemand` slot is **never force-loaded** by the floor probe (residency-only floor) — **and (BC3/F-BASE) a `None`/`0`/hot-restart baseline never crashes the tick** | **K.** `test_capacity_signal.py::test_ollama_ondemand_floor_is_residency_only` — for `served_model='ollama-ondemand'` the floor adapter calls the **residency-only** path and a **spy asserts the scratch-allocation floor is never invoked** (mirrors `test_load_aware_liveness.py`). **K2 (BC3 hermetic).** `::test_none_probe_yields_well_formed_row` — a failed probe (`probe_ms=None`) and a cold loadable ollama-ondemand slot (`probe_ms=None`, no baseline) each produce a **well-formed** companion row with `live_slowdown_factor=NULL` and the tick **completing** (no `TypeError`/`ZeroDivisionError`). **K3 (BC3/F-BASE PG).** `test_capacity_pg.py::test_capacity_upsert_null_and_sticky_baseline` — drive the real `CAPACITY_UPSERT` with `probe_ms=NULL` and with `cold_probe_ms=0` → `live_slowdown_factor IS NULL`; then a second tick with a NEW `probe_ms` proves `cold_probe_ms` is **unchanged** (sticky `COALESCE`, no hot recapture); liveness UPSERT unaffected throughout. | K,K2: **hermetic**; K3: **PG-guarded** |
| 7 | The hermetic default suite stays green; per-PID and exporter reads are injected fakes (no real `nvidia-smi`/HTTP in units); DB-backed tests guarded behind `GPU_FLEET_TEST_DB` | The whole table: all new default-suite tests inject fakes and need no DB; every PG test lives in `test_capacity_pg.py` and skips when `GPU_FLEET_TEST_DB` is unset. **L.** `pytest tests/ -q` count does not drop and demands no DB. | **hermetic + guarded** |
| 8 | **BC1 — reader-side headroom is enforced in PRODUCTION:** a 32k request and a 4k request route **differently** against the SAME slot whose `effective_free` sits between the two headroom thresholds; pick + first-claim + failover-claim all receive non-default `max_context`; `kv_bytes` resolves to a defined symbol; no engine import, no live-hardware read | **N1 (e2e, hermetic).** `test_di_fleet.py::test_request_context_threads_through_all_claim_paths` — drive the production orchestration surface (`route_slots` with a recording `pick_fn`; `dispatch` with `run_leased_shard`/`run_failover_shard` bound to a fake `conn_factory` + recording `lease_ops`, the seams `main()` wires). Seed a fake `model_capacity` so one slot's `effective_free` lies **between** the 4k and 32k headroom thresholds. **Assert:** `pick_fn` is called with the request `max_context`; **both** `claim` and `failover_transfer` receive the same non-default `max_context`; the **4k** request claims the slot and the **32k** request does **not**. **N2 (PG).** `test_capacity_pg.py::test_headroom_predicate_refuses_oversized_context` — the real `LEASE_CLAIM_SQL`/`PICK` against an ephemeral DB with a seeded `model_capacity` row: a 32k claim matches **zero** rows and a 4k claim succeeds on the same slot. **N3 (boundary, hermetic).** `::test_no_engine_import_in_reader` — assert `di_fleet`/`pick_slot` import neither the DI engine nor any GPU library and that request capacity comes only from argv + the registry read. | N1,N3: **hermetic**; N2: **PG-guarded** |
| 9 | **(F-CARD) Migration 010 is idempotent on re-apply and `capacity_policy` is a singleton; the companion-empty reader is one-row-per-slot** | **Q (PG).** `test_capacity_pg.py::test_010_reapply_singleton_and_view_cardinality` — apply the chain + `010`, then apply `010` **again**; assert `SELECT count(*) FROM capacity_policy` is exactly `1`; seed one routable `gpu_slots` row and NO `gpu_slots_capacity` row; assert `SELECT count(*) FROM capacity_slots WHERE (node,endpoint_url,slot_id)=(…)` is exactly `1`; and assert `pick(..., k=2)` returns one unique PK (covered jointly with P2). | **PG-guarded** |

**Hermetic-default guarantee.** New default-suite tests (A1,A2,C,C-KEYS,F,H,J,K,K2,M2,N1,N3,P1)
add to the suite and need no DB. Existing lease/epoch/pick tests stay green because: the
companion table is absent in their fakes → `COALESCE(effective_free, vram_free)` falls
through to today's `vram_free_mib`; `model_capacity` absent → footprint/KV `COALESCE` to 0;
`max_context` defaults to `NULL` → 0 KV; the epoch `CASE`'s new `mig_mode/ecc_mode` terms
are `IS DISTINCT FROM` over NULLs → no spurious bump; and the new row-dict keys are present
in every builder so no fake's `conn.execute(UPSERT, row)` KeyErrors. The PG tests
(A3,A4,D,E,G,I,K3,M,N2,P2,Q) skip cleanly with no `GPU_FLEET_TEST_DB`.

---

## 4. Live-infra safety

The build is **inert** with respect to live infra. It only writes
`migrations/010_exporter_capacity_signal.sql`; edits `heartbeat.py`, `heartbeat_all.py`,
`pick_slot.py`, `di_fleet.py`, and `tests/*`; and runs the **hermetic**
`python3 -m pytest tests/ -q`. It MUST NOT, and does not need to:

- connect to / migrate the **live `gpu_fleet`** Postgres — the PG tests refuse a
  non-ephemeral DB and skip by default (`test_epoch_pg.py:33-37`); only an
  operator-provided `GPU_FLEET_TEST_DB` throwaway cluster runs them;
- restart or touch the running **`gpu-fleet-heartbeat`** service;
- touch **peecee**'s shared GPU — **critically**, the **probe-floor scratch allocation is
  never executed against real hardware in the build**: every floor probe, exporter read,
  and per-PID read is an **injected fake** in the unit tests (gate bullets 3/4/6), and the
  ollama-ondemand adapter is **residency-only by construction** (it cannot force a load);
- **measure model footprints on real GPUs** — `model_capacity` rows are **data the operator
  seeds offline** (like `min_load_vram_mib`); the build only references the table, and its
  tests **seed fakes**. **BC1's request-capacity contract reads argv + the registry only;
  it never imports the DI/Node engine and never probes a card** (gate test N3).

The operator, **after** integration, applies `010` (stop heartbeat → migrate → start),
redeploys the writer then reader checkouts, and (optionally) seeds `model_capacity`. `010`
is additive, so even an unstopped heartbeat is safe. Re-applying `010` is safe and
idempotent (gate test Q).

---

## 5. Boundaries to preserve

- **di-fleet consumers shell out to `di --json` and never import the Node engine**
  (`~/git/divergent-ideation`). This build is 100% registry-side SQL + heartbeat/di-fleet
  Python; **no code crosses that boundary.** BC1's request capacity is sourced from
  **argv** (`--model`/`--max-context`, parsed in `_split_argv`) and **registry SQL**
  (`model_capacity`/`capacity_policy` rows) only — never by inspecting the engine or a GPU
  (gate test N3). Re-deploying **`bin/di-fleet`** (a thin `exec python3 di_fleet.py`
  wrapper, not edited) is the operator step of updating the gpu-fleet checkout on consumer
  hosts.
- **The table + the query stay the router.** No exporter on the hot path (consumers read
  **derived columns**, never Prometheus — *policy in the consumer, mechanism in the
  table*); no cross-host fanout (a node reads its **own local** exporter; peecee is read
  over the **existing** pull channel); no central daemon, no new SPOF.
- **Fault isolation (C3):** the exporter signal lives in a **companion table LEFT JOINed**
  by `pick`, written by a **separate, savepoint-guarded** statement (push **and** pull,
  BC4), so a malformed/crashed exporter degrades the fleet to liveness-only routing and
  **cannot poison the `gpu_slots` liveness UPSERT**.
- **The picker locks only the base `gpu_slots` row** (`FOR UPDATE OF gpu_slots SKIP
  LOCKED`), never a join view, and the policy/model joins are provably non-multiplying
  (F-CARD/F-LOCK), so the router's one-row-per-slot, exactly-once claim contract is
  preserved.
- **Only the card-owning node writes its phantom** (no SPOF, no cross-host attribution).

---

## 6. Open questions — the build's answers

- **OQ-A — companion table vs columns on `gpu_slots`.** **Companion table.** Fault
  isolation (a flaky exporter can't poison the liveness UPSERT) is the RFC's own
  recommendation and is load-bearing for the LEFT-JOIN-degrades-gracefully property.
- **OQ-B — probe-floor aggressiveness / observer effect.** **Ship `live_slowdown_factor`
  first (Slice 1, no new side effect); gate the scratch-allocation floor per-backend
  (Slice 2); residency-only for `ollama-ondemand`** (it can never force a load). Proven by
  gate test K.
- **OQ-C — clock-skew sensitivity of `source_ts` decay (BC2, restated naming clocks).**
  **Compute staleness from SAME-clock differences.** The writer (the node) samples both the
  source measurement time and node-local now at write and stores their difference as
  `fast_source_age_s`/`slow_source_age_s` (**node clock** throughout that subtraction); the
  DB stamps `updated_ts = now()` (**DB clock**). Decay fires when `fast_source_age_s +
  (now() − updated_ts) > k × half_life` — a **node-clock difference** plus a **DB-clock
  difference**, never a node-timestamp vs DB-timestamp comparison. So a node↔DB NTP skew
  **cancels** (it is not load-bearing), **and** a genuinely frozen source still decays (its
  age grows, or `now() − updated_ts` grows if the row stops being written). We explicitly
  **reject** the falsifier's literal fix of stamping the source timestamp with DB `now()` —
  that would defeat frozen-exporter detection (RFC gate bullet 1 needs the *source's own*
  measurement time). gemini-002 #3's "comparing two frozen DB columns never decays" is
  answered by the **second summand**: `now() − updated_ts` advances with wall-clock even
  when both stored ages are frozen. Gate tests A1–A4 pin both skew-resistance and
  frozen-source decay.
- **OQ-E — which bands bump `epoch`.** **Only the slow capability bands
  (`mig_mode`/`ecc_mode`, joining RFC-0003's `{served_model, nvlink_domain, max_context}`)
  bump `epoch` and fence held leases; the fast capacity bands never do.** This honors both
  the anti-churn intent and "a capability change is routing-relevant," while avoiding the
  self-abort loop. Recorded as claim **C-EPOCH**.
- **OQ-P — phantom: shrink `effective_free` vs mint a self-lease.** **Shrink
  `effective_free` in the companion** (smallest blast radius; the existing `FOR UPDATE OF
  gpu_slots SKIP LOCKED` pick routes around a `headroom < 0` slot with **zero** lease-column
  writes from the heartbeat). The synthetic `lease_holder='phantom:<card>'` self-lease is
  **deferred**. Gate tests H/I prove the shrink mechanism.
- **OQ-R — request-capacity sourcing (the BC1 decision).** **`max_context` from the
  di-fleet argv layer (`--max-context`, else `capacity_policy.default_request_context_tokens`);
  per-slot `model_footprint`/KV from the `model_capacity` policy table joined on
  `served_model`; `kv_bytes` as the inline SQL expression over that joined row + the
  `%(max_context)s` param.** Chosen because di-fleet already parses argv and `pick`/`claim`
  already accept `model`/`min_vram`/`model_mib`, so the contract is a threading + data
  change that **never** imports the engine or probes hardware. **If a future model's
  footprint/KV cannot be expressed as `(footprint_mib, kv_mib_per_1k_tokens)` data, the
  build ESCALATES rather than crossing the boundary or measuring real GPUs.**
- **OQ-S — policy table cardinality (the F-CARD decision).** **`capacity_policy` is a true
  singleton** (`id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1)`), referenced by the view and
  the picker via a guaranteed-one-row `WHERE id = 1`. Per-model knobs live in the separate
  `model_capacity` table keyed by `model PRIMARY KEY`. Neither can multiply a slot row, so
  the reader's one-row-per-slot contract holds even with the companion empty. Chosen over a
  "policy dimension + active selector + partial unique index" because this fleet has exactly
  one global tuning profile; YAGNI for a multi-profile selector.
- **Betrayal pheromone** and the **"make every LAN VRAM consumer speak the lease protocol"**
  provocation are explicitly **out of scope** (the RFC defers both to a v2/tracked issue).

---

## 7. Load-bearing claims (falsifiers, attack these)

- **C1 — Migration `010` is additive, reversible, behavior-neutral, and idempotent on
  re-apply.** *Support:* three new tables + one view + two nullable `gpu_slots` columns, all
  `IF NOT EXISTS`/nullable/defaulted; the singleton `capacity_policy` PK makes the seed
  idempotent (`ON CONFLICT (id) DO NOTHING`); the liveness UPSERT names none of them;
  `pytest tests/ -q` stays green before any consumer reads them; gate test Q re-applies
  `010` and asserts one policy row. *Refuted by:* it alters/drops an existing column, breaks
  the running UPSERT, a re-apply yields a second policy row, or an absent companion/policy
  row changes routing.
- **C2 — `010` is the correct, unused migration number.** *Support:* `migrations/` holds
  `001`–`009`; `010` is the lowest unused file; the `free_slots` contract migration is
  unbuilt. *Refuted by:* a `010` file exists, or this campaign lands the `free_slots`
  contract migration as `010`.
- **C-EPOCH — Fast capacity bands never bump `epoch`; only slow capability bands
  (`mig_mode`/`ecc_mode`) do; within-band raw churn writes an identical companion row.**
  *Support:* the epoch `CASE` extends only with `mig_mode`/`ecc_mode` (`IS DISTINCT FROM`);
  the companion stores banded values so a same-band tick is a byte-identical no-op; a held
  lease's renew survives a fast-band move (gate tests C/D/E). *Refuted by:* a vram/util band
  move advances `epoch`, a held lease aborts on a fast-band move, or a MIG/ECC change fails
  to fence.
- **C3 — The exporter signal cannot poison liveness.** *Support:* companion is LEFT JOINed
  and written by a separate **savepoint-guarded** statement in **both** the push
  (`heartbeat_once`) and pull (`pull_write`) paths, placed AFTER the liveness UPSERT so a
  `ROLLBACK TO SAVEPOINT` undoes only the capacity write; `pick` degrades to liveness-only
  via `COALESCE`. *Refuted by:* a companion-write failure rolls back the `gpu_slots` UPSERT,
  or a malformed companion value KeyErrors/crashes `pick`.
- **C4 — `pick` routes on the lower of probe-floor and exporter free.** *Support:*
  `effective_free_mib = LEAST(probe_floor_mib, exporter_free_mib)`; gate tests F/G with an
  over-reporting fake exporter. *Refuted by:* an over-reporting exporter lets a slot be
  picked beyond its probe-measured floor.
- **C5 — `pick` never returns empty when all fast fields are stale.** *Support:* the
  fleet-floor guard falls back to last-known-good band with `degraded=True`; gate test J.
  *Refuted by:* an all-stale fleet makes `pick()` return `[]`.
- **C6 — The build never touches live infra and the hermetic suite stays green with no DB.**
  *Support:* only SQL/code/tests written; all hardware reads (incl. model footprints) are
  injected/seeded fakes; the ollama-ondemand floor is residency-only; PG tests are
  `GPU_FLEET_TEST_DB`-guarded and refuse `gpu_fleet`. *Refuted by:* a unit test shells real
  `nvidia-smi`/HTTP, the build connects to live `gpu_fleet` or measures a real GPU, or
  `pytest tests/ -q` drops/demands a DB.
- **C7 (restated for production threading) — The reader swap is backward-compatible AND the
  feature is live in production once seeded.** *Support:* with `model_capacity` unseeded and
  `max_context` unset, the headroom predicate is byte-equivalent to today's
  (`COALESCE`→`vram_free`, footprint/KV→0); legacy `vram_free_mib`/`free_slots` keys stay; AND
  the e2e test (N1/N2) shows that once seeded, a 32k vs 4k request routes differently through
  the real `route_slots`/claim/failover path. *Refuted by:* an un-upgraded reader KeyErrors;
  a slot with no companion/model row routes differently than today; or the "production path"
  remains a no-op after seeding.
- **C8 — One UPSERT edit covers both writers AND every row-builder carries the new keys;
  held leases survive ticks.** *Support:* `heartbeat_all` `from heartbeat import UPSERT`
  (`heartbeat_all.py:24-30`); `mig_mode`/`ecc_mode` are added to `GPU_QUERY`/`gpu_stats` and
  to **all three** row dicts (`heartbeat_once`, `probe_node`, `_failed_row`), so no
  `conn.execute(UPSERT, row)` can `KeyError` (gate test C-KEYS); the `gpu_slots` UPSERT
  `SET` never lists lease columns, so a tick over a held slot preserves the lease. *Refuted
  by:* a writer emits its own UPSERT, a row-builder omits a key and the puller `KeyError`s,
  or a tick clears/rewrites a lease column.
- **C9 (BC1 — the gate-clearing claim) — The RFC's reader-side headroom invariant has a
  PRODUCTION path that preserves the `di --json` boundary.** *Support:* `max_context` is
  parsed at the di-fleet argv layer (`_split_argv` gains `--max-context`, peeks `--model`)
  and threaded by `main()` through `route_slots`→`pick`, the first-attempt
  `run_leased_shard`→`claim`, **and** `run_failover_shard`→`failover_transfer` (the same
  non-default scalar in all three); per-slot `footprint_mib`/`kv_mib_per_1k_tokens` come from
  the `model_capacity` policy table joined on `served_model`; `kv_bytes` is the defined
  inline SQL expression `CEIL(COALESCE(mc.kv_mib_per_1k_tokens,0) * %(max_context)s::numeric /
  1000.0)::int` (no undefined symbol); the engine is never imported and no GPU is read (gate
  tests N1/N2/N3). *Refuted by:* a 32k and 4k request routing identically against a slot whose
  `effective_free` is between the thresholds; `pick`/first-claim/failover-claim receiving a
  default `max_context` in production; the SQL referencing an undefined `kv_bytes`; or di-fleet
  importing the engine / probing a GPU to source footprint or context.
- **C10 (BC2) — Freshness decay is single-clock.** *Support:* staleness is
  `fast_source_age_s (node-clock difference) + (now() − updated_ts) (DB-clock difference)`;
  no node-timestamp is ever compared to a DB-timestamp; gate tests A2/A4 show a several ×
  half_life skew keeps a fresh slot `measured`, and A1/A3 show a frozen source still decays
  (the `now()-updated_ts` summand advances even when both stored ages are frozen). *Refuted
  by:* a node↔DB skew above `k × half_life` decaying a fresh slot, or a frozen
  `source_age`/un-written row failing to decay.
- **C11 (BC3/F-BASE) — A `None`/`0`/hot-restart baseline never crashes a tick.** *Support:*
  `live_slowdown_factor` is computed in the `CAPACITY_UPSERT` SQL via `CASE`/`NULLIF`, never
  a Python division; a failed probe or a cold ollama-ondemand slot (every tick
  `probe_ms=None`, no baseline) yields `NULL` and a well-formed companion row, inside the
  savepoint guard; the cold baseline is sticky via
  `COALESCE(gpu_slots_capacity.cold_probe_ms, EXCLUDED.cold_probe_ms)` so a process restart
  never recaptures a hot baseline; gate tests K2/K3. *Refuted by:* a `None`/`0` `probe_ms`
  raising and aborting the tick, an ollama-ondemand slot getting no companion row / being
  force-loaded, or a restart overwriting the cold baseline with a hot probe.
- **C12 (BC4) — Pull-mode slots receive companion telemetry.** *Support:* `probe_node`
  computes the companion fields and `pull_write` issues the savepoint-guarded
  `CAPACITY_UPSERT` after the liveness UPSERT; gate tests M/M2 show a pulled node (incl.
  peecee) gets a `gpu_slots_capacity` row. *Refuted by:* running the puller leaves a pulled
  node with no companion row, or a companion failure aborts the puller's liveness write.
- **C13 (F-CARD) — The policy/model joins cannot multiply a slot row.** *Support:*
  `capacity_policy` is a singleton (`id PK CHECK (id=1)`), `model_capacity` is keyed by
  `model PRIMARY KEY`, and `capacity_slots`/PICK reference policy via `WHERE id = 1`; gate
  tests Q + P2 prove a re-applied `010` keeps exactly one policy row and `pick(k=2)` on a
  one-slot fleet returns a single unique PK. *Refuted by:* a re-apply or a tuning insert
  yielding a second policy row, the view returning >1 row per slot with the companion
  absent, or `pick(k=2)` returning the same slot twice.
- **C14 (F-LOCK) — `pick` locks the base table, never a join view.** *Support:* `PICK`
  selects `FROM gpu_slots` with inline LEFT JOINs and `FOR UPDATE OF gpu_slots SKIP LOCKED`;
  the `capacity_slots` view is read-only and never locked; gate test P1 inspects the SQL and
  P2 proves a real claim works. *Refuted by:* `pick` running `FOR UPDATE` against
  `capacity_slots` (errors `cannot lock rows in view`) or omitting the `OF gpu_slots`
  target and failing on the non-lockable joins.
