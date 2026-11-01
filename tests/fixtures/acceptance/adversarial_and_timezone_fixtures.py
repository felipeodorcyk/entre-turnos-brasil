"""Fixtures para testes adversos, não-colisão geográfica e fusos horários da Frente C.

Cobre:
1. Casos adversos: duplicata inserida, turno trocado, arquivo truncado,
   ausente virando zero, chave inválida.
2. Identificadores idênticos em UFs distintas (AC vs SP vs ZZ) sem colisão.
3. Seção com população variável (aptos divergentes).
4. Fusos horários múltiplos e semântica de fechamento (rejeição de transmissão/emissão).
"""
from __future__ import annotations

import pandas as pd


# -----------------------------------------------------------------------------
# 2. Fixture de Não-Colisão entre UFs e População Variável
# -----------------------------------------------------------------------------
# Três seções com exatamente os mesmos identificadores locais (município 00001,
# zona 0001, seção 0001) em três UFs distintas: AC, SP e ZZ (exterior).
# NUNCA podem colidir ou ser agrupadas na mesma unidade.
#
# Seção SP-00001-0001-0001: aptos T1 = 200, aptos T2 = 210.
# -> flag_aptos_divergente: True, status: PAREADA
# -----------------------------------------------------------------------------

def build_multi_uf_variable_pop_dfs():
    st_rows = [
        # AC
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "qt_aptos": 100, "qt_comparecimento": 80,
         "qt_abstencoes": 20, "qt_votos_nominais": 75, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0001", "source_id": "sha_ac"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "qt_aptos": 100, "qt_comparecimento": 85,
         "qt_abstencoes": 15, "qt_votos_nominais": 80, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0001", "source_id": "sha_ac"},

        # SP (com aptos divergentes: 200 no T1, 210 no T2)
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "SP", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "qt_aptos": 200, "qt_comparecimento": 160,
         "qt_abstencoes": 40, "qt_votos_nominais": 150, "qt_votos_legenda": 0, "qt_votos_brancos": 5,
         "qt_votos_nulos": 5, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0001", "source_id": "sha_sp"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "SP", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "qt_aptos": 210, "qt_comparecimento": 170,
         "qt_abstencoes": 40, "qt_votos_nominais": 160, "qt_votos_legenda": 0, "qt_votos_brancos": 6,
         "qt_votos_nulos": 4, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0001", "source_id": "sha_sp"},

        # ZZ (Exterior - aptos iguais)
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "ZZ", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "qt_aptos": 300, "qt_comparecimento": 150,
         "qt_abstencoes": 150, "qt_votos_nominais": 140, "qt_votos_legenda": 0, "qt_votos_brancos": 5,
         "qt_votos_nulos": 5, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0001", "source_id": "sha_zz"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "ZZ", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "qt_aptos": 300, "qt_comparecimento": 160,
         "qt_abstencoes": 140, "qt_votos_nominais": 150, "qt_votos_legenda": 0, "qt_votos_brancos": 6,
         "qt_votos_nulos": 4, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0001", "source_id": "sha_zz"},
    ]

    cw_rows = [
        {"ano": 2026, "nr_turno": t, "sg_uf": uf, "cd_municipio_tse": "00001", "nr_zona": "0001",
         "nr_secao": "0001", "nr_secao_apuradora": "0001", "nr_local_votacao": "0001",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": f"sha_cw_{uf}_{t}"}
        for uf in ("AC", "SP", "ZZ") for t in (1, 2)
    ]

    vl_rows = [
        # AC
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 35,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_ac"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 40,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_ac"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 38,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_ac"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 42,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_ac"},

        # SP
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "SP", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 80,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_sp"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "SP", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 70,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_sp"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "SP", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 85,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_sp"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "SP", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 75,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_sp"},

        # ZZ
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "ZZ", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 90,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_zz"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "ZZ", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 50,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_zz"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "ZZ", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 100,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_zz"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "ZZ", "cd_municipio_tse": "00001",
         "nr_zona": "0001", "nr_secao": "0001", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 50,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_zz"},
    ]

    st = pd.DataFrame(st_rows)
    cw = pd.DataFrame(cw_rows)
    vl = pd.DataFrame(vl_rows)

    for c in ("qt_aptos", "qt_comparecimento", "qt_abstencoes", "qt_votos_nominais",
              "qt_votos_legenda", "qt_votos_brancos", "qt_votos_nulos", "qt_votos_anulados_apu_sep"):
        st[c] = st[c].astype("Int64")
    vl["qt_votos"] = vl["qt_votos"].astype("Int64")
    vl["sq_candidato"] = vl["sq_candidato"].astype("Int64")

    return st, cw, vl


# -----------------------------------------------------------------------------
# 3. Fixture de Fusos Horários e Semântica de Fechamento
# -----------------------------------------------------------------------------

