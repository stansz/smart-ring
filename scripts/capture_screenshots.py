#!/usr/bin/env python3
"""Capture dashboard screenshots via headless Playwright/Chromium.

Loads each dashboard tab from a running API instance, forces dark mode, waits
for charts to paint, and saves a full-page PNG. Designed for the demo-data
screenshot workflow (run against a temp API pointed at the demo DB) but works
against any base URL.

Usage::

    # temp API on :8001 (pointed at the demo DB via DATABASE_URL)
    python scripts/capture_screenshots.py --base http://127.0.0.1:8001

Outputs: docs/screenshots/{dashboard,analytics,garmin,admin}.png
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "docs" / "screenshots"

# (tab_hash, css guard, wait-note). Guard is a selector that proves the tab's
# signature content has rendered (Recharts SVG, a table row, etc.).
TABS = [
    ("dashboard", "svg", "Recharts + DayRing SVGs"),
    ("analytics", ".recharts-wrapper", "trend charts"),
    ("garmin", "table tbody tr, a[href*='activities']", "activity list rows"),
    ("admin", "table", "sync log + ring status"),
]

WIDTH = 1440
HEIGHT = 900
SCALE_FACTOR = 2  # must match device_scale_factor in main()


def force_dark(page) -> None:
    """Enable dark mode: set localStorage then add the class, then reload so
    the React app reads the persisted preference on init."""
    page.evaluate("localStorage.setItem('darkMode', 'true')")
    page.evaluate("document.documentElement.classList.add('dark')")
    page.reload(wait_until="networkidle")


def neutralize_pwa_scroll(page) -> None:
    """Temporarily neutralize the PWA scroll shell for full-page capture.

    The app uses the standard mobile-app-shell pattern (web/src/index.css):
    ``html { overflow: hidden }`` + ``body { height: 100vh; overflow-y: auto }``
    — body is a *fixed-height inner scroll container*. Full-page screenshots
    then only rasterize the initial viewport: the capture extends to the full
    body scroll height but everything below the fold comes out pure black.

    Fix: force the body to flow naturally (auto height, no clipping) so the
    page is a normal document and full-page capture paints end-to-end.
    Verified: every section paints (see capture_tab's section check).
    """
    page.evaluate("""() => {
        document.documentElement.style.overflow = 'visible';
        document.body.style.height = 'auto';
        document.body.style.overflow = 'visible';
    }""")


def capture_tab(page, base: str, tab: str, guard: str, out: Path) -> None:
    """Navigate to a tab, wait for its signature content, screenshot."""
    page.goto(f"{base}/#{tab}", wait_until="networkidle")
    # Fragment-only navigations don't reload the document; the app reads the
    # hash at mount time (App.tsx), so force a real reload for the tab switch
    # to take effect.
    page.reload(wait_until="networkidle")
    page.wait_for_load_state("networkidle")
    # Guard: signature content present.
    try:
        page.wait_for_selector(guard, timeout=8000)
    except Exception:
        pass  # best-effort; still capture whatever rendered
    # Settle time for Recharts mount animations + Leaflet tiles.
    time.sleep(2.5)
    # Full-page capture. The PWA scroll shell (html overflow:hidden + body
    # height:100vh) makes plain full_page capture leave everything below the
    # fold pure black — neutralize the shell first so the whole page paints.
    neutralize_pwa_scroll(page)
    time.sleep(1.0)
    page.screenshot(path=str(out), full_page=True, animations="disabled")
    body_h = page.evaluate("document.body.scrollHeight")
    try:
        from PIL import Image
        im = Image.open(out).convert("RGB")
        captured_h = im.size[1] // SCALE_FACTOR
        status = "OK" if abs(captured_h - body_h) < 40 else "WARN (page may be cut!)"
        # Completeness guard: every h2 section must have painted content at its
        # capture-time position. This is the exact pre-fix failure mode — the
        # capture reached full height but sections below the initial viewport
        # rasterized pure black. (The page bottom itself may legitimately be
        # empty min-h-screen background, so we check sections, not the tail.)
        px = im.load()
        w = im.size[0]
        sections = page.evaluate(
            "[...document.querySelectorAll('h2')].map(e => "
            "Math.round(e.getBoundingClientRect().top))"
        )
        # Robust per-section paint check: fraction of non-background pixels in
        # a band just inside each heading. (Simple row variance is fragile —
        # a 30px sampling stride can miss narrow glyphs entirely.)
        bg = (17, 24, 39)  # slate-900, the app's dark page background
        empty = []
        for top in sections:
            if top < 0 or top >= body_h:
                continue
            fracs = []
            for dy in (8, 16, 24):
                row = [px[x, (top + dy) * SCALE_FACTOR] for x in range(0, w, 5)]
                fracs.append(
                    sum(1 for c in row
                        if sum(abs(c[i] - bg[i]) for i in range(3)) > 60)
                    / len(row)
                )
            if max(fracs) < 0.03:
                empty.append(top)
        sec = "OK" if not empty else f"WARN empty sections at y={empty} (not painted!)"
        print(f"  captured {tab:10} -> {out.name} ({out.stat().st_size // 1024} KB)"
              f" [body={body_h}px, png={captured_h}px {status}, sections {sec}]")
    except ImportError:
        print(f"  captured {tab:10} -> {out.name} ({out.stat().st_size // 1024} KB)"
              f" [body={body_h}px — install Pillow for auto height check]")


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture dashboard screenshots.")
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--tabs", nargs="*", default=None,
                    help="subset of tabs to capture (default: all)")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    tabs = [(t, g, n) for (t, g, n) in TABS if not args.tabs or t in args.tabs]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT},
                                device_scale_factor=2)  # retina-quality PNGs
        # First load: set dark mode, reload so the app reads it on init.
        page.goto(args.base, wait_until="networkidle")
        force_dark(page)

        for tab, guard, note in tabs:
            out = args.out / f"{tab}.png"
            capture_tab(page, args.base, tab, guard, out)

        browser.close()
    print(f"Done — {len(tabs)} screenshots in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
