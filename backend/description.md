# Контракт интеграции Chainlit-сервиса с фронтендом datacraft

Этот документ описывает точки сопряжения, которым обязан соответствовать
Chainlit-сервис, чтобы подключиться к фронтенду datacraft (форк Apache Superset).
Если соблюсти эти контракты, внутренности сервиса (агент) можно переписать —
например, на deepagents — и фронтенд не заметит разницы.

Кастомна тут только фронтовая обёртка UI (assistant-ui поверх Chainlit-WS);
нативный UI Chainlit не используется.

Ключевые файлы фронта: `superset-frontend/src/views/dashboardAiChat/`.
Ключевые файлы бэка datacraft: `superset/datacraft/services/chainlit_chat/`,
`superset/datacraft/ai/dashboard_chat/`, `superset/datacraft/ai/charts/`.

---

## 0. Главное: сервис ДОЛЖЕН быть настоящим Chainlit-приложением

Фронт подключается через `@chainlit/react-client` (`ChainlitAPI`, socket.io
WebSocket) + `@assistant-ui/react` поверх него. То есть он говорит на **родном
протоколе Chainlit** (socket.io-события, endpoint `/auth/header`, отдача файлов
через `/project/file/...`). Свой сервис — это `chainlit run app.py`; кастомная
логика (deepagents) заменяет только то, что происходит внутри `@cl.on_message`.
Своё «голое» WS-API писать нельзя — сломается клиент.

---

## 1. Точки подключения, которые фронт жёстко ожидает

### 1a. Аутентификация — `@cl.header_auth_callback` + endpoint `/auth/header`

Handshake фронта (`api.ts`) состоит из двух шагов:

1. `POST /api/v1/chainlit/ticket` к **datacraft-бэку** → короткий JWT-тикет
   (HS256, `aud=chainlit`, `iss=datacraft`, TTL ~60с).
2. `POST {CHAINLIT_SERVER_URL}/auth/header` с `Authorization: Bearer <ticket>`
   и `credentials: 'include'` → Chainlit проверяет тикет и ставит
   **session-cookie**. Дальше WS-сессия авторизуется этой кукой (в Chainlit 2.x
   при самом WS заголовок не читается — только кука).

Твой сервис обязан реализовать `@cl.header_auth_callback`, который:
- достаёт Bearer из заголовка `Authorization`;
- локально проверяет JWT секретом `CHAINLIT_JWT_SECRET` (HS256), сверяет
  `aud` / `iss` / `exp` / `sub`;
- возвращает `cl.User(identifier=str(sub), metadata={"username": ...})`.

`identifier` = `sub` — на нём завязана привязка тредов к пользователю в data
layer. Секрет обязан совпадать с тем, что datacraft кладёт в тикет.
Текущая реализация симметричная (HS256, общий секрет), не JWKS/RS256.

### 1b. Профили чата — `@cl.set_chat_profiles`, имена ровно `charts` и `analyst`

Фронт хардкодит имена профилей в `modes.ts` (`ChatMode = 'charts' | 'analyst'`)
и шлёт выбранный профиль в WS-авторизацию через Recoil-атом (`setChatProfile`).
Если имена не совпадут — реконнект в нужный режим не отработает. Новый сервис
должен вернуть те же два имени (либо параллельно править `modes.ts`).

- `charts` — ассистент по графикам дашборда (ходит в MCP-инструменты).
- `analyst` — plotly-аналитик (строит интерактивный график).

### 1c. Data layer — `@cl.data_layer` на Postgres

Фронт умеет **листать и возобновлять** треды, завязываясь на стабильные
`thread_id` из Chainlit. Нужен `SQLAlchemyDataLayer` на Postgres.
Важный нюанс: движок создавать с `poolclass=NullPool` — иначе при стриминге
ловишь «another operation is in progress» на параллельных upsert'ах шагов.

### 1d. Обработчики жизненного цикла

