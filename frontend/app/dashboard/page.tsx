import DashboardClient from "./DashboardClient";
import { Suspense } from "react";

export default function DashboardPage() {
  return (
    <Suspense fallback={<div className="p-8 text-ink-500">加载 dashboard...</div>}>
      <DashboardClient />
    </Suspense>
  );
}
