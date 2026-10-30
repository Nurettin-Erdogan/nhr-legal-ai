import { createContext, useContext } from "react";

export type Theme = "light" | "dark";

export type ThemeContextValue = { theme: Theme; toggle: () => void; setTheme: (t: Theme) => void };

export const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export const useTheme = () => {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
};
