"""Artwork tracing: the designer's pen strokes become spec geometry.

The continuity principle this module exists for: a hand drawing carries two
kinds of truth. STONE truth (species, cuts, counts, sizes) survives language
— the vision layer can name it. COMPOSITION truth (where the clusters sit,
how the branch curves) does not survive language; re-synthesizing it from
parametric taste ruins the design. Proven overlay tools (CAD underlays,
image tracing) anchor to the source image's own geometry — so does this.

Deterministic, no AI: color segmentation finds the drawn stones, connected
components group them, and the anchors come out as normalized coordinates
(x along the drawing, y in the same scale) ready for a spec `composition`
section. The same image traces to the same anchors, every time.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from PIL import Image

TRACE_MAX_SIDE = 720  # segmentation resolution; blobs are far larger than 1px


@dataclass(frozen=True)
class TracedCluster:
    x: float       # image px (downscaled)
    y: float
    radius: float  # circumscribing radius of the drawn cluster, px
    petals: int


def _green_mask(im: Image.Image) -> list[list[bool]]:
    """Emerald ink: green clearly dominating both red and blue."""
    w, h = im.size
    px = im.load()
    mask = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y][:3]
            if g > 70 and g > r * 1.12 and g > b * 1.12:
                mask[y][x] = True
    return mask


def _components(mask: list[list[bool]], min_area: int) -> list[list[tuple[int, int]]]:
    h, w = len(mask), len(mask[0])
    seen = [[False] * w for _ in range(h)]
    out = []
    for y0 in range(h):
        for x0 in range(w):
            if not mask[y0][x0] or seen[y0][x0]:
                continue
            queue, blob = deque([(x0, y0)]), []
            seen[y0][x0] = True
            while queue:
                x, y = queue.popleft()
                blob.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        queue.append((nx, ny))
            if len(blob) >= min_area:
                out.append(blob)
    return out


def _group_into_clusters(blobs: list[list[tuple[int, int]]],
                         join_px: float) -> list[TracedCluster]:
    """Petal blobs whose centers sit within join_px form one quatrefoil."""
    centers = []
    for blob in blobs:
        cx = sum(p[0] for p in blob) / len(blob)
        cy = sum(p[1] for p in blob) / len(blob)
        centers.append((cx, cy, blob))
    used = [False] * len(centers)
    clusters = []
    for i, (cx, cy, _) in enumerate(centers):
        if used[i]:
            continue
        group = [i]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j, (jx, jy, _) in enumerate(centers):
                if used[j]:
                    continue
                if any(abs(jx - centers[k][0]) < join_px
                       and abs(jy - centers[k][1]) < join_px for k in group):
                    group.append(j)
                    used[j] = True
                    changed = True
        pts = [p for k in group for p in centers[k][2]]
        gx = sum(p[0] for p in pts) / len(pts)
        gy = sum(p[1] for p in pts) / len(pts)
        radius = max(((p[0] - gx) ** 2 + (p[1] - gy) ** 2) ** 0.5 for p in pts)
        clusters.append(TracedCluster(gx, gy, radius, len(group)))
    return clusters


def _gold_mask(im: Image.Image) -> list[list[bool]]:
    """Gold ink: warm tones, red leading green leading blue, darker than paper."""
    w, h = im.size
    px = im.load()
    mask = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y][:3]
            if r > 90 and r > b * 1.25 and g > b * 1.1 and r >= g and r - b > 35:
                mask[y][x] = True
    return mask


def trace_spray(image_path: str) -> dict:
    """Trace a leaf-spray artwork into normalized composition anchors.

    Finds the master study (the largest-drawn chain of green quatrefoils),
    walks it terminal-first, infers the slot of a drawn-but-not-green cluster
    (the diamond quatrefoil) from its double-width gap, and measures the
    piece's full reach from the gold foliage beyond the last cluster.

    Returns {"clusters": [[x, y, r], ...], "vein": [[x, y], ...]} — all
    normalized so the tip-most cluster center is (0, 0) and the piece's full
    drawn reach is 1.0: scale by the spec's usable reach and the drawing's
    own proportions come back in mm. Same image in, same anchors out."""
    im = Image.open(image_path).convert("RGB")
    scale = TRACE_MAX_SIDE / max(im.size)
    if scale < 1:
        im = im.resize((round(im.width * scale), round(im.height * scale)))
    blobs = _components(_green_mask(im), min_area=max(24, im.width * im.height // 20000))
    clusters = _group_into_clusters(blobs, join_px=im.width * 0.055)
    if len(clusters) < 3:
        raise ValueError(
            f"traced only {len(clusters)} green clusters — the drawing needs "
            "at least a terminal and two stations to anchor a composition")

    # walk the master chain from the largest cluster; a hop is accepted while
    # it fits one cluster pitch — or two, where a non-green cluster sits —
    # AND the candidate is size-consistent: a garland graduates gently, so a
    # cluster from a smaller-drawn study (half the size) is never the next link
    chain = [max(clusters, key=lambda c: c.radius)]
    rest = [c for c in clusters if c is not chain[0]]
    while rest:
        last = chain[-1]
        rest.sort(key=lambda c: (c.x - last.x) ** 2 + (c.y - last.y) ** 2)
        cand = next((c for c in rest if c.radius >= 0.62 * last.radius), None)
        if cand is None:
            break
        hop = ((cand.x - last.x) ** 2 + (cand.y - last.y) ** 2) ** 0.5
        if hop > 2.35 * (last.radius + cand.radius):
            break  # the next size-consistent green blob is another study
        chain.append(cand)
        rest.remove(cand)

    # the diamond quatrefoil is drawn but not green: its slot is the gap wide
    # enough for two pitches — fill it midway, sized like its smaller neighbor
    slots: list[tuple[float, float, float]] = [(chain[0].x, chain[0].y, chain[0].radius)]
    for a, b in zip(chain, chain[1:]):
        gap = ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5
        if gap > 1.55 * (a.radius + b.radius):
            slots.append(((a.x + b.x) / 2, (a.y + b.y) / 2, min(a.radius, b.radius)))
        slots.append((b.x, b.y, b.radius))

    # full reach: gold foliage extends past the last cluster — project gold
    # pixels near the chain onto the chain direction and take the far edge
    ux, uy = slots[-1][0] - slots[0][0], slots[-1][1] - slots[0][1]
    n = (ux ** 2 + uy ** 2) ** 0.5 or 1.0
    ux, uy = ux / n, uy / n
    band = 2.2 * slots[0][2]
    gold = _gold_mask(im)
    reach = n
    for y in range(len(gold)):
        for x in range(len(gold[0])):
            if not gold[y][x]:
                continue
            along = (x - slots[0][0]) * ux + (y - slots[0][1]) * uy
            across = abs(-(x - slots[0][0]) * uy + (y - slots[0][1]) * ux)
            if across < band and along > reach:
                reach = along
    span = reach

    x0, y0 = slots[0][0], slots[0][1]
    norm = [[round((x - x0) / span, 4), round((y - y0) / span, 4),
             round(r / span, 4)] for x, y, r in slots]
    if norm[-1][0] < 0:  # tip on the left, tail to the right, always
        norm = [[-x, y, r] for x, y, r in norm]
    if norm[-1][1] > 0:  # tail rises (y down): tail above the tip, always
        norm = [[x, -y, r] for x, y, r in norm]
    norm = [[x, y, r] for x, y, r in norm]
    # the vein hugs the chain from its convex side
    vein = [[round(x, 4), round(y - r * 0.9, 4)] for x, y, r in norm]
    return {"clusters": norm, "vein": vein}
