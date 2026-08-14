import { useMemo } from "react";

/**
 * Word-level diff, computed in the browser.
 *
 * The backend already token-aligns these two strings and stores its opcodes, but
 * it does so on the *normalized* forms — case-folded, units unified — because
 * that is what classification must run on. What a reader needs to see is the
 * text as it was actually read. So the display diff is computed here, over the
 * raw readings, and the backend's classification is shown alongside it rather
 * than derived from it.
 *
 * Colour carries meaning here and only here: added and removed.
 */

type Op = { tag: "equal" | "insert" | "delete"; text: string };

function diffWords(a: string[], b: string[]): Op[] {
  // Longest common subsequence. The strings are one region's worth of text —
  // tens of tokens at most — so the quadratic table is free and exact.
  const n = a.length;
  const m = b.length;
  const table: number[][] = Array.from({ length: n + 1 }, () =>
    new Array(m + 1).fill(0),
  );
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      table[i][j] =
        a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);

  const ops: Op[] = [];
  let i = 0;
  let j = 0;
  const push = (tag: Op["tag"], text: string) => {
    const last = ops[ops.length - 1];
    if (last && last.tag === tag) last.text += ` ${text}`;
    else ops.push({ tag, text });
  };
  while (i < n && j < m) {
    if (a[i] === b[j]) push("equal", a[i++]), j++;
    else if (table[i + 1][j] >= table[i][j + 1]) push("delete", a[i++]);
    else push("insert", b[j++]);
  }
  while (i < n) push("delete", a[i++]);
  while (j < m) push("insert", b[j++]);
  return ops;
}

export function WordDiff({
  reference,
  marketplace,
}: {
  reference: string;
  marketplace: string;
}) {
  const ops = useMemo(
    () =>
      diffWords(
        reference.split(/\s+/).filter(Boolean),
        marketplace.split(/\s+/).filter(Boolean),
      ),
    [reference, marketplace],
  );

  if (!ops.length)
    return (
      <p className="text-xs text-ink-4">No text was read on either side.</p>
    );

  return (
    <p className="font-mono text-xs leading-6">
      {ops.map((op, i) => {
        if (op.tag === "equal")
          return (
            <span key={i} className="text-ink-2">
              {op.text}{" "}
            </span>
          );
        if (op.tag === "delete")
          return (
            <del
              key={i}
              className="rounded bg-material-bg px-1 text-material no-underline line-through"
              title="On the reference only"
            >
              {op.text}{" "}
            </del>
          );
        return (
          <ins
            key={i}
            className="rounded bg-clear-bg px-1 text-clear no-underline"
            title="On the marketplace image only"
          >
            {op.text}{" "}
          </ins>
        );
      })}
    </p>
  );
}
