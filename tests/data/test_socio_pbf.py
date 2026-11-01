"""Testes de unidade, integridade e conformidade de contrato para o módulo socio_pbf (Handoff 35)."""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from br2026.ingest import socio_pbf as sp

MOCK_MAPPING = pd.DataFrame([
    {"sg_uf": "AC", "cd_municipio_tse": "01007", "cd_municipio_ibge": "1200138", "nm_municipio": "Bujari"},
    {"sg_uf": "AC", "cd_municipio_tse": "01015", "cd_municipio_ibge": "1200179", "nm_municipio": "Capixaba"},
    {"sg_uf": "MT", "cd_municipio_tse": "99999", "cd_municipio_ibge": "5101837", "nm_municipio": "Boa Esperança do Norte"},
])

MOCK_SIAFI_TO_IBGE = {
    "0001": "1200138",
    "0002": "1200179",
}

MOCK_DOMICILIOS = {
    "1200138": 3000.0,
    "1200179": 2000.0,
}

SYNTHETIC_PBF_CSV = (
    "MÊS COMPETÊNCIA;MÊS REFERÊNCIA;UF;CÓDIGO MUNICÍPIO SIAFI;NOME MUNICÍPIO;CPF FAVORECIDO;NIS FAVORECIDO;NOME FAVORECIDO;VALOR PARCELA\n"
    "202406;202406;AC;0001;BUJARI;***.111.111-**;10000000001;PESSOA TESTE 1;600,00\n"
    "202406;202405;AC;0001;BUJARI;***.111.111-**;10000000001;PESSOA TESTE 1;300,50\n"  # parcela retroativa para o mesmo NIS
    "202406;202406;AC;0001;BUJARI;***.111.111-**;10000000001;PESSOA TESTE 1;600,00\n"  # duplicidade técnica
    "202406;202406;AC;0002;CAPIXABA;***.222.222-**;20000000002;PESSOA TESTE 2;1.200,00\n"  # valor com ponto e vírgula
    "202406;202406;AC;0002;CAPIXABA;***.333.333-**;0;PESSOA TESTE 3;400,00\n"             # NIS zero/inválido
    "202405;202405;AC;0001;BUJARI;***.444.444-**;40000000004;PESSOA TESTE 4;500,00\n"    # competência divergente (deve ser rejeitada)
)


def test_parse_pbf_stream_audits_integrity_and_cents():
    stream = io.StringIO(SYNTHETIC_PBF_CSV)
    totals, audit = sp.parse_pbf_stream(stream, expected_comp="202406")

    # Linha com competência 202405 foi descartada
    assert audit["linhas_totais"] == 6
    assert audit["linhas_aceitas"] == 5
    assert audit["linhas_competencia_divergente"] == 1

    # Duplicidade técnica e repetição de NIS detectadas
    assert audit["repeticoes_nis_no_recorte"] == 2
    assert audit["duplicidades_tecnicas_comp_ref_nis"] == 1
    assert audit["identificadores_nis_invalidos_ou_ausentes"] == 1
    assert audit["nis_distintos_unicos"] == 2

    # Verificação de centavos acumulados
    # SIAFI 0001: 600,00 + 300,50 + 600,00 = 1500,50 -> 150050 centavos
    assert totals["0001"][0] == 3
    assert totals["0001"][1] == 150050

    # SIAFI 0002: 1200,00 + 400,00 = 1600,00 -> 160000 centavos
    assert totals["0002"][0] == 2
    assert totals["0002"][1] == 160000

    assert audit["valor_total_centavos"] == 310050
    assert audit["valor_total_reais"] == 3100.50


def test_no_pii_leaks_in_output():
    """Garante que nenhum identificador (CPF, NIS, Nome) vaze na auditoria ou no DataFrame."""
    stream = io.StringIO(SYNTHETIC_PBF_CSV)
    totals, audit = sp.parse_pbf_stream(stream, expected_comp="202406")
    df_long = sp.build_pbf_long_contract(
        totals=totals,
        mapping_df=MOCK_MAPPING,
        siafi_to_ibge=MOCK_SIAFI_TO_IBGE,
        domicilios_map=MOCK_DOMICILIOS,
        source_id="b" * 64,
        periodo="2024-06",
    )

    audit_str = json.dumps(audit)
    df_str = df_long.to_string()

    # Nenhum NIS de teste presente
    for forbidden in ["10000000001", "20000000002", "40000000004"]:
        assert forbidden not in audit_str
        assert forbidden not in df_str

    # Nenhum CPF ou nome presente
    for forbidden in ["111.111", "222.222", "PESSOA TESTE"]:
        assert forbidden not in audit_str
        assert forbidden not in df_str


