# Централизованный конфиг бэкенда через pydantic-settings

Дата: 2026-07-16. Статус: утверждён.

## Проблема

Чтение окружения размазано по коду: `os.environ.get(...)` в `auth.py`,
`app.py`, `agents/base.py`. Нет единого места, где видно, какие переменные
вообще существуют. Пользователь путается и рано или поздно заведёт дубль.

Текущие точки чтения env (наш Python):

| Переменная | Где читается | Обяз. |
| --- | --- | --- |
| `DATABASE_URL` | `app.py` get_data_layer | да |
| `CHAINLIT_JWT_SECRET` | `auth.py` | да |
| `CHAINLIT_JWT_AUDIENCE` | `auth.py` | да |
| `CHAINLIT_JWT_ISSUER` | `auth.py` | да |
| `MODEL_PROVIDER` | `agents/base.py` | нет (default openrouter) |
| `OPENROUTER_MODEL` | `agents/base.py` | нет |
| `OPENROUTER_BASE_URL` | `agents/base.py` | нет |
| `OPENROUTER_API_KEY` | `agents/base.py` | только при openrouter |
| `OLLAMA_MODEL` | `agents/base.py` | нет |
| `OLLAMA_BASE_URL` | `agents/base.py` | нет |
| `TOAST_DATABASE_URL` | `app.py` get_toast_store | нет (фича-флаг) |
| `OAUTH_GENERIC_CLIENT_ID` | `app.py` (факт наличия) | нет |

Переменные, которые читает **сам Chainlit** (не наш Python), но которые
должны попасть в единый реестр: `CHAINLIT_AUTH_SECRET`, `CHAINLIT_URL`,
`OAUTH_GENERIC_CLIENT_SECRET`, `OAUTH_GENERIC_AUTH_URL`,
`OAUTH_GENERIC_TOKEN_URL`, `OAUTH_GENERIC_USER_INFO_URL`,
`OAUTH_GENERIC_SCOPES`, `OAUTH_GENERIC_USER_IDENTIFIER`.

## Решения обсуждения

| Вопрос | Решение |
| --- | --- |
| Scope | Всё в одном месте: Settings владеет переменными, которые читает наш Python; переменные, которые читает Chainlit, объявляются полями-документацией (passthrough) |
| Доступ | Ленивый `get_settings()` с `@lru_cache` — Settings строится при первом вызове, не при импорте |
| Структура | Плоский класс с секциями-комментариями (`settings.openrouter_model`) |
| Провайдер | `ModelProvider(str, Enum)` вместо `Literal` — в стиле существующего `Mode(Enum)` |

## Архитектура

Новый модуль `backend/config.py` — единственный источник правды о
переменных окружения. Потребители (`auth.py`, `app.py`, `agents/base.py`)
получают значения через `get_settings()`, а не через `os.environ`.
Значения по-прежнему приходят из окружения (compose) — модуль решает
задачу «какие переменные есть и какие обязательны», а не заменяет compose.

## Компоненты

### `backend/config.py` (новый)

Ниже — концептуальная структура класса (секции и типы). Точные
определения полей с `Field(validation_alias=...)` — в блоке после него;
он и является авторитетным. Правило: если имя переменной совпадает с
именем поля без учёта регистра (`chainlit_auth_secret` ←
`CHAINLIT_AUTH_SECRET`), alias не нужен; если отличается (`jwt_secret` ←
`CHAINLIT_JWT_SECRET`), нужен `validation_alias`.

