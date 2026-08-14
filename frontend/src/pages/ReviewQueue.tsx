import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type FindingFilters } from "../api/client";
import type { Finding, Severity, Verdict } from "../api/types";
import {
  EmptyState,
  ErrorState,
  Mono,
  SeverityTag,
  Skeleton,
  VerdictTag,
} from "../components/primitives";
import { useToast } from "../components/Toast";
import { methodLabel } from "../lib/meaning";

const VERDICTS: Verdict[] = ["STALE_VERSION", "UNKNOWN_IMAGE", "ERROR", "PASS"];
const SEVERITIES: Severity[] = ["MATERIAL", "COSMETIC", "UNCERTAIN", "NONE"];
const PAGE = 50;

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded border px-2 py-0.5 text-xs transition-colors ${
        active
          ? "border-ink bg-ink text-white"
          : "border-line bg-surface text-ink-2 hover:bg-surface-sunk"
      }`}
    >
      {children}
    </button>
  );
}

export function ReviewQueue() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { notify } = useToast();
  const [params, setParams] = useSearchParams();

  // The default view is the work that actually needs doing: unacknowledged
  // material staleness. Everything else is one click away.
  const [verdicts, setVerdicts] = useState<Verdict[]>(
    (params.getAll("verdict") as Verdict[]).length
      ? (params.getAll("verdict") as Verdict[])
      : ["STALE_VERSION"],
  );
  const [severities, setSeverities] = useState<Severity[]>(
    (params.getAll("severity") as Severity[]).length
      ? (params.getAll("severity") as Severity[])
      : ["MATERIAL"],
  );
  const [onlyOpen, setOnlyOpen] = useState(params.get("acknowledged") !== "true");
  const [productId, setProductId] = useState(params.get("product_id") ?? "");
  const [offset, setOffset] = useState(0);
  const [cursor, setCursor] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);

  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const runIdParam = params.get("run");
  const runId = runIdParam ? Number(runIdParam) : runs.data?.[0]?.id;

  const filters: FindingFilters = useMemo(
    () => ({
      verdict: verdicts,
      severity: severities,
      acknowledged: onlyOpen ? false : undefined,
      product_id: productId || undefined,
      offset,
      limit: PAGE,
    }),
    [verdicts, severities, onlyOpen, productId, offset],
  );

  useEffect(() => {
    const p = new URLSearchParams();
    verdicts.forEach((v) => p.append("verdict", v));
    severities.forEach((v) => p.append("severity", v));
    if (!onlyOpen) p.set("acknowledged", "true");
    if (productId) p.set("product_id", productId);
    if (runIdParam) p.set("run", runIdParam);
    setParams(p, { replace: true });
  }, [verdicts, severities, onlyOpen, productId, runIdParam, setParams]);

  const findings = useQuery({
    queryKey: ["findings", runId, filters],
    queryFn: () => api.findings(runId!, filters),
    enabled: !!runId,
  });

  const rows = findings.data?.items ?? [];

  useEffect(() => {
    setCursor(0);
    setSelected(new Set());
  }, [runId, verdicts, severities, onlyOpen, productId, offset]);

  const acknowledge = useMutation({
    mutationFn: (ids: number[]) =>
      ids.length === 1
        ? api.acknowledge(ids[0], "ACKNOWLEDGED", "")
        : api.bulkAcknowledge(ids, "ACKNOWLEDGED", ""),
    onSuccess: (_d, ids) => {
      notify(ids.length === 1 ? "Acknowledged" : `Acknowledged ${ids.length} findings`);
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["findings"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (e: ApiError) => notify(e.message, "error"),
  });

  // j / k to move, a to acknowledge, Enter to open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.metaKey ||
        e.ctrlKey
      )
        return;
      if (!rows.length) return;

      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        setCursor((c) => Math.min(c + 1, rows.length - 1));
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        navigate(`/findings/${rows[cursor].id}`);
      } else if (e.key === "a") {
        e.preventDefault();
        const ids = selected.size ? [...selected] : [rows[cursor].id];
        acknowledge.mutate(ids);
      } else if (e.key === "x") {
        e.preventDefault();
        setSelected((s) => {
          const n = new Set(s);
          n.has(rows[cursor].id) ? n.delete(rows[cursor].id) : n.add(rows[cursor].id);
          return n;
        });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, cursor, selected, navigate, acknowledge]);

  useEffect(() => {
    rowRefs.current[cursor]?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const toggle = <T,>(list: T[], value: T, set: (v: T[]) => void) =>
    set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value]);

  return (
    <div className="flex h-[calc(100vh-2.75rem)] flex-col">
      <div className="border-b border-line bg-surface px-4 py-2">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <div className="flex items-center gap-1.5">
            <span className="text-2xs font-semibold uppercase tracking-wide text-ink-3">
              Verdict
            </span>
            {VERDICTS.map((v) => (
              <Chip
                key={v}
                active={verdicts.includes(v)}
                onClick={() => toggle(verdicts, v, setVerdicts)}
              >
                {v === "STALE_VERSION"
                  ? "Stale"
                  : v === "UNKNOWN_IMAGE"
                    ? "Not identified"
                    : v === "ERROR"
                      ? "Failed"
                      : "Current"}
              </Chip>
            ))}
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-2xs font-semibold uppercase tracking-wide text-ink-3">
              Severity
            </span>
            {SEVERITIES.map((v) => (
              <Chip
                key={v}
                active={severities.includes(v)}
                onClick={() => toggle(severities, v, setSeverities)}
              >
                {v.charAt(0) + v.slice(1).toLowerCase()}
              </Chip>
            ))}
          </div>

          <Chip active={onlyOpen} onClick={() => setOnlyOpen((o) => !o)}>
            {onlyOpen ? "Unacknowledged only" : "Including acknowledged"}
          </Chip>

          <input
            className="field w-36 font-mono text-xs"
            placeholder="Product SKU"
            value={productId}
            onChange={(e) => setProductId(e.target.value.trim().toUpperCase())}
            aria-label="Filter by product"
          />

          {runs.data && runs.data.length > 0 ? (
            <select
              className="field w-auto text-xs"
              value={runId ?? ""}
              onChange={(e) => {
                const p = new URLSearchParams(params);
                p.set("run", e.target.value);
                setParams(p);
              }}
              aria-label="Run"
            >
              {runs.data.map((r) => (
                <option key={r.id} value={r.id}>
                  Run {r.id} · {r.status.toLowerCase()}
                </option>
              ))}
            </select>
          ) : null}

          <div className="ml-auto flex items-center gap-2 text-xs text-ink-3">
            <span className="hidden md:inline">
              <span className="kbd">j</span> <span className="kbd">k</span> move ·{" "}
              <span className="kbd">x</span> select · <span className="kbd">a</span>{" "}
              acknowledge · <span className="kbd">↵</span> open
            </span>
          </div>
        </div>

        {selected.size > 0 ? (
          <div className="mt-2 flex items-center gap-2 rounded border border-line bg-surface-sunk px-2.5 py-1.5">
            <span className="text-xs">{selected.size} selected</span>
            <button
              className="btn-primary btn-sm"
              onClick={() => acknowledge.mutate([...selected])}
              disabled={acknowledge.isPending}
            >
              Acknowledge selected
            </button>
            <button className="btn-ghost btn-sm" onClick={() => setSelected(new Set())}>
              Clear
            </button>
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {findings.isLoading ? (
          <Skeleton rows={14} />
        ) : findings.isError ? (
          <div className="p-4">
            <ErrorState error={findings.error} retry={() => findings.refetch()} />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title="Nothing to review here"
            detail={
              onlyOpen
                ? "Every finding matching these filters has been acknowledged. Widen the filters, or include acknowledged findings, to see more."
                : "No findings match these filters. Try clearing the severity or verdict filters."
            }
            action={
              <button
                className="btn-ghost"
                onClick={() => {
                  setVerdicts(["STALE_VERSION", "UNKNOWN_IMAGE"]);
                  setSeverities(["MATERIAL", "COSMETIC", "UNCERTAIN"]);
                }}
              >
                Widen filters
              </button>
            }
          />
        ) : (
          <table className="dense-table">
            <thead>
              <tr>
                <th className="w-8" />
                <th className="w-14">Image</th>
                <th className="min-w-[13rem]">Product</th>
                <th className="w-28">Verdict</th>
                <th className="w-24">Severity</th>
                <th className="w-32">Serving → approved</th>
                <th className="w-16 text-right">Regions</th>
                <th className="w-36">Matched by</th>
                <th className="w-20 text-right">Confidence</th>
                {/* Absorbs the slack so the data columns stay packed together and
                    scannable, instead of drifting apart across a wide screen. */}
                <th className="w-full" />
              </tr>
            </thead>
            <tbody>
              {rows.map((f: Finding, i: number) => (
                <tr
                  key={f.id}
                  ref={(el) => (rowRefs.current[i] = el)}
                  data-cursor={i === cursor}
                  data-selected={selected.has(f.id)}
                  onClick={() => setCursor(i)}
                  onDoubleClick={() => navigate(`/findings/${f.id}`)}
                  className="cursor-default"
                >
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(f.id)}
                      onChange={(e) => {
                        e.stopPropagation();
                        setSelected((s) => {
                          const n = new Set(s);
                          n.has(f.id) ? n.delete(f.id) : n.add(f.id);
                          return n;
                        });
                      }}
                      aria-label={`Select finding ${f.id}`}
                    />
                  </td>
                  <td>
                    {f.thumb_url ? (
                      <img
                        src={f.thumb_url}
                        alt=""
                        loading="lazy"
                        className="h-9 w-9 rounded border border-line object-cover"
                      />
                    ) : null}
                  </td>
                  <td>
                    <button
                      className="text-left hover:underline"
                      onClick={() => navigate(`/findings/${f.id}`)}
                    >
                      <div className="font-medium leading-tight">{f.product_name}</div>
                      <Mono className="text-ink-3">{f.product_id}</Mono>
                    </button>
                  </td>
                  <td>
                    <VerdictTag verdict={f.verdict} />
                    {f.acknowledged ? (
                      <span className="ml-1.5 text-2xs text-ink-4">acknowledged</span>
                    ) : null}
                  </td>
                  <td>
                    <SeverityTag severity={f.severity} />
                  </td>
                  <td>
                    <Mono>
                      {f.matched_version ?? "—"}
                      <span className="mx-1 text-ink-4">→</span>
                      {f.current_version ?? "—"}
                    </Mono>
                  </td>
                  <td className="text-right">
                    <Mono>{f.region_count || "—"}</Mono>
                  </td>
                  <td>
                    <span className="text-xs text-ink-3">{methodLabel[f.match_method]}</span>
                  </td>
                  <td className="text-right">
                    <Mono>{f.confidence ? f.confidence.toFixed(2) : "—"}</Mono>
                  </td>
                  <td />
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="flex items-center gap-3 border-t border-line bg-surface px-4 py-1.5 text-xs text-ink-3">
        <span>
          {findings.data
            ? `${offset + 1}–${Math.min(offset + PAGE, findings.data.total)} of ${findings.data.total}`
            : "—"}
        </span>
        <div className="ml-auto flex gap-1.5">
          <button
            className="btn-ghost btn-sm"
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE))}
          >
            Previous
          </button>
          <button
            className="btn-ghost btn-sm"
            disabled={!findings.data || offset + PAGE >= findings.data.total}
            onClick={() => setOffset((o) => o + PAGE)}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
