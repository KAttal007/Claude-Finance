export function Placeholder({ title, phase }: { title: string; phase: number }) {
  return (
    <section>
      <h2>{title}</h2>
      <p className="muted">Arrives in Phase {phase} (design doc section 26).</p>
    </section>
  );
}
