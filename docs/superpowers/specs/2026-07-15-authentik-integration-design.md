# Дизайн: интеграция authentik (SSO-логин) в lore

Дата: 2026-07-15
Статус: утверждён (секции 1–2 одобрены пользователем)

## Цель и скоуп

Полноценный SSO-логин пользователей через authentik — как в datacraft:
пользователь без сессии видит экран входа, после логина в authentik попадает
в чат под своим именем.

**В скоупе:** аутентификация end-to-end (authentik в compose, OAuth-флоу,
экран логина в SPA, identity в Chainlit).

**Вне скоупа (следующие шаги):** реальный обмен сообщениями через
`chainlitChatProvider` (socket.io, треды, стриминг) — чат после этого шага
остаётся на mock-провайдере; MCP-инструменты (проект — независимая
демонстрация, MCP не планируется); кастомизация флоу authentik (регистрация,
восстановление пароля — стандартные флоу из коробки).

## Выбранный подход

**Встроенный OAuth Chainlit (generic-провайдер), Chainlit — confidential
client.** Рассматривались альтернативы: SPA как public client (Code+PKCE,
JWKS-валидация в `header_auth_callback`) и отдельный BFF, выдающий
HS256-тикеты по образцу datacraft. Выбран встроенный OAuth как вариант с
минимумом нового кода: OIDC-флоу целиком у Chainlit, фронтенду нужен только
вызов логина и проверка сессии.

Известное ограничение подхода: после OAuth-callback Chainlit редиректит на
свой корень (`:8000`, его родной UI), а не в наш React на `:3000`.
Решение — popup-флоу (см. «Поток аутентификации»).

## Архитектура

Новые сервисы в `docker-compose.yml` (по образцу datacraft-app):

| Сервис | Образ | Назначение |
|---|---|---|
| `authentik-server` | `ghcr.io/goauthentik/server:2026.2` | IdP, host-порт **9100** (не 9000 — чтобы не конфликтовать с datacraft-app) |
| `authentik-worker` | тот же | фоновые задачи authentik |
| `authentik-db` | `postgres:16` | выделенная БД authentik (не смешиваем с `chainlit-db`) |
| `authentik-redis` | `redis:alpine` | кэш/очереди authentik |
| `authentik-init` | `python:3.13-slim` | одноразовый bootstrap через API authentik |

`backend` получает `depends_on: authentik-server (condition: service_healthy)`.
Healthcheck authentik — `/-/health/ready/` (как в datacraft).

### Bootstrap (`infra/authentik-bootstrap.py`)

Адаптация `datacraft-app/docker/authentik-bootstrap.py`:

- создаёт OAuth2-провайдера: `client_type=confidential`,
  `sub_mode=user_username`, scopes `openid profile email`,
  подписывающий ключ — авто-selfsigned authentik;
