"use client";

// FindingCard — clickable LLM finding card.
// PRD §PIT 设计原则 2: 每个 finding 必带 evidence + 反向可追到 Raw manifest.

import { useSelectionStore } from "../stores/selectionStore";
import { dataAgeHuman, formatTimestamp } from "../lib/formatting";
import type { Finding, QualityStatus } from "../types/api";

export interface FindingCardProps {
  finding: Finding;
  compact?: boolean;
  onClick?: () => void;
}

export function FindingCard({ finding, compact, onClick }: FindingCardProps) {
  const openEvidence = useSelectionStore((s) => s.openEvidence);
  const title = finding.title_zh ?? finding.title ?? "(untitled)";
  const claim = finding.claim_zh ?? finding.claim ?? "";
  const limitations = finding.limitations_zh ?? finding.limitations ?? [];
  const confidence = finding.final_confidence ?? finding.llm_confidence ?? 0;

  const confidenceColor = confidence >= 0.7 ? "bg-emerald-500"
    : confidence >= 0.4 ? "bg-amber-500"
    : "bg-rose-500";

  return (
    <article
      className={`card cursor-pointer hover:shadow-md transition-shadow ${compact ? "p-3" : "p-4"} ${finding.rejected ? "opacity-60" : ""}`}
      onClick={() => onClick?.()}
    >
      <header className="flex items-start justify-between gap-3 mb-2">
        <h3 className={`${compact ? "text-sm" : "text-base"} font-semibold text-ink-900 leading-snug flex-1`}>
          {title}
        </h3>
        <div className="flex flex-col items-end shrink-0">
          <div className="flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full ${confidenceColor}`} />
            <span className="font-mono text-xs tabular-nums text-ink-700">
              {confidence.toFixed(2)}
            </span>
          </div>
          <span className="text-[10px] text-ink-500 uppercase tracking-wide">
            {finding.causal_language_level ?? "DESCRIPTIVE"}
          </span>
        </div>
      </header>

      {claim && (
        <p className="text-xs text-ink-700 leading-relaxed mb-2 line-clamp-3">
          {claim}
        </p>
      )}

      {limitations.length > 0 && (
        <div className="text-xs bg-amber-50 border border-amber-200 rounded px-2 py-1.5 mb-2 text-amber-800">
          <div className="font-medium mb-0.5">⚠️ limitations</div>
          <ul className="list-disc pl-4 space-y-0.5">
            {limitations.slice(0, 3).map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </div>
      )}

      <footer className="flex items-center justify-between text-[10px] text-ink-500 border-t border-ink-200 pt-2 mt-1">
        <div className="flex items-center gap-2">
          <span>evidence: <b className="text-ink-700">{finding.evidence_ids.length}</b></span>
          {finding.model && <span>model: <b className="text-ink-700 font-mono">{finding.model}</b></span>}
          {finding.prompt_version && <span>prompt_v: <b className="text-ink-700 font-mono">{finding.prompt_version}</b></span>}
        </div>
        <div className="flex items-center gap-1">
          {finding.created_at && <span>{formatTimestamp(finding.created_at, false)}</span>}
          <button
            type="button"
            className="btn-ghost text-[10px] px-1.5 py-0.5"
            onClick={(e) => {
              e.stopPropagation();
              if (finding.evidence_ids[0]) openEvidence(finding.evidence_ids[0]);
            }}
          >
            查看证据
          </button>
        </div>
      </footer>

      {finding.rejected && (
        <div className="mt-2 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1">
          ✗ REJECTED · {finding.reject_reason ?? "validation failed"}
        </div>
      )}
    </article>
  );
}
