import { Bar, LoadingPanel } from "@/components/Chrome";

export default function Loading() {
  return (
    <>
      <Bar offline={false} step="proof" />
      <LoadingPanel eyebrow="Proof it works" title="Loading the proof…" items={["Scoring the DOJ replay", "Reading the backtest", "Reading the weekend scan"]} />
    </>
  );
}
