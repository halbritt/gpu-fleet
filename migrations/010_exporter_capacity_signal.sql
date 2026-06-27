-- RFC 0005 — Exporter-fed capacity signal (probe-anchored). Migration 010 (Slice 0).
--
-- ADDITIVE / behavior-neutral: three new tables, one new view, two new nullable
-- gpu_slots columns. Renames nothing, drops nothing. Every companion/policy field is
-- nullable/defaulted or seeded ON CONFLICT DO NOTHING against a real key, so the schema
-- existing changes NOTHING until the heartbeat populates the companion AND the reader
-- switches (Slice 3) AND the operator seeds model_capacity. The running heartbeat
-- liveness UPSERT names none of these, so it is unaffected the instant this DDL commits.
--
-- 010 is the lowest unused migration number (migrations/ holds 001-009). The RFC body's
-- "Migration 010 (or 011 if the free_slots contract migration lands first)" resolves to
-- 010: the free_slots -> capacity CONTRACT migration is not built, so it never consumed a
-- number. The packet objective's generic "migration 006" defers to the live tree.
--
-- Apply order (operator, AFTER integration): DB -> writers -> reader (BC5). Slice 2 has a
-- HARD precondition on THIS migration (mig_mode/ecc_mode ride the NON-savepoint-guarded
-- liveness UPSERT), so deploying a writer against the un-migrated schema fails the
-- liveness UPSERT and ages slots out. Additive => safe even with gpu-fleet-heartbeat
-- running; stop -> migrate -> start is optional and equally safe. IF NOT EXISTS / nullable
-- everywhere => idempotent re-apply (gate test Q).

-- ── Companion table (OQ-A) — fault isolation: a flaky exporter can't poison the
-- liveness UPSERT, because capacity lives in a SEPARATE table the heartbeat writes under
-- a savepoint and pick LEFT JOINs. Keyed by the SAME PK as gpu_slots; all columns
-- nullable/defaulted, so an absent row == capacity_source 'absent' == "fall back to
-- today's vram_free_mib".
CREATE TABLE IF NOT EXISTS gpu_slots_capacity (
    node               TEXT NOT NULL,
    endpoint_url       TEXT NOT NULL,
    slot_id            INT  NOT NULL DEFAULT 0,

    cold_probe_ms        INT,        -- idle/registration decode baseline (STICKY, F-BASE)
    live_slowdown_factor NUMERIC,    -- this-tick probe / cold baseline (computed in SQL, BC3)
    probe_floor_mib      INT,        -- probe-measured allocatable floor (banded)
    exporter_free_mib    INT,        -- enrichment: exporter-reported free VRAM (banded)
    effective_free_mib   INT,        -- LEAST(probe_floor, exporter) - phantom (banded, C4/OQ-P)
    util_band            SMALLINT,   -- quantized util (hysteresis band)
    power_w              INT,        -- exporter enrichment
    temp_c               INT,        -- exporter enrichment
    phantom_mib          INT NOT NULL DEFAULT 0,  -- measured unrecognized-PID VRAM (OQ-P)
    phantom_pids         INT NOT NULL DEFAULT 0,

    -- Provenance enum (Principle 2). The writer stamps measured/exporter_down/absent;
    -- the freshness-decay logic (view + inline pick/claim) derives 'stale'.
    capacity_source TEXT NOT NULL DEFAULT 'absent'
        CHECK (capacity_source IN ('measured','stale','exporter_down','absent')),

    -- BC2 single-clock freshness: BOTH are SAME-clock differences. fast_source_age_s is the
    -- node-clock age of the fast-field source measurement at write time (a node-local
    -- subtraction); now()-updated_ts is a DB-clock difference. Staleness = their sum, so an
    -- absolute node<->DB NTP skew CANCELS in each difference, yet a frozen source (its age
    -- grows each tick) or an unwritten row (now()-updated_ts grows) still decays.
    fast_source_age_s NUMERIC,       -- node-clock age of the FAST source measurement
    slow_source_age_s NUMERIC,       -- node-clock age of the SLOW capability measurement
    updated_ts        TIMESTAMPTZ NOT NULL DEFAULT now(),  -- DB write clock

    PRIMARY KEY (node, endpoint_url, slot_id)
);

-- ── Slow CAPABILITY bands on gpu_slots (C-EPOCH). MIG/ECC come from the node's OWN local
-- nvidia-smi (measured, trusted), NOT the exporter, so coupling them to epoch does not
-- couple epoch to the untrusted exporter. Nullable => epoch behaves EXACTLY as today
-- (NULL IS DISTINCT FROM NULL is false) until a writer names them.
ALTER TABLE gpu_slots
    ADD COLUMN IF NOT EXISTS mig_mode TEXT,
    ADD COLUMN IF NOT EXISTS ecc_mode TEXT;

