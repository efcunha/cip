"""Registro de tools e coleta consolidada de sinais de custo por cloud.

O orquestrador chama `collect_cost_signals` para obter um resumo textual dos dados ao
vivo (read-only) das clouds relevantes, que é injetado no contexto do LLM.

Também expõe as tools como `FunctionTool` do LlamaIndex, permitindo uso via agente
ReAct/function-calling na evolução para especialistas ativos (Fase 4).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cip.logging import get_logger

log = get_logger(__name__)

# Instanciação lazy: só constrói o client da cloud quando realmente usada.
_BUILDERS: dict[str, Callable[[], Any]] = {}


def _register(cloud: str, builder: Callable[[], Any]) -> None:
    _BUILDERS[cloud] = builder


def _aws() -> Any:
    from cip.tools.aws_cost import AWSCostTools

    return AWSCostTools()


def _azure() -> Any:
    from cip.tools.azure_advisor import AzureAdvisorTools

    return AzureAdvisorTools()


def _gcp() -> Any:
    from cip.tools.gcp_recommender import GCPRecommenderTools

    return GCPRecommenderTools()


def _knowledge() -> Any:
    from cip.tools.knowledge import KnowledgeBaseTools

    return KnowledgeBaseTools()


_register("aws", _aws)
_register("azure", _azure)
_register("gcp", _gcp)
_register("knowledge", _knowledge)


def collect_cost_signals(clouds: list[str]) -> tuple[str, list[str]]:
    """Retorna (texto_resumo, tools_usadas) para as clouds informadas."""
    lines: list[str] = []
    used: list[str] = []
    for cloud in clouds:
        builder = _BUILDERS.get(cloud)
        if not builder:
            continue
        try:
            tool = builder()
            lines.append(tool.summarize())
            used.append(f"{cloud}:cost")
        except Exception as exc:  # best-effort
            log.warning("tool_build_failed", cloud=cloud, error=str(exc))
    return "\n".join(lines), used


def build_function_tools(clouds: list[str]) -> list[Any]:
    """Expõe as tools como FunctionTool do LlamaIndex (para agente ativo)."""
    from llama_index.core.tools import FunctionTool

    tools: list[Any] = []
    for cloud in clouds:
        builder = _BUILDERS.get(cloud)
        if not builder:
            continue
        try:
            obj = builder()
        except Exception as exc:
            log.warning("tool_build_failed", cloud=cloud, error=str(exc))
            continue
        if hasattr(obj, "summarize"):
            tools.append(
                FunctionTool.from_defaults(
                    fn=obj.summarize,
                    name=f"{cloud}_cost_summary",
                    description=f"Resumo read-only de custo/inventário da conta {cloud.upper()}.",
                )
            )
    return tools


def build_knowledge_function_tool() -> Any:
    """Expõe a tool de knowledge base (RAG interno) como FunctionTool."""
    from llama_index.core.tools import FunctionTool

    obj = _knowledge()
    return FunctionTool.from_defaults(
        fn=obj.consult_official_cloud_knowledge,
        name="consult_official_cloud_knowledge",
        description=(
            "Consulta a base de conhecimento oficial CIP (documentação pública "
            "de AWS/GCP/Azure, read-only). Use quando precisar de referência "
            "técnica canônica para responder perguntas sobre serviços de cloud."
        ),
    )
