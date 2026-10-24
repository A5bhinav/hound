export default function Loading() {
  return (
    <div className="api-error" style={{ borderLeftColor: "var(--trace)" }} role="status">
      <p className="eyebrow">Following the money</p>
      <p>Tracing hop by hop from the victim&apos;s send. Large cases can take a few seconds.</p>
    </div>
  );
}
