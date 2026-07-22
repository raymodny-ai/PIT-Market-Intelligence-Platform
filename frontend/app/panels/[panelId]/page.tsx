export default function PanelPage({ params }: { params: { panelId: string } }) {
  return (
    <main style={{ padding: "2rem" }}>
      <h2>Panel: {params.panelId}</h2>
      <p>Phase 0 placeholder. Panel detail view comes in Phase 1-2.</p>
    </main>
  );
}
