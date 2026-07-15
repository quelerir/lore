import type { Chat, Message } from "../types/chat";

export interface SendMessageResult {
  userMessage: Message;
  assistantMessage: Message;
  stream: AsyncGenerator<string, void, void>;
}

export interface RegenerateMessageResult {
  assistantMessage: Message;
  replaceMessageId: string;
  stream: AsyncGenerator<string, void, void>;
}

export interface ChatProvider {
  getChats(): Promise<Chat[]>;
  getMessages(chatId: string): Promise<Message[]>;
  createChat(): Promise<Chat>;
  sendMessage(chatId: string, content: string): Promise<SendMessageResult>;
  regenerateMessage(
    chatId: string,
    assistantMessageId: string,
  ): Promise<RegenerateMessageResult>;
}
