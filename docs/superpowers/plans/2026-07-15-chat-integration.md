# Chat Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реальный чат: React SPA говорит с Chainlit по родному socket.io-протоколу — серверные треды, resume, стриминг Ollama-ответов; mock удаляется.

**Architecture:** `@chainlit/react-client` (транспорт+state, cookie-auth) → `useExternalStoreRuntime` (адаптер) → примитивы `@assistant-ui/react` → наши компоненты. Треды — REST того же клиента (`listThreads`/`renameThread`/`deleteThread`), resume — `setIdToResume` + reconnect.

**Tech Stack:** @chainlit/react-client 0.4.2, recoil 0.7.7, React **18.3.1** (даунгрейд — см. constraints), @assistant-ui/react 0.14.x, vitest.

**Спека:** `docs/superpowers/specs/2026-07-15-chat-integration-design.md`

## Global Constraints

- **React даунгрейдится 19 → 18.3.1** (и `@types/react*` → ^18): recoil 0.7.7 (peer react-client) падает под React 19 — проверено рендер-тестом (`ReactCurrentDispatcher` удалён из internals); под 18.3.1 работает (проверено там же). assistant-ui (`^18 || ^19`) и lucide-react совместимы.
- Все API проверены по исходникам установленных пакетов (react-client 0.4.2 dist, chainlit 2.11.1 в `/opt/venv` образа `lore-backend`):
  - cookie-auth зашита в react-client: fetch `credentials:"include"`, socket.io `withCredentials:true`; WS-handshake авторизуется кукой (`socket.py:_authenticate_connection`);
  - `useChatSession().connect({ userEnv })` (debounced), `disconnect()`; resume: `useChatInteract().setIdToResume(id)` перед connect;
  - `useChatInteract()`: `sendMessage(step)`, `stopTask()`, `clear()`; `useChatMessages()`: `{threadId, messages: IStep[]}`; `useChatData()`: `{connected, loading, error}`;
  - `ChainlitAPI(url, 'webapp', undefined, on401)`; `listThreads({first}, {}) → {pageInfo, data: IThread[]}`; `renameThread(threadId, name)`; `deleteThread(threadId)`;
  - `useExternalStoreRuntime({ messages, convertMessage, isRunning, onNew(AppendMessage), onCancel })`.
- Сигнатуры примитивов assistant-ui в задачах соответствуют 0.14.26; при расхождении типов на tsc исполнитель сверяется с `frontend/node_modules/@assistant-ui/*/dist/*.d.ts` и сохраняет семантику шага.
- Локальный Node = 16: любые npm/vitest-команды — через `docker run node:22-alpine`; проверка типов/сборка — `docker compose build frontend`.
- UI-тексты на русском, стиль существующих CSS-модулей.
- Работа в ветке `chat-integration` от `authentik-sso`. Бэкенд не меняется.
- Для живых проверок нужен работающий стек (`docker compose up -d`) и Ollama на хосте (`ollama serve`, модель `gemma3`).

## File Structure

| Файл | Судьба | Ответственность |
|---|---|---|
| `frontend/package.json` | modify | React 18, +react-client, +recoil, +vitest |
| `frontend/src/chat/chainlitClient.ts` | create | синглтон ChainlitAPI + колбэк on401 |
| `frontend/src/chat/convertMessage.ts` | create | IStep → ThreadMessageLike (+фильтр isChatMessage) |
| `frontend/src/chat/convertMessage.test.ts` | create | vitest-юниты |
| `frontend/src/chat/threadToChat.ts` | create | IThread → Chat (заголовок/дата для сайдбара) + тест |
| `frontend/src/chat/ChainlitRuntimeProvider.tsx` | create | RecoilRoot + ChainlitContext + сессия + ExternalStoreRuntime |
| `frontend/src/chat/useThreads.ts` | create | список/rename/delete тредов + refresh |
| `frontend/src/App.tsx` | modify | треды вместо localStorage-чатов, гейт как был |
| `frontend/src/components/MessageList/*` | modify | ThreadPrimitive.Viewport/Messages |
| `frontend/src/components/UserMessage/*`, `AssistantMessage/*` | modify | контекст useMessage; минус regenerate/thumbs |
| `frontend/src/components/ChatComposer/*` | modify | ComposerPrimitive Input/Send/Cancel |
| `frontend/src/providers/` | **delete** | вся абстракция ChatProvider + mock + заглушка |
| `frontend/Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md` | modify | минус VITE_CHAT_PROVIDER |
| `infra/e2e-chat.py` | create | скриптовый e2e: OAuth-cookie → WS → сообщение → стрим → REST-проверка треда |
| `docs/usage.md`, `docs/improvements.md` | modify | актуализация (mock ушёл; F1/F3 ✅) |

