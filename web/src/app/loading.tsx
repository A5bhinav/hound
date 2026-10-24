import { Bar, LoadingPanel } from "@/components/Chrome";

export default function Loading() {
  return (
    <>
      <Bar offline={false} />
      <LoadingPanel eyebrow="Hound" title="Loading…" items={["Opening the page"]} />
    </>
  );
}
