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
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { RecoilRoot } from "recoil";
import { chainlitApi } from "./chainlitClient";
import { collectCitationsByMessage } from "./citations";
import { collectChatMessages, convertMessage } from "./convertMessage";
import { collectTraceByMessage } from "./executionSteps";
import { SessionUiContext } from "./sessionUi";
import { collectWarningsByMessage } from "./warnings";

export type ChatMode = "fast" | "deep";

interface ProviderProps {
  // Тред, выбранный пользователем (null = новый чат). Определяет resume.
  sessionThreadId: string | null;
  // Растёт при каждом ЯВНОМ переключении сессии (выбор треда / новый чат).
  // Эхо серверного threadId сюда не входит — иначе принятие своего же id
  // вызывало бесконечный reconnect.
  sessionNonce: number;
  chatProfile: ChatMode;
  onServerThreadId: (id: string) => void;
  children: ReactNode;
}

const appendMessageText = (message: AppendMessage): string =>
  message.content
    .filter((part): part is { type: "text"; text: string } => part.type === "text")
    .map((part) => part.text)
    .join("\n");

function SessionBridge({
  sessionThreadId,
  sessionNonce,
  chatProfile,
  onServerThreadId,
  children,
}: ProviderProps) {
  const { connect, disconnect, setChatProfile } = useChatSession();
  const { clear, sendMessage, stopTask, setIdToResume } = useChatInteract();
  const { messages, threadId } = useChatMessages();
  const { loading, connected } = useChatData();

  // Пока идёт намеренное переключение — маскируем разрыв сокета (плашка +
  // мигание пустого чата). Реальные обрывы (без смены sessionNonce) не
  // попадают под маску и покажут плашку как раньше.
  const [switching, setSwitching] = useState(false);

  // Явное переключение → входим в режим маскировки. Страховочный таймаут
  // снимает маску, если reconnect почему-то затянулся.
  useEffect(() => {
    setSwitching(true);
    const cap = window.setTimeout(() => setSwitching(false), 1500);
    return () => window.clearTimeout(cap);
  }, [sessionNonce]);

  // Снимаем маску вскоре после восстановления соединения (тред уже резюмлен,
  // сообщения отрисованы) — небольшой запас, чтобы не мигнуло.
  useEffect(() => {
    if (!switching || !connected) return;
    const t = window.setTimeout(() => setSwitching(false), 140);
    return () => window.clearTimeout(t);
  }, [switching, connected]);

  // Шаг 1. Явное переключение сессии (sessionNonce) или смена режима: чистим
  // экран и ПУБЛИКУЕМ resume-id/профиль. Сам connect — в шаге 2 ниже.
  //
  // Почему не connect() прямо здесь: react-client замыкает resume-id (threadId)
  // в момент рендера, поэтому connect() сразу после setIdToResume() подхватил
  // бы ПРЕДЫДУЩИЙ id и резюмил не тот тред — баг «переключение со второго раза».
  useEffect(() => {
    clear();
    setChatProfile(chatProfile);
    setIdToResume(sessionThreadId ?? undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionNonce, chatProfile]);

  // Шаг 2. Подключаемся при явном переключении (sessionNonce) ИЛИ когда
  // react-client пересоздал `connect` уже со свежим resume-id — тогда сокет
  // резюмит нужный тред. `connect` стабилен после подключения, так что
  // reconnect-петли это не создаёт.
  useEffect(() => {
    void connect({ userEnv: {} });
    return () => {
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionNonce, connect]);

  // Сервер присвоил id новому треду (первое сообщение) — сообщаем наверх ТОЛЬКО
  // для подсветки в списке. Это не трогает sessionNonce/sessionThreadId, так что
  // reconnect не триггерится.
  useEffect(() => {
    if (threadId && threadId !== sessionThreadId) {
      onServerThreadId(threadId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  // react-client вкладывает ответы ассистента в run-обёртку on_message; берём
  // сообщения из всего дерева, а не только с верхнего уровня.
  const chatMessages = useMemo(() => collectChatMessages(messages), [messages]);

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

  const traceByMessage = useMemo(
    () => collectTraceByMessage(messages),
    [messages],
  );

  const citationsByMessage = useMemo(
    () => collectCitationsByMessage(messages),
    [messages],
  );

  const warningsByMessage = useMemo(
    () => collectWarningsByMessage(messages),
    [messages],
  );

  // Пока идёт задача — последний ассистентский ответ считается активным:
  // на нём показываем лоадер и держим блок шагов раскрытым.
  const activeMessageId = useMemo(() => {
    if (!loading) return null;
    for (let i = chatMessages.length - 1; i >= 0; i--) {
      if (chatMessages[i].type === "assistant_message") return chatMessages[i].id;
    }
    return null;
  }, [loading, chatMessages]);

  const sessionUi = useMemo(
    () => ({
      switching,
      traceByMessage,
      citationsByMessage,
      warningsByMessage,
      activeMessageId,
    }),
    [switching, traceByMessage, citationsByMessage, warningsByMessage, activeMessageId],
  );

  return (
    <SessionUiContext.Provider value={sessionUi}>
      <AssistantRuntimeProvider runtime={runtime}>
        {connected === false && !switching ? (
          <div className="wsReconnectBanner">Переподключение к серверу…</div>
        ) : null}
        {children}
      </AssistantRuntimeProvider>
    </SessionUiContext.Provider>
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
