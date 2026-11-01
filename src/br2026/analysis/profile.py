"""Perfil cadastral por unidade do painel (O4).

O perfil descreve os APTOS cadastrados na seção de ORIGEM, na data de geração
do arquivo. Cada dimensão é uma marginal separada: as proporções de uma
dimensão usam o total daquela dimensão e nunca se somam a outra. A seção de
origem é ligada à unidade pela correspondência EFETIVADA do T1; sem linha de
correspondência, a própria seção é a apuradora. Votos não entram aqui.
"""
from __future__ import annotations

import pandas as pd

GEO = ["sg_uf", "cd_municipio_tse", "nr_zona"]


def origin_to_unit(crosswalk: pd.DataFrame, membership: pd.DataFrame, turno: int = 1) -> pd.DataFrame:
    cw = crosswalk[(crosswalk.nr_turno == turno) & (crosswalk.status_correspondencia == "EFETIVADA")]
    cw = cw[GEO + ["nr_secao", "nr_secao_apuradora"]].dropna(subset=["nr_secao_apuradora"])
    mem = membership[membership.nr_turno == turno]
    via = cw.merge(mem.rename(columns={"nr_secao": "nr_secao_apuradora"}),
                   on=GEO + ["nr_secao_apuradora"], how="inner")[GEO + ["nr_secao", "id_unidade"]]
    own = mem[GEO + ["nr_secao", "id_unidade"]]
    own = own.merge(via[GEO + ["nr_secao"]], on=GEO + ["nr_secao"], how="left", indicator=True)
    own = own[own._merge == "left_only"].drop(columns="_merge")
    out = pd.concat([via, own], ignore_index=True)
    if out.duplicated(GEO + ["nr_secao"]).any():
        raise ValueError("Seção de origem ligada a mais de uma unidade")
    return out


# Motivos de exclusão, na ordem de precedência (O-R1).
MOTIVOS = ("SEM_PERFIL", "PERFIL_PARCIAL_ORIGENS", "DIMENSAO_AUSENTE", "MARGINAIS_INCOERENTES",
           "TOTAL_ZERO")


def unit_profile(profiles: pd.DataFrame, crosswalk: pd.DataFrame, membership: pd.DataFrame,
                 cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retorna (proporções das unidades elegíveis, diagnóstico de TODAS as unidades).

    Elegível só a unidade em que toda seção de origem tem todas as dimensões
    exigidas, com o mesmo total positivo em cada dimensão. Ausência nunca vira
    zero: zero só aparece para categoria de uma dimensão observada (zero
    observado ou categoria sem linha naquela dimensão presente).
    """
    pc = cfg["profile"]
    dims = list(pc["grupos"])
    pr = profiles[(profiles.ano_referencia == pc["ano_referencia"]) & profiles.dimensao.isin(dims)].copy()
    lookup = {(d, code): g for d, groups in pc["grupos"].items() for g, codes in groups.items()
              for code in codes}
    pr["grupo"] = [lookup.get((d, c), "desconhecido") for d, c in zip(pr.dimensao, pr.cd_categoria)]
    o2u = origin_to_unit(crosswalk, membership)
    m = pr.merge(o2u, on=GEO + ["nr_secao"], how="left")
    sem_unidade = m.id_unidade.isna()
    m = m[~sem_unidade]

    # Diagnóstico por seção de origem, depois por unidade.
    sec = GEO + ["nr_secao"]
    tot_sec = m.groupby(sec + ["dimensao"]).qt_eleitores.sum().unstack("dimensao").reindex(columns=dims)
    origins = o2u.set_index(sec)
    origins = origins.join(tot_sec, how="left")
    origins["tem_perfil"] = origins[dims].notna().any(axis=1)
    missing = origins[dims].isna()
    origins["faltantes"] = [ "|".join(d for d, miss in zip(dims, row) if miss) if t else ""
                             for row, t in zip(missing.to_numpy(), origins.tem_perfil.to_numpy())]
    origins["incoerente"] = origins[dims].nunique(axis=1, dropna=True) > 1
    g = origins.groupby("id_unidade")
    diag = pd.DataFrame({
        "n_origens": g.size(),
        "n_origens_com_perfil": g.tem_perfil.sum().astype(int),
        "dimensoes_faltantes": g.faltantes.agg(lambda x: "|".join(sorted({p for v in x for p in v.split("|") if p}))),
        "marginais_incoerentes": g.incoerente.any(),
        "total_cadastro": origins.groupby("id_unidade")[dims[0]].sum(min_count=1),
    })
    cond = {
        "SEM_PERFIL": diag.n_origens_com_perfil == 0,
        "PERFIL_PARCIAL_ORIGENS": diag.n_origens_com_perfil < diag.n_origens,
        "DIMENSAO_AUSENTE": diag.dimensoes_faltantes != "",
        "MARGINAIS_INCOERENTES": diag.marginais_incoerentes,
        "TOTAL_ZERO": diag.total_cadastro.fillna(0) <= 0,
    }
    diag["motivo_exclusao"] = None
    for motivo in reversed(MOTIVOS):  # o primeiro da precedência prevalece
        diag.loc[cond[motivo], "motivo_exclusao"] = motivo
    diag["elegivel"] = diag.motivo_exclusao.isna()
    diag.attrs["linhas_sem_unidade"] = int(sem_unidade.sum())

    ok = diag.index[diag.elegivel]
    mm = m[m.id_unidade.isin(ok)]
    cnt = mm.groupby(["id_unidade", "dimensao", "grupo"]).qt_eleitores.sum()
    shares = (cnt / cnt.groupby(level=["id_unidade", "dimensao"]).transform("sum")).unstack(["dimensao", "grupo"])
    if shares.empty:
        return pd.DataFrame(index=pd.Index([], name="id_unidade")), diag.reset_index()
    shares.columns = [f"perfil_{d.lower()}_{grp}" for d, grp in shares.columns]
    # Toda dimensão está presente nas elegíveis: NaN aqui é categoria sem linha
    # numa dimensão observada, isto é, zero observado.
    shares = shares.fillna(0.0)
    return shares, diag.reset_index()


def profile_design(shares: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Remove uma categoria de referência por dimensão (as demais, incluindo
    'desconhecido', permanecem)."""
    drop = [f"perfil_{d.lower()}_{ref}" for d, ref in cfg["profile"]["referencias"].items()]
    return shares.drop(columns=[c for c in drop if c in shares.columns])
