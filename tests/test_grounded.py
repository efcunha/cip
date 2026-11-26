from __future__ import annotations

from types import SimpleNamespace

from cip.rag.grounded import (
    DECLINE_SENTINEL,
    append_sources_footer,
    build_grounded_messages,
    is_decline,
    validate_answer,
)


def _n(i: int, text: str = "texto") -> SimpleNamespace:
    return SimpleNamespace(
        text=text, score=0.9, metadata={"title": f"Doc {i}", "url": f"https://x.test/{i}"}
    )


NODES = [_n(1), _n(2), _n(3)]


def test_valid_cite() -> None:
    r = validate_answer("S3 faz isso [1] e aquilo [3].", NODES)
    assert r.ok and r.cited_indices == [1, 3]


def test_no_cite() -> None:
    assert validate_answer("sem citação", NODES).reason == "no_citation"


def test_empty() -> None:
    assert validate_answer("  ", NODES).reason == "empty_answer"


def test_out_of_range() -> None:
    assert validate_answer("x [9]", NODES).reason == "citation_out_of_range"
    assert validate_answer("x [0]", NODES).reason == "citation_out_of_range"


def test_foreign_url() -> None:
    r = validate_answer("x [1] veja https://evil.test/a", NODES)
    assert not r.ok and r.reason == "foreign_url"


def test_retrieved_url_passes() -> None:
    assert validate_answer("x [1] veja https://x.test/2.", NODES).ok


def test_decline_sentinel() -> None:
    assert is_decline(f"  {DECLINE_SENTINEL}\n")
    assert is_decline("nao_encontrado.")
    assert not is_decline("achei NAO_ENCONTRADO aqui")


def test_footer_only_cited() -> None:
    out = append_sources_footer("resp [2]", NODES, [2])
    assert "https://x.test/2" in out
    assert "https://x.test/1" not in out and "https://x.test/3" not in out


def test_prompt_numbers_and_trims() -> None:
    nodes = [_n(i, "a" * 500) for i in range(1, 4)]
    system, user = build_grounded_messages("pergunta?", nodes, 100)
    for i in (1, 2, 3):
        assert f"[{i}] Doc {i}" in user
    assert "a" * 101 not in user
    assert "PERGUNTA: pergunta?" in user
    assert DECLINE_SENTINEL in system
