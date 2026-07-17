# Full Trace View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Панель «Ход выполнения» показывает ПОЛНОЕ дерево шагов Chainlit (llm/tool/run) с бейджами типов и длительностями — LangSmith-подобный трейс для дебага; SQL-режим тоже отдаёт llm-шаги.

**Architecture:** Сборщик перестаёт фильтровать по `type === "tool"` и отдаёт всё поддерево хода (кроме `*_message`-шагов) с нетронутой вложенностью; рекурсивный `StepItem` дополняется бейджем типа и длительностью. Бэкенд SQL-демо получает `LangchainCallbackHandler`, чтобы LLM-вызовы графа становились шагами.

**Tech Stack:** React 18/TypeScript/vitest/happy-dom, `@chainlit/react-client` (IStep), Chainlit 2.x, langgraph.

**Spec:** `docs/superpowers/specs/2026-07-17-full-trace-view-design.md`

## Global Constraints

- Ветка: `demo/sql-chat` (всё — поверх рекурсивного рендера, который уже там).
- Всегда включено, та же панель — никаких тумблеров/env-флагов.
- Счётчики токенов НЕ делаем; серверную cot-фильтрацию Chainlit НЕ трогаем.
- Фронтенд-команды из `frontend/` с Node 22: `export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH"` перед `npm test` / `npm run build`.
- Бэкенд-команды из `backend/`: `uv run pytest tests/ -q`, `uv run ruff check .`.

---

### Task 1: Сборщик отдаёт полный трейс (`collectTraceByMessage`)

**Files:**
- Modify: `frontend/src/chat/executionSteps.ts`
- Modify: `frontend/src/chat/sessionUi.ts`
- Modify: `frontend/src/chat/ChainlitRuntimeProvider.tsx` (импорт, `useMemo`, объект контекста)
- Modify: `frontend/src/components/AssistantMessage/AssistantMessage.tsx:32-33`
- Test: `frontend/src/chat/executionSteps.test.ts`

**Interfaces:**
- Consumes: `IStep` (`type`, `steps`, `start`, `createdAt`) из `@chainlit/react-client`.
- Produces: `collectTraceByMessage(steps: IStep[]): Map<string, IStep[]>` — id ответа → ВСЕ шаги его run'а кроме `*_message`, вложенность цела; `MESSAGE_TYPES: Set<string>` (экспорт — рендер тоже фильтрует детей); поле контекста `SessionUi.traceByMessage` (вместо `toolStepsByMessage`).

- [ ] **Step 1: Обновить тесты под новый контракт**

