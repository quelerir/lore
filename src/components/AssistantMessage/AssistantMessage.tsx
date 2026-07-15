import { Check, Copy, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import type { Message } from "../../types/chat";
import styles from "./AssistantMessage.module.css";

interface AssistantMessageProps {
  message: Message;
  onCopy: () => Promise<boolean> | boolean;
  onRegenerate: () => void;
}

export default function AssistantMessage({
  message,
  onCopy,
  onRegenerate,
}: AssistantMessageProps) {
  const [isCopied, setIsCopied] = useState(false);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);

  const handleCopy = async () => {
    const copied = await onCopy();
    if (!copied) return;

    setIsCopied(true);
    window.setTimeout(() => setIsCopied(false), 1600);
  };

  const toggleFeedback = (nextFeedback: "up" | "down") => {
    setFeedback((currentFeedback) =>
      currentFeedback === nextFeedback ? null : nextFeedback,
    );
  };

  return (
    <div className={styles.row}>
      <div className={styles.content}>
        <div className={styles.bubble}>
          <p>{message.content || "..."}</p>
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            onClick={handleCopy}
            aria-label={isCopied ? "Скопировано" : "Копировать ответ"}
            title={isCopied ? "Скопировано" : "Копировать"}
          >
            {isCopied ? <Check size={16} /> : <Copy size={16} />}
          </button>
          <button
            type="button"
            onClick={onRegenerate}
            aria-label="Сгенерировать заново"
            disabled={message.status === "streaming"}
          >
            <RotateCcw size={16} />
          </button>
          <button
            type="button"
            onClick={() => toggleFeedback("up")}
            aria-label="Понравился ответ"
            title="Понравился ответ"
            className={feedback === "up" ? styles.activePositive : undefined}
          >
            <ThumbsUp size={16} />
          </button>
          <button
            type="button"
            onClick={() => toggleFeedback("down")}
            aria-label="Не понравился ответ"
            title="Не понравился ответ"
            className={feedback === "down" ? styles.activeNegative : undefined}
          >
            <ThumbsDown size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
