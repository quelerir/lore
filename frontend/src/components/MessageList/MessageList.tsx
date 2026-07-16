import { ThreadPrimitive } from "@assistant-ui/react";
import { useSessionUi } from "../../chat/sessionUi";
import AssistantMessage from "../AssistantMessage/AssistantMessage";
import UserMessage from "../UserMessage/UserMessage";
import styles from "./MessageList.module.css";

export default function MessageList() {
  const { switching } = useSessionUi();

  return (
    <ThreadPrimitive.Viewport className={styles.viewport}>
      <div className={styles.inner}>
        {switching ? (
          // Во время переключения не мигаем пустым чатом / «Начните диалог» —
          // показываем мягкий лоадер, пока не приедет нужный тред.
          <div className={styles.loading} role="status" aria-label="Загрузка чата">
            <span />
            <span />
            <span />
          </div>
        ) : (
          <>
            <ThreadPrimitive.Empty>
              <div className={styles.empty}>
                <h3>Начните новый диалог</h3>
                <p>Задайте вопрос внизу — ассистент ответит в этом окне.</p>
              </div>
            </ThreadPrimitive.Empty>
            <ThreadPrimitive.Messages
              components={{ UserMessage, AssistantMessage }}
            />
          </>
        )}
      </div>
    </ThreadPrimitive.Viewport>
  );
}
