"""Referência independente de reconciliação e casos fixos de filtro.

Lê as fontes analíticas diretamente (não o JSON exportado), recalcula totais
e um conjunto determinístico de recortes. O JSON gerado é consumido pelo
teste do motor TypeScript, de modo que os dois lados não compartilham código.

Uso:
    python tools/web_export/oracle.py
    python tools/web_export/oracle.py --out web/src/engine/oracle_cases.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOCIO = ["renda_pc", "baixa_renda", "desocupacao", "vinculos", "pbf", "urbana"]
COUNT = [
    "qt_aptos_t1",
    "qt_aptos_t2",
    "qt_comparecimento_t1",
    "qt_comparecimento_t2",
    "qt_votos_validos_t1",
    "qt_votos_validos_t2",
    "qt_lula_t1",
    "qt_lula_t2",
    "qt_flavio_t1",
    "qt_flavio_t2",
]


def _ratio(num: float, den: float) -> float | None:
    return None if den == 0 else num / den


def _load(root: Path) -> pd.DataFrame:
    metrics = pd.read_csv(root / "data/analytics/metrics_municipio.csv", dtype={"cd_municipio_tse": str})
    painel = pd.read_parquet(root / "data/analytics/socio/painel_municipal_socio.parquet")
    painel["cd_municipio_tse"] = painel["cd_municipio_tse"].astype(str).str.zfill(5)
    import zipfile

    with zipfile.ZipFile(root / "data/raw/ibge_setores/municipio_tse_ibge.zip") as zf:
        with zf.open("municipio_tse_ibge.csv") as fh:
            cross = pd.read_csv(fh, sep=";", encoding="latin-1", dtype=str)
    cross["cd_municipio_tse"] = cross["CD_MUNICIPIO_TSE"].str.zfill(5)
    cross["cd_ibge"] = cross["CD_MUNICIPIO_IBGE"].str.zfill(7)
    df = metrics.merge(
        cross[["SG_UF", "cd_municipio_tse", "cd_ibge"]].rename(columns={"SG_UF": "sg_uf"}),
        on=["sg_uf", "cd_municipio_tse"],
        how="left",
        validate="one_to_one",
    )
    df = df.merge(
        painel[["sg_uf", "cd_municipio_tse", "regiao", *SOCIO]],
        on=["sg_uf", "cd_municipio_tse"],
        how="left",
        validate="one_to_one",
    )
    if df["cd_ibge"].isna().any():
        raise SystemExit("oráculo: município sem código IBGE")
    return df


def _apply(df: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    out = df
    if spec.get("ufs"):
        out = out[out.sg_uf.isin(spec["ufs"])]
    if spec.get("regioes"):
        out = out[out.regiao.isin(spec["regioes"])]
    if spec.get("municipios"):
        out = out[out.cd_ibge.isin(spec["municipios"])]
    for field in SOCIO:
        rule = (spec.get("socio") or {}).get(field)
        if not rule:
            continue
        series = out[field]
        if rule.get("missing"):
            mask = series.isna()
            if rule.get("min") is not None or rule.get("max") is not None:
                lo = rule.get("min", -math.inf)
                hi = rule.get("max", math.inf)
                mask = mask | series.between(lo, hi, inclusive="both")
        else:
            lo = rule.get("min", -math.inf)
            hi = rule.get("max", math.inf)
            mask = series.between(lo, hi, inclusive="both")
        out = out[mask]
    return out


def aggregate(df: pd.DataFrame) -> dict[str, Any]:
    s = {c: int(df[c].sum()) for c in COUNT}
    l1, l2 = s["qt_lula_t1"], s["qt_lula_t2"]
    f1, f2 = s["qt_flavio_t1"], s["qt_flavio_t2"]
    v1, v2 = s["qt_votos_validos_t1"], s["qt_votos_validos_t2"]
    a1, a2 = s["qt_aptos_t1"], s["qt_aptos_t2"]
    c1, c2 = s["qt_comparecimento_t1"], s["qt_comparecimento_t2"]
    sh1, sh2 = _ratio(l1, v1), _ratio(l2, v2)
    fh1, fh2 = _ratio(f1, v1), _ratio(f2, v2)
    t1, t2 = _ratio(c1, a1), _ratio(c2, a2)
    m1 = None if sh1 is None or fh1 is None else sh1 - fh1
    m2 = None if sh2 is None or fh2 is None else sh2 - fh2
    return {
        "municipios": int(len(df)),
        "aptos_t1": a1,
        "aptos_t2": a2,
        "validos_t1": v1,
        "validos_t2": v2,
        "lula_t1": l1,
        "lula_t2": l2,
        "flavio_t1": f1,
        "flavio_t2": f2,
        "participacao_lula_t1": sh1,
        "participacao_lula_t2": sh2,
        "participacao_flavio_t1": fh1,
        "participacao_flavio_t2": fh2,
        "comparecimento_t1": t1,
        "comparecimento_t2": t2,
        "delta_margem_pp": None if m1 is None or m2 is None else 100 * (m2 - m1),
        "delta_margem_votos": (l2 - f2) - (l1 - f1),
        "delta_comparecimento_pp": None if t1 is None or t2 is None else 100 * (t2 - t1),
        "sem_renda": int(df["renda_pc"].isna().sum()),
    }


CASES: list[dict[str, Any]] = [
    {"id": "brasil_territorial", "filters": {}},
    {"id": "uf_sp", "filters": {"ufs": ["SP"]}},
    {"id": "uf_ac_rr", "filters": {"ufs": ["AC", "RR"]}},
    {"id": "regiao_norte", "filters": {"regioes": ["Norte"]}},
    {"id": "regiao_sul_sudeste", "filters": {"regioes": ["Sul", "Sudeste"]}},
    {"id": "renda_500_1000", "filters": {"socio": {"renda_pc": {"min": 500, "max": 1000}}}},
    {"id": "renda_borda_735", "filters": {"socio": {"renda_pc": {"min": 735.09, "max": 735.11}}}},
    {"id": "renda_ausente", "filters": {"socio": {"renda_pc": {"missing": True}}}},
    {"id": "pbf_0_20", "filters": {"socio": {"pbf": {"min": 0, "max": 20}}}},
    {"id": "pbf_alto", "filters": {"socio": {"pbf": {"min": 57.934, "max": 200}}}},
    {"id": "vinculos_p20_p80", "filters": {"socio": {"vinculos": {"min": 100.773, "max": 269.305}}}},
    {"id": "desocupacao_p50", "filters": {"socio": {"desocupacao": {"min": 0, "max": 4.114}}}},
    {"id": "urbana_p20_p80", "filters": {"socio": {"urbana": {"min": 50.25, "max": 89.019}}}},
    {"id": "baixa_renda_p20_p80", "filters": {"socio": {"baixa_renda": {"min": 17.07, "max": 56.06}}}},
    {"id": "mg_renda_800_1200", "filters": {"ufs": ["MG"], "socio": {"renda_pc": {"min": 800, "max": 1200}}}},
    {"id": "nordeste_pbf_40_80", "filters": {"regioes": ["Nordeste"], "socio": {"pbf": {"min": 40, "max": 80}}}},
    {"id": "tres_capitais", "filters": {"municipios": ["3550308", "3304557", "3106200"]}},
    {"id": "boa_esperanca", "filters": {"municipios": ["5101837"]}},
    {"id": "vazio", "filters": {"municipios": ["9999999"]}},
    {"id": "sp_pbf_ausente", "filters": {"ufs": ["SP"], "socio": {"pbf": {"missing": True}}}},
    {"id": "renda_zero", "filters": {"socio": {"renda_pc": {"min": 0, "max": 0}}}},
    {"id": "co_urbana_90_pbf_ausente", "filters": {"regioes": ["Centro-Oeste"], "socio": {"urbana": {"min": 90, "max": 100}, "pbf": {"missing": True}}}},
    {"id": "df", "filters": {"ufs": ["DF"]}},
    {"id": "bujari_sao_paulo", "filters": {"municipios": ["1200138", "3550308"]}},
    {"id": "renda_exata_735_106", "filters": {"socio": {"renda_pc": {"min": 735.106, "max": 735.106}}}},
    {"id": "pbf_ausente_ou_baixo", "filters": {"socio": {"pbf": {"min": 0, "max": 10, "missing": True}}}},
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "web/src/engine/oracle_cases.json")
    args = parser.parse_args()
    root = args.root.resolve()
    df = _load(root)

    # Reconciliação independente: soma municipal = linha TOTAL de metrics_uf.
    uf = pd.read_csv(root / "data/analytics/metrics_uf.csv")
    total = uf[uf.sg_uf == "TOTAL"].iloc[0]
    checks = {}
    for field in ("qt_aptos_t1", "qt_aptos_t2", "qt_comparecimento_t2", "qt_votos_validos_t2", "qt_lula_t2", "qt_flavio_t2"):
        got, expected = int(df[field].sum()), int(total[field])
        checks[field] = {"soma_municipal": got, "total_uf": expected, "igual": got == expected}
        if got != expected:
            raise SystemExit(f"oráculo: {field} divergente ({got} != {expected})")

    # Referência oficial: 392/392 sem diferença e totais nacionais.
    ref = pd.read_csv(root / "reports/analysis/evidencias_nacional/referencia_m1_m2_uf.csv")
    if int(ref.dif.abs().max()) != 0:
        raise SystemExit("oráculo: referência oficial com diferença não zero")
    official = {}
    for turn in (1, 2):
        part = ref[ref.nr_turno == turn].groupby("metrica").valor_referencia.sum()
        official[f"t{turn}"] = {k.replace("qt_", ""): int(v) for k, v in part.items()}
    official["unidades"] = int(ref.sg_uf.nunique())
    official["inclui_exterior"] = "ZZ" in set(ref.sg_uf)

    cases = []
    all_cases = list(CASES) + [{"id": f"uf_{uf}", "filters": {"ufs": [uf]}} for uf in sorted(df.sg_uf.unique())]
    for case in all_cases:
        subset = _apply(df, case["filters"])
        cases.append({"id": case["id"], "filters": case["filters"], "expected": aggregate(subset)})

    pointer = root / "web/public/release/current.json"
    release_id = json.loads(pointer.read_text(encoding="utf-8"))["release_id"] if pointer.exists() else None
    payload = {
        "generated_by": "tools/web_export/oracle.py",
        "release_id": release_id,
        "universe": "pareado_territorial",
        "reconciliation": checks,
        "official": official,
        "cases": cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"oráculo: {len(cases)} casos, reconciliação {sum(1 for c in checks.values() if c['igual'])}/{len(checks)}")
    print(f"saída: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
