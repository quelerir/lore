import type { Chat } from "../../types/chat";
import styles from "./ChatListItem.module.css";

interface ChatListItemProps {
  chat: Chat;
  isActive: boolean;
  onClick: () => void;
}

export default function ChatListItem({
  chat,
  isActive,
  onClick,
}: ChatListItemProps) {
  return (
    <button
      className={`${styles.item} ${isActive ? styles.active : ""}`}
      onClick={onClick}
      type="button"
    >
      <div className={styles.header}>
        <div className={styles.title}>{chat.title}</div>
        <div className={styles.time}>{chat.time}</div>
      </div>
      <div className={styles.description}>{chat.description}</div>
    </button>
  );
}
