# gpu-fleet RFCs

Design documents for the remaining v2 work, prepared via `/adhd` (parallel
divergent ideation under isolated cognitive frames, scored, with traps rejected)
and intended to be driven through **striatum design → build → verify** workflows,
one RFC per chain. Each RFC carries a **falsifiable gate** for the verify stage.

| RFC | Title | Status | Backlog |
|-----|-------|--------|---------|
| [0001](0001-exclusive-slot-leases.md) | Exclusive slot leases | **Shipped** (migration 007) | v2 #4 |
| [0002](0002-zero-touch-node-lifecycle.md) | Zero-touch node lifecycle | **Shipped** (migration 009) | self-heartbeat (SPOF) + self-register |
| [0003](0003-stale-router-epoch-fencing.md) | Stale-router epoch fencing | **Shipped** (migration 008) | `epoch` reject hook |
| [0004](0004-quad-server-nvlink-onboarding.md) | Quad-server NVLink onboarding | Stub — **blocked (hardware)** | NVLink TP domains |
| [0005](0005-exporter-capacity-signal.md) | Exporter-fed capacity signal (probe-anchored) | Draft — ready | richer capacity signal |
| [0006](0006-whisper-stt-lease-holder.md) | whisper-STT as a standing exclusive lease-holder | **Shipped** (`whisper_lease.py`) | Plane GPUFLE-1 |

## Dependency / build order

```
0001 (leases) ──► 0003 (epoch fence rides on the lease renew)   [both SHIPPED]
   │
   └──► 0002 (lifecycle: claim gains `AND status='routable'`)    [SHIPPED]
            │
0001+0002+0003 ──► 0004 (quad-server; blocked until the hardware exists)

0005 (exporter capacity signal) ── independent; composes with the shipped spine,
                                    needs no new hardware
```

- **0001 / 0003 / 0002 are shipped and live** (migrations 007 / 008 / 009 applied;
  `gpu-fleet-heartbeat` restarted onto each new writer). 0001 established the lease
  primitive; 0003 added the renew-fence epoch hook; 0002 added quarantine→graduate +
  the peer-runnable puller-lease.
- **0004** is a stub: do **not** start build until the quad-server hardware is
  present and a follow-up `/adhd` pass answers its open questions.
- **0005** is the next buildable RFC — it enriches the capacity signal feeding `pick`
  (probe-anchored, with provenance/hysteresis hygiene and per-PID co-tenant detection),
  composes with the shipped spine, and needs no new hardware. Deferred follow-ups from
  0001/0002 are tracked as GitHub issues.

## Already shipped (context)

The v1 spine these build on is live: K-fan-out (`di_fleet.py`), load-aware liveness
(`ollama-ondemand`), concurrent fast-fail probing, and the capability/`SKIP LOCKED`
pick. The v2 RFCs **0001 (leases), 0003 (epoch fencing), and 0002 (zero-touch
lifecycle)** are now also shipped and live (migrations 007/008/009). See the top-level
`README.md` "done" section.
