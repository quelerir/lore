import { createContext, useContext } from "react";

export interface SessionUi {
  // true, пока идёт намеренное переключение сессии (выбор треда / новый чат):
  // маскируем разрыв сокета — прячем плашку реконнекта и мигание пустого чата.
  switching: boolean;
}

export const SessionUiContext = createContext<SessionUi>({ switching: false });

export const useSessionUi = (): SessionUi => useContext(SessionUiContext);
