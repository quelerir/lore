# Ход выполнения инструментов + рабочий лоадер Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Показать пользователю ход выполнения инструментов агента (сворачиваемый блок над ответом) и починить индикатор загрузки, который сейчас не появляется.

**Architecture:** Tool-шаги уже приходят в дерево `messages` react-client; новый чистый модуль группирует их по ответу, контекст `sessionUi` их прокидывает, новый компонент `ExecutionSteps` рендерит сворачиваемый блок в `AssistantMessage`. Лоадер привязывается к `activeMessageId` (идёт задача), а не к `streaming` конкретного сообщения. Правок бэкенда нет.

**Tech Stack:** React 18, TypeScript, `@assistant-ui/react`, `@chainlit/react-client`, Vitest, CSS-модули.

**Spec:** `docs/superpowers/specs/2026-07-16-execution-steps-and-loader-design.md`

## Global Constraints

- Рабочая директория для команд: `frontend/`. Тесты: `cd frontend && npm test`. Типы/сборка: `npm run build`.
- Комментарии — по-русски, в стиле существующего кода. CSS — модули (`*.module.css`).
- Показываем только шаги `type === "tool"`. Узлы графа, `type:"llm"` (внутренний SQL), `run` — не показываем.
- Блок «Ход выполнения» — над текстом ответа; `open` во время выполнения, свёрнут после.
- `IStep` (из `@chainlit/react-client`): поля `{ id, name, type, input, output, streaming, isError, steps, createdAt, start }`.
- Лоадер (`TypingIndicator`) показываем при `id === activeMessageId && !text`.
- После каждой задачи `npm test` и `npm run build` зелёные.

---

### Task 1: Модуль группировки tool-шагов

Чистая функция, отделяющая tool-шаги по ответу. Отдельный модуль — как `convertMessage.ts`.

**Files:**
- Create: `frontend/src/chat/executionSteps.ts`
- Test: `frontend/src/chat/executionSteps.test.ts`

**Interfaces:**
- Produces: `collectToolStepsByMessage(steps: IStep[]): Map<string, IStep[]>` — ключ = id `assistant_message`, значение = его `type:"tool"` шаги в хронологическом порядке. Ключи без tool-шагов не добавляются.

- [ ] **Step 1: Написать падающие тесты**

Создать `frontend/src/chat/executionSteps.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { IStep } from "@chainlit/react-client";
import { collectToolStepsByMessage } from "./executionSteps";

const step = (over: Partial<IStep>): IStep =>
  ({
    id: "s1",
    name: "step",
    type: "run",
    output: "",
    createdAt: "2026-07-16T09:00:00Z",
    ...over,
  }) as IStep;

describe("collectToolStepsByMessage", () => {
  it("пустая Map, если инструментов нет", () => {
    const tree: IStep[] = [
      step({ id: "u1", type: "user_message", output: "привет" }),
    ];
    expect(collectToolStepsByMessage(tree).size).toBe(0);
  });

  it("группирует tool-шаги по ответу того же on_message-run", () => {
    const tree: IStep[] = [
      step({
        id: "u1",
        type: "user_message",
        output: "грейды",
        steps: [
          step({
            id: "run1",
            name: "on_message",
            type: "run",
            steps: [
              step({ id: "a1", type: "assistant_message", output: "ответ" }),
              step({
                id: "lg",
                name: "LangGraph",
                type: "run",
                steps: [
                  step({
                    id: "t1",
                    name: "query_document_tables",
                    type: "tool",
                    input: "грейды",
                    output: "{...}",
                    createdAt: "2026-07-16T09:00:01Z",
                  }),
                ],
              }),
            ],
          }),
        ],
      }),
    ];

    const map = collectToolStepsByMessage(tree);
    expect([...map.keys()]).toEqual(["a1"]);
    expect(map.get("a1")!.map((s) => s.id)).toEqual(["t1"]);
  });

  it("не смешивает инструменты между двумя ходами", () => {
    const turn = (uid: string, aid: string, tid: string): IStep =>
      step({
        id: uid,
        type: "user_message",
        steps: [
          step({
            id: `run-${uid}`,
            type: "run",
            steps: [
              step({ id: aid, type: "assistant_message", output: "ok" }),
              step({
                id: `lg-${uid}`,
                type: "run",
                steps: [step({ id: tid, type: "tool", name: "calculator" })],
              }),
            ],
          }),
        ],
      });
    const tree: IStep[] = [turn("u1", "a1", "t1"), turn("u2", "a2", "t2")];

    const map = collectToolStepsByMessage(tree);
    expect(map.get("a1")!.map((s) => s.id)).toEqual(["t1"]);
    expect(map.get("a2")!.map((s) => s.id)).toEqual(["t2"]);
  });

  it("игнорирует llm-шаги (внутренний SQL)", () => {
    const tree: IStep[] = [
      step({
        id: "run1",
        type: "run",
        steps: [
          step({ id: "a1", type: "assistant_message", output: "ответ" }),
          step({ id: "llm1", type: "llm", name: "sql-plan" }),
        ],
      }),
    ];
    expect(collectToolStepsByMessage(tree).size).toBe(0);
  });
});
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd frontend && npm test -- executionSteps`
Expected: FAIL — не найден модуль `./executionSteps`.

