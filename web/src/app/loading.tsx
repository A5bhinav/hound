import { Bar } from "@/components/Chrome";

export default function Loading() {
  return (
    <>
      <Bar offline={false} />
      <p className="page-intro" role="status">
        Loading…
      </p>
    </>
  );
}
