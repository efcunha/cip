"""End-to-end test do /analyze com payload IaC inseguro."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cip.agents.orchestrator import get_orchestrator


IAC_PAYLOAD = """
resource "aws_s3_bucket" "data" {
  bucket = "critical-data"
}

resource "aws_security_group" "web" {
  ingress {
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "web" {
  ami = "ami-12345"
  instance_type = "m5.xlarge"
}

resource "aws_db_instance" "primary" {
  engine = "postgres"
  instance_class = "db.t3.medium"
  allocated_storage = 100
  tags = {
    Environment = "prod"
  }
}
"""


async def main() -> None:
    orch = get_orchestrator()
    result = await orch.handle(
        question="Analise essa infraestrutura Terraform e liste problemas",
        cloud='aws',
        iac_payload=IAC_PAYLOAD,
    )
    print(f"Summary: {result.summary[:200]}")
    print(f"Findings: {len(result.findings)}")
    print(f"Plan intent: {result.plan.intent.value if result.plan else None}")
    print()
    print("Findings priorizados:")
    for f in result.prioritized_findings():
        impact = f"${f.financial_impact_usd:.0f}" if f.financial_impact_usd else "n/a"
        print(f"  [{f.severity:>8}] {f.domain:<13} impact={impact:>8}  {f.title}")


if __name__ == "__main__":
    asyncio.run(main())