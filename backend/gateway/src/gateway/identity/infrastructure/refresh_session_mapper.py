from gateway.identity.domain.models.refresh_session import RefreshSession
from gateway.identity.infrastructure.refresh_session_model import RefreshSessionModel


def to_domain(row: RefreshSessionModel) -> RefreshSession:
    return RefreshSession(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


def to_model(session: RefreshSession) -> RefreshSessionModel:
    return RefreshSessionModel(
        id=session.id,
        user_id=session.user_id,
        token_hash=session.token_hash,
        expires_at=session.expires_at,
        revoked_at=session.revoked_at,
    )
