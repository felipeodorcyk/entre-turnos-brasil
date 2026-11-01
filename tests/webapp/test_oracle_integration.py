"""Integração: oráculo independente sobre os dados reais do projeto."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = [
    ROOT / "data/analytics/metrics_municipio.csv",
    ROOT / "data/analytics/socio/painel_municipal_socio.parquet",
    ROOT / "data/raw/ibge_setores/municipio_tse_ibge.zip",
    ROOT / "reports/analysis/evidencias_nacional/referencia_m1_m2_uf.csv",
]


@pytest.mark.integration
def test_oracle_real_data(tmp_path: Path) -> None:
    for path in REQUIRED:
        if not path.exists():
            pytest.skip(f"entrada real ausente: {path}")
    out = tmp_path / "oracle_cases.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools/web_export/oracle.py"), "--out", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["cases"]) >= 20
    assert all(check["igual"] for check in payload["reconciliation"].values())
    assert payload["official"]["unidades"] == 28
    assert payload["official"]["inclui_exterior"] is True
    assert payload["official"]["t2"]["aptos"] == 158_745_502
    assert payload["official"]["t2"]["lula"] == 64_256_232
    assert payload["official"]["t2"]["flavio"] == 59_826_041
    # Casos críticos presentes.
    ids = {case["id"] for case in payload["cases"]}
    assert {"vazio", "boa_esperanca", "renda_ausente", "renda_borda_735"} <= ids
    by_id = {case["id"]: case["expected"] for case in payload["cases"]}
    assert by_id["vazio"]["municipios"] == 0
    assert by_id["boa_esperanca"]["municipios"] == 1
    assert by_id["boa_esperanca"]["sem_renda"] == 1
    assert by_id["renda_ausente"]["municipios"] == 1
