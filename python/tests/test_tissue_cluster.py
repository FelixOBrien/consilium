"""Otsu threshold, 8-connected growth, and the shared region-vector mean."""

from __future__ import annotations

import inspect
import math

import pytest
from pydantic import ValidationError

from consilium.api.schemas.concept import (  # pragma: allowlist secret
    HeatmapCell,
    HeatmapCluster,
    HeatmapPatchScore,
    HeatmapRequest,
)
from consilium.db import concepts as concept_db  # pragma: allowlist secret
from consilium.search import patches as patch_search  # pragma: allowlist secret
from consilium.search.cluster import grow_tissue_cluster, otsu_threshold  # pragma: allowlist secret
from consilium.search.common import SearchError  # pragma: allowlist secret
from consilium.search.query_vector import NO_TISSUE, mean_conchz  # pragma: allowlist secret

_SIZE = 512


def _patch(x: int, y: int, score: float, size: int = _SIZE) -> HeatmapPatchScore:
    return HeatmapPatchScore(x=x, y=y, size=size, score=score)


def _seed(x: int, y: int, size: int = _SIZE) -> HeatmapCell:
    return HeatmapCell(x=x, y=y, size=size)


def test_otsu_splits_a_bimodal_slide_above_the_low_mode() -> None:
    threshold = otsu_threshold([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    assert 0.0 < threshold < 1.0
    assert otsu_threshold([0.4, 0.4]) == 0.4
    assert otsu_threshold([]) == 0.0


def test_cluster_includes_diagonal_neighbours_and_not_a_gap() -> None:
    patches = [
        _patch(0, 0, 1.0),
        _patch(_SIZE, 0, 0.0),
        _patch(_SIZE, _SIZE, 1.0),
        _patch(_SIZE * 3, 0, 1.0),
    ]
    cluster = grow_tissue_cluster(patches, [_seed(0, 0)])
    cells = {(cell.x, cell.y) for cell in cluster.cells}
    assert (0, 0) in cells
    assert (_SIZE, _SIZE) in cells
    assert (_SIZE, 0) not in cells
    assert (_SIZE * 3, 0) not in cells
    assert cluster.patch_count == len(cluster.cells) == 2
    assert cluster.threshold <= 1.0
    assert cluster.bbox.x == 0
    assert cluster.bbox.y == 0
    assert cluster.bbox.width == _SIZE * 2
    assert cluster.bbox.height == _SIZE * 2
    _assert_eight_connected(cluster.cells)
    _assert_bbox_encloses(cluster)


def test_threshold_is_clamped_to_the_seed_mean_and_seeds_stay() -> None:
    patches = [_patch(0, 0, 0.2), *(_patch(index * _SIZE, 0, 1.0) for index in range(1, 8))]
    scores = [patch.score for patch in patches]
    cluster = grow_tissue_cluster(patches, [_seed(0, 0)])
    assert cluster.threshold == min(otsu_threshold(scores), 0.2)
    assert cluster.threshold <= 0.2
    assert any(cell.x == 0 and cell.y == 0 for cell in cluster.cells)
    _assert_eight_connected(cluster.cells)
    _assert_bbox_encloses(cluster)


def test_disconnected_seeds_are_both_kept() -> None:
    patches = [
        _patch(0, 0, 1.0),
        _patch(_SIZE, 0, 0.0),
        _patch(_SIZE * 3, 0, 1.0),
    ]
    cluster = grow_tissue_cluster(patches, [_seed(0, 0), _seed(_SIZE * 3, 0)])
    cells = {(cell.x, cell.y) for cell in cluster.cells}
    assert cells == {(0, 0), (_SIZE * 3, 0)}
    assert cluster.patch_count == 2


def test_mean_conchz_renormalises_and_empty_matches_search() -> None:
    first = [0.0] * 768
    second = [0.0] * 768
    first[0] = 1.0
    second[1] = 1.0
    mean = mean_conchz([first, second])
    expected = math.sqrt(0.5)
    assert mean.values[0] == pytest.approx(expected)
    assert mean.values[1] == pytest.approx(expected)
    assert sum(value * value for value in mean.values) == pytest.approx(1.0)
    with pytest.raises(SearchError) as caught:
        mean_conchz([])
    assert caught.value.status_code == 422
    assert caught.value.code == "validation_error"
    assert caught.value.message == NO_TISSUE


def test_search_and_heatmap_share_the_query_vector() -> None:
    query = inspect.getsource(concept_db._tissue_query)
    heatmap = inspect.getsource(concept_db._tissue_heatmap)
    search = inspect.getsource(patch_search)
    assert "patch_query_vector" in query
    assert "region_query_vector" in query
    assert "_score_slide" in heatmap
    assert "patch_query_vector" in search
    assert "region_query_vector" in search
    assert "def _region_vectors" not in search
    assert "def _mean_conchz" not in search


def test_heatmap_request_accepts_exactly_one_source() -> None:
    region = {"slide_id": "slide-1", "x": 0, "y": 0, "width": 512, "height": 512}
    assert HeatmapRequest.model_validate({"text": "necrosis"}).grow is False
    concept = HeatmapRequest.model_validate({"concept_id": "tumour-necrosis"})
    assert concept.concept_id == "tumour-necrosis"
    assert HeatmapRequest.model_validate({"patch_id": 4, "grow": True}).grow is True
    assert HeatmapRequest.model_validate({"region": region}).region is not None
    for payload in (
        {},
        {"text": "necrosis", "concept_id": "tumour-necrosis"},
        {"text": "necrosis", "patch_id": 4},
        {"patch_id": 4, "region": region},
        {"text": "necrosis", "concept_id": "x", "patch_id": 4, "region": region},
        {"patch_id": 4, "negative_text": "normal tissue"},
        {"region": region, "negative_text": "normal tissue"},
        {"text": "necrosis", "grow": True},
        {"concept_id": "tumour-necrosis", "grow": True},
    ):
        with pytest.raises(ValidationError):
            HeatmapRequest.model_validate(payload)


def _assert_eight_connected(cells: list[HeatmapCell]) -> None:
    keys = {(cell.x // cell.size, cell.y // cell.size) for cell in cells}
    # A cluster grown from one seed is one component. Disconnected seeds are
    # checked separately; this helper still requires each cell's neighbours
    # to use the same 8-grid when the set is a single component.
    start = next(iter(keys))
    seen: set[tuple[int, int]] = set()
    stack = [start]
    while stack:
        gx, gy = stack.pop()
        if (gx, gy) in seen:
            continue
        seen.add((gx, gy))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                key = (gx + dx, gy + dy)
                if key in keys and key not in seen:
                    stack.append(key)
    assert seen == keys


def _assert_bbox_encloses(cluster: HeatmapCluster) -> None:
    min_x = min(cell.x for cell in cluster.cells)
    min_y = min(cell.y for cell in cluster.cells)
    max_x = max(cell.x + cell.size for cell in cluster.cells)
    max_y = max(cell.y + cell.size for cell in cluster.cells)
    assert cluster.bbox.x == min_x
    assert cluster.bbox.y == min_y
    assert cluster.bbox.width == max_x - min_x
    assert cluster.bbox.height == max_y - min_y
    for cell in cluster.cells:
        assert cluster.bbox.x <= cell.x
        assert cluster.bbox.y <= cell.y
        assert cell.x + cell.size <= cluster.bbox.x + cluster.bbox.width
        assert cell.y + cell.size <= cluster.bbox.y + cluster.bbox.height
