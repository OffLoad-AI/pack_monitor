import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { Region } from "../api/types";
import { ImageCompare } from "../components/ImageCompare";
import {
  ErrorState,
  Mono,
  SectionTitle,
  SeverityTag,
  Skeleton,
  VerdictTag,
} from "../components/primitives";
import { useToast } from "../components/Toast";
import { formatDate } from "../lib/format";
import { editTypeLabel, fieldLabel, methodHint, methodLabel } from "../lib/meaning";

/**
 * One edit often surfaces as several boxes — moving a logo changes its top edge,
 * its bottom edge and its sides, each a separate connected component. All of them
 * belong on the image, but listing them as three identical rows reads as three
 * problems. Group by what actually changed, and say how many areas it touched.
 */
function groupRegions(regions: Region[]) {
  const groups = new Map<string, { region: Region; keys: string[]; count: number }>();
  regions.forEach((r, i) => {
    const key = `${r.field_key}|${r.old}|${r.new}|${r.severity}|${r.edit_type}|${r.from_version}|${r.to_version}`;
    const existing = groups.get(key);
    const id = r.region_signature ?? `r${i}`;
    if (existing) {
      existing.count += 1;
      existing.keys.push(id);
    } else {
      groups.set(key, { region: r, keys: [id], count: 1 });
    }
  });
  return [...groups.values()];
}

function RegionRow({
  region,
  index,
  count,
  onFocus,
}: {
  region: Region;
  index: number;
  count: number;
  onFocus: () => void;
}) {
  return (
    <button
      onClick={onFocus}
      className="block w-full border-b border-line px-3 py-2 text-left hover:bg-surface-sunk"
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 font-mono text-2xs text-ink-4">{index + 1}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium">
              {fieldLabel(region.field_key)}
            </span>
            {region.acknowledged ? (
              <span className="shrink-0 rounded border border-line bg-surface-sunk px-1 text-2xs text-ink-3">
                acknowledged
              </span>
            ) : null}
          </div>

          {region.old || region.new ? (
            <div className="mt-0.5 font-mono tabular text-xs">
              <span className="text-ink-3 line-through">{region.old || "—"}</span>
              <span className="mx-1.5 text-ink-4">→</span>
              <span className="font-medium text-ink">{region.new || "—"}</span>
            </div>
          ) : null}

          <div className="mt-1 flex flex-wrap items-center gap-2">
            <SeverityTag severity={region.severity} />
            {region.edit_type ? (
              <span className="text-2xs text-ink-3">
                {editTypeLabel[region.edit_type] ?? region.edit_type}
              </span>
            ) : null}
            {region.from_version && region.to_version ? (
              <Mono className="text-ink-4">
                {region.from_version} → {region.to_version}
              </Mono>
            ) : null}
            {count > 1 ? (
              <span className="text-2xs text-ink-4">{count} areas</span>
            ) : null}
          </div>
        </div>
      </div>
    </button>
  );
}

