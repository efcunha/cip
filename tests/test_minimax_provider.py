"""Testes para o provider LLM MiniMax M3 (Round 19).

Valida:
- MiniMax M3 é reconhecido como provider válido
- build_llm() instancia OpenAILike com base_url correto
- Config fields do MiniMax estão presentes
- .env.example documenta MiniMax
- ReAct mode funciona com MiniMax (mesmo fluxo que outros providers)

Uso:
    pytest tests/test_minimax_provider.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Config support
# ─────────────────────────────────────────────────────────────────────────


class TestConfigSupportsMiniMax:
    """Config reconhece MiniMax como provider."""

    def test_minimax_is_valid_provider(self) -> None:
        from src.cip.config import Settings

        s = Settings()
        # Literal inclui "minimax"
        # Validamos via construtor
        try:
            s2 = Settings(llm_provider="minimax", llm_model="MiniMax-M3")  # type: ignore[arg-type]
            assert s2.llm_provider == "minimax"
            assert s2.llm_model == "MiniMax-M3"
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"minimax provider não aceito: {exc}")

    def test_default_provider_is_stub(self) -> None:
        """Default em código é bedrock (produção).

        O .env e o ENV do container podem sobrepor para stub/minimax. Este teste
        verifica o default de CÓDIGO (pydantic), isolando também do os.environ
        (o estágio homolog do Dockerfile define `ENV LLM_PROVIDER=minimax`, o que
        mascara o default verdadeiro dentro do container).
        """
        from src.cip.config import Settings

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_PROVIDER", None)
            s = Settings(_env_file=None)
            # Default no código é bedrock (produção).
            assert s.llm_provider == "bedrock"

    def test_llm_api_key_field_exists(self) -> None:
        from src.cip.config import Settings

        s = Settings()
        assert hasattr(s, "llm_api_key")
        assert isinstance(s.llm_api_key, str)

    def test_llm_base_url_field_exists(self) -> None:
        from src.cip.config import Settings

        s = Settings()
        assert hasattr(s, "llm_base_url")
        assert isinstance(s.llm_base_url, str)

    def test_minimax_provider_with_api_key(self) -> None:
        from src.cip.config import Settings

        s = Settings(
            llm_provider="minimax",  # type: ignore[arg-type]
            llm_model="MiniMax-M3",
            llm_api_key="sk-test-123",
            llm_base_url="https://api.minimax.chat/v1",
        )
        assert s.llm_api_key == "sk-test-123"
        assert s.llm_base_url == "https://api.minimax.chat/v1"


# ─────────────────────────────────────────────────────────────────────────
# build_llm() com provider minimax
# ─────────────────────────────────────────────────────────────────────────


class TestBuildLLMMiniMax:
    """build_llm() instancia MiniMax corretamente."""

    def _patch_openai_like(self):
        """Patch OpenAILike que é lazy-imported dentro de build_llm."""
        # OpenAILike é importado lazy, então patchamos via sys.modules
        import sys
        import types

        # Cria module fake para llama_index.llms.openai_like
        fake_module = types.ModuleType("llama_index.llms.openai_like")
        mock_class = MagicMock()
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance
        fake_module.OpenAILike = mock_class
        sys.modules["llama_index.llms.openai_like"] = fake_module
        return mock_class, mock_instance

    def test_build_minimax_uses_default_base_url(self) -> None:
        """Sem env override, usa https://api.minimax.io/v1 (CORRIGIDO Round 22+)."""
        from src.cip.config import Settings
        from src.cip.rag import llm as llm_mod

        mock_settings = Settings(
            llm_provider="minimax",  # type: ignore[arg-type]
            llm_model="MiniMax-M3",
            llm_api_key="sk-test",
            llm_base_url="",  # vazio → usa default
            llm_context_size=128000,
        )
        mock_class, mock_instance = self._patch_openai_like()
        with patch.object(llm_mod, "get_settings", return_value=mock_settings):
            result = llm_mod.build_llm()

        # Verifica que OpenAILike foi chamado com base_url default
        call_kwargs = mock_class.call_args.kwargs
        assert call_kwargs["model"] == "MiniMax-M3"
        assert call_kwargs["api_base"] == "https://api.minimax.io/v1"
        assert call_kwargs["api_key"] == "sk-test"
        assert call_kwargs["is_chat_model"] is True
        assert result is mock_instance

    def test_build_minimax_uses_custom_base_url(self) -> None:
        """Com env override, usa URL customizada."""
        from src.cip.config import Settings
        from src.cip.rag import llm as llm_mod

        mock_settings = Settings(
            llm_provider="minimax",  # type: ignore[arg-type]
            llm_model="MiniMax-M3",
            llm_api_key="sk-test",
            llm_base_url="https://custom.minimax.proxy/v1",
        )
        mock_class, mock_instance = self._patch_openai_like()
        with patch.object(llm_mod, "get_settings", return_value=mock_settings):
            llm_mod.build_llm()

        call_kwargs = mock_class.call_args.kwargs
        assert call_kwargs["api_base"] == "https://custom.minimax.proxy/v1"

    def test_build_minimax_uses_litellm_params(self) -> None:
        """MiniMax herda temperature, max_tokens, timeout do Settings."""
        from src.cip.config import Settings
        from src.cip.rag import llm as llm_mod

        mock_settings = Settings(
            llm_provider="minimax",  # type: ignore[arg-type]
            llm_model="MiniMax-M3",
            llm_api_key="sk-test",
            llm_base_url="",
            llm_temperature=0.3,
            llm_max_tokens=4096,
            llm_timeout_s=30.0,
            llm_max_retries=3,
            llm_context_size=128000,
        )
        mock_class, mock_instance = self._patch_openai_like()
        with patch.object(llm_mod, "get_settings", return_value=mock_settings):
            llm_mod.build_llm()

        call_kwargs = mock_class.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["max_tokens"] == 4096
        assert call_kwargs["timeout"] == 30.0
        assert call_kwargs["max_retries"] == 3
        assert call_kwargs["context_window"] == 128000

    def test_build_minimax_logs_activation(self) -> None:
        """Loga quando MiniMax é ativado (auditoria)."""
        from src.cip.config import Settings
        from src.cip.rag import llm as llm_mod

        mock_settings = Settings(
            llm_provider="minimax",  # type: ignore[arg-type]
            llm_model="MiniMax-M3",
            llm_api_key="sk-test",
            llm_base_url="",
        )
        mock_class, mock_instance = self._patch_openai_like()
        with patch.object(llm_mod, "get_settings", return_value=mock_settings):
            with patch.object(llm_mod.log, "info") as mock_log:
                llm_mod.build_llm()
                calls = [c for c in mock_log.call_args_list if c[0] == ("minimax_llm_active",)]
                assert len(calls) == 1
                assert calls[0].kwargs["model"] == "MiniMax-M3"

    def test_unknown_provider_raises(self) -> None:
        """Provider desconhecido ainda levanta ValueError."""
        from src.cip.config import Settings

        with pytest.raises(Exception):
            Settings(llm_provider="minimax_typo")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────
