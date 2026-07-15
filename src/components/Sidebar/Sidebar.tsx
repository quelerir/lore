import { MessageSquarePlus, X } from "lucide-react";
import type { Chat } from "../../types/chat";
import ChatList from "../ChatList/ChatList";
import styles from "./Sidebar.module.css";

interface SidebarProps {
  chats: Chat[];
  activeChatId: string | null;
  isMobileOpen: boolean;
  onSelectChat: (chatId: string) => void;
  onCreateChat: () => void;
  onCloseMobileMenu: () => void;
}

export default function Sidebar({
  chats,
  activeChatId,
  isMobileOpen,
  onSelectChat,
  onCreateChat,
  onCloseMobileMenu,
}: SidebarProps) {
  return (
    <>
      <div
        className={`${styles.overlay} ${isMobileOpen ? styles.overlayVisible : ""}`}
        onClick={onCloseMobileMenu}
      />
      <aside className={`${styles.sidebar} ${isMobileOpen ? styles.sidebarOpen : ""}`}>
        <div className={styles.headerRow}>
          <h1 className={styles.title}>Lore</h1>
          <button
            className={styles.closeButton}
            onClick={onCloseMobileMenu}
            type="button"
            aria-label="Закрыть меню"
          >
            <X size={18} />
          </button>
        </div>
        <div className={styles.sectionLabel}>Темы</div>

        <ChatList chats={chats} activeChatId={activeChatId} onSelectChat={onSelectChat} />

        <button className={styles.newChatButton} onClick={onCreateChat} type="button">
          <MessageSquarePlus size={18} />
          <span>Новый чат</span>
        </button>
      </aside>
    </>
  );
}
