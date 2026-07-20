import { useEffect, useState, type CSSProperties } from "react";
import { getCurrentUser, loginWithPopup, logout, type AuthUser } from "./authClient";

// Shared auth control (user badge + login/logout). The session is one backend
// cookie, so this reflects the same login across the chat and the FileViewer.
const buttonStyle: CSSProperties = {
  border: "1px solid rgba(255,255,255,0.2)",
  background: "transparent",
  color: "inherit",
  borderRadius: 8,
  padding: "4px 10px",
  fontSize: 13,
  cursor: "pointer",
};

export default function AuthBar() {
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    void getCurrentUser().then(setUser);
  }, []);

  const handleLogin = async () => {
    try {
      const loggedIn = await loginWithPopup();
      setUser(loggedIn);
      window.location.reload();
    } catch {
      // popup closed / timed out
    }
  };

  const handleLogout = async () => {
    await logout();
    window.location.reload();
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "10px 6px",
        marginTop: "auto",
      }}
    >
      {user ? (
        <>
          <span
            title={user.identifier}
            style={{
              flex: 1,
              minWidth: 0,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              fontSize: 13,
              opacity: 0.85,
            }}
          >
            {user.identifier}
          </span>
          <button type="button" style={buttonStyle} onClick={() => void handleLogout()}>
            Выйти
          </button>
        </>
      ) : (
        <button type="button" style={buttonStyle} onClick={() => void handleLogin()}>
          Войти
        </button>
      )}
    </div>
  );
}