def test_build_pbf_long_contract_and_administrative_ratio():
    stream = io.StringIO(SYNTHETIC_PBF_CSV)
    totals, _ = sp.parse_pbf_stream(stream, expected_comp="202406")
    df_long = sp.build_pbf_long_contract(
        totals=totals,
        mapping_df=MOCK_MAPPING,
        siafi_to_ibge=MOCK_SIAFI_TO_IBGE,
        domicilios_map=MOCK_DOMICILIOS,
        source_id="b" * 64,
        periodo="2024-06",
    )

    sp.validate_socio_pbf_contract(df_long)

    # 3 municípios × 4 indicadores = 12 linhas
    assert len(df_long) == 12

    # Verifica Bujari (1200138)
    buj = df_long.set_index(["cd_municipio_ibge", "indicador"]).loc["1200138"]
    assert buj.loc["registros_pagamento_pbf", "valor"] == 3.0
    assert buj.loc["valor_total_bolsa_familia", "valor"] == 1500.50
    # Média: 1500.50 / 3 = 500.1667
    assert buj.loc["beneficio_medio_bolsa_familia", "valor"] == pytest.approx(500.1667, 1e-4)

    # Razão administrativa por 100 domicílios: 100 * 3 / 3000 = 0.1
    assert buj.loc["registros_pbf_por_100_domicilios_2022", "valor"] == 0.1
    assert buj.loc["registros_pbf_por_100_domicilios_2022", "numerador"] == 3.0
    assert buj.loc["registros_pbf_por_100_domicilios_2022", "denominador"] == 3000.0

    # Município não instalado ou sem dados na época (5101837)
    ben = df_long.set_index(["cd_municipio_ibge", "indicador"]).loc["5101837"]
    assert pd.isna(ben.loc["registros_pagamento_pbf", "valor"])
    assert ben.loc["registros_pagamento_pbf", "motivo_ausencia"] == "municipio_instalado_pos_2023"


def test_contract_validation_rejects_header_mismatch():
    bad_stream = io.StringIO("COL1;COL2;COL3\n1;2;3\n")
    with pytest.raises(ValueError, match="Cabeçalho PBF incompatível"):
        sp.parse_pbf_stream(bad_stream)


def test_reconcile_pbf_exact_penny_and_count(tmp_path):
    stream = io.StringIO(SYNTHETIC_PBF_CSV)
    totals, _ = sp.parse_pbf_stream(stream, expected_comp="202406")

    # Mapeia como se fosse RS
    mapping_rs = pd.DataFrame([
        {"sg_uf": "RS", "cd_municipio_tse": "85000", "cd_municipio_ibge": "4300034", "nm_municipio": "Aceguá"}
    ])
    siafi_rs = {"0001": "4300034"}
    df_long = sp.build_pbf_long_contract(totals, mapping_rs, siafi_rs, None, "c" * 64)

    legacy_file = tmp_path / "test_pbf_legacy_rs.parquet"
    legacy_df = pd.DataFrame([
        {"id_municipio_ibge": "4300034", "registros_pagamento_pbf": 3, "valor_total_bolsa_familia": 1500.50}
    ])
    legacy_df.to_parquet(legacy_file, index=False)

    try:
        rec = sp.reconcile_pbf_rs_against_legacy(df_long, legacy_file)
        assert rec["status"] == "RECONCILIADO_EXATO"
        assert rec["municipios_rs"] == 1
        assert rec["total_registros_nacional_rs"] == 3
        assert rec["total_valor_reais_nacional_rs"] == 1500.50
        assert rec["municipios_com_divergencia_registros"] == 0
        assert rec["municipios_com_divergencia_valor"] == 0
    finally:
        if legacy_file.exists():
            legacy_file.unlink()