---

### Task 1: React 18 и новые зависимости

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json` (регенерация)

**Interfaces:**
- Produces: собирающийся фронтенд на React 18.3.1 с установленными `@chainlit/react-client@0.4.2`, `recoil@^0.7.7`, dev: `vitest@^3`, `happy-dom@^18` (среда для юнитов).

- [ ] **Step 1: Создать ветку**

```bash
git checkout authentik-sso && git checkout -b chat-integration
```

- [ ] **Step 2: Править `frontend/package.json`**

В `dependencies` заменить/добавить (assistant-ui и lucide не трогать):

```json
    "@chainlit/react-client": "^0.4.2",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "recoil": "^0.7.7"
```

В `devDependencies` заменить типы и добавить vitest:

```json
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "happy-dom": "^18.0.0",
    "vitest": "^3.0.0"
```

В `scripts` добавить: `"test": "vitest run"`.

- [ ] **Step 3: Регенерировать lock**

Run: `docker run --rm -v "$PWD/frontend:/app" -w /app node:22-alpine npm install --package-lock-only --no-audit --no-fund`
Expected: exit 0; в lock появились react-client 0.4.x и react 18.3.x.

- [ ] **Step 4: Проверить сборку (React 18 совместимость текущего кода)**

Run: `docker compose build frontend 2>&1 | tail -5`
Expected: `✓ built`, tsc без ошибок (код не использует React-19-специфики).

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "feat: downgrade to React 18 for recoil, add @chainlit/react-client and vitest"
```

---

### Task 2: convertMessage и threadToChat (TDD)

**Files:**
- Create: `frontend/src/chat/convertMessage.ts`, `frontend/src/chat/threadToChat.ts`
- Test: `frontend/src/chat/convertMessage.test.ts`, `frontend/src/chat/threadToChat.test.ts`

**Interfaces:**
- Produces:
  - `isChatMessage(step: IStep): boolean` — только `user_message`/`assistant_message`;
  - `convertMessage(step: IStep): ThreadMessageLike` — роль, текст из `output`, статус running при `step.streaming`;
  - `threadToChat(thread: IThread): Chat` — `{id, title: name || "Без названия", description: "", time: <локальная дата>}` (тип `Chat` из `src/types/chat.ts`).

- [ ] **Step 1: Написать `frontend/src/chat/convertMessage.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { IStep } from "@chainlit/react-client";
import { convertMessage, isChatMessage } from "./convertMessage";

const step = (over: Partial<IStep>): IStep =>
  ({
    id: "s1",
    name: "user",
    type: "user_message",
    output: "привет",
    createdAt: "2026-07-15T12:00:00Z",
    ...over,
  }) as IStep;

describe("isChatMessage", () => {
  it("пропускает только сообщения", () => {
    expect(isChatMessage(step({ type: "user_message" }))).toBe(true);
    expect(isChatMessage(step({ type: "assistant_message" }))).toBe(true);
    expect(isChatMessage(step({ type: "run" }))).toBe(false);
    expect(isChatMessage(step({ type: "tool" }))).toBe(false);
  });
});

describe("convertMessage", () => {
  it("маппит user_message", () => {
    const m = convertMessage(step({}));
    expect(m.role).toBe("user");
    expect(m.content).toEqual([{ type: "text", text: "привет" }]);
    expect(m.id).toBe("s1");
  });

  it("маппит стримящийся assistant_message в running", () => {
    const m = convertMessage(
      step({ type: "assistant_message", output: "отв", streaming: true }),
    );
    expect(m.role).toBe("assistant");
    expect(m.status?.type).toBe("running");
  });

  it("завершённый assistant_message — complete", () => {
    const m = convertMessage(step({ type: "assistant_message", streaming: false }));
    expect(m.status?.type).toBe("complete");
  });

  it("пустой output не ломает", () => {
    const m = convertMessage(step({ output: undefined as unknown as string }));
    expect(m.content).toEqual([{ type: "text", text: "" }]);
  });
});
```

