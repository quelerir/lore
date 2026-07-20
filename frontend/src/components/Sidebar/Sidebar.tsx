import { FolderOpen, MessageSquareText, PanelLeft, PenSquare, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import AuthBar from "../../auth/AuthBar";
import type { Chat } from "../../types/chat";
import ChatList from "../ChatList/ChatList";
import styles from "./Sidebar.module.css";

interface SidebarProps {
  chats: Chat[];
  activeChatId: string | null;
  isMobileOpen: boolean;
  isCollapsed: boolean;
  onSelectChat: (chatId: string) => void;
  onRenameChat: (chatId: string) => void;
  onDeleteChat: (chatId: string) => void;
  onCreateChat: () => void;
  onCloseMobileMenu: () => void;
  onToggleCollapse: () => void;
  onOpenHistoryPopover: () => void;
}

export default function Sidebar({
  chats,
  activeChatId,
  isMobileOpen,
  isCollapsed,
  onSelectChat,
  onRenameChat,
  onDeleteChat,
  onCreateChat,
  onCloseMobileMenu,
  onToggleCollapse,
  onOpenHistoryPopover,
}: SidebarProps) {
  const [searchValue, setSearchValue] = useState("");
  const filteredChats = useMemo(() => {
    const normalizedQuery = searchValue.trim().toLowerCase();
    if (!normalizedQuery) return chats;

    return chats.filter((chat) =>
      `${chat.title} ${chat.description}`.toLowerCase().includes(normalizedQuery),
    );
  }, [chats, searchValue]);

  return (
    <>
      <div
        className={`${styles.overlay} ${isMobileOpen ? styles.overlayVisible : ""}`}
        onClick={onCloseMobileMenu}
      />
      {isCollapsed ? (
        <aside className={styles.sidebarRail}>
          <button
            className={styles.railButton}
            onClick={onCreateChat}
            type="button"
            aria-label="Новый чат"
            title="Новый чат"
            data-tooltip="Новый чат"
          >
            <PenSquare size={18} />
          </button>

          <a
            className={styles.railButton}
            href="/files"
            aria-label="File Viewer"
            title="File Viewer"
            data-tooltip="File Viewer"
          >
            <FolderOpen size={18} />
          </a>

          <button
            className={styles.railButton}
            onClick={onOpenHistoryPopover}
            type="button"
            aria-label="Истории чатов"
            title="Истории чатов"
            data-tooltip="Истории чатов"
          >
            <MessageSquareText size={18} />
          </button>
        </aside>
      ) : null}
      <aside
        className={`${styles.sidebar} ${isMobileOpen ? styles.sidebarOpen : ""} ${
          isCollapsed ? styles.sidebarCollapsed : ""
        }`}
      >
        <div className={styles.headerRow}>
          <div className={styles.brandBlock}>
            <h1 className={styles.title}>Lore</h1>
          </div>

          <div className={styles.headerActions}>
            <button
              className={styles.panelButton}
              onClick={onToggleCollapse}
              type="button"
              aria-label="Свернуть боковую панель"
              data-tooltip="Скрыть"
            >
              <PanelLeft size={18} />
            </button>
            <button
              className={styles.closeButton}
              onClick={onCloseMobileMenu}
              type="button"
              aria-label="Закрыть меню"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        <div className={styles.primaryLinks}>
          <button
            className={styles.newChatButton}
            onClick={onCreateChat}
            type="button"
            data-tooltip="Новый чат"
          >
            <PenSquare size={18} />
            <span>Новый чат</span>
          </button>

          <a className={styles.sectionLink} href="/files" data-tooltip="File Viewer">
            <FolderOpen size={18} />
            <span>File Viewer</span>
          </a>
        </div>

        <label className={styles.searchField} aria-label="Поиск по чатам">
          <Search size={18} />
          <input
            type="search"
            placeholder="Поиск по чатам"
            value={searchValue}
            onChange={(event) => setSearchValue(event.target.value)}
          />
        </label>

        <ChatList
          chats={filteredChats}
          activeChatId={activeChatId}
          onSelectChat={onSelectChat}
          onRenameChat={onRenameChat}
          onDeleteChat={onDeleteChat}
        />

        <AuthBar />
      </aside>
    </>
  );
}
