-- Advertise the tuned Qwen3.6-35B-A3B review capability on proximal's single
-- llama.cpp slot. Owner-directed deployment, 2026-08-03. The endpoint remains
-- unchanged; llama.cpp loads the accepted GGUF LoRA and serves alias
-- qwen3.6-ft. This is a capability transition, not an additional slot.
--
-- SCOPE: fleet_nodes desired state only. heartbeat_all measures and writes
-- gpu_slots on the next tick; the served_model change bumps the measured
-- epoch and fences a holder routed against the old capability.
--
-- Rollback: restore the service without --lora and apply a new append-only
-- migration setting both values back to qwen3.6-35b-a3b. Do not edit or
-- reverse this migration after it has been applied.

UPDATE fleet_nodes
SET served_model = 'qwen3.6-ft',
    probe_model = 'qwen3.6-ft'
WHERE node = 'proximal' AND slot_id = 0;