- [ ] **Step 2: Написать `frontend/src/chat/threadToChat.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { IThread } from "@chainlit/react-client";
import { threadToChat } from "./threadToChat";

const thread = (over: Partial<IThread>): IThread =>
  ({ id: "t1", createdAt: "2026-07-15T12:00:00Z", steps: [], ...over }) as IThread;

describe("threadToChat", () => {
  it("маппит имя и id", () => {
    const c = threadToChat(thread({ name: "Мой чат" }));
    expect(c).toMatchObject({ id: "t1", title: "Мой чат" });
    expect(c.time.length).toBeGreaterThan(0);
  });

  it("подставляет заглушку при отсутствии имени", () => {
    expect(threadToChat(thread({})).title).toBe("Без названия");
  });
});
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `docker run --rm -v "$PWD/frontend:/app" -w /app node:22-alpine sh -c "npm ci --no-audit --no-fund >/dev/null && npm test" 2>&1 | tail -5`
Expected: FAIL — `Cannot find module './convertMessage'`.

- [ ] **Step 4: Реализовать `frontend/src/chat/convertMessage.ts`**

```ts
import type { IStep } from "@chainlit/react-client";
import type { ThreadMessageLike } from "@assistant-ui/react";

export const isChatMessage = (step: IStep): boolean =>
  step.type === "user_message" || step.type === "assistant_message";

export function convertMessage(step: IStep): ThreadMessageLike {
  const isUser = step.type === "user_message";
  return {
    id: step.id,
    role: isUser ? "user" : "assistant",
    content: [{ type: "text", text: step.output ?? "" }],
    createdAt: step.createdAt ? new Date(step.createdAt) : undefined,
    status: isUser
      ? undefined
      : step.streaming
        ? { type: "running" }
        : { type: "complete", reason: "stop" },
  };
}
```

- [ ] **Step 5: Реализовать `frontend/src/chat/threadToChat.ts`**

```ts
import type { IThread } from "@chainlit/react-client";
import type { Chat } from "../types/chat";

export function threadToChat(thread: IThread): Chat {
  return {
    id: thread.id,
    title: thread.name?.trim() || "Без названия",
    description: "",
    time: new Date(thread.createdAt).toLocaleString("ru-RU", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }),
  };
}
```

- [ ] **Step 6: Тесты зелёные**

Run: та же команда, что в Step 3.
Expected: `6 passed` (или больше, если vitest считает describe-блоки иначе); exit 0.

- [ ] **Step 7: Настроить среду vitest** — если Step 6 ругнулся на DOM/environment, добавить в `frontend/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // @ts-expect-error vitest config in vite config
  test: {
    environment: "happy-dom",
  },
});
```

(чистые функции работают и в node-環境 — шаг применять только при реальной ошибке).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/chat frontend/vite.config.ts
git commit -m "feat: add IStep->assistant-ui and IThread->Chat converters (TDD)"
```

---

### Task 3: Runtime-провайдер и живой чат (новая сессия)

**Files:**
- Create: `frontend/src/chat/chainlitClient.ts`, `frontend/src/chat/ChainlitRuntimeProvider.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/components/MessageList/MessageList.tsx`, `frontend/src/components/UserMessage/UserMessage.tsx`, `frontend/src/components/AssistantMessage/AssistantMessage.tsx`, `frontend/src/components/ChatComposer/ChatComposer.tsx`

