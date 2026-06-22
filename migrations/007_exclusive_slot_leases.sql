-- RFC 0001 — Exclusive slot leases (v1, capacity-1).
--
-- Make di-fleet's K-fan-out claims EXCLUSIVE instead of advisory: a slot is held
-- by exactly one consumer for a bounded, self-renewing TTL evaluated entirely by
-- Postgres. Capacity is DERIVED from live leases (no mutable counter, no reaper);
-- a crashed/frozen consumer's lease expires autonomously; a zombie that wakes is
-- fenced out by lease_id. The table + a query stay the router — no central daemon.
--
-- ── This migration is the EXPAND half of an expand/contract (parallel-change) ──
-- The RFC's data model renames `free_slots` -> `capacity`. A literal
--   ALTER TABLE gpu_slots RENAME COLUMN free_slots TO capacity;
-- would break the RUNNING heartbeat writer (heartbeat.py / heartbeat_all.py both
-- INSERT/UPDATE `free_slots`) the instant the DDL commits — before any consumer is
-- upgraded. So we EXPAND now (add `capacity` alongside `free_slots`) and CONTRACT
-- later: a future, out-of-scope migration 008 drops `free_slots` only AFTER the
-- heartbeat stops writing it. End state is identical to the RFC; the in-between
-- state never breaks a live process and is fully reversible (see bottom).
--
-- This migration is PURELY ADDITIVE: ADD COLUMN (constant default / nullable),
-- one backfill UPDATE, one new partial index. It renames nothing and drops nothing.
-- `free_slots` and `gpu_slots_claim_idx` are intentionally left untouched.
--
-- Deploy ordering (operator, AFTER the build integrates — DB -> readers -> writers):
--   1. DB:       apply this file (additive => safe even with gpu-fleet-heartbeat
--                running; stop -> migrate -> start is optional and equally safe).
--   2. Readers:  deploy the new pick_slot.py (picks lease-free slots; still emits
--                the `free_slots` key, aliased from `capacity`, for un-upgraded readers).
--   3. Writers:  deploy the new di_fleet.py + re-deploy bin/di-fleet (begins
--                claiming / renewing / releasing with the in-flight abort active).
-- The heartbeat writer needs NO change in v1.

-- capacity: immutable max concurrent leases. Every slot in the current fleet is 1.
-- Intentionally NOT dynamically branched on in the capacity-1 pick/claim path (the
-- lease-free predicate IS the availability test when capacity = 1) — it is the
-- expand-half of the free_slots -> capacity rename, not a dead/drifting column.
ALTER TABLE gpu_slots
    ADD COLUMN IF NOT EXISTS capacity INT NOT NULL DEFAULT 1 CHECK (capacity >= 1);

-- Backfill from the column it supersedes. The fleet is all capacity-1 today
-- (free_slots defaulted to 1); GREATEST(...,1) keeps the CHECK satisfied even if a
-- row somehow carried free_slots = 0.
UPDATE gpu_slots SET capacity = GREATEST(free_slots, 1);

-- Lease columns: all nullable, NO default. A fresh INSERT that omits them (exactly
-- today's heartbeat UPSERT) leaves them NULL => every slot reads FREE => today's
-- behavior, until a consumer claims. A slot is FREE  <=>  lease_id IS NULL OR now() >= lease_expires.
ALTER TABLE gpu_slots
    ADD COLUMN IF NOT EXISTS lease_id      UUID,        -- NULL = free; the fence token (zombie renew matches 0 rows)
    ADD COLUMN IF NOT EXISTS lease_holder  TEXT,        -- consumer id (observability only)
    ADD COLUMN IF NOT EXISTS lease_expires TIMESTAMPTZ; -- server-stamped now() + ttl; autonomous expiry, no reaper

-- Partial covering index for the lease-free pick path. COMPLEMENTS (does not
-- replace) gpu_slots_claim_idx, which stays for the legacy free_slots ordering
-- until the contract migration retires it.
CREATE INDEX IF NOT EXISTS gpu_slots_lease_pick_idx
    ON gpu_slots (alive, heartbeat_ts DESC)
    WHERE lease_id IS NULL;

-- NOTE: the CLAIM lifecycle (leases.py) uses gen_random_uuid(), which is in core
-- Postgres since 13 (no extension needed on a modern cluster). On <13 add:
--   CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- This migration itself stamps no UUIDs, so it has no such dependency.

-- ── Reversibility (before any consumer has claimed) ────────────────────────────
-- This migration restores the exact prior schema/behavior with:
--   DROP INDEX IF EXISTS gpu_slots_lease_pick_idx;
--   ALTER TABLE gpu_slots
--     DROP COLUMN IF EXISTS lease_id,
--     DROP COLUMN IF EXISTS lease_holder,
--     DROP COLUMN IF EXISTS lease_expires,
--     DROP COLUMN IF EXISTS capacity;
-- `free_slots` was never touched, so rollback is total.
--
-- ── Out of scope (future contract migration 008) ───────────────────────────────
-- Once pick_slot/di_fleet no longer read `free_slots` AND the heartbeat stops
-- writing it, 008 drops gpu_slots.free_slots (+ fleet_nodes.free_slots) and
-- gpu_slots_claim_idx. NOT built here — this build stays strictly additive.
