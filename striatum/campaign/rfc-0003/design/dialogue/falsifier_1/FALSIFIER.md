# FALSIFIER - RFC 0003 build plan challenge

author: falsifier-openai-codex-gpt-5.5-003

## Claim challenged

The holder plan refines RFC-0003 by excluding `endpoint_url` from the epoch bump
CASE and claims endpoint changes are still covered by row turnover plus
`di --json` child failure. The concrete claim is C5: because `endpoint_url` is in
the `(node, endpoint_url, slot_id)` primary key, a changed endpoint creates a new
row, the old row ages out of `live_slots`, and an existing consumer on the old
URL will fail its child and fail over.

That is not an epoch fence. It is a best-effort runtime symptom outside the
registry predicate. The proposed renew path can continue extending the old
leased row after the row has stopped being the fresh endpoint for that node and
slot.

## Evidence

- RFC-0003 names `endpoint_url` as routing-relevant and lists "consumer caches an
  endpoint across a node restart" as a failure mode the fence should address.
- `migrations/001_gpu_slots.sql` makes `endpoint_url` part of the primary key and
  defines `live_slots` as `alive` plus `heartbeat_ts > now() - interval '45
  seconds'`.
- The plan agrees that an endpoint change cannot be an in-place `ON CONFLICT`
  update. It inserts a new row and leaves the old endpoint row behind until
  freshness removes it from `live_slots`.
- The plan's Slice D renew predicate adds only
  `(lease_epoch IS NULL OR epoch = lease_epoch)` to the RFC-0001 identity and
  expiry checks. It does not require the held row to be alive, fresh, present in
  `live_slots`, or the current endpoint row for `(node, slot_id)`.
- The gate map proves same-row capability bumps and churn non-bumps. It does not
  include an endpoint-turnover test where a lease remains on the old PK row while
  heartbeat starts writing the new endpoint row.

## Concrete counterexample

1. A consumer claims `(node='peecee', endpoint_url='old', slot_id=0)`. The claim
   stamps `lease_epoch = epoch` on that old row.
2. The node restarts or reconfigures and heartbeat begins writing
   `(node='peecee', endpoint_url='new', slot_id=0)`. Because `endpoint_url` is in
   the PK, this inserts a different row. The old row receives no in-place epoch
   bump.
3. The old row stops being fresh, so future picks will not see it through
   `live_slots`. But the already-running holder renews before lease expiry.
4. Under the plan's renew predicate, the old row still matches `lease_id`, still
   satisfies `now() < lease_expires`, and still has `epoch = lease_epoch`.
   Therefore renew succeeds even though the endpoint the consumer routed against
   is stale by the RFC's own failure model.

The holder plan's rebuttal is that the child should fail against the old URL.
That is a live-infra assumption, not a database invariant. The old URL can remain
reachable behind a proxy, serve the previous backend during a rolling restart,
or fail later than the renew that should have forced re-pick. In each case the
plan keeps routing to a cached endpoint while the registry continues to renew
the stale lease.

## Refutation test

The plan needs an endpoint-turnover gate, not only an in-place epoch-bump gate:

1. Seed a real or faithful registry with endpoint `old`, claim it, and stamp
   `lease_epoch`.
2. Simulate heartbeat moving the same `(node, slot_id)` to endpoint `new`, so the
   old endpoint row is no longer fresh but still carries the held `lease_id`.
3. Advance past the `live_slots` freshness window while staying before
   `lease_expires`.
4. Assert renew of the old lease returns zero rows.

With the plan as written, that assertion should fail. Neither
`FakeSlotDB.bump_epoch(slot)` nor a fake renew returning false after a bump
models the primary-key split the plan relies on for endpoint changes.

## Unanswered gap

The committed plan must choose one falsifiable position:

- remove endpoint turnover from RFC-0003's accepted guarantee and say endpoint
  restarts are only best-effort child-failure handling outside the epoch fence;
  or
- add a binding design constraint and gate that renewal fails once the held row
  is no longer the fresh heartbeated endpoint row for its node and slot.

Without that choice, the plan has a test-gate adequacy hole and a live-infra
leak: it asks external `di --json` behavior to compensate for a stale registry
lease that the database itself continues to renew.