**Interfaces:**
- Consumes: `convertMessage`, `isChatMessage` (Task 2); `useAuth` (существующий).
- Produces:
  - `chainlitApi: ChainlitAPI` + `setOn401(cb: () => void)` из `chainlitClient.ts`;
  - `<ChainlitRuntimeProvider activeThreadId={string|null} onServerThreadId={(id: string) => void}>` — внутри дети видят assistant-ui runtime, подключённый к Chainlit;
  - компоненты чата без пропсов (контекст runtime); у `AssistantMessage` осталась только кнопка «копировать».

- [ ] **Step 1: `frontend/src/chat/chainlitClient.ts`**

```ts
import { ChainlitAPI } from "@chainlit/react-client";

const baseUrl: string =
  import.meta.env.VITE_CHAINLIT_URL ?? "http://localhost:8000";

let on401: (() => void) | undefined;

export const setOn401 = (cb: () => void) => {
  on401 = cb;
};

export const chainlitApi = new ChainlitAPI(baseUrl, "webapp", undefined, () =>
  on401?.(),
);
```

- [ ] **Step 2: `frontend/src/chat/ChainlitRuntimeProvider.tsx`**

```tsx
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type AppendMessage,
} from "@assistant-ui/react";
import {
  ChainlitContext,
  useChatData,
  useChatInteract,
  useChatMessages,
  useChatSession,
} from "@chainlit/react-client";
import { useEffect, useMemo, type ReactNode } from "react";
import { RecoilRoot } from "recoil";
import { chainlitApi } from "./chainlitClient";
import { convertMessage, isChatMessage } from "./convertMessage";

interface ProviderProps {
  activeThreadId: string | null;
  onServerThreadId: (id: string) => void;
  children: ReactNode;
}

const appendMessageText = (message: AppendMessage): string =>
  message.content
    .filter((part): part is { type: "text"; text: string } => part.type === "text")
    .map((part) => part.text)
    .join("\n");

function SessionBridge({ activeThreadId, onServerThreadId, children }: ProviderProps) {
  const { connect, disconnect } = useChatSession();
  const { clear, sendMessage, stopTask, setIdToResume } = useChatInteract();
  const { messages, threadId } = useChatMessages();
  const { loading, connected } = useChatData();

  // Одна WS-сессия на активный тред: смена треда = clear + resume + reconnect.
  useEffect(() => {
    clear();
    setIdToResume(activeThreadId ?? undefined);
    void connect({ userEnv: {} });
    return () => {
      disconnect();
    };
    // connect/clear/… стабильны между рендерами (recoil-колбэки react-client)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThreadId]);

  // Сервер присвоил id новому треду (первое сообщение) — сообщаем наверх.
  useEffect(() => {
    if (threadId && threadId !== activeThreadId) {
      onServerThreadId(threadId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  const chatMessages = useMemo(() => messages.filter(isChatMessage), [messages]);

  const runtime = useExternalStoreRuntime({
    messages: chatMessages,
    convertMessage,
    isRunning: loading,
    isDisabled: connected === false,
    onNew: async (message: AppendMessage) => {
      sendMessage({
        name: "user",
        type: "user_message",
        output: appendMessageText(message),
      });
    },
    onCancel: async () => {
      stopTask();
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {connected === false ? (
        <div className="wsReconnectBanner">Переподключение к серверу…</div>
      ) : null}
      {children}
    </AssistantRuntimeProvider>
  );
}

export default function ChainlitRuntimeProvider(props: ProviderProps) {
  return (
    <RecoilRoot>
      <ChainlitContext.Provider value={chainlitApi}>
        <SessionBridge {...props} />
      </ChainlitContext.Provider>
    </RecoilRoot>
  );
}
```

- [ ] **Step 3: Переписать `MessageList.tsx`**

```tsx
import { ThreadPrimitive } from "@assistant-ui/react";
import AssistantMessage from "../AssistantMessage/AssistantMessage";
import UserMessage from "../UserMessage/UserMessage";
import styles from "./MessageList.module.css";

export default function MessageList() {
  return (
    <ThreadPrimitive.Viewport className={styles.viewport}>
      <ThreadPrimitive.Messages
        components={{ UserMessage, AssistantMessage }}
      />
    </ThreadPrimitive.Viewport>
  );
}
```

