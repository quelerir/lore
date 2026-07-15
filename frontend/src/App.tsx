import {
  AssistantRuntimeProvider,
  type ChatModelAdapter,
  useLocalRuntime,
} from "@assistant-ui/react";
import { useEffect, useMemo, useRef, useState } from "react";
import ChatComposer from "./components/ChatComposer/ChatComposer";
import ChatHeader from "./components/ChatHeader/ChatHeader";
import MessageList from "./components/MessageList/MessageList";
import Sidebar from "./components/Sidebar/Sidebar";
import LoginScreen from "./components/LoginScreen/LoginScreen";
import { useAuth } from "./auth/useAuth";
import type { AuthUser } from "./auth/authClient";
import { chatProvider } from "./providers";
import type { Chat, Message } from "./types/chat";
import styles from "./App.module.css";

const STORAGE_KEY = "lore-chat-state";

const noopRuntimeAdapter: ChatModelAdapter = {
  async *run() {
    yield { content: [{ type: "text", text: "" as const }] };
  },
};

type PersistedChatState = {
  chats: Chat[];
  messagesByChat: Record<string, Message[]>;
  activeChatId: string | null;
};

type ChatModalState =
  | { type: "rename"; chatId: string; value: string }
  | { type: "delete"; chatId: string }
  | null;

const readPersistedState = (): PersistedChatState | null => {
  try {
    const rawState = window.localStorage.getItem(STORAGE_KEY);
    if (!rawState) return null;

    const parsedState = JSON.parse(rawState) as PersistedChatState;
    if (!Array.isArray(parsedState.chats) || !parsedState.messagesByChat) {
      return null;
    }

    return parsedState;
  } catch {
    return null;
  }
};

const writePersistedState = (state: PersistedChatState) => {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Ignore quota and private mode storage failures.
  }
};