Заменить содержимое `frontend/src/chat/executionSteps.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import type { IStep } from "@chainlit/react-client";
import { collectTraceByMessage } from "./executionSteps";

const step = (over: Partial<IStep>): IStep =>
  ({
    id: "s1",
    name: "step",
    type: "run",
    output: "",
    createdAt: "2026-07-16T09:00:00Z",
    ...over,
  }) as IStep;

describe("collectTraceByMessage", () => {
  it("пустая Map, если хода нет", () => {
    const tree: IStep[] = [
      step({ id: "u1", type: "user_message", output: "привет" }),
    ];
    expect(collectTraceByMessage(tree).size).toBe(0);
  });

  it("отдаёт всё поддерево run'а: контейнеры и вложенные шаги", () => {
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
                  step({ id: "t1", name: "calculator", type: "tool" }),
                ],
              }),
            ],
          }),
        ],
      }),
    ];

    const map = collectTraceByMessage(tree);
    expect([...map.keys()]).toEqual(["a1"]);
    expect(map.get("a1")!.map((s) => s.id)).toEqual(["lg"]);
    expect(map.get("a1")![0].steps!.map((s) => s.id)).toEqual(["t1"]);
  });

  it("llm-шаги входят в трейс", () => {
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
    expect(collectTraceByMessage(tree).get("a1")!.map((s) => s.id)).toEqual([
      "llm1",
    ]);
  });

  it("*_message-шаги в трейс не попадают", () => {
    const tree: IStep[] = [
      step({
        id: "run1",
        type: "run",
        steps: [
          step({ id: "u1", type: "user_message", output: "вопрос" }),
          step({ id: "a1", type: "assistant_message", output: "ответ" }),
          step({ id: "t1", type: "tool", name: "calculator" }),
        ],
      }),
    ];
    expect(collectTraceByMessage(tree).get("a1")!.map((s) => s.id)).toEqual([
      "t1",
    ]);
  });

  it("не смешивает трейсы двух ходов", () => {
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
              step({ id: tid, type: "tool", name: "calculator" }),
            ],
          }),
        ],
      });
    const tree: IStep[] = [turn("u1", "a1", "t1"), turn("u2", "a2", "t2")];

    const map = collectTraceByMessage(tree);
    expect(map.get("a1")!.map((s) => s.id)).toEqual(["t1"]);
    expect(map.get("a2")!.map((s) => s.id)).toEqual(["t2"]);
  });

  it("вложенные tool-шаги остаются детьми и не дублируются на верхнем уровне", () => {
    const tree: IStep[] = [
      step({
        id: "run1",
        type: "run",
        steps: [
          step({ id: "a1", type: "assistant_message", output: "ответ" }),
          step({
            id: "stage1",
            name: "Выполнение SQL — раунд 1",
            type: "tool",
            steps: [
              step({ id: "att1", name: "Попытка 1", type: "tool" }),
              step({ id: "att2", name: "Попытка 2", type: "tool" }),
            ],
          }),
        ],
      }),
    ];
    const map = collectTraceByMessage(tree);
    expect(map.get("a1")!.map((s) => s.id)).toEqual(["stage1"]);
    expect(map.get("a1")![0].steps!.map((s) => s.id)).toEqual(["att1", "att2"]);
  });
});
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd frontend && export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" && npm test`
Expected: FAIL — `collectTraceByMessage` не экспортируется.

- [ ] **Step 3: Реализация сборщика**

Заменить содержимое `frontend/src/chat/executionSteps.ts`:

```typescript
import type { IStep } from "@chainlit/react-client";

// Шаги-сообщения — контент чата, в трейс не входят (ни на одном уровне).
export const MESSAGE_TYPES = new Set([
  "user_message",
  "assistant_message",
  "system_message",
]);

const stepTime = (step: IStep): number => {
  const value = step.start ?? step.createdAt;
  const ms = value ? new Date(value).getTime() : NaN;
  return Number.isNaN(ms) ? 0 : ms;
};

/**
 * Сопоставляет id assistant_message → полный трейс его хода.
 *
 * Chainlit оборачивает on_message в run-шаг: ответ (assistant_message) и весь
 * ход (llm/tool/run) лежат в одном поддереве этого run. Находим каждый run,
 * среди прямых детей которого есть assistant_message, и отдаём ВСЕ его
 * дочерние шаги, кроме *_message, с нетронутой вложенностью step.steps —
 * LangSmith-подобное дерево для дебага.
 */
export function collectTraceByMessage(steps: IStep[]): Map<string, IStep[]> {
  const map = new Map<string, IStep[]>();

  const walk = (nodes: IStep[]): void => {
    for (const node of nodes) {
      const children = node.steps ?? [];
      const answer = children.find((s) => s.type === "assistant_message");
      if (answer) {
        const trace = children
          .filter((s) => !MESSAGE_TYPES.has(s.type))
          .sort((a, b) => stepTime(a) - stepTime(b));
        if (trace.length) map.set(answer.id, trace);
      }
      if (children.length) walk(children);
    }
  };

  walk(steps);
  return map;
}
```

- [ ] **Step 4: Переименовать поле контекста**

В `frontend/src/chat/sessionUi.ts` заменить:

```typescript
  // id ответа (assistant_message) → его tool-шаги для блока «Ход выполнения».
  toolStepsByMessage: Map<string, IStep[]>;
```

на:

```typescript
  // id ответа (assistant_message) → полный трейс хода (llm/tool/run) для
  // блока «Ход выполнения».
  traceByMessage: Map<string, IStep[]>;
```