(классы из существующего `MessageList.module.css` переиспользуются; внутренние обёртки, потерявшие смысл, удалить вместе с их стилями.)

- [ ] **Step 4: Переписать `UserMessage.tsx` и `AssistantMessage.tsx` на контекст**

`UserMessage.tsx`:

```tsx
import { useMessage } from "@assistant-ui/react";
import styles from "./UserMessage.module.css";

const textOf = (content: readonly { type: string; text?: string }[]): string =>
  content
    .filter((part) => part.type === "text")
    .map((part) => part.text ?? "")
    .join("\n");

export default function UserMessage() {
  const text = useMessage((m) => textOf(m.content));
  return (
    <div className={styles.row}>
      <div className={styles.bubble}>{text}</div>
    </div>
  );
}
```

`AssistantMessage.tsx` — то же чтение текста плюс:
- индикатор набора при `useMessage((m) => m.status?.type === "running")` и пустом тексте;
- кнопка копирования (перенести существующий clipboard-fallback из App.tsx в `frontend/src/chat/copyText.ts` и звать оттуда);
- кнопки regenerate/thumbs и их стили — удалить.

Существующую разметку/классы бабблов сохранить (менять источник данных, не вёрстку).

- [ ] **Step 5: Переписать `ChatComposer.tsx` на примитивы**

```tsx
import { ComposerPrimitive, ThreadPrimitive } from "@assistant-ui/react";
import { ArrowUp, Square } from "lucide-react";
import styles from "./ChatComposer.module.css";

export default function ChatComposer() {
  return (
    <ComposerPrimitive.Root className={styles.form}>
      <ComposerPrimitive.Input
        className={styles.input}
        placeholder="Спросите что-нибудь…"
        rows={1}
        autoFocus
      />
      <ThreadPrimitive.If running={false}>
        <ComposerPrimitive.Send className={styles.sendButton} aria-label="Отправить">
          <ArrowUp size={18} />
        </ComposerPrimitive.Send>
      </ThreadPrimitive.If>
      <ThreadPrimitive.If running>
        <ComposerPrimitive.Cancel className={styles.sendButton} aria-label="Остановить">
          <Square size={16} />
        </ComposerPrimitive.Cancel>
      </ThreadPrimitive.If>
    </ComposerPrimitive.Root>
  );
}
```

- [ ] **Step 6: Промежуточный App.tsx (только новая сессия, треды — в Task 4)**

В `App()` заменить `useLocalRuntime(noopRuntimeAdapter)` (и удалить сам адаптер) на обёртку:

```tsx
return (
  <ChainlitRuntimeProvider activeThreadId={activeThreadId} onServerThreadId={setActiveThreadId}>
    <AppContent user={state.user} onLogout={() => void logout()} />
  </ChainlitRuntimeProvider>
);
```

где `activeThreadId` — `useState<string | null>(null)` в `App`. В `AppContent` на этом шаге: убрать вызовы `chatProvider`/стриминг-циклы/`composerValue`-логику, JSX чата заменить на `<MessageList />` + `<ChatComposer />` (без пропсов); сайдбар временно получает `chats={[]}`. tsc может подсветить неиспользуемые обработчики — удалить их сразу (окончательная форма — в Task 4).

Подключить 401 → экран логина: в `useAuth` добавить в возвращаемый объект
`invalidate: () => setState({ status: "anonymous", isBusy: false, error: "Сессия истекла, войдите снова." })`,
а в `App`:

```tsx
useEffect(() => {
  setOn401(invalidate);
}, [invalidate]);
```

Стиль баннера переподключения — в `frontend/src/styles/global.css`:

```css
.wsReconnectBanner {
  position: fixed;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fcd34d;
  border-radius: 10px;
  padding: 6px 14px;
  font-size: 13px;
  z-index: 100;
}
```

