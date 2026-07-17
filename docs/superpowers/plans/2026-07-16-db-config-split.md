# Разбивка DSN обеих БД на компоненты Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Хранить подключения к БД компонентами (host/port/user/password/name), а DSN собирать одним хелпером `build_dsn` в `config.py`.

**Architecture:** `Settings` заменяет цельные `database_url`/`toast_database_url` на компоненты `CHAINLIT_DB_*`/`TOAST_DB_*`; `database_url` и `toast_dsn` становятся вычисляемыми свойствами. Chainlit → схема `postgresql+asyncpg`, Toast → `postgresql`. Потребители (app.py, compose, eval, тесты) переводятся на компоненты.

**Tech Stack:** Python 3.13, pydantic-settings, pytest, docker compose.

**Spec:** `docs/superpowers/specs/2026-07-16-db-config-split-design.md`

## Global Constraints

- Рабочая директория: `backend/`. Тесты: `cd backend && uv run pytest`.
- Комментарии/докстринги — по-русски, в стиле кода.
- Две схемы DSN: Chainlit data-layer → `postgresql+asyncpg://…`; Toast asyncpg → `postgresql://…`.
- Логин/пароль в DSN экранируются через `urllib.parse.quote`.
- Chainlit-компоненты обязательны (кроме порта, дефолт 5432); Toast-компоненты опциональны (фича-флаг, `toast_dsn is None` при неполном наборе).
- Env-имена: `CHAINLIT_DB_HOST/PORT/USER/PASSWORD/NAME`, `TOAST_DB_HOST/PORT/USER/PASSWORD/NAME`.
- После каждой задачи `cd backend && uv run pytest` зелёный.

---

### Task 1: build_dsn + компоненты в Settings

**Files:**
- Modify: `backend/config.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces: `build_dsn(scheme: str, user: str, password: str, host: str, port: int, name: str) -> str`; `Settings.database_url` (property → `postgresql+asyncpg://…`); `Settings.toast_dsn` (property → `postgresql://…` | None); поля `chainlit_db_host/user/password/name`, `chainlit_db_port`, `toast_db_host/user/password/name`, `toast_db_port`.

- [ ] **Step 1: Обновить тесты конфига**

В `backend/tests/test_config.py` заменить словарь `BASE` и связанные тесты.
Заменить строку `BASE = {...}` (сейчас с `DATABASE_URL`) на компоненты:

```python
BASE = {
    "CHAINLIT_DB_HOST": "localhost",
    "CHAINLIT_DB_USER": "u",
    "CHAINLIT_DB_PASSWORD": "p",
    "CHAINLIT_DB_NAME": "db",
    "CHAINLIT_JWT_SECRET": "secret",
    "CHAINLIT_JWT_AUDIENCE": "chainlit",
    "CHAINLIT_JWT_ISSUER": "datacraft",
}
```

Точечные правки:

1. Заменить тело `test_required_fields_present` (проверял `database_url.endswith`)
   на проверку собранного DSN:

```python
def test_required_fields_present(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://u:p@localhost:5432/db"
    assert s.jwt_secret == "secret"
```

2. В `test_defaults_applied` заменить ТОЛЬКО строку
   `assert s.toast_database_url is None` на `assert s.toast_dsn is None`
   (остальные проверки дефолтов модели/ollama оставить как есть).

3. Добавить два новых теста (сборка Toast-DSN и экранирование):

```python
def test_toast_dsn_assembled(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("TOAST_DB_HOST", "th")
    monkeypatch.setenv("TOAST_DB_USER", "tu")
    monkeypatch.setenv("TOAST_DB_PASSWORD", "tp")
    monkeypatch.setenv("TOAST_DB_NAME", "tn")
    s = Settings(_env_file=None)
    assert s.toast_dsn == "postgresql://tu:tp@th:5432/tn"


def test_password_url_escaped(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CHAINLIT_DB_PASSWORD", "p@ss/w:rd")
    s = Settings(_env_file=None)
    assert "p%40ss%2Fw%3Ard" in s.database_url
```

`test_missing_required_raises` оставить как есть — он удаляет ключи `BASE`
(теперь Chainlit-компоненты) и ждёт `ValidationError`, проверка сохраняется.

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: FAIL — нет `build_dsn`/компонентов/свойств (`AttributeError`/`ValidationError`).

- [ ] **Step 3: Реализовать в config.py**

В `backend/config.py` добавить импорт и хелпер (после существующих импортов):

```python
from urllib.parse import quote
```

```python
def build_dsn(scheme: str, user: str, password: str,
              host: str, port: int, name: str) -> str:
    """Собрать DSN, экранируя логин и пароль (спецсимволы в URL)."""
    return f"{scheme}://{quote(user)}:{quote(password)}@{host}:{port}/{name}"
```

