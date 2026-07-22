"""Generate PWA icons for the Smart Ring dashboard.

One-shot. Outputs PNGs into dashboard/:
  - icon-192.png, icon-512.png        (regular, transparent bg, any-maskable)
  - icon-maskable-192.png, icon-512.png  (full-bleed bg + ring in 80% safe zone)
  - icon-apple-180.png                 (solid bg, no transparency, iOS)

Run: venv/bin/python3 scripts/gen_icons.py
"""
from PIL import Image, ImageDraw

THEME = (37, 99, 235)        # blue-600 (#2563eb)
BG_DARK = (17, 24, 39)       # gray-900 (#111827) — matches dark mode bg
BG_LIGHT = (249, 250, 251)   # gray-50 (#f9fafb) — matches light mode bg
WHITE = (255, 255, 255, 255)
RING_HIGHLIGHT = (96, 165, 250)  # blue-400 — inner highlight band


def draw_ring(draw, cx, cy, outer_r, ring_width):
    """Draw a ring: outer disc in THEME, inner punch-out, thin highlight band on the inside."""
    cx, cy, outer_r, ring_width = int(cx), int(cy), int(outer_r), int(ring_width)
    # Outer filled disc
    draw.ellipse(
        [cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r],
        fill=THEME,
    )
    # Inner punch-out (transparent)
    inner_r = outer_r - ring_width
    draw.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=(0, 0, 0, 0),
    )
    # Subtle highlight band on the inner edge — reads as a beveled physical ring
    highlight_r = inner_r + max(1, ring_width // 5)
    draw.ellipse(
        [cx - highlight_r, cy - highlight_r, cx + highlight_r, cy + highlight_r],
        outline=RING_HIGHLIGHT,
        width=max(1, ring_width // 8),
    )


def make_regular(size):
    """Transparent background; ring fills ~80% of canvas."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size / 2
    outer_r = size * 0.42
    ring_width = max(2, size * 0.10)
    draw_ring(draw, cx, cy, outer_r, ring_width)
    return img


def make_maskable(size):
    """Solid theme-colored background; ring sized to 80% safe zone."""
    img = Image.new("RGBA", (size, size), THEME + (255,))
    draw = ImageDraw.Draw(img)
    cx = cy = size / 2
    # Safe zone is the center 80% — ring sits at 70% to leave breathing room
    outer_r = size * 0.34
    ring_width = max(2, size * 0.085)
    draw_ring(draw, cx, cy, outer_r, ring_width)
    return img


def make_apple(size):
    """iOS: solid bg, no transparency, ring prominent. Apple icons get rounded by the OS."""
    img = Image.new("RGBA", (size, size), BG_DARK + (255,))
    draw = ImageDraw.Draw(img)
    cx = cy = size / 2
    outer_r = size * 0.40
    ring_width = max(2, size * 0.10)
    draw_ring(draw, cx, cy, outer_r, ring_width)
    # Flatten to RGB (no alpha) so PNG has no transparency channel
    return img.convert("RGB")


def main():
    outputs = [
        ("icon-192.png", make_regular(192)),
        ("icon-512.png", make_regular(512)),
        ("icon-maskable-192.png", make_maskable(192)),
        ("icon-maskable-512.png", make_maskable(512)),
        ("icon-apple-180.png", make_apple(180)),
    ]
    for name, img in outputs:
        # Apple icon saved as RGB; others stay RGBA
        path = f"dashboard/{name}"
        if img.mode == "RGB":
            img.save(path, "PNG")
        else:
            img.save(path, "PNG")
        print(f"wrote {path} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
