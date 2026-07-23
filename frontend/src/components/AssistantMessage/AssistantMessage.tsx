import { useMessage } from "@assistant-ui/react";
import { Check, Copy } from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { rehypeCitationMarkers } from "../../chat/citationMarkers";
import { copyText } from "../../chat/copyText";
import { useSessionUi } from "../../chat/sessionUi";
import Citations from "../Citations/Citations";
import ExecutionSteps from "../ExecutionSteps/ExecutionSteps";
import Warnings from "../Warnings/Warnings";
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
  const id = useMessage((m) => m.id);
  const { traceByMessage, citationsByMessage, warningsByMessage, activeMessageId } =
    useSessionUi();
  const steps = traceByMessage.get(id) ?? [];
  const citations = citationsByMessage.get(id) ?? [];
  const warnings = warningsByMessage.get(id) ?? [];
  // Hard failures / "база недоступна" show as a banner at the START of the message
  // (deterministic, from metadata — never left to the LLM to phrase); soft
  // degradations stay as chips below the answer.
  const bannerWarnings = warnings.filter((w) => w.level === "error");
  const chipWarnings = warnings.filter((w) => w.level === "warning");
  const isActive = id === activeMessageId;
  const [isCopied, setIsCopied] = useState(false);

  // Inline [n] superscripts link to their citation card — only once the cards are
  // rendered (i.e. not while streaming) and only for markers that have a card.
  const markerSet = new Set(
    citations.map((c) => c.marker).filter((m): m is number => m != null),
  );
  const useMarkers = !isActive && markerSet.size > 0;
  const jumpToCitation = (marker: number) => {
    const el = document.getElementById(`citation-${marker}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add(styles.flash);
    window.setTimeout(() => el.classList.remove(styles.flash), 1200);
  };

  const handleCopy = async () => {
    const copied = await copyText(text);
    if (!copied) return;

    setIsCopied(true);
    window.setTimeout(() => setIsCopied(false), 1600);
  };

  return (
    <div className={styles.row}>
      <div className={styles.content}>
        <ExecutionSteps steps={steps} running={isActive} />
        {!isActive ? <Warnings items={bannerWarnings} /> : null}
        <div className={styles.bubble}>
          {text ? (
            <Markdown
              remarkPlugins={REMARK_PLUGINS}
              rehypePlugins={useMarkers ? [[rehypeCitationMarkers, markerSet]] : []}
              components={
                useMarkers
                  ? {
                      sup: ({ node, children, ...props }) => {
                        const marker = node?.properties?.dataMarker;
                        if (marker == null) return <sup {...props}>{children}</sup>;
                        const n = Number(marker);
                        return (
                          <sup
                            className={styles.citationMarker}
                            role="button"
                            tabIndex={0}
                            onClick={() => jumpToCitation(n)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") jumpToCitation(n);
                            }}
                          >
                            {n}
                          </sup>
                        );
                      },
                    }
                  : undefined
              }
            >
              {text}
            </Markdown>
          ) : isActive ? (
            <TypingIndicator />
          ) : null}
        </div>
        {!isActive ? <Warnings items={chipWarnings} /> : null}
        {!isActive ? <Citations items={citations} /> : null}
        <div className={styles.actions}>
          <button
            type="button"
            onClick={() => void handleCopy()}
            aria-label={isCopied ? "Скопировано" : "Копировать ответ"}
            title={isCopied ? "Скопировано" : "Копировать"}
            disabled={isActive}
          >
            {isCopied ? <Check size={16} /> : <Copy size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}
