"""Contexto socioeconômico × variação T1–T2 (handoff 37; plano em docs/methodology/PLANO_ESTATISTICO_37.md).

Três níveis, todos associações territoriais (não efeitos causais, não votos individuais):

1. **Faixas municipais**: quintis de cada indicador fixados uma vez entre os municípios do território
   (sem peso; empates na mesma faixa). Votação por faixa = soma dos votos / soma dos válidos.
2. **Modelos municipais**: uma observação por município; um indicador por vez; bruto e ajustado na
   mesma amostra; efeito fixo de UF; peso = aptos do 1º turno; erros agrupados por região geográfica
   imediata do IBGE.
3. **Entorno dos locais**: unidades do painel dentro do município (efeito fixo de município), erros
   agrupados pelo local de votação que as unidades compartilham.

Indicadores municipais (Censo 2022, RAIS 2025, PBF 08/2026) chegam pelo contrato longo das frentes
34/35; o entorno, pelas saídas da frente 36. Cada join é conferido por linhas e votos.
"""
from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from br2026.analysis import associations as assoc

LN2 = math.log(2.0)

# indicador -> (arquivo staging, nome no contrato, período, transformação, incremento, rótulo da escala)
INDICADORES = {
    "renda_pc": ("socio_ibge/socio_ibge_long.parquet", "renda_domiciliar_per_capita_media", "2022", "log",
                 LN2, "por duplicação da renda domiciliar per capita média"),
    "baixa_renda": ("socio_ibge/socio_ibge_long.parquet", "pct_pessoas_baixa_renda_ate_meio_sm", "2022", "nivel",
                    10.0, "por +10 p.p. de pessoas com até ½ salário mínimo"),
    "desocupacao": ("socio_ibge/socio_ibge_long.parquet", "taxa_desocupacao", "2022", "nivel",
                    5.0, "por +5 p.p. na taxa de desocupação"),
    "vinculos": ("socio_rais/socio_rais_2025.parquet", "vinculos_formais_por_mil_hab", "2025-12-31", "nivel",
                 100.0, "por +100 vínculos formais por mil habitantes"),
    "pbf": ("socio_pbf/socio_pbf_202608.parquet", "registros_pbf_por_100_domicilios_2022", "2026-08", "nivel",
            10.0, "por +10 registros do PBF por 100 domicílios"),
    "urbana": ("socio_ibge/socio_ibge_long.parquet", "pct_populacao_urbana", "2022", "nivel",
               10.0, "por +10 p.p. de população urbana"),
}
SENSIBILIDADES = {
    "renda_pc_mediana": ("socio_ibge/socio_ibge_long.parquet", "renda_domiciliar_per_capita_mediana", "2022", "log",
                         LN2, "por duplicação da renda domiciliar per capita mediana"),
    "participacao": ("socio_ibge/socio_ibge_long.parquet", "taxa_participacao_forca_trabalho", "2022", "nivel",
                     10.0, "por +10 p.p. na participação na força de trabalho"),
    "vinculos_2023": ("socio_rais/socio_rais_2023.parquet", "vinculos_formais_por_mil_hab", "2023-12-31", "nivel",
                      100.0, "por +100 vínculos formais por mil habitantes (RAIS 2023)"),
    "pbf_2024": ("socio_pbf/socio_pbf_202406.parquet", "registros_pbf_por_100_domicilios_2022", "2024-06", "nivel",
                 10.0, "por +10 registros do PBF por 100 domicílios (06/2024)"),
}
ROTULO = {"renda_pc": "Renda domiciliar per capita média", "baixa_renda": "Pessoas com até ½ salário mínimo",
          "desocupacao": "Taxa de desocupação", "vinculos": "Vínculos formais por mil hab.",
          "pbf": "Registros do Bolsa Família por 100 domicílios", "urbana": "População urbana",
          "renda_pc_mediana": "Renda domiciliar per capita mediana", "participacao": "Participação na força de trabalho",
          "vinculos_2023": "Vínculos formais por mil hab. (2023)", "pbf_2024": "Registros do PBF por 100 dom. (06/2024)"}
