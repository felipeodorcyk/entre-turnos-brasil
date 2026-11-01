# Cópia congelada de classify (laço por seção) do commit 5288a23, usada como oráculo de equivalência.
"""Horários de encerramento (B5).

Somente registros com semântica ENCERRAMENTO_URNA entram nas faixas.
Recebimento no TSE, totalização ou emissão não substituem encerramento.
O fuso vem da documentação do campo (`fuso_documentado`), nunca da UF.
Faixas são semiabertas [início, fim) em horário de Brasília, definidas em
config/analysis.toml antes de olhar resultados. O desfecho é a seção inteira;
nada aqui informa a preferência de quem votou depois de 17h.
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from br2026.config import load_config

BRT = ZoneInfo("America/Sao_Paulo")
RAW_FORMATS = ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def _parse_hms(s: str) -> time | None:
    return None if s == "24:00:00" else time.fromisoformat(s)


def normalize_timestamp(raw, tz_name) -> tuple[pd.Timestamp | None, str | None]:
    """(ts em Brasília, motivo_ausencia). Nunca infere fuso."""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)) or str(raw).strip() in ("", "#NULO", "#NE"):
        return None, "SEM_REGISTRO"
    if not isinstance(tz_name, str) or not tz_name.strip():  # None, NaN, pd.NA, "" (achado F-01 de C)
        return None, "FUSO_NAO_DOCUMENTADO"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return None, "FUSO_NAO_DOCUMENTADO"
    for fmt in RAW_FORMATS:
        try:
            naive = datetime.strptime(str(raw).strip(), fmt)
            break
        except ValueError:
            continue
    else:
        return None, "BRUTO_INVALIDO"
    return pd.Timestamp(naive.replace(tzinfo=tz)).tz_convert(BRT), None


def classify(closure: pd.DataFrame, election_dates: dict[int, str], cfg: dict | None = None,
             tolerance_min: int | None = None) -> pd.DataFrame:
    """Uma faixa por seção × turno; classes exaustivas e mutuamente exclusivas.

    Reemissões com o mesmo encerramento colapsam; encerramentos conflitantes na
    mesma seção/turno vão para INVALIDO (motivo CONFLITO_REEMISSAO).
    `tolerance_min` substitui o fim da primeira faixa pós-limite (sensibilidade).
    """
    cfg = cfg or load_config()
    cc = cfg["closure"]
    bands = [dict(b) for b in cc["faixas"]]
    if tolerance_min is not None:
        lim = datetime.combine(datetime.today(), _parse_hms(cc["limite_oficial"]))
        cut = (lim + pd.Timedelta(minutes=tolerance_min)).time().isoformat()
        bands[1]["fim"] = cut
        bands[2]["inicio"] = cut
    key = ["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
    d = closure.copy()
    d["elegivel"] = d.semantica.isin(cc["semanticas_elegiveis"])
    norm = [normalize_timestamp(r, z) if pd.isna(b) else (b, None)
            for r, z, b in zip(d.ts_bruto, d.fuso_documentado, d.ts_brasilia)]
    d["ts"] = [n[0] for n in norm]
    d["motivo"] = [n[1] for n in norm]

    rows = []
    for k, g_all in d.groupby(key, sort=True):
        base = dict(zip(key, k))
        g = g_all[g_all.elegivel]
        if g.empty:
            # Só há recebimento/totalização/emissão: não substituem encerramento.
            rows.append({**base, "faixa": cc["classe_invalida"], "ts_brasilia": pd.NaT,
                         "motivo_invalido": "SEM_SEMANTICA_ELEGIVEL", "n_registros": 0,
                         "flag_reemissao": bool(g_all.flag_reemissao.any()),
                         "flag_substituicao_urna": bool(g_all.flag_substituicao_urna.any())})
            continue
        valid = g[g.ts.notna()]
        distinct = valid.ts.drop_duplicates()
        if len(valid) == 0:
            rows.append({**base, "faixa": cc["classe_invalida"], "ts_brasilia": pd.NaT,
                         "motivo_invalido": g.motivo.dropna().iloc[0] if g.motivo.notna().any() else "SEM_REGISTRO",
                         "n_registros": len(g), "flag_reemissao": bool(g.flag_reemissao.any()),
                         "flag_substituicao_urna": bool(g.flag_substituicao_urna.any())})
            continue
        if len(distinct) > 1:
            rows.append({**base, "faixa": cc["classe_invalida"], "ts_brasilia": pd.NaT,
                         "motivo_invalido": "CONFLITO_REEMISSAO", "n_registros": len(g),
                         "flag_reemissao": True, "flag_substituicao_urna": bool(g.flag_substituicao_urna.any())})
            continue
        ts = distinct.iloc[0]
        rows.append({**base, "ts_brasilia": ts, "faixa": None, "motivo_invalido": None,
                     "n_registros": len(g), "flag_reemissao": bool(g.flag_reemissao.any()) or len(g) > 1,
                     "flag_substituicao_urna": bool(g.flag_substituicao_urna.any())})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    ok = out.faixa.isna()
    dates = out.nr_turno.map(lambda t: pd.Timestamp(election_dates[int(t)]).date())
    same_day = out.ts_brasilia.map(lambda x: x.date() if pd.notna(x) else None) == dates
    wrong_day = ok & ~same_day
    out.loc[wrong_day, "faixa"] = cc["classe_invalida"]
    out.loc[wrong_day, "motivo_invalido"] = "DATA_DIFERENTE_DA_ELEICAO"
    ok = out.faixa.isna()
    tod = pd.Series([x.time() for x in out.loc[ok, "ts_brasilia"]], index=out.index[ok], dtype=object)
    lab = pd.Series(None, index=tod.index, dtype=object)
    for b in bands:
        lo, hi = _parse_hms(b["inicio"]), _parse_hms(b["fim"])
        m = (tod >= lo) & ((tod < hi) if hi is not None else True)
        if (m & lab.notna()).any():
            raise AssertionError("Faixas sobrepostas na configuração")
        lab[m] = b["nome"]
    if lab.isna().any():
        raise AssertionError("Faixas não exaustivas na configuração")
    out.loc[ok, "faixa"] = lab
    if "status_fuso" in d.columns:
        sf = d[d.elegivel].groupby(key).status_fuso.first().rename("status_fuso").reset_index()
        out = out.merge(sf, on=key, how="left")
    lim = _parse_hms(cc["limite_oficial"])
    lim_min = lim.hour * 60 + lim.minute + lim.second / 60
    out["minutos_apos_limite"] = out.ts_brasilia.map(
        lambda x: (x.hour * 60 + x.minute + x.second / 60) - lim_min if pd.notna(x) else np.nan)
    return out


def band_transitions(classified: pd.DataFrame) -> pd.DataFrame:
    """Tabela T1 × T2 de faixas por seção (inclui INVALIDO e ausência de turno)."""
    key = ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
    t1 = classified[classified.nr_turno == 1].set_index(key).faixa.rename("faixa_t1")
    t2 = classified[classified.nr_turno == 2].set_index(key).faixa.rename("faixa_t2")
    j = pd.concat([t1, t2], axis=1).fillna("SEM_TURNO")
    return pd.crosstab(j.faixa_t1, j.faixa_t2, dropna=False)


def support_check(classified: pd.DataFrame, bands: list[str], min_sections: int,
                  min_municipalities: int, turno: int) -> dict:
    """Regra pré-registrada de não estimação por falta de suporte."""
    c = classified[(classified.nr_turno == turno) & classified.faixa.isin(bands)]
    n = c.groupby("faixa").size().reindex(bands, fill_value=0)
    m = c.groupby("faixa").cd_municipio_tse.nunique().reindex(bands, fill_value=0)
    falta = [b for b in bands if n[b] < min_sections or m[b] < min_municipalities]
    return {"estimar": not falta, "faixas_sem_suporte": falta,
            "secoes": n.to_dict(), "municipios": m.to_dict()}


def covariate_overlap(df: pd.DataFrame, band_col: str, covariates: list[str],
                      bands: list[str]) -> pd.DataFrame:
    """Sobreposição de covariáveis entre faixas: faixa comum [max(min), min(max)]
    e fração de cada faixa fora dela."""
    rows = []
    for c in covariates:
        sub = df[df[band_col].isin(bands)]
        lo = sub.groupby(band_col)[c].min().max()
        hi = sub.groupby(band_col)[c].max().min()
        for b in bands:
            x = sub.loc[sub[band_col] == b, c]
            rows.append({"covariavel": c, "faixa": b, "suporte_comum_inf": lo, "suporte_comum_sup": hi,
                         "fracao_fora": float(((x < lo) | (x > hi)).mean()) if len(x) else np.nan})
    return pd.DataFrame(rows)
