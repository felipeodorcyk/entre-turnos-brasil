"""Rótulos legíveis das categorias de origem e destino dos fluxos (handoff 24, versão editorial).

Candidatos: nome de urna e partido do JSON oficial nacional do 1º turno (portal Resultados,
eleição 6257, `docs/sources/contraste/br-c0001-e006257-u.json`). Demais categorias: texto fixo.
Grava `docs/sources/rotulos_votaveis.csv` (codigo, rotulo, fonte). Só rótulos: nenhum número
do relatório vem desta tabela.

Uso: python tools/rotulos_votaveis.py [--root DIR]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

FIXOS = {
    "LULA_T1": "Lula no 1º turno", "FLAVIO_T1": "Flávio no 1º turno", "OUTROS": "demais candidatos menores",
    "ABSTENCAO": "abstenção", "BRANCO": "voto em branco", "NULO": "voto nulo",
    "ENTRADA_CADASTRO_CENARIO": "entrada no cadastro (cenário)", "SAIDA_CADASTRO_CENARIO": "saída do cadastro (cenário)",
    "LULA": "Lula", "FLAVIO": "Flávio",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=Path(__file__).resolve().parents[1], type=Path)
    a = ap.parse_args(argv)
    p = a.root / "docs" / "sources" / "contraste" / "br-c0001-e006257-u.json"
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    j = json.loads(p.read_text(encoding="utf-8"))
    linhas = [(k, v, "fixo") for k, v in FIXOS.items()]
    for agr in j["carg"][0]["agr"]:
        for par in agr["par"]:
            for c in par["cand"]:
                linhas.append((f"CAND_{int(c['n'])}", f"{c['nmu'].title()} ({par.get('sg', '')}, {int(c['n'])})",
                               f"{p.relative_to(a.root).as_posix()}@{sha[:16]}"))
    out = a.root / "docs" / "sources" / "rotulos_votaveis.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["codigo", "rotulo", "fonte"])
        w.writerows(sorted(linhas))
    print(f"{len(linhas)} rótulos em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
