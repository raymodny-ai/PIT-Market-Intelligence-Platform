// formatting helpers (PIT-aware) — display PIT metadata safely.

import type { QualityStatus } from "../types/api";

export const QUALITY_PALETTE: Record<QualityStatus, { bg: string; text: string; dot: string; label_zh: string }> = {
  VALID:                  { bg: "bg-emerald-50", text: "text-emerald-700", dot: "bg-emerald-500", label_zh: "有效" },
  DEGRADED:               { bg: "bg-amber-50",   text: "text-amber-700",   dot: "bg-amber-500",   label_zh: "降级" },
  STALE:                  { bg: "bg-amber-100",  text: "text-amber-800",   dot: "bg-amber-600",   label_zh: "陈旧" },
  PARTIAL:                { bg: "bg-yellow-50",  text: "text-yellow-700",  dot: "bg-yellow-500",  label_zh: "部分" },
  REJECTED:               { bg: "bg-rose-50",    text: "text-rose-700",    dot: "bg-rose-500",    label_zh: "拒绝" },
  INFERRED_AVAILABILITY:  { bg: "bg-violet-50",  text: "text-violet-700",  dot: "bg-violet-500",  label_zh: "推断可得" },
  SOURCE_FAILED:          { bg: "bg-red-50",     text: "text-red-700",     dot: "bg-red-500",     label_zh: "源失败" },
  SOURCE_THROTTLED:       { bg: "bg-orange-50",  text: "text-orange-700",  dot: "bg-orange-500",  label_zh: "限流" },
  EMPTY_RESPONSE:         { bg: "bg-gray-50",    text: "text-gray-600",    dot: "bg-gray-400",    label_zh: "空响应" },
};

export function qualityPill(status: QualityStatus, compact = false) {
  const p = QUALITY_PALETTE[status];
  return {
    className: `quality-pill ${p.bg} ${p.text}`,
    label: compact ? status : p.label_zh,
    dotClass: p.dot,
  };
}

export function formatNumber(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(digits) + "M";
  if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(digits) + "k";
  if (Math.abs(v) < 0.01 && v !== 0) return v.toExponential(2);
  return v.toFixed(digits);
}

export function formatPercent(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return (v * 100).toFixed(digits) + "%";
}

export function formatZScore(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export function formatTimestamp(iso: string | undefined | null, withTz = true): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    // Always render in UTC to keep SSR and CSR identical (server and
    // browser often disagree on local TZ). Label the TZ explicitly so the
    // caller isn't surprised.
    const yyyy = d.getUTCFullYear();
    const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const mi = String(d.getUTCMinutes()).padStart(2, "0");
    const ss = String(d.getUTCSeconds()).padStart(2, "0");
    return withTz ? `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss} UTC` : `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`;
  } catch {
    return iso;
  }
}

// Compact form: "MM-DD HH:MM UTC" — for mobile / narrow viewports where
// the full "YYYY-MM-DD HH:MM:SS UTC" doesn't fit. Year is dropped (a panel
// from last year is an edge case, and the user can hover/click for full).
export function formatTimestampShort(iso: string | undefined | null, withTz = true): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const mi = String(d.getUTCMinutes()).padStart(2, "0");
    return withTz ? `${mm}-${dd} ${hh}:${mi} UTC` : `${mm}-${dd} ${hh}:${mi}`;
  } catch {
    return iso;
  }
}

// formatTimestampUtc — always renders in UTC, never local TZ. Use this for
// SSR-rendered timestamps to avoid React hydration mismatches (server vs
// browser locale).
export function formatTimestampUtc(iso: string | undefined | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const yyyy = d.getUTCFullYear();
    const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const mi = String(d.getUTCMinutes()).padStart(2, "0");
    const ss = String(d.getUTCSeconds()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}Z`;
  } catch {
    return iso;
  }
}



export function dataAgeHuman(iso: string | undefined, now = new Date()): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const diffMs = now.getTime() - d.getTime();
  if (diffMs < 0) return "未来";
  const min = Math.floor(diffMs / 60000);
  if (min < 60) return `${min} 分钟`;
  const hr = Math.floor(min / 60);
  if (hr < 48) return `${hr} 小时`;
  const days = Math.floor(hr / 24);
  return `${days} 天`;
}

export function zScoreColor(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "#e2e8f0";
  // Blue (-3) → white (0) → red (+3), diverging
  const t = Math.max(-3, Math.min(3, v));
  if (t < 0) {
    const a = (-t) / 3; // 0..1
    return `rgba(37, 99, 235, ${0.15 + a * 0.7})`;
  }
  const a = t / 3;
  return `rgba(220, 38, 38, ${0.15 + a * 0.7})`;
}
