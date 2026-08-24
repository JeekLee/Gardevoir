FROM ghcr.io/astral-sh/uv:0.11.7 AS uv

FROM python:3.14-slim-bookworm

COPY --from=uv /uv /uvx /bin/

ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/backend

# 루트는 가상 워크스페이스이므로 두 멤버를 함께 설치해야 한다.
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages

RUN groupadd --system --gid 10001 gardevoir \
    && useradd --system --uid 10001 --gid gardevoir --no-create-home gardevoir

USER gardevoir
WORKDIR /app/backend/gateway

EXPOSE 21000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:21000/healthz', timeout=2)"]

CMD ["uvicorn", "--factory", "gateway.app:create_app", "--host", "0.0.0.0", "--port", "21000"]
