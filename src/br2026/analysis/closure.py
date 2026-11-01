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
RAW_FORMATS = ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
               "%Y%m%dT%H%M%S")   # último: BU do portal Resultados (handoff 29)


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
    if closure.empty:
        return pd.DataFrame()
    d = closure.copy()
    d["elegivel"] = d.semantica.isin(cc["semanticas_elegiveis"])
    d["ts"] = pd.Series(pd.NaT, index=d.index, dtype="datetime64[ns, America/Sao_Paulo]")
    d["motivo"] = None
    e_idx = d.index[d.elegivel]
    # Só os registros elegíveis precisam de horário normalizado.
    norm = [normalize_timestamp(r, z) if pd.isna(b) else (b, None)
            for r, z, b in zip(d.loc[e_idx, "ts_bruto"], d.loc[e_idx, "fuso_documentado"],
                               d.loc[e_idx, "ts_brasilia"])]
    d.loc[e_idx, "ts"] = pd.Series([n[0] for n in norm], index=e_idx,
                                   dtype="datetime64[ns, America/Sao_Paulo]")
    d.loc[e_idx, "motivo"] = [n[1] for n in norm]

    # Agregação vetorizada por seção (antes: laço Python por seção, inviável em escala).
    for f in ("flag_reemissao", "flag_substituicao_urna"):
        d[f] = d[f].fillna(False).astype(bool)
    allg = d.groupby(key, sort=True)
    out = pd.DataFrame({"_reem_all": allg.flag_reemissao.any(), "_subs_all": allg.flag_substituicao_urna.any()})
    e = d[d.elegivel]
    eg = e.groupby(key, sort=True)
    stats = pd.DataFrame({
        "n_registros": eg.size(), "_n_valid": eg.ts.count(), "_n_distinct": eg.ts.nunique(),
        "_ts_first": eg.ts.first(), "_motivo_first": eg.motivo.first(),
        "_reem": eg.flag_reemissao.any(), "_subs": eg.flag_substituicao_urna.any(),
    })
    out = out.join(stats, how="left")
    has_e = out.n_registros.notna()
    out["n_registros"] = out.n_registros.fillna(0).astype(int)
    out["_n_valid"] = out._n_valid.fillna(0).astype(int)
    out["_n_distinct"] = out._n_distinct.fillna(0).astype(int)
    inv = cc["classe_invalida"]
    out["faixa"] = None
    out["motivo_invalido"] = None
    out["ts_brasilia"] = out._ts_first
    # Só recebimento/totalização/emissão: não substituem encerramento.
    m0 = ~has_e
    out.loc[m0, ["faixa", "motivo_invalido"]] = [inv, "SEM_SEMANTICA_ELEGIVEL"]
    m1 = has_e & (out._n_valid == 0)
    out.loc[m1, "faixa"] = inv
    out.loc[m1, "motivo_invalido"] = out.loc[m1, "_motivo_first"].fillna("SEM_REGISTRO")
    m2 = has_e & (out._n_distinct > 1)
    out.loc[m2, ["faixa", "motivo_invalido"]] = [inv, "CONFLITO_REEMISSAO"]
    out.loc[m0 | m1 | m2, "ts_brasilia"] = pd.NaT
    ok_rows = has_e & ~m1 & ~m2
    out["flag_reemissao"] = np.where(m0, out._reem_all,
                                     np.where(m2, True, out._reem.fillna(False).astype(bool)
                                              | (ok_rows & (out.n_registros > 1))))
    out["flag_substituicao_urna"] = np.where(m0, out._subs_all, out._subs.fillna(False).astype(bool))
    out["flag_reemissao"] = out.flag_reemissao.astype(bool)
    out["flag_substituicao_urna"] = out.flag_substituicao_urna.astype(bool)
    out = out.drop(columns=[c for c in out.columns if c.startswith("_")]).reset_index()
    out = out[key + ["faixa", "ts_brasilia", "motivo_invalido", "n_registros", "flag_reemissao",
                     "flag_substituicao_urna"]]
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
