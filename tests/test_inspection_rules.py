"""Testes completos do Inspection Engine: 7 regras Terraform + 7 regras Kubernetes.

Cada regra tem pelo menos um cenário positivo (deve detectar) e negativo (não deve detectar).

Uso:
    pytest tests/test_inspection_rules.py -v
"""

from __future__ import annotations

import pytest

from cip.inspection.engine import detect_type, inspect_payload
from cip.inspection.terraform import analyze as analyze_tf
from cip.inspection.kubernetes import analyze as analyze_k8s


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _titles(findings) -> list[str]:
    return [f.title for f in findings]


def _by_severity(findings, severity: str) -> list:
    return [f for f in findings if f.severity == severity]


# ─────────────────────────────────────────────────────────────────────────
# Terraform — 7 regras
# ─────────────────────────────────────────────────────────────────────────


class TestTerraformRuleT1_S3NoEncryption:
    """T1 — S3 sem server-side encryption."""

    TF_T1_INSECURE = """
resource "aws_s3_bucket" "data" {
  bucket = "my-data"
}
"""
    TF_T1_SECURE = """
resource "aws_s3_bucket" "data" {
  bucket = "my-data"
  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "AES256"
      }
    }
  }
}
"""

    def test_detects_s3_without_sse(self) -> None:
        findings = analyze_tf(self.TF_T1_INSECURE)
        assert any("S3" in f.title and "criptografia" in f.title for f in findings)
        assert any(f.severity == "high" for f in findings)

    def test_does_not_flag_s3_with_sse(self) -> None:
        findings = analyze_tf(self.TF_T1_SECURE)
        s3_findings = [f for f in findings if "S3" in f.title and "criptografia" in f.title]
        assert len(s3_findings) == 0


class TestTerraformRuleT2_SecurityGroupPublic:
    """T2 — Security Group com ingress 0.0.0.0/0."""

    TF_T2_INSECURE = """
resource "aws_security_group" "web" {
  ingress {
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
"""
    TF_T2_SECURE = """
resource "aws_security_group" "web" {
  ingress {
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }
}
"""

    def test_detects_sg_with_internet_open(self) -> None:
        findings = analyze_tf(self.TF_T2_INSECURE)
        assert any(
            f.severity == "critical" and "Security group" in f.title and "internet" in f.title
            for f in findings
        )

    def test_does_not_flag_sg_with_private_cidr(self) -> None:
        findings = analyze_tf(self.TF_T2_SECURE)
        sg_findings = [f for f in findings if "Security group" in f.title]
        assert len(sg_findings) == 0


class TestTerraformRuleT3_RDSNoEncryption:
    """T3 — RDS sem storage_encrypted."""

    TF_T3_INSECURE = """
resource "aws_db_instance" "primary" {
  engine = "postgres"
  instance_class = "db.t3.medium"
  allocated_storage = 100
}
"""
    TF_T3_SECURE = """
resource "aws_db_instance" "primary" {
  engine = "postgres"
  instance_class = "db.t3.medium"
  allocated_storage = 100
  storage_encrypted = true
}
"""

    def test_detects_rds_without_encryption(self) -> None:
        findings = analyze_tf(self.TF_T3_INSECURE)
        rds_findings = [f for f in findings if "RDS" in f.title and "criptografia" in f.title]
        assert len(rds_findings) == 1
        assert rds_findings[0].severity == "high"

    def test_does_not_flag_rds_with_encryption(self) -> None:
        findings = analyze_tf(self.TF_T3_SECURE)
        rds_findings = [f for f in findings if "RDS" in f.title and "criptografia" in f.title]
        assert len(rds_findings) == 0


