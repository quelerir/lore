import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Menu, Search, X } from "lucide-react";
import styles from "./ChatHeader.module.css";

interface ChatHeaderProps {
  title: string;
  onOpenSidebar: () => void;
  searchQuery: string;
  searchPosition: number;
  searchTotal: number;
  onSearchQueryChange: (value: string) => void;
  onSearchNext: () => void;
  onSearchPrevious: () => void;
  onSearchClear: () => void;
}

export default function ChatHeader({
  title,
  onOpenSidebar,
  searchQuery,
  searchPosition,
  searchTotal,
  onSearchQueryChange,
  onSearchNext,
  onSearchPrevious,
  onSearchClear,
}: ChatHeaderProps) {
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchQuery.trim()) {
      setIsSearchOpen(true);
    }
  }, [searchQuery]);

  useEffect(() => {
    if (!isSearchOpen) return;
    inputRef.current?.focus();
  }, [isSearchOpen]);

  const handleSearchClose = () => {
    setIsSearchOpen(false);
    onSearchClear();
  };

  return (
    <header className={styles.header}>
      <button
        className={styles.menuButton}
        onClick={onOpenSidebar}
        type="button"
        aria-label="Открыть список чатов"
      >
        <Menu size={18} />
      </button>
      <h2 className={styles.title}>{title}</h2>
      <div className={styles.searchWrap}>
        {!isSearchOpen ? (
          <button
            className={styles.searchToggle}
            type="button"
            onClick={() => setIsSearchOpen(true)}
            aria-label="Открыть поиск по сообщениям"
          >
            <Search size={18} />
          </button>
        ) : (
          <div className={styles.searchShell}>
            <div className={styles.searchField}>
              <Search size={18} className={styles.searchIcon} />
              <input
                ref={inputRef}
                className={styles.searchInput}
                type="text"
                value={searchQuery}
                onChange={(event) => onSearchQueryChange(event.target.value)}
                placeholder="Поиск"
                aria-label="Поиск"
              />
            </div>
            <div className={styles.searchMeta}>
              <span className={styles.searchCount}>
                {searchTotal > 0 ? `${searchPosition} из ${searchTotal}` : "0 из 0"}
              </span>
              <button
                className={styles.searchButton}
                type="button"
                onClick={onSearchPrevious}
                disabled={searchTotal === 0}
                aria-label="Предыдущее совпадение"
              >
                <ChevronUp size={18} />
              </button>
              <button
                className={styles.searchButton}
                type="button"
                onClick={onSearchNext}
                disabled={searchTotal === 0}
                aria-label="Следующее совпадение"
              >
                <ChevronDown size={18} />
              </button>
              <button
                className={styles.searchClose}
                type="button"
                onClick={handleSearchClose}
                aria-label="Закрыть поиск"
              >
                <X size={18} />
              </button>
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
