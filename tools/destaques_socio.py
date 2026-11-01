"""Reprodução do recorte de imprensa sobre Bolsa Família × emprego formal (tabela 25 do relatório).

Recorte do Poder360: municípios em que há mais famílias no Bolsa Família do que empregos com
carteira assinada. Aproximação com os insumos do projeto: registros de pagamento da folha de
agosto/2026 (CGU/MDS; não há identificador familiar) > vínculos CLT ativos em 31/12/2025 (RAIS,
município do estabelecimento). Os períodos e as definições da reportagem não foram publicados,
então a contagem de municípios difere; a tabela compara o grupo com os demais municípios.

Uso:
    python tools/destaques_socio.py [--root R]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]


def grupo_pbf_clt(root: Path) -> pd.DataFrame:
    m = pd.read_parquet(root / "data/analytics/socio/painel_municipal_socio.parquet")
    k = ["sg_uf", "cd_municipio_tse"]
    p = pd.read_parquet(root / "data/staging/socio_pbf/socio_pbf_202608.parquet")
    p = p[p.indicador == "registros_pagamento_pbf"][k + ["valor"]].rename(columns={"valor": "registros_pbf"})
    r = pd.read_parquet(root / "data/staging/socio_rais/socio_rais_2025.parquet")
    r = r[r.indicador == "vinculos_clt_total"][k + ["valor"]].rename(columns={"valor": "vinculos_clt"})
    d = m.merge(p, on=k, how="left").merge(r, on=k, how="left")
    d["grupo"] = (d.registros_pbf > d.vinculos_clt).map({True: "pbf_maior_que_clt", False: "demais"})
    d.loc[d.registros_pbf.isna() | d.vinculos_clt.isna(), "grupo"] = "sem_indicador"
    cols = ["qt_votos_validos_t1", "qt_votos_validos_t2", "qt_lula_t1", "qt_lula_t2", "qt_flavio_t1", "qt_flavio_t2",
            "qt_aptos_t1", "qt_aptos_t2", "qt_abstencoes_t1", "qt_abstencoes_t2", "delta_qt_lula", "delta_qt_flavio",
            "delta_qt_comparecimento"]
    g = d.groupby("grupo")[cols].sum()
    g["municipios"] = d.groupby("grupo").size()
    g["lula_vence_t1"] = d[d.qt_lula_t1 > d.qt_flavio_t1].groupby("grupo").size()
    g["lula_vence_t2"] = d[d.qt_lula_t2 > d.qt_flavio_t2].groupby("grupo").size()
    g["flavio_vence_t1"] = d[d.qt_flavio_t1 > d.qt_lula_t1].groupby("grupo").size()
    g["flavio_vence_t2"] = d[d.qt_flavio_t2 > d.qt_lula_t2].groupby("grupo").size()
    g = g.fillna(0)
    tot = g.sum()
    g["share_lula_t1"] = g.qt_lula_t1 / g.qt_votos_validos_t1
    g["share_lula_t2"] = g.qt_lula_t2 / g.qt_votos_validos_t2
    g["delta_share_lula"] = g.share_lula_t2 - g.share_lula_t1
    g["abstencao_t1"] = g.qt_abstencoes_t1 / g.qt_aptos_t1
    g["abstencao_t2"] = g.qt_abstencoes_t2 / g.qt_aptos_t2
    g["fracao_validos_t1"] = g.qt_votos_validos_t1 / tot.qt_votos_validos_t1
    g["fracao_ganho_lula"] = g.delta_qt_lula / tot.delta_qt_lula
    g["fracao_aumento_comparecimento"] = g.delta_qt_comparecimento / tot.delta_qt_comparecimento
    return g.reset_index()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", default=os.environ.get("BR2026_ROOT", str(REPO)), help="raiz com data/")
    a = p.parse_args(argv)
    t = grupo_pbf_clt(Path(a.root))
    out = REPO / "reports/analysis/tabelas_nacional/tab25_socio_pbf_clt.csv"
    t.to_csv(out, index=False)
    print(t[["grupo", "municipios", "share_lula_t1", "share_lula_t2", "delta_qt_lula", "fracao_ganho_lula"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
