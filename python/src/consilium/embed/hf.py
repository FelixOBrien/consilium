"""Load CONCH-Z's text tower and bge-small on CPU.

The full CONCH-Z checkpoint includes a 307M vision tower this process never
runs. Only `text.*` weights are read out of the safetensors file. Tokenization
and the forward pass follow the model card: the tokenizer pads to 128 ids,
`encode_text` drops the last slot for the CLS token, and the result is
L2-normalised.

Importing this module does not import torch. The heavy libraries load on first
use, so the default test install can import the package without them.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Any

from consilium.embed.text import (  # pragma: allowlist secret
    CONCHZ_MAX_TOKENS,
    REPORT_MAX_TOKENS,
    EmbedDependencyError,
    EmbedModelError,
    EncodedText,
    scrub_secret,
)

logger = logging.getLogger(__name__)

CONCHZ_REPO = "MahmoodLab/CONCH-Z"
BGE_REPO = "BAAI/bge-small-en-v1.5"
_CONCH_FILES = (
    "config.json",
    "text_tower.py",
    "conch_tokenizer.py",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "model.safetensors",
)


def _need(module: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:
        raise EmbedDependencyError(
            "Text encoders need the pipeline dependency group "
            "(`uv sync --group pipeline`)."
        ) from exc


class ConchzTextModel:
    """CONCH-Z text tower. `encode` matches `ConchZ.encode_text(..., normalize=True)`."""

    def __init__(self, tower: Any, tokenizer: Any, max_tokens: int) -> None:
        self._tower = tower
        self._tokenizer = tokenizer
        self._max_tokens = max_tokens

    def encode(self, texts: list[str]) -> list[EncodedText]:
        torch = _need("torch")
        fast = self._tokenizer.tokenizer
        raw = fast(
            texts,
            add_special_tokens=True,
            truncation=False,
            padding=False,
        )
        counts = [len(ids) for ids in raw["input_ids"]]
        truncated = [count > self._max_tokens for count in counts]
        input_ids = self._tokenizer(texts)
        with torch.inference_mode():
            # The published encode_text drops the final pad slot so the tower
            # can append its CLS embedding.
            latent = self._tower(input_ids[:, :-1])
            embedded = torch.nn.functional.normalize(latent.float(), dim=-1)
        rows = embedded.detach().cpu().tolist()
        return [
            EncodedText(values=tuple(row), truncated=flag, token_count=count)
            for row, flag, count in zip(rows, truncated, counts, strict=True)
        ]


class BgeTextModel:
    """bge-small with CLS pooling and L2 normalisation, as on the model card."""

    def __init__(self, model: Any, tokenizer: Any, max_tokens: int) -> None:
        self._model = model
        self._tokenizer = tokenizer
        self._max_tokens = max_tokens

    def encode(self, texts: list[str]) -> list[EncodedText]:
        torch = _need("torch")
        raw = self._tokenizer(
            texts,
            add_special_tokens=True,
            truncation=False,
            padding=False,
        )
        counts = [len(ids) for ids in raw["input_ids"]]
        truncated = [count > self._max_tokens for count in counts]
        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self._max_tokens,
            return_tensors="pt",
        )
        encoded = {key: value.to("cpu") for key, value in encoded.items()}
        with torch.inference_mode():
            output = self._model(**encoded)
            cls = output.last_hidden_state[:, 0]
            embedded = torch.nn.functional.normalize(cls.float(), dim=-1)
        rows = embedded.detach().cpu().tolist()
        return [
            EncodedText(values=tuple(row), truncated=flag, token_count=count)
            for row, flag, count in zip(rows, truncated, counts, strict=True)
        ]


def load_conchz_text_tower(token: str) -> ConchzTextModel:
    """Download CONCH-Z if needed and build the text tower on CPU."""
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    logger.info("Loading CONCH-Z text tower on CPU")
    try:
        snapshot = _snapshot(CONCHZ_REPO, token, _CONCH_FILES)
        root = Path(snapshot)
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        text_tower = _load_module(root / "text_tower.py", "conchz_text_tower")
        tokenizer_mod = _load_module(root / "conch_tokenizer.py", "conchz_tokenizer")
        tower = text_tower.ConchTextTower(
            context_length=config["context_length"],
            vocab_size=config["vocab_size"],
            width=config["text_width"],
            heads=config["text_heads"],
            layers=config["text_layers"],
            mlp_ratio=config["mlp_ratio"],
            embed_dim=config["embed_dim"],
            pad_id=config["pad_id"],
        )
        state = _text_state(root / "model.safetensors")
        tower.load_state_dict(state)
        tower.eval()
        for parameter in tower.parameters():
            parameter.requires_grad_(False)
        tokenizer = tokenizer_mod.ConchTokenizer.from_pretrained(
            str(root),
            context_length=int(config["context_length"]),
        )
    except EmbedDependencyError:
        raise
    except EmbedModelError:
        raise
    except Exception as exc:
        raise EmbedModelError(
            "CONCH-Z text tower failed to load: " + scrub_secret(str(exc), token)
        ) from None
    max_tokens = int(config["context_length"]) - 1
    if max_tokens != CONCHZ_MAX_TOKENS:
        logger.info(
            "CONCH-Z config context limit is %s tokens; the documented cap is %s",
            max_tokens,
            CONCHZ_MAX_TOKENS,
        )
    return ConchzTextModel(tower, tokenizer, max_tokens)


def load_bge_encoder(token: str | None) -> BgeTextModel:
    """Load `BAAI/bge-small-en-v1.5` on CPU. The token is optional; the repo is public."""
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    logger.info("Loading bge-small report encoder on CPU")
    try:
        transformers = _need("transformers")
        torch = _need("torch")
        tokenizer = transformers.AutoTokenizer.from_pretrained(BGE_REPO, token=token)
        model = transformers.AutoModel.from_pretrained(BGE_REPO, token=token)
        model.eval()
        model.to(device="cpu", dtype=torch.float32)
        for parameter in model.parameters():
            parameter.requires_grad_(False)
        limit = getattr(tokenizer, "model_max_length", REPORT_MAX_TOKENS)
        if not isinstance(limit, int) or limit <= 0 or limit > 100_000:
            limit = REPORT_MAX_TOKENS
    except EmbedDependencyError:
        raise
    except Exception as exc:
        raise EmbedModelError(
            "bge-small failed to load: " + scrub_secret(str(exc), token)
        ) from None
    return BgeTextModel(model, tokenizer, limit)


def _snapshot(repo: str, token: str | None, allow: tuple[str, ...]) -> str:
    hub = _need("huggingface_hub")
    return hub.snapshot_download(repo_id=repo, token=token, allow_patterns=list(allow))


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise EmbedModelError(f"Could not load {path.name} from the model repository")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text_state(path: Path) -> dict[str, Any]:
    safetensors = _need("safetensors")
    with safetensors.safe_open(str(path), framework="pt", device="cpu") as handle:
        keys = list(handle.keys())
        text_keys = [key for key in keys if key.startswith("text.")]
        if not text_keys:
            prefixes = sorted({key.split(".", 1)[0] for key in keys})
            raise EmbedModelError(
                "CONCH-Z checkpoint has no text.* weights. "
                f"Top-level prefixes: {prefixes}"
            )
        return {key.removeprefix("text."): handle.get_tensor(key) for key in text_keys}
