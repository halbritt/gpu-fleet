-- 012_peecee_dense_27b_return.sql
-- Swap peecee's LLM slot (slot 0) back from qwen3-vl:8b (011) to the dense
-- Q4_K_M qwen3.6:27b. Owner-directed change (halbritt, 2026-07-21): this
-- supersedes 011's fit-rule selection by direct Principal request, not by a
-- re-run of the peecee-serves-qwen3-vl@1 selection procedure; the VL capability
-- is de-advertised until a future migration brings it back.
--
-- Runtime already matches: the 27b was loaded resident on peecee 2026-07-21
-- (ollama ps: 17 GB, 100% GPU, num_ctx 32768, keep_alive Forever) — the same
-- tuned-resident state 006 documents (q8_0 KV + flash-attn, ~18.9 GiB used at
-- 32k ctx). This migration converges the advertised directory to the box.
--
-- Context: peecee bugchecked 2026-07-20 (0x1E in nvlddmkm.sys on driver 610.62);
-- the box was rolled back to driver 596.49 the same night (halbritt/peecee
-- README "GPU driver" section). The swap to 27b is the owner's call following
-- that incident, not a consequence of the fit rule.
--
-- Unchanged, re-asserted:
--   probe_model 'ollama-ondemand' — the load-aware liveness-MODE selector
--     (005/011: setting it to the served tag would revert to per-tick decode
--     probes that force-load the model).
--   max_context 32768 — 006's measured full-residency context for the 27b.
--   min_load_vram_mib 21000 — still valid for the 27b by 006's original
--     justification (conservative vs the ~18-19 GiB cold-load footprint) and
--     still inside 011's finding-176 liveness window.
--
-- SCOPE: fleet_nodes (desired state) only; gpu_slots converges on the next
-- heartbeat tick, and the UPSERT's epoch CASE (RFC 0003, migration 008) fences
-- any in-flight lease on the served_model change. No schema or code change; no
-- change to marker's slot 1. Append-only provenance: 011 remains history.

UPDATE fleet_nodes
SET served_model      = 'qwen3.6:27b',
    probe_model       = 'ollama-ondemand',
    max_context       = 32768,
    min_load_vram_mib = 21000
WHERE node = 'peecee' AND slot_id = 0;
