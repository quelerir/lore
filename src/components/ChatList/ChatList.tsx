import type { Chat } from "../../types/chat";
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

const parseTimeWeight = (time: string) => {
  if (time === "Только что") return 10_000;

  const match = time.match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return -1;

  const [, hours, minutes] = match;
  return Number(hours) * 60 + Number(minutes);
};

const getGroupMeta = (time: string) => {
  if (time === "Вчера") {
    return { label: "Вчера", order: 1 };
  }

  if (time === "Только что" || /^\d{1,2}:\d{2}$/.test(time)) {
    return { label: "Сегодня", order: 0 };
  }

  return { label: "Ранее", order: 2 };
};

export default function ChatList({
  chats,
  activeChatId,
  onSelectChat,
  onRenameChat,
  onDeleteChat,
}: ChatListProps) {
  const groups = chats.reduce<Map<string, ChatGroup>>((accumulator, chat) => {
    const groupMeta = getGroupMeta(chat.time);
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
        (left, right) => parseTimeWeight(right.time) - parseTimeWeight(left.time),
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
