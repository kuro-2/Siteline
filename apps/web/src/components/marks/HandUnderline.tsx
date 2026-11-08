"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { underlinePaths } from "@/lib/marks";

const useIso = typeof window === "undefined" ? useEffect : useLayoutEffect;

/** Gold hand-drawn underline under a key phrase. Drawn once; static afterwards. */
export function HandUnderline({ id, children }: { id: string; children: ReactNode }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [width, setWidth] = useState(0);
  useIso(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setWidth(el.getBoundingClientRect().width);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const paths = width > 0 ? underlinePaths(id, width, 5) : [];
  return (
    <span ref={ref} className="relative inline-block whitespace-nowrap">
      {children}
      {width > 0 && (
        <svg
          aria-hidden="true"
          className="pointer-events-none absolute left-0 -bottom-[6px] overflow-visible"
          width={width}
          height={10}
        >
          {paths.map((d, i) => (
            <path key={i} d={d} pathLength={1} className="hand-stroke" style={{ animationDelay: `${i * 80}ms` }} />
          ))}
        </svg>
      )}
    </span>
  );
}
