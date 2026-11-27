"""Testes do prompt (siglas/banners) e da remoção de banners na ingestão."""
from __future__ import annotations

import pytest

from cip.ingestion.webtext import (
    clean_html,
    find_notice_banners,
    is_notice_banner_line,
    strip_notice_banners,
)
from cip.prompts.system import SENIOR_ENGINEER_SYSTEM_PROMPT
from cip.rag.grounded import DECLINE_SENTINEL, GROUNDED_SYSTEM_PROMPT


@pytest.mark.parametrize("prompt", [SENIOR_ENGINEER_SYSTEM_PROMPT, GROUNDED_SYSTEM_PROMPT])
def test_prompts_have_acronym_and_banner_rules(prompt: str) -> None:
    low = prompt.lower()
    assert "sigla" in low and "pdb" in low
    assert "nunca invente" in low
    assert "banners" in low and "aposentadoria" in low


def test_grounding_rules_intact() -> None:
    assert "SOMENTE" in GROUNDED_SYSTEM_PROMPT
    assert f"exatamente: {DECLINE_SENTINEL}" in GROUNDED_SYSTEM_PROMPT
    assert "NUNCA invente" in SENIOR_ENGINEER_SYSTEM_PROMPT
    assert "não encontrei referência confiável" in SENIOR_ENGINEER_SYSTEM_PROMPT


AKS_BANNER = "Azure Linux with OS Guard retirement"
DATED = "Starting on 30 November 2025, AKS will no longer support Azure Linux 2.0."


def test_aks_banner_detected() -> None:
    assert is_notice_banner_line(AKS_BANNER)
    assert is_notice_banner_line(DATED)


@pytest.mark.parametrize(
    "line",
    [
        "Note: run az aks nodepool add before scaling the pool.",
        "Warning: deleting a node pool removes all its nodes.",
        "Note: the --foo flag is deprecated since 2023. Use --bar instead.",
        "Warning: kubenet will be retired on 31 March 2028. Migrate to Azure CNI Overlay.",
        "API deprecation",
        "Deprecation",
        "System node pools serve the primary purpose of hosting critical system pods.",
        "",
    ],
)
def test_procedural_content_kept(line: str) -> None:
    assert not is_notice_banner_line(line)


def test_strip_removes_label_and_banner() -> None:
    out = strip_notice_banners(["Intro", "Important", AKS_BANNER, "Create a node pool."])
    assert out == ["Intro", "Create a node pool."]


def test_find_is_read_only() -> None:
    text = f"a\n{AKS_BANNER}\nb"
    assert find_notice_banners(text) == [AKS_BANNER]
    assert AKS_BANNER in text


def test_clean_html_drops_banner_keeps_content() -> None:
    body = "conteudo real do pilar " * 40
    html = (
        "<html><body><main>"
        f"<div><p>Important</p><p>{AKS_BANNER}</p></div>"
        "<p>Note: run this first.</p>"
        f"<p>{body}</p></main></body></html>"
    )
    text = clean_html(html)
    assert "OS Guard" not in text
    assert "Important" not in text
    assert "Note: run this first." in text
    assert "conteudo real" in text
