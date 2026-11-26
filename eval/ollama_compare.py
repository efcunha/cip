"""Comparação de modelos Ollama para o caminho de geração grounded da CIP.

Mede, por modelo candidato, time-to-first-token (TTFT), tempo total, tokens/s,
groundedness (toda citação ``[n]`` existe entre os trechos recuperados, via
``cip.rag.grounded.validate_answer``) e correção de recusa. Também mede a qualidade de
recuperação para perguntas PT-BR vs EN (embeddings bge-large-en-v1.5, só inglês).

Somente leitura: o retrieval consulta o banco remoto via ``ssh`` + ``psql`` dentro de uma
sessão ``default_transaction_read_only``. Nada é ingerido, alterado ou implantado.

Fases (pode rodar separado; o resultado de cada fase fica em ``eval/reports/``):
    python eval/ollama_compare.py retrieval            # embeda perguntas + consulta o DB remoto
    python eval/ollama_compare.py generation --models qwen2.5:3b-instruct gemma3:4b
    python eval/ollama_compare.py report               # monta o relatório Markdown
    python eval/ollama_compare.py all                  # as três

Requer, para ``retrieval``: sentence-transformers + torch e acesso ssh ao host ``cloudpilot``
(``--ssh-host``). Requer, para ``generation``: um Ollama acessível (``--ollama``) com os
modelos já baixados e ``httpx``. Nenhum segredo é lido ou gravado.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cip.rag.grounded import (  # noqa: E402
    DECLINE_SENTINEL,
    build_grounded_messages,
    is_decline,
    validate_answer,
)

QUESTIONS_FILE = Path(__file__).parent / "ollama_questions.json"
REPORTS_DIR = Path(__file__).parent / "reports"
RETRIEVAL_RAW = REPORTS_DIR / "ollama-retrieval-raw.json"
GENERATION_RAW = REPORTS_DIR / "ollama-generation-raw.json"
REPORT_MD = REPORTS_DIR / "ollama-model-comparison.md"

DEFAULT_MODELS = ["qwen2.5:3b-instruct", "gemma3:4b", "qwen2.5:7b-instruct"]
GROUPS = ("in_rag", "out_of_rag", "ambiguous")
# Variantes do prefixo de query: "none" = sem prefixo; "e5" = "query: " (config atual da CIP,
# convenção E5 aplicada a um BGE); "bge" = instrução oficial do BGE para retrieval.
VARIANTS = {
    "none": "",
    "e5": "query: ",
    "bge": "Represent this sentence for searching relevant passages: ",
}
PROD_VARIANT = "e5"  # o que o engine faz hoje (embed_query_instruction="query: ")
EMBED_MODEL = "BAAI/bge-large-en-v1.5"
# Mesmos valores de src/cip/config.py
TOP_K = 8
MIN_SCORE = 0.50
LLM_CONTEXT_TOP_K = 4
LLM_CHUNK_CHARS = 1200
NUM_CTX = 4096
MAX_TOKENS = 512
TEMPERATURE = 0.1


# --------------------------------------------------------------------------- helpers
def load_questions(path: Path = QUESTIONS_FILE) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for group in GROUPS:
        for q in data[group]:
            out.append({**q, "group": group})
    return out


def _fold(text: str) -> str:
    """minúsculas + sem acentos, para comparar menções."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def mention_hits(answer: str, terms: list[str]) -> tuple[int, int]:
    """Quantos termos (``a|b`` = qualquer alternativa) aparecem na resposta."""
    low = _fold(answer)
    hits = sum(1 for t in terms if any(_fold(alt) in low for alt in t.split("|")))
    return hits, len(terms)


def forbidden_hits(answer: str, terms: list[str]) -> list[str]:
    low = _fold(answer)
    return [t for t in terms if _fold(t) in low]


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = min(len(s) - 1, max(0, int(round(p / 100 * (len(s) - 1)))))
    return s[k]


def med(values: list[float]) -> float:
    return statistics.median(values) if values else float("nan")


