# Ingestão exaustiva (cobertura ~100% dos serviços priorizados)

Este documento descreve a estratégia de **ingestão em massa** da documentação
oficial das três clouds, complementando a ingestão curada do `sources.yaml`.

## Por que não "100% de tudo"

Os catálogos das clouds têm centenas de serviços cada (AWS ~240, Azure ~200,
GCP ~150), com dezenas de milhares de páginas que mudam toda semana. Ingerir
*literalmente tudo* geraria uma base cara de manter, cheia de ruído (SDK
references, changelogs, páginas localizadas) e com baixo sinal para
recomendações de arquitetura.

A abordagem adotada é **cobertura exaustiva dos serviços priorizados**: o
catálogo curado em `sources.yaml` define *quais* serviços importam (com
categoria e metadados), e a camada de descoberta expande cada serviço para
**todas as páginas da sua documentação**.

## Fontes por provedor

| Cloud | Fonte de descoberta | Formato do conteúdo |
|-------|---------------------|---------------------|
| AWS   | `<guia>/llms.txt` (índice oficial para LLMs) | Markdown limpo via `.md` |
| GCP   | `docs.cloud.google.com/sitemap.xml` (60 sub-sitemaps) | HTML → markdown |
| Azure | `learn.microsoft.com/_sitemaps/sitemapindex.xml` (`azure_en-us_*`, `entra_en-us_*`) | HTML → markdown |

Observações:

- **AWS** é o melhor caso: cada guia expõe um `llms.txt` que lista todas as
  páginas, e cada página tem uma versão `.md` (markdown limpo, sem JS). Isso
  elimina o problema de renderização e produz chunks de alta qualidade.
- **GCP** publica sitemaps que incluem tudo (inclusive referências de SDK
  Java/Node/PHP). Filtramos pelo prefixo de produto derivado do `sources.yaml`
  (ex.: `/compute/docs`, `/bigquery/docs`).
- **Azure** publica um sitemap por produto **e por idioma**. Restringimos às
  sub-sitemaps `azure_en-us_*` (onde vive `/en-us/azure/<serviço>/`) e
  `entra_en-us_*`, e filtramos pelo caminho do serviço.

## Volume estimado (scope=full, sem limite)

| Cloud | Serviços | Páginas |
|-------|----------|---------|
| AWS   | 45       | ~24.300 |
| GCP   | 37       | ~178.000 |
| Azure | 38       | ~21.000 |

> Números variam conforme a documentação é atualizada. Use `--max-pages-per-service`
> para limitar durante testes.

## Como usar

### Prévia (não persiste, só conta páginas)

```bash
python -m cip.ingestion.discovery --cloud aws   --scope full
python -m cip.ingestion.discovery --cloud gcp   --scope full --limit 200
python -m cip.ingestion.discovery --cloud azure --scope full --json azure_pages.json
```

### Ingestão expandida

```bash
# Exaustivo (cuidado: dezenas de milhares de páginas)
python -m cip.ingestion.ingest --scope full --expand

# Recomendado para começar: limitar páginas por serviço + resume
python -m cip.ingestion.ingest --scope full --cloud aws --expand \
    --max-pages-per-service 300 --resume
```

Ao expandir, cada serviço é dividido em **lotes de 40 páginas**
(`EXPAND_BATCH_SIZE`). Cada lote tem uma chave de progresso própria, então
`--resume` retoma exatamente de onde parou e falhas ficam isoladas por lote.

## Ingestão incremental (delta) — o que torna a automação viável

O passo caro da ingestão é o **embedding** (o `SemanticSplitterNodeParser` usa
embeddings para dividir o texto). Reprocessar ~223 mil páginas a cada execução
seria inviável. Por isso a ingestão é **incremental**:

1. Cada página baixada tem um `doc_hash` (SHA-256 do conteúdo bruto).
2. Antes de embedar, o ingestor consulta o banco:
   - **inalterada** (`url` + `doc_hash` já existem) → **pulada** (sem embedding);
   - **alterada** (`url` existe, `doc_hash` diferente) → chunks antigos são
     removidos e a página é re-ingerida;
   - **nova** (`url` ausente) → ingerida.
3. Dedupe adicional por `content_hash` de chunk (pega chunks idênticos entre
   páginas diferentes).

Resultado: depois da carga inicial, as execuções recorrentes só embedam o que
realmente mudou — rápido e barato.

## Automação (GitHub Actions)

O workflow `.github/workflows/refresh-docs.yml` mantém a base atualizada **sem
ação humana**:

