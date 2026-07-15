import { ThreadPrimitive } from "@assistant-ui/react";
import AssistantMessage from "../AssistantMessage/AssistantMessage";
import UserMessage from "../UserMessage/UserMessage";
import styles from "./MessageList.module.css";

export default function MessageList() {
  return (
    <ThreadPrimitive.Viewport className={styles.viewport}>
      <div className={styles.inner}>
        <ThreadPrimitive.Messages
          components={{ UserMessage, AssistantMessage }}
        />
      </div>
    </ThreadPrimitive.Viewport>
  );
}
