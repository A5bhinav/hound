export default function Loading() {
  return (
    <div className="api-error" style={{ borderLeftColor: "var(--trace)" }} role="status">
      <p className="eyebrow">Loading the proof</p>
      <p>Scoring the DOJ replay and reading the backtest and weekend scan.</p>
    </div>
  );
}
