# Ревью: точки улучшения

Дата: 2026-07-15. Ревью бэкенда, docker-инфраструктуры и (кратко) фронтенда.
Все утверждения про поведение Chainlit проверены по исходникам версии
2.11.1 из образа `lore-backend`. Ничего из списка не применено — это бэклог
для обсуждения.

Приоритеты: 🔴 стоит сделать в ближайшую итерацию · 🟡 желательно ·
⚪ по вкусу / когда дорастём.

## Docker / compose

### ✅ D1. У `backend` нет healthcheck, зависимости ждут только старта — сделано 2026-07-15
У Chainlit есть готовый `GET /health` (server.py:1834), но compose его не
использует: `frontend.depends_on: backend` срабатывает по факту запуска
процесса, а не готовности. Лечится тремя строками (curl в slim-образе нет,
но есть python):

```yaml
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"]
      interval: 10s
      retries: 5
```

и `condition: service_healthy` у frontend.

### ✅ D2. Нет restart-политик — сделано 2026-07-15
Ни у одного сервиса нет `restart: unless-stopped` — после ребута хоста или
крэша процесса стек сам не поднимется. Для всех длительных сервисов —
одна строка; `authentik-init` оставить с `restart: "no"`.

### ✅ D3. Сборка бэкенда нерепродуцируема: `uv.lock` лежит в репо, но не используется — сделано 2026-07-15
Нюанс реализации: в pyproject нет `[build-system]`, поэтому uv считает проект
virtual и не устанавливает сами модули — pytest получил `pythonpath = ["."]`,
а venv вынесен в `/opt/venv`, чтобы bind-mount `/app` его не прятал.
`lore-core/services/lore-chat/Dockerfile` ставит зависимости через `pip install -e .` по
pyproject, где версии почти не ограничены (`deepagents`, `langchain-ollama`
вообще без границ). Каждый build может притащить другие версии — вплоть до
ломающих (экосистема langchain это любит). При этом точный срез уже
зафиксирован в `uv.lock`. Рекомендация:

```dockerfile
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
CMD ["uv", "run", "--no-sync", "chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
```

