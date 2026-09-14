import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NHR Legal AI",
  description: "Türk hukuku için kaynaklı araştırma ve yapay zekâ asistanı",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  );
}
