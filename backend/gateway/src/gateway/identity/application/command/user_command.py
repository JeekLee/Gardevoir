from pydantic import EmailStr, Field, SecretStr

from shared_kernel.api import CamelModel
from shared_kernel.auth import Role


class Login(CamelModel):
    email: EmailStr
    password: SecretStr


class Refresh(CamelModel):
    refresh_token: str


class CreateUser(CamelModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    password: SecretStr
    role: Role = Role.USER


class UpdateUser(CamelModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)


class ChangePassword(CamelModel):
    current_password: SecretStr
    new_password: SecretStr


class ChangeRole(CamelModel):
    role: Role