- [ ] **Step 7: Сборка + живая проверка нового чата**

Run: `docker compose build frontend && docker compose up -d frontend`
Затем вручную: логин на :3000 → написать сообщение → ответ агента стримится токен за токеном; кнопка Stop обрывает; в `docker compose logs backend` — обращение к Ollama без ошибок. (Нужна запущенная Ollama.)

- [ ] **Step 8: Commit**

```bash
git add frontend/src
git commit -m "feat: live chainlit chat via react-client + external store runtime"
```

---

### Task 4: Серверные треды в сайдбаре

**Files:**
- Create: `frontend/src/chat/useThreads.ts`
- Modify: `frontend/src/App.tsx`, `frontend/src/components/Sidebar/Sidebar.tsx` (если поменяются пропсы — держать `Chat[]`)

**Interfaces:**
- Consumes: `chainlitApi`, `threadToChat` (Tasks 2–3).
- Produces: `useThreads(): { chats: Chat[]; isLoading: boolean; error: string | null; refresh: () => Promise<void>; rename: (id: string, name: string) => Promise<void>; remove: (id: string) => Promise<void> }`.

- [ ] **Step 1: `frontend/src/chat/useThreads.ts`**

```ts
import { useCallback, useEffect, useState } from "react";
import type { Chat } from "../types/chat";
import { chainlitApi } from "./chainlitClient";
import { threadToChat } from "./threadToChat";

const PAGE_SIZE = 50;

export function useThreads() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { data } = await chainlitApi.listThreads({ first: PAGE_SIZE }, {});
      setChats(data.map(threadToChat));
      setError(null);
    } catch {
      setError("Не удалось загрузить список чатов.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const rename = useCallback(
    async (id: string, name: string) => {
      await chainlitApi.renameThread(id, name);
      await refresh();
    },
    [refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      await chainlitApi.deleteThread(id);
      await refresh();
    },
    [refresh],
  );

  return { chats, isLoading, error, refresh, rename, remove };
}
```

- [ ] **Step 2: Финальный `AppContent`**

- `const { chats, error: threadsError, refresh, rename, remove } = useThreads();` (внутри `ChainlitRuntimeProvider` — `AppContent` уже там).
- `activeThreadId`/`setActiveThreadId` спускаются пропсами из `App`.
- «Новый чат» → `setActiveThreadId(null)` (SessionBridge создаст свежую сессию).
- Выбор чата → `setActiveThreadId(chat.id)`.
- `onServerThreadId` в `App`: `setActiveThreadId(id)` + дёрнуть `refresh` (пробросить колбэк через ref/prop: `App` хранит `refreshRef`, `AppContent` кладёт туда `refresh`).
- Модалка rename → `rename(chatModal.chatId, value)`; delete → `remove(...)`; после удаления активного — `setActiveThreadId(null)`.
- Удалить окончательно: `PersistedChatState`, `readPersistedState`, `writePersistedState`, `STORAGE_KEY`, `messagesByChat`, `syncChatPreview`, `handleCopy`, `handleRegenerate`, `isStreaming`/`stopStreamingRef`.
- `threadsError` показать над списком в сайдбаре (пропс `errorText?: string` в Sidebar).

- [ ] **Step 3: Сборка + живая проверка тредов**

