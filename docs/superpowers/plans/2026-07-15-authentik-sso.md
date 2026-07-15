# Authentik SSO Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SSO-логин через authentik: пользователь без сессии видит экран входа, после логина в authentik попадает в чат под своим именем.

**Architecture:** authentik поднимается в том же docker-compose (server, worker, db, redis + одноразовый bootstrap-init, создающий OAuth2-провайдера и приложение через API). Chainlit выступает confidential OIDC-клиентом через встроенный generic OAuth-провайдер (env `OAUTH_GENERIC_*` + `@cl.oauth_callback`). React SPA логинит пользователя popup-окном и определяет сессию поллингом `GET /user`.

**Tech Stack:** Chainlit 2.11.1 (generic OAuth), authentik 2026.2, React 19 + Vite (без новых npm-зависимостей), docker compose.

**Спека:** `docs/superpowers/specs/2026-07-15-authentik-integration-design.md`

## Global Constraints

- Chainlit зафиксирован на 2.11.1 (поведение проверено по исходникам в образе `lore-backend`): callback-путь `GET /auth/oauth/generic/callback`; redirect_uri строится из env `CHAINLIT_URL`; auth-cookie `access_token`, `SameSite=Lax` (localhost:3000 → localhost:8000 — same-site, cookie ходит).
- Post-login redirect Chainlit ведёт на его собственный UI и НЕ конфигурируется (в исходниках FIXME) — поэтому popup-флоу, полный редирект не делать.
- `@cl.oauth_callback` кидает `ValueError` на импорте, если generic-провайдер не сконфигурирован (нужны все шесть env: CLIENT_ID, CLIENT_SECRET, AUTH_URL, TOKEN_URL, USER_INFO_URL, SCOPES) — регистрация в `app.py` обязана быть условной.
- authentik публикуется на host-порту **9100** (9000 занят datacraft-app).
- Все новые env-переменные имеют рабочие dev-дефолты прямо в `docker-compose.yml` (паттерн проекта); `.env.example` документирует их.
- `auth.py`, header-auth и существующие тесты бэкенда не меняются.
- UI-тексты — на русском, стиль существующих компонентов (CSS-модули, палитра `#334155`/`#eef2f7`, радиусы 12px).
- Локальный Node — v16 (слишком стар для Vite 6): проверка типов/сборка фронтенда только через `docker compose build frontend`.
- Проверка тестов бэкенда — в контейнере образа `lore-backend` (см. команды в задачах).

## File Structure

| Файл | Ответственность |
|---|---|
| `docker-compose.yml` (modify) | +5 сервисов authentik, env `OAUTH_GENERIC_*` у backend |
| `.env.example` (modify) | новые переменные authentik |
| `infra/authentik-bootstrap.py` (create) | идемпотентное создание OAuth2-провайдера и приложения `lore` |
| `backend/app.py` (modify) | `oauth_user()` + условная регистрация `cl.oauth_callback` |
| `backend/tests/test_oauth.py` (create) | юнит-тесты маппинга userinfo → `cl.User` |
| `frontend/src/auth/authClient.ts` (create) | HTTP-клиент: `getCurrentUser`, `loginWithPopup`, `logout` |
| `frontend/src/auth/useAuth.ts` (create) | хук состояния `loading / anonymous / authenticated` |
| `frontend/src/components/LoginScreen/*` (create) | экран входа |
| `frontend/src/App.tsx` (modify) | гейт по состоянию auth |
| `frontend/src/components/Sidebar/*` (modify) | футер: имя пользователя + выход |
| `README.md` (modify) | раздел про SSO, порт 9100, akadmin |

---

### Task 1: Сервисы authentik в docker-compose

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Produces: сервисы `authentik-server` (healthy на `http://authentik-server:9000` внутри сети, `http://localhost:9100` снаружи), `authentik-db`, `authentik-redis`, `authentik-worker`; YAML-якорь `&authentik-env`; volume `authentik-db-data`. Env-переменные: `AUTHENTIK_PORT`, `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_BOOTSTRAP_PASSWORD`, `AUTHENTIK_BOOTSTRAP_TOKEN`.

- [ ] **Step 1: Добавить сервисы в `docker-compose.yml`**

Вставить после сервиса `chainlit-db` (перед комментарием про Ollama):

