# lore — ИИ-чат (React + Chainlit)

Полноценный docker-compose проект: React-фронтенд чата и Chainlit-бэкенд
(deepagents + Ollama) с JWT-аутентификацией и хранением истории в Postgres.

## Структура

```
├── docker-compose.yml    # оркестрация всех сервисов
├── .env.example          # шаблон настроек (копируй в .env)
├── frontend/             # React + Vite SPA (nginx в контейнере)
│   ├── Dockerfile        # multi-stage: node build → nginx
│   ├── nginx.conf
│   └── src/
│       └── providers/    # mock- и chainlit-провайдеры чата
└── backend/              # Chainlit-сервис
    ├── Dockerfile
    ├── app.py            # обработчики Chainlit (auth, data layer, on_message)
    ├── agent.py          # build_agent() — deepagent поверх Ollama
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

Ollama не входит в compose — запусти её на хосте:

```bash
ollama serve        # если ещё не запущена
ollama pull gemma3
```

Затем весь проект:

```bash
docker compose up -d --build
```

| Сервис      | Адрес                  |
|-------------|------------------------|
| Фронтенд    | http://localhost:3000  |
| Chainlit    | http://localhost:8000  |
| authentik   | http://localhost:9100  |
| Postgres    | внутренний (chainlit-db:5432) |

## Настройка

Все переменные имеют рабочие дефолты в `docker-compose.yml`; переопределяются
через `.env` в корне (см. `.env.example`):

- `CHAINLIT_PUBLIC_URL` — адрес бэкенда, каким его видит браузер
  (build-time настройка Vite: после смены пересобери фронтенд —
  `docker compose up -d --build frontend`).
- `OLLAMA_BASE_URL`, `OLLAMA_MODEL` — где искать Ollama и какую модель брать.
- `CHAINLIT_JWT_SECRET` / `AUDIENCE` / `ISSUER` — параметры проверки
  JWT-тикетов; должны совпадать со стороной, которая тикеты выдаёт.
  Дефолтный секрет годится только для локальной разработки.

CORS: разрешённые origin'ы фронтенда задаются в
`backend/.chainlit/config.toml` (`allow_origins`) — `http://localhost:3000`
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

## Состояние интеграции

Полный цикл работает end-to-end: SSO-логин через authentik, чат с агентом
по родному socket.io-протоколу Chainlit (`@chainlit/react-client` +
runtime `@assistant-ui/react`), стриминг ответов Ollama, серверные треды
(история в Postgres, возобновление после перезагрузки, переименование и
удаление). Для ответов агента нужна запущенная на хосте Ollama с моделью
`OLLAMA_MODEL` (по умолчанию `gemma3`).

## Разработка без Docker

Фронтенд (Node ≥ 20):

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Бэкенд (Python ≥ 3.13, нужны Postgres и Ollama):

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
