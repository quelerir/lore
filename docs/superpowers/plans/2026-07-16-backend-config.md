# Централизованный конфиг бэкенда Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать чтение переменных окружения бэкенда в один модуль `backend/config.py` на pydantic-settings — единый реестр переменных с валидацией и приоритетом env-файлов.

**Architecture:** Плоский `Settings(BaseSettings)` + `ModelProvider(str, Enum)` + ленивый `get_settings()` с `@lru_cache`. Потребители (`auth.py`, `agents/base.py`, `app.py`) читают через `get_settings()` вместо `os.environ`. Значения приходят из окружения (compose) и опциональных файлов `.env`/`.env.local`.

**Tech Stack:** Python 3.13, uv, pydantic v2, pydantic-settings, pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-backend-config-design.md`

## Global Constraints

- Рабочая директория для команд: `backend/`. Тесты: `cd backend && uv run pytest ...`.
- Комментарии и docstrings — по-русски, в стиле существующего кода.
- Обязательны без дефолта только 4 поля: `database_url`, `jwt_secret`, `jwt_audience`, `jwt_issuer`.
- Соответствие поле↔переменная через `Field(validation_alias="ENV_NAME")`, если имена отличаются; passthrough-поля с совпадающими именами — без alias.
- Gate `OPENROUTER_API_KEY` — внутри `build_model()`, не в глобальном валидаторе.
- Приоритет источников (высший→низший): OS env (compose) → `.env.local` → `.env`. В коде `env_file=(".env", ".env.local")` — побеждает последний.
- `ModelProvider(str, Enum)`: `OPENROUTER = "openrouter"`, `OLLAMA = "ollama"`.
- После каждой задачи весь набор тестов зелёный: `cd backend && uv run pytest`.

---

### Task 1: Модуль config.py и зависимость

Ядро конфигурации: enum, Settings, ленивый геттер. Плюс новый тест-набор и conftest, т.к. без них существующие тесты сломаются на первом же потребителе.

**Files:**
- Create: `backend/config.py`
- Create: `backend/tests/test_config.py`
- Create: `backend/tests/conftest.py`
- Modify: `backend/pyproject.toml` (dependency + py-modules)
- Create: `backend/.gitignore` (`.env.local`)

**Interfaces:**
- Produces: `ModelProvider(str, Enum)` с членами `OPENROUTER`, `OLLAMA`; класс `Settings(BaseSettings)` с полями по спеке; `get_settings() -> Settings` с `@lru_cache` (у неё есть `.cache_clear()`).

- [ ] **Step 1: Установить pydantic-settings**

Run: `cd backend && uv add pydantic-settings`
Expected: `pyproject.toml` и `uv.lock` обновлены без ошибок.

- [ ] **Step 2: Прописать модуль в упаковку**

В `backend/pyproject.toml`:

```toml
[tool.setuptools]
py-modules = ["app", "auth", "config"]
packages = ["agents", "toast"]
```

- [ ] **Step 3: Написать падающие тесты config**

Создать `backend/tests/test_config.py`:

```python
import pytest
from pydantic import ValidationError

from config import ModelProvider, Settings

# Полный набор env для конструирования Settings без файлов.
BASE = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
    "CHAINLIT_JWT_SECRET": "secret",
    "CHAINLIT_JWT_AUDIENCE": "chainlit",
    "CHAINLIT_JWT_ISSUER": "datacraft",
}


