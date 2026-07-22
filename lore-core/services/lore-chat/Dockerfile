FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Venv живёт вне /app, чтобы bind-mount исходников (прогон тестов) его не прятал.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Build context is the uv workspace root (lore-core/): the chat depends on the
# workspace packages lore-audit-core / lore-audit-api, so the whole workspace
# (lockfile + members) must be visible to `uv sync`.
WORKDIR /workspace

# Сначала только манифесты — слой зависимостей кэшируется отдельно от исходников.
COPY pyproject.toml uv.lock ./
COPY packages/lore-core-domain/pyproject.toml packages/lore-core-domain/pyproject.toml
COPY packages/lore-audit-core/pyproject.toml packages/lore-audit-core/pyproject.toml
COPY packages/lore-retrieval/pyproject.toml packages/lore-retrieval/pyproject.toml
COPY services/lore-audit-api/pyproject.toml services/lore-audit-api/pyproject.toml
COPY services/lore-chat/pyproject.toml services/lore-chat/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --package datacraft-chainlit

# Теперь исходники всех задействованных членов воркспейса.
COPY packages/lore-core-domain packages/lore-core-domain
COPY packages/lore-audit-core packages/lore-audit-core
COPY packages/lore-retrieval packages/lore-retrieval
COPY services/lore-audit-api services/lore-audit-api
COPY services/lore-chat services/lore-chat
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package datacraft-chainlit

# chainlit ищет app.py + config.py в рабочем каталоге (pyproject pythonpath=["."]).
WORKDIR /workspace/services/lore-chat

EXPOSE 8000
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
