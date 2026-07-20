import type { Chat, Message } from "../types/chat";
import type {
  ChatProvider,
  RegenerateMessageResult,
  SendMessageResult,
} from "./chatProvider";

const createUnsupportedStream = async function* () {
  yield "Chainlit provider is not configured yet.";
};

export class ChainlitChatProvider implements ChatProvider {
  constructor(private readonly baseUrl: string) {}

  async getChats(): Promise<Chat[]> {
    return [];
  }

  async getMessages(_chatId: string): Promise<Message[]> {
    return [];
  }

  async createChat(): Promise<Chat> {
    return {
      id: crypto.randomUUID(),
      title: "Новый чат",
      description: "Чат для Chainlit-сессии.",
      time: "Только что",
    };
  }

  async sendMessage(chatId: string, content: string): Promise<SendMessageResult> {
    const userMessage: Message = {
      id: crypto.randomUUID(),
      chatId,
      role: "user",
      content,
      status: "completed",
    };

    const assistantMessage: Message = {
      id: crypto.randomUUID(),
      chatId,
      role: "assistant",
      content: "",
      status: "streaming",
    };

    /*
      Здесь можно подключить Chainlit API:
      1. Создать/переиспользовать session id.
      2. Отправить POST на `${this.baseUrl}/api/message`.
      3. Прочитать ReadableStream и по чанкам обновлять assistant message.
      4. Сохранить thread metadata для списка чатов.
    */
    void this.baseUrl;

    return {
      userMessage,
      assistantMessage,
      stream: createUnsupportedStream(),
    };
  }

  async regenerateMessage(
    chatId: string,
    assistantMessageId: string,
  ): Promise<RegenerateMessageResult> {
    /*
      Для реального Chainlit-подключения здесь можно:
      1. Найти предыдущий user prompt.
      2. Отправить запрос на повторную генерацию.
      3. Вернуть новый stream и заменить assistantMessageId.
    */
    return {
      assistantMessage: {
        id: crypto.randomUUID(),
        chatId,
        role: "assistant",
        content: "",
        status: "streaming",
      },
      replaceMessageId: assistantMessageId,
      stream: createUnsupportedStream(),
    };
  }
}
