"""Shared Laya image preparation for coinpoker-help (server and training use this one module).

Rust (`crates/ingest/src/laya/geometry.rs`) cuts region crops from the frame with the same
content-rect rule as `content_rect` below and sends them to `scripts/laya-server.py`. For a
`glyphs` pass the server calls `segment_glyphs` on the amount crop, so training crops and live
crops come from identical code. numpy and Pillow are imported lazily; this module never writes
pixels anywhere.
"""

TITLE_BAR_PX = 28
TITLE_BAR_RANGE = (20, 48)
CONTENT_ASPECT = 1.3677
MAX_GLYPHS = 8
GLYPH_STYLES = ("white", "gold")


def content_rect(w, h):
    """(x0, y0, cw, ch) of the content area below CoinPoker's unscaled title bar."""
    t = h - int(round(w / CONTENT_ASPECT))
    if TITLE_BAR_RANGE[0] <= t <= TITLE_BAR_RANGE[1]:
        return 0, t, w, h - t
    avail_h = h - TITLE_BAR_PX
    if avail_h <= 0:
        return 0, TITLE_BAR_PX, w, 0
    if w / avail_h > CONTENT_ASPECT:  # pillarbox
        cw = int(round(avail_h * CONTENT_ASPECT))
        return (w - cw) // 2, TITLE_BAR_PX, cw, avail_h
    ch = int(round(w / CONTENT_ASPECT))  # letterbox
    return 0, TITLE_BAR_PX + (avail_h - ch) // 2, w, ch


def box_px(box, w, h):
    """Normalized content box -> integer px (floor start, ceil end, clamped)."""
    import math

    x0, y0, cw, ch = content_rect(w, h)
    u0, v0, u1, v1 = box
    a = max(0, min(w, int(math.floor(x0 + u0 * cw))))
    b = max(0, min(h, int(math.floor(y0 + v0 * ch))))
    c = max(0, min(w, int(math.ceil(x0 + u1 * cw))))
    d = max(0, min(h, int(math.ceil(y0 + v1 * ch))))
    return a, b, c, d


def _text_score(arr, style):
    import numpy as np

    r, g, b = arr[..., 0].astype(np.float32), arr[..., 1].astype(np.float32), arr[..., 2].astype(np.float32)
    if style == "white":
        # bright and unsaturated: the minimum channel, minus a saturation penalty
        mn = np.minimum(np.minimum(r, g), b)
        mx = np.maximum(np.maximum(r, g), b)
        return mn - 0.5 * (mx - mn)
    if style == "gold":
        # yellow/gold of any brightness (folded players are drawn dimmer)
        return np.minimum(r, g * 1.25) - b
    raise ValueError("unknown glyph style")


TEXT_MIN_PEAK = {"white": 150.0, "gold": 55.0}


def _text_mask(arr, style):
    """Adaptive text mask: background level + 45% of the way to the bright text level.

    Relative thresholds keep dim (folded) and bright amounts, and the antialiased decimal point, in the
    same mask; an absolute floor on the peak means a crop without text yields an empty mask.
    """
    import numpy as np

    s = _text_score(arr, style)
    peak = float(np.percentile(s, 99.5))
    if peak < TEXT_MIN_PEAK[style]:
        return np.zeros(s.shape, dtype=bool)
    bg = float(np.median(s))
    return s > bg + 0.45 * (peak - bg)


def _components(mask):
    import numpy as np

    h, w = mask.shape
    lab = np.zeros((h, w), dtype=np.int32)
    comps = []
    n = 0
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if lab[y, x]:
            continue
        n += 1
        stack = [(y, x)]
        lab[y, x] = n
        x0 = x1 = x
        y0 = y1 = y
        area = 0
        while stack:
            cy, cx = stack.pop()
            area += 1
            x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not lab[ny, nx]:
                        lab[ny, nx] = n
                        stack.append((ny, nx))
        comps.append({"x0": x0, "x1": x1 + 1, "y0": y0, "y1": y1 + 1, "area": area})
    return comps


