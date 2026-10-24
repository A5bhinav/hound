import { Bar, LoadingPanel } from "@/components/Chrome";

export default function Loading() {
  return (
    <>
      <Bar offline={false} step={1} />
      <LoadingPanel eyebrow="Step 1 of 4 · Report the scam" title="Loading…" items={["Connecting to the hotline feed"]} />
    </>
  );
}
