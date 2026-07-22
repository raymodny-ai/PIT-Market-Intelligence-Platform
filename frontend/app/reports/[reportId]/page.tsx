export default function ReportPage({ params }: { params: { reportId: string } }) {
  return (
    <main style={{ padding: "2rem" }}>
      <h2>Frozen Report: {params.reportId}</h2>
      <p>Phase 0 placeholder. Frozen report rendering comes in Phase 2.</p>
    </main>
  );
}
