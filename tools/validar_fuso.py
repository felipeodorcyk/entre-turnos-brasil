"""Validação nacional da semântica do relógio do BU (handoff 29).

Pergunta: o relógio do BU marca a hora LOCAL? Se sim, o deslocamento para Brasília inferido
pela ABERTURA das urnas (votação a partir das 8h de Brasília, Res. TSE 23.751/2026) tem de ser o
fuso legal do município. A comparação usa, por município e turno, o deslocamento inferido por
`br2026.analysis.closure_tz.infer_municipal_offsets` (só aberturas, nunca o encerramento) e o
fuso legal:

- Lei 12.876/2013: UTC−3 no DF e nos estados do Sul, Sudeste, Nordeste, GO, TO, PA e AP
  (deslocamento 0 h); UTC−4 em MT, MS, RO, RR (+1 h); UTC−5 no AC (+2 h). AM: a lei divide o
  estado por uma linha de Tabatinga a Porto Acre, sem listar municípios (+1 ou +2 h; o lado da
  linha não é verificável pela lei, só pela abertura).
- Decreto 2.784/1913: Fernando de Noronha (PE 30015) em UTC−2 (−1 h).

Saída: `reports/analysis/evidencias_horarios/validacao_fuso_municipios.csv` (um município ×
turno por linha) e um resumo no stdout. Exterior fora: o fuso varia por país e não tem norma
brasileira; os horários do exterior ficam fora da comparação principal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from br2026.analysis.closure_tz import infer_municipal_offsets  # noqa: E402
from br2026.config import load_config  # noqa: E402
from br2026.contract import read_table  # noqa: E402
from br2026.panel.run import staging_path  # noqa: E402

FUSO_LEGAL_H = {**{uf: 0 for uf in ("AL", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "PA", "PB", "PE", "PI",
                                    "PR", "RJ", "RN", "RS", "SC", "SE", "SP", "TO")},
                "MT": 1, "MS": 1, "RO": 1, "RR": 1, "AC": 2}
EXCECOES_MUNICIPIO_H = {("PE", "30015"): -1}   # Fernando de Noronha
AMBIGUO_LEGAL = {"AM": (1, 2)}


def legal(uf: str, mun: str) -> tuple[str, object]:
    if (uf, mun) in EXCECOES_MUNICIPIO_H:
        return "DECRETO_2784_1913", EXCECOES_MUNICIPIO_H[(uf, mun)]
    if uf in AMBIGUO_LEGAL:
        return "LEI_12876_LINHA_SEM_LISTA", AMBIGUO_LEGAL[uf]
    if uf in FUSO_LEGAL_H:
        return "LEI_12876_UF", FUSO_LEGAL_H[uf]
    return "SEM_NORMA_BRASILEIRA", None


def validar(closure: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    off = infer_municipal_offsets(closure, cfg)
    off = off[off.sg_uf != "ZZ"].copy()
    leg = [legal(u, m) for u, m in zip(off.sg_uf, off.cd_municipio_tse)]
    off["base_legal"] = [b for b, _ in leg]
    off["offset_legal_h"] = [v if not isinstance(v, tuple) else "|".join(map(str, v)) for _, v in leg]

    def confere(r) -> str:
        if r.status_fuso != "INFERIDO_ABERTURA_MUNICIPAL":
            return "SEM_INFERENCIA"
        v = legal(r.sg_uf, r.cd_municipio_tse)[1]
        ok = r.offset_h in v if isinstance(v, tuple) else r.offset_h == v
        return "CONFERE" if ok else "DIVERGE"
    off["resultado"] = off.apply(confere, axis=1)
    return off


def main() -> int:
    cl = read_table(staging_path(RAIZ / "data" / "staging", "closure"), "closure")
    v = validar(cl, load_config())
    out = RAIZ / "reports" / "analysis" / "evidencias_horarios"
    out.mkdir(parents=True, exist_ok=True)
    v.to_csv(out / "validacao_fuso_municipios.csv", index=False)
    print(v.groupby(["nr_turno", "resultado"]).size().to_string())
    print(v[v.resultado != "CONFERE"].head(30).to_string(index=False))
    return 0 if (v.resultado == "CONFERE").all() else 1


if __name__ == "__main__":
    raise SystemExit(main())
