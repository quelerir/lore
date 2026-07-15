import {
  AssistantRuntimeProvider,
  type ChatModelAdapter,
  useLocalRuntime,
} from "@assistant-ui/react";
import { useEffect, useMemo, useState } from "react";
import ChatComposer from "./components/ChatComposer/ChatComposer";
import ChatHeader from "./components/ChatHeader/ChatHeader";
import MessageList from "./components/MessageList/MessageList";
import Sidebar from "./components/Sidebar/Sidebar";
import { chatProvider } from "./providers";
import type { Chat, Message } from "./types/chat";
import styles from "./App.module.css";

const noopRuntimeAdapter: ChatModelAdapter = {
  async *run() {
    yield { content: [{ type: "text", text: "" as const }] };
  },
};

function AppContent() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [messagesByChat, setMessagesByChat] = useState<Record<string, Message[]>>({});
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [composerValue, setComposerValue] = useState("");
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);
  const activeChat = useMemo(
    () => chats.find((chat) => chat.id === activeChatId) ?? null,
    [activeChatId, chats],
  );
  const activeMessages = activeChatId ? messagesByChat[activeChatId] ?? [] : [];
  useEffect(() => {
    const bootstrap = async () => {
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
    if (!activeChatId || !composerValue.trim()) return;

    const trimmedValue = composerValue.trim();
    setComposerValue("");

    const result = await chatProvider.sendMessage(activeChatId, trimmedValue);
    const currentMessages = messagesByChat[activeChatId] ?? [];

    upsertChatMessages(activeChatId, [
      ...currentMessages,
      result.userMessage,
      result.assistantMessage,
    ]);
    syncChatPreview(activeChatId, trimmedValue);

    for await (const partial of result.stream) {
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
  };

  const handleCopy = async (_messageId: string, content: string) => {
    await navigator.clipboard.writeText(content);
  };

  const handleRegenerate = async (messageId: string) => {
    if (!activeChatId) return;

    const result = await chatProvider.regenerateMessage(activeChatId, messageId);

    setMessagesByChat((prev) => ({
      ...prev,
      [activeChatId]: (prev[activeChatId] ?? []).map((message) =>
        message.id === result.replaceMessageId ? result.assistantMessage : message,
      ),
    }));

    for await (const partial of result.stream) {
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
  };

  return (
    <div className={styles.shell}>
      <div className={styles.frame}>
        <Sidebar
          chats={chats}
          activeChatId={activeChatId}
          isMobileOpen={isMobileSidebarOpen}
          onSelectChat={handleSelectChat}
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
              <ChatComposer
                value={composerValue}
                onChange={setComposerValue}
                onSubmit={handleSubmit}
              />
            </>
          )}
        </main>
      </div>
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
