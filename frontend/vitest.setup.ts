// Vitest setup: mocks for Next.js routing + global fetch.
import "@testing-library/jest-dom/vitest";
import { vi, afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Polyfill matchMedia (some Radix / shadcn primitives poke at it).
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (q: string) => ({
    matches: false,
    media: q,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// Silence React Query's DevTools "missing" warning in tests.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});