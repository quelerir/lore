import {
  LogOut,
  MoreHorizontal,
  Moon,
  Pencil,
  Search,
  Sun,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { AuthUser } from "../../auth/authClient";
import type { Chat } from "../../types/chat";
import ChatList from "../ChatList/ChatList";
import styles from "./Sidebar.module.css";

function ToggleChatsIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 18 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M5.45703 1.45703C4.9648 1.46139 4.56207 1.47012 4.2161 1.4985C3.79482 1.53342 3.49686 1.59127 3.26003 1.67531L3.04175 1.76917C2.56153 2.01364 2.16098 2.38472 1.88158 2.84093L1.76917 3.04175C1.63165 3.31132 1.54434 3.65512 1.4985 4.2161C1.45157 4.7869 1.45157 5.51487 1.45157 6.54625V9.45375C1.45157 10.484 1.45157 11.2131 1.4985 11.7839C1.54434 12.346 1.63165 12.6887 1.76917 12.9583L1.88158 13.1591C2.16098 13.6153 2.56262 13.9864 3.04175 14.2308L3.26003 14.3247C3.49686 14.4087 3.79482 14.4666 4.2161 14.5015C4.56098 14.5299 4.96371 14.5386 5.45593 14.543L5.45703 1.45703ZM17.8226 9.45375C17.8226 10.46 17.8226 11.2589 17.7703 11.9018C17.7233 12.4715 17.6338 12.9681 17.4374 13.4243L17.3479 13.6175C16.9824 14.334 16.4261 14.9357 15.7402 15.3561L15.439 15.5252C14.9315 15.7839 14.376 15.8941 13.7255 15.9476C13.0816 16 12.2827 16 11.2764 16H6.54625C5.53997 16 4.74106 16 4.09823 15.9476C3.52851 15.9018 3.03192 15.8101 2.57572 15.6147L2.38363 15.5252C1.66665 15.1599 1.06458 14.6036 0.643929 13.9176L0.475852 13.6175C0.216098 13.1089 0.104775 12.5533 0.0523874 11.9018C-2.43948e-08 11.2589 0 10.4611 0 9.45375V6.54625C0 5.53997 -2.43948e-08 4.74106 0.0523874 4.09823C0.105866 3.44666 0.216098 2.89113 0.475852 2.38363L0.643929 2.0824C1.06474 1.39683 1.66679 0.840861 2.38363 0.475853L2.57572 0.385266C3.03192 0.188813 3.52851 0.0982266 4.09823 0.0523876C4.74106 1.05711e-07 5.53888 0 6.54625 0H11.2764C12.2827 0 13.0816 1.05711e-07 13.7244 0.0523876C14.376 0.105866 14.9315 0.216098 15.439 0.475853L15.7402 0.643929C16.4262 1.06459 16.9826 1.66665 17.3479 2.38363L17.4374 2.57572C17.6338 3.03192 17.7233 3.52851 17.7703 4.09823C17.8226 4.74106 17.8226 5.53888 17.8226 6.54625V9.45375ZM6.90859 14.5484H11.2764C12.3067 14.5484 13.0357 14.5484 13.6065 14.5015C14.1675 14.4557 14.5113 14.3683 14.7809 14.2308L14.9817 14.1184C15.4379 13.839 15.809 13.4374 16.0535 12.9583L16.1473 12.74C16.2314 12.5031 16.2892 12.2052 16.3241 11.7839C16.3711 11.2131 16.3711 10.4851 16.3711 9.45375V6.54625C16.3711 5.51596 16.3711 4.7869 16.3241 4.2161C16.2892 3.79482 16.2314 3.49686 16.1473 3.26003L16.0535 3.04175C15.8098 2.56374 15.439 2.16227 14.9817 1.88158L14.7809 1.76917C14.5113 1.63165 14.1675 1.54434 13.6065 1.4985C13.0357 1.45157 12.3078 1.45157 11.2764 1.45157H6.9075L6.90859 1.45703V14.5484Z"
        fill="currentColor"
      />
    </svg>
  );
}

function HistoryChatsIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 17 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M1.37326 8C1.37326 4.37584 4.49561 1.37326 8.43056 1.37326C12.3655 1.37326 15.4879 4.37584 15.4879 8C15.4852 9.45955 14.979 10.8735 14.0547 12.0031C13.9927 12.0805 13.9481 12.1704 13.9238 12.2666C13.8996 12.3628 13.8963 12.4631 13.9143 12.5607C14.0124 13.0852 14.1518 13.5963 14.3108 14.096C13.6749 14.0117 13.0458 13.882 12.4285 13.7078L12.2984 13.6851C12.1665 13.6737 12.0341 13.7009 11.9174 13.7635C10.844 14.3343 9.64626 14.6312 8.43056 14.6278C4.49561 14.6278 1.37326 11.6231 1.37326 7.99896M0 7.99896C0 12.4533 3.81208 16 8.43056 16C9.77875 16.0022 11.1093 15.6937 12.319 15.0986C13.269 15.3485 14.2447 15.5044 15.2721 15.5684C15.3869 15.5754 15.5016 15.5535 15.6057 15.5046C15.7098 15.4557 15.8 15.3814 15.868 15.2886C15.9359 15.1958 15.9794 15.0874 15.9946 14.9734C16.0097 14.8593 15.9959 14.7434 15.9546 14.636L15.7408 14.0527C15.5736 13.5694 15.4311 13.0893 15.3258 12.6051C16.3212 11.276 16.8598 9.66049 16.8611 8C16.8611 3.54465 13.049 0 8.43056 0C3.81208 0 0 3.54465 0 8"
        fill="currentColor"
      />
    </svg>
  );
}

function FileViewerIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 15 15"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M5.01163 0C5.63236 0.000372883 6.23704 0.197245 6.73901 0.562401L7.78151 1.32076C8.06173 1.52358 8.39877 1.63429 8.74366 1.63429H12.0626C12.8413 1.63481 13.588 1.94432 14.1387 2.49487C14.6895 3.04542 14.9992 3.79201 15 4.57073V11.4293C14.9995 12.2082 14.6898 12.955 14.1391 13.5058C13.5883 14.0565 12.8415 14.3662 12.0626 14.3667H2.93742C2.15869 14.3662 1.412 14.0567 0.861268 13.5061C0.310537 12.9556 0.00077855 12.209 0 11.4302V2.9384C0.000259514 2.15933 0.309788 1.41224 0.860576 0.861269C1.41136 0.310297 2.15835 0.000519331 2.93742 0H5.01163ZM1.30214 7.01825V11.4302C1.30214 12.3317 2.03405 13.0636 2.93644 13.0645H12.0616C12.964 13.0645 13.6959 12.3326 13.6959 11.4302V7.01727L1.30214 7.01825ZM2.93644 1.3041C2.03405 1.3041 1.30214 2.03503 1.30214 2.9384V5.71414H13.6959V4.57171C13.6959 3.66834 12.964 2.93742 12.0616 2.93742H8.74268C8.12151 2.93696 7.51644 2.73974 7.01433 2.37404L5.97183 1.61666C5.6923 1.4131 5.35547 1.30334 5.00968 1.30312L2.93644 1.3041Z"
        fill="currentColor"
      />
    </svg>
  );
}

function NewChatIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M6.00826 0.0976562C6.19532 0.0976562 6.37471 0.171964 6.50698 0.304232C6.63925 0.436501 6.71356 0.615895 6.71356 0.802951C6.71356 0.990007 6.63925 1.1694 6.50698 1.30167C6.37471 1.43394 6.19532 1.50825 6.00826 1.50825H3.5339C3.25498 1.50797 2.97875 1.5627 2.72101 1.6693C2.46328 1.77591 2.22909 1.9323 2.03187 2.12953C1.83465 2.32675 1.67826 2.56093 1.57165 2.81867C1.46504 3.07641 1.41031 3.35264 1.41059 3.63155V12.4695C1.41059 13.6425 2.36088 14.5928 3.5339 14.5928H12.3718C12.6507 14.5931 12.927 14.5383 13.1847 14.4317C13.4424 14.3251 13.6766 14.1687 13.8739 13.9715C14.0711 13.7743 14.2275 13.5401 14.3341 13.2824C14.4407 13.0246 14.4954 12.7484 14.4951 12.4695V9.99512C14.4951 9.80806 14.5694 9.62866 14.7017 9.4964C14.834 9.36413 15.0134 9.28982 15.2004 9.28982C15.3875 9.28982 15.5669 9.36413 15.6991 9.4964C15.8314 9.62866 15.9057 9.80806 15.9057 9.99512V12.4695C15.906 12.9336 15.8148 13.3933 15.6373 13.8222C15.4598 14.2511 15.1995 14.6407 14.8713 14.9689C14.5431 15.2972 14.1534 15.5574 13.7245 15.7349C13.2956 15.9124 12.836 16.0037 12.3718 16.0034H3.5339C3.06974 16.0037 2.61008 15.9124 2.1812 15.7349C1.75233 15.5574 1.36264 15.2972 1.03443 14.9689C0.706225 14.6407 0.445931 14.2511 0.268434 13.8222C0.0909383 13.3933 -0.000278219 12.9336 6.37435e-07 12.4695V3.63155C0.000281772 2.69439 0.372692 1.79569 1.03537 1.13302C1.69804 0.470348 2.59674 0.0979374 3.5339 0.0976562H6.00826Z"
        fill="currentColor"
      />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M11.5869 0.737083C12.0772 0.259746 12.7358 -0.00507115 13.42 7.35832e-05C14.1042 0.00521832 14.7588 0.27991 15.2418 0.764565C15.7248 1.24922 15.9972 1.90475 16 2.58897C16.0027 3.27318 15.7356 3.93091 15.2566 4.41946L9.78076 9.93773C9.33119 10.3911 8.76041 10.7052 8.13684 10.8424L5.60626 11.3982C5.46463 11.4291 5.3175 11.4239 5.17839 11.3831C5.03929 11.3423 4.91269 11.2672 4.81023 11.1646C4.70778 11.062 4.63276 10.9354 4.59209 10.7962C4.55142 10.6571 4.54639 10.5099 4.57748 10.3683L5.1343 7.84412C5.27217 7.21837 5.58929 6.64459 6.04641 6.19384L11.5869 0.737083ZM14.2512 1.74783C14.0294 1.5258 13.7289 1.40052 13.4151 1.39933C13.1014 1.39813 12.7999 1.52113 12.5765 1.74147L7.03594 7.19928C6.77397 7.45806 6.59049 7.78685 6.51095 8.14745L6.13868 9.83804L7.83351 9.46471C8.19199 9.38622 8.52077 9.20486 8.77956 8.94502L14.2543 3.42569C14.4761 3.20258 14.6002 2.90064 14.5996 2.5861C14.5991 2.27156 14.4737 1.97009 14.2512 1.74783Z"
        fill="currentColor"
      />
    </svg>
  );
}

