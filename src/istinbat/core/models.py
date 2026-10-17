# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Opening the vector store and loading the machine-learning models.

Heavy imports (torch, llama.cpp, chromadb) are deferred to call time so the
interface starts instantly and tests run without those libraries installed.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any

from .settings import Settings


class ModelNotFoundError(FileNotFoundError):
    """A configured model file or directory is missing."""


def _require_path(path: str, description: str) -> None:
    if not path:
        raise ModelNotFoundError(f"{description} is not configured")
    if not os.path.exists(path):
        raise ModelNotFoundError(f"{description} not found: {path}")


def open_collection(settings: Settings) -> Any:
    """Open (creating if needed) the ChromaDB collection that stores book chunks."""
    import chromadb

    client = chromadb.PersistentClient(path=settings.paths.vector_db)
    return client.get_or_create_collection(
        name=settings.paths.collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def load_embedder(settings: Settings) -> Any:
    _require_path(settings.paths.embedder_model, "Embedding model")
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.paths.embedder_model)


def load_reranker(settings: Settings) -> Any:
    _require_path(settings.paths.reranker_model, "Reranker model")
    from sentence_transformers import CrossEncoder

    return CrossEncoder(settings.paths.reranker_model, max_length=512)


def load_llm(settings: Settings) -> Any:
    _require_path(settings.paths.llm_model, "Language model")
    from llama_cpp import Llama

    llm = settings.llm
    with open(os.devnull, "w") as devnull, contextlib.redirect_stderr(devnull):
        return Llama(
            model_path=settings.paths.llm_model,
            n_ctx=llm.context_window,
            n_threads=llm.threads,
            n_threads_batch=llm.batch_threads,
            n_gpu_layers=llm.gpu_layers,
            verbose=False,
        )
