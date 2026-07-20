// Auth against the Chainlit backend: session lives in a same-site cookie set by
// the authentik OAuth flow. Restored after the main-branch frontend dropped it.
export type AuthUser = {
  identifier: string;
  metadata?: Record<string, unknown>;
};

const baseUrl: string =
  import.meta.env.VITE_CHAINLIT_URL ?? "http://localhost:8000";

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export async function getCurrentUser(): Promise<AuthUser | null> {
  try {
    const response = await fetch(`${baseUrl}/user`, { credentials: "include" });
    if (!response.ok) return null;
    return (await response.json()) as AuthUser;
  } catch {
    return null;
  }
}

export async function loginWithPopup(timeoutMs = 60_000): Promise<AuthUser> {
  const popup = window.open(
    `${baseUrl}/auth/oauth/generic`,
    "lore-login",
    "width=480,height=720",
  );
  if (!popup) {
    throw new Error("Браузер заблокировал окно входа. Разрешите всплывающие окна.");
  }

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await sleep(1000);
    const user = await getCurrentUser();
    if (user) {
      popup.close();
      return user;
    }
    if (popup.closed) {
      throw new Error("Окно входа было закрыто до завершения входа.");
    }
  }

  popup.close();
  throw new Error("Не удалось войти: время ожидания истекло.");
}

export async function logout(): Promise<void> {
  await fetch(`${baseUrl}/logout`, { method: "POST", credentials: "include" });
}
