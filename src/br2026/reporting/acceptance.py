"""Conferência contra referência oficial independente (aceite dos marcos M1/M4).

O esperado vem da referência, nunca do staging. A conferência falha quando a
referência está vazia, incompleta para alguma UF × turno × métrica do staging,
duplicada, com valor inválido, com data de corte anterior à eleição, ou quando
aponta para um insumo que é o próprio arquivo por seção sob teste.
"""
from __future__ import annotations

import re

import pandas as pd

REQUIRED_METRICS = ("qt_aptos", "qt_comparecimento", "qt_abstencoes", "qt_votos_brancos",
                    "qt_votos_nulos", "qt_lula", "qt_flavio")
REF_COLUMNS = ("nr_turno", "sg_uf", "metrica", "valor", "fonte_tipo", "url", "sha256_fonte",
               "data_corte")
# RESULTADO_DIVULGADO_TSE: resultado oficial por UF (fonte preferida).
# TOTALIZACAO_MUNZONA: produto agregado distinto do arquivo por seção; detecta
# erros de leitura/normalização, mas não é independente da totalização do TSE.
SOURCE_TYPES = ("RESULTADO_DIVULGADO_TSE", "TOTALIZACAO_MUNZONA")
# Famílias de arquivo por seção que não podem servir de referência para si mesmas.
SECTION_LEVEL = re.compile(r"(?:votacao_secao|detalhe_votacao_secao|bweb_|buweb|perfil_eleitor_secao)",
                           re.IGNORECASE)


def observed_totals(section_turn: pd.DataFrame, votes_long: pd.DataFrame,
                    nr_lula: int, nr_flavio: int, cd_cargo: int = 1) -> dict:
    st = section_turn[section_turn.cd_cargo == cd_cargo]
    vl = votes_long[votes_long.cd_cargo == cd_cargo]
    obs = {}
    for (t, uf), g in st.groupby(["nr_turno", "sg_uf"]):
        for c in REQUIRED_METRICS[:5]:
            obs[(int(t), uf, c)] = int(g[c].sum()) if g[c].notna().all() else None
    for t, uf in sorted({(k[0], k[1]) for k in obs}):
        for name, nr in (("qt_lula", nr_lula), ("qt_flavio", nr_flavio)):
            m = (vl.nr_turno == t) & (vl.sg_uf == uf) & (vl.nr_votavel == nr)
            obs[(t, uf, name)] = int(vl.loc[m, "qt_votos"].sum())
    return obs


def expected_keys(observed: dict, turnos=None) -> set:
    """Toda UF × turno do staging, com todas as métricas obrigatórias."""
    pairs = {(t, uf) for t, uf, _ in observed if turnos is None or t in turnos}
    return {(t, uf, m) for t, uf in pairs for m in REQUIRED_METRICS}


def check_reference(ref: pd.DataFrame, observed: dict, keys: set, election_dates: dict,
                    staging_hashes: set, section_urls: set) -> list[str]:
    """Lista de problemas; vazia significa aprovação."""
    p: list[str] = []
    if ref is None or ref.empty:
        return ["referência vazia"]
    miss_cols = [c for c in REF_COLUMNS if c not in ref.columns]
    if miss_cols:
        return [f"colunas ausentes na referência: {miss_cols}"]
    r = ref.copy()
    nulls = r[list(REF_COLUMNS)].isna().any(axis=1)
    if nulls.any():
        p.append(f"{int(nulls.sum())} linha(s) com campo obrigatório vazio")
    r["nr_turno"] = pd.to_numeric(r.nr_turno, errors="coerce")
    bad_turn = ~r.nr_turno.isin([1, 2])
    if bad_turn.any():
        p.append(f"{int(bad_turn.sum())} linha(s) com turno inválido")
    bad_metric = ~r.metrica.isin(REQUIRED_METRICS)
    if bad_metric.any():
        p.append(f"métricas desconhecidas: {sorted(set(r.metrica[bad_metric].astype(str)))}")
    num = pd.to_numeric(r.valor, errors="coerce")
    bad_val = num.isna() | (num < 0) | (num != num.round())
    if bad_val.any():
        p.append(f"{int(bad_val.sum())} valor(es) não inteiros não negativos: "
                 f"{r.valor[bad_val].astype(str).tolist()[:5]}")
    bad_src = ~r.fonte_tipo.isin(SOURCE_TYPES)
    if bad_src.any():
        p.append(f"fonte_tipo fora de {SOURCE_TYPES}: {sorted(set(r.fonte_tipo[bad_src].astype(str)))}")
    sha = r.sha256_fonte.astype(str)
    if (~sha.str.fullmatch(r"[0-9a-f]{64}")).any():
        p.append("sha256_fonte inválido")
    same = sha.isin(staging_hashes)
    if same.any():
        p.append(f"{int(same.sum())} linha(s) com fonte igual a insumo do staging (não independente)")
    url = r.url.astype(str)
    if (~url.str.match(r"^https?://")).any():
        p.append("url sem esquema http(s)")
    dep = url.isin(section_urls) | url.str.contains(SECTION_LEVEL)
    if dep.any():
        p.append(f"{int(dep.sum())} linha(s) apontam para arquivo por seção (não independente)")
    corte = pd.to_datetime(r.data_corte, errors="coerce")
    if corte.isna().any():
        p.append("data_corte inválida")
    else:
        eleicao = r.nr_turno.map(lambda t: pd.Timestamp(election_dates.get(int(t), "2100-01-01"))
                                 if pd.notna(t) else pd.NaT)
        early = corte < eleicao
        if early.any():
            p.append(f"{int(early.sum())} linha(s) com data de corte anterior à eleição do turno")
    r["_key"] = list(zip(r.nr_turno.fillna(-1).astype(int), r.sg_uf.astype(str), r.metrica.astype(str)))
    dup = r._key.duplicated(keep=False)
    if dup.any():
        p.append(f"chaves duplicadas: {sorted(set(r._key[dup]))[:5]}")
    present = set(r._key)
    missing = sorted(keys - present)
    if missing:
        p.append(f"{len(missing)} chave(s) esperada(s) ausente(s), ex. {missing[:5]}")
    dup_keys = set(r._key[dup])
    for k, v in zip(r._key, num):
        if k in keys and pd.notna(v) and k not in dup_keys:
            o = observed.get(k)
            if o is None:
                p.append(f"{k}: staging sem total (termo ausente)")
            elif o != int(v):
                p.append(f"{k}: staging {o} ≠ oficial {int(v)}")
    return p
