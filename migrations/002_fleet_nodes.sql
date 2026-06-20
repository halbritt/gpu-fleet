-- fleet_nodes: the DECLARED members of the fleet (the desired set) + how to
-- reach and probe each. The heartbeat driver iterates this table EVERY tick and
-- writes observed liveness into gpu_slots. Growing the fleet (e.g. the
-- quad-server, or a node coming back) is a pure INSERT here -- no code, no timer
-- edit, no consumer change. This is the "no human intervention" seam: an agent,
-- or a node's own boot-time join-script, inserts a row and it is live next tick.

CREATE TABLE fleet_nodes (
    node          TEXT NOT NULL,
    slot_id       INT  NOT NULL DEFAULT 0,
    endpoint_url  TEXT NOT NULL,
    served_model  TEXT NOT NULL,
    probe_model   TEXT,                 -- decode-probe target; defaults to served_model
    latency_class TEXT NOT NULL DEFAULT 'batch'
        CHECK (latency_class IN ('interactive', 'batch')),
    gpu_cmd       TEXT NOT NULL DEFAULT 'nvidia-smi',  -- how the driver runs nvidia-smi
    nvlink_domain TEXT,
    max_context   INT,
    free_slots    INT NOT NULL DEFAULT 1,
    epoch         BIGINT NOT NULL DEFAULT 0,
    enabled       BOOLEAN NOT NULL DEFAULT true,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (node, slot_id)
);

INSERT INTO fleet_nodes
    (node, endpoint_url, served_model, probe_model, latency_class, gpu_cmd, max_context)
VALUES
    ('proximal', 'http://localhost:8081/v1', 'qwen3.6-35b-a3b', 'qwen3.6-35b-a3b',
        'interactive', 'nvidia-smi', 262144),
    ('peecee', 'http://peecee:11434/v1', 'qwen3.6:27b', 'qwen3.6:27b',
        'batch', 'ssh -o BatchMode=yes peecee nvidia-smi', 32768)
ON CONFLICT (node, slot_id) DO NOTHING;
