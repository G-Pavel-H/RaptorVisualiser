"""Generate every flavour of favicon + an Open Graph social card from a single
Pillow script. Run from repo root:

    backend/.venv/bin/python frontend/scripts/build_icons.py

Writes into frontend/src/. Re-run any time the visual changes.
"""
from __future__ import annotations

import math
import pathlib
from typing import Iterable, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = pathlib.Path(__file__).resolve().parent.parent / "src"
SCALE = 6  # supersample, downscale at the end → free anti-aliasing

# ---------- colors ----------
BG_OUTER = (7, 9, 13, 255)
BG_INNER = (19, 27, 41, 255)
CYAN_OUTER = (0, 168, 200, 255)
CYAN_INNER = (208, 255, 255, 255)
BLUE_OUTER = (37, 99, 235, 255)
BLUE_INNER = (207, 228, 255, 255)
EDGE = (58, 71, 99, 255)
RIM = (255, 255, 255, 140)


def lerp(a: Tuple[int, ...], b: Tuple[int, ...], t: float) -> Tuple[int, ...]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def radial_circle(canvas: Image.Image, cx: float, cy: float, r: float,
                  inner: Tuple[int, ...], outer: Tuple[int, ...],
                  rim: Tuple[int, ...] | None = RIM,
                  rim_w: float = 0.07) -> None:
    """Paint a soft radial-gradient disc by stamping concentric rings."""
    steps = max(8, int(r))
    for i in range(steps, 0, -1):
        t = 1 - (i / steps) ** 1.3
        # Highlight pushed slightly up-left of center for a glossy-bead look
        color = lerp(inner, outer, 1 - t)
        rr = r * (i / steps)
        ox = -r * 0.12 * (1 - i / steps)
        oy = -r * 0.18 * (1 - i / steps)
        cx2, cy2 = cx + ox, cy + oy
        ImageDraw.Draw(canvas).ellipse(
            [cx2 - rr, cy2 - rr, cx2 + rr, cy2 + rr],
            fill=color,
        )
    if rim is not None:
        ImageDraw.Draw(canvas).ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            outline=rim,
            width=max(1, int(r * rim_w)),
        )


def edge_curve(canvas: Image.Image, x1: float, y1: float, x2: float, y2: float,
               color: Tuple[int, ...] = EDGE, width: float = 0.04) -> None:
    """Quadratic-ish bezier curve from (x1,y1) to (x2,y2) sampled as points."""
    d = ImageDraw.Draw(canvas)
    midy = (y1 + y2) / 2
    # Sample with control points (x1, midy) and (x2, midy) → soft S-curve.
    pts = []
    for i in range(64):
        t = i / 63
        x = (1 - t) ** 3 * x1 + 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t ** 2 * x2 + t ** 3 * x2
        y = (1 - t) ** 3 * y1 + 3 * (1 - t) ** 2 * t * midy + 3 * (1 - t) * t ** 2 * midy + t ** 3 * y2
        pts.append((x, y))
    w = max(1, int(width * max(canvas.size)))
    for a, b in zip(pts, pts[1:]):
        d.line([a, b], fill=color, width=w)


def rounded_dark_bg(canvas: Image.Image, radius_ratio: float = 0.22) -> None:
    """Rounded square with vertical radial dark gradient."""
    w, h = canvas.size
    bg = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(bg)
    radius = int(min(w, h) * radius_ratio)
    # Vertical gradient stripes
    grad = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        grad.putpixel((0, y), lerp(BG_INNER, BG_OUTER, t * 0.9))
    grad = grad.resize((w, h))
    # Rounded mask
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=radius, fill=255)
    canvas.paste(grad, (0, 0), mask)


