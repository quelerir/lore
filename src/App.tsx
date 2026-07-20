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

type ChatHistoryGroup = {
  label: string;
  chats: Chat[];
  order: number;
};

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

const parseTimeWeight = (time: string) => {
  if (time === "Только что") return 10_000;

  const match = time.match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return -1;

  const [, hours, minutes] = match;
  return Number(hours) * 60 + Number(minutes);
};

const getHistoryGroupMeta = (time: string) => {
  if (time === "Вчера") {
    return { label: "Вчера", order: 1 };
  }

  if (time === "Только что" || /^\d{1,2}:\d{2}$/.test(time)) {
    return { label: "Сегодня", order: 0 };
  }

  return { label: "Ранее", order: 2 };
};

function AppContent() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [messagesByChat, setMessagesByChat] = useState<Record<string, Message[]>>({});
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [composerValue, setComposerValue] = useState("");
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isHistoryPopoverOpen, setIsHistoryPopoverOpen] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [chatModal, setChatModal] = useState<ChatModalState>(null);
  const stopStreamingRef = useRef(false);
  const activeChat = useMemo(
    () => chats.find((chat) => chat.id === activeChatId) ?? null,
    [activeChatId, chats],
  );
  const historyGroups = useMemo(() => {
    const groups = chats.reduce<Map<string, ChatHistoryGroup>>((accumulator, chat) => {
      const groupMeta = getHistoryGroupMeta(chat.time);
      const existingGroup = accumulator.get(groupMeta.label);

      if (existingGroup) {
        existingGroup.chats.push(chat);
        return accumulator;
      }

      accumulator.set(groupMeta.label, {
        label: groupMeta.label,
        chats: [chat],
        order: groupMeta.order,
      });

      return accumulator;
    }, new Map());

    return [...groups.values()]
      .sort((left, right) => left.order - right.order)
      .map((group) => ({
        ...group,
        chats: [...group.chats].sort(
          (left, right) => parseTimeWeight(right.time) - parseTimeWeight(left.time),
        ),
      }));
  }, [chats]);
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
    setIsHistoryPopoverOpen(false);
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
          isCollapsed={isSidebarCollapsed}
          onSelectChat={handleSelectChat}
          onRenameChat={handleRenameChat}
          onDeleteChat={handleDeleteChat}
          onCreateChat={handleCreateChat}
          onCloseMobileMenu={() => setIsMobileSidebarOpen(false)}
          onToggleCollapse={() => {
            setIsSidebarCollapsed((prev) => !prev);
            setIsHistoryPopoverOpen(false);
          }}
          onOpenHistoryPopover={() => setIsHistoryPopoverOpen((prev) => !prev)}
        />

        <main className={styles.content}>
          {isHistoryPopoverOpen ? (
            <button
              className={styles.historyPopoverBackdrop}
              type="button"
              aria-label="Закрыть историю чатов"
              onClick={() => setIsHistoryPopoverOpen(false)}
            />
          ) : null}

          {isSidebarCollapsed && isHistoryPopoverOpen ? (
            <div className={styles.historyPopover}>
              <div className={styles.historyPopoverHeader}>Недавние чаты</div>
              <div className={styles.historyPopoverList}>
                {historyGroups.map((group) => (
                  <section key={group.label} className={styles.historyPopoverGroup}>
                    <div className={styles.historyPopoverGroupLabel}>{group.label}</div>
                    <div className={styles.historyPopoverGroupItems}>
                      {group.chats.map((chat) => (
                        <button
                          key={chat.id}
                          type="button"
                          className={`${styles.historyPopoverItem} ${
                            chat.id === activeChatId ? styles.historyPopoverItemActive : ""
                          }`}
                          onClick={() => handleSelectChat(chat.id)}
                        >
                          {chat.title}
                        </button>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            </div>
          ) : null}

          <ChatHeader
            title={activeChat?.title ?? "Lore"}
            onOpenSidebar={() => {
              if (window.innerWidth <= 960) {
                setIsMobileSidebarOpen(true);
                return;
              }

              setIsSidebarCollapsed(false);
              setIsHistoryPopoverOpen(false);
            }}
            showSidebarButton={isSidebarCollapsed}
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

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <AppContent />
    </AssistantRuntimeProvider>
  );
}
