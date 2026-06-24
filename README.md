# gpu-fleet

A registry spine for a **dynamic, extensible, multi-host GPU fleet** that serves
a local-first AI stack (interactive voice, divergent-ideation, ingest, …).

The core idea, from a divergent-ideation run on the design: **there is no router.**
A Postgres heartbeat table + one `SELECT … FOR UPDATE SKIP LOCKED` query *is* the
discovery plane, the load-balancer, and the work-queue — no central daemon, no
single point of failure.

## Model

- A node **joins** the fleet by heartbeating a `gpu_slots` row; it **leaves** by
  going silent (a stale heartbeat ages it out of the `live_slots` view). Join,
  leave, and crash are the same self-healing event.
- **Liveness is a real decode-probe** (a 1-token completion), not an HTTP
  `/health` 200 — a wedged model loop serves 200s while failing to decode.
- **Addressing is by capability** (`served_model`, `vram_free_mib`,
  `latency_class`, `nvlink_domain`), never by host identity. NVLink pairs share
  an `nvlink_domain` tag and act as one larger tensor-parallel slot.
- **Mechanism here, policy in the consumer.** The table knows only what exists
  and whether it is alive. Each consumer (di, praxis, ingest) carries its own
  policy and claims with its own `pick`.
- **Non-LLM capabilities.** A slot need not be an OpenAI decode endpoint. Set
  `probe_model = '-'` (sentinel; also `none`/`gpu-only`) and the heartbeat treats
  **GPU reachability** (nvidia-smi) as liveness — it skips the decode-probe, which
  for a non-LLM job would needlessly load a model and fight it for VRAM. Example:
  `served_model = 'marker'` on peecee (GPU document→markdown via surya); consumers
  request the `marker` capability, resolve the host from the `ssh://…` endpoint,
  and run the conversion bridge.

## Tables

- `gpu_slots` — the directory (one row per node × endpoint × slot). Carries the
  lease columns (`capacity`, `lease_id`, `lease_holder`, `lease_expires`,
  `lease_epoch`) and the lifecycle columns (`status`, `probe_streak`, `gpu_uuid`,
  `boot_epoch`).
- `live_slots` — view: `alive` AND heartbeat fresher than 45 s.
- `routable_slots` — view: `live_slots` AND `status='routable'` (the set consumers
  actually route to; a slot is verified-before-leasable).
- `fleet_meta` — single-row table holding the global puller-lease (so the
  heartbeat driver is peer-runnable, not pinned to one host).

## Usage

```bash
psql -d gpu_fleet -f migrations/001_gpu_slots.sql      # apply

# a node heartbeats itself (interactive, local nvidia-smi):
python3 heartbeat.py --node proximal --endpoint http://localhost:8081/v1 \
    --served-model qwen3.6-35b-a3b --latency-class interactive --max-context 262144 \
    --interval 15

# proximal-driven heartbeat for a node that can't self-report yet (Windows desktop):
python3 heartbeat.py --node peecee --endpoint http://peecee:11434/v1 \
    --served-model qwen3.6:27b --latency-class batch --max-context 32768 \
    --gpu-cmd "ssh -o BatchMode=yes peecee nvidia-smi"

# a consumer claims slots by capability (di fan-out width K):
python3 pick_slot.py --latency-class batch -k 4 --json
```

## Install (autonomous — no human intervention)

```bash
psql -d gpu_fleet -f migrations/001_gpu_slots.sql
psql -d gpu_fleet -f migrations/002_fleet_nodes.sql       # declares the fleet members

# heartbeat driver as a self-restarting user service (survives reboot via linger):
cp systemd/gpu-fleet-heartbeat.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now gpu-fleet-heartbeat

# di auto-routes onto a live batch slot (no manual endpoint):
cp bin/di-fleet ~/.local/bin/ && chmod +x ~/.local/bin/di-fleet
di-fleet "your problem" --json
```

**Growing the fleet needs no code change** — insert a row:
```sql
INSERT INTO fleet_nodes (node, endpoint_url, served_model, latency_class, gpu_cmd, max_context, nvlink_domain)
VALUES ('quad-a', 'http://quad:8081/v1', 'qwen3.6-35b-a3b', 'batch',
        'ssh -o BatchMode=yes quad nvidia-smi', 262144, 'quad-pair-0');
```
It is live on the next heartbeat tick; a node that goes silent (probe fails) ages
out of `live_slots` automatically. An agent or a node's boot-time join-script does
this insert — the human is out of the loop.

