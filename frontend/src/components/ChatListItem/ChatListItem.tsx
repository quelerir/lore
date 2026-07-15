import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Chat } from "../../types/chat";
import styles from "./ChatListItem.module.css";

interface ChatListItemProps {
  chat: Chat;
  isActive: boolean;
  onClick: () => void;
  onRename: () => void;
  onDelete: () => void;
}

export default function ChatListItem({
  chat,
  isActive,
  onClick,
  onRename,
  onDelete,
}: ChatListItemProps) {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const itemRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!itemRef.current?.contains(event.target as Node)) {
        setIsMenuOpen(false);
      }
    };

    window.addEventListener("mousedown", handlePointerDown);
    return () => window.removeEventListener("mousedown", handlePointerDown);
  }, []);

  return (
    <div ref={itemRef} className={`${styles.item} ${isActive ? styles.active : ""}`}>
      <button className={styles.main} onClick={onClick} type="button">
        <div className={styles.header}>
          <div className={styles.title}>{chat.title}</div>
        </div>
        <div className={styles.description}>{chat.description}</div>
      </button>

      <div className={`${styles.topRight} ${isMenuOpen ? styles.topRightOpen : ""}`}>
        <div className={styles.time}>{chat.time}</div>
        <button
          className={styles.menuButton}
          type="button"
          aria-label="Меню чата"
          aria-expanded={isMenuOpen}
          onClick={(event) => {
            event.stopPropagation();
            setIsMenuOpen((prev) => !prev);
          }}
        >
          <MoreHorizontal size={14} />
        </button>
      </div>

      {isMenuOpen ? (
        <div className={styles.dropdown}>
          <button
            className={styles.dropdownItem}
            type="button"
            onClick={() => {
              setIsMenuOpen(false);
              onRename();
            }}
          >
            <Pencil size={14} />
            <span>Переименовать</span>
          </button>
          <button
            className={`${styles.dropdownItem} ${styles.dropdownItemDanger}`}
            type="button"
            onClick={() => {
              setIsMenuOpen(false);
              onDelete();
            }}
          >
            <Trash2 size={14} />
            <span>Удалить</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}