```yaml
  # --- authentik (SSO) ------------------------------------------------------

  authentik-db:
    image: postgres:16
    environment:
      POSTGRES_USER: authentik
      POSTGRES_PASSWORD: authentik
      POSTGRES_DB: authentik
    volumes:
      - authentik-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U authentik"]
      interval: 5s
      timeout: 5s
      retries: 5

  authentik-redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD-SHELL", "redis-cli ping | grep PONG"]
      interval: 5s
      timeout: 3s
      retries: 5

  authentik-server:
    image: ghcr.io/goauthentik/server:2026.2
    command: server
    environment: &authentik-env
      AUTHENTIK_SECRET_KEY: ${AUTHENTIK_SECRET_KEY:-dev-only-authentik-secret-key-change-me}
      AUTHENTIK_REDIS__HOST: authentik-redis
      AUTHENTIK_POSTGRESQL__HOST: authentik-db
      AUTHENTIK_POSTGRESQL__USER: authentik
      AUTHENTIK_POSTGRESQL__PASSWORD: authentik
      AUTHENTIK_POSTGRESQL__NAME: authentik
      # Сеются один раз при первой инициализации БД authentik.
      AUTHENTIK_BOOTSTRAP_PASSWORD: ${AUTHENTIK_BOOTSTRAP_PASSWORD:-admin}
      AUTHENTIK_BOOTSTRAP_TOKEN: ${AUTHENTIK_BOOTSTRAP_TOKEN:-dev-only-bootstrap-api-token-change-me}
      AUTHENTIK_ERROR_REPORTING__ENABLED: "false"
    ports:
      - "${AUTHENTIK_PORT:-9100}:9000"
    depends_on:
      authentik-db:
        condition: service_healthy
      authentik-redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://localhost:9000/-/health/ready/ > /dev/null || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 60s

  authentik-worker:
    image: ghcr.io/goauthentik/server:2026.2
    command: worker
    environment: *authentik-env
    depends_on:
      authentik-db:
        condition: service_healthy
      authentik-redis:
        condition: service_healthy
```

В блок `volumes:` внизу файла добавить:

```yaml
  authentik-db-data:
```

- [ ] **Step 2: Дополнить `.env.example`**

Добавить в конец файла:

```bash
# --- authentik (SSO) ---
# Host-порт authentik (9100, чтобы не конфликтовать с datacraft-app на 9000)
AUTHENTIK_PORT=9100
# Browser-facing URL authentik; должен согласовываться с AUTHENTIK_PORT
AUTHENTIK_PUBLIC_URL=http://localhost:9100
AUTHENTIK_SECRET_KEY=dev-only-authentik-secret-key-change-me
# Пароль пользователя akadmin (сеется при первом старте)
AUTHENTIK_BOOTSTRAP_PASSWORD=admin
# API-токен для bootstrap-скрипта (сеется при первом старте)
AUTHENTIK_BOOTSTRAP_TOKEN=dev-only-bootstrap-api-token-change-me
# OAuth2-клиент, создаваемый bootstrap-скриптом для Chainlit
AUTHENTIK_CLIENT_ID=lore-chainlit
AUTHENTIK_CLIENT_SECRET=dev-only-oauth-client-secret-change-me
```

- [ ] **Step 3: Проверить конфиг и поднять authentik**

Run: `docker compose config --quiet && docker compose up -d authentik-server authentik-worker`
Expected: без ошибок; образы скачаются при первом запуске (~1–2 мин).

- [ ] **Step 4: Дождаться готовности и проверить**

Run: `sleep 90 && docker compose ps authentik-server --format '{{.Status}}' && curl -s -o /dev/null -w '%{http_code}\n' http://localhost:9100/-/health/ready/`
Expected: `Up ... (healthy)` и `204` (или `200`). Если `starting` — подождать ещё 30с и повторить.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat: add authentik services (server, worker, db, redis) to compose"
```

---

### Task 2: Bootstrap-скрипт authentik + init-сервис

**Files:**
- Create: `infra/authentik-bootstrap.py`
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: healthy `authentik-server` (Task 1), env `AUTHENTIK_BOOTSTRAP_TOKEN`.
- Produces: в authentik существуют OAuth2-провайдер (confidential, `client_id` из `AUTHENTIK_CLIENT_ID`, redirect `http://localhost:8000/auth/oauth/generic/callback`, `sub_mode=user_username`, scopes openid/profile/email) и приложение со слагом `lore`. Сервис `authentik-init` (one-shot).

- [ ] **Step 1: Создать `infra/authentik-bootstrap.py`**

Адаптация `datacraft-app/docker/authentik-bootstrap.py` (тот же API-клиент, один redirect URI, слаг `lore`):

