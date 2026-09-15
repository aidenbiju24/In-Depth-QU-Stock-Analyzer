/** Typed client for the local FastAPI backend.
 *
 * The browser talks ONLY to our own quant service — never to external data
 * providers (PROJECT_SPEC §8).
 *
 * - Production builds default to SAME-ORIGIN `/api` (next start rewrites or
 *   any reverse proxy forwards to FastAPI) — no cross-origin exposure.
 * - Dev defaults to FastAPI directly on :8000 because Next's dev rewrite
 *   proxy drops POST bodies; CORS is configured server-side for this.
 * - Override either case with NEXT_PUBLIC_QUANT_API_URL.
 */

export const API =
  process.env.NEXT_PUBLIC_QUANT_API_URL ??
  (process.env.NODE_ENV === "production"
    ? "/api"
    : "http://127.0.0.1:8000/api");

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      0,
      "Cannot reach the quant backend. Is it running on port 8000? (uvicorn app.api:app --app-dir backend)"
    );
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep default detail */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const get = <T,>(path: string) => request<T>(path);
export const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
export const patchQ = <T,>(path: string, query: string) =>
  request<T>(`${path}?${query}`, { method: "PATCH" });

// ------------------------------------------------------------------ types
export interface Health {
  status: string;
  time: string;
  db: string;
  row_counts: Record<string, number>;
  credentials_missing: Record<string, boolean>;
}

export interface Quote {
  ticker: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  as_of: string;
  price: number;
  prev_close: number | null;
  change_pct: number | null;
  volume: number | null;
}

export interface IngestReport {
  ticker: string;
  ok: boolean;
  report: {
    companies: number;
    prices: number;
    statements: number;
    fundamentals: number;
    earnings: number;
    errors: string[];
    validation: { errors: number; warnings: number } | null;
  };
}

export interface AnalyzeResponse {
  ticker: string;
  as_of: string;
  quant_score: number;
  factor_scores: Record<string, number>;
  metric_scores: Record<string, number | null>;
  raw_inputs: Record<string, number | null>;
  coverage: Record<string, number>;
  missing: { metric: string; reason: string }[];
  model_version: string;
}

export interface MetricDef {
  factor: string;
  label: string;
  direction: string;
  weight: number;
  band: [number, number];
}

export interface MetricsBreakdown {
  ticker: string;
  as_of: string;
  raw_inputs: Record<string, number | null>;
  metric_scores: Record<string, number | null>;
  definitions: Record<string, MetricDef>;
  factor_scores: Record<string, number>;
  quant_score: number;
  coverage: Record<string, number>;
  missing: { metric: string; reason: string }[];
}

export interface DCFInputsResponse {
  ticker: string;
  as_of: string;
  fiscal_date: string;
  derived: Record<string, number | null>;
  placeholders: Record<string, number>;
  missing: string[];
}

export interface DCFRequest {
  base_revenue: number;
  revenue_growth: number[];
  ebit_margin: number | number[];
  tax_rate: number;
  capex_pct_revenue: number | number[];
  depreciation_pct_revenue: number | number[];
  wc_change_pct_revenue: number | number[];
  wacc: number;
  terminal_growth: number;
  net_debt: number;
  shares_diluted: number;
  current_price: number | null;
}

export interface DCFResponse {
  ticker: string;
  fair_value_per_share: number;
  enterprise_value: number;
  equity_value: number;
  pv_explicit: number;
  pv_terminal: number;
  terminal_value: number;
  upside: number | null;
  warnings: string[];
  assumptions: DCFRequest;
  projected: {
    year: number;
    revenue: number;
    ebit: number;
    nopat: number;
    d_and_a: number;
    capex: number;
    wc_change: number;
    fcf: number;
    discount_factor: number;
    pv_fcf: number;
  }[];
}

export interface SensitivityResponse {
  ticker: string;
  wacc_axis: number[];
  growth_axis: number[];
  table: (number | null)[][];
}

export interface MonteCarloResponse {
  ticker: string;
  current_price: number;
  days: number;
  n_simulations: number;
  mu_annual: number;
  sigma_annual: number;
  seed: number;
  mean: number;
  median: number;
  std: number;
  p05: number;
  p25: number;
  p75: number;
  p95: number;
  prob_gain: number;
  prob_loss: number;
  percentile_path: {
    days: number[];
    p5: number[];
    p25: number[];
    p50: number[];
    p75: number[];
    p95: number[];
  };
  version: string;
  disclaimer: string;
}

export interface RegimeResponse {
  version: string;
  as_of: string;
  primary_regime: string;
  trend: string;
  volatility_regime: string;
  risk_on_off: string;
  note: string;
}

export interface EarningsResponse {
  version: string;
  records: {
    fiscal_date: string;
    report_date: string | null;
    eps_actual: number | null;
    eps_estimated: number | null;
    eps_surprise: number | null;
    eps_surprise_pct: number | null;
    revenue_actual: number | null;
    revenue_estimate: number | null;
    revenue_surprise_pct: number | null;
    market_reaction: number | null;
  }[];
  summary: {
    n_reports: number;
    n_with_estimates: number | null;
    beat_rate: number | null;
    mean_surprise_pct: number | null;
    median_surprise_pct: number | null;
  };
}

