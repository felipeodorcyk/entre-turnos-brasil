"""Confronto UF × turno × métrica do staging com a referência oficial independente (handoff 26).

Referência: `docs/sources/official_totals_reference.csv` (Relatório de Totalização por UF, dois
turnos). Observado: somas do staging por seção (`br2026.reporting.acceptance.observed_totals`),
a mesma função dos aceites M1/M2. Uma linha por UF × turno × métrica, com a diferença; nenhuma
tolerância.

Saída: `reports/analysis/evidencias_nacional/referencia_m1_m2_uf.csv`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from br2026.config import election_numbers, load_config  # noqa: E402
from br2026.contract import read_table  # noqa: E402
from br2026.panel.run import staging_path  # noqa: E402
from br2026.reporting.acceptance import observed_totals  # noqa: E402


def main() -> int:
    staging = RAIZ / "data" / "staging"
    st = read_table(staging_path(staging, "section_turn"), "section_turn")
    vl = read_table(staging_path(staging, "votes_long"), "votes_long")
    obs = observed_totals(st, vl, *election_numbers(load_config()))
    ref = pd.read_csv(RAIZ / "docs" / "sources" / "official_totals_reference.csv", dtype={"sg_uf": str})
    linhas = []
    for r in ref.itertuples(index=False):
        o = obs.get((int(r.nr_turno), r.sg_uf, r.metrica))
        linhas.append({"nr_turno": int(r.nr_turno), "sg_uf": r.sg_uf, "metrica": r.metrica,
                       "valor_referencia": int(r.valor), "valor_staging": o,
                       "dif": None if o is None else int(o) - int(r.valor), "url": r.url})
    # UF × turno do staging sem referência também é falha (cobertura incompleta)
    chaves_ref = {(int(r.nr_turno), r.sg_uf, r.metrica) for r in ref.itertuples(index=False)}
    for k, v in sorted(obs.items()):
        if k not in chaves_ref:
            linhas.append({"nr_turno": k[0], "sg_uf": k[1], "metrica": k[2], "valor_referencia": None,
                           "valor_staging": v, "dif": None, "url": None})
    df = pd.DataFrame(linhas).sort_values(["nr_turno", "sg_uf", "metrica"])
    out = RAIZ / "reports" / "analysis" / "evidencias_nacional"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "referencia_m1_m2_uf.csv", index=False)
    ok = df.dif.notna() & (df.dif == 0)
    print(f"{int(ok.sum())} de {len(df)} métricas iguais; UF × turno: "
          f"{df.groupby(['nr_turno', 'sg_uf']).ngroups}")
    if not ok.all():
        print(df[~ok].to_string(index=False))
    return 0 if ok.all() else 1


if __name__ == "__main__":
    raise SystemExit(main())
