"""Reprodução da seleção UOL/Agência Tatu de seções "abertas até 19h" (handoff 29).

Fonte: arquivos públicos do mapa interativo da Agência Tatu (`data/raw/externo/tatu_votacao_apos_17h/`,
hashes em `docs/sources/contraste/tatu_votacao_apos_17h/SHA256SUMS`). `nomes/{UF}.json` lista,
por local de votação, as seções com [seção, abertura, encerramento, comparecimento, tarde,
campo5, votos após 17h, último voto, marcador 19h]; os significados foram conferidos contra o
nosso staging (comparecimento idêntico seção a seção) e contra o BU (ver `reconciliar_tardias.py`).

Esta ferramenta não decide se a seleção está "certa": mede (1) se as seções marcadas existem no
painel e (2) se a soma dos votos do painel nelas reproduz os totais publicados. A diferença
residual fica registrada com a explicação que os dados permitem.

Saída: `reports/analysis/evidencias_horarios/tatu_secoes.parquet` (lista normalizada, sem nomes de
locais) e `tatu_reproducao.json`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from br2026.contract import read_table  # noqa: E402
from br2026.panel.run import staging_path  # noqa: E402

FONTE = RAIZ / "data" / "raw" / "externo" / "tatu_votacao_apos_17h"
PUBLICADO = {"secoes": 5330, "lula": 828376, "flavio": 679147, "comparecimento": 1563997}
K = ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]


def secoes_tatu() -> pd.DataFrame:
    meta = json.loads((FONTE / "meta.json").read_text(encoding="utf-8"))
    mun = pd.DataFrame(json.loads((FONTE / "municipios.json").read_text(encoding="utf-8"))).iloc[:, :3]
    mun.columns = ["mun_nome", "sg_uf", "cd"]
    linhas = []
    for uf in meta["ufs"]:
        for loc in json.loads((FONTE / "nomes" / f"{uf}.json").read_text(encoding="utf-8")):
            for s in loc[7]:
                linhas.append([uf, loc[4], loc[5], loc[6], *s])
    d = pd.DataFrame(linhas, columns=["sg_uf", "mun_nome", "zona", "nr_local", "secao", "abertura_tatu",
                                      "encerramento_tatu", "comparecimento_tatu", "tarde_tatu", "campo5_tatu",
                                      "votos_apos17_tatu", "ultimo_voto_tatu", "u19_tatu"])
    d = d.merge(mun, on=["mun_nome", "sg_uf"], how="left", validate="many_to_one")
    if d.cd.isna().any():
        raise SystemExit(f"{int(d.cd.isna().sum())} seção(ões) da Tatu sem código de município")
    d["cd_municipio_tse"] = d.cd.astype(int).astype(str).str.zfill(5)
    d["nr_zona"] = d.zona.astype(int).astype(str).str.zfill(4)
    d["nr_secao"] = d.secao.astype(int).astype(str).str.zfill(4)
    return d.drop(columns=["cd", "zona", "secao", "mun_nome"])


def main() -> int:
    d = secoes_tatu()
    st = read_table(staging_path(RAIZ / "data" / "staging", "section_turn"), "section_turn")
    st = st[(st.cd_cargo == 1) & (st.nr_turno == 2) & (st.sg_uf != "ZZ")]
    vl = read_table(staging_path(RAIZ / "data" / "staging", "votes_long"), "votes_long")
    vl = vl[(vl.cd_cargo == 1) & (vl.nr_turno == 2) & vl.nr_votavel.isin([13, 22])]
    v = vl.pivot_table(index=K, columns="nr_votavel", values="qt_votos", aggfunc="sum", fill_value=0)
    v.columns = ["lula_t2", "flavio_t2"]
    d = d.merge(st[K + ["qt_comparecimento"]], on=K, how="left").merge(v.reset_index(), on=K, how="left")
    u = d[d.u19_tatu]
    rep = {"secoes_lista_tatu": int(len(d)), "secoes_universo_tatu": 497897,
           "secoes_marcadas_19h": int(len(u)), "secoes_marcadas_sem_par_no_painel": int(u.qt_comparecimento.isna().sum()),
           "lula_t2": int(u.lula_t2.sum()), "flavio_t2": int(u.flavio_t2.sum()),
           "comparecimento_t2": int(u.qt_comparecimento.sum()),
           "comparecimento_igual_secao_a_secao": bool((d.comparecimento_tatu == d.qt_comparecimento).mean() > 0.999),
           "fracao_comparecimento_igual": float((d.comparecimento_tatu == d.qt_comparecimento).mean()),
           "publicado": PUBLICADO}
    rep["dif_vs_publicado"] = {"secoes": rep["secoes_marcadas_19h"] - PUBLICADO["secoes"],
                               "lula": rep["lula_t2"] - PUBLICADO["lula"],
                               "flavio": rep["flavio_t2"] - PUBLICADO["flavio"],
                               "comparecimento": rep["comparecimento_t2"] - PUBLICADO["comparecimento"]}
    out = RAIZ / "reports" / "analysis" / "evidencias_horarios"
    out.mkdir(parents=True, exist_ok=True)
    d.drop(columns=["nr_local"]).to_parquet(out / "tatu_secoes.parquet", index=False)
    (out / "tatu_reproducao.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
