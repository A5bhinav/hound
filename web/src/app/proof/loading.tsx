export default function Loading() {
  return (
    <main className="wrap" role="status">
      <header className="page-head">
        <div>
          <p className="label">Proof it works</p>
          <h1>Loading the proof…</h1>
        </div>
      </header>
      <ul className="box checks">
        <li>Scoring the DOJ replay</li>
        <li>Reading the backtest</li>
        <li>Reading the weekend scan</li>
      </ul>
    </main>
  );
}