(или экспортировать lock в requirements.txt и ставить pip'ом с `--require-hashes`).

### 🟡 D4. Контейнер бэкенда работает от root
В Dockerfile нет `USER`; nginx-образ фронтенда тоже дефолтный. Для демо
терпимо, для стенда — завести непривилегированного пользователя
(`RUN useradd -m app` + `USER app`).

### 🟡 D5. Секреты с дефолтами в compose
Postgres-пароли захардкожены (`chainlit`/`authentik`), а
`AUTHENTIK_BOOTSTRAP_TOKEN` — статический admin-токен API authentik.
Внутри compose-сети это приемлемо для dev; для остального — обязательное
переопределение задокументировано в deployment.md. Опционально: warning
при старте, docker secrets.

### 🟡 D6. Дублирование значений в compose
`${AUTHENTIK_CLIENT_ID:-lore-chainlit}` и `${AUTHENTIK_CLIENT_SECRET:-...}`
повторяются в `backend` и `authentik-init`; `${CHAINLIT_PUBLIC_URL:-...}` —
в `backend` (CHAINLIT_URL) и `authentik-init` (REDIRECT_URI). Рассинхрон
дефолтов сломает OAuth неочевидным образом. Вариант: top-level `x-`-якоря:

```yaml
x-oauth-client: &oauth-client
  AUTHENTIK_CLIENT_ID: ${AUTHENTIK_CLIENT_ID:-lore-chainlit}
  AUTHENTIK_CLIENT_SECRET: ${AUTHENTIK_CLIENT_SECRET:-dev-only-oauth-client-secret-change-me}
```

### ⚪ D7. Два инстанса Postgres
`chainlit-db` и `authentik-db` — отдельные серверы. Изоляция осознанная
(разные владельцы данных, независимый сброс), но для лёгкого демо можно
один сервер с двумя базами (initdb-скрипт с `CREATE DATABASE`). Я бы
оставил как есть — экономия ~100 МБ RAM не стоит потери простоты сброса.

### ⚪ D8. compose-файл растёт (~190 строк)
Можно вынести authentik-блок в `compose.authentik.yml` и подключить через
`include:` (Compose v2.20+). Пока читаемо, но при следующем росте — пора.

### ⚪ D9. Мелочи
- authentik без media-тома — загруженные иконки пропадут при пересоздании;
- nginx фронтенда без security-заголовков (`X-Content-Type-Options`,
  `frame-ancestors`);
- базовые образы не запинованы по digest.

## Бэкенд

### 🟡 B1. Два источника правды для истории диалога
`on_message` ведёт `cl.user_session["history"]` вручную, параллельно data
layer пишет те же сообщения в steps; `on_chat_resume` реконструирует
историю из steps. Инвариант «история в сессии == steps треда» нигде не
зафиксирован и легко разъедется (например, при ошибке стриминга ответ
частично уйдёт в steps, но не попадёт в history, и наоборот). Варианты:
строить messages из steps на каждый запрос (проще, +1 запрос) или явно
задокументировать/протестировать инвариант.

### 🟡 B2. Файловые элементы не переживут пересоздание контейнера
`SQLAlchemyDataLayer` создан без `storage_provider` — метаданные элементов
пишутся в Postgres, а сами файлы остаются в локальной ФС контейнера. Для
текущего текстового чата не актуально, но сломается на следующем шаге при
`cl.Plotly` (datacraft-контракт, description.md §1e): resume-треды будут
ссылаться на исчезнувшие файлы. Решение при интеграции: volume под данные
элементов или S3-совместимый storage client (minio в compose).

### 🟡 B3. Нет CI
Тесты гоняются руками. Минимальный GitHub Actions: job на
`docker compose build` + pytest в контейнере (там же можно ruff/mypy —
они уже в dev-зависимостях, но нигде не запускаются).

### ⚪ B4. `_NullPoolSQLAlchemyDataLayer` создаёт движок дважды
`super().__init__` создаёт pooled-движок, который тут же выбрасывается и
заменяется NullPool-версией (app.py:33-46). Это осознанный обход
ограничения Chainlit 2.11.1 — `SQLAlchemyDataLayer.__init__` действительно
не пробрасывает `poolclass` (проверено по исходникам) — так что сабкласс
оправдан. Но он хрупок к изменениям родителя: комментарий стоит дополнить
пометкой «проверять при апгрейде chainlit», а лучше — предложить upstream
параметр `engine_kwargs`.

### ⚪ B5. Миграции схемы
`init/schema.sql` применяется только при первой инициализации тома.
Изменение схемы = пересоздание тома (потеря истории) или ручной SQL. Для
демо нормально; при первом же реальном изменении схемы — alembic или хотя
бы нумерованные init-скрипты.

### ⚪ B6. pyproject: версии и структура
Зависимости без верхних границ (см. D3 — lock решает проблему для docker,
но `pip install -e .` локально всё равно тянет «что придётся»); плоские
`py-modules = ["app", "agent", "auth"]` — при росте перейти на пакет
`lore_backend/`. `description.md` — контракт datacraft, для standalone-lore
он частично неактуален (профили charts/analyst, MCP) — стоит пометить
шапкой «референс, не текущее ТЗ».

## Фронтенд (кратко, вне основного скоупа ревью)

### ✅ F1. assistant-ui подключён, но не используется по назначению — сделано 2026-07-15
Чат переведён на `@chainlit/react-client` + `useExternalStoreRuntime`;
ручной стейт-менеджмент и noop-runtime удалены. Попутно F2 в основном
закрыт (App.tsx ужался, стриминг-циклы ушли в runtime). Цена решения:
даунгрейд React 19 → 18.3.1 (recoil, peer react-client, несовместим с 19).
`useLocalRuntime(noopRuntimeAdapter)` + вся логика чата (state, стриминг,
остановка, персистентность) написана вручную в App.tsx; от библиотеки
используются только презентационные обёртки `ThreadPrimitive`/
`ComposerPrimitive`. Это ровно «реимплементация библиотечного кода»:
у assistant-ui runtime всё это есть из коробки (ChatModelAdapter со
стримингом и отменой). На шаге интеграции `chainlitChatProvider` надо
выбрать: либо переехать на runtime по-настоящему (и выкинуть ручной
стейт-менеджмент), либо убрать зависимость и оставить свои компоненты.
Держать оба слоя — худший вариант.

### 🟡 F2. App.tsx — 500-строчный god-component
Персистентность, модалки, clipboard-fallback, два стриминг-цикла
(send/regenerate — почти дублирующие друг друга) в одном файле. Разнести:
`useChats`, `usePersistedState`, `ChatModal`, общий helper стриминга.
Частично решится само при F1.

### ✅ F3. localStorage общий для всех пользователей — сделано 2026-07-15
localStorage-персистентность удалена целиком: треды серверные, история —
в Postgres под identifier пользователя.
Ключ `lore-chat-state` не привязан к identifier — после SSO два
пользователя на одной машине увидят чаты друг друга. Включить identifier
в ключ (или убрать localStorage при переходе на серверные треды).

### 🟡 F4. `VITE_CHAINLIT_URL` вшивается на этапе сборки
Смена адреса бэкенда требует пересборки образа. Для деплоя удобнее
runtime-конфиг: nginx отдаёт `config.js`/`env.json`, сгенерированный из
env при старте контейнера.

### ⚪ F5. Косметика
`package.json` name — `executive-brief-chat` (наследие) → `lore-frontend`;
`frontend/.env.example` не упоминается в README.

## Сводка приоритетов

| # | Что | Усилие |
|---|---|---|
| ~~D1~~ | ~~healthcheck бэкенда + service_healthy~~ ✅ | минуты |
| ~~D2~~ | ~~restart-политики~~ ✅ | минуты |
| ~~D3~~ | ~~uv.lock в Docker-сборке~~ ✅ | ~час |
| ~~F1~~ | ~~определиться с assistant-ui при интеграции чата~~ ✅ | решение + рефакторинг |
| B1/B2 | история и storage элементов | вместе с интеграцией чата |
| B3 | минимальный CI | ~час |
