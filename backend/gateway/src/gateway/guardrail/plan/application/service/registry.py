"""In-process plan registry with atomic swap (§6).

```
발행 → 백그라운드에서 [계획 v38] 컴파일   ← 이 동안 요청은 v37 로 계속 처리
     → 참조 대입으로 교체 (파이썬에서 원자적, 락 불필요)
```

**요청 하나는 시작할 때 잡은 계획을 끝까지 쓴다.** 입력을 v37, 출력을 v38 로 검사하면
판정이 앞뒤가 안 맞고 나중에 재현이 불가능하다. 그 규칙을 지키는 것은 호출자(2c)지만,
계획이 불변이어야 가능하므로 여기서 불변으로 만든다.

**폴링:** uvicorn 워커는 별도 프로세스라 한 워커의 발행이 다른 워커에 보이지 않는다.
§14 가 "``LISTEN/NOTIFY`` 는 후속, 폴링으로 시작"이라고 했다.
"""

import asyncio
import logging

from gateway.guardrail.plan.application.compiler import compile_guardrail
from gateway.guardrail.plan.application.port.guardrail_source import GuardrailSource
from gateway.guardrail.plan.domain.models.execution_plan import ExecutionPlan

logger = logging.getLogger(__name__)


class PlanRegistry:
    def __init__(self, *, source: GuardrailSource, poll_interval_s: float = 5.0) -> None:
        self._source = source
        self._poll_interval_s = poll_interval_s
        #: guardrail -> plan. 항목 대입은 GIL 아래에서 원자적이므로 락이 없다.
        self._plans: dict[str, ExecutionPlan] = {}
        self._task: asyncio.Task | None = None
        self.compiles = 0

    # -- 요청 경로 -----------------------------------------------------------

    def get(self, name: str) -> ExecutionPlan | None:
        """dict 조회 한 번. DB 도 네트워크도 없다 (§6)."""
        return self._plans.get(name)

    @property
    def loaded(self) -> frozenset[str]:
        return frozenset(self._plans)

    # -- 컴파일 --------------------------------------------------------------

    async def refresh(self, name: str) -> ExecutionPlan | None:
        versions = await self._source.latest_versions()
        version_number = versions.get(name)
        if version_number is None:
            return None
        return await self._compile_into(name, version_number)

    async def load_all(self) -> int:
        """기동 시 1회. §11.6 실측으로 50개 271 ms 였다."""
        versions = await self._source.latest_versions()
        loaded = 0
        for name, version_number in versions.items():
            if await self._compile_into(name, version_number) is not None:
                loaded += 1
        return loaded

    async def _compile_into(self, name: str, version_number: int) -> ExecutionPlan | None:
        current = self._plans.get(name)
        if current is not None and current.version_number == version_number:
            return current

        guardrail = await self._source.load_published(name, version_number)
        if guardrail is None:
            logger.warning("guardrail %r v%s vanished between read and load", name, version_number)
            return None

        try:
            plan = compile_guardrail(guardrail)
        except Exception:
            # 잘못된 발행 하나가 운영 중인 계획을 없애서는 안 된다. 이전 계획을 그대로
            # 두고 넘어간다 — 그러지 않으면 발행 실수가 가드레일 해제와 같아진다.
            logger.exception("compiling guardrail %r v%s failed", name, version_number)
            return None

        self.compiles += 1
        # 원자적 교체. 이미 계획을 잡고 있는 요청은 영향받지 않는다.
        self._plans[name] = plan
        logger.info(
            "guardrail %r compiled to v%s (%d instructions, checkpoints=%s)",
            name,
            version_number,
            plan.instruction_count,
            sorted(plan.checkpoints),
        )
        return plan

    # -- 폴러 ----------------------------------------------------------------

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _poll(self) -> None:
        """번호가 바뀐 가드레일만 다시 컴파일한다.

        예외로 루프가 죽으면 그 워커는 영원히 낡은 계획을 쓴다. 조용히 낡는 것이
        가장 나쁘므로 로그를 남기고 계속 돈다.
        """
        while True:
            await asyncio.sleep(self._poll_interval_s)
            try:
                for name, version_number in (await self._source.latest_versions()).items():
                    await self._compile_into(name, version_number)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("plan poll failed; keeping the current plans")
