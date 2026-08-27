"""Stored graph migration for MODEL-dependent MASK verdicts."""

from pathlib import Path
from runpy import run_path

_MIGRATION = Path(__file__).parents[1] / (
    "alembic/postgres/versions/260827_block_model_mask_verdicts.py"
)
_migrate_graph = run_path(str(_MIGRATION))["_migrate_graph"]


def test_migration_blocks_only_mask_verdicts_reachable_from_model_checks() -> None:
    """MODEL 상류 MASK만 BLOCK으로 올리고 regex MASK와 다른 설정은 보존한다."""
    graph = {
        "metadata": {"owner": "default"},
        "nodes": [
            {"id": "extract", "type": "extract", "config": {"checkpoint": "input"}},
            {"id": "model", "type": "model", "config": {"policy": "민감정보인가?"}},
            {"id": "transform", "type": "transform", "config": {"op": "lower"}},
            {"id": "regex", "type": "regex", "config": {"pattern": "secret"}},
            {"id": "model-mask", "type": "verdict", "config": {"action": "mask"}},
            {"id": "model-block", "type": "verdict", "config": {"action": "block"}},
            {"id": "regex-mask", "type": "verdict", "config": {"action": "mask"}},
        ],
        "edges": [
            {"src": "extract", "dst": "model"},
            {"src": "model", "dst": "transform"},
            {"src": "transform", "dst": "model-mask"},
            {"src": "model", "dst": "model-block"},
            {"src": "extract", "dst": "regex"},
            {"src": "regex", "dst": "regex-mask"},
        ],
    }

    migrated = _migrate_graph(graph)
    actions = {
        node["id"]: node["config"]["action"]
        for node in migrated["nodes"]
        if node["type"] == "verdict"
    }

    assert actions == {
        "model-mask": "block",
        "model-block": "block",
        "regex-mask": "mask",
    }
    assert migrated["edges"] == graph["edges"]
    assert migrated["metadata"] == graph["metadata"]
