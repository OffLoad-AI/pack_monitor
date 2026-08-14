import type {
  BatchCreated,
  Comparison,
  ComparisonDetail,
  Config,
  Created,
  Page,
  StageName,
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
    res = await fetch(path, init);
  } catch {
    throw new ApiError("Cannot reach the API server.", 0,
      "Start it with: uvicorn api.main:app --port 8000 (from the backend directory).");
  }

  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail ?? res.statusText;
    } catch {
      /* the response had no JSON body */
    }
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail), res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function json<T>(path: string, method: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Artefact paths are relative to the static `data/` mount. */
export function fileUrl(path: string | null | undefined): string | undefined {
  return path ? `/files/${path}` : undefined;
}

export const api = {
  create: (reference: File, marketplace: File, label?: string) => {
    const form = new FormData();
    form.append("reference", reference);
    form.append("marketplace", marketplace);
    if (label) form.append("label", label);
    return request<Created>("/api/comparisons", { method: "POST", body: form });
  },

  createBatch: (files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return request<BatchCreated>("/api/comparisons/batch", {
      method: "POST",
      body: form,
    });
  },

  list: (verdicts: string[] = [], offset = 0, limit = 50) => {
    const p = new URLSearchParams();
    verdicts.forEach((v) => p.append("verdict", v));
    p.set("offset", String(offset));
    p.set("limit", String(limit));
    return request<Page<Comparison>>(`/api/comparisons?${p}`);
  },

  get: (id: number) => request<ComparisonDetail>(`/api/comparisons/${id}`),
  remove: (id: number) =>
    request<void>(`/api/comparisons/${id}`, { method: "DELETE" }),
  stages: () => request<StageName[]>("/api/comparisons/stages"),

  config: () => request<Config>("/api/config"),
  updateConfig: (values: Record<string, number>) =>
    json<Config>("/api/config", "PUT", { values }),
  calibration: () => request<Record<string, any>>("/api/calibration"),
};
