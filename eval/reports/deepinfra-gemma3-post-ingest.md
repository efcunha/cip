# Post-ingest re-measure: DeepInfra gemma-3-27b-it, 3 pages added to the KB
- Generated: 2026-11-26T22:39:38.749540+00:00 (ON) / 2026-11-26T22:43:14.913261+00:00 (OFF). Runs per question: 3, max_tokens=1024, temperature=0.1, top_k=8, min_score=0.5, embedding BAAI/bge-large-en-v1.5 prefix `query: `.
- Corpus: `data_cloud_docs` 2928 -> 2973 rows (+45 chunks: Cosmos DB consistency-levels 15, Kubernetes disruptions 12, AKS use-multiple-node-pools 18). Nothing else changed: same questions, same `eval/ollama_compare.py`, same model; `retrieval_min_score` untouched (0.50).
- Before = `deepinfra-gemma3-query-translation-{on,off}-raw.json` (recomputed with the current hardened metrics, incl. `in_on_topic`). After = `deepinfra-gemma3-post-ingest-translation-{on,off}-raw.json`. Retrieval raw: `deepinfra-gemma3-post-ingest-retrieval-raw.json` (PT/EN) and `deepinfra-gemma3-post-ingest-translation-retrieval-raw.json` (PT translated).
- Commands (key from the Windows user env var, process-only): `ollama_compare.py retrieval`; `translate --backend openai --translation-raw ...`; `generation --backend openai --models google/gemma-3-27b-it --runs 3 --translation on|off --out ...`.

## Before / after (translation ON, production mode)
| Metric | Before | After |
|---|---|---|
| In-RAG false refusal | 19% | 0% |
| In-RAG valid answers | 81% | 100% |
| In-RAG on-topic (valid + must_mention) | 79% | 79% |
| In-RAG fallback (invalid citation) | 0% | 0% |
| Out-of-RAG refusal | 100% | 100% |
| Out-of-RAG answered with citation | 0% | 0% |
| Citation validity (answered) | 100% | 100% |
| Ambiguous acceptable | 100% | 100% |
| Answer TTFT median (s) | 0.64 | 0.74 |
| Answer TTFT p95 (s) | 1.22 | 1.21 |
| Answer total median (s) | 2.91 | 2.67 |
| Answer total p95 (s) | 5.68 | 5.78 |
| Answers (valid) count | 48 | 55 |
| Off-topic terms leaked (out-of-RAG answers) | 0 | 0 |
| Off-topic terms leaked (ambiguous) | 0 | 0 |

## Same metrics, translation OFF (PT-BR raw query)
| Metric | Before | After |
|---|---|---|
| In-RAG false refusal | 25% | 12% |
| In-RAG valid answers | 75% | 88% |
| In-RAG on-topic (valid + must_mention) | 65% | 69% |
| In-RAG fallback (invalid citation) | 0% | 0% |
| Out-of-RAG refusal | 100% | 100% |
| Out-of-RAG answered with citation | 0% | 0% |
| Citation validity (answered) | 100% | 100% |
| Ambiguous acceptable | 100% | 100% |
| Answer TTFT median (s) | 0.60 | 0.77 |
| Answer TTFT p95 (s) | 0.70 | 1.26 |
| Answer total median (s) | 1.97 | 3.56 |
| Answer total p95 (s) | 3.49 | 7.93 |

## Per-question in-RAG outcome (count of 3 runs: refused / valid / on-topic), ON
| id | before refused | before on-topic | after refused | after valid | after on-topic |
|---|---|---|---|---|---|
| in-01 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 |
| in-02 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 |
| in-03 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 |
| in-04 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 |
| in-05 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 |
| in-06 | 0/3 | 3/3 | 0/3 | 3/3 | 2/3 |
| in-07 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 |
| in-08 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 |
| in-09 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 |
| in-10 **(target)** | 3/3 | 0/3 | 0/3 | 3/3 | 1/3 |
| in-11 | 0/3 | 3/3 | 0/3 | 3/3 | 2/3 |
| in-12 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 |
| in-13 **(target)** | 3/3 | 0/3 | 0/3 | 3/3 | 0/3 |
| in-14 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 |
| in-15 **(target)** | 3/3 | 0/3 | 0/3 | 3/3 | 0/3 |
| in-16 | 0/3 | 2/3 | 0/3 | 3/3 | 3/3 |

## Retrieval of the 3 target questions (PT translated, top-4 fed to the model; top-k=8)
| id | top-1 before | top-1 after | top-1 URL after | top-4 chunks from new page | top-4 with answer keywords | top-8 from new page |
|---|---|---|---|---|---|---|
| in-13 | 0.750 | 0.856 | learn.microsoft.com/en-us/azure/cosmos-db/consistency-levels | 4/4 | 3/4 | 8/8 |
| in-15 | 0.700 | 0.741 | kubernetes.io/docs/concepts/workloads/pods/disruptions/ | 4/4 | 2/4 | 6/8 |
| in-10 | 0.721 | 0.773 | learn.microsoft.com/en-us/azure/aks/use-multiple-node-pools | 4/4 | 4/4 | 4/8 |

Note: `text` in the raw files is truncated to 1500 chars, so keyword counts are a lower bound.

