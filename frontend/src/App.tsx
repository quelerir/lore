import { useCallback, useEffect, useRef, useState } from "react";
import type { AuthUser } from "./auth/authClient";
import { useAuth } from "./auth/useAuth";
import ChainlitRuntimeProvider, {
  type ChatMode,
} from "./chat/ChainlitRuntimeProvider";
import { setOn401 } from "./chat/chainlitClient";
import { useThreads } from "./chat/useThreads";
import ChatComposer from "./components/ChatComposer/ChatComposer";
import ChatHeader from "./components/ChatHeader/ChatHeader";
import LoginScreen from "./components/LoginScreen/LoginScreen";
import MessageList from "./components/MessageList/MessageList";
import Sidebar from "./components/Sidebar/Sidebar";
import styles from "./App.module.css";

type ChatModalState =
  | { type: "rename"; chatId: string; value: string }
  | { type: "delete"; chatId: string }
  | null;

type ThemeMode = "light" | "dark";

interface AppContentProps {
  user: AuthUser;
  activeThreadId: string | null;
  mode: ChatMode;
  theme: ThemeMode;
  onModeChange: (mode: ChatMode) => void;
  onSelectThread: (id: string | null) => void;
  registerRefresh: (refresh: () => void) => void;
  onLogout: () => void;
  onToggleTheme: () => void;
}

