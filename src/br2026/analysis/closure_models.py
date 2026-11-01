"""Comparações entre faixas de encerramento (O4/B5), pré-especificadas.

Para cada agrupamento (faixa do T1 ou do T2) e cada faixa b ≠ referência:

  1. universo = unidades com faixa ∈ {ref, b} (MISTA, INVALIDO e ANTES_17H fora);
  2. suporte comum: para cada covariável contínua, apara unidades fora de
     [max(mín_ref, mín_b), min(máx_ref, máx_b)] e registra quantas;
  3. regra de suporte após aparar: ≥ mín. seções por faixa, ≥ mín. municípios
     por faixa e ≥ mín. municípios que contêm AMBAS as faixas (é deles que vem a
     comparação com efeito fixo de município). Falhou → NAO_ESTIMADO só desta
     comparação;
  4. WLS com EF de município, pesos aptos do T1, erros agrupados por município.

Desfecho é a unidade inteira; coeficiente é associação, não efeito do horário.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from br2026.analysis import associations as assoc


def common_support(d: pd.DataFrame, band_col: str, bands: list[str], cont: list[str]) -> tuple[pd.Series, dict]:
    keep = pd.Series(True, index=d.index)
    limits = {}
    for c in cont:
        g = d.groupby(band_col)[c]
        lo, hi = g.min().reindex(bands).max(), g.max().reindex(bands).min()
        limits[c] = (lo, hi)
        if not (lo <= hi):
            return pd.Series(False, index=d.index), limits
        keep &= d[c].between(lo, hi)
    return keep, limits


def pairwise_comparison(d: pd.DataFrame, band_col: str, ref: str, band: str, outcome: str,
                        cont: list[str], other: list[str], cfg: dict) -> dict:
    """Retorna dict com 'status' (PASS/NAO_ESTIMADO), 'motivo' e, se PASS, estimativas."""
    cc = cfg["closure"]
    base = {"agrupamento": band_col, "referencia": ref, "faixa": band, "desfecho": outcome}
    sub = d[d[band_col].isin([ref, band])].dropna(subset=[outcome] + cont + other)
    n0 = len(sub)
    if sub.empty or sub[band_col].nunique() < 2:
        return {**base, "status": "NAO_ESTIMADO", "motivo": "uma das faixas sem unidades", "n_inicial": n0}
    keep, limits = common_support(sub, band_col, [ref, band], cont)
    sub = sub[keep]
    trimmed = n0 - len(sub)
    if sub.empty or sub[band_col].nunique() < 2:
        return {**base, "status": "NAO_ESTIMADO", "motivo": "sem sobreposição de covariáveis",
                "n_inicial": n0, "n_aparados": trimmed}
    n_by = sub.groupby(band_col).size()
    m_by = sub.groupby(band_col).municipio.nunique()
    both = sub.groupby("municipio")[band_col].nunique()
    m_both = int((both == 2).sum())
    falta = [b for b in (ref, band)
             if n_by.get(b, 0) < cc["suporte_min_secoes"] or m_by.get(b, 0) < cc["suporte_min_municipios"]]
    if falta or m_both < cc["suporte_min_municipios"]:
        return {**base, "status": "NAO_ESTIMADO",
                "motivo": (f"suporte insuficiente: faixas {falta}" if falta else
                           f"apenas {m_both} município(s) com ambas as faixas"),
                "n_inicial": n0, "n_aparados": trimmed, "municipios_com_ambas": m_both}
    X = np.column_stack([(sub[band_col] == band).to_numpy(float)]
                        + [sub[c].to_numpy(float) for c in cont + other])
    w = sub.peso.to_numpy(float)
    g = sub.municipio.to_numpy()
    G = len(np.unique(g))
    if len(sub) <= X.shape[1] + G:
        return {**base, "status": "NAO_ESTIMADO", "motivo": "graus de liberdade insuficientes",
                "n_inicial": n0, "n_aparados": trimmed}
    Xd = assoc.demean(X, w, g)
    keep_cols = np.flatnonzero(np.abs(Xd).max(axis=0) > 1e-12)
    if 0 not in keep_cols:
        return {**base, "status": "NAO_ESTIMADO", "motivo": "faixa sem variação dentro de município"}
    Xd = Xd[:, keep_cols]
    f = assoc.clustered_fit(Xd, assoc.demean(sub[outcome].to_numpy(float), w, g), w, g, absorbed=G)
    raw = sub.groupby(band_col).apply(lambda s: np.average(s[outcome], weights=s.peso),
                                      include_groups=False)
    return {**base, "status": "PASS", "motivo": "",
            "diferenca_bruta": float(raw[band] - raw[ref]), "beta_ajustado": float(f["beta"][0]),
            "ep": float(f["se"][0]), "inf": float(f["inf"][0]), "sup": float(f["sup"][0]),
            "n": f["n"], "grupos": G, "n_inicial": n0, "n_aparados": trimmed,
            "municipios_com_ambas": m_both, "controles": "|".join(cont + other),
            "aviso": assoc.few_clusters_warning(G, cfg["inference"]["poucos_grupos"]) or "",
            "rotulo": "associação ajustada entre unidades (EF município); não é efeito do horário"}
