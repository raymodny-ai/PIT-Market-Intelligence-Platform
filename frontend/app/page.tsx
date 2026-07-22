import Link from "next/link";

export default function HomePage() {
  return (
    <main style={{ padding: "2rem", maxWidth: 720, margin: "0 auto" }}>
      <h1>PIT Market Intelligence Platform</h1>
      <p>Phase 0 — Engineering skeleton. Pick a workspace:</p>
      <ul>
        <li>
          <Link href="/dashboard">/dashboard</Link> — Dynamic research
        </li>
        <li>
          <Link href="/reports/sample">/reports/[reportId]</Link> — Frozen
          report
        </li>
        <li>
          <Link href="/panels/sample">/panels/[panelId]</Link> — Panel detail
        </li>
        <li>
          <Link href="/findings/sample">/findings/[findingId]</Link> — Finding
          audit
        </li>
        <li>
          <Link href="/lineage/sample">/lineage/[entityId]</Link> — Field
          lineage
        </li>
      </ul>
    </main>
  );
}
