"""Fixtures de aceite e oráculos independentes da Frente C (validação independente).

Calculados manualmente / por lógica independente sem reutilizar o código sob teste.
Cobre:
1. Seção duplicada
2. Seção agregada com grafo multi-seções e mudança entre turnos
3. UF/turno diferente e não-colisão geográfica
4. População variável (aptos divergentes T1 vs T2)
5. Dado ausente (preservação de <NA>, regras de exclusão contábil e apuração)
6. Fusos horários, semântica de fechamento e recusa de transmissão/emissão
7. Amostras oficiais de referência com URLs e hashes conhecidos
"""
from __future__ import annotations

import pandas as pd


# -----------------------------------------------------------------------------
# 1. Fixture de Agregação Complexa (Oráculo independente)
# -----------------------------------------------------------------------------
# Cenário de seções no município 01007 (AC, Zona 0001):
# - Seções 0010, 0011, 0012:
#   T1: 0011 agrega em 0010 (0010 apura 0010+0011). 0012 apura individualmente.
#   T2: 0012 agrega em 0011, que agrega em 0010 (0010 apura 0010+0011+0012).
#   -> Componente conexo único une 0010, 0011, 0012 em uma única unidade: AC-01007-0001-0010
#   -> tipo_unidade: AGREGADO_SECOES, n_secoes_origem: 3
#   -> Valores calculados à mão:
#      T1: 0010 apura 100 aptos (Lula=30, Flavio=40, validos=80, comp=85, abst=15, brancos=3, nulos=2)
#          0012 apura 50 aptos (Lula=15, Flavio=20, validos=40, comp=42, abst=8, brancos=1, nulos=1)
#          Total esperado T1: aptos=150, validos=120, comp=127, abst=23, brancos=4, nulos=3, Lula=45, Flavio=60
#      T2: 0010 apura 150 aptos (Lula=55, Flavio=70, validos=130, comp=135, abst=15, brancos=3, nulos=2)
#          Total esperado T2: aptos=150, validos=130, comp=135, abst=15, brancos=3, nulos=2, Lula=55, Flavio=70
# - Seção 0020:
#   Individual nos dois turnos. T1 aptos=80, T2 aptos=80. Lula T1=35, Flavio T1=25. Lula T2=40, Flavio T2=30.
#   -> tipo_unidade: SECAO, n_secoes_origem: 1, status: PAREADA
# - Seção 0030:
#   Presente no T1, ausente no T2.
#   -> status: EXCLUIDA_AUSENTE_T2
# - Seção 0040:
#   Presente no T2, ausente no T1.
#   -> status: EXCLUIDA_AUSENTE_T1
# - Seção 0050:
#   Falha de contabilidade no T1 (comparecimento != válidos + brancos + nulos).
#   -> status: EXCLUIDA_CONTABILIDADE
# - Seção 0060:
#   Não apurada (st_secao_instalada=False no T1).
#   -> status: EXCLUIDA_NAO_APURADA
# - Seção 0070:
#   Crosswalk ambíguo (flag_ambigua=True).
#   -> status: EXCLUIDA_AMBIGUA
# -----------------------------------------------------------------------------

