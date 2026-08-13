"""Guardrail authoring commands.

``graph`` is a plain dict: the node schema lives in ``Node.validate()``, and a
second Pydantic copy of it would drift. Pydantic's job here is only to reject
payloads that are not objects at all.
"""

from shared_kernel.api import CamelModel


class CreateGuardrail(CamelModel):
    #: 슬러그 규칙은 도메인이 강제한다 (Guardrail.__post_init__). 여기서 pattern 을
    #: 겹쳐 두면 규칙이 두 곳에 생기고, CLI 는 그중 하나만 통과한다.
    name: str
    graph: dict


class UpdateDraft(CamelModel):
    graph: dict