def rate(num: int, den: int) -> float:
    return num / den if den else float("nan")


def fmt_pct(x: float) -> str:
    return "n/a" if x != x else f"{100 * x:.0f}%"


def fmt_num(x: float, nd: int = 2) -> str:
    return "n/a" if x != x else f"{x:.{nd}f}"


# --------------------------------------------------------------------------- retrieval
def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def build_retrieval_sql(jobs: list[dict[str, Any]], top_k: int) -> str:
    """SQL somente-leitura: uma linha JSON por job (chave + top-k chunks por cosseno)."""
    lines = ["SET default_transaction_read_only = on;"]
    for j in jobs:
        key = j["key"].replace("'", "''")
        lines.append(
            "SELECT jsonb_build_object('key','" + key + "','rows',coalesce(jsonb_agg("
            "jsonb_build_object('score',score,'service',svc,'cloud',cld,'url',url,"
            "'header_path',hp,'text',txt) ORDER BY score DESC),'[]'::jsonb))::text FROM ("
            "SELECT 1-(embedding <=> '" + _vec_literal(j["vec"]) + "'::vector) AS score,"
            "metadata_->>'service' AS svc,metadata_->>'cloud' AS cld,metadata_->>'url' AS url,"
            "metadata_->>'header_path' AS hp,left(text,1500) AS txt FROM data_cloud_docs "
            f"ORDER BY embedding <=> '{_vec_literal(j['vec'])}'::vector LIMIT {top_k}) t;"
        )
    return "\n".join(lines) + "\n"


def run_remote_sql(sql: str, ssh_host: str, pg_user: str, timeout: int) -> dict[str, list]:
    remote = (
        f"sudo stackctl shell -- podman exec -i postgres psql -U {pg_user} -d cip "
        "-At -v ON_ERROR_STOP=1"
    )
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", ssh_host, remote],
        input=sql.encode("utf-8"), capture_output=True, timeout=timeout, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ssh/psql failed: {proc.stderr.decode('utf-8', 'replace')[:500]}")
    results: dict[str, list] = {}
    for line in proc.stdout.decode("utf-8").splitlines():
        if line.startswith("{"):
            obj = json.loads(line)
            results[obj["key"]] = obj["rows"]
    return results


