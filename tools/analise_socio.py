"""Análises do contexto socioeconômico (handoff 37), a partir das saídas de `analyze` e das frentes 34–36.

Lê `data/analytics/` (painel, métricas, perfil, faixas de encerramento) e os produtos socioeconômicos
em `data/staging/`; escreve tabelas agregadas em `data/analytics/socio/`, consumidas por `report`.
Não altera nenhum total eleitoral: cada join é conferido por linhas e votos.

Uso: python tools/analise_socio.py [--offline]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from br2026.analysis import socio  # noqa: E402
from br2026.analysis.closure_models import pairwise_comparison  # noqa: E402
from br2026.analysis.profile import profile_design  # noqa: E402
from br2026.config import load_config  # noqa: E402
from br2026.contract import read_table  # noqa: E402
from br2026.panel.run import staging_path  # noqa: E402

AN = RAIZ / "data" / "analytics"
OUT = AN / "socio"
GEO = ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
ELIMINADOS = {14: "Renan Santos (MISSÃO)", 55: "Ronaldo Caiado (PSD)", 70: "Augusto Cury (AVANTE)"}


def votos_eliminados_t1(cfg: dict) -> pd.DataFrame:
    """Votos do 1º turno de cada eliminado por município (staging), mais 'outros'. Votos em candidato
    que renunciou são nulos técnicos (config [election.nulo_tecnico]) e não entram, como no painel."""
    vl = read_table(staging_path(RAIZ / "data" / "staging", "votes_long"), "votes_long")
    vl = vl[(vl.cd_cargo == 1) & (vl.nr_turno == 1) & (vl.sg_uf != "ZZ")]
    tecnicos = list(cfg["election"]["nulo_tecnico"]["t1"])
    nominais = vl[(vl.tipo_votavel == "NOMINAL") & ~vl.nr_votavel.isin([13, 22] + tecnicos)]
    p = nominais.assign(cand=nominais.nr_votavel.map(lambda n: f"qt_cand_{n}" if n in ELIMINADOS else "qt_cand_outros")) \
        .pivot_table(index=["sg_uf", "cd_municipio_tse"], columns="cand", values="qt_votos", aggfunc="sum", fill_value=0)
    return p.reset_index()


def quadro_unidades(cfg: dict) -> pd.DataFrame:
    """Unidades pareadas do território com variações, controles, perfil e faixa de encerramento (como `analyze`)."""
    panel = pd.read_parquet(AN / "panel.parquet")
    terr = panel[(panel.status_painel == "PAREADA") & (panel.sg_uf != cfg["universe"]["uf_exterior"])]
    um = pd.read_parquet(AN / "metrics_units.parquet").set_index("id_unidade")
    d = terr.set_index("id_unidade")
    d = d.join(um[["delta_share_lula_validos", "delta_margem_lula_flavio_validos", "delta_comparecimento_aptos",
                   "comparecimento_aptos_t1", "share_lula_validos_t1"]])
    d["log_aptos_t1"] = np.log(d.qt_aptos_t1.astype(float).where(d.qt_aptos_t1 > 0))
    d["peso"] = d.qt_aptos_t1.astype(float)
    d["municipio"] = d.sg_uf + "-" + d.cd_municipio_tse
    prof = pd.read_parquet(AN / "profile_units.parquet").set_index("id_unidade")
    d = d.join(profile_design(prof, cfg), how="left")
    # faixas de encerramento (variante principal), unidade com seções em faixas diferentes = MISTA
    cs = pd.read_csv(AN / "closure_sections.csv", dtype={"cd_municipio_tse": str, "nr_zona": str, "nr_secao": str},
                     usecols=["nr_turno"] + GEO + ["faixa"])
    mb = pd.read_parquet(AN / "panel_membership.parquet")
    c = cs.merge(mb, on=["nr_turno"] + GEO, how="inner")
    g = c.groupby(["id_unidade", "nr_turno"]).faixa.agg(["first", "nunique"])
    g["faixa_unidade"] = np.where(g["nunique"] == 1, g["first"], "MISTA")
    w = g.faixa_unidade.unstack().rename(columns={1: "faixa_t1", 2: "faixa_t2"})
    d = d.join(w[["faixa_t1", "faixa_t2"]], how="left")
    d["faixa_t1_tardia"] = d.faixa_t1.isin(["18H_19H", "A_PARTIR_19H"]).astype(float)
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    resumo: dict = {}

    # 1. painel municipal
    mun, audit = socio.painel_municipal(RAIZ, AN, offline=a.offline)
    elim = votos_eliminados_t1(cfg)
    n0 = len(mun)
    mun = mun.merge(elim, on=["sg_uf", "cd_municipio_tse"], how="left", validate="one_to_one")
    assert len(mun) == n0
    cand_cols = [c for c in mun.columns if c.startswith("qt_cand_")]
    soma_cand = int(mun[cand_cols].sum().sum())
    demais = int((mun.qt_votos_validos_t1 - mun.qt_lula_t1 - mun.qt_flavio_t1).sum())
    audit["votos_eliminados_t1"] = {"soma_candidatos": soma_cand, "demais_validos": demais,
                                    "confere": soma_cand == demais}
    if soma_cand != demais:
        raise SystemExit(f"votos dos eliminados ({soma_cand}) diferem dos demais válidos ({demais})")
    mun.to_parquet(OUT / "painel_municipal_socio.parquet", index=False)
    resumo["painel_municipal"] = audit

    # 2. faixas
    fx = pd.concat([socio.tabela_faixas(mun, n) for n in socio.INDICADORES], ignore_index=True)
    fx.to_csv(OUT / "faixas_nacional.csv", index=False)
    fr = pd.concat([socio.tabela_faixas(mun, n, "regiao") for n in socio.INDICADORES], ignore_index=True)
    fr.to_csv(OUT / "faixas_regiao.csv", index=False)
    fu = pd.concat([socio.tabela_faixas(mun, n, "sg_uf") for n in socio.INDICADORES], ignore_index=True)
    fu.to_csv(OUT / "faixas_uf.csv", index=False)

    # 3. modelos municipais
    mm = socio.modelos_municipais(mun)
    mm.to_csv(OUT / "modelos_municipais.csv", index=False)
    pd.concat([socio.modelo_conjunto(mun, y) for y in socio.DESFECHOS], ignore_index=True) \
        .to_csv(OUT / "modelo_conjunto.csv", index=False)

    # 4. afinidade
    rot = {f"qt_cand_{k}": v for k, v in ELIMINADOS.items()} | {"qt_cand_outros": "Outros eliminados"}
    socio.perfis_bases(mun, rot).to_csv(OUT / "perfis_bases.csv", index=False)
    mun_c = mun.assign(qt_bn_t1=mun.qt_votos_brancos_t1 + mun.qt_votos_nulos_t1,
                       qt_abst_t1=mun.qt_aptos_t1 - mun.qt_comparecimento_t1)
    socio.correlacoes_bases(mun_c, rot | {"qt_bn_t1": "Brancos e nulos", "qt_abst_t1": "Abstenção"}) \
        .to_csv(OUT / "correlacoes_bases.csv", index=False)

    # 5. entorno
    d = quadro_unidades(cfg)
    mb = pd.read_parquet(AN / "panel_membership.parquet")
    ent, diag = socio.entorno_unidades(RAIZ, d.reset_index()[["id_unidade", "sg_uf"]], mb)
    resumo["entorno_unidades"] = diag
    linhas_ent = []
    if not ent.empty:
        d = d.join(ent, how="left")
        d["status_entorno"] = d.status_entorno.fillna("SEM_REGISTRO")
        ctrl = ["log_aptos_t1", "comparecimento_aptos_t1", "share_lula_validos_t1"] + \
            [c for c in d.columns if c.startswith("perfil_")]
        valido = d[d.status_entorno == "VALIDO"]
        renda_ok = valido[valido.flag_renda_valida.fillna(False).astype(bool)]
        # versão final (handoff 40): só o raio principal de 1 km; colunas _500/_3000, se armazenadas, são legado
        me = socio.modelos_entorno(d, ctrl, cfg["socio"]["entorno_cobertura_renda_min"])
        me.to_csv(OUT / "modelos_entorno.csv", index=False)
        resumo["entorno_raio"] = {
            "raio_m": int(cfg["socio"]["entorno_raio_m"]),
            "cobertura_area_min": cfg["socio"]["entorno_cobertura_area_min"],
            "cobertura_renda_min": cfg["socio"]["entorno_cobertura_renda_min"],
            "unidades_entorno_valido": int(len(valido)), "unidades_renda_valida": int(len(renda_ok)),
            "unidades_modelo_principal": {v: int(me[(me.indicador == v) & (me.filtro == "principal")
                                                    & (me.cluster == "id_local")].n_unidades.iloc[0])
                                          for v in socio.ENTORNO}}
        cob = d.groupby("sg_uf").agg(unidades=("peso", "size"), aptos=("peso", "sum"))
        cob["unidades_entorno_valido"] = d[d.status_entorno == "VALIDO"].groupby("sg_uf").size()
        cob["aptos_entorno_valido"] = d[d.status_entorno == "VALIDO"].groupby("sg_uf").peso.sum()
        cob["unidades_renda_valida"] = renda_ok.groupby("sg_uf").size()
        cob["aptos_renda_valida"] = renda_ok.groupby("sg_uf").peso.sum()
        cob = cob.fillna(0).reset_index()
        tot = cob.drop(columns="sg_uf").sum()
        cob = pd.concat([cob, pd.DataFrame([{"sg_uf": "TOTAL", **tot.to_dict()}])], ignore_index=True)
        cob.to_csv(OUT / "cobertura_entorno_uf.csv", index=False)

    # 6. seções tardias: mesma comparação de `analyze`, com e sem contexto de entorno, mesma amostra
    cont = ["log_aptos_t1", "comparecimento_aptos_t1", "share_lula_validos_t1"]
    prof_cols = [c for c in d.columns if c.startswith("perfil_")]
    other = prof_cols + ["faixa_t1_tardia"]
    tard = []
    if "status_entorno" in d:
        dd = d.assign(_renda_log=np.log(d.renda_media_responsavel.where(d.renda_media_responsavel > 0)),
                      _dens_log=np.log(d.densidade_hab_km2.where(d.densidade_hab_km2 > 0)))
        amostra_ent = dd[(dd.status_entorno == "VALIDO") & dd.flag_renda_valida.fillna(False).astype(bool)]
        novos = ["_renda_log", "pct_pop_urbana", "_dens_log", "pct_pop_favela"]
        amostra_ent = amostra_ent.dropna(subset=novos)
        for y in socio.DESFECHOS:
            for rot_, base, extra in (("a_amostra_original", dd, []), ("b_amostra_com_entorno_sem_controles", amostra_ent, []),
                                      ("c_amostra_com_entorno_com_controles", amostra_ent, novos)):
                r = pairwise_comparison(base.reset_index(), "faixa_t2", "17H00_17H15", "A_PARTIR_19H", y, cont,
                                        other + extra, cfg)
                tard.append({"etapa": rot_, **{k: v for k, v in r.items() if k != "controles"}})
    pd.DataFrame(tard).to_csv(OUT / "tardias_com_contexto.csv", index=False)

    # proveniência: SHA-256 de cada insumo lido
    import hashlib

    def sha(p: Path) -> str:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()

    st = RAIZ / "data" / "staging"
    insumos = [AN / n for n in ("metrics_municipio.csv", "metrics_units.parquet", "panel.parquet",
                                "panel_membership.parquet", "profile_units.parquet", "closure_sections.csv")]
    insumos += [st / f for f in {v[0] for v in {**socio.INDICADORES, **socio.SENSIBILIDADES}.values()}]
    insumos += sorted((st / "entorno_local").glob("locais_*.parquet")) + sorted((st / "entorno_local").glob("secoes_*.parquet"))
    insumos.append(RAIZ / "data" / "raw" / "ibge_localidades" / "municipios.json")
    resumo["insumos_sha256"] = {str(p.relative_to(RAIZ)).replace("\\", "/"): sha(p) for p in insumos if p.exists()}
    resumo["segundos"] = round(time.perf_counter() - t0, 1)
    (OUT / "resumo_socio.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2, default=str),
                                           encoding="utf-8")
    print(json.dumps({k: v for k, v in resumo.items() if k != "painel_municipal"}, ensure_ascii=False, default=str)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
