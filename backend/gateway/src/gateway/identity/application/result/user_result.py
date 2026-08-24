from datetime import datetime
from uuid import UUID

from shared_kernel.api import CamelModel
from shared_kernel.auth import Role


class UserSummary(CamelModel):
    id: UUID
    email: str
    name: str
    role: Role
    deactivated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TokenPair(CamelModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class LoginResult(CamelModel):
    tokens: TokenPair
    user: UserSummary
