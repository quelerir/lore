import { useEffect, useState } from "react";
import type { AuthUser } from "./auth/authClient";
import { useAuth } from "./auth/useAuth";
import ChainlitRuntimeProvider from "./chat/ChainlitRuntimeProvider";
import { setOn401 } from "./chat/chainlitClient";
import ChatComposer from "./components/ChatComposer/ChatComposer";
import ChatHeader from "./components/ChatHeader/ChatHeader";
import LoginScreen from "./components/LoginScreen/LoginScreen";
import MessageList from "./components/MessageList/MessageList";
import Sidebar from "./components/Sidebar/Sidebar";
import styles from "./App.module.css";

function AppContent({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);

  return (
    <div className={styles.shell}>
      <div className={styles.frame}>
        <Sidebar
          chats={[]}
          activeChatId={null}
          isMobileOpen={isMobileSidebarOpen}
          user={user}
          onLogout={onLogout}
          onSelectChat={() => {}}
          onRenameChat={() => {}}
          onDeleteChat={() => {}}
          onCreateChat={() => {}}
          onCloseMobileMenu={() => setIsMobileSidebarOpen(false)}
        />

        <main className={styles.content}>
          <ChatHeader title="Lore" onOpenSidebar={() => setIsMobileSidebarOpen(true)} />

          <MessageList />
          <p className={styles.disclaimer}>
            Lore может допускать ошибки. Рекомендуем проверять важную информацию.
          </p>
          <ChatComposer />
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const { state, login, logout, invalidate } = useAuth();
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);

  useEffect(() => {
    setOn401(invalidate);
  }, [invalidate]);

  if (state.status === "loading") {
    return <div className={styles.authLoading}>Загрузка…</div>;
  }

  if (state.status === "anonymous") {
    return (
      <LoginScreen
        onLogin={() => void login()}
        isBusy={state.isBusy}
        error={state.error}
      />
    );
  }

  return (
    <ChainlitRuntimeProvider
      activeThreadId={activeThreadId}
      onServerThreadId={setActiveThreadId}
    >
      <AppContent user={state.user} onLogout={() => void logout()} />
    </ChainlitRuntimeProvider>
  );
}
