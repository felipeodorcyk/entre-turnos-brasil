"""Testes de unidade e conformidade de contrato para o módulo socio_rais (Handoff 35)."""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from br2026.ingest import socio_rais as sr


MOCK_TSE_IBGE = pd.DataFrame([
    {"sg_uf": "AC", "cd_municipio_tse": "01007", "cd_municipio_ibge": "1200138", "nm_municipio": "Bujari", "cd_municipio_ibge_6": "120013"},
    {"sg_uf": "AC", "cd_municipio_tse": "01015", "cd_municipio_ibge": "1200179", "nm_municipio": "Capixaba", "cd_municipio_ibge_6": "120017"},
    {"sg_uf": "MT", "cd_municipio_tse": "99999", "cd_municipio_ibge": "5101837", "nm_municipio": "Boa Esperança do Norte", "cd_municipio_ibge_6": "510183"},
])

MOCK_POP = pd.DataFrame([
    {"cd_municipio_ibge": "1200138", "variavel": "populacao_residente", "valor": 12000.0},
    {"cd_municipio_ibge": "1200179", "variavel": "populacao_residente", "valor": 8000.0},
])

SYNTHETIC_COMT = (
    '"Bairros SP - Código","Bairros Fortaleza - Código","Bairros RJ - Código","CNAE 2.0 Classe - Código",'
    '"CNAE 95 Classe - Código","Distritos SP - Código","Qtd Vínculos CLT","Qtd Vínculos Ativos",'
    '"Qtd Vínculos Estatutários","Ind Atividade Ano - Código","Ind CEI Vinculado - Código",'
    '"Ind Estab Participante PAT - Código","Ind RAIS Negativa - Código","Ind Estab Participante SIMPLES - Código",'
    '"Município - Código","Natureza Jurídica - Código","Região Adm DF - Código","CNAE 2.0 Subclasse - Codigo",'
    '"Tamanho Estabelecimento - Código","Tipo Estabelecimento - Código","UF - Código","IBGE Subsetor - Código","CEP Estab"\n'
    '999997,999997,999997," 9609299",9309,999997,5,10,5,1,0,9,0,0,120013,9999,999997," 9609299",1,5,12,21,14430000\n'
    '999997,999997,999997," 9609299",9309,999997,15,20,5,1,0,9,0,0,120013,9999,999997," 9609299",1,5,12,21,14430000\n'
    '999997,999997,999997," 8690999",8516,999997,0,0,0,1,0,9,0,0,120017,9999,999997," 8690999",2,5,12,22,38600150\n'
    '999997,999997,999997," 8690999",8516,999997,2,2,0,1,0,9,0,0,120017,9999,999997," 8690999",2,5,12,22,38600150\n'
)


def test_parse_rais_stream_aggregates_correctly():
    stream = io.StringIO(SYNTHETIC_COMT)
    totals, audit = sr.parse_rais_stream(stream)

    assert "120013" in totals
    assert totals["120013"]["vinculos_formais_total"] == 30  # 10 + 20
    assert totals["120013"]["vinculos_clt_total"] == 20      # 5 + 15
    assert totals["120013"]["vinculos_estatutarios_total"] == 10  # 5 + 5
    assert totals["120013"]["estabelecimentos_total"] == 2

    assert "120017" in totals
    assert totals["120017"]["vinculos_formais_total"] == 2
    assert totals["120017"]["vinculos_clt_total"] == 2
    assert totals["120017"]["vinculos_estatutarios_total"] == 0
    assert totals["120017"]["estabelecimentos_total"] == 2

    assert audit["linhas_processadas"] == 4
    assert audit["vinculos_formais_total_brasil"] == 32
    assert audit["vinculos_clt_total_brasil"] == 22
    assert audit["vinculos_estatutarios_total_brasil"] == 10


