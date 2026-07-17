import { createContext, useContext } from "react";
import type { IStep } from "@chainlit/react-client";

export interface SessionUi {
  // true, пока идёт намеренное переключение сессии (выбор треда / новый чат):
  // маскируем разрыв сокета — прячем плашку реконнекта и мигание пустого чата.
  switching: boolean;
  // id ответа (assistant_message) → полный трейс хода (llm/tool/run) для
  // блока «Ход выполнения».
  traceByMessage: Map<string, IStep[]>;
  // id последнего ассистентского сообщения, пока идёт задача (loading);
  // иначе null. Управляет показом лоадера и раскрытием блока шагов.
  activeMessageId: string | null;
}

export const SessionUiContext = createContext<SessionUi>({
  switching: false,
  traceByMessage: new Map(),
  activeMessageId: null,
});

export const useSessionUi = (): SessionUi => useContext(SessionUiContext);
