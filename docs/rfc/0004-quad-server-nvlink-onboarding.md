# RFC 0004 — Quad-server NVLink tensor-parallel onboarding

- **Status:** Stub / Blocked (hardware not yet present) — design sketch only
- **Backlog:** gpu-fleet README "Next" — *"NVLink-pair domains launched as one
  tensor-parallel endpoint"*
- **Depends on:** RFC-0001 (leases), RFC-0002 (self-registration), RFC-0003
  (epoch)
- **Prepared via:** authored directly as a placeholder — full `/adhd` design
  deferred until the hardware exists and its real constraints are known

## Why this is a stub

The quad-3090 server ("two NVLink pairs = two ~48 GiB tensor-parallel domains")
is **"coming"** but not on the bench. Designing the allocation/eviction details
now would be speculation against unknown topology (NVLink bandwidth, whether both
pairs share a host, how the inference server exposes a TP endpoint). This RFC
records the **shape** and the **seams** so the work is ready to pick up the moment
the box arrives — and flags it as **blocked**, not forgotten.

## Problem shape

A node with two NVLink pairs presents **two ~48 GiB tensor-parallel domains**, not
four independent 24 GiB GPUs. Big-context / big-model work should route to a TP
domain (one logical endpoint spanning the pair), while the registry must not
treat the pair as two separable slots.

## Seams already in place

The spine was built to absorb this with **no schema change**:

- **`nvlink_domain` tag** (`gpu_slots` / `fleet_nodes`): equal value ⇒ one TP
  domain; NULL ⇒ singleton. A pair advertises a shared `nvlink_domain` and acts as
  one larger slot. Already documented in migration 001.
- **Capability addressing**: consumers request by `vram_free_mib` / `max_context`,
  so a 48 GiB TP domain is selected for big-context work by the same `pick` query
  — no special-casing.
- **`capacity`** (RFC-0001): a TP domain is one slot, leased as a unit. The pair
  is never double-booked because the lease is on the domain, not the cards.
- **Self-registration** (RFC-0002): the quad-server self-registers its two TP
  domains by answering probes; **measured capability** (not declared) reports the
  real per-domain VRAM/throughput — so a misconfigured TP launch (only one card
  in the domain) graduates as what it actually serves, not what it claims.
- **`epoch`** (RFC-0003): a domain re-forming (a card drops, the pair splits)
  bumps epoch and fences holders off the stale topology.

## Open design questions (resolve when hardware lands — `/adhd` candidate then)

- How is a TP endpoint launched and health-probed as *one* OpenAI endpoint
  spanning two cards? (llama-server `--tensor-split` / a TP-aware server.)
- Do both pairs share one host process or two? How does `nvidia-smi` per-card VRAM
  roll up into one domain's `vram_free_mib`?
- Lease granularity: whole domain only, or sub-domain slots for small jobs?
- Routing policy: should big-context work be *restricted* to TP domains (a
  capability filter), and should di's fan-out prefer spreading across domains?
- Failure of one card in a pair: demote the whole domain, or fall back to a
  single-card slot?

## Falsifiable gate (deferred)

- A registered NVLink pair appears as **one** live slot with ~48 GiB
  `vram_free_mib`, not two 24 GiB slots.
- A lease on the domain blocks both cards from independent claim.
- Big-context work routes to the TP domain; small work can still use singletons.

**Do not start build** until the hardware is present and these questions are
answered with a follow-up `/adhd` design pass.
