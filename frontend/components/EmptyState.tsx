"use client";

// EmptyState — distinguishes "no data" vs "filtered out" (PRD §错误与降级).

import { ReactNode } from "react";

export interface EmptyStateProps {
  title?: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
  variant?: "no-data" | "filtered" | "error";
}

export function EmptyState({ title, description, icon, action, variant = "no-data" }: EmptyStateProps) {
  const defaults = {
    "no-data":   { title: "当前切片无数据",         color: "text-ink-400", icon: <DocIcon /> },
    "filtered":  { title: "质量过滤后无数据",         color: "text-amber-500", icon: <FilterIcon /> },
    "error":     { title: "加载失败",                color: "text-rose-500", icon: <WarnIcon /> },
  }[variant];

  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
      <div className={`${defaults.color} mb-3`}>{icon ?? defaults.icon}</div>
      <h3 className="text-sm font-semibold text-ink-900 mb-1">
        {title ?? defaults.title}
      </h3>
      {description && <p className="text-xs text-ink-500 max-w-md">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

function DocIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}
function FilterIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
    </svg>
  );
}
function WarnIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}
