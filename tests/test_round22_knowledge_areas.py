"""Testes das adições Round 22 — knowledge areas expandidos.

Valida:
1. SOFTWARE_ARCHITECTURE specialist registrado + router reconhece keywords
2. sources_advanced.yaml carrega pseudo-clouds 'architecture' e 'case-studies'
3. Schema SQL aceita os novos valores de cloud (após migration)
4. New test cases no eval cobrem as 2 áreas
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────
# SOFTWARE_ARCHITECTURE specialist
# ─────────────────────────────────────────────────────────────────────────


class TestSoftwareArchitectureSpecialist:
    """SOFTWARE_ARCHITECTURE prompt registrado + roteável."""

    def test_prompt_registered(self) -> None:
        from cip.prompts.specialists import SPECIALIST_PROMPTS, get_specialist_prompt

        assert "software_architecture" in SPECIALIST_PROMPTS
        assert get_specialist_prompt("software_architecture") is not None

    def test_prompt_covers_core_patterns(self) -> None:
        from cip.prompts.specialists import get_specialist_prompt

        prompt = get_specialist_prompt("software_architecture").lower()
        for kw in ("microservice", "cqrs", "event", "circuit breaker", "saga"):
            assert kw in prompt, f"prompt deve mencionar '{kw}'"

    def test_router_detects_microservices(self) -> None:
        from cip.agents.router import classify

        plan = classify("Quando usar microservices em vez de monolito?")
        assert "software_architecture" in plan.specialists

    def test_router_detects_circuit_breaker(self) -> None:
        from cip.agents.router import classify

        plan = classify("Como implementar circuit breaker para resiliência?")
        assert "software_architecture" in plan.specialists

    def test_router_detects_cqrs(self) -> None:
        from cip.agents.router import classify

        plan = classify("Quando aplicar CQRS em um sistema distribuído?")
        assert "software_architecture" in plan.specialists

    def test_router_detects_saga(self) -> None:
        from cip.agents.router import classify

        plan = classify("Explique o padrão Saga para transações distribuídas.")
        assert "software_architecture" in plan.specialists

    def test_router_detects_event_sourcing(self) -> None:
        from cip.agents.router import classify

        plan = classify("Como aplicar event sourcing em microsserviços?")
        assert "software_architecture" in plan.specialists

    def test_router_pt_br_keywords(self) -> None:
        """Suporta keywords em PT-BR."""
        from cip.agents.router import classify

        plan = classify("Quais os padrões de projeto para arquitetura cloud?")
        # "padrões de projeto" + "arquitetura" estão nos keywords
        assert "software_architecture" in plan.specialists


# ─────────────────────────────────────────────────────────────────────────
# Sources YAML — pseudo-clouds architecture + case-studies
# ─────────────────────────────────────────────────────────────────────────


class TestRound22Sources:
    """sources_advanced.yaml tem architecture + case-studies carregáveis."""

    def test_yaml_top_level_has_architecture(self) -> None:
        import yaml

        yaml_path = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert "architecture" in data
        assert isinstance(data["architecture"], list)
        assert len(data["architecture"]) >= 1

    def test_yaml_top_level_has_case_studies(self) -> None:
        import yaml

        yaml_path = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert "case-studies" in data
        assert isinstance(data["case-studies"], list)
        assert len(data["case-studies"]) >= 5  # AWS postmortems, Netflix, etc

    def test_load_sources_includes_architecture(self) -> None:
        from src.cip.ingestion.ingest import load_sources

        mvp = load_sources("mvp")
        assert "architecture" in mvp
        assert len(mvp["architecture"]) >= 5
        # Cada entry deve ter url válida
        for entry in mvp["architecture"]:
            assert entry.get("urls"), f"Entry sem URLs: {entry}"
            for u in entry["urls"]:
                assert u.startswith("http")

    def test_load_sources_includes_case_studies(self) -> None:
        from src.cip.ingestion.ingest import load_sources

        mvp = load_sources("mvp")
        assert "case-studies" in mvp
        assert len(mvp["case-studies"]) >= 10
        # Deve ter source AWS postmortems
        sources = {e.get("source") for e in mvp["case-studies"]}
        assert "aws-postmortems" in sources

    def test_architecture_categories_have_architecture(self) -> None:
        """Entries de architecture têm category=architecture (não conflitam)."""
        from src.cip.ingestion.ingest import load_sources

        mvp = load_sources("mvp")
        for entry in mvp["architecture"]:
            assert entry.get("category") == "architecture"

    def test_case_studies_categories_have_case_studies(self) -> None:
        """Entries de case-studies têm category=case-studies."""
        from src.cip.ingestion.ingest import load_sources

        mvp = load_sources("mvp")
        for entry in mvp["case-studies"]:
            assert entry.get("category") == "case-studies"


# ─────────────────────────────────────────────────────────────────────────
# Schema SQL — permite novos pseudo-clouds
# ─────────────────────────────────────────────────────────────────────────


class TestSchemaRound22:
    """Schema aceita 'multi', 'architecture', 'case-studies' como cloud."""

    def test_schema_cloud_check_includes_new_values(self) -> None:
        schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
        # Extrai a constraint de cloud
        assert "cloud IN ('aws', 'gcp', 'azure', 'multi', 'architecture', 'case-studies')" in schema

    def test_schema_doc_type_check_includes_new_types(self) -> None:
        schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
        # Deve incluir postmortem, case-study, engineering-blog
        for t in ("postmortem", "case-study", "engineering-blog"):
            assert t in schema, f"doc_type '{t}' deve estar no CHECK do schema"

    def test_migration_002_exists(self) -> None:
        path = ROOT / "db" / "migrations" / "002_relax_cloud_and_doc_type_constraints.sql"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        # Migration deve dropar constraint antiga e recriar
        assert "DROP CONSTRAINT IF EXISTS cloud_docs_cloud_check" in content
        assert "ADD CONSTRAINT cloud_docs_cloud_check" in content
        assert "case-studies" in content

    def test_apply_migrations_script_exists(self) -> None:
        path = ROOT / "scripts" / "apply_migrations.py"
        assert path.exists()


# ─────────────────────────────────────────────────────────────────────────
# Eval test cases — architecture + case-studies
# ─────────────────────────────────────────────────────────────────────────


class TestRound22EvalCases:
    """Novos casos de eval cobrem architecture + case-studies."""

    def test_eval_has_architecture_cases(self) -> None:
        cases_path = ROOT / "eval" / "test_cases.json"
        data = json.loads(cases_path.read_text(encoding="utf-8"))
        arch_cases = [c for c in data["cases"] if c["category"] == "software_architecture"]
        assert len(arch_cases) >= 5, f"Esperado >= 5 casos arch, achou {len(arch_cases)}"

    def test_eval_has_case_studies_cases(self) -> None:
        cases_path = ROOT / "eval" / "test_cases.json"
        data = json.loads(cases_path.read_text(encoding="utf-8"))
        case_cases = [c for c in data["cases"] if c["category"] == "case_studies"]
        assert len(case_cases) >= 3, f"Esperado >= 3 casos case-studies, achou {len(case_cases)}"

    def test_architecture_cases_have_must_mention(self) -> None:
        cases_path = ROOT / "eval" / "eval" / "test_cases.json" if (ROOT / "eval" / "eval").exists() else ROOT / "eval" / "test_cases.json"
        data = json.loads(cases_path.read_text(encoding="utf-8"))
        arch_cases = [c for c in data["cases"] if c["category"] == "software_architecture"]
        for c in arch_cases:
            assert c.get("must_mention"), f"Caso {c['id']} sem must_mention"
            assert len(c["must_mention"]) >= 3


# ─────────────────────────────────────────────────────────────────────────
# homolog_validate.py existe e tem --area
# ─────────────────────────────────────────────────────────────────────────


class TestHomologValidateScript:
    """homolog_validate.py tem os argumentos esperados."""

    def test_script_exists(self) -> None:
        assert (ROOT / "scripts" / "homolog_validate.py").exists()

    def test_script_has_area_arg(self) -> None:
        content = (ROOT / "scripts" / "homolog_validate.py").read_text(encoding="utf-8")
        assert "--area" in content
        assert "software_architecture" in content
        assert "case_studies" in content

    def test_script_has_strict_arg(self) -> None:
        content = (ROOT / "scripts" / "homolog_validate.py").read_text(encoding="utf-8")
        assert "--strict" in content

    def test_script_rejects_stub_provider(self) -> None:
        """require_real_provider() rejeita LLM_PROVIDER=stub."""
        from scripts.homolog_validate import require_real_provider

        with pytest.raises(SystemExit) as exc_info:
            require_real_provider("stub")
        assert "stub" in str(exc_info.value).lower() or "real" in str(exc_info.value).lower()

    def test_script_homolog_suite_has_all_areas(self) -> None:
        """HOMOLOG_SUITE cobre aws/gcp/azure/architecture/case_studies."""
        from scripts.homolog_validate import HOMOLOG_SUITE

        areas = {c["area"] for c in HOMOLOG_SUITE}
        for expected in ("aws", "gcp", "azure", "software_architecture", "case_studies"):
            assert expected in areas, f"HOMOLOG_SUITE precisa cobrir '{expected}'"

    def test_estimate_cost_per_provider(self) -> None:
        """estimate_cost retorna valores diferentes por provider."""
        from scripts.homolog_validate import estimate_cost

        cost_minimax = estimate_cost("resposta de 1000 chars", "minimax")
        cost_bedrock = estimate_cost("resposta de 1000 chars", "bedrock")
        cost_local = estimate_cost("resposta de 1000 chars", "local")
        assert cost_local == 0.0  # local = grátis
        assert cost_bedrock > cost_minimax > 0


# ─────────────────────────────────────────────────────────────────────────
# Forum fetcher — estrutura + funções
# ─────────────────────────────────────────────────────────────────────────


class TestForumFetcherStructure:
    """forum_fetcher.py tem todas as funções + dataclass."""

    def test_module_exists(self) -> None:
        assert (ROOT / "src" / "cip" / "ingestion" / "forum_fetcher.py").exists()

    def test_forum_hit_dataclass(self) -> None:
        from src.cip.ingestion.forum_fetcher import ForumHit

        hit = ForumHit(url="https://x", title="y", source="z")
        assert hit.url == "https://x"
        assert hit.score == 0
        assert hit.matched_terms == []

    def test_is_relevant_requires_both_terms(self) -> None:
        """Relevância = termo de case study + termo de cloud/arquitetura."""
        from src.cip.ingestion.forum_fetcher import _is_relevant

        # Só termo de case study, sem cloud → não relevante
        ok, _ = _is_relevant("postmortem of a cooking recipe", "")
        assert ok is False

        # Ambos
        ok, matched = _is_relevant("aws postmortem lambda outage", "")
        assert ok is True
        assert any("aws" in m for m in matched)

    def test_collect_forum_urls_returns_list(self) -> None:
        """collect_forum_urls é callable e retorna lista."""
        from src.cip.ingestion.forum_fetcher import collect_forum_urls

        # Chamada com httpx.Client mockado deve retornar lista vazia se tudo falhar
        # Aqui só validamos a assinatura — não fazemos fetch real
        import inspect
        sig = inspect.signature(collect_forum_urls)
        assert "sources" in sig.parameters
        assert "min_score" in sig.parameters
        assert "max_per_source" in sig.parameters


class TestIngestForumCasesScript:
    """ingest_forum_cases.py CLI."""

    def test_script_exists(self) -> None:
        assert (ROOT / "scripts" / "ingest_forum_cases.py").exists()

    def test_script_supports_fetch_only(self) -> None:
        content = (ROOT / "scripts" / "ingest_forum_cases.py").read_text(encoding="utf-8")
        assert "--fetch-only" in content
        assert "--source" in content
        assert "--min-score" in content
        assert "--prune-old" in content


# ─────────────────────────────────────────────────────────────────────────
# Makefile targets
# ─────────────────────────────────────────────────────────────────────────


class TestMakefileRound22Targets:
    """Novos Makefile targets adicionados."""

    def test_homolog_real_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "homolog-real:" in makefile
        assert "homolog_validate.py" in makefile

    def test_homolog_software_arch_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "homolog-software-arch:" in makefile

    def test_homolog_cases_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "homolog-cases:" in makefile

    def test_ingest_forum_cases_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "ingest-forum-cases:" in makefile

    def test_schema_migrate_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "schema-migrate:" in makefile


# ─────────────────────────────────────────────────────────────────────────
# Router integration — software_architecture + cloud_provider coexist
# ─────────────────────────────────────────────────────────────────────────


class TestRouterArchitectureIntegration:
    """Em queries mistas (cloud + arquitetura), router combina corretamente."""

    def test_microservices_on_aws(self) -> None:
        from cip.agents.router import classify

        plan = classify("Microsserviços em AWS — como decompor um monolito?")
        assert "software_architecture" in plan.specialists
        assert "aws" in plan.specialists

    def test_circuit_breaker_on_eks(self) -> None:
        from cip.agents.router import classify

        plan = classify("Como implementar circuit breaker em microsserviços no Kubernetes?")
        assert "software_architecture" in plan.specialists
        # kubernetes detectado explicitamente (não usamos "EKS" pq vira IAC_REVIEW)
        assert "kubernetes" in plan.specialists

    def test_saga_in_azure(self) -> None:
        from cip.agents.router import classify

        # Sem "vs" para evitar trigger de COMPARE
        plan = classify("Padrão Saga em microsserviços Azure — orquestração e coreografia")
        assert "software_architecture" in plan.specialists
        assert "azure" in plan.specialists
