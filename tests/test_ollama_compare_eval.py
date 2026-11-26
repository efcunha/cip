"""Eval hardening: an off-topic answer with a valid citation must not count as on-topic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.ollama_compare import is_on_topic, load_questions, model_summary

REPORTS = Path(__file__).resolve().parent.parent / "eval" / "reports"
OFF_TOPIC_IN10 = (
    "Começando em 30 de novembro de 2025, o Azure Kubernetes Service (AKS) não oferecerá mais "
    "suporte para o Azure Linux 2.0 [1]. As imagens de nó serão removidas e você não poderá "
    "dimensionar seus pools de nós [1]."
)
ON_TOPIC_IN10 = (
    "Um node pool é um grupo de nós com a mesma configuração. Há pools de sistema e pools "
    "de usuário (system e user pool) [1]."
)


def _must(qid: str) -> list[str]:
    return next(q["must_mention"] for q in load_questions() if q["id"] == qid)


def test_in10_off_topic_valid_answer_is_not_on_topic() -> None:
    rec = {"outcome": "valid", "answer": OFF_TOPIC_IN10}
    assert not is_on_topic(rec, _must("in-10"))


def test_in10_real_node_pool_answer_is_on_topic() -> None:
    rec = {"outcome": "valid", "answer": ON_TOPIC_IN10}
    assert is_on_topic(rec, _must("in-10"))


def test_declined_is_never_on_topic() -> None:
    assert not is_on_topic({"outcome": "declined", "answer": "NAO_ENCONTRADO"}, ["a"])


def test_question_ids_stable() -> None:
    ids = [q["id"] for q in load_questions() if q["group"] == "in_rag"]
    assert ids == [f"in-{n:02d}" for n in range(1, 17)]


@pytest.mark.parametrize("mode,expected_on_topic", [("on", 38 / 48), ("off", 31 / 48)])
def test_recount_from_stored_raw(mode: str, expected_on_topic: float) -> None:
    path = REPORTS / f"deepinfra-gemma3-query-translation-{mode}-raw.json"
    if not path.exists():
        pytest.skip("raw eval json not available")
    raw = json.loads(path.read_text(encoding="utf-8"))
    summary = model_summary(raw["models"]["google/gemma-3-27b-it"])
    assert summary["in_on_topic"] == pytest.approx(expected_on_topic, abs=0.001)


def test_in13_level_names_on_topic_and_vague_not() -> None:
    ok = "Cinco níveis: Strong, Bounded staleness, Session, Consistent prefix e Eventual [1]."
    assert is_on_topic({"outcome": "valid", "answer": ok}, _must("in-13"))
    vague = "Há níveis de consistência [1]."
    assert not is_on_topic({"outcome": "valid", "answer": vague}, _must("in-13"))


def test_in15_accepts_pdb_with_definition() -> None:
    ok = "Um PDB limita Pods inativos por interrupções voluntárias [1]."
    assert is_on_topic({"outcome": "valid", "answer": ok}, _must("in-15"))
    bare = "Um PDB é um recurso [1]."
    assert not is_on_topic({"outcome": "valid", "answer": bare}, _must("in-15"))


def test_post_ingest_recount() -> None:
    path = REPORTS / "deepinfra-gemma3-post-ingest-translation-on-raw.json"
    if not path.exists():
        pytest.skip("raw eval json not available")
    raw = json.loads(path.read_text(encoding="utf-8"))
    summary = model_summary(raw["models"]["google/gemma-3-27b-it"])
    assert summary["in_on_topic"] == pytest.approx(46 / 48, abs=0.001)
