"""Factory de LLM e embeddings, abstraindo o provider (bedrock | openai | local).

O objetivo é permitir trocar o modelo base sem reescrever o resto do sistema.
Os imports pesados são feitos lazily para não obrigar instalar todos os providers.
"""

from __future__ import annotations

import os
from typing import Any

from cip.config import get_settings
from cip.logging import get_logger

from llama_index.core.llms import CompletionResponse, CustomLLM, LLMMetadata
log = get_logger(__name__)


def build_embed_model() -> Any:
    """Constrói o modelo de embeddings conforme EMBED_PROVIDER.

    - local   (padrão): modelo HuggingFace pequeno rodando em CPU. Custo zero,
      sem dependência externa; ideal para servidor barato. Padrão é o
      `multilingual-e5-small` (384d), que lida com perguntas em PT sobre docs EN.
    - bedrock: Amazon Titan Embeddings — nenhum modelo roda localmente (só chamada
      de API). Bom quando não se quer ML no servidor. `embed_dim=1024`.
    - openai:  text-embedding-3-small — idem, via API. `embed_dim=1536`.

    The local default is `intfloat/multilingual-e5-small` with 384 dimensions;
    provider-specific dimensions must match the configured vector store.
    """
    settings = get_settings()
    provider = settings.embed_provider
    log.info("loading_embeddings", provider=provider, model=settings.embed_model)

    if provider == "local":
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        return HuggingFaceEmbedding(
            model_name=settings.embed_model,
            device=settings.embed_device,
            embed_batch_size=32,
            query_instruction=settings.embed_query_instruction or None,
            text_instruction=settings.embed_text_instruction or None,
        )

    if provider == "bedrock":
        from llama_index.embeddings.bedrock import BedrockEmbedding

        return BedrockEmbedding(
            model_name=settings.embed_model,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            aws_session_token=settings.aws_session_token,
            region_name=settings.aws_region,
        )

    if provider == "openai":
        from llama_index.embeddings.openai import OpenAIEmbedding

        return OpenAIEmbedding(model=settings.embed_model)

    raise ValueError(f"EMBED_PROVIDER desconhecido: {provider}")



class _StubLLM(CustomLLM):
    """LLM determinístico para Fase 1A sem credenciais.

    Recebe o prompt montado pelo engine (que inclui o contexto recuperado)
    e devolve um resumo fixo citando as fontes detectadas. Útil para validar
    ingestão + retrieval + formato de resposta sem chamar Bedrock/OpenAI.
    """

    @property
    def metadata(self) -> "LLMMetadata":
        return LLMMetadata(
            model_name="stub",
            is_chat_model=False,
            num_output=512,
        )

    def complete(self, prompt: str, **kwargs: Any) -> "CompletionResponse":
        return CompletionResponse(text=_stub_response(prompt))

    async def acomplete(self, prompt: str, **kwargs: Any) -> "CompletionResponse":
        return CompletionResponse(text=_stub_response(prompt))

    def stream_complete(self, prompt: str, **kwargs: Any):
        text = _stub_response(prompt)
        yield CompletionResponse(text=text, delta=text)


def _stub_response(prompt: str) -> str:
    """Extrai chunks do prompt (formato LlamaIndex) e devolve resposta baseada no conteúdo."""
    import re

    # LlamaIndex coloca chunks no prompt como "Text: ...\nMetadata: ..."
    chunks = re.findall(r"Text: (.*?)(?:\nMetadata:|\n\n|$)", prompt, re.DOTALL)
    sources = re.findall(r"https?://[^\s\)\]\"'>]+", prompt)
    unique_sources = list(dict.fromkeys(sources))[:5]

    if chunks:
        # Resumir: primeiras 200 chars de cada chunk
        summaries = []
        for i, chunk in enumerate(chunks[:3]):
            clean = chunk.strip()[:200].replace('\n', ' ')
            summaries.append(f"Chunk {i+1}: {clean}...")

        cites = "\n".join(f"- {u}" for u in unique_sources)
        return (
            "[stub LLM — provider stub ativo na Fase 1A]\n\n"
            "Resposta baseada no contexto recuperado:\n\n"
            + "\n\n".join(summaries) +
            f"\n\nFontes consultadas:\n{cites}\n\n"
            "Para respostas geradas por LLM real, configure LLM_PROVIDER=bedrock ou openai "
            "com credenciais válidas."
        )

    if unique_sources:
        cites = "\n".join(f"- {u}" for u in unique_sources)
        return (
            "[stub LLM — provider stub ativo na Fase 1A]\n\n"
            "Resposta baseada exclusivamente no contexto recuperado da base oficial. "
            "Fontes consultadas:\n"
            f"{cites}\n\n"
            "Para respostas geradas por LLM real, configure LLM_PROVIDER=bedrock ou openai "
            "com credenciais válidas."
        )

    return (
        "[stub LLM] Nenhuma fonte recuperada acima do score mínimo "
        "(RETRIEVAL_MIN_SCORE). Nada a responder sem grounding."
    )


