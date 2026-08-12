"""ORM models.

**Every model must be re-exported here.** Base.metadata only knows about models
that have been imported, and Alembic autogenerate reads Base.metadata — a model
missing from this file is silently absent from migrations.
"""

from gateway.infrastructure.models.api_key import ApiKeyModel

__all__ = ["ApiKeyModel"]
