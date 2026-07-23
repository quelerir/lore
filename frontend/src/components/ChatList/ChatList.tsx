import type { Chat } from "../../types/chat";
import { getChatGroupMeta } from "../../chat/chatDates";
import ChatListItem from "../ChatListItem/ChatListItem";
import styles from "./ChatList.module.css";

interface ChatListProps {
  chats: Chat[];
  activeChatId: string | null;
  onSelectChat: (chatId: string) => void;
  onRenameChat: (chatId: string) => void;
  onDeleteChat: (chatId: string) => void;
}

type ChatGroup = {
  label: string;
  chats: Chat[];
  order: number;
};

export default function ChatList({
  chats,
  activeChatId,
  onSelectChat,
  onRenameChat,
  onDeleteChat,
}: ChatListProps) {
  const groups = chats.reduce<Map<string, ChatGroup>>((accumulator, chat) => {
    const groupMeta = getChatGroupMeta(chat.createdAt);
    const existingGroup = accumulator.get(groupMeta.label);

    if (existingGroup) {
      existingGroup.chats.push(chat);
      return accumulator;
    }

    accumulator.set(groupMeta.label, {
      label: groupMeta.label,
      chats: [chat],
      order: groupMeta.order,
    });

    return accumulator;
  }, new Map());

  const sortedGroups = [...groups.values()]
    .sort((left, right) => left.order - right.order)
    .map((group) => ({
      ...group,
      chats: [...group.chats].sort(
        (left, right) =>
          new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime(),
      ),
    }));

  return (
    <div className={styles.list}>
      {sortedGroups.map((group) => (
        <section key={group.label} className={styles.group}>
          <div className={styles.groupLabel}>{group.label}</div>
          <div className={styles.groupItems}>
            {group.chats.map((chat) => (
              <ChatListItem
                key={chat.id}
                chat={chat}
                isActive={chat.id === activeChatId}
                onClick={() => onSelectChat(chat.id)}
                onRename={() => onRenameChat(chat.id)}
                onDelete={() => onDeleteChat(chat.id)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
