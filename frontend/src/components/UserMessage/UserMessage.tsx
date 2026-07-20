import { useMessage } from "@assistant-ui/react";
import styles from "./UserMessage.module.css";

export default function UserMessage() {
  const text = useMessage((m) =>
    m.content
      .filter((part) => part.type === "text")
      .map((part) => ("text" in part ? part.text : ""))
      .join("\n"),
  );

  return (
    <div className={styles.row}>
      <div className={styles.bubble}>
        <p>{text}</p>
      </div>
    </div>
  );
}
