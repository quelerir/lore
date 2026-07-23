import { ComposerPrimitive, ThreadPrimitive } from "@assistant-ui/react";
import { ArrowUp, Check, ChevronDown, Square, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ChatMode } from "../../chat/ChainlitRuntimeProvider";
import styles from "./ChatComposer.module.css";

interface ChatComposerProps {
  mode: ChatMode;
  onModeChange: (mode: ChatMode) => void;
}

const modeLabel: Record<ChatMode, string> = {
  fast: "Быстрый",
  deep: "Умный",
};

export default function ChatComposer({
  mode,
  onModeChange,
}: ChatComposerProps) {
  const [isModeMenuOpen, setIsModeMenuOpen] = useState(false);
  const modeMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isModeMenuOpen) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (!modeMenuRef.current?.contains(event.target as Node)) {
        setIsModeMenuOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsModeMenuOpen(false);
      }
    };

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isModeMenuOpen]);

  return (
    <div className={styles.wrapper}>
      <ComposerPrimitive.Root className={styles.form}>
        <ComposerPrimitive.Input
          className={styles.textarea}
          placeholder="Спросите Lore"
          rows={1}
          autoFocus
        />

        <div className={styles.actions}>
          <div className={styles.modeMenu} ref={modeMenuRef}>
            <button
              type="button"
              className={styles.modeTrigger}
              aria-haspopup="menu"
              aria-expanded={isModeMenuOpen}
              onClick={() => setIsModeMenuOpen((open) => !open)}
            >
              <span className={styles.modeTriggerLeft}>
                <Zap size={14} />
                <span>{modeLabel[mode]}</span>
              </span>
              <ChevronDown
                size={14}
                className={isModeMenuOpen ? styles.modeChevronOpen : styles.modeChevron}
              />
            </button>

            {isModeMenuOpen ? (
              <div className={styles.modeDropdown} role="menu" aria-label="Выбор интеллекта">
                <button
                  type="button"
                  className={styles.modeOption}
                  onClick={() => {
                    onModeChange("fast");
                    setIsModeMenuOpen(false);
                  }}
                >
                  <span className={styles.modeOptionText}>
                    <span className={styles.modeOptionTitle}>Быстрый</span>
                    <span className={styles.modeOptionHint}>Для быстрых ответов</span>
                  </span>
                  {mode === "fast" ? <Check size={14} /> : null}
                </button>
                {/* <button
                  type="button"
                  className={styles.modeOption}
                  onClick={() => {
                    onModeChange("deep");
                    setIsModeMenuOpen(false);
                  }}
                >
                  <span className={styles.modeOptionText}>
                    <span className={styles.modeOptionTitle}>Умный</span>
                    <span className={styles.modeOptionHint}>Для более глубокого ответа</span>
                  </span>
                  {mode === "deep" ? <Check size={14} /> : null}
                </button> */}
              </div>
            ) : null}
          </div>

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
        </div>
      </ComposerPrimitive.Root>
    </div>
  );
}
