"""End-to-end test do /analyze com payload K8s inseguro."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cip.agents.orchestrator import get_orchestrator


K8S_PAYLOAD = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-prod
  namespace: production
spec:
  template:
    spec:
      hostNetwork: true
      containers:
        - name: api
          image: myrepo/api:latest
          resources:
            limits:
              cpu: 500m
              memory: 512Mi
        - name: worker
          image: myrepo/worker:latest
          securityContext:
            privileged: true
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: dangerous-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
  - kind: ServiceAccount
    name: ci-runner
    namespace: ci
"""


async def main() -> None:
    orch = get_orchestrator()
    result = await orch.handle(
        question="Analise essa config Kubernetes",
        iac_payload=K8S_PAYLOAD,
    )
    print(f"Plan intent: {result.plan.intent.value if result.plan else None}")
    print(f"Specialists: {result.plan.specialists if result.plan else []}")
    print(f"Findings: {len(result.findings)}")
    print()
    print("Findings:")
    for f in result.prioritized_findings():
        print(f"  [{f.severity:>8}] {f.domain:<13} {f.title}")


if __name__ == "__main__":
    asyncio.run(main())