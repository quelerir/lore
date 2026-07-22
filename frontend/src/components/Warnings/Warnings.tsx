import { AlertTriangle, XCircle } from "lucide-react";
import type { Warning } from "../../chat/warnings";
import styles from "./Warnings.module.css";

interface WarningsProps {
  items: Warning[];
}

/**
 * Чипы-предупреждения (янтарные — мягкие деградации) и баннер ошибки (красный —
 * жёсткий сбой) под ответом ассистента. Чтобы сбой не уходил в молчание.
 */
export default function Warnings({ items }: WarningsProps) {
  if (!items.length) return null;
  return (
    <div className={styles.wrap}>
      {items.map((w, i) => (
        <div key={i} className={w.level === "error" ? styles.error : styles.warning}>
          {w.level === "error" ? (
            <XCircle size={14} className={styles.icon} aria-hidden />
          ) : (
            <AlertTriangle size={14} className={styles.icon} aria-hidden />
          )}
          <span>{w.text}</span>
        </div>
      ))}
    </div>
  );
}
