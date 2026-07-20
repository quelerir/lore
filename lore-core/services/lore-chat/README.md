# datacraft-chainlit

Минимальный Chainlit-сервис на deepagents + Ollama (gemma3) с JWT-аутентификацией
и хранением истории в Postgres. Каркас интеграции с фронтендом datacraft.

## Запуск

Сервис запускается через корневой `docker-compose.yml` проекта (сервисы
`backend` + `chainlit-db`), переменные окружения — см. `.env.example` в корне:

```bash
docker compose up -d --build backend
```

Ollama не входит в compose — запусти её отдельно (локально/на хосте) и укажи
`OLLAMA_BASE_URL`. Для локальных тестов:

```bash
ollama serve                  # если ещё не запущена
ollama pull gemma3
```

Chainlit доступен на http://localhost:8000. Из контейнера Ollama на хосте
доступна как `http://host.docker.internal:11434` (значение по умолчанию).

## Компоненты

- `app.py` — обработчики Chainlit (auth, data layer, on_message).
- `agent.py` — `build_agent()`, фабрика deepagent поверх Ollama.
- `auth.py` — `verify_ticket()`, проверка JWT (HS256).
- `init/schema.sql` — схема Postgres data layer.

## Тесты

```bash
pip install -e ".[dev]"
pytest -v
```

## Область каркаса

Реализовано: JWT-auth, персистентность в Postgres, чистый чат-агент.
Опущено (см. `description.md`): профили charts/analyst, MCP-инструменты,
форвардинг userEnv, cl.Plotly-ответы.
