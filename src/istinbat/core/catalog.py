# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The models Istinbat can download, and where each one comes from.

The list is fixed in code on purpose: the application only ever fetches these files,
from these repositories, so nothing a user types or a book contains can point a
download somewhere else.

* Embedding model: ``BAAI/bge-m3`` (multilingual, Arabic and English).
* Reranking model: ``BAAI/bge-reranker-v2-m3``.
* Language models: Gemma 4 ``E2B`` and ``E4B`` as GGUF files from Unsloth, in the
  dynamic ``Q4_K_XL``, ``Q6_K_XL`` and ``Q8_K_XL`` quantizations.

Only the files needed to run a model are listed (no ONNX copies, images, vision
projectors or speculative-decoding drafters). Sizes are approximate and used only to
estimate progress and disk space before the real sizes are known.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

_MB = 1_000_000
_GB = 1_000 * _MB


class ModelKind(str, Enum):
    EMBEDDER = "embedder"
    RERANKER = "reranker"
    LLM = "llm"

    @property
    def settings_attribute(self) -> str:
        """The ``PathsConfig`` field that holds the chosen model of this kind."""
        return {"embedder": "embedder_model", "reranker": "reranker_model", "llm": "llm_model"}[self.value]


@dataclass(frozen=True)
class RemoteFile:
    path: str            # Relative path inside the repository (and inside the local folder).
    approx_bytes: int

    def __post_init__(self) -> None:
        parts = PurePosixPath(self.path).parts
        if not parts or PurePosixPath(self.path).is_absolute() or ".." in parts:
            raise ValueError(f"unsafe file path: {self.path!r}")


@dataclass(frozen=True)
class ModelOption:
    """One downloadable choice."""

    key: str                          # Stable identifier, e.g. "llm.e2b.q4_k_xl".
    kind: ModelKind
    repo: str                         # Hugging Face repository, "owner/name".
    directory: str                    # Folder name inside the models folder.
    files: tuple[RemoteFile, ...]
    entry: str = ""                   # File inside ``directory`` to load; empty means the folder itself.
    family: str | None = None         # "E2B" or "E4B" for language models.
    quant: str | None = None          # "Q4_K_XL", ... for language models.
    revision: str = "main"

    @property
    def approx_bytes(self) -> int:
        return sum(file.approx_bytes for file in self.files)

    def local_path(self, models_dir: str | Path) -> Path:
        """What the settings should point to once this option is downloaded."""
        folder = Path(models_dir) / self.directory
        return folder / self.entry if self.entry else folder

    def is_downloaded(self, models_dir: str | Path) -> bool:
        """Files are renamed into place only when complete, so their presence means a finished download."""
        folder = Path(models_dir) / self.directory
        return all((folder / file.path).is_file() for file in self.files)


EMBEDDER = ModelOption(
    key="embedder",
    kind=ModelKind.EMBEDDER,
    repo="BAAI/bge-m3",
    directory="bge-m3",
    files=(
        RemoteFile("modules.json", 349),
        RemoteFile("config_sentence_transformers.json", 123),
        RemoteFile("sentence_bert_config.json", 54),
        RemoteFile("1_Pooling/config.json", 191),
        RemoteFile("config.json", 687),
        RemoteFile("sentencepiece.bpe.model", 5 * _MB),
        RemoteFile("special_tokens_map.json", 964),
        RemoteFile("tokenizer.json", 17 * _MB),
        RemoteFile("tokenizer_config.json", 444),
        RemoteFile("pytorch_model.bin", 2_270 * _MB),
    ),
)

RERANKER = ModelOption(
    key="reranker",
    kind=ModelKind.RERANKER,
    repo="BAAI/bge-reranker-v2-m3",
    directory="bge-reranker-v2-m3",
    files=(
        RemoteFile("config.json", 795),
        RemoteFile("sentencepiece.bpe.model", 5 * _MB),
        RemoteFile("special_tokens_map.json", 964),
        RemoteFile("tokenizer.json", 17 * _MB),
        RemoteFile("tokenizer_config.json", 1_170),
        RemoteFile("model.safetensors", 2_270 * _MB),
    ),
)

LLM_FAMILIES = ("E2B", "E4B")
LLM_QUANTS = ("Q4_K_XL", "Q6_K_XL", "Q8_K_XL")

# Approximate download sizes in bytes, from the repositories' file listings.
_LLM_SIZES = {
    ("E2B", "Q4_K_XL"): 3_180 * _MB,
    ("E2B", "Q6_K_XL"): 4_710 * _MB,
    ("E2B", "Q8_K_XL"): 5_280 * _MB,
    ("E4B", "Q4_K_XL"): 5_130 * _MB,
    ("E4B", "Q6_K_XL"): 7_460 * _MB,
    ("E4B", "Q8_K_XL"): 8_710 * _MB,
}


def _llm_option(family: str, quant: str) -> ModelOption:
    name = f"gemma-4-{family}-it"
    filename = f"{name}-UD-{quant}.gguf"
    return ModelOption(
        key=f"llm.{family.lower()}.{quant.lower()}",
        kind=ModelKind.LLM,
        repo=f"unsloth/{name}-GGUF",
        directory=name,
        files=(RemoteFile(filename, _LLM_SIZES[(family, quant)]),),
        entry=filename,
        family=family,
        quant=quant,
    )


LLMS = tuple(_llm_option(family, quant) for family in LLM_FAMILIES for quant in LLM_QUANTS)


def all_options() -> tuple[ModelOption, ...]:
    return (EMBEDDER, RERANKER, *LLMS)


def option_by_key(key: str) -> ModelOption:
    for option in all_options():
        if option.key == key:
            return option
    raise KeyError(key)


def llms_of(family: str) -> tuple[ModelOption, ...]:
    return tuple(option for option in LLMS if option.family == family)