def test_required_fields_present(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.database_url.endswith("/db")
    assert s.jwt_secret == "secret"
    assert s.jwt_audience == "chainlit"
    assert s.jwt_issuer == "datacraft"


def test_missing_required_raises(monkeypatch):
    for k in BASE:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_defaults_applied(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.model_provider is ModelProvider.OPENROUTER
    assert s.openrouter_model == "anthropic/claude-haiku-4.5"
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert s.openrouter_api_key is None
    assert s.ollama_model == "gemma3"
    assert s.ollama_base_url == "http://ollama:11434"
    assert s.toast_database_url is None


def test_bad_provider_rejected(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MODEL_PROVIDER", "garbage")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_validation_alias_maps_env(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-123")
    s = Settings(_env_file=None)
    assert s.model_provider is ModelProvider.OLLAMA
    assert s.openrouter_api_key == "key-123"
```

- [ ] **Step 4: Убедиться, что тесты падают**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 5: Реализовать config.py**

Создать `backend/config.py`:

```python
"""Единый реестр переменных окружения бэкенда.

Поля, которые читает наш Python, — обязательные или с дефолтами. Поля с
пометкой «читает Chainlit» существуют только для реестра: функционально их
читает сам фреймворк из окружения. Значения берутся из окружения (compose)
и опциональных файлов .env / .env.local (см. приоритет ниже).
"""

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelProvider(str, Enum):
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        # Порядок приоритета файлов (побеждает последний): .env → .env.local.
        # Реальные переменные окружения (compose) важнее любого файла.
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
    )

    # --- Chainlit data layer (читает app.py) ---
    database_url: str = Field(validation_alias="DATABASE_URL")

    # --- JWT-тикеты datacraft (читает auth.py) ---
    jwt_secret: str = Field(validation_alias="CHAINLIT_JWT_SECRET")
    jwt_audience: str = Field(validation_alias="CHAINLIT_JWT_AUDIENCE")
    jwt_issuer: str = Field(validation_alias="CHAINLIT_JWT_ISSUER")

    # --- Модель / провайдер (читает agents/base.py) ---
    model_provider: ModelProvider = Field(
        default=ModelProvider.OPENROUTER, validation_alias="MODEL_PROVIDER"
    )
    openrouter_model: str = Field(
        default="anthropic/claude-haiku-4.5", validation_alias="OPENROUTER_MODEL"
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias="OPENROUTER_BASE_URL",
    )
    openrouter_api_key: str | None = Field(
        default=None, validation_alias="OPENROUTER_API_KEY"
    )
    ollama_model: str = Field(default="gemma3", validation_alias="OLLAMA_MODEL")
    ollama_base_url: str = Field(
        default="http://ollama:11434", validation_alias="OLLAMA_BASE_URL"
    )

    # --- TOAST-таблицы (читает app.py; фича-флаг) ---
    toast_database_url: str | None = Field(
        default=None, validation_alias="TOAST_DATABASE_URL"
    )

    # --- OAuth generic: CLIENT_ID читает app.py, остальное — Chainlit ---
    oauth_generic_client_id: str | None = Field(
        default=None, validation_alias="OAUTH_GENERIC_CLIENT_ID"
    )

    # --- Passthrough: читает сам Chainlit, здесь — для единого реестра.
    # Имена полей совпадают с env (без учёта регистра), alias не нужен. ---
    chainlit_auth_secret: str | None = None
    chainlit_url: str | None = None
    oauth_generic_client_secret: str | None = None
    oauth_generic_auth_url: str | None = None
    oauth_generic_token_url: str | None = None
    oauth_generic_user_info_url: str | None = None
    oauth_generic_scopes: str | None = None
    oauth_generic_user_identifier: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 6: Создать conftest с baseline-env**

Создать `backend/tests/conftest.py`:

```python
"""Общие фикстуры тестов бэкенда.

baseline-env даёт 4 обязательных поля Settings, чтобы любой потребитель
get_settings() конструировался. Загрузка env-файлов отключается, чтобы
тесты не зависели от локального .env.local разработчика. Кэш get_settings
чистится вокруг каждого теста.
"""

import pytest

import config

_BASELINE = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
    "CHAINLIT_JWT_SECRET": "test-secret-that-is-32-bytes-long!!",
    "CHAINLIT_JWT_AUDIENCE": "chainlit",
    "CHAINLIT_JWT_ISSUER": "datacraft",
}


@pytest.fixture(autouse=True)
def _config_env(monkeypatch):
    # Не читать файлы .env/.env.local в тестах.
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    for k, v in _BASELINE.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()
```

- [ ] **Step 7: Убедиться, что тесты config проходят**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: PASS (5 тестов)

Run: `cd backend && uv run pytest`
Expected: PASS (существующие тесты пока не трогали потребителей — остаются зелёными)

- [ ] **Step 8: Игнорировать .env.local**

Создать `backend/.gitignore`:

```gitignore
.env.local
```

- [ ] **Step 9: Commit**

```bash
git add backend/config.py backend/tests/test_config.py backend/tests/conftest.py backend/pyproject.toml backend/uv.lock backend/.gitignore
git commit -m "feat(config): pydantic-settings registry with lazy get_settings and env-file priority"
```

---

### Task 2: auth.py читает настройки

**Files:**
- Modify: `backend/auth.py`
- Modify: `backend/tests/test_auth.py`

**Interfaces:**
- Consumes: `config.get_settings()` → `s.jwt_secret`, `s.jwt_audience`, `s.jwt_issuer`.

- [ ] **Step 1: Упростить тест под conftest**

В `backend/tests/test_auth.py` удалить локальную autouse-фикстуру `_env`
(baseline теперь в conftest; секрет из conftest совпадает по длине). Заменить
константу `SECRET` на значение из conftest и убрать блок фикстуры:

```python
import time
import jwt
import pytest
import auth

SECRET = "test-secret-that-is-32-bytes-long!!"


def _token(**over):
    payload = {
        "sub": "42",
        "username": "alice",
        "aud": "chainlit",
        "iss": "datacraft",
        "exp": int(time.time()) + 60,
    }
    payload.update(over)
    return jwt.encode(payload, SECRET, algorithm="HS256")
```

(тела тестов `test_valid_ticket_returns_sub_and_username` и далее — без
изменений; фикстура `_env` удалена целиком.)

- [ ] **Step 2: Проверить, что тесты зелёные на conftest-env**

Это рефакторинг (поведение не меняется), поэтому шаг проверяет, что после
удаления локальной фикстуры baseline из conftest покрывает JWT-env.

Run: `cd backend && uv run pytest tests/test_auth.py -v`
Expected: PASS (5 тестов) — `verify_ticket` ещё читает `os.environ`, но conftest
выставил те же значения. Дальше переводим auth на единый источник.

- [ ] **Step 3: Переписать auth.py на get_settings**

Заменить содержимое `backend/auth.py`:

```python
import jwt

from config import get_settings


def verify_ticket(token: str) -> dict[str, str]:
    """Validate a datacraft-issued HS256 ticket, return {sub, username}.

    Raises jwt.InvalidTokenError (or subclass) on any validation failure.
    """
    s = get_settings()
    payload = jwt.decode(
        token,
        s.jwt_secret,
        algorithms=["HS256"],
        audience=s.jwt_audience,
        issuer=s.jwt_issuer,
        options={"require": ["exp", "sub", "aud", "iss"]},
    )
    return {
        "sub": str(payload["sub"]),
        "username": str(payload.get("username", payload["sub"])),
    }
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_auth.py -v`
Expected: PASS (5 тестов)

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/auth.py backend/tests/test_auth.py
git commit -m "refactor(auth): read JWT config via get_settings"
```

---

### Task 3: agents/base.py — enum-провайдер и gate ключа

**Files:**
- Modify: `backend/agents/base.py`
- Modify: `backend/tests/test_agents.py`

**Interfaces:**
- Consumes: `config.get_settings()`, `config.ModelProvider`.
- Produces: `build_model() -> BaseChatModel` — `ChatOllama` при `ModelProvider.OLLAMA`, иначе `ChatOpenAI`; `RuntimeError` при openrouter без ключа.

- [ ] **Step 1: Обновить тест провайдера под кэш и gate**

В `backend/tests/test_agents.py` заменить `test_build_model_provider_switch`:

```python
def test_build_model_provider_switch(monkeypatch):
    from langchain_ollama import ChatOllama
    from langchain_openai import ChatOpenAI

    from agents.base import build_model
    from config import get_settings

    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_settings.cache_clear()
    model = build_model()
    assert isinstance(model, ChatOpenAI)
    assert "openrouter.ai" in str(model.openai_api_base)

    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    get_settings.cache_clear()
    assert isinstance(build_model(), ChatOllama)


def test_build_model_openrouter_requires_key(monkeypatch):
    import pytest

    from agents.base import build_model
    from config import get_settings

    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        build_model()
```

- [ ] **Step 2: Запустить — падает на старом base**

Run: `cd backend && uv run pytest tests/test_agents.py::test_build_model_openrouter_requires_key -v`
Expected: FAIL — старый `build_model` делает `os.environ["OPENROUTER_API_KEY"]` → `KeyError`, а не `RuntimeError`.

- [ ] **Step 3: Переписать build_model**

В `backend/agents/base.py` заменить импорты и `build_model` (блок `import os` больше не нужен):

```python
from enum import Enum

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from config import ModelProvider, get_settings


class Mode(Enum):
    FAST = "fast"
    DEEP = "deep"


PROFILE_TO_MODE: dict[str, Mode] = {"fast": Mode.FAST, "deep": Mode.DEEP}


def build_model() -> BaseChatModel:
    """OpenRouter по умолчанию; MODEL_PROVIDER=ollama — локальный фолбэк."""
    s = get_settings()
    if s.model_provider is ModelProvider.OLLAMA:
        return ChatOllama(model=s.ollama_model, base_url=s.ollama_base_url)
    if not s.openrouter_api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY обязателен при MODEL_PROVIDER=openrouter"
        )
    return ChatOpenAI(
        model=s.openrouter_model,
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
    )
