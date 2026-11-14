"""Curated histology concepts for phrase heatmaps.

About twenty prompts, general ones plus a few per specialty. Embeddings are
not filled here: `encode_concept_rows` uses the CONCH-Z text tower
(`conchz`, 768-d) when weights are available. Report-space vectors are never
written onto a concept.
"""

from __future__ import annotations

from dataclasses import dataclass

from consilium.embed.spaces import CONCHZ_DIM  # pragma: allowlist secret
from consilium.embed.text import TextEncoders  # pragma: allowlist secret

# General concepts first, then specialties in the same order as the cohort.
_CONCEPTS: tuple[tuple[str, str, str, str | None, str | None], ...] = (
    (
        "tumour-necrosis",
        "Tumour necrosis",
        "an H&E image of tumour necrosis",
        "viable tumour without necrosis",
        None,
    ),
    (
        "mitotic-figures",
        "Mitotic figures",
        "an H&E image of mitotic figures",
        "quiescent nuclei without mitoses",
        None,
    ),
    (
        "lymphocytic-infiltrate",
        "Lymphocytic infiltrate",
        "an H&E image of lymphocytic infiltrate",
        "tumour without inflammatory infiltrate",
        None,
    ),
    (
        "fibrosis",
        "Fibrosis",
        "an H&E image of fibrosis",
        "cellular tumour without fibrosis",
        None,
    ),
    (
        "mucin",
        "Mucin",
        "an H&E image of extracellular mucin",
        "tumour without mucin",
        None,
    ),
    (
        "glandular-differentiation",
        "Glandular differentiation",
        "an H&E image of glandular differentiation",
        "solid sheets of tumour cells",
        None,
    ),
    (
        "keratinisation",
        "Keratinisation",
        "an H&E image of keratinisation",
        "non-keratinising epithelium",
        None,
    ),
    (
        "haemorrhage",
        "Haemorrhage",
        "an H&E image of haemorrhage",
        "tissue without haemorrhage",
        None,
    ),
    (
        "ductal-carcinoma-in-situ",
        "Ductal carcinoma in situ",
        "an H&E image of ductal carcinoma in situ",
        "invasive carcinoma without in situ ducts",
        "breast",
    ),
    (
        "lobular-architecture",
        "Lobular architecture",
        "an H&E image of discohesive lobular carcinoma cells",
        None,
        "breast",
    ),
    (
        "lepidic-growth",
        "Lepidic growth",
        "an H&E image of lepidic growth along alveolar walls",
        "solid tumour filling alveoli",
        "thorax",
    ),
    (
        "keratinising-squamous",
        "Keratinising squamous carcinoma",
        "an H&E image of keratinising squamous cell carcinoma",
        None,
        "thorax",
    ),
    (
        "dirty-necrosis",
        "Dirty necrosis",
        "an H&E image of dirty necrosis in colorectal adenocarcinoma",
        "adenocarcinoma without necrosis",
        "colorectal",
    ),
    (
        "cribriform-glands",
        "Cribriform glands",
        "an H&E image of cribriform glands",
        None,
        "colorectal",
    ),
    (
        "signet-ring",
        "Signet-ring cells",
        "an H&E image of signet-ring cells",
        "gland-forming adenocarcinoma",
        "gastrointestinal",
    ),
    (
        "intestinal-metaplasia",
        "Intestinal metaplasia",
        "an H&E image of intestinal metaplasia",
        None,
        "gastrointestinal",
    ),
    (
        "diffuse-lymphoid",
        "Diffuse lymphoid infiltrate",
        "an H&E image of a diffuse lymphoid infiltrate",
        "scattered inflammatory cells",
        "hematologic",
    ),
    (
        "starry-sky",
        "Starry-sky pattern",
        "an H&E image of a starry-sky pattern",
        None,
        "hematologic",
    ),
    (
        "melanocytic-nests",
        "Melanocytic nests",
        "an H&E image of melanocytic nests",
        "junctional melanocytes in a single line",
        "skin",
    ),
    (
        "pagetoid-spread",
        "Pagetoid spread",
        "an H&E image of pagetoid spread of melanocytes",
        None,
        "skin",
    ),
)


@dataclass(frozen=True)
class ConceptRow:
    """One concept. Embeddings stay `None` until the CONCH-Z step runs."""

    id: str
    label: str
    prompt: str
    negative_prompt: str | None
    specialty: str | None
    ordinal: int
    embedding: tuple[float, ...] | None = None
    negative_embedding: tuple[float, ...] | None = None

    def with_embeddings(
        self,
        embedding: tuple[float, ...] | None,
        negative_embedding: tuple[float, ...] | None,
    ) -> ConceptRow:
        return ConceptRow(
            id=self.id,
            label=self.label,
            prompt=self.prompt,
            negative_prompt=self.negative_prompt,
            specialty=self.specialty,
            ordinal=self.ordinal,
            embedding=embedding,
            negative_embedding=negative_embedding,
        )


def concept_rows() -> tuple[ConceptRow, ...]:
    """The curated list, prompts only, in display order."""
    rows = [
        ConceptRow(
            id=concept_id,
            label=label,
            prompt=prompt,
            negative_prompt=negative,
            specialty=specialty,
            ordinal=ordinal,
        )
        for ordinal, (concept_id, label, prompt, negative, specialty) in enumerate(
            _CONCEPTS, start=1
        )
    ]
    _validate_prompts(rows)
    return tuple(rows)


def encode_concept_rows(
    rows: tuple[ConceptRow, ...] | list[ConceptRow],
    encoders: TextEncoders,
) -> tuple[ConceptRow, ...]:
    """Fill `embedding` and `negative_embedding` in the CONCH-Z text space."""
    if not rows:
        return ()
    prompts = encoders.encode_image_texts([row.prompt for row in rows])
    negative_texts = [row.negative_prompt for row in rows if row.negative_prompt]
    encoded_negatives = encoders.encode_image_texts(negative_texts) if negative_texts else []
    negative_at = iter(encoded_negatives)
    encoded: list[ConceptRow] = []
    for row, prompt_encoding in zip(rows, prompts, strict=True):
        if len(prompt_encoding.vector.values) != CONCHZ_DIM:
            raise ValueError("concept embeddings must be 768-d conchz vectors")
        negative_vector: tuple[float, ...] | None = None
        if row.negative_prompt:
            negative_encoding = next(negative_at)
            if len(negative_encoding.vector.values) != CONCHZ_DIM:
                raise ValueError("concept negative embeddings must be 768-d conchz vectors")
            negative_vector = negative_encoding.vector.values
        encoded.append(row.with_embeddings(prompt_encoding.vector.values, negative_vector))
    return tuple(encoded)


def _validate_prompts(rows: list[ConceptRow]) -> None:
    ids = [row.id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("concept ids must be unique")
    ordinals = [row.ordinal for row in rows]
    if ordinals != list(range(1, len(rows) + 1)):
        raise ValueError("concept ordinals must be 1..n in order")
    for row in rows:
        if not row.prompt.strip() or not row.label.strip():
            raise ValueError(f"concept {row.id} needs a label and a prompt")
        # Whitespace stand-in for the 127-token CONCH-Z cap. Real prompts are short.
        if len(row.prompt.split()) + 2 > 127:
            raise ValueError(f"concept {row.id} prompt exceeds the encoder token budget")
        if row.negative_prompt and len(row.negative_prompt.split()) + 2 > 127:
            raise ValueError(f"concept {row.id} negative prompt exceeds the encoder token budget")
