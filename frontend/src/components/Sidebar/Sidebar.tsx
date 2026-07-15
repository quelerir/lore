import { LogOut, PenSquare, UserRound, X } from "lucide-react";
import type { AuthUser } from "../../auth/authClient";
import type { Chat } from "../../types/chat";
import ChatList from "../ChatList/ChatList";
import styles from "./Sidebar.module.css";

interface SidebarProps {
  chats: Chat[];
  activeChatId: string | null;
  isMobileOpen: boolean;
  user: AuthUser;
  errorText?: string | null;
  onSelectChat: (chatId: string) => void;
  onRenameChat: (chatId: string) => void;
  onDeleteChat: (chatId: string) => void;
  onCreateChat: () => void;
  onCloseMobileMenu: () => void;
  onLogout: () => void;
}

export default function Sidebar({
  chats,
  activeChatId,
  isMobileOpen,
  user,
  errorText,
  onSelectChat,
  onRenameChat,
  onDeleteChat,
  onCreateChat,
  onCloseMobileMenu,
  onLogout,
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

        <button className={styles.newChatButton} onClick={onCreateChat} type="button">
          <PenSquare size={18} />
          <span>Новый чат</span>
        </button>

        {errorText ? <p className={styles.errorText}>{errorText}</p> : null}

        <ChatList
          chats={chats}
          activeChatId={activeChatId}
          onSelectChat={onSelectChat}
          onRenameChat={onRenameChat}
          onDeleteChat={onDeleteChat}
        />

        <div className={styles.userFooter}>
          <div className={styles.userInfo}>
            <UserRound size={18} />
            <span className={styles.userName}>{user.identifier}</span>
          </div>
          <button
            className={styles.logoutButton}
            onClick={onLogout}
            type="button"
            aria-label="Выйти"
            title="Выйти"
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>
    </>
  );
}
