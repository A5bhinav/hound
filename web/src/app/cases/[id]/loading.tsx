import { Bar, LoadingPanel } from "@/components/Chrome";

export default function Loading() {
  return (
    <>
      <Bar offline={false} step={2} />
      <LoadingPanel eyebrow="Step 2 of 4 · Follow the money" title="Following the money…" items={["Tracing wallet by wallet from the victim's send", "Large cases can take a few seconds"]} />
    </>
  );
}
