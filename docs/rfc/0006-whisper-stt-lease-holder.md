# RFC 0006 — whisper-STT as a standing exclusive lease-holder

- **Status:** Shipped (`whisper_lease.py` + `systemd/whisper-stt.service.d/` + `systemd/whisper-stt-lease-renew.service`)
- **Backlog:** Plane GPUFLE-1 ("Onboard whisper-stt as an exclusive lease-holder")
- **Depends on:** RFC 0001 (leases, shipped), RFC 0002 (graduation gate, shipped)
- **Prepared via:** one-way promotion of the `/adhd` PULL below; the showerthoughts
  source note is RAW INPUT and is never edited (per the showerthoughts rule) —
  **this file is the design of record.**

## Source (promoted verbatim)

From `showerthoughts/divergent-ideation-gpu-fleet-prefix-routing-2026-06-25.md`
(PULL #2, status ACTIVE at promotion time, 2026-07-20):

> **PULL (build it NOW, standalone) — [stack/gpu-fleet] whisper-STT as a fleet
> lease-holder.** Independent of the whole routing question: whisper-stt acquires an
> exclusive lease on the same 3090 capacity row the llama slot derives from, so when STT
> is live the llama slot's **derived** capacity drops below routable and `pick` SKIPs it.
> The real whisper-vs-llama OOM collision becomes a **scheduling skip, not a crash/page**.
> - *flip-if:* the 3090 stops being shared (whisper moves off-box) → moot.
> - *next:* gpu-fleet — wire lease acquire/release into `whisper-stt.service` start/stop
>   (or a tiny VRAM-watcher), assert via RFC 0005 derived capacity that the llama slot
>   drops below routable when STT is hot. Owner: gpu-fleet.

## What shipped

`whisper_lease.py` (+ `bin/whisper-stt-lease`) — acquire / renew-loop / release
over the shipped RFC 0001 primitives (`di_fleet.claim/renew/release`; no new
lease SQL). Wired into the SYSTEM unit `whisper-stt.service` via a drop-in
(`ExecStartPre` acquire / `ExecStopPost` release) plus a companion renew unit
bound to whisper-stt's lifetime (a 45s-TTL lease held for hours needs a renewer,
and a `Type=simple` unit has no second long-running Exec).

Design points, and where they bend the note:

- **The service's OWN slot row is claimed directly — no `pick`.** whisper is not
  choosing fleet capacity; it is annotating its own GPU. Node/endpoint/slot are
  pinned (`proximal` / `http://localhost:8081/v1` / 0).
- **"Derived capacity drops below routable" is RFC 0001's lease-free predicate**,
  not a new RFC 0005 signal: while the lease is live, `pick` and CLAIM both
  refuse the row (`lease_id IS NULL OR now() >= lease_expires`), so every fleet
  consumer skips the shared 3090. RFC 0005's `effective_free_mib` additionally
  reflects whisper's resident MiB whenever the exporter feeds it, but the skip
  itself needs no exporter.
- **Refusal is asymmetric by design (exit codes are the contract):**
  - slot actively leased by another consumer, or headroom short → **exit 75**
    (the scheduling skip); `Restart=on-failure` retries until the fleet lease
    drains (`StartLimitIntervalSec=0` so a minutes-long shard can't exhaust the
    retry budget). This is the OOM class converted to a skip — in BOTH
    directions (fleet work skips hot STT; STT start defers under fleet work).
  - registry dark, or slot not registry-offerable (unregistered / dead / stale /
    unroutable) → **start WITHOUT a lease, loudly** (degrade open). Fleet
    consumers can only be scheduled THROUGH the registry, so a slot the registry
    cannot offer cannot collide via the fleet — and praxis's live voice intake
    must not be hostage to Postgres.
- **The renew loop restores coverage; it never kills whisper.** On lease loss it
  re-claims (including a fenced takeover of a dead predecessor's ghost lease
  under our own holder id); on standing refusal it waits and retries each tick.
  Residual (accepted): between a lapse and re-claim a fleet consumer can claim
  the slot while STT is live — the pre-onboarding status quo, bounded by one
  renew tick instead of standing.

## Falsifiable gate (verified at ship time)

With `whisper-stt.service` active: `gpu_slots` shows
`lease_holder = 'whisper-stt/proximal'` with a future `lease_expires`,
`pick_slot.py` returns **no** proximal row, and the lease survives longer than
one TTL (renew loop live). With whisper-stt stopped: the lease is NULL and
`pick_slot.py` returns the proximal row again. Hermetic tests:
`tests/test_whisper_lease.py`.

## Flip-if

The 3090 stops being shared (whisper moves off-box) → remove the drop-in and the
companion unit; the module keeps working for any other standing co-tenant.
