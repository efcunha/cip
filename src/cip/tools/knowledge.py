"""Tools read-only de consulta à base de conhecimento oficial (RAG interno).

Exposta ao consumidor externo (CloudPilot) como FunctionTool via registry
para uso em agentes ReAct. NUNCA muta dados: apenas consulta o RAG e
devolve um dict estruturado com a resposta, fontes e flag de grounding.
"""

from __future__ import annotations

from typing import Any

from cip.config import CloudName, get_settings
from cip.logging import get_logger

log = get_logger(__name__)


class KnowledgeBaseTools:
    """Wrapper read-only sobre o RagEngine para exposição como tool."""

    def __init__(self) -> None:
        # Import lazy: evita carregar o modelo de embeddings em import-time.
        from cip.rag.engine import get_engine

        self._engine = get_engine()
        self._settings = get_settings()

    async def consult_official_cloud_knowledge(
        self,
        question: str,
        cloud: CloudName | None = None,
        service: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Consulta a base de conhecimento oficial (RAG interno, read-only).

        Retorna dict com chaves: answer (str), sources (list[dict]),
        has_grounding (bool), refusal_reason (str | None).
        """
        try:
            result = await self._engine.query(
                question=question, cloud=cloud, service=service, category=category
            )
        except Exception as exc:
            log.error("knowledge_query_failed", error=str(exc), question=question[:120])
            return {
                "answer": (
                    "Falha técnica ao consultar a base de conhecimento. "
                    "Tente novamente ou refine a pergunta."
                ),
                "sources": [],
                "has_grounding": False,
                "refusal_reason": "engine_error",
            }

        return {
            "answer": result.answer,
            "sources": [
                {
                    "cloud": s.cloud,
                    "service": s.service,
                    "title": s.title,
                    "url": s.url,
                    "score": s.score,
                }
                for s in result.sources
            ],
            "has_grounding": result.has_grounding,
            "refusal_reason": result.refusal_reason,
        }

    def summarize(self) -> str:
        """Resumo textual para injetar no contexto do LLM (sinal de disponibilidade)."""
        return (
            "Knowledge base oficial disponível via tool "
            f"consult_official_cloud_knowledge (provider={self._settings.embed_provider}, "
            f"model={self._settings.embed_model}, dim={self._settings.embed_dim})."
        )
