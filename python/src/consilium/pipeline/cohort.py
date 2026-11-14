"""Cohort tiers, specialty map, and deterministic sampling.

Stage 1 selects cases. Synthetic authorship and longitudinal patient links
are stage 7 and are not assigned here.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# Table order in docs/context.md. Tie-breaks follow this order.
SPECIALTY_ORDER: tuple[str, ...] = (
    "breast",
    "thorax",
    "colorectal",
    "gastrointestinal",
    "skin",
    "hematologic",
)

PROJECT_SPECIALTY: dict[str, str] = {
    "TCGA-BRCA": "breast",
    "TCGA-LUAD": "thorax",
    "TCGA-LUSC": "thorax",
    "TCGA-COAD": "colorectal",
    "TCGA-READ": "colorectal",
    "TCGA-STAD": "gastrointestinal",
    "TCGA-ESCA": "gastrointestinal",
    "TCGA-SKCM": "skin",
    "TCGA-DLBC": "hematologic",
}

TARGET_PROJECTS: tuple[str, ...] = tuple(PROJECT_SPECIALTY)

# Decimal gigabytes, matching the "under 1 GB" counts in docs/context.md.
BYTES_PER_GB = 1_000_000_000

TIER_CASE_COUNTS: dict[str, int] = {
    "smoke": 10,
    "demo": 200,
    "stretch": 500,
}

# Smoke and demo counts are specified. Stretch keeps a 5% split (25 of 500),
# the same fraction as 10 of about 200, so evaluation still has held-out cases.
TIER_HELD_OUT: dict[str, int] = {
    "smoke": 2,
    "demo": 10,
    "stretch": 25,
}


@dataclass(frozen=True)
class CohortCandidate:
    """One eligible case before tier sampling."""

    specialty: str
    case_key: str
    history_rank: int


def allocate(
    total: int,
    available: Mapping[str, int],
    order: Sequence[str] = SPECIALTY_ORDER,
) -> dict[str, int]:
    """Spread `total` as evenly as possible, capped by `available`.

    A specialty with fewer cases than its share keeps all of them. Leftover
    slots go to specialties that still have cases, lowest count first, then
    `order`. Raising `total` never lowers a specialty's count.
    """
    if total < 0:
        raise ValueError("total must be >= 0")
    quotas = {name: 0 for name in order}
    remaining = min(total, sum(max(0, int(available.get(name, 0))) for name in order))
    while remaining:
        choices = [name for name in order if quotas[name] < max(0, int(available.get(name, 0)))]
        if not choices:
            break
        chosen = min(choices, key=lambda name: (quotas[name], order.index(name)))
        quotas[chosen] += 1
        remaining -= 1
    return quotas


def _seeded_keys(keys: Sequence[str], seed: int, specialty: str) -> list[str]:
    ordered = sorted(keys)
    rng = random.Random(f"{seed}:{specialty}")
    rng.shuffle(ordered)
    return ordered


def select_cohort(
    candidates: Sequence[CohortCandidate],
    tier: str,
    seed: int,
) -> dict[str, bool]:
    """Return `case_key -> held_out` for one tier.

    The smoke selection is a prefix of the demo selection, which is a prefix
    of the stretch selection, for the same seed and the same candidates.
    Held-out cases prefer a lower `history_rank` (bounded clinical history
    is 0) and are spread across specialties.
    """
    if tier not in TIER_CASE_COUNTS:
        raise ValueError(f"unknown tier {tier!r}")
    grouped: dict[str, list[CohortCandidate]] = {name: [] for name in SPECIALTY_ORDER}
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.specialty not in grouped:
            raise ValueError(f"unknown specialty {candidate.specialty!r}")
        if candidate.case_key in seen:
            raise ValueError(f"duplicate case {candidate.case_key}")
        seen.add(candidate.case_key)
        grouped[candidate.specialty].append(candidate)

    available = {name: len(grouped[name]) for name in SPECIALTY_ORDER}
    quotas = allocate(TIER_CASE_COUNTS[tier], available)
    picked_by_spec: dict[str, list[str]] = {}
    ranks_by_spec: dict[str, dict[str, int]] = {}
    position_by_spec: dict[str, dict[str, int]] = {}
    best_rank = {name: 2 for name in SPECIALTY_ORDER}
    for specialty in SPECIALTY_ORDER:
        ordered_keys = _seeded_keys([item.case_key for item in grouped[specialty]], seed, specialty)
        picked = ordered_keys[: quotas[specialty]]
        ranks = {item.case_key: item.history_rank for item in grouped[specialty]}
        picked_by_spec[specialty] = picked
        ranks_by_spec[specialty] = ranks
        position_by_spec[specialty] = {key: index for index, key in enumerate(ordered_keys)}
        if picked:
            best_rank[specialty] = min(ranks[key] for key in picked)
    # Even counts, but a specialty whose selected cases have a clinical
    # history takes a scarce held-out slot ahead of one that does not.
    held_quotas = _allocate_held(TIER_HELD_OUT[tier], quotas, best_rank)
    chosen: dict[str, bool] = {}
    for specialty in SPECIALTY_ORDER:
        picked = picked_by_spec[specialty]
        ranks = ranks_by_spec[specialty]
        position = position_by_spec[specialty]
        held_order = sorted(picked, key=lambda key: (ranks[key], position[key], key))
        held = set(held_order[: held_quotas[specialty]])
        for key in picked:
            chosen[key] = key in held
    return chosen


def _allocate_held(
    total: int,
    capacity: Mapping[str, int],
    best_rank: Mapping[str, int],
    order: Sequence[str] = SPECIALTY_ORDER,
) -> dict[str, int]:
    """Spread held-out slots, preferring specialties that have a history case."""
    quotas = {name: 0 for name in order}
    remaining = min(total, sum(max(0, int(capacity.get(name, 0))) for name in order))
    while remaining:
        choices = [name for name in order if quotas[name] < max(0, int(capacity.get(name, 0)))]
        if not choices:
            break
        chosen = min(
            choices,
            key=lambda name: (quotas[name], best_rank.get(name, 2), order.index(name)),
        )
        quotas[chosen] += 1
        remaining -= 1
    return quotas
