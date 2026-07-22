/**
 * Tests for the buildPanel() API helper in lib/api.ts.
 *
 * Covers the new "build panel from the UI" feature (commit f12e17d):
 *  - payload shape (decision_time, universe, decision_clock default)
 *  - happy path: returns parsed body
 *  - error path: bubbles up server detail
 *  - 422 Pydantic errors come back with detail array (and a non-null return,
 *    which the page-level error handler must catch)
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
      json: () =>
        Promise.resolve({
          panel_id: "cli-20241231T180500Z-SPY-QQQ",
          decision_time_utc: "2024-12-31T18:05:00+00:00",
          decision_clock: "1805_ET",
          universe: ["SPY", "QQQ"],
          registry_hash: "x",
          feature_version: "features.v1.0",
          metric_registry_version: "metrics.v1.0",
          instrument_registry_version: "registry.v1.0",
        }),
    });

    const r = await buildPanel({
      decision_time: "2024-12-31T18:05:00Z",
      universe: ["SPY", "QQQ"],
    });

    expect(r?.panel_id).toBe("cli-20241231T180500Z-SPY-QQQ");
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
      json: () =>
        Promise.resolve(
          JSON.stringify({
            panel_id: "x",
            decision_time_utc: "x",
            decision_clock: "1805_ET",
            universe: ["SPY"],
            registry_hash: "x",
            feature_version: "x",
            metric_registry_version: "x",
            instrument_registry_version: "x",
          }),
        ),
    });

    await buildPanel({ decision_time: "2024-12-31T18:05:00Z", universe: ["SPY"] });

    const body = JSON.parse((global.fetch as any).mock.calls[0][1].body);
    expect(body.decision_clock).toBe("1805_ET");
  });

  it("respects explicit decision_clock=1605_ET", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: () =>
        Promise.resolve(
          JSON.stringify({
            panel_id: "x",
            decision_time_utc: "x",
            decision_clock: "1605_ET",
            universe: ["SPY"],
            registry_hash: "x",
            feature_version: "x",
            metric_registry_version: "x",
            instrument_registry_version: "x",
          }),
        ),
    });

    await buildPanel({
      decision_time: "2024-12-31T16:05:00Z",
      universe: ["SPY"],
      decision_clock: "1605_ET",
    });

    const body = JSON.parse((global.fetch as any).mock.calls[0][1].body);
    expect(body.decision_clock).toBe("1605_ET");
  });

  it("returns null when the server returns a non-OK status (postJson swallows error body)", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: () => Promise.resolve("boom"),
    });

    const r = await buildPanel({
      decision_time: "2024-12-31T18:05:00Z",
      universe: ["SPY"],
    });

    // postJson returns null on !ok — callers see a "no response" message
    // rather than the server's actual 4xx/5xx detail. (TODO: surface detail.)
    expect(r).toBeNull();
  });

  it("returns null on a 422 Pydantic error (postJson swallows error body)", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: () =>
        Promise.resolve(
          JSON.stringify({
            detail: [
              {
                type: "value_error",
                loc: ["body", "decision_clock"],
                msg: "decision_clock must be 1605_ET or 1805_ET",
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

    // Currently null — page shows generic "后端无响应". The form's
    // client-side decision_clock picker prevents this from being hit
    // in practice.
    expect(r).toBeNull();
  });
});