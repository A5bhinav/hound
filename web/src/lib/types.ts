// Mirrors schemas/case.schema.json and schemas/trace.schema.json. Keep in sync.

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

/** GET /cases returns these fields only; the full Case (with sends) is not served yet. */
export interface CaseSummary {
  case_id: string;
  source: "phone" | "screenshot" | "chainabuse" | "doj_replay";
  status: "intake" | "tracing" | "traced" | "packet_ready";
  victim?: { alias?: string; age_band?: string; exchange_used?: string | null } | null;
  story?: { scam_app?: string | null; platform?: string | null; first_contact?: string | null; summary?: string | null } | null;
}

export interface Case extends CaseSummary {
  created_at: string;
  sends: Send[];
  data_cutoff_block?: number | null;
  freeze_visibility?: "visible" | "hidden";
  as_of?: string | null;
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
  label?: string | null;
  label_source?: "exchange_list" | "ofac" | "classifier" | null;
  classifier?: { kind: string; confidence: number; reasons: string[] } | null;
  balance_usdt?: number | null;
  frozen?: { is_frozen: boolean; frozen_at: string | null; freeze_tx: string | null } | null;
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
  attributed_by_seed?: Record<string, number>;
}

export type EndpointReason =
  | "exchange"
  | "holding"
  | "frozen"
  | "dead_end"
  | "dust"
  | "max_hops"
  | "capped"
  | "high_volume"
  | "budget"
  | "time_cap"
  | "swap_unresolved"
  | "tether_destroyed";

export interface Endpoint {
  address: string;
  reason: EndpointReason;
  victim_inflow: number;
  victim_remaining?: number;
  balance_usdt?: number | null;
  freezable: boolean;
  exchange?: string | null;
  attributed_by_seed?: Record<string, number>;
}

export interface Seed {
  seed_id: string;
  tx_hash: string;
  token: string;
  amount: number;
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
  /** Historical case: the UI must say "replay", never "sitting there right now". */
  replay?: boolean;
  status: "done" | "partial" | "error";
  source: "engine" | "hand_built";
  method: {
    accounting: string;
    max_hops: number;
    max_branches_per_node: number;
    min_amount: number;
    as_of_block?: number;
    /** "hidden" = replay: freezes are revealed only after the trace finishes unfolding. */
    freeze_visibility?: "visible" | "hidden";
  };
  seeds: Seed[];
  nodes: TraceNode[];
  edges: TraceEdge[];
  endpoints: Endpoint[];
  other_payers: OtherPayer[];
  stats: { api_calls: number; cache_hits: number; empty_results: number; elapsed_ms: number };
  audit_log: AuditEntry[];
}

export interface AuditEntry {
  t: string;
  step: string;
  address?: string | null;
  detail: string;
}

/** AUDIT N4: POST /cases/{id}/trace answers at once; GET /traces/{id} returns progress until the run ends. */
export interface TraceRunning {
  trace_id: string;
  status: "running";
  audit_log?: AuditEntry[];
}
