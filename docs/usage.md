# Использование lore

Как пользоваться запущенным сервисом. Про установку и конфигурацию —
см. [deployment.md](deployment.md).

## Вход в приложение

1. Откройте http://localhost:3000 — экран «Войдите через authentik».
2. Кнопка входа открывает popup со страницей логина authentik.
3. После входа popup закроется сам, откроется чат; внизу сайдбара —
   имя пользователя и кнопка выхода.

Пользователь по умолчанию: `akadmin`, пароль — значение
`AUTHENTIK_BOOTSTRAP_PASSWORD` (по умолчанию `admin`).

Сессия живёт в cookie Chainlit — обновление страницы логина не требует.
Выход — кнопка в футере сайдбара.

Если popup заблокирован браузером — разрешите всплывающие окна для
`localhost:3000` (SPA покажет соответствующую ошибку).

## Работа с чатом

Чат работает с реальным бэкендом: сообщения уходят в Chainlit по
socket.io, ответы агента (модель из OpenRouter по умолчанию) стримятся
токен за токеном, история хранится в Postgres.

- **Новый чат** — кнопка в сайдбаре; тред создаётся на сервере с первым
  сообщением. Активный чат выбирается кликом — история подгружается из
  БД, агент помнит контекст (resume).
- **Переименовать / удалить** — меню «⋯» на карточке чата (операции
  серверные, применяются для всех устройств пользователя).
- **Отправка** — Enter или кнопка; во время генерации доступна остановка.
- У сообщений ассистента есть кнопка копирования.
- Перезагрузка страницы и вход с другого устройства сохраняют все чаты —
  они привязаны к пользователю authentik.

Для ответов агента при провайдере по умолчанию нужен `OPENROUTER_API_KEY`
в `.env` (модель — `OPENROUTER_MODEL`, по умолчанию
`anthropic/claude-haiku-4.5`). При `MODEL_PROVIDER=ollama` вместо этого на
хосте должна работать Ollama с моделью из `OLLAMA_MODEL` (по умолчанию
`gemma3`): если модель не скачана — `ollama pull gemma3`.

## Режимы ассистента

Переключатель «Быстрый | Умный» в сайдбаре действует на следующий новый
чат (у существующего треда режим зафиксирован):

- **Быстрый** — фиксированный маршрут с одним циклом инструментов:
  модель либо отвечает сразу, либо один раз зовёт инструмент и
  формулирует ответ. Хорош для типовых вопросов.
- **Умный** — deepagents сам планирует шаги и вызовы инструментов.
  Для сложных задач (медленнее).

Обоим режимам доступен калькулятор — попросите что-нибудь посчитать:
«Сколько будет (17 + 3) * 4 / 2?» — и модель вызовет инструмент вместо
счёта в уме. Если задан `TOAST_DATABASE_URL`, доступен и
`query_document_tables` — вопросы про сотрудников, грейды и документы.

Прогон eval-набора: `python3 infra/eval-agents.py`
(нужен запущенный стек и доступ к модели — `OPENROUTER_API_KEY` либо
Ollama при `MODEL_PROVIDER=ollama`).

## Управление пользователями (authentik)

Админка: http://localhost:9100/if/admin/ (вход `akadmin`).

Создать пользователя: **Directory → Users → Create**, затем задать пароль
(**Set password** в карточке пользователя). Новый пользователь сразу может
логиниться в lore — identifier в чате будет его `username`.

Там же настраиваются группы, политики, MFA и прочие возможности
authentik — lore использует стандартные флоу без кастомизации.

## Прямой доступ к API Chainlit

Бэкенд — обычное Chainlit-приложение на http://localhost:8000 со всеми
его endpoint'ами (`/user`, `/logout`, `/project/threads`, WS socket.io).

Аутентификация — любой из двух параллельных механизмов:

1. **Сессионная cookie** после SSO-логина (её использует SPA).
2. **Header-auth по JWT-тикету** (контракт datacraft): короткий HS256-токен
   с `aud=chainlit`, `iss=datacraft`, подписанный `CHAINLIT_JWT_SECRET`,
   обменивается на cookie через `POST /auth/header`:

```bash
TICKET=$(python3 - <<'EOF'
import jwt, time
print(jwt.encode(
    {"sub": "42", "username": "alice", "aud": "chainlit",
     "iss": "datacraft", "exp": int(time.time()) + 60},
    "dev-only-secret-change-me-32-bytes!",   # CHAINLIT_JWT_SECRET
    algorithm="HS256",
))
EOF
)
curl -c cookies.txt -X POST http://localhost:8000/auth/header \
  -H "Authorization: Bearer $TICKET"
curl -b cookies.txt http://localhost:8000/user
```

## Разработка

Фронтенд (нужен Node ≥ 20; бэкенд при этом можно держать в docker):

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
npm test             # юнит-тесты (vitest)
```

Чтобы dev-сервер ходил в бэкенд, добавьте origin `http://localhost:5173`
в `allow_origins` (`lore-core/services/lore-chat/.chainlit/config.toml`) и перезапустите chat.

Бэкенд без docker (Python ≥ 3.13; Postgres и authentik проще оставить в
compose). Модель — OpenRouter по ключу, либо Ollama при
`MODEL_PROVIDER=ollama`. Обязательные для config переменные, которых нет в
дефолтах, задайте в окружении или `.env`/`.env.local`:

```bash
cd backend
pip install -e ".[dev]"
DATABASE_URL=postgresql+asyncpg://chainlit:chainlit@localhost:5432/chainlit \
CHAINLIT_JWT_SECRET=dev-only-secret-change-me-32-bytes! \
CHAINLIT_JWT_AUDIENCE=chainlit CHAINLIT_JWT_ISSUER=datacraft \
OPENROUTER_API_KEY=sk-or-... \
  chainlit run app.py --port 8000
```

(для этого сценария опубликуйте порт `chainlit-db` в compose).

Тесты бэкенда:

```bash
docker run --rm -v "$PWD/backend:/app" -w /app lore-backend \
  sh -c "uv pip install -q pytest && pytest -q"
```
