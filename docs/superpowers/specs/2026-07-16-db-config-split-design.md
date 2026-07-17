# Разбивка DSN обеих БД на компоненты

Дата: 2026-07-16. Статус: утверждён.

## Проблема

Подключения к БД заданы цельными DSN-строками (`DATABASE_URL`,
`TOAST_DATABASE_URL`). Хотим хранить компоненты (host/port/user/password/name)
отдельно, а DSN собирать в одном месте.

## Ключевой нюанс

Две БД используют РАЗНЫЕ схемы DSN:
- Chainlit data-layer (SQLAlchemy async) → `postgresql+asyncpg://…`
- Toast SQL-инструмент (asyncpg raw) → `postgresql://…`

## Решения обсуждения

| Вопрос | Решение |
| --- | --- |
| Какие БД | Обе: Chainlit (обязательная) и Toast (опциональная) |
| Сборка | Хелпер `build_dsn(...)` в `config.py` с URL-экранированием логина/пароля |
| SSL | Не добавляем (YAGNI) |

## `config.py`

```python
from urllib.parse import quote


def build_dsn(scheme: str, user: str, password: str,
              host: str, port: int, name: str) -> str:
    return f"{scheme}://{quote(user)}:{quote(password)}@{host}:{port}/{name}"
```

Поля Settings (через `Field(validation_alias=...)`):

- **Chainlit БД (обязательные, кроме порта):**
  `chainlit_db_host` (`CHAINLIT_DB_HOST`),
  `chainlit_db_user` (`CHAINLIT_DB_USER`),
  `chainlit_db_password` (`CHAINLIT_DB_PASSWORD`),
  `chainlit_db_name` (`CHAINLIT_DB_NAME`),
  `chainlit_db_port: int = 5432` (`CHAINLIT_DB_PORT`).
  Свойство:
  ```python
  @property
  def database_url(self) -> str:
      return build_dsn("postgresql+asyncpg", self.chainlit_db_user,
                       self.chainlit_db_password, self.chainlit_db_host,
                       self.chainlit_db_port, self.chainlit_db_name)
  ```

- **Toast БД (опциональные, фича-флаг):**
  `toast_db_host/user/password/name: str | None = None`
  (`TOAST_DB_HOST/USER/PASSWORD/NAME`), `toast_db_port: int = 5432`
  (`TOAST_DB_PORT`).
  Свойство:
  ```python
  @property
  def toast_dsn(self) -> str | None:
      if not all([self.toast_db_host, self.toast_db_user,
                  self.toast_db_password, self.toast_db_name]):
          return None
      return build_dsn("postgresql", self.toast_db_user,
                       self.toast_db_password, self.toast_db_host,
                       self.toast_db_port, self.toast_db_name)
  ```

Удаляются поля `database_url`/`toast_database_url` (заменены компонентами и
свойствами того же имени `database_url` + новым `toast_dsn`).

## Потребители

- `app.py` `get_data_layer`: `conninfo=get_settings().database_url` — вызов не
  меняется (теперь это вычисляемое свойство).
- `docker-compose.yml`, backend.environment:
  - `DATABASE_URL: postgresql+asyncpg://…` → отдельные
    `CHAINLIT_DB_HOST: chainlit-db`, `CHAINLIT_DB_PORT: "5432"`,
    `CHAINLIT_DB_USER: ${CHAINLIT_DB_USER:-chainlit}`,
    `CHAINLIT_DB_PASSWORD: ${CHAINLIT_DB_PASSWORD:-chainlit}`,
    `CHAINLIT_DB_NAME: ${CHAINLIT_DB_NAME:-chainlit}`.
  - `TOAST_DATABASE_URL: …` → `TOAST_DB_HOST/PORT/USER/PASSWORD/NAME`
    (со значениями по умолчанию пустыми — фича-флаг).
- `infra/eval-sql.py`: вместо `os.environ.get("TOAST_DATABASE_URL")` читает
  `TOAST_DB_*` из env и собирает DSN через `config.build_dsn` (skip, если
  неполно).
- `backend/tests/test_executor.py`: DSN из `TOAST_DB_*` env через `build_dsn`;
  skip, если набор неполный.
- `backend/tests/conftest.py` baseline: вместо `DATABASE_URL` выставляет
  `CHAINLIT_DB_HOST/PORT/USER/PASSWORD/NAME`.
- `backend/tests/test_app_imports.py`, `test_oauth.py`: полагаются на conftest
  baseline (локальный `DATABASE_URL` убрать, если оставался).

## Тестирование

- `test_config.py`:
  - `database_url` собирается из компонентов (схема `postgresql+asyncpg`);
  - `toast_dsn` собирается из компонентов (схема `postgresql`);
  - пароль со спецсимволами (`p@ss/w:rd`) экранируется в DSN;
  - `toast_dsn is None` при неполном наборе Toast-компонентов;
  - отсутствие обязательного Chainlit-компонента → `ValidationError`.
- Существующие тесты (auth/app/oauth/agents) — зелёные после обновления
  conftest baseline.

## Вне scope (YAGNI)

- SSL/sslmode-параметры.
- Логику пула/таймаутов не трогаем.
- Разбивку прочих сервисных БД (authentik) не делаем — это compose-инфра, не
  наш Python-конфиг.
