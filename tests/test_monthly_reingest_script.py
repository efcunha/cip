"""Testes de regressão do script de reingestão mensal (scripts/monthly_reingest.py).

Valida:
- main() grava o relatório de drift. Regressão do NameError: o script chamava
  save_report(), que não existe (a função é save_report_), então morria ANTES
  de gravar o relatório e o drift detectado era perdido;
- trigger_reingestion() propaga o escopo. Com "full" hardcoded, uma execução
  --scope mvp expandia o corpus para toda a documentação de serviços;
- known_catalog_urls() cobre o escopo monitorado (evita "removed" falso).

Uso:
    pytest tests/test_monthly_reingest_script.py -v
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "monthly_reingest.py"


def _load_script():
    """Importa o script pelo caminho (não é um pacote do projeto)."""
    spec = importlib.util.spec_from_file_location("monthly_reingest", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["monthly_reingest"] = module
    spec.loader.exec_module(module)
    return module


def test_main_grava_o_relatorio_de_drift(tmp_path, monkeypatch):
    module = _load_script()
    report = module.DriftReport(
        scope="mvp",
        drift_detected=True,
        changes=[
            module.DriftEntry(
                cloud="aws", service="well-architected", url="https://x/a", status="modified"
            )
        ],
    )
    monkeypatch.setattr(module, "detect_drift", lambda scope: report)
    out = tmp_path / "ingest_drift_report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["monthly_reingest.py", "--detect-only", "--report-json", str(out)],
    )
    rc = module.main()
    assert rc == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["drift_detected"] is True
    assert data["changes"][0]["status"] == "modified"


def test_trigger_reingestion_propaga_o_escopo(monkeypatch):
    module = _load_script()
    calls: dict = {}

    def fake_run(cmd, cwd=None):
        calls["cmd"] = cmd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.trigger_reingestion("mvp") == 0
    cmd = calls["cmd"]
    assert "--scope" in cmd
    assert cmd[cmd.index("--scope") + 1] == "mvp"


def test_known_catalog_urls_cobre_o_escopo_monitorado():
    module = _load_script()
    known = module.known_catalog_urls()
    monitored = {
        url for entry in module.load_sources("mvp") for url in entry.get("urls", [])
    }
    assert monitored
    assert monitored <= known