def segment_glyphs(img, style, max_glyphs=MAX_GLYPHS):
    """Split an amount crop into per-character glyph images.

    Returns (glyph_images, info). info = {"n", "overflow", "line": [y0, y1], "boxes": [[x0,y0,x1,y1]...]}.
    The text line is the tallest component's row band; components outside it are ignored. Components
    overlapping in x are merged (one character). A glyph image is a square window of the original crop
    centred on the character (side = max(line height + 6, width + 6)), padded with edge pixels.
    """
    import numpy as np
    from PIL import Image

    arr = np.asarray(img.convert("RGB")).astype(np.int16)
    mask = _text_mask(arr, style)
    comps = [c for c in _components(mask) if c["area"] >= 2]
    info = {"n": 0, "overflow": False, "line": None, "boxes": []}
    if not comps:
        return [], info
    tall = max(comps, key=lambda c: (c["y1"] - c["y0"], c["area"]))
    ly0, ly1 = tall["y0"], tall["y1"]
    lh = ly1 - ly0
    if lh < 5:
        return [], info
    band = [c for c in comps if c["y1"] > ly0 - 1 and c["y0"] < ly1 + max(2, lh // 4)
            and (c["y1"] - c["y0"] >= 0.45 * lh or c["y0"] >= ly0 + 0.5 * lh)]
    band.sort(key=lambda c: c["x0"])
    merged = []
    for c in band:
        if merged and c["x0"] < merged[-1]["x1"] - 1:
            m = merged[-1]
            m.update(x0=min(m["x0"], c["x0"]), x1=max(m["x1"], c["x1"]), y0=min(m["y0"], c["y0"]),
                     y1=max(m["y1"], c["y1"]), area=m["area"] + c["area"])
        else:
            merged.append(dict(c))
    # a text line is a run of characters: drop anything separated by a gap wider than 1.2 line heights
    # from the run that contains the tallest component
    runs, cur = [], []
    for c in merged:
        if cur and c["x0"] - cur[-1]["x1"] > 1.2 * lh:
            runs.append(cur)
            cur = []
        cur.append(c)
    if cur:
        runs.append(cur)
    run = next(r for r in runs if any(c["x0"] <= tall["x0"] < c["x1"] or c["x0"] == tall["x0"] for c in r))
    info["line"] = [int(ly0), int(ly1)]
    if len(run) > max_glyphs:
        info["overflow"] = True
        info["n"] = len(run)
        return [], info
    H, W = arr.shape[:2]
    rgb = np.asarray(img.convert("RGB"))
    # background = median colour of the non-text pixels in the line band
    by0, by1 = max(0, ly0 - 3), min(H, ly1 + 3)
    bandpx = rgb[by0:by1][~mask[by0:by1]]
    bg = tuple(int(v) for v in (np.median(bandpx, axis=0) if len(bandpx) else (0, 0, 0)))
    out = []
    for c in run:
        # the character itself (1 px margin) on a square canvas of the background colour, so
        # neighbouring characters never enter the glyph image
        xa, xb = max(0, c["x0"] - 1), min(W, c["x1"] + 1)
        ya, yb = max(0, ly0 - 2), min(H, ly1 + 2)
        piece = rgb[ya:yb, xa:xb]
        side = max(lh + 8, (xb - xa) + 8)
        canvas = np.empty((side, side, 3), dtype=np.uint8)
        canvas[:] = bg
        oy = (side - (yb - ya)) // 2
        ox = (side - (xb - xa)) // 2
        canvas[oy:oy + (yb - ya), ox:ox + (xb - xa)] = piece
        out.append(Image.fromarray(canvas))
        info["boxes"].append([int(c["x0"]), int(c["y0"]), int(c["x1"]), int(c["y1"])])
    info["n"] = len(out)
    return out, info
