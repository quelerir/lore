import { PanelLeft } from "lucide-react";
import styles from "./ChatHeader.module.css";

interface ChatHeaderProps {
  title: string;
  onOpenSidebar: () => void;
  showSidebarButton: boolean;
}

export default function ChatHeader({
  title,
  onOpenSidebar,
  showSidebarButton,
}: ChatHeaderProps) {
  return (
    <header className={styles.header}>
      <button
        className={`${styles.menuButton} ${showSidebarButton ? styles.menuButtonVisible : ""}`}
        onClick={onOpenSidebar}
        type="button"
        aria-label="Открыть список чатов"
        data-tooltip="Открыть"
      >
        <PanelLeft size={18} />
      </button>
      <div className={styles.titleRow}>
        <h2 className={styles.title}>{title}</h2>
      </div>
    </header>
  );
}
