"""MCP Server standalone para o Cloud Intelligence Platform (CIP).

Expõe o CIP como ferramenta MCP (Model Context Protocol) para agentes externos
(Cursor, Kiro, Claude Desktop, etc.) via stdio (JSON-RPC 2.0).

Ferramentas:
- cip_ask      → RAG puro (chama POST /ask      da API REST local)
- cip_inspect  → Inspection Engine (chama inspect_payload() diretamente, síncrono)
- cip_analyze  → Orquestrador (chama POST /analyze da API REST local)

As tools cip_ask e cip_analyze delegam para a API REST via httpx para NÃO importar
toda a stack async do RAG/orquestrador no processo MCP. A cip_inspect usa o
Inspection Engine diretamente (síncrono, sem dependências pesadas).

Execução standalone:
    python -m cip.mcp_server

Requisito: API CIP rodando em http://localhost:8000 (para cip_ask e cip_analyze).

O SDK ``mcp`` (FastMCP) é usado quando disponível; caso contrário, cai para uma
implementação mínima do protocolo stdio JSON-RPC 2.0 (sem dependência externa).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# URL base da API CIP (sobrescrevível via env CIP_API_BASE_URL).
_CIP_API_BASE_URL = os.environ.get("CIP_API_BASE_URL", "http://localhost:8000")


# ─────────────────────────────────────────────────────────────────────────
# Implementação core (sem dependência do SDK MCP)
# ─────────────────────────────────────────────────────────────────────────


def _call_http(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST na API CIP local via httpx. Lança RuntimeError com mensagem clara."""
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - httpx é dependência do projeto
        raise RuntimeError("httpx não está instalado. Instale com: pip install httpx") from exc

    url = f"{_CIP_API_BASE_URL}{path}"
    try:
        resp = httpx.post(url, json=payload, timeout=120.0)
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Não foi possível conectar à API CIP em {_CIP_API_BASE_URL}. "
            "Verifique se ela está rodando (ex.: make up / uvicorn cip.api.app:app)."
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Erro HTTP ao chamar CIP API ({url}): {exc}") from exc

    if resp.status_code >= 400:
        raise RuntimeError(f"CIP API retornou {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def _apply_inspect(payload: str) -> list[dict[str, Any]]:
    """Inspection Engine direto (síncrono)."""
    if not payload or not payload.strip():
        raise ValueError("payload é obrigatório e não pode ser vazio.")
    from cip.inspection.engine import inspect_payload

    findings = inspect_payload(payload)
    return [
        {
            "title": f.title,
            "severity": f.severity,
            "domain": f.domain,
            "description": f.description,
            "recommendation": f.recommendation,
            "financial_impact_usd": f.financial_impact_usd,
            "effort": f.effort,
            "references": f.references,
        }
        for f in findings
    ]


def _format_sources(sources: list[dict[str, Any]]) -> str:
    """Formata fontes (SourceOut) em texto citável."""
    if not sources:
        return ""
    lines = ["\n\n**Fontes:**"]
    for s in sources:
        title = s.get("title") or "documento"
        url = s.get("url")
        cloud = s.get("cloud")
        service = s.get("service")
        label = title
        if cloud and service:
            label = f"{title} ({cloud}/{service})"
        elif cloud:
            label = f"{title} ({cloud})"
        lines.append(f"- {label}" + (f" — {url}" if url else ""))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# Handlers das ferramentas
# ─────────────────────────────────────────────────────────────────────────


def cip_ask_impl(question: str, cloud: str | None = None, service: str | None = None) -> str:
    """Tool cip_ask: resposta textual com citações de fontes."""
    req: dict[str, Any] = {"question": question}
    if cloud:
        req["cloud"] = cloud
    if service:
        req["service"] = service

    data = _call_http("/ask", req)
    answer = data.get("answer", "")
    sources = data.get("sources", [])
    return answer + _format_sources(sources)


def cip_inspect_impl(payload: str) -> list[dict[str, Any]]:
    """Tool cip_inspect: lista de findings."""
    return _apply_inspect(payload)


def cip_analyze_impl(
    question: str,
    cloud: str | None = None,
    iac_payload: str | None = None,
) -> dict[str, Any]:
    """Tool cip_analyze: summary + findings + sources."""
    req: dict[str, Any] = {"question": question}
    if cloud:
        req["cloud"] = cloud
    if iac_payload:
        req["iac_payload"] = iac_payload

    data = _call_http("/analyze", req)
    return {
        "summary": data.get("summary", ""),
        "intent": data.get("intent"),
        "clouds": data.get("clouds", []),
        "findings": data.get("findings", []),
        "sources": data.get("sources", []),
        "tools_used": data.get("tools_used", []),
    }


# ─────────────────────────────────────────────────────────────────────────
# SDK MCP (preferencial)
# ─────────────────────────────────────────────────────────────────────────


def _build_fastmcp_server() -> Any:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "cip",
        instructions=(
            "Ferramentas do Cloud Intelligence Platform (CIP): LLM especialista em "
            "infraestrutura cloud AWS/GCP/Azure. Use cip_ask para perguntas conceituais "
            "ancoradas em documentação oficial, cip_inspect para analisar código Terraform "
            "ou manifestos Kubernetes, e cip_analyze para cenários que exigem análise "
            "aprofundada (RAG + tools + inspeção)."
        ),
    )

    @mcp.tool()
    def cip_ask(
        question: str,
        cloud: str | None = None,
        service: str | None = None,
    ) -> str:
        """Consulta o CIP sobre arquitetura e boas práticas das 3 clouds (AWS/GCP/Azure).

        Respostas ancoradas em documentação oficial.

        Args:
            question: Pergunta sobre cloud architecture.
            cloud: Filtrar por "aws", "gcp" ou "azure".
            service: Filtrar por serviço específico (ex.: "s3", "ec2", "gcs").
        """
        return cip_ask_impl(question, cloud=cloud, service=service)

    @mcp.tool()
    def cip_inspect(payload: str) -> list[dict[str, Any]]:
        """Analisa código Terraform (.tf) ou manifesto Kubernetes (YAML).

        Retorna findings de segurança, custo e boas práticas.

        Args:
            payload: Conteúdo do arquivo .tf ou manifest YAML a inspecionar.
        """
        return cip_inspect_impl(payload)

    @mcp.tool()
    def cip_analyze(
        question: str,
        cloud: str | None = None,
        iac_payload: str | None = None,
    ) -> dict[str, Any]:
        """Análise aprofundada de cenário cloud com RAG + tools + inspeção.

        Retorna resumo, findings priorizados e fontes.

        Args:
            question: Pergunta ou cenário a analisar.
            cloud: Cloud alvo ("aws", "gcp" ou "azure").
            iac_payload: Código Terraform/K8s para inspeção inline.
        """
        return cip_analyze_impl(question, cloud=cloud, iac_payload=iac_payload)

    return mcp


