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

interface AppContentProps {
  user: AuthUser;
  activeThreadId: string | null;
  mode: ChatMode;
  onModeChange: (mode: ChatMode) => void;
  onSelectThread: (id: string | null) => void;
  registerRefresh: (refresh: () => void) => void;
  onLogout: () => void;
}

function AppContent({
  user,
  activeThreadId,
  mode,
  onModeChange,
  onSelectThread,
  registerRefresh,
  onLogout,
}: AppContentProps) {
  const { chats, error: threadsError, refresh, rename, remove } = useThreads();
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [chatModal, setChatModal] = useState<ChatModalState>(null);

  useEffect(() => {
    registerRefresh(() => void refresh());
  }, [refresh, registerRefresh]);

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
          isMobileOpen={isMobileSidebarOpen}
          user={user}
          mode={mode}
          onModeChange={onModeChange}
          errorText={threadsError}
          onSelectChat={handleSelectChat}
          onRenameChat={handleRenameChat}
          onDeleteChat={handleDeleteChat}
          onCreateChat={handleCreateChat}
          onCloseMobileMenu={() => setIsMobileSidebarOpen(false)}
          onLogout={onLogout}
        />

        <main className={styles.content}>
          <ChatHeader
            title={activeChat?.title ?? "Lore"}
            onOpenSidebar={() => setIsMobileSidebarOpen(true)}
          />

          <MessageList />
          <p className={styles.disclaimer}>
            Lore может допускать ошибки. Рекомендуем проверять важную информацию.
          </p>
          <ChatComposer />
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
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [mode, setMode] = useState<ChatMode>("fast");
  const refreshThreadsRef = useRef<(() => void) | null>(null);

  // Смена режима действует на новый чат: активный тред сбрасывается,
  // SessionBridge создаст свежую сессию с выбранным профилем.
  const handleModeChange = useCallback((next: ChatMode) => {
    setMode(next);
    setActiveThreadId(null);
  }, []);

  useEffect(() => {
    setOn401(invalidate);
  }, [invalidate]);

  const registerRefresh = useCallback((refresh: () => void) => {
    refreshThreadsRef.current = refresh;
  }, []);

  const handleServerThreadId = useCallback((id: string) => {
    setActiveThreadId(id);
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
      activeThreadId={activeThreadId}
      chatProfile={mode}
      onServerThreadId={handleServerThreadId}
    >
      <AppContent
        user={state.user}
        activeThreadId={activeThreadId}
        mode={mode}
        onModeChange={handleModeChange}
        onSelectThread={setActiveThreadId}
        registerRefresh={registerRefresh}
        onLogout={() => void logout()}
      />
    </ChainlitRuntimeProvider>
  );
}