Run: `docker compose build frontend && docker compose up -d frontend`
Вручную: после первого ответа чат появился в сайдбаре с автоименем; релоад — список на месте; клик по старому чату — история восстановилась и агент помнит контекст (спросить «о чём мы говорили?»); rename/удаление работают; «Новый чат» стартует чистую сессию.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat: server-side thread list with resume, rename, delete"
```

---

### Task 5: Зачистка mock-инфраструктуры

**Files:**
- Delete: `frontend/src/providers/` (4 файла)
- Modify: `frontend/Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md`

**Interfaces:**
- Consumes: App больше не импортирует `providers` (Task 4).

- [ ] **Step 1: Удалить провайдеры и переключатель**

```bash
git rm -r frontend/src/providers
```

- `frontend/Dockerfile`: удалить `ARG VITE_CHAT_PROVIDER=mock` и его `ENV`-строку.
- `docker-compose.yml`: удалить арг `VITE_CHAT_PROVIDER` (и комментарий) из `frontend.build.args`.
- `.env.example`: удалить блок `CHAT_PROVIDER`.
- `README.md`: убрать упоминания `CHAT_PROVIDER`/mock (разделы «Настройка» и «Состояние интеграции» — теперь чат реальный; отметить, что для ответов нужна Ollama).

- [ ] **Step 2: Полная пересборка**

Run: `docker compose build frontend 2>&1 | tail -3 && docker run --rm -v "$PWD/frontend:/app" -w /app node:22-alpine sh -c "npm ci --no-audit --no-fund >/dev/null && npm test" 2>&1 | tail -3`
Expected: сборка ок; юниты зелёные.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove mock chat provider and CHAT_PROVIDER switch"
```

---

### Task 6: Скриптовый e2e и актуализация документации

**Files:**
- Create: `infra/e2e-chat.py`
- Modify: `docs/usage.md`, `docs/improvements.md`

**Interfaces:**
- Consumes: рабочий стек + Ollama; логика cookie-логина из `/tmp/lore-e2e-oauth.py` (сессионный скрипт — код ниже самодостаточен).

- [ ] **Step 1: `infra/e2e-chat.py`**

Скрипт (запуск: `python3 infra/e2e-chat.py`, зависимость: `pip install python-socketio[client]` — или запуск в контейнере `python:3.13-slim`):

```python
#!/usr/bin/env python3
"""E2E: SSO-логин → WS-чат с агентом → проверка треда в data layer.

Протокол (chainlit 2.11.1, socket.py): handshake c auth-словарём
{sessionId, threadId, userEnv, clientType}; cookie access_token
авторизует соединение; клиент шлёт "connection_successful" (триггерит
on_chat_start), сообщения — событием "client_message"; сервер стримит
"stream_token"/"new_message".
"""

import http.cookiejar
import json
import sys
import time
import urllib.parse
import urllib.request
import uuid

import socketio  # python-socketio[client]

CHAINLIT = "http://localhost:8000"
USERNAME = "akadmin"
PASSWORD = "admin"
PROMPT = "Ответь одним словом: столица Франции?"


# --- 1. SSO-логин (повторяет проверенный OAuth-флоу) -----------------------

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


no_redirect = urllib.request.build_opener(
    NoRedirect, urllib.request.HTTPCookieProcessor(jar)
)


def get_location(url):
    try:
        resp = no_redirect.open(url, timeout=15)
        return resp.headers.get("Location")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return e.headers.get("Location")
        raise


authorize_url = get_location(f"{CHAINLIT}/auth/oauth/generic")
flow_redirect = get_location(authorize_url)
parsed = urllib.parse.urlparse(urllib.parse.urljoin(authorize_url, flow_redirect))
next_q = urllib.parse.parse_qs(parsed.query).get("next", ["/"])[0]
flow_slug = [p for p in parsed.path.split("/") if p][-1]
base = f"{parsed.scheme}://{parsed.netloc}"
executor = (
    f"{base}/api/v3/flows/executor/{flow_slug}/"
    f"?query={urllib.parse.quote(urllib.parse.urlencode({'next': next_q}))}"
)

state = json.loads(opener.open(executor, timeout=15).read())
for _ in range(10):
    component = state.get("component")
    if component == "xak-flow-redirect":
        break
    if component == "ak-stage-identification":
        payload = {"uid_field": USERNAME, "component": component}
        if state.get("password_fields"):
            payload["password"] = PASSWORD
    elif component == "ak-stage-password":
        payload = {"password": PASSWORD, "component": component}
    else:
        sys.exit(f"unexpected flow component: {component}")
    req = urllib.request.Request(
        executor,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    state = json.loads(opener.open(req, timeout=15).read())

to = urllib.parse.urljoin(base, state["to"])
callback = get_location(to)
try:
    no_redirect.open(callback, timeout=30)
except urllib.error.HTTPError as e:
    if e.code not in (301, 302, 303, 307, 308):
        raise
user = json.loads(opener.open(f"{CHAINLIT}/user", timeout=15).read())
assert user["identifier"] == USERNAME
cookie_header = "; ".join(f"{c.name}={c.value}" for c in jar)
print(f"1. SSO ok ({user['identifier']})")

# --- 2. WS-чат --------------------------------------------------------------

sio = socketio.Client()
tokens: list[str] = []
done = {"flag": False}


@sio.on("stream_token")
def on_stream(data):
    tokens.append(data.get("token", ""))


@sio.on("update_message")
def on_update(data):
    done["flag"] = True


@sio.on("new_message")
def on_new(data):
    if data.get("type") == "assistant_message" and not data.get("streaming"):
        done["flag"] = True


session_id = uuid.uuid4().hex
sio.connect(
    CHAINLIT,
    socketio_path="/ws/socket.io",
    headers={"Cookie": cookie_header},
    auth={
        "sessionId": session_id,
        "threadId": None,
        "userEnv": "{}",
        "clientType": "webapp",
        "chatProfile": None,
    },
    wait_timeout=15,
)
sio.emit("connection_successful")
time.sleep(1)  # даём on_chat_start собрать агента
sio.emit(
    "client_message",
    {
        "message": {
            "id": str(uuid.uuid4()),
            "name": USERNAME,
            "type": "user_message",
            "output": PROMPT,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    },
)
deadline = time.time() + 120
while time.time() < deadline and not (done["flag"] and tokens):
    time.sleep(0.5)
sio.disconnect()
answer = "".join(tokens)
assert answer.strip(), "агент не ответил (Ollama запущена?)"
print(f"2. stream ok ({len(tokens)} токенов): {answer[:60]!r}")

# --- 3. Тред записан в data layer -------------------------------------------

req = urllib.request.Request(
    f"{CHAINLIT}/project/threads",
    data=json.dumps({"pagination": {"first": 10}, "filter": {}}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
threads = json.loads(opener.open(req, timeout=15).read())["data"]
assert threads, "тредов нет"
steps = threads[0].get("steps") or []
outputs = [s.get("output", "") for s in steps]
assert any(PROMPT in o for o in outputs), "user-сообщение не в data layer"
print(f"3. thread ok (id={threads[0]['id'][:8]}…, steps={len(steps)})")
print("E2E CHAT OK")
```

