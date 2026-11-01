"""Painel comparável entre turnos (B1).

Unidade: componente conexo do grafo que liga cada seção de origem à seção
apuradora de cada turno. Uma seção que é apuradora sempre conta a si mesma,
por isso a apuradora é ligada à origem homônima. Quando a agregação muda
entre turnos, as seções envolvidas formam uma única unidade e as contagens
são somadas — nenhum voto é redistribuído proporcionalmente.

Todas as unidades permanecem na saída; exclusões recebem motivo e entram na
reconciliação, que precisa fechar exatamente com os totais completos.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from br2026.contract import CONTRACT_VERSION

COUNTS = ["qt_aptos", "qt_comparecimento", "qt_abstencoes", "qt_votos_validos",
          "qt_votos_brancos", "qt_votos_nulos", "qt_lula", "qt_flavio"]
GEO = ["sg_uf", "cd_municipio_tse", "nr_zona"]
# Precedência dos motivos: o primeiro que se aplica define o status.
STATUS_ORDER = ["EXCLUIDA_AMBIGUA", "EXCLUIDA_CORRESPONDENCIA_NAO_EFETIVADA",
                "EXCLUIDA_AUSENTE_T1", "EXCLUIDA_AUSENTE_T2",
                "EXCLUIDA_NAO_APURADA", "EXCLUIDA_CONTABILIDADE"]


class _UnionFind:
    def __init__(self):
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def technical_null_votes(votes_long: pd.DataFrame, technical_null: dict | None,
                         cd_cargo: int = 1) -> pd.DataFrame:
    """Votos por seção × turno em votáveis com 'Nulo técnico' na totalização oficial."""
    key = ["nr_turno"] + GEO + ["nr_secao"]
    if not technical_null:
        return pd.DataFrame(columns=key + ["qt_nulo_tecnico"])
    m = pd.Series(False, index=votes_long.index)
    for t, nrs in technical_null.items():
        m |= (votes_long.nr_turno == int(str(t).lstrip("t"))) & votes_long.nr_votavel.isin(nrs)
    v = votes_long[m & (votes_long.cd_cargo == cd_cargo)]
    return v.groupby(key).qt_votos.sum().rename("qt_nulo_tecnico").reset_index()


def section_counts(section_turn: pd.DataFrame, votes_long: pd.DataFrame,
                   nr_lula: int, nr_flavio: int, cd_cargo: int = 1,
                   technical_null: dict | None = None) -> pd.DataFrame:
    """Uma linha por seção apuradora × turno, com totais e votos dos finalistas.

    Votos em candidatura com 'Nulo técnico' (ex.: renúncia) vêm somados em
    QT_VOTOS_NOMINAIS no detalhe, mas a totalização oficial os conta como nulos.
    Com `technical_null` = {"t1": [nr, ...]}, eles saem dos válidos e entram nos
    nulos; a identidade comparecimento = válidos + brancos + nulos se preserva.
    """
    st = section_turn[section_turn.cd_cargo == cd_cargo].copy()
    key = ["nr_turno"] + GEO + ["nr_secao"]
    tec = technical_null_votes(votes_long, technical_null, cd_cargo)
    st = st.merge(tec, on=key, how="left", validate="one_to_one")
    apurada_st = st.qt_votos_nominais.notna()
    st["qt_nulo_tecnico"] = st.qt_nulo_tecnico.astype("Int64").where(~apurada_st | st.qt_nulo_tecnico.notna(), 0)
    st["qt_votos_validos"] = st.qt_votos_nominais + st.qt_votos_legenda - st.qt_nulo_tecnico
    st["qt_votos_nulos"] = st.qt_votos_nulos + st.qt_nulo_tecnico
    vl = votes_long[(votes_long.cd_cargo == cd_cargo)
                    & votes_long.nr_votavel.isin([nr_lula, nr_flavio])]
    cand = (vl.assign(c=np.where(vl.nr_votavel == nr_lula, "qt_lula", "qt_flavio"))
              .pivot_table(index=key, columns="c", values="qt_votos", aggfunc="sum")
              .reindex(columns=["qt_lula", "qt_flavio"]).reset_index())
    out = st.merge(cand, on=key, how="left", validate="one_to_one")
    # Seção apurada sem linha do candidato: zero observado; seção sem apuração: ausente.
    apurada = out.qt_votos_validos.notna()
    for c in ("qt_lula", "qt_flavio"):
        out[c] = out[c].astype("Int64")
        out.loc[apurada & out[c].isna(), c] = 0
    for c in COUNTS:
        out[c] = out[c].astype("Int64")
    return out


def _components(counts: pd.DataFrame, crosswalk: pd.DataFrame):
    """Grafo só com correspondências EFETIVADAS (v1.1). Origens que no turno têm
    apenas correspondência ESPERADA (CESP) são marcadas, nunca ligadas."""
    uf = _UnionFind()
    ambiguous: set = set()
    key = ["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
    efet = crosswalk[crosswalk.status_correspondencia == "EFETIVADA"]
    esp = crosswalk[crosswalk.status_correspondencia == "ESPERADA"]
    only_esp = esp.merge(efet[key].drop_duplicates(), on=key, how="left", indicator=True)
    only_esp = only_esp[only_esp._merge == "left_only"]
    not_effective = {("O", r.sg_uf, r.cd_municipio_tse, r.nr_zona, r.nr_secao)
                     for r in only_esp.itertuples(index=False)}
    for o in not_effective:
        uf.find(o)
    for r in efet.itertuples(index=False):
        o = ("O", r.sg_uf, r.cd_municipio_tse, r.nr_zona, r.nr_secao)
        uf.find(o)
        if r.flag_ambigua or r.tipo_correspondencia == "AMBIGUA":
            ambiguous.add(o)
        if isinstance(r.nr_secao_apuradora, str):
            a = ("A", r.nr_turno, r.sg_uf, r.cd_municipio_tse, r.nr_zona, r.nr_secao_apuradora)
            uf.union(o, a)
            # A apuradora é sempre a urna da própria seção homônima. Ligar A(s)–O(s) aqui,
            # e não só para seções com linha em section_turn, resolve cadeias 0012→0011→0010
            # (achado F-03 de C) unindo-as numa unidade, sem redistribuir votos.
            uf.union(a, ("O", r.sg_uf, r.cd_municipio_tse, r.nr_zona, r.nr_secao_apuradora))
    for r in counts.itertuples(index=False):
        a = ("A", r.nr_turno, r.sg_uf, r.cd_municipio_tse, r.nr_zona, r.nr_secao)
        uf.union(a, ("O", r.sg_uf, r.cd_municipio_tse, r.nr_zona, r.nr_secao))
    return uf, ambiguous, not_effective


def _sum_strict(g: pd.core.groupby.DataFrameGroupBy, cols: list[str]) -> pd.DataFrame:
    """Soma em que qualquer termo ausente torna o total ausente (ausente ≠ zero)."""
    s = g[cols].sum(min_count=1)
    has_na = g[cols].count().lt(g.size(), axis=0)
    return s.mask(has_na)


def build_panel(section_turn: pd.DataFrame, votes_long: pd.DataFrame,
                crosswalk: pd.DataFrame, nr_lula: int, nr_flavio: int,
                return_membership: bool = False, technical_null: dict | None = None):
    """Retorna o painel; com return_membership, também (seção apuradora × turno → id_unidade)."""
    counts = section_counts(section_turn, votes_long, nr_lula, nr_flavio, technical_null=technical_null)
    uf, ambiguous, not_effective = _components(counts, crosswalk)

    nodes = list(uf.parent)
    comp = pd.DataFrame({"node": nodes, "root": [uf.find(n) for n in nodes]})
    origins = comp[comp.node.map(lambda n: n[0] == "O")].copy()
    origins["geo"] = origins.node.map(lambda n: n[1:4])
    origins["secao"] = origins.node.map(lambda n: n[4])
    origins["amb"] = origins.node.isin(ambiguous)
    origins["nao_efet"] = origins.node.isin(not_effective)
    per = origins.groupby("root").agg(
        n_secoes_origem=("node", "size"), secao_min=("secao", "min"),
        n_geo=("geo", "nunique"), geo=("geo", "first"), amb=("amb", "any"),
        nao_efet=("nao_efet", "any"))
    per["id_unidade"] = [f"{g[0]}-{g[1]}-{g[2]}-{s}" for g, s in zip(per.geo, per.secao_min)]

    counts["root"] = [uf.find(("A", t, a, b, c, d)) for t, a, b, c, d in
                      counts[["nr_turno"] + GEO + ["nr_secao"]].itertuples(index=False)]
    counts["nao_apurada"] = (counts.st_secao_instalada.eq(False) | counts.st_secao_anulada.eq(True)
                             | counts.qt_votos_validos.isna())
    # Q2 (v1.1): anulados em separado > 0 sem regra documentada → identidade indeterminada.
    counts["falha_contab"] = (counts.flag_identidade_aptos.eq(False)
                              | counts.flag_identidade_comparecimento.eq(False)
                              | counts.qt_votos_anulados_apu_sep.fillna(0).gt(0))

    panel = per[["id_unidade", "n_secoes_origem", "n_geo", "geo", "amb", "nao_efet"]].copy()
    for t in (1, 2):
        ct = counts[counts.nr_turno == t]
        g = ct.groupby("root")
        agg = _sum_strict(g, COUNTS).add_suffix(f"_t{t}")
        agg[f"_present_t{t}"] = True
        agg[f"_nao_apurada_t{t}"] = g.nao_apurada.any()
        agg[f"_contab_t{t}"] = g.falha_contab.any()
        loc = (ct[["root", "nr_local_votacao"]].dropna().drop_duplicates()
               .sort_values(["root", "nr_local_votacao"]))
        agg[f"nr_local_votacao_t{t}"] = loc.groupby("root").nr_local_votacao.agg("|".join)
        panel = panel.join(agg, how="left")
    panel = panel.reset_index(drop=True)

    present = {t: panel[f"_present_t{t}"].eq(True) for t in (1, 2)}
    cond = {
        # n_geo > 1 é defensivo: no contrato v1.1 a apuradora herda UF/município/zona da origem
        # (agregação ocorre no mesmo local de votação), então só a flag de A o aciona (achado F-02).
        "EXCLUIDA_AMBIGUA": panel.amb | (panel.n_geo > 1),
        "EXCLUIDA_CORRESPONDENCIA_NAO_EFETIVADA": panel.nao_efet,
        "EXCLUIDA_AUSENTE_T1": ~present[1],
        "EXCLUIDA_AUSENTE_T2": ~present[2],
        "EXCLUIDA_NAO_APURADA": panel._nao_apurada_t1.eq(True) | panel._nao_apurada_t2.eq(True),
        "EXCLUIDA_CONTABILIDADE": panel._contab_t1.eq(True) | panel._contab_t2.eq(True),
    }
    panel["status_painel"] = np.select(
        [pd.Series(cond[s]).fillna(False).astype(bool).to_numpy() for s in STATUS_ORDER],
        STATUS_ORDER, "PAREADA")
    panel[GEO] = pd.DataFrame(panel.geo.tolist(), index=panel.index)
    panel["tipo_unidade"] = np.where(panel.n_secoes_origem > 1, "AGREGADO_SECOES", "SECAO")
    both = panel.qt_aptos_t1.notna() & panel.qt_aptos_t2.notna()
    panel["flag_aptos_divergente"] = pd.array(
        np.where(both, (panel.qt_aptos_t1 != panel.qt_aptos_t2).fillna(False), pd.NA), dtype="boolean")
    lt1, lt2 = panel.nr_local_votacao_t1, panel.nr_local_votacao_t2
    panel["flag_local_alterado"] = pd.array(
        np.where(lt1.notna() & lt2.notna(), lt1 != lt2, pd.NA), dtype="boolean")
    panel["n_secoes_origem"] = panel.n_secoes_origem.astype("int32")
    panel["contract_version"] = CONTRACT_VERSION
    cols = (["id_unidade"] + GEO + ["n_secoes_origem", "tipo_unidade", "status_painel",
            "flag_aptos_divergente", "nr_local_votacao_t1", "nr_local_votacao_t2",
            "flag_local_alterado"]
            + [f"{c}_t{t}" for c in COUNTS for t in (1, 2)] + ["contract_version"])
    panel = panel[cols].sort_values("id_unidade").reset_index(drop=True)
    if not return_membership:
        return panel
    ids = per.id_unidade
    membership = counts[["nr_turno"] + GEO + ["nr_secao"]].assign(
        id_unidade=counts.root.map(ids).values)
    return panel, membership


def reconcile(panel: pd.DataFrame, membership: pd.DataFrame, section_turn: pd.DataFrame,
              votes_long: pd.DataFrame, nr_lula: int, nr_flavio: int,
              technical_null: dict | None = None) -> pd.DataFrame:
    """Conservação exata entre seções e painel, por turno × métrica × status.

    Caminho independente: cada seção apuradora é somada a partir de
    section_turn/votes_long e atribuída ao status da sua unidade. Compara-se com
    a soma das unidades do painel. `secoes_sem_unidade` e `secoes_duplicadas`
    precisam ser 0; `dif` precisa ser 0 onde a unidade é totalizável. Unidades
    com termo ausente (ausente ≠ zero) são contadas em `unidades_nao_totalizaveis`
    e seus votos observados em `votos_em_nao_totalizaveis`.
    """
    counts = section_counts(section_turn, votes_long, nr_lula, nr_flavio, technical_null=technical_null)
    key = ["nr_turno"] + GEO + ["nr_secao"]
    m = counts.merge(membership, on=key, how="left", validate="one_to_one", indicator=True)
    m = m.merge(panel[["id_unidade", "status_painel"]], on="id_unidade", how="left")
    rows = []
    for t in (1, 2):
        mt = m[m.nr_turno == t]
        for c in COUNTS:
            col = f"{c}_t{t}"
            unit_ok = panel[col].notna()
            for s in ["PAREADA"] + STATUS_ORDER:
                ps = panel[(panel.status_painel == s)]
                ms = mt[mt.status_painel == s]
                ok_ids = set(ps.id_unidade[unit_ok[ps.index]])
                rows.append({
                    "nr_turno": t, "metrica": c, "status_painel": s,
                    "total_secoes": int(ms[c].sum()),
                    "total_painel": int(ps[col].sum()),
                    "dif": int(ps[col].sum()) - int(ms[ms.id_unidade.isin(ok_ids)][c].sum()),
                    "unidades_nao_totalizaveis": int((~unit_ok[ps.index]).sum()),
                    "votos_em_nao_totalizaveis": int(ms[~ms.id_unidade.isin(ok_ids)][c].sum()),
                })
    out = pd.DataFrame(rows)
    out.attrs["secoes_sem_unidade"] = int(m.id_unidade.isna().sum())
    out.attrs["secoes_duplicadas"] = int(membership.duplicated(key).sum())
    out.attrs["total_completo"] = {
        (t, c): int(counts.loc[counts.nr_turno == t, c].sum()) for t in (1, 2) for c in COUNTS}
    return out


def coverage(panel: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Cobertura por recorte em unidades, aptos e votos válidos, incluídos × excluídos."""
    by = by or ["sg_uf"]
    p = panel.assign(incluida=panel.status_painel.eq("PAREADA"))
    agg = {"unidades": ("id_unidade", "size")}
    for c in ("qt_aptos_t1", "qt_aptos_t2", "qt_votos_validos_t1", "qt_votos_validos_t2"):
        agg[c] = (c, "sum")
    g = p.groupby(by + ["incluida"]).agg(**agg).unstack("incluida", fill_value=0)
    # sem nenhuma exclusão (ou inclusão) o unstack não cria a coluna; zero aqui é contagem observada
    g = g.reindex(columns=pd.MultiIndex.from_product([list(agg), [True, False]]), fill_value=0)
    g.columns = [f"{m}_{'incluida' if inc else 'excluida'}" for m, inc in g.columns]
    for m in ("unidades",) + tuple(k for k in agg if k != "unidades"):
        inc, exc = g.get(f"{m}_incluida", 0), g.get(f"{m}_excluida", 0)
        g[f"{m}_pct_incluida"] = inc / (inc + exc).replace(0, np.nan)
    return g.reset_index()


def aggregate_panel(panel: pd.DataFrame, level: str) -> pd.DataFrame:
    """Soma unidades pareadas a LOCAL (local do T1) ou MUNICIPIO para sensibilidade."""
    p = panel[panel.status_painel == "PAREADA"]
    keys = {"LOCAL": ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_local_votacao_t1"],
            "MUNICIPIO": ["sg_uf", "cd_municipio_tse"]}[level]
    cols = [f"{c}_t{t}" for c in COUNTS for t in (1, 2)]
    return p.groupby(keys, dropna=False)[cols].sum().reset_index()
