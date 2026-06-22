# gpu-fleet RFCs

Design documents for the remaining v2 work, prepared via `/adhd` (parallel
divergent ideation under isolated cognitive frames, scored, with traps rejected)
and intended to be driven through **striatum design → build → verify** workflows,
one RFC per chain. Each RFC carries a **falsifiable gate** for the verify stage.

| RFC | Title | Status | Backlog |
|-----|-------|--------|---------|
| [0001](0001-exclusive-slot-leases.md) | Exclusive slot leases | Draft — ready | v2 #4 |
| [0002](0002-zero-touch-node-lifecycle.md) | Zero-touch node lifecycle | Draft — ready | self-heartbeat (SPOF) + self-register |
| [0003](0003-stale-router-epoch-fencing.md) | Stale-router epoch fencing | Draft — small, rides on 0001 | `epoch` reject hook |
| [0004](0004-quad-server-nvlink-onboarding.md) | Quad-server NVLink onboarding | Stub — **blocked (hardware)** | NVLink TP domains |

## Dependency / build order

```
0001 (leases) ──► 0003 (epoch fence rides on the lease renew)
   │
   └──► 0002 (lifecycle: claim gains `AND status='routable'`)
            │
0001+0002+0003 ──► 0004 (quad-server; blocked until the hardware exists)
```

- **0001 first** — it establishes the lease primitive (derived capacity, Postgres
  clock, fencing) that 0002 and 0003 extend.
- **0002** composes with 0001 (verified-before-leasable) and is independently
  valuable (kills the proximal SSH-driver SPOF).
- **0003** is a thin extension of 0001's renew fence — ships right after 0001.
- **0004** is a stub: do **not** start build until the quad-server hardware is
  present and a follow-up `/adhd` pass answers its open questions.

## Already shipped (context)

The v2 spine that these build on is live: K-fan-out (`di_fleet.py`), load-aware
liveness (`ollama-ondemand`), concurrent fast-fail probing, and the
capability/`SKIP LOCKED` pick. See the top-level `README.md` "Done" section.
