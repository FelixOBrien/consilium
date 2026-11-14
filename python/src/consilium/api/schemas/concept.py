from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from consilium.api.schemas.common import APIModel, Specialty  # pragma: allowlist secret

# CONCH-Z text tower token cap. The stub treats characters as a stand-in for tokens.
ENCODER_TEXT_LIMIT = 127

SIMILARITY_NOTICE = (
    "Embedding similarity between the phrase and each patch. Not a finding and not a diagnosis."
)


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


class HeatmapRequest(APIModel):
    """F-06 sends `text`. `concept_id` and `negative_text` are optional."""

    text: str | None = None
    concept_id: str | None = None
    negative_text: str | None = None

    @model_validator(mode="after")
    def one_phrase(self) -> Self:
        text = self.text.strip() if self.text is not None else None
        concept_id = self.concept_id.strip() if self.concept_id is not None else None
        negative = self.negative_text.strip() if self.negative_text is not None else None
        if text == "":
            raise ValueError("text must not be empty")
        if concept_id == "":
            raise ValueError("concept_id must not be empty")
        if (text is None) == (concept_id is None):
            raise ValueError("provide text or concept_id, not both")
        self.text = text
        self.concept_id = concept_id
        self.negative_text = negative or None
        return self


class HeatmapResponse(APIModel):
    text: str
    concept_id: str | None = None
    negative_text: str | None = None
    notice: str
    truncated: bool
    patches: list[HeatmapPatchScore]
    top: list[HeatmapPatchScore]