- redirect URI (strict): `http://localhost:8000/auth/oauth/generic/callback`
  (точный путь callback'а сверить с исходниками chainlit при реализации);
- создаёт приложение со слагом `lore`;
- идемпотентен: если приложение `lore` существует — no-op;
- при падении пишет внятную ошибку в лог и не валит остальной стек
  (`restart: "no"`, остальные сервисы от него не зависят).

Дефолтный пользователь — `akadmin`, пароль сеется через
`AUTHENTIK_BOOTSTRAP_PASSWORD`.

## Поток аутентификации

```
Браузер (SPA :3000)        Chainlit (:8000)          authentik (:9100)
   │ 1. GET /user (include)     │                        │
   ├──────────────────────────▶│ 401 → экран логина     │
   │ 2. popup:                  │                        │
   │    /auth/oauth/generic     │                        │
   ├──────────────────────────▶│ 302 ─────────────────▶│
   │ 3. логин в authentik (в popup)                      │
   │ 4. callback + code         │◀───────────────────────┤
   │                            │ обмен code→token,      │
   │                            │ userinfo,              │
   │                            │ @cl.oauth_callback,    │
   │                            │ auth-cookie            │
   │ 5. SPA поллит GET /user; 200 → закрыть popup,       │
   │    показать чат с именем пользователя               │
```

1. SPA при загрузке зовёт `GET {VITE_CHAINLIT_URL}/user` с
   `credentials: 'include'`. 401 → экран логина, 200 → чат.
2. Кнопка «Войти через authentik» открывает **popup** на
   `{VITE_CHAINLIT_URL}/auth/oauth/generic`.
3. После логина callback возвращается в Chainlit, тот через
   `@cl.oauth_callback` создаёт `cl.User` и ставит auth-cookie на
   `localhost:8000`. Popup остаётся на родном UI Chainlit — пользователь его
   почти не видит.
4. SPA поллит `GET /user` (интервал ~1с, таймаут ~60с); при 200 закрывает
   popup (`handle.close()`) и переключается в состояние authenticated.

Popup вместо полного редиректа — из-за фиксированного post-login редиректа
Chainlit на свой корень. **Пункт плана реализации:** проверить в исходниках
установленного Chainlit 2.x, есть ли конфигурируемый redirect после логина;
если есть — заменить popup на редирект всей вкладки.

## Компоненты

### Бэкенд (`backend/`)

- `app.py`: добавить `@cl.oauth_callback` — маппинг userinfo authentik в
  `cl.User(identifier=preferred_username, metadata={"email": ..., "name": ...})`.
  Identifier = username (согласовано с `sub_mode=user_username`).
- `@cl.header_auth_callback` **не удаляется** — оба механизма сосуществуют,
  контракт datacraft-тикетов остаётся рабочим; `CHAINLIT_JWT_*` становятся
  опциональными (нужны только для тикетного пути).
- `auth.py` и существующие тесты не меняются.

### Конфигурация generic OAuth (env бэкенда)

Точные имена переменных сверить с исходниками установленного chainlit;
ожидаемый набор:

| Переменная | Значение (dev-дефолт) |
|---|---|
| `OAUTH_GENERIC_CLIENT_ID` | из `AUTHENTIK_CLIENT_ID` |
| `OAUTH_GENERIC_CLIENT_SECRET` | из `AUTHENTIK_CLIENT_SECRET` |
| `OAUTH_GENERIC_AUTH_URL` | `http://localhost:9100/application/o/authorize/` (browser-facing) |
| `OAUTH_GENERIC_TOKEN_URL` | `http://authentik-server:9000/application/o/token/` (internal) |
| `OAUTH_GENERIC_USER_INFO_URL` | `http://authentik-server:9000/application/o/userinfo/` (internal) |
| `OAUTH_GENERIC_SCOPES` | `openid profile email` |
| `OAUTH_GENERIC_USER_IDENTIFIER` | `preferred_username` |
| `CHAINLIT_URL` | `http://localhost:8000` (иначе redirect_uri построится неверно) |

Разделение browser-facing (`localhost:9100`) и internal
(`authentik-server:9000`) URL — тот же паттерн, что
`AUTHENTIK_BASE_URL` / `AUTHENTIK_INTERNAL_URL` в datacraft.

### Фронтенд (`frontend/`)

- Новый модуль `src/auth/`:
  - `authClient.ts`: `getCurrentUser()` → `GET /user`; `login()` → popup +
    поллинг; `logout()` → `POST /logout` (оба с `credentials: 'include'`);
  - `useAuth.ts`: хук с состояниями `loading | anonymous | authenticated(user)`.
- `App.tsx`: `loading` → спиннер; `anonymous` → экран логина с кнопкой
  «Войти через authentik»; `authenticated` → существующий чат, в сайдбаре —
  имя пользователя и кнопка выхода.
- Базовый URL — существующий `VITE_CHAINLIT_URL`. Новых npm-зависимостей нет.

### Инфраструктура

- `docker-compose.yml`: +5 сервисов (см. таблицу), новые env у `backend`.
- `infra/authentik-bootstrap.py` (новая папка `infra/` в корне).
- `.env.example`: `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_BOOTSTRAP_TOKEN`,
  `AUTHENTIK_BOOTSTRAP_PASSWORD`, `AUTHENTIK_CLIENT_ID`,
  `AUTHENTIK_CLIENT_SECRET`, `AUTHENTIK_PORT=9100`. Все — с dev-дефолтами
  в compose (как остальные переменные проекта).
- CORS: `http://localhost:3000` уже в `allow_origins`
  (`backend/.chainlit/config.toml`) — для `GET /user` / `POST /logout` с
  `credentials: 'include'` этого достаточно.

## Обработка ошибок

- **authentik недоступен:** popup не откроет страницу логина / вернёт 5xx;
  поллинг SPA завершается по таймауту (~60с) с сообщением «Не удалось войти,
  попробуйте ещё раз» и возвратом на экран логина.
- **Пользователь закрыл popup:** поллинг обнаруживает `handle.closed` и
  останавливается без ошибки.
- **Невалидный code / протухший обмен:** Chainlit сам вернёт 401, cookie не
  появится — SPA остаётся на экране логина.
- **Bootstrap упал** (нет токена, authentik не поднялся): понятная ошибка в
  `docker compose logs authentik-init`; чат продолжает работать в mock-режиме.

## Тестирование

- **Юнит (бэкенд):** тест маппинга `oauth_callback`
  (raw_user_data → `cl.User`), рядом с существующими тестами.
- **Smoke после `docker compose up`:**
  - `GET :8000/auth/config` содержит generic-oauth провайдера;
  - `GET :8000/auth/oauth/generic` → 302 на `localhost:9100`;
  - лог `authentik-init` — «setup complete» или «already exists»;
  - `GET :9100/-/health/ready/` → 2xx.
- **E2E (вручную):** открыть `:3000` → экран логина → popup → вход `akadmin`
  → popup закрылся, в сайдбаре имя пользователя; logout возвращает на экран
  логина.

## Открытые пункты для этапа реализации

1. Сверить точные имена `OAUTH_GENERIC_*` переменных и путь callback'а с
   исходниками установленной версии Chainlit.
2. Проверить, поддерживает ли Chainlit 2.x конфигурируемый post-login
   redirect; если да — заменить popup-флоу на редирект всей вкладки.
3. Уточнить минимальный набор обязательных env authentik
   (`AUTHENTIK_SECRET_KEY` и bootstrap-переменные) по документации версии
   2026.2.