class TestTerraformRuleT4_RDSNoMultiAZ:
    """T4 — RDS em produção sem Multi-AZ."""

    TF_T4_INSECURE = """
resource "aws_db_instance" "primary" {
  engine = "postgres"
  instance_class = "db.t3.medium"
  allocated_storage = 100
  tags = {
    Environment = "prod"
  }
}
"""
    TF_T4_SECURE = """
resource "aws_db_instance" "primary" {
  engine = "postgres"
  instance_class = "db.t3.medium"
  allocated_storage = 100
  multi_az = true
  tags = {
    Environment = "prod"
  }
}
"""
    TF_T4_DEV_OK = """
resource "aws_db_instance" "primary" {
  engine = "postgres"
  instance_class = "db.t3.medium"
  allocated_storage = 100
  tags = {
    Environment = "dev"
  }
}
"""

    def test_detects_prod_rds_without_multi_az(self) -> None:
        findings = analyze_tf(self.TF_T4_INSECURE)
        assert any(
            "Multi-AZ" in f.title and f.severity == "high" for f in findings
        )

    def test_does_not_flag_rds_with_multi_az(self) -> None:
        findings = analyze_tf(self.TF_T4_SECURE)
        multi_az_findings = [f for f in findings if "Multi-AZ" in f.title]
        assert len(multi_az_findings) == 0

    def test_does_not_flag_non_prod_rds(self) -> None:
        findings = analyze_tf(self.TF_T4_DEV_OK)
        multi_az_findings = [f for f in findings if "Multi-AZ" in f.title]
        assert len(multi_az_findings) == 0


class TestTerraformRuleT5_NoTags:
    """T5 — Compute sem tags/labels."""

    TF_T5_INSECURE = """
resource "aws_instance" "web" {
  ami = "ami-12345"
  instance_type = "t3.small"
}
"""
    TF_T5_SECURE = """
resource "aws_instance" "web" {
  ami = "ami-12345"
  instance_type = "t3.small"
  tags = {
    Name = "web"
    Environment = "prod"
    Owner = "team-a"
  }
}
"""

    def test_detects_compute_without_tags(self) -> None:
        findings = analyze_tf(self.TF_T5_INSECURE)
        tag_findings = [f for f in findings if "tags" in f.title.lower() or "labels" in f.title.lower()]
        assert len(tag_findings) == 1
        assert tag_findings[0].domain == "finops"
        assert tag_findings[0].financial_impact_usd is not None

    def test_does_not_flag_compute_with_tags(self) -> None:
        findings = analyze_tf(self.TF_T5_SECURE)
        tag_findings = [f for f in findings if "tags" in f.title.lower()]
        assert len(tag_findings) == 0


class TestTerraformRuleT6_OversizedInstance:
    """T6 — Instância oversized (m5/c5/r5/x families)."""

    TF_T6_INSECURE = """
resource "aws_instance" "web" {
  ami = "ami-12345"
  instance_type = "m5.xlarge"
}
"""
    TF_T6_SECURE = """
resource "aws_instance" "web" {
  ami = "ami-12345"
  instance_type = "t3.small"
}
"""

    def test_detects_large_instance_without_justification(self) -> None:
        findings = analyze_tf(self.TF_T6_INSECURE)
        oversized = [f for f in findings if "oversized" in f.title.lower()]
        assert len(oversized) == 1
        assert oversized[0].domain == "finops"
        assert oversized[0].financial_impact_usd and oversized[0].financial_impact_usd > 0

    def test_does_not_flag_small_instance(self) -> None:
        findings = analyze_tf(self.TF_T6_SECURE)
        oversized = [f for f in findings if "oversized" in f.title.lower()]
        assert len(oversized) == 0


class TestTerraformRuleT7_NoPreventDestroy:
    """T7 — Recursos críticos sem lifecycle.prevent_destroy."""

    TF_T7_INSECURE = """
resource "aws_s3_bucket" "data" {
  bucket = "critical-data"
}
"""
    TF_T7_SECURE = """
resource "aws_s3_bucket" "data" {
  bucket = "critical-data"
  lifecycle {
    prevent_destroy = true
  }
}
"""

    def test_detects_critical_resource_without_prevent_destroy(self) -> None:
        findings = analyze_tf(self.TF_T7_INSECURE)
        prevent = [f for f in findings if "prevent_destroy" in f.title.lower()]
        assert len(prevent) >= 1
        assert any(f.domain == "operations" for f in prevent)

    def test_does_not_flag_resource_with_prevent_destroy(self) -> None:
        findings = analyze_tf(self.TF_T7_SECURE)
        prevent = [f for f in findings if "prevent_destroy" in f.title.lower()]
        assert len(prevent) == 0