Заменить строку `database_url: str = Field(validation_alias="DATABASE_URL")` на
компоненты Chainlit:

```python
    # --- Chainlit data layer (компоненты; DSN собирается свойством) ---
    chainlit_db_host: str = Field(validation_alias="CHAINLIT_DB_HOST")
    chainlit_db_port: int = Field(default=5432, validation_alias="CHAINLIT_DB_PORT")
    chainlit_db_user: str = Field(validation_alias="CHAINLIT_DB_USER")
    chainlit_db_password: str = Field(validation_alias="CHAINLIT_DB_PASSWORD")
    chainlit_db_name: str = Field(validation_alias="CHAINLIT_DB_NAME")
```

Заменить блок `# --- TOAST-таблицы …` c полем `toast_database_url` на
компоненты Toast:

```python
    # --- Toast БД для SQL-инструмента (компоненты; фича-флаг) ---
    toast_db_host: str | None = Field(default=None, validation_alias="TOAST_DB_HOST")
    toast_db_port: int = Field(default=5432, validation_alias="TOAST_DB_PORT")
    toast_db_user: str | None = Field(default=None, validation_alias="TOAST_DB_USER")
    toast_db_password: str | None = Field(
        default=None, validation_alias="TOAST_DB_PASSWORD"
    )
    toast_db_name: str | None = Field(default=None, validation_alias="TOAST_DB_NAME")
```

Добавить свойства в класс `Settings` (после полей, до конца класса):

```python
    @property
    def database_url(self) -> str:
        """DSN Chainlit data-layer (SQLAlchemy async)."""
        return build_dsn(
            "postgresql+asyncpg", self.chainlit_db_user, self.chainlit_db_password,
            self.chainlit_db_host, self.chainlit_db_port, self.chainlit_db_name,
        )

    @property
    def toast_dsn(self) -> str | None:
        """DSN Toast-БД (asyncpg). None, если компоненты заданы не полностью."""
        if not all([self.toast_db_host, self.toast_db_user,
                    self.toast_db_password, self.toast_db_name]):
            return None
        return build_dsn(
            "postgresql", self.toast_db_user, self.toast_db_password,
            self.toast_db_host, self.toast_db_port, self.toast_db_name,
        )
```

- [ ] **Step 4: Убедиться, что тесты конфига проходят**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/config.py backend/tests/test_config.py
git commit -m "feat(config): split DB DSNs into components with build_dsn"
```

---

### Task 2: conftest baseline + прогон всего набора

Обновить общий baseline тестов, чтобы все потребители `get_settings()` собирались из компонентов.

**Files:**
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes: компоненты `CHAINLIT_DB_*` (Task 1).

- [ ] **Step 1: Обновить baseline conftest**

В `backend/tests/conftest.py` заменить словарь `_BASELINE` (сейчас с
`DATABASE_URL`) на компоненты:

```python
_BASELINE = {
    "CHAINLIT_DB_HOST": "localhost",
    "CHAINLIT_DB_USER": "u",
    "CHAINLIT_DB_PASSWORD": "p",
    "CHAINLIT_DB_NAME": "db",
    "CHAINLIT_JWT_SECRET": "test-secret-that-is-32-bytes-long!!",
    "CHAINLIT_JWT_AUDIENCE": "chainlit",
    "CHAINLIT_JWT_ISSUER": "datacraft",
}
```

- [ ] **Step 2: Прогнать весь набор**

Run: `cd backend && uv run pytest`
Expected: PASS — `test_app_imports`/`test_oauth` (импортируют `app`) собирают
`Settings` из компонентов через conftest; data-layer использует свойство
`database_url`.

- [ ] **Step 3: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add backend/tests/conftest.py
git commit -m "test(config): baseline env uses CHAINLIT_DB_* components"
```

---

### Task 3: Потребители Toast-DSN (eval + интеграционный тест)

**Files:**
- Modify: `infra/eval-sql.py`
- Modify: `backend/tests/test_executor.py`

**Interfaces:**
- Consumes: `config.build_dsn` (Task 1); env `TOAST_DB_*`.

- [ ] **Step 1: Хелпер сборки Toast-DSN из env в eval**

В `infra/eval-sql.py` заменить чтение DSN. Добавить импорт рядом с прочими
backend-импортами:

```python
from config import build_dsn  # noqa: E402
```

Добавить функцию сборки (после импортов):

