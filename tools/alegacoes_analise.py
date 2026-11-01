"""Testes das alegações de fraude (A01–A10). Chamado por `alegacoes_fraude.py analisar`.

Convenções:
- universo: seções do território com BU do 2º turno (censo do portal); o exterior não tem BU no portal;
- "participação de Lula" = Lula / (Lula + Flávio), os votos válidos do 2º turno;
- horários do BU convertidos para Brasília com o fuso municipal inferido pela abertura
  (`closure_tz_offsets.csv`, o mesmo do capítulo 8);
- comparações "no mesmo município": regressão ponderada por votos válidos com efeito fixo de
  município e erro-padrão agrupado por município.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REGIAO = {**dict.fromkeys(["AC", "AM", "AP", "PA", "RO", "RR", "TO"], "Norte"),
          **dict.fromkeys(["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"], "Nordeste"),
          **dict.fromkeys(["DF", "GO", "MS", "MT"], "Centro-Oeste"),
          **dict.fromkeys(["ES", "MG", "RJ", "SP"], "Sudeste"),
          **dict.fromkeys(["PR", "RS", "SC"], "Sul")}
BENFORD1 = np.log10(1 + 1 / np.arange(1, 10))
BENFORD2 = np.array([sum(np.log10(1 + 1 / (10 * d1 + d2)) for d1 in range(1, 10)) for d2 in range(10)])
SEMENTE = 20261025


# --------------------------------------------------------------------------- utilitários
def fe_wls(df: pd.DataFrame, y: str, xs: list[str], grupo: str, peso: str) -> pd.DataFrame:
    """y ~ xs + efeito fixo de `grupo`, ponderado; erro-padrão agrupado por `grupo` (CR1)."""
    d = df[[y, *xs, grupo, peso]].dropna()
    d = d[d[peso] > 0]
    w = d[peso].to_numpy(float)
    g = d[grupo].to_numpy()
    cols = [y, *xs]
    sw_g = d[peso].groupby(d[grupo]).transform("sum")
    m = d[cols].mul(d[peso], axis=0).groupby(d[grupo]).transform("sum").div(sw_g, axis=0)
    Z = (d[cols] - m).to_numpy(float)
    Y, X = Z[:, 0], Z[:, 1:]
    sw = np.sqrt(w)
    Xw, Yw = X * sw[:, None], Y * sw
    XtX_inv = np.linalg.pinv(Xw.T @ Xw)
    b = XtX_inv @ Xw.T @ Yw
    e = Yw - Xw @ b
    meat = np.zeros((X.shape[1], X.shape[1]))
    for _, idx in pd.Series(np.arange(len(g))).groupby(g):
        s = Xw[idx.to_numpy()].T @ e[idx.to_numpy()]
        meat += np.outer(s, s)
    G, n, k = len(np.unique(g)), len(Y), X.shape[1]
    V = XtX_inv @ meat @ XtX_inv * (G / (G - 1)) * ((n - 1) / (n - k))
    se = np.sqrt(np.diag(V))
    return pd.DataFrame({"termo": xs, "coef": b, "ep": se, "ic95_inf": b - 1.96 * se,
                         "ic95_sup": b + 1.96 * se, "n": n, "grupos": G})


def digitos(v: np.ndarray, pos: int) -> np.ndarray:
    v = v[v >= (10 if pos == 2 else 1)]
    s = v.astype(str)
    return np.array([int(x[pos - 1]) for x in s])


def benford_linha(nome: str, v: np.ndarray) -> dict:
    v = np.asarray(v, dtype=np.int64)
    d1 = digitos(v, 1)
    f1 = np.bincount(d1, minlength=10)[1:] / len(d1)
    d2 = digitos(v, 2)
    f2 = np.bincount(d2, minlength=10) / len(d2)
    return {"serie": nome, "n_1d": len(d1), "mad_1d": float(np.abs(f1 - BENFORD1).mean()),
            "n_2d": len(d2), "mad_2d": float(np.abs(f2 - BENFORD2).mean()),
            **{f"p1_{k}": float(f1[k - 1]) for k in range(1, 10)},
            **{f"p2_{k}": float(f2[k]) for k in range(10)}}


# --------------------------------------------------------------------------- carga
def carregar(root: Path) -> dict:
    a = root / "data/analytics/alegacoes"
    bu = pd.read_parquet(a / "bu_t2.parquet")
    bu = bu[bu.sg_uf != "ZZ"].copy()
    tz = pd.read_csv(root / "data/analytics/closure_tz_offsets.csv", dtype={"cd_municipio_tse": str})
    tz = tz[tz.nr_turno == 2][["sg_uf", "cd_municipio_tse", "offset_h"]]
    bu = bu.merge(tz, on=["sg_uf", "cd_municipio_tse"], how="left")
    for c in ("encerramento", "emissao", "abertura"):
        bu[c + "_br"] = (pd.to_datetime(bu[c], format="%Y%m%dT%H%M%S", errors="coerce")
                         + pd.to_timedelta(bu.offset_h.fillna(0), unit="h"))
    bu["validos"] = bu.lula + bu.flavio
    bu["regiao"] = bu.sg_uf.map(REGIAO)
    st = root / "data/staging"
    vl = duckdb.sql(f"""
        select nr_turno, sg_uf, cd_municipio_tse, nr_zona, nr_secao,
               sum(case when nr_votavel = 13 then qt_votos else 0 end) as lula,
               sum(case when nr_votavel = 22 then qt_votos else 0 end) as flavio,
               sum(case when tipo_votavel = 'NOMINAL' then qt_votos else 0 end) as nominais
        from read_parquet('{(st / 'votes_long/*.parquet').as_posix()}')
        where cd_cargo = 1 and sg_uf <> 'ZZ' group by all""").df()
    aptos = duckdb.sql(f"""
        select sg_uf, cd_municipio_tse, nr_zona, nr_secao, qt_aptos as aptos, nr_local_votacao
        from read_parquet('{(st / 'section_turn/*_T2.parquet').as_posix()}')
        where cd_cargo = 1 and sg_uf <> 'ZZ'""").df()
    return {"bu": bu, "vl": vl, "aptos": aptos, "s22": pd.read_parquet(a / "secoes_2022.parquet"),
            "d22": pd.read_parquet(a / "secoes_2022_detalhe.parquet"),
            "mod": pd.read_parquet(a / "modelo_urna_logs.parquet")}


# --------------------------------------------------------------------------- testes
def a00_integridade(D: dict, N: dict) -> pd.DataFrame:
    """BUs decodificados × consolidado oficial por seção (base de todos os testes)."""
    bu, vl = D["bu"], D["vl"]
    t2 = vl[vl.nr_turno == 2]
    j = bu.merge(t2, on=["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"], how="outer",
                 suffixes=("_bu", "_ofi"), indicator=True)
    so_ofi = j[j._merge == "right_only"]
    amb = j[j._merge == "both"]
    dif = amb[(amb.lula_bu != amb.lula_ofi) | (amb.flavio_bu != amb.flavio_ofi)]
    N["a00"] = {"secoes_bu": int(len(bu)), "secoes_oficial_t2": int(len(t2)),
                "secoes_so_no_oficial": int(len(so_ofi)),
                "votos_lula_so_no_oficial": int(so_ofi.lula_ofi.sum()),
                "secoes_bu_e_oficial": int(len(amb)), "secoes_com_diferenca": int(len(dif)),
                "lula_bu": int(bu.lula.sum()), "flavio_bu": int(bu.flavio.sum()),
                "lula_oficial_territorio": int(t2.lula.sum()), "flavio_oficial_territorio": int(t2.flavio.sum()),
                "comparecimento_igual_soma": int((bu.comparecimento == bu.lula + bu.flavio + bu.branco + bu.nulo).sum())}
    return pd.DataFrame([N["a00"]])


def a01_secoes_tardias(D: dict, N: dict) -> pd.DataFrame:
    """'O resultado veio das seções encerradas depois das 17h.'"""
    bu = D["bu"].copy()
    h = bu.encerramento_br
    lim = lambda hh, mm: pd.Timestamp(f"2026-10-25 {hh:02d}:{mm:02d}:00")  # noqa: E731
    bu["faixa"] = np.select(
        [h.isna(), h <= lim(17, 0), h <= lim(17, 10), h < lim(19, 0)],
        ["sem horário", "a) até 17h00", "b) 17h00–17h10", "c) 17h10–19h00"], "d) 19h00 ou depois")
    t = bu.groupby("faixa").agg(secoes=("lula", "size"), lula=("lula", "sum"), flavio=("flavio", "sum"),
                                comparecimento=("comparecimento", "sum")).reset_index()
    t["margem_lula"] = t.lula - t.flavio
    t["pct_lula_validos"] = 100 * t.lula / (t.lula + t.flavio)
    # nenhum BU encerra antes das 17h (o mesário encerra depois do horário); o encerramento normal
    # vai até 17h10, o corte da nota do TSE
    normal = t[t.faixa.str[0] <= "b"]
    tard = t[t.faixa.str[0] > "b"]
    pior = {"faixa": "pior caso: todo voto do dia nas seções tardias para Flávio",
            "secoes": int(t.secoes.sum()), "lula": int(normal.lula.sum()),
            "flavio": int(normal.flavio.sum() + tard.lula.sum() + tard.flavio.sum()),
            "comparecimento": int(t.comparecimento.sum())}
    c = pd.DataFrame([pior])
    c["margem_lula"] = c.lula - c.flavio
    c["pct_lula_validos"] = 100 * c.lula / (c.lula + c.flavio)
    out = pd.concat([t, c], ignore_index=True)
    N["a01"] = {"secoes_antes_17h": int((h < lim(17, 0)).sum()),
                "secoes_ate_17h10": int(normal.secoes.sum()), "margem_so_ate_17h10": int(normal.margem_lula.sum()),
                "pct_lula_so_ate_17h10": round(100 * normal.lula.sum() / (normal.lula.sum() + normal.flavio.sum()), 2),
                "secoes_tardias": int(tard.secoes.sum()), "margem_tardias": int(tard.margem_lula.sum()),
                "validos_tardias_dia_todo": int(tard.lula.sum() + tard.flavio.sum()),
                "margem_pior_caso": int(c.margem_lula.iloc[0]),
                "margem_total_territorio": int(bu.lula.sum() - bu.flavio.sum()),
                "pct_lula_total_territorio": round(100 * bu.lula.sum() / bu.validos.sum(), 2),
                "votos_apos_17h_tse": 34393, "votos_alegados_apos_17h": 1_800_000}
    return out


def a02_benford(D: dict, N: dict) -> pd.DataFrame:
    """'O teste de Benford (1º dígito) nos votos por seção acusa fraude.'"""
    bu, s22 = D["bu"], D["s22"]
    s22t2 = s22[(s22.nr_turno == 2) & (s22.sg_uf != "ZZ")]
    linhas = [benford_linha("2026 T2 Lula", bu.lula.to_numpy()),
              benford_linha("2026 T2 Flávio", bu.flavio.to_numpy()),
              benford_linha("2022 T2 Lula", s22t2.lula.to_numpy()),
              benford_linha("2022 T2 Bolsonaro", s22t2.bolsonaro.to_numpy())]
    # nulo sem fraude: cada seção sorteia votos com a participação do seu município
    rng = np.random.default_rng(SEMENTE)
    g = bu.groupby(["sg_uf", "cd_municipio_tse"])
    p = (g.lula.transform("sum") / g.validos.transform("sum")).fillna(0.5).to_numpy()
    sim_l = rng.binomial(bu.validos.to_numpy(), p)
    linhas += [benford_linha("simulação sem fraude, Lula", sim_l),
               benford_linha("simulação sem fraude, Flávio", bu.validos.to_numpy() - sim_l)]
    t = pd.DataFrame(linhas)
    N["a02"] = {r.serie: {"mad_1d": round(r.mad_1d, 4), "mad_2d": round(r.mad_2d, 4)} for r in t.itertuples()}
    N["a02"]["validos_por_secao_mediana"] = float(bu.validos.median())
    N["a02"]["validos_por_secao_p10_p90"] = [float(bu.validos.quantile(.1)), float(bu.validos.quantile(.9))]
    return t


def _t1(D: dict) -> pd.DataFrame:
    t1 = D["vl"][D["vl"].nr_turno == 1][["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao", "lula", "nominais"]]
    return t1.rename(columns={"lula": "lula_t1", "nominais": "nominais_t1"})


def a03_biometria(D: dict, N: dict) -> pd.DataFrame:
    """'Habilitações sem biometria ("votos manuais") superam a margem e explicam o resultado.'"""
    bu = D["bu"].merge(_t1(D), on=["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"], how="left")
    bu = bu[bu.comparecimento > 0].copy()
    bu["mun"] = bu.sg_uf + bu.cd_municipio_tse
    bu["sem_bio"] = bu.hab_sem_biometria + bu.hab_biometria_falhou
    bu["pct_sem_bio"] = 100 * bu.sem_bio / bu.comparecimento
    bu["pct_lula_t2"] = 100 * bu.lula / bu.validos
    bu["pct_lula_t1"] = 100 * bu.lula_t1 / bu.nominais_t1
    bu["delta_lula"] = bu.pct_lula_t2 - bu.pct_lula_t1
    linhas = []
    for y, rot in [("pct_lula_t2", "participação de Lula no 2º turno (p.p.)"),
                   ("pct_lula_t1", "placebo: participação de Lula no 1º turno (p.p.)"),
                   ("delta_lula", "variação da participação de Lula, 1º→2º turno (p.p.)")]:
        r = fe_wls(bu, y, ["pct_sem_bio"], "mun", "validos").iloc[0].to_dict()
        linhas.append({"desfecho": rot, **r})
    t = pd.DataFrame(linhas)
    # quintis de habilitação sem digital, dentro do município: variação de Lula por quintil
    bu["q"] = bu.groupby("mun").pct_sem_bio.rank(pct=True).mul(5).clip(upper=4.999).astype(int) + 1
    bu["delta_mun"] = bu.delta_lula - bu.groupby("mun").delta_lula.transform("mean")
    q = bu.groupby("q").apply(lambda g: pd.Series({
        "secoes": len(g), "pct_sem_bio_medio": np.average(g.pct_sem_bio, weights=g.comparecimento),
        "delta_lula_rel_municipio": np.average(g.delta_mun.fillna(0), weights=g.validos)}),
        include_groups=False).reset_index()
    N["a03"] = {"habilitados_sem_digital": int(bu.sem_bio.sum()),
                "sem_biometria_cadastrada": int(bu.hab_sem_biometria.sum()),
                "biometria_nao_reconhecida": int(bu.hab_biometria_falhou.sum()),
                "comparecimento": int(bu.comparecimento.sum()),
                "pct_sem_digital": round(100 * bu.sem_bio.sum() / bu.comparecimento.sum(), 2),
                "regressoes": t.round(4).to_dict("records"), "quintis": q.round(3).to_dict("records")}
    return pd.concat([t.assign(tabela="regressao"), q.assign(tabela="quintil")], ignore_index=True)


def a04_unanimes(D: dict, N: dict) -> pd.DataFrame:
    """'Seções com 100% para um candidato provam fraude.'"""
    bu, s22 = D["bu"], D["s22"]
    s22t2 = s22[(s22.nr_turno == 2) & (s22.sg_uf != "ZZ")]
    lin = []
    for ano, d, a, b in [(2026, bu, "lula", "flavio"), (2022, s22t2, "lula", "bolsonaro")]:
        d = d[(d[a] + d[b]) > 0]
        for cand, outro, nome in [(a, b, "Lula"), (b, a, "adversário")]:
            u = d[d[outro] == 0]
            lin.append({"ano": ano, "so_votos_para": nome, "secoes": len(u), "secoes_total": len(d),
                        "votos": int(u[cand].sum()),
                        "ufs": "; ".join(f"{k} {v}" for k, v in u.sg_uf.value_counts().items())})
    t = pd.DataFrame(lin)
    marg = int(bu.lula.sum() - bu.flavio.sum())
    u26 = t[(t.ano == 2026) & (t.so_votos_para == "Lula")].iloc[0]
    # concentração ≥ 95% em qualquer direção (seções com pelo menos 50 válidos)
    d = bu[bu.validos >= 50]
    N["a04"] = {**{f"{r.ano}_{r.so_votos_para}": {"secoes": r.secoes, "votos": r.votos} for r in t.itertuples()},
                "margem": marg, "pct_margem_unanimes_lula": round(100 * u26.votos / marg, 3),
                "secoes_95_lula": int((d.lula >= .95 * d.validos).sum()),
                "secoes_95_flavio": int((d.flavio >= .95 * d.validos).sum())}
    return t


def _intervalos(mod: pd.DataFrame) -> pd.DataFrame:
    m = mod.dropna().groupby("modelo").nr_urna.agg(["min", "max", "size"]).sort_values("min").reset_index()
    return m


def a06_modelo_urna(D: dict, N: dict) -> pd.DataFrame:
    """'Urnas de modelos antigos deram mais votos a Lula' (tese de 2022 que voltou)."""
    mod = D["mod"].dropna()
    iv = _intervalos(mod)
    # sobreposição entre faixas invalida a extrapolação
    sobre = any(iv["min"].iloc[k + 1] <= iv["max"].iloc[k] for k in range(len(iv) - 1))
    bu = D["bu"].merge(_t1(D), on=["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"], how="left")
    bu["modelo"] = None
    for r in iv.itertuples():
        bu.loc[bu.nr_urna.between(r.min, r.max), "modelo"] = r.modelo
    # validação: a faixa reproduz o modelo do log nas seções com log
    chk = mod.copy()
    chk["pred"] = None
    for r in iv.itertuples():
        chk.loc[chk.nr_urna.between(r.min, r.max), "pred"] = r.modelo
    acerto = float((chk.pred == chk.modelo).mean())
    bu = bu[bu.validos > 0].merge(D["aptos"][["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao", "nr_local_votacao"]],
                                  on=["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"], how="left")
    bu["mun"] = bu.sg_uf + bu.cd_municipio_tse
    bu["local"] = bu.mun + "-" + bu.nr_zona + "-" + bu.nr_local_votacao.astype(str)
    bu["pct_lula_t2"] = 100 * bu.lula / bu.validos
    bu["delta_lula"] = bu.pct_lula_t2 - 100 * bu.lula_t1 / bu.nominais_t1
    bruto = bu.dropna(subset=["modelo"]).groupby("modelo").apply(lambda g: pd.Series({
        "secoes": len(g), "pct_lula_t2": 100 * g.lula.sum() / g.validos.sum(),
        "pct_nordeste": 100 * (g.regiao == "Nordeste").mean()}), include_groups=False).reset_index()
    ref = "UE2020" if "UE2020" in set(bu.modelo) else sorted(set(bu.modelo.dropna()))[-1]
    dummies = [m for m in sorted(set(bu.modelo.dropna())) if m != ref]
    for m in dummies:
        bu["m_" + m] = (bu.modelo == m).astype(float)
    xs = ["m_" + m for m in dummies]
    b = bu.dropna(subset=["modelo"])
    fe2 = fe_wls(b, "pct_lula_t2", xs, "mun", "validos").assign(desfecho="pct_lula_t2")
    fed = fe_wls(b, "delta_lula", xs, "mun", "validos").assign(desfecho="delta_lula")
    # mesmo local de votação: seções da mesma escola com urnas de modelos diferentes
    fel = fe_wls(b, "pct_lula_t2", xs, "local", "validos").assign(desfecho="pct_lula_t2_mesmo_local")
    fe = pd.concat([fe2, fed, fel], ignore_index=True)
    fe["termo"] = fe.termo.str[2:] + " − " + ref
    # controle: 2022, com o modelo informado pelo TSE no detalhe por seção
    d22 = D["d22"][(D["d22"].nr_turno == 2) & (D["d22"].sg_uf != "ZZ") & (D["d22"].modelo != "#NULO#")]
    v22 = D["s22"][D["s22"].nr_turno == 2].merge(d22, on=["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"])
    v22 = v22.assign(validos=v22.lula + v22.bolsonaro, mun=v22.sg_uf + v22.cd_municipio_tse.astype(str),
                     modelo=v22.modelo.str.replace(" ", ""))
    v22 = v22[v22.validos > 0].copy()
    v22["pct_lula_t2"] = 100 * v22.lula / v22.validos
    bruto22 = v22.groupby("modelo").apply(lambda g: pd.Series({
        "secoes": len(g), "pct_lula_t2": 100 * g.lula.sum() / g.validos.sum(),
        "pct_nordeste": 100 * (g.sg_uf.map(REGIAO) == "Nordeste").mean()}), include_groups=False).reset_index()
    ref22 = "UE2020"
    for m in sorted(set(v22.modelo)):
        v22["m_" + m] = (v22.modelo == m).astype(float)
    xs22 = ["m_" + m for m in sorted(set(v22.modelo)) if m != ref22]
    v22["local"] = v22.mun + "-" + v22.nr_zona.astype(str) + "-" + v22.nr_local_votacao.astype(str)
    fe22 = pd.concat([fe_wls(v22, "pct_lula_t2", xs22, "mun", "validos").assign(desfecho="pct_lula_t2_2022"),
                      fe_wls(v22, "pct_lula_t2", xs22, "local", "validos").assign(desfecho="pct_lula_t2_2022_mesmo_local")],
                     ignore_index=True)
    fe22["termo"] = fe22.termo.str[2:] + " − " + ref22
    # mesma seção em 2022 e 2026: entre as que usaram UE2020 em 2022, as que passaram a um modelo
    # antigo em 2026 mudaram a participação de Lula de forma diferente das que seguiram com UE2020?
    chave = ["sg_uf", "mun_i", "zona_i", "secao_i"]
    a26 = b.assign(mun_i=b.cd_municipio_tse.astype(int), zona_i=b.nr_zona.astype(int), secao_i=b.nr_secao.astype(int))
    a22 = v22.assign(mun_i=v22.cd_municipio_tse.astype(int), zona_i=v22.nr_zona.astype(int),
                     secao_i=v22.nr_secao.astype(int))[chave + ["pct_lula_t2", "modelo"]]
    pn = a26.merge(a22, on=chave, suffixes=("", "_2022"))
    pn = pn[pn.modelo_2022 == "UE2020"].copy()
    pn["delta_2022_2026"] = pn.pct_lula_t2 - pn.pct_lula_t2_2022
    fep = pd.concat([fe_wls(pn, "delta_2022_2026", xs, "mun", "validos").assign(desfecho="delta_2022_2026_mesma_secao"),
                     fe_wls(pn, "delta_2022_2026", xs, "local", "validos").assign(desfecho="delta_2022_2026_mesma_secao_mesmo_local")],
                    ignore_index=True)
    fep["termo"] = fep.termo.str[2:] + " − " + ref
    # teto: se toda a diferença no mesmo local fosse fraude, quanto mudaria a margem (2 × p.p. × válidos)
    teto = sum(2 * max(r.coef, 0) / 100 * b.loc[b.modelo == r.termo.split(" ")[0], "validos"].sum()
               for r in fel.assign(termo=fel.termo.str[2:]).itertuples())
    fe = pd.concat([fe, fe22, fep], ignore_index=True)
    N["a06_2022"] = {"secoes": int(len(v22)), "bruto": bruto22.round(2).to_dict("records"),
                     "efeito_fixo": fe22.round(3).to_dict("records")}
    N["a06_painel"] = {"secoes_pareadas_ue2020_em_2022": int(len(pn)),
                       "modelo_2026": pn.modelo.value_counts().to_dict(),
                       "efeito_fixo": fep.round(3).to_dict("records")}
    N["a06"] = {"logs_com_modelo": int(len(mod)), "faixas": iv.to_dict("records"), "faixas_sobrepostas": sobre,
                "acerto_faixa_vs_log": round(acerto, 4),
                "secoes_com_modelo_atribuido": int(bu.modelo.notna().sum()), "secoes": int(len(bu)),
                "referencia": ref, "bruto": bruto.round(2).to_dict("records"),
                "efeito_fixo": fe[fe.desfecho.isin(["pct_lula_t2", "delta_lula", "pct_lula_t2_mesmo_local"])
                                  ].round(3).to_dict("records"),
                "teto_margem_se_diferenca_mesmo_local_fosse_fraude": int(round(teto)),
                "margem": int(b.lula.sum() - b.flavio.sum())}
    return pd.concat([bruto.assign(tabela="bruto_2026"), bruto22.assign(tabela="bruto_2022"),
                      fe.assign(tabela="efeito_fixo")], ignore_index=True)


def a07_uf(D: dict, N: dict) -> pd.DataFrame:
    """'Lula ganhou 2 milhões de votos na Bahia depois da decisão do STF' e 'virada impossível'."""
    vl = D["vl"]
    g = vl.groupby(["sg_uf", "nr_turno"])[["lula", "flavio"]].sum().unstack("nr_turno")
    t = pd.DataFrame({"lula_t1": g[("lula", 1)], "lula_t2": g[("lula", 2)],
                      "flavio_t1": g[("flavio", 1)], "flavio_t2": g[("flavio", 2)]}).reset_index()
    t["delta_lula"] = t.lula_t2 - t.lula_t1
    t["delta_flavio"] = t.flavio_t2 - t.flavio_t1
    bu = D["bu"]
    tard = bu[bu.encerramento_br > pd.Timestamp("2026-10-25 17:10:00")].groupby("sg_uf").agg(
        secoes_encerradas_apos_17h10=("lula", "size"), lula_nessas_secoes_dia_todo=("lula", "sum"))
    t = t.merge(tard, on="sg_uf", how="left").sort_values("delta_lula", ascending=False)
    t["rank_delta_lula"] = np.arange(1, len(t) + 1)
    ba = t[t.sg_uf == "BA"].iloc[0]
    N["a07"] = {"BA_delta_lula": int(ba.delta_lula), "BA_rank": int(ba.rank_delta_lula),
                "BA_secoes_apos_17h10": int(ba.secoes_encerradas_apos_17h10),
                "BA_lula_nessas_secoes_dia_todo": int(ba.lula_nessas_secoes_dia_todo),
                "ufs_lula_cresceu": int((t.delta_lula > 0).sum()), "ufs_flavio_cresceu": int((t.delta_flavio > 0).sum()),
                "delta_lula_brasil": int(t.delta_lula.sum()), "delta_flavio_brasil": int(t.delta_flavio.sum())}
    return t


def a08_teixeira(D: dict, N: dict) -> pd.DataFrame:
    """'Somei três BUs em Teixeira de Freitas (BA) e a diferença (164) não bate com o TSE (93).'"""
    bu = D["bu"]
    cod = "39934"   # Teixeira de Freitas (BA), zona 183: código TSE conferido no BU web do 1º turno
    m = bu[(bu.sg_uf == "BA") & (bu.cd_municipio_tse == cod)].copy()
    m["margem"] = m.lula - m.flavio
    s = m.margem.sort_values()
    rng = np.random.default_rng(SEMENTE)
    trios = np.array([rng.choice(m.margem.to_numpy(), 3, replace=False).sum() for _ in range(100_000)])
    N["a08"] = {"cd_municipio_tse": cod, "secoes_com_bu": int(len(m)), "margem_municipio": int(m.margem.sum()),
                "lider": "Lula" if m.margem.sum() > 0 else "Flávio",
                "trio_mais_favoravel_a_flavio": int(s.head(3).sum()), "trio_mais_favoravel_a_lula": int(s.tail(3).sum()),
                "pct_trios_abs_164_ou_mais": round(100 * float((np.abs(trios) >= 164).mean()), 2),
                "pct_trios_mesmo_sinal_que_municipio": round(100 * float((np.sign(trios) == np.sign(m.margem.sum())).mean()), 2)}
    return m[["nr_zona", "nr_secao", "lula", "flavio", "margem"]].sort_values("margem")


def a09_secoes_regiao(D: dict, N: dict) -> pd.DataFrame:
    """'Reduziram seções no Nordeste para prejudicar Lula' (alegação a favor de Lula)."""
    bu, s22 = D["bu"], D["s22"]
    s22t2 = s22[(s22.nr_turno == 2) & (s22.sg_uf != "ZZ")].assign(regiao=lambda d: d.sg_uf.map(REGIAO))
    d22 = D["d22"][(D["d22"].nr_turno == 2) & (D["d22"].sg_uf != "ZZ")].assign(regiao=lambda d: d.sg_uf.map(REGIAO))
    a = s22t2.groupby("regiao").agg(secoes_2022=("lula", "size"), nominais_2022=("nominais", "sum")).join(
        d22.groupby("regiao").agg(aptos_2022=("aptos", "sum")))
    b26 = bu.merge(D["aptos"], on=["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"], how="left")
    b = b26.groupby("regiao").agg(secoes_2026=("lula", "size"), aptos_2026=("aptos", "sum"),
                                  comparecimento_2026=("comparecimento", "sum"), validos_2026=("validos", "sum"))
    t = a.join(b).reset_index()
    t["aptos_por_secao_2022"] = t.aptos_2022 / t.secoes_2022
    t["aptos_por_secao_2026"] = t.aptos_2026 / t.secoes_2026
    t["var_secoes_pct"] = 100 * (t.secoes_2026 / t.secoes_2022 - 1)
    t["validos_por_secao_2022"] = t.nominais_2022 / t.secoes_2022
    t["validos_por_secao_2026"] = t.validos_2026 / t.secoes_2026
    N["a09"] = t.round(2).to_dict("records")
    return t


def a10_curva_totalizacao(D: dict, N: dict, root: Path) -> pd.DataFrame:
    """'O painel virou depois das 19h: os votos da prorrogação mudaram o resultado.'

    Reconstrói a curva do painel pela primeira totalização de cada seção (horário do TSE, Brasília),
    com o exterior, e mostra quem estava entrando no painel em cada momento.
    """
    st = root / "data/staging"
    tot = duckdb.sql(f"""
        select sg_uf, cd_municipio_tse, nr_zona, nr_secao,
               strptime(ts_bruto, '%d/%m/%Y %H:%M:%S') as ts
        from read_parquet('{(st / 'closure/*_T2.parquet').as_posix()}')
        where semantica = 'PRIMEIRA_TOTALIZACAO_TSE'""").df()
    vl = duckdb.sql(f"""
        select sg_uf, cd_municipio_tse, nr_zona, nr_secao,
               sum(case when nr_votavel = 13 then qt_votos else 0 end) as lula,
               sum(case when nr_votavel = 22 then qt_votos else 0 end) as flavio
        from read_parquet('{(st / 'votes_long/*_T2.parquet').as_posix()}')
        where cd_cargo = 1 group by all""").df()
    k = ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
    d = vl.merge(tot, on=k, how="left")
    enc = D["bu"][k + ["encerramento_br"]]
    d = d.merge(enc, on=k, how="left")
    d["tardia"] = d.encerramento_br > pd.Timestamp("2026-10-25 17:10:00")
    d["regiao"] = d.sg_uf.map(REGIAO).fillna("Exterior")
    d = d.sort_values("ts")
    d["minuto"] = d.ts.dt.floor("5min")
    g = d.groupby("minuto").agg(secoes=("lula", "size"), lula=("lula", "sum"), flavio=("flavio", "sum"),
                                tardias=("tardia", "sum"))
    for r in ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul", "Exterior"]:
        g["validos_" + r] = d[d.regiao == r].assign(v=lambda x: x.lula + x.flavio).groupby("minuto").v.sum()
    g = g.fillna(0)
    c = g.cumsum()
    c["pct_lula_acumulado"] = 100 * c.lula / (c.lula + c.flavio)
    c["secoes_acumuladas_pct"] = 100 * c.secoes / len(d)
    c["lider"] = np.where(c.lula >= c.flavio, "Lula", "Flávio")
    for r in ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul", "Exterior"]:
        c["pct_validos_" + r] = 100 * c["validos_" + r] / (c.lula + c.flavio)
    c = c.reset_index()
    trocas = c[c.lider != c.lider.shift()]
    # a mesma curva sem nenhuma seção encerrada depois das 17h10
    s = d[~d.tardia].groupby("minuto")[["lula", "flavio"]].sum().cumsum()
    s["lider"] = np.where(s.lula >= s.flavio, "Lula", "Flávio")
    s = s.reset_index()
    trocas_sem = s[s.lider != s.lider.shift()]
    c = c.merge(s.assign(pct_lula_sem_tardias=100 * s.lula / (s.lula + s.flavio))[["minuto", "pct_lula_sem_tardias"]],
                on="minuto", how="left")
    c["pct_lula_sem_tardias"] = c.pct_lula_sem_tardias.ffill()
    marco = lambda hhmm: c[c.minuto <= pd.Timestamp(f"2026-10-25 {hhmm}")].iloc[-1]  # noqa: E731
    N["a10"] = {"secoes": int(len(d)), "sem_horario_totalizacao": int(d.ts.isna().sum()),
                "trocas_de_lider_sem_secoes_tardias": [{"minuto": str(r.minuto), "lider": r.lider}
                                                       for r in trocas_sem.itertuples()],
                "trocas_de_lider": [{"minuto": str(r.minuto), "lider": r.lider,
                                     "pct_lula": round(r.pct_lula_acumulado, 2),
                                     "secoes_pct": round(r.secoes_acumuladas_pct, 1)} for r in trocas.itertuples()],
                "marcos": {h: {"pct_lula": round(float(marco(h).pct_lula_acumulado), 2),
                               "secoes_pct": round(float(marco(h).secoes_acumuladas_pct), 1),
                               "tardias_no_painel": int(marco(h).tardias),
                               "pct_validos_nordeste": round(float(marco(h).pct_validos_Nordeste), 1),
                               "pct_validos_sudeste": round(float(marco(h).pct_validos_Sudeste), 1)}
                           for h in ["17:10", "19:00", "19:45", "20:25", "23:30"]}}
    return c


def figuras(tab: Path, fig_dir: Path) -> None:
    """Figuras A1–A3 do relatório de alegações, na paleta editorial do projeto."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from br2026.reporting.pilot_comparative import PALETTE as P

    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "axes.edgecolor": "#cbd5e1", "axes.linewidth": 0.8, "axes.grid": True,
        "grid.color": P["grid"], "grid.linestyle": "--", "grid.linewidth": 0.6, "grid.alpha": 0.7,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "savefig.dpi": 200,
    })
    fig_dir.mkdir(parents=True, exist_ok=True)
    fmt = lambda v: f"{v:,.0f}".replace(",", ".")  # noqa: E731

    # A1: curva do painel com e sem as seções encerradas depois das 17h10
    c = pd.read_csv(tab / "alegacoes_a10_curva_totalizacao.csv", parse_dates=["minuto"])
    c = c[c.minuto >= pd.Timestamp("2026-10-25 19:00")]
    fig, ax = plt.subplots(figsize=(10, 4.8), constrained_layout=True)
    ax.plot(c.minuto, c.pct_lula_acumulado, color=P["navy"], linewidth=2, label="Painel completo")
    ax.plot(c.minuto, c.pct_lula_sem_tardias, color=P["abstencao"], linewidth=2, linestyle="--",
            label="Sem nenhuma seção encerrada depois das 17h10")
    ax.axhline(50, color="#334155", linewidth=0.8)
    ax.set_ylabel("Lula, % dos votos dos dois candidatos")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Hh%M"))
    ax.set_xlim(pd.Timestamp("2026-10-25 19:00"), pd.Timestamp("2026-10-25 21:30"))
    ax.set_ylim(49, 53)
    ax.legend(fontsize=8.5, loc="upper right")
    ax.set_title("Figura A1 — Painel de totalização reconstruído: a 'virada' acontece mesmo sem as seções tardias",
                 fontsize=10.5, fontweight="bold", color=P["navy"])
    fig.savefig(fig_dir / "figA1_curva_totalizacao.png")
    plt.close(fig)

    # A2: margem por horário de encerramento e pior caso
    t = pd.read_csv(tab / "alegacoes_a01_secoes_tardias.csv")
    rot = {"b) 17h00–17h10": "Encerradas até 17h10\n(484.541 seções)",
           "c) 17h10–19h00": "17h10 a 19h\n(7.004)", "d) 19h00 ou depois": "19h ou depois\n(6.352)",
           "pior caso: todo voto do dia nas seções tardias para Flávio":
               "Pior caso: todo voto do dia\nnas seções tardias para Flávio"}
    t = t[t.faixa.isin(rot)]
    fig, ax = plt.subplots(figsize=(9.5, 4.6), constrained_layout=True)
    y = np.arange(len(t))[::-1]
    cores = [P["lula"] if k != list(rot)[3] else P["abstencao"] for k in t.faixa]
    ax.barh(y, t.margem_lula / 1e6, color=cores, height=0.6)
    for yi, v in zip(y, t.margem_lula):
        ax.annotate(f"+{fmt(v)}", (v / 1e6, yi), xytext=(4, 0), textcoords="offset points", va="center", fontsize=8.5)
    ax.set_yticks(y)
    ax.set_yticklabels([rot[f] for f in t.faixa], fontsize=8.5)
    ax.axvline(0, color="#334155", linewidth=0.8)
    ax.set_xlabel("Vantagem de Lula sobre Flávio (milhões de votos)")
    ax.set_xlim(0, 4.6)
    ax.set_title("Figura A2 — Lula vence no horário normal e também no pior caso",
                 fontsize=10.5, fontweight="bold", color=P["navy"])
    fig.savefig(fig_dir / "figA2_margem_por_encerramento.png")
    plt.close(fig)

    # A3: 1º dígito — dados reais de 2026 e 2022 e simulação sem fraude, contra a lei de Benford
    b = pd.read_csv(tab / "alegacoes_a02_benford.csv").set_index("serie")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True, constrained_layout=True)
    d = np.arange(1, 10)
    for ax, (cand, s26, s22, ssim) in zip(axes, [("Lula", "2026 T2 Lula", "2022 T2 Lula", "simulação sem fraude, Lula"),
                                                 ("Adversário", "2026 T2 Flávio", "2022 T2 Bolsonaro",
                                                  "simulação sem fraude, Flávio")]):
        ax.bar(d, 100 * BENFORD1, color="#e2e8f0", width=0.8, label="Lei de Benford")
        for serie, cor, mk, lab in [(s26, P["lula"] if cand == "Lula" else P["flavio"], "o", "2026, real"),
                                    (s22, P["terceiros"], "s", "2022, real"),
                                    (ssim, P["navy"], "x", "2026, simulação sem fraude")]:
            ax.plot(d, [100 * b.loc[serie, f"p1_{k}"] for k in d], marker=mk, color=cor, linewidth=1.4,
                    markersize=6, label=f"{lab} (MAD {b.loc[serie, 'mad_1d']:.3f})".replace(".", ","))
        ax.set_xticks(d)
        ax.set_xlabel("Primeiro dígito dos votos por seção")
        ax.set_title(f"{cand}", fontsize=10, fontweight="bold", color=P["navy"])
        ax.legend(fontsize=7.5)
    axes[0].set_ylabel("% das seções")
    fig.suptitle("Figura A3 — O 1º dígito foge de Benford igualmente nos dados reais e numa eleição simulada sem fraude",
                 fontsize=10.5, fontweight="bold", color=P["navy"])
    fig.savefig(fig_dir / "figA3_benford.png")
    plt.close(fig)


def analisar(root: Path, repo: Path) -> int:
    D = carregar(root)
    N: dict = {}
    tab = repo / "reports/analysis/tabelas_nacional"
    ev = repo / "reports/analysis/evidencias_nacional"
    tab.mkdir(parents=True, exist_ok=True)
    ev.mkdir(parents=True, exist_ok=True)
    passos = [("a00_integridade", a00_integridade), ("a01_secoes_tardias", a01_secoes_tardias),
              ("a02_benford", a02_benford), ("a03_biometria", a03_biometria), ("a04_unanimes", a04_unanimes),
              ("a06_modelo_urna", a06_modelo_urna), ("a07_uf", a07_uf), ("a08_teixeira", a08_teixeira),
              ("a09_secoes_regiao", a09_secoes_regiao)]
    for nome, f in passos:
        t = f(D, N)
        t.to_csv(tab / f"alegacoes_{nome}.csv", index=False)
        print(nome, "ok")
    a10_curva_totalizacao(D, N, root).to_csv(tab / "alegacoes_a10_curva_totalizacao.csv", index=False)
    print("a10_curva_totalizacao ok")
    figuras(tab, repo / "reports/analysis/figuras_alegacoes")
    print("figuras ok")
    (ev / "alegacoes_numeros.json").write_text(json.dumps(N, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0