и в дефолте контекста `toolStepsByMessage: new Map(),` → `traceByMessage: new Map(),`.

В `frontend/src/chat/ChainlitRuntimeProvider.tsx`:
- импорт: `import { collectTraceByMessage } from "./executionSteps";`
- `useMemo`: `const traceByMessage = useMemo(() => collectTraceByMessage(messages), [messages]);`
- объект контекста: `() => ({ switching, traceByMessage, activeMessageId }), [switching, traceByMessage, activeMessageId],`

В `frontend/src/components/AssistantMessage/AssistantMessage.tsx`:

```typescript
  const { traceByMessage, activeMessageId } = useSessionUi();
  const steps = traceByMessage.get(id) ?? [];
```

- [ ] **Step 5: Прогнать тесты и сборку**

Run: `cd frontend && export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" && npm test && npm run build`
Expected: все PASS, сборка чистая (компилятор поймает пропущенные переименования).

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/chat/executionSteps.ts src/chat/executionSteps.test.ts \
        src/chat/sessionUi.ts src/chat/ChainlitRuntimeProvider.tsx \
        src/components/AssistantMessage/AssistantMessage.tsx
git commit -m "feat(demo): collect full step trace per message, not only tools"
```

---

### Task 2: `formatDuration` — длительность шага

**Files:**
- Modify: `frontend/src/chat/executionSteps.ts` (добавить функцию)
- Test: `frontend/src/chat/executionSteps.test.ts` (дополнить)

**Interfaces:**
- Produces: `formatDuration(start?: string, end?: string): string | null` — ISO-строки из `IStep.start`/`IStep.end`; `< 1000 мс` → `"N мс"`, иначе `"N.N с"`; нет границ / мусор / отрицательное → `null`.

- [ ] **Step 1: Написать падающие тесты**

Добавить в `frontend/src/chat/executionSteps.test.ts` (импорт дополнить: `import { collectTraceByMessage, formatDuration } from "./executionSteps";`):

```typescript
describe("formatDuration", () => {
  it("миллисекунды до секунды", () => {
    expect(
      formatDuration("2026-07-17T09:00:00.000Z", "2026-07-17T09:00:00.450Z"),
    ).toBe("450 мс");
  });

  it("секунды с одним знаком", () => {
    expect(
      formatDuration("2026-07-17T09:00:00.000Z", "2026-07-17T09:00:01.230Z"),
    ).toBe("1.2 с");
  });

  it("null без границ или с мусором", () => {
    expect(formatDuration(undefined, "2026-07-17T09:00:01Z")).toBeNull();
    expect(formatDuration("2026-07-17T09:00:01Z", undefined)).toBeNull();
    expect(formatDuration("не дата", "2026-07-17T09:00:01Z")).toBeNull();
    // end раньше start — часы разъехались, не показываем ерунду
    expect(
      formatDuration("2026-07-17T09:00:02Z", "2026-07-17T09:00:01Z"),
    ).toBeNull();
  });
});
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd frontend && export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" && npm test`
Expected: FAIL — `formatDuration` не экспортируется.

- [ ] **Step 3: Реализация**

Добавить в конец `frontend/src/chat/executionSteps.ts`:

```typescript
/** Длительность шага для трейса: "450 мс" / "1.2 с"; null, если границ нет. */
export function formatDuration(start?: string, end?: string): string | null {
  if (!start || !end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${Math.round(ms)} мс`;
  return `${(ms / 1000).toFixed(1)} с`;
}
```

- [ ] **Step 4: Прогнать тесты, закоммитить**

Run: `cd frontend && export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" && npm test`
Expected: все PASS.

```bash
cd frontend
git add src/chat/executionSteps.ts src/chat/executionSteps.test.ts
git commit -m "feat(demo): step duration formatter for trace view"
```

---

### Task 3: Рендер — бейджи типов и длительность

**Files:**
- Modify: `frontend/src/components/ExecutionSteps/ExecutionSteps.tsx`
- Modify: `frontend/src/components/ExecutionSteps/ExecutionSteps.module.css`
- Test: `frontend/src/components/ExecutionSteps/ExecutionSteps.test.tsx`