# ─────────────────────────────────────────────────────────────────────────
# Kubernetes — 7 regras
# ─────────────────────────────────────────────────────────────────────────


class TestK8sRuleK1_Privileged:
    """K1 — Container privilegiado."""

    K8S_K1_INSECURE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myrepo/api:1.0
          securityContext:
            privileged: true
"""
    K8S_K1_SECURE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myrepo/api:1.0
          securityContext:
            privileged: false
"""

    def test_detects_privileged_container(self) -> None:
        findings = analyze_k8s(self.K8S_K1_INSECURE)
        assert any(
            f.severity == "critical" and "privilegiado" in f.title.lower() for f in findings
        )

    def test_does_not_flag_non_privileged_container(self) -> None:
        findings = analyze_k8s(self.K8S_K1_SECURE)
        priv = [f for f in findings if "privilegiado" in f.title.lower()]
        assert len(priv) == 0


class TestK8sRuleK2_HostNetwork:
    """K2 — Workload usando hostNetwork."""

    K8S_K2_INSECURE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      hostNetwork: true
      containers:
        - name: api
          image: myrepo/api:1.0
"""

    def test_detects_host_network(self) -> None:
        findings = analyze_k8s(self.K8S_K2_INSECURE)
        assert any(
            f.severity == "high" and "hostnetwork" in f.title.lower() for f in findings
        )


class TestK8sRuleK3_BroadRBAC:
    """K3 — RBAC excessivamente permissivo (ClusterRole com wildcard/admin)."""

    K8S_K3_INSECURE = """
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: dangerous
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
  - kind: ServiceAccount
    name: ci-runner
    namespace: ci
"""
    K8S_K3_SECURE = """
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: safe
  namespace: app
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: view
subjects:
  - kind: ServiceAccount
    name: app-sa
    namespace: app
"""

    def test_detects_cluster_admin_binding(self) -> None:
        findings = analyze_k8s(self.K8S_K3_INSECURE)
        rbac_findings = [f for f in findings if "RBAC" in f.title or "excessivamente" in f.title.lower()]
        assert len(rbac_findings) == 1
        assert rbac_findings[0].severity == "critical"

    def test_does_not_flag_safe_role_binding(self) -> None:
        findings = analyze_k8s(self.K8S_K3_SECURE)
        rbac_findings = [f for f in findings if "RBAC" in f.title]
        assert len(rbac_findings) == 0


class TestK8sRuleK4_NoRunAsNonRoot:
    """K4 — Container sem runAsNonRoot."""

    K8S_K4_INSECURE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myrepo/api:1.0
          resources:
            limits:
              cpu: 100m
              memory: 128Mi
"""
    K8S_K4_SECURE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myrepo/api:1.0
          securityContext:
            runAsNonRoot: true
"""

    def test_detects_container_without_run_as_non_root(self) -> None:
        findings = analyze_k8s(self.K8S_K4_INSECURE)
        rnr = [f for f in findings if "runasnonroot" in f.title.lower()]
        assert len(rnr) == 1
        assert rnr[0].severity == "medium"

    def test_does_not_flag_container_with_run_as_non_root(self) -> None:
        findings = analyze_k8s(self.K8S_K4_SECURE)
        rnr = [f for f in findings if "runasnonroot" in f.title.lower()]
        assert len(rnr) == 0


class TestK8sRuleK5_NoResourceLimits:
    """K5 — Container sem resource limits."""

    K8S_K5_INSECURE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myrepo/api:1.0
"""
    K8S_K5_SECURE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myrepo/api:1.0
          resources:
            limits:
              cpu: 200m
              memory: 256Mi
            requests:
              cpu: 100m
              memory: 128Mi
