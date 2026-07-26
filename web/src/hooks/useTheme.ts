import { useState, useEffect, useCallback } from "react";

export function useTheme() {
  const [darkMode, setDarkMode] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("darkMode") === "true";
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", darkMode);
    localStorage.setItem("darkMode", String(darkMode));
  }, [darkMode]);

  const toggle = useCallback(() => setDarkMode((prev) => !prev), []);

  return { darkMode, toggle } as const;
}
