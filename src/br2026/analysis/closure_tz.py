"""Inferência rotulada do fuso dos horários do BU web (decisão Q1, v1.1).

Os campos de abertura, encerramento e emissão do BU não têm fuso documentado.
Sob a premissa (a confirmar) de votação das 8h às 17h de Brasília em todo o país,
o deslocamento do relógio bruto é inferido por município e turno a partir da
ABERTURA das urnas, nunca da UF e nunca do próprio encerramento:

  * a mediana da abertura + k precisa cair em `janela_mediana` (Brasília);
  * ao menos `fracao_min_janela_ampla` das aberturas + k em `janela_ampla`;
  * exatamente um k entre os candidatos satisfaz as duas condições.

Sem solução única, o município fica DESCONHECIDO e seus horários não são
convertidos. Fuso documentado na linha sempre prevalece (DOCUMENTADO).
"""
from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from br2026.analysis.closure import BRT, RAW_FORMATS

MUN = ["nr_turno", "sg_uf", "cd_municipio_tse"]


def _parse_naive(raw) -> pd.Timestamp:
    for fmt in RAW_FORMATS:
        t = pd.to_datetime(raw, format=fmt, errors="coerce")
        if pd.notna(t):
            return t
    return pd.NaT


def parse_naive_series(raw: pd.Series) -> pd.Series:
    """Versão vetorizada de `_parse_naive`: primeiro formato que interpreta cada valor."""
    txt = raw.astype(object).where(raw.notna()).map(lambda v: v.strip() if isinstance(v, str) else None)
    out = pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns]")
    for fmt in RAW_FORMATS:
        todo = out.isna() & txt.notna()
        if not todo.any():
            break
        out[todo] = pd.to_datetime(txt[todo], format=fmt, errors="coerce").astype("datetime64[ns]")
    return out


