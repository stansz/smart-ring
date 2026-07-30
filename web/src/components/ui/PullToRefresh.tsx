import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

/**
 * Pull-to-refresh: at scrollTop<=0, a downward drag reveals a spinner; releasing
 * past the threshold refetches all TanStack queries. Standalone PWAs disable
 * Chrome's native pull-to-reload, so this restores the gesture in-app.
 *
 * Touch-only (mouse/trackpad users keep native browser refresh).
 *
 * Implementation notes:
 * - The page uses `html { overflow: hidden }` + `body { overflow-y: auto }`
 *   (see index.css), so the scrolling element is the BODY, not the document
 *   root. `window.scrollY` is always 0 here — using it as the "at top?" check
 *   was the bug that silently killed scrolling on every move. We read the
 *   real scroll position from body/documentElement/window.
 * - touchmove uses `passive: false` + e.preventDefault() ONLY when the user
 *   is at the top AND clearly pulling down. Anywhere else, we never touch
 *   the default scroll behavior.
 * - pull / refreshing live in refs (not state) so the effect attaches the
 *   listeners exactly once and closures always see the latest values.
 *   A tiny `tick` counter forces a re-render only when the visual needs it.
 * - Throttled re-render: only flip `tick` when pull changes by >= 1px.
 */
const THRESHOLD = 70; // px to drag before release triggers refresh
const MAX_PULL = 90;  // px of visual translation allowed (resistance after)

/** The page is scrolled to the top of its actual scroll container. */
function isAtScrollTop(): boolean {
  // The HTML element has overflow:hidden, so it's not the scroll container;
  // the body is. Read every plausible scroll source and treat >0 as "scrolled".
  return (
    (document.body?.scrollTop ?? 0) <= 0 &&
    (document.documentElement?.scrollTop ?? 0) <= 0 &&
    window.scrollY <= 0
  );
}

export function PullToRefresh({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [tick, setTick] = useState(0);
  const pull = useRef(0);
  const refreshing = useRef(false);
  const startY = useRef<number | null>(null);
  const startX = useRef<number | null>(null);
  const triggered = useRef(false);

  useEffect(() => {
    const renderIfChanged = (nextPull: number) => {
      if (Math.abs(nextPull - pull.current) >= 1) {
        pull.current = nextPull;
        setTick((t) => t + 1);
      }
    };

    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      if (refreshing.current) return;
      startY.current = e.touches[0].clientY;
      startX.current = e.touches[0].clientX;
      triggered.current = false;
    };

    const onTouchMove = (e: TouchEvent) => {
      if (startY.current == null || startX.current == null) return;
      // If the page is scrolled ANYWHERE, this is a normal scroll — do nothing.
      // Never block the default scroll behavior. (Was the regression bug.)
      if (!isAtScrollTop()) {
        renderIfChanged(0);
        return;
      }
      const dy = e.touches[0].clientY - startY.current;
      const dx = e.touches[0].clientX - startX.current;
      // Ignore mostly-horizontal swipes (e.g. back-gesture, carousel).
      if (Math.abs(dx) > Math.abs(dy) * 1.5) {
        renderIfChanged(0);
        return;
      }
      if (dy <= 0) {
        renderIfChanged(0);
        return;
      }
      // At the top of the actual scroll container, pulling down: engage.
      // Block the browser's overscroll only here, so it can't consume the gesture.
      e.preventDefault();
      // Resistance: logarithmically damp so it doesn't whip the page.
      renderIfChanged(Math.min(MAX_PULL, Math.log10(1 + dy / 30) * 60));
    };

    const onTouchEnd = () => {
      if (startY.current == null) return;
      if (pull.current >= THRESHOLD && !triggered.current) {
        triggered.current = true;
        refreshing.current = true;
        pull.current = THRESHOLD;
        setTick((t) => t + 1);
        // Refetch everything (mirrors the post-sync blanket invalidate).
        queryClient.invalidateQueries().finally(() => {
          // Brief settle so the spinner is perceptible, then release.
          setTimeout(() => {
            refreshing.current = false;
            pull.current = 0;
            setTick((t) => t + 1);
          }, 400);
        });
      } else {
        renderIfChanged(0);
      }
      startY.current = null;
      startX.current = null;
    };

    const onTouchCancel = () => {
      startY.current = null;
      startX.current = null;
      renderIfChanged(0);
    };

    // passive: true for start/end/cancel (no preventDefault needed); passive: false
    // for move so we can block the browser's overscroll only when actually engaging.
    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("touchend", onTouchEnd, { passive: true });
    window.addEventListener("touchcancel", onTouchCancel, { passive: true });
    return () => {
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("touchcancel", onTouchCancel);
    };
  }, [queryClient]);

  // Read refs at render time. `tick` is the only thing that changes here.
  void tick;
  const offsetPx = pull.current;
  const isRefreshing = refreshing.current;

  return (
    <>
      <div
        aria-hidden
        className="pointer-events-none fixed left-0 right-0 top-0 z-40 flex justify-center"
        style={{
          transform: `translateY(${offsetPx - 40}px)`,
          transition: isRefreshing ? "transform 0.2s ease" : "transform 0.05s linear",
        }}
      >
        <div
          className={`mt-2 h-8 w-8 rounded-full bg-white/90 dark:bg-gray-800/90 shadow border border-gray-200 dark:border-gray-700 flex items-center justify-center ${
            isRefreshing ? "" : offsetPx > 10 ? "opacity-100" : "opacity-0"
          }`}
        >
          <svg
            className={isRefreshing ? "animate-spin" : ""}
            style={{ transform: isRefreshing ? undefined : `rotate(${offsetPx * 4}deg)` }}
            width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
          >
            <path d="M21 12a9 9 0 1 1-3-6.7" />
            <polyline points="21 4 21 10 15 10" />
          </svg>
        </div>
      </div>
      {children}
    </>
  );
}