def draw_logo(canvas: Image.Image, *, with_bg: bool = True) -> None:
    """Paint the tree-icon mark centered on `canvas`."""
    w, h = canvas.size
    if with_bg:
        rounded_dark_bg(canvas)

    # Layout the three leaves + one summary node inside the central square area.
    size = min(w, h)
    cx0, cy0 = w / 2, h / 2
    # Coordinates relative to a 64-unit design space, then scaled.
    unit = size / 64
    summary = (cx0,             cy0 - 14 * unit)
    leaves = [
        (cx0 - 14 * unit, cy0 + 14 * unit),
        (cx0,             cy0 + 14 * unit),
        (cx0 + 14 * unit, cy0 + 14 * unit),
    ]
    # Edges first (so nodes sit on top).
    for lx, ly in leaves:
        edge_curve(canvas, summary[0], summary[1], lx, ly,
                   width=0.03 * (size / canvas.size[0]))

    radial_circle(canvas, *summary, r=9 * unit,
                  inner=CYAN_INNER, outer=CYAN_OUTER)
    for lx, ly in leaves:
        radial_circle(canvas, lx, ly, r=6 * unit,
                      inner=BLUE_INNER, outer=BLUE_OUTER)


def render_favicon(size: int) -> Image.Image:
    big = Image.new("RGBA", (size * SCALE, size * SCALE), (0, 0, 0, 0))
    draw_logo(big, with_bg=True)
    return big.resize((size, size), Image.LANCZOS)


def render_og_card() -> Image.Image:
    W, H = 1200, 630
    big = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
    # Dark backdrop with a soft cyan corner light.
    backdrop = Image.new("RGBA", big.size, BG_OUTER)
    glow = Image.new("RGBA", big.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse(
        [-400 * 2, -400 * 2, 1000 * 2, 1000 * 2],
        fill=(0, 229, 255, 35),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    backdrop = Image.alpha_composite(backdrop, glow)
    big.paste(backdrop, (0, 0))

    # Icon at left
    icon = Image.new("RGBA", (380 * 2, 380 * 2), (0, 0, 0, 0))
    draw_logo(icon, with_bg=True)
    big.paste(icon, (110 * 2, 125 * 2), icon)

    # Text
    d = ImageDraw.Draw(big)
    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    title_font, body_font, mono_font = None, None, None
    for p in font_paths:
        try:
            title_font = ImageFont.truetype(p, 132)
            body_font = ImageFont.truetype(p, 44)
            break
        except OSError:
            continue
    if title_font is None:
        title_font = ImageFont.load_default()
        body_font = ImageFont.load_default()

    text_x = 560 * 2
    d.text((text_x, 200 * 2), "RAPTOR.live", fill=(231, 234, 243, 255),
           font=title_font)
    d.text((text_x, 290 * 2), "watch a retrieval tree build itself", fill=(0, 229, 255, 255),
           font=body_font)
    d.text((text_x, 370 * 2), "live RAPTOR visualizer · paste text · query", fill=(168, 176, 194, 255),
           font=body_font)

    return big.resize((W, H), Image.LANCZOS)


def write(img: Image.Image, name: str) -> None:
    p = OUT / name
    img.save(p)
    print(f"  wrote {p.relative_to(OUT.parent)}  ({img.size[0]}×{img.size[1]})")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("Rendering favicons →", OUT)
    # Standard sizes
    write(render_favicon(16),  "favicon-16.png")
    write(render_favicon(32),  "favicon-32.png")
    write(render_favicon(48),  "favicon-48.png")
    write(render_favicon(180), "apple-touch-icon.png")
    write(render_favicon(192), "icon-192.png")
    write(render_favicon(512), "icon-512.png")

    # Multi-resolution .ico for legacy / Safari
    ico_src = render_favicon(256)
    ico_src.save(OUT / "favicon.ico",
                 sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"  wrote src/favicon.ico  (multi-res)")

    # Open Graph card for LinkedIn / Twitter / Slack previews
    write(render_og_card(), "og-image.png")
    print("done.")


if __name__ == "__main__":
    main()
