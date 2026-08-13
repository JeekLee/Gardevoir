"""Guardrail error catalog.

One enum line per error. No class per error (skills/gardevoir-be).
"""

from shared_kernel.exception import (
    ConflictError,
    ErrorCatalog,
    NotFoundError,
    ValidationError,
)


class GuardrailError(ErrorCatalog):
    NOT_FOUND = ("GUARDRAIL-001", "no such guardrail", NotFoundError)
    CYCLE = ("GUARDRAIL-002", "the graph contains a cycle", ValidationError)
    DANGLING_EDGE = ("GUARDRAIL-003", "an edge points at a missing node", ValidationError)
    DUPLICATE_NODE_ID = ("GUARDRAIL-004", "node ids must be unique", ValidationError)
    INVALID_NODE_CONFIG = ("GUARDRAIL-005", "a node's configuration is invalid", ValidationError)
    NAME_TAKEN = ("GUARDRAIL-006", "a guardrail with this name already exists", ConflictError)
    PUBLISHED_IS_IMMUTABLE = (
        "GUARDRAIL-007",
        "a published guardrail cannot be modified",
        ConflictError,
    )
    NO_DRAFT = ("GUARDRAIL-008", "this guardrail has no draft", NotFoundError)
    MALFORMED_GRAPH = (
        "GUARDRAIL-009",
        'the graph is not shaped like {"nodes": [...], "edges": [...]}',
        ValidationError,
    )
    INVALID_NAME = ("GUARDRAIL-010", "the guardrail name is not a valid slug", ValidationError)
    CONCURRENT_WRITE = (
        "GUARDRAIL-011",
        "another write to this guardrail won the race; retry",
        ConflictError,
    )
