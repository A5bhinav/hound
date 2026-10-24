import Link from "next/link";

export function Bar({ sample, children }: { sample: boolean; children?: React.ReactNode }) {
  return (
    <header className="bar">
      <Link href="/" className="wordmark">
        Hound
      </Link>
      <span className="bar-meta">{children}</span>
      {sample && <span className="sample-flag">SAMPLE DATA · not a real trace</span>}
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
