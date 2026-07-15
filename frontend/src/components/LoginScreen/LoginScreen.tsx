import { LogIn } from "lucide-react";
import styles from "./LoginScreen.module.css";

interface LoginScreenProps {
  onLogin: () => void;
  isBusy: boolean;
  error: string | null;
}

export default function LoginScreen({ onLogin, isBusy, error }: LoginScreenProps) {
  return (
    <div className={styles.screen}>
      <div className={styles.card}>
        <h1 className={styles.title}>Lore</h1>
        <p className={styles.text}>
          Войдите через authentik, чтобы продолжить работу с чатом.
        </p>
        <button
          className={styles.button}
          onClick={onLogin}
          type="button"
          disabled={isBusy}
        >
          <LogIn size={18} />
          <span>{isBusy ? "Ожидание входа…" : "Войти через authentik"}</span>
        </button>
        {error ? <p className={styles.error}>{error}</p> : null}
      </div>
    </div>
  );
}
