import type { IThread } from "@chainlit/react-client";
import type { Chat } from "../types/chat";
import { formatChatTime } from "./chatDates";

export function threadToChat(thread: IThread): Chat {
  const createdAt = String(thread.createdAt ?? "");

  return {
    id: thread.id,
    title: thread.name?.trim() || "Без названия",
    description: "",
    createdAt,
    time: formatChatTime(createdAt),
  };
}
