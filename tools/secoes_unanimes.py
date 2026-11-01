"""Teste da alegação de seções com votos para um só candidato (C12, handoff 24).

Lê o consolidado oficial `votacao_secao_2026_BR` (resolvido por data/raw/manifest.json, SHA-256
conferido), filtra presidente no turno pedido e, para as seções listadas em
docs/sources/contraste/c12_secoes_citadas.csv, conta os votáveis nominais com voto > 0 e a
participação do mais votado. Também conta, no país, quantas seções tiveram um único votável
nominal com votos. Saída agregada por seção (sem dado pessoal).

Uso: python tools/secoes_unanimes.py [--root DIR] [--turno 1]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd


def _norm(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.upper()) if unicodedata.category(c) != "Mn").strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=Path(__file__).resolve().parents[1], type=Path)
    ap.add_argument("--turno", default="1")
    a = ap.parse_args(argv)
    reg = json.loads((a.root / "data" / "raw" / "manifest.json").read_text(encoding="utf-8"))["registros"]["votacao_secao_2026_BR"]
    zp = a.root / "data" / "raw" / reg["arquivo"]
    sha = hashlib.sha256(zp.read_bytes()).hexdigest()
    if sha != reg["sha256"]:
        raise SystemExit("SHA-256 do consolidado difere do manifesto")
    cit = pd.read_csv(a.root / "docs" / "sources" / "contraste" / "c12_secoes_citadas.csv", dtype=str)
    alvo = {(r.sg_uf, _norm(r.nm_municipio), int(r.nr_zona), int(r.nr_secao)) for r in cit.itertuples()}
    votos = defaultdict(lambda: defaultdict(int))     # (uf, mun, zona, secao) -> nr_votavel -> votos
    unico = defaultdict(lambda: [0, 0])               # uf -> [seções com 1 votável nominal, seções]
    sec_nom = defaultdict(dict)
    with zipfile.ZipFile(zp) as z, z.open("votacao_secao_2026_BR.csv") as fh:
        rd = csv.reader(io.TextIOWrapper(fh, encoding="latin-1", newline=""), delimiter=";")
        h = next(rd)
        ix = {c: i for i, c in enumerate(h)}
        for row in rd:
            if row[ix["CD_CARGO"]] != "1" or row[ix["NR_TURNO"]] != a.turno:
                continue
            nr = int(row[ix["NR_VOTAVEL"]])
            q = int(row[ix["QT_VOTOS"]])
            k = (row[ix["SG_UF"]], _norm(row[ix["NM_MUNICIPIO"]]), int(row[ix["NR_ZONA"]]), int(row[ix["NR_SECAO"]]))
            if nr not in (95, 96) and q > 0:
                sec_nom[k][nr] = q
            if k in alvo:
                votos[k][nr] += q
    for k, d in sec_nom.items():
        unico[k[0]][1] += 1
        unico[k[0]][0] += int(len(d) == 1)
    linhas = []
    for (uf, mun, zona, secao) in sorted(alvo):
        d = votos.get((uf, mun, zona, secao), {})
        nom = {n: q for n, q in d.items() if n not in (95, 96) and q > 0}
        tot = sum(nom.values())
        top = max(nom.items(), key=lambda x: x[1]) if nom else (None, 0)
        linhas.append({"sg_uf": uf, "municipio": mun, "nr_zona": zona, "nr_secao": secao,
                       "encontrada": bool(d), "votaveis_nominais_com_voto": len(nom),
                       "votos_nominais": tot, "mais_votado": top[0],
                       "participacao_mais_votado": round(top[1] / tot, 4) if tot else None,
                       "brancos_nulos": sum(q for n, q in d.items() if n in (95, 96))})
    out = pd.DataFrame(linhas)
    dest = a.root / "reports" / "analysis" / "tabelas_piloto" / "c12_secoes_citadas_resultado.csv"
    out.to_csv(dest, index=False)
    br = pd.DataFrame([{"sg_uf": uf, "secoes_um_votavel_nominal": v[0], "secoes": v[1]} for uf, v in sorted(unico.items())])
    br.to_csv(dest.with_name("c12_secoes_um_votavel_por_uf.csv"), index=False)
    print(out.to_string(index=False))
    print("país:", int(br.secoes_um_votavel_nominal.sum()), "de", int(br.secoes.sum()), "seções com um só votável nominal")
    print("fonte:", reg["arquivo"], sha[:16])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
