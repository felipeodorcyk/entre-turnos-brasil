"""Conferência independente do vínculo origem→apuradora (QB-A2-01, handoff 17).

A correspondência EFETIVADA do staging vem do BU web (`DS_SECOES_AGREGADAS`).
A CEFT (correspondências efetivadas) não traz seção apuradora, mas traz a urna
efetivada de cada seção: seções que compartilham a mesma urna efetivada foram
apuradas juntas. Logo, dentro de um grupo (UF, município, zona, urna efetivada),
todas as seções precisam ter a mesma `nr_secao_apuradora` no staging, e seções
de urnas diferentes não podem compartilhar apuradora. A CESP, como só descreve
expectativa, nunca entra aqui.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

GEO = ["sg_uf", "cd_municipio_tse", "nr_zona"]


def read_ceft(zip_path: Path) -> pd.DataFrame:
    """Lê o CSV oficial da CEFT (Latin-1, `;`) com identificadores preenchidos."""
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        raw = z.read(name)
    df = pd.read_csv(io.BytesIO(raw), sep=";", encoding="latin-1", dtype=str,
                     usecols=["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_URNA_EFETIVADA"])
    return pd.DataFrame({
        "sg_uf": df.SG_UF.str.strip(), "cd_municipio_tse": df.CD_MUNICIPIO.str.zfill(5),
        "nr_zona": df.NR_ZONA.str.zfill(4), "nr_secao": df.NR_SECAO.str.zfill(4),
        "nr_urna_efetivada": df.NR_URNA_EFETIVADA.str.strip(),
    })


def check_effective_against_ceft(crosswalk: pd.DataFrame, ceft: pd.DataFrame, turno: int = 1) -> dict:
    cw = crosswalk[(crosswalk.nr_turno == turno) & (crosswalk.status_correspondencia == "EFETIVADA")]
    cw = cw[GEO + ["nr_secao", "nr_secao_apuradora"]]
    m = ceft.merge(cw, on=GEO + ["nr_secao"], how="outer", indicator=True)
    only_ceft = int((m._merge == "left_only").sum())
    only_cw = int((m._merge == "right_only").sum())
    both = m[m._merge == "both"].copy()
    valid_urna = both.nr_urna_efetivada.notna() & ~both.nr_urna_efetivada.isin(["-1", "-3", "#NULO", ""])
    g = both[valid_urna].groupby(GEO + ["nr_urna_efetivada"])
    apur_per_urna = g.nr_secao_apuradora.nunique(dropna=False)
    # Urna com mais de uma apuradora: o BU separou o que a CEFT diz ter sido apurado junto.
    split = apur_per_urna[apur_per_urna > 1]
    urna_per_apur = both[valid_urna].groupby(GEO + ["nr_secao_apuradora"]).nr_urna_efetivada.nunique()
    merged = urna_per_apur[urna_per_apur > 1]
    grupos_multi = g.size()[g.size() > 1]
    # A CEFT lista uma linha por urna efetivada: as seções ausentes nela devem ser
    # exatamente as agregadas em outra, e o conjunto de seções com urna deve ser o
    # conjunto de apuradoras do crosswalk.
    full = crosswalk[(crosswalk.nr_turno == turno) & (crosswalk.status_correspondencia == "EFETIVADA")]
    key = GEO + ["nr_secao"]
    ceft_keys = set(map(tuple, ceft[key].to_numpy()))
    agregadas = set(map(tuple, full.loc[full.tipo_correspondencia == "AGREGADA_EM_OUTRA", key].to_numpy()))
    ausentes = set(map(tuple, m.loc[m._merge == "right_only", key].to_numpy()))
    apur = set(map(tuple, full.dropna(subset=["nr_secao_apuradora"])[GEO + ["nr_secao_apuradora"]].to_numpy()))
    return {
        "ausentes_na_ceft_sao_exatamente_agregadas": ausentes == agregadas,
        "apuradoras_do_crosswalk_igual_secoes_com_urna": apur == ceft_keys,
        "apuradoras_sem_urna_na_ceft": len(apur - ceft_keys),
        "secoes_com_urna_que_nao_sao_apuradoras": len(ceft_keys - apur),
        "turno": turno, "secoes_ceft": len(ceft), "secoes_crosswalk_efetivada": len(cw),
        "so_na_ceft": only_ceft, "so_no_crosswalk": only_cw,
        "secoes_sem_urna_efetivada_valida": int((~valid_urna).sum()),
        "urnas_com_mais_de_uma_secao": int(len(grupos_multi)),
        "secoes_em_urnas_compartilhadas": int(grupos_multi.sum()),
        "urnas_divididas_entre_apuradoras": int(len(split)),
        "apuradoras_com_mais_de_uma_urna": int(len(merged)),
        "exemplos_divergentes": [dict(zip(GEO + ["nr_urna_efetivada"], k)) for k in list(split.index[:5])]
        + [dict(zip(GEO + ["nr_secao_apuradora"], k)) for k in list(merged.index[:5])],
    }
