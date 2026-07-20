import { Check, Copy, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useState } from "react";
import type { Message } from "../../types/chat";
import styles from "./AssistantMessage.module.css";

const SVG_PATTERN = /<svg[\s\S]*?<\/svg>/gi;
const CARD_METADATA_PATTERN = /<!--\s*lore-card:\s*([\s\S]*?)\s*-->/i;

type CardData = {
  fileName: string;
  runLabel: string;
  title: string;
  meta: string;
  preview: string;
  columns?: string[];
  rows?: Array<Record<string, string | number>>;
  figureLabel?: string;
  chunks?: Array<{
    meta: string;
    title: string;
    preview?: string;
    columns?: string[];
    rows?: Array<Record<string, string | number>>;
    figureLabel?: string;
  }>;
};

type ParsedMessageContent = {
  text: string;
  cardData: CardData | null;
};

const getActiveChunkIndex = (messageText: string, cardData: CardData | null) => {
  if (!cardData?.chunks?.length) return 0;

  const normalizedText = messageText.toLowerCase();

  if (
    normalizedText.includes("бюдж") ||
    normalizedText.includes("roi") ||
    normalizedText.includes("канал") ||
    normalizedText.includes("table")
  ) {
    return cardData.chunks.findIndex((chunk) => chunk.columns?.length) || 0;
  }

  if (
    normalizedText.includes("figure") ||
    normalizedText.includes("схем") ||
    normalizedText.includes("revenue bridge") ||
    normalizedText.includes("заявк")
  ) {
    return cardData.chunks.findIndex((chunk) => chunk.figureLabel) || 0;
  }

  if (
    normalizedText.includes("summary") ||
    normalizedText.includes("heading") ||
    normalizedText.includes("решени") ||
    normalizedText.includes("рост")
  ) {
    return 0;
  }

  return 0;
};

const parseMessageContent = (content: string): ParsedMessageContent => {
  const cardMatch = content.match(CARD_METADATA_PATTERN);
  let cardData: CardData | null = null;

  if (cardMatch) {
    try {
      cardData = JSON.parse(cardMatch[1]) as CardData;
    } catch {
      cardData = null;
    }
  }

  return {
    text: content.replace(SVG_PATTERN, "").replace(CARD_METADATA_PATTERN, "").trim(),
    cardData,
  };
};

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
  const [isCardOpen, setIsCardOpen] = useState(false);
  const { text, cardData } = parseMessageContent(message.content);
  const activeChunkIndex = getActiveChunkIndex(text, cardData);

  useEffect(() => {
    if (!isCardOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsCardOpen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isCardOpen]);

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
          {text ? <p>{text}</p> : null}
          {cardData ? (
            <button
              type="button"
              className={styles.fileTeaserButton}
              onClick={() => setIsCardOpen(true)}
            >
              <div className={styles.fileTeaserTop}>
                <span className={styles.fileTeaserName}>
                  {cardData?.fileName ?? "board_summary_q3.pdf"}
                </span>
                <span className={styles.fileTeaserBadge}>PDF</span>
              </div>
              <div className={styles.fileTeaserText}>
                Чанки: 3 · Связанные данные: 2 · Диагностика: 3 · Замечания: 2
              </div>
            </button>
          ) : null}
          {!text && !cardData ? <p>...</p> : null}
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

      {isCardOpen ? (
        <div className={styles.modalOverlay} onClick={() => setIsCardOpen(false)}>
          <div
            className={styles.modalCard}
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby={`file-preview-title-${message.id}`}
          >
            <div className={styles.modalHeader}>
              <div>
                <h3 id={`file-preview-title-${message.id}`} className={styles.modalTitle}>
                  {cardData?.fileName ?? "Файл"}
                </h3>
                <p className={styles.modalSubtitle}>{cardData?.runLabel ?? "Превью документа"}</p>
              </div>
              <button
                type="button"
                className={styles.modalCloseButton}
                onClick={() => setIsCardOpen(false)}
                aria-label="Закрыть окно"
              >
                Закрыть
              </button>
            </div>

            {cardData ? (
              <div className={styles.modalDetailsCard}>
                <div className={styles.modalStatsRow}>
                  <div className={styles.modalStat}>
                    <span>Чанки</span>
                    <strong>3</strong>
                  </div>
                  <div className={styles.modalStat}>
                    <span>Связанные данные</span>
                    <strong>2</strong>
                  </div>
                  <div className={styles.modalStat}>
                    <span>Диагностика</span>
                    <strong>3</strong>
                  </div>
                  <div className={styles.modalStat}>
                    <span>Замечания</span>
                    <strong>2</strong>
                  </div>
                </div>

                <div className={styles.modalChunkList}>
                  {(cardData.chunks ?? [cardData]).map((chunk, index) => (
                    <div
                      key={`${chunk.meta}-${index}`}
                      className={`${styles.modalChunkCard} ${
                        index === activeChunkIndex ? styles.modalChunkCardActive : ""
                      }`}
                    >
                      <div className={styles.modalChunkMeta}>{chunk.meta}</div>
                      <strong className={styles.modalChunkTitle}>{chunk.title}</strong>
                      {chunk.columns?.length && chunk.rows?.length ? (
                        <div className={styles.fileTable}>
                          <table>
                            <thead>
                              <tr>
                                {chunk.columns.map((column) => (
                                  <th key={column}>{column}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {chunk.rows.map((row, rowIndex) => (
                                <tr key={rowIndex}>
                                  {chunk.columns?.map((column) => (
                                    <td key={column}>{String(row[column] ?? "—")}</td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : null}
                      {chunk.figureLabel ? (
                        <div className={styles.figurePreview}>
                          <div className={styles.figureCanvas}>
                            <div className={styles.figureHillLeft} />
                            <div className={styles.figureHillRight} />
                            <div className={styles.figureSun} />
                            <div className={styles.figureFlowLabel}>{chunk.figureLabel}</div>
                          </div>
                        </div>
                      ) : null}
                      {chunk.preview ? <p className={styles.filePreview}>{chunk.preview}</p> : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