## min_score distribution (top-1 cosine), after vs before the ingest
| Mode | Group | n | min before | min after | median before | median after | max before | max after |
|---|---|---|---|---|---|---|---|---|
| ON (PT translated) | in-RAG | 16 | 0.700 | 0.741 | 0.791 | 0.795 | 0.822 | 0.856 |
| ON (PT translated) | out-of-RAG | 12 | 0.491 | 0.491 | 0.598 | 0.598 | 0.697 | 0.697 |
| ON (PT translated) | ambiguous | 8 | 0.628 | 0.628 | 0.678 | 0.678 | 0.735 | 0.735 |
| OFF (PT raw) | in-RAG | 16 | 0.607 | 0.607 | 0.722 | 0.727 | 0.748 | 0.758 |
| OFF (PT raw) | out-of-RAG | 12 | 0.562 | 0.562 | 0.642 | 0.642 | 0.668 | 0.668 |
| OFF (PT raw) | ambiguous | 8 | 0.628 | 0.628 | 0.663 | 0.663 | 0.698 | 0.698 |
| EN | in-RAG | 16 | 0.700 | 0.741 | 0.790 | 0.792 | 0.822 | 0.859 |
| EN | out-of-RAG | 12 | 0.487 | 0.487 | 0.598 | 0.598 | 0.697 | 0.697 |
| EN | ambiguous | 8 | 0.628 | 0.628 | 0.676 | 0.676 | 0.735 | 0.735 |

- ON (PT translated): lowest in-RAG = in-15 0.7409; highest out-of-RAG = out-08 0.6966; separation +0.0443.
- OFF (PT raw): lowest in-RAG = in-04 0.6073; highest out-of-RAG = out-12 0.6681; separation -0.0608.

Questions gated (top-1 < threshold), in-RAG / out-of-RAG / ambiguous, after (before in parentheses):
| Threshold | ON after | ON before | OFF after | OFF before |
|---|---|---|---|---|
| 0.50 | 0/1/0 | 0/1/0 | 0/0/0 | 0/0/0 |
| 0.55 | 0/3/0 | 0/3/0 | 0/0/0 | 0/0/0 |
| 0.60 | 0/6/0 | 0/6/0 | 0/3/0 | 0/3/0 |
| 0.65 | 0/9/3 | 0/9/3 | 1/8/2 | 1/8/2 |
| 0.68 | 0/9/4 | 0/9/4 | 2/12/7 | 3/12/7 |
| 0.70 | 0/12/6 | 1/12/6 | 2/12/8 | 4/12/8 |
| 0.75 | 1/12/8 | 2/12/8 | 15/12/8 | 16/12/8 |

In-RAG top-1 after, ON, lowest five:
in-15 0.741, in-11 0.760, in-10 0.773, in-09 0.780, in-01 0.785

Out-of-RAG top-1 after, ON, highest five:
out-08 0.697, out-12 0.688, out-04 0.680, out-05 0.642, out-07 0.630

## Translation call latency (cold)
Before: median 0.43 s, p95 0.79 s. After: median 0.61 s, p95 1.33 s (n=36).
## Reading the results
- The 3 target questions (in-10, in-13, in-15) no longer get refused: false refusal ON 19% -> 0% (0/48 refused; 48/48 valid with valid citations). In all three, the top-4 context comes from the new page (4/4 chunks each).
- In-RAG on-topic stays 79% (38/48) because the metric `must_mention` is stricter than the answer: in-13 answers list all five levels (Strong, Bounded staleness, Session, Consistent prefix, Eventual) but never write the word "consistency" (0/3 on-topic); in-15 answers define PDB correctly but use the abbreviation "PDB" and never "PodDisruptionBudget" (0/3); in-10 answers are on-topic in 1/3 runs (runs 2 and 3 add the Azure Linux OS Guard retirement notice and miss the system/user pool terms). These are metric/term misses, not refusals; the eval questions were not changed in this step.
- Out-of-RAG refusal stays 100%, no off-topic leak (0 terms), no out-of-RAG answer with a citation. Citation validity stays 100%.
- Latency (answers that reached the LLM): TTFT median 0.64 -> 0.74 s, p95 1.22 -> 1.21 s; total median 2.91 -> 2.67 s, p95 5.68 -> 5.78 s. Translation call median 0.43 -> 0.61 s. The differences are inside the API day-to-day variance seen earlier (OFF baseline moved 0.60 -> 0.77 s TTFT with no code change); 7 more answers (55 vs 48) now go through generation instead of a fast refusal, which also lifts the all-answers numbers.
- Caveat: n=3 runs per condition; the cache of `cip-api` was not involved (eval runs the engine path directly against the DB).

## min_score candidate (report only, threshold unchanged at 0.50)
- The out-of-RAG distribution did not move (max ON 0.697, OFF 0.668): the 45 new chunks did not attract off-topic queries. In-RAG min ON rose 0.700 -> 0.741 (in-15 0.6996 -> 0.741), so the old in-15 problem at 0.70 is gone; separation ON is now +0.044 (before +0.003). OFF is still overlapping (in-04 0.607 below out-12 0.668).
- 0.60: ON gates 6/12 out-of-RAG, 0 in-RAG, 0 ambiguous; OFF gates 3/12 out-of-RAG, 0 in-RAG. Safe in both modes, margin ON 0.14, OFF 0.007 (in-04 0.607).
- 0.65: ON gates 9/12 out-of-RAG, 0 in-RAG, but 3/8 ambiguous (behaviour change visible to the user); OFF gates 1 in-RAG (in-04) + 8/12 out-of-RAG + 2 ambiguous, so 0.65 is only acceptable when translation is always on (translation failure or 5 s timeout falls back to the PT query).
- 0.70 is now feasible in ON (0 in-RAG gated, 12/12 out-of-RAG, 6/8 ambiguous) but refuses most ambiguous questions and breaks OFF (2 in-RAG gated); not recommended. Candidates unchanged: 0.60 (conservative, both modes) or 0.65 (ON only). Decision left to the user; `config.py` and the remote `cip.env` were not touched.