```

(Промпты `SYSTEM_PROMPT`, `DEEP_PROMPT` ниже в файле — без изменений.)

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_agents.py -v`
Expected: PASS

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/base.py backend/tests/test_agents.py
git commit -m "refactor(agents): build_model via get_settings + ModelProvider enum, key gate"
```

---

### Task 4: app.py — три точки чтения через настройки

**Files:**
- Modify: `backend/app.py`
- Modify: `backend/tests/test_app_imports.py`
- Modify: `backend/tests/test_oauth.py`

**Interfaces:**
- Consumes: `config.get_settings()` → `s.database_url`, `s.toast_database_url`, `s.oauth_generic_client_id`.

- [ ] **Step 1: Упростить тесты импорта под conftest**

В `backend/tests/test_app_imports.py` убрать дублирующий env (conftest даёт baseline):

```python
import importlib


def test_app_imports():
    app = importlib.import_module("app")
    assert hasattr(app, "handle_message")
```

В `backend/tests/test_oauth.py` убрать локальный env-хелпер:

```python
import asyncio
import importlib

import chainlit as cl


def _app():
    return importlib.import_module("app")


def test_oauth_user_maps_authentik_userinfo():
    app = _app()
    default = cl.User(identifier="alice")
    raw = {
        "sub": "alice",
        "preferred_username": "alice",
        "email": "alice@example.com",
        "name": "Alice Doe",
    }
    user = asyncio.run(app.oauth_user("generic", "token", raw, default))
    assert user is not None
    assert user.identifier == "alice"
    assert user.metadata["provider"] == "authentik"
    assert user.metadata["email"] == "alice@example.com"
    assert user.metadata["name"] == "Alice Doe"


