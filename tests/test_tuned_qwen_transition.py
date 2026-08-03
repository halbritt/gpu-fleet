from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "015_proximal_tuned_qwen.sql"


def test_tuned_qwen_transition_declares_one_exact_proximal_capability():
    sql = MIGRATION.read_text()

    assert "UPDATE fleet_nodes" in sql
    assert "served_model = 'qwen3.6-ft'" in sql
    assert "probe_model = 'qwen3.6-ft'" in sql
    assert "WHERE node = 'proximal' AND slot_id = 0" in sql
    assert "qwen3.6-35b-a3b" in sql, "rollback capability must remain explicit"
    assert "gpu_slots" not in sql.split("UPDATE fleet_nodes", 1)[1].split("WHERE", 1)[0]
