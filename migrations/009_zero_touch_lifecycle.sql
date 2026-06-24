-- RFC 0002 — Zero-touch node lifecycle. Columns-only / additive (one new table,
-- one new view). Backward-compatible: BEFORE Slice 1 the running heartbeat UPSERT
-- names none of these, so it is unaffected the instant this commits; consumers do
-- not read `status` until Slice 4, so until then behavior == today.
--
-- 009 is the lowest unused migration number (migrations/ holds 001-008). The RFC
-- body's "Migration 006" is stale/illustrative: it predates this campaign's peecee
-- dense flip (006), RFC-0001's leases (007), and RFC-0003's epoch (008). Reuse none.
--
-- Apply order (operator, AFTER integration): DB -> heartbeat (writer) -> puller ->
-- consumers. Additive, so safe even with gpu-fleet-heartbeat running; stop -> migrate
-- -> start is optional and equally safe. ADD COLUMN / CREATE ... IF NOT EXISTS make
-- a re-apply idempotent.

-- Pillar 4 — quarantine->graduate, MEASURED capability.
ALTER TABLE gpu_slots
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (status IN ('unverified','probationary','routable','demoted')),
    ADD COLUMN IF NOT EXISTS probe_streak INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS gpu_uuid TEXT,        -- measured identity (NULL = unknown / pull-only)
    ADD COLUMN IF NOT EXISTS boot_epoch BIGINT;    -- Pillar 5 ratchet (SEPARATE from `epoch`); NULL = ratchet off

-- Backfill: every slot live TODAY is treated as routable (RFC migration note),
-- so flipping the consumer gate later strands nothing already in service.
UPDATE gpu_slots SET status = 'routable';

-- Pillar 2 — per-node driver-lease (single-writer arbitration on the DECLARED table).
ALTER TABLE fleet_nodes
    ADD COLUMN IF NOT EXISTS driven_by  TEXT,         -- which writer holds this node (NULL = puller drives)
    ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ; -- deadman TTL; expired => puller resumes

-- Pillar 1 — global puller-lease row (deadman TTL; same shape as RFC-0001 slot lease).
-- Column `holder` matches the Slice-2 CAS VERBATIM (BC5).
CREATE TABLE IF NOT EXISTS fleet_meta (
    id          INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- single-row
    holder      TEXT,
    lease_until TIMESTAMPTZ
);
INSERT INTO fleet_meta (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Pillar 4 — routable_slots, ADDED ALONGSIDE live_slots (expand/contract; do NOT
-- drop live_slots here — a later contract migration retires it, as 007 did for
-- free_slots). routable = live AND graduated.
CREATE VIEW routable_slots AS
    SELECT *, (now() - heartbeat_ts) AS staleness
    FROM gpu_slots
    WHERE alive
      AND heartbeat_ts > now() - interval '45 seconds'
      AND status = 'routable';

-- ── Reversibility (before the consumer slice deploys) ──────────────────────────
--   DROP VIEW IF EXISTS routable_slots;
--   DROP TABLE IF EXISTS fleet_meta;
--   ALTER TABLE fleet_nodes DROP COLUMN IF EXISTS lease_until, DROP COLUMN IF EXISTS driven_by;
--   ALTER TABLE gpu_slots  DROP COLUMN IF EXISTS boot_epoch, DROP COLUMN IF EXISTS gpu_uuid,
--                          DROP COLUMN IF EXISTS probe_streak, DROP COLUMN IF EXISTS status;
