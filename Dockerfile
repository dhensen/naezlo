# The backend image: FastAPI + Alembic. The frontend is not in it; production serves the
# single-page app from a Cloudflare Worker (deploy/app-worker) that proxies the backend paths here.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /uvx /bin/

# Dependencies first, so a source change does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY README.md alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN uv sync --frozen

RUN useradd --system --no-create-home app
USER app

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

CMD ["uvicorn", "naezlo.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
