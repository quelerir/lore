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
