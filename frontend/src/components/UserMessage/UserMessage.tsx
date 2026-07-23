import { useMessage } from "@assistant-ui/react";
import { renderHighlightedText, useSearchHighlightQuery } from "../MessageList/searchHighlight";
import styles from "./UserMessage.module.css";

export default function UserMessage() {
  const text = useMessage((m) =>
    m.content
      .filter((part) => part.type === "text")
      .map((part) => ("text" in part ? part.text : ""))
      .join("\n"),
  );
  const searchQuery = useSearchHighlightQuery();

  return (
    <div
      className={styles.row}
      data-chat-search-item="true"
      data-chat-search-text={text}
    >
      <div className={styles.bubble}>
        <p>{renderHighlightedText(text, searchQuery, styles.searchHit)}</p>
      </div>
    </div>
  );
}
