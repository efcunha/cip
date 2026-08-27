"""Configuração central via variáveis de ambiente (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CloudName = Literal["aws", "gcp", "azure", "multi", "architecture", "case-studies"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    cip_env: str = "dev"
    cip_readonly: bool = Field(default=True, description="Trava global: bloqueia ações mutantes.")
    log_level: str = "INFO"

    # Banco
    database_url: str = "postgresql://cip:cip@localhost:5432/cip"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "cip"
    db_user: str = "cip"
    db_password: str = "cip"

    # LLM
    llm_provider: Literal["bedrock", "openai", "local", "stub", "minimax", "deepseek"] = "bedrock"
    llm_model: str = "anthropic.claude-sonnet-4-5-20250929-v1:0"
    # Contexto depende do provider. Bedrock Sonnet 4.5 = 200k. MiniMax M3 = 1M (verified).
    llm_context_size: int = 200_000
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2048          # teto de saída (default do SDK é 512 = trunca)
    llm_timeout_s: float = 60.0         # timeout da chamada ao provedor
    llm_max_retries: int = 2            # baixo: evita retry storm sob carga
    # OpenAI-compatible providers (openai, local, minimax, deepseek) — credenciais + base URL.
    # Para MiniMax M3 o DSH canônico é MINIMAX_API_KEY — também aceito.
    llm_api_key: str = ""               # override de LLM_API_KEY
    # Alias explícito para MINIMAX_API_KEY (variavel canonica do DSH). Round 22+.
    minimax_api_key: str = Field(default="", validation_alias="MINIMAX_API_KEY")
    # Alias explícito para DEEPSEEK_API_KEY (fallback DeepSeek-V4-Flash). Round 22+.
    deepseek_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")
    # Base URL próprio do DeepSeek (isolado do LLM_BASE_URL global, que no .env
    # pode estar apontando para o MiniMax). Round 22+.
    deepseek_base_url: str = Field(default="", validation_alias="DEEPSEEK_BASE_URL")
    llm_base_url: str = ""              # override de LLM_BASE_URL
                                         #   MiniMax: https://api.minimax.io/v1 (padrão)
                                         #   DeepSeek: https://api.deepseek.com/v1 (padrão)

    # Concorrência / robustez (backpressure em vez de derreter sob carga)
    max_concurrent_requests: int = 200  # acima disso -> HTTP 429
    request_timeout_s: float = 90.0     # timeout total por request -> HTTP 504
    # Pool de conexões do banco (pgvector). Dimensione ~ concorrência por worker.
    db_pool_size: int = 20
    db_max_overflow: int = 20
    db_pool_timeout_s: float = 30.0
    db_pool_recycle_s: int = 1800

    # Embeddings (perfil minimalista por padrão: modelo pequeno + multilíngue,
    # roda em CPU/servidor barato com ~0.5GB RAM).
    #   provider local   -> HuggingFace local (custo zero, sem dependência externa)
    #   provider bedrock -> Amazon Titan Embeddings (sem ML local; embed_dim=1024)
    #   provider openai  -> text-embedding-3-small (sem ML local; embed_dim=1536)
    # ATENÇÃO: embed_dim deve casar com o modelo escolhido; trocar exige re-ingestão.
    embed_provider: Literal["local", "bedrock", "openai"] = "local"
    embed_model: str = "intfloat/multilingual-e5-small"
    embed_dim: int = 384
    embed_device: str = "cpu"
    # Prefixos de instrução (E5/BGE recomendam). Vazio = sem prefixo.
    embed_query_instruction: str = "query: "
    embed_text_instruction: str = "passage: "

    @model_validator(mode="after")
    def _validate_embed_dim_matches_provider(self) -> Settings:
        # Whitelist explícita por provider. Trocar o modelo exige re-ingestão
        # completa; bloquear mismatch na boot evita servir dados inconsistentes.
        expected_dims: dict[str, set[int]] = {
            "local": {384, 768, 1024},
            "bedrock": {1024, 1536},
            "openai": {1536, 3072},
        }
        allowed = expected_dims.get(self.embed_provider, set())
        if self.embed_dim not in allowed:
            raise ValueError(
                f"embed_dim={self.embed_dim} inconsistente com embed_provider="
                f"{self.embed_provider!r}. Dimensões aceitas: {sorted(allowed) or 'nenhuma'}. "
                f"Trocar a dimensão exige re-ingestão completa da base."
            )
        return self

    # Retrieval
    # ATENÇÃO: min_score depende do MODELO de embeddings. Para o e5-small (padrão)
    # os scores ficam altos/comprimidos (~0.75-0.85); use ~0.80. Para bge-large
    # era ~0.35. Revalide com eval/run_eval.py ao trocar o modelo.
    retrieval_top_k: int = 8
    retrieval_min_score: float = 0.80

    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None

    # Azure
    azure_subscription_id: str | None = None
    azure_tenant_id: str | None = None
    azure_client_id: str | None = None
    azure_client_secret: str | None = None

    # GCP
    gcp_project_id: str | None = None
    google_application_credentials: str | None = None

    # Observabilidade
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None

    # ─── JWT (Round 22+ Phase 2) ─────────────────────────────────
    # Dev: HS256 com secret compartilhado. Prod: RS256 com JWKS endpoint.
    jwt_secret: str = ""                          # default dev: vazio = usa "dev-secret"
    jwt_algorithm: str = "HS256"                   # HS256 | RS256
    jwt_issuer: str | None = None                  # validar `iss` em prod
    jwt_audience: str | None = None                # validar `aud` em prod


@lru_cache
def get_settings() -> Settings:
    return Settings()
