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

/** Длительность шага для трейса: "450 мс" / "1.2 с"; null, если границ нет. */
export function formatDuration(start?: string, end?: string): string | null {
  if (!start || !end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${Math.round(ms)} мс`;
  return `${(ms / 1000).toFixed(1)} с`;
}
