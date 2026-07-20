import type { IThread } from "@chainlit/react-client";
import type { Chat } from "../types/chat";

export function threadToChat(thread: IThread): Chat {
  return {
    id: thread.id,
    title: thread.name?.trim() || "Без названия",
    description: "",
    time: new Date(thread.createdAt).toLocaleString("ru-RU", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }),
  };
}
