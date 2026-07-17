import { ComposerPrimitive, ThreadPrimitive } from "@assistant-ui/react";
import { ArrowUp, Square } from "lucide-react";
import styles from "./ChatComposer.module.css";

export default function ChatComposer() {
  return (
    <div className={styles.wrapper}>
      <ComposerPrimitive.Root className={styles.form}>
        <ComposerPrimitive.Input
          className={styles.textarea}
          placeholder="Задайте вопрос Lore"
          rows={1}
          autoFocus
        />

        <ThreadPrimitive.If running={false}>
          <ComposerPrimitive.Send
            className={`${styles.iconButton} ${styles.sendButton}`}
            aria-label="Отправить сообщение"
          >
            <ArrowUp size={18} />
          </ComposerPrimitive.Send>
        </ThreadPrimitive.If>
        <ThreadPrimitive.If running>
          <ComposerPrimitive.Cancel
            className={`${styles.iconButton} ${styles.sendButton}`}
            aria-label="Остановить генерацию"
          >
            <Square size={12} fill="currentColor" />
          </ComposerPrimitive.Cancel>
        </ThreadPrimitive.If>
      </ComposerPrimitive.Root>
    </div>
  );
}
