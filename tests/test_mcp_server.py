"""Testes do MCP Server do CIP.

Cobrem:
- cip_inspect com payload Terraform inseguro → retorna findings
- cip_inspect com payload K8s inseguro → retorna findings
- Schema das 3 tools (nomes, parâmetros, tipos, required)
"""

from __future__ import annotations

import cip.mcp_server as ms

TF_INSECURE = """
resource "aws_s3_bucket" "data" {
  bucket = "my-data"
}
resource "aws_security_group" "web" {
  ingress {
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
"""

K8S_INSECURE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myrepo/api:latest
          securityContext:
            privileged: true
"""


# ─────────────────────────────────────────────────────────────────────────
# cip_inspect — Terraform
# ─────────────────────────────────────────────────────────────────────────


def test_cip_inspect_terraform_returns_findings():
    findings = ms.cip_inspect_impl(TF_INSECURE)
    assert isinstance(findings, list)
    assert len(findings) > 0

    # Cada finding tem os campos esperados
    for f in findings:
        assert set(f) >= {
            "title",
            "severity",
            "domain",
            "description",
            "recommendation",
        }

    severities = {f["severity"] for f in findings}
    assert "critical" in severities  # SG 0.0.0.0/0
    assert any("S3" in f["title"] for f in findings)  # bucket sem SSE


def test_cip_inspect_terraform_security_group_detected():
    findings = ms.cip_inspect_impl(TF_INSECURE)
    titles = " ".join(f["title"] for f in findings)
    assert "security group" in titles.lower() or "0.0.0.0" in titles.lower()


# ─────────────────────────────────────────────────────────────────────────
# cip_inspect — Kubernetes
# ─────────────────────────────────────────────────────────────────────────


def test_cip_inspect_kubernetes_returns_findings():
    findings = ms.cip_inspect_impl(K8S_INSECURE)
    assert isinstance(findings, list)
    assert len(findings) > 0

    severities = {f["severity"] for f in findings}
    assert "critical" in severities  # privileged=true


def test_cip_inspect_kubernetes_privileged_detected():
    findings = ms.cip_inspect_impl(K8S_INSECURE)
    titles = " ".join(f["title"].lower() for f in findings)
    assert "privilegiado" in titles


# ─────────────────────────────────────────────────────────────────────────
# Schema das 3 tools
# ─────────────────────────────────────────────────────────────────────────


def test_tools_spec_has_exactly_three_tools():
    names = {t["name"] for t in ms._TOOLS_SPEC}
    assert names == {"cip_ask", "cip_inspect", "cip_analyze"}
    assert len(ms._TOOLS_SPEC) == 3


def test_tools_spec_names_and_order():
    names = [t["name"] for t in ms._TOOLS_SPEC]
    assert names == ["cip_ask", "cip_inspect", "cip_analyze"]


def test_cip_ask_schema():
    tool = next(t for t in ms._TOOLS_SPEC if t["name"] == "cip_ask")
    props = tool["inputSchema"]["properties"]
    assert tool["inputSchema"]["required"] == ["question"]
    assert props["question"]["type"] == "string"
    assert props["cloud"]["type"] == "string"
    assert props["service"]["type"] == "string"
    assert "arquitetura" in tool["description"].lower()


def test_cip_inspect_schema():
    tool = next(t for t in ms._TOOLS_SPEC if t["name"] == "cip_inspect")
    props = tool["inputSchema"]["properties"]
    assert tool["inputSchema"]["required"] == ["payload"]
    assert props["payload"]["type"] == "string"
    assert "terraform" in tool["description"].lower()


def test_cip_analyze_schema():
    tool = next(t for t in ms._TOOLS_SPEC if t["name"] == "cip_analyze")
    props = tool["inputSchema"]["properties"]
    assert tool["inputSchema"]["required"] == ["question"]
    assert props["question"]["type"] == "string"
    assert props["cloud"]["type"] == "string"
    assert props["iac_payload"]["type"] == "string"


def test_fastmcp_server_tool_annotations():
    """Valida o schema via SDK FastMCP (Annotated/type hints) quando disponível."""
    try:
        import mcp.server.fastmcp  # noqa: F401
    except ImportError:
        import pytest

        pytest.skip("SDK mcp não disponível")

    import asyncio

    mcp = ms._build_fastmcp_server()
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {"cip_ask", "cip_inspect", "cip_analyze"}


def test_inspect_empty_payload_raises():
    import pytest

    with pytest.raises(ValueError):
        ms.cip_inspect_impl("   ")
