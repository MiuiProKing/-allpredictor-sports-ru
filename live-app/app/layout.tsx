import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AllPredictor Sports Live — матчи и понятный разбор",
  description:
    "Реальное расписание спортивных матчей, прозрачная аналитическая оценка и понятная инструкция перед переходом на сайт ставок.",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
