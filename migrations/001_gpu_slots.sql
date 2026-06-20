-- gpu-fleet registry spine.
--
-- A heartbeat-refreshed DIRECTORY of live GPU serving slots across a dynamic,
-- extensible, multi-host fleet. Domain-agnostic substrate: this table holds
-- only mechanism (which slots exist, their capacity, are they alive); all
-- POLICY (which model is "the chat model", how many branches di gets, latency
-- thresholds) lives in the consumers.
--
-- A node JOINS the fleet by heartbeating a row; it LEAVES by going silent
-- (a stale heartbeat ages it out of `live_slots`). Liveness is a real
-- decode-probe result (`alive`), NOT an HTTP /health 200 — a wedged model loop
-- can serve 200s while failing to decode.
--
-- Addressing is by CAPABILITY (served_model, vram_free, latency_class,
-- nvlink_domain), never by host identity. NVLink pairs advertise a shared
-- `nvlink_domain` tag and act as one larger tensor-parallel slot.

CREATE TABLE gpu_slots (
    node            TEXT NOT NULL,            -- host identity, e.g. 'proximal', 'peecee'
    endpoint_url    TEXT NOT NULL,            -- OpenAI-compatible base, e.g. http://peecee:11434/v1
    slot_id         INT  NOT NULL DEFAULT 0,  -- for -np N backends; 0 = single slot

    gpu_model       TEXT,                     -- 'NVIDIA GeForce RTX 3090 Ti'
    nvlink_domain   TEXT,                     -- topology tag; equal value => one TP domain; NULL = singleton
    vram_total_mib  INT,
    vram_free_mib   INT,
    gpu_util_pct    INT,

    loaded_model    TEXT,                     -- model the decode-probe exercised (warm), or NULL
    served_model    TEXT,                     -- model id/tag consumers should request
    max_context     INT,                      -- context the backend serves (NULL = unknown)
    latency_class   TEXT NOT NULL DEFAULT 'batch'
        CHECK (latency_class IN ('interactive', 'batch')),
    free_slots      INT  NOT NULL DEFAULT 1 CHECK (free_slots >= 0),

    epoch           BIGINT NOT NULL DEFAULT 0, -- node bumps on topology/model change; stale-router reject hook
    alive           BOOLEAN NOT NULL DEFAULT false, -- last decode-probe succeeded
    probe_ms        INT,                       -- decode-probe round-trip
    note            TEXT,                      -- freeform: last error, etc.
    heartbeat_ts    TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (node, endpoint_url, slot_id)
);

CREATE INDEX gpu_slots_claim_idx
    ON gpu_slots (latency_class, alive, free_slots DESC, heartbeat_ts DESC);

-- "live" = decode-probe passed AND heartbeat is fresh. The TTL (45s) is the
-- evaporation that makes leave/crash self-healing: stop heartbeating -> vanish.
CREATE VIEW live_slots AS
    SELECT *, (now() - heartbeat_ts) AS staleness
    FROM gpu_slots
    WHERE alive
      AND heartbeat_ts > now() - interval '45 seconds';
