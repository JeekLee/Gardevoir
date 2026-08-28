"""Stored graph migration for the tool-call node redesign."""

import logging
from pathlib import Path
from runpy import run_path

from gateway.guardrail.application.compiler import compile_guardrail
from gateway.guardrail.application.service.inspector import Inspector
from gateway.guardrail.domain.models.guardrail import Guardrail, VerdictAction
from gateway.guardrail.domain.models.mode import Mode

_MIGRATION = Path(__file__).parents[1] / (
    "alembic/postgres/versions/260828_redesign_tool_call_nodes.py"
)
_migrate_graph = run_path(str(_MIGRATION))["_migrate_graph"]


def _call(name: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {"function": {"name": name, "arguments": "{}"}},
                    ]
                }
            }
        ]
    }


def test_migration_reconnects_taint_and_side_effect_through_regex() -> None:
    """특수 소스를 일반 Extract→Regex 문법으로 바꾸고 verdict 입력을 재연결한다."""
    graph = {
        "metadata": {"owner": "default"},
        "nodes": [
            {"id": "tainted", "type": "taint", "config": {"checkpoint": "tool_call"}},
            {
                "id": "side-effect",
                "type": "side_effect",
                "config": {"checkpoint": "tool_call", "read_only": ["read_file"]},
            },
            {
                "id": "block",
                "type": "verdict",
                "config": {"action": "block", "combine": "all"},
            },
        ],
        "edges": [
            {"src": "tainted", "dst": "block"},
            {"src": "side-effect", "dst": "block"},
        ],
    }

    migrated = _migrate_graph(graph)
    nodes = {node["id"]: node for node in migrated["nodes"]}

    assert nodes["tainted"] == {
        "id": "tainted",
        "type": "extract",
        "config": {"from": "tool_result", "at": "tool_call"},
    }
    assert nodes["tainted__regex"]["config"] == {"pattern": "."}
    assert nodes["side-effect"] == {
        "id": "side-effect",
        "type": "tool_extract",
        "config": {"tools": {"exclude": ["read_file"]}, "field": "name"},
    }
    assert nodes["side-effect__regex"]["config"] == {"pattern": "."}
    assert migrated["edges"] == [
        {"src": "tainted", "dst": "tainted__regex"},
        {"src": "side-effect", "dst": "side-effect__regex"},
        {"src": "tainted__regex", "dst": "block"},
        {"src": "side-effect__regex", "dst": "block"},
    ]
    assert migrated["metadata"] == graph["metadata"]


def test_migrated_default_policy_preserves_tool_call_decisions() -> None:
    """오염+부작용만 차단하고 read-only 또는 비오염 호출은 계속 허용한다."""
    graph = _migrate_graph(
        {
            "nodes": [
                {
                    "id": "tainted",
                    "type": "taint",
                    "config": {"checkpoint": "tool_call"},
                },
                {
                    "id": "side-effect",
                    "type": "side_effect",
                    "config": {"checkpoint": "tool_call", "read_only": ["read_file"]},
                },
                {
                    "id": "block",
                    "type": "verdict",
                    "config": {"action": "block", "combine": "all"},
                },
            ],
            "edges": [
                {"src": "tainted", "dst": "block"},
                {"src": "side-effect", "dst": "block"},
            ],
        }
    )
    guardrail = Guardrail.from_graph(
        name="default",
        version="5",
        version_number=5,
        description="",
        graph=graph,
    )
    guardrail.validate()
    plan = compile_guardrail(guardrail)
    inspector = Inspector(plans=None)  # type: ignore[arg-type]
    tainted = {"messages": [{"role": "tool", "content": "external"}]}
    clean = {"messages": [{"role": "user", "content": "send it"}]}

    assert (
        inspector.tool_call(plan, _call("send_email"), tainted, mode=Mode.ENFORCE).action
        is VerdictAction.BLOCK
    )
    assert (
        inspector.tool_call(plan, _call("read_file"), tainted, mode=Mode.ENFORCE).action
        is VerdictAction.ALLOW
    )
    assert (
        inspector.tool_call(plan, _call("send_email"), clean, mode=Mode.ENFORCE).action
        is VerdictAction.ALLOW
    )


def test_unexpected_provenance_migrates_conservatively_and_logs(
    caplog,
) -> None:
    """예상 밖 provenance는 배포를 막지 않고 항상 참인 안전측 조건으로 바꾼다."""
    graph = {
        "nodes": [
            {
                "id": "origin",
                "type": "provenance",
                "config": {"checkpoint": "tool_call", "min_length": 8},
            },
            {"id": "block", "type": "verdict", "config": {"action": "block"}},
        ],
        "edges": [{"src": "origin", "dst": "block"}],
    }

    with caplog.at_level(logging.WARNING):
        migrated = _migrate_graph(graph)

    nodes = {node["id"]: node for node in migrated["nodes"]}
    assert nodes["origin"]["type"] == "tool_extract"
    assert nodes["origin"]["config"] == {
        "tools": {"exclude": []},
        "field": "name",
    }
    assert nodes["origin__regex"]["config"] == {"pattern": "(?s).*"}
    assert "cannot be preserved" in caplog.text
