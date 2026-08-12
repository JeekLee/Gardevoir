from shared_kernel.api import CamelModel, Page


class GuardrailSummary(CamelModel):
    guardrail_name: str
    guardrail_version: int


def test_serialises_to_camel_case():
    dto = GuardrailSummary(guardrail_name="doc-agent", guardrail_version=37)
    assert dto.model_dump(by_alias=True) == {
        "guardrailName": "doc-agent",
        "guardrailVersion": 37,
    }


def test_accepts_both_camel_and_snake_on_input():
    assert GuardrailSummary(guardrailName="a", guardrailVersion=1).guardrail_name == "a"
    assert GuardrailSummary(guardrail_name="b", guardrail_version=2).guardrail_name == "b"


def test_page_is_generic():
    page = Page[GuardrailSummary](
        items=[GuardrailSummary(guardrail_name="a", guardrail_version=1)], total=42
    )
    body = page.model_dump(by_alias=True)
    assert body["total"] == 42
    assert body["items"][0]["guardrailName"] == "a"


def test_from_attributes_allows_building_from_orm_like_objects():
    """DAO가 ORM 행이나 dataclass에서 결과 DTO를 만들 수 있어야 한다."""

    class Row:
        guardrail_name = "from-orm"
        guardrail_version = 9

    dto = GuardrailSummary.model_validate(Row())
    assert dto.guardrail_name == "from-orm"
    assert dto.guardrail_version == 9
