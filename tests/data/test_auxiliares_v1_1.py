"""Testes offline das tabelas auxiliares v1.1 — `profiles`, `closure`, `section_crosswalk`.

Cenário sintético (AC/T1, formato TSE real) num projeto temporário, sem rede.
Cobre: formato longo do perfil e fechamento das marginais; preservação dos
horários brutos, fuso não documentado, reemissão/substituição e anomalia;
correspondência ESPERADA (eleitorado) × EFETIVADA (BU web), ambiguidade e
SEM_APURACAO; validação do contrato depois do round-trip Parquet; e
idempotência por UF/turno.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures" / "data"))

from br2026.panel.run import staging_path  # noqa: E402
from br2026.contract import validate_parquet  # noqa: E402
from br2026.normalize import run  # noqa: E402
from synth_raw import montar_raw, total, voto  # noqa: E402

UF = "AC"
TURNO = 1

COLS_PERFIL = ["AA_ELEICAO", "DT_GERACAO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA",
               "NR_SECAO", "CD_GENERO", "DS_GENERO", "CD_FAIXA_ETARIA",
               "DS_FAIXA_ETARIA", "CD_GRAU_ESCOLARIDADE", "DS_GRAU_ESCOLARIDADE",
               "CD_ESTADO_CIVIL", "DS_ESTADO_CIVIL", "CD_RACA_COR", "DS_RACA_COR",
               "QT_ELEITORES"]
COLS_BWEB = ["ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA",
             "NR_SECAO", "DT_ABERTURA", "DT_ENCERRAMENTO", "DT_EMISSAO_BU",
             "DT_BU_RECEBIDO", "DS_SECOES_AGREGADAS", "NR_URNA_EFETIVADA",
             "CD_CARGO_PERGUNTA"]
COLS_ELEITORADO = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                   "CD_TIPO_SECAO_AGREGADA", "NR_SECAO_PRINCIPAL",
                   "NR_LOCAL_VOTACAO", "NR_LOCAL_VOTACAO_ORIGINAL"]


def _csv(cols, linhas) -> bytes:
    corpo = [";".join(f'"{c}"' for c in cols)]
    corpo += [";".join(str(v) for v in ln) for ln in linhas]
    return "\n".join(corpo).encode("latin-1")


def _zip(membro: str, dados: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(membro, dados)
    return buf.getvalue()


def _registrar(raw: Path, manifesto: dict, stem: str, arquivo: str, conteudo: bytes) -> None:
    (raw / arquivo).write_bytes(conteudo)
    manifesto["registros"][stem] = {
        "fonte": stem, "arquivo": arquivo,
        "sha256": hashlib.sha256(conteudo).hexdigest(),
        "bytes": len(conteudo), "uf": UF, "turnos": [TURNO],
        "url": f"https://local/{arquivo}",
    }


def _perfil(secao, gen, faixa, esc, civil, raca, qt, mun="1201", zona="10",
            ds_raca=None) -> list:
    """Linha do perfil: cd e ds são iguais por convenção, exceto raça."""
    return ["2026", "14/07/2026", UF, mun, zona, secao, gen, f"G{gen}", faixa,
            f"F{faixa}", esc, f"E{esc}", civil, f"C{civil}", raca,
            ds_raca or f"R{raca}", qt]


def _bweb(secao, lista, urna, abertura="2026-10-04 06:00:01",
          encerramento="2026-10-04 15:00:00", emissao="2026-10-04 15:02:00",
          recebido="2026-10-04 18:00:00", mun="1201", zona="10") -> list:
    return ["2026", TURNO, UF, mun, zona, secao, abertura, encerramento, emissao,
            recebido, lista, urna, "1"]


def _eleitorado(secao, tipo, principal="0", local="1001", original="1001",
                mun="1201", zona="10") -> list:
    return [TURNO, UF, mun, zona, secao, tipo, principal, local, original]


def _montar_cenario(raiz: Path) -> None:
    """Cinco insumos: votos, detalhe (com tempos), perfil, bweb e eleitorado."""
    votos = [
        voto(UF, "10", "10", "1201", "13", "280002542548", "3"),
        voto(UF, "10", "10", "1201", "22", "280002542553", "2"),
        voto(UF, "10", "20", "1201", "13", "280002542548", "1"),
        voto(UF, "10", "20", "1201", "22", "280002542553", "1"),
    ]
    # o detalhe do fixture é reconstruído abaixo com as colunas de tempo
    totais = [
        total(UF, "10", "10", "1201", 8, 6, 2, 4, 0, 1, 1),
        total(UF, "10", "20", "1201", 3, 2, 1, 1, 0, 1, 0),
        total(UF, "10", "30", "1201", 2, 2, 0, 2, 0, 0, 0),
    ]
    montar_raw(raiz, votos, totais)
    raw = raiz / "data" / "raw"
    manifesto = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))

    # ---- detalhe com as duas colunas de tempo (reemissão na seção 10) ----- #
    zp = raw / "detalhe_votacao_secao_2026.zip"
    with zipfile.ZipFile(zp) as z:
        nome = z.namelist()[0]
        linhas = [ln for ln in z.read(nome).decode("latin-1").splitlines() if ln.strip()]
    tempos = [("04/10/2026 17:46:44", "04/10/2026 17:48:34"),
              ("04/10/2026 17:47:00", "04/10/2026 17:48:34"),
              ("04/10/2026 17:48:10", "04/10/2026 17:50:00")]
    novas = [linhas[0].rstrip(";")
             + ';"DT_RECEBIMENTO_BU_HOR_TSE";"DT_PRIM_TOT_PARCIAL_HOR_TSE"']
    novas += [ln + f';"{r}";"{p}"' for ln, (r, p) in zip(linhas[1:], tempos, strict=True)]
    novo = _zip(nome, ("\n".join(novas)).encode("latin-1"))
    _registrar(raw, manifesto, "detalhe_votacao_secao_2026", zp.name, novo)

    # ---- perfil: 3 seções; seção 10 com combos repetidos e raça -1 -------- #
    perfil = [
        # seção 10: cruzamento com total 10 em todas as dimensões
        _perfil("10", "4", "3034", "5", "1", "1", 5),
        _perfil("10", "2", "3034", "5", "1", "1", 3),
        # combos repetidos (dimensões extras do bruto): somam 2 na raça -1
        _perfil("10", "4", "4044", "5", "1", "-1", 1, ds_raca="NÃO INFORMADO"),
        _perfil("10", "4", "4044", "5", "1", "-1", 1, ds_raca="NÃO INFORMADO"),
        # seção 20: uma categoria por dimensão, total 3
        _perfil("20", "4", "3034", "5", "1", "1", 3),
        # seção 30: agregada, total 2
        _perfil("30", "2", "4044", "5", "1", "1", 2),
    ]
    pz = _zip("perfil_eleitor_secao_2026_AC.csv", _csv(COLS_PERFIL, perfil))
    _registrar(raw, manifesto, "perfil_eleitor_secao_2026_AC",
               "perfil_eleitor_secao_2026_AC.zip", pz)

    # ---- bweb: seção 10 própria, 20 e 50 listam agregadas; 60 ambígua ----- #
    bweb = [
        _bweb("10", "#NULO#", "111"),
        _bweb("10", "#NULO#", "111", emissao="2026-10-04 15:05:00"),  # reemissão
        _bweb("20", "30 / 60", "222"),
        _bweb("20", "30 / 60", "333"),                                 # substituição
        _bweb("50", "60", "444", abertura="horario quebrado"),         # anomalia
    ]
    bz = _zip("bweb_1t_AC_051020261403.csv", _csv(COLS_BWEB, bweb))
    _registrar(raw, manifesto, "bweb_1t_AC_051020261403",
               "bweb_1t_AC_051020261403.zip", bz)

    # ---- eleitorado: tipo 1 = própria, 2 = agregada ----------------------- #
    eleitorado = [
        _eleitorado("10", "1"), _eleitorado("20", "1", local="1002"),
        _eleitorado("30", "2", principal="20", local="1003"),
        _eleitorado("40", "1", local="1004"),   # sem registro no bweb
        _eleitorado("50", "1", local="1005"),
        _eleitorado("60", "2", principal="50", local="1006"),
    ]
    ez = _zip("eleitorado_local_votacao_2026_AC.csv",
              _csv(COLS_ELEITORADO, eleitorado))
    _registrar(raw, manifesto, "eleitorado_local_votacao_2026",
               "eleitorado_local_votacao_2026.zip", ez)

    (raw / "manifest.json").write_text(json.dumps(manifesto, indent=2), encoding="utf-8")


@pytest.fixture()
def staging(tmp_path):
    _montar_cenario(tmp_path)
    res = run(UF, TURNO, tmp_path)
    assert res.bloqueios == (), res.bloqueios
    return tmp_path / "data" / "staging", res


def _tabela(staging: Path, nome: str) -> pd.DataFrame:
    return validate_parquet(staging_path(staging, nome), nome)


# --------------------------------------------------------------------------- #
# profiles                                                                     #
# --------------------------------------------------------------------------- #


def test_profiles_formato_longo_e_marginais(staging):
    st, res = staging
    p = _tabela(st, "profiles")
    assert len(p) == 18           # seção 10: 8 combos; 20 e 30: 5 cada
    assert set(p.dimensao) == {"GENERO", "FAIXA_ETARIA", "GRAU_ESCOLARIDADE",
                               "ESTADO_CIVIL", "RACA_COR"}
    # combos repetidos da seção 10 foram somados (GENERO 4 = 5 + 2)
    s10 = p[(p.nr_zona == "0010") & (p.nr_secao == "0010")]
    gen4 = s10[(s10.dimensao == "GENERO") & (s10.cd_categoria == "4")]
    assert len(gen4) == 1 and int(gen4.qt_eleitores.iloc[0]) == 7
    # cada dimensão fecha no total da seção (10, 3 e 2)
    marginais = s10.groupby("dimensao")["qt_eleitores"].sum()
    assert set(marginais) == {10}
    assert res.linhas["profiles_novas"] == len(p)


def test_profiles_preserva_desconhecido_e_datas(staging):
    st, _ = staging
    p = _tabela(st, "profiles")
    raca = p[(p.dimensao == "RACA_COR") & (p.cd_categoria == "-1")]
    assert not raca.empty
    assert bool(raca.flag_desconhecido.all())
    assert set(raca.ds_categoria) == {"NÃO INFORMADO"}
    # -1 continua como categoria (nunca remanejado) e a categoria informada existe
    assert set(p[p.dimensao == "RACA_COR"].cd_categoria) == {"-1", "1"}
    assert p.dt_referencia_cadastro.isna().all()
    assert str(p.dt_geracao.iloc[0].date()) == "2026-07-14"
    assert p.ano_referencia.unique().tolist() == [2026]


# --------------------------------------------------------------------------- #
# closure                                                                      #
# --------------------------------------------------------------------------- #


def test_closure_preserva_horario_bruto_sem_inferir_fuso(staging):
    st, res = staging
    c = _tabela(st, "closure")
    # bweb: seções 10, 20 e 50 × 4 campos (+ reemissão) ; detalhe: 3 seções × 2
    assert set(c.semantica) == {"ABERTURA_URNA", "ENCERRAMENTO_URNA", "EMISSAO_BU",
                                "RECEBIMENTO_BU_TSE", "PRIMEIRA_TOTALIZACAO_TSE"}
    assert c.ts_brasilia.isna().all()
    assert set(c.motivo_ausencia) == {"FUSO_NAO_DOCUMENTADO", "BRUTO_INVALIDO"}
    assert c.fuso_documentado.isna().all() and c.fonte_fuso.isna().all()
    # texto exatamente como na fonte, nos dois formatos
    assert "2026-10-04 06:00:01" in set(c.ts_bruto)
    assert "04/10/2026 17:46:44" in set(c.ts_bruto)
    assert res.linhas["closure_novas"] == len(c)


def test_closure_preserva_reemissao_e_substituicao(staging):
    st, _ = staging
    c = _tabela(st, "closure")
    em = c[(c.nr_secao == "0010") & (c.semantica == "EMISSAO_BU")]
    assert len(em) == 2                                  # duas emissões, nada descartado
    assert bool(em.flag_reemissao.all())
    # seção 20 tem duas urnas efetivas
    s20 = c[c.nr_secao == "0020"]
    assert bool(s20.flag_substituicao_urna.all())
    assert not c[c.nr_secao == "0010"].flag_substituicao_urna.any()


def test_closure_marca_bruto_invalido_sem_corrigir(staging):
    st, _ = staging
    c = _tabela(st, "closure")
    ruim = c[(c.nr_secao == "0050") & (c.semantica == "ABERTURA_URNA")]
    assert ruim.ts_bruto.iloc[0] == "horario quebrado"
    assert bool(ruim.flag_anomalia.all())
    assert ruim.motivo_ausencia.iloc[0] == "BRUTO_INVALIDO"


# --------------------------------------------------------------------------- #
# section_crosswalk                                                            #
# --------------------------------------------------------------------------- #


def test_crosswalk_esperada_e_efetivada(staging):
    st, res = staging
    cw = _tabela(st, "section_crosswalk")
    esp = cw[cw.status_correspondencia == "ESPERADA"]
    efe = cw[cw.status_correspondencia == "EFETIVADA"]
    # ESPERADA: 6 seções (10,20,50 próprias; 30,60 agregadas; 40 sem apuração)
    assert len(esp) == 6 and len(efe) == 5
    # EFETIVADA vem do BU web: 10 própria, 20 e 50 principais, 30 agregada,
    # 60 ambígua (listada por 20 e por 50)
    tipos = set(zip(efe.nr_secao, efe.tipo_correspondencia))
    assert ("0010", "PROPRIA") in tipos
    assert ("0020", "PRINCIPAL_COM_AGREGADAS") in tipos
    assert ("0030", "AGREGADA_EM_OUTRA") in tipos
    amb = efe[efe.tipo_correspondencia == "AMBIGUA"]
    assert len(amb) == 1 and amb.nr_secao.iloc[0] == "0060"
    assert bool(amb.flag_ambigua.all()) and amb.nr_secao_apuradora.isna().all()
    assert "0020" in amb.justificativa.iloc[0] and "0050" in amb.justificativa.iloc[0]
    # agregada aponta para a seção principal
    assert efe[efe.nr_secao == "0030"].nr_secao_apuradora.iloc[0] == "0020"
    assert esp[esp.nr_secao == "0030"].nr_secao_apuradora.iloc[0] == "0020"
    # seção sem registro no BU web não é inventada: SEM_APURACAO com apuradora nula
    sem = esp[esp.nr_secao == "0040"]
    assert sem.tipo_correspondencia.iloc[0] == "SEM_APURACAO"
    assert sem.nr_secao_apuradora.isna().all()
    assert res.linhas["section_crosswalk_novas"] == len(cw)


def test_crosswalk_locais_e_fonte(staging):
    st, _ = staging
    cw = _tabela(st, "section_crosswalk")
    s30 = cw[cw.nr_secao == "0030"]
    assert set(s30.nr_local_votacao) == {"1003"}
    assert set(s30.fonte) == {
        "bweb:DS_SECOES_AGREGADAS",
        "eleitorado_local_votacao:CD_TIPO_SECAO_AGREGADA",
    }
    # nenhuma coluna de votos: correspondência não distribui votos
    assert not [c for c in cw.columns if c.startswith("qt_")]


# --------------------------------------------------------------------------- #
# idempotência e contrato                                                      #
# --------------------------------------------------------------------------- #


def test_idempotencia_por_uf_turno(staging):
    st, primeiro = staging
    raiz = st.parents[1]
    segundo = run(UF, TURNO, raiz)
    assert segundo.bloqueios == ()
    for tabela in ("profiles", "closure", "section_crosswalk"):
        a = validate_parquet(staging_path(st, tabela), tabela)
        assert len(a) == primeiro.linhas[f"{tabela}_total"]


def test_contrato_valida_as_tres_tabelas(staging):
    st, _ = staging
    for tabela in ("profiles", "closure", "section_crosswalk"):
        df = validate_parquet(staging_path(st, tabela), tabela)
        assert len(df) > 0


def test_crosswalk_t2_por_presenca_no_detalhe_com_gate():
    """D-T2-01 (contrato v1.2.0): sem BU web nem CEFT, a EFETIVADA do turno vem da presença das
    apuradoras no detalhe do turno + agregação do eleitorado, com gate por seção."""
    import pandas as pd
    from br2026.contract import validate
    from br2026.normalize import _construir_crosswalk
    ele = pd.DataFrame({
        "NR_TURNO": ["2"] * 6, "SG_UF": ["AC"] * 6, "CD_MUNICIPIO": ["1392"] * 6, "NR_ZONA": ["1"] * 6,
        "NR_SECAO":               ["10", "11", "12", "20", "21", "30"],
        "CD_TIPO_SECAO_AGREGADA": ["1",  "2",  "2",  "1",  "2",  "1"],
        "NR_SECAO_PRINCIPAL":     ["-1", "10", "10", "-1", "20", "-1"],
        "NR_LOCAL_VOTACAO": ["1015"] * 6, "NR_LOCAL_VOTACAO_ORIGINAL": ["-1"] * 6,
        "QT_ELEITOR_SECAO": ["100"] * 6,
    })
    # 12: esperada agregada mas tem apuração própria (conflito); 30: própria sem registro no turno
    det = pd.DataFrame({"NR_ZONA": ["1", "1", "1"], "NR_SECAO": ["10", "12", "20"]})
    cw = _construir_crosswalk(ele, pd.DataFrame(), "e" * 64, "", "AC", 2,
                              detalhe_df=det, sha_det="d" * 64)
    validate(cw, "section_crosswalk")
    ef = cw[cw.status_correspondencia == "EFETIVADA"].set_index("nr_secao")
    assert set(ef.fonte) == {"detalhe+eleitorado_local_votacao"} and set(ef.source_id) == {"d" * 64}
    assert ef.loc["0010", "tipo_correspondencia"] == "PRINCIPAL_COM_AGREGADAS"
    assert ef.loc["0011", "tipo_correspondencia"] == "AGREGADA_EM_OUTRA" and ef.loc["0011", "nr_secao_apuradora"] == "0010"
    assert ef.loc["0012", "tipo_correspondencia"] == "AMBIGUA" and bool(ef.loc["0012", "flag_ambigua"])
    assert ef.loc["0021", "nr_secao_apuradora"] == "0020"
    assert "0030" not in ef.index                     # sem registro no turno: painel exclui
    esp = cw[cw.status_correspondencia == "ESPERADA"].set_index("nr_secao")
    assert len(esp) == 6 and esp.loc["0030", "tipo_correspondencia"] == "SEM_APURACAO"
