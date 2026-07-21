-- 013_peecee_qwen3_vl_return.sql
-- Swap peecee's LLM slot (slot 0) back from the dense qwen3.6:27b (012) to
-- qwen3-vl:8b, restoring 011's advertised state. Owner-directed (halbritt,
-- 2026-07-21), reversing 012's owner-directed detour the same day; 011's
-- fit-rule selection (contract peecee-serves-qwen3-vl@1) and its adjudication
-- card resume as the governing rationale for this exact row state — see 011
-- for the full derivation of every value below.
--
-- Runtime already matches: qwen3-vl:8b re-loaded resident on peecee 2026-07-21
-- (ollama ps: 7.5 GB, 100% GPU, num_ctx 32768, keep_alive Forever). This
-- migration converges the advertised directory back to the box.
--
-- Values identical to 011 (see its header for justification):
--   served_model      qwen3-vl:8b       (fit rule: 32B fails residency at floor)
--   probe_model       'ollama-ondemand' (liveness-mode selector, never the tag)
--   max_context       32768             (measured full-residency floor)
--   min_load_vram_mib 21000             (finding-176 liveness-window value)
--
-- SCOPE: fleet_nodes (desired state) only; gpu_slots converges on the next
-- heartbeat tick; the epoch CASE fences in-flight leases. Append-only
-- provenance: 012 remains history.

UPDATE fleet_nodes
SET served_model      = 'qwen3-vl:8b',
    probe_model       = 'ollama-ondemand',
    max_context       = 32768,
    min_load_vram_mib = 21000
WHERE node = 'peecee' AND slot_id = 0;
