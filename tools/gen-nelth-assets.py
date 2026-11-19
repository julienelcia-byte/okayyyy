#!/usr/bin/env python3
# Copyright 2026 Optix AI. Licensed under the Apache License, Version 2.0.
"""Generates the NELTH brand assets used by tools/nelthize-framework.py.

Every asset replaces a Phi-branded image inside the prebuilt framework:

  wordmark-light-155x64.png / wordmark-light-78x32.png   -> chrome_{200,100}_percent.pak id 40262
  wordmark-grey-155x64.png  / wordmark-grey-78x32.png    -> chrome_{200,100}_percent.pak id 40263
  tile-inset-256.png / tile-inset-128.png                -> resources.pak ids 14152 / 14200
  tile-128/256/512.png                                   -> resources.pak ids 14154/14155/14156
  avatar-plain-128.png, avatar-L/K/M-128.png             -> resources.pak ids 15659/15163/15687/15739
  brand-155x80.png                                       -> client/resources/onboarding/brand.png

The master art is the 1024 px Nelth tile (the download page logo). The "N"
silhouette is extracted from it once, then redrawn monochrome for the
profile-avatar tiles, exactly like the upstream swirl+letter tiles.

Usage:  python3 tools/gen-nelth-assets.py [--master path] [--check]
Outputs land in tools/nelth-assets/ (committed, so CI needs no fonts).
"""

import argparse
import os

from PIL import Image, ImageDraw, ImageFont

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(REPO, "tools", "nelth-assets")
DEFAULT_MASTER = "/home/z/my-project/public/nelth-logo.png"

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

TEXT_DARK = (32, 33, 36, 255)      # light-mode wordmark text (was black)
TEXT_GREY = (154, 160, 166, 255)   # dark-mode wordmark text (was mid grey)
TILE_BLACK = (5, 6, 5, 255)        # avatar tile background (was pure black)


def load_master(path):
    return Image.open(path).convert("RGB")


def extract_n_silhouette(master):
    """The white N silhouette (RGBA) cropped tight, from the green neon art.

    Connected-component labelling (BFS) separates the outer rounded-square
    ring from the N letterform: the ring is the component with the largest
    bounding box, the N is the largest component comfortably inside it.
    """
    from collections import deque
    import numpy as np
    a = np.asarray(master).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    green = (g > 90) & (g > r + 40) & (g > b + 40)
    h, w = green.shape

    labels = np.zeros((h, w), dtype=np.int32)
    comps = []
    ys, xs = np.nonzero(green)
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        if labels[sy, sx]:
            continue
        cid = len(comps) + 1
        q = deque([(sy, sx)])
        labels[sy, sx] = cid
        pixels = []
        while q:
            y, x = q.popleft()
            pixels.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and green[ny, nx] \
                        and not labels[ny, nx]:
                    labels[ny, nx] = cid
                    q.append((ny, nx))
        comps.append(pixels)

    if not comps:
        raise SystemExit("no green artwork found in the master")

    stats = []
    for pixels in comps:
        pys = [p[0] for p in pixels]
        pxs = [p[1] for p in pixels]
        stats.append((len(pixels), min(pxs), min(pys), max(pxs), max(pys)))
    max_span = max(max(s[3] - s[1], s[4] - s[2]) for s in stats)
    inner = [s for s in stats
             if max(s[3] - s[1], s[4] - s[2]) <= max_span * 0.8]
    area, x0, y0, x1, y1 = max(inner, key=lambda s: s[0])

    mask = np.zeros((h, w), dtype=bool)
    # re-walk the pixels of the winning component
    for pixels, s in zip(comps, stats):
        if s == (area, x0, y0, x1, y1):
            for py, px2 in pixels:
                mask[py, px2] = True
    sub = mask[y0:y1 + 1, x0:x1 + 1]
    return Image.fromarray((sub * 255).astype("uint8")).convert("RGBA")


def over(dst, src, xy):
    """Composite src over dst at xy (works for any sizes, straight alpha)."""
    dst.paste(src, xy, src.split()[3])


def rounded_tile(size, radius_ratio=0.23, fill=TILE_BLACK):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rad = int(size * radius_ratio)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=rad, fill=fill)
    return img


