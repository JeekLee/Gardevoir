"""Gateway-wide contract surface.

여기 있는 것은 **계약 버전** 하나뿐이다. §7.2 가 버전을 URL 접두어로 두기로 했다 —
헤더를 따로 두면 호출처가 관리해야 하는데 그건 쓸모없는 부담이다.

라우터 셋(identity·guardrail·proxy)이 전부 이 접두어 아래 붙으므로 특정 컨텍스트의
소유가 아니다. `/v1/chat/completions` 의 와이어 계약(헤더·확장 객체·차단 본문)은
proxy/contract.py 에 있다.
"""

API_PREFIX = "/v1"

__all__ = ["API_PREFIX"]
