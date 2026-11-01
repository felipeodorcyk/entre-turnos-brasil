"""Fábrica de brutos sintéticos no formato TSE para testar a normalização (M3).

Monta `data/raw/` + `manifest.json` de um projeto temporário com os ZIPs de
`votacao_secao` e `detalhe_votacao_secao` contendo os cabeçalhos reais (Latin-1,
`;`, aspas), para `br2026.normalize.run` processar sem rede.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

# Colunas que `normalize` lê, na ordem dos arquivos reais (subconjunto dos reais).
COLS_VOTOS = ["DT_GERACAO", "ANO_ELEICAO", "NR_TURNO", "CD_ELEICAO", "SG_UF",
              "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO", "NR_VOTAVEL",
              "SQ_CANDIDATO", "QT_VOTOS"]
COLS_DETALHE = ["DT_GERACAO", "ANO_ELEICAO", "NR_TURNO", "CD_ELEICAO", "SG_UF",
                "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO", "QT_APTOS",
                "QT_COMPARECIMENTO", "QT_ABSTENCOES", "QT_VOTOS_NOMINAIS",
                "QT_VOTOS_LEGENDA", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS",
                "QT_VOTOS_ANULADOS_APU_SEP", "NR_LOCAL_VOTACAO", "ST_SECAO_INSTALADA",
                "ST_SECAO_ANULADA", "DS_ORIGEM_VOTO"]

_NOME_VOTOS = "votacao_secao_2026_BR.csv"
_NOME_DETALHE = "detalhe_votacao_secao_2026_BR.csv"
_SHA = "a" * 64  # placeholder; o manifesto real usa o hash do ZIP


def _csv(cols, linhas) -> bytes:
    corpo = [";".join(f'"{c}"' for c in cols)]
    for ln in linhas:
        corpo.append(";".join(str(v) for v in ln))
    return ("\n".join(corpo)).encode("latin-1")


def _zip(membro: str, dados: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(membro, dados)
    return buf.getvalue()


def voto(uf, zona, secao, mun, votavel, sq, votos, turno="1", cd="6257", cargo="1"):
    return ["26/10/2026", "2026", turno, cd, uf, mun, zona, secao, cargo,
            votavel, sq, votos]


def total(uf, zona, secao, mun, aptos, comp, abst, nom, leg, bra, nul, anul=0,
          local="1001", instalada="Sim", anulada="Não", origem="Urna Eletrônica",
          turno="1", cd="6257", cargo="1"):
    return ["26/10/2026", "2026", turno, cd, uf, mun, zona, secao, cargo, aptos,
            comp, abst, nom, leg, bra, nul, anul, local, instalada, anulada, origem]


def montar_raw(raiz: Path, linhas_votos, linhas_total) -> None:
    """Cria `data/raw/` com os dois ZIPs e o manifesto apontando para eles."""
    raw = raiz / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    zv = _zip(_NOME_VOTOS, _csv(COLS_VOTOS, linhas_votos))
    zd = _zip(_NOME_DETALHE, _csv(COLS_DETALHE, linhas_total))
    (raw / "votacao_secao_2026_BR.zip").write_bytes(zv)
    (raw / "detalhe_votacao_secao_2026.zip").write_bytes(zd)

    def sha(b):
        return hashlib.sha256(b).hexdigest()

    man = {
        "manifest_version": "1.0",
        "registros": {
            "votacao_secao_2026_BR": {
                "fonte": "votacao_secao", "arquivo": "votacao_secao_2026_BR.zip",
                "sha256": sha(zv), "bytes": len(zv), "uf": "BR", "turnos": [1],
                "url": "https://local/votacao_secao_2026_BR.zip",
            },
            "detalhe_votacao_secao_2026": {
                "fonte": "detalhe_votacao_secao", "arquivo": "detalhe_votacao_secao_2026.zip",
                "sha256": sha(zd), "bytes": len(zd), "uf": "BR", "turnos": [1],
                "url": "https://local/detalhe_votacao_secao_2026.zip",
            },
        },
    }
    (raw / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")


def sha256_zip(raiz: Path, stem: str) -> str:
    man = json.loads((raiz / "data" / "raw" / "manifest.json").read_text(encoding="utf-8"))
    return man["registros"][stem]["sha256"]
