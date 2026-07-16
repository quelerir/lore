# Развертывание lore

Документация по развертыванию и эксплуатации стека. Про работу с уже
запущенным сервисом — см. [usage.md](usage.md).

## Архитектура

```
Браузер ──:3000──▶ frontend (nginx, React SPA)
   │
   ├────:8000──▶ backend (Chainlit + deepagents)
   │                 ├──▶ chainlit-db (Postgres 16, история чатов)
   │                 ├──▶ authentik-server:9000 (обмен code→token, userinfo)
   │                 ├──▶ OpenRouter API (LLM по умолчанию) / Ollama :11434 (фолбэк)
   │                 └──▶ TOAST-БД loreagent_test (опц., query_document_tables)
   │
   └────:9100──▶ authentik-server (IdP, SSO)
                     ├──▶ authentik-db (Postgres 16)
                     ├──▶ authentik-redis
                     └──  authentik-worker (фоновые задачи)

authentik-init — one-shot контейнер: создаёт OAuth2-провайдера и
приложение `lore` в authentik при первом старте, дальше no-op.
```

| Сервис | Порт хоста | Назначение |
|---|---|---|
| frontend | 3000 | SPA чата (nginx) |
| backend | 8000 | Chainlit API/WS |
| authentik-server | 9100 | IdP: логин, админка |
| chainlit-db, authentik-db, authentik-redis | — | только внутренняя сеть |

## Требования

- Docker с Compose v2 (проверено на Docker 29 / Compose v5).
- ~4 ГБ свободной RAM для стека (authentik — самый тяжёлый).
- **Ключ OpenRouter** (`OPENROUTER_API_KEY`) — провайдер модели по
  умолчанию. Запиши его в `.env` перед стартом (без него бэкенд
  поднимется, но запросы к агенту будут падать).
