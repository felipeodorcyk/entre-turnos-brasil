"""R23-1/R23-4: o contraste deriva veredictos de predicados e bloqueia insumo inconsistente.

Dados sintéticos, sem relação com resultados eleitorais reais.
"""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "contraste_piloto", Path(__file__).resolve().parents[2] / "tools" / "contraste_piloto.py")
cp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cp)


def _json_nacional(turno, lula, flavio, outros, brancos, nulos, abst):
    validos = lula + flavio + outros
    comp = validos + brancos + nulos
    cands = [{"n": "13", "vap": str(lula)}, {"n": "22", "vap": str(flavio)}]
    if outros:
        cands.append({"n": "70", "vap": str(outros)})
    return {"ele": "6257" if turno == 1 else "6258", "t": str(turno),
            "e": {"esi": str(comp + abst), "c": str(comp), "a": str(abst)},
            "v": {"vb": str(brancos), "tvn": str(nulos), "vvc": str(validos)},
            "carg": [{"agr": [{"par": [{"cand": cands}]}]}]}


def _painel(lula2_extra=0):
    rows = []
    for i, (uf, mun) in enumerate([("AC", "01392"), ("RS", "88013"), ("MG", "41238"), ("MG", "41335")]):
        # aptos 110 nos dois turnos; comparecimento 100 = válidos + brancos + nulos
        l1, f1, o1, b, n, ab = 40, 40, 10, 5, 5, 10
        l2, f2 = 52 + lula2_extra, 43 - lula2_extra
        b2, n2 = 3, 2
        ab2 = 110 - (l2 + f2 + b2 + n2)
        rows.append(dict(id_unidade=f"u{i}", sg_uf=uf, cd_municipio_tse=mun, status_painel="PAREADA",
                         qt_aptos_t1=110, qt_aptos_t2=110,
                         qt_comparecimento_t1=110 - ab, qt_comparecimento_t2=110 - ab2,
                         qt_abstencoes_t1=ab, qt_abstencoes_t2=ab2,
                         qt_votos_validos_t1=l1 + f1 + o1, qt_votos_validos_t2=l2 + f2,
                         qt_votos_brancos_t1=b, qt_votos_brancos_t2=b2,
                         qt_votos_nulos_t1=n, qt_votos_nulos_t2=n2,
                         qt_lula_t1=l1, qt_lula_t2=l2, qt_flavio_t1=f1, qt_flavio_t2=f2))
    return pd.DataFrame(rows)


@pytest.fixture
def raiz(tmp_path):
    def montar(panel=None, j1=None, j2=None, tab07_mut=None):
        src = tmp_path / "docs" / "sources" / "contraste"
        src.mkdir(parents=True, exist_ok=True)
        (src / "br-c0001-e006257-u.json").write_text(json.dumps(j1 or _json_nacional(1, 400, 420, 100, 30, 50, 200)))
        (src / "br-c0001-e006258-u.json").write_text(json.dumps(j2 or _json_nacional(2, 520, 450, 0, 20, 30, 180)))
        pd.DataFrame({"claim_id": [f"C{i:02d}" for i in range(1, 12)], "source_id": "FX", "familia": "TESTE",
                      "parafrase_fiel": "sintética", "tipo": "teste"}).to_csv(src / "alegacoes.csv", index=False)
        p = panel if panel is not None else _painel()
        an = tmp_path / "data" / "analytics"
        an.mkdir(parents=True, exist_ok=True)
        p.to_parquet(an / "panel.parquet", index=False)
        g = cp.teste_100(p[p.status_painel == "PAREADA"]).reset_index()
        t7 = g.rename(columns={"o1": "o1_demais_candidatos_t1", "dl": "delta_lula", "impede": "unidades_que_impedem_100pct",
                               "deficit": "votos_demais_que_nao_cabem_em_lula", "identidade_dif": "identidade_saldos_dif"})
        if tab07_mut:
            tab07_mut(t7)
        tab = tmp_path / "reports" / "analysis" / "tabelas_piloto"
        tab.mkdir(parents=True, exist_ok=True)
        t7.to_csv(tab / "tab07_identidade_saldos_e_teste_100pct.csv", index=False)
        return tmp_path
    return montar


def _resultado(root):
    return pd.read_csv(root / "reports" / "analysis" / "tabelas_piloto" / "contraste_resultados.csv").set_index("claim_id")


