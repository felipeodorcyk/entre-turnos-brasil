"""Staging particionado por UF × turno e leitura agregada do perfil (expansão nacional).

O normalize grava cada UF/turno numa partição própria, e a leitura do diretório devolve a
mesma tabela que o arquivo único do layout anterior. O perfil é somado no DuckDB e precisa
dar o mesmo resultado que a soma feita no pandas sobre o bruto inteiro.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from br2026.contract import read_table  # noqa: E402
from br2026.normalize import (  # noqa: E402
    _COLS_PERFIL, _DIMENSOES_PERFIL, NormalizeError, _construir_profiles, _gravar_mesa,
    _ler_perfil_agregado, _particao_vigente,
)


def _vl(uf: str, turno: int, n: int, fonte: str = "a" * 64) -> pd.DataFrame:
    return pd.DataFrame({
        "sg_uf": pd.Series([uf] * n, dtype="string"),
        "nr_turno": pd.Series([turno] * n, dtype="int8"),
        "cd_municipio_tse": pd.Series([f"{i:05d}" for i in range(n)], dtype="string"),
        "nr_zona": pd.Series(["0001"] * n, dtype="string"),
        "nr_secao": pd.Series([f"{i:04d}" for i in range(n)], dtype="string"),
        "cd_cargo": pd.Series([1] * n, dtype="int16"),
        "id_bu": pd.Series([None] * n, dtype=object),   # coluna inteiramente nula
        "source_id": pd.Series([fonte] * n, dtype="string"),
    })


def test_particoes_independentes_por_uf_e_turno(tmp_path):
    alvo = tmp_path / "votes_long.parquet"
    assert _gravar_mesa(_vl("AC", 1, 3), alvo, "AC", 1) == 3
    assert _gravar_mesa(_vl("RS", 1, 5), alvo, "RS", 1) == 8
    assert _gravar_mesa(_vl("AC", 2, 2), alvo, "AC", 2) == 10
    pasta = tmp_path / "votes_long"
    assert sorted(p.name for p in pasta.glob("*.parquet")) == ["AC_T1.parquet", "AC_T2.parquet", "RS_T1.parquet"]
    antes = (pasta / "RS_T1.parquet").read_bytes()
    # regravar AC/T1 não toca as outras partições
    assert _gravar_mesa(_vl("AC", 1, 4), alvo, "AC", 1) == 11
    assert (pasta / "RS_T1.parquet").read_bytes() == antes
    assert not alvo.exists()


def test_gravacao_recusa_linhas_de_outra_fatia(tmp_path):
    with pytest.raises(NormalizeError, match="outra UF"):
        _gravar_mesa(_vl("RS", 1, 2), tmp_path / "votes_long.parquet", "AC", 1)
    with pytest.raises(NormalizeError, match="outro turno"):
        _gravar_mesa(_vl("AC", 2, 2), tmp_path / "votes_long.parquet", "AC", 1)


def test_migracao_do_arquivo_unico_preserva_a_tabela(tmp_path):
    unico = pd.concat([_vl("AC", 1, 3), _vl("AC", 2, 2), _vl("MG", 1, 4)], ignore_index=True)
    alvo = tmp_path / "votes_long.parquet"
    unico.to_parquet(alvo, index=False)
    lido_antes = pd.read_parquet(alvo)
    # a primeira gravação migra o arquivo único e só então troca a fatia pedida
    assert _gravar_mesa(_vl("MG", 2, 1), alvo, "MG", 2) == 10
    assert not alvo.exists()
    depois = read_table(tmp_path / "votes_long", "votes_long")
    sem_nova = depois[~((depois.sg_uf == "MG") & (depois.nr_turno == 2))].reset_index(drop=True)
    pd.testing.assert_frame_equal(sem_nova, lido_antes)
    assert depois["id_bu"].isna().all()


def test_particao_vigente_confere_a_fonte(tmp_path):
    alvo = tmp_path / "profiles.parquet"
    df = _vl("AC", 1, 2).drop(columns=["nr_turno"])
    _gravar_mesa(df, alvo, "AC", None, ordenar_por=("sg_uf", "cd_municipio_tse"))
    assert _particao_vigente(alvo, "AC", None, "a" * 64)
    assert not _particao_vigente(alvo, "AC", None, "b" * 64)
    assert not _particao_vigente(alvo, "RS", None, "a" * 64)


# --------------------------------------------------------------------------- #
# perfil: soma no DuckDB = soma no pandas sobre o bruto inteiro                 #
# --------------------------------------------------------------------------- #


def _linha(secao, gen, faixa, esc, civil, raca, qt, mun="1201", zona="10", ds_gen=None):
    return {"AA_ELEICAO": "2026", "DT_GERACAO": "14/07/2026", "SG_UF": "AC",
            "CD_MUNICIPIO": mun, "NR_ZONA": zona, "NR_SECAO": secao,
            "CD_GENERO": gen, "DS_GENERO": ds_gen if ds_gen is not None else f"G{gen}",
            "CD_FAIXA_ETARIA": faixa, "DS_FAIXA_ETARIA": f"F{faixa}",
            "CD_GRAU_ESCOLARIDADE": esc, "DS_GRAU_ESCOLARIDADE": f"E{esc}",
            "CD_ESTADO_CIVIL": civil, "DS_ESTADO_CIVIL": f"C{civil}",
            "CD_RACA_COR": raca, "DS_RACA_COR": f"R{raca}", "QT_ELEITORES": qt}


def _escrever(tmp_path: Path, linhas: list[dict]) -> Path:
    caminho = tmp_path / "perfil.csv"
    df = pd.DataFrame(linhas)[list(_COLS_PERFIL)]
    df.to_csv(caminho, sep=";", index=False, encoding="latin-1")
    return caminho


def _referencia_pandas(caminho: Path) -> pd.DataFrame:
    """A soma do layout anterior: bruto inteiro no pandas, uma cópia por dimensão."""
    bruto = pd.read_csv(caminho, sep=";", dtype=str, encoding="latin-1", keep_default_na=False,
                        na_values=[""])
    partes = []
    for dim, cd, ds in _DIMENSOES_PERFIL:
        p = bruto[["AA_ELEICAO", "DT_GERACAO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]].copy()
        p["DIMENSAO"], p["CD_CATEGORIA"], p["DS_CATEGORIA"] = dim, bruto[cd], bruto[ds]
        p["QT_ELEITORES"], p["QT_INVALIDOS"] = pd.to_numeric(bruto["QT_ELEITORES"]), 0
        partes.append(p)
    return pd.concat(partes, ignore_index=True)


def test_perfil_agregado_igual_a_soma_no_pandas(tmp_path):
    linhas = [
        _linha("1", "2", "1", "3", "1", "1", "5"),
        _linha("1", "2", "1", "3", "1", "2", "7"),          # mesma marginal, outra raça
        _linha("1", "4", "2", "3", "1", "1", "2"),
        _linha("01", "2", "1", "3", "1", "1", "1"),         # zfill colide com a seção "1"
        _linha("2", "", "1", "3", "1", "1", "4", ds_gen=""),  # categoria vazia
        _linha("2", "-1", "1", "3", "1", "1", "3", ds_gen="NÃO INFORMADO"),
        _linha("3", " 2", "1", "3", "1", "1", "6", mun=" 1201"),  # espaços no bruto
    ]
    caminho = _escrever(tmp_path, linhas)
    novo = _construir_profiles(_ler_perfil_agregado(caminho, "AC"), "f" * 64)
    ref = _construir_profiles(_referencia_pandas(caminho), "f" * 64)
    pd.testing.assert_frame_equal(novo.reset_index(drop=True), ref.reset_index(drop=True),
                                  check_dtype=False)
    secao1 = novo[(novo.nr_secao == "0001") & (novo.dimensao == "GENERO")]
    assert dict(zip(secao1.cd_categoria, secao1.qt_eleitores)) == {"2": 13, "4": 2}
    assert novo.groupby("dimensao").qt_eleitores.sum().nunique() == 1


def test_perfil_agregado_recusa_quantidade_invalida(tmp_path):
    caminho = _escrever(tmp_path, [_linha("1", "2", "1", "3", "1", "1", "5"),
                                   _linha("2", "2", "1", "3", "1", "1", "x")])
    with pytest.raises(NormalizeError, match="QT_ELEITORES"):
        _construir_profiles(_ler_perfil_agregado(caminho, "AC"), "f" * 64)
