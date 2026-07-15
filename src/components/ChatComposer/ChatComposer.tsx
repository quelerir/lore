import { ComposerPrimitive } from "@assistant-ui/react";
import { ArrowUp, Plus, Square } from "lucide-react";
import { KeyboardEvent, useEffect, useId, useRef } from "react";
import styles from "./ChatComposer.module.css";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  isStreaming: boolean;
}

export default function ChatComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  isStreaming,
}: ChatComposerProps) {
  const fileInputId = useId();
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = "auto";
    const nextHeight = Math.min(textarea.scrollHeight, 180);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 180 ? "auto" : "hidden";
  }, [value]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSubmit();
    }
  };

  return (
    <div className={styles.wrapper}>
      <ComposerPrimitive.Root className={styles.form}>
        <label className={styles.iconButton} htmlFor={fileInputId}>
          <Plus size={18} />
        </label>
        <input id={fileInputId} className={styles.fileInput} type="file" />

        <textarea
          ref={textareaRef}
          className={styles.textarea}
          placeholder="Задайте вопрос Lore"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
        />

        <button
          className={`${styles.iconButton} ${styles.sendButton}`}
          type="button"
          onClick={isStreaming ? onStop : onSubmit}
          disabled={!isStreaming && !value.trim()}
          aria-label={isStreaming ? "Остановить генерацию" : "Отправить сообщение"}
        >
          {isStreaming ? <Square size={12} fill="currentColor" /> : <ArrowUp size={18} />}
        </button>
      </ComposerPrimitive.Root>
    </div>
  );
}
