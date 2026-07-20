# lore — ИИ-чат (React + Chainlit)

Полноценный docker-compose проект: React-фронтенд чата и Chainlit-бэкенд
(langgraph/deepagents поверх OpenRouter, с Ollama-фолбэком) с
JWT/SSO-аутентификацией и хранением истории в Postgres.

## Структура

```
├── docker-compose.yml    # оркестрация всех сервисов
├── .env.example          # шаблон настроек (копируй в .env)
├── frontend/             # React + Vite SPA (nginx в контейнере)
│   ├── Dockerfile        # multi-stage: node build → nginx
│   ├── nginx.conf
│   └── src/
│       └── providers/    # mock- и chainlit-провайдеры чата
└── lore-core/services/lore-chat/   # Chainlit-сервис
    ├── Dockerfile
    ├── app.py            # обработчики Chainlit (auth, data layer, on_message)
    ├── config.py         # единый реестр переменных окружения (pydantic-settings)
    ├── agents/           # build_agent() — fast/deep режимы, выбор модели, инструменты
    ├── toast/            # доступ к TOAST-таблицам (query_document_tables)
    ├── auth.py           # verify_ticket() — проверка JWT (HS256)
    └── init/schema.sql   # схема Postgres data layer
```

## Документация

- [Развертывание и эксплуатация](docs/deployment.md) — требования, конфигурация,
  тома и сброс данных, продакшен-чеклист, troubleshooting.
- [Использование](docs/usage.md) — вход, работа с чатом, управление
  пользователями в authentik, прямой доступ к API, разработка.
- [Бэклог улучшений](docs/improvements.md) — результаты ревью кода и
  инфраструктуры с приоритетами.

## Быстрый старт

По умолчанию модель берётся из OpenRouter — нужен только API-ключ.
Скопируй шаблон и впиши ключ:

```bash
cp .env.example .env
# в .env: OPENROUTER_API_KEY=sk-or-...
```

Затем весь проект:

```bash
docker compose up -d --build
```

Ollama нужна, только если переключиться на локальный фолбэк
(`MODEL_PROVIDER=ollama`) — тогда запусти её на хосте (`ollama serve`,
`ollama pull gemma3`); в compose она не входит.

| Сервис      | Адрес                  |
|-------------|------------------------|
| Фронтенд    | http://localhost:3000  |
| Chainlit    | http://localhost:8000  |
| authentik   | http://localhost:9100  |
| Postgres    | внутренний (chainlit-db:5432) |

## Настройка

Все переменные имеют рабочие дефолты в `docker-compose.yml` (кроме
`OPENROUTER_API_KEY` — он пустой); переопределяются через `.env` в корне
(см. `.env.example`):

- `OPENROUTER_API_KEY` — **единственное обязательное** для ответов агента
  при провайдере по умолчанию (`MODEL_PROVIDER=openrouter`). Без ключа
  бэкенд поднимется, но первый же запрос упадёт с ошибкой.
- `MODEL_PROVIDER` — `openrouter` (по умолчанию) или `ollama` (локальный
  фолбэк). `OPENROUTER_MODEL` / `OPENROUTER_BASE_URL` и `OLLAMA_MODEL` /
  `OLLAMA_BASE_URL` — модель и адрес соответствующего провайдера.
- `TOAST_DATABASE_URL` — read-only DSN к внешним TOAST-таблицам
  (`loreagent_test`). Пусто — агенту доступен только калькулятор; задан —
  добавляется инструмент `query_document_tables` (таблицы сотрудников,
  грейдов, документов). Compose эту БД не поднимает.
- `CHAINLIT_PUBLIC_URL` — адрес бэкенда, каким его видит браузер
  (build-time настройка Vite: после смены пересобери фронтенд —
  `docker compose up -d --build frontend`).
- `CHAINLIT_JWT_SECRET` / `AUDIENCE` / `ISSUER` — параметры проверки
  JWT-тикетов; должны совпадать со стороной, которая тикеты выдаёт.
  Дефолтный секрет годится только для локальной разработки.

CORS: разрешённые origin'ы фронтенда задаются в
`lore-core/services/lore-chat/.chainlit/config.toml` (`allow_origins`) — `http://localhost:3000`
уже добавлен.

## Аутентификация (authentik SSO)

Вход в приложение — через authentik (поднимается в этом же compose,
`http://localhost:9100`). При первом старте init-контейнер `authentik-init`
автоматически создаёт OAuth2-провайдера и приложение `lore`; Chainlit
подключён к нему как confidential-клиент (generic OAuth).

- Пользователь по умолчанию: `akadmin`, пароль — `AUTHENTIK_BOOTSTRAP_PASSWORD`
  (по умолчанию `admin`). Админка: http://localhost:9100/if/admin/.
- Логин из SPA открывается popup-окном; после входа popup закрывается сам.
- Переменные: `AUTHENTIK_PORT`, `AUTHENTIK_PUBLIC_URL`, `AUTHENTIK_SECRET_KEY`,
  `AUTHENTIK_BOOTSTRAP_PASSWORD`, `AUTHENTIK_BOOTSTRAP_TOKEN`,
  `AUTHENTIK_CLIENT_ID`, `AUTHENTIK_CLIENT_SECRET` (см. `.env.example`).
  Секреты с dev-дефолтами годятся только для локальной разработки.
- Header-auth по JWT-тикетам (контракт datacraft) продолжает работать
  параллельно; `CHAINLIT_JWT_*` нужны только для него.

## Режимы ассистента

Два режима (переключатель в сайдбаре, действует на новый чат;
у существующего чата режим зафиксирован на треде):

- **Быстрый** (`fast`, по умолчанию) — чистый langgraph с фиксированным
  маршрутом и одним циклом инструментов: `model → tools → final`.
  Предсказуем, не зацикливается, подходит маленьким моделям.
- **Умный** (`deep`) — deepagents: сам планирует шаги и вызовы
  инструментов. Для сложных задач (медленнее).

Оба режима используют общий набор инструментов
(`lore-core/services/lore-chat/agents/tools.py`): калькулятор (безопасная арифметика через
AST) и — когда задан `TOAST_DATABASE_URL` — `query_document_tables`,
read-only доступ к TOAST-таблицам (`loreagent_test`: сотрудники, грейды,
документы) через `lore-core/services/lore-chat/toast/`. Без `TOAST_DATABASE_URL` доступен
только калькулятор. Прогон eval-кейсов: `python3 infra/eval-agents.py`.

## Состояние интеграции

Полный цикл работает end-to-end: SSO-логин через authentik, чат с агентом
по родному socket.io-протоколу Chainlit (`@chainlit/react-client` +
runtime `@assistant-ui/react`), стриминг ответов выбранной модели,
серверные треды (история в Postgres, возобновление после перезагрузки,
переименование и удаление), два режима агента над TOAST-слоем. Для ответов
агента нужен `OPENROUTER_API_KEY` (провайдер по умолчанию) либо
запущенная на хосте Ollama при `MODEL_PROVIDER=ollama`.

## Разработка без Docker

Фронтенд (Node ≥ 20):

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Бэкенд (Python ≥ 3.13; нужны Postgres и `OPENROUTER_API_KEY`, либо Ollama
при `MODEL_PROVIDER=ollama`). Без compose обязательны ещё `DATABASE_URL` и
`CHAINLIT_JWT_*` — задай их в `.env`/`.env.local` или в окружении:

```bash
cd backend
pip install -e ".[dev]"
chainlit run app.py --port 8000
```

## Тесты бэкенда

```bash
cd backend
pip install -e ".[dev]"
pytest -v
```