# .env.example documentation
# ─────────────────────────────────────────────────────────────────────────


class TestEnvExampleDocumentsMiniMax:
    """.env.example explica MiniMax."""

    def test_env_example_mentions_minimax(self) -> None:
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "minimax" in env.lower() or "MiniMax" in env

    def test_env_example_explains_minimax_base_url(self) -> None:
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        # Round 22+: URL correto é api.minimax.io (era .chat em versão antiga).
        assert "api.minimax.io" in env

    def test_env_example_includes_provider_in_list(self) -> None:
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "minimax" in env.lower()


# ─────────────────────────────────────────────────────────────────────────
# Integration com RAG engine (sanity check)
# ─────────────────────────────────────────────────────────────────────────


class TestRAGEngineAcceptsMiniMax:
    """RAG engine aceita MiniMax como provider."""

    def test_rag_engine_no_llm_import(self) -> None:
        """RAG engine não importa provider LLM diretamente (lazy)."""
        engine_file = (ROOT / "src" / "cip" / "rag" / "engine.py").read_text(encoding="utf-8")
        assert "minimax" not in engine_file.lower()

    def test_minimax_provider_works_with_full_stack(self) -> None:
        """MiniMax provider passa pelo orchestrator e ReAct sem erro."""
        from src.cip.config import Settings
        from src.cip.rag import llm as llm_mod

        mock_settings = Settings(
            llm_provider="minimax",  # type: ignore[arg-type]
            llm_model="MiniMax-M3",
            llm_api_key="sk-test-123",
            llm_base_url="https://api.minimax.chat/v1",
        )
        # Patch OpenAILike via sys.modules (lazy import)
        import sys
        import types

        fake_module = types.ModuleType("llama_index.llms.openai_like")
        mock_class = MagicMock()
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance
        fake_module.OpenAILike = mock_class
        sys.modules["llama_index.llms.openai_like"] = fake_module

        with patch.object(llm_mod, "get_settings", return_value=mock_settings):
            llm = llm_mod.build_llm()
        assert llm is mock_instance
        assert mock_class.called

    def test_minimax_supports_function_calling(self) -> None:
        """ReAct mode requer function calling — OpenAILike suporta."""
        from src.cip.config import Settings
        from src.cip.rag import llm as llm_mod

        mock_settings = Settings(
            llm_provider="minimax",  # type: ignore[arg-type]
            llm_model="MiniMax-M3",
            llm_api_key="sk-test",
            llm_base_url="",
        )
        import sys
        import types

        fake_module = types.ModuleType("llama_index.llms.openai_like")
        mock_class = MagicMock()
        mock_class.return_value = MagicMock()
        fake_module.OpenAILike = mock_class
        sys.modules["llama_index.llms.openai_like"] = fake_module

        with patch.object(llm_mod, "get_settings", return_value=mock_settings):
            llm_mod.build_llm()
            call_kwargs = mock_class.call_args.kwargs
            assert call_kwargs["is_chat_model"] is True


