"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { t } from "@/lib/i18n";

export type Snap = "peek" | "half" | "full";
const SNAP_VH: Record<Snap, number> = { peek: 15, half: 50, full: 92 };
const ORDER: Snap[] = ["peek", "half", "full"];

/**
 * The field-report sheet. Desktop (≥1024px): a 420px column beside the map.
 * Mobile: a bottom sheet with peek / half / full snap points, a drag handle that is also
 * a button, and dialog semantics when full. It never covers the whole map unasked.
 */
export function Sheet({
  label,
  snap,
  onSnap,
  children,
}: {
  label: string;
  snap: Snap;
  onSnap: (s: Snap) => void;
  children: ReactNode;
}) {
  const [drag, setDrag] = useState<number | null>(null); // current height in vh while dragging
  const start = useRef<{ y: number; vh: number } | null>(null);
  const [desktop, setDesktop] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const set = () => setDesktop(mq.matches);
    set();
    mq.addEventListener("change", set);
    return () => mq.removeEventListener("change", set);
  }, []);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      start.current = { y: e.clientY, vh: SNAP_VH[snap] };
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [snap],
  );
  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!start.current) return;
    const dy = ((start.current.y - e.clientY) / window.innerHeight) * 100;
    setDrag(Math.max(10, Math.min(95, start.current.vh + dy)));
  }, []);
  const onPointerUp = useCallback(() => {
    if (drag !== null) {
      const nearest = ORDER.reduce((a, b) => (Math.abs(SNAP_VH[b] - drag) < Math.abs(SNAP_VH[a] - drag) ? b : a));
      onSnap(nearest);
    }
    start.current = null;
    setDrag(null);
  }, [drag, onSnap]);

  const cycle = () => onSnap(ORDER[(ORDER.indexOf(snap) + 1) % ORDER.length] ?? "peek");
  const full = !desktop && snap === "full";

  return (
    <section
      aria-label={label}
      role={full ? "dialog" : "region"}
      aria-modal={full ? true : undefined}
      className={[
        "z-10 flex flex-col bg-sheet",
        // mobile bottom sheet
        "fixed inset-x-0 bottom-0 rounded-t-sheet shadow-float",
        // desktop column
        "lg:static lg:h-full lg:w-[420px] lg:shrink-0 lg:rounded-none lg:border-l lg:border-rule lg:shadow-none",
      ].join(" ")}
      style={
        desktop
          ? undefined
          : {
              height: `${drag ?? SNAP_VH[snap]}dvh`,
              transition: drag === null ? "height var(--t-sheet) var(--ease-out)" : "none",
            }
      }
    >
      <button
        type="button"
        className="flex h-6 w-full shrink-0 cursor-grab touch-none items-center justify-center lg:hidden"
        aria-label={snap === "full" ? t("explore.sheet_shrink") : t("explore.sheet_expand")}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onClick={() => drag === null && cycle()}
      >
        <span aria-hidden="true" className="h-1 w-10 rounded-pill bg-rule" />
      </button>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-8 lg:px-6 lg:pt-6">{children}</div>
    </section>
  );
}
