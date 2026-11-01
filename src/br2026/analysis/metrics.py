"""Descrição e contabilidade entre turnos (B2).

Toda razão leva o denominador no nome: `_validos` (votos válidos), `_aptos`,
`_comparecimento`. Denominador zero ou ausente produz NaN, nunca 0 nem inf.
Percentuais são proporções em [0, 1]; diferenças de proporção são reportadas
em pontos percentuais apenas na camada de relatório.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ratio(num, den) -> pd.Series:
    num = pd.to_numeric(pd.Series(num), errors="coerce").astype("float64")
    den = pd.to_numeric(pd.Series(den), errors="coerce").astype("float64")
    return num.where(den > 0) / den.where(den > 0)


def unit_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    """Métricas por unidade e turno; as variações são T2 − T1."""
    out = panel[["id_unidade", "sg_uf", "cd_municipio_tse", "status_painel"]].copy()
    for t in (1, 2):
        v, a, c = (panel[f"qt_votos_validos_t{t}"], panel[f"qt_aptos_t{t}"],
                   panel[f"qt_comparecimento_t{t}"])
        out[f"share_lula_validos_t{t}"] = ratio(panel[f"qt_lula_t{t}"], v)
        out[f"share_flavio_validos_t{t}"] = ratio(panel[f"qt_flavio_t{t}"], v)
        out[f"margem_lula_flavio_validos_t{t}"] = (out[f"share_lula_validos_t{t}"]
                                                   - out[f"share_flavio_validos_t{t}"])
        out[f"lula_por_apto_t{t}"] = ratio(panel[f"qt_lula_t{t}"], a)
        out[f"flavio_por_apto_t{t}"] = ratio(panel[f"qt_flavio_t{t}"], a)
        out[f"abstencao_aptos_t{t}"] = ratio(panel[f"qt_abstencoes_t{t}"], a)
        out[f"comparecimento_aptos_t{t}"] = ratio(c, a)
        out[f"brancos_comparecimento_t{t}"] = ratio(panel[f"qt_votos_brancos_t{t}"], c)
        out[f"nulos_comparecimento_t{t}"] = ratio(panel[f"qt_votos_nulos_t{t}"], c)
    for c in ("qt_lula", "qt_flavio", "qt_votos_validos", "qt_comparecimento", "qt_aptos",
              "qt_abstencoes", "qt_votos_brancos", "qt_votos_nulos"):
        out[f"delta_{c}"] = (panel[f"{c}_t2"] - panel[f"{c}_t1"]).astype("Int64")
    out["delta_margem_lula_flavio_votos"] = (out.delta_qt_lula - out.delta_qt_flavio).astype("Int64")
    for m in ("share_lula_validos", "share_flavio_validos", "margem_lula_flavio_validos",
              "lula_por_apto", "flavio_por_apto", "abstencao_aptos", "comparecimento_aptos",
              "brancos_comparecimento", "nulos_comparecimento"):
        out[f"delta_{m}"] = out[f"{m}_t2"] - out[f"{m}_t1"]
    return out


def aggregate_metrics(panel: pd.DataFrame) -> dict:
    """Agregado do conjunto: razões de somas (ponderadas), nunca média de percentuais."""
    s = {c: int(panel[c].sum()) for c in panel.columns if c.startswith("qt_")}
    r = {}
    for t in (1, 2):
        v, a, c = s[f"qt_votos_validos_t{t}"], s[f"qt_aptos_t{t}"], s[f"qt_comparecimento_t{t}"]
        div = lambda n, d: n / d if d > 0 else float("nan")
        r[f"share_lula_validos_t{t}"] = div(s[f"qt_lula_t{t}"], v)
        r[f"share_flavio_validos_t{t}"] = div(s[f"qt_flavio_t{t}"], v)
        r[f"margem_lula_flavio_validos_t{t}"] = (r[f"share_lula_validos_t{t}"]
                                                 - r[f"share_flavio_validos_t{t}"])
        r[f"lula_por_apto_t{t}"] = div(s[f"qt_lula_t{t}"], a)
        r[f"flavio_por_apto_t{t}"] = div(s[f"qt_flavio_t{t}"], a)
        r[f"comparecimento_aptos_t{t}"] = div(c, a)
        r[f"abstencao_aptos_t{t}"] = div(s[f"qt_abstencoes_t{t}"], a)
        r[f"brancos_comparecimento_t{t}"] = div(s[f"qt_votos_brancos_t{t}"], c)
        r[f"nulos_comparecimento_t{t}"] = div(s[f"qt_votos_nulos_t{t}"], c)
    for k in list(r):
        if k.endswith("_t1"):
            base = k[:-3]
            r[f"delta_{base}"] = r[f"{base}_t2"] - r[k]
    r.update({f"delta_{c[:-3]}": s[f"{c[:-3]}_t2"] - s[c] for c in s if c.endswith("_t1")})
    r["delta_margem_lula_flavio_votos"] = r["delta_qt_lula"] - r["delta_qt_flavio"]
    r["totais"] = s
    return r


def share_contributions(panel: pd.DataFrame, cand: str, by: list[str]) -> pd.DataFrame:
    """Contribuição exata de cada recorte à variação da participação agregada.

    Com S_t = Σ v_it / Σ V_it, a variação S_2 − S_1 = Σ_i (v_i2/V_2 − v_i1/V_1).
    O termo de cada recorte soma exatamente à variação total. Também é
    decomposto em efeito de participação interna (Δs_i · w_i1) e de peso
    (s_i2 · Δw_i), com w_it = V_it / V_t.
    """
    g = panel.groupby(by)[[f"qt_{cand}_t1", f"qt_{cand}_t2",
                           "qt_votos_validos_t1", "qt_votos_validos_t2"]].sum()
    V1, V2 = g.qt_votos_validos_t1.sum(), g.qt_votos_validos_t2.sum()
    if V1 <= 0 or V2 <= 0:
        raise ValueError("Total de votos válidos nulo; contribuição indefinida")
    out = pd.DataFrame(index=g.index)
    out["contribuicao_delta_share"] = g[f"qt_{cand}_t2"] / V2 - g[f"qt_{cand}_t1"] / V1
    s1 = ratio(g[f"qt_{cand}_t1"], g.qt_votos_validos_t1).fillna(0).values
    s2 = ratio(g[f"qt_{cand}_t2"], g.qt_votos_validos_t2).fillna(0).values
    w1, w2 = g.qt_votos_validos_t1.values / V1, g.qt_votos_validos_t2.values / V2
    out["efeito_participacao"] = (s2 - s1) * w1
    out["efeito_peso"] = s2 * (w2 - w1)
    out["contribuicao_delta_votos"] = g[f"qt_{cand}_t2"] - g[f"qt_{cand}_t1"]
    out["peso_validos_t1"], out["peso_validos_t2"] = w1, w2
    return out.reset_index()


def turnout_flow_bounds(aptos, comp_t1, comp_t2) -> pd.DataFrame:
    """Limites para pessoas que entraram/saíram do comparecimento numa população fixa.

    Com N aptos, C1 e C2 comparecimentos, o número k que votou nos dois turnos
    satisfaz max(0, C1 + C2 − N) ≤ k ≤ min(C1, C2). Entradas = C2 − k e
    saídas = C1 − k. A variação líquida C2 − C1 não identifica k: com C1 = C2
    pode haver troca de até min(C1, N − C1) pessoas.

    Pressupõe a MESMA população de aptos nos dois turnos; para N1 ≠ N2 os
    limites não se aplicam e o resultado é NaN com motivo.
    """
    N = pd.Series(aptos, dtype="float64") if not isinstance(aptos, tuple) else None
    if isinstance(aptos, tuple):
        n1, n2 = (pd.Series(x, dtype="float64") for x in aptos)
    else:
        n1 = n2 = N
    c1, c2 = pd.Series(comp_t1, dtype="float64"), pd.Series(comp_t2, dtype="float64")
    same = (n1 == n2) & n1.notna()
    n = n1.where(same)
    k_min = np.maximum(0, c1 + c2 - n)
    k_max = np.minimum(c1, c2)
    return pd.DataFrame({
        "variacao_liquida": c2 - c1,
        "ambos_min": k_min.where(same), "ambos_max": k_max.where(same),
        "entradas_min": (c2 - k_max).where(same), "entradas_max": (c2 - k_min).where(same),
        "saidas_min": (c1 - k_max).where(same), "saidas_max": (c1 - k_min).where(same),
        "motivo": np.where(same, None, "APTOS_DIFERENTES_OU_AUSENTES"),
    })
