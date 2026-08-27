# MCP Server — Cloud Intelligence Platform (CIP)

Servidor MCP (Model Context Protocol) que expõe o CIP como ferramenta para
agentes externos (Cursor, Kiro, Claude Desktop, etc.).

## Ferramentas

| Tool         | Descrição                                                                   | Requer API? |
|--------------|-----------------------------------------------------------------------------|-------------|
| `cip_ask`    | Consulta arquitetura/boas práticas das 3 clouds (RAG puro, com fontes).     | Sim         |
| `cip_inspect`| Analisa Terraform (.tf) ou K8s YAML → findings de segurança/custo/práticas. | Não         |
| `cip_analyze`| Análise aprofundada (RAG + tools + inspeção) → summary + findings + fontes. | Sim         |

## Requisitos

- **API CIP rodando** em `http://localhost:8000` (obrigatório para `cip_ask` e
  `cip_analyze`; opcional para `cip_inspect`).

  ```powershell
  # dentro do diretório do projeto
  uvicorn cip.api.app:app --host 0.0.0.0 --port 8000
  # ou: make up
  ```

- Python 3.11+ com o pacote instalado (`pip install -e .`) e o SDK `mcp`
  (`pip install mcp`). O server também funciona **sem** o SDK `mcp`: há um
  fallback para o protocolo stdio JSON-RPC 2.0 implementado manualmente.

- URL da API configurável via env `CIP_API_BASE_URL` (default
  `http://localhost:8000`).

## Execução standalone

```powershell
python -m cip.mcp_server
```

O processo lê JSON-RPC 2.0 da stdin e responde na stdout (protocolo stdio).

## Configuração em editores

Use o arquivo `mcp-config.json` na raiz do projeto:

```json
{
  "mcpServers": {
    "cip": {
      "command": "python",
      "args": ["-m", "cip.mcp_server"],
      "env": {
        "CIP_API_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

### Cursor

1. `Settings > Cursor Settings > MCP`.
2. Clique em **Add new MCP server**.
3. Nome: `cip`. Type: `command`. Command:
   `python -m cip.mcp_server` (com o diretório do projeto no PATH/cwd correto,
   ou use o caminho absoluto do Python).
4. Alternativamente, aponte para o `mcp-config.json` do projeto.

### Kiro

1. No diretório do projeto, o Kiro consome `.mcp.json` ou o `mcp-config.json`.
2. Certifique-se de que o `command` aponte para um `python` que tenha o pacote
   `cip` e as dependências instaladas.

### Claude Desktop

1. Abra `~/.config/Claude/claude_desktop_config.json` (macOS/Linux) ou
   `%APPDATA%\Claude\claude_desktop_config.json` (Windows).
2. Adicione o bloco `cip` (conteúdo idêntico ao de `mcp-config.json`).
3. Reinicie o Claude Desktop.

## Exemplos de uso

### `cip_ask`

```text
Pergunta: "Como reduzir custo de um bucket S3 com dados frios?"
→ consulta RAG com fontes (resposta textual + **Fontes:** ao final).
```

### `cip_inspect`

```text
Payload (Terraform):
  resource "aws_s3_bucket" "data" { bucket = "my-data" }
→ lista de findings (title, severity, domain, description, recommendation, ...).
```

```text
Payload (Kubernetes):
  kind: Deployment ... securityContext: { privileged: true }
→ findings de segurança (critical), confiabilidade e operações.
```

### `cip_analyze`

```text
Pergunta: "Rever este Terraform de RDS para produção" + iac_payload inline
→ { summary, intent, clouds, findings (priorizados), sources, tools_used }.
```

## Decisões de design

- `cip_ask` / `cip_analyze` chamam a API REST via `httpx` para **não** importar
  a stack async do RAG/orquestrador no processo MCP (requisito do projeto).
- `cip_inspect` chama `cip.inspection.engine.inspect_payload()` diretamente
  (síncrono, sem dependências pesadas).
- Fallback stdio JSON-RPC 2.0 manual caso o SDK `mcp` não esteja instalado.

## Testes

```powershell
rtk python -m pytest tests/test_mcp_server.py -v
```
