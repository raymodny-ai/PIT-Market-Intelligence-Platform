/**
 * Tests for the buildPanel() API helper in lib/api.ts.
 *
 * buildPanel() now returns a tri-state BuildPanelResult (commit fa5af8c+
 * post-P0 follow-up):
 *   { ok: true, data, status }
 *   { ok: false, status, detail }   // detail is human-readable, never null
 *
 * Covers the contract from both happy and unhappy paths.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { buildPanel } from "../api";

describe("buildPanel()", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn() as any;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("sends POST /v1/panels/build with the right body shape", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      status: 201,
      text: () =>
        Promise.resolve(
          JSON.stringify({
            panel_id: "cli-20241231T180500Z-SPY-QQQ",
            decision_time_utc: "2024-12-31T18:05:00+00:00",
            decision_clock: "1805_ET",
            universe: ["SPY", "QQQ"],
            registry_hash: "x",
            feature_version: "features.v1.0",
            metric_registry_version: "metrics.v1.0",
            instrument_registry_version: "registry.v1.0",
          }),
        ),
    });

    const r = await buildPanel({
      decision_time: "2024-12-31T18:05:00Z",
      universe: ["SPY", "QQQ"],
    });

    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.status).toBe(201);
      expect(r.data.panel_id).toBe("cli-20241231T180500Z-SPY-QQQ");
    }
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/v1\/panels\/build$/),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
        body: expect.stringContaining('"decision_clock":"1805_ET"'),
      }),
    );
  });

  it("defaults decision_clock to 1805_ET when omitted", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      status: 201,
      text: () => Promise.resolve("{}"),
    });

    await buildPanel({ decision_time: "2024-12-31T18:05:00Z", universe: ["SPY"] });

    const body = JSON.parse((global.fetch as any).mock.calls[0][1].body);
    expect(body.decision_clock).toBe("1805_ET");
  });

  it("respects explicit decision_clock=1605_ET", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      status: 201,
      text: () => Promise.resolve("{}"),
    });

    await buildPanel({
      decision_time: "2024-12-31T16:05:00Z",
      universe: ["SPY"],
      decision_clock: "1605_ET",
    });

    const body = JSON.parse((global.fetch as any).mock.calls[0][1].body);
    expect(body.decision_clock).toBe("1605_ET");
  });

  it("returns ok:false with FastAPI detail string on 400 unknown symbol", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 400,
      text: () =>
        Promise.resolve(
          JSON.stringify({ detail: "unknown canonical_symbol(s): ['FAKE']" }),
        ),
    });

    const r = await buildPanel({
      decision_time: "2024-12-31T18:05:00Z",
      universe: ["FAKE"],
    });

    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.status).toBe(400);
      expect(r.detail).toContain("unknown canonical_symbol");
      expect(r.detail).toContain("FAKE");
    }
  });

  it("formats Pydantic 422 detail arrays into a single readable string", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 422,
      text: () =>
        Promise.resolve(
          JSON.stringify({
            detail: [
              {
                type: "value_error",
                loc: ["body", "decision_clock"],
                msg: "Value error, decision_clock must be 1605_ET or 1805_ET",
              },
              {
                type: "missing",
                loc: ["body", "decision_time"],
                msg: "field required",
              },
            ],
          }),
        ),
    });

    const r = await buildPanel({
      decision_time: "2024-12-31T18:05:00Z",
      universe: ["SPY"],
      decision_clock: "9999" as any,
    });

    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.status).toBe(422);
      // Should include both field paths and their messages.
      expect(r.detail).toContain("body.decision_clock");
      expect(r.detail).toContain("body.decision_time");
      expect(r.detail).toContain("1605_ET or 1805_ET");
      expect(r.detail).toContain("field required");
    }
  });

  it("falls back to raw body text when 5xx returns non-JSON", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: () => Promise.resolve("Internal Server Error (nginx)"),
    });

    const r = await buildPanel({
      decision_time: "2024-12-31T18:05:00Z",
      universe: ["SPY"],
    });

    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.status).toBe(500);
      expect(r.detail).toContain("500");
      expect(r.detail).toContain("nginx");
    }
  });

  it("returns ok:false with status 0 + network error on fetch throw", async () => {
    (global.fetch as any).mockRejectedValueOnce(new Error("Failed to fetch"));

    const r = await buildPanel({
      decision_time: "2024-12-31T18:05:00Z",
      universe: ["SPY"],
    });

    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.status).toBe(0);
      expect(r.detail).toContain("网络错误");
      expect(r.detail).toContain("Failed to fetch");
    }
  });
});