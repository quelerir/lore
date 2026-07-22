import type { IStep } from "@chainlit/react-client";

/**
 * Предупреждения/ошибки хода, которые бэкенд вешает на metadata сообщения
 * ассистента: `degradations` (мягкие деградации веток пайплайна) и `error`
 * (жёсткий сбой турна). Показываются чипами/баннером под ответом, чтобы сбой
 * не уходил в молчание.
 *
 * ⚠️ NOT EXECUTED in the agent env (Node 16). Pure TS; verify with `npm test`.
 */
export interface Warning {
  level: "warning" | "error";
  text: string;
}

// Коды деградаций пайплайна → человекочитаемый русский текст.
const DEGRADATION_LABELS: Record<string, string> = {
  answer_generation_failed: "Модель недоступна — ответ не сформирован",
  table_lane_unavailable: "Таблицы недоступны — ответ по тексту",
  vector_search_failed: "Смысловой поиск недоступен",
  fulltext_search_failed: "Лексический поиск недоступен",
  structural_expansion_failed: "Структурное расширение недоступно",
  context_load_failed: "Не удалось загрузить контекст",
  reranker_failed: "Реранкер недоступен — базовый порядок",
  auto_merging_failed: "Группировка недоступна — отдельные фрагменты",
};

const degradationText = (code: string): string =>
  DEGRADATION_LABELS[code] ?? `Ограничение: ${code}`;

/** Read degradations + hard error from a step's metadata → typed warnings (deduped). */
export function extractWarnings(step: IStep): Warning[] {
  const meta = (step.metadata ?? {}) as { degradations?: unknown; error?: unknown };
  const out: Warning[] = [];
  if (Array.isArray(meta.degradations)) {
    const seen = new Set<string>();
    for (const code of meta.degradations) {
      if (typeof code === "string" && !seen.has(code)) {
        seen.add(code);
        out.push({ level: "warning", text: degradationText(code) });
      }
    }
  }
  if (typeof meta.error === "string" && meta.error) {
    out.push({ level: "error", text: "Ошибка при обработке запроса" });
  }
  return out;
}

/**
 * id ассистентского сообщения → его предупреждения, обходя дерево шагов (как
 * collectCitationsByMessage). Сообщения без предупреждений в мапу не попадают.
 */
export function collectWarningsByMessage(steps: IStep[]): Map<string, Warning[]> {
  const out = new Map<string, Warning[]>();
  const walk = (nodes: IStep[]): void => {
    for (const node of nodes) {
      if (node.type === "assistant_message") {
        const w = extractWarnings(node);
        if (w.length) out.set(node.id, w);
      }
      if (node.steps?.length) walk(node.steps);
    }
  };
  walk(steps);
  return out;
}