"""

    def test_detects_container_without_limits(self) -> None:
        findings = analyze_k8s(self.K8S_K5_INSECURE)
        limits = [f for f in findings if "resource limits" in f.title.lower()]
        assert len(limits) == 1
        assert limits[0].domain == "reliability"

    def test_does_not_flag_container_with_limits(self) -> None:
        findings = analyze_k8s(self.K8S_K5_SECURE)
        limits = [f for f in findings if "resource limits" in f.title.lower()]
        assert len(limits) == 0


class TestK8sRuleK6_NoProbes:
    """K6 — Workload sem liveness/readiness probes."""

    K8S_K6_INSECURE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myrepo/api:1.0
"""
    K8S_K6_SECURE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myrepo/api:1.0
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 30
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
"""

    def test_detects_workload_without_probes(self) -> None:
        findings = analyze_k8s(self.K8S_K6_INSECURE)
        probes = [f for f in findings if "probes" in f.title.lower()]
        assert len(probes) == 1
        assert probes[0].domain == "reliability"

    def test_does_not_flag_workload_with_probes(self) -> None:
        findings = analyze_k8s(self.K8S_K6_SECURE)
        probes = [f for f in findings if "probes" in f.title.lower()]
        assert len(probes) == 0


class TestK8sRuleK7_LatestImage:
    """K7 — Imagem sem tag fixa (:latest ou sem tag)."""

    K8S_K7_INSECURE_LATEST = """
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
"""
    K8S_K7_INSECURE_NO_TAG = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myrepo/api
"""
    K8S_K7_SECURE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myrepo/api:1.2.3
"""

    def test_detects_latest_tag(self) -> None:
        findings = analyze_k8s(self.K8S_K7_INSECURE_LATEST)
        latest = [f for f in findings if "tag fixa" in f.title.lower()]
        assert len(latest) == 1
        assert "latest" in latest[0].title.lower()

    def test_detects_no_tag(self) -> None:
        findings = analyze_k8s(self.K8S_K7_INSECURE_NO_TAG)
        latest = [f for f in findings if "tag fixa" in f.title.lower()]
        assert len(latest) == 1

    def test_does_not_flag_fixed_tag(self) -> None:
        findings = analyze_k8s(self.K8S_K7_SECURE)
        latest = [f for f in findings if "tag fixa" in f.title.lower()]
        assert len(latest) == 0


# ─────────────────────────────────────────────────────────────────────────
# Integration tests
# ─────────────────────────────────────────────────────────────────────────


class TestInspectionIntegration:
    """Testes de integração end-to-end."""

    def test_inspect_payload_dispatches_terraform(self) -> None:
        tf_payload = 'resource "aws_s3_bucket" "x" { bucket = "x" }'
        findings = inspect_payload(tf_payload)
        assert len(findings) > 0
        assert any("S3" in f.title for f in findings)

    def test_inspect_payload_dispatches_kubernetes(self) -> None:
        k8s_payload = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: x
spec:
  template:
    spec:
      containers:
        - name: c
          image: myrepo/c:1
          securityContext:
            privileged: true
"""
        findings = inspect_payload(k8s_payload)
        assert any("privilegiado" in f.title.lower() for f in findings)

    def test_all_findings_have_required_fields(self) -> None:
        """Todos os findings devem ter title, severity, domain, description, recommendation."""
        payload = """
resource "aws_s3_bucket" "x" { bucket = "x" }

resource "aws_security_group" "web" {
  ingress {
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "x" {
  ami = "ami-x"
  instance_type = "m5.xlarge"
}
"""
        findings = inspect_payload(payload)
        for f in findings:
            assert f.title
            assert f.severity in ("critical", "high", "medium", "low")
            assert f.domain in ("finops", "security", "reliability", "performance", "operations")
            assert f.description
            assert f.recommendation
            assert isinstance(f.references, list)

    def test_severity_distribution_reasonable(self) -> None:
        """Em payload com várias violações, deve haver mix de severidades."""
        payload = """
resource "aws_s3_bucket" "x" { bucket = "x" }
resource "aws_security_group" "web" {
  ingress {
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
"""
        findings = analyze_tf(payload)
        severities = {f.severity for f in findings}
        # Deve ter critical (SG) e high (S3)
        assert "critical" in severities
        assert "high" in severities