"""DoD 3: matrizes distintas com as mesmas marginais não são distinguidas."""
import numpy as np
import pandas as pd
import pytest

from br2026.analysis.bounds import aggregate_bounds, contains, frechet_unit_bounds
from br2026.analysis.ecological import fit_constant_rates, publication_decision
from br2026.analysis.margins import build_margins

O, D = ["CAND_A", "ABSTENCAO"], ["LULA", "ABSTENCAO"]


def test_two_flow_matrices_same_margins():
    A = np.array([[50, 10], [0, 40]])
    B = np.array([[30, 30], [20, 20]])
    assert (A.sum(axis=1) == B.sum(axis=1)).all() and (A.sum(0) == B.sum(0)).all()
    rows, cols = A.sum(axis=1)[None], A.sum(0)[None]
    bounds = aggregate_bounds(rows, cols, O, D)
    assert contains(bounds, A, O, D) and contains(bounds, B, O, D)
    assert bounds.pouco_informativo.all()
    # Uma única unidade (ou unidades com proporções idênticas) não identifica taxas.
    X = np.repeat(rows, 5, axis=0)
    Y = np.repeat(cols, 5, axis=0)
    fit = fit_constant_rates(X, Y)
    assert not fit.identificado
    dec = publication_decision(fit, bounds)
    assert not dec["publicar_matriz_pontual"] and dec["publicar_limites"]


def test_frechet_bounds_manual():
    L, U = frechet_unit_bounds([[60, 40]], [[50, 50]])
    assert L[0].tolist() == [[10, 10], [0, 0]]
    assert U[0].tolist() == [[50, 50], [40, 40]]


def test_open_population_rejected():
    with pytest.raises(ValueError, match="População não fechada"):
        frechet_unit_bounds([[60, 40]], [[50, 55]])


def test_margins_add_explicit_cadastral_categories():
    panel = pd.DataFrame({"id_unidade": ["u1", "u2"],
                          "qt_aptos_t1": [100, 100], "qt_aptos_t2": [110, 95],
                          "qt_abstencoes_t1": [20, 20], "qt_abstencoes_t2": [30, 15],
                          "qt_votos_brancos_t1": [2, 2], "qt_votos_brancos_t2": [3, 1],
                          "qt_votos_nulos_t1": [3, 3], "qt_votos_nulos_t2": [2, 4],
                          "qt_votos_validos_t1": [75, 75], "qt_votos_validos_t2": [75, 75],
                          "qt_lula_t2": [40, 35], "qt_flavio_t2": [35, 40]})
    t1 = pd.DataFrame({"LULA_T1": [30, 40], "FLAVIO_T1": [30, 25], "OUTROS": [15, 10]},
                      index=["u1", "u2"])
    m = build_margins(panel, t1)
    assert "ENTRADA_CADASTRO_CENARIO" in m["nomes_origem"] and "SAIDA_CADASTRO_CENARIO" in m["nomes_destino"]
    assert m["cenario_populacao"] == "rotatividade_minima"
    assert (m["origens"].sum(axis=1) == m["destinos"].sum(axis=1)).all()
    assert m["origens"].loc["u1", "ENTRADA_CADASTRO_CENARIO"] == 10
    assert m["destinos"].loc["u2", "SAIDA_CADASTRO_CENARIO"] == 5
    assert m["unidades_aptos_divergentes"] == 2


def test_merged_origin_bounds_joint_100pct():
    """Handoff 22: '100% dos demais → Lula' usa a origem agregada, não a soma dos máximos por célula."""
    from br2026.analysis.bounds import merged_origin_bounds
    # Origens: CAND_A, CAND_B, ABSTENCAO; destinos: LULA, ABSTENCAO.
    # Unidade 1: A=30, B=30 cabem cada um em LULA=40, mas juntos (60) não.
    rows = np.array([[30, 30, 40], [10, 0, 90]], float)
    cols = np.array([[40, 60], [100, 0]], float)
    lo, hi = merged_origin_bounds(rows, cols, [0, 1], 0)
    assert hi.tolist() == [40.0, 10.0] and lo.tolist() == [0.0, 10.0]
    # Por célula, cada candidato isolado poderia ir 100% para Lula na unidade 1...
    L, U = frechet_unit_bounds(rows, cols)
    assert U[0, 0, 0] == 30 and U[0, 1, 0] == 30
    # ...mas o grupo não: 100% possível só se Σ hi == Σ origem.
    assert hi.sum() < rows[:, :2].sum()
    # Na unidade 2 a abstenção do T2 é zero: 100% dos demais é necessário.
    assert lo[1] == rows[1, :2].sum()


def test_check_margins_tolera_arredondamento_mas_nao_populacao_aberta():
    """Marginais fracionárias (cenário ρ > 0) fecham até o arredondamento; gap real continua erro."""
    from br2026.analysis.bounds import check_margins
    rows = np.array([[0.1, 0.2, 6.16]])
    cols = np.array([[0.3, 6.16]])            # 0.1 + 0.2 fecha com 0.3 só até o arredondamento
    assert abs(rows.sum(1) - cols.sum(1)).max() < 1e-9
    check_margins(rows, cols)
    with pytest.raises(ValueError, match="População não fechada"):
        check_margins(np.array([[1.0, 2.0]]), np.array([[3.5]]))
