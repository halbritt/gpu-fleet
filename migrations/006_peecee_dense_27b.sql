-- 006_peecee_dense_27b.sql
-- Flip peecee's LLM slot (slot 0) from the MoE qwen3.6:35b-a3b back to the dense
-- Q4_K_M qwen3.6:27b -- now the intended resident model on peecee's 24 GiB card.
-- Tuned 2026-06-22: OLLAMA_KV_CACHE_TYPE=q8_0 + OLLAMA_FLASH_ATTENTION keep the dense
-- 27b fully resident at 32k context (~18.9 GiB used / ~5.4 GiB free, ollama ps =
-- 100% GPU). Advertising 35b-a3b here would make a consumer request load the MoE and
-- evict the tuned-resident 27b, so the slot must match the box.
--
-- Keeps the load-aware liveness from 005 (probe_model 'ollama-ondemand'): with
-- OLLAMA_KEEP_ALIVE=-1 the 27b stays WARM (decode-probed); it goes COLD only when
-- marker's convert.ps1 unloads it for a conversion, then re-lists once the card frees.
-- min_load_vram_mib (21000) is left as-is -- conservative for the 27b's smaller
-- ~18-19 GiB cold-load footprint (safe; only slightly strict on the COLD re-list).

UPDATE fleet_nodes
SET served_model = 'qwen3.6:27b'
WHERE node = 'peecee' AND slot_id = 0;
