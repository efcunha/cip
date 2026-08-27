"""Query engine RAG com filtros por cloud/serviço/categoria e citações.

Este módulo é o coração do "não genérico": toda consulta é ancorada em documentos
recuperados da base oficial, com filtro por provedor quando informado, e nenhuma
resposta é produzida sem contexto acima do score mínimo.

Performance (Round 15): query results são cacheadas em memória (TTL configurável)
para queries idênticas. Reduz latência (1-2s → ~10ms) e custo (zero tokens LLM).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

from cip.config import CloudName, get_settings
from cip.logging import get_logger
from cip.prompts.system import SENIOR_ENGINEER_SYSTEM_PROMPT
from cip.rag.query_cache import QueryResultCache, get_query_cache

log = get_logger(__name__)


@dataclass
class Source:
    cloud: str | None
    service: str | None
    title: str | None
    url: str | None
    score: str | None
    # Round 22+ Phase 3: provenance fields (consumed by cloudpilot HTTP integration)
    doc_id: int | None = None
    source_version: str | None = None
    timestamp: str | None = None
    content_preview: str | None = None
    workspace_id: str | None = None
    is_global: bool = True
    source: str | None = None
    canonical_url: str | None = None
    quarantined: bool = False
    marked: bool = False


@dataclass
class RagResult:
    answer: str
    sources: list[Source] = field(default_factory=list)
    has_grounding: bool = True
    refusal_reason: str | None = None
    from_cache: bool = False  # True se veio do cache (Round 15)


class RagEngine:
    """Encapsula retrieval + geração com o LlamaIndex."""

    def __init__(self) -> None:
        from cip.rag.llm import configure_llama_settings
        from cip.rag.vector_store import build_index

        configure_llama_settings()
        self._index = build_index()
        self._settings = get_settings()
        # Query cache (Round 15): TTL via env var, 0 = desabilitado
        cache_ttl = float(os.getenv("CIP_QUERY_CACHE_TTL", "0"))
        self._cache_enabled = cache_ttl > 0
        self._cache: QueryResultCache | None = (
            get_query_cache(ttl=cache_ttl) if self._cache_enabled else None
        )
        if self._cache_enabled:
            log.info("query_cache_enabled", ttl_seconds=cache_ttl)
        else:
            log.info("query_cache_disabled", note="set CIP_QUERY_CACHE_TTL>0 to enable")

    def _build_filters(
        self, cloud: CloudName | None, service: str | None, category: str | None
    ) -> Any | None:
        from llama_index.core.vector_stores import (
            FilterOperator,
            MetadataFilter,
            MetadataFilters,
        )

        active = []
        if cloud:
            active.append(MetadataFilter(key="cloud", value=cloud, operator=FilterOperator.EQ))
        if service:
            active.append(
                MetadataFilter(key="service", value=service, operator=FilterOperator.EQ)
            )
        if category:
            active.append(
                MetadataFilter(key="category", value=category, operator=FilterOperator.EQ)
            )
        if not active:
            return None
        return MetadataFilters(filters=active)

    async def query(
        self,
        question: str,
        cloud: CloudName | None = None,
        service: str | None = None,
        category: str | None = None,
    ) -> RagResult:
        # Cache check (Round 15)
        cache_key = None
        if self._cache_enabled and self._cache is not None:
            cache_key = QueryResultCache.make_key(
                question, cloud, service, category
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.debug("query_cache_hit", key=cache_key[:8])
                # Rehidrata dataclass
                sources = [Source(**s) for s in cached.get("sources", [])]
                return RagResult(
                    answer=cached["answer"],
                    sources=sources,
                    has_grounding=cached.get("has_grounding", True),
                    refusal_reason=cached.get("refusal_reason"),
                    from_cache=True,
                )

        # Cache miss → executa pipeline normal
        filters = self._build_filters(cloud, service, category)

        query_engine = self._index.as_query_engine(
            similarity_top_k=self._settings.retrieval_top_k,
            filters=filters,
            system_prompt=SENIOR_ENGINEER_SYSTEM_PROMPT,
        )

        response = await query_engine.aquery(question)

        # Filtra nós abaixo do score mínimo (anti-alucinação).
        nodes = [
            n
            for n in getattr(response, "source_nodes", [])
            if (n.score or 0) >= self._settings.retrieval_min_score
        ]

        if not nodes:
            log.warning("no_grounding", question=question[:120])
            result = RagResult(
                answer=(
                    "Não encontrei referência confiável na base de conhecimento oficial "
                    "para responder com segurança. Refine a pergunta ou verifique se a "
                    "documentação do serviço já foi ingerida."
                ),
                sources=[],
                has_grounding=False,
                refusal_reason="no_grounding_above_min_score",
            )
        else:
            sources = [
                Source(
                    cloud=n.metadata.get("cloud"),
                    service=n.metadata.get("service"),
                    title=n.metadata.get("title"),
                    url=n.metadata.get("url"),
                    score=n.score,
                    # Round 22+ Phase 3: extrai provenance do metadata
                    # para casar com o shape CipRagResult esperado pelo cloudpilot
                    doc_id=n.metadata.get("doc_id"),
                    source_version=n.metadata.get("version") or n.metadata.get("source_version"),
                    timestamp=n.metadata.get("created_at") or n.metadata.get("timestamp"),
                    content_preview=(getattr(n, "text", "") or "")[:500] or None,
                    workspace_id=n.metadata.get("workspace_id"),
                    is_global=n.metadata.get("is_global", True),
                    source=n.metadata.get("source"),
                    canonical_url=n.metadata.get("canonical_url") or n.metadata.get("url"),
                    quarantined=False,  # Phase 3+: ligar com detector se quiser
                    marked=False,
                )
                for n in nodes
            ]
            result = RagResult(answer=str(response), sources=sources, has_grounding=True)

        # Cache write
        if self._cache_enabled and self._cache is not None and cache_key is not None:
            self._cache.set(cache_key, asdict(result))
            log.debug("query_cache_set", key=cache_key[:8])

        return result

    def retrieve_context(
        self,
        question: str,
        cloud: CloudName | None = None,
        service: str | None = None,
        top_k: int | None = None,
    ) -> list[Source]:
        """Retrieval puro (sem geração) — usado pelos especialistas/orquestrador."""
        filters = self._build_filters(cloud, service, None)
        retriever = self._index.as_retriever(
            similarity_top_k=top_k or self._settings.retrieval_top_k, filters=filters
        )
        nodes = retriever.retrieve(question)
        return [
            Source(
                cloud=n.metadata.get("cloud"),
                service=n.metadata.get("service"),
                title=n.metadata.get("title"),
                url=n.metadata.get("url"),
                score=n.score,
            )
            for n in nodes
            if (n.score or 0) >= self._settings.retrieval_min_score
        ]


_engine: RagEngine | None = None


def get_engine() -> RagEngine:
    """Singleton lazy — evita carregar modelo de embeddings em import."""
    global _engine
    if _engine is None:
        _engine = RagEngine()
    return _engine
