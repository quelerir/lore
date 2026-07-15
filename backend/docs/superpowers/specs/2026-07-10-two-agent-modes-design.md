# Дизайн: два режима работы агента (Deep / Fast)

**Дата:** 2026-07-10
**Статус:** согласован, готов к планированию реализации

## Проблема

`deepagents` слишком сложен для маленьких LLM — они путаются в его многоступенчатой
оркестрации. Нужно два режима работы:

- **Deep** — умный режим через `deepagents` (текущее поведение).
- **Fast** — простой режим через чистый `langgraph`. Сейчас без tool-calling,
  но структура графа готовится под его добавление в будущем.

## Решения (зафиксированы)

| Вопрос | Решение |
|--------|---------|
| Выбор режима | Chainlit **Chat Profiles** (выбор в UI при старте чата) |
| Модель vs режим | Ортогональны; модель задаётся отдельно через env/конфиг |
| Форма простого графа | `StateGraph` + одна нода-LLM + заготовка (TODO) под `ToolNode` |
| Имена режимов | UI-профили **Deep** / **Fast**; в коде `Mode.DEEP` / `Mode.FAST` |

## Структура файлов

```
agents/
  __init__.py    # Mode enum + build_agent(mode, model=None) -> CompiledStateGraph
  base.py        # build_model() из env, SYSTEM_PROMPT, Mode, маппинг профиль->Mode
  deep.py        # build_deep_agent(model) — deepagents (перенос текущего agent.py)
  fast.py        # build_fast_agent(model) — plain langgraph
app.py           # Chat Profiles + диспетчер режима (правки)
auth.py          # без изменений
agent.py         # УДАЛЯЕТСЯ (логика уезжает в agents/deep.py)
```

`agent.py` разбивается на пакет `agents/`. Обновляется `pyproject.toml`
(`py-modules` → `packages`/подключение пакета `agents`).

## Компоненты

### `agents/base.py`
- `Mode` — enum: `DEEP`, `FAST`.
- `SYSTEM_PROMPT` — общий системный промпт (перенос из `agent.py`). Может
  разойтись между режимами позже; пока общий.
- `build_model() -> ChatOllama` — читает `OLLAMA_MODEL` / `OLLAMA_BASE_URL`
  из env (как сейчас). Одна конфигурация модели, общая для обоих режимов.
- `PROFILE_TO_MODE: dict[str, Mode]` — маппинг имени Chat Profile → `Mode`
  (`"Deep" -> DEEP`, `"Fast" -> FAST`). Единая точка соответствия UI↔код.

### `agents/deep.py`
- `build_deep_agent(model) -> CompiledStateGraph` — текущая логика:
  `create_deep_agent(tools=[], system_prompt=SYSTEM_PROMPT, model=model)`.

### `agents/fast.py`
- `build_fast_agent(model) -> CompiledStateGraph`:
  ```python
  async def call_model(state):  # state: MessagesState
      messages = [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
      return {"messages": [await model.ainvoke(messages)]}

  graph = StateGraph(MessagesState)
  graph.add_node("model", call_model)
  graph.add_edge(START, "model")
  # TODO tool-calling: ToolNode + conditional edge model->tools->model
  graph.add_edge("model", END)
  return graph.compile()
  ```
- Форма графа сразу «взрослая» (StateGraph / MessagesState / START-END) с
  TODO-точкой под будущий `ToolNode` и условное ребро.

### `agents/__init__.py`
- `build_agent(mode: Mode, model=None) -> CompiledStateGraph`:
  - если `model is None` → `model = build_model()`;
  - `DEEP` → `build_deep_agent(model)`, `FAST` → `build_fast_agent(model)`.
- Реэкспорт `Mode`, `build_agent`.

### `app.py` (правки)
- `@cl.set_chat_profiles` → два `cl.ChatProfile("Deep", ...)`,
  `cl.ChatProfile("Fast", ...)` с описаниями. Дефолт — `Deep`.
- В `on_chat_start` и `on_chat_resume`:
  - `profile = cl.user_session.get("chat_profile")`;
  - `mode = PROFILE_TO_MODE.get(profile, Mode.DEEP)`;
  - `cl.user_session.set("agent", build_agent(mode))`.
- `handle_message` — **без изменений**: оба режима возвращают
  `CompiledStateGraph`, стриминг через `stream_mode="messages"` работает для обоих.

## Поток данных

```
UI: выбор Chat Profile ("Deep"/"Fast")
      -> Chainlit сохраняет chat_profile в user_session (и на треде)
on_chat_start / on_chat_resume
      -> PROFILE_TO_MODE -> Mode
      -> build_agent(mode) -> CompiledStateGraph -> user_session["agent"]
on_message
      -> handle_message(agent, history, out)  # неизменён
      -> agent.astream(stream_mode="messages") -> stream_token
```

## Обработка ошибок
- Неизвестный/отсутствующий профиль → дефолт `Mode.DEEP` (без падения).
- `handle_message` сохраняет текущее поведение (агент `None` → сообщение
  «Agent not initialised»).

## Тестирование
- `tests/test_agents.py` (замена `tests/test_agent.py`):
  - `build_agent(Mode.DEEP)` и `build_agent(Mode.FAST)` возвращают
    `CompiledStateGraph`;
  - `PROFILE_TO_MODE` корректно мапит имена и падает в `DEEP` по умолчанию;
  - дымовой прогон `fast`-графа с мок-моделью: один шаг, ответ добавлен в
    `messages`.
- `tests/test_app_imports.py` — обновить импорты под новый пакет.

## Вне области (YAGNI сейчас)
- Реальный tool-calling в `fast`-режиме (только заготовка/TODO).
- Отдельная модель на режим (конфигурация модели пока одна).
- Переключение режима внутри уже начатого чата (режим фиксируется профилем на треде).