function AppContent({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const [chats, setChats] = useState<Chat[]>([]);
  const [messagesByChat, setMessagesByChat] = useState<Record<string, Message[]>>({});
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [composerValue, setComposerValue] = useState("");
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [chatModal, setChatModal] = useState<ChatModalState>(null);
  const stopStreamingRef = useRef(false);
  const activeChat = useMemo(
    () => chats.find((chat) => chat.id === activeChatId) ?? null,
    [activeChatId, chats],
  );
  const activeMessages = activeChatId ? messagesByChat[activeChatId] ?? [] : [];
  const modalChat =
    chatModal ? chats.find((chat) => chat.id === chatModal.chatId) ?? null : null;

  useEffect(() => {
    const bootstrap = async () => {
      const persistedState = readPersistedState();
      if (persistedState) {
        setChats(persistedState.chats);
        setMessagesByChat(persistedState.messagesByChat);
        setActiveChatId(persistedState.activeChatId ?? persistedState.chats[0]?.id ?? null);
        setIsHydrated(true);
        return;
      }

      const initialChats = await chatProvider.getChats();
      setChats(initialChats);

      const entries = await Promise.all(
        initialChats.map(async (chat) => [chat.id, await chatProvider.getMessages(chat.id)] as const),
      );

      setMessagesByChat(Object.fromEntries(entries));
      setActiveChatId(initialChats[3]?.id ?? initialChats[0]?.id ?? null);
      setIsHydrated(true);
    };

    void bootstrap();
  }, []);

  useEffect(() => {
    if (!isHydrated) return;

    writePersistedState({
      chats,
      messagesByChat,
      activeChatId,
    });
  }, [activeChatId, chats, isHydrated, messagesByChat]);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const viewport = document.querySelector('[data-radix-scroll-area-viewport]') as
        | HTMLDivElement
        | null;
      if (viewport) {
        viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
      }
    });

    return () => cancelAnimationFrame(frame);
  }, [activeMessages]);

  const upsertChatMessages = (chatId: string, nextMessages: Message[]) => {
    setMessagesByChat((prev) => ({
      ...prev,
      [chatId]: nextMessages,
    }));
  };

  const handleCreateChat = async () => {
    const chat = await chatProvider.createChat();
    setChats((prev) => [chat, ...prev]);
    setMessagesByChat((prev) => ({ ...prev, [chat.id]: [] }));
    setActiveChatId(chat.id);
    setIsMobileSidebarOpen(false);
  };

  const handleSelectChat = (chatId: string) => {
    setActiveChatId(chatId);
    setIsMobileSidebarOpen(false);
  };

  const handleRenameChat = (chatId: string) => {
    const chat = chats.find((item) => item.id === chatId);
    if (!chat) return;

    setChatModal({
      type: "rename",
      chatId,
      value: chat.title,
    });
  };

  const deleteChat = async (chatId: string) => {
    const chatIndex = chats.findIndex((item) => item.id === chatId);
    if (chatIndex === -1) return;

    const remainingChats = chats.filter((item) => item.id !== chatId);
    const nextMessagesByChat = { ...messagesByChat };
    delete nextMessagesByChat[chatId];

    setChats(remainingChats);
    setMessagesByChat(nextMessagesByChat);

    if (activeChatId !== chatId) {
      return;
    }

    if (remainingChats.length > 0) {
      const fallbackChat = remainingChats[Math.max(0, chatIndex - 1)] ?? remainingChats[0];
      setActiveChatId(fallbackChat.id);
      return;
    }

    const newChat = await chatProvider.createChat();
    setChats([newChat]);
    setMessagesByChat({ [newChat.id]: [] });
    setActiveChatId(newChat.id);
  };

  const handleDeleteChat = (chatId: string) => {
    setChatModal({ type: "delete", chatId });
  };

  const handleCloseModal = () => {
    setChatModal(null);
  };

  const handleConfirmModal = async () => {
    if (!chatModal) return;

    if (chatModal.type === "rename") {
      const nextTitle = chatModal.value.trim();
      if (!nextTitle) return;

      setChats((prev) =>
        prev.map((item) =>
          item.id === chatModal.chatId ? { ...item, title: nextTitle } : item,
        ),
      );
      setChatModal(null);
      return;
    }

    await deleteChat(chatModal.chatId);
    setChatModal(null);
  };

  const syncChatPreview = (chatId: string, content: string) => {
    setChats((prev) =>
      prev.map((chat) =>
        chat.id === chatId
          ? {
              ...chat,
              title: chat.title === "Новый чат" ? content.slice(0, 34) || chat.title : chat.title,
              description: content.slice(0, 72),
              time: "Только что",
            }
          : chat,
      ),
    );
  };

  const handleSubmit = async () => {
    if (!activeChatId || !composerValue.trim() || isStreaming) return;

    const trimmedValue = composerValue.trim();
    setComposerValue("");
    setIsStreaming(true);
    stopStreamingRef.current = false;

    const result = await chatProvider.sendMessage(activeChatId, trimmedValue);
    const currentMessages = messagesByChat[activeChatId] ?? [];

    upsertChatMessages(activeChatId, [
      ...currentMessages,
      result.userMessage,
      result.assistantMessage,
    ]);
    syncChatPreview(activeChatId, trimmedValue);

    for await (const partial of result.stream) {
      if (stopStreamingRef.current) {
        await result.stream.return?.();
        break;
      }

      setMessagesByChat((prev) => ({
        ...prev,
        [activeChatId]: (prev[activeChatId] ?? []).map((message) =>
          message.id === result.assistantMessage.id
            ? { ...message, content: partial, status: "streaming" }
            : message,
        ),
      }));
    }

    setMessagesByChat((prev) => ({
      ...prev,
      [activeChatId]: (prev[activeChatId] ?? []).map((message) =>
        message.id === result.assistantMessage.id
          ? { ...message, status: "completed" }
          : message,
      ),
    }));
    setIsStreaming(false);
    stopStreamingRef.current = false;
  };

  const handleStopStreaming = () => {
    stopStreamingRef.current = true;
    setIsStreaming(false);
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

  const handleCopy = async (_messageId: string, content: string) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(content);
        return true;
      }
    } catch {
      // Fallback below handles environments without clipboard access.
    }

    try {
      const textarea = document.createElement("textarea");
      textarea.value = content;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      textarea.style.pointerEvents = "none";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);

      const copied = document.execCommand("copy");
      document.body.removeChild(textarea);
      return copied;
    } catch {
      return false;
    }
  };

  const handleRegenerate = async (messageId: string) => {
    if (!activeChatId) return;

    setIsStreaming(true);
    stopStreamingRef.current = false;

    const result = await chatProvider.regenerateMessage(activeChatId, messageId);

    setMessagesByChat((prev) => ({
      ...prev,
      [activeChatId]: (prev[activeChatId] ?? []).map((message) =>
        message.id === result.replaceMessageId ? result.assistantMessage : message,
      ),
    }));

    for await (const partial of result.stream) {
      if (stopStreamingRef.current) {
        await result.stream.return?.();
        break;
      }

      setMessagesByChat((prev) => ({
        ...prev,
        [activeChatId]: (prev[activeChatId] ?? []).map((message) =>
          message.id === result.assistantMessage.id
            ? { ...message, content: partial, status: "streaming" }
            : message,
        ),
      }));
    }

    setMessagesByChat((prev) => ({
      ...prev,
      [activeChatId]: (prev[activeChatId] ?? []).map((message) =>
        message.id === result.assistantMessage.id
          ? { ...message, status: "completed" }
          : message,
      ),
    }));
    setIsStreaming(false);
    stopStreamingRef.current = false;
  };

  return (
    <div className={styles.shell}>
      <div className={styles.frame}>
        <Sidebar
          chats={chats}
          activeChatId={activeChatId}
          isMobileOpen={isMobileSidebarOpen}
          user={user}
          onLogout={onLogout}
          onSelectChat={handleSelectChat}
          onRenameChat={handleRenameChat}
          onDeleteChat={handleDeleteChat}
          onCreateChat={handleCreateChat}
          onCloseMobileMenu={() => setIsMobileSidebarOpen(false)}
        />

        <main className={styles.content}>
          <ChatHeader
            title={activeChat?.title ?? "Lore"}
            onOpenSidebar={() => setIsMobileSidebarOpen(true)}
          />

          {!isHydrated || !activeChatId ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyCard}>
                <h3>Подготовьте новый executive brief</h3>
                <p>
                  Создайте чат слева или выберите существующий диалог, чтобы продолжить
                  обсуждение.
                </p>
              </div>
            </div>
          ) : (
            <>
              <MessageList
                messages={activeMessages}
                onCopy={handleCopy}
                onRegenerate={handleRegenerate}
              />
              <p className={styles.disclaimer}>
                Lore может допускать ошибки. Рекомендуем проверять важную информацию.
              </p>
              <ChatComposer
                value={composerValue}
                onChange={setComposerValue}
                onSubmit={handleSubmit}
                onStop={handleStopStreaming}
                isStreaming={isStreaming}
              />
            </>
          )}
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
                  ? `Чат "${modalChat.title}" будет удален из списка вместе со всей историей сообщений.`
                  : "Чат будет удален из списка вместе со всей историей сообщений."}
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
  const runtime = useLocalRuntime(noopRuntimeAdapter);
  const { state, login, logout } = useAuth();

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
    <AssistantRuntimeProvider runtime={runtime}>
      <AppContent user={state.user} onLogout={() => void logout()} />
    </AssistantRuntimeProvider>
  );
}
