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

## Tables

- `gpu_slots` — the directory (one row per node × endpoint × slot).
- `live_slots` — view: `alive` AND heartbeat fresher than 45 s.

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

## v1 scope (this spine) vs later

**Done:** directory table, decode-probe heartbeat, capability `pick` with
`SKIP LOCKED`, 45 s TTL membership, interactive/batch classes.

**Next:** real slot leases (decrement/restore `free_slots` per claim, deadman
expiry) so K-fan-out is exclusive, not advisory · `di` wired to `pick` instead of
a static `DIVERGENT_LLM_BASE_URL` · each node self-heartbeats via a systemd timer
(Linux) / scheduled task or service (Windows) · NVLink-pair domains launched as
one tensor-parallel endpoint · richer capacity signal from the nvidia exporter
(VRAM/util/topology) feeding the same rows · `epoch`-stamped backend-side reject
for stale routers.
