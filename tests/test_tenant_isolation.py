"""Isolamento de tenant no retrieval (Round 25).

Valida o escopo de corpus aplicado por ``RagEngine._apply_tenant_scope`` e a
chave de cache multi-tenant (``QueryResultCache.make_key``). O corpus atual é
100% global (nenhum nó tem ``workspace_id``), então ``include_global=False``
resulta em refusal (fail-closed) para qualquer tenant.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from cip.rag.engine import RagEngine
from cip.rag.query_cache import QueryResultCache


def _node(ws: str | None = None, score: float = 0.9) -> Any:
    meta: dict[str, Any] = {
        "title": "doc",
        "url": "https://docs.example.com/x",
        "cloud": "aws",
        "service": "s3",
        "category": "storage",
    }
    if ws is not None:
        meta["workspace_id"] = ws
    return SimpleNamespace(text="chunk", score=score, metadata=meta)


def _scope(nodes: list[Any], tenant_id: str | None, include_global: bool) -> list[Any]:
    # Método não usa `self`; chamado como função pura para evitar instanciar o
    # RagEngine (que carrega o index/embedding model).
    return RagEngine._apply_tenant_scope(None, nodes, tenant_id, include_global)  # type: ignore[arg-type]


def test_tenant_a_does_not_see_tenant_b() -> None:
    nodes = [_node(ws="tenant-b"), _node(ws="tenant-a")]
    scoped = _scope(nodes, "tenant-a", include_global=True)
    assert [n.metadata["workspace_id"] for n in scoped] == ["tenant-a"]


def test_tenant_a_sees_global_when_allowed() -> None:
    nodes = [_node(ws=None), _node(ws="tenant-b")]
    scoped = _scope(nodes, "tenant-a", include_global=True)
    assert len(scoped) == 1
    assert scoped[0].metadata.get("workspace_id") is None


def test_tenant_a_does_not_see_global_when_disallowed() -> None:
    nodes = [_node(ws=None), _node(ws="tenant-a")]
    scoped = _scope(nodes, "tenant-a", include_global=False)
    assert [n.metadata.get("workspace_id") for n in scoped] == ["tenant-a"]


def test_tenant_without_docs_gets_refusal_when_no_global() -> None:
    nodes = [_node(ws=None), _node(ws="tenant-b")]
    scoped = _scope(nodes, "tenant-a", include_global=False)
    assert scoped == []


def test_cache_key_isolates_tenants() -> None:
    k1 = QueryResultCache.make_key("q", tenant_id="a", include_global=True)
    k2 = QueryResultCache.make_key("q", tenant_id="b", include_global=True)
    k3 = QueryResultCache.make_key("q", tenant_id="a", include_global=False)
    assert k1 != k2
    assert k1 != k3


def test_cloud_service_category_filters_still_built() -> None:
    """cloud/service/category continuam alimentando MetadataFilters (não tenant)."""
    filters = RagEngine._build_filters(None, "aws", "s3", "storage")  # type: ignore[arg-type]
    assert filters is not None
    keys = {f.key for f in filters.filters}
    assert keys == {"cloud", "service", "category"}
