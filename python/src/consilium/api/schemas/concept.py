from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from consilium.api.schemas.common import APIModel, Region, Specialty  # pragma: allowlist secret

# CONCH-Z text tower token cap. The stub treats characters as a stand-in for tokens.
ENCODER_TEXT_LIMIT = 127

SIMILARITY_NOTICE = (
    "Embedding similarity between the phrase and each patch. Not a finding and not a diagnosis."
)

TISSUE_SIMILARITY_NOTICE = (
    "Embedding similarity to the selected tissue. Not a finding and not a diagnosis."
)

HeatmapSource = Literal["text", "concept", "patch", "region"]


class Concept(APIModel):
    """Curated phrase. Embeddings are never included."""

    id: str
    label: str
    prompt: str
    specialty: Specialty | None


class HeatmapPatchScore(APIModel):
    x: int
    y: int
    size: int = Field(gt=0)
    score: float = Field(ge=0, le=1)


class HeatmapCell(APIModel):
    """One patch in a tissue cluster. Coordinates only."""

    x: int
    y: int
    size: int = Field(gt=0)


class HeatmapBBox(APIModel):
    """Level-0 box that encloses every cluster cell."""

    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class HeatmapCluster(APIModel):
    """8-connected similar tissue. Embeddings are never included."""

    cells: list[HeatmapCell]
    bbox: HeatmapBBox
    threshold: float
    patch_count: int = Field(ge=1)


class HeatmapRequest(APIModel):
    """Exactly one source: a report word, a concept, a patch or a region.

    `negative_text` belongs with `text` or `concept_id`. `grow` belongs with
    `patch_id` or `region`. `region` is the same level-0 rectangle as patch search.
    """

    text: str | None = None
    concept_id: str | None = None
    patch_id: int | None = Field(default=None, ge=1)
    region: Region | None = None
    negative_text: str | None = None
    grow: bool = False

    @model_validator(mode="after")
    def one_source(self) -> Self:
        text = self.text.strip() if self.text is not None else None
        concept_id = self.concept_id.strip() if self.concept_id is not None else None
        negative = self.negative_text.strip() if self.negative_text is not None else None
        if text == "":
            raise ValueError("text must not be empty")
        if concept_id == "":
            raise ValueError("concept_id must not be empty")
        sources = [
            name
            for name, present in (
                ("text", text is not None),
                ("concept_id", concept_id is not None),
                ("patch_id", self.patch_id is not None),
                ("region", self.region is not None),
            )
            if present
        ]
        if len(sources) != 1:
            raise ValueError("provide exactly one of text, concept_id, patch_id or region")
        tissue = self.patch_id is not None or self.region is not None
        if tissue and negative:
            raise ValueError("negative_text cannot be combined with patch_id or region")
        if self.grow and not tissue:
            raise ValueError("grow is only valid with patch_id or region")
        self.text = text
        self.concept_id = concept_id
        self.negative_text = negative or None
        return self


class HeatmapResponse(APIModel):
    """Per-patch scores. `text` is empty when `source` is `patch` or `region`."""

    text: str
    concept_id: str | None = None
    negative_text: str | None = None
    notice: str
    truncated: bool
    patches: list[HeatmapPatchScore]
    top: list[HeatmapPatchScore]
    source: HeatmapSource
    cluster: HeatmapCluster | None = None
