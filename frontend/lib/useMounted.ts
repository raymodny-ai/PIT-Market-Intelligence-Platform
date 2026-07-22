"use client";

// useMounted — returns true only after the component has mounted on the
// client. Use this to gate any UI that depends on `Date.now()` or
// `new Date().toISOString()` so we never render time-sensitive values
// during SSR (which would mismatch the CSR hydration if hydration takes
// more than a minute/hour/day boundary).
import { useEffect, useState } from "react";

export function useMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted;
}