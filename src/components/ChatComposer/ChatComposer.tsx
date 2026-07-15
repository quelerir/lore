import { ComposerPrimitive } from "@assistant-ui/react";
import { Paperclip, SendHorizontal } from "lucide-react";
import { KeyboardEvent, useId, useRef } from "react";
import styles from "./ChatComposer.module.css";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
}

export default function ChatComposer({
  value,
  onChange,
  onSubmit,
}: ChatComposerProps) {
  const fileInputId = useId();
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSubmit();
    }
  };

  return (
    <div className={styles.wrapper}>
      <ComposerPrimitive.Root className={styles.form}>
        <textarea
          ref={textareaRef}
          className={styles.textarea}
          placeholder="Спросите Datacraft AI"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
        />

        <div className={styles.footer}>
          <label className={styles.iconButton} htmlFor={fileInputId}>
            <Paperclip size={18} />
          </label>
          <input id={fileInputId} className={styles.fileInput} type="file" />

          <button
            className={`${styles.iconButton} ${styles.sendButton}`}
            type="button"
            onClick={onSubmit}
            disabled={!value.trim()}
            aria-label="Отправить сообщение"
          >
            <SendHorizontal size={18} />
          </button>
        </div>
      </ComposerPrimitive.Root>
    </div>
  );
}