```python
#!/usr/bin/env python3
"""
Bootstrap локального authentik: создаёт OAuth2-провайдера и приложение,
чтобы Chainlit (generic OAuth) работал сразу после `docker compose up`.

Запускается one-shot init-контейнером после готовности authentik.
Идемпотентен: если приложение уже существует — no-op.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

AUTHENTIK_URL = os.environ.get("AUTHENTIK_INTERNAL_URL", "http://authentik-server:9000")
API_TOKEN = os.environ["AUTHENTIK_BOOTSTRAP_TOKEN"]
CLIENT_ID = os.environ["AUTHENTIK_CLIENT_ID"]
CLIENT_SECRET = os.environ["AUTHENTIK_CLIENT_SECRET"]
APP_SLUG = os.environ.get("AUTHENTIK_APP_SLUG", "lore")
APP_NAME = os.environ.get("AUTHENTIK_APP_NAME", "Lore Chat")
REDIRECT_URI = os.environ.get(
    "AUTHENTIK_REDIRECT_URI", "http://localhost:8000/auth/oauth/generic/callback"
)
FRONTEND_URL = os.environ.get("LORE_FRONTEND_URL", "http://localhost:3000")

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def api_request(method: str, path: str, data: dict | None = None) -> dict:
    url = f"{AUTHENTIK_URL}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"API error {e.code} on {method} {path}: {error_body}", file=sys.stderr)
        raise


def wait_for_authentik(timeout: int = 300) -> None:
    # /-/health/ready/ становится ready раньше, чем worker просеет bootstrap
    # API-токен, поэтому дополнительно поллим аутентифицированный endpoint.
    print("Waiting for authentik to be ready...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{AUTHENTIK_URL}/-/health/ready/")
            with urllib.request.urlopen(req, timeout=5):
                break
        except Exception:
            time.sleep(5)
    else:
        print("ERROR: authentik did not become ready in time!", file=sys.stderr)
        sys.exit(1)

    while time.time() < deadline:
        req = urllib.request.Request(
            f"{AUTHENTIK_URL}/api/v3/core/applications/?page_size=1", headers=HEADERS
        )
        try:
            with urllib.request.urlopen(req, timeout=5):
                print("authentik is ready!")
                return
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
        except Exception:
            pass
        time.sleep(5)
    print("ERROR: bootstrap token was not accepted in time!", file=sys.stderr)
    sys.exit(1)


def app_exists() -> bool:
    result = api_request("GET", f"/api/v3/core/applications/?slug={APP_SLUG}")
    return result["pagination"]["count"] > 0


def get_flow(designation: str, prefer_keyword: str = "") -> str:
    result = api_request(
        "GET", f"/api/v3/flows/instances/?designation={designation}&ordering=slug"
    )
    flows = result.get("results", [])
    if prefer_keyword:
        for flow in flows:
            if prefer_keyword in flow["slug"]:
                return flow["pk"]
    if flows:
        return flows[0]["pk"]
    raise RuntimeError(f"No {designation} flow found in authentik!")


PROPERTY_MAPPING_PATHS = (
    "/api/v3/propertymappings/provider/scope/?ordering=scope_name&page_size=100",
    "/api/v3/propertymappings/scope/?ordering=scope_name&page_size=100",
)
REQUIRED_SCOPE_NAMES = frozenset({"openid", "profile", "email"})


def get_scope_mappings(timeout: int = 120) -> list[str]:
    """Дождаться дефолтных OIDC scope-маппингов и вернуть их UUID.

    Worker authentik сеет openid/profile/email асинхронно после health-ready.
    Если создать провайдера раньше — в userinfo не будет preferred_username.
    """
    working_path: str | None = None
    for path in PROPERTY_MAPPING_PATHS:
        try:
            api_request("GET", path)
        except urllib.error.HTTPError:
            continue
        working_path = path
        break
    if working_path is None:
        print("ERROR: no propertymappings API path responded.", file=sys.stderr)
        sys.exit(1)

    print("Waiting for default OIDC scope mappings to be seeded...")
    deadline = time.time() + timeout
    present: set[str] = set()
    results: list[dict] = []
    while time.time() < deadline:
        results = api_request("GET", working_path).get("results", [])
        present = {r.get("scope_name") for r in results if r.get("scope_name")}
        if REQUIRED_SCOPE_NAMES.issubset(present):
            return [r["pk"] for r in results]
        time.sleep(2)

    missing = sorted(REQUIRED_SCOPE_NAMES - present)
    print(
        f"ERROR: default OIDC scope mappings not seeded in time, missing: {missing}",
        file=sys.stderr,
    )
    sys.exit(1)


def get_signing_key() -> str | None:
    result = api_request(
        "GET",
        "/api/v3/crypto/certificatekeypairs/?has_key=true&ordering=name&page_size=10",
    )
    pairs = result.get("results", [])
    for pair in pairs:
        if "authentik" in pair["name"].lower() or "self-signed" in pair["name"].lower():
            return pair["pk"]
    if pairs:
        return pairs[0]["pk"]
    return None


def create_provider(
    auth_flow: str,
    invalidation_flow: str,
    scope_mappings: list[str],
    signing_key: str | None,
) -> int:
    provider_data = {
        "name": APP_NAME,
        "authorization_flow": auth_flow,
        "invalidation_flow": invalidation_flow,
        "client_type": "confidential",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": [{"matching_mode": "strict", "url": REDIRECT_URI}],
        "sub_mode": "user_username",
        "include_claims_in_id_token": True,
        "access_code_validity": "minutes=1",
        "access_token_validity": "minutes=10",
        "refresh_token_validity": "days=30",
    }
    if scope_mappings:
        provider_data["property_mappings"] = scope_mappings
    if signing_key:
        provider_data["signing_key"] = signing_key

    result = api_request("POST", "/api/v3/providers/oauth2/", provider_data)
    return result["pk"]


def create_application(provider_id: int) -> None:
    api_request(
        "POST",
        "/api/v3/core/applications/",
        {
            "name": APP_NAME,
            "slug": APP_SLUG,
            "provider": provider_id,
            "meta_launch_url": FRONTEND_URL,
        },
    )


def main() -> None:
    wait_for_authentik()

    if app_exists():
        print(f"Application '{APP_SLUG}' already exists, skipping setup.")
        return

    print("Setting up authentik OAuth2 provider and application...")

    auth_flow = get_flow("authorization", prefer_keyword="implicit")
    print(f"  Authorization flow: {auth_flow}")

    invalidation_flow = get_flow("invalidation")
    print(f"  Invalidation flow: {invalidation_flow}")

    scope_mappings = get_scope_mappings()
    print(f"  Scope mappings: {len(scope_mappings)} found")

    signing_key = get_signing_key()
    print(f"  Signing key: {signing_key or 'none (will use default)'}")

    provider_id = create_provider(
        auth_flow, invalidation_flow, scope_mappings, signing_key
    )
    print(f"  Created OAuth2 provider (id={provider_id})")

    create_application(provider_id)
    print(f"  Created application (slug={APP_SLUG})")

    print()
    print("authentik setup complete!")
    print(f"  App slug:      {APP_SLUG}")
    print(f"  Client ID:     {CLIENT_ID}")
    print("  Admin user:    akadmin")
    print("  Admin console: http://localhost:9100/if/admin/")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Добавить сервис `authentik-init` в `docker-compose.yml`**

После `authentik-worker`:

```yaml
  authentik-init:
    image: python:3.13-slim
    command: ["python3", "/setup/authentik-bootstrap.py"]
    environment:
      AUTHENTIK_INTERNAL_URL: http://authentik-server:9000
      AUTHENTIK_BOOTSTRAP_TOKEN: ${AUTHENTIK_BOOTSTRAP_TOKEN:-dev-only-bootstrap-api-token-change-me}
      AUTHENTIK_CLIENT_ID: ${AUTHENTIK_CLIENT_ID:-lore-chainlit}
      AUTHENTIK_CLIENT_SECRET: ${AUTHENTIK_CLIENT_SECRET:-dev-only-oauth-client-secret-change-me}
      AUTHENTIK_APP_SLUG: lore
      AUTHENTIK_APP_NAME: Lore Chat
      AUTHENTIK_REDIRECT_URI: ${CHAINLIT_PUBLIC_URL:-http://localhost:8000}/auth/oauth/generic/callback
      LORE_FRONTEND_URL: http://localhost:${FRONTEND_PORT:-3000}
    volumes:
      - ./infra/authentik-bootstrap.py:/setup/authentik-bootstrap.py:ro
    depends_on:
      authentik-server:
        condition: service_healthy
    restart: "no"
```

- [ ] **Step 3: Прогнать bootstrap**

Run: `docker compose up authentik-init`
Expected: лог заканчивается `authentik setup complete!` (первый запуск занимает до пары минут — скрипт ждёт scope-маппинги).

- [ ] **Step 4: Проверить идемпотентность**

Run: `docker compose up authentik-init 2>&1 | tail -3`
Expected: `Application 'lore' already exists, skipping setup.`

- [ ] **Step 5: Commit**

```bash
git add infra/authentik-bootstrap.py docker-compose.yml
git commit -m "feat: add authentik bootstrap init container (OAuth2 provider + app 'lore')"
```

---

### Task 3: `oauth_user` в бэкенде (TDD)

**Files:**
- Modify: `backend/app.py`
- Create: `backend/tests/test_oauth.py`

**Interfaces:**
- Produces: `async def oauth_user(provider_id: str, token: str, raw_user_data: dict, default_user: cl.User) -> Optional[cl.User]` в `app.py`; регистрируется как `cl.oauth_callback` ТОЛЬКО при наличии env `OAUTH_GENERIC_CLIENT_ID` (иначе `@cl.oauth_callback` кидает ValueError на импорте — см. Global Constraints).

- [ ] **Step 1: Написать падающий тест `backend/tests/test_oauth.py`**

```python
import asyncio
import importlib

import chainlit as cl


def _app(monkeypatch):
    monkeypatch.setenv("CHAINLIT_JWT_SECRET", "x")
    monkeypatch.setenv("CHAINLIT_JWT_ISSUER", "datacraft")
    monkeypatch.setenv("CHAINLIT_JWT_AUDIENCE", "chainlit")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    return importlib.import_module("app")


def test_oauth_user_maps_authentik_userinfo(monkeypatch):
    app = _app(monkeypatch)
    default = cl.User(identifier="alice")
    raw = {
        "sub": "alice",
        "preferred_username": "alice",
        "email": "alice@example.com",
        "name": "Alice Doe",
    }
    user = asyncio.run(app.oauth_user("generic", "token", raw, default))
    assert user is not None
    assert user.identifier == "alice"
    assert user.metadata["provider"] == "authentik"
    assert user.metadata["email"] == "alice@example.com"
    assert user.metadata["name"] == "Alice Doe"


def test_oauth_user_falls_back_to_default_identifier(monkeypatch):
    app = _app(monkeypatch)
    default = cl.User(identifier="fallback-id")
    user = asyncio.run(app.oauth_user("generic", "token", {}, default))
    assert user is not None
    assert user.identifier == "fallback-id"
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `docker run --rm -v "$PWD/backend:/app" -w /app lore-backend sh -c "pip install -q pytest && pytest tests/test_oauth.py -q"`
Expected: FAIL, `AttributeError: module 'app' has no attribute 'oauth_user'`.

- [ ] **Step 3: Реализовать в `backend/app.py`**

После функции `header_auth_callback` добавить:

```python
async def oauth_user(
    provider_id: str,
    token: str,
    raw_user_data: dict[str, Any],
    default_user: cl.User,
) -> Optional[cl.User]:
    """Map authentik userinfo to a Chainlit user (identifier = username)."""
    identifier = raw_user_data.get("preferred_username") or default_user.identifier
    return cl.User(
        identifier=str(identifier),
        metadata={
            "provider": "authentik",
            "email": raw_user_data.get("email"),
            "name": raw_user_data.get("name"),
        },
    )


# cl.oauth_callback raises at import time when no oauth provider is configured,
# so register only when the generic provider env is present. Without it the
# service still runs in ticket-only (header auth) mode.
if os.environ.get("OAUTH_GENERIC_CLIENT_ID"):
    cl.oauth_callback(oauth_user)
```

(`Any` и `Optional` уже импортированы в `app.py`.)

- [ ] **Step 4: Прогнать все тесты бэкенда**

Run: `docker run --rm -v "$PWD/backend:/app" -w /app lore-backend sh -c "pip install -q pytest && pytest -q"`
Expected: PASS все (7 старых + 2 новых), в т.ч. `test_app_imports` — без oauth-env регистрация просто не выполняется.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/tests/test_oauth.py
git commit -m "feat: map authentik userinfo to Chainlit user via conditional oauth_callback"
```

---

### Task 4: Подключить generic OAuth у backend в compose

**Files:**
- Modify: `docker-compose.yml` (сервис `backend`; все нужные env-переменные уже задокументированы в `.env.example` задачей 1)

**Interfaces:**
- Consumes: `oauth_user` из Task 3 (регистрация включается переменной `OAUTH_GENERIC_CLIENT_ID`), authentik из Task 1–2.
- Produces: рабочие endpoint'ы `GET :8000/auth/oauth/generic` (302 на authentik) и `GET :8000/auth/oauth/generic/callback`; `GET :8000/auth/config` со списком oauth-провайдеров.

- [ ] **Step 1: Добавить env к сервису `backend` в `docker-compose.yml`**

В `environment:` сервиса `backend` (после блока `CHAINLIT_JWT_*`):

```yaml
      # authentik SSO — generic OAuth-провайдер Chainlit.
      # CHAINLIT_URL нужен Chainlit для построения redirect_uri.
      CHAINLIT_URL: ${CHAINLIT_PUBLIC_URL:-http://localhost:8000}
      OAUTH_GENERIC_CLIENT_ID: ${AUTHENTIK_CLIENT_ID:-lore-chainlit}
      OAUTH_GENERIC_CLIENT_SECRET: ${AUTHENTIK_CLIENT_SECRET:-dev-only-oauth-client-secret-change-me}
      OAUTH_GENERIC_AUTH_URL: ${AUTHENTIK_PUBLIC_URL:-http://localhost:9100}/application/o/authorize/
      OAUTH_GENERIC_TOKEN_URL: http://authentik-server:9000/application/o/token/
      OAUTH_GENERIC_USER_INFO_URL: http://authentik-server:9000/application/o/userinfo/
      OAUTH_GENERIC_SCOPES: openid profile email
      OAUTH_GENERIC_USER_IDENTIFIER: preferred_username
```

И в `depends_on` сервиса `backend` добавить:

```yaml
      authentik-server:
        condition: service_healthy
```

- [ ] **Step 2: Перезапустить backend**

Run: `docker compose up -d --build backend`
Expected: контейнер `lore-backend-1` поднимается без ошибок (`docker compose logs backend | tail -3` → "Your app is available").

- [ ] **Step 3: Smoke-проверки**

Run: `curl -s http://localhost:8000/auth/config | python3 -m json.tool | head -20`
Expected: `"oauthProviders": ["generic"]` (и по-прежнему `"headerAuth": true`).

Run: `curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' http://localhost:8000/auth/oauth/generic`
Expected: `307 http://localhost:9100/application/o/authorize/?...` (или `302`; главное — Location на authentik с `client_id=lore-chainlit` и `redirect_uri=http://localhost:8000/auth/oauth/generic/callback`).

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: wire Chainlit generic OAuth to authentik in compose"
```

---

### Task 5: Модуль auth во фронтенде

**Files:**
- Create: `frontend/src/auth/authClient.ts`
- Create: `frontend/src/auth/useAuth.ts`

**Interfaces:**
- Consumes: endpoint'ы Chainlit `GET /user`, `POST /logout`, `GET /auth/oauth/generic` (Task 4); env `VITE_CHAINLIT_URL`.
- Produces:
  - `type AuthUser = { identifier: string; metadata?: Record<string, unknown> }`
  - `getCurrentUser(): Promise<AuthUser | null>`, `loginWithPopup(timeoutMs?): Promise<AuthUser>`, `logout(): Promise<void>`
  - `useAuth(): { state: AuthState; login: () => Promise<void>; logout: () => Promise<void> }`, где `AuthState = { status: "loading" } | { status: "anonymous"; isBusy: boolean; error: string | null } | { status: "authenticated"; user: AuthUser }`

- [ ] **Step 1: Создать `frontend/src/auth/authClient.ts`**

```ts
export type AuthUser = {
  identifier: string;
  metadata?: Record<string, unknown>;
};

const baseUrl: string =
  import.meta.env.VITE_CHAINLIT_URL ?? "http://localhost:8000";

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export async function getCurrentUser(): Promise<AuthUser | null> {
  try {
    const response = await fetch(`${baseUrl}/user`, { credentials: "include" });
    if (!response.ok) return null;
    return (await response.json()) as AuthUser;
  } catch {
    return null;
  }
}

export async function loginWithPopup(timeoutMs = 60_000): Promise<AuthUser> {
  const popup = window.open(
    `${baseUrl}/auth/oauth/generic`,
    "lore-login",
    "width=480,height=720",
  );
  if (!popup) {
    throw new Error("Браузер заблокировал окно входа. Разрешите всплывающие окна.");
  }

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await sleep(1000);
    const user = await getCurrentUser();
    if (user) {
      popup.close();
      return user;
    }
    if (popup.closed) {
      throw new Error("Окно входа было закрыто до завершения входа.");
    }
  }

  popup.close();
  throw new Error("Не удалось войти: время ожидания истекло.");
}

export async function logout(): Promise<void> {
  await fetch(`${baseUrl}/logout`, { method: "POST", credentials: "include" });
}
```

- [ ] **Step 2: Создать `frontend/src/auth/useAuth.ts`**

```ts
import { useCallback, useEffect, useState } from "react";
import {
  getCurrentUser,
  loginWithPopup,
  logout as apiLogout,
  type AuthUser,
} from "./authClient";

export type AuthState =
  | { status: "loading" }
  | { status: "anonymous"; isBusy: boolean; error: string | null }
  | { status: "authenticated"; user: AuthUser };

export function useAuth() {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    void getCurrentUser().then((user) => {
      if (cancelled) return;
      setState(
        user
          ? { status: "authenticated", user }
          : { status: "anonymous", isBusy: false, error: null },
      );
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async () => {
    setState({ status: "anonymous", isBusy: true, error: null });
    try {
      const user = await loginWithPopup();
      setState({ status: "authenticated", user });
    } catch (error) {
      setState({
        status: "anonymous",
        isBusy: false,
        error: error instanceof Error ? error.message : "Не удалось войти.",
      });
    }
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setState({ status: "anonymous", isBusy: false, error: null });
  }, []);

  return { state, login, logout };
}
```

- [ ] **Step 3: Проверить типы сборкой**

Run: `docker compose build frontend`
Expected: сборка проходит (tsc без ошибок). Модуль пока никем не импортируется — это нормально.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/auth
git commit -m "feat: add frontend auth client and useAuth hook (popup login via Chainlit oauth)"
```

---

### Task 6: Экран логина и гейт приложения

**Files:**
- Create: `frontend/src/components/LoginScreen/LoginScreen.tsx`
- Create: `frontend/src/components/LoginScreen/LoginScreen.module.css`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.module.css`
- Modify: `frontend/src/components/Sidebar/Sidebar.tsx`
- Modify: `frontend/src/components/Sidebar/Sidebar.module.css`

**Interfaces:**
- Consumes: `useAuth`, `AuthState`, `AuthUser` из Task 5.
- Produces: приложение, требующее логина; `Sidebar` получает новые обязательные пропсы `user: AuthUser` и `onLogout: () => void`.

- [ ] **Step 1: Создать `frontend/src/components/LoginScreen/LoginScreen.tsx`**

```tsx
import { LogIn } from "lucide-react";
import styles from "./LoginScreen.module.css";

interface LoginScreenProps {
  onLogin: () => void;
  isBusy: boolean;
  error: string | null;
}

export default function LoginScreen({ onLogin, isBusy, error }: LoginScreenProps) {
  return (
    <div className={styles.screen}>
      <div className={styles.card}>
        <h1 className={styles.title}>Lore</h1>
        <p className={styles.text}>
          Войдите через authentik, чтобы продолжить работу с чатом.
        </p>
        <button
          className={styles.button}
          onClick={onLogin}
          type="button"
          disabled={isBusy}
        >
          <LogIn size={18} />
          <span>{isBusy ? "Ожидание входа…" : "Войти через authentik"}</span>
        </button>
        {error ? <p className={styles.error}>{error}</p> : null}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Создать `frontend/src/components/LoginScreen/LoginScreen.module.css`**

```css
.screen {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.card {
  width: min(400px, 100%);
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(214, 221, 229, 0.9);
  border-radius: 16px;
  padding: 32px 28px;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.title {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.04em;
}

.text {
  margin: 0;
  color: #475569;
  font-size: 14px;
}

.button {
  height: 42px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: #111827;
  color: white;
  font-size: 14px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.button:hover {
  background: #1f2937;
}

.button:disabled {
  opacity: 0.6;
  cursor: default;
}

.error {
  margin: 0;
  color: #b91c1c;
  font-size: 13px;
}
```

- [ ] **Step 3: Обновить `frontend/src/App.tsx`**

Добавить импорты после существующих:

```tsx
import LoginScreen from "./components/LoginScreen/LoginScreen";
import { useAuth } from "./auth/useAuth";
import type { AuthUser } from "./auth/authClient";
```

Изменить сигнатуру `AppContent` (строка `function AppContent() {`):

```tsx
function AppContent({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
```

В JSX `AppContent` передать новые пропсы в `<Sidebar ...>` (добавить к существующим):

```tsx
          user={user}
          onLogout={onLogout}
```

Заменить корневой компонент `App` целиком:

```tsx
export default function App() {
  const runtime = useLocalRuntime(noopRuntimeAdapter);
  const { state, login, logout } = useAuth();

  if (state.status === "loading") {
    return <div className={styles.authLoading}>Загрузка…</div>;
  }

  if (state.status === "anonymous") {
    return (
      <LoginScreen
        onLogin={() => void login()}
        isBusy={state.isBusy}
        error={state.error}
      />
    );
  }

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <AppContent user={state.user} onLogout={() => void logout()} />
    </AssistantRuntimeProvider>
  );
}
```

- [ ] **Step 4: Добавить в `frontend/src/App.module.css`**

```css
.authLoading {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #475569;
  font-size: 14px;
}
```

- [ ] **Step 5: Обновить `frontend/src/components/Sidebar/Sidebar.tsx`**

Заменить файл целиком:

```tsx
import { LogOut, PenSquare, UserRound, X } from "lucide-react";
import type { AuthUser } from "../../auth/authClient";
import type { Chat } from "../../types/chat";
import ChatList from "../ChatList/ChatList";
import styles from "./Sidebar.module.css";

interface SidebarProps {
  chats: Chat[];
  activeChatId: string | null;
  isMobileOpen: boolean;
  user: AuthUser;
  onSelectChat: (chatId: string) => void;
  onRenameChat: (chatId: string) => void;
  onDeleteChat: (chatId: string) => void;
  onCreateChat: () => void;
  onCloseMobileMenu: () => void;
  onLogout: () => void;
}

export default function Sidebar({
  chats,
  activeChatId,
  isMobileOpen,
  user,
  onSelectChat,
  onRenameChat,
  onDeleteChat,
  onCreateChat,
  onCloseMobileMenu,
  onLogout,
}: SidebarProps) {
  return (
    <>
      <div
        className={`${styles.overlay} ${isMobileOpen ? styles.overlayVisible : ""}`}
        onClick={onCloseMobileMenu}
      />
      <aside className={`${styles.sidebar} ${isMobileOpen ? styles.sidebarOpen : ""}`}>
        <div className={styles.headerRow}>
          <h1 className={styles.title}>Lore</h1>
          <button
            className={styles.closeButton}
            onClick={onCloseMobileMenu}
            type="button"
            aria-label="Закрыть меню"
          >
            <X size={18} />
          </button>
        </div>

        <button className={styles.newChatButton} onClick={onCreateChat} type="button">
          <PenSquare size={18} />
          <span>Новый чат</span>
        </button>

        <ChatList
          chats={chats}
          activeChatId={activeChatId}
          onSelectChat={onSelectChat}
          onRenameChat={onRenameChat}
          onDeleteChat={onDeleteChat}
        />

        <div className={styles.userFooter}>
          <div className={styles.userInfo}>
            <UserRound size={18} />
            <span className={styles.userName}>{user.identifier}</span>
          </div>
          <button
            className={styles.logoutButton}
            onClick={onLogout}
            type="button"
            aria-label="Выйти"
            title="Выйти"
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>
    </>
  );
}
```

- [ ] **Step 6: Добавить в `frontend/src/components/Sidebar/Sidebar.module.css`**

Перед медиа-запросом:

```css
.userFooter {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid rgba(214, 221, 229, 0.9);
  color: #334155;
}

.userInfo {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.userName {
  font-size: 13px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logoutButton {
  width: 32px;
  height: 32px;
  border: 1px solid rgba(214, 221, 229, 0.9);
  border-radius: 10px;
  background: white;
  color: #1f2937;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.logoutButton:hover {
  background: #eef2f7;
}
```

- [ ] **Step 7: Собрать и перезапустить фронтенд**

Run: `docker compose up -d --build frontend`
Expected: сборка (tsc + vite) проходит, контейнер поднялся.

- [ ] **Step 8: Ручная E2E-проверка**

1. Открыть http://localhost:3000 — экран «Войдите через authentik».
2. Нажать кнопку — popup со страницей логина authentik (`localhost:9100`).
3. Войти: `akadmin` / значение `AUTHENTIK_BOOTSTRAP_PASSWORD` (по умолчанию `admin`).
4. Popup закрывается сам, приложение показывает чат, внизу сайдбара — `akadmin` и кнопка выхода.
5. Обновить страницу — сессия сохраняется (cookie), логин не требуется.
6. Нажать выход — возврат на экран логина.

Expected: все шаги проходят. Если popup «висит» — смотреть `docker compose logs backend` (ошибки обмена code→token) и Network-вкладку браузера.

- [ ] **Step 9: Commit**

```bash
git add frontend/src
git commit -m "feat: gate app behind authentik login (popup flow, user footer in sidebar)"
```

---

### Task 7: Документация и финальная проверка стека

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: всё предыдущее.

- [ ] **Step 1: Обновить `README.md`**

В таблицу сервисов добавить строку:

```markdown
| authentik   | http://localhost:9100  |
```

После раздела «Настройка» добавить раздел:

```markdown
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
```

В разделе «Состояние интеграции» заменить последнее предложение абзаца на актуальное: SSO-логин работает, обмен сообщениями всё ещё через mock-провайдер.

- [ ] **Step 2: Полный перезапуск стека с нуля**

Run: `docker compose down && docker compose up -d --build && sleep 100 && docker compose ps --format 'table {{.Name}}\t{{.Status}}'`
Expected: `frontend`, `backend`, `chainlit-db`, `authentik-server`, `authentik-worker`, `authentik-db`, `authentik-redis` — Up (server/db — healthy); `authentik-init` — Exited (0).

- [ ] **Step 3: Финальный smoke**

Run:
```bash
curl -s -o /dev/null -w 'frontend: %{http_code}\n' http://localhost:3000/
curl -s http://localhost:8000/auth/config | python3 -c "import json,sys; c=json.load(sys.stdin); print('oauth:', c['oauthProviders'], 'header:', c['headerAuth'])"
curl -s -o /dev/null -w 'authentik: %{http_code}\n' http://localhost:9100/-/health/ready/
docker compose logs authentik-init 2>&1 | tail -1
```
Expected: `frontend: 200`; `oauth: ['generic'] header: True`; `authentik: 204` (или 200); лог init — `already exists` или `setup complete`.

- [ ] **Step 4: Тесты бэкенда напоследок**

Run: `docker run --rm -v "$PWD/backend:/app" -w /app lore-backend sh -c "pip install -q pytest && pytest -q"`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: describe authentik SSO setup and default credentials"
```