ORACLE_COMPLEX_EXPECTED = {
    "unidades": {
        "AC-01007-0001-0010": {
            "status": "PAREADA",
            "tipo": "AGREGADO_SECOES",
            "n_secoes_origem": 3,
            "qt_aptos_t1": 150,
            "qt_aptos_t2": 150,
            "qt_comparecimento_t1": 127,
            "qt_comparecimento_t2": 135,
            "qt_abstencoes_t1": 23,
            "qt_abstencoes_t2": 15,
            "qt_votos_validos_t1": 120,
            "qt_votos_validos_t2": 130,
            "qt_lula_t1": 45,
            "qt_lula_t2": 55,
            "qt_flavio_t1": 60,
            "qt_flavio_t2": 70,
            "qt_votos_brancos_t1": 4,
            "qt_votos_brancos_t2": 3,
            "qt_votos_nulos_t1": 3,
            "qt_votos_nulos_t2": 2,
            "flag_aptos_divergente": False,
        },
        "AC-01007-0001-0020": {
            "status": "PAREADA",
            "tipo": "SECAO",
            "n_secoes_origem": 1,
            "qt_aptos_t1": 80,
            "qt_aptos_t2": 80,
            "qt_votos_validos_t1": 60,
            "qt_votos_validos_t2": 70,
            "qt_lula_t1": 35,
            "qt_lula_t2": 40,
            "qt_flavio_t1": 25,
            "qt_flavio_t2": 30,
            "flag_aptos_divergente": False,
        },
        "AC-01007-0001-0030": {
            "status": "EXCLUIDA_AUSENTE_T2",
            "tipo": "SECAO",
            "n_secoes_origem": 1,
        },
        "AC-01007-0001-0040": {
            "status": "EXCLUIDA_AUSENTE_T1",
            "tipo": "SECAO",
            "n_secoes_origem": 1,
        },
        "AC-01007-0001-0050": {
            "status": "EXCLUIDA_CONTABILIDADE",
            "tipo": "SECAO",
            "n_secoes_origem": 1,
        },
        "AC-01007-0001-0060": {
            "status": "EXCLUIDA_NAO_APURADA",
            "tipo": "SECAO",
            "n_secoes_origem": 1,
        },
        "AC-01007-0001-0070": {
            "status": "EXCLUIDA_AMBIGUA",
            "tipo": "SECAO",
            "n_secoes_origem": 1,
        },
    },
    "metricas_pareadas": {
        # Total das pareadas (AC-01007-0001-0010 + AC-01007-0001-0020):
        # Validos T1 = 120 + 60 = 180; Validos T2 = 130 + 70 = 200
        # Lula T1 = 45 + 35 = 80; Lula T2 = 55 + 40 = 95
        # Flavio T1 = 60 + 25 = 85; Flavio T2 = 70 + 30 = 100
        # Share Lula T1 = 80/180 = 4/9 = 0.444444...
        # Share Lula T2 = 95/200 = 19/40 = 0.475
        # Share Flavio T1 = 85/180 = 17/36 = 0.472222...
        # Share Flavio T2 = 100/200 = 0.50
        # Margem T1 = (80 - 85)/180 = -5/180 = -0.027777...
        # Margem T2 = (95 - 100)/200 = -5/200 = -0.025
        # Delta Lula = 95 - 80 = 15
        # Delta Flavio = 100 - 85 = 15
        # Delta Margem Votos = (95-100) - (80-85) = -5 - (-5) = 0
        "qt_validos_pareados_t1": 180,
        "qt_validos_pareados_t2": 200,
        "qt_lula_pareados_t1": 80,
        "qt_lula_pareados_t2": 95,
        "qt_flavio_pareados_t1": 85,
        "qt_flavio_pareados_t2": 100,
        "share_lula_pareados_t1": 80 / 180,
        "share_lula_pareados_t2": 95 / 200,
        "share_flavio_pareados_t1": 85 / 180,
        "share_flavio_pareados_t2": 100 / 200,
        "delta_lula": 15,
        "delta_flavio": 15,
        "delta_margem_votos": 0,
    },
}


