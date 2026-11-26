"""Query engine RAG com filtros por cloud/serviço/categoria e citações.

Este módulo é o coração do "não genérico": toda consulta é ancorada em documentos
recuperados da base oficial, com filtro por provedor quando informado, e nenhuma
resposta é produzida sem contexto acima do score mínimo.

Performance (Round 15): query results são cacheadas em memória (TTL configurável)
para queries idênticas. Reduz latência (1-2s → ~10ms) e custo (zero tokens LLM).
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any

from cip.config import CloudName, get_settings
from cip.logging import get_logger
from cip.prompts.system import SENIOR_ENGINEER_SYSTEM_PROMPT
from cip.rag.query_cache import QueryResultCache, get_query_cache

NO_GROUNDING_ANSWER = (
    "Não encontrei referência confiável na base de conhecimento oficial "
    "para responder com segurança. Refine a pergunta ou verifique se a "
    "documentação do serviço já foi ingerida."
)
FALLBACK_NOTICE = (
    "\n\n[A geração foi interrompida; exibindo trechos da documentação oficial.]\n\n"
)

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
    fallback: str | None = None  # motivo do fallback extrativo (LLM local), ou None


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

    def _apply_tenant_scope(
        self,
        nodes: list[Any],
        tenant_id: str | None,
        include_global: bool,
    ) -> list[Any]:
        """Filtra nós por escopo de tenant (isolamento de corpus).

        Regras:
        - Nó com ``workspace_id`` é documento de tenant: só aparece para o
          tenant dono (``workspace_id == tenant_id``). Tenant A nunca vê
          documento do tenant B.
        - Nó sem ``workspace_id`` é global: só aparece quando
          ``include_global=True``.
        - ``include_global=False`` com tenant sem documentos próprios →
          lista vazia (→ refusal, fail-closed).

        O corpus atual é 100% global (nenhum nó tem ``workspace_id``), então
        ``include_global=False`` resulta em refusal para qualquer tenant.
        """
        scoped: list[Any] = []
        for n in nodes:
            meta = getattr(n, "metadata", {}) or {}
            ws = meta.get("workspace_id")
            if ws is not None:
                if tenant_id is not None and str(ws) == str(tenant_id):
                    scoped.append(n)
                # tenant diverge → excluído (isolamento)
            elif include_global:
                scoped.append(n)
        return scoped

    async def query(
        self,
        question: str,
        cloud: CloudName | None = None,
        service: str | None = None,
        category: str | None = None,
        tenant_id: str | None = None,
        include_global: bool = True,
        top_k: int | None = None,
        min_score: float | None = None,
        force_extractive: bool = False,
    ) -> RagResult:
        if self._settings.llm_provider == "local" and not force_extractive:
            final: RagResult | None = None
            async for kind, payload in self.query_stream(
                question, cloud, service, category,
                tenant_id=tenant_id, include_global=include_global,
                top_k=top_k, min_score=min_score,
            ):
                if kind == "result":
                    final = payload
            assert final is not None
            return final
        effective_top_k = (
            self._settings.retrieval_top_k if top_k is None else top_k
        )
        effective_min_score = (
            self._settings.retrieval_min_score if min_score is None else min_score
        )

        # Cache check (Round 15) — tenant_id/include_global entram na chave.
        cache_key = None
        if self._cache_enabled and self._cache is not None:
            cache_key = QueryResultCache.make_key(
                question, cloud, service, category, tenant_id, include_global
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
        if self._settings.llm_provider == "extractive" or force_extractive:
            return await self._query_extractive(
                question, cloud, service, category,
                tenant_id=tenant_id,
                include_global=include_global,
                top_k=effective_top_k,
                min_score=effective_min_score,
                cache_key=cache_key,
            )

        filters = self._build_filters(cloud, service, category)

        query_engine = self._index.as_query_engine(
            similarity_top_k=effective_top_k,
            filters=filters,
            system_prompt=SENIOR_ENGINEER_SYSTEM_PROMPT,
        )

        response = await query_engine.aquery(question)

        # Filtra nós abaixo do score mínimo (anti-alucinação) + tenant scope.
        nodes = [
            n
            for n in getattr(response, "source_nodes", [])
            if (n.score or 0) >= effective_min_score
        ]
        nodes = self._apply_tenant_scope(nodes, tenant_id, include_global)

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

    async def _query_extractive(
        self,
        question: str,
        cloud: CloudName | None,
        service: str | None,
        category: str | None,
        cache_key: str | None,
        tenant_id: str | None = None,
        include_global: bool = True,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> RagResult:
        """Pipeline extrativo local: retrieval puro + síntese determinística (sem LLM).

        Recupera nós por similaridade (embedding local), filtra pelo score
        mínimo e sintetiza uma resposta que cita os trechos recuperados como
        dados — nunca como instrução operacional. Sem grounding → refusal.
        """
        from cip.rag.extractive import synthesize_extractive

        effective_top_k = self._settings.retrieval_top_k if top_k is None else top_k
        effective_min_score = (
            self._settings.retrieval_min_score if min_score is None else min_score
        )

        filters = self._build_filters(cloud, service, category)
        retriever = self._index.as_retriever(
            similarity_top_k=effective_top_k, filters=filters
        )
        nodes = await retriever.aretrieve(question)
        nodes = [
            n for n in nodes if (n.score or 0) >= effective_min_score
        ]
        nodes = self._apply_tenant_scope(nodes, tenant_id, include_global)

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
                    doc_id=n.metadata.get("doc_id"),
                    source_version=n.metadata.get("version") or n.metadata.get("source_version"),
                    timestamp=n.metadata.get("created_at") or n.metadata.get("timestamp"),
                    content_preview=(getattr(n, "text", "") or "")[:500] or None,
                    workspace_id=n.metadata.get("workspace_id"),
                    is_global=n.metadata.get("is_global", True),
                    source=n.metadata.get("source"),
                    canonical_url=n.metadata.get("canonical_url") or n.metadata.get("url"),
                    quarantined=False,
                    marked=False,
                )
                for n in nodes
            ]
            answer = synthesize_extractive(question, nodes)
            result = RagResult(answer=answer, sources=sources, has_grounding=True)

        if self._cache_enabled and self._cache is not None and cache_key is not None:
            self._cache.set(cache_key, asdict(result))
            log.debug("query_cache_set", key=cache_key[:8])

        return result

    # ── LLM local (Ollama): geração fundamentada com streaming real ────────

    @staticmethod
    def _sources_from_nodes(nodes: list[Any]) -> list[Source]:
        """Constrói ``Source`` (com proveniência) — usado só pelo caminho local."""
        return [
            Source(
                cloud=n.metadata.get("cloud"),
                service=n.metadata.get("service"),
                title=n.metadata.get("title"),
                url=n.metadata.get("url"),
                score=n.score,
                doc_id=n.metadata.get("doc_id"),
                source_version=n.metadata.get("version") or n.metadata.get("source_version"),
                timestamp=n.metadata.get("created_at") or n.metadata.get("timestamp"),
                content_preview=(getattr(n, "text", "") or "")[:500] or None,
                workspace_id=n.metadata.get("workspace_id"),
                is_global=n.metadata.get("is_global", True),
                source=n.metadata.get("source"),
                canonical_url=n.metadata.get("canonical_url") or n.metadata.get("url"),
                quarantined=False,
                marked=False,
            )
            for n in nodes
        ]

    def _get_llm(self) -> Any:
        llm = getattr(self, "_llm", None)
        if llm is not None:
            return llm
        from llama_index.core import Settings as LlamaSettings

        return LlamaSettings.llm

    async def _open_chat_stream(self, llm: Any, messages: list[Any]) -> Any:
        stream = llm.astream_chat(messages)
        if inspect.isawaitable(stream):
            stream = await stream
        return stream.__aiter__()

    async def query_stream(
        self,
        question: str,
        cloud: CloudName | None = None,
        service: str | None = None,
        category: str | None = None,
        tenant_id: str | None = None,
        include_global: bool = True,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Gera a resposta com o LLM local, emitindo ``("delta", str)`` e, ao fim,
        ``("result", RagResult)``.

        Ordem: cache -> retrieval -> gate de min_score (sem LLM se vazio) -> LLM
        com contexto numerado -> validação de citações. Erro, timeout, saída vazia
        ou citação inválida => síntese extrativa (``RagResult.fallback`` preenchido).
        """
        from cip.rag.extractive import synthesize_extractive
        from cip.rag.grounded import (
            append_sources_footer,
            build_grounded_messages,
            is_decline,
            validate_answer,
        )

        s = self._settings
        eff_top_k = s.retrieval_top_k if top_k is None else top_k
        eff_min = s.retrieval_min_score if min_score is None else min_score

        cache = getattr(self, "_cache", None) if getattr(self, "_cache_enabled", False) else None
        cache_key = None
        if cache is not None:
            cache_key = QueryResultCache.make_key(
                question, cloud, service, category, tenant_id, include_global
            )
            cached = cache.get(cache_key)
            if cached is not None:
                log.debug("query_cache_hit", key=cache_key[:8])
                hit = RagResult(
                    answer=cached["answer"],
                    sources=[Source(**x) for x in cached.get("sources", [])],
                    has_grounding=cached.get("has_grounding", True),
                    refusal_reason=cached.get("refusal_reason"),
                    from_cache=True,
                )
                yield ("delta", hit.answer)
                yield ("result", hit)
                return

        def _store(res: RagResult) -> None:
            if cache is not None and cache_key is not None:
                cache.set(cache_key, asdict(res))

        filters = self._build_filters(cloud, service, category)
        retriever = self._index.as_retriever(similarity_top_k=eff_top_k, filters=filters)
        nodes = await retriever.aretrieve(question)
        nodes = [n for n in nodes if (n.score or 0) >= eff_min]
        nodes = self._apply_tenant_scope(nodes, tenant_id, include_global)

        if not nodes:
            log.warning("no_grounding", question=question[:120])
            refusal = RagResult(
                answer=NO_GROUNDING_ANSWER,
                sources=[],
                has_grounding=False,
                refusal_reason="no_grounding_above_min_score",
            )
            _store(refusal)
            yield ("delta", refusal.answer)
            yield ("result", refusal)
            return

        ctx_nodes = nodes[: max(1, int(s.llm_context_top_k))]
        sources = self._sources_from_nodes(ctx_nodes)
        system, user = build_grounded_messages(question, ctx_nodes, s.llm_context_chunk_chars)

        t0 = time.perf_counter()
        emitted = False
        answer = ""
        reason: str | None = None
        held = ""  # buffer inicial: não vaza a resposta de recusa NAO_ENCONTRADO
        released = False
        try:
            from llama_index.core.llms import ChatMessage

            messages = [
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user),
            ]
            llm = self._get_llm()
            loop = asyncio.get_running_loop()
            start = loop.time()
            first_deadline = start + float(s.llm_first_token_timeout_s)
            total_deadline = start + float(s.llm_timeout_s)
            it: Any = None
            first = True
            try:
                it = await asyncio.wait_for(
                    self._open_chat_stream(llm, messages),
                    timeout=max(0.001, min(first_deadline, total_deadline) - loop.time()),
                )
                while True:
                    limit = first_deadline if first else total_deadline
                    remaining = min(limit, total_deadline) - loop.time()
                    chunk = await asyncio.wait_for(it.__anext__(), timeout=max(0.001, remaining))
                    first = False
                    delta = getattr(chunk, "delta", None) or ""
                    if not delta:
                        continue
                    answer += delta
                    if released:
                        emitted = True
                        yield ("delta", delta)
                        continue
                    held += delta
                    probe = held.strip().strip(".").upper()
                    if "NAO_ENCONTRADO".startswith(probe):
                        continue  # ainda pode ser a recusa; segura
                    released = True
                    emitted = True
                    yield ("delta", held)
            except StopAsyncIteration:
                pass
            except TimeoutError:
                reason = "timeout_first_token" if first else "timeout_total"
        except Exception as exc:  # noqa: BLE001 - qualquer falha do LLM => fallback
            reason = f"llm_error:{type(exc).__name__}"
            log.warning("llm_stream_error", error=str(exc)[:200])

        if reason is None:
            if is_decline(answer):
                refusal = RagResult(
                    answer=NO_GROUNDING_ANSWER,
                    sources=[],
                    has_grounding=False,
                    refusal_reason="model_declined",
                )
                _store(refusal)
                yield ("delta", refusal.answer)
                yield ("result", refusal)
                return
            if not answer.strip():
                reason = "empty_output"
            else:
                check = validate_answer(answer, ctx_nodes)
                if not check.ok:
                    reason = f"validation:{check.reason}"
                else:
                    if not released:
                        yield ("delta", held)
                    final_text = append_sources_footer(answer, ctx_nodes, check.cited_indices)
                    footer = final_text[len(answer):]
                    if footer:
                        yield ("delta", footer)
                    ok = RagResult(answer=final_text, sources=sources, has_grounding=True)
                    _store(ok)
                    yield ("result", ok)
                    return

        # Fallback extrativo (nunca cacheado).
        log.warning(
            "llm_fallback_extractive",
            reason=reason,
            model=s.llm_model,
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
        )
        extractive = synthesize_extractive(question, ctx_nodes)
        yield ("delta", (FALLBACK_NOTICE if emitted else "") + extractive)
        yield (
            "result",
            RagResult(answer=extractive, sources=sources, has_grounding=True, fallback=reason),
        )

    def retrieve_context(
        self,
        question: str,
        cloud: CloudName | None = None,
        service: str | None = None,
        top_k: int | None = None,
        tenant_id: str | None = None,
        include_global: bool = True,
    ) -> list[Source]:
        """Retrieval puro (sem geração) — usado pelos especialistas/orquestrador."""
        filters = self._build_filters(cloud, service, None)
        retriever = self._index.as_retriever(
            similarity_top_k=top_k or self._settings.retrieval_top_k, filters=filters
        )
        nodes = retriever.retrieve(question)
        nodes = [
            n for n in nodes if (n.score or 0) >= self._settings.retrieval_min_score
        ]
        nodes = self._apply_tenant_scope(nodes, tenant_id, include_global)
        return [
            Source(
                cloud=n.metadata.get("cloud"),
                service=n.metadata.get("service"),
                title=n.metadata.get("title"),
                url=n.metadata.get("url"),
                score=n.score,
            )
            for n in nodes
        ]


_engine: RagEngine | None = None


def get_engine() -> RagEngine:
    """Singleton lazy — evita carregar modelo de embeddings em import."""
    global _engine
    if _engine is None:
        _engine = RagEngine()
    return _engine
