import type { IStep } from "@chainlit/react-client";
import type { ThreadMessageLike } from "@assistant-ui/react";

export const isChatMessage = (step: IStep): boolean =>
  step.type === "user_message" || step.type === "assistant_message";

const stepTime = (step: IStep): number => {
  const value = step.start ?? step.createdAt;
  const ms = value ? new Date(value).getTime() : NaN;
  return Number.isNaN(ms) ? 0 : ms;
};

/**
 * Собирает user/assistant-сообщения из дерева шагов react-client.
 *
 * Chainlit оборачивает `@cl.on_message` в run-шаг, поэтому ответ ассистента
 * создаётся с parentId = этого run-шага и приходит вложенным в `.steps`, а не
 * на верхнем уровне. Плоский `messages.filter(isChatMessage)` такие ответы
 * терял. Обходим дерево рекурсивно и сортируем результат хронологически.
 */
export function collectChatMessages(steps: IStep[]): IStep[] {
  const out: IStep[] = [];
  const walk = (nodes: IStep[]): void => {
    for (const node of nodes) {
      if (isChatMessage(node)) out.push(node);
      if (node.steps?.length) walk(node.steps);
    }
  };
  walk(steps);
  return out.sort((a, b) => stepTime(a) - stepTime(b));
}

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
