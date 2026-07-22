"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSliceStore } from "@/stores/sliceStore";

const UNIVERSES = ["SPY", "QQQ", "IWM", "GLD", "IAU", "SLV"];
const DOMAINS = ["price", "position", "flow", "otc", "macro", "volatility", "quality"];
const SOURCES = ["yfinance", "fred", "cftc", "finra", "sec", "cboe", "etf_issuer"];
const FREQUENCIES = ["daily", "weekly", "monthly", "quarterly", "event"];
const STATES = [
  "LOW_EXTREME", "LOW", "NEUTRAL", "HIGH", "HIGH_EXTREME",
  "MISSING", "STALE", "INFERRED_AVAILABILITY",
];

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details open style={{ borderBottom: "1px solid var(--border)", padding: "0.5rem 0" }}>
      <summary
        style={{
          fontSize: "11px",
          fontWeight: 600,
          letterSpacing: "0.05em",
          textTransform: "uppercase",
          color: "var(--muted)",
          cursor: "pointer",
          padding: "0.25rem 0.5rem",
        }}
      >
        {title}
      </summary>
      <div style={{ padding: "0.5rem" }}>{children}</div>
    </details>
  );
}

function MultiChips({
  options,
  selected,
  onChange,
}: {
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem" }}>
      {options.map((opt) => {
        const isOn = selected.includes(opt);
        return (
          <button
            key={opt}
            type="button"
            onClick={() => {
              if (isOn) onChange(selected.filter((s) => s !== opt));
              else onChange([...selected, opt]);
            }}
            style={{
              fontSize: "11px",
              padding: "0.2rem 0.5rem",
              border: "1px solid " + (isOn ? "var(--accent)" : "var(--border)"),
              borderRadius: "999px",
              background: isOn ? "var(--accent)" : "white",
              color: isOn ? "white" : "inherit",
              cursor: "pointer",
            }}
          >
            {opt}
          </button>
        );
      })}
    </div>
  );
}

export function FilterRail() {
  const router = useRouter();
  const params = useSearchParams();
  const slice = useSliceStore();

  // Hydrate from URL on mount
  React.useEffect(() => {
    const u = params.get("universe")?.split(",").filter(Boolean) ?? [];
    const d = params.get("domains")?.split(",").filter(Boolean) ?? [];
    const s = params.get("sources")?.split(",").filter(Boolean) ?? [];
    const f = params.get("frequencies")?.split(",").filter(Boolean) ?? [];
    const st = params.get("states")?.split(",").filter(Boolean) ?? [];
    if (u.length) slice.setSymbols(u);
    if (d.length) slice.setDomains?.(d);
    if (s.length) slice.setSources?.(s);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync to URL whenever filters change
  const syncUrl = React.useCallback(
    (next: { universe?: string[]; domains?: string[]; sources?: string[]; frequencies?: string[]; states?: string[] }) => {
      const url = new URL(window.location.href);
      if (next.universe) url.searchParams.set("universe", next.universe.join(","));
      if (next.domains) url.searchParams.set("domains", next.domains.join(","));
      if (next.sources) url.searchParams.set("sources", next.sources.join(","));
      if (next.frequencies) url.searchParams.set("frequencies", next.frequencies.join(","));
      if (next.states) url.searchParams.set("states", next.states.join(","));
      router.replace(url.pathname + "?" + url.searchParams.toString());
    },
    [router]
  );

  return (
    <aside
      style={{
        width: "260px",
        borderRight: "1px solid var(--border)",
        background: "#fafafa",
        flexShrink: 0,
        overflowY: "auto",
        maxHeight: "calc(100vh - 56px)",
      }}
    >
      <Group title="Context">
        <div style={{ display: "grid", gap: "0.5rem", fontSize: "12px" }}>
          <label>
            Decision Clock
            <select
              value={slice.decisionClock}
              onChange={(e) => slice.setDecisionClock(e.target.value as "1605_ET" | "1805_ET")}
              style={{ width: "100%", padding: "0.25rem" }}
            >
              <option value="1605_ET">16:05 ET (盘中)</option>
              <option value="1805_ET">18:05 ET (收盘后)</option>
            </select>
          </label>
        </div>
      </Group>

      <Group title="Universe">
        <MultiChips
          options={UNIVERSES}
          selected={slice.selectedSymbols}
          onChange={(next) => {
            slice.setSymbols(next);
            syncUrl({ universe: next });
          }}
        />
      </Group>

      <Group title="Data">
        <div style={{ display: "grid", gap: "0.5rem" }}>
          <div>
            <div style={{ fontSize: "11px", color: "var(--muted)", marginBottom: "0.25rem" }}>Domains</div>
            <MultiChips
              options={DOMAINS}
              selected={slice.selectedDomains ?? []}
              onChange={(next) => {
                slice.setDomains?.(next);
                syncUrl({ domains: next });
              }}
            />
          </div>
          <div>
            <div style={{ fontSize: "11px", color: "var(--muted)", marginBottom: "0.25rem" }}>Sources</div>
            <MultiChips
              options={SOURCES}
              selected={slice.selectedSources ?? []}
              onChange={(next) => {
                slice.setSources?.(next);
                syncUrl({ sources: next });
              }}
            />
          </div>
          <div>
            <div style={{ fontSize: "11px", color: "var(--muted)", marginBottom: "0.25rem" }}>Frequencies</div>
            <MultiChips
              options={FREQUENCIES}
              selected={slice.selectedFrequencies ?? []}
              onChange={(next) => {
                slice.setFrequencies?.(next);
                syncUrl({ frequencies: next });
              }}
            />
          </div>
        </div>
      </Group>

      <Group title="Quality">
        <MultiChips
          options={STATES}
          selected={slice.selectedStates}
          onChange={(next) => {
            slice.setStates?.(next);
            syncUrl({ states: next });
          }}
        />
        <label style={{ display: "block", marginTop: "0.5rem", fontSize: "12px" }}>
          <input
            type="checkbox"
            checked={slice.includeStale}
            onChange={(e) => slice.setIncludeStale?.(e.target.checked)}
          />{" "}
          Include Stale
        </label>
      </Group>

      <Group title="Analysis">
        <label style={{ display: "block", fontSize: "12px" }}>
          Date start
          <input
            type="date"
            value={slice.dateRange.start}
            onChange={(e) => slice.setDateRange?.({ ...slice.dateRange, start: e.target.value })}
            style={{ width: "100%", padding: "0.25rem" }}
          />
        </label>
        <label style={{ display: "block", fontSize: "12px", marginTop: "0.5rem" }}>
          Date end
          <input
            type="date"
            value={slice.dateRange.end}
            onChange={(e) => slice.setDateRange?.({ ...slice.dateRange, end: e.target.value })}
            style={{ width: "100%", padding: "0.25rem" }}
          />
        </label>
      </Group>
    </aside>
  );
}