def avatar_tile(size, sil, letter=None, n_ratio=0.62, letter_ratio=0.30):
    """Black tile + white N + optional letter at the top right (upstream look)."""
    tile = rounded_tile(size)
    n_w = int(size * n_ratio)
    n_h = int(sil.height * n_w / sil.width)
    n = sil.resize((n_w, n_h), Image.LANCZOS)
    over(tile, n, ((size - n_w) // 2, (size - n_h) // 2))
    if letter:
        fsize = int(size * letter_ratio / 0.729)
        font = ImageFont.truetype(FONT_BOLD, fsize)
        d = ImageDraw.Draw(tile)
        bbox = d.textbbox((0, 0), letter, font=font)
        lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text((size - lw - int(size * 0.045) - bbox[0], int(size * 0.035) - bbox[1]),
               letter, font=font, fill=(255, 255, 255, 255))
    return tile


def tile_inset(size, art, box):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile = art.convert("RGBA").resize((box[2] - box[0], box[3] - box[1]),
                                      Image.LANCZOS)
    over(canvas, tile, (box[0], box[1]))
    return canvas


def wordmark(canvas_wh, tile_h, text_px, text_color, sil, margin=0.05):
    """Emblem tile + 'Nelth' lockup on a transparent canvas (alias of v2)."""
    return wordmark_v2(canvas_wh, tile_h, text_px, text_color, sil, margin)


def wordmark_v2(canvas_wh, tile_h, text_px, text_color, sil, margin=0.05,
                text_dx=0.10, art=None):
    """Emblem tile + 'Nelth' text on a transparent canvas.

    The emblem is the real tile art downscaled (art=), falling back to a
    drawn tile + green silhouette. The font size shrinks until the word fits.
    """
    w, h = canvas_wh
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    tx = int(h * margin)
    if art is not None:
        emblem = art.convert("RGBA").resize((tile_h, tile_h), Image.LANCZOS)
    else:
        emblem = rounded_tile(tile_h)
        n_w = int(tile_h * 0.56)
        n_h = int(sil.height * n_w / sil.width)
        n = sil.resize((n_w, n_h), Image.LANCZOS)
        green_n = Image.new("RGBA", n.size, (0, 0, 0, 0))
        px, gpx = n.load(), green_n.load()
        for y in range(n.height):
            for x in range(n.width):
                a = px[x, y][3]
                if a:
                    gpx[x, y] = (74, 222, 128, a)
        over(emblem, green_n, ((tile_h - n_w) // 2, (tile_h - n_h) // 2))
    over(img, emblem, (tx, (h - tile_h) // 2))
    max_w = w - (tx + tile_h + int(h * text_dx)) - int(h * margin)
    probe = ImageDraw.Draw(img)
    while text_px > 8:
        font = ImageFont.truetype(FONT_BOLD, text_px)
        bbox = probe.textbbox((0, 0), "Nelth", font=font)
        if bbox[2] - bbox[0] <= max_w and bbox[3] - bbox[1] <= int(h * 0.86):
            break
        text_px -= 1
    bbox = probe.textbbox((0, 0), "Nelth", font=font)
    th = bbox[3] - bbox[1]
    d = ImageDraw.Draw(img)
    d.text((tx + tile_h + int(h * text_dx) - bbox[0],
            (h - th) // 2 - bbox[1]), "Nelth", font=font, fill=text_color)
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--master", default=DEFAULT_MASTER)
    ap.add_argument("--check", action="store_true",
                    help="verify assets exist and match expected sizes")
    args = ap.parse_args()

    expected = {
        "wordmark-light-155x64.png": (155, 64),
        "wordmark-light-78x32.png": (78, 32),
        "wordmark-grey-155x64.png": (155, 64),
        "wordmark-grey-78x32.png": (78, 32),
        "tile-inset-256.png": (256, 256),
        "tile-inset-128.png": (128, 128),
        "tile-128.png": (128, 128),
        "tile-256.png": (256, 256),
        "tile-512.png": (512, 512),
        "avatar-plain-128.png": (128, 128),
        "avatar-L-128.png": (128, 128),
        "avatar-K-128.png": (128, 128),
        "avatar-M-128.png": (128, 128),
        "brand-155x80.png": (155, 80),
    }
    if args.check:
        missing = []
        for name, (w, h) in expected.items():
            p = os.path.join(ASSET_DIR, name)
            if not os.path.exists(p):
                missing.append(name)
                continue
            if Image.open(p).size != (w, h):
                missing.append(f"{name} (bad size)")
        if missing:
            raise SystemExit("asset check FAILED: " + ", ".join(missing))
        print(f"asset check OK: {len(expected)} assets")
        return

    os.makedirs(ASSET_DIR, exist_ok=True)
    master = load_master(args.master)
    sil = extract_n_silhouette(master)
    sil.save(os.path.join(ASSET_DIR, "_silhouette.png"))

    art = master
    # pak wordmarks (emblem + Nelth)
    wordmark_v2((155, 64), 52, 40, TEXT_DARK, sil, art=art).save(
        os.path.join(ASSET_DIR, "wordmark-light-155x64.png"))
    wordmark_v2((78, 32), 26, 20, TEXT_DARK, sil, art=art).save(
        os.path.join(ASSET_DIR, "wordmark-light-78x32.png"))
    wordmark_v2((155, 64), 52, 40, TEXT_GREY, sil, art=art).save(
        os.path.join(ASSET_DIR, "wordmark-grey-155x64.png"))
    wordmark_v2((78, 32), 26, 20, TEXT_GREY, sil, art=art).save(
        os.path.join(ASSET_DIR, "wordmark-grey-78x32.png"))

    # full-bleed tiles
    for s in (128, 256, 512):
        art.resize((s, s), Image.LANCZOS).save(
            os.path.join(ASSET_DIR, f"tile-{s}.png"))

    # inset tiles (transparent margin, upstream geometry)
    tile_inset(256, art, (22, 25, 234, 236)).save(
        os.path.join(ASSET_DIR, "tile-inset-256.png"))
    tile_inset(128, art, (11, 12, 117, 118)).save(
        os.path.join(ASSET_DIR, "tile-inset-128.png"))

    # avatar tiles (black tile + white N [+ letter])
    for name, letter in (("avatar-plain-128", None), ("avatar-L-128", "L"),
                         ("avatar-K-128", "K"), ("avatar-M-128", "M")):
        avatar_tile(128, sil, letter).save(
            os.path.join(ASSET_DIR, f"{name}.png"))

    # onboarding brand (was a black "Phi" wordmark on transparency)
    wordmark_v2((155, 80), 56, 40, (11, 11, 11, 255), sil, art=art).save(
        os.path.join(ASSET_DIR, "brand-155x80.png"))

    print(f"assets written to {ASSET_DIR}")


if __name__ == "__main__":
    main()
