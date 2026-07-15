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

- **Новый чат** — кнопка в сайдбаре; активный чат выбирается кликом.
- **Переименовать / удалить** — меню «⋯» на карточке чата.
- **Отправка** — Enter или кнопка; во время генерации доступна остановка.
- У сообщений ассистента есть копирование и перегенерация.

**Текущий режим ответа.** По умолчанию (`CHAT_PROVIDER=mock`) ответы
чата — демонстрационные, генерируются на клиенте; история хранится в
localStorage браузера. Реальное подключение чата к бэкенду
(`chainlitChatProvider`, socket.io) — следующий шаг разработки; после
него режим включается `CHAT_PROVIDER=chainlit` + пересборка frontend.

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
```

Чтобы dev-сервер ходил в бэкенд, добавьте origin `http://localhost:5173`
в `allow_origins` (`backend/.chainlit/config.toml`) и перезапустите backend.

Бэкенд без docker (Python ≥ 3.13; нужны Postgres, authentik и Ollama —
проще оставить их в compose):

```bash
cd backend
pip install -e ".[dev]"
DATABASE_URL=postgresql+asyncpg://chainlit:chainlit@localhost:5432/chainlit \
  chainlit run app.py --port 8000
```

(для этого сценария опубликуйте порт `chainlit-db` в compose).

Тесты бэкенда:

```bash
docker run --rm -v "$PWD/backend:/app" -w /app lore-backend \
  sh -c "uv pip install -q pytest && pytest -q"
```