- `@cl.on_chat_start` — собрать агента под выбранный профиль; прочитать
  `dashboard_id` и `datacraft_token` из сессии (см. раздел 2).
- `@cl.on_chat_resume` — пересобрать агента при возобновлении треда.
- `@cl.on_message` — прогнать агента и отправить ответ.

### 1e. Формат ответа: текст + `cl.Plotly` inline

График возвращается как `cl.Plotly(name="chart", figure=fig, display="inline")`.
Фронт (`MessageCharts.tsx` → `LazyPlot.tsx`) забирает элементы `type==='plotly'`
по `forId` и **дотягивает JSON фигуры отдельным fetch'ем** с
`{CHAINLIT_SERVER_URL}/project/file/...` c `credentials: 'include'`. Это работает
само, если использовать `cl.Plotly`. Инлайн-описания графиков рендерятся из
текста сообщения.

---

## 2. Контракт `userEnv` — как приходит контекст и права

При коннекте фронт передаёт (`useChainlitRuntime.ts`):

```js
connect({ accessToken, userEnv: { dashboard_id, datacraft_token } })
```

- `datacraft_token` — **act-as-user** токен; фронт берёт его из
  `POST /api/v1/chainlit/api_token`. Этим токеном агент ходит в datacraft/MCP
  **от имени пользователя** (least-privilege, caller-binding). Личность и scope
  НИКОГДА не выбирает LLM — только userEnv/headers.
- `dashboard_id` — scope дашборда. Дублируется в `metadata` каждого
  user-сообщения.

Внутри `on_chat_start` эти значения доступны через `cl.user_session`. Когда
агент зовёт инструменты, он должен форвардить их как заголовки:

- `Authorization: Bearer <datacraft_token>`
- `X-Dashboard-Id: <dashboard_id>`

MCP-прокси (`datacraft-mcp/server.py`) именно из этих заголовков достаёт
auth + scope. Инварианты `get_data`: `force=True` (bypass cache), raw SQL по
умолчанию не отдаём.

---

## 3. Хранение данных — две независимые БД

**БД №1 — Chainlit Postgres (владелец — твой сервис).** Отдельный инстанс
(`chainlit-db` в compose), схема в `init/schema.sql`: `users`, `threads`,
`steps` (сообщения и tool-вызовы), `elements` (в т.ч. plotly), `feedbacks`.
Полностью изолирована от метадаты Superset, никаких FK на неё. Здесь живёт вся
история диалогов.

**БД №2 — datacraft metadata (владелец — бэкенд Superset, ты её НЕ трогаешь).**
Таблица `dashboard_ai_chat` — лёгкий индекс, связывающий
`(dashboard_id, user_id) → chainlit_thread_id + title + mode`. Когда Chainlit
создаёт тред, фронт регистрирует его id обратно через
`POST /api/v1/dashboard_ai_chat/<dashboard_id>`.

Ключевое требование: **thread_id должен быть настоящим Chainlit thread_id из data
layer** — иначе список чатов и resume рассыплются.

---

## 4. Конфигурация окружения (contract-level)

| Переменная | Где | Смысл |
|---|---|---|
| `CHAINLIT_SERVER_URL` | datacraft bootstrap (`common.conf`) | фронт берёт базовый URL; указывает на твой сервис |
| `CHAINLIT_JWT_SECRET` | обе стороны | **обязан совпасть** с секретом datacraft |
| `CHAINLIT_JWT_ISSUER` / `_AUDIENCE` | обе стороны | `datacraft` / `chainlit` |
| `DATABASE_URL` | твой сервис | asyncpg-строка к Chainlit Postgres |
| `allow_origins` в `.chainlit/config.toml` | твой сервис | обязан включать origin фронта (напр. `http://localhost:9000`, `:8088`) — иначе `/auth/header` и WS с `credentials:'include'` не пройдут |

---

## 5. Где садится агентная логика (deepagents) и грабли

