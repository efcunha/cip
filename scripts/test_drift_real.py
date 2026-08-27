"""Validação REAL do drift detector.

Simula mudança real forçando um hash diferente do esperado para uma URL.
Espera ver: changes=1 modified.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Adicionar diretório raiz para importar scripts como módulo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.monthly_reingest import detect_drift, get_baseline_hashes  # type: ignore


def main() -> int:
    # 1. Capturar baseline real
    baseline = get_baseline_hashes()
    test_url = "https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html"
    if test_url not in baseline:
        print(f"URL de teste não está no baseline: {test_url}")
        return 2

    real_baseline = baseline[test_url]
    print(f"Baseline real para {test_url[:60]}: {real_baseline[:30]}...")

    # 2. Monkey-patch fetch_url_hash para retornar hash diferente para a URL de teste
    import scripts.monthly_reingest as mreg

    original_fetch = mreg.fetch_url_hash

    def fake_fetch(url: str, timeout: int = 30) -> str | None:
        if url == test_url:
            return "MODIFIED_CONTENT_HASH_SIMULATED_FOR_TEST_1234567890"
        return original_fetch(url)

    mreg.fetch_url_hash = fake_fetch

    # 3. Rodar drift detection
    report = detect_drift("mvp")
    print(f"\n=== RESULTADO ===")
    print(f"Changes: {len(report.changes)}")
    for c in report.changes:
        print(f"  [{c.status}] {c.cloud}/{c.service}: {c.url[:60]}")
        if c.old_hash:
            print(f"    old={c.old_hash[:30]}")
        if c.new_hash:
            print(f"    new={c.new_hash[:30]}")

    # 4. Restaurar
    mreg.fetch_url_hash = original_fetch

    # 5. Validar
    modified = [c for c in report.changes if c.status == "modified" and c.url == test_url]
    if modified:
        print(f"\n[OK] Drift detector pegou a mudanca simulada!")
        return 0
    else:
        print(f"\n[FALHA] Drift detector NAO detectou a mudanca simulada!")
        return 1


if __name__ == "__main__":
    sys.exit(main())