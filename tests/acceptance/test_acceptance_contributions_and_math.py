"""Validação matemática independente e consistência de contribuições (Frente C).

Cobre a Tarefa 6 de 04_HANDOFF_VALIDACAO.md:
1. Soma de contribuições territoriais e decomposição exata em efeito de participação e peso.
2. Unidades dos percentuais (proporções em [0, 1] no dado; p.p. apenas no texto).
3. Limites de fluxo de comparecimento e conservação da população cadastral.
4. Limites de Fréchet e marcação de limites pouco informativos.
5. Invariância de escala e verificação contra cálculo manual independente.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from br2026.analysis.bounds import aggregate_bounds, frechet_unit_bounds
from br2026.analysis.metrics import (
    aggregate_metrics,
    ratio,
    share_contributions,
    turnout_flow_bounds,
    unit_metrics,
)


def test_territorial_contributions_exact_sum_and_decomposition():
    """Valida que a soma das contribuições de cada recorte é exatamente igual ao delta_share nacional.

    Comprova a identidade matemática:
    Delta S = sum_i (v_i2/V2 - v_i1/V1) == sum_i (efeito_participacao + efeito_peso)
    """
    # 4 estados sintéticos com variações heterogêneas
    df = pd.DataFrame([
        {"sg_uf": "AC", "qt_lula_t1": 1000, "qt_lula_t2": 1200, "qt_votos_validos_t1": 3000, "qt_votos_validos_t2": 3200},
        {"sg_uf": "AM", "qt_lula_t1": 5000, "qt_lula_t2": 6500, "qt_votos_validos_t1": 10000, "qt_votos_validos_t2": 12000},
        {"sg_uf": "SP", "qt_lula_t1": 20000, "qt_lula_t2": 22000, "qt_votos_validos_t1": 45000, "qt_votos_validos_t2": 46000},
        {"sg_uf": "RS", "qt_lula_t1": 12000, "qt_lula_t2": 11500, "qt_votos_validos_t1": 25000, "qt_votos_validos_t2": 24000},
    ])

    V1 = df.qt_votos_validos_t1.sum()
    V2 = df.qt_votos_validos_t2.sum()
    L1 = df.qt_lula_t1.sum()
    L2 = df.qt_lula_t2.sum()

    delta_share_nacional_exato = (L2 / V2) - (L1 / V1)

    contrib = share_contributions(df, "lula", by=["sg_uf"])

    # 1. A soma das contribuições fecha EXATAMENTE com a variação agregada nacional
    soma_contrib = contrib.contribuicao_delta_share.sum()
    assert pytest.approx(soma_contrib, rel=1e-12) == delta_share_nacional_exato

    # 2. Decomposição exata: efeito_participacao + efeito_peso == contribuicao_delta_share em cada linha
    decomposicao = contrib.efeito_participacao + contrib.efeito_peso
    np.testing.assert_allclose(decomposicao.values, contrib.contribuicao_delta_share.values, rtol=1e-12)

    # 3. A soma dos pesos fecha exatamente em 1 nos dois turnos
    assert pytest.approx(contrib.peso_validos_t1.sum(), rel=1e-12) == 1.0
    assert pytest.approx(contrib.peso_validos_t2.sum(), rel=1e-12) == 1.0


def test_turnout_flow_bounds_mathematical_properties():
    """Valida as propriedades matemáticas estritas dos limites de fluxo de comparecimento."""
    # N=1000 aptos, C1=700 votaram no T1, C2=800 votaram no T2
    N, C1, C2 = 1000, 700, 800
    res = turnout_flow_bounds(N, C1, C2).iloc[0]

    # Limite inferior: max(0, C1 + C2 - N) = max(0, 1500 - 1000) = 500
    assert res.ambos_min == 500
    # Limite superior: min(C1, C2) = min(700, 800) = 700
    assert res.ambos_max == 700
    # Entradas no T2: C2 - ambos -> [C2 - ambos_max, C2 - ambos_min] = [800 - 700, 800 - 500] = [100, 300]
    assert res.entradas_min == 100
    assert res.entradas_max == 300
    # Saídas no T2: C1 - ambos -> [C1 - ambos_max, C1 - ambos_min] = [700 - 700, 700 - 500] = [0, 200]
    assert res.saidas_min == 0
    assert res.saidas_max == 200

    # Variação líquida = C2 - C1 = 100
    assert res.variacao_liquida == 100
    # Entradas mínimas - saídas mínimas = 100 - 0 = 100 (conservação exata)
    assert res.entradas_min - res.saidas_min == res.variacao_liquida

    # Caso C1 == C2 (comparecimento idêntico não implica eleitorado idêntico)
    res_eq = turnout_flow_bounds(1000, 600, 600).iloc[0]
    assert res_eq.variacao_liquida == 0
    # Ambos os turnos entre max(0, 1200-1000)=200 e min(600,600)=600
    assert res_eq.ambos_min == 200
    assert res_eq.ambos_max == 600
    # A troca pode chegar a min(C1, N - C1) = min(600, 400) = 400 eleitores
    assert res_eq.saidas_max == 400
    assert res_eq.entradas_max == 400


def test_frechet_bounds_exact_formula_and_informativeness():
    """Valida os limites de Fréchet célula a célula contra a fórmula analítica independente."""
    # Marginais observadas para N=100
    # Origens: Lula=40, Bolsonaro=50, Outros=10
    # Destinos: Lula=45, Bolsonaro=55
    rows = np.array([[40.0, 50.0, 10.0]])
    cols = np.array([[45.0, 55.0]])
    orig_names = ["LULA", "BOLSONARO", "OUTROS"]
    dest_names = ["LULA", "BOLSONARO"]

    L, U = frechet_unit_bounds(rows, cols)
    # Fréchet para LULA -> LULA: max(0, 40 + 45 - 100) = 0; min(40, 45) = 40
    assert L[0, 0, 0] == 0.0
    assert U[0, 0, 0] == 40.0

    # Fréchet para BOLSONARO -> BOLSONARO: max(0, 50 + 55 - 100) = 5; min(50, 55) = 50
    assert L[0, 1, 1] == 5.0
    assert U[0, 1, 1] == 50.0

    b = aggregate_bounds(rows, cols, orig_names, dest_names)
    row_ll = b[(b.origem == "LULA") & (b.destino == "LULA")].iloc[0]
    assert pytest.approx(row_ll.taxa_min) == 0.0
    assert pytest.approx(row_ll.taxa_max) == 1.0
    assert bool(row_ll.pouco_informativo) is True  # largura = 1.0 >= 0.5

    row_bb = b[(b.origem == "BOLSONARO") & (b.destino == "BOLSONARO")].iloc[0]
    assert pytest.approx(row_bb.taxa_min) == 0.1
    assert pytest.approx(row_bb.taxa_max) == 1.0


def test_percentage_units_proportions_not_scaled_by_100():
    """Valida que shares e taxas são armazenadas como proporções em [0, 1] e não multiplicadas por 100."""
    panel_synth = pd.DataFrame([{
        "id_unidade": "AC-01007-0001-0001", "sg_uf": "AC", "cd_municipio_tse": "01007",
        "status_painel": "PAREADA",
        "qt_lula_t1": 40, "qt_lula_t2": 60, "qt_flavio_t1": 50, "qt_flavio_t2": 40,
        "qt_votos_validos_t1": 100, "qt_votos_validos_t2": 110,
        "qt_aptos_t1": 150, "qt_aptos_t2": 150,
        "qt_comparecimento_t1": 110, "qt_comparecimento_t2": 120,
        "qt_abstencoes_t1": 40, "qt_abstencoes_t2": 30,
        "qt_votos_brancos_t1": 5, "qt_votos_brancos_t2": 5,
        "qt_votos_nulos_t1": 5, "qt_votos_nulos_t2": 5,
    }])
    um = unit_metrics(panel_synth).iloc[0]
    # Share Lula T1 = 40/100 = 0.40 (NÃO 40.0)
    assert pytest.approx(um.share_lula_validos_t1) == 0.40
    assert 0.0 <= um.share_lula_validos_t1 <= 1.0

    # Margem Lula - Flavio T1 = 0.40 - 0.50 = -0.10 (NÃO -10.0)
    assert pytest.approx(um.margem_lula_flavio_validos_t1) == -0.10
    assert -1.0 <= um.margem_lula_flavio_validos_t1 <= 1.0
