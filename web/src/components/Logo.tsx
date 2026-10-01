import { Scale } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  className?: string;
  variant?: "light" | "dark";
  showText?: boolean;
}

export const Logo = ({ className, variant = "dark", showText = true }: Props) => {
  const textColor = variant === "light" ? "text-primary-foreground" : "text-foreground";
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary">
        <Scale className="h-5 w-5 text-primary-foreground" strokeWidth={2.2} />
      </div>
      {showText && (
        <span className={cn("text-lg font-bold tracking-tight", textColor)}>
          Juris<span className="text-primary">AI</span>
        </span>
      )}
    </div>
  );
};