**Interfaces:**
- Consumes: `formatDuration`, `MESSAGE_TYPES` из `../../chat/executionSteps` (Task 1–2); проп-контракт `ExecutionSteps({ steps, running })` не меняется.

- [ ] **Step 1: Дополнить рендер-тест**

Заменить содержимое `frontend/src/components/ExecutionSteps/ExecutionSteps.test.tsx`:

```tsx
/** @vitest-environment happy-dom */
import { describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { IStep } from "@chainlit/react-client";
import ExecutionSteps from "./ExecutionSteps";

const step = (over: Partial<IStep>): IStep =>
  ({
    id: "s",
    name: "step",
    type: "tool",
    output: "",
    createdAt: "2026-07-17T09:00:00Z",
    start: "2026-07-17T09:00:00.000Z",
    end: "2026-07-17T09:00:00.450Z",
    ...over,
  }) as IStep;

async function render(steps: IStep[]) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(<ExecutionSteps steps={steps} running={false} />);
  });
  return host;
}

describe("ExecutionSteps", () => {
  it("рендерит двухуровневое дерево сворачиваемых стадий", async () => {
    const stage = step({
      id: "stage1",
      name: "Выполнение SQL — раунд 1",
      steps: [
        step({ id: "att1", name: "Попытка 1", input: "SELECT 1", output: "[]" }),
        step({ id: "att2", name: "Попытка 2", isError: true, output: "Ошибка" }),
      ],
    });
    const host = await render([stage]);
    expect(host.textContent).toContain("Выполнение SQL — раунд 1");
    expect(host.textContent).toContain("Попытка 1");
    expect(host.textContent).toContain("Попытка 2");
    // details: панель + стадия + 2 попытки
    expect(host.querySelectorAll("details").length).toBe(4);
  });

  it("показывает бейдж типа и длительность", async () => {
    const llm = step({
      id: "llm1",
      name: "ChatOpenAI",
      type: "llm",
      end: "2026-07-17T09:00:01.230Z",
    });
    const host = await render([llm]);
    expect(host.textContent).toContain("llm");
    expect(host.textContent).toContain("1.2 с");
  });

  it("run-контейнер без input/output не рендерит пустые pre", async () => {
    const run = step({ id: "run1", name: "LangGraph", type: "run" });
    const host = await render([run]);
    expect(host.querySelectorAll("pre").length).toBe(0);
  });
});
```

- [ ] **Step 2: Убедиться, что новые тесты падают**

Run: `cd frontend && export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" && npm test`
Expected: FAIL — нет бейджа/длительности; у run рендерится пустой `pre` output.

- [ ] **Step 3: Реализация — заменить `ExecutionSteps.tsx` целиком**

```tsx
import type { IStep } from "@chainlit/react-client";
import { formatDuration, MESSAGE_TYPES } from "../../chat/executionSteps";
import styles from "./ExecutionSteps.module.css";

interface Props {
  steps: IStep[];
  running: boolean;
}

function statusMark(step: IStep): string {
  if (step.isError) return "✗";
  if (step.streaming || !step.end) return "…";
  return "✓";
}

function StepItem({ step }: { step: IStep }) {
  const children = (step.steps ?? []).filter((s) => !MESSAGE_TYPES.has(s.type));
  const isRunning = Boolean(step.streaming) || !step.end;
  const duration = formatDuration(step.start, step.end);
  return (
    <li className={step.isError ? styles.itemError : styles.item}>
      <details open={isRunning}>
        <summary className={styles.stepSummary}>
          <span className={styles.mark}>{statusMark(step)}</span>
          <span className={styles.typeBadge}>{step.type}</span>
          <span className={styles.stepName}>{step.name}</span>
          {duration ? <span className={styles.duration}>{duration}</span> : null}
        </summary>
        {step.input ? <pre className={styles.io}>{step.input}</pre> : null}
        {step.output || step.streaming ? (
          <pre className={styles.io}>
            {step.output || (step.streaming ? "…" : "")}
          </pre>
        ) : null}
        {children.length ? (
          <ol className={styles.list}>
            {children.map((child) => (
              <StepItem key={child.id} step={child} />
            ))}
          </ol>
        ) : null}
      </details>
    </li>
  );
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
          <StepItem key={step.id} step={step} />
        ))}
      </ol>
    </details>
  );
}
```

