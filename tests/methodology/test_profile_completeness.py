"""O-R1 (revisão 10): dimensão ou origem ausente nunca vira proporção zero.

Cada caso verifica valores, elegibilidade e diagnóstico. A asserção de
comportamento vem antes da de diagnóstico, para que o defeito anterior apareça
como falha de comportamento, não só como coluna inexistente.
"""
import pandas as pd
import pytest

from br2026.analysis.profile import unit_profile
from br2026.config import load_config
from test_profile import BASE, GEO, frames, prof_rows

CFG = load_config()


def run(rows, extra_units=()):
    p, cw, mem = frames(rows)
    if extra_units:
        mem = pd.concat([mem, pd.DataFrame([{"nr_turno": 1, **GEO, "nr_secao": s, "id_unidade": u}
                                            for s, u in extra_units])], ignore_index=True)
    shares, diag = unit_profile(p, cw, mem, CFG)
    return shares, diag.set_index("id_unidade")


def test_dimension_missing_in_one_section_excludes_unit():
    rows = [r for r in BASE if not (r["nr_secao"] == "0003" and r["dimensao"] == "GENERO")]
    shares, d = run(rows)
    assert "U3" not in shares.index, "dimensão ausente não pode virar feminino=0/masculino=0"
    assert "U1" in shares.index
    assert d.at["U3", "motivo_exclusao"] == "DIMENSAO_AUSENTE"
    assert d.at["U3", "dimensoes_faltantes"] == "GENERO"
    assert not d.at["U3", "elegivel"] and d.at["U1", "elegivel"]


def test_dimension_missing_in_whole_dataset():
    rows = [r for r in BASE if r["dimensao"] != "GRAU_ESCOLARIDADE"]
    shares, d = run(rows)
    assert shares.empty
    assert (d.motivo_exclusao == "DIMENSAO_AUSENTE").all()
    assert d.dimensoes_faltantes.str.contains("GRAU_ESCOLARIDADE").all()


def test_partially_missing_origin_inside_aggregated_unit():
    rows = [r for r in BASE if r["nr_secao"] != "0002"]  # U1 = 0001 + 0002
    shares, d = run(rows)
    assert "U1" not in shares.index, "perda parcial de origem não pode ser escondida na agregação"
    assert d.at["U1", "motivo_exclusao"] == "PERFIL_PARCIAL_ORIGENS"
    assert d.at["U1", "n_origens"] == 2 and d.at["U1", "n_origens_com_perfil"] == 1


def test_zero_total_excluded():
    rows = [{**r, "qt_eleitores": 0} if r["nr_secao"] == "0003" else r for r in BASE]
    shares, d = run(rows)
    assert "U3" not in shares.index
    assert d.at["U3", "motivo_exclusao"] == "TOTAL_ZERO"


def test_legitimate_zero_category_kept_as_zero():
    rows = [r for r in BASE if r["nr_secao"] != "0003"]
    rows += prof_rows("0003", {"2": 20, "4": 0}, {"4549": 20}, {"0": 20})
    shares, d = run(rows)
    assert d.at["U3", "elegivel"]
    assert shares.at["U3", "perfil_genero_feminino"] == 0.0          # zero observado
    assert shares.at["U3", "perfil_grau_escolaridade_superior_completo"] == 0.0  # categoria sem linha
    assert shares.at["U3", "perfil_genero_masculino"] == pytest.approx(1.0)


def test_unit_without_any_profile_is_diagnosed():
    shares, d = run(BASE, extra_units=[("0009", "U9")])
    assert "U9" not in shares.index
    assert "U9" in d.index, "unidade sem perfil precisa aparecer no diagnóstico"
    assert d.at["U9", "motivo_exclusao"] == "SEM_PERFIL" and d.at["U9", "n_origens_com_perfil"] == 0
