import { ThreadPrimitive } from "@assistant-ui/react";
import type { Message } from "../../types/chat";
import AssistantMessage from "../AssistantMessage/AssistantMessage";
import UserMessage from "../UserMessage/UserMessage";
import styles from "./MessageList.module.css";

interface MessageListProps {
  messages: Message[];
  onCopy: (messageId: string, content: string) => Promise<boolean> | boolean;
  onRegenerate: (messageId: string) => void;
}

export default function MessageList({
  messages,
  onCopy,
  onRegenerate,
}: MessageListProps) {
  return (
    <ThreadPrimitive.Viewport className={styles.viewport}>
      <div className={styles.inner}>
        {messages.map((message) =>
          message.role === "assistant" ? (
            <AssistantMessage
              key={message.id}
              message={message}
              onCopy={() => onCopy(message.id, message.content)}
              onRegenerate={() => onRegenerate(message.id)}
            />
          ) : (
            <UserMessage key={message.id} message={message} />
          ),
        )}
      </div>
    </ThreadPrimitive.Viewport>
  );
}
