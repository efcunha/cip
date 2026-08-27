"""Testes do Inspection Engine (Terraform + Kubernetes)."""

from cip.inspection.engine import detect_type, inspect_payload

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


def test_detect_terraform():
    assert detect_type(TF_INSECURE) == "terraform"


def test_detect_kubernetes():
    assert detect_type(K8S_INSECURE) == "kubernetes"


def test_terraform_findings_include_critical_sg():
    findings = inspect_payload(TF_INSECURE)
    severities = {f.severity for f in findings}
    assert "critical" in severities  # SG 0.0.0.0/0
    assert any("S3" in f.title for f in findings)  # bucket sem SSE


def test_kubernetes_findings_include_privileged():
    findings = inspect_payload(K8S_INSECURE)
    titles = " ".join(f.title.lower() for f in findings)
    assert "privilegiado" in titles
    assert any(f.severity == "critical" for f in findings)
