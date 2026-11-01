"""Testes offline da normalização (M3) — `br2026.normalize.run`.

Usam brutos sintéticos (formato TSE real) num projeto temporário, sem rede e sem
tocar o staging real do piloto. Cobrem: validação do contrato, `tipo_votavel`,
sentinela de `sq_candidato`, padding de identificadores, flags de identidade
(inclusive indeterminada por anulados), idempotência por UF/turno e bloqueio do
2º turno.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures" / "data"))

from br2026.panel.run import staging_path  # noqa: E402
from br2026.contract import validate, validate_parquet, ContractError  # noqa: E402
from br2026.normalize import NormalizeError, run  # noqa: E402
from synth_raw import montar_raw, sha256_zip, total, voto  # noqa: E402


def _cenario_padrao(raiz):
    """AC/T1 com 2 seções: uma normal, uma com anulados separados (>0)."""
    votos = [
        voto("AC", "1", "10", "1201", "13", "280002542548", "10"),
        voto("AC", "1", "10", "1201", "95", "-1", "2"),
        voto("AC", "1", "10", "1201", "96", "-1", "1"),
        voto("AC", "1", "11", "1201", "13", "280002542548", "7"),
    ]
    tot = [
        # aptos=14 comp=10 abst=4 | nom=10+7 leg=0 bra=2 nul=1 → comp 13? ajuste abaixo
        total("AC", "1", "10", "1201", 17, 13, 4, 10, 0, 2, 1),
        total("AC", "1", "11", "1201", 10, 8, 2, 7, 0, 0, 1, anul=5),
    ]
    montar_raw(raiz, votos, tot)


def test_staging_valida_pelo_contrato(tmp_path):
    _cenario_padrao(tmp_path)
    res = run("AC", 1, tmp_path)
    assert res.bloqueios == ()
    for tabela in ("votes_long", "section_turn"):
        df = validate_parquet(staging_path(tmp_path / "data" / "staging", tabela), tabela)
        assert not df.empty


def test_tipo_votavel_e_sentinela_sq(tmp_path):
    _cenario_padrao(tmp_path)
    run("AC", 1, tmp_path)
    vl = validate_parquet(staging_path(tmp_path / "data" / "staging", "votes_long"), "votes_long")

    por_nr = {int(r.nr_votavel): r for r in vl.itertuples()}
    assert por_nr[13].tipo_votavel == "NOMINAL"
    assert por_nr[13].sq_candidato == "280002542548"
    assert por_nr[95].tipo_votavel == "BRANCO"
    assert por_nr[96].tipo_votavel == "NULO"
    # sentinela -1 vira nulo nos não nominais (contrato: nulo para branco/nulo/legenda)
    assert pd.isna(por_nr[95].sq_candidato)
    assert pd.isna(por_nr[96].sq_candidato)


def test_identificadores_sao_preenchidos_com_zeros(tmp_path):
    _cenario_padrao(tmp_path)
    run("AC", 1, tmp_path)
    st = validate_parquet(staging_path(tmp_path / "data" / "staging", "section_turn"), "section_turn")

    r = st.iloc[0]
    assert r.cd_municipio_tse == "1201" or r.cd_municipio_tse == "01201"
    assert len(r.cd_municipio_tse) == 5 and r.cd_municipio_tse.startswith("0")
    assert r.nr_zona == "0001"
    assert r.nr_secao == "0010"


def test_flags_identidade_marcam_e_nao_removem(tmp_path):
    _cenario_padrao(tmp_path)
    res = run("AC", 1, tmp_path)
    st = validate_parquet(staging_path(tmp_path / "data" / "staging", "section_turn"), "section_turn")

    assert len(st) == 2, "nenhuma linha pode ser removida por violar identidade"
    # seção 10: aptos 17 == 13+4 ok; comp 13 == 10+0+2+1 ok
    s10 = st[st.nr_secao == "0010"].iloc[0]
    assert bool(s10.flag_identidade_aptos) is True
    assert bool(s10.flag_identidade_comparecimento) is True
    # seção 11: anulados=5 > 0 → comparecimento indeterminado, flag nula (v1.1)
    s11 = st[st.nr_secao == "0011"].iloc[0]
    assert pd.isna(s11.flag_identidade_comparecimento)
    assert any("indeterminado" in a for a in res.avisos)


def test_flag_identidade_aptos_viola_e_marcada(tmp_path):
    votos = [voto("AC", "1", "10", "1201", "13", "111", "5")]
    # aptos 10 mas comp 8 + abst 1 = 9 ≠ 10 → identidade de aptos violada, mantida
    tot = [total("AC", "1", "10", "1201", 10, 8, 1, 5, 0, 0, 0)]
    montar_raw(raiz := tmp_path, votos, tot)
    res = run("AC", 1, raiz)
    st = validate_parquet(staging_path(raiz / "data" / "staging", "section_turn"), "section_turn")

    assert len(st) == 1
    assert bool(st.iloc[0].flag_identidade_aptos) is False
    assert any("aptos" in a and "violada" in a for a in res.avisos)


def test_source_id_vem_do_manifesto(tmp_path):
    _cenario_padrao(tmp_path)
    run("AC", 1, tmp_path)
    sha_v = sha256_zip(tmp_path, "votacao_secao_2026_BR")
    sha_d = sha256_zip(tmp_path, "detalhe_votacao_secao_2026")
    vl = validate_parquet(staging_path(tmp_path / "data" / "staging", "votes_long"), "votes_long")
    st = validate_parquet(staging_path(tmp_path / "data" / "staging", "section_turn"), "section_turn")
    assert set(vl.source_id.unique()) == {sha_v}
    assert set(st.source_id.unique()) == {sha_d}


def test_idempotencia_por_uf_turno(tmp_path):
    votos = [
        voto("AC", "1", "10", "1201", "13", "111", "5"),
        voto("RS", "2", "20", "4301", "13", "111", "9"),
    ]
    tot = [
        total("AC", "1", "10", "1201", 10, 8, 2, 5, 0, 0, 0),
        total("RS", "2", "20", "4301", 12, 9, 3, 9, 0, 0, 0),
    ]
    montar_raw(raiz := tmp_path, votos, tot)
    run("AC", 1, raiz)
    run("RS", 1, raiz)
    run("AC", 1, raiz)   # reprocessa AC: não pode duplicar

    st = validate_parquet(staging_path(raiz / "data" / "staging", "section_turn"), "section_turn")
    assert sorted(st.sg_uf.unique()) == ["AC", "RS"]
    assert len(st) == 2
    ac = st[st.sg_uf == "AC"]
    assert len(ac) == 1, "reprocessar AC não pode duplicar linhas"


def test_segundo_turno_bloqueado_sem_inventar_dado(tmp_path):
    _cenario_padrao(tmp_path)
    res = run("AC", 2, tmp_path)
    assert any("AUSENTE_EM_26_10" in b for b in res.bloqueios)
    assert not (staging_path(tmp_path / "data" / "staging", "votes_long")).exists()
    assert not (staging_path(tmp_path / "data" / "staging", "section_turn")).exists()


def test_uf_sem_dados_vira_bloqueio(tmp_path):
    votos = [voto("AC", "1", "10", "1201", "13", "111", "5")]
    tot = [total("AC", "1", "10", "1201", 10, 8, 2, 5, 0, 0, 0)]
    montar_raw(raiz := tmp_path, votos, tot)
    res = run("MG", 1, raiz)   # MG não tem linha no bruto sintético
    assert any("nenhum" in b for b in res.bloqueios)


def test_manifesto_ausente_levanta_erro(tmp_path):
    with pytest.raises(NormalizeError):
        run("AC", 1, tmp_path)
