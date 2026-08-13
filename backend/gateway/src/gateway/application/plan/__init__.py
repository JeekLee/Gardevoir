"""Guardrail compilation and execution.

`service/` 가 아니라 별도 패키지인 이유: 컴파일러와 실행기는 유스케이스가 아니라
순수 변환이다. 서비스 클래스로 감싸면 상태 없는 함수에 DI 를 붙이는 셈이 된다.

여기 있는 코드는 **요청 경로**다. Pydantic 금지, 요청당 DB·네트워크 0회 (§11.8).
"""