def build_closure_timezone_dfs():
    """Gera DataFrame de closure cobrindo 4 fusos e casos de semântica."""
    rows = [
        # AC (America/Rio_Branco, UTC-5): 15:05 local = 17:05 Brasília
        {"ano": 2026, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0001", "id_registro": "rec1", "semantica": "ENCERRAMENTO_URNA",
         "fuso_documentado": "America/Rio_Branco", "ts_bruto": "2026-10-04 15:05:00",
         "ts_brasilia": None, "motivo_ausencia": None, "flag_reemissao": False,
         "flag_substituicao_urna": False, "source_id": "sha_cl"},

        # AM (America/Manaus, UTC-4): 16:10 local = 17:10 Brasília
        {"ano": 2026, "nr_turno": 1, "sg_uf": "AM", "cd_municipio_tse": "02001", "nr_zona": "0001",
         "nr_secao": "0001", "id_registro": "rec2", "semantica": "ENCERRAMENTO_URNA",
         "fuso_documentado": "America/Manaus", "ts_bruto": "2026-10-04 16:10:00",
         "ts_brasilia": None, "motivo_ausencia": None, "flag_reemissao": False,
         "flag_substituicao_urna": False, "source_id": "sha_cl"},

        # SP (America/Sao_Paulo, UTC-3): 17:20 local = 17:20 Brasília
        {"ano": 2026, "nr_turno": 1, "sg_uf": "SP", "cd_municipio_tse": "71072", "nr_zona": "0001",
         "nr_secao": "0001", "id_registro": "rec3", "semantica": "ENCERRAMENTO_URNA",
         "fuso_documentado": "America/Sao_Paulo", "ts_bruto": "2026-10-04 17:20:00",
         "ts_brasilia": None, "motivo_ausencia": None, "flag_reemissao": False,
         "flag_substituicao_urna": False, "source_id": "sha_cl"},

        # FN (America/Noronha, UTC-2): 19:30 local = 18:30 Brasília
        {"ano": 2026, "nr_turno": 1, "sg_uf": "PE", "cd_municipio_tse": "25000", "nr_zona": "0001",
         "nr_secao": "0001", "id_registro": "rec4", "semantica": "ENCERRAMENTO_URNA",
         "fuso_documentado": "America/Noronha", "ts_bruto": "2026-10-04 19:30:00",
         "ts_brasilia": None, "motivo_ausencia": None, "flag_reemissao": False,
         "flag_substituicao_urna": False, "source_id": "sha_cl"},

        # Caso FUSO_NAO_DOCUMENTADO: fuso vazio (string vazia para evitar TypeError com nan)
        {"ano": 2026, "nr_turno": 1, "sg_uf": "BA", "cd_municipio_tse": "30001", "nr_zona": "0001",
         "nr_secao": "0001", "id_registro": "rec5", "semantica": "ENCERRAMENTO_URNA",
         "fuso_documentado": "", "ts_bruto": "2026-10-04 17:10:00",
         "ts_brasilia": None, "motivo_ausencia": None, "flag_reemissao": False,
         "flag_substituicao_urna": False, "source_id": "sha_cl"},

        # Caso Semântica NÃO ELEGÍVEL: transmissão passando por encerramento
        {"ano": 2026, "nr_turno": 1, "sg_uf": "RJ", "cd_municipio_tse": "60001", "nr_zona": "0001",
         "nr_secao": "0001", "id_registro": "rec6", "semantica": "RECEBIMENTO_BU_TSE",
         "fuso_documentado": "America/Sao_Paulo", "ts_bruto": "2026-10-04 17:40:00",
         "ts_brasilia": None, "motivo_ausencia": None, "flag_reemissao": False,
         "flag_substituicao_urna": False, "source_id": "sha_cl"},

        # Caso Conflito de Reemissão: dois registros com horários distintos de encerramento
        {"ano": 2026, "nr_turno": 1, "sg_uf": "MG", "cd_municipio_tse": "40001", "nr_zona": "0001",
         "nr_secao": "0001", "id_registro": "rec7a", "semantica": "ENCERRAMENTO_URNA",
         "fuso_documentado": "America/Sao_Paulo", "ts_bruto": "2026-10-04 17:05:00",
         "ts_brasilia": None, "motivo_ausencia": None, "flag_reemissao": True,
         "flag_substituicao_urna": False, "source_id": "sha_cl"},
        {"ano": 2026, "nr_turno": 1, "sg_uf": "MG", "cd_municipio_tse": "40001", "nr_zona": "0001",
         "nr_secao": "0001", "id_registro": "rec7b", "semantica": "ENCERRAMENTO_URNA",
         "fuso_documentado": "America/Sao_Paulo", "ts_bruto": "2026-10-04 17:45:00",
         "ts_brasilia": None, "motivo_ausencia": None, "flag_reemissao": True,
         "flag_substituicao_urna": False, "source_id": "sha_cl"},
    ]
    df = pd.DataFrame(rows)
    return df
