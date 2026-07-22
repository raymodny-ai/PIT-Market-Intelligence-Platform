"use client";

// ErrorBoundary — catches render errors, shows summary (PRD §错误与降级).
// Server-side errors bubble up via Next.js error.tsx convention.

import { Component, ReactNode } from "react";

interface State {
  error: Error | null;
}

interface Props {
  children: ReactNode;
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: any) {
    if (typeof console !== "undefined") {
      console.error("[ErrorBoundary]", error, info);
    }
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return this.props.fallback ? this.props.fallback(this.state.error, this.reset) : (
        <div className="m-4 p-4 bg-rose-50 border border-rose-200 rounded-md">
          <h3 className="text-sm font-semibold text-rose-800 mb-1">组件渲染失败</h3>
          <pre className="text-xs text-rose-700 whitespace-pre-wrap">{this.state.error.message}</pre>
          <button
            type="button"
            className="btn-ghost mt-2 text-xs"
            onClick={this.reset}
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
