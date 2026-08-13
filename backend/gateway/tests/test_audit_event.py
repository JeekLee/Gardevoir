import dataclasses
import datetime as dt

import pytest

from gateway.application.audit.audit_event import AuditEvent, Checkpoint, new_event_id


def _event(**kw) -> AuditEvent:
    fields: dict = {
        "id": new_event_id(),
        "created_at": dt.datetime.now(dt.UTC).replace(tzinfo=None),
        "request_id": "req_1",
        "api_key_id": "k1",
        "app_name": "app_0",
        "guardrail": "base",
        "guardrail_version": 0,
        "mode": "enforce",
        "action": "allow",
        "checkpoint": Checkpoint.NONE,
        "checks_fired": (),
        "verdicts": "[]",
        "tier_reached": "",
        "tainted": False,
        "latency_ms": 0.62,
        "model": "gpt-4o",
        "prompt_tokens": 10,
        "completion_tokens": 5,
    }
    fields.update(kw)
    return AuditEvent(**fields)


def test_new_event_id_is_a_sortable_ulid():
    a, b = new_event_id(), new_event_id()
    assert len(a) == 26
    assert a != b
    assert sorted([b, a]) == [a, b] or a == b


def test_event_is_immutable():
    """감사 기록이 큐에 들어간 뒤 바뀌면 무엇이 저장됐는지 알 수 없다."""
    event = _event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.action = "blocked"  # type: ignore[misc]


def test_created_at_is_a_datetime_not_epoch_seconds():
    """§11.10: DateTime64(3) 에 unix 초를 넣으면 1970년에 조용히 저장된다."""
    assert isinstance(_event().created_at, dt.datetime)


def test_checks_fired_is_a_tuple():
    """가변 리스트면 큐에 들어간 뒤 호출자가 바꿀 수 있다."""
    assert isinstance(_event().checks_fired, tuple)


def test_checkpoint_values_match_the_design_document():
    assert Checkpoint.INPUT == "input"
    assert Checkpoint.TOOL_RESULT == "tool_result"
    assert Checkpoint.OUTPUT == "output"
    assert Checkpoint.TOOL_CALL == "tool_call"
    assert Checkpoint.NONE == ""


def test_audit_event_does_not_know_about_storage():
    """컬럼 순서·행 변환은 sink 가 소유한다. 저장소를 바꿔도 이벤트는 그대로다."""
    assert not hasattr(_event(), "to_row")
    field_names = {f.name for f in dataclasses.fields(AuditEvent)}
    assert "columns" not in field_names
