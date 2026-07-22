export default function LineagePage({ params }: { params: { entityId: string } }) {
  return (
    <main style={{ padding: "2rem" }}>
      <h2>Lineage: {params.entityId}</h2>
      <p>Phase 0 placeholder. Field-level lineage graph comes in Phase 4.</p>
    </main>
  );
}
