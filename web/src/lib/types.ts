// Mirrors BRIEF.md §8.2 (Case) and §8.3 (Trace). Keep in sync with schemas/.

export type Chain = "ethereum" | "tron";

export interface Send {
  chain: Chain;
  tx_hash: string;
  from: string;
  to: string;
  token: string;
  amount: number;
  time: string;
}

export interface Case {
  case_id: string;
  created_at: string;
  source: "phone" | "screenshot" | "chainabuse" | "doj_replay";
  victim: { alias: string; age_band: string; exchange_used: string | null };
  story: { scam_app: string; platform: string; first_contact: string; summary: string };
  sends: Send[];
  status: "intake" | "tracing" | "traced" | "packet_ready";
}

export type NodeKind =
  | "victim"
  | "intermediate"
  | "exchange_deposit"
  | "exchange_hot"
  | "holding"
  | "mixer"
  | "bridge"
  | "unknown";

export interface TraceNode {
  address: string;
  chain: Chain;
  kind: NodeKind;
  label: string | null;
  label_source: "exchange_list" | "ofac" | "classifier" | null;
  classifier: { kind: string; confidence: number; reasons: string[] } | null;
  balance_usdt: number | null;
  frozen: { is_frozen: boolean; frozen_at: string | null; freeze_tx: string | null } | null;
  depth: number;
}

export interface TraceEdge {
  from: string;
  to: string;
  token: string;
  amount: number;
  attributed_amount: number;
  tx_hashes: string[];
  first_time: string;
  last_time: string;
  hop: number;
  confidence: number;
  method: "direct" | "peel" | "consolidation" | "swap" | "bridge_match";
}

export interface Endpoint {
  address: string;
  reason: "exchange" | "holding" | "frozen" | "dead_end" | "dust" | "max_hops";
  victim_inflow: number;
  balance_usdt: number;
  freezable: boolean;
  exchange: string | null;
}

export interface OtherPayer {
  address: string;
  amount: number;
  window_days: number;
  source_exchange: string | null;
  confidence: number;
}

export interface Trace {
  trace_id: string;
  case_id: string;
  created_at: string;
  method: { accounting: string; max_hops: number; max_branches_per_node: number; min_amount: number };
  nodes: TraceNode[];
  edges: TraceEdge[];
  endpoints: Endpoint[];
  other_payers: OtherPayer[];
  stats: { api_calls: number; cache_hits: number; empty_results: number; elapsed_ms: number };
  /** Present only on the web/ placeholder fixture. Real traces never carry it. */
  _sample?: string;
}
