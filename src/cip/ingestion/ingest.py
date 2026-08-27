"""Ingestor da base de conhecimento.

Uso:
    python -m cip.ingestion.ingest --scope mvp
    python -m cip.ingestion.ingest --scope full --cloud aws

Fluxo: carrega sources.yaml -> baixa páginas -> converte para markdown ->
chunking híbrido -> embeddings -> upsert no pgvector (dedupe por content_hash).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import yaml

from cip.logging import configure_logging, get_logger

log = get_logger(__name__)

SOURCES_FILE = Path(__file__).parent / "sources.yaml"
SOURCES_ADVANCED_FILE = Path(__file__).parent / "sources_advanced.yaml"
PROGRESS_FILE = Path(__file__).parent / "ingest_progress.json"

# Raiz do repositório (src/cip/ingestion/ -> subir 3 níveis).
ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Diretórios base para arquivos curados registrados como fonte local.
CURATED_DIR = ROOT / "db" / "curated"

# Conteúdo abaixo deste tamanho (em caracteres) é tratado como página vazia,
# casca de redirect ou erro "soft" e é descartado antes do chunking.
MIN_CONTENT_CHARS = 500


def _make_source_key(cloud: str, entry: dict[str, Any]) -> str:
    """Chave estável de progresso/resume para uma entrada.

    Round 22.5 (hardening): a chave antiga ``cloud:service:batch`` colidia nas
    knowledge areas adicionais (``case-studies``, ``architecture``), onde várias
    entradas compartilham o mesmo ``service`` (ex.: todo world-class engenharia
    de blog usa ``service: case-studies``). Como ``progress["completed"]`` só
    aceita uma chave, apenas UMA fonte era ingerida por execução e as demais
    eram puladas no resume.

    A chave agora inclui ``source`` (estável e único DENTRO de cada cloud/pseudo-
    cloud), antes de ``service``: ``cloud:source:service:batch``. Isso destrava
    múltiplas fontes case-studies (LinkedIn/Uber/GitLab/…), sem afetar o dedupe
    por ``content_hash`` (que continua sendo por chunk, independente da chave).
    """
    source = entry.get("source") or entry["service"]
    return f"{cloud}:{source}:{entry['service']}:{entry.get('batch_id', 0)}"


def save_progress(progress: dict[str, Any]) -> None:
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2), encoding="utf-8")


def load_progress() -> dict[str, Any]:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"completed": [], "failed": [], "total_chunks": 0}


def reset_progress() -> None:
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()


def load_sources(scope: str) -> dict[str, list[dict[str, Any]]]:
    """Carrega fontes (incluindo sources_advanced.yaml se existir).

    Estrutura retornada: dict[cloud, list[entry]], onde cloud pode ser
    ``aws``, ``gcp``, ``azure``, ``multi`` (cloud-agnostic), ``architecture``
    (software architecture patterns) e ``case-studies`` (postmortems / lessons
    learned de fóruns e blogs de engenharia).

    Round 18+: ``sources_advanced.yaml`` preenche gaps sob escopos ``mvp``/``full``.
    Round 22+: chaves top-level adicionais em ``sources_advanced.yaml`` (ex.:
    ``architecture``, ``case-studies``) viram pseudo-clouds disponíveis em
    AMBOS os escopos, sem duplicação. O parâmetro ``scope`` controla apenas as
    fontes curadas nos escopos tradicionais; knowledge areas adicionais
    (arquitetura, postmortems) sempre acompanham.
    """
    data = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8"))
    # Round 18: também carrega sources avançadas (preenche gaps)
    if SOURCES_ADVANCED_FILE.exists():
        adv_data = yaml.safe_load(SOURCES_ADVANCED_FILE.read_text(encoding="utf-8"))
        # Merge: mvp + advanced (advanced sobrescreve se mesmo source)
        for scope_name in ("mvp", "full"):
            if scope_name in adv_data:
                data.setdefault(scope_name, {})
                for cloud, entries in adv_data[scope_name].items():
                    data[scope_name].setdefault(cloud, [])
                    data[scope_name][cloud].extend(entries)

        # Round 22+: knowledge areas adicionais (architecture, case-studies, etc.)
        # ficam como pseudo-clouds top-level no advanced, sempre disponíveis.
        # Excluímos 'mvp'/'full' para não tratar como knowledge area.
        extra_areas = {
            k: v for k, v in adv_data.items() if k not in ("mvp", "full")
        }
        for scope_name in ("mvp", "full"):
            data.setdefault(scope_name, {})
            for area_name, entries in extra_areas.items():
                data[scope_name].setdefault(area_name, [])
                # Dedup por (source, urls) para não duplicar quando o caller
                # invoca load_sources() várias vezes no mesmo processo.
                existing_urls = {
                    url for e in data[scope_name][area_name] for url in e.get("urls", [])
                }
                for entry in entries:
                    new_urls = [u for u in entry.get("urls", []) if u not in existing_urls]
                    # Round 22.4: manter entrada mesmo sem URLs novas quando ela
                    # carrega fontes locais curadas (local_files). Sem isso, uma
                    # entrada com urls=[] (ex.: netflix-tech-blog, cujo Medium
                    # bloqueia o fetch) era descartada silenciosamente no merge.
                    has_local = bool(entry.get("local_files"))
                    if new_urls or has_local:
                        merged = dict(entry)
                        merged["urls"] = new_urls
                        data[scope_name][area_name].append(merged)
                        existing_urls.update(new_urls)

    if scope not in data:
        raise ValueError(f"Escopo '{scope}' não encontrado em sources.yaml")
    result = data[scope]
    # No escopo full, incluir também o mvp (frameworks são base de tudo).
    if scope == "full":
        for cloud, entries in data.get("mvp", {}).items():
            result.setdefault(cloud, [])
            result[cloud] = entries + result[cloud]
    return result


def _load_one_document(url: str) -> Any | None:
    """Baixa uma única página e anexa a URL de origem aos metadados.

    Carregar por-URL garante alinhamento url<->documento (essencial para o
    delta) e isola falhas: uma página que falha não derruba o lote inteiro.
    """
    from llama_index.readers.web import SimpleWebPageReader

    try:
        docs = SimpleWebPageReader(html_to_text=True).load_data([url])
    except Exception as exc:  # noqa: BLE001 - rede/parse podem falhar de várias formas
        log.warning("page_load_failed", url=url, error=str(exc))
        return None
    if not docs:
        return None
    doc = docs[0]
    doc.metadata["url"] = url
    return doc


def _resolve_local_path(raw: str | dict[str, Any]) -> tuple[Path, str] | None:
    """Resolve uma fonte local curada para (path, canonical_url).

    Aceita:
      - string: caminho relativo a ``ROOT`` (canonical_url = ``file://`` + path)
      - dict ``{"path": ..., "url": ...}``: caminho + URL canónica (preferido)

    Retorna ``None`` se o arquivo não existir (registra warning).
    """
    if isinstance(raw, dict):
        rel = raw.get("path", "")
        canonical = raw.get("url") or f"file://{rel}"
    else:
        rel = raw
        canonical = f"file://{rel}"
    if not rel:
        log.warning("local_file_missing_path", entry=raw)
        return None
    path = (ROOT / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
    if not path.exists():
        log.warning("local_file_not_found", path=str(path))
        return None
    return path, canonical


def _load_one_local_document(raw: str | dict[str, Any]) -> Any | None:
    """Carrega um arquivo markdown curado como ``Document``.

    Round 22.4: corrige case-studies cuja URL remota devolve boilerplate,
    404 ou página de bloqueio (AWS aws.amazon.com/message/*, medium.com).
    O conteúdo curado carrega a URL canónica (fonte pública verificável) nos
    metadados, preservando grounding e provenance sem invenção factual.
    """
    from llama_index.core import Document

    resolved = _resolve_local_path(raw)
    if resolved is None:
        return None
    path, canonical = resolved
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("local_file_read_failed", path=str(path), error=str(exc))
        return None
    if not text:
        log.warning("local_file_empty", path=str(path))
        return None
    return Document(text=text, metadata={"url": canonical, "source_file": str(path)})


def _load_local_documents(raw_entries: list[str | dict[str, Any]] | None) -> list[Any]:
    """Carrega todas as fontes locais de uma entrada, isolando falhas por arquivo."""
    if not raw_entries:
        return []
    return [d for e in raw_entries if (d := _load_one_local_document(e)) is not None]


async def _load_documents(urls: list[str]) -> list[Any]:
    import concurrent.futures as cf

    def load_all() -> list[Any]:
        results: list[Any] = []
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            for doc in ex.map(_load_one_document, urls):
                if doc is not None:
                    results.append(doc)
        return results

    return await asyncio.to_thread(load_all)


async def _query_existing_doc_hashes(engine: Any, urls: list[str]) -> dict[str, set[str]]:
    """Retorna {url: {doc_hash, ...}} para URLs já presentes no banco.

    Tolera a tabela ainda não existir (primeira ingestão) devolvendo vazio.
    """
    from sqlalchemy import text

    out: dict[str, set[str]] = {}
    try:
        async with engine.connect() as conn:
            stmt = text(
                "SELECT DISTINCT metadata_ ->> 'url' AS url, metadata_ ->> 'doc_hash' AS dh "
                "FROM data_cloud_docs WHERE metadata_ ->> 'url' = ANY(:urls)"
            )
            res = await conn.execute(stmt, {"urls": urls})
            for url, dh in res.all():
                if url:
                    out.setdefault(url, set()).add(dh)
    except Exception as exc:  # noqa: BLE001 - tabela pode não existir no 1º run
        log.info("doc_hash_lookup_skipped", reason=str(exc))
    return out


async def _delete_docs_by_url(engine: Any, urls: list[str]) -> int:
    """Remove todos os chunks das URLs informadas (para substituir docs alterados)."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        res = await conn.execute(
            text("DELETE FROM data_cloud_docs WHERE metadata_ ->> 'url' = ANY(:urls)"),
            {"urls": urls},
        )
        return res.rowcount or 0


async def _query_existing_chunk_hashes(engine: Any, hashes: list[str]) -> set[str]:
    from sqlalchemy import text

    if not hashes:
        return set()
    try:
        async with engine.connect() as conn:
            stmt = text(
                "SELECT metadata_ ->> 'content_hash' FROM data_cloud_docs "
                "WHERE metadata_ ->> 'content_hash' = ANY(:hashes)"
            )
            res = await conn.execute(stmt, {"hashes": hashes})
            return {row[0] for row in res.all()}
    except Exception as exc:  # noqa: BLE001
        log.info("chunk_hash_lookup_skipped", reason=str(exc))
        return set()


def _partition_delta(
    documents: list[Any], existing: dict[str, set[str]]
) -> tuple[list[Any], list[str], int]:
    """Classifica documentos contra o estado do banco.

    Requer ``doc.metadata['url']`` e ``doc.metadata['doc_hash']``.
    Retorna (to_process, changed_urls, n_unchanged):
      * inalterado: (url, doc_hash) já existe          -> pulado
      * alterado:   url existe mas com doc_hash diferente -> reprocessa + limpa
      * novo:       url ausente                          -> processa
    """
    to_process: list[Any] = []
    changed_urls: list[str] = []
    n_unchanged = 0
    for d in documents:
        url = d.metadata["url"]
        doc_hash = d.metadata["doc_hash"]
        if url in existing:
            if doc_hash in existing[url]:
                n_unchanged += 1
                continue
            changed_urls.append(url)
        to_process.append(d)
    return to_process, changed_urls, n_unchanged


async def ingest_entry(
    cloud: str,
    entry: dict[str, Any],
    embed_model: Any,
    vector_store: Any,
    dry_run: bool = False,
    progress: dict[str, Any] | None = None,
    db_engine: Any | None = None,
) -> tuple[int, int]:
    """Ingestão incremental de uma entrada (serviço/lote).

    Fluxo delta (evita re-embedar documentação inalterada):
      1. Baixa páginas e calcula ``doc_hash`` do conteúdo bruto de cada uma.
      2. Consulta o banco: páginas com mesmo (url, doc_hash) são PULADAS antes
         do embedding (a parte cara). Páginas alteradas têm seus chunks antigos
         removidos e são re-ingeridas. Páginas novas são ingeridas.
      3. Dedupe adicional por content_hash de chunk (pega chunks idênticos entre
         páginas diferentes).
    """
    from llama_index.core import StorageContext, VectorStoreIndex

    from cip.ingestion.chunking import build_nodes, content_hash

    urls = entry.get("urls") or []
    # Round 22.5: chave = cloud:source:service:batch (source é único dentro de cada
    # cloud/pseudo-cloud e destrava múltiplas fontes com o mesmo service — ex.:
    # todos os engineering blogs usam service=case-studies). batch_id distingue
    # lotes na ingestão expandida.
    source_key = _make_source_key(cloud, entry)

    # Resume: pular se já concluído nesta execução
    if progress and source_key in progress.get("completed", []):
        log.info("ingest_skipped_completed", cloud=cloud, service=entry["service"], batch=entry.get("batch_id", 0))
        return 0, 0

    log.info("ingesting", cloud=cloud, source=entry["source"], service=entry["service"], n_urls=len(urls))

    documents = await _load_documents(urls)

    # Round 22.4: fontes locais curadas (db/curated/*.md) complementam as URLs
    # quando o fetch remoto devolve boilerplate/404/bloqueio (AWS message pages,
    # medium.com). São carregadas como Documents com canonical_url nos metadados.
    local_files = entry.get("local_files") or []
    if local_files:
        local_docs = _load_local_documents(local_files)
        if local_docs:
            log.info(
                "ingest_local_files",
                cloud=cloud, service=entry["service"], n_local=len(local_docs),
            )
            documents.extend(local_docs)

    # Validação de conteúdo: descartar documentos vazios / casca de redirect.
    valid_documents = []
    for doc in documents:
        text_content = (doc.get_content() or "").strip()
        if len(text_content) < MIN_CONTENT_CHARS:
            log.warning(
                "ingest_document_skipped_thin",
                cloud=cloud, service=entry["service"],
                url=doc.metadata.get("url"), content_chars=len(text_content),
            )
            continue
        # doc_hash = hash do conteúdo bruto (base da detecção de mudança).
        doc.metadata["doc_hash"] = content_hash(text_content)
        valid_documents.append(doc)

    documents = valid_documents
    if not documents:
        log.warning("ingest_no_valid_documents", cloud=cloud, service=entry["service"], n_urls=len(urls))
        if progress and not dry_run:
            progress["completed"].append(source_key)
            save_progress(progress)
        return 0, 0

    # ─── Delta: pular inalterados, substituir alterados (ANTES de embedar) ───
    n_unchanged = 0
    if not dry_run and db_engine is not None:
        present_urls = [d.metadata["url"] for d in documents]
        existing = await _query_existing_doc_hashes(db_engine, present_urls)
        documents, changed_urls, n_unchanged = _partition_delta(documents, existing)
        if changed_urls:
            deleted = await _delete_docs_by_url(db_engine, changed_urls)
            log.info("ingest_docs_changed", cloud=cloud, service=entry["service"],
                     changed=len(changed_urls), old_chunks_deleted=deleted)

    if not documents:
        log.info("ingest_all_unchanged", cloud=cloud, service=entry["service"], unchanged=n_unchanged)
        if progress and not dry_run:
            progress["completed"].append(source_key)
            save_progress(progress)
        return 0, n_unchanged

    for doc in documents:
        doc.metadata.update(
            {
                "cloud": cloud,
                "service": entry["service"],
                "category": entry["category"],
                "source": entry["source"],
                "doc_type": entry.get("doc_type", "guide"),
                "framework": entry.get("framework"),
                "maturity": entry.get("maturity", "intermediate"),
            }
        )

    nodes = build_nodes(documents, embed_model)

    # Dedupe de chunk (2ª camada): pega chunks idênticos entre páginas distintas.
    existing_hashes: set[str] = set()
    if not dry_run and db_engine is not None:
        hashes = [n.metadata.get("content_hash") for n in nodes if n.metadata.get("content_hash")]
        existing_hashes = await _query_existing_chunk_hashes(db_engine, hashes)

    new_nodes = [n for n in nodes if n.metadata.get("content_hash") not in existing_hashes]
    skipped = len(nodes) - len(new_nodes)

    if dry_run:
        log.info("dry_run", cloud=cloud, service=entry["service"],
                 docs=len(documents), total_chunks=len(nodes), unchanged_docs=n_unchanged)
        return 0, 0

    if not new_nodes:
        log.info("ingest_skipped_all_existing", cloud=cloud, service=entry["service"], skipped=skipped)
        if progress:
            progress["completed"].append(source_key)
            save_progress(progress)
        return 0, skipped + n_unchanged

    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    VectorStoreIndex(new_nodes, storage_context=storage_context, embed_model=embed_model, show_progress=True)
    log.info("ingested", cloud=cloud, service=entry["service"],
             chunks=len(new_nodes), skipped_chunks=skipped, unchanged_docs=n_unchanged)

    if progress:
        progress["completed"].append(source_key)
        progress["total_chunks"] += len(new_nodes)
        save_progress(progress)

    return len(new_nodes), skipped + n_unchanged


# Ao expandir, um serviço pode ter milhares de páginas. Dividimos em lotes para
# limitar uso de memória, permitir resume granular e isolar falhas por lote.
EXPAND_BATCH_SIZE = 40


def _batch_entries(entries: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in entries:
        urls = e["urls"]
        if len(urls) <= size:
            out.append(e)
            continue
        for start in range(0, len(urls), size):
            sub = dict(e)
            sub["urls"] = urls[start:start + size]
            # batch_id torna a chave de progresso única por lote sem alterar o
            # campo 'source' (que vai para os metadados).
            sub["batch_id"] = start // size
            out.append(sub)
    return out


def _expand_sources(
    sources: dict[str, list[dict[str, Any]]],
    only_cloud: str | None,
    scope: str,
    max_pages: int | None,
    batch_size: int = EXPAND_BATCH_SIZE,
) -> dict[str, list[dict[str, Any]]]:
    """Substitui as URLs curadas pela cobertura exaustiva (sitemaps / llms.txt)."""
    from cip.ingestion import discovery

    expanded: dict[str, list[dict[str, Any]]] = {}
    for cloud in sources:
        if only_cloud and cloud != only_cloud:
            expanded[cloud] = sources[cloud]
            continue
        entries = discovery.build_expanded_entries(cloud, scope, cap=max_pages)
        n_pages = sum(len(e["urls"]) for e in entries)
        batched = _batch_entries(entries, batch_size)
        log.info(
            "sources_expanded",
            cloud=cloud,
            services=len(entries),
            pages=n_pages,
            batches=len(batched),
        )
        expanded[cloud] = batched
    return expanded


async def run(
    scope: str,
    only_cloud: str | None,
    dry_run: bool = False,
    resume: bool = False,
    expand: bool = False,
    max_pages: int | None = None,
    time_budget_min: int | None = None,
) -> None:
    import time

    from cip.rag.llm import build_embed_model
    from cip.rag.vector_store import build_vector_store

    sources = load_sources(scope)
    if expand:
        sources = _expand_sources(sources, only_cloud, scope, max_pages)
    embed_model = build_embed_model()
    vector_store = build_vector_store()

    # Engine único para toda a execução (evita recriar por lote).
    db_engine = None
    if not dry_run:
        from sqlalchemy.ext.asyncio import create_async_engine

        from cip.config import get_settings

        s = get_settings()
        db_engine = create_async_engine(
            s.database_url.replace("postgresql://", "postgresql+asyncpg://"),
            pool_pre_ping=True,
        )

    progress = load_progress() if resume else {"completed": [], "failed": [], "total_chunks": 0}
    if not resume:
        reset_progress()

    deadline = time.monotonic() + time_budget_min * 60 if time_budget_min else None
    stats = {"ingested_chunks": 0, "skipped": 0, "batches_done": 0, "batches_failed": 0}
    hit_budget = False
    try:
        for cloud, entries in sources.items():
            if only_cloud and cloud != only_cloud:
                continue
            for entry in entries:
                if deadline and time.monotonic() > deadline:
                    log.warning("time_budget_reached", note="encerrando; use --resume para continuar")
                    hit_budget = True
                    break
                src_key = _make_source_key(cloud, entry)
                try:
                    ingested, skipped = await ingest_entry(
                        cloud, entry, embed_model, vector_store, dry_run, progress, db_engine
                    )
                    stats["ingested_chunks"] += ingested
                    stats["skipped"] += skipped
                    stats["batches_done"] += 1
                except Exception as exc:  # noqa: BLE001
                    log.error("ingest_failed", cloud=cloud, service=entry["service"],
                              batch=entry.get("batch_id", 0), error=str(exc))
                    stats["batches_failed"] += 1
                    if progress:
                        progress["failed"].append(src_key)
                        save_progress(progress)
                    if not resume:
                        raise
            if hit_budget:
                break
    finally:
        if db_engine is not None:
            await db_engine.dispose()

    log.info("ingestion_complete", scope=scope, dry_run=dry_run,
             stopped_on_budget=hit_budget, **stats)

    # Invalida query cache (Round 15): nova ingestão pode mudar answers
    if not dry_run:
        try:
            from cip.rag.query_cache import get_query_cache
            cache = get_query_cache()
            cache.invalidate()  # limpa tudo (chave segura)
            log.info("query_cache_invalidated_post_ingestion")
        except Exception as exc:  # noqa: BLE001
            log.warning("query_cache_invalidation_failed", error=str(exc))


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestor da base de conhecimento CIP")
    parser.add_argument("--scope", choices=["mvp", "full"], default="mvp")
    parser.add_argument("--cloud", choices=["aws", "gcp", "azure"], default=None)
    parser.add_argument("--dry-run", action="store_true", help="Validar sem persistir no banco")
    parser.add_argument("--resume", action="store_true", help="Retomar de onde parou (usa ingest_progress.json)")
    parser.add_argument("--reset-progress", action="store_true", help="Limpar arquivo de progresso e começar do zero")
    parser.add_argument(
        "--expand",
        action="store_true",
        help="Ingestão exaustiva: expande cada serviço para TODAS as páginas "
             "da sua documentação (via llms.txt/sitemaps). Ver cip.ingestion.discovery",
    )
    parser.add_argument(
        "--max-pages-per-service",
        type=int,
        default=None,
        help="Limite de páginas por serviço ao usar --expand (padrão: sem limite)",
    )
    parser.add_argument(
        "--time-budget-min",
        type=int,
        default=None,
        help="Encerra graciosamente após N minutos (para caber em janelas de CI); "
             "combine com --resume para continuar na próxima execução",
    )
    args = parser.parse_args()

    if args.reset_progress:
        reset_progress()

    configure_logging()
    asyncio.run(
        run(
            args.scope,
            args.cloud,
            args.dry_run,
            args.resume,
            expand=args.expand,
            max_pages=args.max_pages_per_service,
            time_budget_min=args.time_budget_min,
        )
    )


if __name__ == "__main__":
    main()