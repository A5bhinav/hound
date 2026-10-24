import type { Chain, NodeKind, TraceNode } from "./types";

export const usdt = (n: number | null | undefined) =>
  n == null ? "—" : `${n.toLocaleString("en-US", { maximumFractionDigits: 2 })} USDT`;

export const pct = (c: number) => `${Math.round(c * 100)}%`;

export const shortAddr = (a: string) => (a.length > 14 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a);

export function explorerUrl(chain: Chain, kind: "address" | "tx", id: string): string | null {
  if (chain === "ethereum" && /^0x[0-9a-f]{40,64}$/i.test(id)) return `https://etherscan.io/${kind}/${id}`;
  if (chain === "tron" && (kind === "tx" || /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(id)))
    return `https://tronscan.org/#/${kind === "tx" ? "transaction" : "address"}/${id}`;
  return null;
}

export const KIND_LABEL: Record<NodeKind, string> = {
  victim: "Victim",
  intermediate: "Intermediate",
  exchange_deposit: "Exchange deposit",
  exchange_hot: "Exchange hot wallet",
  holding: "Holding",
  mixer: "Mixer",
  bridge: "Bridge",
  unknown: "Unknown",
};

export type Tone = "trace" | "exchange" | "hold" | "frozen" | "dead";

/** Colour role for a node, per BRIEF §9.4. */
export function tone(n: TraceNode): Tone {
  if (n.frozen?.is_frozen) return "frozen";
  switch (n.kind) {
    case "exchange_deposit":
    case "exchange_hot":
      return "exchange";
    case "holding":
      return "hold";
    case "mixer":
    case "bridge":
    case "unknown":
      return "dead";
    default:
      return "trace";
  }
}
