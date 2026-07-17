import { useCallback, useEffect, useState } from "react";
import type { Chat } from "../types/chat";
import { chainlitApi } from "./chainlitClient";
import { threadToChat } from "./threadToChat";

const PAGE_SIZE = 50;

export function useThreads() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { data } = await chainlitApi.listThreads({ first: PAGE_SIZE }, {});
      setChats(data.map(threadToChat));
      setError(null);
    } catch {
      setError("Не удалось загрузить список чатов.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const rename = useCallback(
    async (id: string, name: string) => {
      await chainlitApi.renameThread(id, name);
      await refresh();
    },
    [refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      await chainlitApi.deleteThread(id);
      await refresh();
    },
    [refresh],
  );

  return { chats, isLoading, error, refresh, rename, remove };
}