def build_complex_oracle_dfs():
    """Gera DataFrames sintéticos estritamente estruturados para o cenário complexo."""
    section_turn_rows = [
        # T1
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0010", "cd_cargo": 1, "qt_aptos": 100, "qt_comparecimento": 85,
         "qt_abstencoes": 15, "qt_votos_nominais": 80, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0101",
         "source_id": "sha_t1_sec"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0012", "cd_cargo": 1, "qt_aptos": 50, "qt_comparecimento": 42,
         "qt_abstencoes": 8, "qt_votos_nominais": 40, "qt_votos_legenda": 0, "qt_votos_brancos": 1,
         "qt_votos_nulos": 1, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0101",
         "source_id": "sha_t1_sec"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0020", "cd_cargo": 1, "qt_aptos": 80, "qt_comparecimento": 65,
         "qt_abstencoes": 15, "qt_votos_nominais": 60, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0102",
         "source_id": "sha_t1_sec"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0030", "cd_cargo": 1, "qt_aptos": 70, "qt_comparecimento": 55,
         "qt_abstencoes": 15, "qt_votos_nominais": 50, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0103",
         "source_id": "sha_t1_sec"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0050", "cd_cargo": 1, "qt_aptos": 90, "qt_comparecimento": 80,
         "qt_abstencoes": 10, "qt_votos_nominais": 70, "qt_votos_legenda": 0, "qt_votos_brancos": 5,
         "qt_votos_nulos": 1, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica",
         "flag_identidade_aptos": True, "flag_identidade_comparecimento": False,  # 70+5+1 = 76 != 80!
         "nr_local_votacao": "0104", "source_id": "sha_t1_sec"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0060", "cd_cargo": 1, "qt_aptos": 60, "qt_comparecimento": None,
         "qt_abstencoes": None, "qt_votos_nominais": None, "qt_votos_legenda": None, "qt_votos_brancos": None,
         "qt_votos_nulos": None, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": False,  # Não instalada!
         "st_secao_anulada": False, "ds_origem_voto": "Totalização", "flag_identidade_aptos": False,
         "flag_identidade_comparecimento": False, "nr_local_votacao": "0105", "source_id": "sha_t1_sec"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0070", "cd_cargo": 1, "qt_aptos": 100, "qt_comparecimento": 80,
         "qt_abstencoes": 20, "qt_votos_nominais": 75, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0106", "source_id": "sha_t1_sec"},
        # T2
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0010", "cd_cargo": 1, "qt_aptos": 150, "qt_comparecimento": 135,
         "qt_abstencoes": 15, "qt_votos_nominais": 130, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0101", "source_id": "sha_t2_sec"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0020", "cd_cargo": 1, "qt_aptos": 80, "qt_comparecimento": 75,
         "qt_abstencoes": 5, "qt_votos_nominais": 70, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0102", "source_id": "sha_t2_sec"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0040", "cd_cargo": 1, "qt_aptos": 70, "qt_comparecimento": 60,
         "qt_abstencoes": 10, "qt_votos_nominais": 55, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0103", "source_id": "sha_t2_sec"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0050", "cd_cargo": 1, "qt_aptos": 90, "qt_comparecimento": 80,
         "qt_abstencoes": 10, "qt_votos_nominais": 75, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0104", "source_id": "sha_t2_sec"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0060", "cd_cargo": 1, "qt_aptos": 60, "qt_comparecimento": 50,
         "qt_abstencoes": 10, "qt_votos_nominais": 45, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0105", "source_id": "sha_t2_sec"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0070", "cd_cargo": 1, "qt_aptos": 100, "qt_comparecimento": 80,
         "qt_abstencoes": 20, "qt_votos_nominais": 75, "qt_votos_legenda": 0, "qt_votos_brancos": 3,
         "qt_votos_nulos": 2, "qt_votos_anulados_apu_sep": 0, "st_secao_instalada": True,
         "st_secao_anulada": False, "ds_origem_voto": "Urna Eletrônica", "flag_identidade_aptos": True,
         "flag_identidade_comparecimento": True, "nr_local_votacao": "0106", "source_id": "sha_t2_sec"},
    ]

    crosswalk_rows = [
        # T1: 0011 agrega em 0010; 0010 e 0012 apuram a si mesmas
        {"ano": 2026, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0010", "nr_secao_apuradora": "0010", "nr_local_votacao": "0101",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0011", "nr_secao_apuradora": "0010", "nr_local_votacao": "0101",
         "tipo_correspondencia": "AGREGADA", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0012", "nr_secao_apuradora": "0012", "nr_local_votacao": "0101",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0020", "nr_secao_apuradora": "0020", "nr_local_votacao": "0102",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0030", "nr_secao_apuradora": "0030", "nr_local_votacao": "0103",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0050", "nr_secao_apuradora": "0050", "nr_local_votacao": "0104",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0060", "nr_secao_apuradora": "0060", "nr_local_votacao": "0105",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0070", "nr_secao_apuradora": "0070", "nr_local_votacao": "0106",
         "tipo_correspondencia": "AMBIGUA", "status_correspondencia": "EFETIVADA", "flag_ambigua": True, "source_id": "sha_cw"},
        # T2: 0011 e 0012 agregam em 0010
        {"ano": 2026, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0010", "nr_secao_apuradora": "0010", "nr_local_votacao": "0101",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0011", "nr_secao_apuradora": "0010", "nr_local_votacao": "0101",
         "tipo_correspondencia": "AGREGADA", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0012", "nr_secao_apuradora": "0010", "nr_local_votacao": "0101",
         "tipo_correspondencia": "AGREGADA", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0020", "nr_secao_apuradora": "0020", "nr_local_votacao": "0102",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0040", "nr_secao_apuradora": "0040", "nr_local_votacao": "0103",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0050", "nr_secao_apuradora": "0050", "nr_local_votacao": "0104",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0060", "nr_secao_apuradora": "0060", "nr_local_votacao": "0105",
         "tipo_correspondencia": "SECAO_PRINCIPAL", "status_correspondencia": "EFETIVADA", "flag_ambigua": False, "source_id": "sha_cw"},
        {"ano": 2026, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001",
         "nr_secao": "0070", "nr_secao_apuradora": "0070", "nr_local_votacao": "0106",
         "tipo_correspondencia": "AMBIGUA", "status_correspondencia": "EFETIVADA", "flag_ambigua": True, "source_id": "sha_cw"},
    ]

    votes_long_rows = [
        # T1: 0010 (Lula=30, Flavio=40, Ciro=10); 0012 (Lula=15, Flavio=20, Ciro=5)
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0010", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 30,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0010", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 40,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0010", "cd_cargo": 1, "nr_votavel": 12, "qt_votos": 10,
         "sq_candidato": 10003, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},

        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0012", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 15,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0012", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 20,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0012", "cd_cargo": 1, "nr_votavel": 12, "qt_votos": 5,
         "sq_candidato": 10003, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},

        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0020", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 35,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0020", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 25,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},

        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0030", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 25,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0030", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 25,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},

        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0050", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 35,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0050", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 35,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},

        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0070", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 40,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},
        {"ano": 2026, "cd_eleicao": 6257, "nr_turno": 1, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0070", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 35,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t1_vl"},

        # T2: 0010 (Lula=55, Flavio=70, Ciro/outros=5); 0020 (Lula=40, Flavio=30)
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0010", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 55,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0010", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 70,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0010", "cd_cargo": 1, "nr_votavel": 99, "qt_votos": 5,
         "sq_candidato": None, "tipo_votavel": "LEGENDA", "source_id": "sha_t2_vl"},

        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0020", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 40,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0020", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 30,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},

        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0040", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 30,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0040", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 25,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},

        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0050", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 40,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0050", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 35,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},

        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0060", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 20,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0060", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 25,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},

        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0070", "cd_cargo": 1, "nr_votavel": 13, "qt_votos": 40,
         "sq_candidato": 10001, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},
        {"ano": 2026, "cd_eleicao": 6258, "nr_turno": 2, "sg_uf": "AC", "cd_municipio_tse": "01007",
         "nr_zona": "0001", "nr_secao": "0070", "cd_cargo": 1, "nr_votavel": 22, "qt_votos": 35,
         "sq_candidato": 10002, "tipo_votavel": "NOMINAL", "source_id": "sha_t2_vl"},
    ]

    st = pd.DataFrame(section_turn_rows)
    cw = pd.DataFrame(crosswalk_rows)
    vl = pd.DataFrame(votes_long_rows)

    # Tipagem estrita compatível com os contratos
    st["qt_aptos"] = st["qt_aptos"].astype("Int64")
    st["qt_comparecimento"] = st["qt_comparecimento"].astype("Int64")
    st["qt_abstencoes"] = st["qt_abstencoes"].astype("Int64")
    st["qt_votos_nominais"] = st["qt_votos_nominais"].astype("Int64")
    st["qt_votos_legenda"] = st["qt_votos_legenda"].astype("Int64")
    st["qt_votos_brancos"] = st["qt_votos_brancos"].astype("Int64")
    st["qt_votos_nulos"] = st["qt_votos_nulos"].astype("Int64")
    st["qt_votos_anulados_apu_sep"] = st["qt_votos_anulados_apu_sep"].astype("Int64")

    vl["qt_votos"] = vl["qt_votos"].astype("Int64")
    vl["sq_candidato"] = vl["sq_candidato"].astype("Int64")

    return st, cw, vl
