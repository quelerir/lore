-- Синтетический слепок TOAST-слоя (схема как в loreagent_test, данные вымышленные).
-- Идемпотентен. Выполняется в БД lore_data.

DROP SCHEMA IF EXISTS lore_core CASCADE;
DROP SCHEMA IF EXISTS splitter_toast CASCADE;
CREATE SCHEMA lore_core;
CREATE SCHEMA splitter_toast;

CREATE TABLE lore_core.processed_files (
    logical_file_key text PRIMARY KEY,
    source_path      text NOT NULL
);

CREATE TABLE lore_core.payloads (
    payload_id       text PRIMARY KEY,
    logical_file_key text REFERENCES lore_core.processed_files,
    kind             text NOT NULL,
    coordinates      jsonb,
    toast_schema     text,   -- в проде пусто: воспроизводим
    toast_table      text,   -- в проде пусто: воспроизводим
    storage_uri      text
);

CREATE TABLE lore_core.chunks (
    chunk_id     text PRIMARY KEY,
    display_text text,
    payload_refs jsonb
);

INSERT INTO lore_core.processed_files VALUES
 ('file-context-dept', 'functional/Отдел контекстной рекламы__demo.xlsx'),
 ('file-roster',       'hr/Список сотрудников - demo.xlsx'),
 ('file-vacations',    'hr/График отпусков 2026 - demo.xlsx');

-- Кейс toast-grade-001: три параллельные таблицы, JOIN по _splitter_source_row
CREATE TABLE splitter_toast.toast_tbl_a1b2c3d4e5f6a7b8c9d0 (
    _splitter_source_row int,
    column_1 text,  -- группа компетенций
    column_2 text   -- компетенция
);
INSERT INTO splitter_toast.toast_tbl_a1b2c3d4e5f6a7b8c9d0 VALUES
 (1,'Работа с кампаниями','Выполнение KPI'),
 (2,'Работа с кампаниями','Отчетность'),
 (3,'Работа с кампаниями','Оптимизация ставок'),
 (4,'Аналитика','Конкурентный анализ'),
 (5,'Аналитика','Google Таблицы и Excel'),
 (6,'Команда','Менторство и координация'),
 (7,'Команда','Ведение разных ниш');

CREATE TABLE splitter_toast.toast_tbl_b1b2c3d4e5f6a7b8c9d0 (
    _splitter_source_row int,
    middle_lvl_1   text,   -- самостоятельность middle
    middle_lvl_1_2 text    -- качество middle
);
INSERT INTO splitter_toast.toast_tbl_b1b2c3d4e5f6a7b8c9d0 VALUES
 (1,'4','высокий'),(2,'3','стандартный'),(3,'4','высокий'),
 (4,NULL,NULL),(5,'3','стандартный'),(6,NULL,NULL),(7,NULL,NULL);

CREATE TABLE splitter_toast.toast_tbl_c1b2c3d4e5f6a7b8c9d0 (
    _splitter_source_row int,
    group_head   text,     -- самостоятельность group head
    group_head_2 text      -- качество group head
);
INSERT INTO splitter_toast.toast_tbl_c1b2c3d4e5f6a7b8c9d0 VALUES
 (1,'5','исключительно высокий'),(2,'5','исключительно высокий'),
 (3,'5','исключительно высокий'),(4,'5','исключительно высокий'),
 (5,'5','исключительно высокий'),(6,'5','исключительно высокий'),
 (7,'5','исключительно высокий');

-- Кейс toast-legal-001: header-as-data — первая запись блока живёт только
-- в chunks.display_text как «Columns: …».
CREATE TABLE splitter_toast.toast_tbl_d1b2c3d4e5f6a7b8c9d0 (
    _splitter_source_row int,
    column_1 text,              -- ФИО
    column_2 text,              -- должность ru
    senior_legal_manager text   -- должность en (имя колонки = header-дефект)
);
INSERT INTO splitter_toast.toast_tbl_d1b2c3d4e5f6a7b8c9d0 VALUES
 (16,'Смирнов Пётр Ильич','помощник юриста','Assistant Legal Manager');

-- Кейс toast-privacy-001: PII-таблица (закрыта policy gate)
CREATE TABLE splitter_toast.toast_tbl_e1b2c3d4e5f6a7b8c9d0 (
    _splitter_source_row int,
    column_1 text,   -- ФИО
    column_2 text,   -- отдел
    vacation_start date,
    vacation_end   date
);
INSERT INTO splitter_toast.toast_tbl_e1b2c3d4e5f6a7b8c9d0 VALUES
 (37,'Орлова Мария Сергеевна','Paid Search','2026-08-03','2026-08-16');

INSERT INTO lore_core.payloads VALUES
 ('toast_tbl_a1b2c3d4e5f6a7b8c9d0','file-context-dept','table','{"range":"A1:B8"}',NULL,NULL,'toast://a1'),
 ('toast_tbl_b1b2c3d4e5f6a7b8c9d0','file-context-dept','table','{"range":"C1:D8"}',NULL,NULL,'toast://b1'),
 ('toast_tbl_c1b2c3d4e5f6a7b8c9d0','file-context-dept','table','{"range":"E1:F8"}',NULL,NULL,'toast://c1'),
 ('toast_tbl_d1b2c3d4e5f6a7b8c9d0','file-roster','table','{"range":"A15:R16"}',NULL,NULL,'toast://d1'),
 ('toast_tbl_e1b2c3d4e5f6a7b8c9d0','file-vacations','table','{"range":"A37:R37"}',NULL,NULL,'toast://e1');

INSERT INTO lore_core.chunks VALUES
 ('chunk-grades','Матрица компетенций отдела контекстной рекламы: база + уровни Middle и Group Head, соединяются по _splitter_source_row',
  '["toast_tbl_a1b2c3d4e5f6a7b8c9d0","toast_tbl_b1b2c3d4e5f6a7b8c9d0","toast_tbl_c1b2c3d4e5f6a7b8c9d0"]'),
 ('chunk-legal','Columns: Ковалева Ирина Викторовна | ведущий юрисконсульт | Senior Legal Manager. Блок Legal реестра сотрудников (юристы)',
  '["toast_tbl_d1b2c3d4e5f6a7b8c9d0"]'),
 ('chunk-vacations','График отпусков 2026, персональные даты сотрудников',
  '["toast_tbl_e1b2c3d4e5f6a7b8c9d0"]');
