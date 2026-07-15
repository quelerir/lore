# Минимальный каркас: Chainlit + deepagents + Ollama

## Цель

Простейший docker-compose проект-каркас, удовлетворяющий контракту из
`description.md` в объёме, необходимом для подключения фронтенда datacraft:

- настоящее `chainlit run` приложение (родной socket.io-протокол);
- JWT-аутентификация тикета datacraft (`@cl.header_auth_callback`);
- персистентность чатов через официальный `SQLAlchemyDataLayer` на Postgres;
- простой чат-агент на deepagents поверх Ollama (`gemma3`), без инструментов.

**Вне объёма (сознательно опущено):** chat-профили `charts`/`analyst`,
MCP-инструменты, форвардинг `userEnv` (`datacraft_token` / `dashboard_id`),
`cl.Plotly`-ответы. Это каркас; агентную логику заменяют позже.

## Архитектура

Одно `chainlit run` приложение + два контейнера в `docker-compose.yml`:

- **app** — сам Chainlit-сервис (Python 3.13).
- **chainlit-db** — Postgres, владелец истории диалогов.
- **ollama** — локальный LLM-сервер, отдаёт модель `gemma3`.

```
datacraft-chainlit/
├── app.py                # chainlit-обработчики
├── agent.py              # build_agent() — фабрика deepagent
├── auth.py               # verify_ticket() — проверка JWT (HS256)
├── .chainlit/config.toml # allow_origins / CORS
├── chainlit.md           # текст приветствия
├── init/schema.sql       # официальная схема data layer Chainlit
├── pyproject.toml        # зависимости, python 3.13
├── Dockerfile
├── docker-compose.yml    # app + chainlit-db + ollama
└── .env.example
```

## Компоненты

### `agent.py` → `build_agent()`

Изолированная фабрика агента (главное требование задачи). Создаёт deepagents-агент:

- модель: `ChatOllama(model=<OLLAMA_MODEL>, base_url=<OLLAMA_BASE_URL>)`;
- инструменты: пустой список (чистый чат);
- системный промпт: короткий, «ты ассистент datacraft».

Возвращает готовый LangGraph-агент. Никакой логики Chainlit внутри — чистая сборка.

### `auth.py` → `verify_ticket(token)`

- декодирует Bearer-JWT секретом `CHAINLIT_JWT_SECRET` (HS256);
- сверяет `aud` (`CHAINLIT_JWT_AUDIENCE`), `iss` (`CHAINLIT_JWT_ISSUER`), `exp`;
- возвращает `sub` (идентификатор пользователя) и `username` из payload;
- бросает исключение при любой ошибке проверки.

### `app.py` — обработчики Chainlit

- `@cl.header_auth_callback(headers)` — достаёт `Authorization: Bearer <ticket>`,
  зовёт `verify_ticket`, возвращает `cl.User(identifier=str(sub),
  metadata={"username": ...})` или `None` при провале.
- `@cl.data_layer` — `SQLAlchemyDataLayer(conninfo=DATABASE_URL, ...)`; движок
  создаётся с `poolclass=NullPool` (иначе «another operation is in progress» при
  стриминге upsert'ов шагов).
- `@cl.on_chat_start` — `build_agent()`, сохранить в `cl.user_session`.
- `@cl.on_chat_resume` — пересобрать агента при возобновлении треда.
- `@cl.on_message` — прогнать агента **стримингом**:
  ```python
  config = RunnableConfig(callbacks=[cl.LangchainCallbackHandler()])
  async for chunk in agent.astream(state, stream_mode="values", config=config):
      ...
  ```
  Никакого `ainvoke` — он вешает event loop под nest_asyncio Chainlit.
  Финальный ответ — текст через `cl.Message`.

## Поток данных

WS-сообщение → `on_message` → агент стримит поверх Ollama → текстовый ответ.
Chainlit сам пишет треды/шаги в Postgres через data layer.

## Конфигурация окружения (`.env.example`)

| Переменная | Смысл |
|---|---|
| `CHAINLIT_JWT_SECRET` | секрет HS256, общий с datacraft |
| `CHAINLIT_JWT_ISSUER` | `datacraft` |
| `CHAINLIT_JWT_AUDIENCE` | `chainlit` |
| `DATABASE_URL` | asyncpg-строка к chainlit-db |
| `OLLAMA_BASE_URL` | адрес ollama-контейнера (напр. `http://ollama:11434`) |
| `OLLAMA_MODEL` | `gemma3` |

`.chainlit/config.toml` → `allow_origins` включает origin фронта
(`http://localhost:9000`, `http://localhost:8088`) — иначе `/auth/header` и WS с
`credentials:'include'` не пройдут.

## Зависимости

`chainlit`, `deepagents`, `langchain-ollama`, `sqlalchemy`, `asyncpg`, `pyjwt`.
Python 3.13.

## Хранение данных

`init/schema.sql` — официальная схема Chainlit data layer: `users`, `threads`,
`steps`, `elements`, `feedbacks`. Монтируется в `chainlit-db` как init-скрипт.
Изолирована от метадаты Superset, никаких FK на неё.

## Развёртывание

`docker compose up` поднимает три сервиса. При первом запуске нужно один раз
подтянуть модель в ollama (`ollama pull gemma3` внутри контейнера / init-хук).
App ждёт готовности postgres и ollama.

## Критерии готовности

- [ ] `chainlit run app.py` стартует, отдаёт родной socket.io-протокол.
- [ ] `@cl.header_auth_callback` проверяет JWT тем же секретом, отдаёт `cl.User`.
- [ ] `@cl.data_layer` — `SQLAlchemyDataLayer` на Postgres с `NullPool`.
- [ ] `on_chat_start` / `on_chat_resume` / `on_message` собирают и гоняют агента.
- [ ] Агент прогоняется стримингом (не `ainvoke`), отвечает текстом.
- [ ] `build_agent()` — отдельная изолированная функция.
- [ ] `docker compose up` поднимает app + postgres + ollama.
