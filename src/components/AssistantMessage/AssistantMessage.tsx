import { Copy, RotateCcw } from "lucide-react";
import type { Message } from "../../types/chat";
import styles from "./AssistantMessage.module.css";

interface AssistantMessageProps {
  message: Message;
  onCopy: () => void;
  onRegenerate: () => void;
}

export default function AssistantMessage({
  message,
  onCopy,
  onRegenerate,
}: AssistantMessageProps) {
  return (
    <div className={styles.row}>
      <div className={styles.avatar}>A</div>
      <div className={styles.content}>
        <div className={styles.bubble}>
          <p>{message.content || "..."}</p>
        </div>
        <div className={styles.actions}>
          <button type="button" onClick={onCopy} aria-label="Копировать ответ">
            <Copy size={16} />
          </button>
          <button
            type="button"
            onClick={onRegenerate}
            aria-label="Сгенерировать заново"
            disabled={message.status === "streaming"}
          >
            <RotateCcw size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
