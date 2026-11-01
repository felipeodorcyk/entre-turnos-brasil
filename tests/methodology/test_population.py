"""O3: o saldo de aptos não mede entradas/saídas; cenários de rotatividade.

Cada caso parte de uma tabela de fluxos VERDADEIRA escrita à mão (população com
integrantes que saem e entram) e verifica o que as marginais permitem dizer.
"""
import numpy as np
import pandas as pd
import pytest

from br2026.analysis.bounds import aggregate_bounds, contains
from br2026.analysis.margins import ENTRADA, SAIDA, build_margins

D = ["LULA", "FLAVIO", "ABSTENCAO", "BRANCO", "NULO"]


def unit(aptos1, aptos2, cand_t1, abst1, br1, nu1, lula2, fla2, abst2, br2, nu2):
    panel = pd.DataFrame({"id_unidade": ["u"], "qt_aptos_t1": [aptos1], "qt_aptos_t2": [aptos2],
                          "qt_abstencoes_t1": [abst1], "qt_votos_brancos_t1": [br1],
                          "qt_votos_nulos_t1": [nu1], "qt_votos_validos_t1": [sum(cand_t1.values())],
                          "qt_votos_validos_t2": [lula2 + fla2], "qt_lula_t2": [lula2],
                          "qt_flavio_t2": [fla2], "qt_abstencoes_t2": [abst2],
                          "qt_votos_brancos_t2": [br2], "qt_votos_nulos_t2": [nu2]})
    return panel, pd.DataFrame(cand_t1, index=["u"])


def bounds_for(panel, cand, rho):
    m = build_margins(panel, cand, rotatividade=rho)
    return m, aggregate_bounds(m["origens"].to_numpy(), m["destinos"].to_numpy(),
                               m["nomes_origem"], m["nomes_destino"])


# Verdade: 100 aptos nos dois turnos, mas 10 eleitores de Lula no T1 saíram
# (ex.: voto em trânsito no T2) e 10 novos entraram votando em Flávio.
# Origens T1: LULA_T1 40, FLAVIO_T1 30, ABSTENCAO 26, BRANCO 2, NULO 2, ENTRADA 10
# Destinos T2: LULA 30, FLAVIO 40, ABSTENCAO 26, BRANCO 2, NULO 2, SAIDA 10
SWAP_TRUE = pd.DataFrame(0.0, index=["LULA_T1", "FLAVIO_T1", "ABSTENCAO", "BRANCO", "NULO", ENTRADA],
                         columns=D + [SAIDA])
SWAP_TRUE.loc["LULA_T1", ["LULA", SAIDA]] = [30, 10]
SWAP_TRUE.loc["FLAVIO_T1", "FLAVIO"] = 30
SWAP_TRUE.loc["ABSTENCAO", "ABSTENCAO"] = 26
SWAP_TRUE.loc["BRANCO", "BRANCO"] = 2
SWAP_TRUE.loc["NULO", "NULO"] = 2
SWAP_TRUE.loc[ENTRADA, "FLAVIO"] = 10


@pytest.fixture
def swap():
    return unit(100, 100, {"LULA_T1": 40, "FLAVIO_T1": 30}, 26, 2, 2, 30, 40, 26, 2, 2)


def test_equal_aptos_minimal_scenario_has_no_cadastral_categories(swap):
    m, _ = bounds_for(*swap, rho=0.0)
    assert ENTRADA not in m["nomes_origem"] and SAIDA not in m["nomes_destino"]
    assert m["cenario_populacao"] == "rotatividade_minima"
    assert "não observadas" in m["hipotese"]


def test_equal_aptos_true_swap_only_representable_with_turnover(swap):
    m, b = bounds_for(*swap, rho=0.10)
    T = SWAP_TRUE.reindex(index=m["nomes_origem"], columns=m["nomes_destino"]).to_numpy()
    assert (T.sum(1) == m["origens"].to_numpy()[0]).all() and (T.sum(0) == m["destinos"].to_numpy()[0]).all()
    assert contains(b, T, m["nomes_origem"], m["nomes_destino"])


def test_positive_balance_with_simultaneous_entries_and_exits():
    # Verdade: 8 entram e 3 saem → saldo +5. O saldo sozinho daria 5 entradas e 0 saídas.
    panel, cand = unit(100, 105, {"LULA_T1": 40, "FLAVIO_T1": 30}, 26, 2, 2, 42, 37, 22, 2, 2)
    m0, _ = bounds_for(panel, cand, rho=0.0)
    assert m0["origens"][ENTRADA].iloc[0] == 5 and SAIDA not in m0["nomes_destino"]
    m3, _ = bounds_for(panel, cand, rho=0.03)
    assert m3["origens"][ENTRADA].iloc[0] == pytest.approx(8)
    assert m3["destinos"][SAIDA].iloc[0] == pytest.approx(3)


def test_turnover_widens_abstention_attribution(swap):
    _, b0 = bounds_for(*swap, rho=0.0)
    _, b1 = bounds_for(*swap, rho=0.10)
    k = ["origem", "destino"]
    a0 = b0.set_index(k).loc[("ABSTENCAO", "ABSTENCAO")]
    a1 = b1.set_index(k).loc[("ABSTENCAO", "ABSTENCAO")]
    # Com troca de integrantes, parte da abstenção do T2 pode vir de quem entrou:
    # o mínimo de abstenção "retida" cai e a largura não diminui.
    assert a1.fluxo_min <= a0.fluxo_min and (a1.fluxo_max - a1.fluxo_min) >= (a0.fluxo_max - a0.fluxo_min)
    e = b1.set_index(k).loc[(ENTRADA, "ABSTENCAO")]
    assert e.fluxo_max > 0


def test_negative_turnover_rejected(swap):
    with pytest.raises(ValueError, match="negativa"):
        build_margins(*swap, rotatividade=-0.1)
