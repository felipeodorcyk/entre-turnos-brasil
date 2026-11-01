"""O4: comparações de horário — efeito de controle, sobreposição, suporte."""
import numpy as np
import pandas as pd

from br2026.analysis.closure_models import pairwise_comparison
from br2026.config import load_config

CFG = load_config()
REF, LATE = "17H00_17H15", "A_PARTIR_19H"


def frame(n_mun=20, per=20, seed=0, late_bigger=True, overlap=True, both_in_mun=True):
    """Unidades por município; desfecho depende SÓ do tamanho (sem efeito de faixa)."""
    rng = np.random.default_rng(seed)
    rows = []
    for m in range(n_mun):
        for i in range(per):
            late = (i % 2 == 0) if both_in_mun else (m % 2 == 0)
            base = 5.5 if late and late_bigger else 5.0
            if not overlap:
                base = 7.0 if late else 4.0
            la = base + rng.normal(0, 0.3 if overlap else 0.1)
            rows.append({"municipio": f"M{m:02d}", "faixa_t2": LATE if late else REF,
                         "log_aptos_t1": la, "peso": float(np.exp(la)),
                         "y": 0.02 * la + rng.normal(0, 0.002)})
    return pd.DataFrame(rows)


def test_control_explains_raw_difference():
    r = pairwise_comparison(frame(), "faixa_t2", REF, LATE, "y", ["log_aptos_t1"], [], CFG)
    assert r["status"] == "PASS"
    assert abs(r["diferenca_bruta"]) > 0.005          # bruto confunde faixa com tamanho
    assert abs(r["beta_ajustado"]) < 3 * r["ep"] + 1e-4  # ajustado não acusa efeito inexistente


def test_no_covariate_overlap_blocks_comparison():
    r = pairwise_comparison(frame(overlap=False), "faixa_t2", REF, LATE, "y", ["log_aptos_t1"], [], CFG)
    assert r["status"] == "NAO_ESTIMADO" and "sobreposição" in r["motivo"]


def test_requires_municipalities_with_both_bands():
    r = pairwise_comparison(frame(both_in_mun=False), "faixa_t2", REF, LATE, "y", ["log_aptos_t1"], [], CFG)
    assert r["status"] == "NAO_ESTIMADO" and "ambas as faixas" in r["motivo"]


def test_band_without_support_blocks_only_itself():
    d = frame()
    few = d.sample(5, random_state=1).index
    d.loc[few, "faixa_t2"] = "18H_19H"
    r_few = pairwise_comparison(d, "faixa_t2", REF, "18H_19H", "y", ["log_aptos_t1"], [], CFG)
    r_ok = pairwise_comparison(d, "faixa_t2", REF, LATE, "y", ["log_aptos_t1"], [], CFG)
    assert r_few["status"] == "NAO_ESTIMADO" and r_ok["status"] == "PASS"


def test_trimming_reported():
    d = frame()
    d.loc[d.index[:3], "log_aptos_t1"] = 20.0  # extremos só no grupo de referência/tardio
    r = pairwise_comparison(d, "faixa_t2", REF, LATE, "y", ["log_aptos_t1"], [], CFG)
    assert r["n_aparados"] >= 1
