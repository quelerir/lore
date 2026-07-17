import { useCallback, useEffect, useState } from "react";
import {
  getCurrentUser,
  loginWithPopup,
  logout as apiLogout,
  type AuthUser,
} from "./authClient";

export type AuthState =
  | { status: "loading" }
  | { status: "anonymous"; isBusy: boolean; error: string | null }
  | { status: "authenticated"; user: AuthUser };

export function useAuth() {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    void getCurrentUser().then((user) => {
      if (cancelled) return;
      setState(
        user
          ? { status: "authenticated", user }
          : { status: "anonymous", isBusy: false, error: null },
      );
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async () => {
    setState({ status: "anonymous", isBusy: true, error: null });
    try {
      const user = await loginWithPopup();
      setState({ status: "authenticated", user });
    } catch (error) {
      setState({
        status: "anonymous",
        isBusy: false,
        error: error instanceof Error ? error.message : "Не удалось войти.",
      });
    }
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setState({ status: "anonymous", isBusy: false, error: null });
  }, []);

  const invalidate = useCallback(() => {
    setState({
      status: "anonymous",
      isBusy: false,
      error: "Сессия истекла, войдите снова.",
    });
  }, []);

  return { state, login, logout, invalidate };
}