- [ ] **Step 3: Реализовать модуль**

Создать `frontend/src/chat/executionSteps.ts`:

```ts
import type { IStep } from "@chainlit/react-client";

const stepTime = (step: IStep): number => {
  const value = step.start ?? step.createdAt;
  const ms = value ? new Date(value).getTime() : NaN;
  return Number.isNaN(ms) ? 0 : ms;
};

// Собирает все tool-шаги из поддерева узла (в т.ч. вложенные в run/llm).
function gatherTools(nodes: IStep[], out: IStep[]): void {
  for (const node of nodes) {
    if (node.type === "tool") out.push(node);
    if (node.steps?.length) gatherTools(node.steps, out);
  }
}

/**
 * Сопоставляет id assistant_message → его tool-шаги.
 *
 * Chainlit оборачивает on_message в run-шаг: ответ (assistant_message) и вызовы
 * инструментов лежат в одном поддереве этого run. Находим каждый run, среди
 * прямых детей которого есть assistant_message, и относим все tool-шаги этого
 * поддерева к id ответа. Ключи без инструментов в Map не попадают.
 */
export function collectToolStepsByMessage(steps: IStep[]): Map<string, IStep[]> {
  const map = new Map<string, IStep[]>();

  const walk = (nodes: IStep[]): void => {
    for (const node of nodes) {
      const children = node.steps ?? [];
      const answer = children.find((s) => s.type === "assistant_message");
      if (answer) {
        const tools: IStep[] = [];
        gatherTools(children, tools);
        if (tools.length) {
          map.set(answer.id, tools.sort((a, b) => stepTime(a) - stepTime(b)));
        }
      }
      if (children.length) walk(children);
    }
  };

  walk(steps);
  return map;
}
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd frontend && npm test -- executionSteps`
Expected: PASS (4 теста)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/chat/executionSteps.ts frontend/src/chat/executionSteps.test.ts
git commit -m "feat(frontend): group tool steps by assistant message"
```

---

### Task 2: Расширить контекст sessionUi

**Files:**
- Modify: `frontend/src/chat/sessionUi.ts`

**Interfaces:**
- Consumes: `IStep` из `@chainlit/react-client`.
- Produces: `SessionUi` с полями `switching: boolean`, `toolStepsByMessage: Map<string, IStep[]>`, `activeMessageId: string | null`. Хук `useSessionUi()` без изменений сигнатуры.

- [ ] **Step 1: Обновить интерфейс и дефолт контекста**

Заменить содержимое `frontend/src/chat/sessionUi.ts`:

```ts
import { createContext, useContext } from "react";
import type { IStep } from "@chainlit/react-client";

export interface SessionUi {
  // true, пока идёт намеренное переключение сессии (выбор треда / новый чат):
  // маскируем разрыв сокета — прячем плашку реконнекта и мигание пустого чата.
  switching: boolean;
  // id ответа (assistant_message) → его tool-шаги для блока «Ход выполнения».
  toolStepsByMessage: Map<string, IStep[]>;
  // id последнего ассистентского сообщения, пока идёт задача (loading);
  // иначе null. Управляет показом лоадера и раскрытием блока шагов.
  activeMessageId: string | null;
}

export const SessionUiContext = createContext<SessionUi>({
  switching: false,
  toolStepsByMessage: new Map(),
  activeMessageId: null,
});

export const useSessionUi = (): SessionUi => useContext(SessionUiContext);
```

- [ ] **Step 2: Проверить типы и тесты**

Run: `cd frontend && npm run build`
Expected: провайдер (`ChainlitRuntimeProvider`) даёт ошибку типа — `sessionUi` не содержит новых обязательных полей. Это ожидаемо, чиним в Task 3.

Run: `cd frontend && npm test`
Expected: существующие тесты PASS (тип-ошибка сборки не влияет на Vitest-логику).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/chat/sessionUi.ts
git commit -m "feat(frontend): extend sessionUi context with tool steps and active message"
```

