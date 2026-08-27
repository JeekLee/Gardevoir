"""Migrate all/length nodes to verdict combine and regex.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: str | Sequence[str] | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade stored guardrail graphs."""
    guardrails = sa.table(
        "guardrails",
        sa.column("id", sa.String()),
        sa.column("graph", postgresql.JSONB()),
    )
    connection = op.get_bind()
    rows = connection.execute(sa.select(guardrails.c.id, guardrails.c.graph)).mappings().all()
    for row in rows:
        migrated = _migrate_graph(row["graph"])
        if migrated != row["graph"]:
            connection.execute(
                guardrails.update().where(guardrails.c.id == row["id"]).values(graph=migrated)
            )


def downgrade() -> None:
    """Reject a lossy downgrade."""
    raise RuntimeError("node catalog role migration cannot be downgraded without data loss")


def _migrate_graph(graph: object) -> object:
    if not isinstance(graph, dict):
        return graph
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return graph

    nodes = [dict(node) for node in raw_nodes]
    edges = [dict(edge) for edge in raw_edges]
    all_ids = {
        node.get("id")
        for node in nodes
        if node.get("type") == "all" and isinstance(node.get("id"), str)
    }
    node_by_id = {node["id"]: node for node in nodes if isinstance(node.get("id"), str)}
    all_inputs = {
        node_id: [
            edge.get("src")
            for edge in edges
            if edge.get("dst") == node_id and isinstance(edge.get("src"), str)
        ]
        for node_id in all_ids
    }

    for node_id, inputs in all_inputs.items():
        if len(inputs) < 2:
            raise RuntimeError(f"all node {node_id!r} has fewer than two inputs")
        for edge in edges:
            if edge.get("src") != node_id:
                continue
            target = node_by_id.get(edge.get("dst"))
            if target is None or target.get("type") != "verdict":
                raise RuntimeError(f"all node {node_id!r} does not feed a verdict")
            config = dict(target.get("config") or {})
            config["combine"] = "all"
            target["config"] = config

    migrated_nodes = []
    for node in nodes:
        if node.get("id") in all_ids:
            continue
        if node.get("type") == "length":
            config = node.get("config")
            max_chars = config.get("max_chars") if isinstance(config, dict) else None
            if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
                raise RuntimeError(f"length node {node.get('id')!r} has invalid max_chars")
            node["type"] = "regex"
            node["config"] = {"pattern": f"(?s).{{{max_chars + 1},}}"}
        migrated_nodes.append(node)

    migrated_edges: list[dict] = []
    edge_keys: set[tuple[object, object]] = set()
    for edge in edges:
        src = edge.get("src")
        dst = edge.get("dst")
        if dst in all_ids:
            continue
        candidates = (
            ({"src": input_id, "dst": dst} for input_id in all_inputs[src])
            if src in all_ids
            else (edge,)
        )
        for candidate in candidates:
            key = (candidate.get("src"), candidate.get("dst"))
            if key in edge_keys:
                continue
            edge_keys.add(key)
            migrated_edges.append(candidate)

    return {**graph, "nodes": migrated_nodes, "edges": migrated_edges}
