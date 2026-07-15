import type { Message } from "../../types/chat";
import styles from "./UserMessage.module.css";

interface UserMessageProps {
  message: Message;
}

export default function UserMessage({ message }: UserMessageProps) {
  return (
    <div className={styles.row}>
      <div className={styles.bubble}>
        <p>{message.content}</p>
      </div>
    </div>
  );
}
