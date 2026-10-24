export default function Loading() {
  return (
    <div className="api-error" style={{ borderLeftColor: "var(--trace)" }} role="status">
      <p className="eyebrow">Writing the packet</p>
      <p>Every number is checked against the trace before it is shown.</p>
    </div>
  );
}
