import { ThreadPrimitive } from "@assistant-ui/react";
import { useEffect, useRef } from "react";
import { useSessionUi } from "../../chat/sessionUi";
import AssistantMessage from "../AssistantMessage/AssistantMessage";
import UserMessage from "../UserMessage/UserMessage";
import { SearchHighlightContext } from "./searchHighlight";
import styles from "./MessageList.module.css";

interface MessageListProps {
  searchQuery: string;
  activeSearchIndex: number;
  onSearchStateChange: (state: { total: number; active: number }) => void;
}

export default function MessageList({
  searchQuery,
  activeSearchIndex,
  onSearchStateChange,
}: MessageListProps) {
  const { switching } = useSessionUi();
  const innerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const root = innerRef.current;
    if (!root || switching) return;

    const items = [...root.querySelectorAll<HTMLElement>("[data-chat-search-item='true']")];
    for (const item of items) {
      item.classList.remove(styles.searchMatch, styles.searchActive);
    }

    const query = searchQuery.trim().toLowerCase();
    if (!query) {
      onSearchStateChange({ total: 0, active: 0 });
      return;
    }

    const matches = items.filter((item) =>
      (item.dataset.chatSearchText ?? "").toLowerCase().includes(query),
    );

    if (matches.length === 0) {
      onSearchStateChange({ total: 0, active: 0 });
      return;
    }

    const normalizedIndex = Math.min(activeSearchIndex, matches.length - 1);
    matches.forEach((item, index) => {
      item.classList.add(styles.searchMatch);
      if (index === normalizedIndex) {
        item.classList.add(styles.searchActive);
      }
    });

    matches[normalizedIndex]?.scrollIntoView({
      block: "center",
      behavior: "smooth",
    });

    onSearchStateChange({
      total: matches.length,
      active: normalizedIndex + 1,
    });
  }, [activeSearchIndex, onSearchStateChange, searchQuery, switching]);

  return (
    <ThreadPrimitive.Viewport className={styles.viewport}>
      <SearchHighlightContext.Provider value={searchQuery}>
        <div className={styles.inner} ref={innerRef}>
          {switching ? (
            // Во время переключения не мигаем пустым чатом / «Начните диалог» —
            // показываем мягкий лоадер, пока не приедет нужный тред.
            <div className={styles.loading} role="status" aria-label="Загрузка чата">
              <span />
              <span />
              <span />
            </div>
          ) : (
            <>
              <ThreadPrimitive.Empty>
                <div className={styles.empty}>
                  <h3>
                    Спросите что-нибудь у{" "}
                    <span className={styles.wordmark} aria-label="Lore">
                      <span className={styles.wordmarkLetter}>L</span>
                      <span className={styles.wordmarkDot} aria-hidden="true" />
                      <span className={styles.wordmarkLetter}>RE</span>
                    </span>
                  </h3>
                </div>
              </ThreadPrimitive.Empty>
              <ThreadPrimitive.Messages
                components={{ UserMessage, AssistantMessage }}
              />
            </>
          )}
        </div>
      </SearchHighlightContext.Provider>
    </ThreadPrimitive.Viewport>
  );
}
