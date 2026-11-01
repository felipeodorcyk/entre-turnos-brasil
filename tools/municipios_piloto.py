"""Tabela de nomes dos municípios do piloto, para legendas do relatório (handoff 22).

Lê `eleitorado_local_votacao_2026.zip` resolvido por `data/raw/manifest.json` e grava
`docs/sources/municipios_piloto.csv` (sg_uf, cd_municipio_tse, nm_municipio, source_id), ou o
arquivo indicado em `--saida` (handoff 26: `municipios.csv`, as 28 unidades).
Só rótulos: nenhum número do relatório vem desta tabela.

Uso: python tools/municipios_piloto.py [--root DIR] [--saida NOME] [UF ...]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=Path(__file__).resolve().parents[1], type=Path)
    ap.add_argument("--saida", default="municipios_piloto.csv")
    ap.add_argument("ufs", nargs="*", default=["AC", "RS", "MG"])
    a = ap.parse_args(argv)
    reg = json.loads((a.root / "data" / "raw" / "manifest.json").read_text(encoding="utf-8"))["registros"]
    r = reg["eleitorado_local_votacao_2026"]
    zp = a.root / "data" / "raw" / r["arquivo"]
    sha = hashlib.sha256(zp.read_bytes()).hexdigest()
    if sha != r["sha256"]:
        raise SystemExit(f"SHA-256 de {zp.name} difere do manifesto")
    nomes: dict[tuple[str, str], str] = {}
    with zipfile.ZipFile(zp) as z:
        for uf in a.ufs:
            with z.open(f"eleitorado_local_votacao_2026_{uf}.csv") as fh:
                rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1", newline=""), delimiter=";")
                for row in rd:
                    nomes[(uf, row["CD_MUNICIPIO"].strip().zfill(5))] = row["NM_MUNICIPIO"].strip()
    out = a.root / "docs" / "sources" / a.saida
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sg_uf", "cd_municipio_tse", "nm_municipio", "source_id"])
        for (uf, cd), nm in sorted(nomes.items()):
            w.writerow([uf, cd, nm, sha])
    print(f"{len(nomes)} municípios em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
