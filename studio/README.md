# LangGraph Studio-раннер SQL-инструмента

Опциональный dev-инструмент: запускает SQL-граф (`backend/toast/sql_graph.py`)
против живой `loreagent_test` и показывает ход выполнения в LangGraph Studio.

## Запуск

1. Скопируй креды: `cp .env.example .env` и заполни `OPENROUTER_API_KEY` и
   компоненты `TOAST_DB_*`.
2. Подними сервер и Studio:

   ```bash
   cd studio
   uv run langgraph dev
   ```

   Откроется Studio (нужен бесплатный вход в LangSmith; граф и БД остаются
   локально). Сервер графа — на `http://127.0.0.1:2024`.

3. В форме ввода графа `sql_tool` заполни поля и запусти. Видно подсветку
   узлов scope→generate→execute→judge→summarize и состояние на каждом шаге.

## Готовые входы (из отчёта)

Юристы:
- `question`: Какие ФИО у юристов и их должности?
- `chunk_id`: `e6d9b7ff6df20d08b9c1c543760530ce`
- `table`: `toast_tbl_ec48a6d52d16ab405f95`
- `desc_vector`: юристы Adventum, ФИО и должности
- `desc_full`: Table payload: Лист1 A15:R16. Реестр юристов: ФИО, должность, email.

Грейды:
- `question`: Какие компетенции базовой матрицы отдела контекстной рекламы?
- `chunk_id`: `grade-base`
- `table`: `toast_tbl_17a7241d0a976f287103`
- `desc_vector`: грейды контекстной рекламы, компетенции
- `desc_full`: Table payload: Junior-Group head. Базовая матрица компетенций.

## Тест

```bash
cd studio && uv run pytest
```