---

### Task 3: Вычислять шаги и activeMessageId в провайдере

**Files:**
- Modify: `frontend/src/chat/ChainlitRuntimeProvider.tsx`

**Interfaces:**
- Consumes: `collectToolStepsByMessage` (Task 1), `SessionUi` (Task 2), `collectChatMessages` (существует), `useChatData().loading`, `useChatMessages().messages`.
- Produces: значение `SessionUiContext` с заполненными `toolStepsByMessage` и `activeMessageId`.

- [ ] **Step 1: Импортировать группировку**

В `frontend/src/chat/ChainlitRuntimeProvider.tsx` добавить импорт рядом с существующим из `./convertMessage`:

```ts
import { collectChatMessages, convertMessage } from "./convertMessage";
import { collectToolStepsByMessage } from "./executionSteps";
```

- [ ] **Step 2: Вычислить и положить в контекст**

Заменить строку с `const sessionUi = useMemo(...)` (сейчас `useMemo(() => ({ switching }), [switching])`) на вычисление всех трёх полей:

```ts
  const toolStepsByMessage = useMemo(
    () => collectToolStepsByMessage(messages),
    [messages],
  );

  // Пока идёт задача — последний ассистентский ответ считается активным:
  // на нём показываем лоадер и держим блок шагов раскрытым.
  const activeMessageId = useMemo(() => {
    if (!loading) return null;
    for (let i = chatMessages.length - 1; i >= 0; i--) {
      if (chatMessages[i].type === "assistant_message") return chatMessages[i].id;
    }
    return null;
  }, [loading, chatMessages]);

  const sessionUi = useMemo(
    () => ({ switching, toolStepsByMessage, activeMessageId }),
    [switching, toolStepsByMessage, activeMessageId],
  );
```

(`messages`, `chatMessages`, `loading` уже доступны в `SessionBridge` выше.)

- [ ] **Step 3: Проверить сборку и тесты**

Run: `cd frontend && npm run build`
Expected: PASS (типы контекста сходятся).

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/chat/ChainlitRuntimeProvider.tsx
git commit -m "feat(frontend): compute tool steps and active message in provider"
```

---

### Task 4: Компонент ExecutionSteps

**Files:**
- Create: `frontend/src/components/ExecutionSteps/ExecutionSteps.tsx`
- Create: `frontend/src/components/ExecutionSteps/ExecutionSteps.module.css`

**Interfaces:**
- Consumes: `IStep` из `@chainlit/react-client`.
- Produces: `default` React-компонент `ExecutionSteps({ steps, running }: { steps: IStep[]; running: boolean })`. Пустой `steps` → `null`.

- [ ] **Step 1: Создать компонент**

Создать `frontend/src/components/ExecutionSteps/ExecutionSteps.tsx`:

```tsx
import type { IStep } from "@chainlit/react-client";
import styles from "./ExecutionSteps.module.css";

interface Props {
  steps: IStep[];
  running: boolean;
}

export default function ExecutionSteps({ steps, running }: Props) {
  if (!steps.length) return null;

  return (
    <details className={styles.box} open={running}>
      <summary className={styles.summary}>
        Ход выполнения
        <span className={styles.count}>{steps.length}</span>
      </summary>
      <ol className={styles.list}>
        {steps.map((step) => (
          <li
            key={step.id}
            className={step.isError ? styles.itemError : styles.item}
          >
            <div className={styles.name}>{step.name}</div>
            {step.input ? <pre className={styles.io}>{step.input}</pre> : null}
            <pre className={styles.io}>
              {step.output || (step.streaming ? "…" : "")}
            </pre>
          </li>
        ))}
      </ol>
    </details>
  );
}
```

- [ ] **Step 2: Создать стили**

Создать `frontend/src/components/ExecutionSteps/ExecutionSteps.module.css`:

```css
.box {
  margin: 0 0 8px;
  border: 1px solid #e2e7ee;
  border-radius: 10px;
  background: #f7f9fb;
  font-size: 12.5px;
}

.summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  color: #5b6675;
  font-weight: 600;
  user-select: none;
}

.count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: #e2e7ee;
  color: #5b6675;
  font-size: 11px;
}