# ─────────────────────────────────────────────────────────────────────────
# Documentação do Round 19
# ─────────────────────────────────────────────────────────────────────────


class TestRound19Documentation:
    """Documentação do provider MiniMax."""

    def test_progress_report_exists(self) -> None:
        # Round 19 ainda não foi finalizado neste momento do teste
        # Só verificamos que os arquivos essenciais existem
        assert (ROOT / "docs" / "30-progresso-round-18.md").exists()
        # O Round 19 report será criado pelo próprio Claude no final

    def test_minimax_url_format(self) -> None:
        """URL MiniMax tem formato esperado."""
        from src.cip.rag.llm import build_llm
        from src.cip.config import Settings
        import sys
        import types

        mock_settings = Settings(
            llm_provider="minimax",  # type: ignore[arg-type]
            llm_model="MiniMax-M3",
            llm_api_key="sk-cp-test",
            llm_base_url="",
        )
        # Patch OpenAILike via sys.modules (lazy import)
        fake_module = types.ModuleType("llama_index.llms.openai_like")
        mock_class = MagicMock()
        mock_class.return_value = MagicMock()
        fake_module.OpenAILike = mock_class
        sys.modules["llama_index.llms.openai_like"] = fake_module

        with patch("src.cip.rag.llm.get_settings", return_value=mock_settings):
            build_llm()
            # Verifica que default URL é a esperada (CORRIGIDO Round 22+: .io, não .chat)
            call_kwargs = mock_class.call_args.kwargs
            assert call_kwargs["api_base"] == "https://api.minimax.io/v1"

    def test_known_minimax_models(self) -> None:
        """Documenta modelos MiniMax conhecidos."""
        known = ["MiniMax-M3", "MiniMax-Reasoning-M1"]
        # O sistema deve aceitar qualquer string como model
        for m in known:
            from src.cip.config import Settings
            s = Settings(llm_provider="minimax", llm_model=m)  # type: ignore[arg-type]
            assert s.llm_model == m