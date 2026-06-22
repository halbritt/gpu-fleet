# RFC 0003 — Stale-router epoch fencing

- **Status:** Draft (design) — small; rides on RFC-0001's lease mechanism
- **Backlog:** gpu-fleet README "Next" — *"`epoch`-stamped backend-side reject for stale routers"*
- **Depends on:** RFC-0001 (leases) for the renew-fence hook
- **Prepared via:** authored directly — this is a near-canonical extension of the
  lease fence, not an open design space (it does not meet the `/adhd` gate)

## Summary

A consumer that picked a slot can keep routing work against a **stale view** of
it: the node swapped `llama-server`→`ollama`, changed `served_model`, restarted
with different VRAM, or re-formed an NVLink domain — and the consumer never
noticed. The `gpu_slots.epoch BIGINT` column already exists as the documented
*"node bumps on topology/model change; stale-router reject hook"* but is unused.
This RFC turns it on: a slot bumps `epoch` whenever a routing-relevant capability
changes, and a consumer's claim is **fenced to the epoch it routed against**, so a
mid-flight config change invalidates the claim and forces a re-pick instead of
silently sending work to a slot that no longer serves what was promised.

## Why this is distinct from the lease fence (RFC-0001)

RFC-0001's `lease_id` fences against a *different consumer* re-claiming the slot
(identity/exclusivity). `epoch` fences against the *same slot's capability
changing underneath the holder* (configuration staleness). They are orthogonal:
one protects "who holds it," the other protects "is it still the thing I think it
is." RFC-0001 explicitly reserved `epoch` for this purpose and did **not**
overload it for lease identity.

## Design

### When `epoch` bumps

The heartbeat (or the node, under RFC-0002 self-report) increments
`gpu_slots.epoch` whenever a **routing-relevant** field changes versus the last
tick: `served_model`, `endpoint_url`, `max_context`, `nvlink_domain`, or a
backend swap (the `discover_served_model` result changes). VRAM/util fluctuation
does **not** bump epoch (it's expected churn, already handled by liveness). The
bump is a single `epoch = epoch + 1` inside the existing UPSERT, guarded by a
diff of the routing-relevant columns.

### How a consumer is fenced

- `pick_slot` returns each slot's current `epoch` alongside the endpoint (it
  already returns the row; just surface the column).
- The consumer records the epoch it routed against. Under RFC-0001 leases this is
  free: the claim stamps `lease_epoch` (the slot's epoch at claim time) onto the
  lease.
- The lease **renew** predicate (RFC-0001, every TTL/3) gains `AND epoch =
  $lease_epoch`:

  ```sql
  UPDATE gpu_slots SET lease_expires = now() + $ttl
   WHERE lease_id = $held AND now() < lease_expires
     AND epoch = $lease_epoch            -- config changed under us => zero rows
  RETURNING lease_id;
  ```

  Zero rows now means **"lease lost OR the slot's capability changed underneath
  me — stop, drop the slot, re-pick."** The consumer's existing "zero rows = stop
  touching the GPU" handling already covers it; it just gains a second cause.

This is the whole mechanism: **epoch fencing rides on the lease renew.** No
backend changes, no new protocol — the inference server never needs to know the
registry's epoch, because the registry-side renew is where staleness is caught.

### Without leases (degenerate)

If a consumer routes without taking a lease (e.g. a one-shot request), it can
still do a cheap pre-flight `SELECT epoch FROM gpu_slots WHERE … = $slot` and
compare to the epoch it picked; a mismatch means re-pick. Optional; the lease
path is the primary mechanism.

## Failure modes addressed

| Failure | Defense |
|---|---|
| Node swaps model/backend mid-job | `epoch` bumps → lease renew returns zero rows → consumer re-picks |
| NVLink domain re-forms (RFC-0004) | `nvlink_domain` change bumps epoch → stale TP routing rejected |
| Consumer caches an endpoint across a node restart | restart changes served_model/endpoint → epoch bump → fenced |
| Spurious churn (VRAM/util) causing re-pick storms | only routing-relevant fields bump epoch; VRAM/util excluded |

## Falsifiable gate

- Bumping a slot's `served_model` causes a holding consumer's next lease-renew to
  return **zero rows** (forced re-pick); proven by a test that mutates the row
  mid-lease.
- A VRAM/util-only change does **not** bump epoch and does **not** invalidate a
  lease.
- A re-pick after an epoch bump lands on the slot's *new* capability, never the
  stale one.

## Migration / rollout

1. **DB:** add `lease_epoch BIGINT` to the lease columns (RFC-0001); keep the
   existing `epoch` column.
2. **Heartbeat:** add the routing-relevant-field diff that bumps `epoch`.
3. **`pick_slot` / `di_fleet`:** stamp `lease_epoch` on claim; add `AND epoch =
   $lease_epoch` to renew.

Ships **after** RFC-0001 (it reuses the lease renew). Until then, `epoch` stays a
dormant column (current behavior).

## Open questions

- Exact set of "routing-relevant" fields that bump epoch — start minimal
  (`served_model`, `endpoint_url`, `nvlink_domain`) and widen only if a real
  staleness bug appears.
- Whether `max_context` shrinking mid-lease should hard-fence (could strand a
  big-context job) or just warn.
