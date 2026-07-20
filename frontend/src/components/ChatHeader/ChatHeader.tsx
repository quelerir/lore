import { Menu } from "lucide-react";
import styles from "./ChatHeader.module.css";

interface ChatHeaderProps {
  title: string;
  onOpenSidebar: () => void;
}

export default function ChatHeader({ title, onOpenSidebar }: ChatHeaderProps) {
  return (
    <header className={styles.header}>
      <button
        className={styles.menuButton}
        onClick={onOpenSidebar}
        type="button"
        aria-label="Открыть список чатов"
      >
        <Menu size={18} />
      </button>
      <h2 className={styles.title}>{title}</h2>
    </header>
  );
}
