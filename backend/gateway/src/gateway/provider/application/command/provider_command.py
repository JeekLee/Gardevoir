from pydantic import AnyHttpUrl, Field

from shared_kernel.api import CamelModel


class CreateProvider(CamelModel):
    name: str = Field(min_length=1, max_length=255)
    #: OpenAI 호환 base_url. AnyHttpUrl 이 형식을 검증한다(로컬 http://host:port/v1 도 통과).
    base_url: AnyHttpUrl
    #: 로컬 호스팅이면 비워둘 수 있다.
    api_key: str = ""
    models: list[str] = Field(min_length=1)


class UpdateProvider(CamelModel):
    name: str = Field(min_length=1, max_length=255)
    base_url: AnyHttpUrl
    api_key: str = ""
    models: list[str] = Field(min_length=1)