function AppContent({
  user,
  activeThreadId,
  mode,
  theme,
  onModeChange,
  onSelectThread,
  registerRefresh,
  onLogout,
  onToggleTheme,
}: AppContentProps) {
  const { chats, error: threadsError, refresh, rename, remove } = useThreads();
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(true);
  const [chatModal, setChatModal] = useState<ChatModalState>(null);
  const [messageSearchQuery, setMessageSearchQuery] = useState("");
  const [activeSearchIndex, setActiveSearchIndex] = useState(0);
  const [searchState, setSearchState] = useState({ total: 0, active: 0 });

  useEffect(() => {
    registerRefresh(() => void refresh());
  }, [refresh, registerRefresh]);

  useEffect(() => {
    setMessageSearchQuery("");
    setActiveSearchIndex(0);
    setSearchState({ total: 0, active: 0 });
  }, [activeThreadId]);

  const activeChat = chats.find((chat) => chat.id === activeThreadId) ?? null;
  const modalChat = chatModal
    ? chats.find((chat) => chat.id === chatModal.chatId) ?? null
    : null;

  const handleSelectChat = (chatId: string) => {
    onSelectThread(chatId);
    setIsMobileSidebarOpen(false);
  };

  const handleCreateChat = () => {
    onSelectThread(null);
    setIsMobileSidebarOpen(false);
  };

  const handleRenameChat = (chatId: string) => {
    const chat = chats.find((item) => item.id === chatId);
    if (!chat) return;
    setChatModal({ type: "rename", chatId, value: chat.title });
  };

  const handleDeleteChat = (chatId: string) => {
    setChatModal({ type: "delete", chatId });
  };

  const handleCloseModal = () => setChatModal(null);

  const handleConfirmModal = async () => {
    if (!chatModal) return;

    if (chatModal.type === "rename") {
      const nextTitle = chatModal.value.trim();
      if (!nextTitle) return;
      await rename(chatModal.chatId, nextTitle);
      setChatModal(null);
      return;
    }

    await remove(chatModal.chatId);
    if (activeThreadId === chatModal.chatId) {
      onSelectThread(null);
    }
    setChatModal(null);
  };

  useEffect(() => {
    if (!chatModal) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setChatModal(null);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [chatModal]);

  return (
    <div className={styles.shell}>
      <div className={styles.frame}>
        <Sidebar
          chats={chats}
          activeChatId={activeThreadId}
          collapsed={isSidebarCollapsed}
          isMobileOpen={isMobileSidebarOpen}
          theme={theme}
          user={user}
          errorText={threadsError}
          onSelectChat={handleSelectChat}
          onRenameChat={handleRenameChat}
          onDeleteChat={handleDeleteChat}
          onCreateChat={handleCreateChat}
          onCloseMobileMenu={() => setIsMobileSidebarOpen(false)}
          onToggleCollapsed={() => setIsSidebarCollapsed((value) => !value)}
          onToggleTheme={onToggleTheme}
          onLogout={onLogout}
        />

        <main className={styles.content}>
          <ChatHeader
            title={activeChat?.title ?? "Новый чат"}
            onOpenSidebar={() => setIsMobileSidebarOpen(true)}
            searchQuery={messageSearchQuery}
            searchPosition={searchState.active}
            searchTotal={searchState.total}
            onSearchQueryChange={(value) => {
              setMessageSearchQuery(value);
              setActiveSearchIndex(0);
            }}
            onSearchNext={() => {
              if (searchState.total === 0) return;
              setActiveSearchIndex((current) => (current + 1) % searchState.total);
            }}
            onSearchPrevious={() => {
              if (searchState.total === 0) return;
              setActiveSearchIndex(
                (current) => (current - 1 + searchState.total) % searchState.total,
              );
            }}
            onSearchClear={() => {
              setMessageSearchQuery("");
              setActiveSearchIndex(0);
              setSearchState({ total: 0, active: 0 });
            }}
          />

          <MessageList
            searchQuery={messageSearchQuery}
            activeSearchIndex={activeSearchIndex}
            onSearchStateChange={setSearchState}
          />
          <p className={styles.disclaimer}>
            Lore может допускать ошибки. Рекомендуем проверять важную информацию.
          </p>
          <ChatComposer mode={mode} onModeChange={onModeChange} />
        </main>
      </div>

      {chatModal ? (
        <div className={styles.modalOverlay} onClick={handleCloseModal}>
          <div
            className={styles.modalCard}
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="chat-modal-title"
          >
            <h3 id="chat-modal-title" className={styles.modalTitle}>
              {chatModal.type === "rename" ? "Переименовать чат" : "Удалить чат"}
            </h3>

            {chatModal.type === "rename" ? (
              <>
                <p className={styles.modalText}>Введите новое название чата.</p>
                <input
                  className={styles.modalInput}
                  autoFocus
                  value={chatModal.value}
                  onChange={(event) =>
                    setChatModal((prev) =>
                      prev?.type === "rename"
                        ? { ...prev, value: event.target.value }
                        : prev,
                    )
                  }
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void handleConfirmModal();
                    }
                  }}
                />
              </>
            ) : (
              <p className={styles.modalText}>
                {modalChat
                  ? `Чат "${modalChat.title}" будет удален вместе со всей историей сообщений.`
                  : "Чат будет удален вместе со всей историей сообщений."}
              </p>
            )}

            <div className={styles.modalActions}>
              <button
                className={styles.modalSecondaryButton}
                onClick={handleCloseModal}
                type="button"
              >
                Отмена
              </button>
              <button
                className={styles.modalPrimaryButton}
                onClick={() => void handleConfirmModal()}
                type="button"
                disabled={chatModal.type === "rename" && !chatModal.value.trim()}
              >
                {chatModal.type === "rename" ? "Сохранить" : "Удалить"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function App() {
  const { state, login, logout, invalidate } = useAuth();
  // Тред, выбранный пользователем (null = новый чат) — источник resume.
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(null);
  // Id, который сервер присвоил новому треду — только для подсветки в списке.
  const [serverThreadId, setServerThreadId] = useState<string | null>(null);
  // Растёт при каждом явном переключении сессии, чтобы SessionBridge
  // переподключился даже когда выбранный тред формально не меняется
  // (например «новый чат» → null поверх null).
  const [sessionNonce, setSessionNonce] = useState(0);
  const [mode, setMode] = useState<ChatMode>("fast");
  const [theme, setTheme] = useState<ThemeMode>(() => {
    if (typeof window === "undefined") return "light";
    const stored = window.localStorage.getItem("lore-theme");
    return stored === "dark" ? "dark" : "light";
  });
  const refreshThreadsRef = useRef<(() => void) | null>(null);

  const activeThreadId = selectedThreadId ?? serverThreadId;

  // Явный старт сессии: выбор существующего треда или новый чат (null).
  const startSession = useCallback((threadId: string | null) => {
    setSelectedThreadId(threadId);
    setServerThreadId(null);
    setSessionNonce((n) => n + 1);
  }, []);

  // Смена режима действует на новый чат: SessionBridge создаст свежую сессию.
  const handleModeChange = useCallback(
    (next: ChatMode) => {
      setMode(next);
      startSession(null);
    },
    [startSession],
  );

  useEffect(() => {
    setOn401(invalidate);
  }, [invalidate]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("lore-theme", theme);
  }, [theme]);

  const registerRefresh = useCallback((refresh: () => void) => {
    refreshThreadsRef.current = refresh;
  }, []);

  // Сервер присвоил id новому треду — обновляем подсветку, но НЕ трогаем
  // selectedThreadId/sessionNonce, поэтому reconnect не запускается.
  const handleServerThreadId = useCallback((id: string) => {
    setServerThreadId(id);
    refreshThreadsRef.current?.();
  }, []);

  if (state.status === "loading") {
    return <div className={styles.authLoading}>Загрузка…</div>;
  }

  if (state.status === "anonymous") {
    return (
      <LoginScreen
        onLogin={() => void login()}
        isBusy={state.isBusy}
        error={state.error}
      />
    );
  }

  return (
    <ChainlitRuntimeProvider
      sessionThreadId={selectedThreadId}
      sessionNonce={sessionNonce}
      chatProfile={mode}
      onServerThreadId={handleServerThreadId}
    >
      <AppContent
        user={state.user}
        activeThreadId={activeThreadId}
        mode={mode}
        theme={theme}
        onModeChange={handleModeChange}
        onSelectThread={startSession}
        registerRefresh={registerRefresh}
        onLogout={() => void logout()}
        onToggleTheme={() =>
          setTheme((current) => (current === "dark" ? "light" : "dark"))
        }
      />
    </ChainlitRuntimeProvider>
  );
}
