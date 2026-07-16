import { useMessage } from "@assistant-ui/react";
import { Check, Copy } from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { copyText } from "../../chat/copyText";
import styles from "./AssistantMessage.module.css";

const REMARK_PLUGINS = [remarkGfm, remarkBreaks];

function TypingIndicator() {
  return (
    <div className={styles.typing} aria-label="Ассистент печатает" role="status">
      <span />
      <span />
      <span />
    </div>
  );
}

export default function AssistantMessage() {
  const text = useMessage((m) =>
    m.content
      .filter((part) => part.type === "text")
      .map((part) => ("text" in part ? part.text : ""))
      .join("\n"),
  );
  const isRunning = useMessage((m) => m.status?.type === "running");
  const [isCopied, setIsCopied] = useState(false);

  const handleCopy = async () => {
    const copied = await copyText(text);
    if (!copied) return;

    setIsCopied(true);
    window.setTimeout(() => setIsCopied(false), 1600);
  };

  return (
    <div className={styles.row}>
      <div className={styles.content}>
        <div className={styles.bubble}>
          {text ? (
            <Markdown remarkPlugins={REMARK_PLUGINS}>{text}</Markdown>
          ) : isRunning ? (
            <TypingIndicator />
          ) : null}
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            onClick={() => void handleCopy()}
            aria-label={isCopied ? "Скопировано" : "Копировать ответ"}
            title={isCopied ? "Скопировано" : "Копировать"}
            disabled={isRunning}
          >
            {isCopied ? <Check size={16} /> : <Copy size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}
