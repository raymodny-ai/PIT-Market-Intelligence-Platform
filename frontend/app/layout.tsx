import type { Metadata } from "next";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "PIT Market Intelligence",
  description:
    "Auditable point-in-time data warehouse with evidence-traced LLM analysis.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-ink-50 text-ink-900 antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
