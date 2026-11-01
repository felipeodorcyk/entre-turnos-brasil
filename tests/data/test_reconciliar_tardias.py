"""Reconciliação das contagens externas (handoff 29): classificação da diferença e leitura de horários."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from reconciliar_tardias import _hms, _linha, _melhor  # noqa: E402


def test_status_exato_aproximado_diverge_e_forcado():
    assert _linha("F", "i", 100, "d", 100, "e")["status"] == "EXATO"
    assert _linha("F", "i", 6766, "d", 6770, "e")["status"] == "APROXIMADO"          # 4 <= max(5, 0,5%)
    assert _linha("F", "i", 4773, "d", 4696, "e")["status"] == "DIVERGE"             # 77 > 0,5% de 4.773
    assert _linha("F", "i", 4203, "d", 1532, "e", "RECORTE", "FORA_DO_RECORTE")["status"] == "FORA_DO_RECORTE"
    assert _linha("F", "i", 10, "d", None, "e")["status"] == "NAO_REPRODUZIVEL"


def test_melhor_definicao_e_a_mais_proxima():
    em, en = pd.Series([True] * 3 + [False]), pd.Series([True] + [False] * 3)
    nome, mascara = _melhor(3, {"emissao": em, "encerramento": en})
    assert nome == "emissao" and mascara is em          # devolve a própria máscara contada (R30-3)


def test_hms_aceita_hhmm_hhmmss_e_vazio():
    s = _hms(pd.Series(["19:00", "17:01:03", "", None]))
    assert s.iloc[0] == 19 * 3600 and s.iloc[1] == 17 * 3600 + 63
    assert s.iloc[2:].isna().all()


def test_corte_escolhido_e_o_aplicado_na_soma():
    # seção 1 emitida às 19:00:30: entra em ">= 19:00:00" e fica fora de "> 19:00:59"
    emi = pd.Series([19 * 3600 + 30, 19 * 3600 + 120, 17 * 3600])
    votos = pd.Series([5, 7, 1])
    cand = {"emissão >= 19:00:00": emi >= 19 * 3600, "emissão > 19:00:59": emi >= 19 * 3600 + 60}
    nome, m = _melhor(1, cand)                       # publicado 1 seção: vence o segundo limiar
    assert nome == "emissão > 19:00:59" and int(votos[m].sum()) == 7
