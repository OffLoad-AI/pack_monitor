import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

interface Toast {
  id: number;
  message: string;
  tone: "info" | "error";
}

const ToastContext = createContext<{
  notify: (message: string, tone?: Toast["tone"]) => void;
}>({ notify: () => {} });

export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = useCallback((message: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, tone }]);
    window.setTimeout(
      () => setToasts((t) => t.filter((x) => x.id !== id)),
      tone === "error" ? 6000 : 3200,
    );
  }, []);

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 flex-col items-center gap-2"
        role="status"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto rounded border px-3 py-2 text-sm shadow-sm ${
              t.tone === "error"
                ? "border-material-line bg-material-bg text-material"
                : "border-line bg-surface-rail text-white"
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
