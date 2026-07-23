# Deploying Lore to production

Two images are built by CI and pulled on the server:

- `cr.selcloud.ru/adventum/lore-chat` — backend (Chainlit)
- `cr.selcloud.ru/adventum/lore-frontend` — static SPA (nginx)

Production connects to an **external, already-provisioned** authentik (SSO) and
PostgreSQL. Nothing else is bundled.

---

## 1. Build & publish images (CI)

Both `.github/workflows/build.yml` (chat) and `build-frontend.yml` (frontend)
trigger on a **git tag**. The tag name becomes the image tag.

```bash
git tag v1.0.0
git push origin v1.0.0
```

This pushes `cr.selcloud.ru/adventum/lore-chat:v1.0.0` and
`...lore-frontend:v1.0.0`.

> The frontend bakes the public chat URL at build time. Before tagging, set the
> repo/org Actions variable **`CHAINLIT_PUBLIC_URL`** (Settings → Secrets and
> variables → Actions → Variables) to the browser-facing chat URL. It must equal
> `CHAINLIT_PUBLIC_URL` in `.env.prod` below.

---

## 2. Deploy on the server

```bash
# 1. Get the deploy files (docker-compose.prod.yml + .env.prod.example)
git clone <repo-url> lore && cd lore     # first time
git pull                                 # updates

# 2. Create the env file from the template and fill it in (see §3)
cp .env.prod.example .env.prod
$EDITOR .env.prod

# 3. Pull the tagged images and start
docker compose -f docker-compose.prod.yml --env-file .env.prod pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

- **Compose file:** `docker-compose.prod.yml`
- **Env file:** `.env.prod` (copied from `.env.prod.example`; holds secrets,
  gitignored — never commit it).
- The same `.env.prod` is passed via `--env-file` (fills `${...}` in the compose)
  and read into the chat container (`env_file:`).

To update to a new build: set `LORE_VERSION` to the new tag, then re-run the
`pull` + `up -d` commands.

---

## 3. Filling `.env.prod`

| Variable | Example | Notes |
|---|---|---|
| `LORE_VERSION` | `v1.0.0` | Image tag to pull — the git tag you built. |
| `BACKEND_PORT` | `8000` | Host port for the chat backend. |
| `FRONTEND_PORT` | `3000` | Host port for the frontend. |
| `CHAINLIT_PUBLIC_URL` | `https://chat.example.com` | Browser-facing chat URL. Must equal the `CHAINLIT_PUBLIC_URL` Actions variable baked into the frontend image. |
| `CHAINLIT_DB_HOST` | `postgres.internal` | External chainlit PostgreSQL host. |
| `CHAINLIT_DB_PORT` | `5432` | |
| `CHAINLIT_DB_USER` / `_PASSWORD` / `_NAME` | `chainlit` / … / `chainlit` | Credentials for the chainlit DB. |
| `TOAST_DB_*` | (blank) | External data DB for SQL/table answers. Leave blank to disable the SQL tool. |
| `CHAINLIT_AUTH_SECRET` | `openssl rand -hex 32` | Session secret (≥32 bytes). |
| `CHAINLIT_JWT_SECRET` | `openssl rand -hex 32` | JWT signing secret (≥32 bytes). |
| `CHAINLIT_JWT_AUDIENCE` / `_ISSUER` | `chainlit` / `datacraft` | JWT claims. |
| `AUTHENTIK_PUBLIC_URL` | `https://sso.example.com` | Base URL of the external authentik. The compose derives the authorize/token/userinfo endpoints from it. |
| `AUTHENTIK_CLIENT_ID` / `_SECRET` | `lore-chainlit` / … | OAuth client provisioned in authentik for this app. |
| `OAUTH_GENERIC_SCOPES` | `openid profile email` | |
| `OAUTH_GENERIC_USER_IDENTIFIER` | `preferred_username` | Claim used as the user identity. |
| `MODEL_PROVIDER` | `openrouter` | `openrouter` or `ollama`. |
| `OPENROUTER_API_KEY` | `sk-or-…` | Required when provider is openrouter. |
| `OPENROUTER_MODEL` / `_BASE_URL` | `anthropic/claude-haiku-4.5` / … | |
| `LLM_MAX_TOKENS` | `64000` | |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | … | Only when `MODEL_PROVIDER=ollama`. |
| `LANGSMITH_TRACING` / `_ENDPOINT` / `_API_KEY` | `false` / … | Optional tracing. |

Generate secrets with e.g. `openssl rand -hex 32`.

---

## Prerequisites

- The external chainlit PostgreSQL must already have the schema from
  `lore-core/services/lore-chat/init/schema.sql` applied (in production there is
  no bundled DB container to apply it automatically).
- The external authentik must have an OAuth2/OIDC provider + application whose
  client id/secret match `AUTHENTIK_CLIENT_ID` / `AUTHENTIK_CLIENT_SECRET`, and
  whose redirect URI is `<CHAINLIT_PUBLIC_URL>/auth/oauth/generic/callback`.