class _ExtractiveLLM(CustomLLM):
    """LLM-guard para o modo extrativo (``LLM_PROVIDER=extractive``).

    Não gera texto: existe apenas para que ``configure_llama_settings`` tenha um
    ``LlamaSettings.llm`` válido sem configurar nenhum cliente de geração.
    Qualquer chamada de geração levanta erro — garantindo ZERO chamada externa
    de LLM mesmo se algum caminho tentar usar o query_engine de síntese.
    """

    @property
    def metadata(self) -> "LLMMetadata":
        return LLMMetadata(model_name="extractive", is_chat_model=False, num_output=0)

    def complete(self, prompt: str, **kwargs: Any) -> "CompletionResponse":
        raise RuntimeError("extractive mode: LLM generation disabled (no external model).")

    async def acomplete(self, prompt: str, **kwargs: Any) -> "CompletionResponse":
        raise RuntimeError("extractive mode: LLM generation disabled (no external model).")

    def stream_complete(self, prompt: str, **kwargs: Any):
        raise RuntimeError("extractive mode: LLM generation disabled (no external model).")
        yield  # pragma: no cover


def _is_testing() -> bool:
    """True quando ``IS_TESTING`` está setado (truthy).

    Round 22.5 (hardening): flag de ambiente explícita do pytest (``IS_TESTING=1``)
    para trocar o LLM por ``_StubLLM`` determinístico. Nunca é ativada pelo
    ``LLM_PROVIDER`` do ``.env``, então não afeta produção.
    """
    return os.environ.get("IS_TESTING", "").strip().lower() in ("1", "true", "yes", "on")


