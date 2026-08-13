"""Checkpoint inspection — running a compiled plan against a real request.

``plan/`` 과 분리한 이유: ``plan/`` 은 와이어 포맷을 모르는 순수 변환이고, 여기는
**OpenAI 페이로드 모양**을 안다. 섞으면 컴파일러가 와이어 포맷에 묶인다.

요청 경로다. Pydantic 금지 (§11.8).
"""
