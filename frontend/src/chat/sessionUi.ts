import { createContext, useContext } from "react";
import type { IStep } from "@chainlit/react-client";

export interface SessionUi {
  // true, пока идёт намеренное переключение сессии (выбор треда / новый чат):
  // маскируем разрыв сокета — прячем плашку реконнекта и мигание пустого чата.
  switching: boolean;
  // id ответа (assistant_message) → его tool-шаги для блока «Ход выполнения».
  toolStepsByMessage: Map<string, IStep[]>;
  // id последнего ассистентского сообщения, пока идёт задача (loading);
  // иначе null. Управляет показом лоадера и раскрытием блока шагов.
  activeMessageId: string | null;
}

export const SessionUiContext = createContext<SessionUi>({
  switching: false,
  toolStepsByMessage: new Map(),
  activeMessageId: null,
});

export const useSessionUi = (): SessionUi => useContext(SessionUiContext);
