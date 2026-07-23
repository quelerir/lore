import { useEffect, useState } from "react";
import App from "../App";
import FilesPage from "../features/files/FilesPage";

const getCurrentPath = () => window.location.pathname || "/";

export const navigateTo = (path: string) => {
  if (window.location.pathname === path) return;
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
};

export default function AppRouter() {
  const [pathname, setPathname] = useState(getCurrentPath());

  useEffect(() => {
    const handlePopState = () => setPathname(getCurrentPath());

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    const storedTheme = window.localStorage.getItem("lore-theme");
    document.documentElement.dataset.theme = storedTheme === "dark" ? "dark" : "light";
  }, []);

  if (pathname === "/files") {
    return <FilesPage onNavigateHome={() => navigateTo("/")} />;
  }

  return <App />;
}
