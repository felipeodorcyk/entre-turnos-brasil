"""Oráculo independente baseado em amostra oficial do TSE com URL e SHA-256.

Fonte independente: `detalhe_votacao_munzona_2026.zip`
URL: https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_munzona/detalhe_votacao_munzona_2026.zip
SHA-256 (ZIP): 7f6f40a14ba805b453b1d85c18fe12eec4225cfbf2ba21989ecd7c4e15a12043
Bytes: 2.511.067
Membro extraído diretamente do ZIP: `detalhe_votacao_munzona_2026_BRASIL.csv`
Data/hora de geração informada: 25/10/2026 12:33:24
Eleição: 6257 (Eleição Geral Federal 2026), 1º Turno (04/10/2026), Cargo 1 (Presidente).

Este oráculo lê diretamente o binário do ZIP oficial preservado e extrai
as contagens oficiais por município/zona, servindo para conferência independente
de integridade dos totais e identidades contábeis sem utilizar funções de produção.
"""
from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from pathlib import Path

from br2026.contract import PROJECT_ROOT

DEFAULT_ZIP_PATH = PROJECT_ROOT / "data" / "raw" / "samples" / "detalhe_votacao_munzona_2026.zip"

OFFICIAL_SOURCE_PROVENANCE = {
    "name": "detalhe_votacao_munzona_2026.zip",
    "url": "https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_munzona/detalhe_votacao_munzona_2026.zip",
    "sha256": "7f6f40a14ba805b453b1d85c18fe12eec4225cfbf2ba21989ecd7c4e15a12043",
    "bytes": 2511067,
    "last_modified": "Sun, 25 Oct 2026 15:58:00 GMT",
    "generation_date": "25/10/2026",
    "generation_time": "12:33:24",
    "member": "detalhe_votacao_munzona_2026_BRASIL.csv",
}

# Dados de referência esperados para Bujari / AC (Zona 9, Presidente T1)
OFFICIAL_MUNZONA_SAMPLE_RECORDS = [
    {
        "sg_uf": "AC",
        "cd_municipio_tse": "01007",
        "nm_municipio": "BUJARI",
        "nr_zona": 9,
        "cd_cargo": 1,
        "ds_cargo": "Presidente",
        "nr_turno": 1,
        "cd_eleicao": 6257,
        "qt_aptos": 11152,
        "qt_secoes_principais": 41,
        "qt_secoes_agregadas": 0,
        "qt_secoes_nao_instaladas": 0,
        "qt_total_secoes": 41,
        "qt_comparecimento": 8657,
        "qt_eleitores_secoes_nao_instaladas": 0,
        "qt_abstencoes": 2495,
        "st_voto_em_transito": "N",
        "qt_votos": 8657,
        "qt_total_votos_validos": 8308,
        "qt_votos_nominais_validos": 8308,
        "qt_votos_brancos": 98,
        "qt_total_votos_nulos": 251,
        "qt_votos_nulos": 251,
        "qt_votos_anulados_apu_sep": 0,
    }
]


def compute_file_sha256(path: Path) -> str:
    """Calcula diretamente o hash SHA-256 de um arquivo em blocos de 64 KB."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_bujari_official_from_zip(zip_path: Path | None = None) -> dict:
    """Abre o ZIP oficial diretamente, extrai o membro em memória e localiza o registro de Bujari."""
    path = zip_path or DEFAULT_ZIP_PATH
    if not path.exists():
        raise FileNotFoundError(f"Arquivo ZIP oficial não encontrado: {path}")

    with zipfile.ZipFile(path) as z:
        member_name = OFFICIAL_SOURCE_PROVENANCE["member"]
        with z.open(member_name) as raw_file:
            wrapper = io.TextIOWrapper(raw_file, encoding="latin1")
            reader = csv.DictReader(wrapper, delimiter=";")
            for row in reader:
                if (row.get("CD_MUNICIPIO") == "01007"
                        and row.get("NR_ZONA") == "9"
                        and row.get("CD_CARGO") == "1"
                        and row.get("NR_TURNO") == "1"):
                    return {
                        "sg_uf": row["SG_UF"],
                        "cd_municipio_tse": row["CD_MUNICIPIO"],
                        "nm_municipio": row["NM_MUNICIPIO"],
                        "nr_zona": int(row["NR_ZONA"]),
                        "cd_cargo": int(row["CD_CARGO"]),
                        "ds_cargo": row["DS_CARGO"],
                        "nr_turno": int(row["NR_TURNO"]),
                        "cd_eleicao": int(row["CD_ELEICAO"]),
                        "qt_aptos": int(row["QT_APTOS"]),
                        "qt_secoes_principais": int(row["QT_SECOES_PRINCIPAIS"]),
                        "qt_secoes_agregadas": int(row["QT_SECOES_AGREGADAS"]),
                        "qt_secoes_nao_instaladas": int(row["QT_SECOES_NAO_INSTALADAS"]),
                        "qt_total_secoes": int(row["QT_TOTAL_SECOES"]),
                        "qt_comparecimento": int(row["QT_COMPARECIMENTO"]),
                        "qt_eleitores_secoes_nao_instaladas": int(row["QT_ELEITORES_SECOES_NAO_INSTALADAS"]),
                        "qt_abstencoes": int(row["QT_ABSTENCOES"]),
                        "st_voto_em_transito": row["ST_VOTO_EM_TRANSITO"],
                        "qt_votos": int(row["QT_VOTOS"]),
                        "qt_total_votos_validos": int(row["QT_TOTAL_VOTOS_VALIDOS"]),
                        "qt_votos_nominais_validos": int(row["QT_VOTOS_NOMINAIS_VALIDOS"]),
                        "qt_votos_brancos": int(row["QT_VOTOS_BRANCOS"]),
                        "qt_total_votos_nulos": int(row["QT_TOTAL_VOTOS_NULOS"]),
                        "qt_votos_nulos": int(row["QT_VOTOS_NULOS"]),
                        "qt_votos_anulados_apu_sep": int(row["QT_VOTOS_ANULADOS_APU_SEP"]),
                    }

    raise KeyError("Registro de Bujari/AC Zona 9 não encontrado no membro oficial")


def verify_official_accounting_identities(record: dict) -> dict[str, bool]:
    """Verifica as identidades contábeis oficiais sobre o registro oficial de referência."""
    aptos_fecham = record["qt_aptos"] == (record["qt_comparecimento"] + record["qt_abstencoes"])
    comp_fecha = record["qt_comparecimento"] == (
        record["qt_total_votos_validos"] + record["qt_votos_brancos"] + record["qt_total_votos_nulos"]
    )
    votos_totais_fecham = record["qt_votos"] == record["qt_comparecimento"]
    secoes_fecham = record["qt_total_secoes"] == (
        record["qt_secoes_principais"] + record["qt_secoes_agregadas"] + record["qt_secoes_nao_instaladas"]
    )
    return {
        "identidade_aptos": aptos_fecham,
        "identidade_comparecimento": comp_fecha,
        "identidade_votos_totais": votos_totais_fecham,
        "identidade_secoes": secoes_fecham,
    }
