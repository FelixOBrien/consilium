"""Connected similar tissue on one scored slide.

The threshold is an Otsu split of the slide's min-max scores, clamped so it
is never above the mean score of the seed patches. Growth is breadth-first
over the patch grid (patch model rule 1: ``(x // size, y // size)``) with
8-connectivity. Every seed is kept, then the search steps only onto patches
whose score is at least the threshold. Embeddings are not an input or an
output.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Protocol

from consilium.api.schemas.concept import (  # pragma: allowlist secret
    HeatmapBBox,
    HeatmapCell,
    HeatmapCluster,
    HeatmapPatchScore,
)

# 256 bins is the usual histogram width for Otsu's method.
_OTSU_BINS = 256
_NEIGHBOURS = tuple(
    (dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx != 0 or dy != 0
)


class _Box(Protocol):
    x: int
    y: int
    size: int


def otsu_threshold(scores: Sequence[float], *, nbins: int = _OTSU_BINS) -> float:
    """Histogram Otsu threshold.

    Scores are binned across their own range. The returned value is the centre
    of the bin that maximises between-class variance (the split used by the
    common 1-D implementation of Otsu 1979). A flat set of scores returns
    that score.
    """
    if not scores:
        return 0.0
    if nbins < 2:
        raise ValueError("nbins must be at least 2")
    low = min(scores)
    high = max(scores)
    if high == low:
        return float(low)
    counts = [0] * nbins
    span = high - low
    for score in scores:
        if score >= high:
            index = nbins - 1
        else:
            index = int((score - low) / span * nbins)
            if index < 0:
                index = 0
            elif index >= nbins:
                index = nbins - 1
        counts[index] += 1
    centres = [low + (index + 0.5) * span / nbins for index in range(nbins)]
    total = float(len(scores))
    sum_all = sum(count * centre for count, centre in zip(counts, centres, strict=True))
    weight_background = 0.0
    sum_background = 0.0
    best_variance = -1.0
    best_index = 0
    for index in range(nbins - 1):
        weight_background += counts[index]
        if weight_background == 0.0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0.0:
            break
        sum_background += counts[index] * centres[index]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_all - sum_background) / weight_foreground
        between = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if between > best_variance:
            best_variance = between
            best_index = index
    return centres[best_index]


def grow_tissue_cluster(
    patches: Sequence[HeatmapPatchScore],
    seeds: Sequence[_Box],
) -> HeatmapCluster:
    """8-connected component of similar tissue around `seeds`.

    `patches` are the slide's min-max scores. `seeds` are the patch or the
    region that built the query vector. Seed patches are always cells of the
    cluster. Other patches join only when they share an edge or a corner with
    the cluster and their score is at least the clamped Otsu threshold.
    """
    if not seeds:
        raise ValueError("A tissue cluster needs at least one seed patch.")
    by_key: dict[tuple[int, int], HeatmapPatchScore] = {}
    by_origin: dict[tuple[int, int], HeatmapPatchScore] = {}
    for patch in patches:
        origin = (patch.x, patch.y)
        key = (patch.x // patch.size, patch.y // patch.size)
        if origin in by_origin or key in by_key:
            raise ValueError("Two patches share a grid cell.")
        by_origin[origin] = patch
        by_key[key] = patch

    seen: set[tuple[int, int]] = set()
    seed_patches: list[HeatmapPatchScore] = []
    for seed in seeds:
        origin = (seed.x, seed.y)
        patch = by_origin.get(origin)
        if patch is None or patch.size != seed.size or origin in seen:
            if patch is None or patch.size != seed.size:
                raise ValueError("Seed patch is not on the scored slide.")
            continue
        seen.add(origin)
        seed_patches.append(patch)
    if not seed_patches:
        raise ValueError("Seed patch is not on the scored slide.")

    scores = [patch.score for patch in patches]
    mean_seed = sum(patch.score for patch in seed_patches) / len(seed_patches)
    threshold = min(otsu_threshold(scores), mean_seed)

    queued = {(patch.x // patch.size, patch.y // patch.size) for patch in seed_patches}
    queue: deque[tuple[int, int]] = deque(queued)
    while queue:
        key = queue.popleft()
        gx, gy = key
        for dx, dy in _NEIGHBOURS:
            neighbour_key = (gx + dx, gy + dy)
            neighbour = by_key.get(neighbour_key)
            if neighbour is None or neighbour_key in queued:
                continue
            if neighbour.score >= threshold:
                queued.add(neighbour_key)
                queue.append(neighbour_key)

    chosen = [by_key[key] for key in queued]
    chosen.sort(key=lambda patch: (patch.y, patch.x))
    cells = [HeatmapCell(x=patch.x, y=patch.y, size=patch.size) for patch in chosen]
    min_x = min(cell.x for cell in cells)
    min_y = min(cell.y for cell in cells)
    width = max(cell.x + cell.size for cell in cells) - min_x
    height = max(cell.y + cell.size for cell in cells) - min_y
    return HeatmapCluster(
        cells=cells,
        bbox=HeatmapBBox(x=min_x, y=min_y, width=width, height=height),
        threshold=threshold,
        patch_count=len(cells),
    )
