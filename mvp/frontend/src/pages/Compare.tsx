import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorState } from "../components/primitives";

/**
 * The landing screen. Two drop zones, an optional label, one action.
 *
 * The empty state says what to do rather than apologising for being empty, and
 * the drop zones show dimensions and file size on drop — because the two things
 * most likely to be wrong about a pair are that you dropped the same file twice
 * or that one of them is a thumbnail.
 */
export function Compare() {
  const navigate = useNavigate();
  const [reference, setReference] = useState<File | null>(null);
  const [marketplace, setMarketplace] = useState<File | null>(null);
  const [label, setLabel] = useState("");

  const run = useMutation({
    mutationFn: () => api.create(reference!, marketplace!, label.trim() || undefined),
    onSuccess: (created) => navigate(`/comparisons/${created.id}`),
  });

  const ready = Boolean(reference && marketplace);
  const sameFile =
    reference && marketplace &&
    reference.name === marketplace.name &&
    reference.size === marketplace.size;

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="text-lg font-semibold text-ink">Compare a pair</h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-3">
        Drop your approved artwork and the image a marketplace is showing. The tool
        lines them up, finds what differs, reads both sides, and shows you every
        step of how it decided.
      </p>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <DropZone
          title="Reference artwork"
          hint="The file you approved."
          file={reference}
          onFile={setReference}
        />
        <DropZone
          title="Marketplace image"
          hint="What the listing is showing."
          file={marketplace}
          onFile={setMarketplace}
        />
      </div>

      {sameFile ? (
        <p className="mt-3 rounded border border-cosmetic-line bg-cosmetic-bg px-3 py-2 text-xs text-cosmetic">
          Both slots hold what looks like the same file. That is a valid comparison —
          it will come back as an identical-file match — but check it is what you meant.
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="flex-1 min-w-[16rem]">
          <span className="mb-1 block text-xs font-medium text-ink-2">
            Label (optional)
          </span>
          <input
            className="field"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. SKU001 front"
          />
        </label>
        <button
          className="btn-primary"
          disabled={!ready || run.isPending}
          onClick={() => run.mutate()}
        >
          {run.isPending ? "Comparing…" : "Compare"}
        </button>
      </div>

      {run.isError ? (
        <div className="mt-3">
          <ErrorState error={run.error} />
        </div>
      ) : null}

      <BatchPanel />
    </div>
  );
}

function DropZone({
  title,
  hint,
  file,
  onFile,
}: {
  title: string;
  hint: string;
  file: File | null;
  onFile: (f: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [dims, setDims] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  const accept = (f: File | undefined) => {
    if (!f) return;
    onFile(f);
    const url = URL.createObjectURL(f);
    setPreview((old) => {
      if (old) URL.revokeObjectURL(old);
      return url;
    });
    const img = new Image();
    img.onload = () => setDims(`${img.naturalWidth} x ${img.naturalHeight}`);
    img.src = url;
  };

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-xs font-medium text-ink-2">{title}</span>
        <span className="text-2xs text-ink-4">{hint}</span>
      </div>
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          accept(e.dataTransfer.files[0]);
        }}
        className={`flex h-52 w-full flex-col items-center justify-center gap-2 rounded border-2 border-dashed px-4 text-center transition-colors ${
          over
            ? "border-focus bg-[#eef3fd]"
            : file
              ? "border-line-strong bg-surface"
              : "border-line-strong bg-surface hover:bg-surface-sunk"
        }`}
      >
        {preview ? (
          <img
            src={preview}
            alt=""
            className="max-h-32 max-w-full rounded border border-line object-contain"
          />
        ) : (
          <span className="text-sm text-ink-3">
            Drop an image here, or click to choose
          </span>
        )}
        {file ? (
          <span className="max-w-full truncate font-mono text-2xs text-ink-3">
            {file.name} · {dims ?? "…"} · {(file.size / 1024).toFixed(0)} KB
          </span>
        ) : null}
      </button>
      <input
        ref={input}
        type="file"
        accept="image/*"
        className="sr-only"
        onChange={(e) => accept(e.target.files?.[0])}
      />
    </div>
  );
}

/** Batch mode: a folder of files following the `ref__` / `mkt__` convention. */
function BatchPanel() {
  const navigate = useNavigate();
  const [files, setFiles] = useState<File[]>([]);

  const pairs = (() => {
    const refs = new Set<string>();
    const mkts = new Set<string>();
    for (const f of files) {
      const m = /^(ref|mkt)__(.+?)\.[A-Za-z0-9]+$/.exec(f.name);
      if (!m) continue;
      (m[1] === "ref" ? refs : mkts).add(m[2]);
    }
    const matched = [...refs].filter((k) => mkts.has(k)).sort();
    const lonely = [...refs, ...mkts].filter(
      (k) => !(refs.has(k) && mkts.has(k)),
    );
    return { matched, lonely: [...new Set(lonely)].sort() };
  })();

  const run = useMutation({
    mutationFn: () => api.createBatch(files),
    onSuccess: () => navigate("/history"),
  });

  return (
    <section className="mt-10 border-t border-line pt-5">
      <h2 className="text-sm font-medium text-ink">Compare several pairs</h2>
      <p className="mt-1 max-w-2xl text-sm text-ink-3">
        Choose a folder of files named{" "}
        <code className="font-mono text-xs">ref__name.png</code> and{" "}
        <code className="font-mono text-xs">mkt__name.jpg</code>. Matching names are
        paired up; anything left over is listed rather than quietly skipped.
      </p>

      <label className="btn-ghost mt-3 inline-flex cursor-pointer">
        Choose files
        <input
          type="file"
          multiple
          accept="image/*"
          className="sr-only"
          onChange={(e) => setFiles([...(e.target.files ?? [])])}
        />
      </label>

      {files.length ? (
        <div className="mt-3 rounded border border-line bg-surface px-3.5 py-3">
          <p className="text-sm text-ink-2">
            {pairs.matched.length} pair{pairs.matched.length === 1 ? "" : "s"} detected
            from {files.length} file{files.length === 1 ? "" : "s"}.
          </p>
          {pairs.matched.length ? (
            <ul className="mt-2 max-h-40 space-y-0.5 overflow-auto font-mono text-2xs text-ink-3">
              {pairs.matched.map((k) => (
                <li key={k}>{k}</li>
              ))}
            </ul>
          ) : null}
          {pairs.lonely.length ? (
            <p className="mt-2 text-xs text-cosmetic">
              Unpaired: {pairs.lonely.join(", ")}
            </p>
          ) : null}
          <button
            className="btn-primary btn-sm mt-3"
            disabled={!pairs.matched.length || run.isPending}
            onClick={() => run.mutate()}
          >
            {run.isPending ? "Starting…" : `Compare ${pairs.matched.length} pairs`}
          </button>
          {run.isError ? (
            <div className="mt-2">
              <ErrorState error={run.error} />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
