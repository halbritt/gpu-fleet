-- 003_marker_capability.sql
-- Register marker (GPU document -> markdown/JSON via surya) as a BATCH capability
-- on peecee, so consumers route to it by capability instead of hardcoding the host.
--
-- marker is NOT an OpenAI endpoint, so its liveness is GPU reachability (nvidia-smi),
-- signalled by the probe_model sentinel '-'. The heartbeat skips the decode-probe for
-- such rows: probing an LLM here would needlessly load a model and, for a node mid
-- conversion, fight that job for the 24 GiB. endpoint_url is an ssh:// locator (not an
-- HTTP API); consumers resolve the host and run
-- skills/marker-convert/scripts/convert-peecee.sh.

INSERT INTO fleet_nodes
    (node, slot_id, endpoint_url, served_model, probe_model, latency_class, gpu_cmd, max_context)
VALUES
    ('peecee', 1, 'ssh://peecee', 'marker', '-', 'batch',
        'ssh -o BatchMode=yes peecee nvidia-smi', NULL)
ON CONFLICT (node, slot_id) DO UPDATE SET
    endpoint_url  = EXCLUDED.endpoint_url,
    served_model  = EXCLUDED.served_model,
    probe_model   = EXCLUDED.probe_model,
    latency_class = EXCLUDED.latency_class,
    gpu_cmd       = EXCLUDED.gpu_cmd;
