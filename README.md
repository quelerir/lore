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
| Postgres    | внутренний (chainlit-db:5432) |

## Настройка

Все переменные имеют рабочие дефолты в `docker-compose.yml`; переопределяются
через `.env` в корне (см. `.env.example`):

- `CHAT_PROVIDER` — провайдер чата во фронтенде: `mock` (по умолчанию, демо
  без бэкенда) или `chainlit`. Провайдер — build-time настройка Vite, после
  смены пересобери фронтенд: `docker compose up -d --build frontend`.
- `CHAINLIT_PUBLIC_URL` — адрес бэкенда, каким его видит браузер.
- `OLLAMA_BASE_URL`, `OLLAMA_MODEL` — где искать Ollama и какую модель брать.
- `CHAINLIT_JWT_SECRET` / `AUDIENCE` / `ISSUER` — параметры проверки
  JWT-тикетов; должны совпадать со стороной, которая тикеты выдаёт.
  Дефолтный секрет годится только для локальной разработки.

CORS: разрешённые origin'ы фронтенда задаются в
`backend/.chainlit/config.toml` (`allow_origins`) — `http://localhost:3000`
уже добавлен.

## Состояние интеграции

Инфраструктурно фронтенд и бэкенд связаны (общая сеть compose, CORS, env).
На уровне кода `frontend/src/providers/chainlitChatProvider.ts` — пока
каркас: точки подключения к Chainlit API помечены комментариями, реальный
обмен сообщениями ещё не реализован (поэтому дефолт — `mock`).

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
