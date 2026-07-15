import type { Chat } from "../../types/chat";
import ChatListItem from "../ChatListItem/ChatListItem";
import styles from "./ChatList.module.css";

interface ChatListProps {
  chats: Chat[];
  activeChatId: string | null;
  onSelectChat: (chatId: string) => void;
}

export default function ChatList({
  chats,
  activeChatId,
  onSelectChat,
}: ChatListProps) {
  return (
    <div className={styles.list}>
      {chats.map((chat) => (
        <ChatListItem
          key={chat.id}
          chat={chat}
          isActive={chat.id === activeChatId}
          onClick={() => onSelectChat(chat.id)}
        />
      ))}
    </div>
  );
}
