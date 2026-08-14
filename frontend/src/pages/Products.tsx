import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import {
  EmptyState,
  ErrorState,
  Mono,
  SectionTitle,
  SeverityTag,
  Skeleton,
  VerdictTag,
} from "../components/primitives";
import { formatDate, shortHash } from "../lib/format";

export function Products() {
  const [q, setQ] = useState("");
  const products = useQuery({
    queryKey: ["products", q],
    queryFn: () => api.products(q || undefined),
  });

  return (
    <div className="flex h-[calc(100vh-2.75rem)] flex-col">
      <div className="flex items-center gap-3 border-b border-line bg-surface px-4 py-2">
        <h1 className="text-sm font-semibold">Products</h1>
        <input
          className="field w-64"
          placeholder="Search by name, brand or SKU"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search products"
        />
        <span className="ml-auto text-xs text-ink-3">
          {products.data?.length ?? 0} products
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {products.isLoading ? (
          <Skeleton rows={12} />
        ) : products.isError ? (
          <div className="p-4">
            <ErrorState error={products.error} retry={() => products.refetch()} />
          </div>
        ) : !products.data?.length ? (
          <EmptyState
            title="No products registered"
            detail="Process a corpus of approved artwork first: python -m pipeline.references --corpus ./data/corpus"
          />
        ) : (
          <table className="dense-table">
            <thead>
              <tr>
                <th className="w-14">Artwork</th>
                <th>Product</th>
                <th className="w-24">SKU</th>
                <th className="w-28">Brand</th>
                <th className="w-20 text-right">Versions</th>
                <th className="w-24">Approved</th>
                <th className="w-28">Last verdict</th>
                <th className="w-24">Severity</th>
                <th className="w-24 text-right">Open findings</th>
              </tr>
            </thead>
            <tbody>
              {products.data.map((p) => (
                <tr key={p.id}>
                  <td>
                    {p.current_version?.thumb_url ? (
                      <img
                        src={p.current_version.thumb_url}
                        alt=""
                        loading="lazy"
                        className="h-9 w-9 rounded border border-line object-cover"
                      />
                    ) : null}
                  </td>
                  <td>
                    <Link
                      to={`/products/${p.id}`}
                      className="font-medium hover:underline"
                    >
                      {p.name}
                    </Link>
                  </td>
                  <td>
                    <Mono>{p.id}</Mono>
                  </td>
                  <td className="text-ink-2">{p.brand}</td>
                  <td className="text-right">
                    <Mono>{p.version_count}</Mono>
                  </td>
                  <td>
                    <Mono>{p.current_version?.version_label ?? "—"}</Mono>
                  </td>
                  <td>
                    {p.last_verdict ? <VerdictTag verdict={p.last_verdict} /> : "—"}
                  </td>
                  <td>
                    {p.last_severity ? <SeverityTag severity={p.last_severity} /> : "—"}
                  </td>
                  <td className="text-right">
                    {p.open_findings ? (
                      <Link
                        to={`/queue?product_id=${p.id}`}
                        className="font-mono tabular text-material hover:underline"
                      >
                        {p.open_findings}
                      </Link>
                    ) : (
                      <Mono className="text-ink-4">0</Mono>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export function ProductDetail() {
  const { id } = useParams();
  const product = useQuery({
    queryKey: ["product", id],
    queryFn: () => api.product(id!),
  });

  if (product.isLoading) return <div className="p-4"><Skeleton rows={10} /></div>;
  if (product.isError)
    return (
      <div className="p-4">
        <ErrorState error={product.error} retry={() => product.refetch()} />
      </div>
    );

  const p = product.data!;

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{p.name}</h1>
        <p className="text-xs text-ink-3">
          <Mono>{p.id}</Mono> · {p.brand} · {p.versions.length} artwork versions
        </p>
      </div>

      <div className="panel">
        <SectionTitle right={<span className="text-2xs text-ink-3">oldest to newest</span>}>
          Version history
        </SectionTitle>
        <div className="flex gap-3 overflow-x-auto p-3.5">
          {p.versions.map((v, i) => (
            <div key={v.id} className="flex items-start gap-3">
              <div className="w-40 shrink-0">
                <div
                  className={`overflow-hidden rounded border ${
                    v.is_current ? "border-clear ring-1 ring-clear" : "border-line"
                  }`}
                >
                  {v.thumb_url ? (
                    <img src={v.thumb_url} alt={`${p.id} ${v.version_label}`} className="w-full" />
                  ) : null}
                </div>
                <div className="mt-1.5 flex items-center gap-1.5">
                  <Mono className="font-medium">{v.version_label}</Mono>
                  {v.is_current ? (
                    <span className="rounded border border-clear-line bg-clear-bg px-1 text-2xs text-clear">
                      approved
                    </span>
                  ) : null}
                </div>
                <div className="text-2xs text-ink-3">{formatDate(v.approved_at)}</div>
                <Mono className="text-2xs text-ink-4">{shortHash(v.sha256, 12)}</Mono>
              </div>
              {i < p.versions.length - 1 ? (
                <div className="mt-16 text-ink-4">→</div>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <SectionTitle>Findings across runs</SectionTitle>
        {p.findings.length === 0 ? (
          <EmptyState
            title="No findings yet"
            detail="This product has not appeared in a completed run."
          />
        ) : (
          <table className="dense-table">
            <thead>
              <tr>
                <th className="w-16">Run</th>
                <th className="w-28">Verdict</th>
                <th className="w-24">Severity</th>
                <th className="w-32">Serving → approved</th>
                <th className="w-16 text-right">Regions</th>
                <th className="w-28">Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {p.findings.map((f) => (
                <tr key={f.id}>
                  <td>
                    <Link to={`/runs/${f.run_id}`} className="font-mono text-xs hover:underline">
                      #{f.run_id}
                    </Link>
                  </td>
                  <td>
                    <VerdictTag verdict={f.verdict} />
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
                  <td className="text-xs text-ink-3">
                    {f.acknowledged ? "Acknowledged" : f.verdict === "PASS" ? "—" : "Open"}
                  </td>
                  <td className="text-right">
                    <Link to={`/findings/${f.id}`} className="text-xs hover:underline">
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
