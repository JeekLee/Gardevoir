"""Replace special tool-call nodes with the general source/check grammar.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a5b6c7d8e9f0"
down_revision: str | Sequence[str] | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    """Upgrade every stored draft and published guardrail graph."""
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
    raise RuntimeError("special tool-call nodes cannot be restored without data loss")


def _migrate_graph(graph: object) -> object:
    if not isinstance(graph, dict):
        return graph
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return graph

    used_ids = {
        node.get("id")
        for node in raw_nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    replacements: dict[str, str] = {}
    links: list[dict] = []
    nodes: list = []

    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            nodes.append(raw_node)
            continue
        node = dict(raw_node)
        node_id = node.get("id")
        node_type = node.get("type")
        if not isinstance(node_id, str) or node_type not in {
            "taint",
            "side_effect",
            "provenance",
        }:
            nodes.append(node)
            continue

        config = node.get("config")
        if not isinstance(config, dict):
            config = {}
        regex_id = _unique_id(f"{node_id}__regex", used_ids)
        used_ids.add(regex_id)
        replacements[node_id] = regex_id
        links.append({"src": node_id, "dst": regex_id})

        if node_type == "taint":
            source = {
                **node,
                "type": "extract",
                "config": {
                    "from": "tool_result",
                    "at": config.get("checkpoint", "tool_call"),
                },
            }
            pattern = "."
        elif node_type == "side_effect":
            read_only = config.get("read_only")
            if not isinstance(read_only, list) or not all(
                isinstance(name, str) for name in read_only
            ):
                logger.warning(
                    "side_effect node %r has invalid read_only; migrating to exclude=[]",
                    node_id,
                )
                read_only = []
            source = {
                **node,
                "type": "tool_extract",
                "config": {"tools": {"exclude": read_only}, "field": "name"},
            }
            pattern = "."
        else:
            # 실 DB에는 없지만 예상 밖 데이터로 배포를 멈추지 않는다.
            # 기존 provenance 입력을 항상 참으로 바꿔 차단을 넓히는 보수적 변환이다.
            logger.warning(
                "provenance node %r cannot be preserved; migrating it to an always-matching "
                "tool selector",
                node_id,
            )
            source = {
                **node,
                "type": "tool_extract",
                "config": {"tools": {"exclude": []}, "field": "name"},
            }
            pattern = "(?s).*"

        nodes.extend(
            [
                source,
                {"id": regex_id, "type": "regex", "config": {"pattern": pattern}},
            ]
        )

    edges: list = [*links]
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            edges.append(raw_edge)
            continue
        edge = dict(raw_edge)
        src = edge.get("src")
        if isinstance(src, str) and src in replacements:
            edge["src"] = replacements[src]
        edges.append(edge)

    return {**graph, "nodes": nodes, "edges": edges}


def _unique_id(candidate: str, used: set[object]) -> str:
    if candidate not in used:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in used:
        suffix += 1
    return f"{candidate}_{suffix}"
