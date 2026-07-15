import { ThreadPrimitive } from "@assistant-ui/react";
import AssistantMessage from "../AssistantMessage/AssistantMessage";
import UserMessage from "../UserMessage/UserMessage";
import styles from "./MessageList.module.css";

export default function MessageList() {
  return (
    <ThreadPrimitive.Viewport className={styles.viewport}>
      <div className={styles.inner}>
        <ThreadPrimitive.Empty>
          <div className={styles.empty}>
            <h3>Начните новый диалог</h3>
            <p>Задайте вопрос внизу — ассистент ответит в этом окне.</p>
          </div>
        </ThreadPrimitive.Empty>
        <ThreadPrimitive.Messages
          components={{ UserMessage, AssistantMessage }}
        />
      </div>
    </ThreadPrimitive.Viewport>
  );
}