## Scope — done vs later

**v1 spine (done):** directory table, decode-probe heartbeat, capability `pick`
with `SKIP LOCKED`, 45 s TTL membership, interactive/batch classes, **concurrent
fast-fail probing** (nodes probed in parallel and each row committed the moment
its probe lands, so one slow/black-hole node can't stall the tick and age the
healthy nodes out of `live_slots`), **`di` K-fan-out** (`di-fleet` shards di's
`--frames` across every live MoE slot, runs one `di` subprocess per endpoint
concurrently, fails a dead shard over to a surviving slot so no branch is lost,
and merges the per-shard RunResults into one `di --json`-compatible result), and
**load-aware liveness for shared on-demand nodes** (`probe_model='ollama-ondemand'`:
WARM when the model is already resident, COLD/LOADABLE when the card has the
headroom to load it on demand, NOT-LOADABLE — aged out of `live_slots` — when
marker owns the GPU; so di never routes to a peecee that can't actually serve and
the heartbeat never force-loads a model onto a shared card).

**v2 (done — driven through striatum design→build→verify, one RFC per chain):**

- **Exclusive slot leases** ([RFC 0001](docs/rfc/0001-exclusive-slot-leases.md),
  migration 007). K-fan-out claims are exclusive, not advisory: a slot is held by
  exactly one consumer for a self-renewing 45 s TTL evaluated entirely by Postgres;
  **capacity is derived** from live leases (no mutable counter, no reaper); a
  crashed consumer's lease expires autonomously and a zombie is fenced by
  `lease_id`. `di-fleet` claims/renews/releases per shard and **terminates the
  in-flight `di` child on lease loss** before any second consumer can use the GPU.
- **Stale-router epoch fencing** ([RFC 0003](docs/rfc/0003-stale-router-epoch-fencing.md),
  migration 008). A slot bumps `epoch` on a routing-relevant change
  (`served_model`/`endpoint_url`/`max_context`/`nvlink_domain`); a holder's lease
  renew is fenced to the `lease_epoch` it routed against, so a mid-flight config
  change forces a re-pick. Discovery is **sticky** (the last good `served_model` is
  cached) so a transient probe failure can't flap the model and evict a healthy
  job. VRAM/util churn never bumps epoch.
- **Zero-touch node lifecycle** ([RFC 0002](docs/rfc/0002-zero-touch-node-lifecycle.md),
  migration 009). **Registration = the first heartbeat** (no manual INSERT). A new
  slot enters `status='unverified'` and graduates `unverified→probationary→routable`
  only after N DB-stamped passing probes — **capability is measured, not declared**
  (`gpu_uuid` identity, demote-on-flap, route only the measured throughput). A
  **peer-runnable puller-lease** (`fleet_meta`, deadman TTL) lets any Linux node
  drive the fleet, removing the proximal SSH-driver SPOF; a per-boot monotonic
  `boot_epoch` ratchet refuses replayed/split-brain writes. Routing reads
  `routable_slots`.

**Next:**

- **Quad-server NVLink onboarding** ([RFC 0004](docs/rfc/0004-quad-server-nvlink-onboarding.md))
  — NVLink-pair domains launched as one tensor-parallel endpoint. **Blocked on
  hardware**; owed a follow-up `/adhd` pass when the quad-server arrives.
- **Multi-node puller deploy** — run the (already-shipped) peer-runnable driver on
  ≥ 2 Linux nodes, with push opt-in for the trusted quad-server, to operationally
  retire the proximal SSH SPOF. Waits on a second Linux node.
- **Richer capacity signal from the nvidia exporter** — feed VRAM/util/topology
  from the Prometheus GPU exporters into the same rows
  ([RFC 0005](docs/rfc/0005-exporter-capacity-signal.md)).
- **Deferred follow-ups** — tracked as GitHub issues (soft-reservation herd flag;
  `capacity>1` `slot_leases` table; HTTP-only peecee liveness; EWMA trust score;
  deeper periodic canary probe; contract migration to drop `free_slots`).

The v2 RFCs were prepared via `/adhd` (each carries a falsifiable gate) and live in
[`docs/rfc/`](docs/rfc/).
