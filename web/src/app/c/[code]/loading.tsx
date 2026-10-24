import { Bar, LoadingPanel } from "@/components/Chrome";

export default function Loading() {
  return (
    <>
      <Bar offline={false} />
      <LoadingPanel eyebrow="Your case" title="Loading…" items={["Opening your upload page"]} />
    </>
  );
}
