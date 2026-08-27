"""Rewrite MODEL-dependent MASK verdicts to BLOCK.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
"""

from collections import defaultdict, deque
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "e3f4a5b6c7d8"
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
    raise RuntimeError("MODEL-dependent MASK verdicts cannot be restored safely")


def _migrate_graph(graph: object) -> object:
    if not isinstance(graph, dict):
        return graph
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return graph

    nodes = [dict(node) if isinstance(node, dict) else node for node in raw_nodes]
    outputs: defaultdict[str, list[str]] = defaultdict(list)
    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        src = edge.get("src")
        dst = edge.get("dst")
        if isinstance(src, str) and isinstance(dst, str):
            outputs[src].append(dst)

    model_ids = [
        node.get("id")
        for node in nodes
        if isinstance(node, dict)
        and node.get("type") == "model"
        and isinstance(node.get("id"), str)
    ]
    model_descendants: set[str] = set()
    queue = deque(model_ids)
    while queue:
        node_id = queue.popleft()
        if node_id in model_descendants:
            continue
        model_descendants.add(node_id)
        queue.extend(outputs[node_id])

    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "verdict":
            continue
        if node.get("id") not in model_descendants:
            continue
        config = node.get("config")
        if not isinstance(config, dict) or config.get("action") != "mask":
            continue
        node["config"] = {**config, "action": "block"}

    return {**graph, "nodes": nodes}
