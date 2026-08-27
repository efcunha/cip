"""Conexão com o vector store (pgvector) via LlamaIndex."""

from __future__ import annotations

from typing import Any

from cip.config import get_settings
from cip.rag.llm import build_embed_model


def build_vector_store() -> Any:
    from llama_index.vector_stores.postgres import PGVectorStore

    s = get_settings()
    return PGVectorStore.from_params(
        database=s.db_name,
        host=s.db_host,
        password=s.db_password,
        port=s.db_port,
        user=s.db_user,
        table_name="cloud_docs",
        embed_dim=s.embed_dim,
        hnsw_kwargs={
            "hnsw_m": 16,
            "hnsw_ef_construction": 64,
            "hnsw_ef_search": 40,
            "hnsw_dist_method": "vector_cosine_ops",
        },
        # Pool dimensionado para concorrência (evita esgotar conexões sob carga).
        create_engine_kwargs={
            "pool_size": s.db_pool_size,
            "max_overflow": s.db_max_overflow,
            "pool_timeout": s.db_pool_timeout_s,
            "pool_recycle": s.db_pool_recycle_s,
            "pool_pre_ping": True,
        },
    )


def build_index() -> Any:
    from llama_index.core import StorageContext, VectorStoreIndex

    vector_store = build_vector_store()
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    embed_model = build_embed_model()
    return VectorStoreIndex.from_vector_store(
        vector_store=vector_store, storage_context=storage_context, embed_model=embed_model
    )