interface SidebarProps {
  chats: Chat[];
  activeChatId: string | null;
  collapsed: boolean;
  isMobileOpen: boolean;
  theme: "light" | "dark";
  user: AuthUser;
  errorText?: string | null;
  onSelectChat: (chatId: string) => void;
  onRenameChat: (chatId: string) => void;
  onDeleteChat: (chatId: string) => void;
  onCreateChat: () => void;
  onCloseMobileMenu: () => void;
  onToggleCollapsed: () => void;
  onToggleTheme: () => void;
  onLogout: () => void;
}

export default function Sidebar({
  chats,
  activeChatId,
  collapsed,
  isMobileOpen,
  theme,
  user,
  errorText,
  onSelectChat,
  onRenameChat,
  onDeleteChat,
  onCreateChat,
  onCloseMobileMenu,
  onToggleCollapsed,
  onToggleTheme,
  onLogout,
}: SidebarProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [isCollapsedHistoryOpen, setIsCollapsedHistoryOpen] = useState(false);
  const [historyMenuChatId, setHistoryMenuChatId] = useState<string | null>(null);
  const collapsedHistoryRef = useRef<HTMLDivElement>(null);

  const filteredChats = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return chats;
    return chats.filter((chat) => chat.title.toLowerCase().includes(query));
  }, [chats, searchQuery]);

  useEffect(() => {
    if (!collapsed) {
      setIsCollapsedHistoryOpen(false);
      setHistoryMenuChatId(null);
    }
  }, [collapsed]);

  useEffect(() => {
    if (!isCollapsedHistoryOpen) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (!collapsedHistoryRef.current?.contains(event.target as Node)) {
        setIsCollapsedHistoryOpen(false);
        setHistoryMenuChatId(null);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [isCollapsedHistoryOpen]);

  return (
    <>
      <div
        className={`${styles.overlay} ${isMobileOpen ? styles.overlayVisible : ""}`}
        onClick={onCloseMobileMenu}
      />
      <aside
        className={`${styles.sidebar} ${collapsed ? styles.sidebarCollapsed : ""} ${isMobileOpen ? styles.sidebarOpen : ""}`}
      >
        <div className={styles.headerRow}>
          <div className={styles.brandToggleWrap}>
            <h1 className={styles.title} aria-label="Lore">
              <span className={styles.wordmarkLetter}>L</span>
              <span className={styles.wordmarkDot} aria-hidden="true" />
              <span className={styles.wordmarkLetter}>RE</span>
            </h1>
            <button
              className={`${styles.toggleChatsButton} ${styles.tooltipTrigger}`}
              onClick={onToggleCollapsed}
              type="button"
              aria-label={collapsed ? "Показать список чатов" : "Скрыть список чатов"}
              title={collapsed ? "Показать список чатов" : "Скрыть список чатов"}
              data-tooltip={collapsed ? "Раскрыть меню" : undefined}
            >
              <ToggleChatsIcon />
            </button>
          </div>
          <button
            className={styles.closeButton}
            onClick={onCloseMobileMenu}
            type="button"
            aria-label="Закрыть меню"
          >
            <X size={18} />
          </button>
        </div>

        <div className={styles.primaryActions}>
          <button
            className={`${styles.newChatButton} ${styles.tooltipTrigger}`}
            onClick={onCreateChat}
            type="button"
            data-tooltip={collapsed ? "Новый чат" : undefined}
          >
            <NewChatIcon />
            <span>Новый чат</span>
          </button>

          <a
            className={`${styles.newChatButton} ${styles.tooltipTrigger}`}
            href="/files"
            style={{ textDecoration: "none" }}
            data-tooltip={collapsed ? "File Viewer" : undefined}
          >
            <FileViewerIcon />
            <span>File Viewer</span>
          </a>

          <div className={styles.collapsedHistoryWrap} ref={collapsedHistoryRef}>
            <button
              className={`${styles.collapsedHistoryButton} ${styles.tooltipTrigger}`}
              type="button"
              onClick={() => setIsCollapsedHistoryOpen((value) => !value)}
              aria-label="История чатов"
              title="История чатов"
              aria-expanded={isCollapsedHistoryOpen}
              data-tooltip="История чатов"
            >
              <HistoryChatsIcon />
            </button>

            {isCollapsedHistoryOpen ? (
              <div className={styles.collapsedHistoryDropdown}>
                {chats.length > 0 ? (
                  chats.map((chat) => (
                    <div
                      key={chat.id}
                      className={`${styles.collapsedHistoryItem} ${chat.id === activeChatId ? styles.collapsedHistoryItemActive : ""}`}
                    >
                      <button
                        className={styles.collapsedHistoryMain}
                        type="button"
                        onClick={() => {
                          onSelectChat(chat.id);
                          setIsCollapsedHistoryOpen(false);
                          setHistoryMenuChatId(null);
                        }}
                        title={chat.title}
                      >
                        <span className={styles.collapsedHistoryTitle}>{chat.title}</span>
                      </button>

                      <div className={styles.collapsedHistoryTopRight}>
                        <button
                          className={styles.collapsedHistoryMenuButton}
                          type="button"
                          aria-label="Меню чата"
                          aria-expanded={historyMenuChatId === chat.id}
                          onClick={(event) => {
                            event.stopPropagation();
                            setHistoryMenuChatId((current) =>
                              current === chat.id ? null : chat.id,
                            );
                          }}
                        >
                          <MoreHorizontal size={14} />
                        </button>
                      </div>

                      {historyMenuChatId === chat.id ? (
                        <div className={styles.collapsedHistoryItemDropdown}>
                          <button
                            className={styles.collapsedHistoryDropdownItem}
                            type="button"
                            onClick={() => {
                              setHistoryMenuChatId(null);
                              setIsCollapsedHistoryOpen(false);
                              onRenameChat(chat.id);
                            }}
                          >
                            <Pencil size={14} />
                            <span>Переименовать</span>
                          </button>
                          <button
                            className={`${styles.collapsedHistoryDropdownItem} ${styles.collapsedHistoryDropdownItemDanger}`}
                            type="button"
                            onClick={() => {
                              setHistoryMenuChatId(null);
                              setIsCollapsedHistoryOpen(false);
                              onDeleteChat(chat.id);
                            }}
                          >
                            <Trash2 size={14} />
                            <span>Удалить</span>
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className={styles.collapsedHistoryEmpty}>Нет тем</div>
                )}
              </div>
            ) : null}
          </div>
        </div>

        {errorText ? <p className={styles.errorText}>{errorText}</p> : null}

        <label className={styles.searchField}>
          <Search size={16} className={styles.searchIcon} />
          <input
            className={styles.searchInput}
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Поиск по чатам"
            aria-label="Поиск по чатам"
          />
        </label>

        <div className={styles.chatListWrap}>
          <ChatList
            chats={filteredChats}
            activeChatId={activeChatId}
            onSelectChat={onSelectChat}
            onRenameChat={onRenameChat}
            onDeleteChat={onDeleteChat}
          />
        </div>

        <div className={styles.userFooter}>
          <div className={styles.userInfo}>
            <UserRound size={18} />
            <span className={styles.userName}>{user.identifier}</span>
          </div>
          <div className={styles.footerActions}>
            <button
              className={`${styles.themeButton} ${styles.tooltipTrigger}`}
              onClick={onToggleTheme}
              type="button"
              aria-label={
                theme === "dark" ? "Включить дневную тему" : "Включить ночную тему"
              }
              title={theme === "dark" ? "Дневная тема" : "Ночная тема"}
              data-tooltip={collapsed ? (theme === "dark" ? "Дневная тема" : "Ночная тема") : undefined}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button
              className={`${styles.logoutButton} ${styles.tooltipTrigger}`}
              onClick={onLogout}
              type="button"
              aria-label="Выйти"
              title="Выйти"
              data-tooltip={collapsed ? "Выйти" : undefined}
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