def test_veredicto_c10_sai_dos_dados(raiz):
    root = raiz()                                 # Lula T2 (52) >= demais T1 (10) em todas as unidades
    assert cp.main(["--root", str(root)]) == 0
    r = _resultado(root)
    assert r.loc["C10", "status_conclusao"] == "COMPATIVEL_NAO_NECESSARIA"
    assert "100%_possivel_no_cenario=True" in r.loc["C10", "condicoes"]
    assert "rotatividade" in r.loc["C10", "hipoteses"]


def test_c10_incompativel_quando_lula_t2_menor_que_demais(raiz):
    p = _painel()
    p.loc[0, ["qt_lula_t2", "qt_flavio_t2"]] = [5, 90]   # unidade AC: Lula 5 < demais 10
    root = raiz(panel=p)
    assert cp.main(["--root", str(root)]) == 0
    r = _resultado(root)
    assert r.loc["C10", "status_conclusao"] == "INCOMPATIVEL_NO_CENARIO_E_NAO_NECESSARIA"
    assert "1 unidade(s)" in r.loc["C10", "resultado_numerico"]


def test_tab07_zerada_bloqueia(raiz):
    p = _painel()
    p.loc[0, ["qt_lula_t2", "qt_flavio_t2"]] = [5, 90]

    def zera(t7):
        t7["unidades_que_impedem_100pct"] = 0
        t7["votos_demais_que_nao_cabem_em_lula"] = 0
    root = raiz(panel=p, tab07_mut=zera)
    saida = root / "reports" / "analysis" / "tabelas_piloto" / "contraste_resultados.csv"
    saida.write_text("resultado antigo")
    assert cp.main(["--root", str(root)]) == 2
    assert not saida.exists()                     # nada de veredicto antigo nem novo


def test_contabilidade_do_painel_divergente_bloqueia(raiz):
    p = _painel()
    p.loc[1, "qt_votos_brancos_t2"] += 1          # comparecimento != válidos + brancos + nulos
    assert cp.main(["--root", str(raiz(panel=p))]) == 2


def test_json_nacional_inconsistente_bloqueia(raiz):
    j1 = _json_nacional(1, 400, 420, 100, 30, 50, 200)
    j1["e"]["c"] = str(int(j1["e"]["c"]) + 7)
    assert cp.main(["--root", str(raiz(j1=j1))]) == 2


def test_c03_limiar_muda_com_as_hipoteses():
    d1 = {"lula": 400, "flavio": 420, "validos": 920}
    d2 = {"lula": 520, "flavio": 450, "validos": 970}
    cen = {c["cenario"]: c["fracao_minima"] for c in cp.cenarios_c03(d1, d2)}
    assert cen["A"] == pytest.approx((20 + 100) / 200)       # só os demais, retenção total
    assert cen["B"] == pytest.approx((20 + 150) / 300)       # demais + saldo de novos válidos
    assert cen["C"] == 0.0 and len(set(cen.values())) == 3


def _nacional_com_tardias(root, tse, tatu):
    import shutil
    nac = root / "reports" / "analysis" / "tabelas_nacional"
    nac.mkdir(parents=True, exist_ok=True)
    shutil.copy(root / "reports" / "analysis" / "tabelas_piloto" / "tab07_identidade_saldos_e_teste_100pct.csv", nac)
    ev = root / "reports" / "analysis" / "evidencias_horarios"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "reconciliacao_tardias.json").write_text(json.dumps({"votos_apos_17h_pais": {
        "tse": tse, "tatu_todos_logs": tatu, "congresso_em_foco_cnn": cp.N_LOG,
        "nossa_contagem_na_cauda": 5005, "secoes_na_cauda": 7562}}))
    assert cp.main(["--root", str(root), "--escopo", "nacional"]) == 0
    return pd.read_csv(nac / "contraste_resultados.csv").set_index("claim_id")


def test_c11_parcial_quando_tse_e_tatu_confirmam_a_ordem_de_grandeza(raiz):
    r = _nacional_com_tardias(raiz(), tse=34393, tatu=34126)
    assert r.loc["C11", "status_conclusao"] == "PARCIALMENTE_REPRODUZIDA"
    assert "contagem_propria_nacional=False" in r.loc["C11", "condicoes"]
    assert "reconciliacao_tardias.json" in r.loc["C11", "insumos_sha256"]
    # C08 usa a maior das contagens publicadas
    assert "N=34393" in r.loc["C08", "resultado_numerico"]


def test_c11_divergente_quando_uma_contagem_se_afasta(raiz):
    r = _nacional_com_tardias(raiz(), tse=34393, tatu=30000)
    assert r.loc["C11", "status_conclusao"] == "DIVERGENTE"