def _run_fastmcp() -> None:
    mcp = _build_fastmcp_server()
    mcp.run()


# ─────────────────────────────────────────────────────────────────────────
# Fallback: protocolo stdio JSON-RPC 2.0 manual (sem SDK MCP)
# ─────────────────────────────────────────────────────────────────────────

_TOOLS_SPEC = [
    {
        "name": "cip_ask",
        "description": (
            "Consulta o CIP sobre arquitetura e boas práticas das 3 clouds "
            "(AWS/GCP/Azure). Respostas ancoradas em documentação oficial."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Pergunta sobre cloud architecture."},
                "cloud": {
                    "type": "string",
                    "description": 'Filtrar por "aws", "gcp" ou "azure".',
                },
                "service": {"type": "string", "description": "Filtrar por serviço específico."},
            },
            "required": ["question"],
        },
    },
    {
        "name": "cip_inspect",
        "description": (
            "Analisa código Terraform (.tf) ou manifesto Kubernetes (YAML) e retorna "
            "findings de segurança, custo e boas práticas."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "string",
                    "description": "Conteúdo do arquivo .tf ou manifest YAML.",
                },
            },
            "required": ["payload"],
        },
    },
    {
        "name": "cip_analyze",
        "description": (
            "Análise aprofundada de cenário cloud com RAG + tools + inspeção. Retorna "
            "resumo, findings priorizados e fontes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Pergunta ou cenário a analisar.",
                },
                "cloud": {"type": "string", "description": "Cloud alvo."},
                "iac_payload": {
                    "type": "string",
                    "description": "Código Terraform/K8s para inspeção inline.",
                },
            },
            "required": ["question"],
        },
    },
]


def _text_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _json_result(obj: Any) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False, indent=2)}],
        "isError": False,
    }


def _error_result(msg: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": f"Erro: {msg}"}],
        "isError": True,
    }


def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "cip_ask":
        question = arguments.get("question")
        if not question:
            return _error_result("Parâmetro 'question' é obrigatório e não pode ser vazio.")
        return _text_result(
            cip_ask_impl(
                str(question),
                cloud=arguments.get("cloud"),
                service=arguments.get("service"),
            )
        )

    if name == "cip_inspect":
        payload = arguments.get("payload")
        if not payload:
            return _error_result("Parâmetro 'payload' é obrigatório e não pode ser vazio.")
        findings = cip_inspect_impl(str(payload))
        return _json_result(findings)

    if name == "cip_analyze":
        question = arguments.get("question")
        if not question:
            return _error_result("Parâmetro 'question' é obrigatório e não pode ser vazio.")
        return _json_result(
            cip_analyze_impl(
                str(question),
                cloud=arguments.get("cloud"),
                iac_payload=arguments.get("iac_payload"),
            )
        )

    return _error_result(f"Tool desconhecida: {name!r}")


def _run_stdlib() -> None:
    """Loop stdio JSON-RPC 2.0 mínimo (initialize, tools/list, tools/call, ping)."""
    stdin = sys.stdin
    stdout = sys.stdout

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        response: dict[str, Any] | None = None

        if method == "initialize":
            response = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cip", "version": "0.2.0"},
            }
        elif method == "notifications/initialized":
            continue  # notification, sem resposta
        elif method == "tools/list":
            response = {"tools": _TOOLS_SPEC}
        elif method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments") or {}
            result = _dispatch_tool(name, arguments)
            response = {"content": result["content"], "isError": result["isError"]}
        elif method == "ping":
            response = {}
        else:
            # Método desconhecido: erro -32601
            payload = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Método não encontrado: {method}"},
            }
            stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            stdout.flush()
            continue

        payload = {"jsonrpc": "2.0", "id": msg_id, "result": response}
        stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stdout.flush()


# ─────────────────────────────────────────────────────────────────────────
# Ponto de entrada
# ─────────────────────────────────────────────────────────────────────────


def main() -> None:
    try:
        import mcp.server.fastmcp  # noqa: F401
    except ImportError:
        _run_stdlib()
    else:
        _run_fastmcp()


if __name__ == "__main__":
    main()