- [ ] **Step 4: CSS — бейдж, имя, длительность**

В `frontend/src/components/ExecutionSteps/ExecutionSteps.module.css` добавить после блока `.mark`:

```css
.typeBadge {
  flex-shrink: 0;
  padding: 1px 5px;
  border-radius: 4px;
  background: #e2e7ee;
  color: #5b6675;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  text-transform: lowercase;
}

.stepName {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.duration {
  margin-left: auto;
  flex-shrink: 0;
  color: #8a94a3;
  font-weight: 400;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
```

- [ ] **Step 5: Прогнать тесты и сборку, закоммитить**

Run: `cd frontend && export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" && npm test && npm run build`
Expected: все PASS, сборка чистая.

```bash
cd frontend
git add src/components/ExecutionSteps/
git commit -m "feat(demo): type badges and durations in trace view"
```

---

### Task 4: LLM-шаги в SQL-режиме + ручная проверка

**Files:**
- Modify: `backend/sql_demo.py` (вызов `graph.astream` в `handle_sql_message`)
- Modify: `docs/sql-demo.md` (пункт сценария про трейс)

**Interfaces:**
- Consumes: `cl.LangchainCallbackHandler` (Chainlit), `RunnableConfig` (`langchain_core.runnables`) — тот же паттерн, что в `app.handle_message`.

- [ ] **Step 1: Передать колбэк в прогон графа**

В `backend/sql_demo.py` добавить импорт:

```python
from langchain_core.runnables import RunnableConfig
```

и заменить вызов:

```python
    async for mode, payload in graph.astream(
        inputs, stream_mode=["updates", "messages", "values"]
    ):
```

на:

```python
    # Колбэк превращает LLM-вызовы узлов (generate/judge/summarize) в
    # llm-шаги Chainlit — полный трейс для дебага. Тег internal скрывает
    # только их токены из стрима сообщения, шаги остаются видимыми.
    config = RunnableConfig(callbacks=[cl.LangchainCallbackHandler()])
    async for mode, payload in graph.astream(
        inputs, stream_mode=["updates", "messages", "values"], config=config
    ):
```

- [ ] **Step 2: Тесты и линтер бэкенда**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`
Expected: 0 failed, `All checks passed!`

- [ ] **Step 3: Дополнить сценарий показа**

В `docs/sql-demo.md` в раздел «Сценарий показа» после пункта 3 добавить:

```markdown
3а. Там же видны llm-шаги (промпт и ответ generate/judge/summarize) и
    run-контейнеры — полный трейс, приближенный к LangSmith: у каждого узла
    бейдж типа и длительность.
```

- [ ] **Step 4: Ручная проверка**

Поднять бэкенд+фронтенд (`docs/sql-demo.md`), задать вопрос в режиме
«SQL (демо)» и в fast-режиме («сколько 17*23?»):
- в трейсе видны llm-шаги с промптами, tool-шаги, run-контейнеры;
- у узлов бейджи `llm`/`tool`/`run` и длительности;
- всё сворачивается на каждом уровне; resume старого треда воспроизводит трейс.

- [ ] **Step 5: Commit**

```bash
git add backend/sql_demo.py docs/sql-demo.md
git commit -m "feat(demo): LLM steps in SQL mode trace via LangchainCallbackHandler"
```

---

## Final Verification

- [ ] `cd frontend && npm test && npm run build` — чисто (Node 22)
- [ ] `cd backend && uv run pytest tests/ -q && uv run ruff check .` — чисто
- [ ] Ручная проверка из Task 4 Step 4 пройдена
- [ ] Все коммиты — в `demo/sql-chat`, ветка запушена
