"""What one checkpoint's inspection produced."""

from dataclasses import dataclass

from gateway.guardrail.domain.models.guardrail import VerdictAction

#: 가려진 자리에 넣는 문자열. 무엇이 지워졌는지 사용자가 알 수 있어야 한다 (§9).
MASK_PLACEHOLDER = "[개인정보 삭제됨]"

#: 규칙 티어까지만 돌았다는 표시. Phase 4 가 "model" 을 더한다.
TIER_RULES = "rules"
TIER_NONE = ""


@dataclass(frozen=True, slots=True)
class Inspection:
    """한 체크포인트의 결과.

    **도메인 어휘로 말한다** (``VerdictAction``). 와이어의 ``Action`` 으로 옮기는 것은
    proxy 의 일이다 — 핵심 도메인이 HTTP 계약을 알면 계약이 바뀔 때마다 도메인이 흔들린다.

    ``action`` 은 **적용된** 판정이다 — dry-run 에서는 언제나 ALLOW 이고, 규칙이 무엇을
    하려 했는지는 ``would_have`` 에 있다. 둘을 한 필드에 담으면 호출자가 dry-run 응답을
    차단으로 오해한다 (§7.3).
    """

    action: VerdictAction
    tier: str = TIER_NONE
    checks_fired: tuple[str, ...] = ()
    pending_model: tuple[str, ...] = ()
    #: 치환이 **실제로 일어났는지**. ``action is MASK`` 와 다르다 — 홀드백 밖에서
    #: 걸리면 판정은 MASK 인데 아무것도 못 가린다 (§9).
    masked: bool = False
    would_have: VerdictAction | None = None
    #: ④ 가 막은 이유 — 툴 이름과 인수 **이름**. 값은 담지 않는다 (§10).
    evidence: tuple[dict, ...] = ()

    @property
    def blocked(self) -> bool:
        return self.action is VerdictAction.BLOCK

    @property
    def ran(self) -> bool:
        """계획이 이 체크포인트를 실제로 검사했는지.

        검사하지 않은 것과 검사해서 통과한 것은 다르다 — 전자는 호출자에게 알려야
        한다 (§7.3 의 ``inspected``).
        """
        return self.tier != TIER_NONE


NOT_INSPECTED = Inspection(action=VerdictAction.ALLOW)
