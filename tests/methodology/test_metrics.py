"""DoD 2: ganho absoluto com perda de vantagem; denominador zero; válidos e aptos variando."""
import numpy as np
import pandas as pd
import pytest

from br2026.analysis.metrics import (aggregate_metrics, ratio, share_contributions,
                                     turnout_flow_bounds, unit_metrics)
from br2026.panel.build import build_panel


@pytest.fixture
def pareada(section_turn, votes_long, crosswalk):
    p = build_panel(section_turn, votes_long, crosswalk, 13, 22)
    return p[p.status_painel == "PAREADA"].reset_index(drop=True)


def test_absolute_gain_with_relative_loss(pareada, expected):
    m = aggregate_metrics(pareada)
    e = expected["metricas_pareadas"]
    for k, v in e.items():
        assert m[k] == pytest.approx(v, abs=1e-12), k
    assert m["delta_qt_lula"] > 0 and m["delta_share_lula_validos"] > 0
    assert m["delta_margem_lula_flavio_validos"] < 0


def test_aggregate_is_ratio_of_sums_not_mean_of_ratios(pareada):
    m = aggregate_metrics(pareada)
    um = unit_metrics(pareada)
    mean_unweighted = um.share_lula_validos_t1.mean()
    assert m["share_lula_validos_t1"] == pytest.approx(140 / 320)
    assert mean_unweighted != pytest.approx(m["share_lula_validos_t1"])


def test_zero_denominator_is_nan_not_zero_or_inf():
    r = ratio([0, 5, 3], [0, 0, 3])
    assert np.isnan(r[0]) and np.isnan(r[1]) and r[2] == 1.0


def test_unit_with_zero_valid_votes(pareada):
    p = pareada.copy()
    for c in ("qt_votos_validos_t2", "qt_lula_t2", "qt_flavio_t2"):
        p.loc[0, c] = 0
    um = unit_metrics(p)
    assert np.isnan(um.share_lula_validos_t2[0]) and np.isnan(um.delta_share_lula_validos[0])


def test_share_can_rise_while_votes_fall_when_valid_votes_drop():
    p = pd.DataFrame({"id_unidade": ["u"], "sg_uf": ["AC"], "cd_municipio_tse": ["01007"],
                      "status_painel": ["PAREADA"],
                      "qt_lula_t1": [50], "qt_lula_t2": [45], "qt_flavio_t1": [50], "qt_flavio_t2": [35],
                      "qt_votos_validos_t1": [100], "qt_votos_validos_t2": [80],
                      "qt_aptos_t1": [150], "qt_aptos_t2": [150],
                      "qt_comparecimento_t1": [110], "qt_comparecimento_t2": [95],
                      "qt_abstencoes_t1": [40], "qt_abstencoes_t2": [55],
                      "qt_votos_brancos_t1": [5], "qt_votos_brancos_t2": [7],
                      "qt_votos_nulos_t1": [5], "qt_votos_nulos_t2": [8]})
    um = unit_metrics(p)
    assert um.delta_qt_lula[0] == -5
    assert um.delta_share_lula_validos[0] == pytest.approx(45 / 80 - 0.5)
    assert um.delta_lula_por_apto[0] == pytest.approx(-5 / 150)


def test_contributions_sum_exactly_to_national_change(pareada):
    c = share_contributions(pareada, "lula", ["sg_uf", "cd_municipio_tse"])
    m = aggregate_metrics(pareada)
    assert c.contribuicao_delta_share.sum() == pytest.approx(m["delta_share_lula_validos"], abs=1e-15)
    assert (c.efeito_participacao + c.efeito_peso).sum() == pytest.approx(
        m["delta_share_lula_validos"], abs=1e-15)
    assert c.contribuicao_delta_votos.sum() == m["delta_qt_lula"]


def test_identical_turnout_allows_full_replacement():
    """Exemplo obrigatório: comparecimento idêntico não implica os mesmos votantes."""
    b = turnout_flow_bounds([100], [60], [60]).iloc[0]
    assert b.variacao_liquida == 0
    assert b.entradas_min == 0 and b.entradas_max == 40
    assert b.saidas_max == 40 and b.ambos_min == 20 and b.ambos_max == 60


def test_turnout_bounds_refuse_different_populations():
    b = turnout_flow_bounds(([100], [110]), [60], [70]).iloc[0]
    assert np.isnan(b.entradas_min) and b.motivo == "APTOS_DIFERENTES_OU_AUSENTES"
    assert b.variacao_liquida == 10
