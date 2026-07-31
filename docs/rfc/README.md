# gpu-fleet RFCs

This table is the authoritative implementation-status manifest for the RFCs.
The documents record the full design; the status and unshipped slices below say
which parts exist in the current repository and deployment.

| RFC | Title | Implemented | Not implemented |
|-----|-------|-------------|-----------------|
| [0001](0001-exclusive-slot-leases.md) | Exclusive slot leases | Migration 007; claim, renew, release, failover fencing | `capacity>1` lease table |
| [0002](0002-zero-touch-node-lifecycle.md) | Zero-touch node lifecycle | Migration 009; registration, graduation, puller and node leases, boot-epoch ratchet | Per-node RLS roles; second deployed puller |
| [0003](0003-stale-router-epoch-fencing.md) | Stale-router epoch fencing | Migration 008; writer epoch bump and renew fence | None in the accepted slice |
| [0004](0004-quad-server-nvlink-onboarding.md) | Quad-server NVLink onboarding | Design stub | Blocked on hardware and measurements |
| [0005](0005-exporter-capacity-signal.md) | Exporter-fed capacity signal (probe-anchored) | Migration 010; companion writer, freshness decay, request-aware pick/claim, test seams | Production exporter/per-PID adapters; synthetic phantom leases |
| [0006](0006-whisper-stt-lease-holder.md) | whisper-STT as a standing exclusive lease-holder | `whisper_lease.py`, service units, live deployment | None in the accepted slice |

## Dependency / build order

```
0001 (leases) ──► 0003 (epoch fence rides on the lease renew)   [both SHIPPED]
   │
   └──► 0002 (lifecycle: claim gains `AND status='routable'`)    [SHIPPED]
            │
0001+0002+0003 ──► 0004 (quad-server; blocked until the hardware exists)

0005 (capacity signal core) ── independent; composes with the shipped spine
```

- **0001 / 0003 / the implemented 0002 core are shipped and live** (migrations
  007 / 008 / 009 applied). 0002's RLS roles and second puller deployment are
  intentionally listed as unshipped rather than inferred from the design prose.
- **0004** is a stub: do **not** start build until the quad-server hardware is
  present and a follow-up `/adhd` pass answers its open questions.
- **0005's core is shipped.** Its production exporter and per-PID adapters are
  deferred; the injected seams and hermetic tests are not evidence that those
  collectors are deployed. Deferred work belongs in Plane project `GPUFLE`.

## Already shipped (context)

The v1 spine these build on is live: K-fan-out (`di_fleet.py`), load-aware liveness
(`ollama-ondemand`), concurrent fast-fail probing, and the capability/`SKIP LOCKED`
pick. The v2 RFCs **0001 (leases), 0003 (epoch fencing), and 0002 (zero-touch
lifecycle core)** are also shipped and live (migrations 007/008/009). See the
table above for slices that remain unimplemented.