```python
def _toast_dsn() -> str | None:
    host = os.environ.get("TOAST_DB_HOST")
    user = os.environ.get("TOAST_DB_USER")
    password = os.environ.get("TOAST_DB_PASSWORD")
    name = os.environ.get("TOAST_DB_NAME")
    if not all([host, user, password, name]):
        return None
    port = int(os.environ.get("TOAST_DB_PORT", "5432"))
    return build_dsn("postgresql", user, password, host, port, name)
```

Заменить тело гейта в `main` (было `dsn = os.environ.get("TOAST_DATABASE_URL")`):

```python
    dsn = _toast_dsn()
    if not dsn or not os.environ.get("OPENROUTER_API_KEY"):
        print("SKIP: нужны TOAST_DB_* и OPENROUTER_API_KEY")
        return
```

Обновить docstring модуля: заменить упоминание `TOAST_DATABASE_URL` на
`TOAST_DB_* (host/port/user/password/name)`.

- [ ] **Step 2: Интеграционный тест собирает DSN из компонентов**

В `backend/tests/test_executor.py` заменить первые строки чтения DSN:

```python
import asyncio
import os

import pytest


def _dsn() -> str | None:
    host = os.environ.get("TOAST_DB_HOST")
    user = os.environ.get("TOAST_DB_USER")
    password = os.environ.get("TOAST_DB_PASSWORD")
    name = os.environ.get("TOAST_DB_NAME")
    if not all([host, user, password, name]):
        return None
    from config import build_dsn

    port = int(os.environ.get("TOAST_DB_PORT", "5432"))
    return build_dsn("postgresql", user, password, host, port, name)


DSN = _dsn()
pytestmark = pytest.mark.skipif(not DSN, reason="TOAST_DB_* not set")
```

(Остальное — `LEGAL`, `_run`, `_exe`, тела тестов — без изменений; `_exe`
использует уже собранный `DSN`.)

- [ ] **Step 3: Проверка**

Run: `cd backend && uv run pytest tests/test_executor.py -v`
Expected: SKIPPED без `TOAST_DB_*`.

Run: `cd /Users/stamplevskiyd/development/lore && python3 -m py_compile infra/eval-sql.py`
Expected: exit 0.

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add infra/eval-sql.py backend/tests/test_executor.py
git commit -m "refactor(toast): assemble Toast DSN from TOAST_DB_* components"
```

---

### Task 4: docker-compose на компоненты

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: env-имена `CHAINLIT_DB_*`, `TOAST_DB_*`.

- [ ] **Step 1: Заменить DATABASE_URL и TOAST_DATABASE_URL**

В `docker-compose.yml`, в `backend.environment`, заменить строку

```yaml
      DATABASE_URL: postgresql+asyncpg://${CHAINLIT_DB_USER:-chainlit}:${CHAINLIT_DB_PASSWORD:-chainlit}@chainlit-db:5432/${CHAINLIT_DB_NAME:-chainlit}
```

на компоненты:

```yaml
      CHAINLIT_DB_HOST: chainlit-db
      CHAINLIT_DB_PORT: "5432"
      CHAINLIT_DB_USER: ${CHAINLIT_DB_USER:-chainlit}
      CHAINLIT_DB_PASSWORD: ${CHAINLIT_DB_PASSWORD:-chainlit}
      CHAINLIT_DB_NAME: ${CHAINLIT_DB_NAME:-chainlit}
```

Заменить строку

```yaml
      TOAST_DATABASE_URL: ${TOAST_DATABASE_URL:-}
```

на компоненты (фича-флаг, пустые по умолчанию):

```yaml
      TOAST_DB_HOST: ${TOAST_DB_HOST:-}
      TOAST_DB_PORT: ${TOAST_DB_PORT:-5432}
      TOAST_DB_USER: ${TOAST_DB_USER:-}
      TOAST_DB_PASSWORD: ${TOAST_DB_PASSWORD:-}
      TOAST_DB_NAME: ${TOAST_DB_NAME:-}
```

- [ ] **Step 2: Проверить валидность compose**

Run: `cd /Users/stamplevskiyd/development/lore && docker compose config -q`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add docker-compose.yml
git commit -m "chore(compose): pass DB config as components, not DSN strings"
```

---

## Верификация плана целиком

1. `cd backend && uv run pytest` — все тесты зелёные (config собирает DSN из компонентов, baseline обновлён).
2. `grep -rn "DATABASE_URL\|TOAST_DATABASE_URL\|toast_database_url" backend infra docker-compose.yml --include="*.py" --include="*.yml" | grep -v __pycache__` — не осталось старых цельных DSN-переменных (кроме, возможно, комментариев).
3. `docker compose config -q` — compose валиден.
4. `cd backend && uv run ruff check .` — чисто.
