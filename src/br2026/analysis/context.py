"""Contexto municipal por unidade (O-R6).

Contexto descreve o MUNICÍPIO da unidade, não os eleitores. Variáveis brutas vêm
de `municipal_context` (frente A); os indicadores são derivados aqui segundo
`config [context.derivadas]`. Valor ausente, não positivo onde há log, ou ano de
referência heterogêneo entre municípios torna o indicador ausente — nunca zero.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MUN = ["sg_uf", "cd_municipio_tse"]


def municipal_features(context: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retorna (indicadores por município, diagnóstico por variável)."""
    cc = cfg["context"]
    raw = context[context.variavel.isin(cc["variaveis"])]
    diag = []
    for v in cc["variaveis"]:
        r = raw[raw.variavel == v]
        anos = sorted(r.ano_referencia.dropna().unique().tolist())
        diag.append({"variavel": v, "municipios": int(r[MUN].drop_duplicates().shape[0]),
                     "valores_ausentes": int(r.valor.isna().sum()), "anos_referencia": anos,
                     "ano_heterogeneo": len(anos) > 1})
    wide = raw.pivot_table(index=MUN, columns="variavel", values="valor", aggfunc="first")
    wide = wide.reindex(columns=cc["variaveis"])
    bad_year = {d["variavel"] for d in diag if d["ano_heterogeneo"]}
    for v in bad_year:  # ano heterogêneo: comparação entre municípios não é homogênea
        wide[v] = np.nan
    out = pd.DataFrame(index=wide.index)
    for name, (op, *vars_) in cc["derivadas"].items():
        x = wide[vars_[0]].astype(float)
        if op == "log":
            out[name] = np.log(x.where(x > 0))
        elif op == "log_razao":
            den = wide[vars_[1]].astype(float)
            out[name] = np.log((x / den.where(den > 0)).where(x > 0))
        else:
            raise ValueError(f"operação de contexto desconhecida: {op}")
    return out, pd.DataFrame(diag)