def _sec(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def infer_municipal_offsets(closure: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    c = cfg["closure_tz"]
    lo_m, hi_m = (_sec(time.fromisoformat(x)) for x in c["janela_mediana"])
    lo_a, hi_a = (_sec(time.fromisoformat(x)) for x in c["janela_ampla"])
    ab = closure[(closure.semantica == "ABERTURA_URNA") & closure.fuso_documentado.isna()].copy()
    cols = MUN + ["n_aberturas", "mediana_abertura_bruta", "offset_h", "fracao_janela_ampla",
                  "status_fuso", "motivo"]
    ab["t"] = parse_naive_series(ab.ts_bruto)
    ab = ab[ab.t.notna()]
    if ab.empty:
        return pd.DataFrame(columns=cols)
    ab["s"] = ab.t.dt.hour * 3600 + ab.t.dt.minute * 60 + ab.t.dt.second
    rows = []
    for k, g in ab.groupby(MUN, sort=True):
        s = g.s.to_numpy(float)
        med = float(np.median(s))
        ok = []
        for h in c["candidatos_h"]:
            shifted = s + 3600 * h
            m = med + 3600 * h
            frac = float(((shifted >= lo_a) & (shifted < hi_a)).mean())
            if lo_m <= m < hi_m and frac >= c["fracao_min_janela_ampla"]:
                ok.append((h, frac))
        base = dict(zip(MUN, k), n_aberturas=len(s),
                    mediana_abertura_bruta=f"{int(med // 3600):02d}:{int(med % 3600 // 60):02d}")
        if len(ok) == 1:
            rows.append({**base, "offset_h": ok[0][0], "fracao_janela_ampla": ok[0][1],
                         "status_fuso": "INFERIDO_ABERTURA_MUNICIPAL", "motivo": None})
        else:
            rows.append({**base, "offset_h": np.nan, "fracao_janela_ampla": np.nan,
                         "status_fuso": "DESCONHECIDO",
                         "motivo": "SEM_SOLUCAO" if not ok else "SOLUCAO_MULTIPLA"})
    return pd.DataFrame(rows, columns=cols)


def apply_offsets(closure: pd.DataFrame, offsets: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Preenche ts_brasilia e status_fuso; o bruto não é alterado (vetorizado)."""
    conv = set(cfg["closure_tz"]["semanticas_convertidas"])
    d = closure.merge(offsets[MUN + ["offset_h", "status_fuso"]], on=MUN, how="left")
    naive = parse_naive_series(d.ts_bruto)
    ts = pd.Series(pd.NaT, index=d.index, dtype="datetime64[ns, America/Sao_Paulo]")
    tz = d.fuso_documentado.astype(object)
    documented = tz.map(lambda v: isinstance(v, str) and bool(v.strip()))
    for name in tz[documented].unique():
        m = documented & (tz == name)
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            continue  # fuso inválido: continua sem horário convertido
        ts[m] = naive[m].dt.tz_localize(name, ambiguous="NaT", nonexistent="NaT").dt.tz_convert(BRT)
    inferred = ~documented & d.semantica.isin(conv) & d.status_fuso.eq("INFERIDO_ABERTURA_MUNICIPAL")
    ts[inferred] = (naive[inferred] + pd.to_timedelta(d.offset_h[inferred].astype(float), unit="h")
                    ).dt.tz_localize(BRT)
    d["ts_brasilia"] = ts
    d["status_fuso"] = np.where(documented, "DOCUMENTADO",
                                np.where(inferred, "INFERIDO_ABERTURA_MUNICIPAL", "DESCONHECIDO"))
    return d


KEY = ["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
VARIANTS = {
    # Só encerramento com fuso documentado. Resultado temporal principal.
    "documental": {"DOCUMENTADO"},
    # Cenários exploratórios: inferência pela abertura, não validada (O-R3).
    "exploratorio_inferido": {"DOCUMENTADO", "INFERIDO_ABERTURA_MUNICIPAL"},
    "exploratorio_inferido_offset_zero": {"DOCUMENTADO", "INFERIDO_OFFSET_ZERO"},
}


def select_closure_variant(conv: pd.DataFrame, variant: str) -> pd.DataFrame:
    """Elegibilidade decidida pelo evento ENCERRAMENTO_URNA (O-R2).

    Uma seção entra na variante só se TODOS os seus registros de encerramento
    têm status admitido. Eventos auxiliares (abertura, emissão, recebimento)
    nunca tornam a seção elegível. Seção não elegível mantém os registros, mas o
    encerramento perde o horário convertido e o fuso, e `classify` a marca
    INVALIDO / FUSO_NAO_DOCUMENTADO. Reemissões e conflitos seguem a regra de
    `classify` sobre os encerramentos admitidos.
    """
    allowed = VARIANTS[variant]
    d = conv.copy()
    status = np.where((d.status_fuso == "INFERIDO_ABERTURA_MUNICIPAL") & d.offset_h.eq(0),
                      "INFERIDO_OFFSET_ZERO", d.status_fuso)
    # offset zero continua sendo inferência; só é admitido na variante específica.
    if variant == "exploratorio_inferido":
        status = np.where(status == "INFERIDO_OFFSET_ZERO", "INFERIDO_ABERTURA_MUNICIPAL", status)
    d["_status_var"] = status
    enc = d.semantica == "ENCERRAMENTO_URNA"
    ok_sec = d[enc].assign(ok=lambda x: x._status_var.isin(allowed)).groupby(KEY).ok.all()
    d = d.join(ok_sec.rename("_sec_ok"), on=KEY)
    drop = enc & ~d._sec_ok.fillna(False).astype(bool)
    d.loc[drop, "ts_brasilia"] = pd.NaT
    d.loc[drop, "fuso_documentado"] = None
    d.loc[drop, "status_fuso"] = "NAO_ADMITIDO_NA_VARIANTE"
    return d.drop(columns=["_status_var", "_sec_ok"])
