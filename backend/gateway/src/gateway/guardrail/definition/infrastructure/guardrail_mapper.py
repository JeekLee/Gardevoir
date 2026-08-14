"""Guardrail domain <-> ORM mapping.

The graph's serialised shape belongs to the domain (``from_graph``/``to_graph``) —
the admin API needs the same conversion, and two parsers would drift. This module
only moves the surrounding columns.
"""

from gateway.guardrail.definition.infrastructure.guardrail_model import GuardrailModel
from gateway.guardrail.domain.guardrail import Guardrail


def to_domain(row: GuardrailModel) -> Guardrail:
    return Guardrail.from_graph(
        name=row.name,
        version=row.version,
        version_number=row.version_number,
        graph=row.graph or {},
    )


def to_model(guardrail: Guardrail, *, id: str) -> GuardrailModel:
    return GuardrailModel(
        id=id,
        name=guardrail.name,
        version=guardrail.version,
        version_number=guardrail.version_number,
        graph=guardrail.to_graph(),
    )
