/**
 * Tests for the time/quality formatting helpers in lib/formatting.ts.
 *
 * Focus: SSR/CSR determinism (UTC everywhere) + the new compact
 * formatTimestampShort() used on mobile.
 */
import { describe, it, expect } from "vitest";
import {
  formatTimestamp,
  formatTimestampShort,
  formatTimestampUtc,
  formatNumber,
  formatPercent,
  qualityPill,
} from "../formatting";

describe("formatTimestamp", () => {
  it("renders a fixed UTC string, no local TZ", () => {
    const out = formatTimestamp("2024-12-31T18:05:30Z", true);
    expect(out).toBe("2024-12-31 18:05:30 UTC");
  });

  it("drops the TZ label when withTz=false", () => {
    expect(formatTimestamp("2024-12-31T18:05:30Z", false)).toBe(
      "2024-12-31 18:05:30",
    );
  });

  it("returns — for null / undefined", () => {
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp(undefined)).toBe("—");
    expect(formatTimestamp("")).toBe("—");
  });

  it("falls back to the raw string when unparseable", () => {
    expect(formatTimestamp("not-a-date")).toBe("not-a-date");
  });
});

describe("formatTimestampShort", () => {
  it("drops the year + seconds for narrow viewports", () => {
    expect(formatTimestampShort("2024-12-31T18:05:30Z", true)).toBe(
      "12-31 18:05 UTC",
    );
  });

  it("drops the TZ label when withTz=false", () => {
    expect(formatTimestampShort("2024-12-31T18:05:30Z", false)).toBe(
      "12-31 18:05",
    );
  });

  it("returns — for null / undefined", () => {
    expect(formatTimestampShort(null)).toBe("—");
    expect(formatTimestampShort(undefined)).toBe("—");
  });

  it("is significantly shorter than the full format", () => {
    const full = formatTimestamp("2024-12-31T18:05:30Z", true);
    const short = formatTimestampShort("2024-12-31T18:05:30Z", true);
    expect(short.length).toBeLessThan(full.length);
  });
});

describe("formatTimestampUtc", () => {
  it("renders with trailing Z", () => {
    expect(formatTimestampUtc("2024-12-31T18:05:30Z")).toBe(
      "2024-12-31 18:05:30Z",
    );
  });

  it("returns — for null", () => {
    expect(formatTimestampUtc(null)).toBe("—");
  });
});

describe("formatNumber", () => {
  it("renders normal values with two decimals", () => {
    expect(formatNumber(123.456)).toBe("123.46");
  });
  it("renders millions with M suffix", () => {
    expect(formatNumber(1_500_000)).toBe("1.50M");
  });
  it("renders thousands with k suffix", () => {
    expect(formatNumber(2_300)).toBe("2.30k");
  });
  it("returns — for null / NaN", () => {
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber(NaN)).toBe("—");
  });
});

describe("formatPercent", () => {
  it("multiplies by 100 and adds %", () => {
    expect(formatPercent(0.5)).toBe("50.00%");
  });
  it("returns — for null", () => {
    expect(formatPercent(null)).toBe("—");
  });
});

describe("qualityPill", () => {
  it("renders Chinese label by default", () => {
    const p = qualityPill("VALID");
    expect(p.label).toBe("有效");
    expect(p.className).toContain("bg-emerald-50");
  });
  it("renders raw status when compact=true", () => {
    expect(qualityPill("VALID", true).label).toBe("VALID");
  });
});