```python
from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelProvider(str, Enum):
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"


class Settings(BaseSettings):
    """Единый реестр переменных окружения бэкенда.

    Поля, которые читает наш Python, — обязательные или с дефолтами.
    Поля с пометкой «читает Chainlit» существуют только для реестра:
    функционально их читает сам фреймворк из окружения.
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    # --- Chainlit data layer (читает app.py) ---
    database_url: str  # DATABASE_URL — обязателен

    # --- JWT-тикеты datacraft (читает auth.py) ---
    jwt_secret: str      # CHAINLIT_JWT_SECRET — обязателен
    jwt_audience: str    # CHAINLIT_JWT_AUDIENCE — обязателен
    jwt_issuer: str      # CHAINLIT_JWT_ISSUER — обязателен

    # --- Модель / провайдер (читает agents/base.py) ---
    model_provider: ModelProvider = ModelProvider.OPENROUTER
    openrouter_model: str = "anthropic/claude-haiku-4.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str | None = None  # обязателен ТОЛЬКО при openrouter
    ollama_model: str = "gemma3"
    ollama_base_url: str = "http://ollama:11434"

    # --- TOAST-таблицы (читает app.py; фича-флаг) ---
    toast_database_url: str | None = None

    # --- OAuth generic: CLIENT_ID читает app.py, остальное — Chainlit ---
    oauth_generic_client_id: str | None = None

    # --- Passthrough: читает сам Chainlit, здесь — для единого реестра ---
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

Авторитетные определения полей. Поля, где имя переменной отличается от
имени поля, используют `Field(validation_alias=...)`; passthrough-поля,
где имя совпадает (`chainlit_auth_secret` ← `CHAINLIT_AUTH_SECRET`),
alias не требуют:

```python
from pydantic import Field

    database_url: str = Field(validation_alias="DATABASE_URL")
    jwt_secret: str = Field(validation_alias="CHAINLIT_JWT_SECRET")
    jwt_audience: str = Field(validation_alias="CHAINLIT_JWT_AUDIENCE")
    jwt_issuer: str = Field(validation_alias="CHAINLIT_JWT_ISSUER")
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
    toast_database_url: str | None = Field(
        default=None, validation_alias="TOAST_DATABASE_URL"
    )
    oauth_generic_client_id: str | None = Field(
        default=None, validation_alias="OAUTH_GENERIC_CLIENT_ID"
    )
```

Passthrough-поля используют `validation_alias` с их env-именами
аналогично. Это делает соответствие поле↔переменная явным и единым.

### Потребители

**`auth.py`** — `verify_ticket` берёт значения из `get_settings()`:

```python
from config import get_settings


def verify_ticket(token: str) -> dict[str, str]:
    s = get_settings()
    payload = jwt.decode(
        token,
        s.jwt_secret,
        algorithms=["HS256"],
        audience=s.jwt_audience,
        issuer=s.jwt_issuer,
        options={"require": ["exp", "sub", "aud", "iss"]},
    )
    ...
```

**`agents/base.py`** — `build_model` использует enum и настройки;
gate ключа OpenRouter здесь, а не в глобальном валидаторе:

```python
from config import ModelProvider, get_settings


def build_model() -> BaseChatModel:
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

**`app.py`** — три точки:

```python
from config import get_settings

# get_data_layer:
    conninfo=get_settings().database_url,
# get_toast_store:
    dsn = get_settings().toast_database_url
# строка регистрации oauth:
if get_settings().oauth_generic_client_id:
    cl.oauth_callback(oauth_user)
```

## Обработка ошибок

- Отсутствует обязательное поле (`database_url` / JWT-тройка) →
  `pydantic.ValidationError` при первом `get_settings()` — fail-fast с
  понятным сообщением, какое поле пусто.
- `MODEL_PROVIDER` вне enum → `ValidationError` (ловит опечатку).
- `provider=openrouter` без `OPENROUTER_API_KEY` → `RuntimeError` в
  `build_model()` с явным текстом (не в глобальном валидаторе, чтобы не
  ронять потребителей, не касающихся модели).

## Тестирование

- **`backend/tests/conftest.py` (новый):** autouse-фикстура — выставляет
  baseline dev-env для 4 обязательных полей (`DATABASE_URL`,
  `CHAINLIT_JWT_SECRET/AUDIENCE/ISSUER`) и делает `get_settings.cache_clear()`
  до и после каждого теста. Убирает повторяющиеся `monkeypatch.setenv(JWT...)`
  из `test_auth`, `test_oauth`, `test_app_imports`.
- **`test_config.py` (новый):**
  - отсутствует обязательное поле → `ValidationError`;
  - дефолты применяются при пустом env;
  - `MODEL_PROVIDER="garbage"` → `ValidationError`;
  - `validation_alias` работает (`CHAINLIT_JWT_SECRET` → `jwt_secret`).
- **`test_agents.py::test_build_model_provider_switch`:** добавить
  `get_settings.cache_clear()` между сменами `MODEL_PROVIDER` (иначе вернётся
  закэшированный объект); проверить `RuntimeError` при openrouter без ключа.
- Существующие `test_auth`/`test_oauth`/`test_app_imports` — упростить за
  счёт conftest-фикстуры (убрать дублирующий setenv).

## Зависимость и упаковка

- `uv add pydantic-settings` (pydantic v2 уже приходит с Chainlit).
- `pyproject.toml`: `py-modules = ["app", "auth", "config"]`.

## Что НЕ делаем (YAGNI)

- Не трогаем `docker-compose.yml` — имена переменных те же.
- Не вводим вложенные группы настроек.
- Не переносим чтение passthrough-переменных из Chainlit в наш код —
  они остаются полями-документацией.
- Не вводим `.env`-файл загрузку (значения приходят из compose).