def test_oauth_user_falls_back_to_default_identifier():
    app = _app()
    default = cl.User(identifier="fallback-id")
    user = asyncio.run(app.oauth_user("generic", "token", {}, default))
    assert user is not None
    assert user.identifier == "fallback-id"
```

- [ ] **Step 2: Проверить, что тесты зелёные на conftest-env**

Рефакторинг без смены поведения: baseline из conftest даёт `DATABASE_URL`,
а `oauth_generic_client_id` по умолчанию `None`, поэтому oauth-провайдер не
регистрируется — как и раньше.

Run: `cd backend && uv run pytest tests/test_app_imports.py tests/test_oauth.py -v`
Expected: PASS. Дальше переводим app на единый источник.

- [ ] **Step 3: Перевести app.py на get_settings**

В `backend/app.py`:

Заменить импорт:

```python
from config import get_settings
```

(строку `import os` оставить только если `os` используется ещё где-то; после
правок ниже `os` в app.py больше не нужен — удалить `import os`.)

В `get_data_layer`:

```python
@cl.data_layer
def get_data_layer() -> _NullPoolSQLAlchemyDataLayer:
    return _NullPoolSQLAlchemyDataLayer(
        conninfo=get_settings().database_url,
    )
```

В `get_toast_store`:

```python
def get_toast_store() -> Optional[PgToastStore]:
    """Ленивый синглтон подключения к TOAST-таблицам loreagent_test.

    Без TOAST_DATABASE_URL сервис работает как раньше (только calculator).
    """
    global _toast_store
    dsn = get_settings().toast_database_url
    if not dsn:
        return None
    if _toast_store is None:
        _toast_store = PgToastStore(dsn)
    return _toast_store
```

Строку регистрации oauth-провайдера:

```python
if get_settings().oauth_generic_client_id:
    cl.oauth_callback(oauth_user)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest`
Expected: PASS (все, включая app-импорты и oauth)

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/tests/test_app_imports.py backend/tests/test_oauth.py
git commit -m "refactor(app): data layer, toast store and oauth flag via get_settings"
```

---

### Task 5: Финальная проверка отсутствия прямого os.environ

Гарантия, что в рантайм-коде не осталось прямого чтения окружения (единый источник правды).

**Files:**
- Modify: (по результату — любой оставшийся потребитель)

- [ ] **Step 1: Найти оставшиеся чтения env в рантайме**

Run:
```bash
cd backend && grep -rn "os\.environ\|os\.getenv" --include="*.py" . | grep -v __pycache__ | grep -v "/tests/"
```
Expected: пусто. Тестовый `test_toast_store.py` читает `TOAST_DATABASE_URL`
через `os.environ` для skip-условия — это допустимо (гейт запуска теста, не
рантайм). Если в рантайм-коде что-то осталось — перевести на `get_settings()`
тем же приёмом и дописать поле в `Settings`, если его не было.

- [ ] **Step 2: Полный прогон и линтер**

Run: `cd backend && uv run pytest`
Expected: PASS (все тесты + config)

Run: `cd backend && uv run ruff check .`
Expected: All checks passed!

- [ ] **Step 3: Commit (если были правки)**

```bash
git add -A
git commit -m "chore(config): ensure no direct os.environ reads remain in runtime code"
```

Если правок на шаге 1 не потребовалось — задача закрывается без коммита.

---

## Верификация плана целиком

1. `cd backend && uv run pytest` — все тесты зелёные, включая `test_config.py`.
2. `grep -rn "os\.environ" backend --include="*.py" | grep -v tests | grep -v __pycache__` — пусто.
3. Ручная проверка: `MODEL_PROVIDER=openrouter` без ключа → понятный `RuntimeError`; `MODEL_PROVIDER=garbage` → `ValidationError` при старте.
4. `docker compose config -q` — конфиг валиден (имена переменных не менялись).
