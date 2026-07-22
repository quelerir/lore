import { FileText } from "lucide-react";
import type { Citation } from "../../chat/citations";
import { navigateTo } from "../../router/AppRouter";
import styles from "./Citations.module.css";

interface CitationsProps {
  items: Citation[];
}

/** Заголовок карточки: путь заголовков → иначе ключ файла → иначе «Источник». */
const cardLabel = (c: Citation): string =>
  c.headingPath.length ? c.headingPath.join(" › ") : c.logicalFileKey || "Источник";

/**
 * Блок карточек-источников под ответом ассистента. Клик по карточке уводит в
 * FileViewer (`/files?...`) на конкретный чанк через роутерный navigateTo —
 * прямая SPA-навигация, без iframe/postMessage (см. дизайн-спеку citations).
 */
export default function Citations({ items }: CitationsProps) {
  if (!items.length) return null;
  return (
    <div className={styles.wrap}>
      <div className={styles.title}>Источники</div>
      <ul className={styles.list}>
        {items.map((c, i) => (
          <li key={`${c.chunkId}-${i}`}>
            <button
              type="button"
              className={styles.card}
              onClick={() => navigateTo(c.deepLink)}
              title="Открыть источник в просмотрщике файлов"
            >
              <span className={styles.head}>
                <FileText size={14} className={styles.icon} aria-hidden />
                <span className={styles.heading}>{cardLabel(c)}</span>
              </span>
              {c.previewText ? <span className={styles.preview}>{c.previewText}</span> : null}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
