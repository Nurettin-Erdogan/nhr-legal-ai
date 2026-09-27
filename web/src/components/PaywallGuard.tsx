import { ReactNode } from "react";

interface PaywallGuardProps {
  children: ReactNode;
  requiredTier?: "starter" | "pro" | "kurumsal";
  featureName?: string;
}

// Ödeme geçici olarak devre dışı — tüm özellikler ücretsiz kullanılabilir.
export const PaywallGuard = ({ children }: PaywallGuardProps) => <>{children}</>;