- [ ] **Step 2: Прогнать e2e**

Run: `docker run --rm --network host -v "$PWD/infra:/infra" python:3.13-slim sh -c "pip install -q 'python-socketio[client]' && python /infra/e2e-chat.py"`
(на macOS `--network host` не пробрасывает localhost — тогда запускать хостовым python3: `pip3 install --user 'python-socketio[client]' && python3 infra/e2e-chat.py`)
Expected: `1. SSO ok` → `2. stream ok` → `3. thread ok` → `E2E CHAT OK`. Если поле auth/событие не совпало (минорные различия версий) — сверить с `/opt/venv/.../chainlit/socket.py` в образе и поправить скрипт, семантика неизменна.

- [ ] **Step 3: Ручной финальный прогон** (чеклист спеки)

Логин → новый чат → стриминг → релоад → история → второй чат → переключение туда-обратно (контекст агента жив) → rename → delete → logout/login.

- [ ] **Step 4: Актуализировать документацию**

- `docs/usage.md`: раздел «Работа с чатом» — убрать абзац про mock-режим, описать серверные треды (история в Postgres, resume после релоада); в раздел «Разработка» добавить `npm test` (vitest).
- `docs/improvements.md`: пометить `✅ F1` (assistant-ui теперь на настоящем runtime) и `✅ F3` (localStorage удалён) с датой; в B1 добавить примечание, что фронтовая история теперь читается из steps (инвариант остался только на бэкенде).

- [ ] **Step 5: Commit**

```bash
git add infra/e2e-chat.py docs/usage.md docs/improvements.md
git commit -m "test: scripted WS chat e2e; docs: real chat instead of mock"
```