export interface RecommendationResponse {
  ticker: string;
  action: "Strong Buy" | "Buy" | "Hold" | "Sell" | "Strong Sell";
  score: number;
  rules_fired: string[];
  reasoning: string[];
  version: string;
  disclaimer: string;
}

export interface PortfolioSummary {
  id: string;
  name: string;
  benchmark: string;
  cash: number;
  positions: { ticker: string; quantity: number; avg_cost: number | null }[];
}

export interface PortfolioAnalytics {
  portfolio_id: string;
  benchmark: string;
  weights: Record<string, number>;
  positions_value: Record<string, number>;
  total_value: number;
  stats: Record<string, number | null>;
  correlation: {
    matrix: Record<string, Record<string, number>>;
    pairs_sorted: { a: string; b: string; correlation: number }[];
    highly_correlated: { a: string; b: string; correlation: number }[];
  };
  equity_curve: { dates: string[]; values: number[] };
}

export interface OptimizationResponse {
  objective: string;
  weights: Record<string, number>;
  expected_return: number;
  expected_volatility: number;
  expected_sharpe: number;
  constraints: Record<string, unknown>;
  inputs: Record<string, unknown>;
  version: string;
}

export interface BacktestResponse {
  config: Record<string, unknown>;
  stats: Record<string, number | null>;
  equity_curve: { dates: string[]; values: number[] };
  benchmark_curve: { dates: string[]; values: number[] };
  trade_log: Record<string, unknown>[];
  skipped_executions: Record<string, unknown>[];
}

export interface DecisionRecord {
  id: number;
  decision_date: string;
  ticker: string;
  price: number | null;
  quant_score: number | null;
  value_score: number | null;
  growth_score: number | null;
  quality_score: number | null;
  momentum_score: number | null;
  risk_score: number | null;
  dcf_fair_value: number | null;
  dcf_upside: number | null;
  decision: string;
  position_size: number | null;
  thesis: string | null;
  catalysts: string | null;
  risks: string | null;
  outcome: string | null;
}

export interface ModelRun {
  id: number;
  model: string;
  version: string;
  subject: string;
  input_as_of: string | null;
  run_at: string;
}

export interface ModelRunDetail extends ModelRun {
  parameters: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  source_data: Record<string, unknown> | null;
}

// ------------------------------------------------------------- endpoints
export const fetchHealth = () => get<Health>("/health");
export const fetchQuote = (t: string) => get<Quote>(`/quote/${t}`);
export const ingest = (t: string) => post<IngestReport>(`/ingest/${t}`);
export const analyze = (t: string) => post<AnalyzeResponse>(`/analyze/${t}`);
export const fetchMetricsBreakdown = (t: string) =>
  get<MetricsBreakdown>(`/analyze/${t}/metrics`);
export const fetchDCFInputs = (t: string) => get<DCFInputsResponse>(`/dcf-inputs/${t}`);
export const runDCF = (t: string, body: DCFRequest) =>
  post<DCFResponse>(`/dcf/${t}`, body);
export const runSensitivity = (t: string, body: DCFRequest) =>
  post<SensitivityResponse>(`/dcf/${t}/sensitivity`, body);
export const runMonteCarlo = (t: string, sims: number, seed: number) =>
  get<MonteCarloResponse>(`/montecarlo/${t}?sims=${sims}&seed=${seed}`);
export const fetchRegime = () => get<RegimeResponse>("/regime");
export const fetchEarnings = (t: string) => get<EarningsResponse>(`/earnings/${t}`);
export const fetchRecommendation = (t: string) =>
  get<RecommendationResponse>(`/recommend/${t}`);
export const fetchPortfolios = () => get<PortfolioSummary[]>("/portfolios");
export const fetchPortfolio = (id: string) => get<PortfolioSummary>(`/portfolios/${id}`);
export const createPortfolio = (name: string, benchmark: string) =>
  post<{ id: string; name: string }>("/portfolios", { name, benchmark });
export const addPosition = (
  id: string,
  ticker: string,
  quantity: number,
  avgCost: number | null
) =>
  post<{ ok: boolean }>(`/portfolios/${id}/positions`, {
    ticker,
    quantity,
    avg_cost: avgCost,
  });
export const fetchPortfolioAnalytics = (id: string) =>
  get<PortfolioAnalytics>(`/portfolios/${id}/analytics`);
export const runOptimize = (
  tickers: string[],
  objective: string,
  maxPosition: number
) =>
  post<OptimizationResponse>("/optimize", {
    tickers,
    objective,
    max_position: maxPosition,
  });
export const runBacktest = (body: {
  universe: string[];
  start: string;
  end: string;
  benchmark: string;
  rebalance_frequency: string;
  top_n: number;
  factor: string;
}) => post<BacktestResponse>("/backtest", body);
export const fetchDecisions = (ticker?: string) =>
  get<DecisionRecord[]>(`/decisions${ticker ? `?ticker=${ticker}` : ""}`);
export const recordDecision = (body: Partial<DecisionRecord> & { ticker: string; decision: string }) =>
  post<{ id: number; ok: boolean }>("/decisions", body);
export const updateOutcome = (id: number, outcome: string) =>
  patchQ<{ ok: boolean }>(`/decisions/${id}/outcome`, `outcome=${encodeURIComponent(outcome)}`);
export const fetchModelRuns = () => get<ModelRun[]>("/model_runs");
export const fetchModelRun = (id: number) => get<ModelRunDetail>(`/model_runs/${id}`);
