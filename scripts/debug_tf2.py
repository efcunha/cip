"""Debug: testar os 3 casos que falham."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cip.inspection.terraform import _parse

print("=" * 70)
print("T4 — RDS com tags Environment=prod")
print("=" * 70)
payload_t4 = """
resource "aws_db_instance" "primary" {
  engine = "postgres"
  instance_class = "db.t3.medium"
  allocated_storage = 100
  tags = {
    Environment = "prod"
  }
}
"""
parsed = _parse(payload_t4)
print(json.dumps(parsed, indent=2, default=str))

print("\n" + "=" * 70)
print("T6 — aws_instance m5.xlarge")
print("=" * 70)
payload_t6 = """
resource "aws_instance" "web" {
  ami = "ami-12345"
  instance_type = "m5.xlarge"
}
"""
parsed = _parse(payload_t6)
print(json.dumps(parsed, indent=2, default=str))

print("\n" + "=" * 70)
print("T7 — S3 com lifecycle.prevent_destroy=true")
print("=" * 70)
payload_t7 = """
resource "aws_s3_bucket" "data" {
  bucket = "critical-data"
  lifecycle {
    prevent_destroy = true
  }
}
"""
parsed = _parse(payload_t7)
print(json.dumps(parsed, indent=2, default=str))