DESFECHOS = ("delta_share_lula_validos", "delta_comparecimento_aptos", "delta_margem_lula_flavio_validos")
REGIAO = {"1": "Norte", "2": "Nordeste", "3": "Sudeste", "4": "Sul", "5": "Centro-Oeste"}
LOCALIDADES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"


# --------------------------------------------------------------------------- insumos
def regioes_imediatas(raiz: Path, offline: bool = False) -> pd.DataFrame:
    """Município IBGE → região geográfica imediata (agrupamento espacial dos erros) e grande região."""
    pasta = raiz / "data" / "raw" / "ibge_localidades"
    arq = pasta / "municipios.json"
    if not arq.exists():
        if offline:
            raise FileNotFoundError(f"{arq} ausente e execução offline")
        pasta.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(LOCALIDADES_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            corpo = r.read()
        if corpo[:2] == b"\x1f\x8b":                        # a API pode responder em gzip
            import gzip
            corpo = gzip.decompress(corpo)
        json.loads(corpo)                                   # resposta inválida não é promovida
        tmp = arq.with_suffix(".tmp")
        tmp.write_bytes(corpo)
        tmp.replace(arq)
    js = json.loads(arq.read_text(encoding="utf-8"))
    linhas = []
    for m in js:
        ri = m.get("regiao-imediata") or {}
        rint = ri.get("regiao-intermediaria") or {}
        uf = (rint.get("UF") or {})
        linhas.append({"cd_municipio_ibge": str(m["id"]).zfill(7), "cd_regiao_imediata": str(ri.get("id")),
                       "sg_uf_ibge": uf.get("sigla")})
    out = pd.DataFrame(linhas)
    out["regiao"] = out.cd_municipio_ibge.str[0].map(REGIAO)
    if out.cd_municipio_ibge.duplicated().any():
        raise ValueError("município repetido na lista de localidades")
    return out


def _longo(raiz: Path, arquivo: str, indicador: str, periodo: str) -> pd.DataFrame:
    d = pd.read_parquet(raiz / "data" / "staging" / arquivo)
    d = d[(d.indicador == indicador) & d.periodo_referencia.astype(str).str.startswith(periodo[:4])]
    if d.duplicated(["sg_uf", "cd_municipio_ibge"]).any():
        raise ValueError(f"{indicador}: mais de uma linha por município no período {periodo}")
    return d[["sg_uf", "cd_municipio_ibge", "cd_municipio_tse", "valor"]]


def indicadores_municipais(raiz: Path, offline: bool = False) -> pd.DataFrame:
    """Um registro por município IBGE com os indicadores principais e de sensibilidade (valor bruto)."""
    base = None
    for nome, (arq, ind, per, *_rest) in {**INDICADORES, **SENSIBILIDADES}.items():
        d = _longo(raiz, arq, ind, per).rename(columns={"valor": nome})
        d["cd_municipio_tse"] = d.cd_municipio_tse.astype("string").str.zfill(5)
        if base is None:
            base = d
        else:
            n0 = len(base)
            base = base.merge(d.drop(columns=["sg_uf"]), on=["cd_municipio_ibge"], how="outer",
                              suffixes=("", "_dup"), validate="one_to_one")
            if "cd_municipio_tse_dup" in base:
                conflito = (base.cd_municipio_tse.notna() & base.cd_municipio_tse_dup.notna()
                            & (base.cd_municipio_tse != base.cd_municipio_tse_dup))
                if conflito.any():
                    raise ValueError(f"{nome}: código TSE diverge entre fontes para o mesmo município IBGE")
                base["cd_municipio_tse"] = base.cd_municipio_tse.fillna(base.cd_municipio_tse_dup)
                base = base.drop(columns=["cd_municipio_tse_dup"])
            if len(base) < n0:
                raise ValueError("join de indicadores perdeu municípios")
    reg = regioes_imediatas(raiz, offline=offline)
    base = base.merge(reg, on="cd_municipio_ibge", how="left", validate="one_to_one")
    return base


def painel_municipal(raiz: Path, analytics: Path, offline: bool = False) -> tuple[pd.DataFrame, dict]:
    """`metrics_municipio` do território com os indicadores; auditoria de linhas e votos no join."""
    m = pd.read_csv(analytics / "metrics_municipio.csv", dtype={"cd_municipio_tse": str})
    m = m[m.sg_uf != "ZZ"].copy()
    m["cd_municipio_tse"] = m.cd_municipio_tse.str.zfill(5)
    ind = indicadores_municipais(raiz, offline=offline)
    ind = ind[ind.cd_municipio_tse.notna()]
    n0, v0 = len(m), (int(m.qt_votos_validos_t1.sum()), int(m.qt_votos_validos_t2.sum()))
    d = m.merge(ind.drop(columns=["sg_uf"]), on="cd_municipio_tse", how="left", validate="one_to_one")
    v1 = (int(d.qt_votos_validos_t1.sum()), int(d.qt_votos_validos_t2.sum()))
    if len(d) != n0 or v1 != v0:
        raise ValueError(f"join municipal alterou linhas ou votos: {n0}->{len(d)}, {v0}->{v1}")
    # controles (seção 7 do plano)
    d["log_aptos_t1"] = np.log(d.qt_aptos_t1.astype(float))
    v1_ = d.qt_votos_validos_t1.astype(float)
    d["share_demais_validos_t1"] = (v1_ - d.qt_lula_t1 - d.qt_flavio_t1) / v1_
    d["brancos_nulos_comparecimento_t1"] = (d.qt_votos_brancos_t1 + d.qt_votos_nulos_t1) / d.qt_comparecimento_t1
    audit = {"municipios_territorio": n0, "com_codigo_ibge": int(d.cd_municipio_ibge.notna().sum()),
             "sem_codigo_ibge": d.loc[d.cd_municipio_ibge.isna(), ["sg_uf", "cd_municipio_tse"]].to_dict("records"),
             "votos_validos_t1": v0[0], "votos_validos_t2": v0[1],
             "cobertura": {k: int(d[k].notna().sum()) for k in {**INDICADORES, **SENSIBILIDADES}},
             "com_regiao_imediata": int(d.cd_regiao_imediata.notna().sum())}
    return d, audit


def regressor(d: pd.DataFrame, nome: str) -> tuple[pd.Series, float, str]:
    """(variável transformada, incremento na escala da variável transformada, rótulo da escala)."""
    _, _, _, transf, inc, rot = {**INDICADORES, **SENSIBILIDADES}[nome]
    x = d[nome].astype(float)
    if transf == "log":
        x = np.log(x.where(x > 0))
    return x, inc, rot


# --------------------------------------------------------------------------- faixas
def cortes_quintis(v: pd.Series) -> np.ndarray:
    """Limites 20/40/60/80% dos valores observados (sem peso, valores efetivamente observados)."""
    v = v.dropna().to_numpy(float)
    return np.quantile(v, [0.2, 0.4, 0.6, 0.8], method="inverted_cdf")


def faixa(v: pd.Series, cortes: np.ndarray) -> pd.Series:
    """Faixa 1–5 = 1 + número de cortes estritamente menores que o valor; empates ficam juntos."""
    out = pd.Series(pd.NA, index=v.index, dtype="Int64")
    ok = v.notna()
    out[ok] = 1 + (v[ok].to_numpy(float)[:, None] > cortes[None, :]).sum(axis=1)
    return out


SOMAS = ["qt_aptos_t1", "qt_aptos_t2", "qt_comparecimento_t1", "qt_comparecimento_t2", "qt_votos_validos_t1",
         "qt_votos_validos_t2", "qt_lula_t1", "qt_lula_t2", "qt_flavio_t1", "qt_flavio_t2"]


def tabela_faixas(d: pd.DataFrame, nome: str, grupo: str | None = None) -> pd.DataFrame:
    """Votação por faixa (razão de somas), T1 e T2 na mesma amostra; cortes fixos no território."""
    cortes = cortes_quintis(d[nome])
    f = faixa(d[nome], cortes)
    dd = d.assign(faixa=f).dropna(subset=["faixa"])
    chaves = ["faixa"] if grupo is None else [grupo, "faixa"]
    g = dd.groupby(chaves)
    t = g[SOMAS].sum()
    t["municipios"] = g.size()
    t["valor_min"], t["valor_max"] = g[nome].min(), g[nome].max()
    t = t.reset_index()
    for k in (1, 2):
        t[f"share_lula_t{k}"] = t[f"qt_lula_t{k}"] / t[f"qt_votos_validos_t{k}"]
        t[f"share_flavio_t{k}"] = t[f"qt_flavio_t{k}"] / t[f"qt_votos_validos_t{k}"]
        t[f"comparecimento_t{k}"] = t[f"qt_comparecimento_t{k}"] / t[f"qt_aptos_t{k}"]
    t["delta_share_lula"] = t.share_lula_t2 - t.share_lula_t1
    t["delta_margem"] = (t.share_lula_t2 - t.share_flavio_t2) - (t.share_lula_t1 - t.share_flavio_t1)
    t["delta_comparecimento"] = t.comparecimento_t2 - t.comparecimento_t1
    t["delta_qt_lula"] = t.qt_lula_t2 - t.qt_lula_t1
    t["delta_qt_flavio"] = t.qt_flavio_t2 - t.qt_flavio_t1
    t["indicador"] = nome
    # faixa k vai de (corte k−1, corte k]; com empates pode haver menos de cinco faixas ocupadas
    fk = t.faixa.astype(int)
    t["corte_inferior"] = [cortes[k - 2] if k > 1 else np.nan for k in fk]
    t["corte_superior"] = [cortes[k - 1] if k < 5 else np.nan for k in fk]
    t["municipios_sem_indicador"] = int(d[nome].isna().sum())
    return t


# --------------------------------------------------------------------------- modelos municipais
CONTROLES_MUN = ["log_aptos_t1", "share_lula_validos_t1", "share_demais_validos_t1", "comparecimento_aptos_t1",
                 "brancos_nulos_comparecimento_t1"]


def _ajuste_fe(y, X, w, fe, cluster) -> dict:
    """WLS com efeito fixo absorvido (FWL) e erro agrupado CR1 (`assoc.clustered_fit`)."""
    G_fe = len(np.unique(fe))
    Xd, yd = assoc.demean(X, w, fe), assoc.demean(y, w, fe)
    if Xd.ndim == 1:
        Xd = Xd[:, None]
    return assoc.clustered_fit(Xd, yd, w, cluster, absorbed=G_fe)


def vif_primeiro(X: np.ndarray, w: np.ndarray, fe) -> float:
    """VIF do regressor (coluna 0) sobre os demais, após absorver o efeito fixo."""
    Xd = assoc.demean(X, w, fe)
    if Xd.ndim == 1 or Xd.shape[1] == 1:
        return 1.0
    x0, Z = Xd[:, 0], Xd[:, 1:]
    b = np.linalg.lstsq(Z * np.sqrt(w)[:, None], x0 * np.sqrt(w), rcond=None)[0]
    r = x0 - Z @ b
    r2 = 1 - np.sum(w * r ** 2) / np.sum(w * x0 ** 2)
    return float(1 / max(1 - r2, 1e-12))


def modelo_municipal(d: pd.DataFrame, nome: str, desfecho: str, pesos: str = "aptos",
                     cluster: str = "cd_regiao_imediata", excluir_grandes: bool = False) -> list[dict]:
    """Bruto e ajustado na mesma amostra; coeficientes já na escala editorial (p.p. por incremento)."""
    x, inc, rot = regressor(d, nome)
    ctrl = [c for c in CONTROLES_MUN] + ([] if nome == "urbana" else ["urbana"])
    base = d.assign(_x=x)
    cols = ["_x", desfecho, "sg_uf", cluster, "qt_aptos_t1"] + ctrl
    s = base.dropna(subset=cols)
    s = s[np.isfinite(s._x)]
    if excluir_grandes:
        s = s[s.qt_aptos_t1 <= 1_000_000]
    w = s.qt_aptos_t1.to_numpy(float) if pesos == "aptos" else np.ones(len(s))
    g = s[cluster].astype(str).to_numpy()
    fe = s.sg_uf.to_numpy()
    y = s[desfecho].to_numpy(float)
    out = []
    for espec, cols_x in (("bruto", ["_x"]), ("ajustado", ["_x"] + ctrl)):
        X = s[cols_x].to_numpy(float)
        f = _ajuste_fe(y, X, w, fe, g)
        fator = 100.0 * inc                     # desfecho em proporção → p.p.; regressor → incremento
        out.append({"indicador": nome, "desfecho": desfecho, "especificacao": espec, "pesos": pesos,
                    "cluster": cluster, "sem_grandes": excluir_grandes,
                    "beta": float(f["beta"][0]), "ep": float(f["se"][0]),
                    "efeito_pp": float(f["beta"][0]) * fator, "inf_pp": float(f["inf"][0]) * fator,
                    "sup_pp": float(f["sup"][0]) * fator, "escala": rot, "n": int(f["n"]),
                    "grupos": int(f["grupos"]), "vif": vif_primeiro(X, w, fe) if espec == "ajustado" else np.nan,
                    "x_p05": float(np.percentile(s[nome], 5)), "x_p50": float(np.percentile(s[nome], 50)),
                    "x_p95": float(np.percentile(s[nome], 95)),
                    "controles": "|".join(cols_x[1:]) + "|EF_UF",
                    "aviso": assoc.few_clusters_warning(int(f["grupos"])) or ""})
    return out


def modelos_municipais(d: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    for nome in INDICADORES:
        for y in DESFECHOS:
            linhas += modelo_municipal(d, nome, y)                                    # principal
            linhas += modelo_municipal(d, nome, y, pesos="iguais")                    # sensibilidade
            linhas += modelo_municipal(d, nome, y, cluster="sg_uf")
            linhas += modelo_municipal(d, nome, y, excluir_grandes=True)
            hc = d.assign(_obs=d.cd_municipio_tse + d.sg_uf)
            linhas += [{**r, "cluster": "HC1"} for r in modelo_municipal(hc, nome, y, cluster="_obs")]
    for nome in SENSIBILIDADES:
        for y in DESFECHOS:
            linhas += modelo_municipal(d, nome, y)
    out = pd.DataFrame(linhas)
    out["papel"] = np.where(out.indicador.isin(list(SENSIBILIDADES)), "sensibilidade_indicador",
                            np.where((out.pesos == "aptos") & (out.cluster == "cd_regiao_imediata") & ~out.sem_grandes,
                                     "principal", "sensibilidade"))
    return out


def modelo_conjunto(d: pd.DataFrame, desfecho: str) -> pd.DataFrame:
    """Todos os indicadores juntos (sensibilidade de colinearidade): coeficientes e VIF de cada um."""
    nomes = [n for n in INDICADORES if n != "urbana"] + ["urbana"]
    xs = {n: regressor(d, n) for n in nomes}
    base = d.assign(**{f"_x_{n}": xs[n][0] for n in nomes})
    cols = [f"_x_{n}" for n in nomes] + CONTROLES_MUN
    s = base.dropna(subset=cols + [desfecho, "cd_regiao_imediata"])
    s = s[np.isfinite(s[cols]).all(axis=1)]
    X, y, w = s[cols].to_numpy(float), s[desfecho].to_numpy(float), s.qt_aptos_t1.to_numpy(float)
    f = _ajuste_fe(y, X, w, s.sg_uf.to_numpy(), s.cd_regiao_imediata.astype(str).to_numpy())
    linhas = []
    for i, n in enumerate(nomes):
        fator = 100.0 * xs[n][1]
        Xr = np.column_stack([X[:, i], np.delete(X, i, axis=1)])
        linhas.append({"indicador": n, "desfecho": desfecho, "efeito_pp": f["beta"][i] * fator,
                       "inf_pp": f["inf"][i] * fator, "sup_pp": f["sup"][i] * fator, "n": f["n"],
                       "vif": vif_primeiro(Xr, w, s.sg_uf.to_numpy())})
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------- afinidade (perfis territoriais)
def perfis_bases(d: pd.DataFrame, rotulos_t1: dict[str, str] | None = None) -> pd.DataFrame:
    """Média de cada indicador ponderada pelos votos de cada base, mesma amostra de municípios."""
    nomes = list(INDICADORES)
    s = d.dropna(subset=nomes)
    bases = {"Lula, 1º turno": s.qt_lula_t1, "Lula, 2º turno": s.qt_lula_t2,
             "Flávio, 1º turno": s.qt_flavio_t1, "Flávio, 2º turno": s.qt_flavio_t2,
             "Demais candidatos, 1º turno": s.qt_votos_validos_t1 - s.qt_lula_t1 - s.qt_flavio_t1,
             "Brancos e nulos, 1º turno": s.qt_votos_brancos_t1 + s.qt_votos_nulos_t1,
             "Brancos e nulos, 2º turno": s.qt_votos_brancos_t2 + s.qt_votos_nulos_t2,
             "Abstenção, 1º turno": s.qt_aptos_t1 - s.qt_comparecimento_t1,
             "Abstenção, 2º turno": s.qt_aptos_t2 - s.qt_comparecimento_t2,
             "Aptos, 1º turno": s.qt_aptos_t1}
    for col, rot in (rotulos_t1 or {}).items():
        if col in s:
            bases[f"{rot}, 1º turno"] = s[col]
    linhas = []
    for base, w in bases.items():
        w = w.astype(float)
        linhas.append({"base": base, "votos": float(w.sum()), "municipios": int(len(s)),
                       **{n: float(np.average(s[n].astype(float), weights=w)) for n in nomes}})
    out = pd.DataFrame(linhas)
    for cand in ("Lula", "Flávio"):
        a = out.set_index("base").loc[f"{cand}, 2º turno", nomes] - out.set_index("base").loc[f"{cand}, 1º turno", nomes]
        out = pd.concat([out, pd.DataFrame([{"base": f"{cand}: 2º − 1º turno (diferença de perfil)", **a.to_dict()}])],
                        ignore_index=True)
    return out


def correlacoes_bases(d: pd.DataFrame, colunas_t1: dict[str, str]) -> pd.DataFrame:
    """Correlação (ponderada por aptos) entre a votação de cada base no 1º turno, por apto, e a variação
    de Lula e Flávio por apto. Associação entre municípios, não transferência."""
    s = d.copy()
    ap = s.qt_aptos_t1.astype(float)
    y = {"delta_lula_por_apto": (s.qt_lula_t2 - s.qt_lula_t1) / ap,
         "delta_flavio_por_apto": (s.qt_flavio_t2 - s.qt_flavio_t1) / ap,
         "delta_comparecimento_por_apto": (s.qt_comparecimento_t2 - s.qt_comparecimento_t1) / ap}
    linhas = []

    def wcorr(a, b, w):
        ma, mb = np.average(a, weights=w), np.average(b, weights=w)
        cov = np.average((a - ma) * (b - mb), weights=w)
        return cov / np.sqrt(np.average((a - ma) ** 2, weights=w) * np.average((b - mb) ** 2, weights=w))

    for col, rot in colunas_t1.items():
        x = s[col].astype(float) / ap
        for yn, yv in y.items():
            ok = x.notna() & yv.notna()
            linhas.append({"base_t1": rot, "variacao": yn, "correlacao_ponderada": float(wcorr(x[ok], yv[ok], ap[ok])),
                           "municipios": int(ok.sum())})
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------- entorno
ENTORNO = {
    "renda_resp": ("renda_media_responsavel", "log", LN2, "por duplicação da renda média dos responsáveis no entorno"),
    "urbana_entorno": ("pct_pop_urbana", "nivel", 10.0, "por +10 p.p. de população urbana no entorno"),
    "densidade": ("densidade_hab_km2", "log", LN2, "por duplicação da densidade do entorno"),
    "favela": ("pct_pop_favela", "nivel", 10.0, "por +10 p.p. de população em favelas e comunidades urbanas"),
}


def entorno_unidades(raiz: Path, terr: pd.DataFrame, membership: pd.DataFrame,
                     sufixo: str = "") -> tuple[pd.DataFrame, dict]:
    """Entorno do local apurador do 1º turno de cada unidade (D37-X1); MISTA se houver mais de um local."""
    pasta = raiz / "data" / "staging" / "entorno_local"
    sec, loc = [], []
    for uf in sorted(terr.sg_uf.unique()):
        ps, pl = pasta / f"secoes_{uf}.parquet", pasta / f"locais_{uf}.parquet"
        if ps.exists() and pl.exists():
            sec.append(pd.read_parquet(ps, columns=["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao",
                                                    "id_local_apurador", "flag_mudou_local"]))
            loc.append(pd.read_parquet(pl))
    if not sec:
        return pd.DataFrame(), {"status": "SEM_ENTORNO"}
    sec, loc = pd.concat(sec, ignore_index=True), pd.concat(loc, ignore_index=True)
    s1 = sec[sec.nr_turno == 1]
    mb = membership[membership.nr_turno == 1]
    k = ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
    j = mb.merge(s1, on=["nr_turno"] + k, how="left", validate="one_to_one")
    if len(j) != len(mb):
        raise ValueError("vínculo seção–local multiplicou linhas")
    mud = sec.groupby(k).flag_mudou_local.any()
    j = j.join(mud.rename("mudou_local"), on=k)
    g = j.groupby("id_unidade")
    u = pd.DataFrame({"n_locais": g.id_local_apurador.nunique(), "id_local": g.id_local_apurador.first(),
                      "mudou_local": g.mudou_local.any(), "sem_local": g.id_local_apurador.apply(lambda s: s.isna().all())})
    u.loc[u.n_locais > 1, "id_local"] = None
    l1 = loc[loc.nr_turno == 1].set_index("id_local")
    cols = ["flag_entorno_valido", "flag_renda_valida", "cobertura_area", "cobertura_renda",
            "flag_coord_fora_municipio", "flag_coord_limite_municipio"] + [c for c in l1.columns if any(
                c.startswith(p) for p in ("renda_media_responsavel", "pct_pop_urbana", "densidade_hab_km2",
                                          "pct_pop_favela", "cobertura_area_", "cobertura_renda_"))]
    u = u.join(l1[sorted(set(cols))], on="id_local")
    u["status_entorno"] = np.select(
        [u.sem_local, u.n_locais > 1, u.flag_entorno_valido.fillna(False).astype(bool)],
        ["SEM_LOCAL", "MISTA", "VALIDO"], "INVALIDO")
    u = u.loc[u.index.isin(terr.id_unidade)]
    diag = {"unidades_territorio": int(len(terr)), "com_registro": int(len(u)),
            "status": u.status_entorno.value_counts().to_dict(),
            "renda_valida": int((u.status_entorno.eq("VALIDO") & u.flag_renda_valida.fillna(False).astype(bool)).sum()),
            "locais_validos": int(u.loc[u.status_entorno == "VALIDO", "id_local"].nunique()),
            "mudou_local": int(u.mudou_local.fillna(False).sum())}
    return u, diag


def elegivel_raio(d: pd.DataFrame, var: str, raio: int | None = None, area_min: float = 0.90,
                  renda_min: float = 0.75) -> pd.Series:
    """Unidade elegível para o indicador `var` no raio pedido (R38-1). `raio=None` é o principal, cujas flags o
    produtor já calculou; num raio de sensibilidade, a cobertura de área (e, para a renda, a de renda) é a do
    próprio raio, não a de 1 km. Em ambos, exige local único com coordenada utilizável e valor transformável."""
    col, transf, _, _ = ENTORNO[var]
    if raio is None:
        ok = d.status_entorno.eq("VALIDO")
        if var == "renda_resp":
            ok &= d.flag_renda_valida.fillna(False).astype(bool)
        x = d[col]
    else:
        ok = d.status_entorno.isin(["VALIDO", "INVALIDO"]) & d.id_local.notna()
        ok &= d[f"cobertura_area_{raio}"].ge(area_min)
        if var == "renda_resp":
            ok &= d[f"cobertura_renda_{raio}"].ge(renda_min)
        x = d[f"{col}_{raio}"]
    x = x.astype(float)
    return ok & (x.gt(0) if transf == "log" else x.notna())


def modelos_entorno(d: pd.DataFrame, controles: list[str], renda_min: float = 0.75) -> pd.DataFrame:
    """Modelos do entorno da versão final (handoff 40): só o raio principal de 1 km, com as verificações de
    qualidade nesse raio (erros por município, sem mudança de local, coberturas, peso da renda, coordenadas
    fora do município). A amostra principal é a de `elegivel_raio(..., None)`, sem depender de outros raios."""
    valido = d[d.status_entorno == "VALIDO"]
    renda_ok = valido[valido.flag_renda_valida.fillna(False).astype(bool)]
    linhas = []
    for var in ENTORNO:
        base = renda_ok if var == "renda_resp" else valido
        for y in DESFECHOS:
            linhas.append(modelo_entorno(base, var, y, controles))
            linhas.append(modelo_entorno(base, var, y, controles, cluster="municipio"))
            linhas.append(modelo_entorno(base[~base.mudou_local.fillna(False).astype(bool)], var, y, controles,
                                         filtro="sem_mudanca_local"))
            for lim, nm in ((0.75, "cobertura_area_075"), (0.95, "cobertura_area_095")):
                sel = d[(d.status_entorno.isin(["VALIDO", "INVALIDO"])) & (d.cobertura_area >= lim)
                        & d.id_local.notna()]
                if var == "renda_resp":
                    sel = sel[sel.cobertura_renda >= renda_min]
                linhas.append(modelo_entorno(sel, var, y, controles, filtro=nm))
            if var == "renda_resp":
                linhas.append(modelo_entorno(base, var, y, controles, coluna="renda_media_responsavel_peso_domicilios",
                                             filtro="peso_domicilios"))
                for lim in (0.50, 0.90):
                    sel = valido[valido.cobertura_renda >= lim]
                    linhas.append(modelo_entorno(sel, var, y, controles, filtro=f"cobertura_renda_{lim:.2f}"))
                sel = valido[~valido.flag_coord_fora_municipio.fillna(False).astype(bool)]
                sel = sel[sel.flag_renda_valida.fillna(False).astype(bool)]
                linhas.append(modelo_entorno(sel, var, y, controles, filtro="sem_coord_fora_municipio"))
    return pd.DataFrame(linhas)


def modelo_entorno(d: pd.DataFrame, var: str, desfecho: str, controles: list[str], cluster: str = "id_local",
                   coluna: str | None = None, filtro: str = "principal") -> dict:
    """Unidades no mesmo município (EF município), peso aptos T1, erro agrupado pelo local."""
    col, transf, inc, rot = ENTORNO[var]
    col = coluna or col
    x = d[col].astype(float)
    if transf == "log":
        x = np.log(x.where(x > 0))
    s = d.assign(_x=x).dropna(subset=["_x", desfecho, cluster] + controles)
    s = s[np.isfinite(s._x)]
    w = s.peso.to_numpy(float)
    fe = s.municipio.to_numpy()
    X = s[["_x"] + controles].to_numpy(float)
    Xd = assoc.demean(X, w, fe)
    if np.abs(Xd[:, 0]).max() < 1e-12:
        return {"indicador": var, "desfecho": desfecho, "status": "SEM_VARIACAO_NO_MUNICIPIO"}
    f = assoc.clustered_fit(Xd, assoc.demean(s[desfecho].to_numpy(float), w, fe), w,
                            s[cluster].astype(str).to_numpy(), absorbed=len(np.unique(fe)))
    fator = 100.0 * inc
    return {"indicador": var, "coluna": col, "desfecho": desfecho, "filtro": filtro, "cluster": cluster,
            "status": "PASS", "efeito_pp": float(f["beta"][0]) * fator, "inf_pp": float(f["inf"][0]) * fator,
            "sup_pp": float(f["sup"][0]) * fator, "escala": rot, "n_unidades": int(f["n"]),
            "n_locais": int(s.id_local.nunique()), "n_municipios": int(len(np.unique(fe))),
            "grupos": int(f["grupos"])}
