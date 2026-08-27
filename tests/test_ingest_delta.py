"""Testes da lógica de ingestão incremental (delta) e do batching."""

from __future__ import annotations

from types import SimpleNamespace

from cip.ingestion.ingest import _partition_delta, _batch_entries


def _doc(url: str, doc_hash: str):
    return SimpleNamespace(metadata={"url": url, "doc_hash": doc_hash})


def test_partition_delta_classifica_novo_alterado_inalterado():
    docs = [
        _doc("https://x/a", "h_a"),   # inalterado
        _doc("https://x/b", "h_b2"),  # alterado (banco tem h_b1)
        _doc("https://x/c", "h_c"),   # novo
    ]
    existing = {
        "https://x/a": {"h_a"},
        "https://x/b": {"h_b1"},
    }
    to_process, changed_urls, n_unchanged = _partition_delta(docs, existing)

    assert n_unchanged == 1
    assert changed_urls == ["https://x/b"]
    urls = sorted(d.metadata["url"] for d in to_process)
    assert urls == ["https://x/b", "https://x/c"]  # alterado + novo


def test_partition_delta_tudo_inalterado():
    docs = [_doc("https://x/a", "h"), _doc("https://x/b", "h")]
    existing = {"https://x/a": {"h"}, "https://x/b": {"h"}}
    to_process, changed_urls, n_unchanged = _partition_delta(docs, existing)
    assert to_process == []
    assert changed_urls == []
    assert n_unchanged == 2


def test_partition_delta_banco_vazio_tudo_novo():
    docs = [_doc("https://x/a", "h1"), _doc("https://x/b", "h2")]
    to_process, changed_urls, n_unchanged = _partition_delta(docs, {})
    assert len(to_process) == 2
    assert changed_urls == []
    assert n_unchanged == 0


def test_batch_entries_divide_e_gera_chaves_unicas():
    entry = {"service": "ec2", "source": "aws-docs", "category": "compute",
             "urls": [f"https://x/{i}.md" for i in range(95)]}
    batches = _batch_entries([entry], size=40)
    assert len(batches) == 3
    assert [len(b["urls"]) for b in batches] == [40, 40, 15]
    keys = [f"aws:{b['service']}:{b['batch_id']}" for b in batches]
    assert len(keys) == len(set(keys))          # chaves de progresso únicas
    assert all(b["source"] == "aws-docs" for b in batches)  # source preservado


def test_batch_entries_nao_divide_quando_cabe():
    entry = {"service": "sns", "source": "aws-docs", "urls": ["u1", "u2"]}
    batches = _batch_entries([entry], size=40)
    assert len(batches) == 1
    assert "batch_id" not in batches[0]  # entrada pequena permanece intacta
