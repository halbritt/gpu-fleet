-- Schema integrity and endpoint-turnover cleanup.
--
-- Apply after 013, before deploying the matching heartbeat_all.py. The migration
-- is additive for live rows. It removes only capacity rows whose parent slot is
-- already absent, then makes future slot deletion clean up its companion row.

CREATE OR REPLACE FUNCTION gpu_fleet_heartbeat_ttl()
RETURNS interval
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$ SELECT interval '45 seconds' $$;

CREATE OR REPLACE FUNCTION gpu_slot_is_fresh(observed_at timestamptz)
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$ SELECT observed_at > now() - gpu_fleet_heartbeat_ttl() $$;

COMMENT ON FUNCTION gpu_fleet_heartbeat_ttl() IS
    'Authoritative live-slot and lease-renew freshness window.';
COMMENT ON FUNCTION gpu_slot_is_fresh(timestamptz) IS
    'True when a database-stamped heartbeat is inside the fleet freshness window.';

CREATE OR REPLACE VIEW live_slots AS
    SELECT node, endpoint_url, slot_id, gpu_model, nvlink_domain,
           vram_total_mib, vram_free_mib, gpu_util_pct, loaded_model,
           served_model, max_context, latency_class, free_slots, epoch,
           alive, probe_ms, note, heartbeat_ts,
           (now() - heartbeat_ts) AS staleness
    FROM gpu_slots
    WHERE alive AND gpu_slot_is_fresh(heartbeat_ts);

CREATE OR REPLACE VIEW routable_slots AS
    SELECT node, endpoint_url, slot_id, gpu_model, nvlink_domain,
           vram_total_mib, vram_free_mib, gpu_util_pct, loaded_model,
           served_model, max_context, latency_class, free_slots, epoch,
           alive, probe_ms, note, heartbeat_ts, capacity, lease_id,
           lease_holder, lease_expires, lease_epoch, status, probe_streak,
           gpu_uuid, boot_epoch, (now() - heartbeat_ts) AS staleness
    FROM gpu_slots
    WHERE alive
      AND gpu_slot_is_fresh(heartbeat_ts)
      AND status = 'routable';

DELETE FROM gpu_slots_capacity c
WHERE NOT EXISTS (
    SELECT 1
    FROM gpu_slots g
    WHERE (g.node, g.endpoint_url, g.slot_id)
        = (c.node, c.endpoint_url, c.slot_id)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'gpu_slots_capacity_slot_fkey'
          AND conrelid = 'gpu_slots_capacity'::regclass
    ) THEN
        ALTER TABLE gpu_slots_capacity
            ADD CONSTRAINT gpu_slots_capacity_slot_fkey
            FOREIGN KEY (node, endpoint_url, slot_id)
            REFERENCES gpu_slots (node, endpoint_url, slot_id)
            ON DELETE CASCADE;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'gpu_slots_lease_tuple_check'
          AND conrelid = 'gpu_slots'::regclass
    ) THEN
        ALTER TABLE gpu_slots
            ADD CONSTRAINT gpu_slots_lease_tuple_check CHECK (
                (lease_id IS NULL
                 AND lease_holder IS NULL
                 AND lease_expires IS NULL
                 AND lease_epoch IS NULL)
                OR
                (lease_id IS NOT NULL
                 AND lease_holder IS NOT NULL
                 AND lease_expires IS NOT NULL
                 AND lease_epoch IS NOT NULL)
            ) NOT VALID;
    END IF;
END
$$;

ALTER TABLE gpu_slots VALIDATE CONSTRAINT gpu_slots_lease_tuple_check;

-- A slot stores one lease tuple inline on its primary-key row. A btree_gist
-- exclusion constraint cannot add another one-lease-per-slot guarantee here;
-- it becomes relevant only if leases move to a separate multi-row table.

ALTER TABLE gpu_slots DROP CONSTRAINT IF EXISTS gpu_slots_status_check;
ALTER TABLE gpu_slots
    ADD CONSTRAINT gpu_slots_status_check
    CHECK (status IN ('unverified', 'probationary', 'routable')) NOT VALID;
ALTER TABLE gpu_slots VALIDATE CONSTRAINT gpu_slots_status_check;

CREATE OR REPLACE FUNCTION reject_gpu_slot_epoch_regression()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.epoch < OLD.epoch THEN
        RAISE EXCEPTION
            'gpu_slots epoch regression for %/%/%: % -> %',
            NEW.node, NEW.endpoint_url, NEW.slot_id, OLD.epoch, NEW.epoch
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS gpu_slots_epoch_monotonic ON gpu_slots;
CREATE CONSTRAINT TRIGGER gpu_slots_epoch_monotonic
AFTER UPDATE ON gpu_slots
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION reject_gpu_slot_epoch_regression();

-- Reversibility:
--   DROP TRIGGER IF EXISTS gpu_slots_epoch_monotonic ON gpu_slots;
--   DROP FUNCTION IF EXISTS reject_gpu_slot_epoch_regression();
--   ALTER TABLE gpu_slots
--       DROP CONSTRAINT IF EXISTS gpu_slots_lease_tuple_check;
--   ALTER TABLE gpu_slots DROP CONSTRAINT IF EXISTS gpu_slots_status_check;
--   ALTER TABLE gpu_slots ADD CONSTRAINT gpu_slots_status_check
--       CHECK (status IN ('unverified','probationary','routable','demoted'));
--   ALTER TABLE gpu_slots_capacity
--       DROP CONSTRAINT IF EXISTS gpu_slots_capacity_slot_fkey;
--   Recreate live_slots and routable_slots with their prior literal predicate,
--   then DROP FUNCTION gpu_slot_is_fresh(timestamptz) and
--   DROP FUNCTION gpu_fleet_heartbeat_ttl().
