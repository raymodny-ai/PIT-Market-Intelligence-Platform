/**
 * Component test for /panels/new — the build-panel form page.
 *
 * Covers the happy path and the validation error path. We mock the
 * fetch layer (so the test doesn't need a running backend) and the
 * Next.js router (so the success path's navigation doesn't throw).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import NewPanelPage from "../page";

// ─────────────────────────────────────────────────────────────────────
// Mocks — must come before the component import (vitest hoists vi.mock)
// ─────────────────────────────────────────────────────────────────────

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn(), back: vi.fn() }),
}));

// Stub fetch — the page calls fetchPanelsList, fetchInstruments, buildPanel.
// Handlers are checked in insertion order; the most specific match should
// come first (e.g. /v1/panels/build must precede /v1/panels).
const originalFetch = global.fetch;
function mockFetch(handlers: Array<[string, () => unknown]>) {
  global.fetch = vi.fn((input: any) => {
    const url = typeof input === "string" ? input : input.url;
    for (const [match, build] of handlers) {
      if (url.includes(match)) {
        const body = build();
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(body),
        });
      }
    }
    return Promise.reject(new Error(`unmocked URL: ${url}`));
  }) as any;
}

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <NewPanelPage />
    </QueryClientProvider>,
  );
}

// fetchInstruments() in lib/api.ts calls /v1/instruments/registry and
// extracts Object.values(r.instruments). So the wire format is the
// wrapped { instruments: { ... } } shape, not a bare array.
const INSTRUMENTS_PAYLOAD = {
  instruments: {
    SPY: { canonical_symbol: "SPY", asset_class: "equity", display_name_zh: "SPDR S&P 500" },
    QQQ: { canonical_symbol: "QQQ", asset_class: "equity", display_name_zh: "Invesco QQQ" },
    GLD: { canonical_symbol: "GLD", asset_class: "commodity", display_name_zh: "SPDR Gold" },
    SLV: { canonical_symbol: "SLV", asset_class: "commodity", display_name_zh: "iShares Silver" },
  },
};

const PANELS_LIST_RESPONSE = {
  panels: [],
  count: 0,
};

// ─────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────

describe("/panels/new (build panel form)", () => {
  beforeEach(() => {
    mockPush.mockClear();
    mockFetch([
      ["/v1/instruments/registry", () => INSTRUMENTS_PAYLOAD],
      ["/v1/panels", () => PANELS_LIST_RESPONSE],
    ]);
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders the page title, datetime input, clock picker, and universe chips", async () => {
    renderPage();

    expect(screen.getByText("新建 PIT Panel")).toBeInTheDocument();
    expect(document.querySelector('input[type="datetime-local"]')).toBeTruthy();
    expect(screen.getByRole("button", { name: "1605_ET" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1805_ET" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /构建 panel/ })).toBeInTheDocument();

    // Universe chips render only after the instruments query resolves.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "GLD" })).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "SPY" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "QQQ" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "SLV" })).toBeInTheDocument();
  });

  it("fills in a default decision_time on mount (the next ET decision clock)", async () => {
    renderPage();

    await waitFor(() => {
      const input = document.querySelector(
        'input[type="datetime-local"]',
      ) as HTMLInputElement;
      expect(input.value).not.toBe("");
      // YYYY-MM-DDTHH:MM
      expect(input.value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    });
  });

  it("submits the form, calls POST /v1/panels/build, and navigates on success", async () => {
    mockFetch([
      ["/v1/instruments/registry", () => INSTRUMENTS_PAYLOAD],
      // /v1/panels/build must come BEFORE /v1/panels — it's a substring
      ["/v1/panels/build", () => ({
        panel_id: "cli-20241231T180500Z-SPY-QQQ-GLD-SLV",
        decision_time_utc: "2024-12-31T18:05:00+00:00",
        decision_clock: "1805_ET",
        universe: ["SPY", "QQQ", "GLD", "SLV"],
        registry_hash: "abc",
        feature_version: "features.v1.0",
        metric_registry_version: "metrics.v1.0",
        instrument_registry_version: "registry.v1.0",
      })],
      ["/v1/panels", () => PANELS_LIST_RESPONSE],
    ]);

    const user = userEvent.setup();
    renderPage();

    // Wait for universe chips to be ready (instruments query resolved).
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "GLD" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /构建 panel/ }));

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith(
        "/panels/cli-20241231T180500Z-SPY-QQQ-GLD-SLV",
      );
    });

    const calls = (global.fetch as any).mock.calls.filter(
      (c: any[]) => String(c[0]).includes("/v1/panels/build"),
    );
    expect(calls.length).toBeGreaterThan(0);
    const body = JSON.parse(calls[0][1].body);
    expect(body.universe).toEqual(["SPY", "QQQ", "GLD", "SLV"]);
    expect(body.decision_clock).toBe("1805_ET");
    expect(body.decision_time).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
  });

  it("shows an error message when the server returns a non-OK build response", async () => {
    (global.fetch as any) = vi.fn((input: any) => {
      const url = String(input);
      if (url.includes("/v1/panels/build")) {
        return Promise.resolve({
          ok: false,
          status: 500,
          statusText: "Internal Server Error",
          json: () => Promise.reject(new Error("not json")),
        });
      }
      if (url.includes("/v1/instruments/registry")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(INSTRUMENTS_PAYLOAD),
        });
      }
      if (url.includes("/v1/panels")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(PANELS_LIST_RESPONSE),
        });
      }
      return Promise.reject(new Error(`unmocked: ${url}`));
    });

    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "GLD" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /构建 panel/ }));

    await waitFor(() => {
      // postJson() returns null on !ok, so the page surfaces
      // "后端无响应 — 检查 FastAPI 是否在运行".
      expect(screen.getByText(/后端无响应/)).toBeInTheDocument();
    });

    expect(mockPush).not.toHaveBeenCalled();
  });

  it("disables the submit button when the universe becomes empty", async () => {
    mockFetch([
      ["/v1/instruments/registry", () => INSTRUMENTS_PAYLOAD],
      ["/v1/panels", () => PANELS_LIST_RESPONSE],
    ]);
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "GLD" })).toBeInTheDocument();
    });

    // Default universe is [SPY, QQQ, GLD, SLV] — remove all 4.
    for (const sym of ["SPY", "QQQ", "GLD", "SLV"]) {
      await user.click(screen.getByRole("button", { name: sym }));
    }

    const submitBtn = screen.getByRole("button", { name: /构建 panel/ });
    expect(submitBtn).toBeDisabled();
  });

  it("shows a panel_id preview when decision_time + universe are both set", async () => {
    mockFetch([
      ["/v1/instruments/registry", () => INSTRUMENTS_PAYLOAD],
      ["/v1/panels", () => PANELS_LIST_RESPONSE],
    ]);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("预览 panel_id")).toBeInTheDocument();
    });

    // Preview should look like 'cli-YYYYMMDDTHHMMSSZ-SPY-QQQ-GLD-SLV'
    const previewEl = screen.getByText(/cli-\d{8}T\d{6}Z-/);
    expect(previewEl.textContent).toMatch(
      /cli-\d{8}T\d{6}Z-SPY-QQQ-GLD-SLV/,
    );
  });

  it("switches the decision_clock when a clock button is clicked", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "GLD" })).toBeInTheDocument();
    });

    // Default is 1805_ET; click 1605_ET and verify the active class moves.
    const btn1605 = screen.getByRole("button", { name: "1605_ET" });
    const btn1805 = screen.getByRole("button", { name: "1805_ET" });

    await user.click(btn1605);
    expect(btn1605.className).toContain("border-brand-500");
    expect(btn1805.className).not.toContain("border-brand-500");
  });
});