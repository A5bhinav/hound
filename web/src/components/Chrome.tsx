import Link from "next/link";

/** offline: HOUND_DATA=fixture, serving the repo's examples/ instead of the live backend. */
export function Bar({ offline, children }: { offline: boolean; children?: React.ReactNode }) {
  return (
    <header className="bar">
      <Link href="/" className="wordmark">
        Hound
      </Link>
      <span className="bar-meta">{children}</span>
      <nav className="bar-nav" aria-label="Main">
        <Link href="/">Cases</Link>
        <Link href="/exchange">Exchange check</Link>
        <Link href="/proof">Proof</Link>
      </nav>
      {offline && <span className="sample-flag">OFFLINE · examples/ data, not the live API</span>}
    </header>
  );
}

export function ApiError({ message }: { message: string }) {
  return (
    <div className="api-error" role="alert">
      <p className="eyebrow">Couldn&apos;t load from the Hound API</p>
      <p>{message}</p>
    </div>
  );
}