.list {
  margin: 0;
  padding: 4px 12px 10px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.item,
.itemError {
  border-left: 3px solid #c7d0db;
  padding-left: 10px;
}

.itemError {
  border-left-color: #d0463b;
}

.name {
  font-weight: 600;
  color: #2b3443;
  margin-bottom: 3px;
}

.io {
  margin: 2px 0 0;
  padding: 6px 8px;
  border-radius: 6px;
  background: #eef2f6;
  color: #3a4556;
  font-size: 11.5px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 160px;
  overflow: auto;
}
```

- [ ] **Step 3: Проверить сборку**

Run: `cd frontend && npm run build`
Expected: PASS (компонент компилируется; пока нигде не используется — это ок).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ExecutionSteps/
git commit -m "feat(frontend): ExecutionSteps collapsible block component"
```

---

### Task 5: Подключить блок и починить лоадер в AssistantMessage

**Files:**
- Modify: `frontend/src/components/AssistantMessage/AssistantMessage.tsx`

**Interfaces:**
- Consumes: `useSessionUi()` → `toolStepsByMessage`, `activeMessageId`; `ExecutionSteps` (Task 4); `useMessage`.

- [ ] **Step 1: Импортировать зависимости**

В `frontend/src/components/AssistantMessage/AssistantMessage.tsx` добавить импорты:

```tsx
import { useSessionUi } from "../../chat/sessionUi";
import ExecutionSteps from "../ExecutionSteps/ExecutionSteps";
```

- [ ] **Step 2: Прочитать id, шаги и активность; отрисовать блок и лоадер**

Внутри `AssistantMessage` добавить после `const text = useMessage(...)`:

```tsx
  const id = useMessage((m) => m.id);
  const { toolStepsByMessage, activeMessageId } = useSessionUi();
  const steps = toolStepsByMessage.get(id) ?? [];
  const isActive = id === activeMessageId;
```

Удалить старую строку `const isRunning = useMessage((m) => m.status?.type === "running");`
и заменить использование в JSX. Кнопка копирования блокируется, пока идёт
задача, поэтому `disabled={isActive}`.

Заменить блок `.bubble`/`.actions` на:

```tsx
      <div className={styles.content}>
        <ExecutionSteps steps={steps} running={isActive} />
        <div className={styles.bubble}>
          {text ? (
            <Markdown remarkPlugins={REMARK_PLUGINS}>{text}</Markdown>
          ) : isActive ? (
            <TypingIndicator />
          ) : null}
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            onClick={() => void handleCopy()}
            aria-label={isCopied ? "Скопировано" : "Копировать ответ"}
            title={isCopied ? "Скопировано" : "Копировать"}
            disabled={isActive}
          >
            {isCopied ? <Check size={16} /> : <Copy size={16} />}
          </button>
        </div>
      </div>
```

- [ ] **Step 3: Проверить сборку и тесты**

Run: `cd frontend && npm run build`
Expected: PASS (нет неиспользуемых переменных, типы сходятся).

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AssistantMessage/AssistantMessage.tsx
git commit -m "feat(frontend): render execution steps and fix loader in AssistantMessage"
```

---

### Task 6: Ручная проверка в UI

Дымовая проверка сквозного поведения при поднятом стеке (backend с `TOAST_DATABASE_URL` и `OPENROUTER_API_KEY`, frontend dev/сборка).

**Files:** —

- [ ] **Step 1: Собрать фронтенд**

Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 2: Проверить сценарии вручную**

- Вопрос «столица Франции?» → точки-лоадер появляются сразу под пустым пузырём, блока «Ход выполнения» нет.
- Вопрос про грейды контекстной рекламы → над ответом блок «Ход выполнения» с шагом `query_document_tables` (вход-вопрос, выход-JSON), раскрыт во время ответа, свёрнут после завершения.
- При ошибке инструмента (`isError`) шаг помечен красным.

Если поведение не совпало — вернуться к соответствующей задаче, не «чинить на месте».

- [ ] **Step 3: Финальная проверка набора**

Run: `cd frontend && npm test && npm run build`
Expected: все тесты PASS, сборка PASS.

---

## Верификация плана целиком

1. `cd frontend && npm test` — `executionSteps.test.ts` и существующие тесты зелёные.
2. `cd frontend && npm run build` — типы и сборка без ошибок.
3. Ручные сценарии из Task 6 воспроизводятся.
4. Бэкенд и `.chainlit/config.toml` не менялись (`git diff --stat` не содержит backend-файлов).