-- ── Policy-as-data (tuning is a row edit, never a redeploy). TRUE SINGLETON (F-CARD):
-- id PK + CHECK (id = 1) makes a second row IMPOSSIBLE, so a re-applied migration or a
-- fat-fingered tuning insert can never create a second policy row — the seed's
-- ON CONFLICT (id) DO NOTHING now has a real unique constraint to conflict on. The view
-- and the picker reference it via a guaranteed-one-row WHERE id = 1, so neither can
-- multiply a slot row. Tuning is an UPDATE of the id = 1 row.
CREATE TABLE IF NOT EXISTS capacity_policy (
    id                              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    fast_half_life_s                NUMERIC  NOT NULL DEFAULT 30,    -- fast fields: seconds-scale
    slow_half_life_s                NUMERIC  NOT NULL DEFAULT 3600,  -- capability fields: hours-scale
    decay_k                         NUMERIC  NOT NULL DEFAULT 3,     -- decay multiplier k
    vram_band_mib                   INT      NOT NULL DEFAULT 1000,  -- VRAM hysteresis band width
    util_band_pct                   INT      NOT NULL DEFAULT 10,    -- util hysteresis band width
    band_confirm_m                  SMALLINT NOT NULL DEFAULT 2,     -- M-of-N band confirmations
    band_confirm_n                  SMALLINT NOT NULL DEFAULT 3,
    default_request_context_tokens  INT      NOT NULL DEFAULT 0      -- BC1 max_context fallback (0 => 0 KV)
);
INSERT INTO capacity_policy (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ── Request-capacity policy (BC1) — per-model footprint + per-token KV cost, AS DATA,
-- measured offline by the operator (like min_load_vram_mib already is). The build NEVER
-- measures real GPUs and seeds NO rows here. model PRIMARY KEY => a LEFT JOIN on a slot's
-- served_model returns AT MOST ONE row per slot (F-CARD: no fan-out). A model with NO row
-- LEFT-JOINs to NULL => COALESCE(...,0) => footprint 0, KV 0 => the headroom predicate
-- reduces to today's flat-VRAM test (the backward-compat anchor, C7).
CREATE TABLE IF NOT EXISTS model_capacity (
    model                 TEXT PRIMARY KEY,
    footprint_mib         INT     NOT NULL DEFAULT 0,
    kv_mib_per_1k_tokens  NUMERIC NOT NULL DEFAULT 0
);

-- ── Diagnostic / read-only view: gpu_slots LEFT JOIN companion LEFT JOIN model_capacity,
-- CROSS JOIN the SINGLETON policy. Provably ONE ROW per (node, endpoint_url, slot_id)
-- (F-CARD): the companion/model joins are PK/unique and the policy is the singleton.
--
-- The locking pick/claim paths replicate this same join + decay INLINE over the base
-- tables (Slice 3, F-LOCK) and NEVER lock FOR UPDATE through this view. live_slots /
-- routable_slots are NOT dropped (expand/contract).
CREATE OR REPLACE VIEW capacity_slots AS
SELECT
    g.*,
    c.cold_probe_ms,
    c.live_slowdown_factor,
    c.probe_floor_mib,
    c.exporter_free_mib,
    c.util_band,
    c.power_w,
    c.temp_c,
    c.phantom_mib,
    c.phantom_pids,
    c.fast_source_age_s,
    c.slow_source_age_s,
    c.updated_ts AS capacity_updated_ts,
    mc.footprint_mib,
    mc.kv_mib_per_1k_tokens,
    -- BC2 single-clock staleness = node-clock age + DB-clock (now()-updated_ts).
    (COALESCE(c.fast_source_age_s, 0)
       + GREATEST(0, EXTRACT(EPOCH FROM (now() - c.updated_ts)))) AS fast_staleness_s,
    (COALESCE(c.slow_source_age_s, 0)
       + GREATEST(0, EXTRACT(EPOCH FROM (now() - c.updated_ts)))) AS slow_staleness_s,
    -- Freshness-decayed provenance: a 'measured' fast field aged past k*fast_half_life_s
    -- self-erases to 'stale'; an absent companion stays 'absent'.
    CASE
        WHEN c.node IS NULL THEN 'absent'
        WHEN c.capacity_source = 'measured'
             AND (COALESCE(c.fast_source_age_s, 0)
                    + GREATEST(0, EXTRACT(EPOCH FROM (now() - c.updated_ts))))
                 > cp.decay_k * cp.fast_half_life_s
            THEN 'stale'
        ELSE c.capacity_source
    END AS capacity_source,
    -- Decayed effective_free: NULL once the fast fields decay to stale, so a reader
    -- COALESCEs through to gpu_slots.vram_free_mib instead of a stale number.
    CASE
        WHEN c.capacity_source = 'measured'
             AND (COALESCE(c.fast_source_age_s, 0)
                    + GREATEST(0, EXTRACT(EPOCH FROM (now() - c.updated_ts))))
                 <= cp.decay_k * cp.fast_half_life_s
            THEN c.effective_free_mib
        ELSE NULL
    END AS effective_free_mib,
    cp.decay_k,
    cp.fast_half_life_s,
    cp.slow_half_life_s,
    cp.default_request_context_tokens
FROM gpu_slots g
LEFT JOIN gpu_slots_capacity c
       ON (c.node, c.endpoint_url, c.slot_id) = (g.node, g.endpoint_url, g.slot_id)
LEFT JOIN model_capacity mc ON mc.model = g.served_model
CROSS JOIN (SELECT * FROM capacity_policy WHERE id = 1) cp;

-- ── Reversibility (before Slice 3 deploys) ─────────────────────────────────────────────
--   DROP VIEW IF EXISTS capacity_slots;
--   DROP TABLE IF EXISTS model_capacity;
--   DROP TABLE IF EXISTS capacity_policy;
--   DROP TABLE IF EXISTS gpu_slots_capacity;
--   ALTER TABLE gpu_slots DROP COLUMN IF EXISTS ecc_mode, DROP COLUMN IF EXISTS mig_mode;