def test_build_rais_long_contract_structure_and_rates():
    stream = io.StringIO(SYNTHETIC_COMT)
    totals, _ = sr.parse_rais_stream(stream)
    df_long = sr.build_rais_long_contract(
        totals=totals,
        mapping_df=MOCK_TSE_IBGE,
        pop_df=MOCK_POP,
        source_id="f" * 64,
        periodo="2023-12-31",
    )

    sr.validate_socio_contract(df_long)

    # 3 municípios no mapping × 4 indicadores = 12 linhas
    assert len(df_long) == 12

    # Verifica Bujari (1200138)
    buj = df_long.set_index(["cd_municipio_ibge", "indicador"]).loc["1200138"]
    assert buj.loc["vinculos_formais_total", "valor"] == 30.0
    assert buj.loc["vinculos_clt_total", "valor"] == 20.0
    assert buj.loc["vinculos_estatutarios_total", "valor"] == 10.0

    # Taxa por mil hab: 1000 * 30 / 12000 = 2.5
    assert buj.loc["vinculos_formais_por_mil_hab", "valor"] == 2.5
    assert buj.loc["vinculos_formais_por_mil_hab", "numerador"] == 30.0
    assert buj.loc["vinculos_formais_por_mil_hab", "denominador"] == 12000.0

    # Verifica município novo sem declaração (Boa Esperança do Norte 5101837)
    ben = df_long.set_index(["cd_municipio_ibge", "indicador"]).loc["5101837"]
    assert pd.isna(ben.loc["vinculos_formais_total", "valor"])
    assert ben.loc["vinculos_formais_total", "motivo_ausencia"] == "municipio_instalado_pos_2023"


def test_contract_validation_rejects_missing_cols_and_pk_duplicates():
    df_bad = pd.DataFrame([{"sg_uf": "AC", "cd_municipio_ibge": "1200138"}])
    with pytest.raises(ValueError, match="Colunas ausentes no contrato longo"):
        sr.validate_socio_contract(df_bad)

    # DataFrame com chave duplicada
    stream = io.StringIO(SYNTHETIC_COMT)
    totals, _ = sr.parse_rais_stream(stream)
    df_valid = sr.build_rais_long_contract(totals, MOCK_TSE_IBGE, MOCK_POP, "0" * 64)
    df_dup = pd.concat([df_valid, df_valid.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="Violação de unicidade da chave primária"):
        sr.validate_socio_contract(df_dup)


def test_reconciliation_detects_match_and_reports_divergence(tmp_path):
    stream = io.StringIO(SYNTHETIC_COMT)
    totals, _ = sr.parse_rais_stream(stream)
    # Criar mapping simulando RS
    mapping_rs = pd.DataFrame([
        {"sg_uf": "RS", "cd_municipio_tse": "85000", "cd_municipio_ibge": "4300034", "nm_municipio": "Aceguá", "cd_municipio_ibge_6": "430003"}
    ])
    totals_rs = {"430003": {"vinculos_formais_total": 1339, "vinculos_clt_total": 1000, "vinculos_estatutarios_total": 339, "estabelecimentos_total": 50}}
    df_long = sr.build_rais_long_contract(totals_rs, mapping_rs, None, "a" * 64)

    # Legado com 1347 vínculos (divergência documentada do DEE de -8 vínculos)
    legacy_file = tmp_path / "test_legacy_rs.parquet"
    legacy_df = pd.DataFrame([{"id_municipio_ibge": "4300034", "vinculos_formais_total": 1347}])
    legacy_df.to_parquet(legacy_file, index=False)

    try:
        rec = sr.reconcile_rs_against_legacy(df_long, legacy_file)
        assert rec["status"] == "CONCILIADO_COM_DIVERGENCIA_DOCUMENTADA"
        assert rec["municipios_comparados"] == 1
        assert rec["diferenca_absoluta"] == -8.0
        assert "DEE-RS" in rec["nota_metodologica"]
    finally:
        if legacy_file.exists():
            legacy_file.unlink()
