# Дизайн: интеграция чата (chainlit WS + assistant-ui runtime)

Дата: 2026-07-15
Статус: утверждён (секции 1–2 одобрены пользователем)

## Цель и скоуп

Заменить mock-чат реальным обменом с Chainlit-бэкендом: родной socket.io-
протокол, серверные треды из Postgres, стриминг ответов агента (Ollama).
Закрывает пункты бэклога F1 (assistant-ui по назначению), F2 (частично,
через удаление ручного стейт-менеджмента) и F3 (localStorage удаляется).

**В скоупе:** WS-подключение с cookie-аутентификацией (SSO уже работает),
серверный список тредов, resume тредов с историей, отправка/стриминг/
остановка, удаление треда, переименование (при наличии endpoint'а),
удаление mock-инфраструктуры.

**Вне скоупа:** feedback (лайки/дизлайки — у Chainlit есть API, отдельный
шаг; кнопки скрываются), перегенерация (в протоколе Chainlit её нет —
кнопка удаляется), файлы/элементы (`cl.Plotly` и storage_provider — см.
B2 в improvements.md), профили чата `charts`/`analyst` из контракта
datacraft (в lore один профиль).

## Ключевые решения (утверждены)

1. **Серверные треды.** Список чатов — из data layer Chainlit
   (`POST /project/threads`), переключение чата — resume треда по
   `thread_id` (бэкенд уже реализует `on_chat_resume`). localStorage-
   персистентность удаляется.
2. **F1: react-client + assistant-ui runtime** («как в datacraft»,
   description.md §0): транспорт и состояние — хуки
   `@chainlit/react-client`, поверх них `ExternalStoreRuntime` для
   `@assistant-ui/react`, примитивы остаются. Альтернативы (свои
   компоненты без assistant-ui; ручной socket.io) отклонены.
3. **Mock удаляется целиком**: `providers/` (интерфейс ChatProvider, mock,
   заглушка), переключатель `VITE_CHAT_PROVIDER`, localStorage.

## Архитектура

```
Наши компоненты (Sidebar, MessageList, ChatComposer, ...)
        │
assistant-ui примитивы (ThreadPrimitive, ComposerPrimitive)
        │
ExternalStoreRuntime  ←  convertMessage(IStep → ThreadMessageLike)
        │
@chainlit/react-client hooks (useChatSession / useChatMessages / useChatInteract)
        │
socket.io (cookie-auth) ──▶ Chainlit :8000 ──▶ Postgres / Ollama
```

Новые зависимости: `@chainlit/react-client` + его peer `recoil`.
`@assistant-ui/react` остаётся (используется по назначению).
Бэкенд не меняется.

### Аутентификация WS

SSO-cookie `access_token` (домен `localhost:8000`) авторизует и REST, и
socket.io-handshake — по контракту (description.md §1a) WS-сессия
авторизуется кукой. `localhost:3000 → localhost:8000` — same-site, cookie
ходит при `credentials: 'include'` / `withCredentials: true`.

## Поток данных

- **Список чатов:** `useThreads` → `POST /project/threads` (первая
  страница, сортировка по дате создания ↓). Обновляется после первого
  ответа в новом треде и после удаления/переименования.
- **Выбор чата:** смена `activeThreadId` → переподключение WS-сессии с
  resume этого треда → `on_chat_resume` на бэкенде → история из БД,
  контекст агента восстановлен.
- **Новый чат:** свежая сессия без thread_id; тред создаётся сервером при
  первом сообщении; после ответа — `refresh()` списка.
- **Сообщение:** `useChatInteract().sendMessage`; токены стримятся через
  WS, `useChatMessages` отдаёт растущий step, runtime помечает
  `isRunning`. Остановка — `stopTask`.

## Компоненты

### Новый модуль `frontend/src/chat/`

| Файл | Ответственность |
|---|---|
| `chainlitClient.ts` | синглтон `ChainlitAPI` (base = `VITE_CHAINLIT_URL`, cookie-креды) |
| `convertMessage.ts` | чистая функция `IStep → ThreadMessageLike`; роль из `type` (`user_message`/`assistant_message`), флаг стриминга. Единственное место, знающее оба формата |
| `useThreads.ts` | список/удаление/переименование тредов + `refresh()`; состояние `loading/error` |
| `ChainlitRuntimeProvider.tsx` | `RecoilRoot` + `ChainlitContext.Provider`; connect/resume по `activeThreadId`; сборка `ExternalStoreRuntime` (messages ← convert, `onNew` → sendMessage, `onCancel` → stopTask, `isRunning`) |

### Изменения существующего

- `App.tsx`: удаляются `messagesByChat`, оба стриминг-цикла, localStorage,
  `noopRuntimeAdapter`, `chatProvider`; остаются auth-гейт,
  `activeThreadId`, модалки rename/delete (зовут `useThreads`), мобильный
  сайдбар. Ожидаемое сокращение — примерно вдвое.
- `MessageList`, `UserMessage`, `AssistantMessage`, `ChatComposer`:
  переводятся на runtime (`ThreadPrimitive.Messages` с нашими
  компонентами); кнопки regenerate и thumbs удаляются, копирование
  остаётся.
- Удаляются: `src/providers/` целиком; `VITE_CHAT_PROVIDER` из
  `frontend/Dockerfile`, `docker-compose.yml`, `.env.example`, README.

## Обработка ошибок

- **Обрыв WS** — баннер «переподключение…» из состояния `useChatSession`;
  socket.io переподключается сам.
- **401** (протухла cookie) на REST или WS-handshake — сброс auth-состояния
  в `anonymous` → существующий экран логина.
- **Ошибка агента** (Ollama недоступна и т.п.) — Chainlit шлёт
  error-сообщение в тред; рендерим в ленте как системную ошибку.
- **Ошибка загрузки тредов** — сообщение в сайдбаре + retry.

## Тестирование

- **Юнит:** `convertMessage` (vitest — первый юнит-тест фронтенда;
  добавляется как dev-зависимость и отдельная npm-команда, docker-сборка
  остаётся tsc+vite).
- **Скриптовый e2e** (поверх готового OAuth-скрипта): python-socketio
  подключается с SSO-cookie, шлёт сообщение, получает стрим-токены, затем
  через REST проверяет, что тред и step'ы легли в Postgres. Требует
  запущенной Ollama.
- **Ручной прогон:** логин → новый чат → стриминг ответа → релоад →
  история на месте → второй чат → переключение туда-обратно → удаление.

## Риски → проверить на этапе плана (по исходникам пакетов)

1. Точный API сессии/resume в актуальном `@chainlit/react-client`
   (`connect`, `idToResume`/аналог) и его совместимость с chainlit 2.11.1.
2. Прокидывает ли react-client cookie (fetch `credentials`, socket.io
   `withCredentials`) на кросс-портовые запросы; fallback — кастомный
   fetch/опции сокета.
3. Наличие REST для переименования треда в 2.11.1; если нет — кнопка
   rename удаляется вместе с regenerate.
4. Формат `ListThreadsRequest` (пагинация/фильтры) для `/project/threads`.
