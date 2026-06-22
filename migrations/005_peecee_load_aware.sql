-- 005_peecee_load_aware.sql
-- Make peecee's on-demand MoE slot (slot 0) tell the truth about whether it can
-- ACTUALLY serve right now, instead of always advertising "alive".
--
-- Today slot 0 uses probe_model='gpu-only' (004): liveness is mere GPU
-- reachability, so it advertises alive even when marker (slot 1) owns the whole
-- 24.5 GiB card and the MoE therefore CANNOT load. di then routes a request that
-- peecee can't serve -- the bug.
--
-- Threshold calibration (measured this session, 24564 MiB card): the MoE needs
-- ~21.85 GiB of VRAM for its weights and loads (at a ~3%/97% CPU/GPU spill that
-- still serves correctly) whenever the card is otherwise idle -- observed idle
-- free was 21690-22095 MiB (the rest is irreducible Windows-desktop/driver
-- overhead, NOT available to ollama). When marker is resident it takes multiple
-- GiB, dropping free well below that. So the loadable floor is the free VRAM
-- needed to LOAD the model (~21 GiB), NOT its total resident footprint: 21000 MiB
-- sits just under the idle floor (so marker-idle => loadable) and above any
-- marker-resident state (so marker-busy => not loadable). 23000 would be
-- UNREACHABLE -- the card never has that much free given desktop overhead -- and
-- would wrongly mark peecee not-loadable forever, defeating di's fan-out.
--
-- The new probe_model='ollama-ondemand' mode (heartbeat.py ollama_ondemand_liveness)
-- gives three honest states with NO consumer/schema change:
--   WARM         model already resident   -> alive, probe_ms set (decode-probe a
--                                             model that is ALREADY loaded -- this
--                                             does not force a load)
--   COLD/LOADABLE not resident, free VRAM >= min_load_vram_mib -> alive, probe_ms NULL
--                                             (does NOT decode-probe -> never forces a load)
--   NOT LOADABLE  not resident, free VRAM <  min_load_vram_mib -> alive=false
--                                             (ages out of live_slots; di won't route to it)
-- min_load_vram_mib is the free-VRAM floor (MiB) to call the model loadable.
--
-- DEPLOY ORDERING (operator): this column does not exist until this migration is
-- applied, and heartbeat_all.py's per-tick FETCH selects it. So:
--   1. Apply THIS migration (psql ... -f migrations/005_peecee_load_aware.sql).
--   2. THEN restart the heartbeat on the new code:
--        systemctl --user restart gpu-fleet-heartbeat   (or the system unit name)
-- Doing it in the other order makes the new-code FETCH reference a missing column
-- and the tick errors until the migration lands; the old code ignores the new
-- column, so applying the migration first is always safe.

ALTER TABLE fleet_nodes ADD COLUMN IF NOT EXISTS min_load_vram_mib INT;

UPDATE fleet_nodes
SET probe_model       = 'ollama-ondemand',
    min_load_vram_mib = 21000
WHERE node = 'peecee' AND slot_id = 0;