Заменяешь **только сборку и прогон агента** внутри `on_chat_start` / `on_message`.
Ответ по-прежнему: финальный текст + опциональный `cl.Plotly`.

Критичная грабля: гонять граф **только стримингом** (`astream` / `astream_events`).
`ainvoke` + `cl.LangchainCallbackHandler` вешает event loop под nest_asyncio
Chainlit (дедлок). Текущий код использует:

```python
config = RunnableConfig(callbacks=[cl.LangchainCallbackHandler()])
async for result in agent.astream(state, stream_mode="values", config=config):
    pass
```

deepagents/LangGraph совместимы с этим — сохрани стриминг.

---

## 6. Поток подключения (сводка)

1. **Init** (фронт):
   - `POST /api/v1/chainlit/ticket` → JWT-тикет.
   - `POST {CHAINLIT_SERVER_URL}/auth/header` с `Bearer <ticket>` → session-cookie.
   - `POST /api/v1/chainlit/api_token` → `datacraft_token`.
   - `GET /api/v1/dashboard_ai_chat/<dashboard_id>` → список чатов.
2. **Connect** (фронт → Chainlit WS): `connect({ userEnv: { dashboard_id, datacraft_token } })`,
   выбранный `chatProfile` = `charts` | `analyst`.
3. **Message**: user-сообщение → `on_message` → агент (стриминг) → MCP-инструменты
   с форвардом `Authorization` + `X-Dashboard-Id` → ответ (текст + опц. `cl.Plotly`).
4. **Persist**: Chainlit сам пишет треды/шаги/элементы в свою Postgres; фронт
   регистрирует `chainlit_thread_id` в `dashboard_ai_chat` datacraft-бэка.

---

## 7. Чек-лист «мой сервис готов подключиться»

- [ ] Это `chainlit run` приложение (родной socket.io-протокол).
- [ ] `@cl.header_auth_callback` проверяет datacraft-JWT тем же секретом,
      возвращает `cl.User(identifier=sub)`.
- [ ] `@cl.set_chat_profiles` → профили с именами `charts` и `analyst`.
- [ ] `@cl.data_layer` → `SQLAlchemyDataLayer` на Postgres с `NullPool`.
- [ ] `on_chat_start` / `on_chat_resume` / `on_message` читают `dashboard_id`
      и `datacraft_token` из `user_session`.
- [ ] Инструменты форвардят `Authorization: Bearer <datacraft_token>`
      и `X-Dashboard-Id`.
- [ ] Агент прогоняется стримингом (не `ainvoke`).
- [ ] Ответ = текст + опц. `cl.Plotly(display="inline")`.
- [ ] CORS в `config.toml` разрешает origin фронта.
- [ ] `CHAINLIT_SERVER_URL`, `CHAINLIT_JWT_*`, `DATABASE_URL` выставлены
      и согласованы с datacraft.

---

## Ссылки на код

- Фронт-подключение / auth / рендер: `superset-frontend/src/views/dashboardAiChat/`
  (`api.ts`, `DashboardAiChatPanel.tsx`, `useChainlitRuntime.ts`, `modes.ts`,
  `MessageCharts.tsx`, `LazyPlot.tsx`, `convertMessage.ts`).
- Datacraft-бэк (тикеты, api_token, config):
  `superset/datacraft/services/chainlit_chat/{api.py, jwt.py}`,
  `superset/datacraft/config.py`.
- Datacraft-бэк (индекс чатов, AI-charts):
  `superset/datacraft/ai/dashboard_chat/{models.py, api.py}`,
  `superset/datacraft/ai/charts/api.py`.
- MCP-прокси (caller-binding): `datacraft-mcp/server.py`.
- Действующая реализация Chainlit-сервиса (референс):
  `datacraft-chainlit/{app.py, profiles.py, tickets.py, agents/, init/schema.sql}`.
- Дизайн рерайта на deepagents:
  `docs/superpowers/specs/2026-07-09-chainlit-deepagents-rewrite-design.md`.
