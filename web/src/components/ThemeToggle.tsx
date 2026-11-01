import { Moon, Sun } from "lucide-react";
import { useTheme } from "./ThemeContext";

export const ThemeToggle = ({ className = "" }: { className?: string }) => {
  const { theme, toggle } = useTheme();
  return (
    <button
      onClick={toggle}
      aria-label="Tema değiştir"
      className={`relative h-10 w-10 rounded-lg hover:bg-secondary flex items-center justify-center transition ${className}`}
    >
      {theme === "light" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
    </button>
  );
};
