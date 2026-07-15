import type { IStep } from "@chainlit/react-client";
import type { ThreadMessageLike } from "@assistant-ui/react";

export const isChatMessage = (step: IStep): boolean =>
  step.type === "user_message" || step.type === "assistant_message";

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