- [Ollama](https://ollama.com) на хосте нужна, **только** если выбран
  локальный фолбэк `MODEL_PROVIDER=ollama` (в compose не входит):

```bash
ollama serve        # если ещё не запущена
ollama pull gemma3  # модель по умолчанию
```

## Быстрый старт

```bash
git clone <repo> lore && cd lore
docker compose up -d --build
```

Первый старт занимает пару минут: authentik инициализирует БД, затем
`authentik-init` создаёт OAuth-приложение. Готовность:

```bash
docker compose ps                       # все Up, server/db — healthy
docker compose logs authentik-init     # "authentik setup complete!"
```

Открыть http://localhost:3000, войти: `akadmin` / `admin`
(пароль — `AUTHENTIK_BOOTSTRAP_PASSWORD`).

## Конфигурация

Почти все переменные имеют рабочие dev-дефолты в `docker-compose.yml` —
исключение `OPENROUTER_API_KEY` (пустой, задать обязательно при провайдере
по умолчанию). Переопределение — через `.env` в корне
(`cp .env.example .env`).

| Переменная | Дефолт | Смысл |
|---|---|---|
| `FRONTEND_PORT` | `3000` | host-порт SPA |
| `BACKEND_PORT` | `8000` | host-порт Chainlit |
| `AUTHENTIK_PORT` | `9100` | host-порт authentik |
| `CHAINLIT_PUBLIC_URL` | `http://localhost:8000` | URL бэкенда, каким его видит браузер; из него же строится OAuth redirect_uri |
| `AUTHENTIK_PUBLIC_URL` | `http://localhost:9100` | browser-facing URL authentik (согласован с `AUTHENTIK_PORT`) |
| `CHAT_PROVIDER` | `mock` | провайдер чата SPA: `mock` \| `chainlit` (build-time: пересобрать frontend) |
| `OPENROUTER_API_KEY` | — (пусто) | ключ OpenRouter; **обязателен** при `MODEL_PROVIDER=openrouter` |
| `MODEL_PROVIDER` | `openrouter` | провайдер модели: `openrouter` (по умолчанию) \| `ollama` (фолбэк) |
| `OPENROUTER_MODEL` | `anthropic/claude-haiku-4.5` | модель OpenRouter |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | эндпоинт OpenRouter |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | адрес Ollama из контейнера (только при `MODEL_PROVIDER=ollama`) |
| `OLLAMA_MODEL` | `gemma3` | модель Ollama |
| `TOAST_DATABASE_URL` | — (пусто) | read-only DSN к TOAST-таблицам `loreagent_test`; пусто — только калькулятор, задан — инструмент `query_document_tables` |
| `AUTHENTIK_SECRET_KEY` | dev-значение | секрет authentik (сессии, подписи) |
| `AUTHENTIK_BOOTSTRAP_PASSWORD` | `admin` | пароль `akadmin`; применяется только при первой инициализации БД authentik |
| `AUTHENTIK_BOOTSTRAP_TOKEN` | dev-значение | admin API-токен для bootstrap-скрипта; тоже сеется однократно |
| `AUTHENTIK_CLIENT_ID` / `_SECRET` | `lore-chainlit` / dev-значение | OAuth2-клиент Chainlit (создаётся bootstrap-скриптом) |
| `CHAINLIT_AUTH_SECRET` | dev-значение | секрет сессий Chainlit |
| `CHAINLIT_JWT_SECRET` / `_AUDIENCE` / `_ISSUER` | dev / `chainlit` / `datacraft` | проверка header-auth тикетов (параллельный datacraft-контракт; для SSO не нужны) |

**Важно про bootstrap-переменные:** `AUTHENTIK_BOOTSTRAP_*` применяются
только при первой инициализации тома `authentik-db-data`. Смена пароля
akadmin после этого — через админку authentik, смена API-токена — тоже
(Directory → Tokens).

## Данные и тома

| Том | Содержимое | Потеря при удалении |
|---|---|---|
| `chainlit-db-data` | пользователи, треды, сообщения чата | вся история чатов |
| `authentik-db-data` | конфигурация authentik, пользователи, OAuth-приложение | все аккаунты; bootstrap отработает заново |

Полный сброс (удаляет ВСЕ данные):

```bash
docker compose down -v
docker compose up -d --build   # чистая инициализация + bootstrap заново
```

Схема `backend/init/schema.sql` применяется только при первой инициализации
тома `chainlit-db-data`; миграций нет — при изменении схемы том нужно
пересоздавать (или накатывать изменения вручную).

## Обновление

```bash
git pull
docker compose up -d --build    # пересоберёт backend/frontend, перезапустит изменённое
```

`CHAT_PROVIDER` и `CHAINLIT_PUBLIC_URL` вшиваются во frontend на этапе
сборки — после их смены обязательно `docker compose up -d --build frontend`.

## Эксплуатация

```bash
docker compose ps                          # статусы
docker compose logs -f backend             # логи Chainlit
docker compose logs -f authentik-server    # логи IdP
docker compose restart backend             # перезапуск одного сервиса
docker compose down                        # остановить всё (данные сохраняются)
```

Тесты бэкенда (в контейнере, локальный Python не нужен):

```bash
docker run --rm -v "$PWD/backend:/app" -w /app lore-backend \
  sh -c "uv pip install -q pytest && pytest -q"
```

## Развертывание вне localhost

Dev-дефолты рассчитаны на локальную машину. Чеклист для стенда/прода:

1. **Все секреты** из `.env.example` заменить на сгенерированные
   (`openssl rand -base64 36`); `CHAINLIT_AUTH_SECRET` — через
   `chainlit create-secret`. Пароли Postgres в compose (`chainlit`/`authentik`)
   тоже параметризовать при внешней доступности БД.
2. **Домены и TLS.** Поставить reverse-proxy (traefik/caddy/nginx) перед
   frontend, backend и authentik; выставить:
   - `CHAINLIT_PUBLIC_URL=https://chat-api.example.com`
   - `AUTHENTIK_PUBLIC_URL=https://auth.example.com`
   - домен фронтенда — в `allow_origins`
     (`backend/.chainlit/config.toml`).
3. **Redirect URI.** Bootstrap-скрипт заводит redirect
   `${CHAINLIT_PUBLIC_URL}/auth/oauth/generic/callback` только при первом
   старте. При смене домена позже — поправить в админке authentik
   (Applications → Providers → Lore Chat).
4. **Cookie.** За HTTPS-прокси выставить у backend
   `CHAINLIT_COOKIE_SAMESITE=none` (Chainlit тогда включит `Secure`),
   если фронтенд и бэкенд на разных доменах.
5. **Ollama.** На отдельном хосте — указать `OLLAMA_BASE_URL`; секция
   `extra_hosts` нужна только для host-gateway сценария.
6. **Рестарт-политики.** В compose сейчас нет `restart: unless-stopped` —
   для стенда добавить всем длительным сервисам (см. docs/improvements.md).

## Troubleshooting

| Симптом | Причина / решение |
|---|---|
| `authentik-server` долго `health: starting` | нормально при первом старте (миграции БД, до ~2 мин); смотреть `logs authentik-server` |
| `authentik-init` упал с 403 | bootstrap-токен не принят: том `authentik-db-data` был создан со старым `AUTHENTIK_BOOTSTRAP_TOKEN`; либо вернуть старое значение, либо выдать токен в админке, либо `down -v` |
| Popup логина: `redirect_uri mismatch` | `CHAINLIT_PUBLIC_URL` не совпадает с redirect URI в authentik — поправить в админке (Providers) |
| После логина SPA не «отлипает» (401 на `/user`) | cookie не дошла: проверить, что фронтенд-origin есть в `allow_origins`, а при HTTPS/другом домене — `CHAINLIT_COOKIE_SAMESITE=none` |
| Ответы чата не приходят (после включения `chainlit`-провайдера) | При `MODEL_PROVIDER=openrouter`: не задан/неверен `OPENROUTER_API_KEY` — смотреть `docker compose logs backend`. При `MODEL_PROVIDER=ollama`: Ollama недоступна — `curl http://localhost:11434/api/tags` на хосте, проверить `OLLAMA_BASE_URL`, `ollama pull gemma3` |
| `query_document_tables` не работает / агент говорит, что таблиц нет | не задан `TOAST_DATABASE_URL` (тогда доступен только калькулятор) либо DSN недоступен из контейнера |
| Порт 9100/3000/8000 занят | поменять `AUTHENTIK_PORT` (+ `AUTHENTIK_PUBLIC_URL`), `FRONTEND_PORT`, `BACKEND_PORT` (+ `CHAINLIT_PUBLIC_URL`) в `.env` |
| `backend` перезапускается с `ValueError ... oauth provider` | заданы не все `OAUTH_GENERIC_*` (частичная конфигурация); задать все или убрать `OAUTH_GENERIC_CLIENT_ID` |