def phase_retrieval(args: argparse.Namespace) -> dict[str, Any]:
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    questions = load_questions()
    model = SentenceTransformer(EMBED_MODEL, device="cpu")
    jobs: list[dict[str, Any]] = []
    for q in questions:
        for lang, field in (("pt", "question"), ("en", "question_en")):
            for vname, prefix in VARIANTS.items():
                jobs.append({"key": f"{q['id']}|{lang}|{vname}", "text": prefix + q[field]})
    vecs = model.encode([j["text"] for j in jobs], normalize_embeddings=True, batch_size=16)
    for j, v in zip(jobs, vecs, strict=True):
        j["vec"] = [float(x) for x in v]
    results: dict[str, list] = {}
    for i in range(0, len(jobs), 40):  # lotes: stdin do ssh não fica gigante
        results.update(run_remote_sql(
            build_retrieval_sql(jobs[i:i + 40], TOP_K), args.ssh_host, args.pg_user, 300))
    missing = [j["key"] for j in jobs if j["key"] not in results]
    if missing:
        raise RuntimeError(f"retrieval missing {len(missing)} keys, e.g. {missing[:3]}")
    raw = {
        "generated_at": datetime.now(UTC).isoformat(),
        "embed_model": EMBED_MODEL, "top_k": TOP_K, "min_score": MIN_SCORE,
        "variants": VARIANTS, "results": results,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    RETRIEVAL_RAW.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    print(f"retrieval: {len(results)} queries -> {RETRIEVAL_RAW}")
    return raw


def retrieval_summary(raw: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Métricas de retrieval por (idioma, variante)."""
    res = raw["results"]
    out: dict[str, Any] = {}
    for lang in ("pt", "en"):
        for vname in VARIANTS:
            inr = [q for q in questions if q["group"] == "in_rag"]
            top1: list[float] = []
            hit1 = hitk = below = n_above = 0
            for q in inr:
                rows = res[f"{q['id']}|{lang}|{vname}"]
                exp = set(q["expected_service"])
                top1.append(rows[0]["score"])
                hit1 += rows[0]["service"] in exp
                hitk += any(r["service"] in exp for r in rows)
                below += rows[0]["score"] < raw["min_score"]
                n_above += sum(1 for r in rows if r["score"] >= raw["min_score"])
            leak: dict[str, float] = {}
            for g in ("out_of_rag", "ambiguous"):
                gq = [q for q in questions if q["group"] == g]
                above = sum(1 for q in gq
                            if res[f"{q['id']}|{lang}|{vname}"][0]["score"] >= raw["min_score"])
                leak[g] = rate(above, len(gq))
            out[f"{lang}|{vname}"] = {
                "n": len(inr), "recall_top1": rate(hit1, len(inr)),
                "recall_topk": rate(hitk, len(inr)),
                "top1_median": med(top1), "top1_min": min(top1), "top1_max": max(top1),
                "below_min_score": rate(below, len(inr)),
                "chunks_above_min_mean": n_above / len(inr),
                "leak_above_min": leak,
            }
    return out


def nodes_for(raw: dict[str, Any], qid: str, lang: str = "pt",
              variant: str = PROD_VARIANT) -> tuple[list[Any], int]:
    """Nós como o engine local os veria: gate min_score, depois top llm_context_top_k.

    Retorna ``(nodes, n_above_min_score)``.
    """
    rows = [r for r in raw["results"][f"{qid}|{lang}|{variant}"] if r["score"] >= raw["min_score"]]
    nodes = [
        SimpleNamespace(
            text=r["text"], score=r["score"],
            metadata={"url": r["url"], "service": r["service"], "cloud": r["cloud"]},
        )
        for r in rows[:LLM_CONTEXT_TOP_K]
    ]
    return nodes, len(rows)


# --------------------------------------------------------------------------- generation
MIN_CONTENT_CHARS = 40
_CITE_ONLY_RE = re.compile(r"\[\d{1,3}(?:\s*,\s*\d{1,3})*\]")


def has_content(answer: str) -> bool:
    """Falso quando a resposta é só marcadores ``[n]`` (citação sem afirmação)."""
    body = _CITE_ONLY_RE.sub("", answer)
    return len(re.sub(r"[\W_]+", "", body)) >= MIN_CONTENT_CHARS


def is_loose_decline(answer: str) -> bool:
    """Sentinela mais marcadores ``[n]``/pontuação: recusa na intenção, mas não exata.

    ``is_decline`` do engine exige igualdade exata, então em produção isto seria tratado
    como resposta e mostraria ``NAO_ENCONTRADO [1]`` ao usuário. Medido à parte.
    """
    return DECLINE_SENTINEL in answer.upper() and not has_content(
        re.sub(DECLINE_SENTINEL, "", answer, flags=re.IGNORECASE))


def classify(answer: str, nodes: list[Any]) -> tuple[str, str | None]:
    """Resultado de uma geração: declined | valid | invalid (cai no extractive).

    ``valid`` exige citações válidas (``validate_answer``) E conteúdo além dos marcadores.
    """
    if is_decline(answer):
        return "declined", None
    if is_loose_decline(answer):
        return "declined", "loose_sentinel"
    v = validate_answer(answer, nodes)
    if not v.ok:
        return "invalid", v.reason
    if not has_content(answer):
        return "invalid", "no_content"
    return "valid", None


def stream_chat(client: Any, base: str, model: str, system: str, user: str,
                num_gpu: int | None, timeout: float) -> dict[str, Any]:
    """Uma geração via /api/chat com streaming; mede TTFT e total (wall-clock)."""
    options: dict[str, Any] = {
        "num_ctx": NUM_CTX, "temperature": TEMPERATURE, "num_predict": MAX_TOKENS,
    }
    if num_gpu is not None:
        options["num_gpu"] = num_gpu
    body = {
        "model": model, "stream": True, "keep_alive": "30m", "options": options,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    t0 = time.perf_counter()
    ttft: float | None = None
    parts: list[str] = []
    final: dict[str, Any] = {}
    try:
        with client.stream("POST", f"{base}/api/chat", json=body, timeout=timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                obj = json.loads(line)
                piece = (obj.get("message") or {}).get("content") or ""
                if piece:
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    parts.append(piece)
                if obj.get("done"):
                    final = obj
    except Exception as exc:  # noqa: BLE001 - registrar e seguir (equivale a fallback no engine)
        return {"error": f"{type(exc).__name__}: {exc}"[:300], "answer": "".join(parts),
                "ttft_s": ttft, "total_s": time.perf_counter() - t0}
    total = time.perf_counter() - t0
    ev_n = final.get("eval_count") or 0
    ev_ns = final.get("eval_duration") or 0
    return {
        "answer": "".join(parts).strip(), "ttft_s": ttft, "total_s": total,
        "eval_count": ev_n, "tokens_per_s": (ev_n / (ev_ns / 1e9)) if ev_ns else None,
        "prompt_tokens": final.get("prompt_eval_count"),
        "load_s": (final.get("load_duration") or 0) / 1e9,
    }


def phase_generation(args: argparse.Namespace) -> dict[str, Any]:
    import httpx  # noqa: PLC0415

    raw_ret = json.loads(RETRIEVAL_RAW.read_text(encoding="utf-8"))
    questions = load_questions()
    if args.ids:
        questions = [q for q in questions if q["id"] in set(args.ids)]
    if args.max_per_group:
        seen: dict[str, int] = {}
        kept = []
        for q in questions:
            seen[q["group"]] = seen.get(q["group"], 0) + 1
            if seen[q["group"]] <= args.max_per_group:
                kept.append(q)
        questions = kept
    out: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(), "ollama": args.ollama,
        "runs": args.runs, "num_gpu": args.num_gpu, "num_ctx": NUM_CTX,
        "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE, "models": {},
    }
    with httpx.Client() as client:
        ver = client.get(f"{args.ollama}/api/version", timeout=10).json()
        out["ollama_version"] = ver.get("version")
        for model in args.models:
            print(f"== {model}")
            # warm-up descartado (carrega o modelo na memória)
            sysm, usr = build_grounded_messages("O que é o Amazon S3?", [], LLM_CHUNK_CHARS)
            warm = stream_chat(client, args.ollama, model, sysm, usr, args.num_gpu, args.timeout)
            print(f"   warm-up: {warm.get('total_s', 0):.1f}s {warm.get('error', '')}")
            records: list[dict[str, Any]] = []
            for q in questions:
                nodes, n_above = nodes_for(raw_ret, q["id"])
                if not nodes:  # gate min_score: o engine recusa sem chamar o LLM
                    records.append({"id": q["id"], "group": q["group"], "outcome": "gated",
                                    "n_above": n_above, "run": 0})
                    continue
                system, user = build_grounded_messages(q["question"], nodes, LLM_CHUNK_CHARS)
                for run in range(1, args.runs + 1):
                    r = stream_chat(client, args.ollama, model, system, user,
                                    args.num_gpu, args.timeout)
                    rec: dict[str, Any] = {"id": q["id"], "group": q["group"], "run": run,
                                           "n_above": n_above, "n_ctx_nodes": len(nodes), **r}
                    if r.get("error") or not r["answer"]:
                        rec["outcome"], rec["reason"] = "invalid", r.get("error", "empty_answer")
                    else:
                        rec["outcome"], rec["reason"] = classify(r["answer"], nodes)
                    must = q.get("must_mention") or []
                    rec["mention_hits"], rec["mention_total"] = mention_hits(r["answer"], must)
                    rec["forbidden"] = ([] if rec["outcome"] == "declined"
                                        else forbidden_hits(r["answer"],
                                                            q.get("must_not_mention") or []))
                    records.append(rec)
                    print(f"   {q['id']} r{run} {rec['outcome']:8s} "
                          f"ttft={(r.get('ttft_s') or 0):.1f}s total={r['total_s']:.1f}s")
            out["models"][model] = records
            # libera RAM/VRAM antes do próximo candidato
            client.post(f"{args.ollama}/api/generate",
                        json={"model": model, "keep_alive": 0}, timeout=60)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    target = Path(args.out) if args.out else GENERATION_RAW
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"generation -> {target}")
    return out


def normalize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reaplica a regra ``no_content`` a registros gravados antes dela existir."""
    out = []
    for r in records:
        ans = r.get("answer", "")
        if r.get("outcome") in ("valid", "invalid") and is_loose_decline(ans):
            r = {**r, "outcome": "declined", "reason": "loose_sentinel", "forbidden": []}
        elif r.get("outcome") == "valid" and not has_content(ans):
            r = {**r, "outcome": "invalid", "reason": "no_content", "forbidden": []}
        out.append(r)
    return out


def model_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    records = normalize(records)
    llm = [r for r in records if r["outcome"] != "gated"]
    ok_lat = [r for r in llm if not r.get("error") and r.get("ttft_s") is not None]
    ttft = [r["ttft_s"] for r in ok_lat]
    total = [r["total_s"] for r in ok_lat]
    tps = [r["tokens_per_s"] for r in ok_lat if r.get("tokens_per_s")]
    subst = [r for r in ok_lat if r["outcome"] == "valid"]
    s_ttft = [r["ttft_s"] for r in subst]
    s_total = [r["total_s"] for r in subst]
    # run 1 = prefill frio; runs 2+ reaproveitam o cache de prompt do Ollama (TTFT otimista)
    s_ttft_cold = [r["ttft_s"] for r in subst if r.get("run") == 1]

    def of(group: str) -> list[dict[str, Any]]:
        return [r for r in records if r["group"] == group]

    inr, oor, amb = of("in_rag"), of("out_of_rag"), of("ambiguous")
    answered = [r for r in llm if r["outcome"] in ("valid", "invalid")]
    mention = [r["mention_hits"] / r["mention_total"] for r in inr
               if r["outcome"] == "valid" and r.get("mention_total")]
    amb_ok = [r for r in amb if r["outcome"] in ("declined", "gated")
              or (r["outcome"] == "valid" and not r.get("forbidden"))]
    return {
        "llm_calls": len(llm), "errors": sum(1 for r in llm if r.get("error")),
        "ttft_med": med(ttft), "ttft_p95": pct(ttft, 95),
        "total_med": med(total), "total_p95": pct(total, 95), "tps_med": med(tps),
        "a_ttft_cold_med": med(s_ttft_cold), "answers": len(subst),
        "a_ttft_med": med(s_ttft), "a_ttft_p95": pct(s_ttft, 95),
        "a_total_med": med(s_total), "a_total_p95": pct(s_total, 95),
        "no_content": sum(1 for r in llm if r.get("reason") == "no_content"),
        "loose_declines": sum(1 for r in llm if r.get("reason") == "loose_sentinel"),
        "citation_valid_rate": rate(sum(1 for r in answered if r["outcome"] == "valid"),
                                    len(answered)),
        "in_valid": rate(sum(1 for r in inr if r["outcome"] == "valid"), len(inr)),
        "in_false_refusal": rate(sum(1 for r in inr if r["outcome"] in ("declined", "gated")),
                                 len(inr)),
        "in_fallback": rate(sum(1 for r in inr if r["outcome"] == "invalid"), len(inr)),
        "in_mention": med(mention) if mention else float("nan"),
        "out_refused": rate(sum(1 for r in oor if r["outcome"] in ("declined", "gated")),
                            len(oor)),
        "out_refused_by_model": rate(sum(1 for r in oor if r["outcome"] == "declined"),
                                     len(oor)),
        "out_gated": rate(sum(1 for r in oor if r["outcome"] == "gated"), len(oor)),
        "out_answered_cited": rate(sum(1 for r in oor if r["outcome"] == "valid"), len(oor)),
        "out_fallback": rate(sum(1 for r in oor if r["outcome"] == "invalid"), len(oor)),
        "out_forbidden": sum(len(r.get("forbidden") or []) > 0 for r in oor),
        "amb_ok": rate(len(amb_ok), len(amb)),
        "amb_fallback": rate(sum(1 for r in amb if r["outcome"] == "invalid"), len(amb)),
        "amb_forbidden": sum(len(r.get("forbidden") or []) > 0 for r in amb),
        "n_in": len(inr), "n_out": len(oor), "n_amb": len(amb),
    }


# --------------------------------------------------------------------------- report
def phase_report(args: argparse.Namespace) -> str:
    questions = load_questions()
    lines = ["# Ollama model comparison (generated by eval/ollama_compare.py)", ""]
    gen_path = Path(args.gen) if args.gen else GENERATION_RAW
    gen = json.loads(gen_path.read_text(encoding="utf-8")) if gen_path.exists() else None
    if gen:
        lines += [
            f"- Generated: {gen['generated_at']}, Ollama {gen.get('ollama_version')}, "
            f"runs per question: {gen['runs']}, num_ctx={gen['num_ctx']}, "
            f"max_tokens={gen['max_tokens']}, temperature={gen['temperature']}, "
            f"num_gpu={gen['num_gpu'] if gen['num_gpu'] is not None else 'default'}",
            "", "## Latency and groundedness per model", "",
            "Substantive answers = valid citations plus real content. Declines such as "
            "`NAO_ENCONTRADO` are short, so they are excluded from the answer columns. "
            "`no_content` = only `[n]` "
            "markers; `loose decline` = sentinel plus markers (refusal intent, but the engine's "
            "exact-match `is_decline` would show it to the user as text); both counted over "
            "all runs.", "",
            "| Model | Answers | Answer TTFT cold, run 1 (s) | Answer TTFT med (s) | "
            "Answer TTFT p95 (s) | Answer total med (s) "
            "| Answer total p95 (s) | All-calls TTFT med (s) | All-calls total med (s) | tok/s | "
            "Citation-valid | In-RAG valid | In-RAG false refusal | In-RAG fallback | "
            "no_content | loose decline | must_mention |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        sums = {m: model_summary(r) for m, r in gen["models"].items()}
        for m, s in sums.items():
            lines.append(
                f"| {m} | {s['answers']} | {fmt_num(s['a_ttft_cold_med'])} | "
                f"{fmt_num(s['a_ttft_med'])} | "
                f"{fmt_num(s['a_ttft_p95'])} | {fmt_num(s['a_total_med'])} | "
                f"{fmt_num(s['a_total_p95'])} | {fmt_num(s['ttft_med'])} | "
                f"{fmt_num(s['total_med'])} | {fmt_num(s['tps_med'], 1)} | "
                f"{fmt_pct(s['citation_valid_rate'])} | {fmt_pct(s['in_valid'])} | "
                f"{fmt_pct(s['in_false_refusal'])} | {fmt_pct(s['in_fallback'])} | "
                f"{s['no_content']} | {s['loose_declines']} | {fmt_pct(s['in_mention'])} |")
        lines += ["", "## Refusal correctness per model", "",
                  "| Model | Out-of-RAG refused (total) | by model | gated by min_score | "
                  "answered with citation | fallback | off-topic terms leaked | "
                  "Ambiguous acceptable | Ambiguous fallback | Ambiguous leaks |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for m, s in sums.items():
            lines.append(
                f"| {m} | {fmt_pct(s['out_refused'])} | {fmt_pct(s['out_refused_by_model'])} | "
                f"{fmt_pct(s['out_gated'])} | {fmt_pct(s['out_answered_cited'])} | "
                f"{fmt_pct(s['out_fallback'])} | {s['out_forbidden']}/{s['n_out']} | "
                f"{fmt_pct(s['amb_ok'])} | {fmt_pct(s['amb_fallback'])} | "
                f"{s['amb_forbidden']}/{s['n_amb']} |")
        s0 = next(iter(sums.values()))
        lines += ["", f"Question counts: in_rag={s0['n_in']}, out_of_rag={s0['n_out']}, "
                  f"ambiguous={s0['n_amb']}. Latency rows only count calls that reached the "
                  "LLM (questions gated by min_score never call it).", ""]
    if RETRIEVAL_RAW.exists():
        raw = json.loads(RETRIEVAL_RAW.read_text(encoding="utf-8"))
        rs = retrieval_summary(raw, questions)
        lines += [
            "## PT-BR vs EN retrieval (bge-large-en-v1.5, read-only, no re-ingest)", "",
            f"Top-k={raw['top_k']}, min_score={raw['min_score']}. In-RAG questions "
            f"(n={rs['pt|none']['n']}). Variant `e5` = `query: ` prefix (current CIP config), "
            "`none` = no prefix, `bge` = official BGE retrieval instruction.", "",
            "| Lang | Prefix | recall@1 | recall@k | top-1 median | top-1 min | top-1 max | "
            "top-1 < min_score | chunks >= min_score (mean) | out-of-RAG top-1 >= min_score | "
            "ambiguous top-1 >= min_score |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for key, v in rs.items():
            lang, vname = key.split("|")
            lines.append(
                f"| {lang} | {vname} | {fmt_pct(v['recall_top1'])} | {fmt_pct(v['recall_topk'])} "
                f"| {fmt_num(v['top1_median'])} | {fmt_num(v['top1_min'])} | "
                f"{fmt_num(v['top1_max'])} | {fmt_pct(v['below_min_score'])} | "
                f"{fmt_num(v['chunks_above_min_mean'], 1)} | "
                f"{fmt_pct(v['leak_above_min']['out_of_rag'])} | "
                f"{fmt_pct(v['leak_above_min']['ambiguous'])} |")
        lines += ["", "Per-question top-1 (prefix `e5`, as in production):", "",
                  "| id | PT top-1 score | PT top-1 service | EN top-1 score | EN top-1 service "
                  "| expected |", "|---|---|---|---|---|---|"]
        for q in (x for x in questions if x["group"] == "in_rag"):
            p = raw["results"][f"{q['id']}|pt|{PROD_VARIANT}"][0]
            e = raw["results"][f"{q['id']}|en|{PROD_VARIANT}"][0]
            lines.append(f"| {q['id']} | {p['score']:.3f} | {p['service']} | {e['score']:.3f} | "
                         f"{e['service']} | {','.join(q['expected_service'])} |")
        lines.append("")
    text = "\n".join(lines) + "\n"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    target = Path(args.report_out) if args.report_out else REPORT_MD
    target.write_text(text, encoding="utf-8")
    print(f"report -> {target}")
    return text


# --------------------------------------------------------------------------- cli
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("phase", choices=["retrieval", "generation", "report", "all"])
    p.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    p.add_argument("--ollama", default="http://localhost:11434")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--num-gpu", type=int, default=None, help="0 força CPU-only")
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--ids", nargs="*", help="só estes ids de pergunta")
    p.add_argument("--max-per-group", type=int, default=0)
    p.add_argument("--out", help="arquivo JSON de saída da geração")
    p.add_argument("--gen", help="arquivo JSON de geração usado no relatório")
    p.add_argument("--report-out", help="arquivo Markdown de saída")
    p.add_argument("--ssh-host", default="cloudpilot")
    p.add_argument("--pg-user", default="cloudpilot")
    args = p.parse_args()
    if args.phase in ("retrieval", "all"):
        phase_retrieval(args)
    if args.phase in ("generation", "all"):
        phase_generation(args)
    if args.phase in ("report", "all"):
        phase_report(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
