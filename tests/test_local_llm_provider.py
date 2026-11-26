"""Provider ``local`` (Ollama/vLLM): URL e chave vêm das settings, não hardcoded."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import cip.rag.llm as llm_mod


def _settings(**over: Any) -> SimpleNamespace:
    base = dict(
        llm_provider="local",
        llm_model="cip-llm",
        llm_base_url="",
        llm_api_key="",
        llm_context_size=4096,
        llm_temperature=0.1,
        llm_max_tokens=512,
        llm_timeout_s=90.0,
        llm_max_retries=0,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _build(monkeypatch, **over: Any) -> Any:
    monkeypatch.setattr(llm_mod, "get_settings", lambda: _settings(**over))
    return llm_mod.build_llm()


def test_local_uses_base_url_from_settings(monkeypatch) -> None:
    llm = _build(monkeypatch, llm_base_url="http://ollama:11434/v1")
    assert llm.api_base == "http://ollama:11434/v1"


def test_local_default_url_when_empty(monkeypatch) -> None:
    llm = _build(monkeypatch)
    assert llm.api_base == "http://localhost:8001/v1"


def test_local_api_key_from_settings(monkeypatch) -> None:
    assert _build(monkeypatch, llm_api_key="abc").api_key == "abc"


def test_local_default_api_key(monkeypatch) -> None:
    assert _build(monkeypatch).api_key == "not-needed"


def test_local_passes_model_params(monkeypatch) -> None:
    llm = _build(monkeypatch)
    assert llm.model == "cip-llm"
    assert llm.temperature == 0.1
    assert llm.max_tokens == 512
    assert llm.timeout == 90.0
    assert llm.max_retries == 0
    assert llm.is_chat_model is True


def test_new_settings_defaults() -> None:
    from cip.config import Settings

    s = Settings(_env_file=None)
    assert s.llm_first_token_timeout_s == 30.0
    assert s.llm_context_top_k == 4
    assert s.llm_context_chunk_chars == 1200
