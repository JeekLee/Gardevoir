from gateway.identity.domain.models.password_hash import PasswordHash
from gateway.identity.domain.models.user import User
from gateway.identity.infrastructure.user_model import UserModel
from shared_kernel.auth import Role


def to_domain(row: UserModel) -> User:
    return User(
        id=row.id,
        email=row.email,
        name=row.name,
        password_hash=PasswordHash(row.password_hash),
        role=Role(row.role),
        deactivated_at=row.deactivated_at,
    )


def to_model(user: User) -> UserModel:
    return UserModel(
        id=user.id,
        email=user.email,
        name=user.name,
        password_hash=user.password_hash.value,
        role=str(user.role),
        deactivated_at=user.deactivated_at,
    )