export function FindingDetail() {
  const { id } = useParams();
  const findingId = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { notify } = useToast();
  const [note, setNote] = useState("");

  const finding = useQuery({
    queryKey: ["finding", findingId],
    queryFn: () => api.finding(findingId),
  });
  const images = useQuery({
    queryKey: ["finding-images", findingId],
    queryFn: () => api.findingImages(findingId),
  });
  // The approval date of the artwork this listing should be showing.
  const versions = useQuery({
    queryKey: ["product-versions", finding.data?.product_id],
    queryFn: () => api.productVersions(finding.data!.product_id),
    enabled: !!finding.data?.product_id,
  });

  const decide = useMutation({
    mutationFn: (decision: "ACKNOWLEDGED" | "ESCALATED") =>
      api.acknowledge(findingId, decision, note),
    onSuccess: (_d, decision) => {
      notify(decision === "ACKNOWLEDGED" ? "Acknowledged" : "Escalated");
      setNote("");
      qc.invalidateQueries({ queryKey: ["finding", findingId] });
      qc.invalidateQueries({ queryKey: ["findings"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (e: ApiError) => notify(e.message, "error"),
  });

  const undo = useMutation({
    mutationFn: () => api.unacknowledge(findingId),
    onSuccess: () => {
      notify("Acknowledgement removed");
      qc.invalidateQueries({ queryKey: ["finding", findingId] });
      qc.invalidateQueries({ queryKey: ["findings"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (e: ApiError) => notify(e.message, "error"),
  });

  if (finding.isLoading) return <div className="p-4"><Skeleton rows={10} /></div>;
  if (finding.isError)
    return (
      <div className="p-4">
        <ErrorState error={finding.error} retry={() => finding.refetch()} />
      </div>
    );

  const f = finding.data!;
  const chain = f.version_chain;
  const approvedOn =
    versions.data?.find((v) => v.id === f.current_version_id)?.approved_at ?? null;

  return (
    <div className="flex h-[calc(100vh-2.75rem)] flex-col">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-2">
        <button className="btn-ghost btn-sm" onClick={() => navigate(-1)}>
          ← Back
        </button>
        <div>
          <div className="flex items-center gap-2">
            <Link
              to={`/products/${f.product_id}`}
              className="text-sm font-semibold hover:underline"
            >
              {f.product_name}
            </Link>
            <Mono className="text-ink-3">{f.product_id}</Mono>
          </div>
          <div className="text-2xs text-ink-3">
            Run {f.run_id} · {f.source_name}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <VerdictTag verdict={f.verdict} />
          <SeverityTag severity={f.severity} />
        </div>

        <div className="ml-auto flex items-center gap-4 text-xs text-ink-3">
          <span title={methodHint[f.match_method]}>
            {methodLabel[f.match_method]}
            {f.confidence ? (
              <Mono className="ml-1.5 text-ink-2">{f.confidence.toFixed(2)}</Mono>
            ) : null}
          </span>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_23rem]">
        <div className="min-h-0 border-b border-line lg:border-b-0 lg:border-r">
          {images.isLoading ? (
            <Skeleton rows={10} />
          ) : images.isError ? (
            <div className="p-4">
              <ErrorState error={images.error} />
            </div>
          ) : (
            <ImageCompare
              scrapedUrl={images.data!.scraped_url}
              matchedUrl={images.data!.matched_url}
              currentUrl={images.data!.current_url}
              overlayUrl={images.data!.diff_overlay_url}
              regions={f.regions}
              matchedLabel={f.matched_version ?? "unknown"}
              currentLabel={f.current_version ?? "—"}
            />
          )}
        </div>

        <aside className="flex min-h-0 flex-col overflow-y-auto bg-surface">
          <div className="border-b border-line px-3.5 py-3">
            <div className="text-2xs font-semibold uppercase tracking-wide text-ink-3">
              Version
            </div>
            {f.verdict === "STALE_VERSION" ? (
              <p className="mt-1.5 text-sm">
                Serving <Mono className="font-medium">{f.matched_version}</Mono>,
                approved is <Mono className="font-medium">{f.current_version}</Mono>
                {approvedOn ? <>, approved {formatDate(approvedOn)}</> : null}.
              </p>
            ) : f.verdict === "PASS" ? (
              <p className="mt-1.5 text-sm">
                Serving the approved artwork,{" "}
                <Mono className="font-medium">{f.current_version}</Mono>.
              </p>
            ) : (
              <p className="mt-1.5 text-sm text-ink-2">
                No approved artwork explains this image. It may be a photograph
                taken by the seller rather than the brand's own file.
              </p>
            )}

            {chain.length > 2 ? (
              <div className="mt-2">
                <div className="text-2xs text-ink-3">
                  This listing is {chain.length - 1} versions behind:
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  {chain.map((v, i) => (
                    <span key={v} className="flex items-center gap-1">
                      <Mono
                        className={
                          i === 0
                            ? "rounded border border-material-line bg-material-bg px-1 text-material"
                            : i === chain.length - 1
                              ? "rounded border border-clear-line bg-clear-bg px-1 text-clear"
                              : "text-ink-3"
                        }
                      >
                        {v}
                      </Mono>
                      {i < chain.length - 1 ? (
                        <span className="text-ink-4">→</span>
                      ) : null}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          <div className="min-h-0 flex-1">
            <SectionTitle
              right={
                <span className="font-mono text-2xs text-ink-3">
                  {groupRegions(f.regions).length} change
                  {groupRegions(f.regions).length === 1 ? "" : "s"}
                </span>
              }
            >
              What changed
            </SectionTitle>
            {f.regions.length === 0 ? (
              <p className="px-3.5 py-4 text-sm text-ink-3">
                Nothing to review — this listing serves the approved artwork.
              </p>
            ) : (
              groupRegions(f.regions).map((g, i) => (
                <RegionRow
                  key={g.keys[0]}
                  region={g.region}
                  index={i}
                  count={g.count}
                  onFocus={() =>
                    window.dispatchEvent(
                      new CustomEvent("pcm:focus-region", { detail: g.keys[0] }),
                    )
                  }
                />
              ))
            )}
          </div>

          {f.regions.length > 0 ? (
            <div className="sticky bottom-0 border-t border-line bg-surface px-3.5 py-3">
              {f.acknowledged ? (
                <div className="space-y-2">
                  <p className="text-xs text-ink-3">
                    Reviewed and acknowledged. It will stay out of the queue until
                    new artwork is approved for this product.
                  </p>
                  <button
                    className="btn-ghost w-full justify-center"
                    onClick={() => undo.mutate()}
                    disabled={undo.isPending}
                  >
                    Move back to the queue
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  <label className="block">
                    <span className="text-2xs font-semibold uppercase tracking-wide text-ink-3">
                      Note
                    </span>
                    <textarea
                      className="field mt-1 resize-none"
                      rows={2}
                      placeholder="Why is this acceptable, or who is fixing it?"
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                    />
                  </label>
                  <div className="flex gap-2">
                    <button
                      className="btn-primary flex-1 justify-center"
                      onClick={() => decide.mutate("ACKNOWLEDGED")}
                      disabled={decide.isPending}
                    >
                      Acknowledge
                    </button>
                    <button
                      className="btn-ghost flex-1 justify-center"
                      onClick={() => decide.mutate("ESCALATED")}
                      disabled={decide.isPending}
                    >
                      Escalate
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
