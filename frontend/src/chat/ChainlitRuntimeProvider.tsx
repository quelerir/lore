import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type AppendMessage,
} from "@assistant-ui/react";
import {
  ChainlitContext,
  useChatData,
  useChatInteract,
  useChatMessages,
  useChatSession,
} from "@chainlit/react-client";
import { useEffect, useMemo, type ReactNode } from "react";
import { RecoilRoot } from "recoil";
import { chainlitApi } from "./chainlitClient";
import { convertMessage, isChatMessage } from "./convertMessage";

interface ProviderProps {
  activeThreadId: string | null;
  onServerThreadId: (id: string) => void;
  children: ReactNode;
}

const appendMessageText = (message: AppendMessage): string =>
  message.content
    .filter((part): part is { type: "text"; text: string } => part.type === "text")
    .map((part) => part.text)
    .join("\n");

function SessionBridge({ activeThreadId, onServerThreadId, children }: ProviderProps) {
  const { connect, disconnect } = useChatSession();
  const { clear, sendMessage, stopTask, setIdToResume } = useChatInteract();
  const { messages, threadId } = useChatMessages();
  const { loading, connected } = useChatData();

  // Одна WS-сессия на активный тред: смена треда = clear + resume + reconnect.
  useEffect(() => {
    clear();
    setIdToResume(activeThreadId ?? undefined);
    void connect({ userEnv: {} });
    return () => {
      disconnect();
    };
    // connect/clear/… стабильны между рендерами (recoil-колбэки react-client)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThreadId]);

  // Сервер присвоил id новому треду (первое сообщение) — сообщаем наверх.
  useEffect(() => {
    if (threadId && threadId !== activeThreadId) {
      onServerThreadId(threadId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  const chatMessages = useMemo(() => messages.filter(isChatMessage), [messages]);

  const runtime = useExternalStoreRuntime({
    messages: chatMessages,
    convertMessage,
    isRunning: loading,
    isDisabled: connected === false,
    onNew: async (message: AppendMessage) => {
      sendMessage({
        name: "user",
        type: "user_message",
        output: appendMessageText(message),
      });
    },
    onCancel: async () => {
      stopTask();
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {connected === false ? (
        <div className="wsReconnectBanner">Переподключение к серверу…</div>
      ) : null}
      {children}
    </AssistantRuntimeProvider>
  );
}

export default function ChainlitRuntimeProvider(props: ProviderProps) {
  return (
    <RecoilRoot>
      <ChainlitContext.Provider value={chainlitApi}>
        <SessionBridge {...props} />
      </ChainlitContext.Provider>
    </RecoilRoot>
  );
}
