import type {
  Finding,
  FindingDetail,
  FindingImages,
  Page,
  Product,
  ProductDetail,
  Run,
  Stats,
  Thresholds,
  Version,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly hint?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(
      "Cannot reach the API server.",
      0,
      "Start it with: uvicorn api.main:app --port 8000 (from the backend directory).",
    );
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* response had no JSON body */
    }
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      res.status,
    );
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface FindingFilters {
  verdict?: string[];
  severity?: string[];
  acknowledged?: boolean;
  product_id?: string;
  match_method?: string;
  sort?: string;
  order?: "asc" | "desc";
  offset?: number;
  limit?: number;
}

function toQuery(filters: FindingFilters): string {
  const p = new URLSearchParams();
  filters.verdict?.forEach((v) => p.append("verdict", v));
  filters.severity?.forEach((v) => p.append("severity", v));
  if (filters.acknowledged !== undefined)
    p.set("acknowledged", String(filters.acknowledged));
  if (filters.product_id) p.set("product_id", filters.product_id);
  if (filters.match_method) p.set("match_method", filters.match_method);
  if (filters.sort) p.set("sort", filters.sort);
  if (filters.order) p.set("order", filters.order);
  p.set("offset", String(filters.offset ?? 0));
  p.set("limit", String(filters.limit ?? 50));
  return p.toString();
}

export const api = {
  stats: () => request<Stats>("/api/stats"),

  products: (q?: string) =>
    request<Product[]>(`/api/products${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  product: (id: string) => request<ProductDetail>(`/api/products/${id}`),
  productVersions: (id: string) => request<Version[]>(`/api/products/${id}/versions`),

  runs: () => request<Run[]>("/api/runs"),
  run: (id: number) => request<Run>(`/api/runs/${id}`),
  startRun: (input_dir: string) =>
    request<Run>("/api/runs", {
      method: "POST",
      body: JSON.stringify({ input_dir }),
    }),
  findings: (runId: number, filters: FindingFilters) =>
    request<Page<Finding>>(`/api/runs/${runId}/findings?${toQuery(filters)}`),

  finding: (id: number) => request<FindingDetail>(`/api/findings/${id}`),
  findingImages: (id: number) => request<FindingImages>(`/api/findings/${id}/images`),
  acknowledge: (id: number, decision: string, note: string) =>
    request<unknown>(`/api/findings/${id}/acknowledge`, {
      method: "POST",
      body: JSON.stringify({ decision, note }),
    }),
  unacknowledge: (id: number) =>
    request<unknown>(`/api/findings/${id}/acknowledge`, { method: "DELETE" }),
  bulkAcknowledge: (ids: number[], decision: string, note: string) =>
    request<unknown>("/api/findings/bulk-acknowledge", {
      method: "POST",
      body: JSON.stringify({ finding_ids: ids, decision, note }),
    }),

  thresholds: () => request<Thresholds>("/api/config/thresholds"),
  updateThresholds: (values: Record<string, number>) =>
    request<Thresholds>("/api/config/thresholds", {
      method: "PUT",
      body: JSON.stringify({ values }),
    }),
  calibration: () => request<Record<string, any>>("/api/calibration"),
};
