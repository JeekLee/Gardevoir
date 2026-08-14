"""콘솔에 로그인하는 사람."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid7

from gateway.identity.domain.enums.role import Role
from gateway.identity.domain.exceptions.user_error import UserError
from gateway.identity.domain.models.password_hash import PasswordHash


def normalise_email(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    email: str
    name: str
    password_hash: PasswordHash
    role: Role = Role.USER
    deactivated_at: datetime | None = None

    @classmethod
    def register(cls, *, email: str, name: str, password: str, role: Role = Role.USER) -> User:
        return cls(
            id=uuid7(),
            email=normalise_email(email),
            name=name,
            password_hash=PasswordHash.of(password),
            role=role,
        )

    def update(self, *, email: str, name: str) -> User:
        self.ensure_active()
        return replace(self, email=normalise_email(email), name=name)

    def set_password(self, password: str) -> User:
        self.ensure_active()
        return replace(self, password_hash=PasswordHash.of(password))

    def change_role(self, role: Role) -> User:
        self.ensure_active()
        if self.role is role:
            return self
        return replace(self, role=role)

    def deactivate(self) -> User:
        if self.deactivated_at is not None:
            return self
        return replace(self, deactivated_at=datetime.now(UTC))

    def ensure_active(self) -> None:
        if self.deactivated_at is not None:
            UserError.DEACTIVATED.raise_(details={"id": str(self.id)})

    def ensure_admin(self) -> None:
        self.ensure_active()
        if self.role is not Role.ADMIN:
            UserError.NOT_ADMIN.raise_(details={"id": str(self.id), "role": str(self.role)})

    def authenticate(self, password: str) -> None:
        self.ensure_active()
        if not self.password_hash.matches(password):
            UserError.INVALID_CREDENTIALS.raise_()


__all__ = ["User", "normalise_email"]
