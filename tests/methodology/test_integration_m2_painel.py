"""Marco M2 — painel entre turnos sobre dados reais.

Exige os dois turnos e correspondências EFETIVADAS nos dois (v1.1). CESP
(esperada) não substitui CEFT. Aprovação do M2 no piloto não é G2.
"""
import json

import pandas as pd
import pytest

from br2026.analysis.run import run_analyze
from br2026.panel.run import run_panel
from integration_support import STAGING, blocked, reference_problems, require, turns_by_uf

pytestmark = [pytest.mark.integration, pytest.mark.m2]


@pytest.fixture(scope="module")
def ready():
    require("section_turn", "votes_long", "section_crosswalk")
    sem_t2 = sorted(uf for uf, t in turns_by_uf().items() if 2 not in t)
    if sem_t2:
        blocked(f"2º turno ausente para {sem_t2}")
    cw = require("section_crosswalk")[0]
    efet = cw[cw.status_correspondencia == "EFETIVADA"].groupby("nr_turno").size()
    falta = [t for t in (1, 2) if efet.get(t, 0) == 0]
    if falta:
        blocked(f"sem correspondência EFETIVADA no(s) turno(s) {falta} (ex.: CEFT 2T ausente)")


@pytest.fixture(scope="module")
def run(ready, tmp_path_factory):
    out = tmp_path_factory.mktemp("m2_analytics")
    return {"panel": run_panel(STAGING, out), "analyze": run_analyze(STAGING, out), "out": out}


def test_m2_panel_reconciles_exactly(run):
    assert run["panel"]["status"] == "PASS", run["panel"].get("problemas")
    rec = pd.read_csv(run["out"] / "panel_reconciliation.csv")
    assert (rec.dif == 0).all()


def test_m2_exclusions_quantified(run):
    panel = pd.read_parquet(run["out"] / "panel.parquet")
    cov = pd.read_csv(run["out"] / "coverage_uf.csv")
    assert cov.unidades_incluida.sum() + cov.unidades_excluida.sum() == len(panel)
    assert panel.status_painel.notna().all()


def test_m2_analyze_blocks_justified_and_code_committed(run):
    assert run["analyze"]["status"] == "PASS", run["analyze"]
    st = pd.read_csv(run["out"] / "analysis_status.csv")
    assert st.loc[st.status != "PASS", "motivo"].fillna("").str.len().gt(0).all()
    man = json.loads((run["out"] / "analysis_manifest.json").read_text(encoding="utf-8"))
    assert man["codigo_com_alteracoes_nao_commitadas"] is False, "aceite exige código commitado"


def test_m2_official_reference_both_turns(ready):
    probs = reference_problems(turnos={1, 2})
    assert not probs, "referência T1+T2:\n" + "\n".join(probs[:20])
