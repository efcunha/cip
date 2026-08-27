"""Debug: parse TF_INSECURE e ver estrutura."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cip.inspection.terraform import _parse, analyze

payload = '''
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
'''
parsed = _parse(payload)
print("=== PARSED ===")
print(json.dumps(parsed, indent=2, default=str))

print("\n=== FINDINGS ===")
findings = analyze(payload)
for f in findings:
    print(f"  [{f.severity:>8}] {f.title}")