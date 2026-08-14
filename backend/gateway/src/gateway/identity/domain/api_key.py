"""ApiKey aggregate.

Persistence-ignorant: no SQLAlchemy, no FastAPI, no httpx.

Guardrail resolution lives here because "a request can never escape the key's
allowed set" is a business rule, independent of how the key is stored or how the
request arrived (§5, §7.2). Putting it in a router or a repository would
duplicate it.
"""

import hashlib
import secrets
from dataclasses import dataclass, field
from enum import StrEnum

from gateway.identity.domain.api_key_error import ApiKeyError

KEY_PREFIX = "gdv_live_"

_TOKEN_BYTES = 32


class Scope(StrEnum):
    """What a credential is allowed to reach.

    인가는 토폴로지가 아니라 크레덴셜에서 온다 (§7.2, §12). Admin 표면을 별도
    배포로 떼어 네트워크로 막는 대신 스코프로 막는다.
    """

    PROXY = "proxy"
    ADMIN = "admin"


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def hash_key(raw: str) -> str:
    """Hash a key for storage and cache lookup.

    An API key is high-entropy random, so a fast hash is the right choice.
    bcrypt/argon2 exist for low-entropy human passwords and would be far too
    slow on a path that runs for every request.
    """
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


@dataclass(frozen=True, slots=True)
class ApiKey:
    id: str
    name: str
    key_hash: str
    upstream_base_url: str
    upstream_api_key: str
    allowed_guardrails: tuple[str, ...]
    default_guardrail: str | None
    disabled: bool = False
    #: 기본값을 안전한 쪽으로 둔다 — 스코프가 명시되지 않은 키는 admin 에
    #: 접근할 수 없다.
    scopes: tuple[Scope, ...] = field(default=(Scope.PROXY,))

    def has_scope(self, scope: Scope) -> bool:
        return scope in self.scopes

    def require_scope(self, scope: Scope) -> None:
        if not self.has_scope(scope):
            ApiKeyError.SCOPE_NOT_GRANTED.raise_(
                details={"required": str(scope), "granted": [str(s) for s in self.scopes]}
            )

    def resolve_guardrail(self, requested: str | None) -> str:
        """Resolve the effective guardrail, never escaping the allowed set."""
        if requested:
            if requested not in self.allowed_guardrails:
                ApiKeyError.GUARDRAIL_NOT_ALLOWED.raise_(
                    details={
                        "requested": requested,
                        "allowed": list(self.allowed_guardrails),
                    }
                )
            return requested
        if self.default_guardrail:
            return self.default_guardrail
        if self.allowed_guardrails:
            return self.allowed_guardrails[0]
        ApiKeyError.NO_GUARDRAIL_CONFIGURED.raise_(details={"key_id": self.id})
