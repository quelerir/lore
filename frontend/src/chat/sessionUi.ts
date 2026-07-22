import { createContext, useContext } from "react";
import type { IStep } from "@chainlit/react-client";
import type { Citation } from "./citations";
import type { Warning } from "./warnings";

export interface SessionUi {
  // true, пока идёт намеренное переключение сессии (выбор треда / новый чат):
  // маскируем разрыв сокета — прячем плашку реконнекта и мигание пустого чата.
  switching: boolean;
  // id ответа (assistant_message) → полный трейс хода (llm/tool/run) для
  // блока «Ход выполнения».
  traceByMessage: Map<string, IStep[]>;
  // id ответа (assistant_message) → его цитаты-источники (карточки под ответом,
  // клик → FileViewer). Сообщения без цитат в мапе отсутствуют.
  citationsByMessage: Map<string, Citation[]>;
  // id ответа (assistant_message) → предупреждения/ошибки хода (чипы/баннер под
  // ответом). Сообщения без предупреждений в мапе отсутствуют.
  warningsByMessage: Map<string, Warning[]>;
  // id последнего ассистентского сообщения, пока идёт задача (loading);
  // иначе null. Управляет показом лоадера и раскрытием блока шагов.
  activeMessageId: string | null;
}

export const SessionUiContext = createContext<SessionUi>({
  switching: false,
  traceByMessage: new Map(),
  citationsByMessage: new Map(),
  warningsByMessage: new Map(),
  activeMessageId: null,
});

export const useSessionUi = (): SessionUi => useContext(SessionUiContext);
