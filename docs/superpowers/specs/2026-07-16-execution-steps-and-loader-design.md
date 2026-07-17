# Ход выполнения инструментов + рабочий индикатор загрузки

Дата: 2026-07-16. Статус: утверждён.

## Проблема

1. Пользователь не видит, что делает агент во время долгого ответа (deep-режим,
   toast-субагент с discovery/inspect/SQL). Кажется, что всё зависло.
2. Индикатор загрузки (`TypingIndicator`, три точки в `AssistantMessage`) на
   практике **не появляется**: пустой ассистентский пузырь получает статус
   `running` только с приходом первого текстового токена, а для toast/deep
   первые токены (SQL-планирование) отфильтрованы как `internal`.

## Контекст архитектуры

Фронтенд кастомный: `@assistant-ui/react` (external store runtime) поверх
`@chainlit/react-client`. `LangchainCallbackHandler` (уже подключён в
`handle_message`) создаёт шаги графа и инструментов. Они **уже приходят** в
дерево `messages` react-client как `IStep`:

```
user_message
└─ run  (on_message)
   ├─ assistant_message      ← ответ (out = cl.Message)
   └─ run  (LangGraph)
      └─ ... type:"tool" ...  ← вызовы инструментов (name/input/output/isError/streaming)
```

`IStep` (react-client): `{ id, name, type: StepType, input, output, streaming,
isError, steps, createdAt, start }`, где `StepType` включает `tool`, `llm`,
`run`, `assistant_message`, `user_message`.

Сейчас `collectChatMessages` (в `convertMessage.ts`) обходит дерево и оставляет
только `user_message`/`assistant_message`, отбрасывая tool-шаги. Внутренний
SQL-LLM имеет `type:"llm"` — в блок инструментов он не попадёт по определению.

## Решения обсуждения

| Вопрос | Решение |
| --- | --- |
| Детализация | Только инструменты (`type:"tool"`): имя, вход, результат. Узлы графа и llm-шаги не показываем |
| Размещение | Сворачиваемый блок «Ход выполнения» НАД текстом ответа; раскрыт во время выполнения, сворачивается после |
| Лоадер | Чиним: `TypingIndicator` привязываем к «идёт активная задача», а не к `streaming` конкретного сообщения |
| Бэкенд | Не трогаем: правок в `app.py`/`config.toml` не требуется |

## Компоненты

### `frontend/src/chat/executionSteps.ts` (новый, чистый модуль)

```ts
import type { IStep } from "@chainlit/react-client";

// Сопоставляет id assistant_message → его tool-шаги (хронологически).
// Ключ — id ответа; tool-шаги берутся из того же on_message-run.
export function collectToolStepsByMessage(steps: IStep[]): Map<string, IStep[]>;
```

Алгоритм: обойти дерево; для каждого `run`, у которого среди прямых детей есть
`assistant_message`, собрать все `type:"tool"` шаги из его поддерева и
сопоставить их id этого `assistant_message`. Пустой список → ключ не
добавляется. Чистая функция без React — покрывается unit-тестами.

### `frontend/src/chat/sessionUi.ts` (расширяется)

Добавляются поля контекста:

```ts
export interface SessionUi {
  switching: boolean;
  toolStepsByMessage: Map<string, IStep[]>;
  // id последнего ассистентского сообщения, пока идёт задача (loading);
  // иначе null. Управляет показом лоадера.
  activeMessageId: string | null;
}
```

Дефолт контекста дополняется пустой `Map` и `null`.

### `frontend/src/chat/ChainlitRuntimeProvider.tsx` (правится)

В `SessionBridge` через `useMemo` из сырого `messages` вычисляются:
- `toolStepsByMessage = collectToolStepsByMessage(messages)`;
- `activeMessageId` — id последнего `assistant_message` (из `chatMessages`),
  если `loading === true`, иначе `null`.

Оба кладутся в `SessionUiContext` рядом со `switching`.

### `frontend/src/components/ExecutionSteps/ExecutionSteps.tsx` (новый) + CSS-модуль

Пропсы: `{ steps: IStep[]; running: boolean }`. Рендер:
- `<details>` с заголовком «Ход выполнения» (`open` = `running`);
- список шагов: имя инструмента, `input` и `output` моноширинно; `isError` —
  красным акцентом; пустой `output` при `streaming` — «…».
- Пустой `steps` → компонент возвращает `null`.

### `frontend/src/components/AssistantMessage/AssistantMessage.tsx` (правится)

- Из `useSessionUi()` берём `toolStepsByMessage` и `activeMessageId`, из
  `useMessage((m) => m.id)` — id текущего сообщения.
- Над `.bubble` рендерим `<ExecutionSteps steps={steps} running={id === activeMessageId} />`,
  если шаги есть.
- **Фикс лоадера:** `TypingIndicator` показываем при
  `id === activeMessageId && !text` (не завися от `m.status`). Закрывает
  «пустую паузу» до первого токена, в т.ч. когда токены отфильтрованы.

## Поток данных

`messages` (react-client, обновляется живьём) → `useMemo` в `SessionBridge` →
`{ toolStepsByMessage, activeMessageId }` → `SessionUiContext` →
`AssistantMessage` по своему id достаёт шаги → `ExecutionSteps` (раскрыт пока
`running`) и/или `TypingIndicator`. Tool-шаги появляются в дереве по мере
выполнения — блок наполняется в реальном времени.

## Обработка ошибок

- `IStep.isError === true` → шаг помечается красным акцентом.
- Пустой `output` → «…» (шаг ещё выполняется) либо пусто (завершён без вывода).
- Нет tool-шагов → блок не рендерится, поведение как раньше (обычный ответ).
- Отсутствие `activeMessageId` (задача не идёт) → ни лоадера, ни ложного
  раскрытия блока.

## Тестирование

- **`frontend/src/chat/executionSteps.test.ts` (новый, Vitest):**
  - плоское дерево без инструментов → пустая Map;
  - `on_message`-run с `assistant_message` + вложенными `tool` в `LangGraph`-run
    → ключ = id ответа, значение = tool-шаги в хронологическом порядке;
  - два хода (два `on_message`-run) → инструменты не смешиваются между ответами;
  - `type:"llm"` (внутренний SQL) в список инструментов не попадает.
  (Форма шагов — по образцу `convertMessage.test.ts`.)
- **`convertMessage.test.ts`** — без изменений (логика чат-сообщений та же).
- **Ручная проверка:** вопрос про грейды контекстной рекламы → блок «Ход
  выполнения» с шагом `query_document_tables` (вход-вопрос, выход-JSON),
  раскрыт во время ответа, свёрнут после; короткий вопрос («столица Франции»)
  → точки-лоадер появляются сразу, блока нет.

## Вне scope (YAGNI)

- Узлы графа и llm-шаги в UI не показываем.
- Бэкенд и `.chainlit/config.toml` не трогаем.
- Никакого маппинга имён инструментов в человеческие подписи/переводы.
- Не переносим tool-шаги в assistant-ui `tool-call` content parts — держим
  отдельным блоком через контекст (меньше связанности с рантаймом).
