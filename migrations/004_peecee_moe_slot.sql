-- 004_peecee_moe_slot.sql
-- Flip peecee's LLM slot (slot 0) from the dense qwen3.6:27b to the MoE
-- qwen3.6:35b-a3b, so peecee serves the same high-throughput ideation model as
-- proximal. di's fan-out wants uniform MoE slots; the MoE is weak at tool calls
-- but di never tool-calls, so that trade-off is irrelevant on this lane.
--
-- LIVENESS = GPU reachability (probe_model 'gpu-only'), NOT a decode-probe. peecee
-- shares its single 24 GiB GPU with marker (slot 1, see 003). A 15 s decode-probe
-- would keep ollama's ~23 GiB MoE pinned resident between ticks and starve marker;
-- GPU-reachability liveness advertises the capability without loading anything.
-- The MoE loads only when a consumer (di) actually sends a request and unloads
-- when idle, so di and marker time-share the card instead of fighting over it.

UPDATE fleet_nodes
SET served_model = 'qwen3.6:35b-a3b',
    probe_model  = 'gpu-only'
WHERE node = 'peecee' AND slot_id = 0;