- **Agendado semanalmente** (segunda, 03:00 UTC), em paralelo por cloud (matrix).
- Roda `ingest --scope full --expand --resume --time-budget-min N` por cloud.
- **Cache** dos sitemaps e do progresso entre execuções (menos retrabalho).
- **`--time-budget-min`** encerra o job com folga dentro do limite do runner;
  `--resume` continua na execução seguinte.
- `workflow_dispatch` permite disparo manual com `cloud`, `max_pages_per_service`
  e `time_budget_min` como parâmetros.
- Um gate `validate-links` roda em PRs que alteram o `sources.yaml`.

> **Pré-requisitos de infraestrutura**: o runner precisa alcançar o banco
> pgvector (via `DB_HOST` público/túnel ou runner self-hosted). O embedding com
> `BAAI/bge-large-en-v1.5` em CPU é lento para o corpus completo — recomenda-se
> fazer a **carga inicial (seed)** uma vez em infraestrutura com mais recursos
> (ou GPU) e deixar o CI cuidar apenas do **delta semanal**, que é leve.

## Robustez

- **Cache**: os sitemaps baixados ficam em `src/cip/ingestion/.discovery_cache/`
  (ignorado pelo git). Re-execuções não rebaixam tudo; só o que faltou.
- **Filtro de conteúdo**: o ingestor descarta páginas com menos de
  `MIN_CONTENT_CHARS` (500) caracteres — evita indexar páginas vazias ou casca
  de redirect.
- **Delta + dedupe**: `doc_hash` (nível de página) evita re-embedar o que não
  mudou; `content_hash` (nível de chunk) evita chunks repetidos.
- **Lotes**: cada serviço é dividido em lotes de 40 páginas, com falhas isoladas
  e progresso por lote.
- **Paralelismo**: downloads de sub-sitemaps são paralelizados; um sub-sitemap
  que falhe por timeout é apenas logado e recuperado no próximo run (cache).

## Filtro de ruído

O `discovery.py` descarta URLs de baixo valor arquitetural (ver
`DEFAULT_EXCLUDE_PATTERNS`): referências de SDK/CLI/API, release notes, amostras
de código e — o maior ofensor no GCP — **variantes de idioma** (`?hl=...`) e de
versão (`?view=...`). Cada página do GCP aparecia ~14x (uma por locale); manter
só a canônica derrubou o GCP de 178k para ~11k páginas.

| Cloud | Sem filtro | Com filtro | Redução |
|-------|-----------|-----------|---------|
| GCP   | ~178.000  | ~11.400   | −94% |
| Azure | ~21.000   | ~15.700   | −25% |
| AWS   | ~24.300   | ~24.300   | ~0 (já limpo via `.md`) |
| **Total** | **~223.000** | **~51.400** | **−77%** |

## Estimativa de custo/tempo (medida nesta infra)

Benchmark real (CPU do runner): modelo pequeno de 384d embeda ~8 chunks/s
(embedding final); com o `SemanticSplitter` (que também embeda) o efetivo fica
em ~4-6 chunks/s. Tokens/página: AWS `.md` ~2,5k (limpo); GCP/Azure ~10k (HTML
com boilerplate).

| Cenário | Páginas | Chunks (aprox.) | Tempo embed (CPU) | Storage (384d) |
|---------|---------|-----------------|-------------------|----------------|
| **Curado (padrão prod.)** | ~245 | ~2.000 | ~5-10 min | ~12 MB |
| Exaustivo filtrado | ~51.400 | ~400.000 | ~20-24 h (1 CPU) | ~2,3 GB |

Custo com embeddings **gerenciados** (opcional, ~US$0,02/1M tokens):
- Curado: ~US$ 0,05 (uma vez).
- Exaustivo: ~US$ 15-25 (uma vez); o delta semanal depois é centavos.

> **Conclusão prática:** o **curado** roda tranquilo em servidor barato (poucos
> MB, minutos de embedding, ~0,5 GB de RAM para o modelo). O **exaustivo** só faz
> sentido com infra dedicada (ou embeddings gerenciados) — não é o padrão.

## Ajuste de `MIN_CONTENT_CHARS`

Mantido em **500** caracteres: descarta páginas vazias/casca de redirect sem
cortar conteúdo real. Como GCP/Azure são páginas longas e a AWS vem em `.md`
limpo, não há ganho em subir o limite; o corte de ruído é feito por URL (acima).

## Boas práticas / limites

- Respeite `robots.txt` e os termos de uso de cada provedor. Os caminhos de
  documentação usados aqui são públicos e permitidos para leitura.
- Prefira rodar a ingestão exaustiva de forma incremental (por cloud, com
  `--max-pages-per-service` e `--resume`) antes de um full completo.
- A re-ingestão mensal (workflow `refresh-docs.yml`) mantém o conhecimento
  atualizado sem retreino do modelo.
