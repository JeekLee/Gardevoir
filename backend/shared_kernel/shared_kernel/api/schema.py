"""Wire DTO base.

camelCase on the wire, snake_case in Python. Applies to DTOs that cross the HTTP
boundary.

It must NOT be used for types on the request evaluation path — Pydantic
validation there would cost more than the entire per-request guardrail budget
of 0.63 ms (§11.8).
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class Page[T](CamelModel):
    items: list[T]
    total: int
