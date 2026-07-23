import type { Metadata } from "next";
import { Providers } from "./providers";
import { Sidebar } from "../components/Sidebar";
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
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 overflow-auto">
              <div className="max-w-7xl mx-auto p-4 lg:p-6">{children}</div>
            </main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
