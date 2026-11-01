"""Testes de aceite com fixtures e oráculos manuais independentes (Frente C).

Verifica a lógica de unificação de seções, contabilidade e reconciliação
contra o gabarito calculado manualmente em `oracle_fixtures.py`.
"""
from __future__ import annotations

import pytest

from br2026.analysis.metrics import aggregate_metrics, unit_metrics
from br2026.panel.build import build_panel, coverage, reconcile
from tests.fixtures.acceptance.oracle_fixtures import (
    ORACLE_COMPLEX_EXPECTED,
    build_complex_oracle_dfs,
)


def test_oracle_complex_aggregation_and_statuses():
    """Valida o componente conexo, a fusão de seções agregadas e todos os motivos de exclusão."""
    st, cw, vl = build_complex_oracle_dfs()
    nr_lula, nr_flavio = 13, 22

    panel, membership = build_panel(st, vl, cw, nr_lula, nr_flavio, return_membership=True)
    expected_units = ORACLE_COMPLEX_EXPECTED["unidades"]

    # 1. Todas as unidades esperadas existem
    assert set(panel.id_unidade) == set(expected_units.keys())

    # 2. Conferir cada unidade contra o oráculo independente
    for uid, exp in expected_units.items():
        row = panel[panel.id_unidade == uid].iloc[0]
        assert row.status_painel == exp["status"], f"Status divergente para {uid}"
        assert row.tipo_unidade == exp["tipo"], f"Tipo divergente para {uid}"
        assert row.n_secoes_origem == exp["n_secoes_origem"], f"n_secoes divergente para {uid}"

        if exp["status"] == "PAREADA":
            assert row.qt_aptos_t1 == exp["qt_aptos_t1"]
            assert row.qt_aptos_t2 == exp["qt_aptos_t2"]
            assert row.qt_votos_validos_t1 == exp["qt_votos_validos_t1"]
            assert row.qt_votos_validos_t2 == exp["qt_votos_validos_t2"]
            assert row.qt_lula_t1 == exp["qt_lula_t1"]
            assert row.qt_lula_t2 == exp["qt_lula_t2"]
            assert row.qt_flavio_t1 == exp["qt_flavio_t1"]
            assert row.qt_flavio_t2 == exp["qt_flavio_t2"]
            assert bool(row.flag_aptos_divergente) == exp["flag_aptos_divergente"]

    # 3. Conferir métricas pareadas agregadas
    pareadas = panel[panel.status_painel == "PAREADA"]
    exp_m = ORACLE_COMPLEX_EXPECTED["metricas_pareadas"]

    assert int(pareadas.qt_votos_validos_t1.sum()) == exp_m["qt_validos_pareados_t1"]
    assert int(pareadas.qt_votos_validos_t2.sum()) == exp_m["qt_validos_pareados_t2"]
    assert int(pareadas.qt_lula_t1.sum()) == exp_m["qt_lula_pareados_t1"]
    assert int(pareadas.qt_lula_t2.sum()) == exp_m["qt_lula_pareados_t2"]
    assert int(pareadas.qt_flavio_t1.sum()) == exp_m["qt_flavio_pareados_t1"]
    assert int(pareadas.qt_flavio_t2.sum()) == exp_m["qt_flavio_pareados_t2"]

    agg = aggregate_metrics(pareadas)
    assert pytest.approx(agg["share_lula_validos_t1"]) == exp_m["share_lula_pareados_t1"]
    assert pytest.approx(agg["share_lula_validos_t2"]) == exp_m["share_lula_pareados_t2"]
    assert pytest.approx(agg["share_flavio_validos_t1"]) == exp_m["share_flavio_pareados_t1"]
    assert pytest.approx(agg["share_flavio_validos_t2"]) == exp_m["share_flavio_pareados_t2"]
    assert agg["delta_qt_lula"] == exp_m["delta_lula"]
    assert agg["delta_qt_flavio"] == exp_m["delta_flavio"]
    assert agg["delta_margem_lula_flavio_votos"] == exp_m["delta_margem_votos"]


def test_oracle_reconciliation_exact_conservation():
    """Valida a reconciliação independente contra os totais de seção."""
    st, cw, vl = build_complex_oracle_dfs()
    nr_lula, nr_flavio = 13, 22

    panel, membership = build_panel(st, vl, cw, nr_lula, nr_flavio, return_membership=True)
    rec = reconcile(panel, membership, st, vl, nr_lula, nr_flavio)

    # Identidades obrigatórias do contrato
    assert rec.attrs["secoes_sem_unidade"] == 0, "Há seções sem unidade mapeada"
    assert rec.attrs["secoes_duplicadas"] == 0, "Há seções duplicadas no membership"
    assert (rec.dif == 0).all(), f"Divergência de reconciliação encontrada: {rec[rec.dif != 0]}"


def test_oracle_coverage_summary():
    """Valida o cálculo de cobertura por recorte contra contagem esperada."""
    st, cw, vl = build_complex_oracle_dfs()
    panel = build_panel(st, vl, cw, nr_lula=13, nr_flavio=22)
    cov = coverage(panel, by=["sg_uf"])

    assert len(cov) == 1
    row = cov.iloc[0]
    assert row.sg_uf == "AC"
    # De 7 unidades: 2 pareadas (0010 e 0020) e 5 excluídas (0030, 0040, 0050, 0060, 0070)
    assert row.unidades_incluida == 2
    assert row.unidades_excluida == 5
    assert pytest.approx(row.unidades_pct_incluida) == 2 / 7