def build_llm() -> Any:
    """Constrói o LLM conforme LLM_PROVIDER.

    Round 22.5: quando ``IS_TESTING`` está setado, retorna ``_StubLLM`` (ver
    ``configure_llama_settings``). O gate vive NO PONTO DE CONFIGURAÇÃO do
    LlamaIndex (``configure_llama_settings``), preservando ``build_llm`` como
    factory pura — os unit tests de provider (test_minimax_provider.py) mockam
    ``get_settings`` e chamam ``build_llm`` diretamente, então devem ver o caminho
    real do provider, não o stub.
    """
    settings = get_settings()
    provider = settings.llm_provider

    if provider == "bedrock":
        from llama_index.llms.bedrock import Bedrock

        return Bedrock(
            model=settings.llm_model,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            aws_session_token=settings.aws_session_token,
            region_name=settings.aws_region,
            context_size=settings.llm_context_size,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )

    if provider == "openai":
        from llama_index.llms.openai import OpenAI

        return OpenAI(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )

    if provider == "local":
        # Ex.: servidor OpenAI-compatible (vLLM/Ollama) hospedando Llama 3.3 70B.
        from llama_index.llms.openai_like import OpenAILike

        return OpenAILike(
            model=settings.llm_model,
            api_base="http://localhost:8001/v1",
            api_key="not-needed",
            context_window=settings.llm_context_size,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
            is_chat_model=True,
        )
    if provider == "stub":
        log.warning("stub_llm_active", reason="sem credenciais Bedrock/OpenAI na Fase 1A")
        return _StubLLM()

    if provider == "extractive":
        # Modo local determinístico: nenhum cliente de geração é configurado.
        # O RagEngine sintetiza por extração (rag/extractive.py) sem LLM.
        log.info("extractive_llm_guard_active", note="síntese extrativa local, sem LLM externo")
        return _ExtractiveLLM()

    if provider == "minimax":
        # MiniMax M3 (MiniMax) — API OpenAI-compatible.
        # Endpoint default: https://api.minimax.io/v1 (CORRETO — era .chat em versão antiga).
        # Override via env var LLM_BASE_URL se necessário.
        #
        # Tenta usar llama_index.llms.openai_like (wrapper canônico).
        # Fallback: usa openai.OpenAI diretamente via um shim CustomLLM se o pacote
        # não estiver instalado (cenário comum em sandboxes onde pip install falha).
        # Ordem de precedência da API key:
        #   1) LLM_API_KEY (campo llm_api_key)
        #   2) MINIMAX_API_KEY (campo minimax_api_key, variavel canonica do DSH)
        #   3) env var MINIMAX_API_KEY (caso o .env não seja carregado por pydantic)
        api_key = (
            settings.llm_api_key
            or settings.minimax_api_key
            or os.environ.get("MINIMAX_API_KEY", "")
            or "not-set"
        )
        base_url = settings.llm_base_url or "https://api.minimax.io/v1"
        log.info(
            "minimax_llm_active",
            model=settings.llm_model,
            api_base=base_url,
            api_key_prefix=api_key[:10] + "..." if api_key != "not-set" else "NOT-SET",
        )

        try:
            from llama_index.llms.openai_like import OpenAILike

            return OpenAILike(
                model=settings.llm_model,
                api_base=base_url,
                api_key=api_key,
                context_window=settings.llm_context_size,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
                timeout=settings.llm_timeout_s,
                max_retries=settings.llm_max_retries,
                is_chat_model=True,
            )
        except ImportError:
            # Fallback: shim minimalista sobre openai.OpenAI.
            # Reproduz a interface mínima que o RagEngine usa (.complete/.acomplete).
            log.warning(
                "minimax_openai_like_missing",
                note="usando shim via openai.OpenAI direto (pacote llama-index-llms-openai-like indisponivel)",
            )

            from openai import OpenAI

            class _MinimaxShimLLM(CustomLLM):
                """Shim OpenAI-compat para MiniMax M3 — sem dependencia de llama-index-llms-openai-like.

                Round 22+ fix: o client OpenAI é criado LAZILY em cada chamada (em
                vez de uma vez em __init__). Sem isso, aparece o erro intermitente
                'NoneType' object has no attribute 'send' quando o client é
                compartilhado entre múltiplas chamadas async (transport httpx
                fica em estado inválido após o loop asyncio fechar).
                """

                def __init__(self) -> None:
                    super().__init__()
                    # Sem cache de client — ver _call_chat
                    self._client_lock = __import__("threading").Lock()

                def _get_client(self) -> Any:
                    """Cria um novo client a cada chamada (race-free via lock)."""
                    return OpenAI(
                        api_key=api_key,
                        base_url=base_url,
                        timeout=settings.llm_timeout_s,
                        max_retries=settings.llm_max_retries,
                    )

                @property
                def metadata(self) -> "LLMMetadata":
                    return LLMMetadata(
                        model_name=settings.llm_model,
                        is_chat_model=True,
                        # Round 22+: reportar context_window explicitamente.
                        # Sem isso, llama-index usa 16384 (default interno) e o
                        # prompt_helper falha com "available context size < 0".
                        context_window=settings.llm_context_size,
                        num_output=settings.llm_max_tokens,
                    )

                def _call_chat(self, prompt: str) -> str:
                    # Client fresco a cada chamada (evita 'NoneType.send' intermitente
                    # vindo de httpx transport compartilhado entre event loops).
                    client = self._get_client()
                    try:
                        resp = client.chat.completions.create(
                            model=settings.llm_model,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=settings.llm_temperature,
                            max_tokens=settings.llm_max_tokens,
                        )
                        return resp.choices[0].message.content or ""
                    finally:
                        try:
                            client.close()
                        except Exception:  # noqa: BLE001
                            pass

                def complete(self, prompt: str, **kwargs: Any) -> "CompletionResponse":
                    return CompletionResponse(text=self._call_chat(prompt))

                async def acomplete(self, prompt: str, **kwargs: Any) -> "CompletionResponse":
                    return CompletionResponse(text=self._call_chat(prompt))

                def stream_complete(self, prompt: str, **kwargs: Any):
                    # Sem streaming nativo — devolve tudo de uma vez como delta.
                    text = self._call_chat(prompt)
                    yield CompletionResponse(text=text, delta=text)

            return _MinimaxShimLLM()

    if provider == "deepseek":
        # DeepSeek (DeepSeek-V4-Flash) — API OpenAI-compatible.
        # Endpoint default: https://api.deepseek.com/v1.
        # Override via env var LLM_BASE_URL se necessário.
        #
        # Mesmo padrão do MiniMax: tenta llama_index.llms.openai_like; se não
        # estiver instalado, cai num shim via openai.OpenAI direto.
        # Ordem de precedência da API key:
        #   1) LLM_API_KEY (campo llm_api_key)
        #   2) DEEPSEEK_API_KEY (campo deepseek_api_key)
        #   3) env var DEEPSEEK_API_KEY (caso o .env não seja carregado pelo pydantic)
        api_key = (
            settings.llm_api_key
            or settings.deepseek_api_key
            or os.environ.get("DEEPSEEK_API_KEY", "")
            or "not-set"
        )
        # Base URL isolado por provider (DEEPSEEK_BASE_URL) — NÃO herda o
        # LLM_BASE_URL global, que no .env local pode apontar para o MiniMax
        # (causava 401 "login fail" ao mandar a chave DeepSeek para minimax.io).
        base_url = settings.deepseek_base_url or "https://api.deepseek.com/v1"
        log.info(
            "deepseek_llm_active",
            model=settings.llm_model,
            api_base=base_url,
            api_key_prefix=api_key[:10] + "..." if api_key != "not-set" else "NOT-SET",
        )

        try:
            from llama_index.llms.openai_like import OpenAILike

            return OpenAILike(
                model=settings.llm_model,
                api_base=base_url,
                api_key=api_key,
                context_window=settings.llm_context_size,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
                timeout=settings.llm_timeout_s,
                max_retries=settings.llm_max_retries,
                is_chat_model=True,
            )
        except ImportError:
            log.warning(
                "deepseek_openai_like_missing",
                note="usando shim via openai.OpenAI direto (pacote llama-index-llms-openai-like indisponivel)",
            )

            from openai import OpenAI

            class _DeepSeekShimLLM(CustomLLM):
                """Shim OpenAI-compat para DeepSeek — sem dependencia de llama-index.

                Client criado LAZILY a cada chamada (mesmo motivo do MiniMax):
                evita 'NoneType' object has no attribute 'send' vindo de httpx
                transport compartilhado entre event loops.
                """

                def __init__(self) -> None:
                    super().__init__()
                    self._client_lock = __import__("threading").Lock()

                def _get_client(self) -> Any:
                    return OpenAI(
                        api_key=api_key,
                        base_url=base_url,
                        timeout=settings.llm_timeout_s,
                        max_retries=settings.llm_max_retries,
                    )

                @property
                def metadata(self) -> "LLMMetadata":
                    return LLMMetadata(
                        model_name=settings.llm_model,
                        is_chat_model=True,
                        context_window=settings.llm_context_size,
                        num_output=settings.llm_max_tokens,
                    )

                def _call_chat(self, prompt: str) -> str:
                    client = self._get_client()
                    try:
                        resp = client.chat.completions.create(
                            model=settings.llm_model,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=settings.llm_temperature,
                            max_tokens=settings.llm_max_tokens,
                        )
                        return resp.choices[0].message.content or ""
                    finally:
                        try:
                            client.close()
                        except Exception:  # noqa: BLE001
                            pass

                def complete(self, prompt: str, **kwargs: Any) -> "CompletionResponse":
                    return CompletionResponse(text=self._call_chat(prompt))

                async def acomplete(self, prompt: str, **kwargs: Any) -> "CompletionResponse":
                    return CompletionResponse(text=self._call_chat(prompt))

                def stream_complete(self, prompt: str, **kwargs: Any):
                    text = self._call_chat(prompt)
                    yield CompletionResponse(text=text, delta=text)

            return _DeepSeekShimLLM()

    raise ValueError(f"LLM_PROVIDER desconhecido: {provider}")


def configure_llama_settings() -> None:
    """Aplica LLM + embeddings nas Settings globais do LlamaIndex.

    Round 22.5: quando ``IS_TESTING`` está setado, o LLM global vira ``_StubLLM``
    determinístico (sem credential/wire handshake) para destravar os testes
    LLM-key-dependent (test_specialists.py, test_tools_mock_integration.py) em CI
    sem MINIMAX/DEEPSEEK_API_KEY. O ``build_llm`` (factory) continua intacto para
    os unit tests de provider. Produção nunca seta ``IS_TESTING``, então não muda.
    """
    from llama_index.core import Settings as LlamaSettings

    LlamaSettings.embed_model = build_embed_model()
    if _is_testing():
        log.info("stub_llm_active", reason="IS_TESTING=1 (ambiente de teste determinístico)")
        LlamaSettings.llm = _StubLLM()
    else:
        LlamaSettings.llm = build_llm()
