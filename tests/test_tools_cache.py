"""Testes para o sistema de cache TTL das tools cloud (Fase 2).

Valida:
- Cache hit/miss corretamente
- TTL funciona (valor expira após tempo)
- Thread-safe (uso concorrente)
- Invalidação manual

Uso:
    pytest tests/test_tools_cache.py -v
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from cip.tools.cache import TTLCache, cached


class TestTTLCache:
    """Testes do TTLCache isolado."""

    def test_set_get_hit(self) -> None:
        c = TTLCache(default_ttl=60)
        c.set("k1", {"data": 123})
        hit, value = c.get("k1")
        assert hit is True
        assert value == {"data": 123}

    def test_get_miss_returns_false(self) -> None:
        c = TTLCache(default_ttl=60)
        hit, value = c.get("missing")
        assert hit is False
        assert value is None

    def test_ttl_expiry(self) -> None:
        c = TTLCache(default_ttl=0.1)  # 100ms
        c.set("k1", "value")
        assert c.get("k1")[0] is True
        time.sleep(0.2)
        hit, _ = c.get("k1")
        assert hit is False, "Cache deveria ter expirado"

    def test_invalidate_specific(self) -> None:
        c = TTLCache()
        c.set("k1", "v1")
        c.set("k2", "v2")
        c.invalidate("k1")
        assert c.get("k1")[0] is False
        assert c.get("k2")[0] is True

    def test_invalidate_all(self) -> None:
        c = TTLCache()
        c.set("k1", "v1")
        c.set("k2", "v2")
        c.invalidate()
        assert c.get("k1")[0] is False
        assert c.get("k2")[0] is False

    def test_stats(self) -> None:
        c = TTLCache(default_ttl=120)
        c.set("k1", "v")
        stats = c.stats()
        assert stats["size"] == 1
        assert stats["ttl_default"] == 120


class TestCachedDecorator:
    """Testes do decorator @cached."""

    def test_decorator_caches_result(self) -> None:
        counter = {"n": 0}

        class Service:
            @cached(ttl=60)
            def expensive(self, x: int) -> int:
                counter["n"] += 1
                return x * 2

        s = Service()
        assert s.expensive(5) == 10
        assert s.expensive(5) == 10
        assert s.expensive(5) == 10
        assert counter["n"] == 1, f"Esperado 1 chamada, obtido {counter['n']}"

    def test_decorator_different_args(self) -> None:
        counter = {"n": 0}

        class Service:
            @cached(ttl=60)
            def compute(self, x: int) -> int:
                counter["n"] += 1
                return x**2

        s = Service()
        assert s.compute(2) == 4
        assert s.compute(3) == 9
        assert s.compute(2) == 4
        assert counter["n"] == 2

    def test_decorator_ttl_expiry(self) -> None:
        counter = {"n": 0}

        class Service:
            @cached(ttl=0.1)
            def compute(self, x: int) -> int:
                counter["n"] += 1
                return x * 10

        s = Service()
        assert s.compute(1) == 10
        assert s.compute(1) == 10  # hit
        time.sleep(0.2)
        assert s.compute(1) == 10  # miss again
        assert counter["n"] == 2

    def test_decorator_kwargs_different_cache(self) -> None:
        counter = {"n": 0}

        class Service:
            @cached(ttl=60)
            def compute(self, x: int = 1, y: int = 1) -> int:
                counter["n"] += 1
                return x + y * 10

        s = Service()
        assert s.compute(x=1, y=2) == 21
        assert s.compute(x=2, y=1) == 12
        assert s.compute(x=1, y=2) == 21  # hit
        assert counter["n"] == 2


class TestCloudToolsIntegration:
    """Testes de integração com tools cloud (smoke test sem credenciais)."""

    def test_aws_tools_degrade_gracefully(self) -> None:
        """Sem credenciais AWS, summarize() deve retornar mensagem amigável."""
        from cip.tools.aws_cost import AWSCostTools

        t = AWSCostTools()
        s = t.summarize()
        # Sem creds válidas, retorna string amigável (não exception)
        assert isinstance(s, str)
        assert "AWS" in s or "credenciais" in s.lower()

    def test_azure_tools_degrade_gracefully(self) -> None:
        from cip.tools.azure_advisor import AzureAdvisorTools

        t = AzureAdvisorTools()
        s = t.summarize()
        assert isinstance(s, str)
        assert "Azure" in s or "Service Principal" in s

    def test_gcp_tools_degrade_gracefully(self) -> None:
        """GCP pode lançar exceção na inicialização sem credenciais (esperado).
        summarize() deve retornar mensagem amigável."""
        from cip.tools.gcp_recommender import GCPRecommenderTools

        try:
            t = GCPRecommenderTools()
            s = t.summarize()
            assert isinstance(s, str)
            # Se construir, summarize deve mencionar GCP ou erro de creds
            assert "GCP" in s or "Service Account" in s or "não foi possível" in s
        except Exception as exc:
            # Também aceitável: construtor falha sem credenciais
            # (GCP Recommender SDK tenta autenticar no __init__)
            assert "credentials" in str(exc).lower() or "auth" in str(exc).lower() or "default" in str(exc).lower()


@pytest.mark.asyncio
async def test_cache_concurrent_access() -> None:
    """Cache deve ser thread-safe (não corromper estado com N acessos simultâneos)."""
    c = TTLCache(default_ttl=60)
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            for j in range(100):
                c.set(f"k{i}", f"v{i}_{j}")
                c.get(f"k{i}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Erros de concorrência: {errors}"
    assert c.stats()["size"] == 10