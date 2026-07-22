export default function FindingPage({ params }: { params: { findingId: string } }) {
  return (
    <main style={{ padding: "2rem" }}>
      <h2>Finding: {params.findingId}</h2>
      <p>Phase 0 placeholder. Finding audit page comes in Phase 3.</p>
    </main>
  );
}
