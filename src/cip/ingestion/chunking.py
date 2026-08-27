"""Chunking híbrido: markdown-aware + semântico, com metadados enriquecidos.

Estratégia (ver docs/02-arquitetura.md):
1. Quebra por estrutura markdown (preserva hierarquia de headers).
2. Divide blocos grandes em chunks semânticos (~512-1024 tokens).
3. Enriquece cada chunk com metadados (seção, tokens, timestamp).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")

TARGET_TOKENS = 800
OVERLAP_TOKENS = 100


def count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_nodes(documents: list[Any], embed_model: Any) -> list[Any]:
    """Aplica MarkdownNodeParser seguido de SemanticSplitter e enriquece metadados.

    Melhorias markdown-aware:
    - Preserva header_path (ex: "## Security > ### Encryption") para contexto
    - Header level como metadado para filtro por granularidade
    - Não split arbitrário dentro de seções - SemanticSplitter usa embeddings
    """
    from llama_index.core.node_parser import (
        MarkdownNodeParser,
        SemanticSplitterNodeParser,
    )

    md_parser = MarkdownNodeParser.from_defaults(
        include_metadata=True,
        include_prev_next_rel=True,
    )
    semantic_parser = SemanticSplitterNodeParser(
        embed_model=embed_model,
        buffer_size=1,
        breakpoint_percentile_threshold=90,
    )

    nodes = md_parser.get_nodes_from_documents(documents)
    nodes = semantic_parser.get_nodes_from_documents(nodes)

    now = datetime.now(timezone.utc).isoformat()
    for node in nodes:
        text = node.get_content()
        # Extrair header_path do metadata do MarkdownNodeParser
        header_path = node.metadata.get("header_path", "")
        header_level = node.metadata.get("header_level", 0)

        node.metadata.update(
            {
                "chunk_tokens": count_tokens(text),
                "content_hash": content_hash(text),
                "ingested_at": now,
                "header_path": header_path,
                "header_level": header_level,
            }
        )
    return nodes
