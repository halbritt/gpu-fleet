# Adding a Windows node to the fleet

A Windows node is **pull-only by design** ([RFC 0002](rfc/0002-zero-touch-node-lifecycle.md)):
it runs **zero fleet code and holds zero DB credentials**. The heartbeat driver
(`heartbeat_all.py`, the `gpu-fleet-heartbeat` user service) probes it over HTTP
plus SSH `nvidia-smi`, and registration is a single `fleet_nodes` INSERT captured
as an append-only migration. No code change, no driver restart — the driver
re-reads `fleet_nodes` every tick.

The existing precedent is **peecee** (migrations 002–006, 011); this doc
generalizes that path.

## 1. Decide the probe mode

The only real design decision. It picks `probe_model`:

| Situation | `probe_model` | Liveness semantics |
|---|---|---|
| Dedicated LLM card, model always resident | NULL (defaults to `served_model`) | Real 1-token decode-probe every tick |
| Shared card, ollama loads on demand (the peecee pattern) | `'ollama-ondemand'` + set `min_load_vram_mib` | WARM / COLD-LOADABLE / NOT-LOADABLE — never force-loads |
| Non-LLM capability (e.g. marker) | `'-'` (also `none` / `gpu-only`) | GPU reachability via `nvidia-smi` only; endpoint may be `ssh://host` |

If the card is shared with **anything** — including the Windows desktop session
driving a display — use `ollama-ondemand`. A plain decode-probe would force-load
the model every tick, which is exactly the bug migration 005 fixed on peecee.

## 2. Windows-side prep (the node runs no fleet code)

The goal is a box that is fully remotely manageable from the puller host, since
after this step you should never need to sit at it again. Two pieces: the
serving stack, and PowerShell 7 + OpenSSH Server for management + the
`gpu_cmd` probe path.

### 2a. Remote management: PowerShell 7 + OpenSSH Server

Full standalone runbook (one elevated console session, key-auth ACL trap,
pwsh-default-shell gotchas, verification, troubleshooting):
**[windows-remote-management.md](windows-remote-management.md)**.

The acceptance test, from the puller host:

```bash
ssh -o BatchMode=yes <node> nvidia-smi   # no prompt, well under the 10s probe timeout
```

That command is exactly what the heartbeat driver runs as `gpu_cmd` every
tick; until it passes, the node can never go live.

### 2b. Serving stack

- Install the GPU driver and the serving stack (e.g. ollama). For ollama:
  - `OLLAMA_HOST=0.0.0.0` so it listens on the LAN (default is loopback-only).
  - `OLLAMA_KEEP_ALIVE=-1` is peecee's pinned host setting (model stays resident
    once loaded).

## 3. Puller-side prep (proximal today; any Linux node holding the puller-lease)

- The node's hostname must resolve from the puller (LAN DNS / hosts entry /
  tailnet name).
- Verify the exact command the driver will run, non-interactively:

  ```bash
  ssh -o BatchMode=yes <node> nvidia-smi   # must return with NO prompt
  ```

  This runs every 15 s tick with a 10 s timeout (`GPU_TIMEOUT`), so it must be
  fast. Any interactive prompt = the probe fails and the node never goes live.

## 4. Measure before you declare

Repo discipline (see migration 011's adjudication card): `served_model` and
`max_context` are declared **only at measured values**. Declaring unmeasured
headroom is fabricated evidence — the quarantine gate will also independently
refuse to route anything the probe can't verify.

- Run the candidate model at the target context; confirm `ollama ps` shows
  **100% GPU** residency at that context. If it spills to CPU, pick the smaller
  model or a smaller (measured) context.
- With the card idle, note free VRAM — that measurement derives
  `min_load_vram_mib`, the free-VRAM floor at which the served model counts as
  loadable. It is a **liveness-window threshold, not the model footprint**
  (finding 176): it must sit ≥ the model's load demand and ≤ the idle-free
  band, and above every co-tenant-resident state, so the slot is admitted when
  the card is free and refused when a co-tenant owns it.

## 5. Register — one append-only migration

Create `migrations/NNN_<node>_join.sql` (next free number) with the rationale
and measurements in the header (the 003/011 precedent), containing essentially:

```sql
INSERT INTO fleet_nodes
    (node, endpoint_url, served_model, probe_model, latency_class,
     gpu_cmd, max_context, min_load_vram_mib)
VALUES
    ('newnode', 'http://newnode:11434/v1', '<measured-model-tag>', 'ollama-ondemand',
     'batch', 'ssh -o BatchMode=yes newnode nvidia-smi', 32768, <measured-floor>)
ON CONFLICT (node, slot_id) DO NOTHING;
```

Apply and commit:

```bash
psql -d gpu_fleet -f migrations/NNN_<node>_join.sql
```

That is the whole registration: the driver's FETCH reads `fleet_nodes` every
tick, so the node is probed within ~15 s with **no restart** of
`gpu-fleet-heartbeat`.

> **Why an INSERT and not zero-touch self-registration?** RFC 0002's
> "registration = first heartbeat" path is for *self-pushing* nodes. A pull-only
> Windows node enters via `fleet_nodes` because that is the set the puller
> iterates — and Windows nodes are deliberately kept pull-only (no fleet
> code/creds on the least reliable host in the fleet).

## 6. Watch it graduate

The new `gpu_slots` row enters `status='unverified'` and ratchets
`unverified → probationary → routable` after **3 consecutive passing probes**
(`GRADUATION_STREAK`, `heartbeat.py`) — roughly 45 s at the 15 s tick. It is
invisible to consumers until then; only `routable_slots` is pickable/leasable.

```bash
journalctl --user -u gpu-fleet-heartbeat -f          # watch the probe land
psql -d gpu_fleet -c "SELECT node, status, probe_streak, alive, note
                        FROM gpu_slots WHERE node='newnode';"
psql -d gpu_fleet -c "TABLE routable_slots;"
```

A failed probe zeroes the streak and re-quarantines — "booted but GPU not
ready" and a lying node both sit harmlessly unverified.

## 7. Smoke test end-to-end

```bash
python3 pick_slot.py --latency-class batch -k 4 --json    # new slot should appear

bin/gpu-fleet-run --model <tag> --job join-smoke -- \
    curl -s @@GPU_FLEET_ENDPOINT_URL@@/models
```

## Anti-patterns (explicit RFC 0002 rejections)

- **Do not** install `heartbeat.py` or Postgres credentials on the Windows
  node. Push mode is an opt-in optimization for trusted Linux nodes only.
- **Do not** hand-INSERT into `gpu_slots` — that table is measured state owned
  by the heartbeat; `fleet_nodes` is the declared state you edit.
- **Do not** set `probe_model` to the model tag on a shared card — that
  disables load-aware liveness and reverts to force-loading decode-probes.

## Decommission

```sql
UPDATE fleet_nodes SET enabled = false WHERE node = 'newnode';
```

The slot goes stale (out of `live_slots` in ≤ 45 s) and the driver's PRUNE then
deletes the directory row — the node fully disappears with no further action.
